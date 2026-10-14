"""AEGIS truck telematics ingest gateway.

The capture side of the truck->broker path (the telematics gateway behind
the CAN bus / OBD-II port of every truck):

    CAN BUS / OBD-II  ->  POST /ingest/telemetry  ->  KAFKA topic
    (aegis.events.truck.telemetry)  ->  ingest consumer  ->  PostGIS `telemetry`

So the command center's telemetry is DELIVERED VIA KAFKA: the topic is the
audit trail of everything the fleet reports. A consumer group reads the topic
back and commits each point into PostGIS.

The analytics platform's captor/pipeline (separate project) later mirrors the
PostGIS tables into its own Kafka topics -> DuckLake; this gateway is upstream
of that, on the capture side.

Endpoints:
  POST /ingest/telemetry   one point dict or a list of them (from the API)
  GET  /health             in-process stats (received / produced / written)
"""
import json
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import psycopg2
from kafka import KafkaConsumer, KafkaProducer

KAFKA = os.environ.get("KAFKA_BOOTSTRAP", "kafka:9092")
TOPIC = os.environ.get("GW_TOPIC", "aegis.events.truck.telemetry")
GROUP = os.environ.get("GW_GROUP", "aegis.truck.ingest")
GW_PORT = int(os.environ.get("GW_PORT", "8411"))
PG = {
    "host": os.environ.get("PG_HOST", "aegis_db"),
    "port": int(os.environ.get("PG_PORT", "5432")),
    "dbname": os.environ.get("PG_DB", "aegis"),
    "user": os.environ.get("PG_USER", "aegis"),
    "password": os.environ.get("PG_PASSWORD", "aegis_dev"),
}

STATS = {
    "points_received": 0,   # HTTP -> producer
    "points_produced": 0,   # acked into kafka
    "points_consumed": 0,   # kafka -> consumer
    "points_written": 0,    # committed to postgres
    "last_ingest_at": None,
    "last_write_at": None,
    "last_record_seq": None,
    "last_record_at": None,
    "errors": {},
    "started_at": datetime.now(timezone.utc).isoformat(),
}
STATS_LOCK = threading.Lock()


def _now():
    return datetime.now(timezone.utc).isoformat()


def _bump(key, n=1):
    with STATS_LOCK:
        STATS[key] += n


def _err(key, msg):
    with STATS_LOCK:
        STATS["errors"][key] = str(msg)[:200]


# ── producer: HTTP -> kafka ──────────────────────────────────────────
PRODUCER = None
PRODUCER_LOCK = threading.Lock()


def producer():
    global PRODUCER
    with PRODUCER_LOCK:
        if PRODUCER is None:
            PRODUCER = KafkaProducer(
                bootstrap_servers=KAFKA,
                key_serializer=lambda v: str(v).encode(),
                value_serializer=lambda v: json.dumps(v, default=str).encode(),
                acks="all",
                retries=5,
                linger_ms=20,
            )
    return PRODUCER


def publish_point(rec: dict) -> None:
    payload = {
        "payload": rec,
        "src": "can_bus/obd2",
        "captured_at": _now(),
        "seq": uuid.uuid4().hex[:12],
    }
    with STATS_LOCK:
        STATS["last_record_seq"] = payload["seq"]
        STATS["last_record_at"] = rec.get("ts") or _now()
    fut = producer().send(TOPIC, key=rec.get("vehicle_id", "unknown"), value=payload)
    fut.add_callback(lambda f: _bump("points_produced"))
    fut.add_errback(lambda e: _err("produce", e))


# ── consumer: kafka -> postgres (batched) ────────────────────────────
def _pg_conn():
    return psycopg2.connect(**PG, connect_timeout=6)


def _write_batch(batch):
    """Write a list of telemetry points in one transaction."""
    conn = _pg_conn()
    try:
        with conn.cursor() as cur:
            # known vehicles only; skip the rest (stream stays honest)
            cur.execute("SELECT id FROM vehicles")
            known = {r[0] for r in cur.fetchall()}
            for rec in batch:
                vid = rec.get("vehicle_id")
                if vid not in known:
                    _err("skip", f"unknown vehicle {vid}")
                    continue
                cur.execute(
                    """INSERT INTO telemetry
                       (vehicle_id, ts, lat, lng, speed_kmh, heading, fuel_pct,
                        engine_temp, cargo_temp, signal_pct, gps_acc_m, geom)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                               ST_SetSRID(ST_MakePoint(%s,%s),4326))""",
                    (vid,
                     rec.get("ts") or _now(),
                     rec.get("lat"), rec.get("lng"), rec.get("speed_kmh"),
                     rec.get("heading"), rec.get("fuel_pct"), rec.get("engine_temp"),
                     rec.get("cargo_temp"), rec.get("signal_pct"), rec.get("gps_acc_m"),
                     rec.get("lng"), rec.get("lat")),
                )
        conn.commit()
    finally:
        conn.close()


def consume_loop():
    batch, batch_at = [], time.time()
    while True:
        try:
            consumer = KafkaConsumer(
                bootstrap_servers=KAFKA,
                group_id=GROUP,
                enable_auto_commit=False,
                auto_offset_reset="earliest",
                fetch_max_wait_ms=500,
                value_deserializer=lambda v: json.loads(v.decode()),
            )
            consumer.subscribe([TOPIC])
            while True:
                msgs = consumer.poll(timeout_ms=250)
                if msgs:
                    for _tp, msg in msgs.items():
                        for m in msg:
                            rec = m.value.get("payload") if isinstance(m.value, dict) else None
                            if rec:
                                batch.append(rec)
                                _bump("points_consumed")
                    now = time.time()
                    if len(batch) >= 25 or now - batch_at > 1.0:
                        _write_batch(batch)
                        _bump("points_written", len(batch))
                        with STATS_LOCK:
                            STATS["last_write_at"] = _now()
                        batch, batch_at = [], now
                    consumer.commit()
        except Exception as e:  # noqa
            if batch:
                try:
                    _write_batch(batch)
                    batch = []
                except Exception as e2:  # noqa
                    _err("write", e2)
                    batch = []
            _err("consume", e)
            print("[gw] consumer restart:", e, flush=True)
            time.sleep(3)


# ── HTTP inlet (the CAN/OBD-II uplink endpoint) ──────────────────────
class Handler(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):  # noqa: N802
        if self.path != "/ingest/telemetry":
            self._send(404, {"ok": False, "error": "not found"})
            return
        try:
            n = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(n) if n else b"{}"
            data = json.loads(raw)
            recs = data if isinstance(data, list) else [data]
            for rec in recs:
                publish_point(rec)
                _bump("points_received")
            with STATS_LOCK:
                STATS["last_ingest_at"] = _now()
            self._send(202, {"ok": True, "accepted": len(recs), "topic": TOPIC})
        except Exception as e:  # noqa
            _err("http", e)
            self._send(400, {"ok": False, "error": str(e)[:160]})

    def do_GET(self):  # noqa: N802
        if self.path != "/health":
            self._send(404, {"ok": False, "error": "not found"})
            return
        with STATS_LOCK:
            snap = json.loads(json.dumps(STATS))
        snap["ok"] = True
        snap["topic"] = TOPIC
        self._send(200, snap)

    def log_message(self, format, *args):  # noqa: A002
        pass


def main():
    threading.Thread(target=consume_loop, daemon=True, name="gw-consumer").start()
    srv = ThreadingHTTPServer(("0.0.0.0", GW_PORT), Handler)
    print(f"[gw] ingest inlet on :{GW_PORT} -> topic {TOPIC} -> PostGIS", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
