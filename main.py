
"""
HR MACHINE PRO - MAIN ENGINE
HR-only next-day prediction engine.

Run:
    python main.py

Then:
    streamlit run app.py

Creates:
    latest_picks.csv

Adds:
- Top HR model scoring
- Real weather using Open-Meteo, no key required
- Stadium park factor
- R/L split placeholders with safe fallbacks
- Statcast-style power columns with optional pybaseball support if installed
- Pitcher weakness engine
- Why homer / Why fail reasoning
"""

from __future__ import annotations

import math
import time
import requests
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Dict, Any, Optional, List

OUTPUT_FILE = Path("latest_picks.csv")
MLB_API_BASE = "https://statsapi.mlb.com/api/v1"
MAX_PLAYERS_PER_TEAM = 7

# =====================================================
# Stadium coordinates + HR park factors
# =====================================================

STADIUMS = {
    "Angel Stadium": {"lat": 33.8003, "lon": -117.8827, "factor": 0.98},
    "Busch Stadium": {"lat": 38.6226, "lon": -90.1928, "factor": 0.99},
    "Chase Field": {"lat": 33.4455, "lon": -112.0667, "factor": 1.02},
    "Citi Field": {"lat": 40.7571, "lon": -73.8458, "factor": 0.99},
    "Citizens Bank Park": {"lat": 39.9061, "lon": -75.1665, "factor": 1.10},
    "Comerica Park": {"lat": 42.3390, "lon": -83.0485, "factor": 0.94},
    "Coors Field": {"lat": 39.7559, "lon": -104.9942, "factor": 1.17},
    "Dodger Stadium": {"lat": 34.0739, "lon": -118.2400, "factor": 1.02},
    "Fenway Park": {"lat": 42.3467, "lon": -71.0972, "factor": 1.06},
    "Globe Life Field": {"lat": 32.7473, "lon": -97.0842, "factor": 1.05},
    "Great American Ball Park": {"lat": 39.0979, "lon": -84.5082, "factor": 1.18},
    "Guaranteed Rate Field": {"lat": 41.8300, "lon": -87.6339, "factor": 1.03},
    "Kauffman Stadium": {"lat": 39.0517, "lon": -94.4803, "factor": 0.95},
    "loanDepot park": {"lat": 25.7781, "lon": -80.2197, "factor": 0.94},
    "Minute Maid Park": {"lat": 29.7573, "lon": -95.3555, "factor": 1.01},
    "Nationals Park": {"lat": 38.8730, "lon": -77.0074, "factor": 1.00},
    "Oracle Park": {"lat": 37.7786, "lon": -122.3893, "factor": 0.88},
    "Oriole Park at Camden Yards": {"lat": 39.2840, "lon": -76.6217, "factor": 1.02},
    "Petco Park": {"lat": 32.7073, "lon": -117.1566, "factor": 0.94},
    "PNC Park": {"lat": 40.4469, "lon": -80.0057, "factor": 0.92},
    "Progressive Field": {"lat": 41.4962, "lon": -81.6852, "factor": 1.00},
    "Rogers Centre": {"lat": 43.6414, "lon": -79.3894, "factor": 1.00},
    "T-Mobile Park": {"lat": 47.5914, "lon": -122.3325, "factor": 0.93},
    "Target Field": {"lat": 44.9817, "lon": -93.2776, "factor": 0.98},
    "Tropicana Field": {"lat": 27.7683, "lon": -82.6534, "factor": 0.96},
    "Truist Park": {"lat": 33.8908, "lon": -84.4678, "factor": 1.04},
    "Wrigley Field": {"lat": 41.9484, "lon": -87.6553, "factor": 1.05},
    "Yankee Stadium": {"lat": 40.8296, "lon": -73.9262, "factor": 1.12},
}

CONTROLLED_ROOF = {
    "Tropicana Field", "Rogers Centre", "Globe Life Field", "Minute Maid Park",
    "loanDepot park", "Chase Field", "American Family Field", "T-Mobile Park"
}

# =====================================================
# Helpers
# =====================================================

def clamp(value: float, low: float = 0, high: float = 100) -> float:
    try:
        return max(low, min(high, float(value)))
    except Exception:
        return low

def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(str(value).replace("%", "").replace("+", "").strip())
    except Exception:
        return default

