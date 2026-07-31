#!/usr/bin/env python3
"""
Build a self-contained, JavaScript-free dashboard.html from prices.db / aviation.db.

Model: month-to-date. Every flight is stored (full history -> Excel); the dashboard
shows up to MAX_PER_AIRLINE_DISPLAY flights per airline per route, spread across the
day. For each shown flight two columns: the month-to-date AVERAGE price, and the
LATEST captured price with its % change vs that average.

Top tiles (all month-to-date for the latest capture's month):
  * Yield change  — median of (latest vs month-avg %) across ALL captured flights,
                    for IndiGo, Air India, and Overall.
  * Load factor   — average for IndiGo, Air India, and All airlines.
  * Daily activity— domestic flights/day, international flights/day, flights captured.
"""

import os
import sqlite3
import datetime as dt
import statistics
from html import escape

import config

AVIATION_DB = "aviation.db"


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def minutes(hhmm):
    if not hhmm or ":" not in hhmm:
        return None
    h, m = hhmm.split(":")[:2]
    try:
        return int(h) * 60 + int(m)
    except ValueError:
        return None


def month_of(date_str):
    return date_str[:7] if date_str else None


def month_label(ym):
    try:
        return dt.datetime.strptime(ym + "-01", "%Y-%m-%d").strftime("%b %Y")
    except (ValueError, TypeError):
        return ym or "—"


def ind(n):
    """Indian digit grouping: 389643 -> '3,89,643'."""
    import re
    n = int(round(n))
    s = str(abs(n))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        head = re.sub(r"(\d)(?=(\d\d)+$)", r"\1,", head)
        s = head + "," + tail
    return ("-" if n < 0 else "") + s


def inr(n):
    return "₹" + ind(n)


def pct_html(pct, good_up=True, suffix="%"):
    """Coloured signed percentage. good_up=False -> up is red (fares/yield)."""
    if pct is None:
        return "<span class='flat'>—</span>"
    if abs(pct) < 0.05:
        return "<span class='flat'>±0" + suffix + "</span>"
    up = pct > 0
    cls = "pos" if (up == good_up) else "neg"
    arr = "▲" if up else "▼"
    return f"<span class='{cls}'>{arr}{abs(pct):.1f}{suffix}</span>"


def flight_stats(pts, month):
    """(avg, last, pct, n) over the given month's non-null prices."""
    mpts = [p for p in pts if p.get("price") is not None and month_of(p["date"]) == month]
    if not mpts:
        return (None, None, None, 0)
    prices = [p["price"] for p in mpts]
    avg = sum(prices) / len(prices)
    last = mpts[-1]["price"]
    pct = (last - avg) / avg * 100 if avg else None
    return (avg, last, pct, len(prices))


# --------------------------------------------------------------------------- #
# load fare data (every flight; full history)
# --------------------------------------------------------------------------- #
def load():
    """Return (flights, capture_dates, meta).

    flights[(sector, airline, fkey)] = {sector, airline, fno, dep, stops, pts:[{date,price}]}
    """
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT capture_date, sector, airline, dep_time, flight_number, price, stops FROM prices"
        ).fetchall()
        meta = conn.execute(
            "SELECT COUNT(*) AS n, MIN(capture_date) AS first, MAX(capture_date) AS last FROM prices"
        ).fetchone()
    except sqlite3.OperationalError:
        conn.close()
        return {}, [], {"n": 0, "first": None, "last": None}
    conn.close()

    sec_names = {s["sector"] for s in config.SECTORS}
    flights, capture_dates = {}, set()
    for r in rows:
        if r["sector"] not in sec_names:
            continue
        capture_dates.add(r["capture_date"])
        fkey = r["flight_number"] or r["dep_time"] or "?"
        key = (r["sector"], r["airline"], fkey)
        f = flights.setdefault(key, {"sector": r["sector"], "airline": r["airline"],
                                     "fno": r["flight_number"], "dep": r["dep_time"],
                                     "stops": r["stops"] or 0, "pts": []})
        f["pts"].append({"date": r["capture_date"], "price": r["price"]})
        if r["dep_time"]:
            f["dep"] = r["dep_time"]
        f["stops"] = r["stops"] or 0
    for f in flights.values():
        f["pts"].sort(key=lambda p: p["date"])
    return flights, sorted(capture_dates), meta


