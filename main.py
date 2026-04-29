
"""
HR MACHINE PRO - ELITE MAIN ENGINE V2
HR-only next-day prediction engine.

Run:
    python main.py

Then:
    streamlit run app.py

Creates:
    latest_picks.csv

Elite additions:
- Eastern Time slate logic
- Real Statcast support when pybaseball is installed
- Safe Statcast fallbacks so GitHub Actions will not break
- Pitch-type matchup foundation
- Wind direction + stadium orientation HR impact
- Smarter top ranking
- Team stacking control
- Request/stat caching for faster runs

Optional for REAL Statcast:
    Add pybaseball to requirements.txt

Recommended requirements.txt:
    streamlit
    pandas
    requests
    pybaseball
"""

from __future__ import annotations

import math
import time
import json
import warnings
import requests
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Dict, Any, Optional, List
from collections import defaultdict

warnings.filterwarnings("ignore")

OUTPUT_FILE = Path("latest_picks.csv")
CACHE_FILE = Path("player_cache.json")
STATCAST_CACHE_FILE = Path("statcast_cache.json")
MLB_API_BASE = "https://statsapi.mlb.com/api/v1"

MAX_PLAYERS_PER_TEAM = 8
MAX_FINAL_PLAYERS_PER_TEAM = 2
MAX_FINAL_ROWS = 150
REQUEST_SLEEP = 0.01

# Set to True. If pybaseball is not installed, it safely falls back.
USE_REAL_STATCAST = True

# =====================================================
# Stadium coordinates + HR park factors + rough HR wind orientation
# =====================================================

STADIUMS = {
    "Angel Stadium": {"lat": 33.8003, "lon": -117.8827, "factor": 0.98, "hr_out_deg": 45},
    "Busch Stadium": {"lat": 38.6226, "lon": -90.1928, "factor": 0.99, "hr_out_deg": 90},
    "Chase Field": {"lat": 33.4455, "lon": -112.0667, "factor": 1.02, "hr_out_deg": 0},
    "Citi Field": {"lat": 40.7571, "lon": -73.8458, "factor": 0.99, "hr_out_deg": 70},
    "Citizens Bank Park": {"lat": 39.9061, "lon": -75.1665, "factor": 1.10, "hr_out_deg": 25},
    "Comerica Park": {"lat": 42.3390, "lon": -83.0485, "factor": 0.94, "hr_out_deg": 150},
    "Coors Field": {"lat": 39.7559, "lon": -104.9942, "factor": 1.17, "hr_out_deg": 15},
    "Dodger Stadium": {"lat": 34.0739, "lon": -118.2400, "factor": 1.02, "hr_out_deg": 45},
    "Fenway Park": {"lat": 42.3467, "lon": -71.0972, "factor": 1.06, "hr_out_deg": 40},
    "Globe Life Field": {"lat": 32.7473, "lon": -97.0842, "factor": 1.05, "hr_out_deg": 45},
    "Great American Ball Park": {"lat": 39.0979, "lon": -84.5082, "factor": 1.18, "hr_out_deg": 120},
    "Guaranteed Rate Field": {"lat": 41.8300, "lon": -87.6339, "factor": 1.03, "hr_out_deg": 135},
    "Kauffman Stadium": {"lat": 39.0517, "lon": -94.4803, "factor": 0.95, "hr_out_deg": 45},
    "loanDepot park": {"lat": 25.7781, "lon": -80.2197, "factor": 0.94, "hr_out_deg": 90},
    "Minute Maid Park": {"lat": 29.7573, "lon": -95.3555, "factor": 1.01, "hr_out_deg": 0},
    "Nationals Park": {"lat": 38.8730, "lon": -77.0074, "factor": 1.00, "hr_out_deg": 70},
    "Oracle Park": {"lat": 37.7786, "lon": -122.3893, "factor": 0.88, "hr_out_deg": 90},
    "Oriole Park at Camden Yards": {"lat": 39.2840, "lon": -76.6217, "factor": 1.02, "hr_out_deg": 60},
    "Petco Park": {"lat": 32.7073, "lon": -117.1566, "factor": 0.94, "hr_out_deg": 45},
    "PNC Park": {"lat": 40.4469, "lon": -80.0057, "factor": 0.92, "hr_out_deg": 60},
    "Progressive Field": {"lat": 41.4962, "lon": -81.6852, "factor": 1.00, "hr_out_deg": 70},
    "Rogers Centre": {"lat": 43.6414, "lon": -79.3894, "factor": 1.00, "hr_out_deg": 45},
    "T-Mobile Park": {"lat": 47.5914, "lon": -122.3325, "factor": 0.93, "hr_out_deg": 90},
    "Target Field": {"lat": 44.9817, "lon": -93.2776, "factor": 0.98, "hr_out_deg": 45},
    "Tropicana Field": {"lat": 27.7683, "lon": -82.6534, "factor": 0.96, "hr_out_deg": 45},
    "Truist Park": {"lat": 33.8908, "lon": -84.4678, "factor": 1.04, "hr_out_deg": 45},
    "Wrigley Field": {"lat": 41.9484, "lon": -87.6553, "factor": 1.05, "hr_out_deg": 45},
    "Yankee Stadium": {"lat": 40.8296, "lon": -73.9262, "factor": 1.12, "hr_out_deg": 90},
}

