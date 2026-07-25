#!/usr/bin/env python3
"""
Build a self-contained, JavaScript-free dashboard.html from prices.db.

Layout:
  * Per sector, a TABLE with 5 time-slots (Early/Morning/Midday/Evening/Night)
    for each airline, showing the latest fare + day-over-day change for each
    booking horizon (D+1 / +1wk / +3wk).
  * A collapsible section of small trend charts (fare vs capture date) so the
    longitudinal movement is visible once several days are collected.

Everything is rendered server-side so it displays in any browser without JS.
"""

import os
import sqlite3
import datetime as dt
from html import escape

import config

HCOLORS = {"D+1": "var(--h1)", "+1wk": "var(--h2)", "+3wk": "var(--h3)"}
AVIATION_DB = "aviation.db"


def minutes(hhmm):
    if not hhmm or ":" not in hhmm:
        return None
    h, m = hhmm.split(":")[:2]
    return int(h) * 60 + int(m)


def load():
    """Return (entries_by_sector, capture_dates, target_by, meta).

    entries_by_sector[sector] = list of (airline, [entry, ...]) groups, where
        entry = {"label", "sub", "dep", "order", "byh": {horizon: [pts]}}
    "slots" sectors -> one entry per popular time-slot per tracked airline
    "all"   sectors -> one entry per distinct nonstop flight, every airline
    """
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT capture_date, sector, horizon, target_date, airline,
                  dep_time, flight_number, price
           FROM prices"""
    ).fetchall()
    meta = conn.execute(
        "SELECT COUNT(*) AS n, MIN(capture_date) AS first, MAX(capture_date) AS last FROM prices"
    ).fetchone()
    conn.close()

    sec_cfg = {s["sector"]: s for s in config.SECTORS}
    buckets = {}  # (capture_date, sector, horizon, airline) -> [flights]
    target_by = {}
    capture_dates = set()
    for r in rows:
        if r["sector"] not in sec_cfg:
            continue
        capture_dates.add(r["capture_date"])
        target_by[(r["capture_date"], r["horizon"])] = r["target_date"]
        buckets.setdefault((r["capture_date"], r["sector"], r["horizon"], r["airline"]), []).append(
            {"dep": r["dep_time"], "price": r["price"], "fno": r["flight_number"]}
        )

    # series[(sector, airline, rowkey, horizon)] = [pts]; rowmeta[(sector,airline,rowkey)] = {...}
    series, rowmeta = {}, {}

    def add(sector, airline, rk, horizon, cd, price, dep, fno, meta_row):
        series.setdefault((sector, airline, rk, horizon), []).append(
            {"date": cd, "price": price, "dep_time": dep, "flight_number": fno,
             "target_date": target_by[(cd, horizon)]})
        rowmeta[(sector, airline, rk)] = meta_row

    for (cd, sector, horizon, airline), flights in buckets.items():
        cfg = sec_cfg[sector]
        if cfg.get("mode", "slots") == "all":
            for f in flights:  # every flight, every airline
                rk = ("flight", f["fno"] or f["dep"])
                add(sector, airline, rk, horizon, cd, f["price"], f["dep"], f["fno"],
                    {"label": f["fno"] or f["dep"], "sub": "",
                     "order": minutes(f["dep"]) if minutes(f["dep"]) is not None else 9999,
                     "dep": f["dep"]})
        else:  # slots: nearest fared flight to each anchor, tracked airlines only
            if airline not in cfg.get("airlines", config.AIRLINES):
                continue
            for i, (slot_label, anchor) in enumerate(config.TIME_SLOTS):
                amin = minutes(anchor)
                best, best_d = None, None
                for f in flights:
                    if f["price"] is None:
                        continue
                    fm = minutes(f["dep"])
                    if fm is None:
                        continue
                    d = abs(fm - amin)
                    if d <= config.SLOT_WINDOW_MIN and (best_d is None or d < best_d or
                                                        (d == best_d and f["price"] < best["price"])):
                        best, best_d = f, d
                if best is None:
                    continue
                add(sector, airline, ("slot", slot_label), horizon, cd, best["price"],
                    best["dep"], best["fno"],
                    {"label": slot_label, "sub": f"~{anchor}", "order": i, "dep": best["dep"]})

    for k in series:
        series[k].sort(key=lambda p: p["date"])

    capture_dates = sorted(capture_dates)
    latest = capture_dates[-1] if capture_dates else None
    horizons = [h for h, _ in config.HORIZONS]

    # Assemble ordered entries per sector (rows present at the latest capture).
    entries_by_sector = {}
    for sector, cfg in sec_cfg.items():
        mode = cfg.get("mode", "slots")
        by_airline = {}
        for (s, a, rk), m in rowmeta.items():
            if s != sector:
                continue
            byh = {h: series.get((sector, a, rk, h), []) for h in horizons}
            if latest is None:
                continue
            has_latest = any(any(p["date"] == latest for p in pts) for pts in byh.values())
            if not has_latest:
                continue
            if mode == "all":
                # Drop flights with no bookable fare at the latest capture
                # (e.g. Alliance Air, which Google Flights lists without a price).
                has_fare = any(any(p["date"] == latest and p["price"] is not None for p in pts)
                               for pts in byh.values())
                if not has_fare:
                    continue
            by_airline.setdefault(a, []).append(
                {"label": m["label"], "sub": m["sub"], "dep": m["dep"], "order": m["order"], "byh": byh})

        if mode == "all":
            k = cfg.get("max_per_airline")
            if k:
                for a in by_airline:
                    by_airline[a] = _spread_pick(sorted(by_airline[a], key=lambda e: e["order"]), k)
            airline_order = sorted(by_airline, key=lambda a: min(e["order"] for e in by_airline[a]))
        else:
            airline_order = [a for a in cfg.get("airlines", config.AIRLINES) if a in by_airline]
        entries_by_sector[sector] = [
            (a, sorted(by_airline[a], key=lambda e: e["order"])) for a in airline_order
        ]

    return entries_by_sector, capture_dates, target_by, meta


def _spread_pick(entries, k):
    """Keep k entries spread across the day (nearest to k anchors in 07:00–21:00)."""
    if len(entries) <= k:
        return entries
    lo, hi = 7 * 60, 21 * 60
    anchors = [(lo + hi) / 2] if k == 1 else [lo + i * (hi - lo) / (k - 1) for i in range(k)]
    chosen, used = [], set()
    for anc in anchors:
        best = None
        for idx, e in enumerate(entries):
            if idx in used:
                continue
            if best is None or abs(e["order"] - anc) < abs(entries[best]["order"] - anc):
                best = idx
        if best is not None:
            used.add(best)
            chosen.append(entries[best])
    return sorted(chosen, key=lambda e: e["order"])


def inr(n):
    return "₹" + f"{int(round(n)):,}"


def delta_cell(pts):
    """Latest price + day-over-day change for one series list (nulls ignored)."""
    pts = [p for p in pts if p.get("price") is not None]
    if not pts:
        return "<td class='muted'>—</td>"
    last = pts[-1]
    chg = ""
    if len(pts) > 1:
        d = last["price"] - pts[-2]["price"]
        if d == 0:
            chg = "<span class='muted'> ±0</span>"
        else:
            cls = "chg-up" if d > 0 else "chg-down"
            arr = "▲" if d > 0 else "▼"
            chg = f" <span class='{cls}'>{arr}{inr(abs(d))}</span>"
    title = escape(last.get("flight_number") or "")
    return f"<td title='{title}'>{inr(last['price'])}{chg}</td>"


def sector_table(sector_name, first_col, groups, latest, target_by):
    horizons = [h for h, _ in config.HORIZONS]
    ncols = len(horizons) + 2
    head_cells = "".join(
        f"<th>{h}<br><span class='muted'>{(target_by.get((latest, h)) or '')[5:]}</span></th>"
        for h in horizons
    )
    body = []
    for airline, entries in groups:
        body.append(f"<tr class='air'><td colspan='{ncols}'>{escape(airline)}</td></tr>")
        for e in entries:
            first = escape(str(e["label"]))
            if e["sub"]:
                first += f"<br><span class='muted'>{escape(e['sub'])}</span>"
            cells = "".join(
                delta_cell([p for p in e["byh"].get(h, []) if p["date"] <= latest])
                for h in horizons
            )
            body.append(
                f"<tr><td class='slot'>{first}</td><td class='muted'>{escape(e['dep'] or '')}</td>{cells}</tr>"
            )
    if not body:
        body.append(f"<tr><td colspan='{ncols}' class='muted'>No flights captured yet</td></tr>")
    return (
        f"<div class='card'><h3>{escape(sector_name)}</h3>"
        f"<table><thead><tr><th>{first_col}</th><th>Dep</th>{head_cells}</tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table></div>"
    )


def svg_chart(series_map):
    W, H, PL, PR, PT, PB = 300, 150, 46, 10, 12, 20
    all_pts = [p for pts in series_map.values() for p in pts]
    if not all_pts:
        return "<div class='empty'>—</div>"
    dates = sorted({p["date"] for p in all_pts})
    prices = [p["price"] for p in all_pts]
    lo, hi = min(prices), max(prices)
    if lo == hi:
        lo -= 500
        hi += 500
    pad = (hi - lo) * 0.15
    lo -= pad
    hi += pad

    def x(i):
        return PL + (W - PL - PR) / 2 if len(dates) <= 1 else PL + i * (W - PL - PR) / (len(dates) - 1)

    def y(v):
        return PT + (H - PT - PB) * (1 - (v - lo) / (hi - lo))

    parts = [f'<svg viewBox="0 0 {W} {H}" width="100%" role="img">']
    for g in range(3):
        v = lo + (hi - lo) * g / 2
        yy = y(v)
        parts.append(f'<line x1="{PL}" y1="{yy:.1f}" x2="{W-PR}" y2="{yy:.1f}" stroke="var(--line)"/>')
        parts.append(f'<text x="{PL-5}" y="{yy+3:.1f}" text-anchor="end">{inr(round(v/100)*100)}</text>')
    parts.append(f'<text x="{x(0):.1f}" y="{H-5}" text-anchor="middle">{dates[0][5:]}</text>')
    if len(dates) > 1:
        parts.append(f'<text x="{x(len(dates)-1):.1f}" y="{H-5}" text-anchor="middle">{dates[-1][5:]}</text>')
    for h, pts in series_map.items():
        col = HCOLORS.get(h, "#888")
        coords = [(x(dates.index(p["date"])), y(p["price"])) for p in sorted(pts, key=lambda p: p["date"])]
        if len(coords) > 1:
            parts.append('<polyline fill="none" stroke="%s" stroke-width="2" points="%s"/>'
                         % (col, " ".join(f"{cx:.1f},{cy:.1f}" for cx, cy in coords)))
        for cx, cy in coords:
            parts.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="2.6" fill="{col}"/>')
    parts.append("</svg>")
    return "".join(parts)


def charts_section(entries_by_sector):
    horizons = [h for h, _ in config.HORIZONS]
    blocks = []
    for sec in config.SECTORS:
        cells = []
        for airline, entries in entries_by_sector.get(sec["sector"], []):
            for e in entries:
                smap = {h: [p for p in e["byh"].get(h, []) if p.get("price") is not None]
                        for h in horizons}
                smap = {h: v for h, v in smap.items() if v}
                if not smap:
                    continue
                cells.append(
                    f"<div class='mini'><div class='mini-t'>{escape(airline)} · {escape(str(e['label']))}</div>"
                    f"{svg_chart(smap)}</div>"
                )
        if cells:
            blocks.append(f"<h4>{escape(sec['name'])}</h4><div class='minis'>{''.join(cells)}</div>")
    return (
        "<details class='charts'><summary>Show trend charts (fare vs capture date)</summary>"
        + "".join(blocks) + "</details>"
    )


def _fmt_int(v):
    try:
        return f"{int(round(v)):,}"
    except (TypeError, ValueError):
        return "—"


def aviation_section():
    """Render the national aviation-activity panel from aviation.db, or ''.

    The MoCA page updates each card independently, so different sections can
    carry different report dates on the same load. We therefore resolve the
    latest (and previous) report date PER SECTION.
    """
    if not os.path.exists(AVIATION_DB):
        return ""
    conn = sqlite3.connect(AVIATION_DB)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("SELECT 1 FROM aviation LIMIT 1")
    except sqlite3.OperationalError:
        conn.close()
        return ""

    def recent_dates(section):
        rows = conn.execute(
            "SELECT report_date, MAX(capture_date) mcd FROM aviation WHERE section=? "
            "GROUP BY report_date ORDER BY mcd DESC, report_date DESC LIMIT 2",
            (section,),
        ).fetchall()
        latest = rows[0]["report_date"] if rows else None
        prev = rows[1]["report_date"] if len(rows) > 1 else None
        return latest, prev

    def val(report, section, item):
        if report is None:
            return (None, None)
        r = conn.execute(
            "SELECT value_num, value_raw FROM aviation WHERE report_date=? AND section=? AND item=?",
            (report, section, item),
        ).fetchone()
        return (r["value_num"], r["value_raw"]) if r else (None, None)

    def traffic_stat(section, item, label):
        latest, prev = recent_dates(section)
        num, raw = val(latest, section, item)
        delta = ""
        if prev:
            pnum, _ = val(prev, section, item)
            if num is not None and pnum is not None and num != pnum:
                cls = "chg-up" if num > pnum else "chg-down"
                arr = "▲" if num > pnum else "▼"
                delta = f" <span class='{cls}'>{arr}{_fmt_int(abs(num - pnum))}</span>"
        return f"<div class='stat'><b>{raw or '—'}{delta}</b><span>{label}</span></div>"

    stats = (
        traffic_stat("Domestic traffic", "Departing flights", "Dom · departing flights") +
        traffic_stat("Domestic traffic", "Departing Pax", "Dom · departing pax") +
        traffic_stat("International traffic", "Departing flights", "Int · departing flights") +
        traffic_stat("International traffic", "Departing Pax", "Int · departing pax")
    )
    traffic_date = recent_dates("Domestic traffic")[0]

    # Per-airline table: Load Factor + On-Time Performance (each with own dates)
    plf_latest, plf_prev = recent_dates("Passenger Load Factor")
    otp_latest, otp_prev = recent_dates("On Time Performance")

    def pct_delta(latest, prev, section, a):
        n, _ = val(latest, section, a)
        p, _ = val(prev, section, a)
        if n is not None and p is not None and n != p:
            cls = "chg-up" if n > p else "chg-down"
            return f" <span class='{cls}'>{'▲' if n>p else '▼'}{abs(n-p):.2f}</span>"
        return ""

    airlines = [r["item"] for r in conn.execute(
        "SELECT DISTINCT item FROM aviation WHERE section='Passenger Load Factor' AND report_date=?",
        (plf_latest,),
    )]
    body = []
    for a in airlines:
        _, plf_raw = val(plf_latest, "Passenger Load Factor", a)
        _, otp_raw = val(otp_latest, "On Time Performance", a)
        plf_d = pct_delta(plf_latest, plf_prev, "Passenger Load Factor", a)
        otp_d = pct_delta(otp_latest, otp_prev, "On Time Performance", a)
        body.append(
            f"<tr><td class='slot'>{escape(a)}</td><td>{plf_raw or '—'}{plf_d}</td>"
            f"<td>{otp_raw or '—'}{otp_d}</td></tr>"
        )
    conn.close()

    return (
        "<div class='card aviation'>"
        "<h3>🛫 National aviation activity <span class='muted'>· civilaviation.gov.in</span></h3>"
        f"<div class='muted' style='font-size:12px;margin:-6px 0 8px'>Traffic as of {escape(traffic_date or '—')}</div>"
        f"<div class='stats compact'>{stats}</div>"
        f"<div class='muted' style='font-size:12px;margin:4px 0 6px'>Load factor &amp; on-time as of {escape(plf_latest or '—')}</div>"
        "<table><thead><tr><th>Airline</th><th>Load factor</th><th>On-time %</th></tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table>"
        "<div class='muted' style='font-size:12px;margin-top:8px'>Deltas vs previous published day. "
        "Updated daily by the Ministry of Civil Aviation (each metric shows the prior day).</div></div>"
    )


def render():
    entries_by_sector, capture_dates, target_by, meta = load()
    latest = capture_dates[-1] if capture_dates else None
    generated = dt.datetime.now().strftime("%Y-%m-%d %H:%M")

    n_tracked = sum(len(entries) for groups in entries_by_sector.values() for _, entries in groups)
    stats = f"""
      <div class="stat"><b>{n_tracked}</b><span>Flights tracked</span></div>
      <div class="stat"><b>{meta['n'] or 0:,}</b><span>Rows stored</span></div>
      <div class="stat"><b>{len(capture_dates)}</b><span>Days captured</span></div>
      <div class="stat"><b>{meta['last'] or '—'}</b><span>Latest capture</span></div>"""
    legend = "".join(
        f"<span><i style='background:{HCOLORS.get(h,'#888')}'></i>{h}</span>" for h, _ in config.HORIZONS
    )

    if latest:
        tables = "".join(
            sector_table(s["name"],
                         "Flight" if s.get("mode", "slots") == "all" else "Slot",
                         entries_by_sector.get(s["sector"], []), latest, target_by)
            for s in config.SECTORS
        )
        charts = charts_section(entries_by_sector)
    else:
        tables = "<div class='empty'>No captures yet. Run <code>python3 capture.py</code>.</div>"
        charts = ""
    aviation = aviation_section()

    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Flight Fare Tracker</title>
<style>
  :root {{ --bg:#f7f8fa; --card:#fff; --ink:#1c1e21; --muted:#6b7280; --line:#e5e7eb;
    --alt:#f3f4f6; --h1:#2563eb; --h2:#16a34a; --h3:#db2777; --up:#dc2626; --down:#16a34a; }}
  @media (prefers-color-scheme: dark) {{ :root {{ --bg:#0f1115; --card:#171a21; --ink:#e6e8eb;
    --muted:#9aa2ad; --line:#262b34; --alt:#1e222b; --h1:#60a5fa; --h2:#4ade80; --h3:#f472b6; }} }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--ink);
    font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; }}
  .wrap {{ max-width:1000px; margin:0 auto; padding:24px 20px 60px; }}
  h1 {{ margin:0 0 4px; font-size:24px; }}
  .sub {{ color:var(--muted); font-size:14px; }}
  .stats {{ display:flex; gap:14px; flex-wrap:wrap; margin:18px 0 22px; }}
  .stat {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:12px 16px; min-width:140px; }}
  .stat b {{ display:block; font-size:20px; }}
  .stat span {{ color:var(--muted); font-size:11px; text-transform:uppercase; letter-spacing:.04em; }}
  .downloads {{ display:flex; gap:12px; flex-wrap:wrap; margin:0 0 18px; }}
  .downloads a {{ display:inline-block; background:var(--card); border:1px solid var(--line);
    border-radius:9px; padding:8px 14px; color:var(--h1); text-decoration:none; font-size:13px; font-weight:600; }}
  .downloads a:hover {{ border-color:var(--h1); }}
  .legend {{ display:flex; gap:18px; flex-wrap:wrap; margin-bottom:18px; font-size:13px; color:var(--muted); }}
  .legend i {{ display:inline-block; width:12px; height:12px; border-radius:3px; margin-right:6px; vertical-align:-1px; }}
  .card {{ background:var(--card); border:1px solid var(--line); border-radius:14px; padding:16px 18px; margin-bottom:16px; }}
  .card h3 {{ margin:0 0 12px; font-size:17px; }}
  .aviation {{ border-color:var(--h1); }}
  .stats.compact {{ margin:6px 0 14px; gap:10px; }}
  .stats.compact .stat {{ min-width:120px; padding:10px 14px; }}
  .stats.compact .stat b {{ font-size:16px; }}
  table {{ width:100%; border-collapse:collapse; font-size:13px; }}
  th,td {{ text-align:right; padding:7px 9px; border-bottom:1px solid var(--line); white-space:nowrap; }}
  th:first-child, td:first-child {{ text-align:left; }}
  th {{ color:var(--muted); font-weight:600; vertical-align:bottom; }}
  td.slot {{ text-align:left; }}
  tr.air td {{ background:var(--alt); font-weight:700; text-align:left; letter-spacing:.02em; }}
  td.muted, .muted {{ color:var(--muted); font-weight:400; }}
  .chg-up {{ color:var(--up); }} .chg-down {{ color:var(--down); }}
  .empty {{ color:var(--muted); padding:40px 0; text-align:center; }}
  details.charts {{ margin-top:8px; }}
  details.charts summary {{ cursor:pointer; color:var(--h1); font-size:14px; padding:8px 0; }}
  details.charts h4 {{ margin:16px 0 8px; }}
  .minis {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(240px,1fr)); gap:12px; }}
  .mini {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:8px 8px 2px; }}
  .mini-t {{ font-size:12px; color:var(--muted); margin-bottom:2px; }}
  svg text {{ fill:var(--muted); font-size:9px; }}
  footer {{ color:var(--muted); font-size:12px; margin-top:28px; }}
  code {{ background:var(--line); padding:1px 5px; border-radius:4px; }}
</style></head>
<body><div class="wrap">
  <h1>✈️ Flight Fare Tracker</h1>
  <div class="sub">Metro routes: IndiGo &amp; Air India at 3 popular slots · Non-metro (Delhi–Jaipur, Pune–Bengaluru): every flight, all airlines · booking horizons +1wk &amp; +3wk</div>
  <div class="stats">{stats}</div>
  <div class="downloads">
    <a href="fares.xlsx" download>⬇︎ Download fares (Excel)</a>
    <a href="aviation.xlsx" download>⬇︎ Download aviation stats (Excel)</a>
  </div>
  <div class="legend">Booking horizon: {legend} &nbsp; · &nbsp; each cell shows latest fare and change vs previous capture</div>
  {tables}
  {aviation}
  {charts}
  <footer>Source: SerpAPI / Google Flights. Prices in INR. Metro slots show the nearest fared flight; non-metro routes show every nonstop flight. Generated {generated}.</footer>
</div></body></html>"""

    with open(config.DASHBOARD_PATH, "w") as fh:
        fh.write(html)
    return config.DASHBOARD_PATH


if __name__ == "__main__":
    print("Wrote", render())
