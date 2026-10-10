"""Live topologie + volledige data-context voor de analytics UI.

GET /api/topology        → nodes (live status + latency) + pipeline flow-counters
GET /api/context/tables  → per tabel: bron → topic → pipeline → lake, rijtallen,
                           freshness, contract-checks, kolommen, Trino-sneldraaier.

Alles read-only, met caching zodat de UI elke 5s mag pollen zonder de
onderliggende systemen te belasten. Probes: HTTP/TCP/SQL van binnennet
(aegis_default) — geen host-ports nodig.
"""
import os
import re
import time
import json
import socket
import threading
import urllib.request
from datetime import datetime, timezone

import psycopg2
import yaml

from captor.config import (AEGIS_DB_HOST, AEGIS_DB_PORT, AEGIS_DB_DB,
                           AEGIS_DB_USER, AEGIS_DB_PASSWORD,
                           KAFKA_BOOTSTRAP,
                           CATALOG_HOST, CATALOG_PORT, CATALOG_DB,
                           CATALOG_USER, CATALOG_PASSWORD,
                           TABLES)
from pipeline.main import SCHEMAS  # kolommen per tabel (single source)

DASH_PORT = 8410
_KAFKA_HOST, _KAFKA_PORT = KAFKA_BOOTSTRAP.split(":")

# ── cache ──────────────────────────────────────────────────────
_cache: dict = {}
_lock = threading.Lock()


def _cached(key, ttl, fn):
    with _lock:
        e = _cache.get(key)
        if e and time.time() - e[0] < ttl:
            return e[1]
    val = fn()
    with _lock:
        _cache[key] = (time.time(), val)
    return val


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


# ── probes ─────────────────────────────────────────────────────
def _probe_http(url, timeout=4, max_bytes=0):
    t0 = time.time()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            data = r.read(max_bytes) if max_bytes else r.read()
            body = data.decode("utf-8", "replace")
            return r.status == 200, int((time.time() - t0) * 1000), body
    except Exception as e:  # noqa
        return False, int((time.time() - t0) * 1000), str(e)[:100]


def _probe_tcp(host, port, timeout=3):
    t0 = time.time()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, int((time.time() - t0) * 1000), "reachable"
    except Exception as e:  # noqa
        return False, int((time.time() - t0) * 1000), str(e)[:100]


def _probe_pg(host, port, db, user, pw):
    t0 = time.time()
    try:
        c = psycopg2.connect(host=host, port=port, dbname=db, user=user,
                             password=pw, connect_timeout=5,
                             options="-c default_transaction_read_only=on")
        c.autocommit = True
        cur = c.cursor()
        cur.execute("SELECT 1")
        cur.fetchone()
        c.close()
        return True, int((time.time() - t0) * 1000), "up"
    except Exception as e:  # noqa
        return False, int((time.time() - t0) * 1000), str(e)[:100]


# ── node probes (elk met eigen TTL) ────────────────────────────
def node_aegis_db():
    def f():
        ok, ms, _ = _probe_pg(AEGIS_DB_HOST, AEGIS_DB_PORT, AEGIS_DB_DB,
                              AEGIS_DB_USER, AEGIS_DB_PASSWORD)
        detail = "read-only · source of truth (unchanged)"
        if ok:
            try:
                c = psycopg2.connect(host=AEGIS_DB_HOST, port=AEGIS_DB_PORT,
                                     dbname=AEGIS_DB_DB, user=AEGIS_DB_USER,
                                     password=AEGIS_DB_PASSWORD,
                                     connect_timeout=5)
                cur = c.cursor()
                cur.execute("SELECT count(*) FROM information_schema.tables "
                            "WHERE table_schema='public'")
                n = cur.fetchone()[0]
                c.close()
                detail = f"read-only · {n} public tables · source of truth"
            except Exception:
                pass
        return {"status": "up" if ok else "down", "latency_ms": ms,
                "detail": detail}
    return _cached("n:aegis_db", 8, f)


def node_captor():
    def f():
        ok, ms, body = _probe_http("http://captor:8400/health")
        detail = "n/a"
        rows_cycle = None
        if ok:
            try:
                d = json.loads(body)
                tbls = d.get("tables") or {}
                if isinstance(tbls, dict) and any("rows_last_cycle" in v for v in tbls.values() if isinstance(v, dict)):
                    rows_cycle = sum(v.get("rows_last_cycle", 0) for v in tbls.values() if isinstance(v, dict))
                elif isinstance(tbls, dict):
                    rows_cycle = sum(v if isinstance(v, int) else 0 for v in tbls.values())
                detail = (f"status {d.get('status')} · rows/cycle {rows_cycle} · "
                          f"cycle {str(d.get('last_cycle_at',''))[:19]}")
            except Exception:
                detail = body[:80]
        return {"status": "up" if ok else "down", "latency_ms": ms,
                "detail": detail, "rows_per_cycle": rows_cycle}
    return _cached("n:captor", 8, f)


