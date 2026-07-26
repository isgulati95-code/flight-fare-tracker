#!/usr/bin/env python3
"""
Build a self-contained, JavaScript-free dashboard.html from prices.db / aviation.db.

Model: month-to-date. For each tracked flight (and each aviation metric) we show
the AVERAGE over the current month's captures, and the change of the LAST capture
vs that month average, in %. As more days are captured the averages get richer,
and it rolls into the next month automatically.

Everything is rendered server-side so it displays in any browser without JS.
"""

import os
import re
import sqlite3
import datetime as dt
from html import escape

import config

# Two booking horizons -> two categorical hues (validated blue / orange).
HCOLORS = {"+1wk": "var(--s1)", "+3wk": "var(--s2)"}
AVIATION_DB = "aviation.db"
LOADFACTOR_KPI_AIRLINES = ["IndiGo", "Air India", "Akasa Air"]


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #
def minutes(hhmm):
    if not hhmm or ":" not in hhmm:
        return None
    h, m = hhmm.split(":")[:2]
    return int(h) * 60 + int(m)


def month_of(date_str):
    return date_str[:7] if date_str else None


def month_label(ym):
    """'2026-07' -> 'Jul 2026'."""
    try:
        return dt.datetime.strptime(ym + "-01", "%Y-%m-%d").strftime("%b %Y")
    except (ValueError, TypeError):
        return ym or "—"


def ind(n):
    """Indian digit grouping: 389643 -> '3,89,643'."""
    n = int(round(n))
    s = str(abs(n))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        head = re.sub(r"(\d)(?=(\d\d)+$)", r"\1,", head)
        s = head + "," + tail
    return ("-" if n < 0 else "") + s


def inr(n):
    return "₹" + ind(n)


def month_agg(pts, month):
    """(avg, last, pct, n) over the given month's non-null prices in pts."""
    mpts = [p for p in pts if p.get("price") is not None and month_of(p["date"]) == month]
    if not mpts:
        allp = [p for p in pts if p.get("price") is not None]
        return (None, (allp[-1]["price"] if allp else None), None, 0)
    prices = [p["price"] for p in mpts]
    avg = sum(prices) / len(prices)
    last = mpts[-1]["price"]
    pct = (last - avg) / avg * 100 if avg else None
    return (avg, last, pct, len(prices))


def delta_html(pct, good_up=True):
    """Coloured % delta. good_up=True -> up is green; False -> up is red (fares)."""
    if pct is None:
        return ""
    if abs(pct) < 0.05:
        return " <span class='flat'>±0%</span>"
    up = pct > 0
    good = (up == good_up)
    cls = "pos" if good else "neg"
    arr = "▲" if up else "▼"
    return f" <span class='{cls}'>{arr}{abs(pct):.1f}%</span>"


# --------------------------------------------------------------------------- #
# fare data loading (per-flight series) — unchanged logic
# --------------------------------------------------------------------------- #
def load():
    """Return (entries_by_sector, capture_dates, target_by, meta)."""
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
    buckets, target_by, capture_dates = {}, {}, set()
    for r in rows:
        if r["sector"] not in sec_cfg:
            continue
        capture_dates.add(r["capture_date"])
        target_by[(r["capture_date"], r["horizon"])] = r["target_date"]
        buckets.setdefault((r["capture_date"], r["sector"], r["horizon"], r["airline"]), []).append(
            {"dep": r["dep_time"], "price": r["price"], "fno": r["flight_number"]}
        )

    series, rowmeta = {}, {}

    def add(sector, airline, rk, horizon, cd, price, dep, fno, meta_row):
        series.setdefault((sector, airline, rk, horizon), []).append(
            {"date": cd, "price": price, "dep_time": dep, "flight_number": fno,
             "target_date": target_by[(cd, horizon)]})
        rowmeta[(sector, airline, rk)] = meta_row

    for (cd, sector, horizon, airline), flights in buckets.items():
        cfg = sec_cfg[sector]
        if cfg.get("mode", "slots") == "all":
            for f in flights:
                rk = ("flight", f["fno"] or f["dep"])
                add(sector, airline, rk, horizon, cd, f["price"], f["dep"], f["fno"],
                    {"label": f["fno"] or f["dep"], "sub": "",
                     "order": minutes(f["dep"]) if minutes(f["dep"]) is not None else 9999,
                     "dep": f["dep"]})
        else:
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
            if not any(any(p["date"] == latest for p in pts) for pts in byh.values()):
                continue
            if mode == "all":
                if not any(any(p["date"] == latest and p["price"] is not None for p in pts)
                           for pts in byh.values()):
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


