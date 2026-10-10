"""US1 tests: idempotentie, manual-poll, schema-uitbreiding."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _mk_captor(tmp_path):
    """Captor zonder echte Kafka (monkeypatch producer.send)."""
    os.environ["STATE_DIR"] = str(tmp_path)
    from poller import Captor

    c = Captor.__new__(Captor)
    import threading
    c._lock = threading.Lock()
    c.state = {"watermarks": {}, "bootstrapped": {}, "shipments_cache": {}}
    c.last_cycle_at = None
    c.cycle_errors = {}
    c.rows_last_cycle = {}
    c.bootstrap_pending = False
    c._cycle_active = False
    sent = []

    class FakeProducer:
        def send(self, topic, key=None, value=None):
            sent.append((topic, key, value))

        def __getattr__(self, name):
            raise AttributeError(name)

    c.producer = FakeProducer()
    c.sent = sent
    return c


def test_emit_rows_idempotent_keying(tmp_path):
    c = _mk_captor(tmp_path)
    n = c._emit_rows("telemetry", ["vehicle_id", "ts", "lat", "lng"],
                     [("T1", "2026-10-09T00:00:00+00", 51.0, 4.0),
                      ("T1", "2026-10-09T00:00:00+00", 51.0, 4.0)],
                     "cycle-test")
    assert n == 2
    keys = [k for (_t, k, _v) in c.sent]
    assert all(k == "T1:2026-10-09T00:00:00+00:00" for k in keys)
    # zelfde key → consumer/dedup kan op key+ts dedupelen
    assert len(set(keys)) == 1


def test_health_shape(tmp_path):
    c = _mk_captor(tmp_path)
    h = c.health()
    assert h["status"] in ("ok", "degraded", "error")
    assert "tables" in h and "telemetry" in h["tables"]
    assert h["bootstrap"]["total_tables"] == 8
