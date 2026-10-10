"""Gedeelde config: bron (read-only), Kafka, lake, poller."""
import os

AEGIS_DB_HOST = os.environ.get("AEGIS_DB_HOST", "aegis_db")
AEGIS_DB_PORT = int(os.environ.get("AEGIS_DB_PORT", "5432"))
AEGIS_DB_DB = os.environ.get("AEGIS_DB_DB", "aegis")
AEGIS_DB_USER = os.environ.get("AEGIS_DB_USER", "aegis")
AEGIS_DB_PASSWORD = os.environ.get("AEGIS_DB_PASSWORD", "aegis_dev")

KAFKA_BOOTSTRAP = os.environ.get("KAFKA_BOOTSTRAP", "kafka:9092")

MINIO_ENDPOINT = os.environ.get("MINIO_ENDPOINT", "http://minio:9000")
# DuckDB S3-secret wil een endpoint ZONDER scheme (hij bouwt de URL zelf).
MINIO_ENDPOINT_BARE = MINIO_ENDPOINT.split("://")[-1]
MINIO_ACCESS_KEY = os.environ.get("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.environ.get("MINIO_SECRET_KEY", "Password123!")
DATA_PATH = os.environ.get("DATA_PATH", "s3://aegis-lake/data/")
CATALOG_HOST = os.environ.get("CATALOG_HOST", "lake-catalog")
CATALOG_PORT = int(os.environ.get("CATALOG_PORT", "5432"))
CATALOG_DB = os.environ.get("CATALOG_DB", "lake")
CATALOG_USER = os.environ.get("CATALOG_USER", "lake")
CATALOG_PASSWORD = os.environ.get("CATALOG_PASSWORD", "Password123!")

POLL_INTERVAL_S = int(os.environ.get("POLL_INTERVAL_S", "30"))

TABLES = [
    ("shipment_events", "aegis.events.shipment", ["id"], True),
    ("telemetry", "aegis.events.telemetry", ["vehicle_id", "ts"], True),
    ("shipments", "aegis.dim.shipments", ["id"], False),
    ("vehicles", "aegis.dim.vehicles", ["id"], False),
    ("lanes", "aegis.dim.lanes", ["id"], False),
    ("locations", "aegis.dim.locations", ["id"], False),
    ("inventory", "aegis.dim.inventory", ["hub_id", "sku"], False),
    ("drivers", "aegis.dim.drivers", ["vehicle_id"], False),
    ("components", "aegis.dim.components", ["vehicle_id", "name"], False),
]

STATE_DIR = os.environ.get("STATE_DIR", "/app/state")


def state_path() -> str:
    return os.path.join(STATE_DIR, "watermarks.json")


def db_dsn() -> str:
    return (f"dbname={AEGIS_DB_DB} user={AEGIS_DB_USER} password={AEGIS_DB_PASSWORD} "
            f"host={AEGIS_DB_HOST} port={AEGIS_DB_PORT}")
