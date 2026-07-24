# Scheduling the daily 10 AM capture

## Option A — Run it yourself each day (simplest for the trial)

```bash
cd /Users/isg/Desktop/MMT && python3 capture.py
```

Then open `dashboard.html`.

## Option B — Automate on this Mac with launchd (runs at 10:00 daily)

Install the job:

```bash
cp /Users/isg/Desktop/MMT/com.mmt.faretracker.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.mmt.faretracker.plist
```

Check it's registered:

```bash
launchctl list | grep faretracker
```

Run it once now to test (optional):

```bash
launchctl start com.mmt.faretracker
```

Remove it later:

```bash
launchctl unload ~/Library/LaunchAgents/com.mmt.faretracker.plist
rm ~/Library/LaunchAgents/com.mmt.faretracker.plist
```

### Important caveat

launchd only fires when the Mac is **powered on and awake** at 10:00. If the
laptop is asleep or off, the job runs at the next wake — but for a specific
departure-date curve, a missed day is a gap in the data.

For guaranteed daily capture regardless of your laptop, run `capture.py` on an
always-on machine (a cheap cloud VM, or a scheduled GitHub Action). That's the
recommended setup once you decide to go beyond the trial.

## Logs

Output of each run is appended to `capture.log`.
