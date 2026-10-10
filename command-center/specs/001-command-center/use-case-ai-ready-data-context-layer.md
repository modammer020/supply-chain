# Use Case: AEGIS Context Layer
## AI-Ready Data + Semantische Context Layer voor de Supply Chain Command Center

Status: **Ontwerp / co-creatie** · Domein: Supply chain & logistiek · Gartner-anker: Hype Cycle 2026, D&A Predictions 2026

---

## 1. Probleemstelling (de pijn)

AEGIS v3 heeft een draaiende analysering: een `watcher`-agent pollt de supply-chain API,
laadt een LLM (researcher-bot) die insights genereert naar `insights.jsonl`, en toont die
in het ANALYST-panel. De LLM "weet" echter niet:

- **Wat** een veld betekend in business-termen (`gevaarmelding` = welke severity-schaal?
  `leveranciersstatus` = welke waarden? `sla_breach` = met welk tijdsrefervol?)
- **Hoe vers** de data is (freshness) — een insight van een agent die op 2 dagen oude data
  slaat, is "vertrouwelijk, fout"
- **Vanaf waar** een waarde komt (lineage/provenance) — kan een conclusie teruggerekend
  worden naar de bron?

Gartner: precies dit is de #1 reden dat AI-uitkomsten falen. 57% van organisaties is
niet AI-ready; 82% van de AI-pipeline-incidenten komt door upstream data-veranderingen
die de consument (hier: de LLM) niet van op de hoogte was. De context die nu ontbreekt,
is niet "nice-to-have" maar het **fundament** waar agentic AI op draait.

**Kernstelling:** De context layer — semantics + freshness + provenance + access — is de
kritieke infrastructuur die maakt dat de AEGIS-analist betrouwbare, traceerbare,
governable insights levert op inference-snelheid.

---

## 2. Gartner-justificatie (waarom nu)

| Signaal (bron) | Cijfer | Relevantie voor AEGIS |
|---|---|---|
| AI-Ready Data — Peak of Inflated Expectations (Hype Cycle 2025/26) | 57% data niet AI-ready | Het fundament missen is de primaire faalmodus |
| Context layer = kritieke infrastructuur (D&A 2026) | — | Semantics levert tot 80% accuracy-winst, 60% kostenbesparing |
| Machine-verifieerbare data contracts (D&A 2026) | 2030: 50% orgs | Contracts die nu ontbreken → fluente, foutieve output |
| Data lineage als trust layer | 70% snellere new data assets | Elke AI-uitkomst terugrekenen naar bron |
| Zero-trust data governance | 2028: 50% orgs | Verantwoord gedrag op ontrackte AI-generated data |

---

## 3. Gewenst eindresultaat (de belofte)

> Elke supply-chain insight die uit AEGIS komt, is **semantisch bevestigd**,
> **versheidsgecertificeerd**, **terugtraceerbaar naar de bron**, en **beperkt
> in scope** via inference-time access control. De mens en de LLM zien dezelfde,
> geverifieerde definities.

Concreet:
1. **Eenheid van betekenis** — één semantische definitie per business-term,
   machine-leesbaar, gekoppeld aan de fysieke kolommen in `aegis_db`.
2. **Freshness-SLA per data product** — agenten weten vóór inferentie hoe vers een
   dataset is; te oude data wordt geblokkeerd of geflagd, niet stil gebruikt.
3. **Provenance/lineage** — elke insight kan in <10 min teruggetraceerd worden naar
   bron-systeem, transformatie en gebruikte query.
4. **Inference-time access control** — de agent-identiteit heeft per-kolom
   rechten; geen inheritantie van dashboard-permissies.

---

## 4. Scope — wat "AI-Ready Data + context layer" betekent in AEGIS

De vier componenten (per Gartner/Atlan AI-ready data infrastructure):

### 4.1 Semantische metadata layer
- Machine-leesbare definities van business-entiteiten en termen.
- Gekoppeld aan PostGIS-kolommen (o.a. coördinaten/geometry, leveranciers, gevaarmeldingen, SLA).
- Business glossary → fysieke asset, via API beschikbaar op inference-tijd.
- Ontologie/knowledge graph voor relaties (leverancier → product → route → risico).

### 4.2 Data contracts (machine-verifieerbaar)
Per data product / bron-tabel:
- **Schema** — kolommen, types, nullability
- **Kwaliteit** — volledigheid, validiteit, range, verdeling
- **Semantiek** — business-betekenis per veld, gelinked aan glossary-entry
- **Lineage** — transformatie-pad van bron tot agent-facing view
- **Freshness-SLA** — expliciete versheidsgarantie
- **Access** — per-agent authorisatie bij context-afgifte

