# Feature Specification: AEGIS Analytics Platform (Spec 002)

**Feature Branch**: `002-analytics-platform`

**Created**: 2026-10-09

**Status**: Draft — co-creatie met user, besproken designkeuzes: captor=poller (A), data lake=DuckLake, dashboard=eigen frontend (B), monitoring=Prometheus+Grafana

**Input**: User description: "Apart project met eigen podman-compose stack (Kafka, Spark, DuckDB/DuckLake, Trino, MinIO, Grafana/Prometheus). Spiegel de bestaande AEGIS-data (PostGIS) naar een analytics dashboard op basis van events. PostGIS blijft single source of truth (ongeraakt). Captor: poller op 30 sec + handmatige trigger."

---

## Context & Probleemstelling

AEGIS v3 (spec 001) is een supply-chain command center: PostGIS (db `aegis`, container
`aegis_db`, port 5433) + FastAPI (`api.py`, port 8300) + single-file frontend (8765).
De data is al analyses-ready qua vorm — `shipment_events` en `telemetry` zijn event
streams; `vehicles`, `lanes`, `locations`, `inventory`, `shipments`, `drivers` zijn
dimensies; `/api/kpi` definieert de KPI's (OTIF, value in transit, delayed, incidents,
carbon, low-stock SKUs).

**Gat:** er is geen historische laag, geen federated query-laag, geen data
observability, en geen dashboard dat op basis van *events over tijd* analiseert.
Daarnaast is de Gartner-geïdentificeerde #1 bottleneck van agentic AI de afwezigheid
van een **AI-Ready Data / context layer** (semantiek, freshness, provenance,
contract-enforcement) — zie `use-case-ai-ready-data-context-layer.md` in deze spec-map.

## Doel

Eén apart project `aegis-analytics` (eigen podman-compose project) dat de bestaande
AEGIS-data **spiegelt** (read-only, verplaatst niets, bremt de command center nooit)
naar een streaming data platform, en daarop een **analytics dashboard** draait dat
live + historische data federated toont — waarbij elk datapunt semantisch
bevestigd, versheidsgecertificeerd en terugtraceerbaar is (de context-layer use case,
in praktijk gebracht).

### Niet-doelen (MVP-grenzen)

- Geen Debezium/CDC, geen K8s, geen multi-broker Kafka, geen Spark-cluster
  (local mode), geen object-storage-cluster (één MinIO is genoeg), geen wijzigingen
  aan `aegis_db` of `api.py` van AEGIS (option A: PostGIS blijft zoals hij is).
- Geen access-control-per-agent (dat is horizon, fase 5 van de use case).

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Spiegel de live AEGIS-data naar het platform (Priority: P1)

De data-architect/start-up draait `podman compose up` in `aegis-analytics/` en de
captor begint automatisch te pollen (30 sec) op `aegis_db`. Alle event-tabellen
(`shipment_events`, `telemetry`) en dimensies (`shipments`, `vehicles`, `lanes`,
`locations`, `inventory`, `drivers`) stromen als events in Kafka-topics. Er is een
handmatige trigger om een poll-cycle nu te forceren.

**Why this priority**: zonder dit is er niets te analyseren. Dit is de ruggegraat —
elk topic is tevens de audit-trail (provenance) van de stack.

**Independent Test**: `curl` de captor-health-endpoint; consumeer een topic met
`kafka-console-consumer` en zie dat de records 1-op-1 overeenkomen met de
`aegis_db`-inhoud; `GET /manual/poll` forceert een cycle en de lag-metrik in
Grafana daalt.

**Acceptance Scenarios**:

1. **Given** het platform draait en `aegis_db` bevat N `shipment_events`, **When**
   de captor 1 cycle draait, **Then** staan er N corresponderende records in
   `aegis.events.shipment` met identieke `id`-waarden en een `captured_at`-timestamp.
2. **Given** de sim-engine voegt 3 nieuwe telemetrie-records toe aan `aegis_db`,
   **When** de volgende poll-cycle (≤ 30 sec) draait, **Then** staan die 3 records in
   `aegis.events.telemetry` zonder duplicaten (idempotentie via `id`).
