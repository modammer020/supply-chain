# Feature Spec: AEGIS Supply-Chain Control Center

**Input**: A full supply-chain command center: a tactical map with real
satellite/street/transport basemaps, live moving truck + vessel fleet, per-lane
OTIF and KPI wall, live traffic/road-conditions, incident simulation with
OSRM-computed alternate routes, inventory/stock position, shipment lifecycle
with documents, and a rich detail view — all backed by PostGIS via FastAPI,
presented in a dark control-room UI.

**Testability**: every requirement below is verifiable via the API
(`http://127.0.0.1:8300`), the database, or the rendered page. Markers are
verified at known city coordinates.

---

## User Scenarios

### Scenario 1 — Operator opens the command center
1. User opens `web/index.html`.
2. Basemap is ESRI satellite with a dark color-grade; road/label layers overlay.
3. The KPI wall populates from `/api/kpi` (units, OTIF, value-in-transit,
   exceptions, low-stock, CO₂, demand).
4. All 20 locations render as hub/destination markers at their real coordinates.
5. 22 trucks + 10 vessels appear on their OSRM-fetched lane routes and begin
   moving at a calm, visible pace.
**Priority**: P0. **Why**: first impression; must look real and work instantly.

### Scenario 2 — Planner watches lanes and finds a slow corridor
1. User opens the Lanes tab.
2. Each lane shows distance, freeflow time, live congestion index + state, OTIF,
   weekly volume.
3. Lanes are sortable; the worst-OTIF lanes float to the top.
4. Clicking a lane draws its primary route (OSRM) on the map and loads its
   alternative routes from cache.
**Priority**: P0.

### Scenario 3 — Dispatcher simulates an accident and gets a re-route
1. User selects a truck and triggers "Simulate accident" (P1).
2. System records the incident in PostGIS, marks the shipment `rerouted`,
   computes an OSRM alternate corridor, and returns a recommendation with
   +km / +min delta.
3. The incident renders on the map with a pulsing marker; the alternate route
   draws in amber; the truck animates onto the alternate route.
4. Dispatcher resolves the incident → shipment returns to `in_transit`.
**Priority**: P0. **Why**: the flagship demo capability.

### Scenario 4 — Analyst inspects a shipment end-to-end
1. User clicks a truck/ship → detail panel opens.
2. Detail shows: vehicle + driver, cargo, customer, value, lane, ETA vs SLA,
   live telemetry (speed, fuel, engine, cargo temp, signal, GPS accuracy) with
   90s sparklines, and a document strip (PO / ASN / BOL / customs status).
3. A route timeline shows departure, checkpoints, ETA, and incident events.
**Priority**: P1.

### Scenario 5 — Buyer reviews inventory position
1. User opens the Inventory tab.
2. Each SKU shows hub, stock vs reorder point, days-of-cover (stock/velocity),
   and a low-stock flag.
3. Low-stock SKUs are highlighted and surfaced on the KPI wall.
**Priority**: P1.

### Scenario 6 — Operator switches basemap + layers
1. User toggles basemap: Satellite ↔ Street (OSM) ↔ Hybrid.
2. User toggles overlays: routes, trails, graticule, road-conditions, incidents.
3. Map color-grade stays consistent with the theme in all modes.
**Priority**: P1.

### Scenario 7 — Traffic layer shows live road conditions
1. Road-conditions feed (keyless DATEX-II/GeoJSON) is proxied by the API.
2. Congestion/incident points render on the map within the current bounds.
3. If the live feed is unreachable, a deterministic per-lane congestion model
   fills in and a SIM badge shows.
**Priority**: P2.

### Scenario 8 — Time control and search
1. Time control (pause / 1× / 4× / 16×) drives the simulation speed; delta-time
   keeps pace consistent regardless of frame rate.
2. Search filters fleet by ID, cargo, hub, or destination.
**Priority**: P1.

---

## Functional Requirements

### Data & API
- **FR-001**: `/api/overview` returns locations, lanes, vehicles, shipments,
  inventory, kpi, incidents, traffic in one call (bootstrap payload).
- **FR-002**: `/api/route/{lane_id}` returns ≥2 route variants (primary +
  alternatives) with GeoJSON geometry, distance_km, duration_min, and a
  `source` of `cache`|`live`; caches in `routes_cached` (daily TTL); falls back
  to a straight 2-point line if OSRM is unreachable.
- **FR-003**: `/api/traffic` returns per-lane congestion `index` (0..1),
  `state` (free/moderate/busy/jammed), and `est_factor`, with a `source`
  (LIVE|SIM).
- **FR-004**: `POST /api/incidents` accepts lane, vehicle, kind, severity, frac;
  computes an OSRM alternate route; persists to PostGIS; returns a
  recommendation with `delta_km`, `delta_min`, `alternative_geometry`; sets the
  affected shipment to `rerouted`.
- **FR-005**: `POST /api/incidents/{id}/resolve` clears the incident and returns
  the shipment to `in_transit`.
- **FR-006**: `POST /api/telemetry` appends a GPS/sensor point per vehicle with
  PostGIS geometry.
