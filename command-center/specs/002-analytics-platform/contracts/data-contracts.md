# Data Contracts (templates) — 002

Locatie in product: `aegis-analytics/contracts/` (één YAML per topic +
`semantics.yaml`). De Spark-validator (`pipeline/contract_check.py`) en de
pytest-suite (`pipeline/tests/`) lezen ** dezelfdde YAML** —
enforce-in-pipeline, niet in documentatie (Gartner-kern; FR-004).

Schema (algemeen):

```yaml
topic: <kafka.topic>
owner: aegis-data-team
freshness_sla_s: <max leeftijd laatste record>
checks:
  schema:
    required: [<kolommen>]
    types: {<kolom>: <str|int|float|ts>}
  enums:
    <kolom>: [waardes]
  ranges:
    <kolom>: [min, max]
  freshness:
    max_lag_s: <geen nieuwe records in > lag = violatie>
on_violation: quarantine | flag
```

## Sjablonen per topic (MVP; waarden te kalibreren bij implementatie)

### contracts/shipment-events.yaml
```yaml
topic: aegis.events.shipment
owner: aegis-data-team
freshness_sla_s: 3600        # shipment-events zijn niet continu; 1u is ruim
checks:
  schema:
    required: [id, shipment_id, ts, type]
    types: {ts: ts, shipment_id: str, type: str}
  enums:
    type: [departure, arrival, status_change, incident, delay, delivery, customs, other]
  ranges: {}
  freshness: {max_lag_s: 86400}
on_violation: flag           # lage frequentie: flag (zie quarantaine)
```

### contracts/telemetry.yaml
```yaml
topic: aegis.events.telemetry
owner: aegis-data-team
freshness_sla_s: 120
checks:
  schema:
    required: [vehicle_id, ts, lat, lng]
    types: {lat: float, lng: float, fuel_pct: float, cargo_temp: float, speed_kmh: float}
  enums: {}
  ranges:
    lat: [-90, 90]
    lng: [-180, 180]
    fuel_pct: [0, 100]
    progress: [0, 1]
    speed_kmh: [0, 160]
    cargo_temp: [-40, 80]
    engine_temp: [0, 150]
    signal_pct: [0, 100]
  freshness: {max_lag_s: 300}
on_violation: quarantine
```

### contracts/shipments.yaml (dimensie, hoogste risico — agent-consumed)
```yaml
topic: aegis.dim.shipments
owner: aegis-data-team
freshness_sla_s: 120
checks:
  schema:
    required: [id, status, lane_id, vehicle_id, created_at]
    types: {status: str, eta_minutes: int, sla_minutes: int, value_eur: float}
  enums:
    status: [planned, in_transit, delayed, delivered, cancelled]
  ranges:
    eta_minutes: [0, 100000]
    sla_minutes: [0, 100000]
    value_eur: [0, 1000000000]
  freshness: {max_lag_s: 900}
on_violation: quarantine
```

### contracts/vehicles.yaml, lanes.yaml, locations.yaml, inventory.yaml, drivers.yaml
Snapshot-dimensies: `on_violation: flag`, schema-checks op `required` +
types; ranges waar zinvol (`vehicles.capacity_t ≥ 0`,
`locations.stock_level [0,1]` of 0-100 — kalibreren op werkelijke data).

### semantics.yaml (context-layer; FR-007)
Zie `data-model.md` § 6 — definitie per KPI/maat (mens-leesbaar +
machine-leesbaar), gerenderd per dashboard-kaart.

## Test-afspraken (pytest, `pipeline/tests/`)

- `test_contract_load`: elke YAML valideert tegen het schema en
  referentiet op bestaende topic-kolommen.
- `test_enum_violation`: record met `status="onbekend"` → quarantaine
  (US2-AS1).
- `test_range_violation`: `fuel_pct=143` → quarantaine (US2-AS4).
- `test_freshness`: geen records in 6 min → topic `red` in
  `/api/kpi` `contract_status`.
- `test_dedup`: dubbele `id` in twee cycles → 1 rij in facts (Edge).
- `test_schema_extension`: nieuwe onbekende kolom in bron → geaccepteerd
  (fail-safe), gekende kolommen blijven ge-ënforceerd (Edge).
