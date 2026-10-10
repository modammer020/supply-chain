#!/bin/sh
# Creeert de AEGIS-analytics topics (idempotent) zodra Kafka healthy is.
set -e
TOPICS="aegis.events.telemetry aegis.events.shipment aegis.dim.shipments aegis.dim.vehicles aegis.dim.lanes aegis.dim.locations aegis.dim.inventory aegis.dim.drivers aegis.dim.components aegis.quarantine"
BOOT="${KAFKA_BOOTSTRAP:-kafka:9092}"
echo "[kafka-init] wacht op Kafka (bootstrap $BOOT)…"
until /opt/kafka/bin/kafka-topics.sh --bootstrap-server "$BOOT" --list >/dev/null 2>&1; do sleep 3; done
for t in $TOPICS; do
  /opt/kafka/bin/kafka-topics.sh --bootstrap-server "$BOOT" --create --if-not-exists \
    --topic "$t" --partitions 3 --replication-factor 1 \
    --config retention.ms=604800000 >/dev/null && echo "[kafka-init] topic ready: $t"
done
echo "[kafka-init] alle topics aangemaakt ✓"
