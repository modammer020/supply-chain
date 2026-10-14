"""AEGIS command-center API — PostGIS + OSRM routing + incident simulation."""
import os, math, time, json, shutil, subprocess, asyncio
from datetime import datetime, timezone
from typing import Optional
import psycopg2
import psycopg2.extras
import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

DB = dict(
    host=os.environ.get("DB_HOST", "127.0.0.1"),
    port=int(os.environ.get("DB_PORT", "5433")),
    dbname="aegis", user="aegis", password="aegis_dev",
)
OSRM = "https://router.project-osrm.org/route/v1/driving"
OSRM_TIMEOUT = 18

app = FastAPI(title="AEGIS API", version="3.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def db():
    c = psycopg2.connect(**DB)
    return c


# ── OSRM polyline (Polyline6) decoder ──
def _decode_polyline(p):
    """Decode Google Polyline6 (as used by OSRM). p: str -> list of [lon, lat]."""
    pts, i = [], 0
    lat = lng = 0
    while i < len(p):
        # lat component (Polyline6: each byte is offset by 63)
        result, shift = 0, 0
        while True:
            b = ord(p[i]) - 63; i += 1
            result |= (b & 0x1F) << shift
            shift += 5
            if not (b & 0x20): break
        result = ~(result >> 1) if (result & 1) else (result >> 1)
        lat += result
        # lng component
        result, shift = 0, 0
        while True:
            b = ord(p[i]) - 63; i += 1
            result |= (b & 0x1F) << shift
            shift += 5
            if not (b & 0x20): break
        result = ~(result >> 1) if (result & 1) else (result >> 1)
        lng += result
        pts.append([lng / 1e5, lat / 1e5])
    return pts


def _wkt(points):
    # points: list of [lon, lat]
    return "LINESTRING(" + ",".join(f"{lo} {la}" for lo, la in points) + ")"


def _geojson_line(points):
    return {"type": "LineString", "coordinates": [[lo, la] for lo, la in points]}


async def fetch_osrm(ola1, olo1, olat2, olo2, alternatives=2):
    """Fetch up to `alternatives+1` routes. Returns list of {points, km, min}."""
    url = f"{OSRM}/{olo1},{ola1};{olo2},{olat2}?alternatives={alternatives}&overview=full&geometries=polyline"
    async with httpx.AsyncClient(timeout=OSRM_TIMEOUT) as c:
        r = await c.get(url)
        r.raise_for_status()
        j = r.json()
    out = []
    for rt in j.get("routes", []):
        pts = _decode_polyline(rt["geometry"])
        if not pts: continue
        out.append({"points": pts, "km": rt["distance"]/1000.0, "min": rt["duration"]/60.0})
    return out


# ════════════════ READ ENDPOINTS ════════════════
@app.get("/api/health")
def health():
    try:
        with db() as c, c.cursor() as cur:
            cur.execute("SELECT count(*) FROM vehicles")
            n = cur.fetchone()[0]
        return {"ok": True, "vehicles": n}
    except Exception as e:
        raise HTTPException(500, f"db: {e}")


@app.get("/api/locations")
def locations():
    with db() as c, c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM locations ORDER BY kind, name")
        return [dict(r) for r in cur.fetchall()]


@app.get("/api/lanes")
def lanes():
    with db() as c, c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT l.*, o.name AS origin_name, d.name AS dest_name,
                   o.lat olat, o.lng olng, d.lat dlat, d.lng dlng,
                   (SELECT count(*) FROM shipments s WHERE s.lane_id=l.id AND s.status='in_transit') AS active
            FROM lanes l JOIN locations o ON o.id=l.origin JOIN locations d ON d.id=l.destination
            ORDER BY l.otif_pct""")
        return [dict(r) for r in cur.fetchall()]


@app.get("/api/vehicles")
def vehicles():
    with db() as c, c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT v.*, s.id AS shipment_id, s.cargo, s.qty, s.value_eur, s.customer,
                   s.status, s.eta_minutes, s.sla_minutes, s.temp_req, s.customs,
                   l.id AS lane_id, l.freeflow_min, l.distance_km,
                   d.full_name AS driver_name, d.dob, d.nationality, d.license,
                   d.license_expiry, d.phone AS driver_phone, d.email AS driver_email,
                   d.years_exp, d.rating, d.trips, d.base AS driver_base, d.avatar
            FROM vehicles v
            LEFT JOIN shipments s ON s.vehicle_id=v.id
            LEFT JOIN lanes l ON l.id=s.lane_id
            LEFT JOIN drivers d ON d.vehicle_id=v.id""")
        return [dict(r) for r in cur.fetchall()]


@app.get("/api/shipments")
def shipments():
    with db() as c, c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT s.*, v.name vname, v.kind, v.driver, l.origin, l.destination, l.distance_km, l.freeflow_min
            FROM shipments s JOIN vehicles v ON v.id=s.vehicle_id JOIN lanes l ON l.id=s.lane_id
            ORDER BY (s.eta_minutes - s.sla_minutes)""")
        rows = [dict(r) for r in cur.fetchall()]
        cur.execute("SELECT * FROM shipment_events ORDER BY shipment_id, ts")
        evs = {}
        for e in cur.fetchall():
            evs.setdefault(e["shipment_id"], []).append(e)
        for r in rows:
            r["events"] = evs.get(r["id"], [])
            r["docs"] = [
                {"type": "PO", "status": "Confirmed", "ref": "PO-" + r["id"][-4:]},
                {"type": "ASN", "status": "Sent", "ref": "ASN-" + r["id"][-4:]},
                {"type": "BOL", "status": "Issued", "ref": "BOL-" + r["id"][-4:]},
                {"type": "Customs", "status": r.get("customs") or "Pending", "ref": "CUS-" + r["id"][-4:]},
            ]
        return rows


@app.get("/api/telemetry/{vehicle_id}")
def telemetry(vehicle_id: str, limit: int = Query(30, le=240)):
    with db() as c, c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM telemetry WHERE vehicle_id=%s ORDER BY ts DESC LIMIT %s",
                    (vehicle_id, limit))
        rows = [dict(r) for r in cur.fetchall()]
    rows.reverse()
    return {"vehicle_id": vehicle_id, "points": rows}


@app.get("/api/inventory")
def inventory():
    with db() as c, c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT i.*, l.name hub_name FROM inventory i JOIN locations l ON l.id=i.hub_id
            ORDER BY (i.stock - i.reorder)""")
        return [dict(r) for r in cur.fetchall()]


# ── KPI wall ──
@app.get("/api/kpi")
def kpi():
    with db() as c, c.cursor() as cur:
        cur.execute("SELECT count(*) FROM vehicles"); n_v = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM vehicles WHERE kind='truck'"); n_t = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM vehicles WHERE kind='ship'"); n_s = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM vehicles WHERE kind='plane'"); n_p = cur.fetchone()[0]
        cur.execute("SELECT coalesce(sum(value_eur),0) FROM shipments WHERE status='in_transit'"); val = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM shipments WHERE status='in_transit'"); n_ship = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM shipments WHERE status IN ('delayed','rerouted')"); n_delay = cur.fetchone()[0]
        cur.execute("SELECT round(avg(otif_pct),1) FROM lanes"); otif = cur.fetchone()[0]
        cur.execute("SELECT round(sum(carbon_tco2)::numeric,2) FROM vehicles"); carbon = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM incidents WHERE resolved_at IS NULL"); n_inc = cur.fetchone()[0]
        cur.execute("SELECT coalesce(sum(velocity),0) FROM inventory"); demand = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM inventory WHERE stock<reorder"); low_stock = cur.fetchone()[0]
    return {
        "units": n_v, "trucks": n_t, "ships": n_s, "planes": n_p,
        "value_in_transit": val, "active_shipments": n_ship, "delayed": n_delay,
        "otif_pct": otif, "carbon_tco2": carbon, "incidents": n_inc,
        "low_stock_skus": low_stock, "weekly_demand_units": round(demand,0)
    }


# ── CHAT WITH THE AGENT (hermes researcher bot) ─────────────────────
HERMES_BIN = os.path.expanduser("~/.local/bin/hermes")
if not os.path.exists(HERMES_BIN):
    HERMES_BIN = shutil.which("hermes") or "hermes"
CHAT_HISTORY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "chat_history.jsonl")
CHAT_TIMEOUT = 180


def _chat_context():
    """Compact live snapshot for the chat agent (DB + disk, no self-HTTP calls:
    uvicorn is single-worker and the agent subprocess blocks the event loop,
    so any self-call would deadlock/timeout)."""
    ctx = {}
    # last analysis cycle — read the file directly (the watcher appends to it)
    try:
        import pathlib
        f = pathlib.Path(__file__).parent / "data" / "insights.jsonl"
        if f.exists():
            line = [l for l in f.read_text().splitlines() if l.strip()][-1]
            last = json.loads(line)
            i = last.get("insight") or {}
            if i:
                ctx["last_cycle"] = {
                    "ts": (last.get("ts") or "")[:19],
                    "summary": i.get("summary"),
                    "risks": i.get("risks", [])[:4],
                    "recommendations": [r.get("action") if isinstance(r, dict) else r
                                        for r in i.get("recommendations", [])[:5]],
                }
    except Exception as e:
        ctx["last_cycle_note"] = f"unavailable: {e}"
    try:
        with db() as c, c.cursor() as cur:
            cur.execute("SELECT coalesce(round(avg(otif_pct),1),0) FROM lanes"); otif = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM vehicles"); n_v = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM shipments WHERE status='in_transit'"); n_tr = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM incidents WHERE resolved_at IS NULL"); n_inc = cur.fetchone()[0]
            cur.execute("""
                SELECT id FROM incidents WHERE resolved_at IS NULL LIMIT 5""")
            inc = [str(r[0]) for r in cur.fetchall()]
            cur.execute("""
                SELECT s.id, s.vehicle_id, s.status, lo.name, ld.name,
                       round((s.value_eur/1000)::numeric,0) k
                FROM shipments s
                JOIN lanes l ON l.id = s.lane_id
                JOIN locations lo ON lo.id = l.origin
                JOIN locations ld ON ld.id = l.destination
                WHERE s.status IN ('delayed','rerouted','in_transit')
                ORDER BY s.value_eur DESC LIMIT 10""")
            risky = [{"id": r[0], "vehicle": r[1], "status": r[2],
                      "route": f"{r[3]}→{r[4]}", "value_k_eur": int(r[5] or 0)} for r in cur.fetchall()]
        ctx["kpi"] = {"otif_pct": float(otif or 0), "units": n_v, "active_shipments": n_tr, "incidents_open": n_inc}
        ctx["open_incidents"] = inc
        ctx["top_shipments"] = risky
    except Exception as e:
        ctx["db_note"] = f"unavailable: {e}"
    return ctx


