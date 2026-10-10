-- ═══════════════════════════════════════════════════════════════
-- AEGIS supply-chain command center — PostGIS schema + seed
-- ═══════════════════════════════════════════════════════════════
CREATE EXTENSION IF NOT EXISTS postgis;

-- ── locations (hubs, DCs, destinations, ports) ──
DROP TABLE IF EXISTS locations CASCADE;
CREATE TABLE locations (
  id        text PRIMARY KEY,
  name      text NOT NULL,
  kind      text NOT NULL CHECK (kind IN ('dc','port','city','airport','terminal')),
  lat       double precision,
  lng       double precision,
  geom      geometry(Point,4326),
  capacity  integer,              -- dock slots / berths
  stock_level double precision,   -- 0..100 fill %
  region    text
);

-- ── lanes (origin → destination corridors) ──
DROP TABLE IF EXISTS lanes CASCADE;
CREATE TABLE lanes (
  id             text PRIMARY KEY,
  origin         text NOT NULL REFERENCES locations(id),
  destination    text NOT NULL REFERENCES locations(id),
  distance_km    double precision,
  freeflow_min   integer,          -- baseline travel time
  otif_pct       integer DEFAULT 100,
  volume         integer DEFAULT 0 -- weekly shipments on this lane
);

-- ── vehicles (trucks, ships) ──
DROP TABLE IF EXISTS vehicles CASCADE;
CREATE TABLE vehicles (
  id           text PRIMARY KEY,
  kind         text NOT NULL CHECK (kind IN ('truck','ship')),
  name         text,
  driver       text,
  model        text,
  capacity_t   double precision,
  load_t       double precision,
  fuel_pct     double precision,
  fuel_range_km double precision,
  registered   text,
  carbon_tco2  double precision
);

-- ── shipments (supply-chain orders bound to a lane + vehicle) ──
DROP TABLE IF EXISTS shipments CASCADE;
CREATE TABLE shipments (
  id            text PRIMARY KEY,
  vehicle_id    text NOT NULL REFERENCES vehicles(id),
  lane_id       text NOT NULL REFERENCES lanes(id),
  cargo         text NOT NULL,
  qty           text,
  value_eur     double precision,
  customer      text,
  status        text NOT NULL DEFAULT 'in_transit'
                CHECK (status IN ('in_transit','delivered','delayed','rerouted','loading')),
  eta_minutes   integer,
  sla_minutes   integer,
  customs       text DEFAULT 'Cleared',
  temp_req      text,
  created_at    timestamptz DEFAULT now()
);

-- ── telemetry (rolling GPS + sensor history) ──
DROP TABLE IF EXISTS telemetry CASCADE;
CREATE TABLE telemetry (
  vehicle_id  text NOT NULL REFERENCES vehicles(id),
  ts          timestamptz NOT NULL DEFAULT now(),
  lat         double precision,
  lng         double precision,
  speed_kmh   double precision,
  heading     double precision,
  fuel_pct    double precision,
  engine_temp double precision,
  cargo_temp  double precision,
  signal_pct  double precision,
  gps_acc_m   double precision,
  geom        geometry(Point,4326),
  PRIMARY KEY (vehicle_id, ts)
);
CREATE INDEX telemetry_ts_idx ON telemetry (vehicle_id, ts DESC);

-- ── incidents (simulated accidents / road closures) ──
DROP TABLE IF EXISTS incidents CASCADE;
CREATE TABLE incidents (
  id          text PRIMARY KEY,
  lane_id     text REFERENCES lanes(id),
  kind        text NOT NULL,       -- accident / closure / weather / hazard
  severity    text NOT NULL CHECK (severity IN ('P1','P2','P3')),
  title       text,
  lat         double precision,
  lng         double precision,
  geom        geometry(Point,4326),
  affected_vehicle text,           -- truck recommended for reroute
  alt_route   geometry(LineString,4326),
  alt_km      double precision,
  alt_min     integer,
  created_at  timestamptz DEFAULT now(),
  resolved_at timestamptz
);

