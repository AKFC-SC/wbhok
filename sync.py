import os
from datetime import datetime, timedelta, timezone

import requests


# ============================================================
# CONFIG
# ============================================================

SM_TOKEN = os.environ["SPORTSMONKS_API_TOKEN"]
WF_TOKEN = os.environ["WEBFLOW_API_TOKEN"]

TEAM_ID = 232744

COLLECTION_ID = "6a671465e31c8cf8983d3d36"

SM_BASE = "https://api.sportmonks.com/v3/football"
WF_BASE = "https://api.webflow.com/v2"


# ============================================================
# HEADERS
# ============================================================

def sm_headers():
    return {
        "Accept": "application/json",
    }


def wf_headers():
    return {
        "Authorization": f"Bearer {WF_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


# ============================================================
# SAFE HELPERS
# ============================================================

def safe_text(value):
    if value is None:
        return ""
    return str(value)


def fixture_slug(fixture):
    fixture_id = fixture.get("id", "")
    return f"fixture-{fixture_id}"


def fixture_name(fixture):
    participants = fixture.get("participants") or []

    home = ""
    away = ""

    for participant in participants:
        meta = participant.get("meta") or {}
        location = meta.get("location")

        name = (
            participant.get("name")
            or participant.get("short_code")
            or ""
        )

        if location == "home":
            home = name

        elif location == "away":
            away = name

    if not home:
        home = "Home"

    if not away:
        away = "Away"

    return f"{home} vs {away}"


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

    return safe_text(
        participant.get("name")
        or participant.get("short_code")
        or ""
    )


def team_id(participant):
    if not participant:
        return None

    return participant.get("id")


# ============================================================
# TEAM LOGO
# ============================================================

def team_logo(participant):
    if not participant:
        return None

    image_path = participant.get("image_path")

    if image_path:
        return {
            "url": image_path,
            "alt": participant_name(participant),
        }

    participant_id = participant.get("id")

    if not participant_id:
        return None

    # SportsMonks CDN fallback
    folder = int(participant_id) // 100000

    return {
        "url": (
            f"https://cdn.sportmonks.com/images/soccer/teams/"
            f"{folder}/{participant_id}.png"
        ),
        "alt": participant_name(participant),
    }


# ============================================================
# TOURNAMENT / LEAGUE LOGO
# ============================================================

def league_logo(fixture):
    league = fixture.get("league") or {}

    image_path = league.get("image_path")

    if image_path:
        return {
            "url": image_path,
            "alt": safe_text(league.get("name")),
        }

    league_id = league.get("id")

    if not league_id:
        return None

    folder = int(league_id) // 100

    return {
        "url": (
            f"https://cdn.sportmonks.com/images/soccer/leagues/"
            f"{folder}/{league_id}.png"
        ),
        "alt": safe_text(league.get("name")),
    }


# ============================================================
# DATE
# ============================================================

def fixture_date(fixture):
    value = fixture.get("starting_at")

    if not value:
        return ""

    # SportsMonks normally returns:
    # 2026-08-15T18:00:00.000000Z
    #
    # Webflow accepts ISO 8601 DateTime.
    try:
        dt = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )

        return dt.astimezone(timezone.utc).isoformat(
            timespec="milliseconds"
        ).replace("+00:00", "Z")

    except Exception:
        return value


# ============================================================
# SCORES
# ============================================================

def get_score(fixture, participant_id):
    """
    Get CURRENT score for a participant.

    SportsMonks scores are normally returned like:

    {
        "participant_id": 123,
        "score": {
            "goals": 2,
            "participant": "home"
        },
        "description": "CURRENT"
    }
    """

    if not participant_id:
        return ""

    scores = fixture.get("scores") or []

    # Sometimes scores can be returned as a list
    if isinstance(scores, dict):
        scores = scores.get("data") or []

    for score in scores:

        if score.get("participant_id") != participant_id:
            continue

        description = score.get("description")

        if description != "CURRENT":
            continue

        score_object = score.get("score") or {}

        goals = score_object.get("goals")

        if goals is not None:
            return safe_text(goals)

        # Fallback in case API returns goals directly
        goals = score.get("goals")

        if goals is not None:
            return safe_text(goals)

    return ""