def fare_month(capture_dates):
    return month_of(capture_dates[-1]) if capture_dates else None


# --------------------------------------------------------------------------- #
# fare tables
# --------------------------------------------------------------------------- #
def _fare_cell(pts, month):
    avg, last, pct, n = month_agg(pts, month)
    if avg is None and last is None:
        return "<td class='muted'>—</td>"
    main = inr(avg) if avg is not None else inr(last)
    title = f"last {inr(last)} · {n} sample(s) this month" if last is not None else ""
    return f"<td class='num' title='{escape(title)}'>{main}{delta_html(pct, good_up=False)}</td>"


def sector_table(sector_name, first_col, groups, month):
    horizons = [h for h, _ in config.HORIZONS]
    ml = month_label(month)
    head = "".join(
        f"<th class='num'>{h}<span class='hsub'>avg · {ml}</span></th>" for h in horizons
    )
    ncols = len(horizons) + 2
    body = []
    for airline, entries in groups:
        body.append(f"<tr class='air'><td colspan='{ncols}'><span class='dot'></span>{escape(airline)}</td></tr>")
        for e in entries:
            first = escape(str(e["label"]))
            if e["sub"]:
                first += f"<span class='rsub'>{escape(e['sub'])}</span>"
            cells = "".join(_fare_cell(e["byh"].get(h, []), month) for h in horizons)
            body.append(
                f"<tr><td class='rowlabel'>{first}</td><td class='muted num'>{escape(e['dep'] or '')}</td>{cells}</tr>"
            )
    if not body:
        body.append(f"<tr><td colspan='{ncols}' class='muted'>No flights captured yet</td></tr>")
    return (
        f"<div class='card'><h3>{escape(sector_name)}</h3>"
        f"<table><thead><tr><th>{first_col}</th><th class='num'>Dep</th>{head}</tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table></div>"
    )


# --------------------------------------------------------------------------- #
# trend charts (raw daily prices)
# --------------------------------------------------------------------------- #
def svg_chart(series_map):
    W, H, PL, PR, PT, PB = 300, 150, 48, 10, 12, 20
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
        parts.append(f'<line x1="{PL}" y1="{yy:.1f}" x2="{W-PR}" y2="{yy:.1f}" stroke="var(--grid)"/>')
        parts.append(f'<text x="{PL-6}" y="{yy+3:.1f}" text-anchor="end">{inr(round(v/100)*100)}</text>')
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
            parts.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="2.8" fill="{col}"/>')
    parts.append("</svg>")
    return "".join(parts)


def charts_section(entries_by_sector):
    horizons = [h for h, _ in config.HORIZONS]
    blocks = []
    for sec in config.SECTORS:
        cells = []
        for airline, entries in entries_by_sector.get(sec["sector"], []):
            for e in entries:
                smap = {h: [p for p in e["byh"].get(h, []) if p.get("price") is not None] for h in horizons}
                smap = {h: v for h, v in smap.items() if v}
                if not smap:
                    continue
                cells.append(
                    f"<div class='mini'><div class='mini-t'>{escape(airline)} · {escape(str(e['label']))}</div>"
                    f"{svg_chart(smap)}</div>"
                )
        if cells:
            blocks.append(f"<h4>{escape(sec['name'])}</h4><div class='minis'>{''.join(cells)}</div>")
    legend = "".join(
        f"<span class='lg'><i style='background:{HCOLORS[h]}'></i>{h}</span>" for h, _ in config.HORIZONS
    )
    return (
        "<details class='charts'><summary>Trend charts — fare vs capture date</summary>"
        f"<div class='legend'>{legend}</div>" + "".join(blocks) + "</details>"
    )


# --------------------------------------------------------------------------- #
# aviation aggregation (month-to-date per section)
# --------------------------------------------------------------------------- #
def _report_dt(rd):
    try:
        return dt.datetime.strptime(rd.strip(), "%d %B %Y")
    except (ValueError, AttributeError):
        return None


