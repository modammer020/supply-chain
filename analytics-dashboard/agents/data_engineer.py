#!/usr/bin/env python3
"""AEGIS data-engineer agent (spec 003, FR-107).

Rolle: hermes-profiel `dataengineer` dat unstructured data uit `inbox/`
(PDF, MD, JSON, txt) extraheert naar gestructureerd JSON en dat in het
analytics-dashboard zet (review-laag: pending → approved/rejected).

Patroon: idem agents/watcher.py van de command center (mandate, hermes
one-shot, strikt JSON, lockfile, jsonl-audit).

Run:  python agents/data_engineer.py [--interval 120] [--once]
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
INBOX = os.path.join(ROOT, "data", "engineer", "inbox")
OUTDIR = os.path.join(ROOT, "data", "engineer")
AUDIT = os.path.join(OUTDIR, "audit.jsonl")
PROCESSED = os.path.join(OUTDIR, "processed.json")
HERMES_BIN = os.path.expanduser("~/.local/bin/hermes")
if not os.path.exists(HERMES_BIN):
    HERMES_BIN = "hermes"
PROFILE = "dataengineer"
TIMEOUT = 240


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def log(msg):
    print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {msg}", flush=True)


# ─────────────────────────────────────────────────────────────────
# MANDATE — wat de dataengineer-moet doen (strikte JSON-uitgang)
# ─────────────────────────────────────────────────────────────────
MANDATE = """You are AEGIS-DATA-ENGINEER, the standing data engineer for the AEGIS analytics platform.
You are invoked by an automation loop that hands you ONE unstructured document (PDF/MD/text).
Your job: extract it into clean, structured JSON so the analytics dashboard can show it
with full lineage. This is for a defence-client demo — be precise and evidence-based.

EXTRACTION RULES:
- Read the document carefully. Identify: document type, vehicles, components,
  findings, severities, actions, and any part numbers or specs.
- Map components to the catalogue part types where possible:
  PART-ENG-001 (engine), PART-HYD-001 (hydraulics), PART-AXL-001 (drivetrain/propeller),
  PART-SUS-001 (suspension/landing gear), PART-ELE-001 (ECU/avionics),
  PART-COO-001 (cooling), PART-EXH-001 (exhaust/APU), PART-VAL-001 (valve/controls/other).
- Never invent facts. If a value is missing or unclear, set it to null and note it in "gaps".
- Keep "quotes" as short verbatim evidence strings (max 3, <=140 chars each).

OUTPUT — STRICT JSON ONLY (no prose, no markdown fences):
{"doc_type": "incident_report|inspection|maintenance_log|spec_update|other",
 "summary": "<one line, max 160 chars>",
 "vehicle_id": "<AEGIS vehicle id like TRK-101/PLN-301/SSV-xxx or null>",
 "components": [
    {"name": "<component name>", "finding": "<what is wrong/observed>",
     "severity": "P1|P2|P3|null", "action": "<recommended action>",
     "part_number": "PART-xxx-nnn|null"}],
 "facts": {"<key>": "<value>"},
 "quotes": ["<verbatim evidence>", ...],
 "gaps": ["<what was missing/unclear>", ...]}
"""


def extract_text(path: str) -> str:
    """PDF/MD/txt → plain text (max ~12k chars, first pages first)."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        try:
            from pypdf import PdfReader
            rd = PdfReader(path)
            txt = "\n".join((p.extract_text() or "") for p in rd.pages[:12])
        except ImportError:
            import subprocess as sp
            p = sp.run(["pdftotext", "-l", "12", path, "-"],
                       capture_output=True, text=True, timeout=60)
            txt = p.stdout
        return txt[:12000]
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()[:12000]


def invoke_engineer(text: str) -> dict:
    prompt = (MANDATE + "\n\nDOCUMENT CONTENT:\n" + text +
              "\n\nExtract now and return the JSON.")
    cmd = [HERMES_BIN, "-p", PROFILE, "chat", "-q", prompt,
           "--oneshot", "-Q", "--max-turns", "3"]
    log(f"invoking {PROFILE} (hermes -p {PROFILE})…")
    t0 = time.time()
    p = subprocess.run(cmd, capture_output=True, text=True,
                       timeout=TIMEOUT, cwd=ROOT)
    out = (p.stdout or "").strip()
    log(f"{PROFILE} responded in {time.time()-t0:.1f}s ({len(out)} chars)")
    return parse_extract(out)


