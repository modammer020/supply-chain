"""Predictive & recommendation engine (FR-101, 102, 103, 106).

Deterministisch + uitlegbaar (defensie-demo): geen ML-runtime, geen API's.
Scoring per component op health/wear/rul_days/next_service; kosten-impact via
component catalog (parts/specs.yaml); cross-link with active shipments (IT).
Cache: 60s. Lege-states → lege lijsten + status, nooit fout.
"""
import os
import time
import yaml
import threading
from datetime import datetime, timezone

from dashboard.api_core import duck

PARTS_PATH = os.path.join(os.path.dirname(__file__), "..", "parts", "specs.yaml")
CACHE_S = 60

# ── catalog ────────────────────────────────────────────────────
with open(PARTS_PATH) as f:
    _CAT = yaml.safe_load(f)
_PARTS = _CAT["parts"]
_FMT = _CAT["catalog"]["part_number_format"]


def _match_part(name: str):
    for p in _PARTS:
        for m in p.get("matches", []):
            if m.lower() in str(name).lower() or str(name).lower() in m.lower():
                return p
    # fallback: op kind/naam-stam
    return _PARTS[-1]


def part_for(component: dict) -> dict:
    p = _match_part(component.get("name") or component.get("component") or "")
    return {
        "part_number": p["part_number"], "name": p["name"],
        "supplier": p["supplier"], "lead_time_days": p["lead_time_days"],
        "price_eur": p["price_eur"], "specs": p["specs"],
    }


# ── scoring ────────────────────────────────────────────────────
# health 0-100 (hoog=goei), wear 0-100 (hoog=slecht), rul_days (laag=riskant)
def component_score(c: dict) -> float:
    """0 = vervangen nu, 100 = gezond. Deterministische gewogen som."""
    health = float(c.get("health") or 50)
    wear = float(c.get("wear") or 50)
    rul = float(c.get("rul_days") or 365)
    rul_norm = max(0.0, min(1.0, rul / 365.0))          # <365d → 0..1
    return round(0.45 * health + 0.25 * (100 - wear) + 0.30 * (100 * rul_norm), 1)


def _status(c: dict) -> str:
    s = c.get("status")
    if s in ("ok", "warning", "critical"):
        return s
    score = component_score(c)
    return "critical" if score < 35 else "warning" if score < 60 else "ok"


def _next_service_days(c: dict) -> int:
    try:
        ns = datetime.fromisoformat(str(c["next_service"]).split()[0])
        return (ns - datetime.now(timezone.utc).replace(tzinfo=None)).days
    except Exception:
        return int(c.get("rul_days") or 999)


# ── engine (gecacheerd) ────────────────────────────────────────
_lock = threading.Lock()
_cache = {"t": 0, "data": None}


def _active_shipments_by_vehicle():
    con = duck()
    try:
        cur = con.execute(
            "SELECT vehicle_id, count(*) n, round(sum(value_eur),0) v "
            "FROM dims.shipments WHERE status IN ('in_transit','delayed','rerouted') "
            "GROUP BY vehicle_id")
        return {r[0]: {"active": int(r[1]), "value_eur": float(r[2] or 0)} for r in cur.fetchall()}
    except Exception:
        return {}


