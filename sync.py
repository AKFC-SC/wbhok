import os
from datetime import datetime, timedelta, timezone

import requests


# =========================================================
# CONFIG
# =========================================================

SM_TOKEN = os.environ["SPORTSMONKS_API_TOKEN"]
WF_TOKEN = os.environ["WEBFLOW_API_TOKEN"]

TEAM_ID = 232744

COLLECTION_ID = "6a671465e31c8cf8983d3d36"

SM_BASE = "https://api.sportmonks.com/v3/football/fixtures/between"
WF_BASE = "https://api.webflow.com/v2"


# =========================================================
# HEADERS
# =========================================================

def wf_headers():
    return {
        "Authorization": f"Bearer {WF_TOKEN}",
        "Content-Type": "application/json",
    }


# =========================================================
# SPORTSMONKS
# =========================================================

def sm_fixtures():
    """
    Get fixtures for the team from SportsMonks.
    """

    start = datetime.now(timezone.utc).date()
    end = start + timedelta(days=365)

    url = f"{SM_BASE}/{start}/{end}/{TEAM_ID}"

    params = {
        "api_token": SM_TOKEN,
        "include": "participants;league;state;venue;scores",
        "per_page": 100,
    }

    response = requests.get(
        url,
        params=params,
        timeout=30,
    )

    print("SPORTSMONKS STATUS:", response.status_code)

    if not response.ok:
        print("SPORTSMONKS RESPONSE:", response.text)

    response.raise_for_status()

    data = response.json()

    return data.get("data", [])


# =========================================================
# TEAM HELPERS
# =========================================================

def fixture_participants(fixture):
    return fixture.get("participants") or []


def get_home_team(fixture):
    participants = fixture_participants(fixture)

    for team in participants:
        meta = team.get("meta") or {}

        if meta.get("location") == "home":
            return team

    return {}


def get_away_team(fixture):
    participants = fixture_participants(fixture)

    for team in participants:
        meta = team.get("meta") or {}

        if meta.get("location") == "away":
            return team

    return {}


def team_name(team):
    return team.get("name", "")


def team_logo(team):
    return team.get("image_path", "")


# =========================================================
# FIXTURE HELPERS
# =========================================================

def fixture_name(fixture):
    home = get_home_team(fixture)
    away = get_away_team(fixture)

    home_name = team_name(home)
    away_name = team_name(away)

    if home_name and away_name:
        return f"{home_name} vs {away_name}"

    return f"Fixture {fixture.get('id', '')}"


def fixture_slug(fixture):
    fixture_id = str(fixture.get("id", ""))

    return f"fixture-{fixture_id}"


def fixture_date(fixture):
    value = fixture.get("starting_at")

    if not value:
        return ""

    return value


def fixture_time(fixture):
    value = fixture.get("starting_at")

    if not value:
        return ""

    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))

        return dt.strftime("%I:%M %p")

    except Exception:
        return ""


# =========================================================
# SCORE HELPERS
# =========================================================

def team_score(fixture, team):
    """
    Get the score for a participant.
    """

    team_id = team.get("id")

    if not team_id:
        return ""

    scores = fixture.get("scores") or []

    for score in scores:

        if score.get("participant_id") != team_id:
            continue

        score_data = score.get("score") or {}

        goals = score_data.get("goals")

        if goals is not None:
            return str(goals)

    return ""


def home_score(fixture):
    return team_score(
        fixture,
        get_home_team(fixture)
    )


def away_score(fixture):
    return team_score(
        fixture,
        get_away_team(fixture)
    )


# =========================================================
# FIELD DATA
# =========================================================

def fixture_field_data(fixture):

    home = get_home_team(fixture)
    away = get_away_team(fixture)

    home_name = team_name(home)
    away_name = team_name(away)

    home_logo = team_logo(home)
    away_logo = team_logo(away)

    league = fixture.get("league") or {}
    state = fixture.get("state") or {}
    venue = fixture.get("venue") or {}

    starting_at = fixture_date(fixture)

    field_data = {
        # Webflow Basic Info
        "name": fixture_name(fixture),
        "slug": fixture_slug(fixture),

        # Teams
        "home-team-name": home_name,
        "away-team-name": away_name,

        # Logos
        "home-team-logo": {
            "url": home_logo,
            "alt": home_name,
        },

        "away-team-logo": {
            "url": away_logo,
            "alt": away_name,
        },

        # Date / Time
        "starting-at": starting_at,
        "time": fixture_time(fixture),

        # Venue
        "venue": venue.get("name", ""),

        # Tournament / League
        "league": league.get("name", ""),

        # SportsMonks
        "sportsmonks-id": str(
            fixture.get("id", "")
        ),

        # Status
        "status": state.get("name", ""),

        # Scores
        "home-team-score": home_score(fixture),
        "away-team-score": away_score(fixture),

        # Links
        "ticket-link": "",
        "match-hub-link": "",
    }

    # Only send tournament logo if SportsMonks actually gives us one.
    # This field is optional in your Webflow collection.
    league_logo = league.get("image_path")

    if league_logo:
        field_data["tournament-logo"] = {
            "url": league_logo,
            "alt": league.get("name", ""),
        }

    return field_data