3. **Given** de stack is net gestart, **When** de captor de eerste cycle draait,
   **Then** worden de *bestaande* volledige tabellen als initial-snapshot gestuurd
   (bootstrap), zodat het dashboard direct met volle historie start.
4. **Given** `aegis_db` is tijdelijk onbereikbaar, **When** een poll-cycle draait,
   **Then** faalt de cycle met een zichtbare fout (Grafana: `captor_errors`-metrik,
   dashboard: "bron offline"-badge) — neergooien van de stack en geen data-verlies.

---

### User Story 2 - Contracts, lake en federated queries (Priority: P2)

De data-engineer definieert per topic een data contract (YAML: schema, enum's zoals
`status`/`severity`/`kind`, range-checks zoals `fuel_pct` 0–100, freshness-SLA).
Spark (structured streaming) leest Kafka, enforce de contracts, en schrijft de
governed data naar DuckLake in MinIO. Trino queryt DuckLake én de live
`aegis_db` (Postgres-connector) in één federated query.

**Why this priority**: dit is de Gartner-kern — "data contract in documentatie is
een policy; data contract in de pipeline is een guardrail". Zonder enforcement is de
lake een onbetrouwbare spiegel; zonder federated queries is er geen "live + trend in
één query" verhaal.

**Independent Test**: injecteer een record met ongeldige `status` in een test-topic;
de Spark-job markeert het als quarantaine (niet in de lake) en Grafana telt de
contract-failure. Query Trino: `SELECT` die DuckLake-tabel JOIN met
live-`shipments` uit Postgres — resultaten komen binnen < 10 sec.

**Acceptance Scenarios**:

1. **Given** een contract met enum `status ∈ {in_transit, delivered, delayed, ...}`,
   **When** een event met `status = "onbekend"` binnenkomt, **Then** gaat het record
   naar een quarantaine-locatie (niet in de facts-lake), en groeit de
   `contract_failures`-metrik met 1.
2. **Given** de lake bevat fact-data van vandaag en gisteren, **When** het dashboard
   vraagt om OTIF-trend over 2 dagen, **Then** levert DuckDB de berekening zonder
   enige toegang tot `aegis_db`.
3. **Given** Trino draait, **When** een query PostGIS-live-data JOIN
   DuckLake-historie doet, **Then** toont het resultaat zowel de huidige als de
   historische staat in één response.
4. **Given** een `fuel_pct`-waarde van 143 (bug in bron), **When** de
   range-check 0–100 actief is, **Then** wordt het record in quarantaine en
   genoteerd in de contract-log.

---

### User Story 3 - Het analytics dashboard (Priority: P3)

De supply-chain manager opent het dashboard en ziet KPI-kaarten (OTIF%, value in
transit, delayed shipments, open incidents, carbon, low-stock SKUs), trends over
tijd (OTIF-per-dag, incidenten-per-lane, ETA-drift, cargo-temperaturen) en een
incidenten-tijdlijn. Elke kaart toont: bron-tabel, semantische definitie van de
meetwaarde, en de leeftijd van de data (freshness).

**Why this priority**: dit is het zichtbare eindproduct — het bewijs dat de stack
waarde levert. (P3 in *implementatievolgorde* omdat het op P1+P2 bouwt; P1-waarde
is dat het de use case zichtbaar maakt.)

**Independent Test**: open de dashboard-URL; elke KPI-kaart toont een waarde die
overeenkomt met `aegis_db`/`/api/kpi` (binnen de capture-lag); hover op een kaart
laat bron + semantiek + timestamp zien; de OTIF-trend-chart toont minimaal de
bootstrap-historie.

**Acceptance Scenarios**:

1. **Given** het dashboard laadt, **When** de KPI-rij weergegeven is, **Then**
   matchen de waarden met de live `aegis_db` (tolerantie = capture-lag) en toont
   elke kaart een "data van HH:MM" badge.
2. **Given** een contract-failure op `shipments.status` in de afgelopen uren,
   **When** de manager de OTIF-kaart bekijkt, **Then** toont de kaart een
   "gebaseerd op gedegegrade data"-indicator.
3. **Given** de command center op 8765 draait, **When** het dashboard op z'n eigen
   port draait, **Then** zijn de twee onafhankelijk: neerhalen van het platform
   beïnvloedt de command center niet (en andersom).
