-- AEGIS global — Ireland, North America & transatlantic (idempotent)
INSERT INTO locations (id,name,kind,lat,lng,geom,capacity,region,meta) VALUES
 ('d-dub','DUBLIN','city',53.3498,-6.2603,ST_SetSRID(ST_MakePoint(-6.2603,53.3498),4326),1200,'EMEA','Dublin, Ireland · EMEA distribution node'),
 ('d-cks','CORK','city',51.8985,-8.4756,ST_SetSRID(ST_MakePoint(-8.4756,51.8985),4326),700,'EMEA','Cork, Ireland · Munster logistics node, Shannon corridor'),
 ('d-nyc','NEW YORK','city',40.7306,-74.0,ST_SetSRID(ST_MakePoint(-74.0,40.7306),4326),3000,'AMERICAS','New York, USA · Americas distribution node'),
 ('d-chi','CHICAGO','city',41.8781,-87.6298,ST_SetSRID(ST_MakePoint(-87.6298,41.8781),4326),1800,'AMERICAS','Chicago, USA · midwest logistics hub'),
 ('d-sjs','SAN JOSE','city',37.3382,-121.8863,ST_SetSRID(ST_MakePoint(-121.8863,37.3382),4326),1600,'AMERICAS','San Jose, USA · west-coast innovation node'),
 ('p-nyc','NEW YORK PORT','port',40.6700,-74.0350,ST_SetSRID(ST_MakePoint(-74.0350,40.6700),4326),5000,'AMERICAS','Port Newark/Elizabeth + NYC · transatlantic ocean gateway')
ON CONFLICT (id) DO NOTHING;

INSERT INTO lanes (id,origin,destination,distance_km,freeflow_min,otif_pct,volume) VALUES
 ('ln-ie-1','d-dub','c-lim',165,110,99,420),
 ('ln-ie-2','c-lim','d-cks',118,90,98,310),
 ('ln-ie-3','d-dub','d-cks',205,150,97,280),
 ('ln-ie-4','c-lim','h-rtm',795,540,95,95),
 ('ln-ie-5','d-dub','h-ant',755,520,96,110),
 ('ln-us-1','d-hq-rrr','d-nyc',2810,1680,96,88),
 ('ln-us-2','d-nyc','d-chi',1195,700,97,140),
 ('ln-us-3','d-hq-rrr','d-sjs',2925,1760,95,64),
 ('mt-1','h-rtm','p-nyc',5780,4320,94,12),
 ('mt-2','c-lim','p-nyc',5230,3900,96,9),
 ('mt-3','p-nyc','h-rtm',5780,4320,94,10)
ON CONFLICT (id) DO NOTHING;

INSERT INTO vehicles (id,kind,name,driver,model,capacity_t,load_t,fuel_pct,fuel_range_km,registered,carbon_tco2) VALUES
 ('TRK-201','truck','IE-01 — Dublin Loop','P. O''BRIEN','Volvo FH16',25,22.4,71,1450,'1998-GH-201',8.2),
 ('TRK-202','truck','IE-02 — Munster Corridor','S. KELLY','DAF XF 480',25,19.8,84,1520,'1998-GK-202',7.4),
 ('TRK-203','truck','IE-03 — Shannon Express','M. MURPHY','MAN TGX 530',25,24.1,66,1480,'1998-GM-203',8.9),
 ('TRK-204','truck','IE-04 — Atlantic Feeder','A. WALSH','Iveco S-Way',19,16.3,90,1390,'1998-GW-204',6.1),
 ('TRK-301','truck','US-01 — Eastbound','B. HENDERSON','Kenworth T680',30,27.5,77,1850,'TX-2021-301',11.3),
 ('TRK-302','truck','US-02 — Westbound','T. BROOKS','Peterbilt 579',30,25.9,81,1820,'TX-2022-302',10.6),
 ('VSL-301','ship','MV Shannon Express','Cpt. E. Doyle','Containership 340m',62000,54800,64,18500,'IE-2018-301',41.2),
 ('VSL-302','ship','MV Atlantic Runner','Cpt. H. Nakamura','Containership 290m',48000,41200,58,17200,'JP-2019-302',36.8)
ON CONFLICT (id) DO NOTHING;