def _spread_pick(items, k):
    """Keep k items spread across the day (nearest to k anchors in 06:00–22:00)."""
    items = sorted(items, key=lambda f: (minutes(f["dep"]) if minutes(f["dep"]) is not None else 9999))
    if len(items) <= k:
        return items
    lo, hi = 6 * 60, 22 * 60
    anchors = [lo + i * (hi - lo) / (k - 1) for i in range(k)]
    chosen, used = [], set()
    for anc in anchors:
        best = None
        for idx, f in enumerate(items):
            if idx in used:
                continue
            fm = minutes(f["dep"]) if minutes(f["dep"]) is not None else 9999
            if best is None or abs(fm - anc) < abs((minutes(items[best]["dep"]) or 9999) - anc):
                best = idx
        if best is not None:
            used.add(best)
            chosen.append(items[best])
    return sorted(chosen, key=lambda f: (minutes(f["dep"]) if minutes(f["dep"]) is not None else 9999))


def display_groups(flights, sector, month):
    """Ordered [(airline, [flight,...])] for a sector, <=N per airline (spread)."""
    by_airline = {}
    for (s, a, _fk), f in flights.items():
        if s != sector:
            continue
        # only show flights present in the current month
        if not any(month_of(p["date"]) == month and p["price"] is not None for p in f["pts"]):
            continue
        by_airline.setdefault(a, []).append(f)
    order = sorted(by_airline, key=lambda a: min((minutes(f["dep"]) or 9999) for f in by_airline[a]))
    out = []
    for a in order:
        picked = _spread_pick(by_airline[a], config.MAX_PER_AIRLINE_DISPLAY)
        out.append((a, picked))
    return out


# --------------------------------------------------------------------------- #
# per-route tables
# --------------------------------------------------------------------------- #
def sector_table(sec, flights, month):
    groups = display_groups(flights, sec["sector"], month)
    badge = "" if sec["scope"] == "domestic" else "<span class='chip'>international</span>"
    if sec.get("max_stops", 0) > 0:
        badge += " <span class='chip alt'>incl. 1-stop</span>"
    body = []
    if not groups:
        body.append("<tr><td colspan='4' class='muted'>No flights captured yet</td></tr>")
    for airline, fl in groups:
        body.append(f"<tr class='air'><td colspan='4'><span class='dot'></span>{escape(airline)}</td></tr>")
        for f in fl:
            avg, last, pct, n = flight_stats(f["pts"], month)
            stops = "<span class='stopbadge'>1 stop</span>" if f["stops"] else ""
            fno = escape(f["fno"] or "—")
            avg_c = inr(avg) if avg is not None else "—"
            last_c = (inr(last) + " " + pct_html(pct, good_up=False)) if last is not None else "—"
            body.append(
                f"<tr><td class='rowlabel'>{fno}{stops}</td>"
                f"<td class='muted num'>{escape(f['dep'] or '')}</td>"
                f"<td class='num'>{avg_c}</td><td class='num'>{last_c}</td></tr>"
            )
    ml = month_label(month)
    return (
        f"<div class='card'><h3>{escape(sec['name'])} {badge}</h3>"
        f"<table><thead><tr><th>Flight</th><th class='num'>Dep</th>"
        f"<th class='num'>Avg · {ml}</th><th class='num'>Latest <span class='hsub'>(vs avg)</span></th>"
        f"</tr></thead><tbody>{''.join(body)}</tbody></table></div>"
    )


# --------------------------------------------------------------------------- #
# aviation (month-to-date per section)
# --------------------------------------------------------------------------- #
def _report_dt(rd):
    try:
        return dt.datetime.strptime(rd.strip(), "%d %B %Y")
    except (ValueError, AttributeError):
        return None