def aviation_summary():
    """Per-section month-to-date aggregation, or None if no aviation data."""
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

    # latest report_date per section (by capture recency)
    latest_rd, recency = {}, {}
    for r in rows:
        key = (r["section"], r["report_date"])
        recency[key] = max(recency.get(key, ""), r["capture_date"])
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
            rmonth = _report_dt(r["report_date"])
            rmonth = rmonth.strftime("%Y-%m") if rmonth else None
            if month is not None and rmonth != month:
                continue
            items.setdefault(r["item"], {"vals": [], "last": None})
            items[r["item"]]["vals"].append(r["value_num"])
            if r["report_date"] == rd:
                items[r["item"]]["last"] = r["value_num"]
        out = {}
        for item, v in items.items():
            avg = sum(v["vals"]) / len(v["vals"]) if v["vals"] else None
            last = v["last"] if v["last"] is not None else (v["vals"][-1] if v["vals"] else None)
            pct = (last - avg) / avg * 100 if (avg and last is not None) else None
            out[item] = {"avg": avg, "last": last, "pct": pct, "n": len(v["vals"])}
        sections[section] = {"report_date": rd, "month": month,
                             "month_name": month_label(month), "items": out}
    return sections


def aviation_section(av):
    if not av:
        return ""

    def tile(section, item, label):
        it = av.get(section, {}).get("items", {}).get(item)
        if not it or it["avg"] is None:
            return f"<div class='stat'><b class='muted'>—</b><span>{label}</span></div>"
        return (f"<div class='stat'><b>{ind(it['avg'])}{delta_html(it['pct'], good_up=True)}</b>"
                f"<span>{label}</span></div>")

    traffic_month = av.get("Domestic traffic", {}).get("month_name", "—")
    tiles = (
        tile("Domestic traffic", "Departing flights", "Dom · departing flights") +
        tile("Domestic traffic", "Departing Pax", "Dom · departing pax") +
        tile("International traffic", "Departing flights", "Int · departing flights") +
        tile("International traffic", "Departing Pax", "Int · departing pax")
    )

    lf = av.get("Passenger Load Factor", {})
    lf_month = lf.get("month_name", "—")
    body = []
    for a, it in sorted(lf.get("items", {}).items()):
        if it["avg"] is None:
            continue
        bar = min(max(it["avg"], 0), 100)
        body.append(
            f"<tr><td class='rowlabel'>{escape(a)}</td>"
            f"<td class='num'>{it['avg']:.1f}%{delta_html(it['pct'], good_up=True)}</td>"
            f"<td class='barcell'><span class='bar'><i style='width:{bar:.0f}%'></i></span></td></tr>"
        )

    return (
        "<div class='card aviation'>"
        "<h3>National aviation activity <span class='chip'>civilaviation.gov.in</span></h3>"
        f"<div class='note'>Traffic — month-to-date average, {escape(traffic_month)}</div>"
        f"<div class='stats compact'>{tiles}</div>"
        f"<div class='note'>Passenger load factor — month-to-date average, {escape(lf_month)}</div>"
        "<table class='lftable'><thead><tr><th>Airline</th><th class='num'>Load factor</th><th></th></tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table>"
        "<div class='note'>Deltas compare the latest published day with the month-to-date average.</div>"
        "</div>"
    )


# --------------------------------------------------------------------------- #
# reusable summaries (also used by export_excel)
# --------------------------------------------------------------------------- #
def fare_summary_rows():
    """Flat rows mirroring the dashboard fare tables (month avg / last / %)."""
    entries_by_sector, capture_dates, _tb, _meta = load()
    month = fare_month(capture_dates)
    name_by = {s["sector"]: s["name"] for s in config.SECTORS}
    out = []
    for sector, groups in entries_by_sector.items():
        for airline, entries in groups:
            for e in entries:
                for h, _ in config.HORIZONS:
                    avg, last, pct, n = month_agg(e["byh"].get(h, []), month)
                    if avg is None and last is None:
                        continue
                    out.append({
                        "month": month, "sector": name_by.get(sector, sector), "airline": airline,
                        "flight": e["label"], "dep_time": e["dep"], "horizon": h,
                        "avg_price": round(avg, 2) if avg is not None else None,
                        "last_price": last, "pct_change": round(pct, 2) if pct is not None else None,
                        "samples": n,
                    })
    return out