Enforcement: niet alleen "is de data aangekomen" (rowcount/null) maar ook
**semantische checks** — value-distribution, type-coercion, enum/categorie-set.
Een contract-violatie blokkeert of flagnet context vóórdat de LLM het ziet.

### 4.3 Lineage & provenance (trust layer)
- End-to-end, kolom-level lineage.
- Elke insight in `insights.jsonl` krijgt metadata: welke bron-tabellen, welke query,
  welke semantische definities, welk tijdstip.
- Impact- en root-cause-analyse: wat breekt er downstream bij een schema-verandering?

### 4.4 Inference-time access control
- AI-agent-identiteit expliciet gemodelleerd (niet geërfd van BI-permissies).
- Kolom- en attribut-niveau policies, geëngineerd wanneer de agent queryt.

---

## 5. Concrete architectuur voor AEGIS v3

Bestaand: `aegis_db` (PostGIS 5433) · `api.py` (FastAPI 8300) · `web/index.html` ·
`agents/watcher.py` (pollt API, 3 min) → `data/insights.jsonl` → `/api/insights`.

Proposities (te bevestigen met jou):

```
┌───────────────────────────────────────────────────────────────┐
│  aegis_db (PostGIS)                                            │
│   - Bron-tabellen (supply chain, gevaar, leveranciers, routes)  │
│   - NIEUW: semantic_layer (glossary, definities, mappings)     │
│   - NIEUW: data_contracts (machine-verifieerbaar, per tabel)   │
│   - NIEUW: lineage / provenance (transformaties + insights)    │
└───────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┴────────────────┐
              │  api.py (FastAPI 8300)          │
              │  /api/data (existing)           │
              │  /api/semantic  (NIEUW)         │
              │  /api/contracts (NIEUW)         │
              │  /api/lineage   (NIEUW)         │
              └───────────────┬────────────────┘
                              │
        ┌─────────────────────┴─────────────────────┐
        │ agents/watcher.py                          │
        │  1. Haalt context (semantics+freshness)    │
        │  2. Valideert data contracts vóór LLM      │
        │  3. Enforce access control (agent-ident)   │
        │  4. Genereert insight + provenance-metadata│
        │  5. Schrijft insights.jsonl (met lineage)  │
        └─────────────────────┬─────────────────────┘
                              │
                    /api/insights → ANALYST-panel
                    (elke insight toont:
                     semantiek + versheid + bron-link)
```

Nieuwe API-endpoints (te bespreken):
- `GET /api/semantic?term=...` → machine-leesbare definitie + gekoppelde kolommen
- `GET /api/contracts?table=...` → contract + status (groen/geel/rood) + laatste checks
- `GET /api/lineage?asset=...` → upstream/downstream + bron-attributie
- (interne) contract-enforce-lijst die de watcher vóór elke LLM-call afvult

---

## 6. Use-case-scenario (end-to-end)

**Situatie:** Een nieuw leveranciersrisico verschijnt in de bron. De watcher draait.

1. Watcher pollt `aegis_db` via de API.
2. **Vóór** de LLM wordt aangeroepen: de watcher haalt de **semantische context**
   op (wat betekent `gevaarmelding`, wat is de severity-schaal) en de
   **freshness-status** per gebruikte tabel.
3. **Contract-check** draait: zijn de gebruikte kolommen binnen hun
   verdeling/enum/null-grenzen? Staat de table vers genoeg?
   - Groen → doorgaan.
   - Rood → insight wordt **geflagd/geblokkeerd** met reden; de LLM krijgt de
     gewijzigde context (niet de ruwe, gebroken data).
4. De researcher-bot genereert een insight op basis van de **governed context**
   (semantisch bevestigde termen + verse data), niet op ruwe kolommen.
5. De insight wordt geschreven naar `insights.jsonl` mét **provenance-metadata**:
   gebruikte tabellen, query, semantische definities, tijdstip, contract-status.
6. ANALYST-panel toont de insight met een klik naar de bron + semantiek.
   Een mens kan de conclusie in <10 min teruggerekenen naar de bron.

**Antiem-patroon (zonder context layer):** de LLM leest de kolommen, interpreteert
`gevaarmelding` op een andere schaal dan de business, slaat op 2 dagen oude data, en
levert een fluente maar foutieve "hoge risk-alert" — zonder dat iemand het ziet.

---

## 7. Succesmeting (KPI's, Gartner-afgestemd)

