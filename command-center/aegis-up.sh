#!/usr/bin/env bash
# AEGIS one-command bring-up — brings the full stack back after a reboot.
# Usage: bash aegis-up.sh
set -u
AEGIS=/home/demouser/aegis
ANALYTICS=/home/demouser/aegis-analytics
LAN=${LAN_IP:-192.168.1.10}

say(){ printf '\n\033[36m== %s\033[0m\n' "$1"; }

say "1/6 Podman system service + containers"
systemctl --user start podman.socket >/dev/null 2>&1 || true
podman start aegis_db >/dev/null 2>&1
for c in aegis_analytics_kafka aegis_analytics_minio aegis_analytics_lake_catalog \
         aegis_analytics_kafka_ui aegis_analytics_grafana aegis_analytics_prometheus \
         aegis_analytics_trino aegis_analytics_captor aegis_analytics_pipeline \
         aegis_analytics_dashboard aegis_analytics_adminer; do
  podman start "$c" >/dev/null 2>&1 || true
done
# gateway (separate compose project) — recreate if the image is available
if ! podman start aegis_gw >/dev/null 2>&1; then
  (cd "$AEGIS" && podman build -q -t aegis-gateway:latest gateway/ >/dev/null 2>&1)
  podman run -d --name aegis_gw --restart unless-stopped --network aegis_default \
    -e KAFKA_BOOTSTRAP=kafka:9092 -e GW_TOPIC=aegis.events.truck.telemetry \
    -e PG_HOST=aegis_db -e PG_PORT=5432 -e PG_DB=aegis -e PG_USER=aegis -e PG_PASSWORD=aegis_dev \
    -p 8411:8411 aegis-gateway:latest >/dev/null 2>&1
fi

say "2/6 Wait for PostGIS + gateway"
for i in $(seq 1 30); do podman exec aegis_db pg_isready -U aegis >/dev/null 2>&1 && break; sleep 2; done
podman exec aegis_db pg_isready -U aegis 2>&1 | head -1
for i in $(seq 1 30); do curl -sf -m 3 http://127.0.0.1:8411/health >/dev/null 2>&1 && break; sleep 2; done

say "3/6 FastAPI :8300 (0.0.0.0 so the LAN can reach it)"
pkill -f "uvicorn api:app" 2>/dev/null; sleep 1
(cd "$AEGIS" && nohup .venv/bin/uvicorn api:app --host 0.0.0.0 --port 8300 \
  >> /tmp/aegis_api.log 2>&1 & echo $! > /tmp/aegis_api.pid)
for i in $(seq 1 20); do curl -sf -m 3 http://127.0.0.1:8300/api/kpi >/dev/null 2>&1 && break; sleep 2; done

say "4/6 Frontend :8765"
pkill -f "http.server 8765" 2>/dev/null; sleep 1
(cd /home/demouser && nohup python3 -m http.server 8765 >> /tmp/aegis_web.log 2>&1 & echo $! > /tmp/aegis_web.pid)

say "5/6 Analyst watcher (3-min cycle)"
pkill -f "agents/watcher.py" 2>/dev/null; sleep 1
(cd "$AEGIS" && nohup .venv/bin/python agents/watcher.py --interval 180 \
  >> /tmp/aegis_watcher.log 2>&1 & echo $! > /tmp/aegis_watcher.pid)

say "6/6 Verify"
ok=1
for u in "http://127.0.0.1:8300/api/kpi" "http://127.0.0.1:8300/api/stack" \
         "http://127.0.0.1:8765/aegis/web/index.html" "http://127.0.0.1:8411/health"; do
  code=$(curl -s -o /dev/null -w '%{http_code}' -m 10 "$u")
  if [ "$code" = "200" ]; then echo "  OK  $code  $u"; else echo "  FAIL $code  $u"; ok=0; fi
done
echo
if [ "$ok" = "1" ]; then
  echo "Stack up. UI: http://127.0.0.1:8765/aegis/web/index.html"
  echo "              http://$LAN:8765/aegis/web/index.html   (LAN)"
else
  echo "Something failed — check /tmp/aegis_api.log, /tmp/aegis_web.log and podman ps."
fi
