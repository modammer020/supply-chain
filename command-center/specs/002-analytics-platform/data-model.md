# Data Model: AEGIS Analytics Platform (002)

**Date**: 2026-10-09 · **Plan-ref**: `plan.md` · **Research-ref**: `research.md`

## 0. Overzicht

```
bron (read-only)          Kafka (audit-trail)      Lake (DuckLake in MinIO)
─────────────────         ────────────────────     ─────────────────────────
aegis_db                  aegis.events.shipment    facts.shipment_events
  shipments               aegis.events.telemetry   facts.telemetry
  shipment_events         aegis.dim.shipments      dims.shipments
  vehicles                aegis.dim.vehicles       dims.vehicles
  lanes                   aegis.dim.lanes          dims.lanes
  locations               aegis.dim.locations      dims.locations
  inventory               aegis.dim.inventory      dims.inventory
  drivers                 aegis.dim.drivers        dims.drivers
                          aegis.metrics            (geen lake-tabel;
                          aegis.quarantine         contract-log in catalog)
```

Principes:
- **Facts** = appender-only, idempotent (dedup op `id`), `captured_at` erbij.
- **Dims** = snapshots per cycle (kleine tabellen, lossless refresh):
  de lake-tabel is een *current-dimension* (UPSERT-gedrag via
  `INSERT ON CONFLICT`-achtige verwerking: Spark appendt een
  `cycle_ts`; readers selecteren de nieuwste per key) + `first_seen`/
  `last_seen` voor change-detectie (provenance: "wanneer veranderde status?").
- **Quarantine** = aparte topic + catalog-tabel; nooit in facts/dims.

## 1. Topic-schemas (Kafka, key = record `id`, value = JSON)

Elke record draagt: het oorspronkelijke payload (kolommen 1-op-1 uit
`aegis_db`, geometry-kolommen `geom` uitgesloten → alleen `lat`/`lng`
doubles, Constitution V: geen geometry-rekeningen), plus capture-metadata:

```json
{
  "payload": { /* oorspronkelijke kolommen */ },
  "src_table": "telemetry",
  "captured_at": "2026-10-09T00:30:00.123+00:00",
  "cycle_id": "c-20261009T003000-01"
}
```

| Topic | Payload-kolommen (payload) | Key |
|---|---|---|
| `aegis.events.shipment` | id, shipment_id, ts, type, note | `id` |
| `aegis.events.telemetry` | vehicle_id, ts, lat, lng, speed_kmh, heading, fuel_pct, engine_temp, cargo_temp, signal_pct, gps_acc_m | `vehicle_id:ts` (composite; geen PK in bron) |
| `aegis.dim.shipments` | id, vehicle_id, lane_id, cargo, qty, value_eur, customer, status, eta_minutes, sla_minutes, customs, temp_req, created_at, progress | `id` |
| `aegis.dim.vehicles` | id, kind, name, driver, model, capacity_t, load_t, fuel_pct, fuel_range_km, registered, carbon_tco2 | `id` |
| `aegis.dim.lanes` | id, origin, destination, distance_km, freeflow_min, otif_pct, volume | `id` |
| `aegis.dim.locations` | id, name, kind, lat, lng, capacity, stock_level, region | `id` |
| `aegis.dim.inventory` | hub_id, sku, stock, reorder, units, velocity | `hub_id:sku` |
| `aegis.dim.drivers` | (volledige rij; `drivers`-schema volgt bron) | `id` |
| `aegis.metrics` | cycle_id, kpi-object (OTIF, value_in_transit, delayed, incidents, carbon, low_stock) — gemeten door captor uit SQL | `cycle_id` |
| `aegis.quarantine` | topic, record, rule_violated, reason, captured_at | hash |

**Type-strictheid** (research V2: DuckLake/Spark wil expliciete types):
- `value_eur` DOUBLE, `qty` VARCHAR (bron is text), `progress` DOUBLE,
  `fuel_pct` DOUBLE, timestamps `TIMESTAMPTZ`, id/kolommen met text → VARCHAR.

## 2. Lake-tabellen (DuckLake, catalog = `lake-catalog` Postgres, data = MinIO `aegis-lake/`)

### facts.shipment_events
`id VARCHAR PK`, `shipment_id VARCHAR`, `ts TIMESTAMPTZ`, `type VARCHAR`,
`note VARCHAR`, `captured_at TIMESTAMPTZ`, `cycle_id VARCHAR`
— partition: `ts::DATE`. Dedup: Spark de-dupliceert per `id`
(laatste `captured_at` wint) vóór append; append-only.

### facts.telemetry
`vehicle_id VARCHAR`, `ts TIMESTAMPTZ`, `lat DOUBLE`, `lng DOUBLE`,
`speed_kmh DOUBLE`, `heading INT`, `fuel_pct DOUBLE`, `engine_temp DOUBLE`,
`cargo_temp DOUBLE`, `signal_pct DOUBLE`, `gps_acc_m DOUBLE`,
`captured_at TIMESTAMPTZ`, `cycle_id VARCHAR`
— composite-key `vehicle_id:ts` (UNIQUE in catalog via DuckLake
unique-constraint waar beschikbaar; anders Spark-dedup). Partition: `ts::DATE`.