def _kafka_meta():
    def f():
        out = {"topics": 0, "partitions": 0}
        try:
            from kafka import KafkaConsumer
            kc = KafkaConsumer(bootstrap_servers=KAFKA_BOOTSTRAP)
            topics = kc.topics()
            out["topics"] = len(topics)
            for t in topics:
                out["partitions"] += len(kc.partitions_for_topic(t) or set())
            kc.close()
        except Exception as e:  # noqa
            out["error"] = str(e)[:80]
        return out
    return _cached("n:kafka-meta", 120, f)


def node_kafka():
    def f():
        ok, ms, _ = _probe_tcp(_KAFKA_HOST, int(_KAFKA_PORT))
        meta = _kafka_meta()
        detail = (f"{meta.get('topics','?')} topics · "
                  f"{meta.get('partitions','?')} partitions · RF1 · retention 168h"
                  if ok else "broker onbereikbaar")
        if meta.get("error"):
            detail += f" · meta: {meta['error']}"
        return {"status": "up" if ok else "down", "latency_ms": ms,
                "detail": detail}
    return _cached("n:kafka", 8, f)


def node_kafka_ui():
    def f():
        ok, ms, _ = _probe_tcp("kafka-ui", 8080)
        return {"status": "up" if ok else "down", "latency_ms": ms,
                "detail": "browse events :8040"}
    return _cached("n:kafka_ui", 15, f)


_METRIC_RE = re.compile(
    r"^(pipeline_records_in_total|pipeline_records_written_total)"
    r'\{table="([^"]+)"\}\s+([\d.]+)')


def node_pipeline():
    def f():
        ok, ms, body = _probe_http(f"http://pipeline:{DASH_PORT}/healthz")
        out = {"status": "up" if ok else "down", "latency_ms": ms,
               "detail": "contract validation · dedup · 20s micro-batch",
               "flush_errors": {}, "in_total": {}, "written_total": {}}
        if ok:
            try:
                d = json.loads(body)
                fe = d.get("flush_errors", {})
                out["flush_errors"] = fe
                out["detail"] += (" · no flush-errors" if not fe
                                  else " · flush-errors " + str(fe))
            except Exception:
                pass
        m_ok, _, m_body = _probe_http(f"http://pipeline:{DASH_PORT}/metrics")
        if m_ok:
            in_t, wr_t = {}, {}
            for line in m_body.splitlines():
                m = _METRIC_RE.match(line.strip())
                if m:
                    (in_t if "in_total" in m.group(1) else wr_t)[m.group(2)] = int(float(m.group(3)))
            out["in_total"] = in_t
            out["written_total"] = wr_t
        # buffered + last_batch via /status is zwaar (lake-counts) → alleen healthz
        return out
    return _cached("n:pipeline", 5, f)


def node_minio():
    def f():
        ok, ms, _ = _probe_http("http://minio:9000/minio/health/ready")
        return {"status": "up" if ok else "down", "latency_ms": ms,
                "detail": "S3 API :9000 · console :9001 · bucket aegis-lake"}
    return _cached("n:minio", 10, f)


def node_lake_catalog():
    def f():
        ok, ms, _ = _probe_pg(CATALOG_HOST, CATALOG_PORT, CATALOG_DB,
                              CATALOG_USER, CATALOG_PASSWORD)
        return {"status": "up" if ok else "down", "latency_ms": ms,
                "detail": "DuckLake v1.0 metadata (10 tables + quarantine)"}
    return _cached("n:lake_catalog", 8, f)


def node_trino():
    def f():
        ok, ms, body = _probe_http("http://trino:8080/v1/info")
        detail = "federation: aegis_db (PostGIS) + lake_catalog"
        if ok:
            try:
                d = json.loads(body)
                detail += f" · {d.get('environment','?')}"
            except Exception:
                pass
        return {"status": "up" if ok else "down", "latency_ms": ms,
                "detail": detail}
    return _cached("n:trino", 10, f)


def node_duckdb():
    def f():
        t0 = time.time()
        try:
            from dashboard import api_core
            api_core.duck().execute("SELECT 1").fetchone()
            return {"status": "up", "latency_ms": int((time.time() - t0) * 1000),
                    "detail": "embedded reader in pipeline + dashboard (primary lake-reader)"}
        except Exception as e:  # noqa
            return {"status": "down",
                    "latency_ms": int((time.time() - t0) * 1000),
                    "detail": str(e)[:80]}
    return _cached("n:duckdb", 10, f)


