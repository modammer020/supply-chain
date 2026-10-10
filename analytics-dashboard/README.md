# AEGIS Analytics Platform (spec 002)

Read-only analytics-platform dat de bestaande AEGIS supply-chain data
(`aegis_db`, PostGIS) spiegelt naar een streaming data stack met
**data contracts, een DuckLake lakehouse, federated queries en een
analytics-dashboard** — de Gartner "AI-Ready Data / context layer" use case,
draaiend in plaats van op papier.

**Volledig los van de command center**: `aegis_db`, `api.py` (8300) en
`web/index.html` (8765) blijven ongewijzigd en draaien gewoon verder.

## Start

```bash
cd analytics-dashboard   # of de map die je hier clone
podman compose up -d --build
podman compose ps          # wacht tot alle 12 Up (kafka + minio + trino first)
```

Binnen ~5 min is er data in het dashboard (bootstrap + poll-cycles).

## Consoles (default-login overal: `Password123!`)

| Tool | URL | Login |
|---|---|---|
| **Analytics Dashboard** | http://localhost:8402 | — |
| Dashboard-API | http://localhost:8401/api/kpi | — |
| Captor (health + manual poll) | http://localhost:8400/health · `curl -X POST localhost:8400/manual/poll` | — |
| Kafka UI | http://localhost:8040 | geen |
| JupyterLab (Spark + DuckDB) | http://localhost:8888/lab | `Password123!` |
| Trino UI (federated SQL) | http://localhost:8543 | geen (lokaal) |
| MinIO Console | http://localhost:9001 | `minioadmin` / `Password123!` |
| Adminer (aegis_db + lake-catalog) | http://localhost:8081 | `aegis` / `aegis_dev` · `lake` / `Password123!` |
| Grafana | http://localhost:3000 | `admin` / `Password123!` |
| Prometheus | http://localhost:9090 | geen |

> De bestaande `aegis_db` behoudt zijn eigen credentials (read-only voor
> het platform) — die worden niet aangepast.

## Architectuur

Zie `../specs/002-analytics-platform/architecture.html` (neon-diagram,
pulsende dataflows, hover-tooltips).

```
aegis_db (PostGIS, read-only)
    │  captor: poll 30s + manual · bootstrap · watermarks
    ▼
Kafka (10 topics: events / dims / metrics)   ← audit-trail
    ▼
Pipeline: contract-validator (YAML per topic) → DuckLake (DuckDB)
    │           violations → catalog.quarantine + Grafana-metrik
    ▼
MinIO (Parquet, s3://aegis-lake) + lake-catalog (Postgres = DuckLake meta)
    ▼
DuckDB (embedded, trends) + Trino (federated: live aegis_db + lake)
    ▼
Dashboard :8402 — KPI-kaarten met bron + semantiek + leeftijd + contract-status
```

## Dagelijks gebruik

| Taak | Hoe |
|---|---|
| Data forceren | `curl -X POST localhost:8400/manual/poll` |
| Pipeline-health | Grafana :3000 → "AEGIS Analytics — Pipeline Health" |
| Ad-hoc lake-analyse | JupyterLab :8888 (DuckLake-kernel) |
| Live + historie in 1 query | Trino UI :8543 (`aegis_db.*` JOIN `lake.*`) |
| Raw events | Kafka UI :8040 → `aegis.events.*` |
| Contract-overtredingen | `GET localhost:8401/api/quality/quarantine` |
| Terugtraceerbaarheid | `GET localhost:8401/api/lineage/{kpi}` |

## Stop

```bash
podman compose down          # platform stopt; command center blijft draaien
podman compose down -v       # + volumes (lake + watermarks + kafka) — WIJKT HISTORIE
```

## Tests

```bash
cd analytics-dashboard   # of de map die je hier clone
.venv/bin/pytest captor/tests pipeline/tests -v   # op host (eigen venv)
```

## Spec

Volledige specificatie: `../specs/002-analytics-platform/`
(spec, plan, research, data-model, contracts, quickstart, tasks, architecture).