def home_score(fixture, home):
    return get_score(
        fixture,
        team_id(home)
    )


def away_score(fixture, away):
    return get_score(
        fixture,
        team_id(away)
    )


# ============================================================
# SPORTS MONKS FIXTURES
# ============================================================

def sm_fixtures():

    today = datetime.now(timezone.utc).date()

    # SportsMonks maximum date range is 100 days.
    # Use 90 days to stay safely below the limit.
    end = today + timedelta(days=90)

    url = (
        f"{SM_BASE}/fixtures/between/"
        f"{today.isoformat()}/"
        f"{end.isoformat()}"
    )

    params = {
        "api_token": SM_TOKEN,
        "include": (
            "participants;"
            "venue;"
            "league;"
            "scores;"
            "state"
        ),
        "filter": f"participantIds:{TEAM_ID}",
        "per_page": 100,
    }

    response = requests.get(
        url,
        params=params,
        headers=sm_headers(),
        timeout=30,
    )

    print("SPORTSMONKS STATUS:", response.status_code)
    print("SPORTSMONKS URL:", response.url)

    if not response.ok:
        print("SPORTSMONKS RESPONSE:", response.text)
        response.raise_for_status()

    data = response.json()

    fixtures = data.get("data") or []

    print("Fixtures received:", len(fixtures))

    return fixtures


# ============================================================
# WEBFLOW COLLECTION
# ============================================================

def get_collection():

    url = (
        f"{WF_BASE}/collections/"
        f"{COLLECTION_ID}"
    )

    response = requests.get(
        url,
        headers=wf_headers(),
        timeout=30,
    )

    print("COLLECTION STATUS:", response.status_code)
    print("COLLECTION RESPONSE:", response.text)

    response.raise_for_status()

    return response.json()


# ============================================================
# SHOW WEBFLOW FIELDS
# ============================================================

def print_webflow_fields(collection):

    print("\nWebflow fields:")

    for field in collection.get("fields", []):

        print(
            f'{field.get("slug")} | '
            f'{field.get("displayName")} | '
            f'{field.get("type")}'
        )

    print()


# ============================================================
# GET WEBFLOW ITEMS
# ============================================================

def wf_items():

    url = (
        f"{WF_BASE}/collections/"
        f"{COLLECTION_ID}/items"
    )

    params = {
        "limit": 100,
    }

    response = requests.get(
        url,
        headers=wf_headers(),
        params=params,
        timeout=30,
    )

    print("ITEMS STATUS:", response.status_code)

    if not response.ok:
        print("ITEMS RESPONSE:", response.text)
        response.raise_for_status()

    data = response.json()

    items = data.get("items") or []

    print("Existing Webflow items:", len(items))

    return items


# ============================================================
# CREATE FIELD DATA
# ============================================================

def fixture_field_data(fixture):

    home, away = get_participants(fixture)

    home_name = participant_name(home)
    away_name = participant_name(away)

    fixture_id = fixture.get("id", "")

    venue = fixture.get("venue") or {}
    venue_name = venue.get("name", "")

    league = fixture.get("league") or {}
    league_name = league.get("name", "")

    state = fixture.get("state") or {}
    state_name = state.get("name", "")

    home_logo = team_logo(home)
    away_logo = team_logo(away)
    tournament_logo = league_logo(fixture)

    field_data = {
        "name": fixture_name(fixture),

        "slug": fixture_slug(fixture),

        "home-team-name": home_name,

        "away-team-name": away_name,

        "date-time": fixture_date(fixture),

        "venue": safe_text(venue_name),

        "league": safe_text(league_name),

        "sportsmonks-id": safe_text(fixture_id),

        "status": safe_text(state_name),

        "home-team-score": home_score(
            fixture,
            home
        ),

        "away-team-score": away_score(
            fixture,
            away
        ),
    }

    # --------------------------------------------------------
    # HOME LOGO
    # --------------------------------------------------------

    if home_logo:
        field_data["opposing-team-logo"] = home_logo

    # --------------------------------------------------------
    # AWAY LOGO
    # --------------------------------------------------------

    if away_logo:
        field_data["away-team-logo"] = away_logo

    # --------------------------------------------------------
    # TOURNAMENT LOGO
    # --------------------------------------------------------

    if tournament_logo:
        field_data["tournament-logo"] = tournament_logo

    return field_data