def aviation_summary():
    if not os.path.exists(AVIATION_DB):
        return None
    conn = sqlite3.connect(AVIATION_DB)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT report_date, capture_date, section, item, value_num FROM aviation "
            "WHERE value_num IS NOT NULL"
        ).fetchall()
    except sqlite3.OperationalError:
        conn.close()
        return None
    conn.close()
    if not rows:
        return None

    recency = {}
    for r in rows:
        k = (r["section"], r["report_date"])
        recency[k] = max(recency.get(k, ""), r["capture_date"])
    latest_rd = {}
    for (section, rd), mcd in recency.items():
        if section not in latest_rd or mcd > latest_rd[section][1]:
            latest_rd[section] = (rd, mcd)

    sections = {}
    for section, (rd, _mcd) in latest_rd.items():
        d = _report_dt(rd)
        month = d.strftime("%Y-%m") if d else None
        items = {}
        for r in rows:
            if r["section"] != section:
                continue
            rm = _report_dt(r["report_date"])
            if month is not None and (rm.strftime("%Y-%m") if rm else None) != month:
                continue
            items.setdefault(r["item"], []).append(r["value_num"])
        out = {it: (sum(v) / len(v) if v else None) for it, v in items.items()}
        sections[section] = {"month": month, "month_name": month_label(month), "avg": out}
    return sections


# --------------------------------------------------------------------------- #
# top tiles
# --------------------------------------------------------------------------- #
def _tile(value_html, label, sub=""):
    sub_html = f"<span class='ksub'>{escape(sub)}</span>" if sub else ""
    return f"<div class='kpi'><b>{value_html}</b><span class='klabel'>{escape(label)}</span>{sub_html}</div>"


def yield_tiles(flights, month):
    """Median of (latest vs month-avg %) across ALL captured flights, by airline."""
    by_airline, overall = {}, []
    for (s, a, _fk), f in flights.items():
        _avg, _last, pct, n = flight_stats(f["pts"], month)
        if pct is None:
            continue
        by_airline.setdefault(a, []).append(pct)
        overall.append(pct)

    def tile(name, vals, label):
        if not vals:
            return _tile("<span class='flat'>—</span>", label, "no flights yet")
        med = statistics.median(vals)
        return _tile(pct_html(med, good_up=False), label, f"median · {len(vals)} flights")

    tiles = ""
    for a in config.FEATURED_AIRLINES:
        tiles += tile(a, by_airline.get(a, []), f"{a} yield")
    tiles += tile("Overall", overall, "Overall yield")
    return tiles


def loadfactor_tiles(av, month_name):
    lf = (av or {}).get("Passenger Load Factor", {}).get("avg", {})
    tiles = ""
    for a in config.FEATURED_AIRLINES:
        v = lf.get(a)
        tiles += _tile(f"{v:.1f}%" if v is not None else "<span class='flat'>—</span>",
                       f"{a} load factor", f"avg · {month_name}")
    allvals = [v for v in lf.values() if v is not None]
    allv = sum(allvals) / len(allvals) if allvals else None
    tiles += _tile(f"{allv:.1f}%" if allv is not None else "<span class='flat'>—</span>",
                   "All airlines load factor", f"avg · {month_name}")
    return tiles


def activity_tiles(av, flights, month, month_name):
    dom = (av or {}).get("Domestic traffic", {}).get("avg", {}).get("Departing flights")
    intl = (av or {}).get("International traffic", {}).get("avg", {}).get("Departing flights")
    n_flights = sum(1 for f in flights.values()
                    if any(month_of(p["date"]) == month and p["price"] is not None for p in f["pts"]))
    return (
        _tile(ind(dom) if dom is not None else "<span class='flat'>—</span>",
              "Domestic flights / day", f"avg · {month_name}") +
        _tile(ind(intl) if intl is not None else "<span class='flat'>—</span>",
              "Intl flights / day", f"avg · {month_name}") +
        _tile(str(n_flights), "Flights captured", f"this month")
    )


