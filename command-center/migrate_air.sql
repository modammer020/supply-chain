-- ═══ AIR FLEET (vluchten) ═══
-- idempotent: wipe air fleet first, then re-insert
DELETE FROM shipment_events WHERE shipment_id LIKE 'SHP-91%';
DELETE FROM shipments WHERE id LIKE 'SHP-91%';
DELETE FROM vehicles WHERE id LIKE 'PLN-3%';
DELETE FROM lanes WHERE id LIKE 'al-%';
DELETE FROM locations WHERE id LIKE 'a-%';

INSERT INTO locations (id,name,kind,lat,lng,geom,capacity,stock_level,region) VALUES
 ('a-skl','SCHIPHOL AMS','airport',52.3086,4.7639,ST_SetSRID(ST_MakePoint(4.7639,52.3086),4326),100,60,'NL'),
 ('a-fra','FRANKFURT FRA','airport',50.0333,8.5706,ST_SetSRID(ST_MakePoint(8.5706,50.0333),4326),100,60,'DE'),
 ('a-lhr','LONDON LHR','airport',51.4700,-0.4543,ST_SetSRID(ST_MakePoint(-0.4543,51.4700),4326),100,60,'GB'),
 ('a-cdg','PARIS CDG','airport',49.0097,2.5479,ST_SetSRID(ST_MakePoint(2.5479,49.0097),4326),100,60,'FR'),
 ('a-vie','VIENNA VIE','airport',48.1100,16.5697,ST_SetSRID(ST_MakePoint(16.5697,48.1100),4326),100,60,'AT');

INSERT INTO lanes (id,origin,destination,distance_km,freeflow_min,otif_pct,volume) VALUES
 ('al-1','a-skl','a-fra',570,120,97,6),
 ('al-2','a-lhr','a-skl',390,100,95,4),
 ('al-3','a-fra','a-vie',860,150,92,3),
 ('al-4','a-skl','a-cdg',460,110,96,5),
 ('al-5','a-cdg','a-fra',590,120,93,3);

INSERT INTO vehicles (id,kind,name,driver,model,capacity_t,load_t,fuel_pct,fuel_range_km,registered,carbon_tco2) VALUES
 ('PLN-301','plane','LUMEN AIR 301','Cpt. A. van der Berg','Boeing 737-800',20,14,82,4500,'2019',1.20),
 ('PLN-302','plane','CARGO LIFT 302','Cpt. R. Osei','Airbus A320-200F',20,17,74,4300,'2016',1.15),
 ('PLN-303','plane','TRANSALP 303','Cpt. M. Fischer','Boeing 737-800',20,12,88,4500,'2021',1.05),
 ('PLN-304','plane','AIRBRIDGE 304','Cpt. L. Moreau','Airbus A320-200F',20,18,69,4300,'2014',1.25),
 ('PLN-305','plane','ALPINE FREIGHT 305','Cpt. S. Novak','Boeing 737-800',20,11,91,4500,'2022',0.95);

INSERT INTO shipments (id,vehicle_id,lane_id,cargo,qty,value_eur,customer,status,eta_minutes,sla_minutes,customs,temp_req,progress,dir) VALUES
 ('SHP-9101','PLN-301','al-1','MEDICAL EQUIPMENT','40 crates',1250000,'HelixMed GmbH','in_transit',95,120,'Cleared','Cooled',0.45,1),
 ('SHP-9102','PLN-302','al-2','PHARMA COLD-CHAIN','60 pallets',2800000,'PharmaNord','in_transit',78,100,'Cleared','2-8°C',0.62,1),
 ('SHP-9103','PLN-303','al-3','ELECTRONICS HSG','90 crates',890000,'TechVie AG','in_transit',130,150,'Cleared','—',0.38,1),
 ('SHP-9104','PLN-304','al-4','SPARE PARTS','75 boxes',540000,'AeroParts','delayed',115,95,'Pending','—',0.55,1),
 ('SHP-9105','PLN-305','al-5','LUXURY GOODS','20 crates',4100000,'Maison Doré','in_transit',105,150,'Cleared','—',0.71,1);

INSERT INTO shipment_events (shipment_id,ts,type,note) VALUES
 ('SHP-9101',now()-interval '4 hours','dep','Departed SCHIPHOL AMS'),
 ('SHP-9102',now()-interval '3 hours','dep','Departed LONDON LHR'),
 ('SHP-9103',now()-interval '5 hours','dep','Departed FRANKFURT FRA'),
 ('SHP-9104',now()-interval '2 hours','dep','Departed SCHIPHOL AMS'),
 ('SHP-9104',now()-interval '40 minutes','sla','SLA re-forecast: ETA beyond window'),
 ('SHP-9105',now()-interval '6 hours','dep','Departed PARIS CDG');