def _chat_replies():
    try:
        with open(CHAT_HISTORY) as f:
            lines = [json.loads(l) for l in f if l.strip()]
    except FileNotFoundError:
        return []
    return [
        {"role": "user" if x.get("role") == "user" else "agent", "text": x["text"]}
        for x in lines if x.get("text") and len(x.get("text", "")) < 4000
    ][-8:]


@app.post("/api/chat")
def chat_agent(payload: dict):
    """Direct chat with the AEGIS-ANALYST (hermes researcher bot).
    Body: {"message": "..."}  →  {"ok":true,"reply":"...","agent":"hermes:researcher","ms":...}
    The agent answers grounded in the CURRENT live API state + last analysis cycle.
    """
    msg = (payload.get("message") or "").strip()
    if not msg or len(msg) > 2000:
        raise HTTPException(400, "message must be 1..2000 chars")
    if HERMES_BIN == "hermes" and not shutil.which("hermes"):
        return JSONResponse({"ok": False, "error": "hermes CLI not found on this host"}, status_code=503)
    try:
        ctx = _chat_context()
    except Exception as e:
        ctx = {"note": f"context unavailable: {e}"}
    prev = _chat_replies()
    hist = "\n".join(f"{'USER' if x['role']=='user' else 'AGENT'}: {x['text'][:800]}" for x in prev) or "(none)"
    prompt = (
        "You are AEGIS-ANALYST, the standing supply-chain analyst inside the AEGIS control center UI. "
        "A dispatcher is chatting with you in real time. Answer their question CONCRETELY using the "
        "live operational context below (cite lane/vehicle/shipment ids). Keep answers short (3-8 sentences "
        "or a compact bullet list). ALWAYS answer in English, even if the user writes in another language. "
        "If you recommend action, give the exact target id and expected effect. "
        "You may note that data is a simulation. "
        "NO preamble, no markdown fences.\n\n"
        f"RECENT CHAT:\n{hist}\n\n"
        f"LIVE CONTEXT (UTC now, fetched from the AEGIS API):\n{json.dumps(ctx, ensure_ascii=False, indent=1)}\n\n"
        f"USER MESSAGE: {msg}"
    )
    t0 = time.time()
    try:
        p = subprocess.run([HERMES_BIN, "-p", "researcher", "chat", "-q", prompt,
                            "--oneshot", "-Q", "--max-turns", "3"],
                           capture_output=True, text=True, timeout=CHAT_TIMEOUT, cwd=os.path.dirname(os.path.abspath(__file__)))
        out = (p.stdout or "").strip()
        payload_txt = "\n".join(l for l in out.splitlines() if not l.startswith("session_id")).strip()
        if not payload_txt:
            payload_txt = (p.stderr or "agent returned no output").strip()[:500]
        reply = payload_txt
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "agent timed out — try again", "ms": int((time.time()-t0)*1000)}
    except Exception as e:
        return {"ok": False, "error": f"agent invocation failed: {e}", "ms": int((time.time()-t0)*1000)}
    # persist to shared history
    try:
        os.makedirs(os.path.dirname(CHAT_HISTORY), exist_ok=True)
        with open(CHAT_HISTORY, "a") as f:
            f.write(json.dumps({"ts": time.time(), "role": "user", "text": msg}) + "\n")
            f.write(json.dumps({"ts": time.time(), "role": "agent", "text": reply[:4000]}) + "\n")
    except Exception:
        pass
    return {"ok": True, "reply": reply, "agent": "hermes:researcher", "ms": int((time.time()-t0)*1000)}


# ── WORLD LIVE EVENTS (keyless: NASA EONET + USGS) ──────────────────
# Real, globally-located data points: natural & man-made events + quakes.
_EONET_URL = "https://eonet.gsfc.nasa.gov/api/v3/events"
_USGS_URL = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson"
_WORLDCACHE_TTL = 900  # 15 min

async def _world_events():
    cached = await _kv_get("world_events")
    if cached:
        return {**cached, "source": "CACHED"}
    events = []
    # 1) NASA EONET — open, globally located natural/manmade events
    try:
        async with httpx.AsyncClient(timeout=12) as hc:
            r = await hc.get(_EONET_URL, params={"status": "open", "limit": 60})
            r.raise_for_status()
            j = r.json()
        for e in j.get("events", []):
            geo = e.get("geometry") or []
            if not geo:
                continue
            g0 = geo[0]
            coords = g0.get("coordinates") if isinstance(g0, dict) else None
            if coords:
                lng, lat = coords[0], coords[1]
            elif isinstance(g0, (list, tuple)) and len(g0) >= 2:
                lng, lat = g0[0], g0[1]
            else:
                continue
            cats = [(cc.get("id"), cc.get("title")) for cc in e.get("categories", [])]
            mag = None
            if isinstance(g0, dict) and g0.get("magnitudeValue") is not None:
                mag = g0.get("magnitudeValue")
            events.append({
                "id": e.get("id"), "type": "eonet",
                "title": e.get("title") or "event",
                "lat": lat, "lng": lng,
                "cat": (cats[0][1] if cats else "event"),
                "cat_id": (cats[0][0] if cats else None),
                "mag": mag,
                "ts": (g0.get("date") if isinstance(g0, dict) else "") or (e.get("sources") or [{}])[0].get("id", ""),
                "link": e.get("link"),
            })
    except Exception:
        pass
    # 2) USGS earthquakes — open, globally located, mag 2.5+ past day
    try:
        async with httpx.AsyncClient(timeout=12) as hc:
            r = await hc.get(_USGS_URL)
            r.raise_for_status()
            j = r.json()
        for f in j.get("features", []):
            p = f.get("properties", {})
            c = (f.get("geometry") or {}).get("coordinates")
            if not c:
                continue
            mag = p.get("mag")
            if mag is None or mag < 3.0:
                continue
            events.append({
                "id": p.get("id"), "type": "quake",
                "title": f"M{mag} {p.get('place','earthquake')}",
                "mag": mag,
                "lat": c[1], "lng": c[0],
                "cat": f"Quake M{mag}",
                "cat_id": "earthquakes",
                "ts": time.strftime("%Y-%m-%dT%H:%M", time.gmtime((p.get("time") or time.time()*1000)/1000)),
                "link": j.get("metadata", {}).get("url"),
            })
    except Exception:
        pass
    out = {"source": "LIVE", "feeds": ["nasa-eonet", "usgs"],
           "count": len(events), "events": events}
    _kv_set("world_events", out, _WORLDCACHE_TTL)
    return out

@app.get("/api/world-events")
async def world_events_endpoint():
    return await _world_events()


# ── DRIVER LIVE CALL (Hermes 'driver' subagent) ────────────────────
# Realtime call persona: the bot is a real truck driver on the road,
# grounded in the unit's live telemetry. Invokes the `driver` Hermes profile.
import os as _os
HERMES_BIN_DRIVER = _os.path.expanduser("~/.local/bin/hermes")
if not _os.path.exists(HERMES_BIN_DRIVER):
    HERMES_BIN_DRIVER = "hermes"