# --------------------------------------------------------------------------- #
# reusable summaries (for Excel)
# --------------------------------------------------------------------------- #
def fare_summary_rows():
    flights, capture_dates, _meta = load()
    month = month_of(capture_dates[-1]) if capture_dates else None
    name_by = {s["sector"]: s["name"] for s in config.SECTORS}
    scope_by = {s["sector"]: s["scope"] for s in config.SECTORS}
    out = []
    for sec in config.SECTORS:
        for airline, fl in display_groups(flights, sec["sector"], month):
            for f in fl:
                avg, last, pct, n = flight_stats(f["pts"], month)
                out.append({
                    "month": month, "route": name_by.get(sec["sector"], sec["sector"]),
                    "scope": scope_by.get(sec["sector"], ""), "airline": airline,
                    "flight": f["fno"], "dep_time": f["dep"], "stops": f["stops"],
                    "avg_price": round(avg, 2) if avg is not None else None,
                    "last_price": last, "pct_vs_avg": round(pct, 2) if pct is not None else None,
                    "samples": n,
                })
    return out


def aviation_summary_rows():
    av = aviation_summary()
    if not av:
        return []
    out = []
    for section, blk in av.items():
        for item, v in blk["avg"].items():
            out.append({"month": blk["month"], "section": section, "item": item,
                        "avg": round(v, 2) if v is not None else None})
    return out


# --------------------------------------------------------------------------- #
# aviation detail panel
# --------------------------------------------------------------------------- #
def aviation_section(av):
    if not av:
        return ""
    lf = av.get("Passenger Load Factor", {})
    body = []
    for a, v in sorted(lf.get("avg", {}).items()):
        if v is None:
            continue
        bar = min(max(v, 0), 100)
        body.append(f"<tr><td class='rowlabel'>{escape(a)}</td><td class='num'>{v:.1f}%</td>"
                    f"<td class='barcell'><span class='bar'><i style='width:{bar:.0f}%'></i></span></td></tr>")
    lf_name = lf.get("month_name", "—")
    return (
        "<div class='card aviation'>"
        "<h3>National aviation activity <span class='chip'>civilaviation.gov.in</span></h3>"
        f"<div class='note'>Passenger load factor — month-to-date average, {escape(lf_name)}</div>"
        "<table class='lftable'><thead><tr><th>Airline</th><th class='num'>Load factor</th><th></th></tr></thead>"
        f"<tbody>{''.join(body) or '<tr><td colspan=3 class=muted>No data yet</td></tr>'}</tbody></table>"
        "</div>"
    )


# --------------------------------------------------------------------------- #
# render
# --------------------------------------------------------------------------- #
def render():
    flights, capture_dates, meta = load()
    latest = capture_dates[-1] if capture_dates else None
    month = month_of(latest)
    ml = month_label(month)
    av = aviation_summary()
    av_month = (av or {}).get("Domestic traffic", {}).get("month_name", ml)
    generated = dt.datetime.now().strftime("%Y-%m-%d %H:%M")

    latest_disp = "—"
    if latest:
        try:
            latest_disp = dt.datetime.strptime(latest, "%Y-%m-%d").strftime("%d %b %Y")
        except ValueError:
            latest_disp = latest

    if latest:
        tables = "".join(sector_table(sec, flights, month) for sec in config.SECTORS)
    else:
        tables = "<div class='empty'>No captures yet. The first run will populate the dashboard.</div>"

    groups_html = (
        "<div class='tilegroup'><div class='glabel'>Yield change "
        f"<span class='gnote'>median · latest vs {ml} avg · all captured flights</span></div>"
        f"<div class='kpis'>{yield_tiles(flights, month)}</div></div>"
        "<div class='tilegroup'><div class='glabel'>Load factor "
        f"<span class='gnote'>{av_month} average</span></div>"
        f"<div class='kpis'>{loadfactor_tiles(av, av_month)}</div></div>"
        "<div class='tilegroup'><div class='glabel'>Daily activity</div>"
        f"<div class='kpis'>{activity_tiles(av, flights, month, av_month)}</div></div>"
    )

    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Flight Fare Tracker</title>
