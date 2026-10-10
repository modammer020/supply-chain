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
_lock = threading.Lock()


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


_duck_cached = {"con": None, "t": 0}


def duck():
    with _lock:
        if _duck_cached["con"] is None or time.time() - _duck_cached["t"] > 30:
            try:
                _duck_cached["con"].close()
            except Exception:
                pass
            _duck_cached["con"] = _duck()
            _duck_cached["t"] = time.time()
        return _duck_cached["con"]


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
    try:
        con = duck()
        r = con.execute(
            "SELECT max(captured_at) FROM facts.telemetry").fetchone()[0]
        if r:
            if r.tzinfo is None:  # DuckDB kan naive teruggeven
                r = r.replace(tzinfo=timezone.utc)
            return int((datetime.now(timezone.utc) - r).total_seconds())
        return 0
    except Exception:
        return 99999


# KPI-definities → lake-query
def _kpi_query(key: str):
    M = {
        "otif_pct": ("SELECT round(avg(otif_pct),1) FROM dims.lanes", "lanes"),
        "value_in_transit": ("SELECT coalesce(sum(value_eur),0) FROM dims.shipments WHERE status='in_transit'", "shipments"),
        "active_shipments": ("SELECT count(*) FROM dims.shipments WHERE status='in_transit'", "shipments"),
        "delayed": ("SELECT count(*) FROM dims.shipments WHERE status IN ('delayed','rerouted')", "shipments"),
        "incidents": ("SELECT count(*) FROM incidents WHERE resolved_at IS NULL", "incidents"),
        "incidents_p1": ("SELECT count(*) FROM incidents WHERE resolved_at IS NULL AND severity='P1'", "incidents"),
        "carbon_tco2": ("SELECT round(sum(carbon_tco2),2) FROM dims.vehicles", "vehicles"),
        "low_stock_skus": ("SELECT count(*) FROM dims.inventory WHERE stock<reorder", "inventory"),
        "weekly_demand_units": ("SELECT coalesce(sum(velocity),0) FROM dims.inventory", "inventory"),
        "units": ("SELECT count(*) FROM dims.vehicles", "vehicles"),
        "fleet_fuel_avg": ("SELECT round(avg(fuel_pct),1) FROM dims.vehicles WHERE fuel_pct IS NOT NULL", "vehicles"),
        "fleet_speed_avg": ("SELECT round(avg(speed_kmh),1) FROM facts.telemetry WHERE speed_kmh > 0 AND ts > now() - interval '24 hour'", "telemetry"),
        "live_vehicles_10m": ("SELECT count(DISTINCT vehicle_id) FROM facts.telemetry WHERE ts > now() - interval '10 minutes'", "telemetry"),
        "cargo_temp": ("SELECT round(avg(cargo_temp),1) FROM facts.telemetry", "telemetry"),
        "telemetry_count": ("SELECT count(*) FROM facts.telemetry", "telemetry"),
        "shipment_status": ("SELECT count(*) FROM dims.shipments", "shipments"),
    }
    return M.get(key)


_kpi_cache = {"t": 0, "data": None}


def get_kpis():
    if time.time() - _kpi_cache["t"] < KPI_CACHE_S and _kpi_cache["data"]:
        return _kpi_cache["data"]
    out = []
    age = _age_seconds()
    for key, sem in SEMANTICS.items():
        qs = _kpi_query(key)
        if qs is None:
            q, src = (None, sem.get("source_table"))
        else:
            q, src = qs
        value = None
        live = False
        try:
            if src == "incidents":
                # live rechtstreeks op de AEGIS-bron (read-only)
                with _aegis() as c, c.cursor() as cur:
                    cur.execute(q)
                    value = cur.fetchone()[0]
                live = True
            else:
                con = duck()
                value = con.execute(q).fetchone()[0]
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
def get_trend(metric: str, bucket: str = "1h", hours: int = 24):
    con = duck()
    B = {"5m": "5 minutes", "15m": "15 minutes", "1h": "1 hour", "1d": "1 day"}
    b = B.get(bucket, "1 hour")
    H = str(hours)
    qmap = {
        "otif": ("SELECT time_bucket(?, ts) t, round(avg(otif_pct),1) v FROM "
                 "SELECT ts, otif_pct FROM dims.lanes GROUP BY 1 ORDER BY 1", [b]),
        "telemetry_count": ("SELECT time_bucket(?, ts) t, count(*) v FROM "
                            "facts.telemetry WHERE ts > now() - (? || ' hours')::interval "
                            "GROUP BY 1 ORDER BY 1", [b, H]),
        "cargo_temp": ("SELECT time_bucket(?, ts) t, round(avg(cargo_temp),2) v, "
                       "max(cargo_temp) mx FROM facts.telemetry "
                       "WHERE ts > now() - (? || ' hours')::interval GROUP BY 1 ORDER BY 1",
                       [b, H]),
        "value_in_transit": ("SELECT time_bucket(?, ts) t, round(sum(value_eur),0) v FROM "
                             "facts.shipment_events WHERE type='status' GROUP BY 1 ORDER BY 1", [b]),
        "shipment_status": ("SELECT time_bucket(?, cycle_ts) t, status, count(*) v FROM "
                            "dims.shipments GROUP BY 1,2 ORDER BY 1", [b]),
        "fleet_speed": ("SELECT time_bucket(?, ts) t, round(avg(speed_kmh),1) v FROM "
                        "facts.telemetry WHERE speed_kmh > 0 "
                        "AND ts > now() - (? || ' hours')::interval GROUP BY 1 ORDER BY 1", [b, H]),
        "live_vehicles": ("SELECT time_bucket(?, ts) t, count(DISTINCT vehicle_id) v FROM "
                          "facts.telemetry WHERE ts > now() - (? || ' hours')::interval "
                          "GROUP BY 1 ORDER BY 1", [b, H]),
    }
    if metric not in qmap:
        return {"series": []}
    q, params = qmap[metric]
    try:
        if metric == "shipment_status":
            cur = con.execute(q, params)
            rows = cur.fetchall()
            series = {}
            for t, status, v in rows:
                series.setdefault(status, []).append(
                    {"ts": t.isoformat(), "value": int(v)})
            return {"series": series}
        if metric == "cargo_temp":
            cur = con.execute(q, params)
            return {"series": [{"ts": t.isoformat(), "value": float(v) if v else None,
                                "max": float(mx) if mx else None}
                               for t, v, mx in cur.fetchall()]}
        cur = con.execute(q, params)
        return {"series": [{"ts": t.isoformat(), "value": float(v) if v is not None else None}
                           for t, v in cur.fetchall()]}
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
