"""
Configuration for the flight-fare tracker.

Edit this file to change which sectors, flights, and booking horizons are tracked.
One SerpAPI Google Flights call returns EVERY flight for a route+date, so the
number of API calls per run is only  (number of SECTORS) x (number of HORIZONS).
"""

# --- Sectors to search (one API call per sector per horizon) -----------------
# Each search returns all airlines and all departure times for that route/date.
SECTORS = [
    {"sector": "DEL-BOM", "origin": "DEL", "destination": "BOM", "name": "Delhi → Mumbai"},
    {"sector": "DEL-BLR", "origin": "DEL", "destination": "BLR", "name": "Delhi → Bengaluru"},
]

# --- Booking horizons: label -> number of days ahead of the capture date -----
HORIZONS = [
    ("D+1", 1),
    ("+1wk", 7),
    ("+3wk", 21),
]

# --- Airlines to track -------------------------------------------------------
AIRLINES = ["IndiGo", "Air India"]

# --- Time slots across the day -----------------------------------------------
# For each sector x airline we pick the nonstop flight nearest each anchor time,
# giving 5 representative departures spread across the day. Because one search
# already returns every flight, adding slots costs NO extra API calls.
# (label, anchor time HH:MM 24h)
TIME_SLOTS = [
    ("Early",   "06:00"),
    ("Morning", "09:00"),
    ("Midday",  "13:00"),
    ("Evening", "17:00"),
    ("Night",   "21:00"),
]

# A flight may fill a slot only if within this many minutes of the anchor.
SLOT_WINDOW_MIN = 150

# --- Search parameters -------------------------------------------------------
CURRENCY = "INR"
COUNTRY = "in"     # gl
LANGUAGE = "en"    # hl

# --- Files -------------------------------------------------------------------
DB_PATH = "prices.db"
DASHBOARD_PATH = "dashboard.html"
