#!/usr/bin/env python3
"""
Daily capture of national aviation metrics from the Ministry of Civil Aviation
dashboard (https://www.civilaviation.gov.in/dashboard).

It publishes, for the previous day:
  * Domestic traffic     - departing/arriving flights & pax, movements, footfalls
  * International traffic - same set
  * Passenger Load Factor - per airline
  * On Time Performance   - per airline

Values are stored in aviation.db in a tidy long format so the history builds up
over time. A plain browser User-Agent is required (the default one is blocked).

NOTE (Nov 2026): MoCA redesigned the site and moved the daily metrics off the
home page onto /dashboard, rebuilt as Bootstrap tab panes. The section/item names
are kept identical to the old schema so the existing aviation.db history continues.
"""

import re
import sqlite3
import datetime as dt

import requests

URL = "https://www.civilaviation.gov.in/dashboard"
AVIATION_DB = "aviation.db"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

# Dashboard tab-pane id -> canonical section name (unchanged from the old schema).
# The page also carries a cumulative "udan" tab; it is not a daily metric, so skip it.
TAB_SECTIONS = [
    ("domestic", "Domestic traffic"),
    ("international", "International traffic"),
    ("otp", "On Time Performance"),
    ("plf", "Passenger Load Factor"),
]
_PANE_IDS = ["domestic", "international", "otp", "plf", "udan"]

# Each metric is a card:
#   <h3/h4 class="my-label">LABEL</h3> <h3 data-once="heading-fix">VALUE</h3>
_CARD = re.compile(
    r'<h[34] class="my-label">\s*(?P<label>.*?)\s*</h[34]>\s*'
    r'<h3 data-once="heading-fix">\s*(?P<value>.*?)\s*</h3>',
    re.S)
# Each pane carries its own report date: <div class="performance-date">...<span>On 13 November 2026</span>
_DATE = re.compile(r'performance-date.*?<span>\s*(?P<d>.*?)\s*</span>', re.S)
_TAG = re.compile(r"<.*?>")


def _clean(s):
    return _TAG.sub("", s).strip()


def _to_num(raw):
    """'3,89,643' -> 389643.0 ; '82.53%' -> 82.53 ; returns (num, unit)."""
    unit = "percent" if "%" in raw else "count"
    cleaned = raw.replace(",", "").replace("%", "").strip()
    try:
        return float(cleaned), unit
    except ValueError:
        return None, unit


def fetch_html():
    r = requests.get(URL, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}, timeout=45)
    r.raise_for_status()
    return r.text


def parse(html):
    """Return list of dicts: {report_date, section, item, value_raw, value_num, unit}.

    Metrics live in Bootstrap tab panes (ids domestic/international/otp/plf/udan);
    each pane has its own 'performance-date' and a set of metric cards.
    """
    pos = {}
    for pid in _PANE_IDS:
        m = re.search(r'id="' + pid + '"', html)
        if m:
            pos[pid] = m.start()
    starts = sorted(pos.values())

    out = []
    for pid, section in TAB_SECTIONS:
        if pid not in pos:
            continue
        start = pos[pid]
        later = [p for p in starts if p > start]           # next pane in DOM order
        seg = html[start:(min(later) if later else len(html))]
        dm = _DATE.search(seg)
        report_date = _clean(dm.group("d")) if dm else ""
        report_date = re.sub(r"^(On|Till)\s+", "", report_date)  # "On 13 November 2026" -> "13 November 2026"
        for m in _CARD.finditer(seg):
            label, raw = _clean(m.group("label")), _clean(m.group("value"))
            num, unit = _to_num(raw)
            out.append({"report_date": report_date, "section": section, "item": label,
                        "value_raw": raw, "value_num": num, "unit": unit})
    return out


def init_db(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS aviation (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            captured_at TEXT NOT NULL,
            capture_date TEXT NOT NULL,
            report_date TEXT,
            section     TEXT NOT NULL,
            item        TEXT NOT NULL,
            value_num   REAL,
            value_raw   TEXT,
            unit        TEXT,
            source      TEXT DEFAULT 'civilaviation.gov.in'
        )
        """
    )
    # One value per (report_date, section, item): survives multiple runs per day
    # and won't duplicate if the site hasn't advanced to a new report date.
    conn.execute(
        """CREATE UNIQUE INDEX IF NOT EXISTS uniq_av
           ON aviation (report_date, section, item)"""
    )
    conn.commit()


def capture():
    """Fetch, parse, and store. Returns number of rows stored (0 on failure)."""
    now = dt.datetime.now()
    try:
        rows = parse(fetch_html())
    except Exception as e:
        print(f"[aviation] capture FAILED: {e}")
        return 0
    if not rows:
        print("[aviation] no rows parsed (site layout may have changed)")
        return 0

    conn = sqlite3.connect(AVIATION_DB)
    init_db(conn)
    stored = 0
    for r in rows:
        before = conn.total_changes
        conn.execute(
            """INSERT OR IGNORE INTO aviation
               (captured_at, capture_date, report_date, section, item, value_num, value_raw, unit)
               VALUES (?,?,?,?,?,?,?,?)""",
            (now.isoformat(timespec="seconds"), now.date().isoformat(),
             r["report_date"], r["section"], r["item"], r["value_num"], r["value_raw"], r["unit"]),
        )
        stored += conn.total_changes - before
    conn.commit()
    report_date = rows[0]["report_date"]
    conn.close()
    print(f"[aviation] report {report_date}: {len(rows)} metrics parsed, {stored} new rows stored.")
    return stored


if __name__ == "__main__":
    capture()
