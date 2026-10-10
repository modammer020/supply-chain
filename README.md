# AEGIS — Supply Chain Platform

Eendagsklaar supply-chain platform in twee lagen:

| Repo | Port | Wat het is |
|---|---|---|
| [`command-center/`](command-center/) | 5433 (DB) · 8300 (API) · 8765 (UI) | **Realtime operatietafel** — live kaart van lanes, voertuigen, voorraad, incidenten en weer, met een dedicated AI-analyst die continu rapporteert |
| [`analytics-dashboard/`](analytics-dashboard/) | 80–13 containers, o.a. 8401/8402 (API+dashboard) | **AI-ready analytics platform** — spiegelt dezelfde live data via Kafka naar een DuckLake-lakehouse met data-contracts, federated SQL (Trino) en een KPI-dashboard met lineage |

Beide delen draaien **volledig onafhankelijk** van elkaar: het analytics-platform leest `aegis_db` read-only en raakt de command-center niet aan.

---

## Use case

Een logistieke organisatie (trucks, maritieme aanvoer, distribution centers) wil op één plek:

1. **Opereren** — de dispatcher ziet realtime elke lane, elk voertuig, elke
   voorraadpositie. Bij een incident (ongeluk op de A2) wil hij direct weten:
   *welke lanes zijn getroffen, wat is de omleiding, hoeveel minuten kosten we?*
   Hij kan de chauffeur bellen (CALL DRIVER), een omleiding accepteren, en de
   impact per laneroute vergelijken (1×/4×/16× timesimulatie).
2. **Analyseren** — de data-engineer/analist wil *dezelfde* data historisch,
   geverifieerd en in één federated query terug: contractgevalideerde events,
   KPI's met semantiek en bronvermelding, quarantaine bij schema-drift, en
   lineage van elke KPI-kaart terug naar de bron. Niet een data-warehouse dat
   drie dagen oud is, maar een **context layer** die live blijft.
3. **Blijven monitoren** — een standing analyst (LLM-agent) scant elke 3
   minuten de operatie: wat is veranderd, wat verdient prioriteit, wat
   escaleert naar P1? Z'n briefings verschijnen in het ANALYST-paneel van de
   command center én in het analytics-dashboard.

Demo-first, real-data-ready: alle data is gesimuleerd (deterministische
ongeluk-sim, per-lane traffic-model, gesynthetiseerde telemetrie), maar de
knelpunten voor echte koppeling staan expliciet gemarkeerd (`POST /api/telemetry`
als telemetrie-connector, RTCPeerConnection voor CALL DRIVER, echte
traffic-feed in `traffic()`/`conditions()`).

---

## Architectuur

### LAYER 1 — Command Center (`command-center/`)

```
                       ┌─────────────────────────────────────────────┐
                       │        web/index.html  (Leaflet + ESRI)     │
                       │  KPI-wall · tabs (Analyst/Exception/Lanes/  │
                       │  Fleet/Inventory/Maritime/Weather) · OSRM   │
                       │  route-trails · timesim · detail-drawer     │
                       │  CALL DRIVER · SIM ACCIDENT · reroute       │
                       └──────────────┬──────────────────────────────┘
                                      │ http (8765 → 8300)
   OSRM ──routes/alternatieven──┐     ▼
   Open-Meteo ──weer──────┐     ┌─────────────┐
   AIS ──maritiem────────┤     │   api.py    │  FastAPI, keyless
                         └────► │  (8300)     │  dag-cache + kv-cache
                                └──────┬──────┘
                                ┌─────┴──────────────────────────┐
                                │  aegis_db (PostGIS 16, :5433)  │
                                │  locations · lanes · vehicles  │
                                │  shipments · telemetry ·       │
                                │  inventory · incidents ·       │
                                │  shipment_events · kv-cache ·  │
                                │  routes_cached                 │
                                └─────▲──────────────────────────┘
                                      │ read-only (analytics)
                       ┌──────────────┴──────────────────────────┐
                       │  agents/watcher.py  (elk 3 min)         │
                       │  polt API → operationele briefing →     │
                       │  hermes researcher-bot (standing        │
                       │  analyst-mandaat) → data/insights.jsonl │
                       └──────────────┬──────────────────────────┘
                                      ▼
                              /api/insights → ANALYST-paneel
```

