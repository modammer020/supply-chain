#!/usr/bin/env python3
"""AEGIS dedicated data agent.

Role: dedicated real-time agent for the AEGIS supply-chain command center.
Every cycle it:
  1. Pulls real-time state from the AEGIS API (overview, incidents, traffic).
  2. Builds a compact operational briefing (KPIs, SLA risk, exceptions,
     inventory, worst lanes).
  3. Invokes the Hermes 'researcher' bot (the analyst bot the user added to
     Hermes) with a clear mandate: ANALYZE the situation CONTINUOUSLY and
     produce prioritized RECOMMENDATIONS for the control room.
  4. Stores the bot's output (JSON) so the UI's ANALYST panel can render it.

The researcher bot is told, every cycle, that it is a standing analyst:
it must keep analyzing (the loop runs continuously), flag what changed,
and always end with concrete, actionable recommendations.

Run:   python agents/watcher.py [--interval 180] [--api http://127.0.0.1:8300]
"""
import argparse
import json
import os
import re as _re
import subprocess
import sys
import time
from datetime import datetime, timezone

import httpx

API = "http://127.0.0.1:8300"
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
INSIGHTS_FILE = os.path.join(ROOT, "data", "insights.jsonl")
LOCK_FILE = os.path.join(ROOT, "data", "watcher.lock")
HERMES_BIN = os.path.expanduser("~/.local/bin/hermes")
if not os.path.exists(HERMES_BIN):
    HERMES_BIN = "hermes"
RESEARCHER_TIMEOUT = 240  # s — LLM cycle budget

# ─────────────────────────────────────────────────────────────────────
# MANDATE — the clear, repeated description of what the researcher bot
# must do. Sent verbatim with every cycle's briefing.
# ─────────────────────────────────────────────────────────────────────
MANDATE = """You are AEGIS-ANALYST, the standing supply-chain analyst for the AEGIS control center.
You are invoked once per monitoring cycle by a dedicated real-time data agent.
Your loop runs continuously — each briefing is a NEW snapshot of the same live operation.
ALWAYS write in English.

YOUR MANDATE (every cycle, without exception):
1. ANALYZE the operational state below: fleet position/SLA, lanes & congestion,
   open incidents, inventory risk, KPI movement.
2. Compare with the PREVIOUS snapshot (provided when available): what CHANGED,
   what is degrading, what improved.
3. RECOMMEND: give 2-5 concrete, prioritized actions for the dispatcher
   (who/what/why/expected effect). Be specific to the data (lane ids, vehicle
   ids, SKUs) — no generic advice.
4. ESCALATE: if anything is P1 (SLA breach on high-value shipment, engine
   overheat, fuel critical), say so first, in one line, prefixed with "ESCALATE:".

OUTPUT — STRICT JSON ONLY, no prose outside the JSON, no markdown fences:
{"summary": "<one line: overall state of the operation>",
 "changes": ["<what changed since previous cycle>", ...],
 "risks": [{"id":"R1","title":"...","severity":"P1|P2|P3","detail":"..."}],
 "recommendations": [{"action":"...","target":"<vehicle/lane/sku id>","why":"...","impact":"..."}],
 "kpi_view": {"otif_pct": <num or null>, "value_in_transit_eur": <num or null>, "note": "<trend>"}}
"""

PREV_FILE = os.path.join(ROOT, "data", "last_briefing.json")


def now_iso():
    return datetime.now(timezone.utc).strftime("%H:%M:%S")


def log(msg):
    print(f"[{now_iso()}] {msg}", flush=True)


# ── 1. Pull real-time data from the API ──────────────────────────────
def pull_state(api):
    t0 = time.time()
    with httpx.Client(timeout=20) as c:
        ov = c.get(f"{api}/api/overview").json()
        inc = c.get(f"{api}/api/incidents").json()
        tr = c.get(f"{api}/api/traffic").json()
    log(f"pulled state in {time.time()-t0:.1f}s: "
        f"{len(ov['shipments'])} shipments, {len(ov['vehicles'])} vehicles, "
        f"{len(inc)} open incidents, kpi.otif={ov['kpi']['otif_pct']}")
    return ov, inc, tr


