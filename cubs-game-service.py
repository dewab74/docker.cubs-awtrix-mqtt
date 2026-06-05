#!/usr/bin/env python3
"""Cubs game MQTT service — continuously polls MLB API and pushes live updates to AWTRIX."""

import json
import os
import signal
import time
from datetime import datetime, timedelta
from urllib.parse import urlparse

import paho.mqtt.client as mqtt
import statsapi
from dateutil import tz

TEAM_ID = 112  # Chicago Cubs
TEAM_SHORT_NAME = "Cubs"
NL_LEAGUE_ID = 104
NL_CENTRAL_DIVISION_ID = 205
LOCAL_TZ = tz.gettz("America/Chicago")

AWTRIX_DEVICE = os.getenv("AWTRIX_DEVICE", "awtrix")
MQTT_TOPIC = os.getenv("MQTT_TOPIC", f"{AWTRIX_DEVICE}/custom/cubs_game_next")
MQTT_STANDINGS_TOPIC = os.getenv("MQTT_STANDINGS_TOPIC", f"{AWTRIX_DEVICE}/custom/cubs_standings")
MQTT_ICON = os.getenv("MQTT_ICON", "40217")
MQTT_WIN_ICON = os.getenv("MQTT_WIN_ICON", "74405")

# Bases-state icons (runner on 1st=bit0, 2nd=bit1, 3rd=bit2)
BASES_ICONS = {
    0b000: "47262",  # empty
    0b001: "47263",  # 1st
    0b010: "47264",  # 2nd
    0b100: "47266",  # 3rd
    0b011: "47267",  # 1st + 2nd
    0b101: "47268",  # 1st + 3rd
    0b110: "47269",  # 2nd + 3rd
    0b111: "47265",  # loaded
}
MQTT_DURATION = int(os.getenv("MQTT_DURATION", "5"))
MQTT_DURATION_LIVE = int(os.getenv("MQTT_DURATION_LIVE", "7"))
MQTT_SCROLL = os.getenv("MQTT_SCROLL", "true").lower() == "true"
MQTT_COLOR = os.getenv("MQTT_COLOR", "#002C5F")
MQTT_CLIENT_ID = os.getenv("MQTT_CLIENT_ID", "cubs-game-service")
MQTT_RETAIN = os.getenv("MQTT_RETAIN", "false").lower() == "true"

# Poll intervals in seconds
POLL_NO_GAMES = int(os.getenv("POLL_NO_GAMES", str(4 * 3600)))  # 4 h — off-season
POLL_UPCOMING = int(os.getenv("POLL_UPCOMING", "900"))  # 15 min — future game
POLL_TODAY = int(os.getenv("POLL_TODAY", "300"))  # 5 min — game today, not started
POLL_LIVE = int(os.getenv("POLL_LIVE", "30"))  # 30 s — game in progress
POLL_FINAL = int(os.getenv("POLL_FINAL", "300"))  # 5 min — game ended today

# Game statuses considered "live" by the MLB Stats API
LIVE_STATUSES = {"In Progress", "Delayed: Rain", "Delayed"}
FINAL_STATUSES = {"Final", "Game Over", "Completed Early", "Completed Early: Rain"}

# ── team colors ────────────────────────────────────────────────────────────────

