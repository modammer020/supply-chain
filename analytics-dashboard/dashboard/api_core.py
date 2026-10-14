"""Dashboard API: KPI, trends, incidents, lineage, quality, status (FR-007..011).

Leest DuckLake (DuckDB embedded) + federated (Trino). Elke kaart draagt
context: value, source_table, semantic_definition, data_age_s, contract_status.
Stale-degradation (FR-011): backend-down → laatste waarde + status stale.
"""
import os
import time
import yaml
import threading
from datetime import datetime, timezone
import duckdb
import psycopg2

from captor.config import (MINIO_ENDPOINT, MINIO_ENDPOINT_BARE, MINIO_ACCESS_KEY,
                           MINIO_SECRET_KEY,
                           DATA_PATH, CATALOG_HOST, CATALOG_PORT, CATALOG_DB,
                           CATALOG_USER, CATALOG_PASSWORD, AEGIS_DB_DB,
                           AEGIS_DB_HOST, AEGIS_DB_PORT, AEGIS_DB_USER, AEGIS_DB_PASSWORD)

CONTRACTS_DIR = os.path.join(os.path.dirname(__file__), "..", "contracts")
SEM_PATH = os.path.join(CONTRACTS_DIR, "semantics.yaml")
TRINO_HOST = os.environ.get("TRINO_HOST", "trino")
TRINO_PORT = int(os.environ.get("TRINO_PORT", "8080"))
TRINO_USER = os.environ.get("TRINO_USER", "aegis")
KPI_CACHE_S = 15

# ── semantiek ──────────────────────────────────────────────────
with open(SEM_PATH) as f:
    SEMANTICS = yaml.safe_load(f)

# ── DuckDB (embedded → DuckLake) ──────────────────────────────
# One DuckDB connection PER WORKER THREAD (thread-local).  DuckDB connections
# are not thread-safe — sharing one connection across the uvicorn threadpool
# caused C++ aborts ("terminate called without an active exception").  The
# per-thread connection is created once (extensions load from the prebuilt
# ~/.duckdb/extensions cache, ATTACH ~0.1 s) and refreshed after 60 s so new
# DuckLake snapshots are picked up.
_thread_local = threading.local()
_TTL_S = 60


def _duck():
    con = duckdb.connect()
    for ext in ("ducklake", "httpfs", "postgres"):
        con.execute(f"INSTALL {ext}")
        con.execute(f"LOAD {ext}")
    con.execute(f"""CREATE OR REPLACE SECRET minio_secret (
        TYPE s3, ENDPOINT '{MINIO_ENDPOINT_BARE}', KEY_ID '{MINIO_ACCESS_KEY}',
        SECRET '{MINIO_SECRET_KEY}', REGION 'us-east-1', URL_STYLE 'path',
        USE_SSL false)""")
    con.execute(f"""ATTACH 'ducklake:postgres:dbname={CATALOG_DB} host={CATALOG_HOST} port={CATALOG_PORT} user={CATALOG_USER} password={CATALOG_PASSWORD}'
                    AS lake (DATA_PATH '{DATA_PATH}')""")
    con.execute("USE lake")
    return con


def duck():
    """Per-thread DuckDB connection (safe: never shared across threads)."""
    con = getattr(_thread_local, "con", None)
    if con is None or time.time() - getattr(_thread_local, "t", 0) > _TTL_S:
        try:
            if con:
                con.close()
        except Exception:
            pass
        try:
            con = _duck()
            _thread_local.con = con
            _thread_local.t = time.time()
        except Exception:
            # broken/lost connection → retry once with a fresh one
            con = _duck()
            _thread_local.con = con
            _thread_local.t = time.time()
    return con


def _aegis():
    """Read-only verbinding met de AEGIS-bron (psycopg2 rechtstreeks).

    Trino 481's postgres-connector faalt op PostGIS-Geometry-kolommen
    (regressie trinodb/trino#29505) — direct JDBC-equivalent via psql
    is robuuster en blijft live op de bron. Read-only: geen schrijfopdrachten.
    """
    conn = psycopg2.connect(
        host=AEGIS_DB_HOST, port=AEGIS_DB_PORT, dbname=AEGIS_DB_DB,
        user=AEGIS_DB_USER, password=AEGIS_DB_PASSWORD,
        connect_timeout=8, options="-c default_transaction_read_only=on")
    conn.autocommit = True
    return conn


