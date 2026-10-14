#!/usr/bin/env python3
"""Fetch the real Dutch A/N road network from Rijkswaterstaat VILD (CC-0 open data),
transform RD (EPSG:28992) -> WGS84 (EPSG:4326) via PostGIS ST_Transform (authoritative),
and emit a cached GeoJSON the UI can draw. Keyless."""
import json, subprocess, os, sys, urllib.request

VILD = ("https://geo.rijkswaterstaat.nl/services/ogc/gdr/vild/ows"
        "?service=WFS&version=2.0.0&request=GetFeature"
        "&typeName=vild:eerste_klasse_weg&outputFormat=application/json")
OUT = "/home/demouser/aegis/web/vendor/nl-roads.geojson"

def wfs():
    req = urllib.request.Request(VILD, headers={"User-Agent": "Mozilla/5.0 aegis-demo/1.0"})
    return json.load(urllib.request.urlopen(req, timeout=90))

d = wfs()
feats = d.get("features", [])
print("VILD features (NL A/N road lines):", len(feats))

# Build WKT lines, transform in chunks via PostGIS ST_Transform
def line_wkt(coords):
    pts = ",".join(f"{x} {y}" for x, y in coords)
    return f"LINESTRING({pts})"

def sqlq(s):
    """Single-quote-safe SQL literal for a text value."""
    return "'" + str(s).replace("'", "''") + "'"

def first_ring(g):
    """Return the first [x,y] vertex list for a LineString/MultiLineString/Polygon."""
    t = g.get("type")
    c = g["coordinates"]
    if t == "LineString":
        return c                      # [[x,y], ...]
    # MultiLineString (list of lines) / Polygon (list of rings) / MultiPolygon
    if t == "MultiLineString":
        return c[0] if c else []      # first line = [[x,y], ...]
    if t == "Polygon":
        return c[0] if c else []      # outer ring = [[x,y], ...]
    if t == "MultiPolygon":
        return c[0][0] if c and c[0] else []
    return c

# chunk the features
CHUNK = 120
out_lines = []
for i in range(0, len(feats), CHUNK):
    batch = feats[i:i+CHUNK]
    # temp table with id + wkt(28992); transform in one statement
    values = []
    idx = []
    for k, f in enumerate(batch):
        c = first_ring(f["geometry"])
        if len(c) < 2:
            continue
        wkt = line_wkt(c)
        values.append(f"({i+k}::int, {sqlq(wkt)}, 28992)")
        idx.append(i+k)
    sql = (
        "CREATE TEMP TABLE _vild(id int, w text, srid int);"
        f"INSERT INTO _vild VALUES {','.join(values)};"
        "SELECT id, ST_AsGeoJSON(ST_Transform(ST_GeomFromText(w, srid), 4326)) FROM _vild;"
    )
    r = subprocess.run(
        ["podman", "exec", "-i", "aegis_db", "psql", "-U", "aegis", "-d", "aegis", "-tA", "-F", "\t"],
        input=sql, capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        print("psql err:", r.stderr[:400]); sys.exit(1)
    import re as _re
    for line in r.stdout.splitlines():
        if not line.strip():
            continue
        # keep only real SELECT rows: "<int>\t<geojson...>"
        m = _re.match(r"^(\d+)\t(.+)$", line)
        if not m:
            continue
        _id = int(m.group(1))
        g = json.loads(m.group(2))
        p = feats[_id]["properties"]
        props = {
            "roadnumber": (p.get("roadnumber") or "").strip() or None,
            "roadname": (p.get("roadname") or "").strip() or None,
            "first_name": (p.get("first_name") or "").strip() or None,
            "loc_des": p.get("loc_des"),
        }
        out_lines.append({"type": "Feature", "geometry": g, "properties": props})

print("transformed:", len(out_lines))
# sanity: coords must be within NL-ish bounds
bad = 0
for f in out_lines:
    c = first_ring(f["geometry"])
    for v in c[:3]:
        lon, lat = v
        if not (3.0 < lon < 7.5 and 50.5 < lat < 53.9):
            bad += 1
            break
print("out-of-NL-bounds (should be ~0):", bad)

geo = {"type": "FeatureCollection",
       "source": "Rijkswaterstaat VILD (CC-0) — Nederlandse A-/N-wegen",
       "features": out_lines}
os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w") as fh:
    json.dump(geo, fh)
print("wrote", OUT, os.path.getsize(OUT), "bytes")
# distinct road numbers
nums = sorted({(f['properties']['roadnumber']) for f in out_lines if f['properties']['roadnumber']})
print("distinct road numbers:", len(nums), nums[:20])