- **FR-007**: `/api/kpi` computes OTIF (lane avg), value-in-transit, fleet
  split, exceptions open, low-stock SKUs, CO₂, weekly demand from the DB.
- **FR-008**: All polylines decode from Polyline6 with the 63-offset and
  zigzag (verified: Rotterdam→Berlin start≈[4.48,51.92], end≈[13.41,52.52]).

### Domain model (PostGIS)
- **FR-009**: `locations` (hubs/ports/cities) with PostGIS point geometry.
- **FR-010**: `lanes` origin→destination with distance_km, freeflow_min,
  otif_pct, volume.
- **FR-011**: `vehicles` trucks + ships with model, capacity/load, fuel, carbon.
- **FR-012**: `shipments` tied to vehicle+lane with cargo, value_eur, customer,
  status lifecycle, eta_minutes, sla_minutes, customs, temp_req, and a
  `shipment_events` history table.
- **FR-013**: `telemetry` time-series with PostGIS point geometry, indexed by
  (vehicle_id, ts desc).
- **FR-014**: `incidents` with severity, affected_vehicle, alternate-route
  LineString, and deltas.
- **FR-015**: `inventory` with stock, reorder, units, velocity → days-of-cover.

### Simulation
- **FR-016**: Delta-time simulation (real elapsed seconds, clamped) so pace is
  frame-rate independent; full truck route ≈75s at 1×, ship ≈150s.
- **FR-017**: Movement follows the OSRM route geometry (interpolate along the
  polyline), not a straight line; heading reflects segment direction.
- **FR-018**: Telemetry (speed, fuel, engine, cargo temp, signal, GPS acc)
  random-walks within realistic bounds and is written to `telemetry`.
- **FR-019**: SLA status derives from schedule lag + telemetry thresholds →
  on_track / at_risk / breached; exceptions raise/resolve organically.

### UI
- **FR-020**: Basemap selector: Satellite (ESRI), Street (OSM), Hybrid.
- **FR-021**: KPI wall (6+ tiles) from `/api/kpi`.
- **FR-022**: Exception-first default panel with SLA segmentation
  (ON TRACK / AT RISK / BREACHED) and P1/P2/P3 queue with Track/Call/Resolve.
- **FR-023**: Lanes tab with per-lane OTIF bars, congestion, distance, volume;
  click loads primary + alternative routes on the map.
- **FR-024**: Fleet tab with unit cards (ID, SLA chip, route, speed, telemetry).
- **FR-025**: Maritime tab with live AIS feed (Hormuz) + SIM fallback.
- **FR-026**: Inventory tab with days-of-cover and low-stock highlighting.
- **FR-027**: Weather tab (Open-Meteo, keyless) with LIVE/CACHED/SIM badge.
- **FR-028**: Detail panel: vehicle/driver, cargo/customer/value, lane, ETA vs
  SLA, live telemetry sparklines, document strip (PO/ASN/BOL/customs), route
  timeline with events.
- **FR-029**: Incident "Simulate accident" control per truck → calls FR-004 and
  renders incident marker + amber alternate route.
- **FR-030**: Layer control (routes, trails, graticule, road-conditions,
  incidents) + minimap overview with live viewport box.
- **FR-031**: Time control (pause/1×/4×/16×) + search (ID/cargo/hub/dest).
- **FR-032**: Map context: dark color-grade, graticule + coordinate labels,
  HUD corners, coordinate/zoom readout.

---

## Key Entities

- **Location** — id, name, kind (dc/port/city), point geometry, capacity, stock_level.
- **Lane** — origin, destination, distance_km, freeflow_min, otif_pct, volume.
- **Vehicle** — id, kind, driver, model, capacity_t, load_t, fuel_pct, carbon_tco2.
- **Shipment** — id, vehicle, lane, cargo, qty, value_eur, customer, status,
  eta/sla, customs, temp_req; has N ShipmentEvents.
- **TelemetryPoint** — vehicle, ts, point geometry, speed, fuel, engine, cargo_temp, signal, gps_acc.
- **Incident** — id, lane, severity, affected_vehicle, point, alternate LineString, delta_km, delta_min.
- **InventoryItem** — hub, sku, stock, reorder, velocity, days_of_cover.
- **TrafficLane** — lane_id, index, state, est_factor.

---

## Success Criteria

- Opening the page shows a populated, live map with moving units and a
  populated KPI wall within ~3s, with 0 console errors.
- All markers land at the correct city coordinates (spot-checked Rotterdam,
  Berlin, Hamburg).
- Simulating an accident returns a real OSRM alternate corridor with a positive
  delta and visibly re-routes the truck.
- Basemap can be switched between satellite/street/hybrid without losing state.
- All KPI and panel figures are sourced from the database (no hardcoded UI
  numbers).
- Works with `podman compose up` (DB) + one API-server command; frontend is a
  static single file.

## Assumptions
- Public OSRM demo server is reachable for routing; otherwise straight-line
  fallback.
- Live road-conditions feed availability varies; SIM fallback is acceptable.
- Demo dataset scope: Benelux + Central Europe, 6 hubs, 14 destinations.
