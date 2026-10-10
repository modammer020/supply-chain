# Tasks: AEGIS Analytics Platform (002)

**Input**: `spec.md`, `plan.md`, `research.md`, `data-model.md`, `contracts/`, `quickstart.md`
**Root**: `/home/demouser/aegis-analytics/`

**Format**: `[ID] [P?] [Story] Description`
- **[P]**: parallel mogelijk (verschillende bestanden, geen dependenties)
- **VER**: verificatiestap die de taak afsluit (spec-kit: geen taak "done" zonder gegande acceptance check)

**Volgorde**: Setup → Foundation (blokkerend) → US1 → US2 → US3 → Observability/Access → Final verification.
US1 moet af zijn vóór US2 (Spark leest topics); US2 vóór US3 (dashboard leest lake).
Observability kan parallel aan US2/US3 (eigen bestanden).

---

## Phase 1: Setup

**Purpose**: project-scaffold, infra-afspraken vastleggen

- [ ] T001 Create project structure per plan.md (`aegis-analytics/` met
      `captor/`, `pipeline/`, `dashboard/`, `contracts/`, `observability/`)
- [ ] T002 [P] Init Python venv `aegis-analytics/.venv` (3.14) met
      fastapi, uvicorn, psycopg2-binary, kafka-python, duckdb, trino,
      prometheus-client, pyyaml, pytest
- [ ] T003 [P] Schrijf `contracts/*.yaml` per topic (7 topic-contracten +
      `semantics.yaml`) — templates in `contracts/data-contracts.md`
- [ ] T004 [P] Schrijf `README.md` (pointer naar `specs/002-analytics-platform/`)

**Checkpoint**: structuur + venv + contracts op disk; `pytest` draait op een dummy-test

---

## Phase 2: Foundation (blokkerend voor alles)

**Purpose**: infra die elke user story nodig heeft — zonder deze fase kan geen story beginnen

- [ ] T005 `compose.yaml` — 12 services met vaste host-ports (plan.md
      access-layer tabel): kafka (KRaft, :9092), kafka-ui (:8040),
      minio (:9000/:9001), lake-catalog (postgres:16), spark
      (base-image + ducklake-spark jar, :4040), trino (:8543,
      postgres- + hive-connector), captor (:8400), dashboard (:8401/:8402),
      prometheus (:9090), grafana (:3000), jupyterlab (:8888), adminer (:8081)
- [ ] T006 [P] `compose.yaml` — volumes: `/lake` (minio), `/captor-state`
      (watermarks), `/trino-conf`, `/grafana` (dashboards), `/jupyter`
- [ ] T007 `compose.yaml` — netwerk: `aegis_default` aansluiten
      (bron `aegis_db` bereiken als host `aegis_db:5432`), credentials env
      (MinIO root, lake-catalog user/pass, grafana admin)
- [ ] T008 Trino-config: `catalog/aegis_db.properties` (postgres-connector
      → `aegis_db:5432/db=aegis`), `catalog/lake.properties`
      (hive-connector → minio S3, base `s3://aegis-lake`), `jvm.config`
      (heap 1g)
- [ ] T009 DuckLake-init script (`pipeline/init_lake.py`): via duckdb
      (extension `ducklake`) `ATTACH 'ducklake:postgres:dbname=lake ...'`
      met `DATA_PATH 's3://aegis-lake/data/'`; creeert idempotent de
      lake-tabellen uit `data-model.md` §2 (facts.telemetry,
      facts.shipment_events, dims.* ×6, quarantaine-tabel in catalog)
- [ ] T010 [P] `observability/prometheus.yml` (scrape: captor :8400,
      spark :4040 metrics, kafka-exporter via kafka-ui metrics indien
      beschikbaar — anders alleen captor+spark+dashboard)
- [ ] T011 [P] `observability/grafana/dashboards/pipeline.json` —
      dashboards: Kafka-lag (indien exporter; anders topic-counts via
      captor-metriken), `contract_failures_total`, `captor_cycles_total`,
      `captor_errors_total`, `last_event_timestamp_s` per topic,
      spark-job runs
- [ ] T012 [P] JupyterLab-config: kernels `pyspark` + `duckdb`
      (duckdb-kernel met `ducklake`-extensie + S3-secret via env)
- [ ] T013 Adminer-config: servers `aegis_db` (aegis) + `lake-catalog`
      (lake), read-only waar zinvol

**⚠️ CRITICAL**: geen user-story mag beginnen voor deze fase klaar is
**Checkpoint**: `podman compose up` → alle 12 Up; `lake-catalog` leeg maar
reachable; `python pipeline/init_lake.py` creeert 9 lake-tabellen
(VER: `SELECT table_name FROM ducklake_table` in duckdb-shell)

---

## Phase 3: US1 — Spiegel (P1, P1 in spec)

**Files**: `captor/*`

- [ ] T014 [US1] `captor/poller.py` — read-only connect op `aegis_db`
      (REPEATABLE READ per cycle); per-tabel watermarks (data-model §3):
      ts-watermark (telemetry, shipment_events, incidents) +
      created_at + change-detectie (shipments: status/progress/eta) +
      full-snapshot (vehicles, lanes, locations, inventory, drivers)
