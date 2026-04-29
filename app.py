
"""
HR MACHINE PRO - PREMIUM ELITE APP
Native Streamlit premium UI. No raw row HTML rendering.

Features:
- Player headshots restored
- Premium dark dashboard layout
- Strength score separated from real HR probability
- Wind impact logic
- Pitch-type matchup foundation
- Lock / Heater / Longshot tags
- Native progress bars so no HTML prints as text
- Fast cached loading
"""

from pathlib import Path
from datetime import datetime, timezone
import base64
import json
import math

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(
    page_title="HR Machine Pro",
    page_icon="⚾",
    layout="wide",
    initial_sidebar_state="collapsed",
)

CSV_FILE = Path("latest_picks.csv")

# =========================================================
# PREMIUM CSS
# =========================================================
st.markdown(
    """
<style>
.stApp {
    background:
        radial-gradient(circle at top left, rgba(168,85,247,.22), transparent 30%),
        radial-gradient(circle at top right, rgba(34,197,94,.12), transparent 28%),
        radial-gradient(circle at bottom right, rgba(56,189,248,.09), transparent 28%),
        linear-gradient(135deg, #050816 0%, #08111f 55%, #020617 100%);
    color: #f8fafc;
}

.block-container {
    padding-top: 1.1rem;
    padding-left: 1.35rem;
    padding-right: 1.35rem;
    max-width: 100%;
}

[data-testid="stHeader"] {
    background: rgba(2,6,23,.65);
}

[data-testid="stVerticalBlockBorderWrapper"] {
    border-color: rgba(148,163,184,.22) !important;
    background:
        radial-gradient(circle at top right, rgba(168,85,247,.10), transparent 38%),
        linear-gradient(135deg, rgba(15,23,42,.96), rgba(2,6,23,.82)) !important;
    box-shadow: 0 16px 42px rgba(0,0,0,.28);
}

[data-testid="stMetric"] {
    background:
        radial-gradient(circle at top right, rgba(34,197,94,.08), transparent 35%),
        linear-gradient(135deg, rgba(15,23,42,.96), rgba(15,23,42,.70));
    border: 1px solid rgba(148,163,184,.20);
    border-radius: 18px;
    padding: 14px 16px;
    box-shadow: 0 14px 34px rgba(0,0,0,.22);
}

[data-testid="stMetricLabel"] {
    color: #94a3b8;
    font-weight: 850;
}

[data-testid="stMetricValue"] {
    color: #eafff3;
    font-weight: 950;
}

.stTextInput input,
.stSelectbox div[data-baseweb="select"] > div {
    background-color: rgba(2,6,23,.78) !important;
    border-color: rgba(148,163,184,.24) !important;
    border-radius: 14px !important;
}

.stSlider {
    padding-top: 5px;
}

div[data-testid="stImage"] img {
    border-radius: 18px;
    border: 2px solid rgba(168,85,247,.85);
    box-shadow: 0 0 28px rgba(168,85,247,.22);
}

h1, h2, h3 {
    letter-spacing: -0.025em;
}

hr {
    border-color: rgba(148,163,184,.14);
}

button[kind="secondary"] {
    border-radius: 14px !important;
    border-color: rgba(168,85,247,.45) !important;
}

div[role="progressbar"] > div {
    background: linear-gradient(90deg, #22c55e, #a855f7) !important;
}

.premium-title {
    font-size: 36px;
    font-weight: 950;
    line-height: 1;
    letter-spacing: -1.1px;
}

.premium-subtitle {
    margin-top: 6px;
    color: #a5b4fc;
    font-size: 12px;
    font-weight: 900;
    letter-spacing: .14em;
}

.small-muted {
    color: #94a3b8;
    font-size: 12px;
    font-weight: 700;
}

.player-name {
    font-size: 20px;
    font-weight: 950;
    line-height: 1.1;
}

.tag-lock {
    color: #86efac;
    font-weight: 950;
}

.tag-heater {
    color: #fdba74;
    font-weight: 950;
}

.tag-longshot {
    color: #fca5a5;
    font-weight: 950;
}

.tag-watch {
    color: #bae6fd;
    font-weight: 950;
}
.live-glow {
    color: #86efac;
    font-weight: 950;
    text-shadow: 0 0 12px rgba(34,197,94,.35);
}
.timer-pill {
    display: inline-block;
    padding: 5px 9px;
    border-radius: 999px;
    background: rgba(168,85,247,.14);
    border: 1px solid rgba(168,85,247,.35);
    color: #ddd6fe;
    font-size: 12px;
    font-weight: 850;
}
</style>
""",
    unsafe_allow_html=True,
)