4. **Given** 24 uur aan bootstrap- + live-events in de lake, **When** de
   trends-pagina opent, **Then** toont de OTIF-per-dag chart ≥ 2 datapunten.

---

### Edge Cases

- **Dubbele records**: de captor pollt overlappingen (een record verscheen in twee
  cycles) → idempotentie via natuurlijk-`id` per topic (Kafka `key = record id`,
  dedup in Spark via window over `captured_at`).
- **Schema-gevoeligheid van de bron**: `aegis_db` krijgt een nieuwe kolom
  (bijv. via een `migrate_*.sql`) → de captor stuurt de nieuwe kolom als
  extensie; de contract-validator accepteert onbekende kolommen maar *eist* dat de
  gekende kolommen binnen contract blijven (fail-safe, niet fail-loud op
  uitbreidingen).
- **Lag accumulatie**: Kafka lag groeit (captor-stroom vs. Spark-behandeling) →
  Grafana-dashboard met `kafka_consumer_lag`-alert; het dashboard toont de
  freshness-badges zodat geen "stale = fout" verward wordt met "verse data".
- **Herstart mid-stream**: platform stopt/start → captor start waar hij stopte
  (watermark per tabel in een kleine state-store; idempotentie voorkomt
  duplicaten in de lake).
- **Handmatige trigger tijdens een cycle**: `POST /manual/poll` tijdens een actieve
  cycle → 409 (cycle al actief), geen overlappende runs.
- **MinIO/Typhoeus-down**: Spark kan niet schrijven → buffered in Kafka
  (retention 7 dagen), geen data-verlies; dashboard toont "lake-stroom
  onderbroken" status.
- **PostGIS-down tijdens bootstrap**: bootstrap faalt partially → per-tabel
  status in captor-health; volgende cycle hervat alleen de onafgemaakte tabellen.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Systeem MOET de `aegis`-database read-only spiegelen naar
  Kafka-topics via een poller met 30-seconden interval, met idempotente
  overdracht (geen duplicaten in de lake bij herhaalde cycles).
- **FR-002**: Systeem MOET een handmatige trigger bieden (`POST` naar de
  captor) die één poll-cycle nu uitvoert, en 409 teruggeeft wanneer een cycle
  al actief is.
- **FR-003**: Systeem MOET bij eerste start een full-bootstrap doen: de
  volledige huidige inhoud van alle fact- en dimensietabellen als snapshot in
  Kafka plaatsen, zodat het dashboard direct met volledige historie start.
