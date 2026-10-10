# Spec 003 — OT/IT Convergentie: Supervisor Cockpit met Predictive & Recommendations

> Status: DRAFT v1 — spec-driven development (spec-kit), opvolger van spec 002.
> Scope-uitbreiding door opdrachtgever 2026-10-09. Doel: demo-klare use case
> voor defensie-klanten (veel context, snel doorlopend, geen lege panelen).

## 1. Probleem & context

AEGIS heeft twee "werelden" die vandaag apart van elkaar kijken:

| Wereld | Data | Vandaag |
|---|---|---|
| **IT** (logistiek) | shipments, lanes, inventory, KPI's, contracten | Command center 001 + analytics 002 |
| **OT** (machine) | telemetry, **components** (health/wear/rul_days/est_cost), voertuigstatus | alleen ruwe grafieken |

Gartner 2026 (IT/OT Convergence, D&A Predictions): de waarde zit in
**geconvergeerde context** — IT-data (wie/waar/waarde) gekruist met
OT-data (conditie/remaining useful life) zodat één operator/supervisor
beide tegelijk kan leiden. Predictive maintenance + recommendation
motiven op RUL (remaining useful life) is hét voorbeeld.

**Nieuw:** `dims.components` zit nu in de lake (spec 002-extensie):
476 regels, 25 component-types over 51 voertuigen (34 trucks, 12 schepen,
5 vliegtuigen) met `rul_days`, `health`, `wear`, `next_service`, `est_cost`.

## 2. Doel

Één dashboard dat IT + OT samen presenteert:
1. **Supervisor summary** — per shift: wat gebeurde, wat verandert,
   wat moet ik morgen doen (recommendations + predictive signalen).
2. **Predictive & recommendation engine** — RUL-basis, component-status,
   kosten-impact, onderdelen-aanbeveling **met artikelnummer + specsheets**.
3. **Per-voertuig dossier** — één klik → compleet dossier + PDF-download
   (voertuig, componenten, telemetrie-trends, geschiedenis, incidenten).
4. **Hermes data-engineer agent** — verwerkt unstructured data
   (PDF-dossiers, rapporten, e-mail) → gestructureerd in het dashboard
   (extractie → review → publish, met lineage).
5. **Snelle koppelingen** naar data management — elke kaart/knop kan
   doorlinken naar bron: contract, topic, lake-table, raw query, bron-DB.

## 3. Functies (FR)

| ID | Functie | Prioriteit |
|---|---|---|
| FR-101 | **OT/IT-verkrijking in KPI-laag**: fleet-health-score (OT) naast logistieke KPI's (IT) op één KPI-rij; cross-metrics: waarde-in-transit per voertuig met laagste component-health | P0 |
| FR-102 | **Predictive engine**: score per component = f(health, wear, rul_days, next_service, kind); rangschikking "top N vervangen" met verwachte kosten en impact op actieve shipments van dat voertuig | P0 |
| FR-103 | **Recommendation panel** (deterministisch, uitlegbaar): per aanbeveling — wat/waarom/impact/kosten + link naar onderdeel; escalatie P1 bij `rul_days < 30` op actieve route | P0 |
| FR-104 | **Onderdeel-catalogus**: artikelnummer (deterministisch gegenereerd: `PART-{KIND}-{SEQ}`), specificaties (specsheet per component-type uit `parts/specs/*.yaml`), leverancier, levertijd, prijs — getoond in component-dossier en in PDF | P0 |
| FR-105 | **Voertuig-dossier (HTML + PDF)**: endpoint `GET /api/vehicle/{id}/dossier` (HTML) + `GET /api/vehicle/{id}/dossier.pdf` (PDF via headless-Chromium/weasyprint); bevat: ID, telemetrie 24u, componenten met health-ringen, geschiedenis, open incidenten, aanbevelingen | P0 |
| FR-106 | **Supervisor-summary endpoint**: `GET /api/supervisor/summary` — shift-overzicht: incidenten (nieuw/opgelost), statuswijzigingen, RUL-events van de shift, top-5 acties, KPI-delta vs vorige shift | P0 |
| FR-107 | **Hermes data-engineer agent** (`hermes -p dataengineer`): mandaat = unstructured input (PDF/MD/tekst in `inbox/`) extracten naar JSON (type: incident-rapport, inspectie, onderhouds-log, specificatie-update) → schrijven naar `data/engineer/{id}.json` + audit-log; dashboard-laag toont de extraherde items met **review-status** (pending/verified) en lineage naar bronbestand | P1 |
| FR-108 | **Deep-link / snelle koppeling**: elke dashboard-kaart heeft een `ⓘ` die opent: bron-tabel, topic, lake-table, contract-status, laatste event, Trino-query (copyable), raw record | P0 |
| FR-109 | **Dashboard-uitbreiding (zelfde look-and-feel)**: nieuw paneel-rij "FLEET HEALTH / PREDICTIVE" (OT) naast bestaande KPI-rij (IT); voertuig-picklist → dossier-view; "SUPVISOR" paneel met summary | P0 |
| FR-110 | **Eval + demo-robustheid**: alles werkt offline/lokaal; deterministische engines (geen API-afhankelijkheid in de demo); `make demo` start alles en toont URL's; lege-states renderen "wachtend" — nooit fout-pagina's | P0 |

