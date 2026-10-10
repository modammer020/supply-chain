# Contract: Captor API

**Service**: `captor` (eigen container, FastAPI, port 8400)
**Bron**: `aegis_db` (PostGIS) — uitsluitend **read-only** (read-only-rol,
geen writes, geen triggers).

## Endpoints

### `GET /health`
Status per tabel + cycle-info. 200 OK (ook bij bron-fout; status in body).

```json
{
  "status": "ok" | "degraded" | "error",
  "source_reachable": true,
  "last_cycle_at": "2026-10-09T00:30:00Z",
  "cycle_duration_ms": 850,
  "interval_s": 30,
  "tables": {
    "telemetry":        {"state": "streaming", "watermark": "2026-10-09T00:30:00Z", "rows_last_cycle": 96},
    "shipment_events":  {"state": "streaming", "watermark": "...", "rows_last_cycle": 0},
    "shipments":        {"state": "streaming", "watermark": "...", "rows_last_cycle": 2},
    "vehicles":         {"state": "snapshot",  "rows_last_cycle": 51},
    "lanes":            {"state": "snapshot",  "rows_last_cycle": 38},
    "locations":        {"state": "snapshot",  "rows_last_cycle": 62},
    "inventory":        {"state": "snapshot",  "rows_last_cycle": 14},
    "drivers":          {"state": "snapshot",  "rows_last_cycle": 51},
    "bootstrap":        {"state": "done" | "in_progress" | "pending", "completed_tables": 8, "total_tables": 9}
  },
  "kafka": {"reachable": true, "topics_created": true}
}
```

`state` ∈ `bootstrap` | `streaming` | `snapshot` | `error` (met
`error`-bericht bij falen; Constitution I: zichtbaar, geen silent-fail).

### `POST /manual/poll`
Forceert één poll-cycle nu (US1).

| Status | Body |
|---|---|
| 200 | `{"cycle_id": "c-...", "triggered": "manual", "started_at": "..."}` |
| 409 | `{"error": "cycle_active", "active_cycle_id": "c-...", "started_at": "..."}` (cycle al actief — FR-002/Edge) |
| 503 | `{"error": "source_unreachable"}` (bron niet bereikbaar; bronstatus blijft zichtbaar in /health) |

Manual-cycles tellen mee in `captor_cycles_total{trigger="manual"}`.

## Prometheus-metriken (captor)

- `captor_cycles_total{trigger="interval"|"manual", table="..."}`
- `captor_rows_captured_total{table="..."}`
- `captor_errors_total{table="...", reason="..."}`
- `captor_last_cycle_timestamp_s` (per table, gauge)
- `captor_bootstrap_pending` (0/1)

## Gedrag (niet-negotationeel)

- Read-only: captor opent `aegis_db` alleen met `SELECT`; transacties in
  `REPEATABLE READ` (geen locks, geen impact op sim-engine).
- Watermarks persistent op volume `/captor-state` (herstart-resistent).
- Idempotentie: overlap-vraag (±1 record) + `captured_at` → Spark-dedup
  (geen duplicaten in facts; Edge "herstart").
- Cron-achtige scheduling: asyncio-timer op 30 s, jitter ≤ 2 s.
