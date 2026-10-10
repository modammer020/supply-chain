"""US2 tests: contract-validator (standalone, zonder Spark/Kafka)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pipeline.main import load_contract, validate_record  # noqa


def test_enum_violation_shipments():
    c = load_contract("aegis.dim.shipments")
    ok, v = validate_record({"id": "S1", "status": "onbekend",
                             "lane_id": "L1", "vehicle_id": "T1",
                             "created_at": "2026-10-09T00:00:00+00"}, c)
    assert not ok
    assert any(r == "enums" for r, _ in v)


def test_range_violation_fuel():
    c = load_contract("aegis.events.telemetry")
    ok, v = validate_record({"vehicle_id": "T1", "ts": "2026-10-09T00:00:00+00",
                             "lat": 51.0, "lng": 4.0, "fuel_pct": 143}, c)
    assert not ok
    assert any(r == "ranges" and "fuel_pct" in reason for r, reason in v)


def test_valid_telemetry():
    c = load_contract("aegis.events.telemetry")
    ok, v = validate_record({"vehicle_id": "T1", "ts": "2026-10-09T00:00:00+00",
                             "lat": 51.9, "lng": 4.4, "fuel_pct": 72.0,
                             "speed_kmh": 80.0, "cargo_temp": 4.2}, c)
    assert ok, v


def test_required_missing():
    c = load_contract("aegis.dim.shipments")
    ok, v = validate_record({"id": "S1"}, c)
    assert not ok
    assert any(r == "schema.required" for r, _ in v)


def test_schema_extension_fail_safe():
    """Nieuwe onbekende kolom in bron → geaccepteerd (fail-safe)."""
    c = load_contract("aegis.dim.vehicles")
    ok, v = validate_record({"id": "V1", "kind": "truck", "fuel_pct": 50.0,
                             "nieuwe_kolom": "x"}, c)
    assert ok, v