# ============================================================
# CREATE WEBFLOW ITEM
# ============================================================

def create_webflow_item(field_data):

    url = (
        f"{WF_BASE}/collections/"
        f"{COLLECTION_ID}/items"
    )

    payload = {
        "fieldData": field_data
    }

    response = requests.post(
        url,
        headers=wf_headers(),
        json=payload,
        timeout=30,
    )

    if not response.ok:

        print("CREATE STATUS:", response.status_code)
        print("CREATE RESPONSE:", response.text)
        print("CREATE PAYLOAD:", field_data)

        response.raise_for_status()

    print("Created:", field_data.get("sportsmonks-id"))


# ============================================================
# UPDATE WEBFLOW ITEM
# ============================================================

def update_webflow_item(item_id, field_data):

    url = (
        f"{WF_BASE}/collections/"
        f"{COLLECTION_ID}/items/"
        f"{item_id}"
    )

    payload = {
        "fieldData": field_data
    }

    response = requests.patch(
        url,
        headers=wf_headers(),
        json=payload,
        timeout=30,
    )

    print("UPDATE STATUS:", response.status_code)

    if not response.ok:

        print("UPDATE RESPONSE:", response.text)
        print("UPDATE PAYLOAD:", field_data)

        response.raise_for_status()

    print("Updated:", field_data.get("sportsmonks-id"))


# ============================================================
# SYNC FIXTURES
# ============================================================

def sync_fixtures():

    # --------------------------------------------------------
    # Test collection first
    # --------------------------------------------------------

    collection = get_collection()

    print_webflow_fields(collection)

    # --------------------------------------------------------
    # Get SportsMonks fixtures
    # --------------------------------------------------------

    fixtures = sm_fixtures()

    # --------------------------------------------------------
    # Get existing Webflow items
    # --------------------------------------------------------

    existing_items = wf_items()

    existing_by_fixture_id = {}

    for item in existing_items:

        field_data = item.get("fieldData") or {}

        fixture_id = (
            field_data.get("sportsmonks-id")
            or field_data.get("fixture-id")
        )

        if fixture_id:
            existing_by_fixture_id[
                safe_text(fixture_id)
            ] = item

    created = 0
    updated = 0

    # --------------------------------------------------------
    # Process fixtures
    # --------------------------------------------------------

    for fixture in fixtures:

        fixture_id = safe_text(
            fixture.get("id")
        )

        if not fixture_id:
            continue

        print(
            "\nProcessing fixture:",
            fixture_id
        )

        field_data = fixture_field_data(
            fixture
        )

        existing = existing_by_fixture_id.get(
            fixture_id
        )

        if existing:

            print(
                "Updating fixture",
                fixture_id
            )

            update_webflow_item(
                existing["id"],
                field_data
            )

            updated += 1

        else:

            print(
                "Creating fixture",
                fixture_id
            )

            create_webflow_item(
                field_data
            )

            created += 1

    # --------------------------------------------------------
    # Summary
    # --------------------------------------------------------

    print()
    print(
        f"Fixtures received: {len(fixtures)}"
    )

    print(
        f"Webflow items created: {created}"
    )

    print(
        f"Webflow items updated: {updated}"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    sync_fixtures()


if __name__ == "__main__":
    main()