# =========================================================
# WEBFLOW - COLLECTION
# =========================================================

def test_collection():

    url = f"{WF_BASE}/collections/{COLLECTION_ID}"

    response = requests.get(
        url,
        headers=wf_headers(),
        timeout=30,
    )

    print("COLLECTION STATUS:", response.status_code)
    print("COLLECTION RESPONSE:", response.text)

    response.raise_for_status()

    return response.json()


# =========================================================
# WEBFLOW - GET ITEMS
# =========================================================

def wf_items():

    url = f"{WF_BASE}/collections/{COLLECTION_ID}/items"

    response = requests.get(
        url,
        headers=wf_headers(),
        params={
            "limit": 100,
        },
        timeout=30,
    )

    print("ITEMS STATUS:", response.status_code)

    if not response.ok:
        print("ITEMS RESPONSE:", response.text)

    response.raise_for_status()

    data = response.json()

    return data.get("items", [])


# =========================================================
# WEBFLOW - CREATE
# =========================================================

def create_webflow_item(field_data):

    url = f"{WF_BASE}/collections/{COLLECTION_ID}/items"

    payload = {
        "fieldData": field_data
    }

    response = requests.post(
        url,
        headers=wf_headers(),
        json=payload,
        timeout=30,
    )

    print("CREATE STATUS:", response.status_code)

    if not response.ok:
        print("CREATE RESPONSE:", response.text)
        print("CREATE PAYLOAD:", field_data)

    response.raise_for_status()

    return response.json()


# =========================================================
# WEBFLOW - UPDATE
# =========================================================

def update_webflow_item(item_id, field_data):

    url = (
        f"{WF_BASE}/collections/"
        f"{COLLECTION_ID}/items/{item_id}"
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

    return response.json()


# =========================================================
# EXISTING ITEMS MAP
# =========================================================

def existing_items_by_fixture_id(items):

    result = {}

    for item in items:

        field_data = item.get("fieldData") or {}

        fixture_id = field_data.get("sportsmonks-id")

        if fixture_id:
            result[str(fixture_id)] = item

    return result


# =========================================================
# SYNC
# =========================================================

def sync_fixtures():

    fixtures = sm_fixtures()

    print(f"Fixtures received: {len(fixtures)}")

    existing_items = wf_items()

    print(
        f"Existing Webflow items: "
        f"{len(existing_items)}"
    )

    existing_by_fixture_id = (
        existing_items_by_fixture_id(existing_items)
    )

    created = 0
    updated = 0

    for fixture in fixtures:

        fixture_id = str(
            fixture.get("id", "")
        )

        if not fixture_id:
            continue

        field_data = fixture_field_data(fixture)

        existing = existing_by_fixture_id.get(
            fixture_id
        )

        try:

            if existing:

                print(
                    f"Updating fixture "
                    f"{fixture_id}"
                )

                update_webflow_item(
                    existing["id"],
                    field_data
                )

                updated += 1

            else:

                print(
                    f"Creating fixture "
                    f"{fixture_id}"
                )

                create_webflow_item(
                    field_data
                )

                created += 1

        except requests.HTTPError:

            print(
                f"FAILED fixture "
                f"{fixture_id}"
            )

            raise

    print("--------------------------------")
    print(
        f"Fixtures received: {len(fixtures)}"
    )
    print(
        f"Webflow items created: {created}"
    )
    print(
        f"Webflow items updated: {updated}"
    )
    print("--------------------------------")


# =========================================================
# MAIN
# =========================================================

def main():

    # Test the collection first.
    test_collection()

    # Then sync fixtures.
    sync_fixtures()


if __name__ == "__main__":
    main()
