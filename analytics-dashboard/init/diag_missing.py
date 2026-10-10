import sys, subprocess, json
from datetime import datetime
sys.path.insert(0, "/app")
from dashboard.api_core import duck

G = "2026-10-09 04:00:00"
con = duck()
have = set(map(tuple, con.execute(
    "SELECT vehicle_id, ts FROM facts.telemetry WHERE ts <= ?", [G]).fetchall()))
out = subprocess.run(
    ["podman", "exec", "aegis_db", "psql", "-U", "aegis", "-d", "aegis",
     "-t", "-A", "-F", "|", "-c",
     "SELECT vehicle_id, to_char(ts, 'YYYY-MM-DD HH24:MI:SS.MS') "
     "FROM telemetry WHERE ts <= '" + G + "'"],
    capture_output=True, text=True).stdout.strip().split("\n")
src = {}
for line in out:
    if not line:
        continue
    veh, ts = line.rsplit("|", 1)
    t = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S.%f")
    src[(veh, t)] = ts
missing = [k for k in src if k not in have]
print(json.dumps({
    "bron_window": len(src), "lake_window": len(have), "missing": len(missing),
    "sample_missing": [f"{v}@{t}" for (v, t) in missing[:12]]}))
