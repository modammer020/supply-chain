# Spec 003 — Quickstart (demo)

## Start (alles)

```bash
cd /home/demouser/aegis-analytics
podman compose up -d --build     # eerste keer: bouwt image + start 12 services
```

Binnen ~5 min:
- bootstrap (captor) + poll-cycles vullen de lake
- dashboard: http://localhost:8402

## Login (default `Password123!` overal)

| Tool | URL | Login |
|---|---|---|
| **Dashboard (4 tabs)** | http://localhost:8402 | — |
| API | http://localhost:8401/docs | — |
| Kafka UI | http://localhost:8040 | geen |
| MinIO | http://localhost:9001 | minioadmin / Password123! |
| Trino | http://localhost:8543 | geen |
| Grafana | http://localhost:3000 | admin / Password123! |
| Jupyter | http://localhost:8888 | Password123! |
| Adminer | http://localhost:8081 | aegis/aegis_dev · lake/Password123! |

## Demo-loop (verdedigingsklanten)

1. **OPERATIONS** — IT-KPI-rij + OT-fleet-rij (OT/IT-convergentie), trends,
   incidenten. Klik op KPI → context-paneel (bron/semantiek/contract/leeftijd/
   snelle koppeling).
2. **FLEET HEALTH** — predictive engine: top-vervangen-lijst met score,
   artikelnummer, kosten, impact op actieve zendingen. Klik rij → voertuig-dossier;
   klik "specs" → specsheets. "PDF" → complete PDF per voertuig.
3. **SUPERVISOR** — shift-samenvatting + top-5 acties + sneldraaiers-tabel
   (data-management-koppelingen).
4. **DATA-ENGINEER** — geëxtracte items uit inbox (hermes agent), lineage +
   review (approve/reject).

## Data-engineer voeden

```bash
# rapport in inbox gooien (md/pdf/txt/json)
cp /pad/naar/inspectierapport.pdf /home/demouser/aegis-analytics/data/engineer/inbox/
# agent één keer draaien (of in de loop: elke 120s)
cd /home/demouser/aegis-analytics
.venv/bin/python agents/data_engineer.py --once
# resultaat bekijken
curl -s localhost:8401/api/engineer/items | python3 -m json.tool | head -30
```

## Voertuig-PDF direct

```bash
curl -s localhost:8401/api/vehicle/TRK-104/dossier.pdf -o dossier.pdf
open dossier.pdf   # of xdg-open
```

## Stop / reset

```bash
podman compose down            # platform stopt, command center blijft draaien
podman compose down -v         # + volumes (lake + kafka) — historie weg
```

## Evaluatie (na demo)

- Acceptance criteria in spec.md §6 afvinken (7 punten).
- Metrieken: `curl -s localhost:8401/api/status` (ducklake/trino up/down),
  `curl -s localhost:8410/status` (pipeline), Grafana dashboard.