# ── 1b. Limerick watch (standing user directive: keep current on Limerick, IE) ──
LIMERICK_HUBS = ("c-lim", "d-csc-lim")
LIMERICK_NOTE = ("LIMERICK WATCH (standing directive from the operator): "
                 "Include a short LIMERICK section in your summary/risks every cycle: "
                 "current weather/conditions at Limerick (Shannon River, Munster), "
                 "any operational impact on the EMEA corridor (Dublin–Limerick–Shannon), "
                 "and whether the Dell Limerick EMEA campus is affected. If data is thin, "
                 "say so and what to verify next.")


def limerick_watch(api):
    """Live Limerick snapshot: weather + ops + inventory touching Limerick."""
    out = {"ts": now_iso(), "hubs": [], "shipments": [], "inventory": [], "weather": None}
    try:
        with httpx.Client(timeout=10) as c:
            wx = c.get(f"{api}/api/weather").json()
            for h in wx.get("hubs", []):
                if h.get("id") in LIMERICK_HUBS or "lim" in str(h.get("id", "")).lower():
                    out["hubs"].append(h)
            ov = c.get(f"{api}/api/overview").json()
            lanes = {l["id"]: l for l in ov.get("lanes", [])}
            locs = {l["id"]: l for l in ov.get("locations", []) if l.get("id") in LIMERICK_HUBS}
            for s in ov.get("shipments", []):
                l = lanes.get(s.get("lane_id")) or {}
                if l.get("origin") in LIMERICK_HUBS or l.get("destination") in LIMERICK_HUBS:
                    out["shipments"].append({
                        "id": s["id"], "vehicle": s["vehicle_id"], "status": s["status"],
                        "cargo": s.get("cargo"), "value_eur": s.get("value_eur"),
                        "origin": locs.get(l.get("origin"), {}).get("name", l.get("origin")),
                        "destination": locs.get(l.get("destination"), {}).get("name", l.get("destination")),
                    })
            for inv in ov.get("inventory", []):
                if "lim" in str(inv.get("hub_id", "")).lower() or inv.get("hub_name", "").lower().startswith("lim"):
                    out["inventory"].append(inv)
        # direct live weather call (keyless) for the Limerick coordinates
        try:
            with httpx.Client(timeout=6) as c:
                r = c.get("https://api.open-meteo.com/v1/forecast",
                          params={"latitude": "52.6541", "longitude": "-8.7228",
                                  "current": "temperature_2m,wind_speed_10m,relative_humidity_2m,weather_code",
                                  "timezone": "auto"})
                r.raise_for_status()
                out["weather"] = r.json().get("current", {})
        except Exception as e:
            out["weather_error"] = str(e)
        log(f"limerick watch: {len(out['hubs'])} hubs, {len(out['shipments'])} shipments, "
            f"{len(out['inventory'])} inv, weather={'ok' if out['weather'] else 'sim'}")
    except Exception as e:
        out["error"] = f"limerick watch failed: {e}"
        log(f"limerick watch error: {e}")
    return out