def _driver_situation(vid, message=""):
    """Build the LIVE SITUATION block the driver bot is grounded in."""
    out = {"vehicle": vid}
    try:
        with db() as c, c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""SELECT v.id,v.kind,v.model,v.driver,v.name,
                                   t.speed_kmh, t.engine_temp, t.fuel_pct, t.heading, t.lat, t.lng
                            FROM vehicles v
                            LEFT JOIN (SELECT vehicle_id,speed_kmh,engine_temp,fuel_pct,heading,lat,lng,
                                              ROW_NUMBER() OVER (PARTITION BY vehicle_id ORDER BY ts DESC) rn
                                       FROM telemetry) t ON t.vehicle_id=v.id AND t.rn=1
                            WHERE v.id=%s""", (vid,))
            v = cur.fetchone()
        if v:
            out.update({
                "kind": v["kind"], "model": v["model"], "driver": v["driver"],
                "speed_kmh": v["speed_kmh"], "engine_temp": v["engine_temp"],
                "fuel_pct": v["fuel_pct"], "heading_deg": v["heading"],
                "lat": v["lat"], "lng": v["lng"],
            })
    except Exception:
        pass
    try:
        with db() as c, c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""SELECT s.id,s.cargo,s.value_eur,s.status,s.eta_minutes,s.sla_minutes,
                                  o.name origin, d.name destination, l.id lane
                           FROM shipments s
                           JOIN lanes l ON l.id=s.lane_id
                           JOIN locations o ON o.id=l.origin
                           JOIN locations d ON d.id=l.destination
                           WHERE s.vehicle_id=%s LIMIT 1""", (vid,))
            s = cur.fetchone()
        if s:
            out.update({"cargo": s["cargo"], "origin": s["origin"],
                        "destination": s["destination"], "status": s["status"],
                        "eta_min": s["eta_minutes"], "sla_min": s["sla_minutes"],
                        "value_eur": s["value_eur"]})
    except Exception:
        pass
    try:
        with db() as c, c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""SELECT id,kind,severity,title,lat,lng,alt_km,alt_min
                           FROM incidents WHERE affected_vehicle=%s AND resolved_at IS NULL LIMIT 3""", (vid,))
            incs = cur.fetchall()
        if incs:
            out["incident"] = [dict(i) for i in incs]
    except Exception:
        pass
    return out

def _driver_prompt(vid, message, situation, history):
    h = ""
    if history:
        h = "\n".join(f"{r['role'].upper()}: {r['content']}" for r in history[-6:])
    sit = json.dumps(situation, indent=1)
    return (
        "You are on a live phone call with the command center. Stay in character as the truck driver. "
        "Answer the caller's message naturally and briefly (1-3 sentences), grounded ONLY in the live situation below.\n\n"
        "LIVE SITUATION:\n" + sit +
        ("\n\nCONVERSATION SO FAR:\n" + h if h else "") +
        f"\n\nCALLER SAYS: {message}\n\nReply now as the driver."
    )

@app.post("/api/driver/call")
async def driver_call(payload: dict):
    vid = (payload.get("vehicle") or "TRK-101").strip()
    message = (payload.get("message") or "Can you hear me? How are things up there?").strip()
    history = payload.get("history") or []
    situation = _driver_situation(vid)
    prompt = _driver_prompt(vid, message, situation, history)
    t0 = time.time()
    cmd = [HERMES_BIN_DRIVER, "-p", "driver", "chat",
           "-q", prompt, "--oneshot", "-Q", "--max-turns", "3"]
    reply = None; err = None
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=60, cwd=_os.getcwd())
        out = (p.stdout or "").strip()
        lines = [l for l in out.splitlines() if not l.startswith("session_id")]
        reply = "\n".join(lines).strip() or (p.stderr or "").strip() or None
    except subprocess.TimeoutExpired:
        err = "driver subagent timed out"
    except Exception as e:
        err = f"driver subagent failed: {e}"
    # Deterministic fallback so the call never comes back empty
    if not reply or not reply.strip():
        reply = _driver_fallback(vid, situation)
        err = err or "deterministic fallback"
    return {
        "ok": bool(reply), "vehicle": vid,
        "agent": "hermes:driver",
        "reply": reply,
        "situation": situation,
        "avatar": _driver_avatar(vid, situation),
        "ms": int((time.time() - t0) * 1000),
        "error": err,
    }

def _driver_avatar(vid, situation):
    try:
        with db() as c, c.cursor() as cur:
            cur.execute("""SELECT avatar FROM drivers WHERE vehicle_id=%s LIMIT 1""", (vid,))
            row = cur.fetchone()
        if row and row[0]:
            return row[0]
    except Exception:
        pass
    # deterministic randomuser portrait keyed by vehicle id
    seed = abs(hash(vid)) % 100
    return f"https://randomuser.me/api/portraits/men/{seed}.jpg"

def _driver_fallback(vid, situation):
    sp = situation.get("speed_kmh")
    temp = situation.get("engine_temp")
    fuel = situation.get("fuel_pct")
    dest = situation.get("destination") or "destination"
    bits = ["yeah, I'm up and driving."]
    if sp is not None:
        bits.append(f"Going about {round(sp)} on the road right now.")
    if temp is not None:
        bits.append(f"Engine's reading around {round(temp)} degrees, all normal.")
    if fuel is not None:
        bits.append(f"Fuel's at about {round(fuel)} percent.")
    inc = situation.get("incident")
    if inc:
        k = inc[0].get("kind", "")
        bits.append({"accident": "Just got into a bit of an accident here, I'm safe, holding position.",
                     "flat_tire": "Got a flat tire, I'm pulling over and swapping it.",
                     "maintenance": "Engine's acting up a bit, I've got the hazards on."}.get(k, "Something's going on up here, I'll keep you posted."))
    else:
        bits.append(f"Heading toward {dest} on schedule.")
    return " ".join(bits)


# ── DELL GLOBAL NETWORK (HQ + CSCs) ──
@app.get("/api/dell-network")
def dell_network():
    with db() as c, c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT id,name,kind,lat,lng,capacity,region,meta
            FROM locations WHERE kind IN ('hq','csc','factory')
            ORDER BY (kind='hq') DESC, (kind='factory') DESC, region, name
        """)
        rows = cur.fetchall()
    by_region = {}
    for r in rows:
        by_region.setdefault(r["region"], []).append(r)
    return {
        "ok": True,
        "total": len(rows),
        "hq": next((r for r in rows if r["kind"] == "hq"), None),
        "cscs": [r for r in rows if r["kind"] == "csc"],
        "factories": [r for r in rows if r["kind"] == "factory"],
        "regions": {k: len(v) for k, v in sorted(by_region.items())},
    }


def _openverse_images(query: str, size: int = 4):
    """Keyless CC image search (Openverse aggregates Flickr/Wikimedia/CC0).
    Verifies each candidate URL server-side and keeps only ones that actually
    serve image bytes (Wikimedia paths from Openverse are often stale/404)."""
    url = "https://api.openverse.org/v1/images/"
    r = _http_get_json(url, {"q": query, "page_size": size})
    out = []
    for it in r.get("results", []):
        u = it.get("url")
        if not u:
            continue
        probe = None
        try:
            p = httpx.get(u, timeout=15, headers={"User-Agent": "aegis-demo/1.0 (contact: demo)"})
            ct = p.headers.get("content-type", "")
            if p.status_code == 200 and (ct.startswith("image/") or len(p.content) > 8000):
                probe = u
        except Exception:
            pass
        if not probe:
            continue
        out.append({
            "url": probe,
            "thumbnail": it.get("thumbnail"),
            "title": (it.get("title") or "")[:80],
            "creator": it.get("creator") or "Unknown",
            "creator_url": it.get("creator_url"),
            "license": (it.get("license") or "CC") + (f" {it.get('license_version')}" if it.get("license_version") else ""),
            "license_url": it.get("license_url"),
            "provider": it.get("provider"),
            "source_page": it.get("foreign_landing_url"),
        })
    return out

@app.get("/api/dell-photo/{site_id}")
def dell_photo(site_id: str):
    """Representative, honest photo for a Dell network site.

    Dell does not publish photos of its own offices, so we never claim one is.
    We look up a Creative-Commons photo of the CITY (office building / skyline)
    via Openverse (keyless, server-side), cache it 7 days, and always label it
    as a representative city photo — never 'the Dell office'.
    """
    import re
    with db() as c, c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT id,name,kind FROM locations WHERE id=%s AND kind IN ('hq','csc','factory')", (site_id,))
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, "site not found")
    city = row["name"].split(" — ")[0].replace("Dell Factory — ", "").replace("Dell HQ — ", "").split(",")[0].strip()

    def fetcher():
        for q in (f"{city} skyline", f"{city} city", f"office building {city}"):
            try:
                hits = _openverse_images(q, 10)
            except Exception:
                continue
            if hits:
                return {"city": city, "query": q, "images": hits[:3],
                        "note": f"Representative {city} photo — Dell does not publish photos of its offices."}
        return None
    d, state = _kv_cached(f"dell_photo_{site_id}", 7 * 86400, fetcher)
    if not d:
        return {"ok": False, "site_id": site_id, "city": city, "images": [],
                "note": "No Creative-Commons city photo found (feed unreachable)."}
    return {"ok": True, "site_id": site_id, "state": state, "name": row["name"],
            "kind": row["kind"], "honest": True, **d}


# ── LANE ROUTES (OSRM primary + alternatives, cached in PostGIS) ──
@app.get("/api/route/{lane_id}")
async def lane_route(lane_id: str, force: bool = False):
    with db() as c, c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""SELECT l.*, o.lat olat,o.lng olng,d.lat dlat,d.lng dlng
                       FROM lanes l JOIN locations o ON o.id=l.origin JOIN locations d ON d.id=l.destination
                       WHERE l.id=%s""", (lane_id,))
        lane = cur.fetchone()
    if not lane:
        raise HTTPException(404, "lane not found")
    if not force:
        # serve cached variants fetched today
        with db() as c, c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""SELECT variant, distance_km, duration_min,
                                   ST_AsGeoJSON(geom) AS geo FROM routes_cached
                           WHERE lane_id=%s AND date_trunc('day', fetched_at) = date_trunc('day', now())
                           ORDER BY variant""", (lane_id,))
            rows = cur.fetchall()
        if rows:
            return {"lane_id": lane_id, "source": "cache", "variants": [
                {"variant": r["variant"], "km": r["distance_km"], "min": r["duration_min"],
                 "geometry": json.loads(r["geo"])} for r in rows]}
    # fetch live
    try:
        variants = await fetch_osrm(lane["olat"], lane["olng"], lane["dlat"], lane["dlng"], alternatives=2)
    except Exception:
        # fallback: straight 2-point line
        variants = [{"points": [[lane["olng"], lane["olat"]], [lane["dlng"], lane["dlat"]]],
                    "km": lane["distance_km"] or 100.0, "min": (lane["freeflow_min"] or 60)}]
    if not variants:
        raise HTTPException(502, "OSRM unavailable")
    with db() as c, c.cursor() as cur:
        for i, v in enumerate(variants):
            cur.execute("DELETE FROM routes_cached WHERE lane_id=%s AND variant=%s", (lane_id, i))
            cur.execute("""INSERT INTO routes_cached (lane_id,variant,geom,distance_km,duration_min)
                           VALUES (%s,%s,ST_GeomFromText(%s,4326),%s,%s)""",
                        (lane_id, i, _wkt(v["points"]), v["km"], v["min"]))
        c.commit()
    out = []
    for i, v in enumerate(variants):
        out.append({"variant": i, "km": round(v["km"],1), "min": round(v["min"],0),
                    "geometry": _geojson_line(v["points"])})
    return {"lane_id": lane_id, "source": "live", "variants": out}


# ── TRAFFIC (per-lane congestion index; simulated, seeded by time-of-day) ──
@app.get("/api/traffic")
def traffic():
    import datetime
    hour = datetime.datetime.utcnow().hour
    with db() as c, c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT id, distance_km, origin, destination FROM lanes ORDER BY id")
        rows = cur.fetchall()
    out = []
    for r in rows:
        # deterministic pseudo-noise from lane id + hour so it's stable within a minute
        seed = sum(ord(ch) for ch in r["id"]) * 7 + hour
        import random
        rnd = random.Random(seed)
        base = 0.15 + 0.55 * (0.5 + 0.5*math.sin((hour + seed%13)/24*2*math.pi))  # rush-hour curve
        idx = max(0.02, min(1.0, base + (rnd.random()-0.5)*0.25))
        # congestion adds ~ (idx) * freeflow penalty
        slow = 1 + idx*1.2
        out.append({
            "lane_id": r["id"], "index": round(idx,2),
            "state": "free" if idx<0.25 else ("moderate" if idx<0.55 else ("busy" if idx<0.8 else "jammed")),
            "est_factor": round(slow,2),
        })
    return {"ts": int(time.time()), "source": "SIM", "lanes": out}


# ════════════════ INCIDENT SIMULATION + REROUTE ════════════════
class IncidentIn(BaseModel):
    lane_id: str
    vehicle_id: Optional[str] = None
    kind: str = "accident"      # accident / closure / weather / hazard / flat_tire / maintenance
    severity: str = "P1"
    # position along the lane (0..1) where the incident happens
    frac: float = 0.5