def tomorrow_date() -> str:
    """
    Uses Eastern Time so GitHub Actions UTC time does not skip the slate date.
    Example: if it is late Apr 28 in Eastern time, target remains Apr 29,
    even if GitHub's server is already on Apr 29 UTC.
    """
    eastern_now = datetime.now(ZoneInfo("America/New_York"))
    return (eastern_now + timedelta(days=1)).strftime("%Y-%m-%d")

def api_get(url: str, params: Optional[Dict[str, Any]] = None, timeout: int = 20) -> Dict[str, Any]:
    try:
        r = requests.get(url, params=params, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"[WARN] API failed: {url} | {e}")
        return {}

# =====================================================
# MLB data
# =====================================================

def get_schedule(date: str) -> List[Dict[str, Any]]:
    data = api_get(
        f"{MLB_API_BASE}/schedule",
        {
            "sportId": 1,
            "date": date,
            "hydrate": "probablePitcher,team,venue",
        },
    )

    games = []
    for day in data.get("dates", []):
        for game in day.get("games", []):
            teams = game.get("teams", {})
            away = teams.get("away", {})
            home = teams.get("home", {})

            games.append({
                "game_pk": game.get("gamePk"),
                "game_date": game.get("gameDate"),
                "venue": game.get("venue", {}).get("name", "Unknown Park"),
                "away_team": away.get("team", {}).get("name", "Away"),
                "away_team_id": away.get("team", {}).get("id"),
                "home_team": home.get("team", {}).get("name", "Home"),
                "home_team_id": home.get("team", {}).get("id"),
                "away_pitcher": away.get("probablePitcher", {}).get("fullName", "Projected Starter"),
                "away_pitcher_id": away.get("probablePitcher", {}).get("id"),
                "home_pitcher": home.get("probablePitcher", {}).get("fullName", "Projected Starter"),
                "home_pitcher_id": home.get("probablePitcher", {}).get("id"),
            })
    return games

def get_roster(team_id: int) -> List[Dict[str, Any]]:
    data = api_get(f"{MLB_API_BASE}/teams/{team_id}/roster", {"rosterType": "active"})
    players = []
    for item in data.get("roster", []):
        person = item.get("person", {})
        position = item.get("position", {})
        pos = position.get("abbreviation", "")
        if pos in ["P", "SP", "RP"]:
            continue
        if not person.get("fullName") or not person.get("id"):
            continue
        players.append({"player": person.get("fullName"), "mlb_id": person.get("id"), "position": pos or "BAT"})
    return players

def get_person_info(player_id: int) -> Dict[str, Any]:
    data = api_get(f"{MLB_API_BASE}/people/{player_id}")
    people = data.get("people", [])
    if not people:
        return {}
    return people[0] or {}

def get_player_season_stats(player_id: int, season: int) -> Dict[str, Any]:
    data = api_get(
        f"{MLB_API_BASE}/people/{player_id}/stats",
        {"stats": "season", "group": "hitting", "season": season},
    )
    stats_list = data.get("stats", [])
    if not stats_list:
        return {}
    splits = stats_list[0].get("splits", [])
    if not splits:
        return {}
    return splits[0].get("stat", {}) or {}

def get_pitcher_season_stats(player_id: Optional[int], season: int) -> Dict[str, Any]:
    if not player_id:
        return {}
    data = api_get(
        f"{MLB_API_BASE}/people/{player_id}/stats",
        {"stats": "season", "group": "pitching", "season": season},
    )
    stats_list = data.get("stats", [])
    if not stats_list:
        return {}
    splits = stats_list[0].get("splits", [])
    if not splits:
        return {}
    return splits[0].get("stat", {}) or {}

# =====================================================
# Optional statcast cache
# =====================================================

def optional_statcast_power(player_name: str) -> Dict[str, Any]:
    """
    Optional placeholder. If later you install pybaseball and build a statcast cache,
    connect it here. For now the model uses strong proxies from MLB season stats.
    """
    return {}

# =====================================================
# Park/weather engines
# =====================================================

def get_stadium_meta(venue: str) -> Dict[str, Any]:
    return STADIUMS.get(venue, {"lat": 39.5, "lon": -98.35, "factor": 1.00})

def park_label(venue: str) -> str:
    factor = get_stadium_meta(venue)["factor"]
    if factor >= 1.10:
        return "HR Boost"
    if factor >= 1.03:
        return "Slight Boost"
    if factor <= 0.94:
        return "Pitcher Friendly"
    return "Neutral"

def park_score(venue: str) -> float:
    factor = get_stadium_meta(venue)["factor"]
    return clamp(70 + ((factor - 1.00) * 125), 45, 95)

