"""Pipeline: Kafka → contract-validator → DuckLake (DuckDB) + quarantaine.

Micro-batching: buffers per tabel, flush elke BATCH_INTERVAL_S in één
transactie. Dedup voor facts (key-based), dims = snapshot-upsert.
Status + metrics op :8410.
"""
import json
import os
import time
import threading

from kafka import TopicPartition
from datetime import datetime, timezone
from decimal import Decimal

from kafka import KafkaConsumer
from prometheus_client import Counter, Gauge, start_http_server
from fastapi import FastAPI, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from pipeline.config import (TABLES, KAFKA_BOOTSTRAP, MINIO_ENDPOINT,
                             MINIO_ENDPOINT_BARE, MINIO_ACCESS_KEY, MINIO_SECRET_KEY, DATA_PATH,
                             CATALOG_HOST, CATALOG_PORT, CATALOG_DB,
                             CATALOG_USER, CATALOG_PASSWORD)

BATCH_INTERVAL = float(os.environ.get("BATCH_INTERVAL_S", "20"))
DEDUP_LIMIT = 20000  # per fact-tabel


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ────────────────────────────────────────────────────────────────
# Contract validator (pure — ook standalone unit-testbaar)
# ────────────────────────────────────────────────────────────────
_CONTRACT_DIR = os.path.join(os.path.dirname(__file__), "..", "contracts")
_CONTRACTS = {}


def load_contract(topic: str) -> dict:
    if topic in _CONTRACTS:
        return _CONTRACTS[topic]
    import yaml
    fname = topic.split(".")[-1]
    if fname == "shipment":
        fname = "shipment-events"
    path = os.path.join(_CONTRACT_DIR, fname + ".yaml")
    c = {"topic": topic, "checks": {"schema": {}, "enums": {}, "ranges": {}},
         "on_violation": "flag", "freshness_sla_s": 3600}
    if os.path.exists(path):
        with open(path) as f:
            c.update(yaml.safe_load(f))
    _CONTRACTS[topic] = c
    return c


def validate_record(payload: dict, contract: dict):
    """Return (ok, violations). violations = [(rule, reason)]."""
    violations = []
    checks = contract.get("checks", {})
    req = (checks.get("schema") or {}).get("required", [])
    for col in req:
        if payload.get(col) is None:
            violations.append(("schema.required", f"missing {col}"))
    for col, allowed in (checks.get("enums") or {}).items():
        v = payload.get(col)
        if v is not None and str(v) not in [str(a) for a in allowed]:
            violations.append(("enums", f"{col}={v!r} not in {allowed}"))
    for col, rng in (checks.get("ranges") or {}).items():
        v = payload.get(col)
        if v is not None:
            try:
                fv = float(v)
                if fv < float(rng[0]) or fv > float(rng[1]):
                    violations.append(("ranges", f"{col}={fv} outside {rng}"))
            except (TypeError, ValueError):
                violations.append(("ranges", f"{col}={v!r} not numeric"))
    return (len(violations) == 0), violations