@app.post("/api/incidents")
async def create_incident(body: IncidentIn):
    with db() as c, c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""SELECT l.*, o.lat olat,o.lng olng,d.lat dlat,d.lng dlng FROM lanes l
                       JOIN locations o ON o.id=l.origin JOIN locations d ON d.id=l.destination
                       WHERE l.id=%s""", (body.lane_id,))
        lane = cur.fetchone()
    if not lane:
        raise HTTPException(404, "lane not found")
    import uuid
    iid = "INC-" + uuid.uuid4().hex[:8].upper()
    # vehicle-fault incidents (flat tire / maintenance) delay the unit — no road detour
    vehicle_fault = body.kind in ("flat_tire", "maintenance")
    # incident point on the straight line
    ilat = lane["olat"] + (lane["dlat"]-lane["olat"])*body.frac
    ilng = lane["olng"] + (lane["dlng"]-lane["olng"])*body.frac
    if vehicle_fault and body.severity == "P1":
        body.severity = "P2"
    # build an AVOID list: OSRM supports avoidance via ?exclusions? Not in demo.
    # Strategy: fetch alternatives, pick the one that deviates most from the incident line (longest).
    if vehicle_fault:
        variants = []
    else:
        try:
            variants = await fetch_osrm(lane["olat"], lane["olng"], lane["dlat"], lane["dlng"], alternatives=3)
        except Exception:
            variants = []
    primary = variants[0] if variants else {"points":[[lane["olng"],lane["olat"]],[lane["dlng"],lane["dlat"]]],
                                            "km": lane["distance_km"] or 100.0, "min": lane["freeflow_min"] or 60}
    # pick best alternative = the longest (detour) one
    alts = [v for v in variants[1:]] or []
    best = max(alts, key=lambda v: v["km"]) if alts else None
    alt_km = best["km"] if best else None
    alt_min = best["min"] if best else None
    alt_geo = best["points"] if best else None
    title = f"{body.kind.upper()} on lane {lane['id']} ({lane['origin']} → {lane['destination']})"
    with db() as c, c.cursor() as cur:
        cur.execute("""INSERT INTO incidents (id,lane_id,kind,severity,title,lat,lng,geom,affected_vehicle,
                       alt_route,alt_km,alt_min)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,ST_SetSRID(ST_MakePoint(%s,%s),4326),%s,
                               ST_GeomFromText(%s,4326),%s,%s)""",
                    (iid, lane["id"], body.kind, body.severity, title, ilat, ilng, ilng, ilat,
                     body.vehicle_id,
                     _wkt(alt_geo) if alt_geo else "LINESTRING(0 0,0 0)", alt_km, alt_min))
        if body.vehicle_id:
            cur.execute("UPDATE shipments SET status='rerouted' WHERE vehicle_id=%s AND status='in_transit'",
                        (body.vehicle_id,))
        c.commit()
    # recommendation text
    delta_km = round(alt_km - primary["km"], 1) if alt_km else 0
    delta_min = round(alt_min - primary["min"], 0) if alt_min else 0
    return {
        "id": iid, "title": title, "lane_id": lane["id"], "vehicle_id": body.vehicle_id,
        "severity": body.severity, "lat": ilat, "lng": ilng,
        "primary_km": round(primary["km"],1), "primary_min": round(primary["min"],0),
        "alternative_km": round(alt_km,1) if alt_km else None,
        "alternative_min": round(alt_min,0) if alt_min else None,
        "delta_km": delta_km, "delta_min": delta_min,
        "recommendation": (
            f"Re-route {body.vehicle_id or 'vehicle'} around the {body.kind}: "
            f"+{delta_km} km / +{int(delta_min)} min via the alternate corridor." if alt_km else
            "No alternative corridor available; consider holding vehicle and dispatching relief unit."
        ),
        "alternative_geometry": _geojson_line(alt_geo) if alt_geo else None,
        "created_at": time.time()
    }


@app.get("/api/incidents")
def incidents(active_only: bool = True):
    with db() as c, c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        q = ("SELECT i.id,i.lane_id,i.kind,i.severity,i.title,i.lat,i.lng,i.affected_vehicle,i.alt_km,i.alt_min,i.created_at,i.resolved_at, "
             "ST_AsGeoJSON(i.alt_route) AS alt_geo, s.value_eur AS impact_value, s.cargo AS impact_cargo, s.customer AS impact_customer "
             "FROM incidents i LEFT JOIN shipments s ON s.vehicle_id = i.affected_vehicle")
        if active_only: q += " WHERE resolved_at IS NULL"
        q += " ORDER BY created_at DESC"
        cur.execute(q)
        rows = []
        for r in cur.fetchall():
            d = dict(r)
            d["alt_geometry"] = json.loads(d.pop("alt_geo")) if d.get("alt_geo") else None
            rows.append(d)
        return rows


@app.post("/api/incidents/{iid}/resolve")
def resolve_incident(iid: str):
    with db() as c, c.cursor() as cur:
        cur.execute("UPDATE incidents SET resolved_at=now() WHERE id=%s", (iid,))
        n = cur.rowcount
        cur.execute("""UPDATE shipments SET status='in_transit'
                       WHERE vehicle_id=(SELECT affected_vehicle FROM incidents WHERE id=%s)
                       AND status='rerouted'""", (iid,))
        c.commit()
    if n == 0: raise HTTPException(404, "incident not found")
    return {"resolved": iid}


# ── push a fresh telemetry point (driven by the frontend sim) ──
# Truck-side path: CAN BUS / OBD-II -> telematics gateway -> KAFKA topic
# (aegis.events.truck.telemetry) -> ingest consumer -> PostGIS.
# The gateway container runs on the aegis_default podman network so it can
# reach both the broker (kafka:9092) and PostGIS (aegis_db:5432). If the
# gateway is unreachable the API falls back to a direct PostGIS insert so
# the command center never goes dark.
import urllib.request as _urlreq

GW_INGEST = os.environ.get("AEGIS_GW_INGEST", "http://127.0.0.1:8411/ingest/telemetry")
GW_HEALTH = os.environ.get("AEGIS_GW_HEALTH", "http://127.0.0.1:8411/health")

def _via_gateway(rec: dict) -> bool:
    """Publish one point through the ingest gateway. True on success."""
    try:
        req = _urlreq.Request(
            GW_INGEST,
            data=json.dumps(rec).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with _urlreq.urlopen(req, timeout=2.0) as r:
            return r.status == 202
    except Exception:
        return False

class TelIn(BaseModel):
    vehicle_id: str; lat: float; lng: float; speed_kmh: float; heading: float
    fuel_pct: float; engine_temp: float; cargo_temp: float; signal_pct: float; gps_acc_m: float

@app.post("/api/telemetry")
def push_telemetry(t: TelIn):
    rec = {
        "vehicle_id": t.vehicle_id, "lat": t.lat, "lng": t.lng,
        "speed_kmh": t.speed_kmh, "heading": t.heading, "fuel_pct": t.fuel_pct,
        "engine_temp": t.engine_temp, "cargo_temp": t.cargo_temp,
        "signal_pct": t.signal_pct, "gps_acc_m": t.gps_acc_m,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    if _via_gateway(rec):
        return {"ok": True, "route": "kafka:aegis.events.truck.telemetry"}
    # fallback: direct PostGIS (gateway down)
    with db() as c, c.cursor() as cur:
        cur.execute("""INSERT INTO telemetry (vehicle_id,lat,lng,speed_kmh,heading,fuel_pct,engine_temp,
                       cargo_temp,signal_pct,gps_acc_m,geom)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,ST_SetSRID(ST_MakePoint(%s,%s),4326))""",
                    (t.vehicle_id,t.lat,t.lng,t.speed_kmh,t.heading,t.fuel_pct,t.engine_temp,
                     t.cargo_temp,t.signal_pct,t.gps_acc_m,t.lng,t.lat))
        c.commit()
    return {"ok": True, "route": "postgis:direct(fallback)"}


# ── shipment lifecycle ──
_LIFECYCLE = ["loading", "in_transit", "delivered"]

@app.post("/api/shipments/{sid}/status")
def set_shipment_status(sid: str, status: str = "in_transit"):
    if status not in ("loading", "in_transit", "delayed", "rerouted", "delivered"):
        raise HTTPException(400, "invalid status")
    with db() as c, c.cursor() as cur:
        cur.execute("UPDATE shipments SET status=%s WHERE id=%s", (status, sid))
        cur.execute("INSERT INTO shipment_events (shipment_id,type,note) VALUES (%s,%s,%s)",
                    (sid, "sla" if status != "delivered" else "arr", f"Status → {status}"))
        c.commit()
    return {"ok": True, "id": sid, "status": status}


# ── weather (Open-Meteo keyless, kv-cached 30 min, SIM fallback) ──
WX_CODES = {0: "CLEAR", 1: "MOSTLY CLEAR", 2: "PARTLY CLOUDY", 3: "OVERCAST", 45: "FOG",
            51: "DRIZZLE", 61: "L. RAIN", 63: "RAIN", 65: "HEAVY RAIN", 71: "SNOW",
            80: "SHOWERS", 95: "THUNDER"}

async def _kv_get(key):
    with db() as c, c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT value, ttl_until FROM kv WHERE key=%s", (key,))
        row = cur.fetchone()
    if row and row["ttl_until"] and row["ttl_until"].timestamp() > time.time():
        return row["value"]
    return None

def _kv_set(key, value, ttl_s):
    with db() as c, c.cursor() as cur:
        cur.execute("""INSERT INTO kv (key,value,ttl_until) VALUES (%s,%s,now() + (%s || ' seconds')::interval)
                       ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value,
                       fetched_at=now(), ttl_until=EXCLUDED.ttl_until""", (key, json.dumps(value), str(int(ttl_s))))
        c.commit()

@app.get("/api/weather")
async def weather():
    cached = await _kv_get("wx_hubs")
    if cached:
        return {"hubs": cached, "source": "CACHED"}
    with db() as c, c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT id,name,lat,lng FROM locations WHERE (kind IN ('dc','port') AND id IN ('h-ams','h-rtm','h-muc','h-ant','h-ham')) OR id IN ('c-lim','d-csc-lim')")
        hubs = [dict(r) for r in cur.fetchall()]
    try:
        lats = ",".join(str(h["lat"]) for h in hubs)
        lngs = ",".join(str(h["lng"]) for h in hubs)
        async with httpx.AsyncClient(timeout=6) as hc:
            r = await hc.get(
                f"https://api.open-meteo.com/v1/forecast?latitude={lats}&longitude={lngs}"
                f"&current=temperature_2m,wind_speed_10m,relative_humidity_2m,weather_code&timezone=auto")
            r.raise_for_status()
            j = r.json()
        norm = [{**{k: h[k] for k in ("id", "name", "lat", "lng")},
                 "temp": j["current"]["temperature_2m"][i],
                 "wind": j["current"]["wind_speed_10m"][i],
                 "hum": j["current"]["relative_humidity_2m"][i],
                 "code": j["current"]["weather_code"][i]} for i, h in enumerate(hubs)]
        if norm and norm[0].get("temp") is None:
            raise ValueError("bad shape")
        _kv_set("wx_hubs", norm, 1800)
        return {"hubs": norm, "source": "LIVE"}
    except Exception:
        norm = [{**{k: h[k] for k in ("id", "name", "lat", "lng")},
                 "temp": round(11 + 6 * abs(((h["lat"] * 7 + h["lng"] * 13)) % 1), 1),
                 "wind": round(6 + 14 * abs(((h["lng"] * 3) % 1)), 1),
                 "hum": int(58 + 30 * abs(((h["lat"] * 5) % 1))),
                 "code": 1 + int(4 * abs(((h["lng"] * 11) % 1)))} for h in hubs]
        _kv_set("wx_hubs", norm, 60)
        return {"hubs": norm, "source": "SIM"}


# ── road conditions: keyless live feed proxy, deterministic fallback ──
_CONDITIONS_URL = "https://openconditions.org/observations.geojson"

@app.get("/api/conditions")
async def conditions(bbox: str = Query("3,50,8,53")):
    """bbox=west,south,east,north. Tries the OpenConditions public feed; falls
    back to a deterministic per-lane model so the layer is never empty."""
    cached = await _kv_get("cond_" + bbox)
    if cached:
        return cached
    try:
        async with httpx.AsyncClient(timeout=7) as hc:
            r = await hc.get(_CONDITIONS_URL, params={"bbox": bbox, "domain": "roads"})
            r.raise_for_status()
            j = r.json()
        feats = j.get("features", []) if j.get("type") == "FeatureCollection" else []
        out = {"source": "LIVE", "feed": "openconditions.org",
               "count": len(feats),
               "points": [{"lat": f["geometry"]["coordinates"][1],
                           "lng": f["geometry"]["coordinates"][0],
                           "kind": (f.get("properties") or {}).get("conditionType", "unknown"),
                           "note": (f.get("properties") or {}).get("headline", "")}
                          for f in feats[:200]
                          if f.get("geometry", {}).get("type") == "Point"]}
        _kv_set("cond_" + bbox, out, 300)
        return out
    except Exception:
        # deterministic fallback: per-lane congestion as points along the lane
        import random
        with db() as c, c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""SELECT l.id, l.distance_km, o.lat olat, o.lng olng, d.lat dlat, d.lng dlng
                           FROM lanes l JOIN locations o ON o.id=l.origin
                           JOIN locations d ON d.id=l.destination""")
            lanes = [dict(r) for r in cur.fetchall()]
        hour = time.localtime().tm_hour
        rnd = random.Random(42 + hour)
        points = []
        for l in lanes:
            idx = min(1.0, max(0.02, 0.15 + 0.5 * (0.5 + 0.5 * math.sin((hour + sum(map(ord, l["id"])) % 13) / 24 * 2 * math.pi)) + (rnd.random() - 0.5) * 0.2))
            if idx > 0.35:
                frac = rnd.random()
                points.append({"lat": l["olat"] + (l["dlat"] - l["olat"]) * frac,
                               "lng": l["olng"] + (l["dlng"] - l["olng"]) * frac,
                               "kind": "congestion" if idx < 0.75 else "incident",
                               "note": f"lane {l['id']} · congestion {int(idx*100)}%"})
        out = {"source": "SIM", "feed": "deterministic per-lane model",
               "count": len(points), "points": points}
        _kv_set("cond_" + bbox, out, 120)
        return out