- [ ] T015 [US1] `captor/poller.py` — Kafka-publisher: record-formaat
      `{payload, src_table, captured_at, cycle_id}` (data-model §1),
      key = record-id (telemetry: `vehicle_id:ts`, inventory:
      `hub_id:sku`); topic per tabel
- [ ] T016 [US1] `captor/poller.py` — bootstrap-modus: volledige
      first-run per tabel (`cycle_id = bootstrap-<ts>`), partial-fail per
      tabel (status `bootstrap_pending`, hervat alleen onafgemaakte)
- [ ] T017 [US1] `captor/poller.py` — idempotentie: overlap-vraag
      (±1 record rond watermark) + persistent watermarks op
      `/captor-state` (json), herstart-resistent
- [ ] T018 [US1] `captor/main.py` — asyncio-timer 30s (jitter ≤ 2s),
      mutex voor concurrente cycles (manual vs interval → 409)
- [ ] T019 [US1] `captor/health.py` — `GET /health` + `POST
      /manual/poll` per `contracts/captor-api.md` (status-codes,
      per-tabel state/watermark/rows, bootstrap-status)
- [ ] T020 [US1] `captor` — prometheus-metriken
      (`captor_cycles_total{trigger,table}`, `captor_rows_captured_total`,
      `captor_errors_total`, `captor_last_cycle_timestamp_s`,
      `captor_bootstrap_pending`) op :8400
- [ ] T021 [US1] `captor/tests/test_idempotency.py` — dubbele
      records/cycles → 1 unieke set in topic; herstart met state-bestand
      → geen duplicaten (Edge: herstart)
- [ ] T022 [US1] `captor/tests/test_manual_poll.py` — POST tijdens
      actieve cycle → 409; bron-down → 503 + /health `error` (Edge:
      concurrente trigger, bron-down)
- [ ] T023 [US1] `captor/tests/test_schema_extension.py` — nieuwe
      onbekende kolom in bron → geaccepteerd (extensie), gekende
      kolommen blijven 1-op-1 (Edge: schema-uitbreiding)