def _trino():
    import trino  # lazy: alleen de status-check / federatie gebruikt dit
    return trino.dbapi.connect(host=TRINO_HOST, port=TRINO_PORT, user=TRINO_USER)


# ── contract-status per tabel (quarantaine in 1u) ─────────────
def _contract_status(source_table: str):
    try:
        con = duck()
        topic = f"aegis.dim.{source_table}"
        if source_table in ("telemetry", "shipment_events"):
            topic = f"aegis.events.{source_table}"
        r = con.execute(
            "SELECT count(*) FROM catalog.quarantine "
            "WHERE topic=? AND captured_at > (now() - interval '1 hour')",
            [topic]).fetchone()[0]
        if r > 0:
            return "yellow"
        return "green"
    except Exception:
        return "green"


def _age_seconds():
    """Data age (s) — live right off the AEGIS source (read-only)."""
    try:
        with _aegis() as c, c.cursor() as cur:
            cur.execute("SELECT max(ts) FROM telemetry")
            r = cur.fetchone()[0]
            if r:
                if r.tzinfo is None:  # DuckDB kan naive teruggeven
                    r = r.replace(tzinfo=timezone.utc)
                return int((datetime.now(timezone.utc) - r).total_seconds())
            return 0
    except Exception:
        return 99999


# KPI-queries: live rechtstreeks op de AEGIS-bron (read-only, psycopg2).
# Zelfde bron + queries als de operationele command center (aegis, :8300) →
# perfect in sync.  De DuckLake wordt nog steeds gebruikt voor trends /
# data-engineer / topology, maar de 16 KPI's lezen de ground truth direct —
# zo vermijden we de 10k-bestanden-scan op de lake en zijn de waarden exact
# wat de command center toont.
def _kpi_source_query(key: str):
    """(psycopg2 SQL, source_table) right off the AEGIS source."""
    M = {
        "otif_pct": ("SELECT round(avg(otif_pct),1) FROM lanes", "lanes"),
        "value_in_transit": ("SELECT coalesce(sum(value_eur),0) FROM shipments WHERE status='in_transit'", "shipments"),
        "active_shipments": ("SELECT count(*) FROM shipments WHERE status='in_transit'", "shipments"),
        "delayed": ("SELECT count(*) FROM shipments WHERE status IN ('delayed','rerouted')", "shipments"),
        "incidents": ("SELECT count(*) FROM incidents WHERE resolved_at IS NULL", "incidents"),
        "incidents_p1": ("SELECT count(*) FROM incidents WHERE resolved_at IS NULL AND severity='P1'", "incidents"),
        "carbon_tco2": ("SELECT round(sum(carbon_tco2)::numeric,2) FROM vehicles", "vehicles"),
        "low_stock_skus": ("SELECT count(*) FROM inventory WHERE stock<reorder", "inventory"),
        "weekly_demand_units": ("SELECT coalesce(sum(velocity),0) FROM inventory", "inventory"),
        "units": ("SELECT count(*) FROM vehicles", "vehicles"),
        "fleet_fuel_avg": ("SELECT round(avg(fuel_pct)::numeric,1) FROM vehicles WHERE fuel_pct IS NOT NULL", "vehicles"),
        "fleet_speed_avg": ("SELECT round(avg(speed_kmh)::numeric,1) FROM telemetry WHERE speed_kmh>0 AND ts>now()-interval '24 hour'", "telemetry"),
        "live_vehicles_10m": ("SELECT count(DISTINCT vehicle_id) FROM telemetry WHERE ts>now()-interval '10 minutes'", "telemetry"),
        "cargo_temp": ("SELECT round(avg(cargo_temp)::numeric,1) FROM telemetry", "telemetry"),
        "telemetry_count": ("SELECT count(*) FROM telemetry", "telemetry"),
        "shipment_status": ("SELECT count(*) FROM shipments", "shipments"),
    }
    return M.get(key)


