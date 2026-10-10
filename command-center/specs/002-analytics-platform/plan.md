# Implementation Plan: AEGIS Analytics Platform (002)

**Branch**: `002-analytics-platform` | **Date**: 2026-10-09 | **Spec**: `specs/002-analytics-platform/spec.md`

**Input**: Feature specification from `/specs/002-analytics-platform/spec.md`

## Summary

Spiegelt de bestaande AEGIS PostGIS-database (read-only, poller op 30 sec +
handmatige trigger) naar een apart podman-compose project met een streaming
data platform: **Kafka** (audit-trail/provenance) → **Spark** structured
streaming (contract-enforcement) → **DuckLake in MinIO** (lakehouse) →
**DuckDB** (interactief, embedded in dashboard-API) + **Trino** (federated
SQL: lake + live Postgres) → **eigen dashboard-frontend** met
semantiek/freshness/provenance per kaart. **Prometheus + Grafana** voor
pipeline-observability. Het project is volledig los van de AEGIS-command
center (spec 001): geen wijzigingen aan `aegis_db`, `api.py` of
`web/index.html`.

## Technical Context

**Language/Version**: Python 3.14 (captor + dashboard-API, eigen venv in
`aegis-analytics/.venv`), Spark via `spark-submit` in container (PySpark 3.5+)

**Primary Dependencies**: FastAPI, uvicorn, psycopg2-binary (captor read-only),
kafka-python / confluent-kafka, PySpark, duckdb (embedded), trino (client),
prometheus-client

**Storage**:
- Bron: PostgreSQL 16 + PostGIS 3.4, container `aegis_db`, host-port 5433
  (read-only; hetzelfde podman-netwerk)
- Lake: DuckLake-tabellen in MinIO (S3), volume `/lake`
- State: captor-watermarks in eigen kleine state (bestand of topic)
- Config: `contracts/*.yaml` (data contracts per topic)

**Testing**: pytest (captor: idempotentie, watermark-herstart,
manual-trigger 409; contracts: enum/range/freshness-unit tests;
dashboard-API: contract-status + freshness-calc), manual-VER-steps per user story

**Target Platform**: Linux, Podman 5.7 + docker-compose provider, 8 cores / 30 GB RAM

**Project Type**: web-service (multi-container data platform + API + frontend)

**Performance Goals**:
- Capture-lag < 60 sec (30-sec poll + Spark-behandeling)
- Federated Trino-query < 10 sec
- Dashboard-initiatie < 3 sec na API-response
- RAM-stack < 14 GB (12 services incl. JupyterLab + Kafka UI; host 30 GB)

**Constraints**:
- Bron `aegis_db` uitsluitend read-only; geen schema- en geen
  trigger-wijzigingen (option A, bevestigd door user)
- Stack start/stop via één `podman compose up/down`; geen build-stap
  nodig voor de frontend (single-file, zoals AEGIS)
- Graceful degradation (Constitution I): bron-/lake-/Trino-uitval →
  stale-badge, geen hard-fail

**Scale/Scope**: 1 bron (AEGIS), ~10 tabellen, ~50 actieve
voertuigen/shipments; telemetry ≈ duizenden records/min (geschat). MVP-schaal:
local mode Spark, 1 Kafka-broker (KRaft), 1 MinIO.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principe | Status | Toelichting |
|---|---|---|
| I. Demo-First, Real-Data-Ready | ✅ PASS | Dashboard werkt op echte `aegis_db`-data vanaf `compose up`; bij bron-uitval → SIM/CACHED-badge (FR-011). |
| II. Single Source of Truth | ✅ PASS | `aegis_db` blijft de SSOT voor de command center; het platform is een read-only *spiegel* (derived read-model), geen tweede waarheid. Gegevens worden in de browser nooit geïnfundueerd. |
| III. Spec-Driven Development | ✅ PASS | Deze spec (002) → plan → research → data-model → contracts → tasks; elk feature met VER-checks. |
| IV. Open & Keyless | ✅ PASS | Alle componenten open-source (Kafka/Spark/DuckDB/Trino/MinIO/Grafana), geen API-keys. |
| V. Geospatial Correctness | ✅ PASS | Geen nieuwe geometry-rekeningen; de spiegel kopieert bestaande WGS84-data. Telemetrie-punten worden onveranderd overgezet. |
| VI. Rich, Professional UX | ✅ PASS | Dashboard volgt het AEGIS control-room theme (deep navy, cyan accent, Rajdhani/JetBrains Mono); geen hardcoded demo-cijfers — alleen DB-afgeleide waarden. |
| VII. Performance & Scale | ✅ PASS | Lake-queries DuckDB/Trino; dashboard laadt in batches; geen impact op command-center-animaties. |

**GATE RESULT: PASS — 0 violations, 0 afwijkingen nodig.**

## Project Structure

### Documentation (this feature)

```text
specs/002-analytics-platform/
├── spec.md              # Deze feature spec (002)
├── plan.md              # This file
├── research.md          # Fase 0: vendor/connector-research (o.a. Trino-DuckLake-connector status)
├── data-model.md        # Fase 1: topics, lake-tabellen, dimensie-strategie, contracten
├── quickstart.md        # Fase 1: compose-up + verificatiestappen
├── contracts/           # Fase 1: API-contracten (captor, dashboard-API) + data-contract-templates
│   ├── captor-api.md
│   ├── dashboard-api.md
│   └── data-contracts/  # per-topic YAML-sjablonen
└── tasks.md             # Fase 2
```

