-- AEGIS v3.x — Dell manufacturing sites (factories)
-- Idempotent: ON CONFLICT DO NOTHING
ALTER TABLE locations DROP CONSTRAINT IF EXISTS locations_kind_check;
ALTER TABLE locations ADD CONSTRAINT locations_kind_check
  CHECK (kind IN ('dc','port','city','airport','terminal','hq','csc','factory'));

INSERT INTO locations (id,name,kind,lat,lng,geom,capacity,region,meta) VALUES
 ('d-fac-wki','Dell Factory — Waukesha, WI','factory',43.0126,-88.5670,ST_SetSRID(ST_MakePoint(-88.5670,43.0126),4326),5200,'NA',
  '11000 Dell Parkway, Waukesha WI · Flash memory, SSD & server-drive manufacturing. One of the largest dedicated SSD plants in the US.'),
 ('d-fac-ric','Dell Factory — Richardson, TX','factory',32.9996,-96.7008,ST_SetSRID(ST_MakePoint(-96.7008,32.9996),4326),4800,'NA',
  '1 Dell Way, Richardson TX · Server & Precision workstation assembly (PowerEdge, PowerStore). Final test, imaging and global logistics.'),
 ('d-fac-chd','Dell Factory — Chengdu, CN','factory',30.5728,104.0668,ST_SetSRID(ST_MakePoint(104.0668,30.5728),4326),6100,'APAC',
  'Dell Chengdu Campus · Server and storage manufacturing for the APAC region. High-volume assembly with local supply chain.'),
 ('d-fac-png','Dell Factory — Penang, MY','factory',5.3349,100.2708,ST_SetSRID(ST_MakePoint(100.2708,5.3349),4326),5600,'APAC',
  'Bayan Lepas Free Industrial Zone, Penang · Long-running manufacturing hub: servers, networking hardware and electronics assembly since the 1990s.'),
 ('d-fac-pun','Dell Factory — Pune, IN','factory',18.5204,73.8567,ST_SetSRID(ST_MakePoint(73.8567,18.5204),4326),4400,'APAC',
  'Dell Pune Campus · PC and server manufacturing serving South Asia; one of the largest Dell manufacturing operations in India.')
ON CONFLICT (id) DO NOTHING;

SELECT count(*) AS factories FROM locations WHERE kind='factory';