### dims.* (per dimensietabel, 6 stuks)
Bron-kolommen 1-op-1 (types conform §1) + `cycle_ts TIMESTAMPTZ`
(cycle van herkomst) + `first_seen TIMESTAMPTZ` + `last_seen TIMESTAMPTZ`.
Readers (dashboard-API/Trino): `SELECT ... WHERE cycle_ts = (SELECT max(cycle_ts) FROM dims.x)`.
`last_seen - first_seen` = wijzigings-venster → provenance ("status
changed 14:32–14:58" uit de snapshot-historie; time-travel via DuckLake
snapshots).

### quarantaine (catalog-tabel, niet MinIO)
`id BIGINT`, `topic VARCHAR`, `record JSON`, `rule VARCHAR`,
`reason VARCHAR`, `captured_at TIMESTAMPTZ` — leesbaar via
dashboard-API `/api/quality/quarantine` en Grafana-metrik.

## 3. Watermarks & idempotentie (captor)

- Per tabel een watermark in een state-bestand (volume/`captor-state.json`,
  niet in `aegis_db` — read-only):
  - `shipment_events`, `telemetry`, `incidents`: `last_max_ts` (poll:
    `WHERE ts > last_max_ts OR (ts = last_max_ts AND id > last_max_id)`;
    overlap 1 record, Spark-dedup lost restant)
  - `shipments`: `last_max_created_at` + **status/progress
    change-detectie**: pollt ook
    `WHERE created_at <= wm AND (status, progress, eta_minutes) <>
    (cache van vorige cycle)` → dim-updates vangen
  - dims (vehicles/lanes/locations/inventory/drivers): full-snapshot per
    cycle (klein, lossless)
- Herstart: watermarks herlezen uit bestand; idempotentie via
  `captured_at`-overlap + Spark-dedup → **geen duplicaten in facts**
  (US1-AS3/Edge "herstart").
- Bootstrap: eenmalige full-read per tabel → `cycle_id = "bootstrap-<ts>"`,
  daarna watermarks initialiseren op max(`ts`). Partial-fail (PostGIS
  weg tijdens bootstrap) → per-tabel status `bootstrap_pending`,
  hervat alleen onafgemaakte tabellen (Edge case).

## 4. Data contracts (YAML per topic) — schema

```yaml
topic: aegis.dim.shipments
owner: aegis-data-team
freshness_sla_s: 120          # max leeftijd van laatste record
checks:
  schema:
    required: [id, status, lane_id, created_at]
    types: {status: str, eta_minutes: int, value_eur: float}
  enums:
    status: [planned, in_transit, delayed, delivered, cancelled]
    type: [departure, arrival, status_change, incident, delay, delivery, customs]  # shipment_events
  ranges:
    fuel_pct: [0, 100]
    progress: [0, 1]
    speed_kmh: [0, 160]
  freshness:
    max_lag_s: 300            # per-topic "geen nieuwe records in 5 min"
on_violation: quarantine      # quarantine | flag
```

Contracts leven in `aegis-analytics/contracts/*.yaml`; de Spark-validator
en de pytest-suite lezen ** dezelfdde YAML** (enforce-in-pipeline =
guardrail, Gartner-kern; FR-004).

## 5. Retentie

- Lake (MVP): 90 dagen per fact-tabel (compactor: DuckLake
  `ducklake_merge_adjacent_files` + delete oude partitionen, dagelijkse
  job).
- Kafka: retention 7 dagen (buffer bij MinIO-down; FR/Edge).
- Dim-snapshots: onbeperkt (klein; time-travel voor provenance).

## 6. Semantische laag (context-layer-koppeling, FR-007)

Per KPI/maat een definitie in `contracts/semantics.yaml` (machine-leesbaar,
door dashboard-API gerenderd per kaart):

```yaml
otif_pct:
  definition: "Percentage lanes met on-time-in-full levering (otif_pct, bron: lanes)"
  source_table: lanes
  formula: "AVG(otif_pct) over actieve lanes"
delayed_shipments:
  definition: "Shipments met eta_minutes > sla_minutes (sla_breach)"
  source_table: shipments
  formula: "COUNT(*) WHERE eta_minutes > sla_minutes"
sla_breach:
  definition: "Verwachtings-tijd (eta) overschrijdt de SLA-tijd"
  source_table: shipments
cargo_temp_alert:
  definition: "cargo_temp buiten temp_req-band van de shipment"
  source_table: telemetry+shipments
```

```
| Metric | Formule |
|---|---|
| otif_pct | AVG(lanes.otif_pct) |
| value_in_transit | SUM(shipments.value_eur WHERE status = in_transit) |
| delayed | COUNT(shipments WHERE eta_minutes > sla_minutes) |
| open_incidents | COUNT(incidents WHERE resolved_at IS NULL) |
| carbon | SUM(vehicles.carbon_tco2) |
| low_stock | COUNT(inventory WHERE stock < reorder) |
```

(Exacte KPI-definities worden afgeleid uit `api.py /api/kpi` bij implementatie —
conform Constitution VI: DB-afgeleide waarden, geen hardcoded cijfers.)
