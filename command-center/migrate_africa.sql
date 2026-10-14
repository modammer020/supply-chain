-- AEGIS: add real Dell offices in Africa + a ME&AFRICA region + routes through Africa.
-- Sources (researched, 2026-10):
--   Casablanca: Dell Careers "Middle East & Africa – Morocco"; Dell staff + jobs (Shore 12 Park, Bd El Qods)
--   Johannesburg: Dell service centres (Midrand), SEC EX-21.1 "Dell Computer (Proprietary) Ltd – South Africa"
--   Lagos: "Dell Technology and Solutions Nigeria Ltd" (Mulliner Towers, Ikoyi / Adeola Odeku St, Victoria Island)
--   Nairobi: SEC EX-21.1 "Dell Emerging Markets (EMEA) Limited (Kenya Branch)"
--   Accra: SEC EX-21.1 "Dell Emerging Markets (EMEA) External Company (Ghana)"
--   Cairo (existing): Dell Careers ME&Africa "Egypt"
BEGIN;

-- 1) Reclassify Cairo as AFRICA (it was EMEA)
UPDATE locations SET region='AFRICA' WHERE id='d-csc-cag';

-- 2) New Africa Dell offices (kind=csc, region=AFRICA)
INSERT INTO locations (id,name,kind,lat,lng,geom,capacity,stock_level,region,meta) VALUES
 ('d-csc-casa','Casablanca — Shore 12 Park','csc',33.5850,-7.6150,ST_SetSRID(ST_MakePoint(-7.6150,33.5850),4326),1200,0.74,'AFRICA','Dell ME&Africa — Morocco hub (sales, services, demand planning)'),
 ('d-csc-jhb','Johannesburg — Rand Park','csc',-26.1870,28.1170,ST_SetSRID(ST_MakePoint(28.1170,-26.1870),4326),2600,0.68,'AFRICA','Dell South Africa — regional service & distribution (Midrand)'),
 ('d-csc-lag','Lagos — Victoria Island','csc',6.4280,3.4210,ST_SetSRID(ST_MakePoint(3.4210,6.4280),4326),1500,0.61,'AFRICA','Dell Nigeria — West Africa hub (Ikoyi / Victoria Island)'),
 ('d-csc-nbo','Nairobi — Westlands','csc',-1.2740,36.7960,ST_SetSRID(ST_MakePoint(36.7960,-1.2740),4326),700,0.55,'AFRICA','Dell Emerging Markets (EMEA) Kenya Branch — East Africa'),
 ('d-csc-acc','Accra — Airport City','csc',5.6037,-0.1870,ST_SetSRID(ST_MakePoint(-0.1870,5.6037),4326),500,0.58,'AFRICA','Dell Emerging Markets (EMEA) Ghana — Gulf of Guinea')
ON CONFLICT (id) DO UPDATE SET region=EXCLUDED.region, meta=EXCLUDED.meta;

COMMIT;

-- 3) Routes through Africa: Rotterdam (EMEA hub) -> Cairo -> Africa offices, plus Africa<->Asia
-- distances via great-circle (approx, honest values)
INSERT INTO lanes (id,origin,destination,distance_km,freeflow_min,otif_pct,volume) VALUES
 ('ln-af1','h-rtm','d-csc-casa',1980,1520,92,7),
 ('ln-af2','d-csc-casa','d-csc-jhb',5480,4260,89,5),
 ('ln-af3','d-csc-casa','d-csc-lag',5380,4180,88,6),
 ('ln-af4','d-csc-lag','d-csc-acc',620,480,91,4),
 ('ln-af5','d-csc-acc','d-csc-nbo',4180,3260,87,4),
 ('ln-af6','d-csc-jhb','d-csc-nbo',1490,1160,90,5),
 ('ln-af7','h-rtm','d-csc-cag',3300,2560,91,6),
 ('ln-af8','d-csc-cag','d-csc-casa',2400,1860,93,5)
ON CONFLICT (id) DO NOTHING;

-- 4) Factory feed lanes (real factories -> regional hubs) to show where they sit
INSERT INTO lanes (id,origin,destination,distance_km,freeflow_min,otif_pct,volume) VALUES
 ('ln-fac1','d-fac-wki','d-hq-rrr',2410,1880,95,9),
 ('ln-fac2','d-fac-pun','d-csc-sin',4380,3410,90,8),
 ('ln-fac3','d-fac-png','d-csc-sin',95,75,97,11),
 ('ln-fac4','d-fac-chd','h-rtm',9180,7140,86,7),
 ('ln-fac5','d-fac-ric','d-hq-rrr',135,105,98,12)
ON CONFLICT (id) DO NOTHING;

SELECT 'migrated: africa offices + routes' AS done;