# =========================================================
# LOAD DATA
# =========================================================
@st.cache_data(ttl=60)
def load_data(path: Path) -> pd.DataFrame:
    return pd.read_csv(path)

if not CSV_FILE.exists():
    st.error("latest_picks.csv was not found. Run main.py first.")
    st.stop()

df = load_data(CSV_FILE)

if df.empty:
    st.warning("latest_picks.csv is empty. Run main.py again.")
    st.stop()

df.columns = [str(c).strip().lower().replace(" ", "_").replace("-", "_") for c in df.columns]

# =========================================================
# COLUMN HELPERS
# =========================================================
def find_col(*names: str):
    for name in names:
        key = name.lower().replace(" ", "_").replace("-", "_")
        if key in df.columns:
            return key
    return None

player_col = find_col("player", "player_name", "name", "batter")
team_col = find_col("team", "player_team", "batting_team")
pos_col = find_col("position", "pos")
line_col = find_col("line", "prop_line")
rating_col = find_col("rating", "score", "hr_rating")
prob_col = find_col("hr_probability", "probability", "model_prob")
edge_col = find_col("edge")
pitcher_col = find_col("opposing_pitcher", "pitcher")
park_col = find_col("park_factor", "park")
weather_col = find_col("weather_boost", "weather")
lineup_col = find_col("lineup_spot", "lineup")
risk_col = find_col("risk")
id_col = find_col("mlb_id", "mlbam_id", "player_id", "id")
why_homer_col = find_col("why_homer")
why_fail_col = find_col("why_fail")
reason_col = find_col("reason")
conf_col = find_col("confidence_score")
barrel_col = find_col("barrel_rate")
hardhit_col = find_col("hard_hit_rate")
flyball_col = find_col("fly_ball_rate")
pitcher_hr9_col = find_col("pitcher_hr9")
wind_col = find_col("wind_speed")
wind_dir_col = find_col("wind_direction")
temp_col = find_col("temperature")
hand_col = find_col("batter_hand")
pitcher_hand_col = find_col("pitcher_hand")
game_col = find_col("game")
game_date_display_col = find_col("game_date_display", "date", "game_date")
game_time_col = find_col("game_time_et", "game_time", "start_time")
game_day_col = find_col("game_day", "day")
slate_type_col = find_col("slate_type", "slate")
game_datetime_utc_col = find_col("game_datetime_utc", "game_datetime", "start_datetime")
pitch_mix_col = find_col("pitch_mix", "primary_pitch", "pitcher_primary_pitch")
pitch_matchup_col = find_col("pitch_matchup", "pitch_type_matchup")
last_5_hr_col = find_col("last_5_hr_games", "last_hr_games")
last_5_hr_count_col = find_col("last_5_hr_count", "recent_hr_count")
last_hr_days_col = find_col("last_hr_days_ago", "last_hr_days")
recent_hr_chart_col = find_col("recent_hr_chart_data", "hr_chart_data")

if player_col is None:
    st.error("CSV needs a player column.")
    st.stop()

# =========================================================
# GENERAL HELPERS
# =========================================================
def safe(row, col_name, default="N/A"):
    if col_name is None:
        return default
    try:
        value = row[col_name]
        if pd.isna(value) or str(value).strip() == "":
            return default
        return value
    except Exception:
        return default

def to_float(value, default=0.0):
    try:
        if value is None or pd.isna(value):
            return default
        return float(str(value).replace("%", "").replace("+", "").strip())
    except Exception:
        return default

def true_hr_probability_from_strength(score_value):
    """
    Confidence/strength is NOT HR probability.
    Convert model strength score to a realistic HR probability range.
    """
    score = to_float(score_value, 70)
    return round(max(2.0, min(18.5, 2.0 + ((score - 55) * 0.32))), 2)

def display_pct(value):
    x = to_float(value, None)
    if x is None:
        return "N/A"
    if x <= 1:
        x *= 100
    return f"{x:.1f}%"