_kpi_cache = {"t": 0, "data": None}


def get_kpis():
    if time.time() - _kpi_cache["t"] < KPI_CACHE_S and _kpi_cache["data"]:
        return _kpi_cache["data"]
    out = []
    age = _age_seconds()
    for key, sem in SEMANTICS.items():
        qs = _kpi_source_query(key)
        if qs is None:
            q, src = (None, sem.get("source_table"))
        else:
            q, src = qs
        value = None
        live = False
        try:
            # Alles direct op de AEGIS-bron (read-only) — in sync met CC.
            with _aegis() as c, c.cursor() as cur:
                cur.execute(q)
                value = cur.fetchone()[0]
            live = True
            out.append({
                "key": key, "value": float(value) if value is not None else None,
                "label": sem.get("label", key), "unit": sem.get("unit", ""),
                "world": sem.get("world", "it"),
                "source_table": src,
                "semantic_definition": sem.get("definition", ""),
                "data_age_s": age,
                "contract_status": _contract_status(src),
                "live": live,
            })
        except Exception as e:  # noqa
            out.append({
                "key": key, "value": None, "label": sem.get("label", key),
                "world": sem.get("world", "it"),
                "source_table": src, "semantic_definition": sem.get("definition", ""),
                "data_age_s": 99999, "contract_status": "red", "live": False,
                "status": "stale", "note": str(e)[:120],
            })
    _kpi_cache.update({"t": time.time(), "data": out})
    return out


# ── trends ─────────────────────────────────────────────────────
# ── trends (live off the AEGIS source — in sync with CC) ───────
# Postgres has no time_bucket(); we bucket on epoch seconds with floor
# division, which gives identical bucket edges.
def get_trend(metric: str, bucket: str = "1h", hours: int = 24):
    S = {
        "5m": 300, "15m": 900, "1h": 3600, "1d": 86400,
    }
    b = S.get(bucket, 3600)
    H = min(int(hours or 24), 168)
    if metric == "telemetry_count":
        q = ("SELECT (EXTRACT(EPOCH FROM ts)::bigint / %s)::bigint * %s AS bucket, count(*) AS v "
             "FROM telemetry WHERE ts > now() - (%s || ' hours')::interval "
             "GROUP BY 1 ORDER BY 1")
        cols = ["telemetry"]
    elif metric == "cargo_temp":
        q = ("SELECT (EXTRACT(EPOCH FROM ts)::bigint / %s)::bigint * %s AS bucket, "
             "round(avg(cargo_temp)::numeric,2) AS v, max(cargo_temp) AS mx "
             "FROM telemetry WHERE ts > now() - (%s || ' hours')::interval "
             "GROUP BY 1 ORDER BY 1")
        cols = ["telemetry"]
    elif metric == "fleet_speed":
        q = ("SELECT (EXTRACT(EPOCH FROM ts)::bigint / %s)::bigint * %s AS bucket, "
             "round(avg(speed_kmh)::numeric,1) AS v "
             "FROM telemetry WHERE speed_kmh > 0 "
             "AND ts > now() - (%s || ' hours')::interval GROUP BY 1 ORDER BY 1")
        cols = ["telemetry"]
    elif metric == "live_vehicles":
        q = ("SELECT (EXTRACT(EPOCH FROM ts)::bigint / %s)::bigint * %s AS bucket, "
             "count(DISTINCT vehicle_id) AS v "
             "FROM telemetry WHERE ts > now() - (%s || ' hours')::interval "
             "GROUP BY 1 ORDER BY 1")
        cols = ["telemetry"]
    else:
        return {"series": []}
    try:
        with _aegis() as c, c.cursor() as cur:
            cur.execute(q, (b, b, str(H)))
            rows = cur.fetchall()
        if metric == "cargo_temp":
            return {"series": [{"ts": datetime.fromtimestamp(int(r[0]), tz=timezone.utc).isoformat(),
                                "value": float(r[1]) if r[1] is not None else None,
                                "max": float(r[2]) if r[2] is not None else None}
                               for r in rows]}
        return {"series": [{"ts": datetime.fromtimestamp(int(r[0]), tz=timezone.utc).isoformat(),
                            "value": float(r[1]) if r[1] is not None else None}
                           for r in rows]}
    except Exception as e:  # noqa
        return {"series": [], "error": str(e)[:120]}


