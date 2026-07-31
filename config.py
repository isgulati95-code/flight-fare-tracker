"""
Configuration for the flight-fare tracker.

Edit this file to change which routes and booking horizon are tracked.
One SerpAPI Google Flights call returns EVERY flight for a route+date, so the
number of API calls per run is  (number of SECTORS) x (number of HORIZONS).
Currently 8 routes x 1 horizon = 8 calls/day (~240/month, within the free 250).
"""

# --- Routes to search --------------------------------------------------------
# scope:     "domestic" or "international" (used only for labelling)
# max_stops: 0 = nonstop only; 1 = also keep one-stop itineraries (e.g. London)
SECTORS = [
    {"sector": "DEL-BOM", "origin": "DEL", "destination": "BOM", "name": "Delhi → Mumbai",       "scope": "domestic",      "max_stops": 0},
    {"sector": "BLR-BOM", "origin": "BLR", "destination": "BOM", "name": "Bengaluru → Mumbai",   "scope": "domestic",      "max_stops": 0},
    {"sector": "DEL-HYD", "origin": "DEL", "destination": "HYD", "name": "Delhi → Hyderabad",     "scope": "domestic",      "max_stops": 0},
    {"sector": "DEL-GOI", "origin": "DEL", "destination": "GOI", "name": "Delhi → Goa",           "scope": "domestic",      "max_stops": 0},
    {"sector": "BOM-MAA", "origin": "BOM", "destination": "MAA", "name": "Mumbai → Chennai",      "scope": "domestic",      "max_stops": 0},
    {"sector": "DEL-DXB", "origin": "DEL", "destination": "DXB", "name": "Delhi → Dubai",         "scope": "international", "max_stops": 0},
    {"sector": "BOM-SIN", "origin": "BOM", "destination": "SIN", "name": "Mumbai → Singapore",    "scope": "international", "max_stops": 0},
    {"sector": "DEL-LHR", "origin": "DEL", "destination": "LHR", "name": "Delhi → London",        "scope": "international", "max_stops": 1},
]

# --- Booking horizon: label -> number of days ahead of the capture date -------
HORIZONS = [
    ("+2wk", 14),
]

# --- Dashboard display -------------------------------------------------------
# Every flight is STORED (full history -> Excel). The dashboard shows at most
# this many flights per airline per route (spread across the day), so it stays
# readable. The yield tiles are still computed over ALL captured flights.
MAX_PER_AIRLINE_DISPLAY = 5

# Airlines that get their own yield / load-factor tiles at the top.
FEATURED_AIRLINES = ["IndiGo", "Air India"]

# --- Search parameters -------------------------------------------------------
CURRENCY = "INR"
COUNTRY = "in"     # gl
LANGUAGE = "en"    # hl

# --- Files -------------------------------------------------------------------
DB_PATH = "prices.db"
DASHBOARD_PATH = "dashboard.html"
