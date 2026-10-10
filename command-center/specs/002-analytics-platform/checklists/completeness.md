# Volledigheidscheck: AEGIS Analytics Platform (002)

**Purpose**: Requirements-quality review — is de spec compleet en de plan consistent met de
afspraken uit de brainstorm? **Feature**: `specs/002-analytics-platform/spec.md`
**Created**: 2026-10-09 · **Review**: user + agent (co-creatie)

## User-afspraken (brainstorm 2026-10-09) → dekking

| # | Afspraak | Spec | Plan | Status |
|---|---|---|---|---|
| 1 | Apart project, eigen podman-compose (niet in AEGIS) | Doel + FR-010 | `aegis-analytics/` root, eigen compose.yaml + .venv | ✅ |
| 2 | Stack: Kafka, Spark, DuckDB, Trino + "enz." | FR-004/005/006/009 | 8 services: kafka, minio, spark, trino, captor, dashboard, prometheus, grafana | ✅ |
| 3 | "Enz." = Grafana/Prometheus én MinIO (beide) | FR-005 + FR-009 | MinIO (DuckLake) + Prometheus/Grafana (observability) | ✅ |
| 4 | PostGIS → Postgres? Option A: ongewijzigd laten | Clarifications + Niet-doelen | Constitution-check II; bron read-only | ✅ |
| 5 | Vraag 1 = A: poller nu, Debezium later | FR-001 + FR-002 | `captor/poller.py`, Debezium in Out-of-Scope (horizon) | ✅ |
| 6 | Vraag 2 = DuckLake | FR-005 | DuckLake in MinIO; Parquet-fallback als Trino-connector niet rijp (research v1) | ✅ |
| 7 | Vraag 3 = B: eigen frontend | FR-007/008/011 | `dashboard/index.html` (AEGIS theme, single-file) | ✅ |
| 8 | Captor 30 sec + handmatige optie | FR-001/FR-002 | 30s-interval + `POST /manual/poll` (409 bij clash) | ✅ |
| 9 | Dashboard op basis van events + bestaande data | US1/US3 + FR-008 | facts/dims splitsing; KPI-rij + trends + telemetrie + incidenten | ✅ |
| 10 | Use case: AI-Ready Data / context layer zichtbaar maken | FR-007/009 + Success criteria | semantiek/freshness/provenance per kaart; contract-enforcement in pipeline | ✅ |
| 11 | Tool-access overal (Grafana, Jupyter, Trino UI, MinIO, Kafka UI, Adminer) | FR-012 + success criterion | access-layer tabel in plan.md; `quickstart.md`; `architecture.html` | ✅ |
| — | **Spec-kit flow compleet**: Spec → Plan → Research → Data-model → Contracts → Quickstart → Tasks | Constitution III | `tasks.md` (53 tasks, per user story, VER-checks, done-definitie) | ✅ |

## Spec-kwaliteit (requirements)

- [x] CHK001 Elke user story onafhankelijk testbaar (US1: topics kloppen met DB; US2:
      quarantaine + federated query; US3: dashboard-waarden = DB + badges)
- [x] CHK002 Alle FR's meetbaar/testbaar (geen "systeem moet robuust zijn"-vage items)
- [x] CHK003 Edge cases gedekt: duplicaten, schema-uitbreiding, lag, herstart,
      concurrente handmatige trigger, MinIO-down, partial bootstrap
- [x] CHK004 Success criteria kwantitatief (5 min tot data, <10 s Trino, <10 GB RAM,
      10 min terugtraceerbaarheid)
- [x] CHK005 Niet-doelen expliciet (geen wijziging AEGIS, geen CDC, geen cluster-modi)
- [x] CHK006 Ambiguïteit geadresseerd via Clarifications-sectie (PostGIS, CDC, DuckLake,
      frontend, interval)

## Plan-kwaliteit

- [x] CHK007 Constitution-check uitgevoerd: 7 principes, alle PASS (zie plan.md)
- [x] CHK008 Projectstructuur concreet (geen Option-labels; paden + bestanden)
- [x] CHK009 Interfaces gedefinieerd (captor-API, dashboard-API, topics) —
      details uit te werken in `contracts/` (fase 1)
- [x] CHK010 Risico's met mitigatie (DuckLake-maturiteit, Spark local-mode,
      bootstrap-volumedruk, concurrentie)
- [x] CHK011 Performance goals + constraints geformuleerd en haalbaar (8C/30GB host)

## Open items (bewust overgelaten aan fase 0/1 — niet onvolledig, maar bepalingsvragen)

- Trino-DuckLake-connector-maturiteit (research v1; fallback paraat)
- Telemetrie-retentie in de lake (30/90/onbeperkt)
- Exacte versies (Trino, Spark, Kafka image, DuckDB)
- Bootstrap-window voor telemetrie (volledige historie vs. laatste 30 dagen)

## Conclusie

**Volledigheid: compleet voor fase 0→1 start.** Alle 10 user-afspraken uit de
brainstorm zijn 1-op-1 gedekt; elke FR hangt aan een user story; elke user story
heeft een independent test; constitution PASS. De 4 open items zijn *bepalingsvragen*
die onderzoek (research.md) beantwoordt, geen ontbrekende requirements.

**Doel in één zin (herbevestigd):** bouwen van een losstaand, read-only analytics
platform (Kafka → Spark+contracts → DuckLake/MinIO → DuckDB+Trino → eigen
dashboard) dat de bestaande AEGIS-events spiegel en analyseert, zodat elk
datapunt semantisch bevestigd, versheidsgecertificeerd en terugtraceerbaar is —
de Gartner "AI-Ready Data / context layer" use case, draaiend in plaats van op papier.
