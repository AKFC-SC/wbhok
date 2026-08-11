import os
import re
import requests
from datetime import datetime, timedelta, timezone


# ============================================================
# ENVIRONMENT
# ============================================================

SM_TOKEN = os.environ["SPORTSMONKS_API_TOKEN"]
WF_TOKEN = os.environ["WEBFLOW_API_TOKEN"]


# ============================================================
# CONFIGURATION
# ============================================================

TEAM_ID = 232744

COLLECTION_ID = "6a671465e31c8cf8983d3d36"

SM_BASE = "https://api.sportmonks.com/v3/football"
WF_BASE = "https://api.webflow.com/v2"


# ============================================================
# HEADERS
# ============================================================

def sm_headers():
    return {
        "Authorization": SM_TOKEN,
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

    return str(value).strip()


def slugify(value):
    value = safe_text(value).lower()

    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-+", "-", value)
    value = value.strip("-")

    return value or "fixture"


def team_name(team):
    if not team:
        return ""

    return safe_text(
        team.get("name")
        or team.get("short_code")
        or team.get("short_name")
        or ""
    )


def team_logo(team):
    if not team:
        return None

    image_url = (
        team.get("image_path")
        or team.get("logo")
        or team.get("image")
        or ""
    )

    if not image_url:
        return None

    return {
        "url": image_url,
        "alt": team_name(team),
    }


# ============================================================
# SPORTSMONKS
# ============================================================

def sm_fixtures():
    start = datetime.now(timezone.utc).date()
    end = start + timedelta(days=365)

    url = (
        f"{SM_BASE}/fixtures/between/"
        f"{start}/{end}"
    )

    params = {
        "api_token": SM_TOKEN,
        "include": "participants;venue;league",
        "per_page": 100,
    }

    response = requests.get(
        url,
        headers=sm_headers(),
        params=params,
        timeout=30,
    )

    print("SPORTSMONKS STATUS:", response.status_code)

    if not response.ok:
        print("SPORTSMONKS RESPONSE:", response.text)

    response.raise_for_status()

    data = response.json()

    fixtures = data.get("data", [])

    result = []

    for fixture in fixtures:

        participants = fixture.get("participants") or []

        home_team = None
        away_team = None

        for participant in participants:

            meta = participant.get("meta") or {}

            location = meta.get("location")

            if location == "home":
                home_team = participant

            elif location == "away":
                away_team = participant

        # Make sure our team is involved
        participant_ids = []

        for participant in participants:
            participant_id = participant.get("id")

            if participant_id:
                participant_ids.append(participant_id)

        if TEAM_ID not in participant_ids:
            continue

        result.append({
            "raw": fixture,
            "home": home_team,
            "away": away_team,
        })

    print("Fixtures received:", len(result))

    return result


# ============================================================
# DATE
# ============================================================

def fixture_date(fixture):
    value = fixture.get("starting_at")

    if not value:
        return ""

    value = str(value).strip()

    # SportsMonks normally returns ISO 8601.
    # Convert it to a Webflow-compatible ISO 8601 value.
    try:

        parsed = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )

        if parsed.tzinfo is None:
            parsed = parsed.replace(
                tzinfo=timezone.utc
            )

        parsed = parsed.astimezone(timezone.utc)

        return parsed.isoformat(
            timespec="seconds"
        ).replace("+00:00", "Z")

    except ValueError:

        # If parsing fails, return original value
        return value


# ============================================================
# FIXTURE NAME
# ============================================================

def fixture_name(fixture):
    home = fixture.get("home") or {}
    away = fixture.get("away") or {}

    home_name = team_name(home)
    away_name = team_name(away)

    if home_name and away_name:
        return f"{home_name} vs {away_name}"

    if home_name:
        return home_name

    if away_name:
        return away_name

    fixture_id = fixture.get("raw", {}).get("id")

    return f"Fixture {fixture_id}"


def fixture_slug(fixture):
    raw = fixture.get("raw") or {}

    fixture_id = raw.get("id")

    return f"fixture-{fixture_id}"


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
# WEBFLOW SCHEMA
# ============================================================

def get_webflow_field_slugs():

    collection = get_collection()

    fields = collection.get("fields", [])

    slugs = set()

    print("\nWebflow fields:")

    for field in fields:

        slug = field.get("slug")

        display_name = field.get("displayName")

        field_type = field.get("type")

        print(
            f"  {slug} | "
            f"{display_name} | "
            f"{field_type}"
        )

        if slug:
            slugs.add(slug)

    print()

    return slugs


# ============================================================
# VALIDATE SCHEMA
# ============================================================

def validate_required_fields(field_slugs):

    required = {
        "name",
        "slug",
        "home-team-name",
        "away-team-name",
        "opposing-team-logo",
        "away-team-logo",
        "date-time",
    }

    missing = required - field_slugs

    if missing:

        raise RuntimeError(
            "Missing Webflow fields: "
            + ", ".join(sorted(missing))
        )


# ============================================================
# FIXTURE -> WEBFLOW
# ============================================================