| KPI | Doel |
|---|---|
| Semantiek-coverage | 100% van de kolommen die agenten queryt, hebben een machine-leesbare definitie |
| Lineage-coverage | >80% van de tabellen die agenten gebruiken, volledig gelined |
| Contract-enforcement | 100% van agent-consumed pipelines heeft groen/geel/rood status vóór LLM |
| Freshness-aware | 100% insights tonen versheid; te-oude data wordt niet stil gebruikt |
| Provenance-latency | Elke insight teruggerekend naar bron in <10 min |
| Accuracy (before/after) | Minder onjuiste insights; meetbaar via sampling door mens |
| Incident-MTTR | Minder "vertrouwelijk, fout" alerts → snellere root-cause via lineage |

---

## 8. Roadmap / fasering (strikte scope, kleine stappen)

**Fase 0 — Inventarisatie (mijlpaal: "wat hebben we")**
- Inventariseer bron-tabellen in `aegis_db`, kolommen, types.
- Identificeer welke tabellen de watcher/LLM daadwerkelijk consumen.
- Inventariseer bestaande definities (tribal knowledge) vs. gemankeerd.

**Fase 1 — Semantische metadata layer (MVP)**
- Bouw `semantic_layer`-tabel + `GET /api/semantic`.
- Definieer de top-N business-terms die de analyst daadwerkelijk gebruikt.
- Koppel aan fysieke kolommen.

**Fase 2 — Data contracts (MVP)**
- Bouw `data_contracts`-tabel + `GET /api/contracts`.
- Contracten voor de 2–3 hoogste-risico, agent-consumed pipelines (eerst!).
- Semantische checks (verdeling, enum, null) + freshness-SLA.
- Watcher enforce vóór LLM-call (groen/geel/rood).

**Fase 3 — Lineage & provenance**
- Bouw `lineage`-tabel + `GET /api/lineage`.
- Provenance-metadata in `insights.jsonl`.
- Bron-link in ANALYST-panel.

**Fase 4 — Inference-time access control**
- Agent-identiteit + kolom-level policies.
- Per-agent authorisatie bij context-afgifte.

**Fase 5 — Agentic DataOps (horizon, Gartner 2030)**
- Agents die contracten zelf interpreteren + onderhandelen.
- Autonomous governance; machine-verifieerbare enforcement.

---

## 9. Risico's & mitigatie

- **Scope-creep** (alles tegelijk) → strikte fasering; fase 1 is de kleinste bruikbare stap.
- **Contracten in documentatie, niet in enforcement** (Gartner: 32% heeft policy, geen enforcement) →
  contracts **in de pipeline**, niet in een wiki.
- **Semantic break die traditionele monitoring mist** (Nexla-incident: 9 dagen green, categorieën verdwenen) →
  semantische checks (verdeling/enum), niet alleen rowcount.
- **Stale lineage** (handmatig verouderd) → geautomatiseerde capture, niet handmatig.
- **Toch op ruwe data slagen** → watcher mag de LLM niet voeden zonder vóórhand context+contract-check.

---

## 10. Uitvoering — gekoppeld aan spec 002

De use case wordt concreet uitgevoerd in **spec 002 (aegis-analytics-platform)**
(`specs/002-analytics-platform/`): een apart podman-compose project dat de
AEGIS-data read-only spiegelt (captor-poller 30s + handmatige trigger) naar
Kafka → Spark (data-contract-enforcement) → DuckLake in MinIO → DuckDB + Trino
(federated) → eigen dashboard. Per Gartner-kern: de context layer
(semantiek + freshness + provenance + contract-enforcement) wordt hier *in de
pipeline* gedraaid, niet op papier. Zie `specs/002-analytics-platform/spec.md`.

## 11. Open vragen (om samen te beantwoorden)

1. **Welke tabellen/kolommen** consument de watcher/LLM nu daadwerkelijk? (nodig voor scope fase 1)
2. **Welke business-terms** zijn kritiek voor de analyst? (top-N voor de semantische layer)
3. **Freshness-SLA**: wat is "vers genoeg" per bron in jouw supply chain (minuten? uren?)
4. **Contracten voor welke pipelines eerst** (de 2–3 hoogste risico)?
5. **Enforcement-punt**: blokkeren we een insight hard (rood = geen LLM-call), of
   flagen we de LLM en laat die een "gebaseerd op gedegegrade data" label geven?
6. **Access control nu of later**: is er nu een echte agent-identiteit, of
   is één service-account genoeg voor fase 0–3?
7. **Glossary-kop**: wie eigenaar van de semantische definities (data owner + analyst, joint)?