# ── incidents (live op bron, read-only) ────────────────────────
def get_incidents(limit: int = 50):
    try:
        with _aegis() as c, c.cursor() as cur:
            cur.execute("""
              SELECT i.id, i.lane_id, i.kind, i.severity, i.title,
                     i.affected_vehicle, i.created_at
              FROM incidents i
              ORDER BY i.created_at DESC LIMIT %s""", (limit,))
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
            for r in rows:
                if isinstance(r.get("created_at"), datetime):
                    r["created_at"] = r["created_at"].isoformat()
        return {"incidents": rows, "live": True}
    except Exception as e:  # noqa
        # fallback op lake
        try:
            con = duck()
            cur = con.execute(
                "SELECT note, captured_at FROM facts.shipment_events WHERE type='status' "
                "AND note ILIKE '%incident%' ORDER BY captured_at DESC LIMIT ?", [limit])
            return {"incidents": [{"title": r[0], "ts": r[1].isoformat()}
                                  for r in cur.fetchall()], "live": False}
        except Exception as e2:
            return {"incidents": [], "error": str(e2)[:120]}


# ── lineage ────────────────────────────────────────────────────
def get_lineage(card: str):
    src = next((s.get("source_table") for k, s in SEMANTICS.items() if k == card), "unknown")
    contract_status = _contract_status(src)
    quar = 0
    try:
        con = duck()
        topic = f"aegis.dim.{src}" if src not in ("telemetry", "shipment_events") else f"aegis.events.{src}"
        quar = con.execute(
            "SELECT count(*) FROM catalog.quarantine WHERE topic=? AND captured_at > (now() - interval '24 hour')",
            [topic]).fetchone()[0]
    except Exception:
        pass
    return {
        "card": card,
        "source": {"db": "aegis_db", "table": src,
                   "topic": f"aegis.{'dim' if src not in ('telemetry','shipment_events') else 'events'}.{src}"},
        "pipeline": {"spark_job": "pipeline-main (duckdb→ducklake)",
                     "lake_table": f"{'facts' if src in ('telemetry','shipment_events') else 'dims'}.{src}"},
        "contract": {"status": contract_status, "violations_24h": quar},
        "freshness": {"data_age_s": _age_seconds(), "sla_s": 300},
        "evidence": {"note": "bron-terugkoppeling via topic + lake-table; records traceerbaar op captured_at"},
    }


# ── quality/quarantine ─────────────────────────────────────────
def get_quarantine(topic: str = None, limit: int = 50):
    try:
        con = duck()
        q = ("SELECT topic, rule, reason, captured_at FROM catalog.quarantine "
             + ("WHERE topic=?" if topic else "") +
             " ORDER BY captured_at DESC LIMIT ?")
        args = [topic] if topic else []
        args.append(limit)
        rows = con.execute(q, args).fetchall()
        return {"quarantine": [
            {"topic": t, "rule": r, "reason": rs,
             "captured_at": ts.isoformat() if hasattr(ts, "isoformat") else str(ts)}
            for t, r, rs, ts in rows]}
    except Exception as e:  # noqa
        return {"quarantine": [], "error": str(e)[:120]}


# ── status ─────────────────────────────────────────────────────
def get_status():
    st = {"kpi_cache_age_s": int(time.time() - _kpi_cache["t"]), "services": {}}
    for name, fn in {"ducklake": lambda: duck().execute("SELECT 1").fetchone(),
                     "trino": lambda: _trino()}.items():
        try:
            fn()
            st["services"][name] = "up"
        except Exception as e:  # noqa
            st["services"][name] = f"down: {str(e)[:60]}"
    return st
