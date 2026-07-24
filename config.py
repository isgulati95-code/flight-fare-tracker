"""
Configuration for the flight-fare tracker.

Edit this file to change which sectors, flights, and booking horizons are tracked.
One SerpAPI Google Flights call returns EVERY flight for a route+date, so the
number of API calls per run is only  (number of SECTORS) x (number of HORIZONS).
"""

# --- Sectors to search (one API call per sector per horizon) -----------------
# Each search returns all airlines and all departure times for that route/date.
# Optional per-sector "airlines" overrides the global AIRLINES list below
# (useful where only one carrier flies the route).
# mode:
#   "slots" (default) - metro routes: track IndiGo & Air India at 3 popular slots
#   "all"             - non-metro routes: capture EVERY nonstop flight, ALL airlines
SECTORS = [
    {"sector": "DEL-BOM", "origin": "DEL", "destination": "BOM", "name": "Delhi → Mumbai"},
    {"sector": "DEL-BLR", "origin": "DEL", "destination": "BLR", "name": "Delhi → Bengaluru"},
    {"sector": "DEL-JAI", "origin": "DEL", "destination": "JAI", "name": "Delhi → Jaipur",
     "mode": "all"},
    {"sector": "PNQ-BLR", "origin": "PNQ", "destination": "BLR", "name": "Pune → Bengaluru",
     "mode": "all"},
]

# --- Booking horizons: label -> number of days ahead of the capture date -----
# API calls/day = len(SECTORS) x len(HORIZONS) = 4 x 2 = 8  (~240/month).
HORIZONS = [
    ("+1wk", 7),
    ("+3wk", 21),
]

# --- Airlines to track (default for sectors without a per-sector override) ----
AIRLINES = ["IndiGo", "Air India"]

# --- Time slots across the day -----------------------------------------------
# 3 most-popular departure windows. For each sector x airline we pick the
# nonstop flight nearest each anchor. Adding slots costs NO extra API calls.
# (label, anchor time HH:MM 24h)
TIME_SLOTS = [
    ("Early morning", "06:30"),
    ("Morning",       "09:00"),
    ("Evening",       "18:30"),
]

# A flight may fill a slot only if within this many minutes of the anchor.
SLOT_WINDOW_MIN = 120

# --- Search parameters -------------------------------------------------------
CURRENCY = "INR"
COUNTRY = "in"     # gl
LANGUAGE = "en"    # hl

# --- Files -------------------------------------------------------------------
DB_PATH = "prices.db"
DASHBOARD_PATH = "dashboard.html"