CONTROLLED_ROOF = {
    "Tropicana Field", "Rogers Centre", "Globe Life Field", "Minute Maid Park",
    "loanDepot park", "Chase Field", "American Family Field", "T-Mobile Park"
}

# =====================================================
# Cache
# =====================================================

def load_json(path: Path) -> Dict[str, Any]:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

def save_json(path: Path, data: Dict[str, Any]) -> None:
    try:
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass

CACHE = load_json(CACHE_FILE)
STATCAST_CACHE = load_json(STATCAST_CACHE_FILE)

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

def format_game_time(game_date_value: Any) -> Dict[str, str]:
    """
    Convert MLB API UTC gameDate into Eastern display fields.
    """
    try:
        raw = str(game_date_value)
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        et = dt.astimezone(ZoneInfo("America/New_York"))
        return {
            "game_datetime_utc": raw,
            "game_date_display": et.strftime("%b %d, %Y"),
            "game_time_et": et.strftime("%I:%M %p ET").lstrip("0"),
            "game_day": et.strftime("%A"),
        }
    except Exception:
        return {
            "game_datetime_utc": str(game_date_value) if game_date_value else "Unknown",
            "game_date_display": "Unknown",
            "game_time_et": "TBD",
            "game_day": "TBD",
        }

def today_date() -> str:
    eastern_now = datetime.now(ZoneInfo("America/New_York"))
    return eastern_now.strftime("%Y-%m-%d")

def tomorrow_date() -> str:
    eastern_now = datetime.now(ZoneInfo("America/New_York"))
    return (eastern_now + timedelta(days=1)).strftime("%Y-%m-%d")

def days_ago_date(days: int) -> str:
    eastern_now = datetime.now(ZoneInfo("America/New_York"))
    return (eastern_now - timedelta(days=days)).strftime("%Y-%m-%d")