-- ── cached OSRM routes (primary + alternatives) ──
DROP TABLE IF EXISTS routes_cached CASCADE;
CREATE TABLE routes_cached (
  lane_id    text NOT NULL,
  variant    integer NOT NULL DEFAULT 0,   -- 0 = primary, 1.. = alternatives
  geom       geometry(LineString,4326),
  distance_km double precision,
  duration_min double precision,
  fetched_at timestamptz DEFAULT now(),
  PRIMARY KEY (lane_id, variant)
);

-- ── hub inventory / stock (supply-chain context) ──
DROP TABLE IF EXISTS inventory CASCADE;
CREATE TABLE inventory (
  hub_id    text NOT NULL REFERENCES locations(id),
  sku       text NOT NULL,
  stock     integer,
  reorder   integer,
  units     text,
  velocity  double precision,  -- units/day demand
  PRIMARY KEY (hub_id, sku)
);

-- ════════════════ SEED ════════════════
INSERT INTO locations (id,name,kind,lat,lng,geom,capacity,stock_level,region) VALUES
 ('h-rtm','ROTTERDAM','port', 51.9244, 4.4777, ST_SetSRID(ST_MakePoint(4.4777,51.9244),4326), 42, 78, 'NL-W'),
 ('h-ams','AMSTERDAM','dc',   52.3676, 4.9041, ST_SetSRID(ST_MakePoint(4.9041,52.3676),4326), 36, 84, 'NL-C'),
 ('h-ant','ANTWERP','port',   51.2194, 4.4025, ST_SetSRID(ST_MakePoint(4.4025,51.2194),4326), 51, 69, 'BE-W'),
 ('h-ham','HAMBURG','port',   53.5511, 9.9937, ST_SetSRID(ST_MakePoint(9.9937,53.5511),4326), 48, 72, 'DE-N'),
 ('h-bru','BRUSSELS','dc',    50.8503, 4.3517, ST_SetSRID(ST_MakePoint(4.3517,50.8503),4326), 28, 91, 'BE-C'),
 ('h-muc','MUNICH','dc',      48.1351, 11.5820,ST_SetSRID(ST_MakePoint(11.5820,48.1351),4326), 31, 58, 'DE-S'),
 ('d-berlin','BERLIN','city', 52.5200, 13.4050, ST_SetSRID(ST_MakePoint(13.4050,52.5200),4326), 12, NULL, 'DE'),
 ('d-paris','PARIS','city',   48.8566, 2.3522, ST_SetSRID(ST_MakePoint(2.3522,48.8566),4326), 14, NULL, 'FR'),
 ('d-bcn','BARCELONA','city', 41.3874, 2.1686, ST_SetSRID(ST_MakePoint(2.1686,41.3874),4326), 10, NULL, 'ES'),
 ('d-waw','WARSAW','city',    52.2297, 21.0122, ST_SetSRID(ST_MakePoint(21.0122,52.2297),4326), 9,  NULL, 'PL'),
 ('d-ldn','LONDON','city',    51.5074, -0.1278, ST_SetSRID(ST_MakePoint(-0.1278,51.5074),4326), 15, NULL, 'UK'),
 ('d-vie','VIENNA','city',    48.2082, 16.3738, ST_SetSRID(ST_MakePoint(16.3738,48.2082),4326), 8,  NULL, 'AT'),
 ('d-prg','PRAGUE','city',    50.0755, 14.4378, ST_SetSRID(ST_MakePoint(14.4378,50.0755),4326), 8,  NULL, 'CZ'),
 ('d-cph','COPENHAGEN','city',55.6761, 12.5683, ST_SetSRID(ST_MakePoint(12.5683,55.6761),4326), 7,  NULL, 'DK'),
 ('d-lis','LISBON','city',    38.7223, -9.1393, ST_SetSRID(ST_MakePoint(-9.1393,38.7223),4326), 6, NULL, 'PT'),
 ('d-sto','STOCKHOLM','city', 59.3293, 18.0686, ST_SetSRID(ST_MakePoint(18.0686,59.3293),4326), 7, NULL, 'SE'),
 ('d-fra','FRANKFURT','city', 50.1109, 8.6821, ST_SetSRID(ST_MakePoint(8.6821,50.1109),4326), 11, NULL, 'DE'),
 ('d-hav','LE HAVRE','port',  49.4903, 0.1004, ST_SetSRID(ST_MakePoint(0.1004,49.4903),4326), 18, NULL, 'FR'),
 ('d-got','GOTHENBURG','city',57.7089, 11.9746, ST_SetSRID(ST_MakePoint(11.9746,57.7089),4326), 6, NULL, 'SE'),
 ('d-osl','OSLO','city',      59.9139, 10.7522, ST_SetSRID(ST_MakePoint(10.7522,59.9139),4326), 5, NULL, 'NO');

