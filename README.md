# Flight Fare Tracker

Tracks daily fares for selected sectors/airlines/flights across several booking
horizons, using **SerpAPI's Google Flights** engine, and renders a dashboard.

## What it captures

### A. Flight fares (SerpAPI / Google Flights)
- **Sectors:** Delhi→Mumbai, Delhi→Bengaluru, Delhi→Jaipur, Pune→Bengaluru
- **Airlines:** IndiGo & Air India (Delhi–Jaipur and Pune–Bengaluru are IndiGo-only)
- **Time slots:** 3 popular windows — Early morning ~06:30, Morning ~09:00, Evening ~18:30
  (nearest nonstop flight to each anchor)
- **Booking horizons:** +1 week, +3 weeks
- Cost = sectors × horizons = **8 API calls/day** (~240/month, within the free 250).

Every returned nonstop flight is stored in `prices.db`; the dashboard selects the
slots × airlines × horizons at view time (edit `config.py` anytime, no re-capture).

### B. National aviation activity (civilaviation.gov.in)
Scraped daily from the Ministry of Civil Aviation home-page dashboard (shows the
previous day): domestic & international **departing flights and passengers**, plus
per-airline **passenger load factor** and **on-time performance**. Stored in
`aviation.db` as a growing daily history.

### Downloads
Two Excel workbooks are regenerated every run and linked on the dashboard:
- `fares.xlsx` — all raw flight fares + a curated slot view
- `aviation.xlsx` — daily long history + pivot sheets (load factor, traffic)

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

One command does everything: SerpAPI fare capture → aviation scrape → rebuild
`dashboard.html` → refresh `fares.xlsx` and `aviation.xlsx`.
Open `dashboard.html` in a browser to view it.

## Automating it daily (no laptop needed)

See `SCHEDULING.md`. Recommended: **GitHub Actions** runs `capture.py` in the
cloud every day at 10:00 IST and commits the updated data + dashboard back.

## Files

| File | Purpose |
|---|---|
| `config.py` | Sectors, airlines, time slots, horizons — edit to change scope |
| `capture.py` | Daily run: SerpAPI fares + aviation scrape + dashboard + Excel |
| `aviation_capture.py` | Scrapes civilaviation.gov.in daily metrics into `aviation.db` |
| `render_dashboard.py` | Builds the self-contained `dashboard.html` |
| `export_excel.py` | Builds `fares.xlsx` and `aviation.xlsx` |
| `prices.db` / `aviation.db` | SQLite stores (fares / aviation), history grows daily |
| `dashboard.html` | The dashboard (regenerated each run) |
| `.github/workflows/capture.yml` | Cloud scheduler — runs daily at 10:00 IST |

## Scaling up later

Edit `config.py` — add sectors to `SECTORS`, horizons to `HORIZONS`.
Cost = `len(SECTORS) × len(HORIZONS)` API calls per day (currently 4 × 2 = 8).
The full 19-sector wishlist ≈ (19 routes × 6 horizons) ≈ 114 calls/day, which
needs a paid SerpAPI plan.