- **FR-004**: Systeem MOET per topic een YAML-data contract hebben
  (schema, enum's, ranges, freshness-SLA) dat de Spark-pipeline enforce vóór
  dat data in de lake komt; overtredingen gaan naar quarantaine + tellen mee
  in een observability-metrik.
- **FR-005**: Systeem MOET de lake opslaan in DuckLake-formaat in MinIO
  (facts partitioned per dag; dims als snapshot-versies), zodat DuckDB, Spark
  en Trino allemaal kunnen lezen.
- **FR-006**: Systeem MOET via Trino federated SQL bieden over zowel
  DuckLake (historie) als de live `aegis_db` (Postgres-connector).
- **FR-007**: Het dashboard MOET per KPI-kaart weergeven: waarde, bron-tabel,
  semantische definitie (mens-leesbaar), en de leeftijd van de data
  (freshness-timestamp).
- **FR-008**: Het dashboard MOET minimaal bevatten: KPI-rij (OTIF, value in
  transit, delayed, incidents, carbon, low-stock), OTIF-trend per dag,
  incidenten-per-lane, cargo-temperatuur per voertuig, incidenten-tijdlijn.
- **FR-009**: Systeem MOET pipeline-observability bieden via
  Prometheus+Grafana: Kafka-lag, contract-failures, captor-cycles, laatste
  event-timestamp per topic.
- **FR-010**: Systeem MOET onafhankelijk van de AEGIS-command center draaien:
  neerhalen van het platform mag `aegis_db`, `api.py` (8300) of
  `web/index.html` (8765) niet beïnvloeden.
- **FR-011**: Systeem MOET graceful degraderen: bij bron-, MinIO- of
  Trino-uitval toont het dashboard de laatste bekende waarden met een zichtbare
  stale/badge-status — geen lege pagina, geen hard-fail (Constitution I).
- **FR-012**: Systeem MOET een eigen browser-console/login bieden voor ELKE
  tool in de stack: Kafka (Kafka UI), Spark + DuckDB (JupyterLab met
  pyspark-/duckdb-kernels), Trino (eigen Web UI), MinIO (eigen Console),
  lake-catalog + aegis_db (Adminer), pipeline-observability (Grafana +
  Prometheus). Elke console op een vaste host-port; default-logins en
  toegangswijze gedocumenteerd in `quickstart.md` (Constitution I:
  werkt vanaf eerste load).

### Key Entities

- **Topic/Stream** (Kafka): `aegis.events.{shipment,telemetry}`,
  `aegis.dim.{shipments,vehicles,lanes,locations,inventory,drivers}`,
  `aegis.metrics` — elk met `captured_at` en de oorspronkelijke `id`.
- **Data Contract** (YAML per topic): schema, enum's, ranges,
  freshness-SLA, owner.
- **Lake Table** (DuckLake in MinIO): `facts.*` (per dag gepartitioneerd),
  `dims.*` (snapshot-versies), `quarantine.*`.
- **Dashboard Card** (API-model): `value`, `source_table`,
  `semantic_definition`, `data_age_s`, `contract_status`.
- **Captor State**: per-tabel watermark (laatst-gezagene `id`/`created_at`),
  bootstrap-status.
- **Metrics** (Prometheus): `captor_cycles_total`, `captor_errors_total`,
  `kafka_consumer_lag`, `contract_failures_total`, `last_event_timestamp_s`.

## Clarifications

- **Q: PostGIS vervangen door plain Postgres?** A: Nee — option A;
  `aegis_db` blijft ongewijzigd (PostGIS = Postgres + extensie; het platform
  is bron-agnostisch en leest gewoon SQL-tabellen).
- **Q: CDC-mechanisme?** A: Poller (vraag 1 = A); Debezium is een latere
  upgrade-option, geen MVP-scope.
- **Q: Lake-formaat?** A: DuckLake (vraag 2), in MinIO (vraag 4 = beide).
- **Q: Dashboard?** A: Eigen lightweight frontend (vraag 3 = B), geen
  Grafana-afhankelijkheid voor het analytics-dashboard (Grafana is alleen
  voor pipeline-observability).
- **Q: Captor-interval?** A: 30 seconden + handmatige trigger (FR-001/FR-002).

## Success Criteria

- [ ] `podman compose up` → binnen 5 min is er live data in het dashboard
  (bootstrap + eerste poll-cycles), zonder enige wijziging aan de AEGIS-command
  center.
- [ ] Een geïnduceerde contract-overtreding (test-data) verscheint in
  quarantaine + Grafana-metrik, en níét in de lake.
- [ ] Federated Trino-query (live Postgres + DuckLake) levert resultaat < 10 sec.
- [ ] Elk dashboard-datapunt toont bron + semantiek + leeftijd; een
  mens kan een waarde in < 10 min teruggerekenen naar de `aegis_db`-tabel.
- [ ] Platform neerhalen (compose down) → command center (8765/8300) blijft 100%
  functioneel; platform herstarten → geen duplicaten in de lake.
- [ ] RAM-gebruik van de stack < 14 GB (host 30 GB; AEGIS zelf ~1–2 GB).
- [ ] Elke tool heeft een eigen browser-console (Grafana, Prometheus,
      JupyterLab, Trino UI, MinIO Console, Kafka UI, Adminer) — port +
      default-login gedocumenteerd in `quickstart.md` (FR-012).

## Out of Scope (horizon, volgende specs)

- Debezium/echte CDC (als 30-sec-lag te groot blijkt).
- Inference-time access control per agent (fase 5 use case).
- Autonomous governance-agents die contracts interpreteren/onderhandelen
  (Gartner 2030-richting).
- Meerdere bronnen dan AEGIS (platform is ontworpen uitbreidbaar, maar MVP = 1 bron).