-- lanes with approximate real distances
INSERT INTO lanes (id,origin,destination,distance_km,freeflow_min,otif_pct,volume) VALUES
 ('ln-1','h-rtm','d-berlin',  780, 515, 96, 14),
 ('ln-2','h-ams','d-paris',   460, 320, 98, 22),
 ('ln-3','h-rtm','d-bcn',    1470, 1120, 91, 9),
 ('ln-4','h-ant','d-fra',     450, 330, 97, 18),
 ('ln-5','h-ams','d-waw',     990, 730, 94, 12),
 ('ln-6','h-rtm','d-ldn',     430, 340, 99, 25),
 ('ln-7','h-ant','d-vie',     790, 600, 95, 10),
 ('ln-8','h-ams','d-prg',     760, 570, 96, 13),
 ('ln-9','h-rtm','d-cph',     830, 610, 93, 11),
 ('ln-10','h-ham','d-sto',    640, 480, 95, 8),
 ('ln-11','h-ham','d-osl',    680, 520, 94, 7),
 ('ln-12','h-rtm','d-lis',   1930, 1450, 90, 6),
 ('ln-13','h-bru','d-ldn',    380, 300, 98, 19),
 ('ln-14','h-muc','d-vie',    420, 310, 97, 15),
 ('ln-15','h-ant','d-paris',  320, 230, 99, 21),
 ('ln-16','h-ams','d-berlin', 710, 470, 96, 16),
 ('ln-17','h-ham','d-fra',    480, 350, 97, 17),
 ('ln-18','h-rtm','d-paris',  450, 310, 98, 20),
 ('ln-19','h-bru','d-waw',    950, 700, 93, 10),
 ('ln-20','h-muc','d-prg',    520, 390, 96, 12),
 ('ln-21','h-ams','d-cph',    770, 580, 95, 9),
 ('ln-22','h-rtm','d-fra',    500, 370, 97, 23);

