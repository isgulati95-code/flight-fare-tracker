# Running the capture automatically every day

Goal: capture fares daily at 10 AM **without depending on your laptop being awake.**

## ✅ Recommended: GitHub Actions (free, runs in the cloud)

Everything is already prepared in this repo:
- `.github/workflows/capture.yml` runs `capture.py` daily at **10:00 IST**
  (04:30 UTC) and commits the updated `prices.db` + `dashboard.html` back.
- The API key is passed in as an encrypted secret — it is **never** in the code.

### One-time setup (~5 minutes)

1. **Create a new GitHub repo** (private is fine), e.g. `flight-fare-tracker`.
   Do *not* add a README/.gitignore — this folder already has them.

2. **Add your SerpAPI key as a secret**
   Repo → **Settings → Secrets and variables → Actions → New repository secret**
   - Name: `SERPAPI_KEY`
   - Value: your SerpAPI private key

3. **Allow Actions to commit back**
   Repo → **Settings → Actions → General → Workflow permissions** →
   select **Read and write permissions** → Save.

4. **Push this project** (run in this folder):
   ```bash
   cd /Users/isg/Desktop/MMT
   git remote add origin https://github.com/<your-username>/flight-fare-tracker.git
   git branch -M main
   git push -u origin main
   ```

5. **Test it now** (don't wait for 10 AM)
   Repo → **Actions → "Daily fare capture" → Run workflow**.
   After ~1 min it should commit a new capture. Check the commit history.

### See the dashboard as a web page (optional)

Repo → **Settings → Pages → Build and deployment → Deploy from a branch** →
Branch `main`, folder `/ (root)` → Save.
Your dashboard will be live at:
`https://<your-username>.github.io/flight-fare-tracker/`
(refreshes automatically after each daily run.)

### Notes
- GitHub sometimes delays scheduled runs by 5–15 min under load — fine for a
  daily fare snapshot.
- Every run costs 6 SerpAPI calls (~180/month) — within the free 250 tier.

---

## Alternative: local only (no GitHub) — less reliable

`launchd` can run it at 10 AM, but **only while the Mac is awake**. See the
`com.mmt.faretracker.plist` in this folder:

```bash
cp com.mmt.faretracker.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.mmt.faretracker.plist
```

If the laptop is asleep/off at 10 AM, that day is missed — which is why the
cloud option above is recommended for a clean daily fare curve.

## Run manually anytime

```bash
cd /Users/isg/Desktop/MMT && python3 capture.py
```