# ── analyst insights (dedicated watcher agent + researcher bot) ──
def _unwrap(v, depth=3):
    for _ in range(depth):
        if isinstance(v, str):
            s = v.strip()
            if s.startswith("```"):
                s = s.split("\n", 1)[1]
                if "```" in s:
                    s = s.rsplit("```", 1)[0]
                s = s.strip()
            try:
                v = json.loads(s)
            except (json.JSONDecodeError, ValueError):
                return v
        else:
            return v
    return v

def _normalize_insight(ins):
    """Best-effort normalization of a watcher insight so the UI always renders
    structured context. Handles: `summary` as a JSON string (double- or
    triple-encoded), `kpi_view.note == 'unparsed'`, missing keys."""
    if not isinstance(ins, dict):
        return ins
    # 1) if summary is a string that looks like JSON, try to unwrap it fully
    s = ins.get("summary")
    if isinstance(s, str) and s.startswith("{"):
        u = _unwrap(s)
        if isinstance(u, dict):
            # promote the inner keys to top level, keep summary text
            inner_text = u.get("summary") if isinstance(u.get("summary"), str) else None
            for k in ("changes", "risks", "recommendations", "kpi_view"):
                if isinstance(u.get(k), list) and not ins.get(k):
                    ins[k] = u[k]
                elif isinstance(u.get(k), dict) and not ins.get(k):
                    ins[k] = u[k]
            if inner_text:
                ins["summary"] = inner_text
            else:
                # fall back to a one-liner of what we have
                ins["summary"] = ins.get("summary", "")[:200]
    # 2) if kpi_view.note says 'unparsed' and we still have a raw string, try once more
    if isinstance(ins.get("kpi_view"), dict) and ins["kpi_view"].get("note") == "unparsed":
        if isinstance(ins.get("summary"), str) and len(ins["summary"]) > 60:
            # strip leading { if present (already attempted above)
            txt = ins["summary"]
            if txt.startswith("{"):
                # salvage: cut at first '}' then re-try
                end = txt.rfind("}")
                if end > 20:
                    try:
                        u2 = json.loads(txt[:end+1])
                        for k in ("changes", "risks", "recommendations", "kpi_view"):
                            if isinstance(u2.get(k), list) and not ins.get(k):
                                ins[k] = u2[k]
                        if isinstance(u2.get("summary"), str):
                            ins["summary"] = u2["summary"]
                        ins["kpi_view"] = {"note": u2.get("kpi_view", {}).get("note", "recovered") if isinstance(u2.get("kpi_view"), dict) else "recovered"}
                    except (json.JSONDecodeError, ValueError):
                        pass
    # 3) ensure all keys present
    ins.setdefault("changes", [])
    ins.setdefault("risks", [])
    ins.setdefault("recommendations", [])
    ins.setdefault("kpi_view", {})
    # 4) HTML-escape is done by the UI (textContent). But guard: if summary
    #    still contains raw JSON braces, truncate to first sentence.
    if isinstance(ins.get("summary"), str) and ins["summary"].startswith("{"):
        txt = ins["summary"]
        # take up to first comma outside a quote
        depth_ = 0; quote = False; end = len(txt)
        for i, ch in enumerate(txt):
            if ch == '"': quote = not quote
            elif not quote:
                if ch == "{": depth_ += 1
                elif ch == "}":
                    depth_ -= 1
                    if depth_ == 0: end = i; break
                elif ch == "," and depth_ == 1:
                    end = i; break
        ins["summary"] = txt[:end].strip() or txt[:200]
    return ins

def _load_insights_rows(limit):
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "insights.jsonl")
    if not os.path.exists(path):
        return []
    rows = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("insight"):
                r["insight"] = _normalize_insight(r["insight"])
            rows.append(r)
    return rows[-limit:]

@app.get("/api/insights")
def insights(limit: int = Query(20, le=200)):
    """Latest analyst cycle(s) written by agents/watcher.py.
    Each record: {ts, briefing, insight, error, api_ok, agent, analyst}."""
    rows = _load_insights_rows(limit)
    rows.reverse()  # newest first
    return {"ok": True, "cycles": rows, "status": "live"}


@app.get("/api/insights/latest")
def insights_latest():
    """Last cycle with a VALID insight (skips transient error cycles)."""
    rows = _load_insights_rows(12)
    for r in reversed(rows):
        if r.get("insight"):
            return {"ok": True, "latest": r}
    if rows:
        return {"ok": True, "latest": rows[-1]}
    return {"ok": True, "latest": None}


@app.get("/api/overview")
async def overview():
    """Single bootstrap payload for the frontend."""
    try:
        weather = await weather()
    except Exception:
        weather = {"hubs": [], "source": "SIM"}
    try:
        cond = await conditions("2,48,22,60")
    except Exception:
        cond = {"source": "SIM", "points": []}
    return {
        "locations": locations(),
        "lanes": lanes(),
        "vehicles": vehicles(),
        "shipments": shipments(),
        "inventory": inventory(),
        "kpi": kpi(),
        "incidents": incidents(True),
        "traffic": traffic(),
        "weather": weather,
        "conditions": cond,
    }

# ── STACK / DATA-PROVENANCE (evidence that every feed is live) ──────
# Aggregates, in one call, proof that each data source is actually live:
# the internal PostGIS, the open-data feeds, and the analytics platform
# (captor → Kafka → pipeline → lake → Trino/Grafana). Each source returns
# a status + a human-readable detail so the STACK tab can show it auditable.
STACK_TIMEOUT = 6.0

async def _probe_http(url, headers=None, timeout=STACK_TIMEOUT):
    """Return (ok, payload_dict_or_None, note). Never raises."""
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as hc:
            r = await hc.get(url, headers=headers or {})
            r.raise_for_status()
            try:
                return True, r.json(), None
            except Exception:
                return True, {"raw": r.text[:200]}, None
    except Exception as e:
        return False, None, str(e).split("\n")[0][:120]