INSERT INTO vehicles (id,kind,name,driver,model,capacity_t,load_t,fuel_pct,fuel_range_km,registered,carbon_tco2) VALUES
 ('TRK-101','truck',NULL,'J. DE VRIES','Scania G450',  26, 18.4, 62, 820, 'NL-482-XX', 0.42),
 ('TRK-102','truck',NULL,'M. KOWALSKI','Volvo FH16',   26, 12.1, 74, 880, 'PL-204-XX', 0.29),
 ('TRK-103','truck',NULL,'A. SCHMIDT','DAF XF 480',    28, 22.6, 48, 760, 'DE-518-XX', 0.53),
 ('TRK-104','truck',NULL,'L. DUBOIS','MAN TGX 530',    26, 15.2, 81, 840, 'FR-117-XX', 0.36),
 ('TRK-105','truck',NULL,'P. NIELSEN','Renault T',     24, 20.3, 55, 790, 'DK-330-XX', 0.47),
 ('TRK-106','truck',NULL,'R. VAN DEN BERG','Mercedes Actros',28,25.1, 69, 900,'NL-902-XX', 0.61),
 ('TRK-107','truck',NULL,'S. MÜLLER','Scania S500',    30, 29.8, 41, 810, 'DE-774-XX', 0.72),
 ('TRK-108','truck',NULL,'K. JOHANSSON','Volvo FH',    26, 14.0, 77, 850, 'SE-641-XX', 0.33),
 ('TRK-109','truck',NULL,'T. DE SMET','DAF XG 480',    24, 16.5, 58, 780, 'BE-221-XX', 0.39),
 ('TRK-110','truck',NULL,'H. BAKKER','Iveco S-Way',    28, 27.9, 66, 820, 'NL-155-XX', 0.66),
 ('TRK-111','truck',NULL,'F. PETIT','Renault T480',    24, 12.3, 83, 800, 'FR-448-XX', 0.29),
 ('TRK-112','truck',NULL,'G. ANDERSSON','Volvo FH16',  26, 20.8, 52, 860, 'SE-093-XX', 0.49),
 ('TRK-113','truck',NULL,'D. JANSSEN','MAN TGM 18.410',18, 8.4, 90, 640, 'NL-377-XX', 0.19),
 ('TRK-114','truck',NULL,'C. WEISSER','Scania R500',   26, 19.2, 61, 830, 'DE-862-XX', 0.45),
 ('TRK-115','truck',NULL,'B. LINDQVIST','DAF XF 460',  22, 10.1, 72, 770, 'SE-518-XX', 0.24),
 ('TRK-116','truck',NULL,'E. VANDENBROUCK','Volvo FH', 30, 31.6, 45, 810, 'NL-604-XX', 0.74),
 ('TRK-117','truck',NULL,'V. KRZYZAK','Scania G500',   34, 34.2, 38, 790, 'PL-990-XX', 0.81),
 ('TRK-118','truck',NULL,'O. BECKER','MAN TGX',        24, 17.4, 64, 800, 'DE-135-XX', 0.41),
 ('TRK-119','truck',NULL,'N. FERRER','Renault T480',   26, 21.1, 57, 830, 'ES-721-XX', 0.50),
 ('TRK-120','truck',NULL,'I. HALVORSEN','Volvo FH',    24, 16.0, 79, 840, 'NO-402-XX', 0.37),
 ('TRK-121','truck',NULL,'Q. LARSEN','DAF XF 480',     26, 18.7, 50, 790, 'SE-887-XX', 0.44),
 ('TRK-122','truck',NULL,'W. KLEIN','Scania G450',     28, 24.5, 68, 850, 'DE-268-XX', 0.57),
 ('VSL-201','ship','NORDIC STAR','Cpt. M. Olsen','Containership 240m', NULL,NULL, 64,NULL,'IMO 9388421', 2.1),
 ('VSL-202','ship','BALTIC CROWN','Cpt. A. Fischer','Containership 300m',NULL,NULL, 58,NULL,'IMO 9401218', 3.4),
 ('VSL-203','ship','SEA ATLAS','Cpt. J. Rossi','Product tanker 180m',NULL,NULL, 71,NULL,'IMO 9275510', 1.8),
 ('VSL-204','ship','GALATEA','Cpt. T. Novak','Bulk carrier 190m',NULL,NULL, 49,NULL,'IMO 9312204', 2.6),
 ('VSL-205','ship','AURORA TRADER','Cpt. S. Berg','Containership 280m',NULL,NULL, 62,NULL,'IMO 9455130', 3.1),
 ('VSL-206','ship','MERIDIAN','Cpt. L. Chen','Feeder 140m',NULL,NULL, 80,NULL,'IMO 9188345', 0.9),
 ('VSL-207','ship','POLARIS','Cpt. K. Eriksen','LNG carrier 295m',NULL,NULL, 55,NULL,'IMO 9466712', 4.2),
 ('VSL-208','ship','CADUCEUS','Cpt. R. Silva','Bulk carrier 170m',NULL,NULL, 67,NULL,'IMO 9299867', 2.3),
 ('VSL-209','ship','LYRA EXPRESS','Cpt. D. Muller','Containership 220m',NULL,NULL, 73,NULL,'IMO 9422098', 2.0),
 ('VSL-210','ship','TITANIC MARE','Cpt. P. Lind','Offshore supply 90m',NULL,NULL, 84,NULL,'IMO 9155670', 0.7);

