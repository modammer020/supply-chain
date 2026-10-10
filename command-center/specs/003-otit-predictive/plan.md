# Spec 003 — Plan (technische context)

Constitution-check (spec 002) blijft gelden: read-only op aegis_db, één
bronwaarheid, contracts op elk datapunt, lineage per KPI. Uitbreiding:

| Domäne | Keuze | Waarom |
|---|---|---|
| Predictive | deterministische scoringsfunctie over `dims.components` (health/wear/rul_days/next_service) | uitlegbaar, reproduceerbaar, geen ML-runtime in demo; RUL-voorspelling blijft in horizon (telemetrie-trends) |
| Onderdelen | `parts/specs.yaml` demo-catalogus, artikelnummers `PART-{KIND}-{SEQ}` | DB heeft geen bestaande bestanden; gelabeld als demo |
| PDF | weasyprint (HTML→PDF) + matplotlib voor telemetrie-grafiek | licht, geen browser-container; Chromium als fallback bij complexe layout |
| OT/IT-laag | KPI-rij IT (logistiek) + KPI-rij OT (fleet-health) + cross-metrics in recommendation impact | één interface voor IT én OT (doel) |
| Data-engineer | hermes-profiel `dataengineer` (idk watcher.py-patroon) + host-side agent + review-API | unstructured → structured met lineage + menselijke review-laag |
| Snelle koppelingen | context-paneel per kaart + tabel "sneldraaiers" (tools+URL's) + copyable Trino-query | data-management-toegang in één klik |

## Architectuur (delta t.o.v. spec 002)

```
dashboard :8401/:8402
├── api_core     (spec 002: KPI/trends/incidents/lineage/quality)
├── engine       (nieuw: predictive + recommendations, 60s-cache)
├── dossier      (nieuw: HTML+PDF per voertuig)
├── engineer_api (nieuw: review-laag op data/engineer/*.json)
└── web/index.html (4 tabs: OPERATIONS · FLEET HEALTH · SUPERVISOR · DATA-ENGINEER)

host
└── agents/data_engineer.py (120s) → hermes -p dataengineer
    └── data/engineer/{inbox/*.md|pdf, eng-*.json, audit.jsonl}
        └── (bind-mount → container /app/data/engineer)
```

## Nieuwe endpoints

| Endpoint | Omschrijving |
|---|---|
| `GET /api/fleet-health?top=N` | OT: fleet-health-score, top-N te vervangen, counts |
| `GET /api/recommendations` | deterministische aanbevelingen (P1/P2/P3 + waarom/impact/kosten) |
| `GET /api/supervisor/summary?shift=24` | shift-samenvatting (IT-KPI's + OT + incidenten + top-5 acties) |
| `GET /api/vehicle/{id}/dossier` | HTML-dossier |
| `GET /api/vehicle/{id}/dossier.pdf` | PDF-dossier (weasyprint) |
| `GET /api/engineer/items?status=` | geëxtracte items (review-status) |
| `GET /api/engineer/items/{id}` | item + lineage + quotes |
| `POST /api/engineer/items/{id}/review?status=` | approve/reject/pending (audit-log) |

## RAM-budget
Engine/dossier draaien in de dashboard-container (DuckDB-embedded, geen aparte
processen). Weasyprint piekt ±300 MB per PDF. Totaal platform blijft < 14 GB.