# ── 2. Build the compact briefing ────────────────────────────────────
def build_briefing(ov, inc, tr, prev):
    k = ov["kpi"]
    # SLA-risky shipments (eta beyond sla)
    risky = []
    for s in ov["shipments"]:
        if s["status"] in ("in_transit", "rerouted", "delayed"):
            delta = (s.get("eta_minutes") or 0) - (s.get("sla_minutes") or 0)
            if delta > 0 or s["status"] != "in_transit":
                risky.append(
                    f"{s['id']} {s['vehicle_id']} {s['status']} "
                    f"eta+{max(delta,0)}min vs SLA ({s['origin']}→{s['destination']}) "
                    f"cargo={s['cargo']} value=€{int(s.get('value_eur') or 0):,}")
    # worst lanes by congestion
    worst_traffic = sorted(tr["lanes"], key=lambda x: -x["index"])[:5]
    worst_traffic_s = ", ".join(f"{t['lane_id']}={t['state']}({int(t['index']*100)}%)"
                                for t in worst_traffic)
    # low stock
    low = [i for i in ov["inventory"] if i["stock"] < i["reorder"]]
    low_s = ", ".join(f"{i['sku']}@{i['hub_name']}={i['stock']}/{i['reorder']}({i['units']})"
                      for i in low[:6]) or "none"
    # open incidents
    inc_s = "; ".join(f"{i['id']} {i['severity']} {i['title']} "
                      f"(alt +{i['alt_km']}km/+{i['alt_min']}min, vehicle {i['affected_vehicle']})"
                      for i in inc[:5]) or "none open"
    # previous-cycle KPI delta
    kpi_note = "first cycle"
    if prev:
        d_otif = round(k["otif_pct"] - prev.get("otif_pct", 0), 1)
        kpi_note = f"OTIF delta since last cycle: {d_otif:+.1f}pp"

    b = {
        "ts": now_iso(),
        "kpi": {
            "units": k["units"], "trucks": k["trucks"], "ships": k["ships"],
            "otif_pct": k["otif_pct"], "value_in_transit_eur": int(k["value_in_transit"]),
            "active_shipments": k["active_shipments"], "delayed": k["delayed"],
            "incidents_open": k["incidents"], "low_stock_skus": k["low_stock_skus"],
            "co2_t": k["carbon_tco2"], "weekly_demand_units": int(k["weekly_demand_units"]),
        },
        "sla_risky_shipments": risky[:12],
        "worst_congestion": worst_traffic_s,
        "low_stock": low_s,
        "open_incidents": inc_s,
        "weather_source": ov.get("weather", {}).get("source"),
        "conditions_source": ov.get("conditions", {}).get("source"),
        "traffic_source": tr.get("source"),
        "prev_kpi_note": kpi_note,
    }
    return b


# ── 3. Invoke the Hermes researcher bot (the analyst) ────────────────
def invoke_researcher(briefing, prev):
    prev_s = json.dumps(prev, indent=1) if prev else "(none — first cycle)"
    prompt = (
        MANDATE
        + "\n\n" + LIMERICK_NOTE
        + "\n\nPREVIOUS CYCLE STATE (for comparison):\n" + prev_s
        + "\n\nCURRENT LIVE BRIEFING (UTC " + briefing["ts"] + "):\n"
        + json.dumps(briefing, indent=1)
        + "\n\nAnalyze now and return the JSON."
    )
    cmd = [HERMES_BIN, "-p", "researcher", "chat",
           "-q", prompt, "--oneshot", "-Q", "--max-turns", "4"]
    log("invoking researcher bot (hermes -p researcher)…")
    t0 = time.time()
    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=RESEARCHER_TIMEOUT, cwd=ROOT)
        out = (p.stdout or "").strip()
        # hermes prints the answer then a session line; take the payload
        lines = out.splitlines()
        payload = "\n".join(l for l in lines if not l.startswith("session_id"))
        log(f"researcher responded in {time.time()-t0:.1f}s ({len(payload)} chars)")
        return parse_insight(payload), None
    except subprocess.TimeoutExpired:
        return None, "researcher bot timed out"
    except Exception as e:
        return None, f"researcher invocation failed: {e}"


def _unwrap(v, depth=3):
    """Recursively unwrap JSON that the bot double/triple-encodes as strings."""
    for _ in range(depth):
        if isinstance(v, str):
            try:
                v = json.loads(v)
            except (json.JSONDecodeError, ValueError):
                return v
        else:
            return v
    return v