# ────────────────────────────────────────────────────────────────
# DuckLake writer (embedded DuckDB)
# ────────────────────────────────────────────────────────────────
SCHEMAS = {
    "telemetry": [("vehicle_id", "str"), ("ts", "ts"), ("lat", "f64"),
                  ("lng", "f64"), ("speed_kmh", "f64"), ("heading", "int"),
                  ("fuel_pct", "f64"), ("engine_temp", "f64"),
                  ("cargo_temp", "f64"), ("signal_pct", "f64"),
                  ("gps_acc_m", "f64"), ("captured_at", "ts"),
                  ("cycle_id", "str")],
    "shipment_events": [("id", "str"), ("shipment_id", "str"), ("ts", "ts"),
                        ("type", "str"), ("note", "str"),
                        ("captured_at", "ts"), ("cycle_id", "str")],
    "shipments": [("id", "str"), ("vehicle_id", "str"), ("lane_id", "str"),
                  ("cargo", "str"), ("qty", "str"), ("value_eur", "f64"),
                  ("customer", "str"), ("status", "str"), ("eta_minutes", "int"),
                  ("sla_minutes", "int"), ("customs", "str"), ("temp_req", "str"),
                  ("created_at", "ts"), ("progress", "f64"),
                  ("cycle_ts", "ts"), ("first_seen", "ts"), ("last_seen", "ts")],
    "vehicles": [("id", "str"), ("kind", "str"), ("name", "str"),
                 ("driver", "str"), ("model", "str"), ("capacity_t", "f64"),
                 ("load_t", "f64"), ("fuel_pct", "f64"),
                 ("fuel_range_km", "f64"), ("registered", "str"),
                 ("carbon_tco2", "f64"), ("cycle_ts", "ts"),
                 ("first_seen", "ts"), ("last_seen", "ts")],
    "lanes": [("id", "str"), ("origin", "str"), ("destination", "str"),
              ("distance_km", "f64"), ("freeflow_min", "int"),
              ("otif_pct", "int"), ("volume", "int"), ("cycle_ts", "ts"),
              ("first_seen", "ts"), ("last_seen", "ts")],
    "locations": [("id", "str"), ("name", "str"), ("kind", "str"),
                  ("lat", "f64"), ("lng", "f64"), ("capacity", "int"),
                  ("stock_level", "f64"), ("region", "str"), ("cycle_ts", "ts"),
                  ("first_seen", "ts"), ("last_seen", "ts")],
    "inventory": [("hub_id", "str"), ("sku", "str"), ("stock", "int"),
                  ("reorder", "int"), ("units", "str"), ("velocity", "f64"),
                  ("cycle_ts", "ts"), ("first_seen", "ts"), ("last_seen", "ts")],
    "drivers": [("vehicle_id", "str"), ("full_name", "str"), ("dob", "str"),
                ("nationality", "str"), ("license", "str"),
                ("license_expiry", "str"), ("phone", "str"), ("email", "str"),
                ("years_exp", "int"), ("rating", "f64"), ("trips", "int"),
                ("base", "str"), ("cycle_ts", "ts"), ("first_seen", "ts"),
                ("last_seen", "ts")],
    "components": [("vehicle_id", "str"), ("name", "str"), ("photo", "str"),
                   ("wear", "int"), ("health", "int"), ("km", "int"),
                   ("last_service", "str"), ("next_service", "str"),
                   ("status", "str"), ("rul_days", "int"), ("est_cost", "int"),
                   ("cycle_ts", "ts"), ("first_seen", "ts"), ("last_seen", "ts")],
}


