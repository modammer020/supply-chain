INSERT INTO shipment_events (shipment_id,type,ts,note) VALUES
 ('SHP-9501','loaded',now() - interval '6 hours','Loaded at Dublin DC · cold chain sealed'),
 ('SHP-9502','loaded',now() - interval '4 hours','Loaded at Limerick stage · power units'),
 ('SHP-9503','loaded',now() - interval '9 hours','Limerick → Rotterdam · air-ride, shock logged'),
 ('SHP-9504','loaded',now() - interval '5 hours','Dublin → Cork · network gear'),
 ('SHP-9601','loaded',now() - interval '14 hours','Round Rock DC · westbound gate 7'),
 ('SHP-9602','loaded',now() - interval '8 hours','Round Rock DC · GPU crates, shock-monitored'),
 ('SHP-9701','loaded',now() - interval '3 days','Rotterdam gateway · transatlantic rotation R-44'),
 ('SHP-9702','loaded',now() - interval '2 days','Limerick/Stevensville rotation L-12'),
 ('SHP-9703','staged',now() - interval '1 day','Port Newark staging · gate 12');
SELECT count(*) FROM shipment_events;
