DROP TABLE IF EXISTS drivers;
CREATE TABLE drivers (
 vehicle_id text primary key references vehicles(id) on delete cascade,
 full_name text, dob text, nationality text, license text, license_expiry text,
 phone text, email text, years_exp int, rating numeric(2,1), trips int, base text, avatar text
);
INSERT INTO drivers VALUES ('PLN-301','Cpt. A. Berg','19-04-11','DE','CD-258176','2030-11-01','+49 616480894','a.berg@aegis-demo.io',26,4.7,3950,'Paris','https://randomuser.me/api/portraits/men/65.jpg');
INSERT INTO drivers VALUES ('PLN-302','Cpt. R. Osei','11-07-11','DE','CD-554710','2030-02-01','+49 642301241','r.osei@aegis-demo.io',11,4.3,6657,'Vienna','https://randomuser.me/api/portraits/men/8.jpg');
INSERT INTO drivers VALUES ('PLN-303','Cpt. M. Fischer','16-02-28','DE','CD-148845','2031-03-01','+49 648870700','m.fischer@aegis-demo.io',17,3.6,12179,'Vienna','https://randomuser.me/api/portraits/men/24.jpg');
INSERT INTO drivers VALUES ('PLN-304','Cpt. L. Moreau','27-09-23','DE','CD-769949','2028-06-01','+49 623076910','l.moreau@aegis-demo.io',27,4.5,6374,'Amsterdam','https://randomuser.me/api/portraits/men/64.jpg');
INSERT INTO drivers VALUES ('PLN-305','Cpt. S. Novak','33-05-26','DE','CD-429407','2030-10-01','+49 670825377','s.novak@aegis-demo.io',30,3.9,6999,'Frankfurt','https://randomuser.me/api/portraits/men/11.jpg');
INSERT INTO drivers VALUES ('VSL-201','Cpt. M. Olsen','24-08-23','DE','CD-460160','2030-05-01','+49 691733095','m.olsen@aegis-demo.io',34,3.6,1701,'Rotterdam','https://randomuser.me/api/portraits/men/20.jpg');
INSERT INTO drivers VALUES ('VSL-202','Cpt. A. Fischer','10-08-12','DE','CD-800675','2027-09-01','+49 686910239','a.fischer@aegis-demo.io',32,4.8,1734,'Antwerp','https://randomuser.me/api/portraits/men/64.jpg');
INSERT INTO drivers VALUES ('VSL-203','Cpt. J. Rossi','35-07-21','DE','CD-198142','2029-08-01','+49 699141000','j.rossi@aegis-demo.io',30,3.5,2125,'Antwerp','https://randomuser.me/api/portraits/men/37.jpg');
INSERT INTO drivers VALUES ('VSL-204','Cpt. T. Novak','9-07-25','DE','CD-584122','2029-03-01','+49 691996233','t.novak@aegis-demo.io',14,4.2,1314,'Antwerp','https://randomuser.me/api/portraits/men/51.jpg');
INSERT INTO drivers VALUES ('VSL-205','Cpt. S. Berg','11-06-22','DE','CD-274447','2030-07-01','+49 683744576','s.berg@aegis-demo.io',27,4.8,1440,'Antwerp','https://randomuser.me/api/portraits/men/54.jpg');
INSERT INTO drivers VALUES ('VSL-206','Cpt. L. Chen','16-05-10','DE','CD-258252','2027-03-01','+49 630306925','l.chen@aegis-demo.io',28,4.5,1046,'Antwerp','https://randomuser.me/api/portraits/men/34.jpg');
INSERT INTO drivers VALUES ('VSL-207','Cpt. K. Eriksen','13-09-22','DE','CD-539297','2031-06-01','+49 691847639','k.eriksen@aegis-demo.io',26,3.9,521,'Hamburg','https://randomuser.me/api/portraits/men/59.jpg');
INSERT INTO drivers VALUES ('VSL-208','Cpt. R. Silva','21-02-20','DE','CD-518359','2030-02-01','+49 674628898','r.silva@aegis-demo.io',16,4.0,2104,'Rotterdam','https://randomuser.me/api/portraits/men/21.jpg');
INSERT INTO drivers VALUES ('VSL-209','Cpt. D. Muller','28-04-22','DE','CD-155129','2027-01-01','+49 686072408','d.muller@aegis-demo.io',29,4.3,404,'Antwerp','https://randomuser.me/api/portraits/men/10.jpg');
INSERT INTO drivers VALUES ('VSL-210','Cpt. P. Lind','13-05-12','DE','CD-765226','2029-06-01','+49 690836544','p.lind@aegis-demo.io',24,4.2,2267,'Antwerp','https://randomuser.me/api/portraits/men/62.jpg');
INSERT INTO drivers VALUES ('TRK-101','J. De vries','13-01-16','NL','CD-207151','2029-12-01','+31 645535068','j.devries@aegis-demo.io',18,4.7,781,'Amsterdam','https://randomuser.me/api/portraits/men/67.jpg');
INSERT INTO drivers VALUES ('TRK-102','M. Kowalski','25-05-26','PL','CD-479324','2028-12-01','+48 682903368','m.kowalski@aegis-demo.io',3,4.6,1340,'Warsaw','https://randomuser.me/api/portraits/men/12.jpg');
INSERT INTO drivers VALUES ('TRK-103','A. Schmidt','20-04-17','DE','CD-275156','2029-04-01','+49 681483341','a.schmidt@aegis-demo.io',20,4.6,1470,'Munich','https://randomuser.me/api/portraits/men/29.jpg');
INSERT INTO drivers VALUES ('TRK-104','L. Dubois','35-05-25','FR','CD-520148','2028-04-01','+33 679476293','l.dubois@aegis-demo.io',18,4.0,238,'Lyon','https://randomuser.me/api/portraits/men/4.jpg');
INSERT INTO drivers VALUES ('TRK-105','P. Nielsen','17-06-12','DE','CD-303051','2031-06-01','+49 670025882','p.nielsen@aegis-demo.io',28,4.9,4167,'Munich','https://randomuser.me/api/portraits/men/45.jpg');
INSERT INTO drivers VALUES ('TRK-106','R. Berg','16-08-21','DE','CD-207119','2028-08-01','+49 636401454','r.berg@aegis-demo.io',13,3.7,2676,'Munich','https://randomuser.me/api/portraits/men/1.jpg');
INSERT INTO drivers VALUES ('TRK-107','S. Müller','34-08-15','DE','CD-774373','2027-11-01','+49 626093192','s.müller@aegis-demo.io',15,4.7,3192,'Munich','https://randomuser.me/api/portraits/men/26.jpg');
INSERT INTO drivers VALUES ('TRK-108','K. Johansson','22-03-15','SE','CD-927468','2029-02-01','+46 663128543','k.johansson@aegis-demo.io',17,4.0,3998,'Gothenburg','https://randomuser.me/api/portraits/men/11.jpg');
INSERT INTO drivers VALUES ('TRK-109','T. De smet','13-06-14','DE','CD-128887','2028-10-01','+49 672458740','t.desmet@aegis-demo.io',28,4.4,2625,'Munich','https://randomuser.me/api/portraits/men/61.jpg');
INSERT INTO drivers VALUES ('TRK-110','H. Bakker','26-09-14','NL','CD-674919','2028-01-01','+31 611911654','h.bakker@aegis-demo.io',28,5.0,2781,'Amsterdam','https://randomuser.me/api/portraits/men/14.jpg');
INSERT INTO drivers VALUES ('TRK-111','F. Petit','22-05-27','FR','CD-304268','2028-01-01','+33 643800696','f.petit@aegis-demo.io',9,3.9,1105,'Lyon','https://randomuser.me/api/portraits/men/42.jpg');
INSERT INTO drivers VALUES ('TRK-112','G. Andersson','22-07-26','SE','CD-974716','2028-01-01','+46 657484087','g.andersson@aegis-demo.io',17,4.5,3458,'Gothenburg','https://randomuser.me/api/portraits/men/67.jpg');
INSERT INTO drivers VALUES ('TRK-113','D. Janssen','13-01-14','NL','CD-657658','2028-09-01','+31 678524460','d.janssen@aegis-demo.io',3,4.8,3300,'Amsterdam','https://randomuser.me/api/portraits/men/24.jpg');
INSERT INTO drivers VALUES ('TRK-114','C. Weisser','14-09-27','DE','CD-248435','2030-10-01','+49 626151306','c.weisser@aegis-demo.io',20,3.5,2914,'Munich','https://randomuser.me/api/portraits/men/67.jpg');
INSERT INTO drivers VALUES ('TRK-115','B. Lindqvist','24-09-24','SE','CD-922369','2027-09-01','+46 617626596','b.lindqvist@aegis-demo.io',10,3.7,292,'Gothenburg','https://randomuser.me/api/portraits/men/13.jpg');
INSERT INTO drivers VALUES ('TRK-116','E. Vandenbrouck','26-04-18','BE','CD-129219','2027-08-01','+32 653703122','e.vandenbrouck@aegis-demo.io',22,5.0,2602,'Ghent','https://randomuser.me/api/portraits/men/66.jpg');
INSERT INTO drivers VALUES ('TRK-117','V. Krzyzak','23-09-16','PL','CD-632840','2031-08-01','+48 678149300','v.krzyzak@aegis-demo.io',10,4.5,3710,'Warsaw','https://randomuser.me/api/portraits/men/34.jpg');
INSERT INTO drivers VALUES ('TRK-118','O. Becker','35-07-12','DE','CD-569267','2028-07-01','+49 626323822','o.becker@aegis-demo.io',15,4.1,417,'Munich','https://randomuser.me/api/portraits/men/31.jpg');
INSERT INTO drivers VALUES ('TRK-119','N. Ferrer','15-05-14','ES','CD-801992','2029-02-01','+34 630729474','n.ferrer@aegis-demo.io',25,4.4,1619,'Madrid','https://randomuser.me/api/portraits/men/19.jpg');
INSERT INTO drivers VALUES ('TRK-120','I. Halvorsen','23-03-23','NO','CD-330254','2027-07-01','+47 675399034','i.halvorsen@aegis-demo.io',8,5.0,3529,'Oslo','https://randomuser.me/api/portraits/men/29.jpg');
INSERT INTO drivers VALUES ('TRK-121','Q. Larsen','25-01-20','DK','CD-523425','2029-07-01','+45 636272404','q.larsen@aegis-demo.io',14,3.9,3077,'Copenhagen','https://randomuser.me/api/portraits/men/47.jpg');
INSERT INTO drivers VALUES ('TRK-122','W. Klein','26-09-12','DE','CD-580951','2030-12-01','+49 612426922','w.klein@aegis-demo.io',15,3.9,2675,'Munich','https://randomuser.me/api/portraits/men/38.jpg');
SELECT vehicle_id, full_name, nationality, years_exp, rating FROM drivers WHERE vehicle_id IN ('TRK-101','TRK-105','PLN-301','VSL-201');