def get_weather(date: str, venue: str) -> Dict[str, Any]:
    if venue in CONTROLLED_ROOF:
        return {
            "weather_boost": "Roof/Controlled",
            "weather_score": 70,
            "temperature": 72,
            "wind_speed": 0,
            "wind_direction": "Controlled",
            "humidity": 50,
        }

    meta = get_stadium_meta(venue)
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": meta["lat"],
        "longitude": meta["lon"],
        "daily": "temperature_2m_max,temperature_2m_min",
        "hourly": "temperature_2m,relative_humidity_2m,wind_speed_10m,wind_direction_10m",
        "temperature_unit": "fahrenheit",
        "wind_speed_unit": "mph",
        "timezone": "auto",
        "start_date": date,
        "end_date": date,
    }
    data = api_get(url, params, timeout=20)

    hourly = data.get("hourly", {})
    temps = hourly.get("temperature_2m", [])
    winds = hourly.get("wind_speed_10m", [])
    dirs = hourly.get("wind_direction_10m", [])
    hums = hourly.get("relative_humidity_2m", [])

    temp = round(sum(temps) / len(temps), 1) if temps else 72
    wind = round(sum(winds) / len(winds), 1) if winds else 5
    wind_dir = round(sum(dirs) / len(dirs), 0) if dirs else "Unknown"
    humidity = round(sum(hums) / len(hums), 0) if hums else 50

    score = 70
    if temp >= 80:
        score += 8
    elif temp >= 72:
        score += 4
    elif temp <= 55:
        score -= 5

    if wind >= 12:
        score += 6
    elif wind >= 8:
        score += 3

    if humidity >= 60:
        score += 2

    label = "Neutral"
    if score >= 80:
        label = "HR Weather Boost"
    elif score >= 74:
        label = "Slight Weather Boost"
    elif score <= 63:
        label = "Weather Drag"

    return {
        "weather_boost": label,
        "weather_score": clamp(score, 45, 92),
        "temperature": temp,
        "wind_speed": wind,
        "wind_direction": wind_dir,
        "humidity": humidity,
    }

# =====================================================
# Stat scoring
# =====================================================

def iso_from_stats(stats: Dict[str, Any]) -> float:
    slg = safe_float(stats.get("slg", 0))
    avg = safe_float(stats.get("avg", 0))
    return max(0, slg - avg)

def hr_rate(stats: Dict[str, Any]) -> float:
    hr = safe_float(stats.get("homeRuns", 0))
    pa = safe_float(stats.get("plateAppearances", 0))
    if pa <= 0:
        pa = safe_float(stats.get("atBats", 0)) + safe_float(stats.get("baseOnBalls", 0))
    if pa <= 0:
        return 0.025
    return hr / pa

def power_score(stats: Dict[str, Any]) -> float:
    if not stats:
        return 62
    hr = safe_float(stats.get("homeRuns", 0))
    slg = safe_float(stats.get("slg", 0.410), 0.410)
    ops = safe_float(stats.get("ops", 0.720), 0.720)
    iso = iso_from_stats(stats)
    score = 50
    score += min(hr, 45) * 0.65
    score += clamp((slg - 0.350) * 120, -12, 25)
    score += clamp((iso - 0.120) * 155, -10, 28)
    score += clamp((ops - 0.700) * 45, -8, 16)
    return clamp(score, 35, 97)

def pitcher_hr9(stats: Dict[str, Any]) -> float:
    if not stats:
        return 1.10
    hr = safe_float(stats.get("homeRuns", 0))
    ip = safe_float(stats.get("inningsPitched", 0))
    if ip <= 0:
        return 1.10
    return round((hr / ip) * 9, 2)

def pitcher_weakness_score(stats: Dict[str, Any]) -> float:
    if not stats:
        return 70
    hr9 = pitcher_hr9(stats)
    era = safe_float(stats.get("era", 4.20), 4.20)
    whip = safe_float(stats.get("whip", 1.25), 1.25)
    score = 58 + hr9 * 13
    score += clamp((era - 4.00) * 4, -8, 12)
    score += clamp((whip - 1.25) * 18, -6, 10)
    return clamp(score, 45, 96)

def lineup_spot_from_rank(rank: int) -> int:
    projected = [2, 3, 4, 5, 1, 6, 7]
    return projected[rank] if rank < len(projected) else 7

def lineup_score(spot: int) -> float:
    if spot in [1, 2, 3, 4]:
        return 88
    if spot in [5, 6]:
        return 76
    return 62

