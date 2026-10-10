"""Voertuig-dossiers: HTML + PDF (FR-105).

GET /api/vehicle/{id}/dossier        → HTML (zelfde look-and-feel)
GET /api/vehicle/{id}/dossier.pdf    → PDF via weasyprint

Inhoud: voertuig-ID, telemetrie-24u (server-side matplotlib-grafiek),
componenten met health-scores + artikelnummers + specsheets, geschiedenis,
open incidenten, aanbevelingen voor dit voertuig.
"""
import base64
import io
import os
from datetime import datetime, timezone

from dashboard.api_core import duck, _aegis
from dashboard import engine


def _tele_chart(vid: str) -> str | None:
    """Telemetrie 24u → base64 PNG (matplotlib, server-side)."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        con = duck()
        cur = con.execute(
            "SELECT ts, speed_kmh, fuel_pct, cargo_temp FROM facts.telemetry "
            "WHERE vehicle_id=? AND ts > now() - interval '24 hours' ORDER BY ts", [vid])
        rows = cur.fetchall()
        if not rows:
            return None
        fig, ax = plt.subplots(figsize=(7, 2.4), dpi=110)
        ax.plot([r[0] for r in rows], [r[1] for r in rows], color="#22d3ee", lw=1.4, label="snelheid km/h")
        ax2 = ax.twinx()
        ax2.plot([r[0] for r in rows], [r[3] for r in rows], color="#fb7185", lw=1, ls="--", label="cargo-°C")
        ax.tick_params(labelsize=8); ax2.tick_params(labelsize=8)
        fig.autofmt_xdate()
        fig.tight_layout()
        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight")
        plt.close(fig)
        return base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return None


def _vehicle(vid: str):
    con = duck()
    try:
        cur = con.execute("SELECT * FROM dims.vehicles WHERE id=?", [vid])
        rows = cur.fetchall()
        if not rows:
            return None
        cols = [d[0] for d in cur.description]
        return dict(zip(cols, rows[0]))
    except Exception:
        return None


def _components(vid: str):
    con = duck()
    try:
        cur = con.execute(
            "SELECT name, wear, health, km, last_service, next_service, status, rul_days, est_cost "
            "FROM dims.components WHERE vehicle_id=? ORDER BY health ASC", [vid])
        cols = [d[0] for d in cur.description]
        out = []
        for r in cur.fetchall():
            c = dict(zip(cols, r))
            c["part"] = engine.part_for(c)
            c["score"] = engine.component_score(c)
            out.append(c)
        return out
    except Exception:
        return []


def _history(vid: str, limit: int = 12):
    con = duck()
    try:
        cur = con.execute(
            "SELECT shipment_id, ts, type, note FROM facts.shipment_events "
            "WHERE shipment_id IN (SELECT id FROM dims.shipments WHERE vehicle_id=?) "
            "ORDER BY ts DESC LIMIT ?", [vid, limit])
        return [{"shipment": r[0], "ts": str(r[1]), "type": r[2], "note": r[3]} for r in cur.fetchall()]
    except Exception:
        return []


def _incidents(vid: str):
    try:
        with _aegis() as c, c.cursor() as cur:
            cur.execute("SELECT id, kind, severity, title, created_at FROM incidents "
                        "WHERE affected_vehicle=%s ORDER BY created_at DESC LIMIT 5", (vid,))
            return [{"id": r[0], "kind": r[1], "severity": r[2], "title": r[3], "at": str(r[4])}
                    for r in cur.fetchall()]
    except Exception:
        return []


def _recs(vid: str):
    d = engine.compute()
    return [r for r in d.get("recommendations", []) if r["vehicle_id"] == vid][:5]


def dossier_html(vid: str) -> str:
    v = _vehicle(vid)
    if v is None:
        return f"<html><body style='background:#050b1a;color:#fb7185;font-family:monospace;padding:40px'>" \
               f"VOERTUIG {vid} NIET GEVONDEN — controleer de picklist.</body></html>"
    comps = _components(vid)
    hist = _history(vid)
    inc = _incidents(vid)
    recs = _recs(vid)
    chart = _tele_chart(vid)
    fleet = engine.compute().get("fleet_health")
    now = datetime.now(timezone.utc)

    def ring(color, val):
        return f"<div class='ring' style='background:conic-gradient({color} {val*3.6}deg, #1c3354 0)'>" \
               f"<b>{val}</b></div>"

    comp_rows = "".join(
        f"<tr class='{c['status'] if c['status'] in ('ok','warning','critical') else ''}'>"
        f"<td>{c['name']}</td><td>{c['health']}</td><td>{c['wear']}</td>"
        f"<td>{c['rul_days']} d</td><td>{c['part']['part_number']}</td>"
        f"<td>{c['part']['name']}</td><td>€{c['est_cost'] or c['part']['price_eur']:,}</td>"
        f"<td>{c['next_service']}</td></tr>"
        for c in comps)
    spec_rows = "".join(
        f"<div class='spec'><b>{c['name']}</b> <span class='pn'>{c['part']['part_number']}</span> · "
        f"leverancier {c['part']['supplier']} · levertijd {c['part']['lead_time_days']} d · "
        f"€{c['part']['price_eur']:,}<ul>"
        + "".join(f"<li><i>{k}</i>: {val}</li>" for k, val in c["part"]["specs"].items())
        + "</ul></div>" for c in comps if c["status"] in ("critical", "warning"))

    inc_rows = "".join(f"<li><b>{i['severity']}</b> {i['kind']} — {i['title']} "
                       f"<span>({i['at'][:16].replace('T',' ')})</span></li>" for i in inc) or \
               "<li class='dim'>geen open incidenten</li>"
    hist_rows = "".join(f"<li><b>{h['ts'][:16].replace('T',' ')}</b> {h['type']} · {h['note']}</li>"
                        for h in hist) or "<li class='dim'>geen historie in 24u</li>"
    rec_rows = "".join(
        f"<li><b>{r['severity']}</b> {r['action']}<br><span class='dim'>waarom: {r['why']} · "
        f"impact: {r['impact']} · levertijd {r['lead_time_days']} d</span></li>"
        for r in recs) or "<li class='dim'>geen aanbevelingen — alles binnen norm</li>"

    return f"""<!DOCTYPE html>
