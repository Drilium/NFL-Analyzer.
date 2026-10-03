#!/usr/bin/env python3
"""
NFL analyzer data pipeline.
Pulls current-season rosters, weekly player stats, snap counts, and the
season schedule (incl. closing betting lines) from nflverse's public
GitHub release assets, and builds one compact JSON file that the
prototype site embeds directly (no server, no API key needed).

Run this weekly during the season (e.g. Tuesday mornings after MNF)
to refresh the data. Usage:
    python3 build_data.py [season]
Defaults to the current season inferred from today's date.
"""
import csv, json, sys, io, urllib.request
from collections import defaultdict
from datetime import date

BASE = "https://github.com/nflverse/nflverse-data/releases/download"

def fetch_csv(path):
    url = f"{BASE}/{path}"
    req = urllib.request.Request(url, headers={"User-Agent": "nfl-analyzer-pipeline/1.0"})
    with urllib.request.urlopen(req) as r:
        data = r.read().decode("utf-8", errors="replace")
    return list(csv.DictReader(io.StringIO(data)))

def season_for_today():
    t = date.today()
    return t.year if t.month >= 3 else t.year - 1

def num(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default

# Position -> (season stat keys -> short output keys), and the single
# metric used for the per-game bar chart on that position's player page.
POS_STATS = {
    "QB": {"chart": "passing_yards", "fields": {
        "attempts": "att", "completions": "cmp", "passing_yards": "pyd",
        "passing_tds": "ptd", "passing_interceptions": "int",
        "passing_epa": "pepa", "rushing_yards": "ryd", "carries": "car"}},
    "RB": {"chart": "rushing_yards", "fields": {
        "carries": "car", "rushing_yards": "ryd", "rushing_tds": "rtd",
        "targets": "tgt", "receptions": "rec", "receiving_yards": "recyd"}},
    "WR": {"chart": "receiving_yards", "fields": {
        "targets": "tgt", "receptions": "rec", "receiving_yards": "recyd",
        "receiving_tds": "rectd", "target_share": "tshr"}},
    "TE": {"chart": "receiving_yards", "fields": {
        "targets": "tgt", "receptions": "rec", "receiving_yards": "recyd",
        "receiving_tds": "rectd", "target_share": "tshr"}},
    "DB": {"chart": "tackles", "fields": {}},
    "LB": {"chart": "tackles", "fields": {}},
    "DL": {"chart": "tackles", "fields": {}},
}
DEF_POS = {"DB", "LB", "DL"}

# How many prior full seasons to pull for "vs this opponent" history and
# for the real defense-allowed-by-position numbers. Keep this small —
# each extra season is another multi-MB download.
HIST_SEASONS_BACK = 2

def fetch_season_stats(season):
    """Fetch one season's weekly stats file; return [] if not published yet."""
    try:
        return fetch_csv(f"stats_player/stats_player_week_{season}.csv")
    except Exception as e:
        print(f"  (skipping {season}: {e})")
        return []

def build(season):
    print(f"Fetching roster_{season}.csv ...")
    roster_rows = fetch_csv(f"rosters/roster_{season}.csv")
    print(f"Fetching stats_player_week_{season}.csv ...")
    stat_rows = fetch_csv(f"stats_player/stats_player_week_{season}.csv")
    print(f"Fetching snap_counts_{season}.csv ...")
    snap_rows = fetch_csv(f"snap_counts/snap_counts_{season}.csv")
    print("Fetching games.csv (full schedule + closing lines) ...")
    game_rows = fetch_csv("schedules/games.csv")

    hist_seasons = list(range(season - HIST_SEASONS_BACK, season))
    hist_stat_rows = {}
    for hs in hist_seasons:
        print(f"Fetching stats_player_week_{hs}.csv (history) ...")
        hist_stat_rows[hs] = fetch_season_stats(hs)

    roster = {}
    for row in roster_rows:
        if row["status"] != "ACT" or not row["gsis_id"]:
            continue
        roster[row["gsis_id"]] = {
            "id": row["gsis_id"], "n": row["full_name"], "t": row["team"],
            "p": row["position"], "j": row["jersey_number"] or None,
            "col": row["college"] or None, "x": int(row["years_exp"] or 0),
        }

    agg = defaultdict(lambda: defaultdict(float))
    games_played = defaultdict(int)
    weekly = defaultdict(list)
    for row in stat_rows:
        if row["season_type"] != "REG":
            continue
        pid = row["player_id"]
        pos = roster.get(pid, {}).get("p")
        games_played[pid] += 1
        tkl = num(row.get("def_tackles_solo")) + num(row.get("def_tackles_with_assist"))
        agg[pid]["tackles"] += tkl
        agg[pid]["sacks"] = agg[pid].get("sacks", 0) + num(row.get("def_sacks"))
        agg[pid]["def_int"] = agg[pid].get("def_int", 0) + num(row.get("def_interceptions"))
        agg[pid]["pd"] = agg[pid].get("pd", 0) + num(row.get("def_pass_defended"))
        agg[pid]["fp"] = agg[pid].get("fp", 0) + num(row.get("fantasy_points_ppr"))
        wk_entry = {"w": int(row["week"]), "opp": row["opponent_team"], "tkl": tkl}
        spec = POS_STATS.get(pos)
        if spec:
            for k in spec["fields"]:
                v = num(row.get(k))
                agg[pid][k] += v
                wk_entry[k] = v
        # keep the chart-relevant raw fields for every player regardless of spec, for weekly display
        for k in ("passing_yards", "rushing_yards", "receiving_yards"):
            wk_entry.setdefault(k, num(row.get(k)))
        weekly[pid].append(wk_entry)

    snaps_by_key = defaultdict(list)
    for row in snap_rows:
        key = (row["player"].strip(), row["team"].strip())
        snaps_by_key[key].append(num(row.get("offense_pct")) + num(row.get("defense_pct")))

    players = []
    for pid, r in roster.items():
        entry = dict(r)
        g = games_played.get(pid, 0)
        entry["g"] = g
        sk = snaps_by_key.get((r["n"], r["t"]))
        entry["sn"] = round(sum(sk) / len(sk) * 100, 1) if sk else None
        if g > 0:
            a = agg[pid]
            spec = POS_STATS.get(r["p"])
            szn = {}
            if spec:
                for full, short in spec["fields"].items():
                    szn[short] = round(a.get(full, 0) / g, 2)
            if r["p"] in DEF_POS:
                szn["tkl"] = round(a["tackles"] / g, 1)
                szn["sacks"] = round(a.get("sacks", 0), 1)
                szn["int"] = int(a.get("def_int", 0))
                szn["pd"] = int(a.get("pd", 0))
            szn["fp"] = round(a.get("fp", 0) / g, 1)
            entry["ss"] = szn
            chart_key = spec["chart"] if spec else "tkl"
            wk_field = {"passing_yards": "passing_yards", "rushing_yards": "rushing_yards",
                        "receiving_yards": "receiving_yards", "tackles": "tkl"}.get(chart_key, "tkl")
            entry["wk"] = [{"w": w["w"], "opp": w["opp"], "v": round(w.get(wk_field, w.get("tkl", 0)), 1)}
                           for w in sorted(weekly[pid], key=lambda x: x["w"])]
        else:
            entry["ss"] = None
            entry["wk"] = []
        players.append(entry)

    players.sort(key=lambda p: (p["t"], p["p"], -(p.get("ss") or {}).get("fp", 0) if p.get("ss") else 0))

    # --- Multi-season "vs this opponent" history, and real defense-allowed-by-position ---
    # Simplification, stated plainly: we only have CURRENT rosters, not historical ones, so
    # every row is attributed to a player's position using their current roster listing.
    # That's right for the vast majority of players (most don't switch position), but a
    # player who changed position since a prior season will be misclassified for that season.
    all_season_rows = [(season, r) for r in stat_rows] + \
                       [(hs, r) for hs in hist_seasons for r in hist_stat_rows.get(hs, [])]

    player_hist = defaultdict(list)
    def_games = defaultdict(set)          # team -> set of (season, week) it played defense
    def_agg = defaultdict(lambda: defaultdict(float))  # (team,pos) -> field -> total

    for szn, row in all_season_rows:
        if row["season_type"] != "REG":
            continue
        pid = row["player_id"]
        r = roster.get(pid)
        if not r:
            continue  # not on a current active roster — skip (see simplification note above)
        pos = r["p"]
        opp = row["opponent_team"]
        wk = int(row["week"])
        spec = POS_STATS.get(pos)
        if not spec:
            continue
        line = {"s": szn, "w": wk, "opp": opp}
        for full, short in spec["fields"].items():
            line[short] = round(num(row.get(full)), 1)
        player_hist[pid].append(line)

        def_games[opp].add((szn, wk))
        for full in spec["fields"]:
            def_agg[(opp, pos)][full] += num(row.get(full))

    for pid, rows in player_hist.items():
        rows.sort(key=lambda x: (x["s"], x["w"]))
    for p in players:
        p["hist"] = player_hist.get(p["id"], [])

    defense_allowed = {}
    for (team, pos), sums in def_agg.items():
        g = len(def_games.get(team, ())) or 1
        spec = POS_STATS[pos]
        row_out = {short: round(sums.get(full, 0) / g, 2) for full, short in spec["fields"].items()}
        row_out["g"] = len(def_games.get(team, ()))
        defense_allowed.setdefault(team, {})[pos] = row_out

    games = []
    for row in game_rows:
        if int(row["season"]) != season:
            continue
        games.append({
            "id": row["game_id"], "wk": int(row["week"]), "date": row["gameday"],
            "away": row["away_team"], "home": row["home_team"],
            "as": int(row["away_score"]) if row["away_score"] else None,
            "hs": int(row["home_score"]) if row["home_score"] else None,
            "spread": num(row["spread_line"], None) if row["spread_line"] else None,
            "total": num(row["total_line"], None) if row["total_line"] else None,
            "aml": int(row["away_moneyline"]) if row["away_moneyline"] else None,
            "hml": int(row["home_moneyline"]) if row["home_moneyline"] else None,
        })
    games.sort(key=lambda g: (g["wk"], g["date"]))

    out = {"season": season, "hist_seasons": hist_seasons, "generated": date.today().isoformat(),
           "players": players, "games": games, "defense_allowed": defense_allowed}
    return out

if __name__ == "__main__":
    season = int(sys.argv[1]) if len(sys.argv) > 1 else season_for_today()
    data = build(season)
    with open("nfl_data.json", "w") as f:
        json.dump(data, f, separators=(",", ":"))
    print(f"Wrote nfl_data.json — {len(data['players'])} players, {len(data['games'])} games, season {season}")