def conf_label(score_value):
    score = to_float(score_value, 0)
    if score >= 90:
        return "ELITE"
    if score >= 82:
        return "HIGH"
    if score >= 72:
        return "MED"
    return "LOW"

def risk_emoji(risk):
    risk = str(risk).upper()
    if risk == "LOW":
        return "🟢 LOW"
    if risk == "MED":
        return "🟡 MED"
    if risk == "HIGH":
        return "🔴 HIGH"
    return "⚪ N/A"

def profile_tag(score_value, risk):
    score = to_float(score_value, 0)
    risk = str(risk).upper()
    if score >= 90 and risk == "LOW":
        return "🔒 LOCK PROFILE", "tag-lock"
    if score >= 84:
        return "🔥 HEATER", "tag-heater"
    if score < 72:
        return "💣 LONGSHOT", "tag-longshot"
    return "✅ STRONG LOOK", "tag-watch"


def game_time_text(row):
    day = safe(row, game_day_col, "TBD")
    date = safe(row, game_date_display_col, "TBD")
    time = safe(row, game_time_col, "TBD")
    return f"{day} • {date} • {time}"

def game_time_full_text(row):
    try:
        return f"{game_time_text(row)} • {countdown_text(row)}"
    except Exception:
        return game_time_text(row)

def wind_impact(row):
    speed = to_float(safe(row, wind_col, 0), 0)
    direction = str(safe(row, wind_dir_col, "Unknown")).lower()

    # If main.py outputs labels later, this catches them.
    if any(x in direction for x in ["out", "to center", "to left", "to right"]):
        if speed >= 12:
            return "🌬️ Strong HR Wind Boost", 8
        if speed >= 8:
            return "🌬️ HR Wind Boost", 5
        return "Light Wind Boost", 2

    if any(x in direction for x in ["in", "from center", "from left", "from right"]):
        if speed >= 12:
            return "🧊 Strong Wind Drag", -8
        if speed >= 8:
            return "Wind Drag", -5
        return "Light Wind Drag", -2

    if speed >= 12:
        return "Crosswind / Unknown Direction", 1

    return "Neutral Wind", 0

def pitch_matchup(row):
    existing = safe(row, pitch_matchup_col, "")
    if str(existing).strip() and existing != "N/A":
        return str(existing)

    batter_hand = str(safe(row, hand_col, "Unknown"))
    pitcher_hand = str(safe(row, pitcher_hand_col, "Unknown"))
    primary = str(safe(row, pitch_mix_col, "Fastball/Breaking Mix"))

    if batter_hand == "L" and pitcher_hand == "R":
        return f"Split edge check: LHB vs RHP • Pitch mix: {primary}"
    if batter_hand == "R" and pitcher_hand == "L":
        return f"Split edge check: RHB vs LHP • Pitch mix: {primary}"
    if pitcher_hand in ["L", "R"]:
        return f"Same-side matchup check • Pitch mix: {primary}"
    return f"Pitch-type matchup pending • Pitch mix: {primary}"

def adjusted_strength(row):
    base = to_float(safe(row, conf_col, safe(row, rating_col, 70)), 70)
    _, wind_boost = wind_impact(row)

    # Small pitch-matchup foundation boost if split is favorable.
    batter_hand = str(safe(row, hand_col, "Unknown"))
    pitcher_hand = str(safe(row, pitcher_hand_col, "Unknown"))
    split_boost = 0
    if (batter_hand == "L" and pitcher_hand == "R") or (batter_hand == "R" and pitcher_hand == "L"):
        split_boost = 2.5

    return round(max(1, min(99, base + wind_boost + split_boost)), 1)

@st.cache_data(ttl=3600)
def initials_image(name):
    initials = "".join([part[0].upper() for part in str(name).split()[:2]]) or "HR"
    svg = f"""
    <svg xmlns="http://www.w3.org/2000/svg" width="160" height="160">
      <rect width="160" height="160" rx="28" fill="#111827"/>
      <circle cx="80" cy="80" r="58" fill="#1e293b" stroke="#a855f7" stroke-width="5"/>
      <text x="50%" y="55%" text-anchor="middle" fill="#f8fafc"
            font-size="40" font-weight="900" font-family="Arial">{initials}</text>
    </svg>
    """
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()

@st.cache_data(ttl=3600)
def mlb_img(pid):
    try:
        pid = str(int(float(pid)))
        return f"https://img.mlbstatic.com/mlb-photos/image/upload/w_160,q_auto:best/v1/people/{pid}/headshot/67/current"
    except Exception:
        return ""