def compute(force=False):
    with _lock:
        if not force and _cache["data"] and time.time() - _cache["t"] < CACHE_S:
            return _cache["data"]
        try:
            con = duck()
            cur = con.execute(
                "SELECT c.vehicle_id, c.name, c.wear, c.health, c.km, "
                "c.last_service, c.next_service, c.status, c.rul_days, c.est_cost, "
                "v.kind, v.name AS vname "
                "FROM dims.components c LEFT JOIN dims.vehicles v ON v.id = c.vehicle_id")
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description]
            comps = [dict(zip(cols, r)) for r in rows]
        except Exception as e:
            comps = []
            err = str(e)[:120]
        active = _active_shipments_by_vehicle() if comps else {}
        items = []
        for c in comps:
            c = {**c, "status_norm": _status(c)}
            part = part_for(c)
            score = component_score(c)
            nsd = _next_service_days(c)
            imp = active.get(c["vehicle_id"], {})
            items.append({
                "vehicle_id": c["vehicle_id"], "vehicle_name": c.get("vname"),
                "vehicle_kind": c.get("kind"), "component": c["name"],
                "score": score, "status": c["status_norm"],
                "health": c.get("health"), "wear": c.get("wear"),
                "rul_days": c.get("rul_days"), "next_service_days": nsd,
                "km": c.get("km"),
                "est_cost_eur": c.get("est_cost"),
                "part": part,
                "active_shipments": imp.get("active", 0),
                "value_at_risk_eur": imp.get("value_eur", 0),
            })
        # ranking: slechtste eerst; binnen die: RUL + waarde-op-stekers
        items.sort(key=lambda x: (x["score"], x["rul_days"] or 999, -x["value_at_risk_eur"]))
        top = items[:10]
        critical = [i for i in items if i["status"] == "critical"]
        warning = [i for i in items if i["status"] == "warning"]
        # recommendation: P1 = critical op actief voertuig of rul<30
        recs = []
        for i in top:
            if i["status"] == "critical" and (i["active_shipments"] > 0 or (i["rul_days"] or 999) < 30):
                sev = "P1"
            elif i["status"] == "critical":
                sev = "P2"
            elif i["rul_days"] and i["rul_days"] < 60:
                sev = "P3"
            else:
                continue
            recs.append({
                "severity": sev,
                "vehicle_id": i["vehicle_id"],
                "vehicle": f'{i["vehicle_name"] or i["vehicle_id"]} ({i["vehicle_kind"]})',
                "component": i["component"],
                "action": f'Replace "{i["component"]}" (part {i["part"]["part_number"]}) on {i["vehicle_id"]}',
                "why": (f'score={i["score"]} · health={i["health"]} · wear={i["wear"]} · '
                        f'RUL={i["rul_days"]}d · next_service={i["next_service_days"]}d'),
                "impact": (f'{i["active_shipments"]} active shipments '
                           f'(€{i["value_at_risk_eur"]:,.0f} at risk)' if i["active_shipments"]
                           else "no active shipment — schedule during downtime"),
                "cost_eur": i["est_cost_eur"], "lead_time_days": i["part"]["lead_time_days"],
            })
        # fleet-health-score (OT) = gemiddelde component-score
        fleet_health = round(sum(i["score"] for i in items) / len(items), 1) if items else None
        data = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "fleet_health": fleet_health,
            "components_total": len(items),
            "critical": len(critical), "warning": len(warning),
            "top_replace": top,
            "recommendations": recs[:8],
            "source": "SIM (dims.components + demo catalog)",
            "error": locals().get("err"),
        }
        _cache.update({"t": time.time(), "data": data})
        return data


# ── supervisor summary (FR-106) ────────────────────────────────
def supervisor_summary(shift_h: int = 24):
    d = compute()
    con = duck()
    out = {"shift_hours": shift_h, "generated_at": d["ts"], "kpi": {}, "actions": d["recommendations"][:5],
           "fleet": {"health": d["fleet_health"], "critical": d["critical"], "warning": d["warning"]},
           "incidents": [], "status_changes": []}
    try:
        out["kpi"]["otif_pct"] = con.execute("SELECT round(avg(otif_pct),1) FROM dims.lanes").fetchone()[0]
        out["kpi"]["value_in_transit_eur"] = int(con.execute(
            "SELECT coalesce(sum(value_eur),0) FROM dims.shipments WHERE status='in_transit'").fetchone()[0])
        out["kpi"]["delayed"] = int(con.execute(
            "SELECT count(*) FROM dims.shipments WHERE status IN ('delayed','rerouted')").fetchone()[0])
    except Exception:
        pass
    try:
        from dashboard.api_core import _aegis
        with _aegis() as c, c.cursor() as cur:
            cur.execute("SELECT i.id, i.kind, i.severity, i.title, i.affected_vehicle, i.created_at "
                        "FROM incidents i "
                        "WHERE i.created_at > now() - (%s * interval '1 hour') "
                        "ORDER BY i.created_at DESC LIMIT 20", (shift_h,))
            out["incidents"] = [{"id": r[0], "kind": r[1], "severity": r[2], "title": r[3],
                                 "vehicle": r[4], "at": str(r[5])} for r in cur.fetchall()]
    except Exception:
        # fallback: incidenten via shipment-events in lake
        try:
            cur = con.execute("SELECT note, captured_at FROM facts.shipment_events WHERE type='status' "
                              "AND note ILIKE '%incident%' ORDER BY captured_at DESC LIMIT 10")
            out["incidents"] = [{"title": r[0], "at": str(r[1])} for r in cur.fetchall()]
        except Exception:
            pass
    return out