@app.get("/api/stack")
async def stack_evidence():
    """Auditable provenance: prove every feed / data path is live right now."""
    import asyncio, datetime

    # ---- 1. internal PostGIS (single source of truth) ----
    db_proof = {"status": "down", "detail": "unreachable", "meta": {}}
    try:
        with db() as c, c.cursor() as cur:
            cur.execute("SELECT count(*), max(ts) FROM telemetry")
            tel_n, tel_max = cur.fetchone()
            cur.execute("SELECT count(*) FROM vehicles")
            veh_n = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM incidents WHERE resolved_at IS NULL")
            inc_n = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM components")
            comp_n = cur.fetchone()[0]
            age = (datetime.datetime.now(datetime.timezone.utc) - tel_max).total_seconds() if tel_max else None
        db_proof = {
            "status": "live",
            "detail": f"telemetry {tel_n:,} rows · last point {int(age)}s ago",
            "meta": {"telemetry_rows": tel_n, "last_telemetry_age_s": int(age) if age is not None else None,
                     "vehicles": veh_n, "incidents_open": inc_n, "components": comp_n},
        }
    except Exception as e:
        db_proof["detail"] = str(e).split("\n")[0][:120]

    # ---- 2. open-data feeds (keyless) ----
    feed_specs = [
        ("eonet", "NASA EONET", "natural & man-made events",
         "https://eonet.gsfc.nasa.gov/api/v3/events?status=open&limit=100"),
        ("usgs", "USGS Earthquakes", "M3+ past 24h (geojson)",
         "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson"),
        ("openmeteo", "Open-Meteo (weather)", "keyless weather · via /api/weather (cached)",
         "http://127.0.0.1:8300/api/weather"),
    ]
    feeds = {}
    async def _feed(kind, name, desc, url):
        ok, payload, note = await _probe_http(url)
        count = None
        if ok:
            if kind == "eonet":
                count = len((payload or {}).get("events", []))
            elif kind == "usgs":
                feats = (payload or {}).get("features", [])
                count = sum(1 for f in feats if (f.get("properties", {}).get("mag") or 0) >= 3.0)
            elif kind == "openmeteo":
                src=(payload or {}).get("source")
                hubs=(payload or {}).get("hubs")
                n=len(hubs) if isinstance(hubs, list) else 0
                t=hubs[0].get("temp") if (n and isinstance(hubs[0], dict)) else None
                count = f"{n} hubs · {src}" if src else (f"{t}°C" if t is not None else n or 1)
        feeds[kind] = {"name": name, "desc": desc, "status": "live" if ok else "offline",
                       "count": count, "note": None if ok else note, "url": url}
    await asyncio.gather(*[_feed(*s) for s in feed_specs])

    # ---- 3. truck-side Kafka ingest (gateway on aegis_default net) ----
    gw_ok, gw_payload, gw_note = await _probe_http("http://127.0.0.1:8411/health")
    truck_kafka = {
        "status": "live" if gw_ok else "offline",
        "topic": "aegis.events.truck.telemetry",
        "note": gw_note,
        "points_received": (gw_payload or {}).get("points_received"),
        "points_produced": (gw_payload or {}).get("points_produced"),
        "points_consumed": (gw_payload or {}).get("points_consumed"),
        "points_written": (gw_payload or {}).get("points_written"),
        "last_record_at": (gw_payload or {}).get("last_record_at"),
    }

    # ---- 4. analytics platform (captor → Kafka → pipeline → lake) ----
    async def _svc(url, kind):
        ok, payload, note = await _probe_http(url)
        return kind, ok, payload, note
    trino_ok, trino_payload, trino_note = await _probe_http("http://127.0.0.1:8543/v1/info")
    grafana_ok, grafana_payload, grafana_note = await _probe_http("http://127.0.0.1:3000/api/health")
    kafka_ok, kafka_payload, kafka_note = await _probe_http("http://127.0.0.1:8040/")
    captor_ok, captor_payload, captor_note = await _probe_http("http://127.0.0.1:8400/health")
    lineage_ok, lineage_payload, lineage_note = await _probe_http("http://127.0.0.1:8401/api/context/tables")

    lineage = {"status": "offline", "summary": None, "tables": []}
    if lineage_ok and lineage_payload:
        lin_tables = lineage_payload.get("tables", [])
        lineage = {
            "status": "live",
            "summary": lineage_payload.get("summary"),
            "tables": [
                {"name": t.get("name"), "kind": t.get("kind"),
                 "source_rows": (t.get("source") or {}).get("rows"),
                 "topic": (t.get("topic") or {}).get("name"),
                 "lake_rows": (t.get("lake") or {}).get("rows"),
                 "contract": (t.get("contract") or {}).get("status")}
                for t in lin_tables
            ],
        }

    return {
        "ok": True,
        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "db": db_proof,
        "feeds": list(feeds.values()),
        "truck_kafka": truck_kafka,
        "analytics": {
            "captor": {"status": "live" if captor_ok else "offline",
                       "detail": (captor_payload or {}).get("last_cycle_at", "") if captor_ok else captor_note,
                       "bootstrap": (captor_payload or {}).get("bootstrap", {}),
                       "tables": {k: v.get("state") for k, v in ((captor_payload or {}).get("tables", {})).items()}},
            "trino": {"status": "live" if trino_ok else "offline",
                      "version": (trino_payload or {}).get("nodeVersion", {}).get("version") if trino_ok else None,
                      "note": trino_note},
            "grafana": {"status": "live" if grafana_ok else "offline",
                        "state": (grafana_payload or {}).get("commit") and "up" or (None if not grafana_ok else None),
                        "note": grafana_note},
            "kafka_ui": {"status": "live" if kafka_ok else "offline", "note": kafka_note},
            "lineage": lineage,
        },
        "links": {
            "analytics_dashboard": "http://127.0.0.1:8401/",
            "grafana": "http://127.0.0.1:3000/",
            "kafka_ui": "http://127.0.0.1:8040/",
            "trino": "http://127.0.0.1:8543/",
        },
    }

# ── LIVE WORLD FEEDS (server-side proxies with kv cache) ─────────────
# The browser cannot hit these directly (CORS / rate limits), so the API
# fetches them, caches them, and serves them. Every feed is keyless/open.

def _kv_cached(key, ttl_s, fetcher):
    """Return cached kv value if fresh, else run fetcher and cache the result."""
    with db() as c, c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT value FROM kv WHERE key=%s", (key,))
        row = cur.fetchone()
        if row and row["value"].get("_fetched_at"):
            age = time.time() - row["value"]["_fetched_at"]
            if age < ttl_s:
                return row["value"], "CACHED"
    try:
        data = fetcher()
    except Exception:
        data = None
    if data is None:
        return (row["value"] if row else None), "STALE" if row else "OFFLINE"
    payload = {**data, "_fetched_at": time.time()}
    with db() as c, c.cursor() as cur:
        cur.execute("INSERT INTO kv (key, value) VALUES (%s,%s::jsonb) "
                    "ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, fetched_at=now()",
                    (key, json.dumps(payload)))
        c.commit()
    return payload, "LIVE"

def _http_get_json(url, params=None, timeout=20.0):
    with httpx.Client(timeout=timeout, follow_redirects=True) as hc:
        r = hc.get(url, params=params)
        r.raise_for_status()
        return r.json()

def _fetch_opensky():
    """Live ADS-B aircraft worldwide (OpenSky, keyless)."""
    j = _http_get_json("https://opensky-network.org/api/states/all",
                       {"point_radius": 55000000, "point_lat": 10, "point_lng": -40})
    states = j.get("states") or []
    acs = []
    for s in states:
        try:
            if s[5] is None or s[6] is None:
                continue
            acs.append({
                "id": s[0], "callsign": (s[1] or "").strip(), "country": s[2] or "",
                "lon": s[5], "lat": s[6], "alt": s[7], "ground": s[8],
                "vel": s[9], "track": s[10], "vrate": s[11],
            })
        except Exception:
            continue
    return {"count": len(acs), "aircraft": acs[:4000], "source": "opensky-network.org (ADS-B)"}

def _fetch_ships():
    """Live AIS ships through the Strait of Hormuz (keyless, server-side)."""
    j = _http_get_json("https://hormuz.data-tracking.net/api/ships", {"limit": 300})
    items = j if isinstance(j, list) else (j.get("data") or j.get("ships") or [])
    ships = []
    for s in items:
        try:
            lat, lon = s.get("latitude"), s.get("longitude")
            if lat is None:
                fixes = s.get("fixes") or []
                if isinstance(fixes, list) and fixes and isinstance(fixes[0], (list, tuple)) and len(fixes[0]) >= 2:
                    lon, lat = fixes[0][0], fixes[0][1]
            ships.append({
                "name": (s.get("name") or s.get("vessel") or "UNKNOWN").upper(),
                "type": s.get("ship_category") or s.get("type") or s.get("category") or "UNKNOWN",
                "lat": lat, "lon": lon,
                "speed": s.get("speed") or s.get("sog") or 0,
                "course": s.get("course") or s.get("hdg") or 0,
                "dwt": s.get("dwt"), "flag": s.get("flag") or "",
                "dest": s.get("destination") or "",
                "zone": s.get("zone") or "",
            })
        except Exception:
            continue
    ships = [s for s in ships if s["lat"] is not None and s["lon"] is not None]
    return {"count": len(ships), "ships": ships[:300], "source": "hormuz.data-tracking.net (AIS)"}

def _fetch_alerts():
    """Active US weather alerts (NOAA api.weather.gov, keyless).
    Points come from two sources, both honest:
      1. the alert's own polygon geometry (exact, ~17 alerts)
      2. a cached Nominatim geocode of the alert's area name (best-effort,
         filled in incrementally over the first few polls — 1 req/1.1s per Nominatim policy)
    """
    import re as _re, threading
    j = _http_get_json("https://api.weather.gov/alerts", {"active": "true"})
    # ---- recover persisted geocode cache (area name -> [lat, lon] or null) ----
    gcache = {}
    try:
        with db() as c, c.cursor() as cur:
            cur.execute("SELECT value FROM kv WHERE key='alerts_geocode'")
            row = cur.fetchone()
            if row and isinstance(row[0], dict):
                gcache = {k: v for k, v in row[0].items() if v}
    except Exception:
        pass
    _lock = threading.Lock()
    budget = {"n": 0}
    def _geocode(area):
        tok = _re.split(r";| and | to |, ", area)[0].strip()
        if not tok:
            return None
        if tok in gcache:
            return gcache[tok]
        with _lock:
            if budget["n"] >= 20:          # max 20 fresh geocodes per poll (~24s)
                return None
            budget["n"] += 1
        try:
            r = httpx.get(
                "https://nominatim.openstreetmap.org/search",
                params={"q": tok, "format": "json", "limit": 1},
                headers={"User-Agent": "aegis-demo/1.0"}, timeout=10).json()
            hit = [float(r[0]["lat"]), float(r[0]["lon"])] if r else None
        except Exception:
            hit = None
        gcache[tok] = hit
        time.sleep(1.1)                    # Nominatim usage policy
        return hit
    al = []
    for f in j.get("features", []):
        p = f.get("properties", {})
        g = f.get("geometry") or {}
        lat = lon = None
        src = None
        try:
            if g.get("coordinates"):
                def _first(pt):
                    if isinstance(pt, (int, float)):
                        return pt
                    return _first(pt[0]) if pt else None
                coords = g["coordinates"]
                lon = _first(coords[0][0])
                lat = _first(coords[0][1])
                src = "geometry"
        except Exception:
            pass
        if lat is None:
            area = p.get("areaDesc")
            if area:
                hit = _geocode(area)
                if hit:
                    lon, lat = hit
                    src = "geocode"
        al.append({
            "id": p.get("id"), "event": p.get("event"), "severity": p.get("severity"),
            "area": p.get("areaDesc"), "lat": lat, "lon": lon, "src": src,
            "desc": (p.get("description") or "")[:200],
        })
    # ---- persist geocode cache (plain jsonb dict, same shape _kv_cached uses) ----
    try:
        with db() as c, c.cursor() as cur:
            cur.execute(
                "INSERT INTO kv (key, value) VALUES ('alerts_geocode', %s::jsonb) "
                "ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, fetched_at=now()",
                (json.dumps(gcache),))
            c.commit()
    except Exception:
        pass
    plotted = sum(1 for a in al if a["lat"] is not None)
    return {"count": len(al), "plotted": plotted,
            "alerts": [a for a in al if a["lat"] is not None][:500],
            "source": "api.weather.gov (NOAA) · areas: geometry + Nominatim"}