RAW_MLB_TEAM_COLORS = {
    108: ["#BA0021", "#003263"],
    109: ["#A71930", "#000000", "#E3D4AD", "#30CED8"],
    110: ["#DF4601", "#000000"],
    111: ["#BD3039", "#0D2B56"],
    112: ["#0E3386", "#CC3433"],
    113: ["#C6011F", "#000000"],
    114: ["#0C2340", "#E31937"],
    115: ["#33006F", "#000000", "#C4CED4"],
    116: ["#0C2340", "#FA4616"],
    117: ["#EB6E1F", "#002D62"],
    118: ["#004687", "#BD9B60"],
    119: ["#005A9C", "#EF3E42", "#A5ACAF"],
    120: ["#AB0003", "#14225A"],
    121: ["#002D72", "#FF5910"],
    133: ["#003831", "#EFB21E"],
    134: ["#FDB827", "#000000"],
    135: ["#2F241D", "#FFC425"],
    136: ["#005C5C", "#0C2C56", "#C4CED4"],
    137: ["#FD5A1E", "#27251F", "#EFD19F"],
    138: ["#C41E3A", "#0B2240", "#FEDB00"],
    139: ["#092C5C", "#8FBCE6", "#F5D130"],
    140: ["#003278", "#C0111F"],
    141: ["#134A8E", "#1D2D5C", "#E8291C"],
    142: ["#002B5C", "#D31145"],
    143: ["#E81828", "#002D72"],
    144: ["#CE1141", "#13274F", "#EAAA00"],
    145: ["#27251F", "#C4CED4"],
    146: ["#00A3E0", "#EF3340", "#000000"],
    147: ["#0C2340", "#C4CED4"],
    158: ["#12284B", "#FFC52F"],
}


def _is_near_black(color: str) -> bool:
    r, g, b = (int(color[i : i + 2], 16) for i in (1, 3, 5))
    return max(r, g, b) < 40


def _primary_palette(raw: dict) -> dict:
    out = {}
    for team_id, colors in raw.items():
        if not colors:
            continue
        primary = colors[0]
        out[team_id] = colors[1] if _is_near_black(primary) and len(colors) > 1 else primary
    return out


MLB_TEAM_COLORS = _primary_palette(RAW_MLB_TEAM_COLORS)

MLB_TEAM_CODES = {
    "LAA": MLB_TEAM_COLORS[108],
    "ARI": MLB_TEAM_COLORS[109],
    "BAL": MLB_TEAM_COLORS[110],
    "BOS": MLB_TEAM_COLORS[111],
    "CHC": MLB_TEAM_COLORS[112],
    "CIN": MLB_TEAM_COLORS[113],
    "CLE": MLB_TEAM_COLORS[114],
    "COL": MLB_TEAM_COLORS[115],
    "DET": MLB_TEAM_COLORS[116],
    "HOU": MLB_TEAM_COLORS[117],
    "KC": MLB_TEAM_COLORS[118],
    "LAD": MLB_TEAM_COLORS[119],
    "WSH": MLB_TEAM_COLORS[120],
    "NYM": MLB_TEAM_COLORS[121],
    "OAK": MLB_TEAM_COLORS[133],
    "PIT": MLB_TEAM_COLORS[134],
    "SD": MLB_TEAM_COLORS[135],
    "SEA": MLB_TEAM_COLORS[136],
    "SF": MLB_TEAM_COLORS[137],
    "STL": MLB_TEAM_COLORS[138],
    "TB": MLB_TEAM_COLORS[139],
    "TEX": MLB_TEAM_COLORS[140],
    "TOR": MLB_TEAM_COLORS[141],
    "MIN": MLB_TEAM_COLORS[142],
    "PHI": MLB_TEAM_COLORS[143],
    "ATL": MLB_TEAM_COLORS[144],
    "CWS": MLB_TEAM_COLORS[145],
    "MIA": MLB_TEAM_COLORS[146],
    "NYY": MLB_TEAM_COLORS[147],
    "MIL": MLB_TEAM_COLORS[158],
}


# ── helpers ────────────────────────────────────────────────────────────────────


def short_team_name(game: dict, side: str) -> str:
    for key in (f"{side}_name_abbrev", f"{side}_abbrev", f"{side}_team_abbrev", f"{side}_file_code"):
        val = game.get(key)
        if val:
            return val
    name = game.get(f"{side}_name") or game.get(f"{side}_team_name")
    return name.split()[-1] if name else side.capitalize()


def team_color_hex(team_id, team_code=None) -> str:
    if team_id and team_id in MLB_TEAM_COLORS:
        return MLB_TEAM_COLORS[team_id]
    if team_code and team_code.upper() in MLB_TEAM_CODES:
        return MLB_TEAM_CODES[team_code.upper()]
    return "#FFFFFF"


