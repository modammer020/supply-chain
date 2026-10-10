# Research: AEGIS Analytics Platform (002) — Fase 0

**Date**: 2026-10-09 · **Plan-ref**: `plan.md` § Phase 0

## V1. Trino-DuckLake-connector: status & beslissing

**Bevindingen (bron: trino issue #26523, open sinds sep-2025; DuckLake-announcing-blog):**

- Er is **geen officiële Trino-DuckLake-connector**. Issue #26523 staat open;
  er bestaan twee community-POC's (altertable-ai/trino-ducklake;
  awitten1/trino-ducklake voor Trino 479, **read-only**, "mostly written by
  AI", geen compose-ready product).
- Trino's officiële `duckdb`-connector leest lokale `.duckdb`-bestanden via
  JDBC — die leest géén DuckLake.
- **DuckLake v1.0 is GA** (2026-04-13, DuckDB ≥ 1.5.2, MIT): productie-ready
  spec, metadata in een SQL-catalog (DuckDB/SQLite/**Postgres**/MySQL), data
  als plain Parquet op object storage, data-inlining voor kleine writes,
  time-travel, Iceberg-interoperabiliteit.

**Beslissing:**
- DuckLake blijft de lakehouse-laag (user-wens + v1.0-GA maakt het veilig).
- **Trino leest DuckLake géén via DuckLake-metadata, maar via de onderliggende
  Parquet-bestanden** met de Trino `hive`-connector (append-only layout,
  date-partitioned) — plus de `postgres`-connector voor live `aegis_db`.
  De "live + historie in één query" is daarmee intact (FR-006).
- **DuckDB (embedded in dashboard-API) is de primaire reader** van de lake:
  native DuckLake-read met snapshot-semantiek en time-travel.
- Als de community-connector later volwassen is (check per release), kan
  Trino upgraden naar echte DuckLake-metadata — architectuur ongewijzigd.

## V2. Spark-schrijven naar DuckLake

**Bevinding (bron: motherduckdb/ducklake-spark):**
- Er is een officiële **Spark DataSource V2 connector** (DuckDB Labs) voor
  het schrijven naar DuckLake: `df.writeTo("ducklake.<catalog>.<table>").append()`.
- Beperkingen: **write-only, append-only**, tabel moet vooraf bestaan
  (DDL via DuckDB), geen complexe typen (list/struct/JSON) → our schema's
  zijn flat (VARCHAR/INT/DOUBLE/TIMESTAMPTZ — ok), strikte types
  (VARCHAR in plaats van BLOB/UUID), `INTEGER` ≠ `BIGINT` (explicit schemas).
- De connector gebruikt DuckDB's ducklake-extension voor de catalog
  (Postgres/SQLite/MotherDuck) en hadoop S3A voor de data-files.

**Beslissing:**
- Spark leest Kafka (micro-batch per 30s-catchup) → contract-validator →
  **schrijft per tabel via ducklake-spark** (append).
- Catalog: **eigen kleine Postgres-container `lake-catalog`** (postgres:16)
  in dezelfde compose — niet SQLite (toekomst: multi-writer + dashboard-API
  kan de catalog ook direct raadplegen voor provenance/snapshots).
- Tussenstap: DuckDB (in een `duckdb-init` entrypoint of dashboard-API)
  creeert de tabel-definities bij eerste start (idempotent DDL).
- Fallback als de connector op de gekozen Spark-versie struikelt: Spark
  schrijft plain Parquet (date-partitioned) naar MinIO en DuckDB leest via
  DuckLake's "existing Parquet zonder deep copy" — architectuur intact.

## V3. Kafka-image & tooling

**Beslissing:**
- `apache/kafka:3.9.0` (KRaft single-node, default image) — 1 broker,
  retention 7 dagen (FR: MinIO-down → geen data-verlies, buffering).
- Debug: `kafka-topics.sh` / `kafka-console-consumer.sh` via `podman exec`
  (geen extra container); health-check via KRaft-endpoint.
- Topics (key = record `id` voor partitioning/dedup):
  `aegis.events.shipment`, `aegis.events.telemetry`,
  `aegis.dim.{shipments,vehicles,lanes,locations,inventory,drivers}`,
  `aegis.metrics`, `aegis.quarantine`.

## V4. Telemetrie-volume (gemeten, 2026-10-09, uit `aegis_db`)

| Tabel | Records | Opmerking |
|---|---|---|
| telemetry | 16,132 | ~1.3k–5.7k/uur (sim actief), ≈ 1–1.5 rec/sec |
| shipment_events | 71 | lage frequentie |
| shipments | 44 | dimensie (status verandert) |
| vehicles | 51 | dimensie |
| incidents | 7 | |
| inventory | 14 | |
| lanes | 38 | |
| locations | 62 | |
| drivers | 51 | |

**Implicaties:**
- 30-sec-poll = < 100 telemetry-records/cycle → micro-batch is triviale
  last; Spark local-mode ruimschoot.
- **Bootstrap-window: volledige historie** is klein (< 20k records).
  Beslissing: full bootstrap alles, **geen** window-limiet (opent voor
  retentie-beslissing bij schaal: 90 dagen is de MVP-retentie).
- `shipment_events` heeft `created_at`-achtige `ts`; watermarks:
  `ts` (telemetry, shipment_events), `created_at` (shipments, incidents),
  full-snapshot (vehicles, lanes, locations, inventory, drivers — kleine
  tabellen, 30-sec refresh is goedkoop en lossless).

## Overige beslissingen & versies

| Onderdeel | Keuze | Waarom |
|---|---|---|
| DuckDB | ≥ 1.5.2 (latest stable) | vereist voor ducklake-extensie (V1) |
| ducklake-spark | 0.1.x pre-release (DuckDB Labs) | enige officiële Spark-writer (V2) |
| Trino | 48x (current), connectors: `postgres`, `hive` | live + Parquet; geen DuckLake-extensie nodig |
| Spark | 3.5.x (Python 3.12-compat; venv apart van Python 3.14 voor captor) | stability; PySpark 3.5 is wijdste compat met ducklake-spark jar |
| MinIO | RELEASE.2025-x (latest stable) | S3-compatible voor Spark S3A + DuckDB httpfs |
| Kafka | apache/kafka 3.9.0 KRaft | V3 |
| lake-catalog | postgres:16 (eigen container, eigen db `lake`) | DuckLake-catalog + provenance raadpleging; los van `aegis_db` (Constitution II) |
| Grafana | grafana/grafana OSS, 1 dashboard (pipeline) | open item beslist: 1 dashboard |
| Prometheus | prom/prometheus, 15s scrape | FR-009 |
| Python venv | eigen `.venv` (3.14) voor captor + dashboard-API | los van AEGIS `.venv` |
| Frontend | single-file `dashboard/index.html`, AEGIS theme (Rajdhani/JetBrains Mono, deep navy/cyan), Chart.js uit CDN (keyless) | Constitution IV/VI |

## Risico-updates (van plan.md)

- **V1-afgedaan**: Trino-DuckLake = bevestigd niet-productie → Parquet-fallback
  is nu *het* ontwerp (geen risico meer, wel genoteerd als bewust-keuze).
- **V2-nieuw**: ducklake-spark is pre-release → mitigatie: Parquet-direct
  fallback (DuckLake "existing parquet" feature) + contract-tests die
  de writer abstract testen (interface `write_lake(df, table)`).
- **Telemetrie-volume**: laag (gemeten) → geen windowing nodig;
  Spark-batch-per-cycle volstaat (vereenvoudiging: micro-batch interval
  = poll-interval, geen continu streaming).

## Open na fase 0 (overnaar fase 1)

- Exacte ducklake-spark jar-versie + compat-matrix met Spark 3.5 (checken
  bij eerste `compose up`; fallback staat paraat).
- Trino `hive`-connector config voor `file://`/S3 op MinIO (S3A credentials
  via Trino `s3` properties).
- MinIO root-credentials (demo: vaste in compose-env, documenteren).