class Lake:
    def __init__(self):
        import duckdb
        self.con = duckdb.connect()
        for ext in ("ducklake", "httpfs", "postgres"):
            self.con.execute(f"INSTALL {ext}")
            self.con.execute(f"LOAD {ext}")
        self.con.execute(f"""CREATE OR REPLACE SECRET minio_secret (
            TYPE s3, ENDPOINT '{MINIO_ENDPOINT_BARE}', KEY_ID '{MINIO_ACCESS_KEY}',
            SECRET '{MINIO_SECRET_KEY}', REGION 'us-east-1', URL_STYLE 'path',
            USE_SSL false)""")
        self.con.execute(f"""ATTACH 'ducklake:postgres:dbname={CATALOG_DB} host={CATALOG_HOST} port={CATALOG_PORT} user={CATALOG_USER} password={CATALOG_PASSWORD}'
                            AS lake (DATA_PATH '{DATA_PATH}')""")
        self.con.execute("USE lake")
        print("[pipeline] DuckLake attached ✓", flush=True)

    @staticmethod
    def _coerce(v, kind):
        if v is None:
            return None
        if kind == "f64":
            try:
                return float(v)
            except (TypeError, ValueError):
                return None
        if kind == "int":
            try:
                return int(v)
            except (TypeError, ValueError):
                return None
        if kind == "ts":
            if isinstance(v, datetime):
                return v
            try:
                return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
            except Exception:
                return None
        return str(v)

    def write_fact(self, tbl, records):
        import pyarrow as pa
        schema = SCHEMAS[tbl]
        dedup_key = "id" if tbl == "shipment_events" else "vehicle_id"
        keys = [r.get(dedup_key) for r in records]
        # dedup: verwijder eerdere versies van dezelfde (key, ts) combo
        if tbl == "telemetry":
            pairs = {(r.get("vehicle_id"), str(r.get("ts"))) for r in records}
        else:
            pairs = {r.get("id") for r in records}
        d = {}
        for col, kind in schema:
            d[col] = [self._coerce(r.get(col), kind) for r in records]
        arr = pa.Table.from_pydict(d, schema=pa.schema(
            [(c, pa.timestamp("us", tz="UTC") if k == "ts" else
              pa.int64() if k == "int" else pa.float64() if k == "f64" else
              pa.string()) for c, k in schema]))
        self.con.register("_batch_view", arr)
        try:
            # ATOMIC: DELETE+INSERT in één transactie, zodat readers (en het
            # opstarten) nooit een tussenstand zien en een crash ertussen
            # geen data verliest. Set-based join-delete (snel) i.p.v. een
            # per-sleutel Python-loop.
            self.con.execute("BEGIN TRANSACTION")
            if pairs:
                if tbl == "telemetry":
                    dk = pa.Table.from_pydict({
                        "vehicle_id": [k for k, _ in pairs],
                        "ts": [datetime.fromisoformat(t.replace("Z", "+00:00"))
                               for _, t in pairs]})
                    self.con.register("_dedup_keys", dk)
                    self.con.execute(
                        "DELETE FROM facts.telemetry AS t USING _dedup_keys d "
                        "WHERE t.vehicle_id = d.vehicle_id AND t.ts = d.ts")
                    self.con.unregister("_dedup_keys")
                else:
                    self.con.execute(
                        "DELETE FROM facts.shipment_events WHERE id IN (SELECT unnest(?))",
                        [list(keys)])
            self.con.execute(
                f"INSERT INTO facts.{tbl} ({', '.join(c for c, _ in schema)}) "
                f"SELECT {', '.join(c for c, _ in schema)} FROM _batch_view")
            self.con.execute("COMMIT")
        except Exception:
            try:
                self.con.execute("ROLLBACK")
            except Exception:
                pass
            raise
        finally:
            self.con.unregister("_batch_view")

    def write_dim(self, tbl, records):
        import pyarrow as pa
        schema = SCHEMAS[tbl]
        # Dedup op primaire sleutel: een batch kan meerdere full-snapshots bevatten
        # (captor emittet elke 30s een volledige snapshot; bij backlog-catchup zit
        # dat in één buffer). Laatste waarneming per sleutel wint (nieuwste).
        key_cols = DIM_KEYS.get(tbl, [schema[0][0]])
        latest: dict = {}
        for r in records:
            k = tuple(str(r.get(c)) for c in key_cols)
            latest[k] = r
        records = list(latest.values())
        d = {}
        for col, kind in schema:
            if col in ("first_seen", "last_seen"):
                d[col] = [datetime.fromisoformat(str(r.get(col)).replace("Z", "+00:00"))
                          if r.get(col) else None for r in records]
            else:
                d[col] = [self._coerce(r.get(col), kind) for r in records]
        arr = pa.Table.from_pydict(d, schema=pa.schema(
            [(c, pa.timestamp("us", tz="UTC") if k == "ts" else
              pa.int64() if k == "int" else pa.float64() if k == "f64" else
              pa.string()) for c, k in schema]))
        self.con.register("_batch_view", arr)
        try:
            # ATOMIC upsert op sleutel (niet gehele tabel wissen) — een flush
            # kan een DEEL van een snapshot bevatten (flush 20s < cyclus 30s),
            # dus alleen de sleutels van deze batch verwijderen.
            # Set-based join-delete (snel) i.p.v. per-sleutel loop.
            self.con.execute("BEGIN TRANSACTION")
            if key_cols:
                kindmap = dict(schema)
                dk = pa.Table.from_pydict({
                    c: [self._coerce(r.get(c), kindmap.get(c, "str"))
                        for r in records] for c in key_cols})
                self.con.register("_dedup_keys", dk)
                conds = " AND ".join(f"t.{c} = d.{c}" for c in key_cols)
                self.con.execute(
                    f"DELETE FROM dims.{tbl} AS t USING _dedup_keys d WHERE {conds}")
                self.con.unregister("_dedup_keys")
            self.con.execute(
                f"INSERT INTO dims.{tbl} ({', '.join(c for c, _ in schema)}) "
                f"SELECT {', '.join(c for c, _ in schema)} FROM _batch_view")
            self.con.execute("COMMIT")
        except Exception:
            try:
                self.con.execute("ROLLBACK")
            except Exception:
                pass
            raise
        finally:
            self.con.unregister("_batch_view")

    def quarantine(self, topic, record, rule, reason):
        self.con.execute(
            "INSERT INTO catalog.quarantine (topic, record, rule, reason, captured_at) "
            "VALUES (?,?,?,?,?)",
            [topic, json.dumps(record, default=str), rule, reason,
             record.get("captured_at")])

    def counts(self):
        """Aantal per tabel via een EIGEN read-only-verbinding.

        Niet op self.con: die is de schrijf-verbinding van de flush-loop en
        een DuckDB-connection draait maximaal 1 query tegelijk — een
        gelijktijdige status-lezing zag de tabel leeg (tussen DELETE en
        INSERT van een dim-batch).
        """
        import duckdb
        out = {}
        try:
            rd = duckdb.connect()
            rd.execute(f"""CREATE OR REPLACE SECRET minio_secret (
                TYPE s3, ENDPOINT '{MINIO_ENDPOINT_BARE}', KEY_ID '{MINIO_ACCESS_KEY}',
                SECRET '{MINIO_SECRET_KEY}', REGION 'us-east-1', URL_STYLE 'path',
                USE_SSL false)""")
            rd.execute(f"""ATTACH 'ducklake:postgres:dbname={CATALOG_DB} host={CATALOG_HOST} port={CATALOG_PORT} user={CATALOG_USER} password={CATALOG_PASSWORD}'
                        AS lake (DATA_PATH '{DATA_PATH}')""")
            rd.execute("USE lake")
            for tbl in SCHEMAS:
                t = f"facts.{tbl}" if tbl in ("telemetry", "shipment_events") else f"dims.{tbl}"
                out[tbl] = rd.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
            out["quarantine"] = rd.execute(
                "SELECT count(*) FROM catalog.quarantine").fetchone()[0]
            rd.close()
        except Exception:
            for tbl in SCHEMAS:
                out[tbl] = None
            out["quarantine"] = None
        return out