INSERT INTO shipments (id,vehicle_id,lane_id,cargo,qty,value_eur,customer,status,eta_minutes,sla_minutes,customs,temp_req) VALUES
 ('SHP-9001','TRK-101','ln-1','ELECTRONICS','2 400 un', 840000,'TechNova GmbH','in_transit', 512, 540,'Cleared',NULL),
 ('SHP-9002','TRK-102','ln-2','PHARMA','800 box', 1250000,'PharmaLux SA','in_transit', 318, 330,'Cleared','2–8°C'),
 ('SHP-9003','TRK-103','ln-3','AUTO PARTS','1 200 pc', 460000,'MotorEuropa SL','in_transit', 1080,1180,'Pending','Ambient'),
 ('SHP-9004','TRK-104','ln-4','TEXTILES','5 600 rl', 210000,'FrankTextil AG','in_transit', 325, 350,'Cleared',NULL),
 ('SHP-9005','TRK-105','ln-5','COLD-CHAIN F&B','3 100 cr',380000,'BaltikFresh AB','in_transit', 700, 750,'Cleared','-18°C'),
 ('SHP-9006','TRK-106','ln-6','CHEMICALS','450 drm', 920000,'ChemBridge Ltd','in_transit', 335, 360,'Cleared','ADR 3'),
 ('SHP-9007','TRK-107','ln-7','MACHINERY','12 un', 1600000,'WienWerk AG','in_transit', 590, 640,'Cleared',NULL),
 ('SHP-9008','TRK-108','ln-8','PACKAGING','2 000 rl', 95000,'CzechPack s.r.o.','in_transit', 560, 600,'Cleared',NULL),
 ('SHP-9009','TRK-109','ln-9','CONSUMER','1 500 ct', 275000,'NordicRetail ApS','in_transit', 605, 640,'Cleared',NULL),
 ('SHP-9010','TRK-110','ln-10','MARINE EQ','200 un', 1150000,'BaltSea Marine AS','in_transit', 470, 520,'Cleared',NULL),
 ('SHP-9011','TRK-111','ln-11','ELECTRONICS','900 un', 340000,'OsloTech AS','in_transit', 515, 550,'Cleared',NULL),
 ('SHP-9012','TRK-112','ln-12','CONSUMER','3 200 un', 410000,'IberiaMall SA','in_transit', 1400,1500,'Pending',NULL),
 ('SHP-9013','TRK-113','ln-13','MEDICAL','600 shm', 680000,'UK HealthDist','in_transit', 295, 310,'Cleared','2–25°C'),
 ('SHP-9014','TRK-114','ln-14','AUTO PARTS','3 400 pc', 720000,'WienAuto GmbH','in_transit', 305, 330,'Cleared',NULL),
 ('SHP-9015','TRK-115','ln-15','WINE & SPIRITS','5 000 bt',310000,'MaisonDeluxe','in_transit', 225, 250,'Cleared',NULL),
 ('SHP-9016','TRK-116','ln-16','RENEWABLES','45 pnl', 980000,'SolarWatt AG','in_transit', 465, 500,'Cleared',NULL),
 ('SHP-9017','TRK-117','ln-17','STEEL','800 t', 6400000,'RheinStahl AG','in_transit', 340, 380,'Cleared',NULL),
 ('SHP-9018','TRK-118','ln-18','COLD-CHAIN F&B','1 800 pl',290000,'GrandFrais SAS','in_transit', 305, 330,'Cleared','0–4°C'),
 ('SHP-9019','TRK-119','ln-19','ELECTRONICS','2 900 un', 560000,'WarszawaTech','in_transit', 690, 740,'Pending',NULL),
 ('SHP-9020','TRK-120','ln-20','TEXTILES','4 100 rl', 180000,'PrahaTextil','in_transit', 385, 410,'Cleared',NULL),
 ('SHP-9021','TRK-121','ln-21','AUTO PARTS','2 200 pc', 390000,'KopenPart A/S','in_transit', 575, 610,'Cleared',NULL),
 ('SHP-9022','TRK-122','ln-22','CHEMICALS','380 drm', 780000,'RheinChem AG','in_transit', 365, 390,'Cleared','ADR 8'),
 ('SHP-9023','VSL-201','ln-1','CONTAINER MIX','840 TEU', 4200000,'Rotterdam Port Auth.','in_transit', 2600, 2900,'Cleared',NULL),
 ('SHP-9024','VSL-203','ln-12','CRUDE DERIVATIVES','96 000 t', 58000000,'IberPetrol SA','in_transit', 5200, 5600,'Cleared','Bulk');