def get_image(row):
    pid = safe(row, id_col, "")
    if str(pid).strip() and str(pid).lower() not in ["nan", "n/a", ""]:
        url = mlb_img(pid)
        if url:
            return url
    return initials_image(safe(row, player_col, "Player"))

def split_text(text, fallback):
    text = str(text).strip()
    if not text or text.lower() in ["nan", "n/a", "none"]:
        text = fallback
    chunks = []
    text = text.replace(". ", ".|").replace("; ", ";|")
    for part in text.split("|"):
        part = part.strip()
        if part:
            chunks.append(part)
    return chunks[:7]

# Add derived fields.
df["_adjusted_strength"] = df.apply(adjusted_strength, axis=1)
df["_real_hr_prob"] = df["_adjusted_strength"].apply(true_hr_probability_from_strength)
df["_profile_label"] = df.apply(lambda r: profile_tag(r["_adjusted_strength"], safe(r, risk_col, "N/A"))[0], axis=1)

# =========================================================
# HEADER
# =========================================================
header_left, header_right = st.columns([2.3, 1.1])
with header_left:
    st.markdown('<div class="premium-title">⚾ HR MACHINE PRO</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="premium-subtitle">PREMIUM HOME RUN PREDICTION ENGINE</div>',
        unsafe_allow_html=True,
    )
    st.caption("Strength score is model confidence. Real HR probability is shown separately.")

with header_right:
    st.write("")
    st.write("")
    st.success(f"Model Active • Updated {datetime.now().strftime('%I:%M %p')}")


def parse_game_datetime(row):
    value = safe(row, game_datetime_utc_col, "")
    try:
        raw = str(value)
        if not raw or raw == "N/A":
            return None
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        return None

