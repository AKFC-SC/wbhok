import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

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

# Saudi Arabia timezone
RIYADH_TZ = ZoneInfo("Asia/Riyadh")


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
# HELPERS
# ============================================================

def safe_text(value):
    if value is None:
        return ""

    return str(value)


def fixture_slug(fixture):
    return f"fixture-{fixture.get('id', '')}"


# ============================================================
# PARTICIPANTS
# ============================================================

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


def participant_id(participant):

    if not participant:
        return None

    return participant.get("id")


def fixture_name(fixture):

    home, away = get_participants(fixture)

    home_name = participant_name(home)
    away_name = participant_name(away)

    if not home_name:
        home_name = "Home"

    if not away_name:
        away_name = "Away"

    return f"{home_name} vs {away_name}"


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

    return None


# ============================================================
# LEAGUE LOGO
# ============================================================

def league_logo(fixture):

    league = fixture.get("league") or {}

    image_path = league.get("image_path")

    if image_path:

        return {
            "url": image_path,
            "alt": safe_text(
                league.get("name")
            ),
        }

    return None


# ============================================================
# DATE
# ============================================================

def fixture_date(fixture):

    value = fixture.get("starting_at")

    if not value:
        return ""

    try:

        dt = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )

        # Webflow DateTime requires ISO UTC
        return (
            dt.astimezone(timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )

    except Exception:

        return value


# ============================================================
# TIME
# ============================================================

def fixture_time(fixture):

    value = fixture.get("starting_at")

    if not value:
        return ""

    try:

        dt = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )

        # Convert UTC time to Saudi time
        dt = dt.astimezone(RIYADH_TZ)

        # Example: 06:00 PM
        return dt.strftime("%I:%M %p")

    except Exception:

        return ""


# ============================================================
# SCORE
# ============================================================

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
# SPORTS MONKS FIXTURES
# ============================================================

def sm_fixtures():

    today = datetime.now(timezone.utc).date()

    season_end = datetime(
        2027,
        6,
        30,
        tzinfo=timezone.utc
    ).date()

    all_fixtures = []

    current_start = today

    # SportsMonks maximum range is 100 days
    while current_start <= season_end:

        current_end = min(
            current_start + timedelta(days=90),
            season_end
        )

        url = (
            f"{SM_BASE}/fixtures/between/"
            f"{current_start.isoformat()}/"
            f"{current_end.isoformat()}/"
            f"{TEAM_ID}"
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

            "per_page": 100,
        }

        print()
        print(
            "SPORTSMONKS REQUEST:",
            current_start,
            "->",
            current_end
        )

        response = requests.get(
            url,
            params=params,
            headers=sm_headers(),
            timeout=30,
        )

        print(
            "SPORTSMONKS STATUS:",
            response.status_code
        )

        if not response.ok:

            print(
                "SPORTSMONKS RESPONSE:",
                response.text
            )

            response.raise_for_status()

        data = response.json()

        fixtures = data.get("data") or []

        print(
            "Fixtures returned:",
            len(fixtures)
        )

        all_fixtures.extend(fixtures)

        current_start = (
            current_end +
            timedelta(days=1)
        )

    # ========================================================
    # REMOVE DUPLICATES
    # ========================================================

    unique_fixtures = {}

    for fixture in all_fixtures:

        fixture_id = fixture.get("id")

        if fixture_id:

            unique_fixtures[
                str(fixture_id)
            ] = fixture

    fixtures = list(
        unique_fixtures.values()
    )

    # ========================================================
    # DEBUG
    # ========================================================

    print()
    print(
        "TOTAL AL KHOLOOD FIXTURES:",
        len(fixtures)
    )

    for fixture in fixtures:

        home, away = get_participants(
            fixture
        )

        league = fixture.get("league") or {}

        print(
            "KHOLOOD FIXTURE:",
            fixture.get("id"),
            "|",
            participant_name(home),
            "vs",
            participant_name(away),
            "|",
            league.get("name", "")
        )

    print()

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

    print(
        "COLLECTION STATUS:",
        response.status_code
    )

    print(
        "COLLECTION RESPONSE:",
        response.text
    )

    response.raise_for_status()

    return response.json()


# ============================================================
# WEBFLOW FIELDS
# ============================================================

def print_webflow_fields(collection):

    print()
    print("Webflow fields:")

    for field in collection.get(
        "fields",
        []
    ):

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

    print(
        "ITEMS STATUS:",
        response.status_code
    )

    if not response.ok:

        print(
            "ITEMS RESPONSE:",
            response.text
        )

        response.raise_for_status()

    data = response.json()

    items = data.get("items") or []

    print(
        "Existing Webflow items:",
        len(items)
    )

    return items


# ============================================================
# FIELD DATA
# ============================================================