def aviation_summary_rows():
    av = aviation_summary()
    if not av:
        return []
    out = []
    for section, blk in av.items():
        for item, it in blk["items"].items():
            out.append({
                "month": blk["month"], "section": section, "item": item,
                "avg": round(it["avg"], 2) if it["avg"] is not None else None,
                "last": it["last"],
                "pct_change": round(it["pct"], 2) if it["pct"] is not None else None,
                "samples": it["n"],
            })
    return out


# --------------------------------------------------------------------------- #
# top KPIs
# --------------------------------------------------------------------------- #
def _kpi(value, label, sub="", accent=False, cls=""):
    sub_html = f"<span class='ksub'>{escape(sub)}</span>" if sub else ""
    return (f"<div class='kpi{' accent' if accent else ''}'>"
            f"<b class='{cls}'>{value}</b><span class='klabel'>{escape(label)}</span>{sub_html}</div>")


def render():
    entries_by_sector, capture_dates, target_by, meta = load()
    latest = capture_dates[-1] if capture_dates else None
    month = fare_month(capture_dates)
    ml = month_label(month)
    generated = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    av = aviation_summary()

    n_flights = sum(len(entries) for groups in entries_by_sector.values() for _, entries in groups)

    # overall fare change %: mean of per-fare (last vs month-avg) %
    pcts = []
    for groups in entries_by_sector.values():
        for _a, entries in groups:
            for e in entries:
                for h, _ in config.HORIZONS:
                    _avg, _last, pct, _n = month_agg(e["byh"].get(h, []), month)
                    if pct is not None:
                        pcts.append(pct)
    overall = sum(pcts) / len(pcts) if pcts else None

    # aviation-derived KPIs
    def av_item(section, item):
        return (av or {}).get(section, {}).get("items", {}).get(item, {})
    lf_vals = [av_item("Passenger Load Factor", a).get("avg")
               for a in LOADFACTOR_KPI_AIRLINES]
    lf_vals = [v for v in lf_vals if v is not None]
    lf_avg = sum(lf_vals) / len(lf_vals) if lf_vals else None
    dom = av_item("Domestic traffic", "Departing flights").get("avg")
    intl = av_item("International traffic", "Departing flights").get("avg")
    av_month = (av or {}).get("Domestic traffic", {}).get("month_name", ml)

    latest_disp = "—"
    if latest:
        try:
            latest_disp = dt.datetime.strptime(latest, "%Y-%m-%d").strftime("%d %b %Y")
        except ValueError:
            latest_disp = latest

    overall_val = "—"
    overall_cls = ""
    if overall is not None:
        arr = "▲" if overall > 0 else ("▼" if overall < 0 else "")
        overall_cls = "neg" if overall > 0.05 else ("pos" if overall < -0.05 else "flat")
        overall_val = f"{arr}{abs(overall):.1f}%"

    kpis = "".join([
        _kpi(overall_val, "Fare vs month avg", f"all sectors · {ml}", accent=True, cls=overall_cls),
        _kpi(f"{lf_avg:.1f}%" if lf_avg is not None else "—", "Avg load factor", "IndiGo · Air India · Akasa"),
        _kpi(ind(dom) if dom is not None else "—", "Domestic flights / day", f"avg · {av_month}"),
        _kpi(ind(intl) if intl is not None else "—", "Intl flights / day", f"avg · {av_month}"),
        _kpi(str(n_flights), "Flights captured", ""),
        _kpi(str(len(capture_dates)), "Days captured", ""),
        _kpi(latest_disp, "Latest capture", ""),
    ])

    if latest:
        tables = "".join(
            sector_table(s["name"], "Flight" if s.get("mode", "slots") == "all" else "Slot",
                         entries_by_sector.get(s["sector"], []), month)
            for s in config.SECTORS
        )
        charts = charts_section(entries_by_sector)
    else:
        tables = "<div class='empty'>No captures yet. Run <code>python3 capture.py</code>.</div>"
        charts = ""

    aviation = aviation_section(av)

    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Flight Fare Tracker</title>
