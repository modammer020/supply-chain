-- ═══ AEGIS v3 migration ═══
-- shipment lifecycle event history
CREATE TABLE IF NOT EXISTS shipment_events (
  id          text PRIMARY KEY DEFAULT 'EV-' || substring(gen_random_uuid()::text,1,8),
  shipment_id text NOT NULL REFERENCES shipments(id),
  ts          timestamptz NOT NULL DEFAULT now(),
  type        text NOT NULL,   -- dep|chk|arr|inc|reroute|sla
  note        text
);
CREATE INDEX shipment_events_idx ON shipment_events (shipment_id, ts);

-- key-value cache (weather, traffic, feed status)
CREATE TABLE IF NOT EXISTS kv (
  key        text PRIMARY KEY,
  value      jsonb NOT NULL,
  fetched_at timestamptz NOT NULL DEFAULT now(),
  ttl_until  timestamptz
);

-- progress column on shipments (0..1 along route, sim writes it)
ALTER TABLE shipments ADD COLUMN IF NOT EXISTS progress double precision DEFAULT 0.5;
ALTER TABLE shipments ADD COLUMN IF NOT EXISTS dir integer DEFAULT 1;

-- seed event history for all shipments
INSERT INTO shipment_events (shipment_id, ts, type, note)
SELECT s.id, now() - interval '6 hours', 'dep', 'Departed ' || o.name ||
       CASE WHEN s.status != 'in_transit' THEN ' (status: ' || s.status || ')' ELSE '' END
  FROM shipments s JOIN lanes l ON l.id=s.lane_id JOIN locations o ON o.id=l.origin;
INSERT INTO shipment_events (shipment_id, ts, type, note)
SELECT s.id, now() - interval '3 hours', 'chk', 'Mid-route checkpoint cleared'
  FROM shipments s WHERE s.status='in_transit';
INSERT INTO shipment_events (shipment_id, ts, type, note)
SELECT s.id, now() - interval '1 hour', 'sla', 'SLA re-forecast: ETA within window'
  FROM shipments s WHERE s.status='in_transit' AND s.id IN ('SHP-9003','SHP-9012','SHP-9019');
