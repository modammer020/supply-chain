#!/usr/bin/env python3
"""DuckLake init: creeert idempotent de lake-tabellen (data-model.md §2).

Draait als een eenmalige sidecar (lake-init) in de compose. Gebruikt DuckDB
met de ducklake-extensie; catalog = Postgres (lake-catalog), data = MinIO.
"""
import os
import sys
import time

CATALOG_HOST = os.environ.get("CATALOG_HOST", "lake-catalog")
CATALOG_PORT = os.environ.get("CATALOG_PORT", "5432")
CATALOG_DB = os.environ.get("CATALOG_DB", "lake")
CATALOG_USER = os.environ.get("CATALOG_USER", "lake")
CATALOG_PASSWORD = os.environ.get("CATALOG_PASSWORD", "Password123!")
MINIO_ENDPOINT = os.environ.get("MINIO_ENDPOINT", "http://minio:9000")
# DuckDB S3-secret wil een endpoint zonder scheme
MINIO_ENDPOINT_BARE = MINIO_ENDPOINT.split("://")[-1]
MINIO_ACCESS = os.environ.get("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET = os.environ.get("MINIO_SECRET_KEY", "Password123!")
DATA_PATH = os.environ.get("DATA_PATH", "s3://aegis-lake/data/")


def wait_for(host, port, tries=60, delay=3):
    import socket
    for i in range(tries):
        try:
            socket.create_connection((host, port), timeout=3).close()
            return
        except OSError:
            print(f"[lake-init] wacht op {host}:{port} (probe {i+1}/{tries})...")
            time.sleep(delay)
    print(f"[lake-init] FOUT: {host}:{port} niet bereikbaar", file=sys.stderr)
    sys.exit(1)


FACTS_TELEMETRY = """
CREATE TABLE IF NOT EXISTS facts.telemetry (
    vehicle_id VARCHAR, ts TIMESTAMP, lat DOUBLE, lng DOUBLE,
    speed_kmh DOUBLE, heading INTEGER, fuel_pct DOUBLE, engine_temp DOUBLE,
    cargo_temp DOUBLE, signal_pct DOUBLE, gps_acc_m DOUBLE,
    captured_at TIMESTAMP, cycle_id VARCHAR
)
"""
FACTS_SHIPMENT_EVENTS = """
CREATE TABLE IF NOT EXISTS facts.shipment_events (
    id VARCHAR, shipment_id VARCHAR, ts TIMESTAMP, type VARCHAR, note VARCHAR,
    captured_at TIMESTAMP, cycle_id VARCHAR
)
"""
# dims: bron-kolommen 1-op-1 + cycle_ts/first_seen/last_seen
DIMS = {
    "shipments": """
CREATE TABLE IF NOT EXISTS dims.shipments (
    id VARCHAR, vehicle_id VARCHAR, lane_id VARCHAR, cargo VARCHAR, qty VARCHAR,
    value_eur DOUBLE, customer VARCHAR, status VARCHAR, eta_minutes INTEGER,
    sla_minutes INTEGER, customs VARCHAR, temp_req VARCHAR,
    created_at TIMESTAMP, progress DOUBLE,
    cycle_ts TIMESTAMP, first_seen TIMESTAMP, last_seen TIMESTAMP
)""",
    "vehicles": """
CREATE TABLE IF NOT EXISTS dims.vehicles (
    id VARCHAR, kind VARCHAR, name VARCHAR, driver VARCHAR, model VARCHAR,
    capacity_t DOUBLE, load_t DOUBLE, fuel_pct DOUBLE, fuel_range_km DOUBLE,
    registered VARCHAR, carbon_tco2 DOUBLE,
    cycle_ts TIMESTAMP, first_seen TIMESTAMP, last_seen TIMESTAMP
)""",
    "lanes": """
CREATE TABLE IF NOT EXISTS dims.lanes (
    id VARCHAR, origin VARCHAR, destination VARCHAR, distance_km DOUBLE,
    freeflow_min INTEGER, otif_pct INTEGER, volume INTEGER,
    cycle_ts TIMESTAMP, first_seen TIMESTAMP, last_seen TIMESTAMP
)""",
    "locations": """
CREATE TABLE IF NOT EXISTS dims.locations (
    id VARCHAR, name VARCHAR, kind VARCHAR, lat DOUBLE, lng DOUBLE,
    capacity INTEGER, stock_level DOUBLE, region VARCHAR,
    cycle_ts TIMESTAMP, first_seen TIMESTAMP, last_seen TIMESTAMP
)""",
    "inventory": """
CREATE TABLE IF NOT EXISTS dims.inventory (
    hub_id VARCHAR, sku VARCHAR, stock INTEGER, reorder INTEGER,
    units VARCHAR, velocity DOUBLE,
    cycle_ts TIMESTAMP, first_seen TIMESTAMP, last_seen TIMESTAMP
)""",
    "drivers": """
CREATE TABLE IF NOT EXISTS dims.drivers (
    vehicle_id VARCHAR, full_name VARCHAR, dob VARCHAR, nationality VARCHAR,
    license VARCHAR, license_expiry VARCHAR, phone VARCHAR, email VARCHAR,
    years_exp INTEGER, rating DOUBLE, trips INTEGER, base VARCHAR,
    cycle_ts TIMESTAMP, first_seen TIMESTAMP, last_seen TIMESTAMP
)""",
    "components": """
CREATE TABLE IF NOT EXISTS dims.components (
    vehicle_id VARCHAR, name VARCHAR, photo VARCHAR, wear INTEGER,
    health INTEGER, km INTEGER, last_service VARCHAR, next_service VARCHAR,
    status VARCHAR, rul_days INTEGER, est_cost INTEGER,
    cycle_ts TIMESTAMP, first_seen TIMESTAMP, last_seen TIMESTAMP
)""",
}
QUARANTINE = """
CREATE TABLE IF NOT EXISTS catalog.quarantine (
    id INTEGER, topic VARCHAR, record TEXT, rule VARCHAR, reason VARCHAR,
    captured_at TIMESTAMP
)
"""


def main():
    wait_for(CATALOG_HOST, int(CATALOG_PORT))
    wait_for("minio", 9000, tries=30)
    import duckdb
    con = duckdb.connect()
    con.execute("INSTALL ducklake")
    con.execute("LOAD ducklake")
    con.execute("INSTALL httpfs")
    con.execute("LOAD httpfs")
    con.execute("INSTALL postgres")
    con.execute("LOAD postgres")
    con.execute(f"""CREATE OR REPLACE SECRET minio_secret (
        TYPE s3, ENDPOINT '{MINIO_ENDPOINT_BARE}',
        KEY_ID '{MINIO_ACCESS}', SECRET '{MINIO_SECRET}',
        REGION 'us-east-1', URL_STYLE 'path', USE_SSL false)""")
    con.execute(f"""ATTACH 'ducklake:postgres:dbname={CATALOG_DB} host={CATALOG_HOST} port={CATALOG_PORT} user={CATALOG_USER} password={CATALOG_PASSWORD}'
                  AS lake (DATA_PATH '{DATA_PATH}')""")
    con.execute("USE lake")
    con.execute("CREATE SCHEMA IF NOT EXISTS facts")
    con.execute("CREATE SCHEMA IF NOT EXISTS dims")
    con.execute("CREATE SCHEMA IF NOT EXISTS catalog")
    for name, ddl in [("telemetry", FACTS_TELEMETRY), ("shipment_events", FACTS_SHIPMENT_EVENTS)] + \
                     [(k, v) for k, v in DIMS.items()]:
        con.execute(ddl)
        print(f"[lake-init] table ready: {name}")
    con.execute(QUARANTINE)
    print("[lake-init] table ready: catalog.quarantine")
    tables = con.execute("SELECT table_schema || '.' || table_name FROM information_schema.tables ORDER BY 1").fetchall()
    print("[lake-init] alle lake-tabellen:", [t[0] for t in tables])
    con.close()
    print("[lake-init] done ✓")


if __name__ == "__main__":
    main()