def fixture_field_data(item):

    fixture = item["raw"]

    home = item.get("home") or {}
    away = item.get("away") or {}

    home_name = team_name(home)
    away_name = team_name(away)

    fixture_id = fixture.get("id")

    league = fixture.get("league") or {}
    venue = fixture.get("venue") or {}

    league_name = safe_text(
        league.get("name")
    )

    venue_name = safe_text(
        venue.get("name")
    )

    # --------------------------------------------------------
    # REQUIRED BASIC FIELDS
    # --------------------------------------------------------

    field_data = {
        "name": fixture_name(item),

        "slug": fixture_slug(item),

        "home-team-name": home_name,

        "away-team-name": away_name,

        "date-time": fixture_date(fixture),

        "venue": venue_name,

        "league": league_name,

        "sportsmonks-id": safe_text(
            fixture_id
        ),

        "status": safe_text(
            (fixture.get("state") or {}).get("name")
        ),

        "home-team-score": "",

        "away-team-score": "",
    }

    # --------------------------------------------------------
    # HOME LOGO
    # --------------------------------------------------------

    home_logo = team_logo(home)

    if home_logo:
        field_data[
            "opposing-team-logo"
        ] = home_logo

    # --------------------------------------------------------
    # AWAY LOGO
    # --------------------------------------------------------

    away_logo = team_logo(away)

    if away_logo:
        field_data[
            "away-team-logo"
        ] = away_logo

    # --------------------------------------------------------
    # TOURNAMENT LOGO
    # --------------------------------------------------------

    if league:

        league_image = (
            league.get("image_path")
            or league.get("logo")
            or ""
        )

        if league_image:

            field_data[
                "tournament-logo"
            ] = {
                "url": league_image,
                "alt": league_name,
            }

    # --------------------------------------------------------
    # REMOVE EMPTY OPTIONAL VALUES
    # --------------------------------------------------------

    cleaned = {}

    for key, value in field_data.items():

        if value is None:
            continue

        if value == "":
            continue

        cleaned[key] = value

    return cleaned


# ============================================================
# WEBFLOW ITEMS
# ============================================================

def wf_items():

    url = (
        f"{WF_BASE}/collections/"
        f"{COLLECTION_ID}/items"
    )

    all_items = []

    offset = 0

    while True:

        params = {
            "offset": offset,
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

        response.raise_for_status()

        data = response.json()

        items = data.get("items", [])

        all_items.extend(items)

        pagination = data.get(
            "pagination",
            {}
        )

        total = pagination.get(
            "total",
            len(all_items)
        )

        if len(all_items) >= total:
            break

        offset += 100

    print(
        "Existing Webflow items:",
        len(all_items)
    )

    return all_items


# ============================================================
# CREATE WEBFLOW ITEM
# ============================================================

def create_webflow_item(field_data):

    url = (
        f"{WF_BASE}/collections/"
        f"{COLLECTION_ID}/items"
    )

    payload = {
        "isArchived": False,
        "isDraft": False,
        "fieldData": field_data,
    }

    print("\nCREATE PAYLOAD:")
    print(payload)

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

    print(
        "CREATE RESPONSE:",
        response.text
    )

    if not response.ok:
        response.raise_for_status()

    return response.json()


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
        "isArchived": False,
        "isDraft": False,
        "fieldData": field_data,
    }

    print("\nUPDATE PAYLOAD:")
    print(payload)

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

    print(
        "UPDATE RESPONSE:",
        response.text
    )

    if not response.ok:
        response.raise_for_status()

    return response.json()


# ============================================================
# FIND EXISTING ITEM
# ============================================================

def build_existing_index(existing_items):

    index = {}

    for item in existing_items:

        field_data = (
            item.get("fieldData")
            or {}
        )

        fixture_id = field_data.get(
            "sportsmonks-id"
        )

        if fixture_id:

            index[
                str(fixture_id)
            ] = item

    return index


# ============================================================
# SYNC
# ============================================================

def sync_fixtures():

    # --------------------------------------------------------
    # Check Webflow schema first
    # --------------------------------------------------------

    field_slugs = (
        get_webflow_field_slugs()
    )

    validate_required_fields(
        field_slugs
    )

    # --------------------------------------------------------
    # Get SportsMonks fixtures
    # --------------------------------------------------------

    fixtures = sm_fixtures()

    # --------------------------------------------------------
    # Get existing Webflow items
    # --------------------------------------------------------

    existing_items = wf_items()

    existing_by_fixture_id = (
        build_existing_index(
            existing_items
        )
    )

    created = 0
    updated = 0

    # --------------------------------------------------------
    # Sync
    # --------------------------------------------------------

    for item in fixtures:

        fixture = item["raw"]

        fixture_id = fixture.get("id")

        fixture_id_string = str(
            fixture_id
        )

        field_data = fixture_field_data(
            item
        )

        existing = (
            existing_by_fixture_id.get(
                fixture_id_string
            )
        )

        try:

            if existing:

                print(
                    "\nUpdating fixture",
                    fixture_id
                )

                update_webflow_item(
                    existing["id"],
                    field_data
                )

                updated += 1

            else:

                print(
                    "\nCreating fixture",
                    fixture_id
                )

                create_webflow_item(
                    field_data
                )

                created += 1

        except Exception as error:

            print(
                "\nFAILED fixture",
                fixture_id
            )

            print(
                "Error:",
                error
            )

            raise

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
# TEST WEBFLOW COLLECTION
# ============================================================

def test_collection():

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
        "COLLECTION TEST STATUS:",
        response.status_code
    )

    print(
        "COLLECTION TEST RESPONSE:",
        response.text
    )

    response.raise_for_status()


# ============================================================
# MAIN
# ============================================================

def main():

    test_collection()

    sync_fixtures()


if __name__ == "__main__":
    main()
