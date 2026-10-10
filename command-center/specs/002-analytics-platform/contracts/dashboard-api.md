# Contract: Dashboard API

**Service**: `dashboard-api` (eigen container, FastAPI, port 8401;
frontend op 8402 via static serve of `index.html` zelf)
**Backends**: DuckDB (embedded → DuckLake catalog `lake-catalog` +
MinIO), Trino (federated: lake-Parquet + live `aegis_db` via postgres-connector).

**Principe (FR-007/FR-011)**: elk datapunt draagt context:
`value`, `source_table`, `semantic_definition`, `data_age_s`,
`contract_status` (`green|yellow|red|stale`). Bij backend-uitval:
laatste bekende waarde + `status: "stale"` — nooit een lege pagina.

## Endpoints

### `GET /api/kpi`
KPI-rij (FR-008). Bron: lake (DuckDB) + live (Trino) waar relevant.

```json
{
  "as_of": "2026-10-09T00:30:30Z",
  "kpis": [
    {
      "key": "otif_pct",
      "value": 95.6,
      "unit": "%",
      "source_table": "lanes",
      "semantic_definition": "Percentage lanes met on-time-in-full levering",
      "data_age_s": 42,
      "contract_status": "green",
      "live": true
    },
    {
      "key": "delayed_shipments",
      "value": 4,
      "unit": "count",
      "source_table": "shipments",
      "semantic_definition": "Shipments met eta_minutes > sla_minutes (sla_breach)",
      "data_age_s": 42,
      "contract_status": "yellow",
      "live": true,
      "note": "1 contract-failure op shipments.status in afgelopen 1u"
    }
  ]
}
```

`contract_status`: `yellow` = er is een quarantaine-record op deze
`source_table` in de afgelopen 1u (dashboard toont "gebaseerd op
gedegradeerde data", US3-AS2). `red` = topic heeft geen verse data
(freshness-SLA verbroken).

### `GET /api/trends/{metric}`
Tijdreeks uit de lake (DuckDB). Query-params: `from`, `to` (ISO,
default 24u), `bucket` (`5m|15m|1h|1d`).

| metric | Definitie |
|---|---|
| `otif` | AVG(lanes.otif_pct) per bucket (snapshot-gebaseerd) |
| `shipment_status` | COUNT per status per bucket (dim-snapshots) |
| `incidents` | COUNT(shipment_events type=incident) per bucket |
| `cargo_temp` | AVG/MAX(cargo_temp) per bucket per vehicle |
| `value_in_transit` | SUM(value_eur) in_transit per bucket |
| `telemetry_count` | events/bucket (pipeline-hartslag) |

```json
{"metric": "cargo_temp", "bucket": "15m", "series": [
  {"ts": "2026-10-09T00:15:00Z", "value": 4.2, "dimension": "TRK-101", "n": 12}
]}
```

### `GET /api/incidents`
Incidenten-tijdlijn: facts.shipment_events (type=incident) +
live-join op `aegis.dim.incidents`/`shipments` (Trino, federated) voor
context (lane, vehicle, severity). Sorteer: `ts` desc; params: `severity`,
`limit`.

### `GET /api/lineage/{card_id}`
Terugkoppeling per kaart (FR-007, success-criterion: < 10 min
terugtraceerbaar):

```json
{
  "card": "otif_pct",
  "source": {"db": "aegis_db", "table": "lanes", "topic": "aegis.dim.lanes"},
  "pipeline": {"spark_job": "2026-10-09T00:30", "lake_table": "dims.lanes", "snapshot": 184},
  "contract": {"status": "green", "last_checked_at": "2026-10-09T00:30:12Z", "violations_24h": 0},
  "freshness": {"data_age_s": 42, "sla_s": 120},
  "evidence": {"cycle_ids": ["c-20261009T003000-01"], "record_count": 38}
}
```

### `GET /api/quality/quarantine?topic=&limit=`
Quarantaine-records (contract-failures) — transparantie van
contract-enforcement (US2-AS1/AS4).

### `GET /api/status`
Platform-health: captor-reikbare (via captor /health), lake-catalog,
MinIO, Trino, Spark-job-laaste-run, contract-statusen per topic.

## Query-strategie (per endpoint)

| Endpoint | Engine | Waarom |
|---|---|---|
| /api/kpi (live-waarden) | Trino federated (postgres + Parquet) | "nu" + context in één query (FR-006) |
| /api/kpi (geaggregeerde lake-waarden) | DuckDB | snel, ge-optimaliseerd voor Parquet/DuckLake |
| /api/trends/* | DuckDB | historie, geen live nodig |
| /api/incidents | Trino (federated join live dims + facts) | US2-AS3 |
| /api/lineage/* | DuckDB-catalog + Prom (metriken) | provenance |
| /api/quality/* | DuckDB-catalog (quarantaine-tabel) | |

Timeout: p95 < 3 s (DuckDB), < 10 s (Trino federated, performance-goal).
Cache: `/api/kpi` 15 s in-memory (herhaalde dashboard-polls).