def format_game_time(game_time: datetime) -> str:
    return game_time.strftime("%I:%M %p").lstrip("0")


def format_countdown(days: int) -> str:
    if days == 0:
        return "Today"
    if days == 1:
        return "Tomorrow"
    return f"{days}d"


def format_ordinal(value) -> str:
    n = int(value)
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def format_inning(game: dict) -> str:
    inning = game.get("current_inning")
    state = game.get("inning_state", "")
    if not inning:
        return ""
    abbrev = {"Top": "T", "Bottom": "B", "Mid": "M", "End": "E"}.get(state, state[:1])
    return f"{abbrev}{inning}"


# ── MQTT ───────────────────────────────────────────────────────────────────────


def _mqtt_client():
    broker_url = os.getenv("MQTT_BROKER_URL", "mqtt://localhost:1883")
    parsed = urlparse(broker_url)
    host = parsed.hostname or "localhost"
    port = parsed.port or 1883
    username = os.getenv("MQTT_USERNAME") or parsed.username
    password = os.getenv("MQTT_PASSWORD") or parsed.password

    kw = {"client_id": MQTT_CLIENT_ID, "protocol": mqtt.MQTTv311}
    try:
        kw["callback_api_version"] = mqtt.CallbackAPIVersion.VERSION2
    except AttributeError:
        pass

    client = mqtt.Client(**kw)
    if username:
        client.username_pw_set(username, password)
    return client, host, port


def publish_mqtt(text_segments, topic: str, icon: str = MQTT_ICON, duration: int = MQTT_DURATION) -> None:
    client, host, port = _mqtt_client()
    payload = {
        "icon": icon,
        "text": text_segments,
        "duration": duration,
        "scroll": MQTT_SCROLL,
        "color": MQTT_COLOR or "#FFFFFF",
    }
    try:
        rc = client.connect(host, port, keepalive=60)
        if rc != mqtt.MQTT_ERR_SUCCESS:
            print(f"[mqtt] connect failed: {rc}")
            return
        client.loop_start()
        info = client.publish(topic, json.dumps(payload), qos=1, retain=MQTT_RETAIN)
        info.wait_for_publish(timeout=5)
        client.loop(0.2)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            print(f"[mqtt] publish failed: {info.rc}")
        client.loop_stop()
        client.disconnect()
        print(f"[mqtt] {topic} → {json.dumps(payload)}")
    except Exception as exc:
        print(f"[mqtt] error: {exc}")


# ── game state ─────────────────────────────────────────────────────────────────


def fetch_game_state(today):
    """Return (state, game_or_None) for Cubs today/upcoming.

    States: NO_GAMES | UPCOMING | TODAY_SCHEDULED | LIVE | FINAL | POSTPONED
    """
    today_str = today.strftime("%Y-%m-%d")
    season_end = today + timedelta(days=365)

    try:
        today_games = statsapi.schedule(start_date=today_str, end_date=today_str, team=TEAM_ID)
    except Exception as exc:
        print(f"[api] error fetching today's schedule: {exc}")
        return "ERROR", None

    for game in today_games:
        status = game.get("status", "")
        if status in FINAL_STATUSES:
            return "FINAL", game
        if status in LIVE_STATUSES:
            return "LIVE", game
        if status == "Postponed":
            return "POSTPONED", game
        # Preview / Scheduled / Warmup not yet counted as live
        return "TODAY_SCHEDULED", game

    # No game today — find next upcoming game
    try:
        future_games = statsapi.schedule(
            start_date=(today + timedelta(days=1)).strftime("%Y-%m-%d"),
            end_date=season_end.strftime("%Y-%m-%d"),
            team=TEAM_ID,
        )
    except Exception as exc:
        print(f"[api] error fetching upcoming schedule: {exc}")
        return "ERROR", None

    if future_games:
        return "UPCOMING", future_games[0]

    return "NO_GAMES", None


# ── display builders ───────────────────────────────────────────────────────────

WHITE = "#FFFFFF"