## 4. Niet-functioneel

- Read-only op `aegis_db` (ook nu — geen wijzigingen in command center).
- Latency: KPI/summary < 2s; PDF < 15s (headless-render); engine-draaien elke 60s (cache).
- RAM-budget: platform blijft < 14 GB (predictive engine = pure Python over
  DuckLake, geen ML-runtime; RUL is linear-voorspelling op telemetrie-trends).
- Defensie-demo: geen externe data-lekkage; alle content lokaal;
  "SIM-source" expliciet gelabeld (net als de bestaande AEGIS-simulatie).

## 5. Data-flow (uitbreiding op spec 002)

```
aegis_db (read-only) ─┬─ captor (30s poll) ─→ Kafka ─→ pipeline ─→ DuckLake
                      │     + components (nieuw)            │
                      │                                     ▼
Hermes dataengineer ──┤                        dashboard :8401/:8402
  inbox/*.pdf|md      │                        (KPI OT+IT · fleet health ·
  → LLM extractie     │                          supervisor summary ·
  → data/engineer/    │                          voertuig-dossiers HTML+PDF)
    {id}.json         ▼
              parts/specs/*.yaml (onderdeel-catalogus, artikelnummers, specsheets)
              → recommendation engine (deterministisch, 60s-cache)
```

## 6. Acceptance criteria (demo-checklist)

1. Dashboard toont KPI-rij (IT) én Fleet-Health-rij (OT) met live-dots.
2. "Top vervangen" lijst: ≥ 5 componenten, elk met RUL-score, artikelnummer,
   prijs, impact op active shipments; klik → voertuig-dossier.
3. Supervisor-summary: shift-overzicht + top-5 acties, automatisch ververst.
4. `curl localhost:8401/api/vehicle/{id}/dossier.pdf` → geldige PDF met
   componenten + artikelnummers + telemetrie-grafiek.
5. Data-engineer: PDF in `inbox/` → na cycle verschijnt geëxtract item in
   dashboard met review-status; lineage naar bronbestand.
6. Elke KPI-kaart: `ⓘ` → context met bron, contract, topic, Trino-query.
7. `podman compose down && podman compose up -d` → demo loopt in < 5 min
   zonder handmatige stappen.

## 7. Risico's / openstaand

- **PDF-rendering**: weasyprint (Python, licht) vs headless-chromium (zwaar).
  Besluit: weasyprint v1 (HTML→PDF, geen browser in container nodig);
  chromium als fallback als grafieken nodig zijn in PDF (Canvas→PNG via
  server-side matplotlib).
- **Artikelnummers**: geen bestaande bestanden in DB → deterministische
  gegenereerde catalogus (`parts/specs/`) met realistische specs
  (CFM56-engines, hydrauliek-pompsets, remschijven, ...) — gelabeld als
  demo-catalogus.
- **Dataengineer-profiel**: nieuw Hermes-profiel `dataengineer` (zelfde
  patroon als `researcher` in agents/watcher.py); prompt = extractie-mandate,
  output = strikt JSON met bronreferentie.
- Trino-DuckLake blijft via Parquet (spec 002 research) — geen verandering.

## 8. Tasks (outline, uitgewerkt in tasks.md)

- T1xx: data-engineer: FR-101..103, 106 (API + engine)
- T2xx: onderdeel-catalogus FR-104 + dossier FR-105 (HTML/PDF)
- T3xx: dashboard-pano FR-109 + deep-link FR-108
- T4xx: hermes-dataengineer agent FR-107 (inbox, cycle, review-laag)
- T5xx: demo-robustheid FR-110 + evaluatie + documentatie
