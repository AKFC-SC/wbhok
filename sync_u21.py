import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests


# ============================================================
# CONFIG
#
# Fully separate from sync.py (First Team) on purpose: this script must never
# be able to affect the First Team Fixtures collection or its sync run, even
# if this file has a bug. Nothing here is imported by or imports sync.py.
# ============================================================

SM_TOKEN = os.environ["SPORTSMONKS_API_TOKEN"]
WF_TOKEN = os.environ["WEBFLOW_API_TOKEN"]

TEAM_ID = 280646
LEAGUE_ID = 3569

COLLECTION_ID = "6a8ffc2c6f62bbad44381165"

SM_BASE = "https://api.sportmonks.com/v3/football"
WF_BASE = "https://api.webflow.com/v2"

RIYADH_TZ = ZoneInfo("Asia/Riyadh")


# ============================================================
# HEADERS
# ============================================================

def sm_headers():
    return {"Accept": "application/json"}


def wf_headers():
    return {
        "Authorization": f"Bearer {WF_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


# ============================================================
# HELPERS
# ============================================================

def safe_text(value):
    if value is None:
        return ""
    return str(value)


def fixture_slug(fixture):
    return f"u21-fixture-{fixture.get('id', '')}"


def get_participants(fixture):
    participants = fixture.get("participants") or []
    home = None
    away = None
    for participant in participants:
        meta = participant.get("meta") or {}
        location = meta.get("location")
        if location == "home":
            home = participant
        elif location == "away":
            away = participant
    return home, away


def participant_name(participant):
    if not participant:
        return ""
    return safe_text(participant.get("name") or participant.get("short_code") or "")


def participant_id(participant):
    if not participant:
        return None
    return participant.get("id")


def fixture_name(fixture):
    home, away = get_participants(fixture)
    home_name = participant_name(home) or "Home"
    away_name = participant_name(away) or "Away"
    return f"{home_name} vs {away_name}"


def team_logo(participant):
    if not participant:
        return None
    image_path = participant.get("image_path")
    if image_path:
        return {"url": image_path, "alt": participant_name(participant)}
    return None


def league_logo(fixture):
    league = fixture.get("league") or {}
    image_path = league.get("image_path")
    if image_path:
        return {"url": image_path, "alt": safe_text(league.get("name"))}
    return None


def fixture_date(fixture):
    value = fixture.get("starting_at")
    if not value:
        return ""
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    except Exception:
        return value


def fixture_time(fixture):
    value = fixture.get("starting_at")
    if not value:
        return ""
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        dt = dt.astimezone(RIYADH_TZ)
        return dt.strftime("%I:%M %p")
    except Exception:
        return ""


def get_score(fixture, team_id):
    if not team_id:
        return ""
    scores = fixture.get("scores") or []
    if isinstance(scores, dict):
        scores = scores.get("data") or []
    for score in scores:
        if score.get("participant_id") != team_id:
            continue
        if score.get("description") != "CURRENT":
            continue
        score_object = score.get("score") or {}
        goals = score_object.get("goals")
        if goals is not None:
            return safe_text(goals)
        goals = score.get("goals")
        if goals is not None:
            return safe_text(goals)
    return ""


# ============================================================
# SPORTSMONKS FIXTURES — U21
#
# Same team-scoped date-range endpoint as First Team, but additionally
# filtered to LEAGUE_ID (3569, Jawwy Elite League U21) since the U21 team
# may play in more than one competition and only this one is in scope.
# ============================================================

def sm_fixtures():
    today = datetime.now(timezone.utc).date()
    season_end = datetime(2027, 6, 30, tzinfo=timezone.utc).date()

    all_fixtures = []
    current_start = today

    while current_start <= season_end:
        current_end = min(current_start + timedelta(days=90), season_end)

        url = f"{SM_BASE}/fixtures/between/{current_start.isoformat()}/{current_end.isoformat()}/{TEAM_ID}"
        params = {
            "api_token": SM_TOKEN,
            "include": "participants;venue;league;scores;state",
            "per_page": 100,
        }

        print()
        print("SPORTSMONKS REQUEST (U21):", current_start, "->", current_end)

        response = requests.get(url, params=params, headers=sm_headers(), timeout=30)
        print("SPORTSMONKS STATUS:", response.status_code)

        if not response.ok:
            print("SPORTSMONKS RESPONSE:", response.text)
            response.raise_for_status()

        data = response.json()
        fixtures = data.get("data") or []
        print("Fixtures returned:", len(fixtures))

        all_fixtures.extend(fixtures)
        current_start = current_end + timedelta(days=1)

    # Deduplicate
    unique_fixtures = {}
    for fixture in all_fixtures:
        fixture_id = fixture.get("id")
        if fixture_id:
            unique_fixtures[str(fixture_id)] = fixture
    fixtures = list(unique_fixtures.values())

    # Filter to the U21 league only — this is the piece First Team sync
    # doesn't need (it has no cross-competition ambiguity to worry about).
    fixtures = [f for f in fixtures if f.get("league_id") == LEAGUE_ID]

    print()
    print("TOTAL AL KHOLOOD U21 FIXTURES (league", LEAGUE_ID, "):", len(fixtures))
    for fixture in fixtures:
        home, away = get_participants(fixture)
        league = fixture.get("league") or {}
        print(
            "U21 FIXTURE:", fixture.get("id"), "|",
            participant_name(home), "vs", participant_name(away), "|",
            league.get("name", ""), "| league_id=", fixture.get("league_id"),
        )
    print()

    return fixtures


# ============================================================
# WEBFLOW
# ============================================================

def get_collection():
    url = f"{WF_BASE}/collections/{COLLECTION_ID}"
    response = requests.get(url, headers=wf_headers(), timeout=30)
    print("COLLECTION STATUS:", response.status_code)
    response.raise_for_status()
    return response.json()


def wf_items():
    url = f"{WF_BASE}/collections/{COLLECTION_ID}/items"
    params = {"limit": 100}
    response = requests.get(url, headers=wf_headers(), params=params, timeout=30)
    print("ITEMS STATUS:", response.status_code)
    if not response.ok:
        print("ITEMS RESPONSE:", response.text)
        response.raise_for_status()
    data = response.json()
    items = data.get("items") or []
    print("Existing U21 Webflow items:", len(items))
    return items


def fixture_field_data(fixture, include_logos=False):
    home, away = get_participants(fixture)
    home_name = participant_name(home)
    away_name = participant_name(away)
    home_id = participant_id(home)
    away_id = participant_id(away)

    venue = fixture.get("venue") or {}
    league = fixture.get("league") or {}
    state = fixture.get("state") or {}

    field_data = {
        "name": fixture_name(fixture),
        "slug": fixture_slug(fixture),
        "home-team-name": home_name,
        "away-team-name": away_name,
        "starting-at": fixture_date(fixture),
        "time": fixture_time(fixture),
        "venue": safe_text(venue.get("name", "")),
        "league": safe_text(league.get("name", "")),
        "fixture-id": safe_text(fixture.get("id", "")),
        "state": safe_text(state.get("name", "")),
        "home-team-score": get_score(fixture, home_id),
        "away-team-score": get_score(fixture, away_id),
    }

    # Logos are only set when creating a new item, matching the First Team
    # sync's behavior (existing items keep whatever logo is already there).
    if include_logos:
        home_logo = team_logo(home)
        if home_logo:
            field_data["home-team-logo"] = home_logo

        away_logo = team_logo(away)
        if away_logo:
            field_data["away-team-logo"] = away_logo

        tournament_logo = league_logo(fixture)
        if tournament_logo:
            field_data["tournament-logo"] = tournament_logo

    return field_data


def create_webflow_item(field_data):
    url = f"{WF_BASE}/collections/{COLLECTION_ID}/items"
    payload = {"fieldData": field_data}
    response = requests.post(url, headers=wf_headers(), json=payload, timeout=30)
    if not response.ok:
        print("CREATE STATUS:", response.status_code)
        print("CREATE RESPONSE:", response.text)
        print("CREATE PAYLOAD:", field_data)
        response.raise_for_status()
    print("Created U21 fixture:", field_data.get("fixture-id"))


def update_webflow_item(item_id, field_data):
    url = f"{WF_BASE}/collections/{COLLECTION_ID}/items/{item_id}"
    payload = {"fieldData": field_data}
    response = requests.patch(url, headers=wf_headers(), json=payload, timeout=30)
    print("UPDATE STATUS:", response.status_code)
    if not response.ok:
        print("UPDATE RESPONSE:", response.text)
        print("UPDATE PAYLOAD:", field_data)
        response.raise_for_status()
    print("Updated U21 fixture:", field_data.get("fixture-id"))


# ============================================================
# SYNC
# ============================================================

def sync_u21_fixtures():
    collection = get_collection()
    print("U21 collection fields:", [f.get("slug") for f in collection.get("fields", [])])

    fixtures = sm_fixtures()
    existing_items = wf_items()

    existing_by_fixture_id = {}
    for item in existing_items:
        field_data = item.get("fieldData") or {}
        fixture_id = field_data.get("fixture-id")
        if fixture_id:
            existing_by_fixture_id[safe_text(fixture_id)] = item

    created = 0
    updated = 0

    for fixture in fixtures:
        fixture_id = safe_text(fixture.get("id"))
        if not fixture_id:
            continue

        print()
        print("Processing U21 fixture:", fixture_id)

        existing = existing_by_fixture_id.get(fixture_id)

        if existing:
            print("Updating U21 fixture", fixture_id)
            field_data = fixture_field_data(fixture, include_logos=False)
            update_webflow_item(existing["id"], field_data)
            updated += 1
        else:
            print("Creating U21 fixture", fixture_id)
            field_data = fixture_field_data(fixture, include_logos=True)
            create_webflow_item(field_data)
            created += 1

    print()
    print("========================================")
    print(f"U21 fixtures received: {len(fixtures)}")
    print(f"U21 Webflow items created: {created}")
    print(f"U21 Webflow items updated: {updated}")
    print("========================================")


def main():
    sync_u21_fixtures()


if __name__ == "__main__":
    main()