def _team_colors(game):
    away_color = team_color_hex(
        game.get("away_id") or game.get("away_team_id"),
        game.get("away_name_abbrev") or game.get("away_file_code"),
    )
    home_color = team_color_hex(
        game.get("home_id") or game.get("home_team_id"),
        game.get("home_name_abbrev") or game.get("home_file_code"),
    )
    return away_color, home_color


def segments_upcoming(game, today) -> list:
    """Matchup + date/time + countdown — used for UPCOMING and TODAY_SCHEDULED."""
    game_time_utc = datetime.strptime(game["game_datetime"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=tz.UTC)
    game_time_local = game_time_utc.astimezone(LOCAL_TZ)
    countdown_days = (game_time_local.date() - today).days

    away = short_team_name(game, "away")
    home = short_team_name(game, "home")
    away_color, home_color = _team_colors(game)
    game_time_text = format_game_time(game_time_local)
    date_text = f"{game_time_local.strftime('%m/%d')} " if countdown_days != 0 else ""

    segs = [
        {"t": away, "c": away_color},
        {"t": " at ", "c": WHITE},
        {"t": home, "c": home_color},
        {"t": " ", "c": WHITE},
    ]
    if date_text:
        segs.append({"t": date_text, "c": WHITE})
    segs += [
        {"t": game_time_text, "c": WHITE},
        {"t": f" ({format_countdown(countdown_days)})", "c": WHITE},
    ]
    return segs


def segments_score(game, suffix: str = "") -> list:
    """Score line: 'CHC 3 · OPP 1 [suffix]'"""
    away = short_team_name(game, "away")
    home = short_team_name(game, "home")
    away_score = game.get("away_score", 0)
    home_score = game.get("home_score", 0)
    away_color, home_color = _team_colors(game)

    segs = [
        {"t": away, "c": away_color},
        {"t": f" {away_score}", "c": WHITE},
        {"t": " · ", "c": WHITE},
        {"t": home, "c": home_color},
        {"t": f" {home_score}", "c": WHITE},
    ]
    if suffix:
        segs.append({"t": f" {suffix}", "c": WHITE})
    return segs


def cubs_won(game) -> bool:
    away = short_team_name(game, "away")
    home = short_team_name(game, "home")
    away_score = int(game.get("away_score", 0))
    home_score = int(game.get("home_score", 0))
    cubs_are_away = "CHC" in away.upper() or "CUB" in away.upper()
    cubs_are_home = "CHC" in home.upper() or "CUB" in home.upper()
    if cubs_are_away:
        return away_score > home_score
    if cubs_are_home:
        return home_score > away_score
    return False


# ── live bases icon ────────────────────────────────────────────────────────────


def fetch_live_details(game_pk) -> tuple[str, str]:
    """Return (bases_icon_id, count_str) for the current at-bat.

    count_str is formatted as 'B-S' (e.g. '2-1'). Falls back gracefully.
    """
    try:
        data = statsapi.get(
            "game",
            {
                "gamePk": game_pk,
                "fields": "liveData,linescore,offense,first,second,third,balls,strikes",
            },
        )
        linescore = data.get("liveData", {}).get("linescore", {})
        offense = linescore.get("offense", {})

        mask = (
            (0b001 if offense.get("first") else 0)
            | (0b010 if offense.get("second") else 0)
            | (0b100 if offense.get("third") else 0)
        )
        icon = BASES_ICONS.get(mask, BASES_ICONS[0b000])

        balls = linescore.get("balls", 0)
        strikes = linescore.get("strikes", 0)
        count_str = f"{balls}-{strikes}"

        print(f"[live] mask={mask:03b} → icon {icon}  count={count_str}")
        return icon, count_str
    except Exception as exc:
        print(f"[live] error fetching live details: {exc}")
        return MQTT_ICON, ""


# ── standings ──────────────────────────────────────────────────────────────────


def publish_standings(today) -> None:
    try:
        standings = statsapi.standings_data(
            leagueId=NL_LEAGUE_ID,
            division=NL_CENTRAL_DIVISION_ID,
            include_wildcard=False,
            date=today.strftime("%m/%d/%Y"),
        )
    except Exception as exc:
        print(f"[api] standings error: {exc}")
        return

    division = standings.get(NL_CENTRAL_DIVISION_ID)
    if not division:
        return
    cubs = next((t for t in division["teams"] if t.get("team_id") == TEAM_ID), None)
    if not cubs:
        return

    rank = format_ordinal(cubs["div_rank"])
    record = f"{cubs['w']}-{cubs['l']}"
    segs = [
        {"t": TEAM_SHORT_NAME, "c": MLB_TEAM_COLORS[TEAM_ID]},
        {"t": f" {rank} NL Central ({record})", "c": WHITE},
    ]
    publish_mqtt(segs, MQTT_STANDINGS_TOPIC)


# ── main loop ──────────────────────────────────────────────────────────────────

_running = True


def _handle_signal(signum, frame):
    global _running
    print(f"\n[service] signal {signum} received, shutting down…")
    _running = False


def run_service() -> None:
    global _running
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    print("[service] Cubs game MQTT service starting…")

    last_standings_publish = 0.0
    STANDINGS_INTERVAL = 1800  # publish standings every 30 min at most

    while _running:
        now = datetime.now(LOCAL_TZ)
        today = now.date()

        state, game = fetch_game_state(today)
        print(f"[service] state={state} time={now.strftime('%H:%M:%S')}")

        if state == "NO_GAMES":
            # Off-season or end of year — nothing to publish
            sleep_secs = POLL_NO_GAMES

        elif state == "ERROR":
            sleep_secs = 60  # back off on API errors

        elif state == "UPCOMING":
            segs = segments_upcoming(game, today)
            publish_mqtt(segs, MQTT_TOPIC)
            sleep_secs = POLL_UPCOMING

        elif state == "TODAY_SCHEDULED":
            segs = segments_upcoming(game, today)
            publish_mqtt(segs, MQTT_TOPIC)
            sleep_secs = POLL_TODAY

        elif state == "POSTPONED":
            # Treat like upcoming — show the next actual game instead
            try:
                season_end = today + timedelta(days=365)
                future_games = statsapi.schedule(
                    start_date=(today + timedelta(days=1)).strftime("%Y-%m-%d"),
                    end_date=season_end.strftime("%Y-%m-%d"),
                    team=TEAM_ID,
                )
                if future_games:
                    segs = segments_upcoming(future_games[0], today)
                    publish_mqtt(segs, MQTT_TOPIC)
            except Exception as exc:
                print(f"[api] postponed fallback error: {exc}")
            sleep_secs = POLL_UPCOMING

        elif state == "LIVE":
            icon, count_str = fetch_live_details(game.get("game_id"))
            inning_tag = format_inning(game)
            suffix = f"{inning_tag} {count_str}" if inning_tag else count_str
            segs = segments_score(game, suffix=suffix.strip())
            publish_mqtt(segs, MQTT_TOPIC, icon=icon, duration=MQTT_DURATION_LIVE)
            sleep_secs = POLL_LIVE

        elif state == "FINAL":
            won = cubs_won(game)
            icon = MQTT_WIN_ICON if won else MQTT_ICON
            segs = segments_score(game, suffix="FINAL")
            publish_mqtt(segs, MQTT_TOPIC, icon=icon)
            sleep_secs = POLL_FINAL

        else:
            sleep_secs = POLL_UPCOMING

        # Publish standings alongside game info (throttled)
        if state not in ("NO_GAMES", "ERROR") and (time.time() - last_standings_publish) >= STANDINGS_INTERVAL:
            publish_standings(today)
            last_standings_publish = time.time()

        next_poll = (now + timedelta(seconds=sleep_secs)).strftime("%H:%M:%S")
        print(f"[service] sleeping {sleep_secs}s (next poll at {next_poll})")

        # Sleep in short chunks so SIGTERM is handled quickly
        deadline = time.time() + sleep_secs
        while _running and time.time() < deadline:
            time.sleep(min(1.0, deadline - time.time()))

    print("[service] stopped.")


if __name__ == "__main__":
    run_service()