def countdown_text(row):
    dt = parse_game_datetime(row)
    if dt is None:
        return "Countdown: TBD"

    now = datetime.now(timezone.utc)
    diff = (dt - now).total_seconds()

    if diff > 0:
        hours = int(diff // 3600)
        minutes = int((diff % 3600) // 60)
        if hours >= 24:
            days = hours // 24
            rem_hours = hours % 24
            return f"Starts in {days}d {rem_hours}h"
        if hours >= 1:
            return f"Starts in {hours}h {minutes}m"
        return f"Starts in {minutes}m"

    # Simple post-start status estimate
    elapsed = abs(diff)
    if elapsed <= 4.5 * 3600:
        return "Live / In Progress"
    return "Final / Completed"


def game_status_badge(row):
    dt = parse_game_datetime(row)
    if dt is None:
        return "⚪ TBD"

    now = datetime.now(timezone.utc)
    diff = (dt - now).total_seconds()

    if diff > 0:
        if diff <= 60 * 60:
            return "🟡 Starting Soon"
        return "🟣 Upcoming"

    if abs(diff) <= 4.5 * 3600:
        return "🟢 LIVE"

    return "⚫ Final"


def get_recent_hr_chart_df(row):
    raw = safe(row, recent_hr_chart_col, "[]")
    try:
        data = json.loads(raw)
        if not isinstance(data, list):
            return pd.DataFrame()
        return pd.DataFrame(data)
    except Exception:
        return pd.DataFrame()

def render_recent_hr_chart(row):
    chart_df = get_recent_hr_chart_df(row)
    if chart_df.empty or "HR" not in chart_df.columns:
        st.info("No recent game-log chart data found for this player yet.")
        return

    chart_df["HR"] = pd.to_numeric(chart_df["HR"], errors="coerce").fillna(0)

    fig = go.Figure()

    fig.add_trace(go.Bar(
        x=chart_df["Game"],
        y=chart_df["HR"],
        customdata=chart_df[["Date", "Opponent", "Days Ago"]] if all(c in chart_df.columns for c in ["Date", "Opponent", "Days Ago"]) else None,
        hovertemplate="<b>%{customdata[0]}</b><br>Opponent: %{customdata[1]}<br>HR: %{y}<br>Days ago: %{customdata[2]}<extra></extra>",
        marker=dict(
            color=chart_df["HR"],
            colorscale=[[0, "rgba(148,163,184,0.20)"], [0.5, "rgba(34,197,94,0.85)"], [1, "rgba(132,204,22,1)"]],
            line=dict(width=0),
        ),
        name="Home Runs",
    ))

    fig.add_hline(
        y=0.5,
        line_width=2,
        line_color="rgba(148,163,184,0.65)",
    )

    fig.update_layout(
        height=300,
        margin=dict(l=20, r=20, t=20, b=20),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#e5e7eb", size=11),
        xaxis=dict(showgrid=False, tickangle=0),
        yaxis=dict(showgrid=True, gridcolor="rgba(148,163,184,0.16)", rangemode="tozero", dtick=1),
        bargap=0.45,
        hoverlabel=dict(bgcolor="#111827", font_size=13),
    )

    st.plotly_chart(fig, use_container_width=True)


def recent_hr_summary(row):
    count = safe(row, last_5_hr_count_col, 0)
    days = safe(row, last_hr_days_col, "N/A")
    if str(count) == "0":
        return "Last 5 HR: none logged"
    if str(days) == "0":
        ago = "last HR today"
    elif str(days) == "1":
        ago = "last HR 1 day ago"
    elif str(days) == "N/A":
        ago = "last HR date N/A"
    else:
        ago = f"last HR {days} days ago"
    return f"Last 5 HR total: {count} • {ago}"


def slate_status_text(dataframe):
    if dataframe.empty:
        return "No games found"

    times = []
    for _, r in dataframe.iterrows():
        dt = parse_game_datetime(r)
        if dt is not None:
            times.append(dt)

    if not times:
        return "Slate time TBD"

    now = datetime.now(timezone.utc)
    upcoming = [t for t in times if t > now]
    live = [t for t in times if t <= now and (now - t).total_seconds() <= 4.5 * 3600]

    if live:
        return f"🟢 Live slate • {len(live)} game(s) in progress"
    if upcoming:
        next_game = min(upcoming)
        seconds = (next_game - now).total_seconds()
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        if hours >= 24:
            return f"🟣 Upcoming slate • first game in {hours//24}d {hours%24}h"
        if hours >= 1:
            return f"🟣 Upcoming slate • first game in {hours}h {minutes}m"
        return f"🟣 Upcoming slate • first game in {minutes}m"

    return "⚪ Slate completed"


# =========================================================
# FILTERS
# =========================================================
with st.container(border=True):
    c0, c1, c2, c3, c4, c5 = st.columns([1.0, 1.55, 1.15, 1.0, 1.2, 1.0])

    with c0:
        slate_view = st.selectbox("Slate", ["Today", "Tomorrow", "All"], index=2)

    with c1:
        search = st.text_input("Search Player", placeholder="Judge, Ohtani, Soto...")

    with c2:
        teams = ["All Teams"]
        if team_col:
            teams += sorted(df[team_col].dropna().astype(str).unique().tolist())
        team_filter = st.selectbox("Team", teams)

    with c3:
        risk_filter = st.selectbox("Risk", ["All", "LOW", "MED", "HIGH"])

    with c4:
        min_strength = st.slider("Min Strength Score", 0, 100, 50)

    with c5:
        show_limit = st.selectbox("Show HR Props", [25, 50, 75, 100, 150, 250], index=1)

    st.caption("Tip: Use All slate when searching for a specific player like Mike Trout.")

# =========================================================
# FILTER LOGIC
# =========================================================
filtered = df.copy()

if slate_type_col and slate_view != "All":
    filtered = filtered[filtered[slate_type_col].astype(str).str.upper() == slate_view.upper()]

if search:
    filtered = filtered[filtered[player_col].astype(str).str.contains(search, case=False, na=False)]

if team_col and team_filter != "All Teams":
    filtered = filtered[filtered[team_col].astype(str) == team_filter]

if risk_col and risk_filter != "All":
    filtered = filtered[filtered[risk_col].astype(str).str.upper() == risk_filter]

filtered = filtered[pd.to_numeric(filtered["_adjusted_strength"], errors="coerce").fillna(0) >= min_strength]
filtered = filtered.sort_values("_adjusted_strength", ascending=False)
display_df = filtered.head(show_limit)

# =========================================================
# METRICS
# =========================================================
m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("HR Props", len(filtered))
m2.metric("Avg Strength", f"{filtered['_adjusted_strength'].mean():.1f}" if len(filtered) else "N/A")
m3.metric("Avg Real HR%", f"{filtered['_real_hr_prob'].mean():.1f}%" if len(filtered) else "N/A")
m4.metric("Elite Profiles", int((filtered["_adjusted_strength"] >= 90).sum()))
m5.metric("Low Risk", int((filtered[risk_col].astype(str).str.upper() == "LOW").sum()) if risk_col else 0)


# =========================================================
# LIVE SLATE STATUS
# =========================================================
with st.container(border=True):
    s1, s2, s3 = st.columns([1.3, 1.3, 2.4])
    s1.metric("Selected Slate", slate_view)
    s2.metric("Visible Games", int(display_df["game"].nunique()) if "game" in display_df.columns and len(display_df) else 0)
    s3.metric("Live Slate Status", slate_status_text(display_df))

# =========================================================
# TOP TARGETS
# =========================================================
st.subheader("🔥 Top HR Targets")
st.caption("Best next-day HR profiles after wind and split adjustment.")

top_cols = st.columns(5)
for i, (_, row) in enumerate(filtered.head(5).iterrows()):
    strength = row["_adjusted_strength"]
    risk = safe(row, risk_col, "N/A")
    tag, _ = profile_tag(strength, risk)
    wind_text, _ = wind_impact(row)

    with top_cols[i]:
        with st.container(border=True):
            st.image(get_image(row), width=78)
            st.caption(f"#{i+1} TARGET • {tag}")
            st.markdown(f"### {safe(row, player_col)}")
            st.caption(f"{safe(row, team_col, 'MLB')} vs {safe(row, pitcher_col, 'Projected Starter')}")
            st.caption(f"🕒 {safe(row, game_day_col, 'TBD')} • {safe(row, game_date_display_col, 'TBD')} • {safe(row, game_time_col, 'TBD')}")
            st.caption(game_status_badge(row))
            st.caption(recent_hr_summary(row))
            st.metric("Real HR Probability", f"{row['_real_hr_prob']}%")
            st.write(f"**Strength:** {strength}/100")
            st.progress(int(max(0, min(100, strength))))
            st.caption(f"{risk_emoji(risk)} • {wind_text}")

# =========================================================
# BOARD
# =========================================================
st.subheader("📊 Home Run Prop Board")
st.caption(f"Showing {len(display_df)} of {len(filtered)} HR props. No sportsbook odds included yet.")

if display_df.empty:
    st.warning("No HR props match your filters.")
    st.stop()

# Header row
h = st.columns([0.75, 2.35, 1.1, 1.05, 1.0, 1.15, 1.25, 1.05, 2.35])
headers = ["", "PLAYER", "REAL HR%", "STRENGTH", "POWER", "PITCHER", "MATCHUP", "RISK", "CONTEXT"]
for col_obj, label in zip(h, headers):
    col_obj.caption(label)

for _, row in display_df.iterrows():
    strength = row["_adjusted_strength"]
    real_prob = row["_real_hr_prob"]
    risk = safe(row, risk_col, "N/A")
    tag, _ = profile_tag(strength, risk)
    wind_text, wind_boost = wind_impact(row)

    with st.container(border=True):
        c = st.columns([0.75, 2.35, 1.1, 1.05, 1.0, 1.15, 1.25, 1.05, 2.35])

        with c[0]:
            st.image(get_image(row), width=58)

        with c[1]:
            st.markdown(f"### {safe(row, player_col)}")
            st.caption(f"{safe(row, team_col, 'MLB')} • {safe(row, pos_col, 'BAT')} • Bat: {safe(row, hand_col, 'Unknown')}")
            st.caption(tag)

        with c[2]:
            st.metric("", f"{real_prob}%")

        with c[3]:
            st.metric("", f"{strength}")

        with c[4]:
            power_val = safe(row, barrel_col, safe(row, hardhit_col, "N/A"))
            st.metric("", power_val)
            st.caption("Barrel/HH")

        with c[5]:
            st.metric("", safe(row, pitcher_hr9_col, "N/A"))
            st.caption(f"HR/9 • {safe(row, pitcher_hand_col, 'P?')}")

        with c[6]:
            st.write(pitch_matchup(row))
            st.caption(wind_text)

        with c[7]:
            st.write(f"### {risk_emoji(risk)}")

        with c[8]:
            st.write(f"**Game Time:** {safe(row, game_day_col, 'TBD')} • {safe(row, game_date_display_col, 'TBD')} • {safe(row, game_time_col, 'TBD')}")
            st.write(f"**Status:** {game_status_badge(row)}")
            st.write(f"**Recent HR:** {recent_hr_summary(row)}")
            st.write(f"**Pitcher:** {safe(row, pitcher_col, 'Projected Starter')}")
            st.write(f"**Park:** {safe(row, park_col, 'Neutral')}")
            st.write(f"**Weather:** {safe(row, weather_col, 'Neutral')}")
            st.write(f"**Wind/Temp:** {safe(row, wind_col, 'N/A')} mph • {safe(row, temp_col, 'N/A')}°")
            st.write(f"**Lineup:** {safe(row, lineup_col, 'Projected')}")

        st.progress(int(max(0, min(100, strength))))

# =========================================================
# RESEARCH ENGINE
# =========================================================
st.subheader("🧠 Research Engine")

selected_player = st.selectbox("Select HR Player", display_df[player_col].astype(str).tolist())
selected = display_df[display_df[player_col].astype(str) == selected_player].iloc[0]

selected_strength = selected["_adjusted_strength"]
selected_prob = selected["_real_hr_prob"]
selected_risk = safe(selected, risk_col, "N/A")
selected_tag, _ = profile_tag(selected_strength, selected_risk)
selected_wind, selected_wind_boost = wind_impact(selected)

with st.container(border=True):
    r1, r2, r3 = st.columns([1.15, 1.75, 2.25])

    with r1:
        st.image(get_image(selected), width=165)
        st.markdown(f"## {safe(selected, player_col)}")
        st.caption(f"{safe(selected, team_col, 'MLB')} • {safe(selected, pos_col, 'BAT')} • Bat: {safe(selected, hand_col, 'Unknown')}")
        st.caption(f"🕒 Plays: {safe(selected, game_day_col, 'TBD')} • {safe(selected, game_date_display_col, 'TBD')} • {safe(selected, game_time_col, 'TBD')}")
        st.write(selected_tag)
        st.metric("Real HR Probability", f"{selected_prob}%")
        st.metric("Strength Score", f"{selected_strength}/100")
        st.write(f"**Risk:** {risk_emoji(selected_risk)}")

    with r2:
        st.markdown("### HR Model Breakdown")

        breakdown = [
            ("Adjusted Strength", selected_strength, "Overall model confidence after matchup context."),
            ("True HR Chance", selected_prob * 5.5, "Scaled display only. Actual probability shown on card."),
            ("Power Indicators", to_float(safe(selected, barrel_col, safe(selected, hardhit_col, 60)), 60), "Barrel / hard-hit proxy."),
            ("Pitcher HR Weakness", 60 + to_float(safe(selected, pitcher_hr9_col, 1.1), 1.1) * 13, "Pitcher HR/9 pressure."),
            ("Wind Impact", 70 + selected_wind_boost * 3, selected_wind),
        ]

        for label, value, note in breakdown:
            value = int(max(0, min(100, value)))
            st.write(f"**{label}**")
            st.progress(value)
            st.caption(note)

    with r3:
        st.markdown("### Last 5 Home Runs")
        st.info(safe(selected, last_5_hr_col, "No HR game log found"))
        render_recent_hr_chart(selected)

        st.markdown("### Why He Can Homer")

        homer_fallback = (
            f"Strength score {selected_strength}/100. "
            f"Real HR probability {selected_prob}%. "
            f"Opponent pitcher: {safe(selected, pitcher_col, 'Projected Starter')}. "
            f"Park/weather: {safe(selected, park_col, 'Neutral')} / {safe(selected, weather_col, 'Neutral')}. "
            f"Wind read: {selected_wind}. "
            f"Pitch matchup: {pitch_matchup(selected)}."
        )

        for line in split_text(safe(selected, why_homer_col, safe(selected, reason_col, "")), homer_fallback):
            st.success(line)

        st.markdown("### Why He Can Fail")
        fail_fallback = (
            "Home runs are low-frequency events. "
            "Lineup, weather, pitcher usage, and pitch selection can change before first pitch."
        )

        for line in split_text(safe(selected, why_fail_col, ""), fail_fallback):
            st.error(line)

st.caption("HR Machine Pro • Premium native UI • Player images restored • Wind + pitch matchup foundation enabled.")
