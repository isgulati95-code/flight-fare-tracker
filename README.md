# Flight Fare Tracker

Tracks daily fares for selected sectors/airlines/flights across several booking
horizons, using **SerpAPI's Google Flights** engine, and renders a dashboard.

## What it captures (trial scope)

- **Sectors:** Delhi→Mumbai, Delhi→Bengaluru
- **Airlines:** IndiGo, Air India
- **Flights:** morning + evening on each sector/airline (8 tracked flights)
- **Booking horizons:** D+1, +1 week, +3 weeks
- One search returns *all* flights for a route+date, so a run costs only
  **6 API calls/day** (2 sectors × 3 horizons) → ~180/month, within the free 250.

Every returned nonstop flight is stored; the 8 target flights are tagged.

## Setup

```bash
pip3 install -r requirements.txt
```

Provide your SerpAPI key one of these ways:
- save it in `serpapi_key.txt` (already done), or
- `export SERPAPI_KEY=your_key`

## Run a capture

```bash
python3 capture.py
```

This queries the API, stores rows in `prices.db`, and rebuilds `dashboard.html`.
Open `dashboard.html` in a browser to view it.

## Schedule it daily at 10 AM (macOS)

Uses `launchd`. Create `~/Library/LaunchAgents/com.mmt.faretracker.plist`
(see `SCHEDULING.md`), then:

```bash
launchctl load ~/Library/LaunchAgents/com.mmt.faretracker.plist
```

## Files

| File | Purpose |
|---|---|
| `config.py` | Sectors, flights, horizons, tolerances — edit to change scope |
| `capture.py` | Daily capture: calls SerpAPI, writes to `prices.db` |
| `render_dashboard.py` | Builds the self-contained `dashboard.html` |
| `prices.db` | SQLite store of every captured flight |
| `dashboard.html` | The dashboard (regenerated each run) |

## Scaling up later

Edit `config.py` — add sectors to `SECTORS`, flights to `TARGETS`, horizons to
`HORIZONS`. Cost = `len(SECTORS) × len(HORIZONS)` API calls per day.
The full 19-sector wishlist ≈ (19 routes × 6 horizons) ≈ 114 calls/day, which
needs a paid SerpAPI plan.