def api_get(url: str, params: Optional[Dict[str, Any]] = None, timeout: int = 20) -> Dict[str, Any]:
    key = url + "::" + json.dumps(params or {}, sort_keys=True)
    if key in CACHE:
        return CACHE[key]

    try:
        r = requests.get(url, params=params, timeout=timeout)
        r.raise_for_status()
        data = r.json()
        CACHE[key] = data
        return data
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

            time_info = format_game_time(game.get("gameDate"))

            games.append({
                "game_pk": game.get("gamePk"),
                "game_date": game.get("gameDate"),
                "game_datetime_utc": time_info["game_datetime_utc"],
                "game_date_display": time_info["game_date_display"],
                "game_time_et": time_info["game_time_et"],
                "game_day": time_info["game_day"],
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

def get_person_info(player_id: Optional[int]) -> Dict[str, Any]:
    if not player_id:
        return {}
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
# REAL Statcast support using pybaseball when available
# =====================================================

def load_statcast_player_cache(season: int) -> Dict[str, Dict[str, Any]]:
    """
    Attempts to load real Statcast batting data using pybaseball.
    If pybaseball is unavailable or slow/fails, safely returns {}.
    """
    cache_key = f"batting_statcast_{season}"
    if cache_key in STATCAST_CACHE:
        return STATCAST_CACHE[cache_key]

    if not USE_REAL_STATCAST:
        return {}

    try:
        from pybaseball import batting_stats
        print("[STATCAST] Loading batting_stats from pybaseball...")
        data = batting_stats(season, qual=1)
        if data is None or data.empty:
            return {}

        # Normalize columns defensively because pybaseball column names can vary.
        data.columns = [str(c).strip() for c in data.columns]

        player_cache = {}
        for _, row in data.iterrows():
            name = str(row.get("Name", "")).strip()
            if not name:
                continue

            def get_any(*cols, default=None):
                for c in cols:
                    if c in row and pd.notna(row[c]):
                        return row[c]
                return default

            player_cache[name.lower()] = {
                "barrel_rate": safe_float(get_any("Barrel%", "Barrel %", "Barrel%", default=0), 0),
                "hard_hit_rate": safe_float(get_any("HardHit%", "HardHit %", "HardHit%", default=0), 0),
                "exit_velocity": safe_float(get_any("EV", "Avg EV", "avgEV", "Exit Velocity", default=0), 0),
                "launch_angle": safe_float(get_any("LA", "Avg LA", "Launch Angle", default=0), 0),
                "iso_statcast": safe_float(get_any("ISO", default=0), 0),
                "max_ev": safe_float(get_any("maxEV", "Max EV", default=0), 0),
            }

        STATCAST_CACHE[cache_key] = player_cache
        save_json(STATCAST_CACHE_FILE, STATCAST_CACHE)
        print(f"[STATCAST] Cached {len(player_cache)} hitters.")
        return player_cache

    except Exception as e:
        print(f"[STATCAST] Real Statcast unavailable, using proxy fallback. Reason: {e}")
        return {}

def optional_statcast_power(player_name: str, statcast_cache: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    key = str(player_name).strip().lower()
    data = statcast_cache.get(key, {})
    if not data:
        return {}

    # Convert pybaseball percent columns safely. Some return 12.3, some 0.123.
    out = {}
    for k, v in data.items():
        val = safe_float(v, 0)
        if k in ["barrel_rate", "hard_hit_rate"] and val <= 1:
            val *= 100
        out[k] = round(val, 2)
    return out

# =====================================================
# Park/weather engines
# =====================================================

def get_stadium_meta(venue: str) -> Dict[str, Any]:
    return STADIUMS.get(venue, {"lat": 39.5, "lon": -98.35, "factor": 1.00, "hr_out_deg": 45})

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

def angle_diff(a: float, b: float) -> float:
    diff = abs(a - b) % 360
    return min(diff, 360 - diff)

def wind_hr_impact(venue: str, wind_direction: Any, wind_speed: Any) -> Dict[str, Any]:
    speed = safe_float(wind_speed, 0)
    try:
        direction = float(wind_direction)
    except Exception:
        return {"wind_label": "Wind Direction Unknown", "wind_score": 70, "wind_boost": 0}

    out_deg = get_stadium_meta(venue).get("hr_out_deg", 45)
    diff = angle_diff(direction, out_deg)
    opposite = angle_diff(direction, (out_deg + 180) % 360)

    boost = 0
    label = "Neutral Wind"

    if diff <= 45:
        if speed >= 14:
            boost, label = 10, "Strong Wind Out"
        elif speed >= 9:
            boost, label = 6, "Wind Out Boost"
        elif speed >= 5:
            boost, label = 3, "Light Wind Out"
    elif opposite <= 45:
        if speed >= 14:
            boost, label = -10, "Strong Wind In"
        elif speed >= 9:
            boost, label = -6, "Wind In Drag"
        elif speed >= 5:
            boost, label = -3, "Light Wind In"
    elif speed >= 12:
        boost, label = 1, "Crosswind"

    return {
        "wind_label": label,
        "wind_score": clamp(70 + boost, 45, 92),
        "wind_boost": boost,
    }

def get_weather(date: str, venue: str) -> Dict[str, Any]:
    if venue in CONTROLLED_ROOF:
        return {
            "weather_boost": "Roof/Controlled",
            "weather_score": 70,
            "temperature": 72,
            "wind_speed": 0,
            "wind_direction": "Controlled",
            "humidity": 50,
            "wind_label": "Controlled",
            "wind_score": 70,
            "wind_boost": 0,
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

    if humidity >= 60:
        score += 2

    wind_data = wind_hr_impact(venue, wind_dir, wind)
    score += wind_data["wind_boost"]

    label = "Neutral"
    if score >= 82:
        label = "HR Weather Boost"
    elif score >= 75:
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
        **wind_data,
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

def statcast_proxy_from_power(pwr: float) -> Dict[str, float]:
    return {
        "barrel_rate": round(clamp((pwr - 50) * 0.32 + 7, 3, 22), 1),
        "hard_hit_rate": round(clamp((pwr - 50) * 0.78 + 34, 25, 62), 1),
        "fly_ball_rate": round(clamp((pwr - 50) * 0.40 + 36, 25, 58), 1),
        "pull_rate": round(clamp((pwr - 50) * 0.28 + 38, 28, 55), 1),
        "exit_velocity": round(clamp((pwr - 50) * 0.20 + 88, 82, 97), 1),
        "launch_angle": round(clamp((pwr - 50) * 0.10 + 13, 7, 22), 1),
    }

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
    projected = [2, 3, 4, 5, 1, 6, 7, 8]
    return projected[rank] if rank < len(projected) else 8

def lineup_score(spot: int) -> float:
    if spot in [1, 2, 3, 4]:
        return 88
    if spot in [5, 6]:
        return 76
    return 62

def hr_probability_from_score(score: float) -> float:
    prob = 1.8 + ((score - 55) * 0.24)
    return round(clamp(prob, 1.5, 16.5), 2)

def edge_proxy(hr_probability: float) -> float:
    return round(clamp((hr_probability - 5.5) * 2.2, -10, 18), 2)

def risk_label(confidence: float) -> str:
    if confidence >= 88:
        return "LOW"
    if confidence >= 76:
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

def pitch_type_matchup_score(batter_hand: str, pitcher_hand: str, pitcher_stats: Dict[str, Any], pwr: float, statcast_extra: Dict[str, Any]) -> Dict[str, Any]:
    score = 70
    notes = []

    if batter_hand == "L" and pitcher_hand == "R":
        score += 5
        notes.append("LHB platoon look vs RHP")
    elif batter_hand == "R" and pitcher_hand == "L":
        score += 5
        notes.append("RHB platoon look vs LHP")
    elif pitcher_hand in ["L", "R"]:
        score -= 2
        notes.append("Same-side matchup")

    hr9 = pitcher_hr9(pitcher_stats)
    if hr9 >= 1.5:
        score += 8
        notes.append("Pitcher allows elevated HR/9")
    elif hr9 >= 1.2:
        score += 4
        notes.append("Pitcher HR/9 is attackable")
    elif hr9 <= 0.8:
        score -= 5
        notes.append("Pitcher suppresses HRs")

    barrel = safe_float(statcast_extra.get("barrel_rate", 0), 0)
    hardhit = safe_float(statcast_extra.get("hard_hit_rate", 0), 0)
    ev = safe_float(statcast_extra.get("exit_velocity", 0), 0)

    if barrel >= 13:
        score += 6
        notes.append("Real Statcast barrel rate is elite")
    elif barrel >= 9:
        score += 3
        notes.append("Real Statcast barrel rate is strong")

    if hardhit >= 50:
        score += 3
        notes.append("Hard-hit profile supports HR upside")

    if ev >= 91:
        score += 2
        notes.append("Exit velocity supports power")

    if pwr >= 82:
        score += 5
        notes.append("Elite power profile")
    elif pwr >= 72:
        score += 3
        notes.append("Strong power profile")

    return {
        "pitch_matchup_score": clamp(score, 45, 96),
        "pitch_matchup": "; ".join(notes) if notes else "Neutral pitch matchup",
        "primary_pitch": "Pitch mix pending",
    }

# =====================================================
# Build picks
# =====================================================

def build_candidate_rows(date: str, slate_type: str = "CUSTOM") -> pd.DataFrame:
    season = datetime.now(ZoneInfo("America/New_York")).year
    statcast_cache = load_statcast_player_cache(season)
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
                statcast_extra = optional_statcast_power(player["player"], statcast_cache)

                # If real Statcast exists, blend into power score.
                if statcast_extra:
                    barrel = safe_float(statcast_extra.get("barrel_rate", 0), 0)
                    hardhit = safe_float(statcast_extra.get("hard_hit_rate", 0), 0)
                    ev = safe_float(statcast_extra.get("exit_velocity", 0), 0)
                    statcast_power = 50
                    statcast_power += clamp((barrel - 7) * 2.3, -10, 25)
                    statcast_power += clamp((hardhit - 38) * 0.9, -8, 18)
                    statcast_power += clamp((ev - 88) * 2.0, -8, 14)
                    pwr = round(clamp(pwr * 0.65 + statcast_power * 0.35, 35, 98), 1)

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
                    "statcast_extra": statcast_extra,
                })

                time.sleep(REQUEST_SLEEP)

            candidates = sorted(candidates, key=lambda x: x["power_score"], reverse=True)[:MAX_PLAYERS_PER_TEAM]

            for rank, cand in enumerate(candidates):
                lineup_spot = lineup_spot_from_rank(rank)
                l_score = lineup_score(lineup_spot)

                proxy = statcast_proxy_from_power(cand["power_score"])
                sc = cand["statcast_extra"]

                barrel_rate = sc.get("barrel_rate", proxy["barrel_rate"])
                hard_hit_rate = sc.get("hard_hit_rate", proxy["hard_hit_rate"])
                fly_ball_rate = sc.get("fly_ball_rate", proxy["fly_ball_rate"])
                pull_rate = sc.get("pull_rate", proxy["pull_rate"])
                exit_velocity = sc.get("exit_velocity", proxy["exit_velocity"])
                launch_angle = sc.get("launch_angle", proxy["launch_angle"])
                max_ev = sc.get("max_ev", "N/A")
                statcast_source = "Real Statcast" if sc else "Proxy"

                recent_power_proxy = clamp(55 + cand["hr_rate"] * 850, 45, 90)

                pitch_match = pitch_type_matchup_score(
                    cand["bat_side"],
                    pitcher_hand,
                    pitcher_stats,
                    cand["power_score"],
                    {
                        "barrel_rate": barrel_rate,
                        "hard_hit_rate": hard_hit_rate,
                        "exit_velocity": exit_velocity,
                    }
                )

                split_bonus = 0
                if cand["bat_side"] == "L" and pitcher_hand == "R":
                    split_bonus = 3
                elif cand["bat_side"] == "R" and pitcher_hand == "L":
                    split_bonus = 3

                rating = (
                    cand["power_score"] * 0.25 +
                    p_weak * 0.16 +
                    p_score * 0.10 +
                    weather["weather_score"] * 0.10 +
                    weather["wind_score"] * 0.08 +
                    l_score * 0.10 +
                    recent_power_proxy * 0.09 +
                    pitch_match["pitch_matchup_score"] * 0.09 +
                    70 * 0.03 +
                    split_bonus
                )

                rating = round(clamp(rating, 1, 99), 1)
                hr_prob = hr_probability_from_score(rating)
                edge = edge_proxy(hr_prob)

                confidence = round(clamp(
                    rating * 0.34 +
                    cand["power_score"] * 0.22 +
                    p_weak * 0.13 +
                    p_score * 0.06 +
                    weather["weather_score"] * 0.05 +
                    weather["wind_score"] * 0.06 +
                    pitch_match["pitch_matchup_score"] * 0.07 +
                    l_score * 0.07 -
                    4.0,
                    1,
                    96,
                ), 1)

                risk = risk_label(confidence)

                smart_rank_score = round(clamp(
                    confidence * 0.45 +
                    hr_prob * 3.0 +
                    cand["power_score"] * 0.18 +
                    p_weak * 0.12 +
                    weather["wind_score"] * 0.08 +
                    pitch_match["pitch_matchup_score"] * 0.10,
                    1,
                    99,
                ), 1)

                why_homer = (
                    f"Power score {round(cand['power_score'], 1)}; "
                    f"{statcast_source} power data; "
                    f"barrel rate {barrel_rate}; hard-hit {hard_hit_rate}; EV {exit_velocity}; "
                    f"projected lineup spot {lineup_spot}; "
                    f"pitcher HR/9 {p_hr9}; "
                    f"{p_label}; {weather['weather_boost']}; "
                    f"{weather['wind_label']}; "
                    f"{pitch_match['pitch_matchup']}; "
                    f"{hand_split_note(cand['bat_side'], pitcher_hand)}."
                )

                why_fail = (
                    f"Home runs are low-frequency events; lineup is projected not confirmed; "
                    f"pitcher hand is {pitcher_hand}; weather direction is {weather['wind_direction']}; "
                    f"full pitch-by-pitch mix is still pending until dedicated pitch feed is connected."
                )

                reason = (
                    f"HR confidence {confidence}/100. "
                    f"Real HR probability estimate {hr_prob}%. "
                    f"{why_homer} Risk note: {why_fail}"
                )

                rows.append({
                    "date": date,
                    "slate_type": slate_type,
                    "game_date_display": game.get("game_date_display", date),
                    "game_time_et": game.get("game_time_et", "TBD"),
                    "game_day": game.get("game_day", "TBD"),
                    "game_datetime_utc": game.get("game_datetime_utc", ""),
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
                    "real_hr_probability": hr_prob,
                    "probability": hr_prob,
                    "rating": rating,
                    "smart_rank_score": smart_rank_score,
                    "edge": edge,
                    "barrel_rate": barrel_rate,
                    "hard_hit_rate": hard_hit_rate,
                    "fly_ball_rate": fly_ball_rate,
                    "exit_velocity": exit_velocity,
                    "launch_angle": launch_angle,
                    "max_ev": max_ev,
                    "statcast_source": statcast_source,
                    "iso": cand["iso"],
                    "slg": cand["slg"],
                    "pull_rate": pull_rate,
                    "pitcher_hr9": p_hr9,
                    "pitcher_barrel_allowed": "Proxy",
                    "primary_pitch": pitch_match["primary_pitch"],
                    "pitch_matchup": pitch_match["pitch_matchup"],
                    "pitch_matchup_score": round(pitch_match["pitch_matchup_score"], 1),
                    "park": venue,
                    "park_factor": p_label,
                    "park_score": round(p_score, 1),
                    "weather_boost": weather["weather_boost"],
                    "weather": weather["weather_boost"],
                    "weather_score": weather["weather_score"],
                    "wind_label": weather["wind_label"],
                    "wind_score": weather["wind_score"],
                    "wind_boost": weather["wind_boost"],
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

    out = out.sort_values("smart_rank_score", ascending=False)

    team_counts = defaultdict(int)
    balanced_rows = []

    for _, row in out.iterrows():
        team = row.get("team", "Unknown")
        if team_counts[team] < MAX_FINAL_PLAYERS_PER_TEAM:
            balanced_rows.append(row)
            team_counts[team] += 1

    balanced = pd.DataFrame(balanced_rows)
    return balanced.sort_values("smart_rank_score", ascending=False).head(MAX_FINAL_ROWS)

# =====================================================
# MAIN
# =====================================================

def main():
    today = today_date()
    tomorrow = tomorrow_date()

    print(f"[HR MACHINE] Building TODAY slate for {today}...")
    today_picks = build_candidate_rows(today, "TODAY")

    print(f"[HR MACHINE] Building TOMORROW slate for {tomorrow}...")
    tomorrow_picks = build_candidate_rows(tomorrow, "TOMORROW")

    picks = pd.concat([today_picks, tomorrow_picks], ignore_index=True) if not today_picks.empty or not tomorrow_picks.empty else pd.DataFrame()

    if picks.empty:
        picks = pd.DataFrame(columns=[
            "date", "slate_type", "game_date_display", "game_time_et", "game_day", "game_datetime_utc",
            "game", "player", "team", "position", "mlb_id", "prop", "line",
            "opposing_pitcher", "pitcher", "pitcher_hand", "batter_hand",
            "lineup_spot", "starter_confirmed", "hr_probability", "real_hr_probability", "probability",
            "rating", "smart_rank_score", "edge", "barrel_rate", "hard_hit_rate", "fly_ball_rate",
            "exit_velocity", "launch_angle", "max_ev", "statcast_source", "iso", "slg", "pull_rate",
            "pitcher_hr9", "pitcher_barrel_allowed", "primary_pitch", "pitch_matchup", "pitch_matchup_score",
            "park", "park_factor", "park_score", "weather_boost", "weather",
            "weather_score", "wind_label", "wind_score", "wind_boost", "wind_direction",
            "wind_speed", "temperature", "humidity", "confidence_score", "risk",
            "why_homer", "why_fail", "reason"
        ])
    else:
        # Preserve slate balance and ranking inside each slate.
        sort_col = "smart_rank_score" if "smart_rank_score" in picks.columns else "confidence_score"
        picks = picks.sort_values(["slate_type", sort_col], ascending=[True, False])

    picks.to_csv(OUTPUT_FILE, index=False)
    save_json(CACHE_FILE, CACHE)
    if "save_json" in globals() and "STATCAST_CACHE_FILE" in globals():
        save_json(STATCAST_CACHE_FILE, STATCAST_CACHE)

    print(f"[HR MACHINE] Saved {len(picks)} HR picks to {OUTPUT_FILE.resolve()}")

    if len(picks):
        print("\nTop 10 HR Targets:")
        cols = [c for c in ["slate_type", "date", "game_time_et", "player", "team", "opposing_pitcher", "hr_probability", "confidence_score", "smart_rank_score", "risk"] if c in picks.columns]
        print(picks[cols].head(10).to_string(index=False))

if __name__ == "__main__":
    main()
