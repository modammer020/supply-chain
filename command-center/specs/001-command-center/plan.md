# Implementation Plan: AEGIS Supply-Chain Control Center

**Feature spec**: `specs/001-command-center/spec.md` | **Constitution**: v1.0.0

## Summary
Rebuild the command center around a real stack: **PostGIS** (single source of
truth) → **FastAPI** (routing proxy, traffic, incidents, telemetry) →
**single-file Leaflet UI** (control-room theme). The simulation writes to the
same PostGIS tables a real GPS pipeline would, so swapping in real data later
is a connector change, not a rewrite.

## Technical Context

| Concern | Decision |
|---|---|
| DB | PostgreSQL 16 + PostGIS 3.4, Podman `aegis_db`, port 5433, db/user/pw `aegis` |
| API | FastAPI + uvicorn, host `127.0.0.1:8300`, venv `.venv` (py3.14) |
| DB access | psycopg2, per-request connections (demo scale) |
| Routing | OSRM demo `router.project-osrm.org` proxied server-side; Polyline6 (63-offset) decode; fallback straight-line |
| Route cache | `routes_cached(lane_id, variant, geom, km, min, fetched_at)`, daily TTL |
| Traffic | keyless live feed (DATEX-II/GeoJSON road conditions) proxied; fallback: deterministic per-lane congestion (hour-of-day sine + seeded noise) |
| Weather | Open-Meteo keyless, cached 30 min in API (in-memory + DB `kv`) |
| AIS | Hormuz monitor (public), SIM fallback |
| Map | Leaflet 1.9.4 + ESRI satellite/transport/places, OSM street; CSS color-grade per mode |
| Frontend | `web/index.html` single file; no build, no framework |
| Telemetry | sim engine (client) computes positions along OSRM polylines + sensor walk; pushes to `POST /api/telemetry` every 5 sim-seconds |
| Sim pace | delta-time; truck full route ≈75s @1×; ship ≈150s; 1×/4×/16× + pause |

## Data Model (PostGIS)

```
locations(id, name, kind, lat, lng, geom, capacity, stock_level, region)
lanes(id, origin→locations, destination→locations, distance_km, freeflow_min, otif_pct, volume)
vehicles(id, kind, name, driver, model, capacity_t, load_t, fuel_pct, fuel_range_km, registered, carbon_tco2)
shipments(id, vehicle_id, lane_id, cargo, qty, value_eur, customer,
          status[loading|in_transit|delayed|rerouted|delivered],
          eta_minutes, sla_minutes, customs, temp_req, progress)
shipment_events(id, shipment_id, ts, type[dep|chk|arr|inc|reroute|sla], note)
telemetry(vehicle_id, ts, lat, lng, speed_kmh, heading, fuel_pct,
          engine_temp, cargo_temp, signal_pct, gps_acc_m, geom)
incidents(id, lane_id, kind, severity, title, lat, lng, geom,
          affected_vehicle, alt_route(geom LineString), alt_km, alt_min,
          created_at, resolved_at)
routes_cached(lane_id, variant, geom, distance_km, duration_min, fetched_at)
inventory(hub_id, sku, stock, reorder, units, velocity)
kv(key, value jsonb, ttl_until)   -- weather/traffic cache
```

## API Design (v2)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/overview` | bootstrap: locations, lanes, vehicles, shipments(+events), inventory, kpi, incidents, traffic, weather |
| GET | `/api/route/{lane_id}` | route variants (cache→live→fallback) |
| GET | `/api/traffic` | per-lane congestion (LIVE if feed ok, else SIM) |
| GET | `/api/kpi` | KPI wall |
| GET | `/api/telemetry/{vid}` | history window |
| POST | `/api/telemetry` | sim GPS point insert |
| POST | `/api/incidents` | create incident + OSRM alternate + recommendation |
| POST | `/api/incidents/{id}/resolve` | resolve + shipment back to in_transit |
| POST | `/api/shipments/{id}/status` | advance shipment lifecycle |
| GET | `/api/weather` | hub weather (Open-Meteo, cached) |
| GET | `/api/conditions?bbox=` | live road conditions (feed proxy, bbox-filtered) |
| GET | `/api/health` | db + feed status |

## Frontend Architecture (single file)

- **Bootstrap**: one `/api/overview` call → state store (plain JS object).
- **Layers**: `basemapLayers{sat,street,hybrid}` toggle; overlay
  layerGroups: routes (per-lane OSRM polylines), unitTrails, graticule,
  conditions, incidents.
- **Unit engine**: per-lane OSRM polyline → arc-length table; unit position =
  arcLength(progress) → [lat,lng]; heading from segment; progress advances by
  delta-time × timeScale.
- **Pusher**: every 5 sim-seconds, batch `POST /api/telemetry` for all units.
- **Incidents**: UI action → POST → returns alt geometry → draw amber line +
  marker; unit's route source switches to the alternate.
- **Panels**: Exceptions (default), Lanes, Fleet, Maritime, Inventory,
  Weather. Detail drawer per unit. KPI wall on top. Minimap bottom-right.
- **Theme**: dark control-room, `--accent #00e5ff`, status
  green/amber/magenta; basemap color-graded via tile-pane CSS filter.

## Milestones

1. **M1 Data layer v2** — schema migration (shipment_events, kv, progress),
   seed enrichment (events, docs), API v2 endpoints incl. conditions proxy.
2. **M2 Routing & incidents** — verify OSRM variants render correctly;
   incident create/resolve with alternate route; shipment lifecycle.
3. **M3 Frontend v3** — full UI rebuild on the API; basemap selector; all
   panels; detail drawer; time control; search.
4. **M4 Polish & verify** — theme consistency, minimap, readouts, 0 console
   errors, acceptance-criteria verification pass.

## Complexity Tracking
<!-- Deviations from the constitution are tracked here. -->
- None.