- [ ] T024 [US1] **VER US1**: `podman compose up captor` →
      /health `status: ok` + `bootstrap.done`; console-consumer toont
      records 1-op-1 met `aegis_db` (id's matchen); manual poll → 200
      en 409 op clash; bron neerzetten (temp) → `degraded`, stack up

**Checkpoint US1**: data stroomt aegis_db → Kafka; independent value
geleverd (audit-trail bestaat, topics inspecteerbaar in Kafka UI)

---

## Phase 4: US2 — Contracts + Lake + Federated (P2)

**Files**: `pipeline/*`

- [ ] T025 [US2] `pipeline/contract_check.py` — validator die
      `contracts/*.yaml` laadt: schema (required + types), enums,
      ranges, freshness; retourneert `(ok, violations[])`; standalone
      testbaar zonder Spark (pure Python)
- [ ] T026 [US2] `pipeline/spark_job.py` — structured streaming (of
      micro-batch per 30s-catchup; beslis bij eerste draai op volume —
      research V4: laag, micro-batch ok) leest Kafka-topics,
      dedup (key + laatst `captured_at` wint)
- [ ] T027 [US2] `pipeline/spark_job.py` — contract-enforcement:
      violations → `aegis.quarantine` topic + catalog-tabel
      (topic/record/rule/reason/captured_at), records zelf → quarantaine
      (niet in facts/dims); `contract_failures_total` per topic
- [ ] T028 [US2] `pipeline/spark_job.py` — writer: ducklake-spark
      V2 connector (`df.writeTo("ducklake.<db>.<table>").append()`),
      explicit schemas (VARCHAR/DOUBLE/TIMESTAMPTZ, data-model §1),
      dims met `cycle_ts`/`first_seen`/`last_seen`;
      **fallback**: plain Parquet date-partitioned in `s3://aegis-lake`
      (interface `write_lake(df, table)` abstraheert; beslist bij eerste
      draai — research V2)
- [ ] T029 [US2] `pipeline/spark_job.py` — metrics-endpoint (spark
      :4040 metrics) + graceful shutdown (checkpoint in Kafka offset)
- [ ] T030 [US2] `pipeline/tests/test_enum_violation.py` —
      `status="onbekend"` → quarantaine, niet in lake (US2-AS1)
- [ ] T031 [US2] `pipeline/tests/test_range_violation.py` —
      `fuel_pct=143` → quarantaine (US2-AS4)
- [ ] T032 [US2] `pipeline/tests/test_freshness.py` — geen records in
      6 min → topic-freshness `red` (contract-failures-metrik +
      dashboard-input)
- [ ] T033 [US2] `pipeline/tests/test_dedup.py` — dubbele `id` over 2
      cycles → 1 rij in facts (Edge: herstart/overlap)
- [ ] T034 [US2] **VER US2**: geïnduceerde overtreding → quarantaine +
      Grafana-metrik + níét in lake; Trino (UI :8543) federated query
      live `aegis_db` JOIN lake-parquet < 10 s; DuckDB leest
      `facts.telemetry` (2 dagen ≥ 2 datapunten na bootstrap + 24h)

**Checkpoint US2**: governed lake + federated queries; independent value
(geen onbetrouwbare spiegel meer; provenance bestaat)

---

## Phase 5: US3 — Dashboard (P3)

**Files**: `dashboard/*`

- [ ] T035 [US3] `dashboard/api/duckdb_client.py` — embedded DuckDB met
      `ducklake`-extensie: ATTACH lake (postgres-catalog + MinIO S3
      secret), query-interface voor trends/aggregaties
- [ ] T036 [US3] `dashboard/api/trino_client.py` — federated queries
      (live `aegis_db` + lake) met timeout 10 s + fallback op
      DuckDB-alleen (stale-badging)
- [ ] T037 [US3] `dashboard/api/main.py` — `GET /api/kpi` per
      `contracts/dashboard-api.md`: value + `source_table` +
      `semantic_definition` (uit `contracts/semantics.yaml`) +
      `data_age_s` + `contract_status` (green/yellow/red; yellow =
      quarantaine op deze tabel in 1u) + cache 15 s
- [ ] T038 [US3] `dashboard/api/main.py` — `GET /api/trends/{metric}`
      (6 metrics, data-model/contracts §, bucket 5m/15m/1h/1d,
      from/to)
- [ ] T039 [US3] `dashboard/api/main.py` — `GET /api/incidents`
      (facts + federated join op dims), `GET /api/lineage/{card_id}`,
      `GET /api/quality/quarantine`, `GET /api/status`
- [ ] T040 [US3] `dashboard/api/main.py` — stale-degradation (FR-011):
      backend-down → laatste bekende waarde + `status: stale`, nooit een
      lege pagina; prometheus-metriken voor API-zelf
- [ ] T041 [US3] `dashboard/api/tests/test_kpi_contract.py` —
      KPI-waarde = waarde uit `aegis_db` (tolerantie capture-lag);
      contract-status correct (US3-AS1/AS2)
- [ ] T042 [US3] `dashboard/index.html` — single-file frontend
      (AEGIS theme: deep navy, cyan accent, Rajdhani/JetBrains Mono,
      Chart.js CDN): KPI-rij (OTIF, value in transit, delayed,
      incidents, carbon, low-stock), trends-charts (OTIF/dag,
      incidenten/_lane, cargo-temp per voertuig, value in transit),
      incidenten-tijdlijn; per kaart badge `data van HH:MM` +
      hover/click → semantiek + lineage (US3-AS1/AS2/AS4)
- [ ] T043 [US3] **VER US3**: dashboard (:8402) toont alle 6 KPI's met
      context-badges; trends ≥ 2 datapunten; platform neerzetten →
      command center (8765/8300) onbetroffen; herstart → geen
      duplicaten in lake

**Checkpoint US3**: eindproduct zichtbaar; de use case is zichtbaar
(elk datapunt = semantiek + freshness + provenance)

---

## Phase 6: Observability & Access (FR-012/FR-009) — parallel mogelijk aan T035-T043

- [ ] T044 [P] Prometheus-draft + Grafana-dashboard live draaien;
      alert-regels: `contract_failures` > 0 in 5 min,
      `last_event_timestamp` > 5 min oud, captor-errors > 0
- [ ] T045 [P] Kafka UI + MinIO Console + Adminer + JupyterLab +
      Trino UI bereikbaar op vaste host-ports; logins werken
      (quickstart §2 tabel 1-op-1)
- [ ] T046 [P] `quickstart.md`-verificatie doorlopen op de draaiende
      stack (elke verificatie-lijn daadwerkelijk uitgevoerd)

---

## Phase 7: Final verification (success criteria uit spec.md)

- [ ] T047 Volledige quickstart-herstart: `down` → `up` → binnen 5 min
      dashboard met live data (succes-criterion 1)
- [ ] T048 Geïnduceerde contract-overtreding → quarantaine + metrik +
      níét in lake (SC 2)
- [ ] T049 Federated Trino-query < 10 s (SC 3)
- [ ] T050 Terugtraceerbaarheid: willekeurige KPI-kaart →
      `aegis_db`-tabel in < 10 min via lineage-endpoint (SC 4)
- [ ] T051 Platform down → command center 100% functioneel; up → geen
      duplicaten (SC 5)
- [ ] T052 `podman stats`: stack < 14 GB RAM (SC 6)
- [ ] T053 Alle 10+1 user-afspraken + FR-001..FR-012 gecheckt tegen
      `checklists/completeness.md`; markers updaten op [x]

**DONE-definitie (Constitution III)**: elke task met VER gegand, elke
success-criterion gemeten op de draaiende stack, completeness-checklist
volledig. Niet "code geschreven" = done, maar "acceptance-criteria
gemeten = done".
