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

import sqlite3
import datetime as dt
from html import escape

import config

HCOLORS = {"D+1": "var(--h1)", "+1wk": "var(--h2)", "+3wk": "var(--h3)"}


def minutes(hhmm):
    if not hhmm or ":" not in hhmm:
        return None
    h, m = hhmm.split(":")[:2]
    return int(h) * 60 + int(m)


def load():
    """Return (series, capture_dates, target_by, meta).

    series[(sector, airline, slot_label, horizon)] = list of
        {date, price, dep_time, flight_number, target_date}  (sorted by date)
    """
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    placeholders = ",".join("?" * len(config.AIRLINES))
    rows = conn.execute(
        f"""
        SELECT capture_date, sector, horizon, target_date, airline,
               dep_time, flight_number, price
        FROM prices
        WHERE price IS NOT NULL AND airline IN ({placeholders})
        """,
        config.AIRLINES,
    ).fetchall()
    meta = conn.execute(
        "SELECT COUNT(*) AS n, MIN(capture_date) AS first, MAX(capture_date) AS last FROM prices"
    ).fetchone()
    conn.close()

    # Group candidate flights per (capture_date, sector, horizon, airline).
    buckets = {}
    target_by = {}  # (capture_date, horizon) -> target_date
    capture_dates = set()
    for r in rows:
        capture_dates.add(r["capture_date"])
        target_by[(r["capture_date"], r["horizon"])] = r["target_date"]
        key = (r["capture_date"], r["sector"], r["horizon"], r["airline"])
        buckets.setdefault(key, []).append(
            {"dep": r["dep_time"], "price": r["price"], "fno": r["flight_number"]}
        )

    # For each bucket pick the flight nearest each time-slot anchor.
    series = {}
    for (cdate, sector, horizon, airline), flights in buckets.items():
        for slot_label, anchor in config.TIME_SLOTS:
            amin = minutes(anchor)
            best, best_d = None, None
            for f in flights:
                fm = minutes(f["dep"])
                if fm is None:
                    continue
                d = abs(fm - amin)
                if d <= config.SLOT_WINDOW_MIN and (best_d is None or d < best_d or
                                                    (d == best_d and f["price"] < best["price"])):
                    best, best_d = f, d
            if best is None:
                continue
            skey = (sector, airline, slot_label, horizon)
            series.setdefault(skey, []).append(
                {
                    "date": cdate,
                    "price": best["price"],
                    "dep_time": best["dep"],
                    "flight_number": best["fno"],
                    "target_date": target_by[(cdate, horizon)],
                }
            )

    for k in series:
        series[k].sort(key=lambda p: p["date"])

    return series, sorted(capture_dates), target_by, meta


def inr(n):
    return "₹" + f"{int(round(n)):,}"


def delta_cell(pts):
    """Latest price + day-over-day change for one series list."""
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


def sector_table(series, sector, sector_name, latest, target_by):
    horizons = [h for h, _ in config.HORIZONS]
    head_cells = "".join(
        f"<th>{h}<br><span class='muted'>{(target_by.get((latest, h)) or '')[5:]}</span></th>"
        for h in horizons
    )
    body = []
    for airline in config.AIRLINES:
        body.append(
            f"<tr class='air'><td colspan='{len(horizons)+2}'>{escape(airline)}</td></tr>"
        )
        for slot_label, anchor in config.TIME_SLOTS:
            # representative departure time at latest capture (prefer earliest horizon w/ data)
            rep_dep = ""
            for h in horizons:
                s = series.get((sector, airline, slot_label, h), [])
                if s and s[-1]["date"] == latest:
                    rep_dep = s[-1]["dep_time"] or ""
                    break
            cells = "".join(
                delta_cell([p for p in series.get((sector, airline, slot_label, h), [])
                            if p["date"] <= latest])
                for h in horizons
            )
            body.append(
                f"<tr><td class='slot'>{slot_label}<br><span class='muted'>~{anchor}</span></td>"
                f"<td class='muted'>{rep_dep}</td>{cells}</tr>"
            )
    return (
        f"<div class='card'><h3>{escape(sector_name)}</h3>"
        f"<table><thead><tr><th>Slot</th><th>Dep</th>{head_cells}</tr></thead>"
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


def charts_section(series):
    horizons = [h for h, _ in config.HORIZONS]
    blocks = []
    for sec in config.SECTORS:
        cells = []
        for airline in config.AIRLINES:
            for slot_label, _ in config.TIME_SLOTS:
                smap = {h: series.get((sec["sector"], airline, slot_label, h), []) for h in horizons}
                smap = {h: v for h, v in smap.items() if v}
                cells.append(
                    f"<div class='mini'><div class='mini-t'>{escape(airline)} · {slot_label}</div>"
                    f"{svg_chart(smap)}</div>"
                )
        blocks.append(f"<h4>{escape(sec['name'])}</h4><div class='minis'>{''.join(cells)}</div>")
    return (
        "<details class='charts'><summary>Show trend charts (fare vs capture date)</summary>"
        + "".join(blocks) + "</details>"
    )


def render():
    series, capture_dates, target_by, meta = load()
    latest = capture_dates[-1] if capture_dates else None
    generated = dt.datetime.now().strftime("%Y-%m-%d %H:%M")

    n_slots = len({(s, a, sl) for (s, a, sl, h) in series})
    stats = f"""
      <div class="stat"><b>{n_slots}</b><span>Flight slots tracked</span></div>
      <div class="stat"><b>{meta['n'] or 0:,}</b><span>Rows stored</span></div>
      <div class="stat"><b>{len(capture_dates)}</b><span>Days captured</span></div>
      <div class="stat"><b>{meta['last'] or '—'}</b><span>Latest capture</span></div>"""
    legend = "".join(
        f"<span><i style='background:{HCOLORS.get(h,'#888')}'></i>{h}</span>" for h, _ in config.HORIZONS
    )

    if latest:
        tables = "".join(
            sector_table(series, s["sector"], s["name"], latest, target_by) for s in config.SECTORS
        )
        charts = charts_section(series)
    else:
        tables = "<div class='empty'>No captures yet. Run <code>python3 capture.py</code>.</div>"
        charts = ""

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
  .legend {{ display:flex; gap:18px; flex-wrap:wrap; margin-bottom:18px; font-size:13px; color:var(--muted); }}
  .legend i {{ display:inline-block; width:12px; height:12px; border-radius:3px; margin-right:6px; vertical-align:-1px; }}
  .card {{ background:var(--card); border:1px solid var(--line); border-radius:14px; padding:16px 18px; margin-bottom:16px; }}
  .card h3 {{ margin:0 0 12px; font-size:17px; }}
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
  <div class="sub">Delhi–Mumbai &amp; Delhi–Bengaluru · IndiGo &amp; Air India · 5 time-slots × 3 booking horizons</div>
  <div class="stats">{stats}</div>
  <div class="legend">Booking horizon: {legend} &nbsp; · &nbsp; each cell shows latest fare and change vs previous capture</div>
  {tables}
  {charts}
  <footer>Source: SerpAPI / Google Flights. Prices in INR, nearest nonstop flight to each slot. Generated {generated}.</footer>
</div></body></html>"""

    with open(config.DASHBOARD_PATH, "w") as fh:
        fh.write(html)
    return config.DASHBOARD_PATH


if __name__ == "__main__":
    print("Wrote", render())
