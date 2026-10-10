# AEGIS — Supply-Chain Command Center v3

Spec-driven (spec-kit) realtime command center. Single source of truth: PostGIS.
Frontend: één HTML-bestand, API-gedreven. Keyless (ESRI tiles, OSRM, Open-Meteo, AIS).

## Starten (één commando per service)

```bash
cd /home/demouser/aegis

# 1. Database (PostGIS 16, port 5433)
podman compose up -d

# 2. API (FastAPI, port 8300)
.venv/bin/uvicorn api:app --host 127.0.0.1 --port 8300

# 3. Frontend (open in browser)
python3 -m http.server 8765 --bind 127.0.0.1     # vanuit /home/demouser
# → http://127.0.0.1:8765/aegis/web/index.html

# 4. Dedicated analyst agent (watcher + hermes researcher-bot), elke 3 min
.venv/bin/python agents/watcher.py --interval 180
```

## Architectuur
- **DB**: `aegis_db` (Podman, PostGIS 16-3.4, port 5433) — locations, lanes, vehicles,
  shipments, telemetry, inventory, incidents, shipment_events, kv-cache, routes_cached.
- **API** (`api.py`): `/api/overview` (bootstrap), `/api/route/{lane}` (OSRM + alternatieven,
  gedecodeerde Polyline6, dag-cache in PostGIS), `/api/incidents` (ongeluk-sim + OSRM-omleiding
  met delta_km/min), `/api/traffic` (deterministische per-lane congestion), `/api/weather`
  (Open-Meteo, kv-cache), `/api/conditions`, `/api/telemetry` (push), `/api/insights`
  (analyst-cycli).
- **Frontend** (`web/index.html`): Leaflet + ESRI sateliet/street/hybrid (neon-cyan theming),
  8-tile KPI-wall, tabs (Analyst / Exception / Lanes / Fleet / Inventory / Maritime / Weather),
  OSRM-route-trails, delta-time simulatie (1×/4×/16×/pauze), detail-drawer (telemetrie-sparklines,
  documenten, route-timeline, CALL DRIVER, SIM ACCIDENT + accept-reroute), minimap + viewbox,
  graticule, measure-tool, search, road-conditions layer.
- **Dedicated agent** (`agents/watcher.py`): polt de API realtime, bouwt een operationele
  briefing, roept de hermes **researcher**-bot aan met een standing-analyst-mandaat
  (continu analyseren, wijzigingen flaggen, prioriterende recommendaties, ESCALATE bij P1).
  Output → `data/insights.jsonl` → `/api/insights` → ANALYST-paneel in de UI.

## Spec
- Constitution: `.specify/memory/constitution.md` (4 principes: Demo-First/Real-Data-Ready,
  Single Source of Truth, Spec-Driven, Open & Keyless).
- Feature 001: `specs/001-command-center/{spec,plan,tasks}.md` — M1–M4 taken afgevinkt.

## Swap naar real data
- Telemetrie: `POST /api/telemetry` is de connector — wijs de echte GPS/telemetrie-pipeline
  daar op (schema = wat de demo schrijft).
- WebRTC: `openCall()` in de frontend is demo (mic-viz + gesynthetiseerde far-end);
  `REAL WEBRTC INTEGRATION` = RTCPeerConnection + EU-edge SFU.
- Traffic: deterministisch per-lane model; keyless live-feed niet beschikbaar
  (HERE/TomTom = auth; OpenConditions = geen live data). Vervang in `traffic()`/`conditions()`.