<html lang="nl"><head><meta charset="utf-8"><title>Dossier {vid}</title>
<style>
 body{{background:#050b1a;color:#d7e6fb;font-family:'Segoe UI',system-ui,sans-serif;margin:0;padding:24px}}
 .hd{{display:flex;gap:16px;align-items:center;border-bottom:2px solid #22d3ee;padding-bottom:14px;margin-bottom:18px}}
 .hd h1{{font-size:26px;letter-spacing:2px;margin:0;color:#fff}}
 .hd .meta{{color:#6f89ad;font-size:13px}}
 .tag{{padding:3px 10px;border-radius:14px;font-size:11px;border:1px solid #1c3354;color:#6f89ad}}
 .grid{{display:grid;grid-template-columns:1.4fr 1fr;gap:14px}}
 @media(max-width:900px){{.grid{{grid-template-columns:1fr}}}}
 .card{{background:#0a1428;border:1px solid #1c3354;border-radius:10px;padding:14px}}
 h2{{font-size:14px;letter-spacing:2px;color:#fff;margin:0 0 10px}}
 table{{width:100%;border-collapse:collapse;font-size:12px}}
 td,th{{padding:6px 8px;border-bottom:1px solid #1c3354;text-align:left}}
 th{{color:#6f89ad;font-size:10px;letter-spacing:1px;text-transform:uppercase}}
 tr.critical td{{background:rgba(251,113,133,.09)}}
 tr.warning td{{background:rgba(251,191,36,.07)}}
 .pn{{font-family:monospace;color:#22d3ee;font-size:11px}}
 .spec{{background:#0d1a33;border-left:3px solid #22d3ee;padding:10px 12px;border-radius:0 8px 8px 0;margin-bottom:10px;font-size:12px}}
 .spec ul{{margin:6px 0 0 18px;padding:0;color:#9fb6d6}}
 .spec li{{margin:2px 0}}.spec i{{color:#6f89ad}}
 ul{{list-style:none;margin:0;padding:0}}
 li{{padding:6px 0;border-bottom:1px dashed #1c3354;font-size:12px}}
 .dim{{color:#44608a}}
 img{{max-width:100%}}
 .kpi{{display:flex;gap:22px;flex-wrap:wrap}}
 .kpi div b{{font-size:20px;color:#fff;display:block}}
 .kpi div span{{font-size:10px;color:#6f89ad;letter-spacing:1px;text-transform:uppercase}}
 .disc{{margin-top:16px;font-size:10px;color:#44608a}}
 @media print{{body{{padding:10px}}}}
</style></head><body>
<div class="hd">
 <h1>VOERTUIGDOSSIER {vid}</h1>
 <div class="meta">{v.get('kind')} · {v.get('name')} · model {v.get('model')} ·
 registratie {v.get('registered')}<br>gegenereerd {now:%Y-%m-%d %H:%M} UTC ·
 bron: aegis_db (read-only) + DuckLake · <span class="dim">SIM-data</span></div>
</div>
<div class="grid">
 <div class="card">
  <h2>COMPONENTEN & HEALTH</h2>
  <table><tr><th>Component</th><th>Health</th><th>Wear</th><th>RUL</th>
  <th>Artikel</th><th>Onderdeel</th><th>Verw. kosten</th><th>Next service</th></tr>
  {comp_rows}</table>
 </div>
 <div class="card">
  <h2>KPI</h2>
  <div class="kpi">
   <div><b>{fleet}</b><span>fleet-health</span></div>
   <div><b>{len([c for c in comps if c['status']=='critical'])}</b><span>critical</span></div>
   <div><b>{len([c for c in comps if c['status']=='warning'])}</b><span>warning</span></div>
   <div><b>€{sum(c['est_cost'] or c['part']['price_eur'] for c in comps if c['status']=='critical'):,}</b><span>vervang-kosten</span></div>
  </div>
  <h2 style="margin-top:16px">ANBEVELINGEN</h2>
  <ul>{rec_rows}</ul>
 </div>
 <div class="card">
  <h2>TELEMETRIE 24U</h2>
  {'<img src="data:image/png;base64,'+chart+'" alt="telemetrie">' if chart else '<div class="dim">geen telemetrie in 24u</div>'}
 </div>
 <div class="card">
  <h2>SPECSHEETS (kritieke componenten)</h2>
  {spec_rows or '<div class="dim">geen kritieke/warning componenten</div>'}
 </div>
 <div class="card">
  <h2>HISTORIE (laatste events)</h2>
  <ul>{hist_rows}</ul>
 </div>
 <div class="card">
  <h2>INCIDENTEN</h2>
  <ul>{inc_rows}</ul>
 </div>
</div>
<div class="disc">AEGIS Analytics · spec 003 · Demo-catalogus: prijzen/specs/generated (SIM).
 Read-only op aegis_db — geen schrijf-acties op de bron.</div>
</body></html>"""


def dossier_pdf(vid: str) -> bytes:
    from weasyprint import HTML
    return HTML(string=dossier_html(vid)).write_pdf()