def node_dashboard():
    return {"status": "up", "latency_ms": 0,
            "detail": "dezze UI · API :8401 · UI+API :8402 (same-origin)"}


def node_prometheus():
    def f():
        ok, ms, _ = _probe_http("http://prometheus:9090/-/healthy")
        return {"status": "up" if ok else "down", "latency_ms": ms,
                "detail": "scrape captor/pipeline/dashboard · 15s"}
    return _cached("n:prometheus", 15, f)


def node_grafana():
    def f():
        ok, ms, body = _probe_http("http://grafana:3000/api/health")
        return {"status": "up" if ok else "down", "latency_ms": ms,
                "detail": "Pipeline Health dashboard · admin/Password123!"}
    return _cached("n:grafana", 15, f)


def node_jupyter():
    def f():
        ok, ms, _ = _probe_tcp("jupyter", 8888)
        return {"status": "up" if ok else "down", "latency_ms": ms,
                "detail": "ad-hoc analysis · Spark + DuckDB"}
    return _cached("n:jupyter", 20, f)


def node_adminer():
    def f():
        ok, ms, _ = _probe_tcp("adminer", 8080)
        return {"status": "up" if ok else "down", "latency_ms": ms,
                "detail": "SQL-console: aegis_db + lake_catalog"}
    return _cached("n:adminer", 20, f)


_NODE_PROBES = {
    "aegis_db": node_aegis_db, "captor": node_captor, "kafka": node_kafka,
    "kafka_ui": node_kafka_ui, "pipeline": node_pipeline, "minio": node_minio,
    "lake_catalog": node_lake_catalog, "trino": node_trino,
    "duckdb": node_duckdb, "dashboard": node_dashboard,
    "prometheus": node_prometheus, "grafana": node_grafana,
    "jupyter": node_jupyter, "adminer": node_adminer,
}


def get_topology():
    nodes = {}
    for nid, fn in _NODE_PROBES.items():
        try:
            nodes[nid] = fn()
        except Exception as e:  # noqa
            nodes[nid] = {"status": "unknown", "latency_ms": None,
                          "detail": str(e)[:80]}
    pl = nodes.get("pipeline", {})
    return {
        "ts": _now_iso(),
        "nodes": nodes,
        "pipeline": {
            "flush_errors": pl.get("flush_errors", {}),
            "records_in_total": pl.get("in_total", {}),
            "records_written_total": pl.get("written_total", {}),
        },
    }


# ── data-context per tabel ─────────────────────────────────────
def _type_map(t):
    return {"str": "TEXT", "int": "INT", "f64": "DOUBLE", "ts": "TIMESTAMPTZ"}.get(t, "TEXT")


def _source_rows():
    """Row counts on the AEGIS source (1 connection, 30s cache)."""
    def f():
        out = {}
        try:
            c = psycopg2.connect(host=AEGIS_DB_HOST, port=AEGIS_DB_PORT,
                                 dbname=AEGIS_DB_DB, user=AEGIS_DB_USER,
                                 password=AEGIS_DB_PASSWORD, connect_timeout=8,
                                 options="-c default_transaction_read_only=on")
            cur = c.cursor()
            for t in [x[0] for x in TABLES] + ["incidents"]:
                cur.execute(f'SELECT count(*) FROM {t}')  # naam uit vaste whitelist
                out[t] = cur.fetchone()[0]
            c.close()
        except Exception as e:  # noqa
            out["error"] = str(e)[:80]
        return out
    return _cached("ctx:src", 30, f)


def _lake_rows():
    """Rijtallen + freshness per lake-tabel (30s cache)."""
    from dashboard import api_core
    def f():
        out = {}
        try:
            con = api_core.duck()
            for t in SCHEMAS:
                sch = "facts" if t in ("telemetry", "shipment_events") else "dims"
                tscol = "captured_at" if sch == "facts" else "cycle_ts"
                r = con.execute(
                    f"SELECT count(*), max({tscol}) FROM {sch}.{t}").fetchone()
                mx = r[1]
                if mx is not None and mx.tzinfo is None:
                    mx = mx.replace(tzinfo=timezone.utc)
                age = int((datetime.now(timezone.utc) - mx).total_seconds()) if mx else None
                out[t] = {"rows": r[0], "age_s": age,
                          "max_ts": mx.isoformat() if mx else None}
        except Exception as e:  # noqa
            out["error"] = str(e)[:80]
        return out
    return _cached("ctx:lake", 30, f)


