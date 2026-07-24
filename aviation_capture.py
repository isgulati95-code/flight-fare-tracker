#!/usr/bin/env python3
"""
Daily capture of national aviation metrics from the Ministry of Civil Aviation
home-page dashboard (https://www.civilaviation.gov.in).

It publishes, for the previous day:
  * Domestic traffic     - departing/arriving flights & pax, movements, footfalls
  * International traffic - same set
  * Passenger Load Factor - per airline
  * On Time Performance   - per airline

Values are stored in aviation.db in a tidy long format so the history builds up
over time. A plain browser User-Agent is required (the default one is blocked).
"""

import re
import sqlite3
import datetime as dt

import requests

URL = "https://www.civilaviation.gov.in/"
AVIATION_DB = "aviation.db"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

SECTIONS = ["Domestic traffic", "International traffic",
            "Passenger Load Factor", "On Time Performance"]

_PAIR = re.compile(
    r'field--name-field-label[^>]*>(?P<label>.*?)</div>\s*'
    r'<div class="field field--name-field-counting-number[^>]*>(?P<value>.*?)</div>',
    re.S)
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
    """Return list of dicts: {report_date, section, item, value_raw, value_num, unit}."""
    out = []
    for seg in re.split(r'(?=<div class="card-header)', html):
        m = re.search(r'<span class="eng-title">\s*(.*?)\s*</span>', seg)
        if not m:
            continue
        title = _clean(m.group(1))
        if title not in SECTIONS:
            continue
        dm = re.search(r'<span class="date-widget">\s*(.*?)\s*</span>', seg)
        report_date = _clean(dm.group(1)) if dm else ""
        report_date = re.sub(r"^On\s+", "", report_date)  # "On 23 July 2026" -> "23 July 2026"
        body = seg.split("card-body", 1)[-1]
        for lbl, val in _PAIR.findall(body):
            label, raw = _clean(lbl), _clean(val)
            num, unit = _to_num(raw)
            out.append({"report_date": report_date, "section": title, "item": label,
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
