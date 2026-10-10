-- Limerick, Ireland — Dell EMEA historic base + city node (idempotent)
INSERT INTO locations (id,name,kind,lat,lng,geom,capacity,region,meta) VALUES
 ('c-lim','Limerick','city',52.6541,-8.7228,ST_SetSRID(ST_MakePoint(-8.7228,52.6541),4326),500,'EMEA',
  'City of Limerick, Munster, Ireland. Shannon River port. Dell historic EMEA manufacturing & logistics base.'),
 ('d-csc-lim','Dell EMEA Campus — Limerick','csc',52.6541,-8.7228,ST_SetSRID(ST_MakePoint(-8.7228,52.6541),4326),2600,'EMEA',
  'Dell Limerick, Ireland · historic EMEA manufacturing & supply-chain campus (Dell Limerick Ltd, est. 2003). Key node for EMEA logistics.')
ON CONFLICT (id) DO NOTHING;
SELECT count(*) FROM locations WHERE id IN ('c-lim','d-csc-lim');