def parse_insight(payload):
    """Extract the strict-JSON insight from the bot's response.

    Handles every encoding the bot has been observed to emit:
      A. plain JSON object
      B. whole object double-encoded as a JSON *string* ("{\\\"summary\\\":...}")
      C. markdown-fence wrapped
      D. `summary` itself being a JSON string
    """
    if not payload:
        return None
    txt = payload.strip()
    if txt.startswith("```"):
        txt = txt.split("\n", 1)[1]
        if "```" in txt:
            txt = txt.rsplit("```", 1)[0]
    txt = txt.strip()

    # Candidate parse sites, in order of preference.
    candidates = []
    try:
        candidates.append(json.loads(txt))               # whole payload is JSON
    except (json.JSONDecodeError, ValueError):
        pass
    dec = json.JSONDecoder()
    for idx in (txt.find("{"), txt.find('"')):
        if idx == -1:
            continue
        try:
            val, _ = dec.raw_decode(txt[idx:])
            candidates.append(val)
        except (json.JSONDecodeError, ValueError):
            continue

    for cand in candidates:
        v = _unwrap(cand)
        if isinstance(v, dict) and "summary" in v:
            # normalize: summary may itself be a JSON string (shape D)
            s = _unwrap(v.get("summary"))
            if isinstance(s, dict):
                v = {**s, **{k: val for k, val in v.items() if k != "summary"}}
            v.setdefault("summary", "")
            v.setdefault("changes", [])
            v.setdefault("risks", [])
            v.setdefault("recommendations", [])
            v.setdefault("kpi_view", {})
            v.setdefault("ts", now_iso())
            return v
    # salvage: the bot sometimes emits truncated JSON. Recover the fields we
    # can via targeted regexes so the panel never looks dead.
    def _arr(key):
        # best-effort: pull a JSON array literal for `key` out of raw text
        m = _re.search(r'"%s"\s*:\s*\[' % _re.escape(key), txt)
        if not m:
            return None
        start = txt.index('[', m.start())
        depth = 0; in_str = False; esc = False; end = start
        for i in range(start, len(txt)):
            ch = txt[i]
            if in_str:
                if esc: esc = False
                elif ch == '\\': esc = True
                elif ch == '"': in_str = False
            else:
                if ch == '"': in_str = True
                elif ch == '[': depth += 1
                elif ch == ']':
                    depth -= 1
                    if depth == 0:
                        end = i; break
        try:
            return json.loads(txt[start:end+1])
        except (json.JSONDecodeError, ValueError):
            return None
    summary_m = _re.search(r'"summary"\s*:\s*"(.*?)(?<!\\)"', txt, _re.S)
    summary = summary_m.group(1).replace('\\"', '"').replace('\\n', ' ') if summary_m else txt[:300]
    salv = {"summary": summary, "recommendations": _arr("recommendations") or [],
            "risks": _arr("risks") or [], "changes": _arr("changes") or [],
            "kpi_view": {"note": "recovered-from-fragment"}}
    if not any(salv[k] for k in ("recommendations", "risks", "changes")):
        salv["kpi_view"]["note"] = "unparsed"
    return salv


# ── 4. Persist for the UI ────────────────────────────────────────────
def persist(briefing, insight, error, api_ok):
    os.makedirs(os.path.dirname(INSIGHTS_FILE), exist_ok=True)
    rec = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "briefing": briefing,
        "insight": insight,
        "error": error,
        "api_ok": api_ok,
        "agent": "aegis-watcher",
        "analyst": "hermes:researcher",
    }
    with open(INSIGHTS_FILE, "a") as f:
        f.write(json.dumps(rec) + "\n")
    if briefing:
        with open(PREV_FILE, "w") as f:
            json.dump(briefing.get("kpi", {}), f)


# ── cycle ────────────────────────────────────────────────────────────
def cycle(api):
    os.makedirs(os.path.dirname(LOCK_FILE), exist_ok=True)
    try:
        lock = os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL)
    except FileExistsError:
        log("another watcher cycle running — skipping")
        return
    os.close(lock)
    open(LOCK_FILE, "w").write(str(os.getpid()))
    try:
        api_ok = False
        prev = None
        if os.path.exists(PREV_FILE):
            try:
                prev = json.load(open(PREV_FILE))
            except Exception:
                prev = None
        briefing, insight, error = None, None, None
        try:
            ov, inc, tr = pull_state(api)
            api_ok = True
            briefing = build_briefing(ov, inc, tr, prev)
            briefing["limerick"] = limerick_watch(api)
            insight, error = invoke_researcher(briefing, prev)
        except Exception as e:
            error = f"API pull failed: {e}"
            log(error)
        persist(briefing, insight, error, api_ok)
        if insight:
            log(f"insight: {insight.get('summary', '')[:120]} "
                f"({len(insight.get('recommendations', []))} recommendations)")
        else:
            log(f"no insight this cycle: {error}")
    finally:
        if os.path.exists(LOCK_FILE):
            os.unlink(LOCK_FILE)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=int, default=180)
    ap.add_argument("--api", default=API)
    args = ap.parse_args()
    log(f"AEGIS watcher starting (interval={args.interval}s, api={args.api})")
    while True:
        cycle(args.api)
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
