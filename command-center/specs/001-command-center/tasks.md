# Tasks: AEGIS Supply-Chain Control Center

**Plan**: `specs/001-command-center/plan.md` | **Spec**: `spec.md`

## M1 — Data layer v2
- [x] T001 Schema migration: `shipment_events`, `kv`, `shipments.progress` [VER: `psql -c "\d shipment_events"`]
- [x] T002 Seed enrichment: shipment_events + doc strings per shipment [VER: `count(*)>0`]
- [x] T003 API `/api/weather` (Open-Meteo, kv-cached 30min, SIM fallback) [VER: curl returns hubs with badge]
- [x] T004 API `/api/conditions?bbox=` (proxy keyless feed; SIM fallback) [VER: returns array + source]
- [x] T005 API `/api/shipments/{id}/status` lifecycle advance [VER: status changes in DB]
- [x] T006 API `/api/overview` includes events + weather [VER: single payload shape]

## M2 — Routing & incidents (verify existing)
- [x] T007 Verify Polyline6 decode → correct city coords [VER: Rotterdam≈4.48,51.92]
- [x] T008 Incident create → OSRM alternate + recommendation [VER: delta_km>0, geometry valid]
- [x] T009 Incident resolve → shipment back to in_transit [VER: status updated]

## M3 — Frontend v3 (single file, API-driven)
- [x] T010 Bootstrap from `/api/overview` [VER: no hardcoded panel numbers]
- [x] T011 Basemap selector (satellite/street/hybrid) + color-grade [VER: toggle works]
- [x] T012 KPI wall (6+) [VER: matches /api/kpi]
- [x] T013 OSRM route polylines per lane (primary + alt) [VER: routes on correct cities]
- [x] T014 Unit movement along route (arc-length, delta-time, heading) [VER: trucks move on roads]
- [x] T015 Exception-first panel + SLA segmentation [VER: counts match]
- [x] T016 Lanes tab (OTIF/congestion/distance/volume) [VER: sortable, click loads route]
- [x] T017 Fleet tab unit cards [VER: telemetry live]
- [x] T018 Maritime tab (AIS + SIM) [VER: rows render]
- [x] T019 Inventory tab (days-of-cover, low-stock) [VER: matches /api/inventory]
- [x] T020 Weather tab [VER: LIVE/SIM badge]
- [x] T021 Detail drawer (telemetry sparklines, docs, timeline) [VER: opens on click]
- [x] T022 Incident simulate control → renders marker + amber alt route [VER: truck re-routes]
- [x] T023 Layer control + minimap + graticule + readout [VER: toggles + viewbox]
- [x] T024 Time control (pause/1×/4×/16×) + search [VER: pace changes, filter works]
- [x] T025 Telemetry push to POST /api/telemetry [VER: rows accumulate in DB]

## M4 — Polish & verify
- [x] T026 0 console errors on load [VER: headless check]
- [x] T027 Marker coordinate spot-check (Rotterdam/Berlin/Hamburg) [VER: correct]
- [x] T028 One-command startup (compose up + api) documented in README [VER: steps reproducible]