# ────────────────────────────────────────────────────────────────
# Pipeline-loop
# ────────────────────────────────────────────────────────────────
TOPIC_TO_TABLE = {tp: tbl for tbl, tp, _k, _f in TABLES}
FACTS = {"telemetry", "shipment_events"}
# primaire sleutel per dim-tabel (uit TABLES) — voor snapshot-dedup
DIM_KEYS = {tbl: key for tbl, _tp, key, _f in TABLES if not _f}


class Pipeline:
    def __init__(self):
        self._lake = None
        self._consumer = None
        self._buf: dict[str, list] = {}
        self._dedup: dict[str, set] = {t: set() for t in FACTS}
        self.lock = threading.Lock()
        self.last_batch_at = _now()
        self._seeked = False
        self.records_in = Counter("pipeline_records_in_total", "Records uit Kafka", ["table"])
        self.written = Counter("pipeline_records_written_total", "Records naar lake", ["table"])
        self.quarantined = Counter("pipeline_quarantine_total", "Quarantaine records", ["table"])
        self.batch_ts = Gauge("pipeline_last_batch_timestamp_s", "Laatste flush per tabel", ["table"])
        self.last_flush_errors: dict[str, str] = {}

    # ── lazy setup (Kafka + DuckLake alleen bij eerste gebruik) ──
    @property
    def lake(self):
        if self._lake is None:
            self._lake = Lake()
        return self._lake

    @property
    def consumer(self):
        if self._consumer is None:
            # Unieke group-id per start: géén committed offsets → earliest leest
            # de volledige historie (robust t.o.v. handmatige group-reset).
            # Voor productie: vaste group + outbox-pattern; voor deze demo: vers.
            group_id = os.environ.get("KAFKA_GROUP_ID", "aegis-pipeline")
            self._consumer = KafkaConsumer(
                bootstrap_servers=KAFKA_BOOTSTRAP,
                group_id=group_id,
                enable_auto_commit=False,
                auto_offset_reset="earliest",
                value_deserializer=lambda b: json.loads(b),
                fetch_max_wait_ms=500,
            )
            self._consumer.subscribe([tp for _t, tp, _k, _f in TABLES])
            print(f"[pipeline] consumer groep={group_id}", flush=True)
        return self._consumer

    def _dedup_key(self, tbl, rec):
        p = rec.get("payload", {})
        return (str(p.get("vehicle_id")) + ":" + str(p.get("ts"))) if tbl == "telemetry" \
            else str(p.get("id"))

    def poll_into_buffers(self, max_wait_s: float = 1.0):
        """Pollt max ~max_wait_s seconden (niet blokkerend tot in het oneindige)."""
        n = 0
        t0 = time.time()
        while time.time() - t0 < max_wait_s:
            msgs = self.consumer.poll(timeout_ms=250)
            if msgs:
                for tp, msg_list in msgs.items():
                    # poll() keys zijn TopicPartition-objecten, niet topic-namen
                    tp_name = tp.topic if isinstance(tp, TopicPartition) else str(tp)
                    tbl = TOPIC_TO_TABLE.get(tp_name)
                    if not tbl:
                        continue
                    for msg in msg_list:
                        v = msg.value if not isinstance(msg, dict) else msg
                        n += 1
                        self.records_in.labels(table=tbl).inc()
                        payload = v.get("payload") or {}
                        contract = load_contract(tp_name)
                        ok, violations = validate_record(payload, contract)
                        if not ok and contract.get("on_violation") == "quarantine":
                            flat = {**payload, "captured_at": v.get("captured_at"),
                                    "cycle_id": v.get("cycle_id")}
                            self.lake.quarantine(tp_name, flat, violations[0][0], violations[0][1])
                            self.quarantined.labels(table=tbl).inc()
                            print(f"[pipeline] QUARANTINE {tp_name}: {violations[0]}", flush=True)
                            continue
                        if not ok:
                            print(f"[pipeline] FLAG {tp_name}: {violations[0]}", flush=True)
                        if tbl in FACTS:
                            k = self._dedup_key(tbl, v)
                            if k in self._dedup[tbl]:
                                continue
                            if len(self._dedup[tbl]) > DEDUP_LIMIT:
                                self._dedup[tbl] = set(list(self._dedup[tbl])[-DEDUP_LIMIT // 2:])
                            self._dedup[tbl].add(k)
                        flat = {**payload,
                                "captured_at": v.get("captured_at"),
                                "cycle_id": v.get("cycle_id"),
                                "cycle_ts": v.get("captured_at"),
                                "first_seen": v.get("captured_at"),
                                "last_seen": v.get("captured_at")}
                        self._buf.setdefault(tbl, []).append(flat)
            else:
                time.sleep(0.1)
        return n

    def flush(self):
        with self.lock:
            buf, self._buf = self._buf, {}
        if buf:
            try:
                _ = self.lake
            except Exception as e:  # noqa
                self.last_flush_errors["lake"] = str(e)[:120]
                print(f"[pipeline] lake nog niet ready: {e}", flush=True)
                self._buf = buf
                return
        for tbl, records in buf.items():
            if not records:
                continue
            try:
                if tbl in FACTS:
                    self.lake.write_fact(tbl, records)
                else:
                    self.lake.write_dim(tbl, records)
                self.written.labels(table=tbl).inc(len(records))
                self.batch_ts.labels(table=tbl).set(time.time())
            except Exception as e:  # noqa
                self.last_flush_errors[tbl] = str(e)
                print(f"[pipeline] flush fout {tbl}: {e}", flush=True)
                # retry: buffer opslaan voor volgende flush
                self._buf.setdefault(tbl, []).extend(records)
        self.last_batch_at = _now()

    def _seek_beginning_once(self):
        """Seek alle assigned partitions naar het begin (eenmalig).

        Demo-keuze: elke (re)start leest de volledige Kafka-historie.
        Veilig omdat de writer idempotent is: facts dedup op (vehicle_id,ts)/(id),
        dims zijn DELETE+INSERT (volledige snapshot). Zo ontkomen we aan
        stale committed offsets die de pipeline anders "leeg" laten lezen.
        """
        if self._seeked:
            return
        for _ in range(60):  # tot assignment (max ~60s)
            if self._consumer.assignment():
                break
            self._consumer.poll(timeout_ms=1000)
        assigned = self._consumer.assignment()
        if assigned:
            self._consumer.seek_to_beginning(*assigned)
            self._seeked = True
            print(f"[pipeline] seek-to-beginning over {len(assigned)} partitions", flush=True)

    def run(self):
        print("[pipeline] loop start", flush=True)
        try:
            _ = self.lake  # DuckLake-attach vóór de eerste flush
            print("[pipeline] lake klaar", flush=True)
        except Exception as e:  # noqa
            print(f"[pipeline] lake-init nog niet mogelijk: {e}", flush=True)
        try:
            _ = self.consumer  # consumer-group join
        except Exception as e:  # noqa
            print(f"[pipeline] consumer-init fout: {e}", flush=True)
        try:
            self._seek_beginning_once()
        except Exception as e:  # noqa
            print(f"[pipeline] seek-to-beginning fout: {e}", flush=True)
        while True:
            t0 = time.time()
            try:
                got = self.poll_into_buffers()
                if got:
                    print(f"[pipeline] +{got} records gepolld (buf: "
                          f"{sum(len(v) for v in self._buf.values())})", flush=True)
                while time.time() - t0 < BATCH_INTERVAL:
                    time.sleep(0.2)
                before = sum(len(v) for v in self._buf.values())
                self.flush()
                if before or self.last_flush_errors:
                    print(f"[pipeline] flush: {before} records, errors="
                          f"{self.last_flush_errors or 'geen'}", flush=True)
                try:
                    self.consumer.commit()
                except Exception:
                    pass
            except Exception as e:  # noqa
                print(f"[pipeline] loop-fout: {e}", flush=True)
                time.sleep(5)

    # ── status endpoint ───────────────────────────────────────
    def status(self):
        counts = {}
        if self._lake is not None:
            try:
                counts = self._lake.counts()
            except Exception as e:  # noqa
                counts = {"error": str(e)[:120]}
        return {
            "status": "ok" if not self.last_flush_errors else "degraded",
            "last_batch_at": self.last_batch_at,
            "buffered": {t: len(v) for t, v in self._buf.items()},
            "flush_errors": self.last_flush_errors,
            "lake_counts": counts,
            "lake_attached": self._lake is not None,
        }


pipeline = Pipeline()


app = FastAPI(title="AEGIS Analytics Pipeline", version="0.1.0")


@app.get("/healthz")
def healthz():
    """Lichtgewicht healthcheck (raakt géén lake) — voor de container-healthcheck."""
    return {"ok": True, "lake_attached": pipeline._lake is not None,
            "flush_errors": pipeline.last_flush_errors}


@app.get("/status")
def status():
    return pipeline.status()


@app.get("/metrics")
def metrics():
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


def main():
    threading.Thread(target=pipeline.run, daemon=True).start()
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8410, log_level="warning")


if __name__ == "__main__":
    main()
