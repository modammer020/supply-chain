# AEGIS Constitution

## Core Principles

### I. Demo-First, Real-Data-Ready
The UI MUST open and work end-to-end on first load without user setup. All live
data sources (OSRM routing, Open-Meteo weather, road-condition feeds) MUST
degrade gracefully to deterministic synthetic data when unreachable, with a
visible badge indicating LIVE / CACHED / SIM. No feature may hard-fail on a
missing external source.

### II. Single Source of Truth
All supply-chain state MUST live in PostgreSQL + PostGIS (the `aegis` database).
The frontend is a stateless consumer of the FastAPI layer; no business state may
be invented in the browser. The simulation engine writes telemetry into the same
database so the UI reflects what a real GPS pipeline would write.

### III. Spec-Driven Development (NON-NEGOTIABLE)
Features are developed via the Spec Kit workflow: Constitution → Spec → Plan →
Tasks → Implementation. Every non-trivial capability ships with its spec
section, a plan section, and verifiable acceptance criteria (tasks with `VER`
checks). No feature is considered done until its acceptance criteria pass.

### IV. Open & Keyless
Prefer free, keyless data sources (ESRI imagery, OSRM/OpenStreetMap routing,
Open-Meteo, public road-condition feeds, public AIS). Where a real feed is
unavailable in the demo environment, a clearly-marked deterministic simulation
stands in — never silent fake data.

### V. Geospatial Correctness
All geometry is WGS84 (EPSG:4326) in PostGIS. Polylines decode to [lon, lat].
Map rendering MUST be verified against known city coordinates; a route that
starts in the wrong hemisphere is a build-breaking bug.

### VI. Rich, Professional UX
Dark control-room theme (deep navy, cyan accent, amber/magenta/green status
semantics), consistent typography (Rajdhani display / JetBrains Mono data),
responsive to 1280px+. Every panel shows real numbers from the database; no
hardcoded demo figures in the UI layer. Visuals communicate state (status
colors, pulses on exceptions) — decoration is minimal.

### VII. Performance & Scale
The UI must remain smooth with 30+ moving units: marker updates batched per
animation frame, routes pre-fetched and cached (PostGIS `routes_cached` with
daily TTL), tiles from multiple keyless providers selectable at runtime.

## Technical Constraints

- **Runtime**: Python 3.14 venv (`aegis/.venv`), FastAPI + uvicorn, psycopg2-binary.
- **Data**: PostgreSQL 16 + PostGIS 3.4 in Podman (`aegis_db`), port 5433.
- **Frontend**: single-file `web/index.html` — Leaflet 1.9.4 (unpkg), no build
  step, no framework. Served statically.
- **Routing**: OSRM public demo server via FastAPI proxy (client never calls OSRM
  directly); fallback to straight-line geometry when unreachable.
- **Traffic**: keyless live road-conditions feed (DATEX-II/GeoJSON) via FastAPI
  proxy; deterministic per-lane congestion model as fallback.
- **Deployment**: Podman Compose (`compose.yaml`) — one container for the DB;
  API server runs on the host (dev) and MUST be startable with one command.

## Domain Rules (Supply-Chain)

- **OTIF** (On-Time-In-Full) is the headline service KPI, computed per lane.
- Shipments follow the standard lifecycle: `loading → in_transit →
  (delayed|rerouted) → delivered`, with event history stored per shipment.
- Every lane exposes: distance, freeflow time, live congestion index, OTIF,
  volume, and ≥1 alternative route geometry.
- Incidents carry severity (P1/P2/P3), affected vehicle, recommended alternate
  route (computed via OSRM, not invented), and an explicit cost delta (km/min).
- KPI wall covers: OTIF, value-in-transit, fleet size (trucks/ship split),
  exceptions open, low-stock SKUs, CO₂, weekly demand velocity.
- Inventory shows days-of-cover per SKU (stock / velocity) with reorder alerts.

## Governance

- Constitution supersedes all other practices; amendments require a version
  bump documented in the accompanying spec artifact.
- Principles are ordered by priority: when in conflict, I wins over II, II
  over III, etc.

**Version**: 1.0.0 | **Ratified**: 2026-10-08 | **Last Amended**: 2026-10-08
