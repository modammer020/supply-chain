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


@app.get("/api/engineer/items")
def engineer_items(status: str = None):
    return engineer_api.list_items(status)


@app.get("/api/engineer/items/{item_id}")
def engineer_item(item_id: str):
    it = engineer_api.get_item(item_id)
    return it or {"error": "niet gevonden"}


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
    # Zelfde app op beide poorten: :8402 = UI + API (één origineel, geen
    # CORS; de frontend probeert /api/status op location.origin eerst).
    # :8401 blijft het 'pure API'-origineel voor koppelingen/monitoring.
    def run_ui():
        uvicorn.run(app, host="0.0.0.0", port=8402, log_level="warning")

    threading.Thread(target=run_ui, daemon=True).start()
    uvicorn.run(app, host="0.0.0.0", port=8401, log_level="warning")


if __name__ == "__main__":
    main()
