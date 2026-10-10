"""Data-engineer review-laag (FR-107): list/inspect/review geëxtracte items.

Leest `data/engineer/*.json` (geschreven door agents/data_engineer.py op de
host, gemount in de dashboard-container). Review-status: pending → approved/
rejected/needs_rework; elke actie gaat in de audit-log (append-only).
"""
import glob
import json
import os
from datetime import datetime, timezone

OUTDIR = os.environ.get("ENGINEER_DIR", "/app/data/engineer")
AUDIT = os.path.join(OUTDIR, "audit.jsonl")
VALID_REVIEWS = ("approved", "rejected", "pending", "needs_rework")


def _items():
    items = []
    for p in sorted(glob.glob(os.path.join(OUTDIR, "eng-*.json"))):
        try:
            with open(p) as f:
                item = json.load(f)
            item["_file"] = os.path.basename(p)
            items.append(item)
        except Exception:
            continue
    items.sort(key=lambda x: x.get("lineage", {}).get("ts", ""), reverse=True)
    return items


def audit(event, **kw):
    try:
        rec = {"event": event, "ts": datetime.now(timezone.utc).isoformat(), **kw}
        with open(AUDIT, "a") as f:
            f.write(json.dumps(rec) + "\n")
    except Exception:
        pass


def list_items(status: str = None):
    out = []
    for it in _items():
        st = it.get("review", {}).get("status")
        if status and st != status:
            continue
        ex = it.get("extracted", {})
        out.append({
            "id": it["id"],
            "file": it.get("source", {}).get("file"),
            "doc_type": ex.get("doc_type"),
            "summary": ex.get("summary"),
            "vehicle_id": ex.get("vehicle_id"),
            "components": ex.get("components", []),
            "gaps": ex.get("gaps", []),
            "status": st,
            "ts": it.get("lineage", {}).get("ts"),
            "agent": it.get("lineage", {}).get("agent"),
        })
    return {"count": len(out), "items": out}


def get_item(item_id: str):
    for it in _items():
        if it["id"] == item_id:
            return it
    return None


def review(item_id: str, status: str, by: str = "operator"):
    if status not in VALID_REVIEWS:
        return {"error": f"status moet een van {VALID_REVIEWS} zijn"}
    it = get_item(item_id)
    if not it:
        return {"error": "item niet gevonden"}
    it["review"]["status"] = status
    it["review"]["by"] = by
    it["review"]["at"] = datetime.now(timezone.utc).isoformat()
    path = os.path.join(OUTDIR, it["_file"])
    with open(path, "w") as f:
        json.dump(it, f, indent=2)
    audit("review", item=item_id, status=status, by=by)
    return {"id": item_id, "status": status}
