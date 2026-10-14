"""Dashboard main: FastAPI :8401 + static frontend :8402 (FR-007..011)."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn
from prometheus_client import make_asgi_app

import dashboard.api_core as core
from dashboard import engine, dossier, engineer_api, topology

app = FastAPI(title="AEGIS Analytics Dashboard", version="0.2.0")
app.mount("/metrics", make_asgi_app())


@app.get("/api/kpi")
def kpi():
    return {"as_of": _now_iso(), "kpis": core.get_kpis()}


def _now_iso():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


@app.get("/api/trends/{metric}")
def trends(metric: str, bucket: str = "1h", hours: int = 24):
    return core.get_trend(metric, bucket, min(hours, 168))


@app.get("/api/incidents")
def incidents(limit: int = 50):
    return core.get_incidents(limit)


@app.get("/api/lineage/{card}")
def lineage(card: str):
    return core.get_lineage(card)


@app.get("/api/quality/quarantine")
def quarantine(topic: str = None, limit: int = 50):
    return core.get_quarantine(topic, limit)


@app.get("/api/status")
def status():
    return core.get_status()


@app.get("/api/semantics")
def semantics():
    return core.SEMANTICS


# ── spec 003: OT/IT-convergentie, predictive, dossiers ──────────
@app.get("/api/fleet-health")
def fleet_health(top: int = 10):
    d = engine.compute()
    return {**d, "top_replace": d["top_replace"][:top]}


@app.get("/api/recommendations")
def recommendations():
    d = engine.compute()
    return {"recommendations": d["recommendations"], "ts": d["ts"]}


@app.get("/api/supervisor/summary")
def supervisor(shift: int = 24):
    return engine.supervisor_summary(min(shift, 72))


@app.get("/api/vehicle/{vid}/dossier")
def vehicle_dossier(vid: str):
    from fastapi.responses import HTMLResponse
    return HTMLResponse(dossier.dossier_html(vid))


@app.get("/api/vehicle/{vid}/dossier.pdf")
def vehicle_dossier_pdf(vid: str):
    from fastapi.responses import Response
    return Response(content=dossier.dossier_pdf(vid),
                    media_type="application/pdf",
                    headers={"Content-Disposition": f"attachment; filename=dossier-{vid}.pdf"})


# ── spec 003: data-engineer review-laag (FR-107) ────────────────
@app.get("/api/topology")
def topology_live():
    return topology.get_topology()


@app.get("/api/context/tables")
def context_tables():
    return topology.get_context_tables()


# ── command-center sync (live reads from :8300 + lake) ──────────
# The analytics platform is the "data + analysis" layer; the operational
# command center (aegis, :8300) owns the live operational feeds (traffic
# index, predictions, live air/ships, per-lane conditions). These proxies
# keep the analytics dashboard IN SYNC with the command center so a single
# screen shows operations + analysis side by side.
import urllib.request
import json as _json

CC_HOST = os.environ.get("CC_HOST", "host.containers.internal")
CC_PORT = os.environ.get("CC_PORT", "8300")


def _cc_get(path: str, timeout: int = 6):
    """Read-only proxy into the operational command center (:8300)."""
    url = f"http://{CC_HOST}:{CC_PORT}{path}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return _json.loads(r.read().decode("utf-8", "replace"))
    except Exception as e:
        return {"error": str(e)[:140], "live": False, "source": "aegis:8300"}


@app.get("/api/network/traffic")
def cc_traffic():
    d = _cc_get("/api/traffic")
    d["source"] = d.get("source", "aegis:8300")
    return d


@app.get("/api/network/conditions")
def cc_conditions(bbox: str = "2,48,22,60"):
    # CC exposes /api/conditions with bbox as a QUERY param (not path segment)
    return _cc_get(f"/api/conditions?bbox={bbox}", timeout=10)


@app.get("/api/network/air")
def cc_air():
    return _cc_get("/api/air", timeout=10)


@app.get("/api/network/ships")
def cc_ships():
    return _cc_get("/api/ships", timeout=10)


@app.get("/api/network/predictions")
def cc_predictions():
    return _cc_get("/api/predictions", timeout=10)


@app.get("/api/network/stats")
def cc_stats():
    return _cc_get("/api/stats")


@app.get("/api/network/reroutes")
def cc_reroutes():
    """Total reroutes / delays straight off the AEGIS source (read-only)."""
    try:
        con = core._aegis()
        with con.cursor() as cur:
            cur.execute("SELECT status, count(*) FROM shipments GROUP BY status")
            by_status = {r[0]: int(r[1]) for r in cur.fetchall()}
            cur.execute("""
                SELECT s.id, s.vehicle_id, s.status, s.lane_id,
                       l.origin, l.destination, round((s.value_eur/1000)::numeric,0) k_eur
                FROM shipments s
                LEFT JOIN lanes l ON l.id = s.lane_id
                WHERE s.status IN ('rerouted','delayed')
                ORDER BY s.value_eur DESC LIMIT 50""")
            rows = [dict(zip([d[0] for d in cur.description], r)) for r in cur.fetchall()]
        total_rerouted = by_status.get("rerouted", 0)
        total_delayed = by_status.get("delayed", 0)
        return {
            "live": True,
            "source": "aegis_db (read-only)",
            "by_status": by_status,
            "total_reroutes": total_rerouted,
            "total_delays": total_delayed,
            "total_disrupted": total_rerouted + total_delayed,
            "items": rows,
        }
    except Exception as e:
        return {"error": str(e)[:140], "live": False, "items": []}


@app.get("/api/engineer/items")
def engineer_items(status: str = None):
    return engineer_api.list_items(status)


@app.get("/api/engineer/items/{item_id}")
def engineer_item(item_id: str):
    it = engineer_api.get_item(item_id)
    return it or {"error": "not found"}


@app.post("/api/engineer/items/{item_id}/review")
def engineer_review(item_id: str, status: str, by: str = "operator"):
    return engineer_api.review(item_id, status, by)


# ── static frontend ────────────────────────────────────────────
WEB = os.path.join(os.path.dirname(__file__), "web")


@app.get("/")
def index():
    return FileResponse(os.path.join(WEB, "index.html"))


@app.get("/{path:path}")
def spa(path: str):
    p = os.path.join(WEB, path)
    if os.path.isfile(p):
        return FileResponse(p)
    return FileResponse(os.path.join(WEB, "index.html"))


def main():
    import threading
    # Same app on both ports: :8402 = UI + API (single origin, no CORS;
    # the frontend probes /api/status on location.origin first).
    # :8401 stays the 'pure API' origin for integrations/monitoring.

    def warmup():
        # Primi de shared state zodat de EERSTE user-request warm is:
        # KPI-cache (psycopg2 op aegis_db), context-cache (DuckDB-attach +
        # MinIO-connectie) en de engine (fleet-health). Draait in de
        # achtergrond, geen impact op de startup-tijd zelf.
        try:
            core.get_kpis()
        except Exception:
            pass
        try:
            topology.get_context_tables()
        except Exception:
            pass
        try:
            from dashboard import engine as _engine
            _engine.compute()
        except Exception:
            pass

    threading.Thread(target=warmup, daemon=True, name="startup-warmup").start()

    def run_ui():
        uvicorn.run(app, host="0.0.0.0", port=8402, log_level="warning")

    threading.Thread(target=run_ui, daemon=True).start()
    uvicorn.run(app, host="0.0.0.0", port=8401, log_level="warning")


if __name__ == "__main__":
    main()
