#!/usr/bin/env python3
"""
Daily flight-fare capture.

For every SECTOR x HORIZON in config.py, this queries SerpAPI's Google Flights
engine once and stores every nonstop flight returned. The dashboard later picks
the 5 time-slots per airline from this data. Then it regenerates the dashboard.

Usage:
    export SERPAPI_KEY=your_key_here      # or put the key in serpapi_key.txt
    python3 capture.py

Run it once a day (see README for scheduling at 10 AM).
"""

import os
import sys
import json
import sqlite3
import datetime as dt

import requests

import config
from render_dashboard import render
from export_excel import build_fares_excel, build_aviation_excel
import aviation_capture

SERPAPI_URL = "https://serpapi.com/search.json"


# --------------------------------------------------------------------------- #
# API key
# --------------------------------------------------------------------------- #
def get_api_key():
    key = os.environ.get("SERPAPI_KEY", "").strip()
    if key:
        return key
    for fname in ("serpapi_key.txt", ".serpapi_key"):
        if os.path.exists(fname):
            with open(fname) as fh:
                k = fh.read().strip()
                if k:
                    return k
    sys.exit(
        "No SerpAPI key found.\n"
        "  Set it with:  export SERPAPI_KEY=your_key\n"
        "  or save it in a file named 'serpapi_key.txt' next to this script."
    )


# --------------------------------------------------------------------------- #
# Database
# --------------------------------------------------------------------------- #
def init_db(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS prices (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            captured_at  TEXT NOT NULL,   -- ISO timestamp of this run
            capture_date TEXT NOT NULL,   -- YYYY-MM-DD of this run
            sector       TEXT NOT NULL,
            origin       TEXT NOT NULL,
            destination  TEXT NOT NULL,
            target_date  TEXT NOT NULL,   -- the flight's departure date
            horizon      TEXT NOT NULL,   -- D+1 / +1wk / +3wk
            airline      TEXT,
            flight_number TEXT,
            dep_time     TEXT,            -- HH:MM
            arr_time     TEXT,            -- HH:MM
            duration_min INTEGER,
            stops        INTEGER,
            price        REAL,
            currency     TEXT,
            tracked      INTEGER DEFAULT 0,
            target_label TEXT,            -- e.g. "IndiGo morning"
            source       TEXT DEFAULT 'SerpAPI/Google Flights'
        )
        """
    )
    # Avoid duplicate rows if the script is run twice in one day.
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uniq_row
        ON prices (capture_date, sector, target_date, airline, flight_number, dep_time)
        """
    )
    conn.commit()


# --------------------------------------------------------------------------- #
# Parsing helpers
# --------------------------------------------------------------------------- #
def _hhmm(timestr):
    """Google Flights time looks like '2024-05-01 09:00' -> return '09:00'."""
    if not timestr:
        return None
    parts = timestr.split(" ")
    return parts[1] if len(parts) == 2 else timestr


def _minutes(hhmm):
    if not hhmm or ":" not in hhmm:
        return None
    h, m = hhmm.split(":")[:2]
    return int(h) * 60 + int(m)


def parse_flights(payload, sector, max_stops=0):
    """Yield dicts for every itinerary with <= max_stops in a SerpAPI response.

    For a multi-leg (one-stop) itinerary the identity is taken from the first
    leg (marketing carrier + flight number + departure time), the arrival from
    the last leg, and the price/duration from the whole itinerary.
    """
    itineraries = (payload.get("best_flights") or []) + (payload.get("other_flights") or [])
    for it in itineraries:
        legs = it.get("flights") or []
        if not legs:
            continue
        stops = len(legs) - 1
        if stops > max_stops:
            continue
        first, last = legs[0], legs[-1]
        yield {
            "airline": first.get("airline"),
            "flight_number": first.get("flight_number"),
            "dep_time": _hhmm((first.get("departure_airport") or {}).get("time")),
            "arr_time": _hhmm((last.get("arrival_airport") or {}).get("time")),
            "duration_min": it.get("total_duration"),
            "stops": stops,
            "price": it.get("price"),
        }


# --------------------------------------------------------------------------- #
# Capture
# --------------------------------------------------------------------------- #
def fetch(api_key, origin, destination, outbound_date):
    params = {
        "engine": "google_flights",
        "departure_id": origin,
        "arrival_id": destination,
        "outbound_date": outbound_date,
        "type": "2",  # one-way
        "currency": config.CURRENCY,
        "gl": config.COUNTRY,
        "hl": config.LANGUAGE,
        "api_key": api_key,
    }
    resp = requests.get(SERPAPI_URL, params=params, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    if data.get("error"):
        raise RuntimeError(f"SerpAPI error: {data['error']}")
    return data


def main():
    api_key = get_api_key()
    now = dt.datetime.now()
    capture_date = now.date().isoformat()
    captured_at = now.isoformat(timespec="seconds")

    conn = sqlite3.connect(config.DB_PATH)
    init_db(conn)

    calls = 0
    rows_inserted = 0

    for sec in config.SECTORS:
        for label, days in config.HORIZONS:
            target_date = (now.date() + dt.timedelta(days=days)).isoformat()
            print(f"[{sec['sector']}] {label}  dep {target_date} ...", end=" ", flush=True)
            try:
                payload = fetch(api_key, sec["origin"], sec["destination"], target_date)
                calls += 1
            except Exception as e:
                print(f"FAILED ({e})")
                continue

            n = 0
            for f in parse_flights(payload, sec["sector"], sec.get("max_stops", 0)):
                try:
                    before = conn.total_changes
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO prices
                        (captured_at, capture_date, sector, origin, destination,
                         target_date, horizon, airline, flight_number, dep_time,
                         arr_time, duration_min, stops, price, currency)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            captured_at, capture_date, sec["sector"],
                            sec["origin"], sec["destination"], target_date, label,
                            f["airline"], f["flight_number"], f["dep_time"],
                            f["arr_time"], f["duration_min"], f["stops"], f["price"],
                            config.CURRENCY,
                        ),
                    )
                    rows_inserted += conn.total_changes - before
                    n += 1
                except sqlite3.Error as e:
                    print(f"(db error: {e})", end=" ")
            conn.commit()
            print(f"{n} flights")

    conn.close()

    print(f"\nDone. {calls} API calls, {rows_inserted} new fare rows stored.")

    # National aviation metrics (separate free source; never blocks fares).
    aviation_capture.capture()

    render()  # rebuild dashboard.html
    build_fares_excel()  # refresh downloadable Excel
    build_aviation_excel()
    print(f"Dashboard updated: {os.path.abspath(config.DASHBOARD_PATH)}")


if __name__ == "__main__":
    main()