def _unwrap(v, depth=3):
    for _ in range(depth):
        if isinstance(v, str):
            try:
                v = json.loads(v)
            except (json.JSONDecodeError, ValueError):
                return v
        else:
            return v
    return v


def parse_extract(payload: str) -> dict:
    if not payload:
        return {}
    txt = payload.strip()
    if txt.startswith("```"):
        txt = txt.split("\n", 1)[1]
        if "```" in txt:
            txt = txt.rsplit("```", 1)[0]
    txt = txt.strip()
    candidates = []
    try:
        candidates.append(json.loads(txt))
    except (json.JSONDecodeError, ValueError):
        pass
    dec = json.JSONDecoder()
    for idx in (txt.find("{"), txt.find('"')):
        if idx == -1:
            continue
        try:
            val, _ = dec.raw_decode(txt[idx:])
            candidates.append(val)
        except (json.JSONDecodeError, ValueError):
            continue
    for cand in candidates:
        v = _unwrap(cand)
        if isinstance(v, dict) and ("summary" in v or "doc_type" in v):
            v.setdefault("doc_type", "other")
            v.setdefault("summary", "")
            v.setdefault("vehicle_id", None)
            v.setdefault("components", [])
            v.setdefault("facts", {})
            v.setdefault("quotes", [])
            v.setdefault("gaps", [])
            return v
    return {}


def load_processed() -> dict:
    if os.path.exists(PROCESSED):
        try:
            return json.load(open(PROCESSED))
        except Exception:
            pass
    return {}


def save_processed(d):
    with open(PROCESSED, "w") as f:
        json.dump(d, f)


def audit(rec):
    with open(AUDIT, "a") as f:
        f.write(json.dumps(rec) + "\n")


def process_file(path: str) -> dict:
    fname = os.path.basename(path)
    text = extract_text(path)
    digest = hashlib.sha256(text.encode()).hexdigest()[:16]
    item_id = "eng-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S") + "-" + digest[:6]
    log(f"processing {fname} ({len(text)} chars) → {item_id}")
    extracted = invoke_engineer(text)
    item = {
        "id": item_id,
        "source": {"file": fname, "path": path, "chars": len(text),
                   "sha256": digest},
        "extracted": extracted,
        "review": {"status": "pending", "by": None, "at": None},
        "lineage": {"agent": f"hermes:{PROFILE}", "ts": now_iso()},
    }
    if not extracted:
        item["extracted"] = {"doc_type": "other", "summary": "extractie gefaald — herhaal handmatig",
                             "vehicle_id": None, "components": [], "facts": {},
                             "quotes": [], "gaps": ["bot gaf geen JSON"]}
        item["review"]["status"] = "needs_rework"
    out_path = os.path.join(OUTDIR, item_id + ".json")
    with open(out_path, "w") as f:
        json.dump(item, f, indent=2)
    processed = load_processed()
    processed[fname] = {"id": item_id, "ts": now_iso(), "status": item["review"]["status"]}
    save_processed(processed)
    audit({"event": "extract", "item": item_id, "file": fname,
           "status": item["review"]["status"], "ts": now_iso()})
    log(f"→ {out_path} (status={item['review']['status']})")
    return item


def cycle():
    os.makedirs(INBOX, exist_ok=True)
    processed = load_processed()
    for fname in sorted(os.listdir(INBOX)):
        path = os.path.join(INBOX, fname)
        if not os.path.isfile(path):
            continue
        if fname in processed:
            continue
        try:
            process_file(path)
        except Exception as e:
            log(f"ERROR {fname}: {e}")
            audit({"event": "error", "file": fname, "error": str(e)[:200], "ts": now_iso()})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=int, default=120)
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()
    log(f"data-engineer agent starting (interval={args.interval}s, once={args.once})")
    while True:
        cycle()
        if args.once:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