INSERT INTO shipments (id,vehicle_id,lane_id,cargo,qty,value_eur,customer,status,eta_minutes,sla_minutes,customs,temp_req,progress,dir) VALUES
 ('SHP-9501','TRK-201','ln-ie-1','Pharma cold-chain (2-8°C)','12 PLT',1450000,'Apotex EMEA','in_transit',180,170,'Cleared','2-8°C',0.35,1),
 ('SHP-9502','TRK-202','ln-ie-2','Dell power units','40 PCL',620000,'Dell EMEA IT','in_transit',120,150,'Cleared','AMBIENT',0.6,1),
 ('SHP-9503','TRK-203','ln-ie-4','Server racks (air-ride)','8 PLT',2150000,'Dell EMEA DC','in_transit',620,580,'Cleared','AMBIENT',0.2,1),
 ('SHP-9504','TRK-204','ln-ie-3','Network gear','16 PCL',880000,'Telecom IRL','in_transit',200,190,'Cleared','AMBIENT',0.75,1),
 ('SHP-9601','TRK-301','ln-us-1','Dell Precision workstations','220 UTS',4900000,'Dell Americas Retail','in_transit',1900,1800,'Cleared','AMBIENT',0.15,1),
 ('SHP-9602','TRK-302','ln-us-3','GPU accelerator crates','90 PCL',9800000,'AI Cloud West','in_transit',2050,1950,'Cleared','AMBIENT',0.4,1),
 ('SHP-9701','VSL-301','mt-1','Containerised IT hardware','2140 TEU',58000000,'Dell Ocean Freight','in_transit',4400,4320,'Cleared','AMBIENT',0.5,1),
 ('SHP-9702','VSL-302','mt-2','Server & storage containers','1720 TEU',47500000,'Dell Ocean Freight','in_transit',4050,3900,'Cleared','AMBIENT',0.3,1),
 ('SHP-9703','VSL-301','mt-3','Containerised IT hardware','1980 TEU',52300000,'Dell Ocean Freight','loading',4400,4320,'Pending','AMBIENT',0.0,1)
ON CONFLICT (id) DO NOTHING;

INSERT INTO shipment_events (shipment_id,event,ts,note) VALUES
 ('SHP-9501','loaded',now() - interval '6 hours','Loaded at Dublin DC · cold chain sealed'),
 ('SHP-9502','loaded',now() - interval '4 hours','Loaded at Limerick stage · power units'),
 ('SHP-9503','loaded',now() - interval '9 hours','Limerick → Rotterdam · air-ride, shock logged'),
 ('SHP-9601','loaded',now() - interval '14 hours','Round Rock DC · westbound gate 7'),
 ('SHP-9701','loaded',now() - interval '3 days','Rotterdam gateway · transatlantic rotation R-44'),
 ('SHP-9702','loaded',now() - interval '2 days','Limerick/Stevensville rotation L-12')
ON CONFLICT DO NOTHING;

-- driver profiles for the new units
INSERT INTO drivers (vehicle_id,full_name,dob,nationality,license,license_expiry,phone,email,years_exp,rating,trips,base,avatar) VALUES
 ('TRK-201','P. O''Brien','1983-04-12','IE','CD-331122','2028-04-01','+350 85 447120','p.obrien@aegis-demo.io',17,4.7,2860,'Dublin','https://randomuser.me/api/portraits/men/22.jpg'),
 ('TRK-202','S. Kelly','1988-09-03','IE','CD-331187','2029-09-01','+350 86 552310','s.kelly@aegis-demo.io',12,4.5,1940,'Limerick','https://randomuser.me/api/portraits/men/33.jpg'),
 ('TRK-203','M. Murphy','1981-02-19','IE','CD-331044','2027-02-01','+350 87 118845','m.murphy@aegis-demo.io',21,4.8,3410,'Cork','https://randomuser.me/api/portraits/men/45.jpg'),
 ('TRK-204','A. Walsh','1990-11-27','IE','CD-331255','2030-11-01','+350 88 220071','a.walsh@aegis-demo.io',9,4.2,1230,'Limerick','https://randomuser.me/api/portraits/men/12.jpg'),
 ('TRK-301','B. Henderson','1979-06-30','US','CD-990341','2027-06-01','+1 512 645-8890','b.henderson@aegis-demo.io',25,4.6,4120,'Round Rock','https://randomuser.me/api/portraits/men/55.jpg'),
 ('TRK-302','T. Brooks','1985-01-08','US','CD-990488','2029-01-01','+1 512 645-9917','t.brooks@aegis-demo.io',15,4.4,2670,'Round Rock','https://randomuser.me/api/portraits/men/67.jpg'),
 ('VSL-301','Cpt. E. Doyle','1976-08-14','IE','STCW-220118','2029-08-01','+353 21 4450012','e.doyle@aegis-demo.io',30,4.9,1450,'Dublin','https://randomuser.me/api/portraits/men/78.jpg'),
 ('VSL-302','Cpt. H. Nakamura','1974-05-22','JP','STCW-220305','2028-05-01','+81 3 5550 1188','h.nakamura@aegis-demo.io',33,4.8,1820,'Shanghai','https://randomuser.me/api/portraits/men/36.jpg')
ON CONFLICT (vehicle_id) DO NOTHING;

SELECT count(*) AS total_vehicles FROM vehicles;
SELECT count(*) AS total_lanes FROM lanes;
SELECT count(*) AS total_locations FROM locations;
