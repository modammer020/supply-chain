# Quickstart: AEGIS Analytics Platform (002)

**Doel**: `podman compose up` → binnen 5 min live analytics-dashboard van de
bestaande AEGIS-data, plus toegang tot elk tool-console.

## 0. Voorwaarden

- Podman 5.7 + compose provider (zelfde setup als AEGIS)
- `aegis_db` draait op host-port **5433** (bestaand)
- Host: ≥ 14 GB vrije RAM (gemeten: 8 cores / 30 GB → ok)

## 1. Start

```bash
cd /home/demouser/aegis-analytics
podman compose up -d          # 12 services
podman compose ps             # alle Up? (kafka + minio moeten ready zijn)
```

**Wacht tot:**
- `curl localhost:8400/health` → `"status": "ok"`, `"bootstrap": {"state": "done"}`
- Grafana (`:3000`) toont `captor_cycles_total` die stijgt

## 2. Console-toegang (FR-012)

| Tool | URL | Login |
|---|---|---|
| **Analytics Dashboard** | `http://localhost:8402` | — |
| Dashboard-API | `http://localhost:8401/api/kpi` | — |
| Captor (health + manual poll) | `http://localhost:8400/health` · `curl -X POST localhost:8400/manual/poll` | — |
| Kafka UI | `http://localhost:8040` | geen |
| JupyterLab (Spark + DuckDB) | `http://localhost:8888/lab` | token uit `logs` bij eerste start |
| Trino UI (federated SQL) | `http://localhost:8543` | geen (lokaal) |
| MinIO Console | `http://localhost:9001` | `minioadmin` / `AEGISlake!2026` |
| Adminer (aegis_db + lake-catalog) | `http://localhost:8081` | aegis/aegis · lake/lake |
| Grafana | `http://localhost:3000` | `admin` / `admin` |
| Prometheus | `http://localhost:9090` | geen |

## 3. Verificatie per user story

### US1 — Spiegel (P1)
```bash
# 1. health: per-tabel status + watermarks
curl -s localhost:8400/health | python3 -m json.tool

# 2. topic-inhoud vergelijken met aegis_db
podman exec -it <captor> podman exec aegis_db psql -U aegis -d aegis -c \
  "SELECT count(*) FROM telemetry;"
podman exec aegis_kafka kafka-topics.sh --bootstrap-server localhost:9092 \
  --describe --topic aegis.events.telemetry

# 3. handmatige trigger (409 als cycle actief)
curl -i -X POST localhost:8400/manual/poll
```

### US2 — Contracts + lake (P2)
```bash
# contract-overtreding induceren (test-script)
python3 pipeline/tests/inject_bad_record.py   # status="onbekend" + fuel_pct=143

# quarantaine-check
curl -s "localhost:8401/api/quality/quarantine?limit=5"

# Grafana: contract_failures_total is +2
# federated Trino-query (live + historie):
# in Trino UI (:8543):
#   SELECT s.id, s.status, d.status AS lake_status
#   FROM aegis_db.shipments s JOIN dims.shipments d USING (id) LIMIT 5;
```

### US3 — Dashboard (P3)
- Open `http://localhost:8402`
- Elke KPI-kaart toont: **waarde + bron + semantiek + "data van HH:MM"**
- Click op een kaart → lineage (bron-tabel, topic, cycle-id, contract-status)
- Waarden matchen `aegis_db` / `curl localhost:8300/api/kpi` (binnen capture-lag)

## 4. Dagelijks gebruik

| Taak | Hoe |
|---|---|
| Data forceren | `curl -X POST localhost:8400/manual/poll` |
| Pipeline-health | Grafana `:3000` (Kafka-lag, contract-failures, cycles) |
| Ad-hoc analyse lake | JupyterLab `:8888` (duckdb-kernel: `duckdb.sql("SELECT ... FROM facts.telemetry")`) |
| Live + historie query | Trino UI `:8543` |
| Raw events bekijken | Kafka UI `:8040` → topic `aegis.events.*` |
| Quarantaine inspecteren | `GET :8401/api/quality/quarantine` of Adminer `lake-catalog` |

## 5. Stop / clean

```bash
podman compose down            # platform stopt; AEGIS blijft draaien (FR-010)
podman compose down -v         # + volumes (lake + watermarks + kafka) — WISKT HISTORIE
```

## 6. Architectuur-overzicht

Zie `architecture.html` (neon-diagram met console-lijnen per tool, pulsende
dataflows, hover-tooltips) — open in de browser:

```bash
xdg-open /home/demouser/aegis/specs/002-analytics-platform/architecture.html
```
