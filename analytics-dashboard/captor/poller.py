"""Captor poller: read-only aegis_db → Kafka (idempotent, watermarks)."""
import json
import os
import threading
import time
import uuid
from datetime import datetime, timezone

import psycopg2
from kafka import KafkaProducer
from prometheus_client import Counter, Gauge

from captor.config import TABLES, db_dsn, state_path, KAFKA_BOOTSTRAP

METRICS_READY = {"telemetry": "ts", "shipment_events": "ts"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Captor:
    def __init__(self, lazy_producer=True):
        self._lock = threading.Lock()
        self.state = self._load_state()
        self.last_cycle_at = None
        self.cycle_errors: dict[str, str] = {}
        self.rows_last_cycle: dict[str, int] = {}
        self.bootstrap_pending = False
        self._cycle_active = False
        self._producer = None
        self._lazy_producer = lazy_producer
        self.cycles_total = Counter("captor_cycles_total", "Captor cycles", ["trigger"])
        self.rows_total = Counter("captor_rows_captured_total", "Rows captured", ["table"])
        self.errors_total = Counter("captor_errors_total", "Captor errors", ["table"])
        self.last_ts = Gauge("captor_last_cycle_timestamp_s", "Laatste cycle per tabel", ["table"])
        self.bootstrap_pending_metric = Gauge("captor_bootstrap_pending", "Bootstrap nog niet klaar")

    # ── state ────────────────────────────────────────────────
    def _load_state(self) -> dict:
        p = state_path()
        if os.path.exists(p):
            try:
                with open(p) as f:
                    return json.load(f)
            except Exception:
                pass
        return {"watermarks": {}, "bootstrapped": {}, "shipments_cache": {}}

    def _save_state(self):
        os.makedirs(os.path.dirname(state_path()), exist_ok=True)
        tmp = state_path() + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.state, f, indent=1)
        os.replace(tmp, state_path())

    # ── helpers ───────────────────────────────────────────────
    @property
    def producer(self):
        if self._producer is None:
            self._producer = KafkaProducer(
                bootstrap_servers=KAFKA_BOOTSTRAP,
                key_serializer=lambda v: str(v).encode("utf-8"),
                value_serializer=lambda v: json.dumps(v, default=str).encode(),
                linger_ms=50,
                retries=5,
                acks=1,
            )
        return self._producer

    def _key_cols(self, tbl: str) -> list:
        return next(k for t, _tp, k, _f in TABLES if t == tbl)

    def _topic(self, tbl: str) -> str:
        return next(tp for t, tp, _k, _f in TABLES if t == tbl)

    def _emit_rows(self, tbl: str, cols: list, rows: list, cycle_id: str) -> int:
        if not rows:
            return 0
        topic = self._topic(tbl)
        key_cols = self._key_cols(tbl)
        n = 0
        for r in rows:
            d = {c: r[i] for i, c in enumerate(cols)}
            key = ":".join(str(d.get(k, "")) for k in key_cols)
            self.producer.send(topic, key=key, value={
                "payload": d,
                "src_table": tbl,
                "captured_at": _now(),
                "cycle_id": cycle_id,
            })
            n += 1
        return n

    # ── bootstrap (eerste keer: volledige historie) ──────────
    def _ensure_bootstrap(self, cur, tbl: str):
        if self.state["bootstrapped"].get(tbl):
            return
        print(f"[captor] bootstrap {tbl} ...", flush=True)
        cur.execute(f"SELECT * FROM {tbl}")
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        n = self._emit_rows(tbl, cols, rows, "bootstrap")
        self._set_watermark(cur, tbl)
        self.state["bootstrapped"][tbl] = True
        print(f"[captor] bootstrap {tbl}: {n} records", flush=True)

    def _set_watermark(self, cur, tbl: str):
        if tbl in ("telemetry", "shipment_events"):
            cur.execute(f"SELECT max(ts) FROM {tbl}")
            mx = cur.fetchone()[0]
            self.state["watermarks"][tbl] = {"ts": mx.isoformat() if mx else None}
        elif tbl == "shipments":
            cur.execute("SELECT max(created_at) FROM shipments")
            mx = cur.fetchone()[0]
            self.state["watermarks"][tbl] = {"created_at": mx.isoformat() if mx else None}
        else:
            self.state["watermarks"][tbl] = {"snapshot": _now()}

    # ── poll per tabel ────────────────────────────────────────
    def _poll_table(self, cur, tbl: str, fact: bool) -> int:
        emitted = 0
        if fact:
            col = "ts"
            wm = (self.state["watermarks"].get(tbl) or {}).get(col)
            # Inclusief (>=): de bron is een LIVE db waar points per point
            # bijkomen; rijen met ts == (of net onder) het vorige max(ts)
            # mogen niet verloren gaan. Dubbels zijn onschadelijk: de
            # pipeline dedupt op (vehicle_id, ts) / id.
            cur.execute(f"SELECT * FROM {tbl} WHERE {col} >= %s::timestamptz", (wm,))
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()
            emitted = self._emit_rows(tbl, cols, rows, f"cycle-{uuid.uuid4().hex[:8]}")
            self._set_watermark(cur, tbl)
        else:
            # dims (incl. shipments): full-snapshot per cycle —
            # de pipeline doet DELETE+INSERT, dus de batch MOET compleet zijn.
            cur.execute(f"SELECT * FROM {tbl}")
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()
            emitted = self._emit_rows(tbl, cols, rows, f"cycle-{uuid.uuid4().hex[:8]}")
            self._set_watermark(cur, tbl)
        return emitted

    # ── cycle ─────────────────────────────────────────────────
    def run_cycle(self, trigger: str = "interval") -> dict:
        with self._lock:
            if self._cycle_active:
                return {"status": "409", "error": "cycle_active"}
            self._cycle_active = True
        try:
            self.cycle_errors = {}
            self.rows_last_cycle = {}
            self.bootstrap_pending = False
            started = time.time()
            try:
                conn = psycopg2.connect(db_dsn(), connect_timeout=8)
                conn.set_session(isolation_level="REPEATABLE READ", readonly=True)
                with conn.cursor() as cur:
                    for tbl, _topic, _key, fact in TABLES:
                        try:
                            self._ensure_bootstrap(cur, tbl)
                            n = self._poll_table(cur, tbl, fact)
                            self.rows_last_cycle[tbl] = n
                        except Exception as e:  # noqa
                            self.cycle_errors[tbl] = str(e)
                            self.bootstrap_pending = True
                            print(f"[captor] tabel {tbl} fout: {e}", flush=True)
                conn.close()
            except Exception as e:  # noqa
                self.cycle_errors["connection"] = str(e)
                print(f"[captor] connectie fout: {e}", flush=True)
            self._save_state()
            self.last_cycle_at = _now()
            self.bootstrap_pending_metric.set(
                1 if not all(self.state["bootstrapped"].values()) else 0)
            return {"status": "ok", "cycle_id": f"c-{int(time.time())}",
                    "trigger": trigger,
                    "duration_ms": int((time.time() - started) * 1000),
                    "rows": self.rows_last_cycle, "errors": self.cycle_errors}
        finally:
            self._cycle_active = False

    # ── health ────────────────────────────────────────────────
    def health(self) -> dict:
        src_ok = True
        try:
            conn = psycopg2.connect(db_dsn(), connect_timeout=4)
            with conn.cursor() as c:
                c.execute("SELECT 1")
                c.fetchone()
            conn.close()
        except Exception:  # noqa
            src_ok = False
        tables = {}
        for tbl, _topic, _key, fact in TABLES:
            wm = self.state["watermarks"].get(tbl) or {}
            boot = self.state["bootstrapped"].get(tbl, False)
            if not boot:
                state = "bootstrap"
            elif self.cycle_errors.get(tbl):
                state = "error"
            else:
                state = "streaming" if fact else "snapshot"
            tables[tbl] = {
                "state": state,
                "watermark": wm.get("ts") or wm.get("created_at") or wm.get("snapshot"),
                "rows_last_cycle": self.rows_last_cycle.get(tbl, 0),
                "error": self.cycle_errors.get(tbl),
            }
        status = "ok" if (src_ok and not self.cycle_errors) else (
            "degraded" if src_ok else "error")
        return {
            "status": status,
            "source_reachable": src_ok,
            "last_cycle_at": self.last_cycle_at,
            "cycle_active": self._cycle_active,
            "bootstrap": {
                "state": "in_progress" if not all(self.state["bootstrapped"].values()) else "done",
                "completed_tables": sum(1 for v in self.state["bootstrapped"].values() if v),
                "total_tables": len(TABLES),
            },
            "tables": tables,
            "kafka": {"reachable": True},
        }

    # ── interval loop ─────────────────────────────────────────
    def start_loop(self, interval_s: int):
        def loop():
            while True:
                res = self.run_cycle("interval")
                if res["status"] == "ok":
                    self.cycles_total.labels(trigger="interval").inc()
                    for t, n in res["rows"].items():
                        self.rows_total.labels(table=t).inc(n)
                        self.last_ts.labels(table=t).set(time.time())
                    for t in res["errors"]:
                        self.errors_total.labels(table=t).inc()
                time.sleep(interval_s)

        threading.Thread(target=loop, daemon=True, name="captor-loop").start()


captor = Captor()