**Kernprincipes** (constitution in `command-center/.specify/memory/constitution.md`):
Demo-First/Real-Data-Ready · Single Source of Truth (PostGIS) · Spec-Driven ·
Open & Keyless (alle openbare APIs, geen API-keys).

**API endpoints**: `/api/overview` (bootstrap), `/api/route/{lane}` (OSRM +
alternatieven, Polyline6, gedag-cache), `/api/incidents` (ongeluk-sim +
omleiding met delta km/min), `/api/traffic`, `/api/weather` (kv-cache),
`/api/conditions`, `/api/telemetry` (push — echte connector), `/api/insights`.

### LAYER 2 — Analytics Platform (`analytics-dashboard/`)

Gartner "AI-Ready Data / context layer"-pattern: de live operationele DB wordt
gespiegeld naar een streaming stack met geverifieerde contracts.

```
aegis_db (PostGIS, READ-ONLY — raakt command-center niet aan)
    │  captor: bootstrap + poll elk 30s + manual trigger · watermarks per source
    ▼
Kafka (10 topics: events / dims / metrics)          ← immutabele audit-trail
    ▼
Pipeline: contract-validator (YAML per topic, contracts/*.yaml)
    │        violations → catalog.quarantine + Grafana-metrik + lineage-tag
    ▼
DuckLake lakehouse:
  · MinIO (Parquet, s3://aegis-lake)     — data path
  · lake-catalog (Postgres)              — DuckLake metadata
    ▼
Query-layers:
  · DuckDB (embedded)  — trends op het lake
  · Trino (federated)  — LIVE aegis_db JOIN lake in één query
    ▼
Dashboard (8402) + API (8401)
  · 4 tabs: KPI / Quality / Lineage / Engineer
  · elke KPI-kaart: waarde + bron + semantiek + leeftijd + contract-status
  · /api/quality/quarantine, /api/lineage/{kpi}
  · data-engineer agent: inbox (.md/.json) → JSON dossiers → PDF
    (make engineer · make pdf VEHICLE=TRK-104)
```