### Source Code (repository root `aegis-analytics/`)

```text
aegis-analytics/
├── compose.yaml              # 12 services: kafka, kafka-ui, minio, lake-catalog,
│                             # spark, trino, captor, dashboard, prometheus,
│                             # grafana, jupyterlab, adminer
├── contracts/
│   └── *.yaml                # data contracts per topic (FR-004)
├── captor/
│   ├── main.py               # poller (30s) + manual trigger (FR-001/002/003)
│   ├── poller.py             # per-tabel watermarks, bootstrap, idempotentie
│   ├── health.py             # /health, /manual/poll, status per tabel
│   └── tests/
├── pipeline/
│   ├── spark_job.py          # structured streaming: Kafka → contract-check → DuckLake/MinIO
│   ├── contract_check.py     # schema/enum/range/freshness validator (ook unit-testbaar standalone)
│   └── tests/
├── dashboard/
│   ├── api/
│   │   ├── main.py           # FastAPI: /api/kpi, /api/trends/*, /api/lineage/{card}
│   │   ├── duckdb_client.py  # embedded DuckDB → DuckLake in MinIO
│   │   ├── trino_client.py   # federated queries (live Postgres + lake)
│   │   └── tests/
│   └── index.html            # single-file frontend (AEGIS theme), geen build-stap
├── observability/
│   ├── prometheus.yml
│   └── grafana/dashboards/pipeline.json   # lag, contract-failures, captor-cycles
├── .venv/                    # eigen Python-venv (captor + dashboard)
└── README.md                 # quickstart (zie specs/002/quickstart.md)
```

### Interfaces (samengevat; details in `contracts/`)

| Interface | Aandrijving | Payload |
|---|---|---|
| `GET /health` (captor) | Dashboard/Grafana | per-tabel status (bootstrap/done/error), laatste watermark, laatste cycle-ts |
| `POST /manual/poll` (captor) | Mens | 200 (cycle gestart) / 409 (cycle actief) |
| `GET /api/kpi` (dashboard) | Frontend | KPI-kaarten: `value, source_table, semantic_definition, data_age_s, contract_status` |
| `GET /api/trends/{metric}` (dashboard) | Frontend | tijdreeks uit lake (DuckDB), eventueel federated (Trino) |
| `GET /api/lineage/{card_id}` (dashboard) | Frontend | terugkoppeling: bron-tabellen, contract-status, event-ts range |
| Kafka-topics | Spark | `aegis.events.*`, `aegis.dim.*`, `aegis.metrics` (schema in data-model.md) |

### Access-layer (FR-012 — elke tool met eigen console)

| Tool | Console | Host-port | Login |
|---|---|---|---|
| Kafka | Kafka UI (Provectus) | 8040 | geen |
| Spark + DuckDB | JupyterLab (pyspark + duckdb kernels) | 8888 | none/token |
| Trino | eigen Web UI | 8543 | geen (lokaal) |
| MinIO | eigen Console | 9001 | minioadmin / (env) |
| lake-catalog + aegis_db | Adminer | 8081 | per DB (aegis / lake) |
| Pipeline | Grafana + Prometheus | 3000 / 9090 | admin / admin |
| Captor | FastAPI | 8400 | — (health + manual poll) |
| Dashboard | API + frontend | 8401 / 8402 | — |

## Phase 0 — Research (open vragen vóór design)

1. **Trino-DuckLake-connector**: status op de gekozen Trino-versie
   (experimenteel?). Fallback: Trino leest onderliggende Parquet rechtstreeks.
2. **DuckLake-schrijven vanuit Spark**: officiële writer-support vs.
   Parquet+metadeel; welke Spark-versie.
3. **Kafka image**: KRaft 1-broker image (Apache of RedPanda) +
   console-consumer voor debug.
4. **Telemetrie-volume**: exacte records/min uit `aegis_db` (bepaalt
   poll-grootte + Spark-windowing).
5. **DuckDB→MinIO**: S3-credentials in de dashboard-API (MinIO
   erlang/credentials via compose-omgeving).

## Risks & Mitigatie

- **DuckLake-connector-maturiteit (Trino)**: mitigation = Parquet-fallback
  (geen architectuurschade); research-vraag 1 beslist dit vóór fase 1.
- **Spark local-mode overhead**: batch-afstand + streaming samen in één job;
  indien pijnlijk → batch-mode per cycle (30-sec) in plaats van continu streaming.
- **Bootstrap-volumedruk**: full-snapshot bij eerste start; telemetrie-history
  eventueel window-limited (bijv. laatste 30 dagen) — beslist in data-model.md.
- **Captor en live-db concurrentie**: read-only + `REPEATABLE READ` per cycle;
  geen locks, geen impact op de sim-engine.

## Open Items (niet-blocker, beslissen tijdens fase 1)

- Telemetrie-retentie in de lake (30d / 90d / onbeperkt).
- Exacte Trino-versie + connector-set (postgres, s3/parquet, ducklake).
- Grafana-dashboard: 1 pipeline-dashboard of 2 (pipeline + data-quality).