-- seed telemetry history (last 30 min, 5-min steps) at lane midpoints
WITH t AS (
  SELECT s.vehicle_id, l.origin AS o, l.destination AS d, l.freeflow_min,
         (now() - (interval '1 minute' * (30 - (g.ord)*5))) AS ts,
         (g.ord * 0.06 + 0.3) AS frac
    FROM shipments s
    JOIN lanes l ON l.id = s.lane_id
    JOIN generate_series(0,5) g(ord) ON TRUE
   WHERE s.vehicle_id LIKE 'TRK-%'
)
INSERT INTO telemetry (vehicle_id,ts,lat,lng,speed_kmh,heading,fuel_pct,engine_temp,cargo_temp,signal_pct,gps_acc_m,geom)
SELECT t.vehicle_id,
       t.ts,
       (SELECT lat FROM locations WHERE id=t.o) + ((SELECT lat FROM locations WHERE id=t.d) - (SELECT lat FROM locations WHERE id=t.o)) * t.frac,
       (SELECT lng FROM locations WHERE id=t.o) + ((SELECT lng FROM locations WHERE id=t.d) - (SELECT lng FROM locations WHERE id=t.o)) * t.frac,
       55 + random()*35,
       round(random()*360),
       (SELECT fuel_pct FROM vehicles WHERE id=t.vehicle_id),
       78 + random()*14,
       18 + random()*5,
       80 + random()*18,
       2 + random()*4,
       ST_SetSRID(ST_MakePoint(
         (SELECT lng FROM locations WHERE id=t.o) + ((SELECT lng FROM locations WHERE id=t.d) - (SELECT lng FROM locations WHERE id=t.o)) * t.frac,
         (SELECT lat FROM locations WHERE id=t.o) + ((SELECT lat FROM locations WHERE id=t.d) - (SELECT lat FROM locations WHERE id=t.o)) * t.frac),4326)
  FROM t;

INSERT INTO inventory (hub_id,sku,stock,reorder,units,velocity) VALUES
 ('h-rtm','ELC-4400',  1820, 1500, 'units',  95.2),
 ('h-rtm','PHM-1180',   420,  600, 'boxes',  28.4),
 ('h-rtm','TEX-7720',  5200, 4000, 'rolls',  210.5),
 ('h-ams','FRZ-2200',  2900, 3000, 'crates', 140.0),
 ('h-ams','ELC-4400',  2300, 1800, 'units',  120.3),
 ('h-ams','PKG-3300',  1100, 2500, 'rolls',  185.7),
 ('h-ant','CHM-8800',   860,  500, 'drums',   22.1),
 ('h-ant','TEX-7720',  3800, 3500, 'rolls',  160.0),
 ('h-ham','STL-1100',   940,  800, 'tons',    18.2),
 ('h-ham','MCH-0500',   150,   120, 'units',   4.1),
 ('h-bru','MED-9000',   310,   250, 'shm',     9.8),
 ('h-bru','ELC-4400',  1600,  1400, 'units',  70.5),
 ('h-muc','RNV-6600',   220,   300, 'panels',  6.3),
 ('h-muc','STL-1100',  1200,  1000, 'tons',   25.0);