**Support services**: Prometheus + Grafana (pipeline-health dashboard),
JupyterLab (DuckLake-kernel voor ad-hoc analyse), Kafka UI, Adminer
(twee DB's: `aegis` + `lake`), MinIO Console.

### Gegevensflow tussen de lagen

```
operatie (realtime)                     analyse (historisch + live)
─────────────────────                   ───────────────────────────
aegis_db  ──read-only mirror──►         Kafka → contracts → DuckLake
  │                                            │
  ▼ API 8300                                    ▼
command-center UI 8765                       dashboard 8402
  ▲                                            ▲
  └─ insights.jsonl ◄─ watcher agent ◄────────┘
     (analyst-briefings in beide panels)
```

---

## Deployment (op een host met `podman`)

**Prereqs**: `podman` + `podman compose`, Python 3.12+ (voor de host-venvs),
vrije poorten 5433/8300/8765 (layer 1) en de poorten in
`analytics-dashboard/Makefile` (layer 2).

### 1. Command center

```bash
cd command-center
python3 -m venv .venv && . .venv/bin/activate
pip install "fastapi" "uvicorn[standard]" "psycopg2-binary" "httpx"
# (afhankelijkheden staan in compose/Dockerfile-context; pip-list in Dockerfile
#  van analytics is de referentie)

podman compose up -d                          # 1. aegis_db (PostGIS 16, :5433)
.venv/bin/uvicorn api:app --host 127.0.0.1 --port 8300   # 2. API
python3 -m http.server 8765 --bind 127.0.0.1  # 3. UI (vanuit de parent-dir)
.venv/bin/python agents/watcher.py --interval 180        # 4. analyst-agent
# → http://<host>:8765/command-center/web/index.html
```

> **Eerste keer**: de schema's/migraties in de repo
> (`schema.sql`, `migrate_*.sql`, `gen_components.py`) zijn het
> referentie-model; een verse `aegis_db` krijgt de basis-tabellen via
> `schema.sql` (draai via `podman exec -i aegis_db psql -U aegis -d aegis < schema.sql`)
> en daarna de data-migraties in de volgorde: v3 → ireland2 → limerick →
> dell → global → factories → drivers → air.

### 2. Analytics dashboard

```bash
cd analytics-dashboard
podman compose up -d --build    # bouwt de 4 eigen images, start de rest
podman compose ps               # wacht tot alle services Up
make demo                       # toont alle URL's
```

Binnen ~5 min is er data in het dashboard (bootstrap + poll-cycles).

**Consoles** (demo-login overal: `Password123!`):

| Tool | Port | Login |
|---|---|---|
| **Analytics Dashboard** | 8402 | — |
| Dashboard-API (docs) | 8401 | — |
| Captor health / manual poll | 8400 | — |
| Kafka UI | 8040 | — |
| Trino UI (federated SQL) | 8543 | — |
| MinIO Console | 9001 | `minioadmin` / `Password123!` |
| JupyterLab | 8888 | `Password123!` |
| Adminer (aegis_db + lake) | 8081 | `aegis` / `aegis_dev` · `lake` / `Password123!` |
| Grafana | 3000 | `admin` / `Password123!` |
| Prometheus | 9090 | — |

### Stop / reset

```bash
cd analytics-dashboard && podman compose down        # platform, cc blijft draaien
cd analytics-dashboard && podman compose down -v     # + volumes = HISTORIE WIJKT
```

### Multi-host

Beide lagen zijn stateless-wrt-de-code: alles staat in volumes
(`aegis_db`-volume, `minio_data`, lake-catalog, watermarks). Voor een
tweede host: clone → `podman compose up -d` per laag → de eerste poll-cycle
spiegelt automatisch. Voor echte multi-host: zet `aegis_db` (replica) en
MinIO (bucket replication) centraal, draai command-center en
analytics-dashboard per regio — de architectuur is daar voor ontworpen.

---

## Repo-layout

```
command-center/
├── api.py              # FastAPI (8300) — alle operationele endpoints
├── web/index.html      # volledige frontend (Leaflet, neon-cyan theming)
├── agents/watcher.py   # dedicated analyst-agent (hermes researcher-bot)
├── compose.yaml        # aegis_db (PostGIS 16)
├── schema.sql, migrate_*.sql   # referentie-schema + data-migraties
├── specs/              # spec-kit: 001 command center, 002 analytics, 003 otit
└── .specify/memory/    # constitution (4 principes)

analytics-dashboard/
├── compose.yaml        # 13 services (kafka, minio, trino, grafana, …)
├── Dockerfile          # eigen image (fastapi/duckdb/trino/weasyprint)
├── Makefile            # make start|stop|demo|engineer|pdf
├── captor/             # read-only poller aegis_db → Kafka (watermarks)
├── pipeline/           # contract-validator → DuckLake writer
├── dashboard/          # dashboard API + 4-tab web frontend
├── contracts/          # YAML data-contracts per topic
├── agents/             # data-engineer agent (inbox → JSON → PDF)
├── trino/ init/        # Trino catalog configs + init-scripts
├── observability/      # Prometheus + Grafana provisioning
├── minio-local/        # offline build-instructies (binaries buiten repo)
└── parts/              # deelbestanden (demo-data generatie)
```

**Niet in de repo** (bewust): `.venv/` (host-dependent), `data/` (runtime
state: insights, chat-history, engineer-inbox — regenererbaar), MinIO/`mc`
binaries (zie `analytics-dashboard/minio-local/README.md`).