<style>
  :root {{
    color-scheme: light;
    --plane:#f4f5f3; --card:#ffffff; --card2:#fbfbfa;
    --ink:#0b0b0b; --ink2:#52514e; --muted:#898781;
    --grid:#e8e7e1; --line:#e6e5df; --border:rgba(11,11,11,0.09);
    --s1:#2a78d6; --s2:#eb6834; --accent:#2a78d6; --accent-wash:#eef4fc;
    --pos:#006300; --neg:#d03b3b;
    --shadow:0 1px 2px rgba(11,11,11,.04), 0 4px 16px rgba(11,11,11,.05);
  }}
  @media (prefers-color-scheme: dark) {{
    :root:where(:not([data-theme="light"])) {{
      color-scheme: dark;
      --plane:#0d0d0d; --card:#171716; --card2:#131312;
      --ink:#ffffff; --ink2:#c3c2b7; --muted:#8f8e86;
      --grid:#2a2a28; --line:#262623; --border:rgba(255,255,255,0.10);
      --s1:#3987e5; --s2:#d95926; --accent:#3987e5; --accent-wash:#14243a;
      --pos:#0ca30c; --neg:#e66767;
      --shadow:0 1px 2px rgba(0,0,0,.4);
    }}
  }}
  :root[data-theme="dark"] {{
    color-scheme: dark;
    --plane:#0d0d0d; --card:#171716; --card2:#131312;
    --ink:#ffffff; --ink2:#c3c2b7; --muted:#8f8e86;
    --grid:#2a2a28; --line:#262623; --border:rgba(255,255,255,0.10);
    --s1:#3987e5; --s2:#d95926; --accent:#3987e5; --accent-wash:#14243a;
    --pos:#0ca30c; --neg:#e66767;
    --shadow:0 1px 2px rgba(0,0,0,.4);
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--plane); color:var(--ink);
    font:15px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
    -webkit-font-smoothing:antialiased; }}
  .wrap {{ max-width:1080px; margin:0 auto; padding:30px 20px 64px; }}
  .num {{ font-variant-numeric:tabular-nums; }}

  header.hero {{ margin-bottom:26px; }}
  h1 {{ margin:0; font-size:27px; letter-spacing:-.02em; display:flex; align-items:center; gap:10px; }}
  .sub {{ color:var(--ink2); font-size:14.5px; margin:8px 0 0; max-width:760px; }}

  .kpis {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(158px,1fr)); gap:12px; margin:22px 0 30px; }}
  .kpi {{ background:var(--card); border:1px solid var(--border); border-radius:14px;
    padding:15px 16px; box-shadow:var(--shadow); }}
  .kpi.accent {{ background:var(--accent-wash); border-color:transparent; }}
  .kpi b {{ display:block; font-size:23px; letter-spacing:-.01em; line-height:1.1; }}
  .kpi .klabel {{ display:block; color:var(--ink2); font-size:12px; margin-top:6px; font-weight:600; }}
  .kpi .ksub {{ display:block; color:var(--muted); font-size:11px; margin-top:2px; }}

  .card {{ background:var(--card); border:1px solid var(--border); border-radius:16px;
    padding:18px 20px; margin-bottom:16px; box-shadow:var(--shadow); }}
  .card h3 {{ margin:0 0 14px; font-size:16.5px; letter-spacing:-.01em; display:flex;
    align-items:center; gap:9px; flex-wrap:wrap; }}
  table {{ width:100%; border-collapse:collapse; font-size:13.5px; }}
  th,td {{ text-align:right; padding:9px 10px; border-bottom:1px solid var(--line); white-space:nowrap; }}
  th:first-child, td:first-child {{ text-align:left; }}
  thead th {{ color:var(--muted); font-weight:600; font-size:11.5px; text-transform:uppercase;
    letter-spacing:.03em; vertical-align:bottom; border-bottom:1px solid var(--grid); }}
  th .hsub {{ display:block; font-weight:500; text-transform:none; letter-spacing:0; color:var(--muted); font-size:10.5px; }}
  tbody tr:last-child td {{ border-bottom:none; }}
  td.rowlabel {{ font-weight:600; }}
  td .rsub {{ color:var(--muted); font-weight:400; margin-left:6px; font-size:12px; }}
  tr.air td {{ background:var(--card2); font-weight:700; font-size:12.5px; letter-spacing:.01em;
    text-transform:uppercase; color:var(--ink2); }}
  tr.air .dot {{ display:inline-block; width:7px; height:7px; border-radius:50%; background:var(--accent);
    margin-right:8px; vertical-align:1px; }}
  td.muted, .muted {{ color:var(--muted); font-weight:400; }}
  .pos {{ color:var(--pos); font-weight:600; font-size:12px; }}
  .neg {{ color:var(--neg); font-weight:600; font-size:12px; }}
  .flat {{ color:var(--muted); font-size:12px; }}
  .empty {{ color:var(--muted); padding:40px 0; text-align:center; }}

  .aviation {{ border-color:var(--accent); border-width:1px; }}
  .chip {{ font-size:11px; font-weight:600; color:var(--accent); background:var(--accent-wash);
    padding:3px 9px; border-radius:999px; }}
  .note {{ color:var(--muted); font-size:11.5px; margin:12px 0 8px; text-transform:uppercase; letter-spacing:.03em; }}
  .note:first-of-type {{ margin-top:0; }}
  .stats.compact {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:10px; margin:0; }}
  .stat {{ background:var(--card2); border:1px solid var(--border); border-radius:12px; padding:12px 14px; }}
  .stat b {{ display:block; font-size:19px; letter-spacing:-.01em; }}
  .stat span {{ color:var(--muted); font-size:11px; margin-top:3px; display:block; }}
  .lftable td {{ vertical-align:middle; }}
  .barcell {{ width:34%; }}
  .bar {{ display:block; height:7px; background:var(--line); border-radius:99px; overflow:hidden; }}
  .bar i {{ display:block; height:100%; background:var(--accent); border-radius:99px; }}

  details.charts {{ background:var(--card); border:1px solid var(--border); border-radius:16px;
    padding:6px 20px; margin-bottom:16px; box-shadow:var(--shadow); }}
  details.charts summary {{ cursor:pointer; color:var(--accent); font-weight:600; font-size:14px; padding:12px 0; }}
  details.charts h4 {{ margin:14px 0 8px; font-size:14px; }}
  .legend {{ display:flex; gap:16px; margin:8px 0 4px; font-size:12px; color:var(--ink2); }}
  .legend .lg i {{ display:inline-block; width:11px; height:11px; border-radius:3px; margin-right:6px; vertical-align:-1px; }}
  .minis {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(240px,1fr)); gap:12px; padding-bottom:8px; }}
  .mini {{ background:var(--card2); border:1px solid var(--border); border-radius:12px; padding:9px 10px 2px; }}
  .mini-t {{ font-size:11.5px; color:var(--muted); margin-bottom:2px; }}
  svg text {{ fill:var(--muted); font-size:9px; font-variant-numeric:tabular-nums; }}

  .downloads {{ display:flex; gap:12px; flex-wrap:wrap; margin:26px 0 8px; }}
  .downloads a {{ display:inline-flex; align-items:center; gap:8px; background:var(--card);
    border:1px solid var(--border); border-radius:11px; padding:11px 18px; color:var(--accent);
    text-decoration:none; font-size:13.5px; font-weight:600; box-shadow:var(--shadow); }}
  .downloads a:hover {{ border-color:var(--accent); }}
  footer {{ color:var(--muted); font-size:12px; margin-top:22px; line-height:1.7; }}
  code {{ background:var(--line); padding:1px 5px; border-radius:4px; }}
</style></head>
<body><div class="wrap">
  <header class="hero">
    <h1>✈️ Flight Fare Tracker</h1>
    <p class="sub">Captures Delhi–Mumbai, Delhi–Bengaluru, Delhi–Jaipur and Pune–Bengaluru across two booking horizons (+1 week and +3 weeks). Figures are the month-to-date average; the coloured delta is the latest capture vs that average.</p>
  </header>

  <section class="kpis">{kpis}</section>

  {tables}
  {aviation}
  {charts}

  <div class="downloads">
    <a href="fares.xlsx" download>⬇︎ Download fares (Excel)</a>
    <a href="aviation.xlsx" download>⬇︎ Download aviation stats (Excel)</a>
  </div>
  <footer>
    Fares: SerpAPI / Google Flights, in INR. Metro routes show three popular slots per airline;
    non-metro routes show individual flights across all airlines.
    Aviation: Ministry of Civil Aviation daily dashboard.<br>
    Generated {generated}.
  </footer>
</div></body></html>"""

    with open(config.DASHBOARD_PATH, "w") as fh:
        fh.write(html)
    return config.DASHBOARD_PATH


if __name__ == "__main__":
    print("Wrote", render())
