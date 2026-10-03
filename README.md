# Game Script — NFL analyzer prototype

A static site (`index.html`) that fetches real 2026 NFL data (`nfl_data.json`)
at load time. The data is pulled from nflverse's public datasets by
`build_data.py` — rosters, weekly stats, snap counts, the full schedule with
closing betting lines, multi-season opponent history, and real
defense-allowed-by-position numbers.

## One-time setup (about 10 minutes)

1. **Create a GitHub repo** and push everything in this folder to it
   (`index.html`, `nfl_data.json`, `build_data.py`, `netlify.toml`, and the
   `.github/workflows/` folder — keep that folder structure as-is).

2. **Connect the repo to Netlify**:
   - Netlify → Add new site → Import an existing project → pick this repo
   - Build command: leave blank (there isn't one — it's just static files)
   - Publish directory: `.` (the repo root — `netlify.toml` already sets this)
   - Deploy. Netlify will redeploy automatically every time something is
     pushed to this repo, which is what makes the weekly refresh below work.

3. **Nothing to configure for the weekly refresh** — the GitHub Actions
   workflow in `.github/workflows/refresh-data.yml` is already set up to run
   on its own. GitHub Actions is enabled by default on every repo.

## How the weekly refresh works

Every Tuesday at 8am ET, a GitHub Action:
1. Runs `build_data.py`, which re-pulls rosters, stats, snap counts, and the
   schedule from nflverse and rewrites `nfl_data.json`.
2. If the data actually changed, commits it and pushes.
3. That push triggers Netlify's auto-deploy, so the live site picks up the
   new file within a minute or two — no manual step, ever.

If nothing changed (bye week quirks, no new games), it skips the commit so
you don't get empty "no changes" deploys.

### Running it manually

Go to the repo's **Actions** tab → "Weekly NFL data refresh" → **Run
workflow**. Useful right after you make a code change to `build_data.py`, or
if you want to force a refresh outside the Tuesday schedule.

### Checking it's working

The page footer note always shows the date the data was last generated
(`DATA.generated`). If that date is more than ~8 days old, check the
Actions tab for a failed run — the most common cause is nflverse not having
published a file yet (rare, but the script skips that season gracefully
rather than crashing).

## Local development

```
python3 build_data.py        # rebuilds nfl_data.json using today's date to pick the season
python3 -m http.server 8000  # serve the folder locally
```

Then open `http://localhost:8000`. Opening `index.html` directly as a local
file (`file://...`) will NOT work — browsers block `fetch()` of local JSON
files for security reasons. It has to be served over HTTP, which is also
exactly how Netlify serves it in production.