@app.get("/api/air")
def air_live():
    d, src_state = _kv_cached("air_live", 600, _fetch_opensky)
    if d is None:
        return {"ok": False, "source": src_state, "count": 0, "aircraft": []}
    return {"ok": True, "source": src_state, "state": src_state, "count": d.get("count"),
            "aircraft": d.get("aircraft", [])}

@app.get("/api/ships")
def ships_live():
    d, src_state = _kv_cached("ships_live", 300, _fetch_ships)
    if d is None:
        return {"ok": False, "source": src_state, "count": 0, "ships": []}
    return {"ok": True, "source": src_state, "state": src_state, "count": d.get("count"),
            "ships": d.get("ships", [])}

@app.get("/api/alerts")
def alerts_live():
    d, src_state = _kv_cached("alerts_live", 300, _fetch_alerts)
    if d is None:
        return {"ok": False, "source": src_state, "count": 0, "alerts": []}
    return {"ok": True, "source": src_state, "state": src_state, "count": d.get("count"),
            "alerts": d.get("alerts", [])}

@app.get("/api/stats")
async def stats():
    """Live under-the-hood numbers for the architecture deck (straight from the DB)."""
    def q(sql, params=None):
        c = psycopg2.connect(**DB)
        try:
            cur = c.cursor()
            # never pass an empty params tuple: it makes psycopg2 interpolate
            # the SQL, which breaks on the bare '%' in LIKE patterns.
            if params:
                cur.execute(sql, params)
            else:
                cur.execute(sql)
            return cur.fetchone()
        finally:
            c.close()
    def n(sql, params=None):
        r = q(sql, params)
        return int(r[0]) if r and r[0] is not None else 0
    try:
        lanes_total = n("SELECT count(*) FROM lanes")
        lanes_air = n("SELECT count(*) FROM lanes WHERE id LIKE 'al-%'")
        lanes_ocean = n("SELECT count(*) FROM lanes WHERE id LIKE 'mt-%'")
        lanes_road = lanes_total - lanes_air - lanes_ocean
        return {
            "tables": n("SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_name NOT LIKE 'spatial_%'"),
            "locations": n("SELECT count(*) FROM locations"),
            "lanes_total": lanes_total,
            "lanes_road": lanes_road,
            "lanes_air": lanes_air,
            "lanes_ocean": lanes_ocean,
            "vehicles": n("SELECT count(*) FROM vehicles"),
            "drivers": n("SELECT count(*) FROM drivers"),
            "shipments": n("SELECT count(*) FROM shipments"),
            "events": n("SELECT count(*) FROM shipment_events"),
            "routes_cached": n("SELECT count(*) FROM routes_cached"),
            "telemetry": n("SELECT count(*) FROM telemetry"),
            "incidents_total": n("SELECT count(*) FROM incidents"),
            "insights": n("SELECT count(*) FROM kv WHERE key LIKE 'insight%'"),
            "components": n("SELECT count(*) FROM components"),
        }
    except Exception as e:
        return {"error": str(e)}


# ════════════════ FULL VEHICLE DATA SHEET (wear, parts, predictions) ════════════════
@app.get("/api/vehicle/{vid}")
def vehicle_sheet(vid: str):
    """Full datasheet for one unit: spec, live telemetry, driver, shipment,
    component wear/health, open incidents and deterministic predictions."""
    with db() as c, c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM vehicles WHERE id=%s", (vid,))
        v = cur.fetchone()
        if not v:
            raise HTTPException(404, "vehicle not found")
        cur.execute("""SELECT s.*, l.id AS lane_id, l.origin AS lane_origin, l.destination AS lane_destination,
                              l.distance_km AS lane_km, l.freeflow_min
                       FROM shipments s JOIN lanes l ON l.id=s.lane_id
                       WHERE s.vehicle_id=%s LIMIT 1""", (vid,))
        shp = cur.fetchone()
        cur.execute("SELECT * FROM drivers WHERE vehicle_id=%s", (vid,))
        drv = cur.fetchone()
        cur.execute("""SELECT name, photo, wear, health, km, last_service, next_service, status, rul_days, est_cost
                       FROM components WHERE vehicle_id=%s ORDER BY health ASC""", (vid,))
        comps = cur.fetchall()
        cur.execute("""SELECT speed_kmh, heading, fuel_pct, engine_temp, cargo_temp, signal_pct, gps_acc_m,
                              ts AS created_at FROM telemetry WHERE vehicle_id=%s
                       ORDER BY ts DESC LIMIT 1""", (vid,))
        tel = cur.fetchone()
        cur.execute("""SELECT id, kind, severity, title, lat, lng, created_at, alt_km, alt_min
                       FROM incidents WHERE affected_vehicle=%s AND resolved_at IS NULL""", (vid,))
        incs = cur.fetchall()
        cur.execute("""SELECT ts, type, note FROM shipment_events WHERE shipment_id IN
                       (SELECT id FROM shipments WHERE vehicle_id=%s)
                       ORDER BY ts DESC LIMIT 12""", (vid,))
        hist = [dict(r) for r in cur.fetchall()]
        # fleet wear context (how this unit compares)
        cur.execute("""SELECT count(*) FILTER (WHERE status='critical') crit,
                              count(*) FILTER (WHERE status='warning') warn
                       FROM components WHERE vehicle_id=%s""", (vid,))
        wsummary = cur.fetchone()
    # ── predictions ──
    speed = (tel or {}).get("speed_kmh") or 0
    remaining_km = None; eta_min = None
    if shp and shp.get("lane_km"):
        eta_min = shp.get("eta_minutes")
        if shp.get("status") == "in_transit" and speed and speed > 5:
            remaining_km = max(0.0, shp.get("eta_minutes", 0) * (speed / 60.0))
    fuel = v.get("fuel_pct") or 0
    rng = v.get("fuel_range_km") or 0
    # fuel margin: range remaining vs route remaining
    fuel_range_left = round(rng * (fuel / 100.0), 0) if rng else None
    fuel_ok = (fuel_range_left is not None and remaining_km is None) or (
        fuel_range_left is not None and remaining_km is not None and fuel_range_left >= remaining_km * 1.05)
    # SLA risk
    sla_risk = "on_time"
    if shp:
        if shp.get("status") in ("rerouted", "delayed") or any(i["severity"] == "P1" for i in incs):
            sla_risk = "breach_risk"
        elif shp.get("eta_minutes") and shp.get("sla_minutes") and shp["eta_minutes"] > shp["sla_minutes"] * 0.95:
            sla_risk = "at_risk"
    worst = comps[0] if comps else None
    # predicted next service date for the worst part
    pred_next = None
    if worst:
        pred_next = worst["next_service"]
    overall = "ok"
    if wsummary and (wsummary["crit"] or 0) > 0: overall = "critical"
    elif wsummary and (wsummary["warn"] or 0) >= 3: overall = "watch"
    return {
        "id": v["id"], "kind": v["kind"], "name": v.get("name") or v["id"],
        "model": v.get("model"), "registered": v.get("registered"),
        "capacity_t": v.get("capacity_t"), "load_t": v.get("load_t"),
        "load_pct": round((v["load_t"] / v["capacity_t"] * 100), 0) if v.get("capacity_t") else None,
        "fuel_pct": fuel, "fuel_range_km": rng, "fuel_range_left_km": fuel_range_left,
        "fuel_ok": fuel_ok,
        "carbon_tco2": v.get("carbon_tco2"),
        "telemetry": {k: tel.get(k) for k in ("speed_kmh", "heading", "fuel_pct", "engine_temp",
                                              "cargo_temp", "signal_pct", "gps_acc_m")} if tel else None,
        "telemetry_at": tel.get("created_at") if tel else None,
        "driver": {k: drv.get(k) for k in ("full_name", "nationality", "license", "license_expiry",
                                           "years_exp", "rating", "trips", "base", "phone", "email", "avatar")} if drv else None,
        "shipment": None if not shp else {
            "id": shp.get("id"), "cargo": shp.get("cargo"), "qty": shp.get("qty"),
            "value_eur": shp.get("value_eur"), "customer": shp.get("customer"),
            "status": shp.get("status"), "eta_minutes": shp.get("eta_minutes"),
            "sla_minutes": shp.get("sla_minutes"), "temp_req": shp.get("temp_req"),
            "origin": shp.get("lane_origin"), "destination": shp.get("lane_destination"),
            "lane_km": shp.get("lane_km"),
        },
        "remaining_km_estimate": round(remaining_km, 0) if remaining_km else None,
        "components": [dict(r) for r in comps],
        "wear_summary": {"critical": wsummary["crit"] or 0, "warning": wsummary["warn"] or 0,
                         "total": len(comps)},
        "incidents_open": [dict(r) for r in incs],
        "history": hist,
        "predictions": {
            "overall": overall,
            "sla_risk": sla_risk,
            "eta_minutes": eta_min,
            "next_service_due": pred_next,
            "worst_part": {"name": worst["name"], "health": worst["health"],
                           "rul_days": worst["rul_days"], "est_cost": worst["est_cost"]} if worst else None,
            "fuel_margin_km": (round(fuel_range_left - remaining_km, 0)
                               if (fuel_range_left and remaining_km is not None) else None),
            "maintenance_cost_30d": int(sum(x["est_cost"] for x in comps if x["rul_days"] <= 30) or 0),
            "note": ("Wear is seeded deterministically per unit; RUL = remaining useful life in days. "
                     "SLA + fuel + wear are re-computed per request against live telemetry.")
        },
    }