def _quarantine_24h():
    from dashboard import api_core
    def f():
        out = {}
        try:
            con = api_core.duck()
            rows = con.execute(
                "SELECT topic, count(*) FROM catalog.quarantine "
                "WHERE captured_at > (now() - interval '24 hour') "
                "GROUP BY topic").fetchall()
            out = {t: n for t, n in rows}
            out["total"] = sum(n for _t, n in rows)
        except Exception:
            out = {"total": 0}
        return out
    return _cached("ctx:quar", 60, f)


_CONTRACTS_DIR = os.path.join(os.path.dirname(__file__), "..", "contracts")
_CONTRACT_CACHE = {}


def _contract(tbl, is_fact):
    fname = "shipment-events" if tbl == "shipment_events" else tbl
    if fname not in _CONTRACT_CACHE:
        p = os.path.join(_CONTRACTS_DIR, fname + ".yaml")
        try:
            with open(p) as fh:
                _CONTRACT_CACHE[fname] = yaml.safe_load(fh) or {}
        except Exception:
            _CONTRACT_CACHE[fname] = {}
    c = _CONTRACT_CACHE[fname]
    checks = c.get("checks", {}) or {}
    schema = checks.get("schema", {}) or {}
    enums = checks.get("enums", {}) or {}
    ranges = checks.get("ranges", {}) or {}
    return {
        "owner": c.get("owner", "—"),
        "sla_s": c.get("freshness_sla_s"),
        "on_violation": c.get("on_violation", "flag"),
        "checks": {"required": len(schema.get("required", [])),
                   "enums": len(enums), "ranges": len(ranges)},
        "required_cols": schema.get("required", []),
    }


def get_context_tables():
    src = _source_rows()
    lake = _lake_rows()
    quar = _quarantine_24h()
    tables = []
    for tbl, topic, key, is_fact in TABLES:
        c = _contract(tbl, is_fact)
        q = quar.get(topic, 0)
        l = lake.get(tbl, {})
        tables.append({
            "name": tbl,
            "kind": "fact" if is_fact else "dim",
            "pk": key,
            "source": {"db": "aegis_db", "rows": src.get(tbl)},
            "topic": {"name": topic, "partitions": 3},
            "pipeline": {"job": "pipeline.main", "batch_s": 20,
                         "dedup": " + ".join(key) if is_fact else "upsert op PK " + " + ".join(key)},
            "lake": {"table": f"{'facts' if is_fact else 'dims'}.{tbl}",
                     "rows": l.get("rows"), "age_s": l.get("age_s"),
                     "max_ts": l.get("max_ts")},
            "contract": {**c, "violations_24h": q,
                         "status": "yellow" if q else "green"},
            "columns": [{"name": n, "type": _type_map(t)} for n, t in SCHEMAS[tbl]],
            "trino_src": f"SELECT * FROM aegis_db.public.{tbl} LIMIT 20",
            "lake_q": f"SELECT * FROM {'facts' if is_fact else 'dims'}.{tbl} ORDER BY ts DESC LIMIT 20"
                      if is_fact else
                      f"SELECT * FROM dims.{tbl} LIMIT 20",
        })
    # incidents: live vanaf de bron (Trino 481 PostGIS-regressie #29505)
    n_inc = src.get("incidents")
    tables.append({
        "name": "incidents", "kind": "live", "pk": ["id"],
        "source": {"db": "aegis_db", "rows": n_inc},
        "topic": {"name": "—", "partitions": 0},
        "pipeline": {"job": "none (direct)", "batch_s": None, "dedup": "read-only query"},
        "lake": {"table": None, "rows": None, "age_s": 0, "max_ts": None},
        "contract": {"owner": "—", "sla_s": None, "on_violation": "—",
                     "checks": {}, "violations_24h": 0, "status": "green"},
        "columns": [],
        "note": "Trino 481 postgres-connector fails on PostGIS-Geometry (#29505) "
                "→ dashboard reads incidents live via psycopg2 (read-only).",
        "trino_src": None, "lake_q": None,
    })
    total_src = sum(v for k, v in src.items() if k != "error" and isinstance(v, int))
    total_lake = sum(v.get("rows", 0) for v in lake.values() if isinstance(v, dict) and v.get("rows") is not None)
    n_green = sum(1 for t in tables if t["contract"]["status"] == "green")
    return {
        "ts": _now_iso(),
        "summary": {
            "source_rows": total_src,
            "lake_rows": total_lake,
            "quarantine_24h": quar.get("total", 0),
            "contracts_green": f"{n_green}/{len(tables)}",
            "error_src": src.get("error"),
            "error_lake": lake.get("error"),
        },
        "tables": tables,
    }