<style>
  :root {{ color-scheme: light;
    --plane:#f4f5f3; --card:#ffffff; --card2:#fbfbfa; --ink:#0b0b0b; --ink2:#52514e;
    --muted:#898781; --grid:#e8e7e1; --line:#e6e5df; --border:rgba(11,11,11,0.09);
    --accent:#2a78d6; --accent-wash:#eef4fc; --pos:#006300; --neg:#d03b3b;
    --shadow:0 1px 2px rgba(11,11,11,.04), 0 4px 16px rgba(11,11,11,.05); }}
  @media (prefers-color-scheme: dark) {{ :root:where(:not([data-theme="light"])) {{ color-scheme:dark;
    --plane:#0d0d0d; --card:#171716; --card2:#131312; --ink:#fff; --ink2:#c3c2b7;
    --muted:#8f8e86; --grid:#2a2a28; --line:#262623; --border:rgba(255,255,255,0.10);
    --accent:#3987e5; --accent-wash:#14243a; --pos:#0ca30c; --neg:#e66767;
    --shadow:0 1px 2px rgba(0,0,0,.4); }} }}
  :root[data-theme="dark"] {{ color-scheme:dark;
    --plane:#0d0d0d; --card:#171716; --card2:#131312; --ink:#fff; --ink2:#c3c2b7;
    --muted:#8f8e86; --grid:#2a2a28; --line:#262623; --border:rgba(255,255,255,0.10);
    --accent:#3987e5; --accent-wash:#14243a; --pos:#0ca30c; --neg:#e66767;
    --shadow:0 1px 2px rgba(0,0,0,.4); }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--plane); color:var(--ink);
    font:15px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; -webkit-font-smoothing:antialiased; }}
  .wrap {{ max-width:1080px; margin:0 auto; padding:30px 20px 64px; }}
  .num {{ font-variant-numeric:tabular-nums; }}
  h1 {{ margin:0; font-size:27px; letter-spacing:-.02em; }}
  .sub {{ color:var(--ink2); font-size:14.5px; margin:8px 0 0; max-width:820px; }}
  .tilegroup {{ margin:22px 0 6px; }}
  .glabel {{ font-size:12px; font-weight:700; text-transform:uppercase; letter-spacing:.05em;
    color:var(--ink2); margin-bottom:10px; }}
  .glabel .gnote {{ font-weight:500; text-transform:none; letter-spacing:0; color:var(--muted); font-size:11.5px; }}
  .kpis {{ display:grid; grid-template-columns:repeat(3,1fr); gap:12px; }}
  @media (max-width:620px) {{ .kpis {{ grid-template-columns:1fr; }} }}
  .kpi {{ background:var(--card); border:1px solid var(--border); border-radius:14px; padding:15px 16px; box-shadow:var(--shadow); }}
  .kpi b {{ display:block; font-size:23px; letter-spacing:-.01em; line-height:1.1; }}
  .kpi .klabel {{ display:block; color:var(--ink2); font-size:12.5px; margin-top:6px; font-weight:600; }}
  .kpi .ksub {{ display:block; color:var(--muted); font-size:11px; margin-top:2px; }}
  .card {{ background:var(--card); border:1px solid var(--border); border-radius:16px; padding:18px 20px; margin-bottom:16px; box-shadow:var(--shadow); }}
  .card h3 {{ margin:0 0 14px; font-size:16.5px; letter-spacing:-.01em; display:flex; align-items:center; gap:9px; flex-wrap:wrap; }}
  table {{ width:100%; border-collapse:collapse; font-size:13.5px; }}
  th,td {{ text-align:right; padding:9px 10px; border-bottom:1px solid var(--line); white-space:nowrap; }}
  th:first-child, td:first-child {{ text-align:left; }}
  thead th {{ color:var(--muted); font-weight:600; font-size:11.5px; text-transform:uppercase; letter-spacing:.03em; border-bottom:1px solid var(--grid); }}
  th .hsub {{ text-transform:none; letter-spacing:0; font-weight:500; }}
  tbody tr:last-child td {{ border-bottom:none; }}
  td.rowlabel {{ font-weight:600; }}
  tr.air td {{ background:var(--card2); font-weight:700; font-size:12.5px; text-transform:uppercase; letter-spacing:.01em; color:var(--ink2); }}
  tr.air .dot {{ display:inline-block; width:7px; height:7px; border-radius:50%; background:var(--accent); margin-right:8px; vertical-align:1px; }}
  td.muted, .muted {{ color:var(--muted); font-weight:400; }}
  .pos {{ color:var(--pos); font-weight:600; }} .neg {{ color:var(--neg); font-weight:600; }}
  .flat {{ color:var(--muted); }}
  .chip {{ font-size:10.5px; font-weight:600; color:var(--accent); background:var(--accent-wash); padding:3px 9px; border-radius:999px; text-transform:uppercase; letter-spacing:.03em; }}
  .chip.alt {{ color:var(--ink2); background:var(--card2); }}
  .stopbadge {{ font-size:10px; font-weight:600; color:var(--ink2); background:var(--card2); border:1px solid var(--border); padding:1px 6px; border-radius:6px; margin-left:8px; }}
  .empty {{ color:var(--muted); padding:40px 0; text-align:center; }}
  .aviation {{ border-color:var(--accent); }}
  .note {{ color:var(--muted); font-size:11.5px; margin:0 0 8px; text-transform:uppercase; letter-spacing:.03em; }}
  .barcell {{ width:36%; }} .bar {{ display:block; height:7px; background:var(--line); border-radius:99px; overflow:hidden; }}
  .bar i {{ display:block; height:100%; background:var(--accent); border-radius:99px; }}
  .downloads {{ display:flex; gap:12px; flex-wrap:wrap; margin:26px 0 8px; }}
  .downloads a {{ display:inline-flex; align-items:center; gap:8px; background:var(--card); border:1px solid var(--border); border-radius:11px; padding:11px 18px; color:var(--accent); text-decoration:none; font-size:13.5px; font-weight:600; box-shadow:var(--shadow); }}
  .downloads a:hover {{ border-color:var(--accent); }}
  footer {{ color:var(--muted); font-size:12px; margin-top:22px; line-height:1.7; }}
  code {{ background:var(--line); padding:1px 5px; border-radius:4px; }}
</style></head>
<body><div class="wrap">
  <header>
    <h1>✈️ Flight Fare Tracker</h1>
    <p class="sub">8 routes · booking horizon +2 weeks · up to 5 flights per airline per route (spread across the day).
    Prices are the month-to-date average; the coloured figure is the latest capture vs that average.
    <b>Latest capture: {latest_disp}</b> · {len(capture_dates)} day(s) this month.</p>
  </header>

  {groups_html}

  <h2 style="font-size:18px;margin:30px 0 12px;letter-spacing:-.01em">Routes</h2>
  {tables}

  {aviation_section(av)}

  <div class="downloads">
    <a href="fares.xlsx" download>⬇︎ Download fares (Excel)</a>
    <a href="aviation.xlsx" download>⬇︎ Download aviation stats (Excel)</a>
  </div>
  <footer>
    Fares: SerpAPI / Google Flights, in INR. Domestic + Dubai + Singapore are nonstop; London includes up to 1 stop.
    Aviation: Ministry of Civil Aviation daily dashboard. Generated {generated}.
  </footer>
</div></body></html>"""

    with open(config.DASHBOARD_PATH, "w") as fh:
        fh.write(html)
    return config.DASHBOARD_PATH


if __name__ == "__main__":
    print("Wrote", render())