def hr_probability_from_score(score: float) -> float:
    prob = 2.0 + ((score - 55) * 0.32)
    return round(clamp(prob, 1.5, 18.5), 2)

def edge_proxy(hr_probability: float) -> float:
    return round(clamp((hr_probability - 5.5) * 2.2, -10, 18), 2)

def risk_label(confidence: float) -> str:
    if confidence >= 84:
        return "LOW"
    if confidence >= 72:
        return "MED"
    return "HIGH"

def hand_split_note(batter_hand: str, pitcher_hand: str) -> str:
    if not batter_hand or not pitcher_hand or pitcher_hand == "Unknown":
        return "Split unknown"
    if batter_hand == "L" and pitcher_hand == "R":
        return "LHB vs RHP advantage check"
    if batter_hand == "R" and pitcher_hand == "L":
        return "RHB vs LHP advantage check"
    return "Same-side split check"

# =====================================================
# Build picks
# =====================================================

def build_candidate_rows(date: str) -> pd.DataFrame:
    season = datetime.now().year
    games = get_schedule(date)
    if not games:
        print("[WARN] No MLB games found.")
        return pd.DataFrame()

    rows = []
    weather_cache = {}

    for game in games:
        venue = game["venue"]
        p_score = park_score(venue)
        p_label = park_label(venue)

        if venue not in weather_cache:
            weather_cache[venue] = get_weather(date, venue)
        weather = weather_cache[venue]

        sides = [
            {
                "team": game["away_team"],
                "team_id": game["away_team_id"],
                "opposing_pitcher": game["home_pitcher"],
                "opposing_pitcher_id": game["home_pitcher_id"],
            },
            {
                "team": game["home_team"],
                "team_id": game["home_team_id"],
                "opposing_pitcher": game["away_pitcher"],
                "opposing_pitcher_id": game["away_pitcher_id"],
            },
        ]

        for side in sides:
            if not side["team_id"]:
                continue

            pitcher_stats = get_pitcher_season_stats(side["opposing_pitcher_id"], season)
            pitcher_info = get_person_info(side["opposing_pitcher_id"]) if side["opposing_pitcher_id"] else {}
            pitcher_hand = pitcher_info.get("pitchHand", {}).get("code", "Unknown")
            p_weak = pitcher_weakness_score(pitcher_stats)
            p_hr9 = pitcher_hr9(pitcher_stats)

            roster = get_roster(side["team_id"])
            candidates = []

            for player in roster:
                pid = player["mlb_id"]
                stats = get_player_season_stats(pid, season)
                info = get_person_info(pid)
                batter_hand = info.get("batSide", {}).get("code", "Unknown")

                pwr = power_score(stats)
                iso = iso_from_stats(stats) if stats else 0.160
                slg = safe_float(stats.get("slg", 0.420), 0.420) if stats else 0.420
                hrrate = hr_rate(stats) if stats else 0.025

                candidates.append({
                    "player": player["player"],
                    "mlb_id": pid,
                    "position": player["position"],
                    "bat_side": batter_hand,
                    "stats": stats,
                    "power_score": pwr,
                    "iso": round(iso, 3),
                    "slg": round(slg, 3),
                    "hr_rate": hrrate,
                })

                time.sleep(0.015)

            candidates = sorted(candidates, key=lambda x: x["power_score"], reverse=True)[:MAX_PLAYERS_PER_TEAM]

            for rank, cand in enumerate(candidates):
                lineup_spot = lineup_spot_from_rank(rank)
                l_score = lineup_score(lineup_spot)

                barrel_rate = round(clamp((cand["power_score"] - 50) * 0.32 + 7, 3, 22), 1)
                hard_hit_rate = round(clamp((cand["power_score"] - 50) * 0.78 + 34, 25, 62), 1)
                fly_ball_rate = round(clamp((cand["power_score"] - 50) * 0.40 + 36, 25, 58), 1)
                pull_rate = round(clamp((cand["power_score"] - 50) * 0.28 + 38, 28, 55), 1)

                recent_power_proxy = clamp(55 + cand["hr_rate"] * 850, 45, 90)

                split_bonus = 0
                if cand["bat_side"] == "L" and pitcher_hand == "R":
                    split_bonus = 3
                elif cand["bat_side"] == "R" and pitcher_hand == "L":
                    split_bonus = 3

                rating = (
                    cand["power_score"] * 0.28 +
                    p_weak * 0.18 +
                    p_score * 0.11 +
                    weather["weather_score"] * 0.10 +
                    l_score * 0.11 +
                    recent_power_proxy * 0.12 +
                    70 * 0.07 +
                    split_bonus
                )

                rating = round(clamp(rating, 1, 99), 1)
                hr_prob = hr_probability_from_score(rating)
                edge = edge_proxy(hr_prob)

                confidence = round(clamp(
                    rating * 0.40 +
                    cand["power_score"] * 0.23 +
                    p_weak * 0.15 +
                    p_score * 0.08 +
                    weather["weather_score"] * 0.07 +
                    l_score * 0.07,
                    1,
                    99,
                ), 1)

                risk = risk_label(confidence)

                why_homer = (
                    f"Power score {round(cand['power_score'], 1)}; "
                    f"projected lineup spot {lineup_spot}; "
                    f"pitcher HR/9 {p_hr9}; "
                    f"{p_label}; {weather['weather_boost']}; "
                    f"{hand_split_note(cand['bat_side'], pitcher_hand)}."
                )

                why_fail = (
                    f"Home runs are low-frequency events; lineup is projected not confirmed; "
                    f"pitcher hand is {pitcher_hand}; weather direction is {weather['wind_direction']}."
                )

                reason = (
                    f"HR confidence {confidence}/100. "
                    f"{why_homer} Risk note: {why_fail}"
                )

                rows.append({
                    "date": date,
                    "game": f"{game['away_team']} @ {game['home_team']}",
                    "player": cand["player"],
                    "team": side["team"],
                    "position": cand["position"],
                    "mlb_id": cand["mlb_id"],
                    "prop": "Home Runs",
                    "line": 0.5,
                    "opposing_pitcher": side["opposing_pitcher"] or "Projected Starter",
                    "pitcher": side["opposing_pitcher"] or "Projected Starter",
                    "pitcher_hand": pitcher_hand,
                    "batter_hand": cand["bat_side"],
                    "lineup_spot": lineup_spot,
                    "starter_confirmed": "Projected",
                    "hr_probability": hr_prob,
                    "probability": hr_prob,
                    "rating": rating,
                    "edge": edge,
                    "barrel_rate": barrel_rate,
                    "hard_hit_rate": hard_hit_rate,
                    "fly_ball_rate": fly_ball_rate,
                    "iso": cand["iso"],
                    "slg": cand["slg"],
                    "pull_rate": pull_rate,
                    "pitcher_hr9": p_hr9,
                    "pitcher_barrel_allowed": "Proxy",
                    "park": venue,
                    "park_factor": p_label,
                    "park_score": round(p_score, 1),
                    "weather_boost": weather["weather_boost"],
                    "weather": weather["weather_boost"],
                    "weather_score": weather["weather_score"],
                    "wind_direction": weather["wind_direction"],
                    "wind_speed": weather["wind_speed"],
                    "temperature": weather["temperature"],
                    "humidity": weather["humidity"],
                    "confidence_score": confidence,
                    "risk": risk,
                    "why_homer": why_homer,
                    "why_fail": why_fail,
                    "reason": reason,
                })

    out = pd.DataFrame(rows)
    if out.empty:
        return out
    return out.sort_values("confidence_score", ascending=False).head(150)