def fixture_field_data(
    fixture,
    include_logos=False
):

    home, away = get_participants(
        fixture
    )

    home_name = participant_name(home)
    away_name = participant_name(away)

    home_id = participant_id(home)
    away_id = participant_id(away)

    venue = fixture.get("venue") or {}

    league = fixture.get("league") or {}

    state = fixture.get("state") or {}

    field_data = {

        # ====================================================
        # REQUIRED FIELDS
        # ====================================================

        "name": fixture_name(fixture),

        "slug": fixture_slug(fixture),

        # ====================================================
        # TEAMS
        # ====================================================

        "home-team-name": home_name,

        "away-team-name": away_name,

        # ====================================================
        # DATE + TIME
        # ====================================================

        "date-time": fixture_date(fixture),

        "time-3": fixture_time(fixture),

        # ====================================================
        # VENUE
        # ====================================================

        "venue": safe_text(
            venue.get("name", "")
        ),

        # ====================================================
        # LEAGUE
        # ====================================================

        "league": safe_text(
            league.get("name", "")
        ),

        # ====================================================
        # SPORTSMONKS ID
        # ====================================================

        "sportsmonks-id": safe_text(
            fixture.get("id", "")
        ),

        # ====================================================
        # STATUS
        # ====================================================

        "status": safe_text(
            state.get("name", "")
        ),

        # ====================================================
        # SCORES
        # ====================================================

        "home-team-score": get_score(
            fixture,
            home_id
        ),

        "away-team-score": get_score(
            fixture,
            away_id
        ),
    }

    # ========================================================
    # LOGOS
    #
    # IMPORTANT:
    # Logos are ONLY added when creating a new Webflow item.
    #
    # Existing items will NOT receive logo updates.
    # ========================================================

    if include_logos:

        home_logo = team_logo(home)

        if home_logo:

            field_data[
                "opposing-team-logo"
            ] = home_logo

        away_logo = team_logo(away)

        if away_logo:

            field_data[
                "away-team-logo"
            ] = away_logo

        tournament_logo = league_logo(
            fixture
        )

        if tournament_logo:

            field_data[
                "tournament-logo"
            ] = tournament_logo

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

        print(
            "CREATE STATUS:",
            response.status_code
        )

        print(
            "CREATE RESPONSE:",
            response.text
        )

        print(
            "CREATE PAYLOAD:",
            field_data
        )

        response.raise_for_status()

    print(
        "Created:",
        field_data.get(
            "sportsmonks-id"
        )
    )


# ============================================================
# UPDATE WEBFLOW ITEM
# ============================================================

def update_webflow_item(
    item_id,
    field_data
):

    url = (
        f"{WF_BASE}/collections/"
        f"{COLLECTION_ID}/items/"
        f"{item_id}"
    )

    # IMPORTANT:
    # field_data does NOT contain any logo fields.
    #
    # Therefore existing Webflow logos are untouched.

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

    print(
        "Updated:",
        field_data.get(
            "sportsmonks-id"
        )
    )


# ============================================================
# SYNC
# ============================================================

def sync_fixtures():

    # --------------------------------------------------------
    # Test Webflow collection
    # --------------------------------------------------------

    collection = get_collection()

    print_webflow_fields(
        collection
    )

    # --------------------------------------------------------
    # Get AL KHOLOOD fixtures only
    # --------------------------------------------------------

    fixtures = sm_fixtures()

    # --------------------------------------------------------
    # Get existing Webflow items
    # --------------------------------------------------------

    existing_items = wf_items()

    existing_by_fixture_id = {}

    for item in existing_items:

        field_data = (
            item.get("fieldData")
            or {}
        )

        fixture_id = (
            field_data.get(
                "sportsmonks-id"
            )
            or
            field_data.get(
                "fixture-id"
            )
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

        print()
        print(
            "Processing fixture:",
            fixture_id
        )

        existing = (
            existing_by_fixture_id.get(
                fixture_id
            )
        )

        # ====================================================
        # EXISTING FIXTURE
        # ====================================================

        if existing:

            print(
                "Updating fixture",
                fixture_id
            )

            # NO LOGOS HERE
            field_data = fixture_field_data(
                fixture,
                include_logos=False
            )

            update_webflow_item(
                existing["id"],
                field_data
            )

            updated += 1

        # ====================================================
        # NEW FIXTURE
        # ====================================================

        else:

            print(
                "Creating fixture",
                fixture_id
            )

            # Logos are added ONLY for new fixtures
            field_data = fixture_field_data(
                fixture,
                include_logos=True
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
        "========================================"
    )

    print(
        f"Fixtures received: {len(fixtures)}"
    )

    print(
        f"Webflow items created: {created}"
    )

    print(
        f"Webflow items updated: {updated}"
    )

    print(
        "========================================"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    sync_fixtures()


if __name__ == "__main__":

    main()
