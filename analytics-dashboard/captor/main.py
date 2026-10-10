"""Captor FastAPI app: /health + POST /manual/poll (FR-001/FR-002)."""
from fastapi import FastAPI, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from captor.config import POLL_INTERVAL_S
from captor.poller import captor

app = FastAPI(title="AEGIS Analytics Captor", version="0.1.0")


@app.on_event("startup")
def _startup():
    captor.start_loop(POLL_INTERVAL_S)


@app.get("/health")
def health():
    return captor.health()


@app.get("/metrics")
def metrics():
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/manual/poll")
def manual_poll():
    res = captor.run_cycle("manual")
    if res["status"] == "409":
        return Response(status_code=409, content='{"error":"cycle_active"}')
    if not captor.health()["source_reachable"]:
        return Response(status_code=503, content='{"error":"source_unreachable"}')
    return res