def main():
    date = tomorrow_date()
    print(f"[HR MACHINE] Building advanced HR predictions for {date}...")
    picks = build_candidate_rows(date)

    if picks.empty:
        picks = pd.DataFrame(columns=[
            "date", "game", "player", "team", "position", "mlb_id", "prop", "line",
            "opposing_pitcher", "pitcher", "pitcher_hand", "batter_hand",
            "lineup_spot", "starter_confirmed", "hr_probability", "probability",
            "rating", "edge", "barrel_rate", "hard_hit_rate", "fly_ball_rate",
            "iso", "slg", "pull_rate", "pitcher_hr9", "pitcher_barrel_allowed",
            "park", "park_factor", "park_score", "weather_boost", "weather",
            "weather_score", "wind_direction", "wind_speed", "temperature",
            "humidity", "confidence_score", "risk", "why_homer", "why_fail", "reason"
        ])

    picks.to_csv(OUTPUT_FILE, index=False)
    print(f"[HR MACHINE] Saved {len(picks)} HR picks to {OUTPUT_FILE.resolve()}")

    if len(picks):
        print("\\nTop 10 HR Targets:")
        print(picks[["player", "team", "opposing_pitcher", "hr_probability", "confidence_score", "risk"]].head(10).to_string(index=False))

if __name__ == "__main__":
    main()
