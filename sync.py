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
# WEBFLOW HEADERS
# =========================================================

def wf_headers():
    return {
        "Authorization": f"Bearer {WF_TOKEN}",
        "Content-Type": "application/json",
    }


# =========================================================
# SPORTSMONKS FIXTURES
# =========================================================

def sm_fixtures():

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
# PARTICIPANTS
# =========================================================

def fixture_participants(fixture):
    return fixture.get("participants") or []


def get_home_team(fixture):

    for team in fixture_participants(fixture):

        meta = team.get("meta") or {}

        if meta.get("location") == "home":
            return team

    return {}


def get_away_team(fixture):

    for team in fixture_participants(fixture):

        meta = team.get("meta") or {}

        if meta.get("location") == "away":
            return team

    return {}


# =========================================================
# TEAM HELPERS
# =========================================================

def team_name(team):
    return team.get("name", "")


def team_logo(team):
    return team.get("image_path", "")


# =========================================================
# FIXTURE NAME / SLUG
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


# =========================================================
# DATE
# =========================================================

def fixture_date(fixture):

    value = fixture.get("starting_at")

    if not value:
        return ""

    return value


# =========================================================
# SCORES
# =========================================================

def team_score(fixture, team):

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
# BUILD WEBFLOW FIELD DATA
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

        # ---------------------------------------------
        # BASIC INFO
        # ---------------------------------------------

        "name": fixture_name(fixture),

        "slug": fixture_slug(fixture),


        # ---------------------------------------------
        # HOME TEAM
        # Webflow display name:
        # Home Team Name
        # Webflow slug:
        # home-team-name
        # ---------------------------------------------

        "home-team-name": home_name,


        # ---------------------------------------------
        # AWAY TEAM
        # ---------------------------------------------

        "away-team-name": away_name,


        # ---------------------------------------------
        # HOME TEAM LOGO
        #
        # IMPORTANT:
        # Webflow display name = Home Team Logo
        # Webflow slug = opposing-team-logo
        # ---------------------------------------------

        "opposing-team-logo": {
            "url": home_logo,
            "alt": home_name,
        },


        # ---------------------------------------------
        # AWAY TEAM LOGO
        # ---------------------------------------------

        "away-team-logo": {
            "url": away_logo,
            "alt": away_name,
        },


        # ---------------------------------------------
        # DATE / TIME
        # Webflow slug = starting-at
        # ---------------------------------------------

        "starting-at": starting_at,


        # ---------------------------------------------
        # VENUE
        # ---------------------------------------------

        "venue": venue.get("name", ""),


        # ---------------------------------------------
        # LEAGUE
        # ---------------------------------------------

        "league": league.get("name", ""),


        # ---------------------------------------------
        # SPORTSMONKS ID
        # ---------------------------------------------

        "sportsmonks-id": str(
            fixture.get("id", "")
        ),


        # ---------------------------------------------
        # STATUS
        # ---------------------------------------------

        "status": state.get("name", ""),


        # ---------------------------------------------
        # SCORES
        # ---------------------------------------------

        "home-team-score": home_score(fixture),

        "away-team-score": away_score(fixture),
    }


    # ---------------------------------------------
    # TOURNAMENT LOGO
    # Optional
    # ---------------------------------------------

    league_logo = league.get("image_path")

    if league_logo:

        field_data["tournament-logo"] = {
            "url": league_logo,
            "alt": league.get("name", ""),
        }


    # ---------------------------------------------
    # TICKET LINK
    # Optional - don't send empty URL
    # ---------------------------------------------

    ticket_link = fixture.get("ticket_link")

    if ticket_link:

        field_data["ticket-link"] = ticket_link


    # ---------------------------------------------
    # MATCH HUB LINK
    # Optional - don't send empty URL
    # ---------------------------------------------

    match_hub_link = fixture.get("match_hub_link")

    if match_hub_link:

        field_data["match-hub-link"] = match_hub_link


    return field_data


# =========================================================
# TEST WEBFLOW COLLECTION
# =========================================================

def test_collection():

    url = f"{WF_BASE}/collections/{COLLECTION_ID}"

    response = requests.get(
        url,
        headers=wf_headers(),
        timeout=30,
    )

    print("COLLECTION STATUS:", response.status_code)

    print(
        "COLLECTION RESPONSE:",
        response.text
    )

    response.raise_for_status()

    return response.json()


# =========================================================
# GET WEBFLOW ITEMS
# =========================================================

def wf_items():

    url = (
        f"{WF_BASE}/collections/"
        f"{COLLECTION_ID}/items"
    )

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

        print(
            "ITEMS RESPONSE:",
            response.text
        )

    response.raise_for_status()

    data = response.json()

    return data.get("items", [])


# =========================================================
# CREATE WEBFLOW ITEM
# =========================================================

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

    print(
        "CREATE STATUS:",
        response.status_code
    )

    if not response.ok:

        print(
            "CREATE RESPONSE:",
            response.text
        )

        print(
            "CREATE PAYLOAD:",
            field_data
        )

    response.raise_for_status()

    return response.json()


# =========================================================
# UPDATE WEBFLOW ITEM
# =========================================================

def update_webflow_item(
    item_id,
    field_data
):

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

    print(
        "UPDATE STATUS:",
        response.status_code
    )

    if not response.ok:

        print(
            "UPDATE RESPONSE:",
            response.text
        )

        print(
            "UPDATE PAYLOAD:",
            field_data
        )

    response.raise_for_status()

    return response.json()


# =========================================================
# EXISTING ITEMS
# =========================================================

def existing_items_by_fixture_id(items):

    result = {}

    for item in items:

        field_data = item.get(
            "fieldData"
        ) or {}

        fixture_id = field_data.get(
            "sportsmonks-id"
        )

        if fixture_id:

            result[str(fixture_id)] = item

    return result


# =========================================================
# SYNC
# =========================================================

def sync_fixtures():

    fixtures = sm_fixtures()

    print(
        f"Fixtures received: {len(fixtures)}"
    )


    # ---------------------------------------------
    # Get existing Webflow items
    # ---------------------------------------------

    existing_items = wf_items()

    print(
        f"Existing Webflow items: "
        f"{len(existing_items)}"
    )


    existing_by_fixture_id = (
        existing_items_by_fixture_id(
            existing_items
        )
    )


    created = 0
    updated = 0


    # ---------------------------------------------
    # Process fixtures
    # ---------------------------------------------

    for fixture in fixtures:

        fixture_id = str(
            fixture.get("id", "")
        )

        if not fixture_id:
            continue


        field_data = fixture_field_data(
            fixture
        )


        existing = (
            existing_by_fixture_id.get(
                fixture_id
            )
        )


        try:

            # -------------------------------------
            # UPDATE
            # -------------------------------------

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


            # -------------------------------------
            # CREATE
            # -------------------------------------

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


    # ---------------------------------------------
    # SUMMARY
    # ---------------------------------------------

    print("--------------------------------")

    print(
        f"Fixtures received: "
        f"{len(fixtures)}"
    )

    print(
        f"Webflow items created: "
        f"{created}"
    )

    print(
        f"Webflow items updated: "
        f"{updated}"
    )

    print("--------------------------------")


# =========================================================
# MAIN
# =========================================================

def main():

    # Test Webflow connection first
    test_collection()

    # Then sync
    sync_fixtures()


if __name__ == "__main__":
    main()
