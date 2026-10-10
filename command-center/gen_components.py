#!/usr/bin/env python3
"""Deterministically seed the `components` table (wear + part condition) for every vehicle.
Same seed -> same wear, so the frontend datasheet and the replay stay consistent.
Outputs a single SQL file: components.sql
"""
import hashlib, math, datetime

def rng_from(seed: str):
    # mulberry32, matches frontend
    h = 0
    for ch in seed:
        h = (h * 31 + ord(ch)) | 0
    h = (h ^ 15) & 0xFFFFFFFF
    h = h | 1
    def step():
        nonlocal h
        h = (h + 0x6D2B79F5) & 0xFFFFFFFF
        t = h
        t = (t ^ (t >> 15)) * 25 | 0
        t = t & 0xFFFFFFFF
        t = (t ^ (t * 17) & 0xFFFFFFFF)
        return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296
    return step

# fetch vehicle list (id, kind, model)
import psycopg2
DB = dict(host="127.0.0.1", port=5433, dbname="aegis", user="aegis", password="aegis_dev")
c = psycopg2.connect(**DB); cur = c.cursor()
cur.execute("SELECT id, kind, model FROM vehicles ORDER BY id")
vehs = cur.fetchall()
c.close()

# component catalogue per kind  (name, photo_key)
CATALOG = {
    "truck": [
        ("Engine", "engine"), ("Transmission", "gearbox"), ("Brake system", "brake"),
        ("Tyres (8x)", "tyre"), ("Fuel system", "fuel"), ("Cooling / radiator", "cooling"),
        ("Electrical / ECU", "ecg"), ("Suspension / airbag", "suspension"),
        ("Exhaust / AdBlue", "exhaust"), ("Cab / body", "cab"),
    ],
    "ship": [
        ("Main engine", "engine"), ("Propeller / shaft", "prop"), ("Ballast system", "valve"),
        ("Navigation / GPS", "radar"), ("Refrigeration", "cooling"), ("Fuel system", "fuel"),
        ("Crane / hatch", "gearbox"), ("Bow thruster", "prop"),
    ],
    "plane": [
        ("Engine #1 (CFM)", "engine"), ("Engine #2 (CFM)", "engine"), ("Avionics / FMS", "ecg"),
        ("Hydraulics", "valve"), ("Landing gear", "suspension"), ("APU", "exhaust"),
        ("Flight controls", "gearbox"), ("Anti-ice / pitot", "cooling"),
    ],
}
# wear rates per kind (relative).  higher = wears faster
BASE_KM = {"truck": 480000, "ship": 190000, "plane": 120000}   # fleet reference hours

NOW = datetime.datetime(2026, 10, 9, 12, 0, 0)

rows = []
for vid, kind, model in vehs:
    r = rng_from(vid + "::wear")
    base_age = r() * 0.5 + 0.35          # 0.35 - 0.85 of reference age
    km = round(BASE_KM[kind] * base_age * (0.8 + r() * 0.5))
    for (cname, photo) in CATALOG[kind]:
        # per-component wear drifts around the vehicle's age
        wear = int(min(97, max(4, base_age * 100 + (r() * 30 - 15))))
        health = 100 - wear
        # last service (days ago)
        last_days = int(r() * 120 + 5)
        last = NOW - datetime.timedelta(days=last_days)
        # next service (days from now), worse when health low
        span = int(90 + (health / 100) * 180 + r() * 40)
        nxt = NOW + datetime.timedelta(days=span)
        # status
        if health < 25: status = "critical"
        elif health < 50: status = "warning"
        else: status = "ok"
        # predicted RUL (remaining useful life, days) proportional to health
        rul = int(30 + health * 3.2 + r() * 30)
        cost = int(1200 + (100 - health) * 900 + r() * 1500)  # € replacement/repair est
        rows.append({
            "vid": vid, "kind": kind, "name": cname, "photo": photo,
            "wear": wear, "health": health, "km": km,
            "last": last.strftime("%Y-%m-%d"), "next": nxt.strftime("%Y-%m-%d"),
            "status": status, "rul": rul, "cost": cost,
        })

# write SQL
out = []
out.append("-- deterministic components seed (wear + part condition)")
out.append("DROP TABLE IF EXISTS components CASCADE;")
out.append("""CREATE TABLE components (
  vehicle_id text NOT NULL REFERENCES vehicles(id) ON DELETE CASCADE,
  name       text NOT NULL,
  photo      text NOT NULL,
  wear       integer NOT NULL,
  health     integer NOT NULL,
  km         integer NOT NULL,
  last_service date NOT NULL,
  next_service date NOT NULL,
  status     text NOT NULL,
  rul_days   integer NOT NULL,
  est_cost   integer NOT NULL,
  PRIMARY KEY (vehicle_id, name)
);""")
out.append("CREATE INDEX components_vehicle_idx ON components(vehicle_id);")
vals = ",\n".join(
    "('{vid}','{name}','{photo}',{wear},{health},{km},'{last}','{next}','{status}',{rul},{cost})".format(**row)
    for row in rows
)
out.append(f"INSERT INTO components (vehicle_id,name,photo,wear,health,km,last_service,next_service,status,rul_days,est_cost) VALUES\n{vals};")
open("components.sql", "w").write("\n".join(out) + "\n")
print(f"wrote components.sql with {len(rows)} component rows for {len(vehs)} vehicles")