# ════════════════ CHAT ACTIONS — the analyst can DO things ════════════════
import re as _re
_UNIT_RE = r"(TRK|PLN|SHI|SHP)-[A-Z0-9]{2,6}"
_LANES_RE = r"(ln|al|mt)-[a-z0-9-]{2,12}"
_LOC_RE = r"(limerick|dublin|cork|rotterdam|amsterdam|antwerp|hamburg|new york|chicago|san jose|round rock|newark)"

def _parse_chat_action(msg: str):
    """Deterministic action parser: the chat can simulate, resolve, zoom, open,
    pause and set speed. Returns {action, ...} or None for a plain question."""
    m = msg.lower()
    r = {}
    unit = _re.search(_UNIT_RE, msg, _re.I)
    unit = unit.group(0).upper() if unit else None
    lane = _re.search(_LANES_RE, msg, _re.I)
    lane = lane.group(0) if lane else None
    loc = _re.search(_LOC_RE, m)
    loc = loc.group(1) if loc else None
    # simulate: explicit "simul..." OR a direct fault command ("leke band op X", "ongeluk op X")
    sim = None
    explicit_sim = _re.search(r"simulat|simulate|simul", m)
    fault_word = ("flat tire" in m or "leke band" in m
                  or ("panne" in m and "flat" not in m) or "breakdown" in m
                  or "accident" in m or "ongeluk" in m)
    if explicit_sim or (fault_word and (unit or lane)):
        if "flat tire" in m or "leke band" in m or ("panne" in m and "flat" not in m):
            sim = "flat_tire"
        elif "breakdown" in m or "panne" in m:
            sim = "maintenance"
        elif "accident" in m or "ongeluk" in m:
            sim = "accident"
        else:
            sim = "accident"
        if not unit and not lane:
            return None
        r = {"action": "simulate", "kind": sim, "vehicle_id": unit, "lane_id": lane}
    # resolve: "los op / resolve / close (INC-xxxx | de incident( )? op unit)"
    inc = _re.search(r"(INC)-([A-Z0-9]{8})", msg, _re.I)
    if (_re.search(r"resolve|oplossen|close the|los \S+ op|los op", m) or ("los" in m and "op" in m and (inc or unit))) and (inc or unit):
        r = {"action": "resolve", "incident_id": (inc.group(1) + "-" + inc.group(2)).upper() if inc else None,
             "vehicle_id": unit}
    # zoom / fly / show
    if _re.search(r"\bzoom|fly|show|toon|vlieg|focus|center|centreren", m) and (unit or lane or loc):
        r = {"action": "zoom", "vehicle_id": unit, "lane_id": lane, "location": loc}
    # open details
    if _re.search(r"\bopen|detail|geef (de |deze |die )?(data|fiche|sheet)", m) and unit:
        r = {"action": "open", "vehicle_id": unit}
    # pause / resume sim
    if _re.search(r"pause|pauze|stop the sim|stilleggen", m):
        r = {"action": "pause"}
    if _re.search(r"resume|ga door|continue the sim", m):
        r = {"action": "resume"}
    # speed
    sp = _re.search(r"(\d+(?:[.,]\d+)?)\s*[x×]\b", m) or _re.search(
        r"(?:speed|snelheid|tempo|timescale)\D{0,8}?(\d+(?:[.,]\d+)?)", m)
    if sp:
        val = float(sp.group(1).replace(",", "."))
        if val in (0.1, 0.2, 0.3, 0.5, 1, 4, 16):
            r = {"action": "speed", "value": val}
    return r or None

async def _execute_chat_action(r: dict):
    """Execute a parsed chat action against the API. Returns {summary, payload}."""
    out = {"summary": None, "payload": None}
    if r["action"] == "simulate":
        lane_id = r.get("lane_id")
        if not lane_id:
            # resolve the unit's current lane
            with db() as c, c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""SELECT s.lane_id FROM shipments s WHERE s.vehicle_id=%s
                               LIMIT 1""", (r["vehicle_id"],))
                row = cur.fetchone()
            lane_id = row["lane_id"] if row else None
        if not lane_id:
            return {"summary": f"Could not find a lane for {r.get('vehicle_id')}.", "payload": None}
        try:
            res = await create_incident(IncidentIn(lane_id=lane_id, vehicle_id=r.get("vehicle_id"),
                                                   kind=r["kind"], severity="P1" if r["kind"] == "accident" else "P2"))
            out["summary"] = (f"Simulated {r['kind']} · {res['id']} on {lane_id}"
                              + (f" · +{res['delta_km']} km reroute" if res.get("delta_km") else f" · +{int(res.get('delta_min') or 0)} min delay"))
            out["payload"] = res
        except HTTPException as e:
            out["summary"] = f"Simulation failed: {e.detail}"
    elif r["action"] == "resolve":
        iid = r.get("incident_id")
        if not iid:
            with db() as c, c.cursor() as cur:
                cur.execute("""SELECT id FROM incidents WHERE affected_vehicle=%s
                               AND resolved_at IS NULL ORDER BY created_at DESC LIMIT 1""",
                            (r.get("vehicle_id"),))
                row = cur.fetchone()
                iid = row[0] if row else None
        if not iid:
            return {"summary": "No open incident found to resolve.", "payload": None}
        try:
            res = resolve_incident(iid)
            out["summary"] = f"Resolved {iid} · route restored."
            out["payload"] = {"resolved": iid}
        except HTTPException as e:
            out["summary"] = f"Resolve failed: {e.detail}"
    # zoom/open/pause/resume/speed are UI actions — the API only reports them
    else:
        target = r.get("vehicle_id") or r.get("lane_id") or r.get("location") or r.get("value")
        out["summary"] = "UI action queued: " + r["action"] + (f" {target}" if target else "")
        out["payload"] = r
    return out

@app.post("/api/chat/action")
async def chat_action_endpoint(payload: dict):
    """Fast deterministic action channel: parse a chat message and execute it.
    simulate/resolve run against the DB; zoom/open/pause/speed are returned
    for the UI to apply. Plain questions return {action: null}."""
    msg = (payload.get("message") or "").strip()
    if not msg:
        return {"action": None}
    r = _parse_chat_action(msg)
    if not r:
        return {"action": None, "summary": None, "payload": None}
    res = await _execute_chat_action(r)
    res["action"] = r["action"]
    return res


# ════════════════ FLEET PREDICTIONS ════════════════
@app.get("/api/predictions")
def fleet_predictions():
    """Predictive view across the fleet: per unit — SLA risk, fuel margin,
    worst part (wear/RUL/cost), overall health. One query, no LLM."""
    with db() as c, c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            WITH comp AS (
                SELECT vehicle_id, name, health, rul_days, est_cost, status,
                       ROW_NUMBER() OVER (PARTITION BY vehicle_id ORDER BY health ASC) rn
                FROM components
            )
            SELECT v.id, v.kind, v.model, v.fuel_pct, v.fuel_range_km,
                   s.lane_id, l.origin AS lane_origin, l.destination AS lane_destination,
                   s.status AS shipment_status, s.eta_minutes, s.sla_minutes,
                   t.speed_kmh, t.engine_temp,
                   comp.name AS worst_part, comp.health AS worst_health,
                   comp.rul_days AS worst_rul, comp.est_cost AS worst_cost,
                   comp.status AS worst_status
            FROM vehicles v
            LEFT JOIN shipments s ON s.vehicle_id = v.id
            LEFT JOIN lanes l ON l.id = s.lane_id
            LEFT JOIN telemetry t ON t.vehicle_id = v.id
                             AND t.ts = (SELECT max(ts) FROM telemetry t2 WHERE t2.vehicle_id = v.id)
            LEFT JOIN comp ON comp.vehicle_id = v.id AND comp.rn = 1
            ORDER BY comp.health ASC NULLS LAST
        """)
        rows = cur.fetchall()
    out = []
    for r in rows:
        speed = r.get("speed_kmh") or 0
        eta = r.get("eta_minutes")
        remaining_km = max(0.0, eta * (speed / 60.0)) if (eta and speed > 5) else None
        fuel_left = round((r["fuel_range_km"] or 0) * (r["fuel_pct"] or 0) / 100.0) if r.get("fuel_range_km") else None
        fuel_margin = round(fuel_left - remaining_km) if (fuel_left and remaining_km is not None) else None
        # SLA risk
        if r.get("shipment_status") in ("rerouted", "delayed"):
            sla = "breach_risk"
        elif eta and r.get("sla_minutes") and eta > r["sla_minutes"] * 0.95:
            sla = "at_risk"
        elif fuel_margin is not None and fuel_margin < 0:
            sla = "fuel_risk"
        else:
            sla = "on_time"
        # overall health score (0-100)
        wh = r.get("worst_health")
        overall = int(max(0, min(100, (wh or 100) * 0.6 + (r["fuel_pct"] or 0) * 0.25
                                 + (25 if sla == "on_time" else 0) * 0.6)))
        out.append({
            "id": r["id"], "kind": r["kind"], "model": r.get("model"),
            "lane": r.get("lane_id"), "from": r.get("lane_origin"), "to": r.get("lane_destination"),
            "speed": round(speed, 1) if speed else None, "engine": r.get("engine_temp"),
            "fuel_pct": r.get("fuel_pct"), "fuel_left_km": fuel_left,
            "remaining_km": round(remaining_km) if remaining_km is not None else None,
            "fuel_margin_km": fuel_margin,
            "eta_min": eta, "sla_min": r.get("sla_minutes"),
            "sla_risk": sla,
            "worst_part": r.get("worst_part"), "worst_health": wh,
            "worst_rul_days": r.get("worst_rul"), "worst_cost": r.get("worst_cost"),
            "worst_status": r.get("worst_status"),
            "health_score": overall,
        })
    # summary
    crit = sum(1 for o in out if o["worst_status"] == "critical")
    warn = sum(1 for o in out if o["worst_status"] == "warning")
    risk = sum(1 for o in out if o["sla_risk"] != "on_time")
    maint30 = sum(o["worst_cost"] or 0 for o in out if (o["worst_rul_days"] or 999) <= 30)
    return {"units": out, "summary": {"fleet": len(out), "critical_parts": crit,
                                      "warning_parts": warn, "sla_risk": risk,
                                      "maintenance_cost_30d": maint30}}
