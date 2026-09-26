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

# Team CMS ("First Team Club Logos") — a REFERENCE-ONLY source of static
# team data, keyed by sportsmonks-team-id. sync.py only READS it, and only
# to fill the Fixtures home-team / away-team Reference fields. It never
# creates, updates, or clears any Team CMS item.
TEAM_COLLECTION_ID = "6a9c2ff98dd513bfc472db69"

# Feature flag. While False the sync behaves exactly as before: Team CMS
# is not read and home-team / away-team are never written.
TEAM_REFERENCES_ENABLED = True

COLLECTION_ID = "6a671465e31c8cf8983d3d36"

# ============================================================
# ARABIC SYNC CONFIG
#
# Everything below is inert while ARABIC_SYNC_ENABLED is False — the
# Arabic sub-pass is never even called from sync_fixtures() in that case.
# When enabled, ARABIC_SYNC_DRY_RUN additionally gates every actual
# Webflow write: dry-run logs the planned change and performs no write.
# ============================================================

ARABIC_CMS_LOCALE_ID = "6a671465e31c8cf8983d3d0d"
PRIMARY_CMS_LOCALE_ID = "6a671465e31c8cf8983d3d0c"

ARABIC_SYNC_ENABLED = True
ARABIC_SYNC_DRY_RUN = True

# How many days before "today" the SportMonks fixture query also covers, so a
# match that finished right before UTC midnight can still receive a late
# status/score correction on the next run(s) instead of falling out of range
# forever. Kept small on purpose — this is a correction window, not a
# historical backfill.
LOOKBACK_DAYS = 2

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
# DATE / TIME PARSING
#
# SportMonks always returns starting_at in UTC (see mapper.js /
# previewMapper.js header comments — this has been the established,
# verified contract throughout this project). This parser accepts:
#   - a 'Z'-suffixed ISO timestamp (the normal SportMonks shape)
#   - an ISO timestamp with an explicit +HH:MM/-HH:MM offset
#   - a timestamp with no timezone marker at all
#
# In every case the result is an aware datetime explicitly anchored to
# UTC. A naive (timezone-less) value is NEVER assumed to be in the
# local system's timezone — it is explicitly treated as already being
# UTC, per the SportMonks contract, instead of silently localized via
# an implicit astimezone() call on a naive datetime (which previously
# caused a 3-hour shift whenever starting_at arrived without a
# trailing Z/offset).
# ============================================================

def parse_starting_at(value):

    dt = datetime.fromisoformat(
        value.replace("Z", "+00:00")
    )

    if dt.tzinfo is None:

        dt = dt.replace(tzinfo=timezone.utc)

    return dt.astimezone(timezone.utc)


# ============================================================
# DATE
# ============================================================

def fixture_date(fixture):

    value = fixture.get("starting_at")

    if not value:
        return ""

    try:

        dt = parse_starting_at(value)

        # Webflow DateTime requires ISO UTC
        return (
            dt.isoformat(timespec="milliseconds")
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

        dt = parse_starting_at(value)

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

def sm_fixtures(locale=None):

    today = datetime.now(timezone.utc).date()

    season_end = datetime(
        2027,
        6,
        30,
        tzinfo=timezone.utc
    ).date()

    all_fixtures = []

    current_start = today - timedelta(days=LOOKBACK_DAYS)

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

        if locale:

            params["locale"] = locale

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
# SPORTS MONKS FIXTURES — ARABIC
#
# Thin wrapper around sm_fixtures(): identical endpoint, identical
# date-range chunking/dedup logic, only "locale": "ar" differs in the
# request params. No separate request-per-fixture — same bulk shape as
# the English call.
# ============================================================

def sm_fixtures_arabic():

    return sm_fixtures(locale="ar")


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

WF_PAGE_SIZE = 100


def wf_items(cms_locale_id=None, collection_id=None):

    # Reads EVERY page of the collection (Webflow caps a page at 100
    # items). The first request is identical to the previous
    # single-request behavior (no offset param); further pages are only
    # requested when the collection holds more than one page of items.
    url = (
        f"{WF_BASE}/collections/"
        f"{collection_id or COLLECTION_ID}/items"
    )

    items = []

    offset = 0

    while True:

        params = {
            "limit": WF_PAGE_SIZE,
        }

        if offset:

            params["offset"] = offset

        if cms_locale_id:

            params["cmsLocaleId"] = cms_locale_id

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

        page = data.get("items") or []

        items.extend(page)

        offset += len(page)

        total = (
            data.get("pagination") or {}
        ).get("total")

        if (
            not page
            or len(page) < WF_PAGE_SIZE
            or (total is not None and offset >= total)
        ):
            break

    print(
        "Existing Webflow items:",
        len(items)
    )

    return items


# ============================================================
# GET WEBFLOW ITEMS — ARABIC
#
# Same endpoint/shape as wf_items(), scoped to the Arabic CMS locale via
# cmsLocaleId. Only items that ALREADY have an Arabic locale row are
# returned here — this is the pre-flight source used to decide which
# fixtures are eligible for an Arabic update at all.
# ============================================================

def wf_items_arabic():

    return wf_items(
        cms_locale_id=ARABIC_CMS_LOCALE_ID
    )


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
# TEAM CMS — REFERENCE LOOKUP (READ-ONLY)
#
# Everything here is inert while TEAM_REFERENCES_ENABLED is False.
# When enabled: Team CMS is read ONCE per run (all pages), a map
# {sportsmonks-team-id -> Webflow team item id} is built, and each
# fixture's SportMonks home/away team ids are looked up in it. Matching
# is by sportsmonks-team-id ONLY — never by team name, never by any
# translation. Team CMS is never written to, and a missing team never
# creates an item or clears an existing Reference: a Reference key is
# simply left out of the payload, and Webflow's partial-update semantics
# keep whatever value is already stored.
# ============================================================

def build_team_map(items):

    candidates = {}

    excluded = 0

    for item in items:

        field_data = item.get("fieldData") or {}

        team_id = safe_text(
            field_data.get("sportsmonks-team-id")
        ).strip()

        if not team_id:
            excluded += 1
            continue

        if (
            item.get("isArchived")
            or item.get("isDraft")
            or not item.get("lastPublished")
        ):
            excluded += 1
            continue

        candidates.setdefault(team_id, []).append(item.get("id"))

    team_map = {}

    for team_id, item_ids in candidates.items():

        if len(item_ids) > 1:

            print(
                "[TEAM] WARNING: duplicate sportsmonks-team-id",
                team_id,
                "in Team CMS — excluded from the map, no reference"
                " will be written for it"
            )

            excluded += len(item_ids)

            continue

        team_map[team_id] = item_ids[0]

    print(
        "[TEAM] Team CMS items read:",
        len(items),
        "| usable:",
        len(team_map),
        "| excluded:",
        excluded
    )

    return team_map


def load_team_map():

    if not TEAM_REFERENCES_ENABLED:

        return {}

    try:

        items = wf_items(collection_id=TEAM_COLLECTION_ID)

    except Exception as err:

        print(
            "[TEAM] WARNING: Team CMS read failed:",
            err
        )
        print(
            "[TEAM] English sync continues, no team references"
            " written this run, existing references untouched"
        )

        return {}

    return build_team_map(items)


def team_reference_fields(fixture, team_map, stats=None):

    refs = {}

    if not team_map:

        return refs

    home, away = get_participants(fixture)

    for key, participant in (
        ("home-team", home),
        ("away-team", away),
    ):

        team_id = safe_text(participant_id(participant))

        team_item_id = team_map.get(team_id) if team_id else None

        if team_item_id:

            refs[key] = team_item_id

            continue

        print(
            "[TEAM] WARNING: TEAM_MISSING",
            key,
            "sportsmonks-team-id =",
            team_id or "(none)",
            "| fixture",
            safe_text(fixture.get("id")),
            "| not in Team CMS — reference left as is"
        )

        if stats is not None:

            stats["missing"].setdefault(
                team_id or "(none)",
                participant_name(participant)
            )

    if stats is not None:

        stats["fixtures"] += 1

        stats["linked"] += len(refs)

    return refs


# A Reference write can be rejected (400/404/422) without anything having
# been created or changed; only those statuses are retried without the
# references. Any other failure (including 5xx, where a create may have
# partially succeeded) is raised exactly as before, so it can never lead
# to a duplicate item.
REFERENCE_RETRY_STATUSES = (400, 404, 422)


def _reference_rejected(err):

    response = getattr(err, "response", None)

    return (
        response is not None
        and response.status_code in REFERENCE_RETRY_STATUSES
    )


def create_fixture_with_team_refs(field_data, team_refs):

    if not team_refs:

        return create_webflow_item(field_data)

    payload = dict(field_data)

    payload.update(team_refs)

    try:

        return create_webflow_item(payload)

    except requests.exceptions.HTTPError as err:

        if not _reference_rejected(err):
            raise

        print(
            "[TEAM] WARNING: Webflow rejected the team references on"
            " CREATE — creating the fixture without them"
        )

        return create_webflow_item(field_data)


def update_fixture_with_team_refs(item_id, field_data, team_refs):

    if not team_refs:

        return update_webflow_item(item_id, field_data)

    payload = dict(field_data)

    payload.update(team_refs)

    try:

        return update_webflow_item(item_id, payload)

    except requests.exceptions.HTTPError as err:

        if not _reference_rejected(err):
            raise

        print(
            "[TEAM] WARNING: Webflow rejected the team references on"
            " UPDATE — updating the fixture without them"
        )

        return update_webflow_item(item_id, field_data)


def print_team_reference_summary(stats):

    print()
    print("[TEAM] REFERENCE SUMMARY")
    print("Fixtures processed:", stats["fixtures"])
    print("References set:", stats["linked"])
    print("Teams missing from Team CMS:", len(stats["missing"]))

    for team_id, name in sorted(stats["missing"].items()):

        print("  MISSING:", team_id, "|", name)


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

    return response.json().get("id")


# ============================================================
# UPDATE WEBFLOW ITEM
# ============================================================

def update_webflow_item(
    item_id,
    field_data,
    cms_locale_id=None
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

    if cms_locale_id:

        # SAFEGUARD: an Arabic-sync caller must always pass the Arabic
        # CMS locale id, never the primary one. This makes it
        # structurally impossible for the Arabic code path to write to
        # the primary/English locale.
        assert cms_locale_id == ARABIC_CMS_LOCALE_ID, (
            "update_webflow_item received a cms_locale_id that is not "
            "the Arabic CMS locale — refusing to write."
        )

        assert cms_locale_id != PRIMARY_CMS_LOCALE_ID, (
            "update_webflow_item must never target the primary locale "
            "via cms_locale_id."
        )

        payload["cmsLocaleId"] = cms_locale_id

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
# CREATE WEBFLOW ITEM — ARABIC LOCALE VARIANT
#
# Attaches a NEW Arabic locale row to an EXISTING primary item via
# Webflow's "Create Items" (bulk/insert) endpoint, NOT the single-item
# "Create Item" endpoint that create_webflow_item() uses. This is a
# different Webflow endpoint with a different payload shape — confirmed
# directly against Webflow's official v2 API documentation
# (developers.webflow.com, "Create Items" / items/insert):
#
#   POST /v2/collections/{collection_id}/items/insert
#   { "items": [ { "id": <existing item id>, "cmsLocaleIds": [...],
#                  "fieldData": {...} } ] }
#
# Passing "id" (the existing primary item's id) is what makes this call
# attach a locale variant to that SAME item instead of creating a new,
# unrelated collection item — omitting "id" would create a new item.
# This function therefore REQUIRES item_id and always sends exactly one
# cmsLocaleId: the Arabic one. It never sends allCmsLocales and never
# includes PRIMARY_CMS_LOCALE_ID.
#
# name/slug REQUIREMENT (Webflow requires both in fieldData on create,
# even when attaching a locale to an existing item):
#
#   slug — the Primary item's own slug, reused verbatim (never an invented
#   Arabic slug). Added by the caller to the create-only payload.
#
#   name — built by the caller from the two Arabic Team CMS names; the
#   English name is never a fallback. The caller blocks creation before
#   reaching this function if either team has no Arabic variant.
#
# This function re-checks both, and the field allow-list, as a
# defense-in-depth guard — it never trusts the caller blindly.
# ============================================================

def create_webflow_item_arabic_variant(item_id, field_data):

    assert item_id, (
        "create_webflow_item_arabic_variant requires an existing "
        "primary item id — refusing to create an unlinked item."
    )

    if not field_data.get("slug"):

        raise ValueError(
            "Refusing to create an Arabic variant with an empty/missing "
            "'slug' — Webflow requires it, and no value is invented here."
        )

    if not field_data.get("name"):

        raise ValueError(
            "Refusing to create an Arabic variant with an empty/missing "
            "'name' — the English name is never used as a fallback."
        )

    assert_arabic_payload(field_data, ARABIC_CREATE_FIELDS)

    url = (
        f"{WF_BASE}/collections/"
        f"{COLLECTION_ID}/items/insert"
    )

    payload = {
        "items": [
            {
                "id": item_id,
                "cmsLocaleIds": [ARABIC_CMS_LOCALE_ID],
                "isDraft": True,
                "isArchived": False,
                "fieldData": field_data,
            }
        ]
    }

    response = requests.post(
        url,
        headers=wf_headers(),
        json=payload,
        timeout=30,
    )

    print(
        "CREATE ARABIC VARIANT STATUS:",
        response.status_code
    )

    if not response.ok:

        print(
            "CREATE ARABIC VARIANT RESPONSE:",
            response.text
        )

        print(
            "CREATE ARABIC VARIANT PAYLOAD:",
            payload
        )

        response.raise_for_status()

    data = response.json()

    created_items = data.get("items") or []

    # SAFEGUARD: verify the response actually describes a locale variant
    # of the SAME item, on the Arabic locale — never trust success blindly.
    if (
        not created_items
        or created_items[0].get("id") != item_id
    ):
        raise RuntimeError(
            "Arabic variant create response did not echo back the same "
            "item id — refusing to treat this as a verified success."
        )

    if created_items[0].get("cmsLocaleId") != ARABIC_CMS_LOCALE_ID:
        raise RuntimeError(
            "Arabic variant create response locale mismatch — refusing "
            "to treat this as a verified success."
        )

    print(
        "Created Arabic variant for item:",
        item_id
    )

    return created_items[0].get("id")


# ============================================================
# PUBLISH WEBFLOW ITEMS
# ============================================================

def publish_webflow_items(item_ids):

    # Items created/updated via the API above land as staged changes —
    # this call is what actually makes them live on alkholoodclub.com /
    # www.alkholoodclub.com. Batched at 100 per request (Webflow's own
    # limit on this endpoint).
    #
    # Unlike sync_u21_players.py's publish step, a failure here is FATAL
    # (raise_for_status is allowed to propagate): if the CMS write
    # succeeded but the publish fails, the live site would silently keep
    # serving stale data, so the run must fail loudly instead of masking it.

    if not item_ids:
        return

    url = (
        f"{WF_BASE}/collections/"
        f"{COLLECTION_ID}/items/publish"
    )

    for i in range(0, len(item_ids), 100):

        batch = item_ids[i:i + 100]

        response = requests.post(
            url,
            headers=wf_headers(),
            json={"itemIds": batch},
            timeout=30,
        )

        print(
            "PUBLISH STATUS:",
            response.status_code
        )

        if not response.ok:

            print(
                "PUBLISH RESPONSE:",
                response.text
            )

            response.raise_for_status()

        print(
            "Published Webflow items:",
            len(batch)
        )


# ============================================================
# ARABIC — SOURCES OF TRUTH
#
# Nothing Arabic comes from SportMonks' locale=ar response and nothing
# falls back to English:
#
#   - Team names / Team references: the Arabic locale variant of each
#     Team CMS item (same item id as the Primary team). Team CMS is only
#     ever READ here — Arabic sync never creates a team, never edits one.
#   - League: the fixed mapping below (unknown league -> field omitted).
#   - Everything else (venue, date, time, status, scores, logos, slug):
#     copied from the English side, exactly as the English pass writes it.
#
# match-hub-link is deliberately never part of an Arabic payload.
# ============================================================

ARABIC_LEAGUE_NAMES = {
    "Pro League": "دوري روشن",
    "Kings Cup": "كأس الملك",
}

ARABIC_TECHNICAL_FIELDS = (
    "status",
    "home-team-score",
    "away-team-score",
    "date-time",
    "time-3",
    "venue",
)

ARABIC_LOGO_FIELDS = (
    "opposing-team-logo",
    "away-team-logo",
    "tournament-logo",
)

# Allow-lists: an Arabic write containing any other key is refused before
# it reaches Webflow (this is what keeps match-hub-link, seo-*, ticket-link
# and every other field out of Arabic writes).
ARABIC_UPDATE_FIELDS = frozenset(
    ARABIC_TECHNICAL_FIELDS
    + (
        "name",
        "home-team-name",
        "away-team-name",
        "home-team",
        "away-team",
        "league",
    )
)

ARABIC_CREATE_FIELDS = ARABIC_UPDATE_FIELDS | frozenset(
    ("slug", "sportsmonks-id") + ARABIC_LOGO_FIELDS
)


def assert_arabic_payload(field_data, allowed):

    unexpected = set(field_data) - set(allowed)

    assert not unexpected, (
        "Arabic write contains fields outside the allow-list: "
        + ", ".join(sorted(unexpected))
    )

    assert "match-hub-link" not in field_data, (
        "match-hub-link must never be sent in an Arabic write."
    )


# ============================================================
# ARABIC — TEAM INDEX
#
# {sportsmonks-team-id: {"id": <team item id>, "name": <Arabic name>}}
#
# Built from the Primary map (already loaded once by sync_fixtures) joined,
# by item id, to the Arabic locale rows of the Team CMS. A team appears
# here only if its Arabic variant exists, is not archived, really is an
# Arabic-locale row and has a non-empty Arabic name. Anything else is
# reported and left out — so a fixture that needs it gets no reference
# rather than a wrong one, and a Primary item is never used in its place.
# ============================================================

def load_arabic_team_index(primary_teams):

    if not primary_teams:

        print(
            "[AR] WARNING: Primary team lookup is empty — no Arabic"
            " team references or names can be resolved this run"
        )

        return {}

    rows = wf_items(
        cms_locale_id=ARABIC_CMS_LOCALE_ID,
        collection_id=TEAM_COLLECTION_ID,
    )

    rows_by_item_id = {}

    for row in rows:

        if row.get("cmsLocaleId") != ARABIC_CMS_LOCALE_ID:
            continue

        rows_by_item_id[row.get("id")] = row

    index = {}

    for team_id, item_id in primary_teams.items():

        row = rows_by_item_id.get(item_id)

        if not row or row.get("isArchived"):

            print(
                "[AR] WARNING: no usable Arabic Team variant for"
                " sportsmonks-team-id",
                team_id,
                "(team item",
                item_id + ") — fixtures using it get no Arabic team data"
            )

            continue

        name = safe_text(
            (row.get("fieldData") or {}).get("name")
        ).strip()

        if not name:

            print(
                "[AR] WARNING: Arabic Team variant has an empty name for"
                " sportsmonks-team-id",
                team_id
            )

            continue

        index[team_id] = {"id": item_id, "name": name}

    print(
        "[AR] Arabic Team variants usable:",
        len(index),
        "of",
        len(primary_teams)
    )

    return index


# ============================================================
# ARABIC — FIELD DATA
#
# Returns (field_data, log_lines, missing_team_ids).
#
# Team-dependent fields (name, home-team-name, away-team-name, home-team,
# away-team) are produced ONLY when BOTH teams resolve to an Arabic Team
# variant — never half of them, never an English name, never a Primary
# item. Technical fields are taken from the same builder the English pass
# uses, so Arabic can never disagree with English.
# ============================================================

def fixture_field_data_arabic(fixture_en, arabic_index):

    base = fixture_field_data(fixture_en, include_logos=False)

    field_data = {
        key: base[key] for key in ARABIC_TECHNICAL_FIELDS
    }

    log_lines = []

    home, away = get_participants(fixture_en)

    resolved = []
    missing = []

    for participant in (home, away):

        team_id = safe_text(participant_id(participant))

        entry = arabic_index.get(team_id) if team_id else None

        if entry:
            resolved.append(entry)
        else:
            missing.append(team_id or "(none)")

    if not missing:

        home_entry, away_entry = resolved

        field_data["home-team-name"] = home_entry["name"]
        field_data["away-team-name"] = away_entry["name"]
        field_data["name"] = (
            f"{home_entry['name']} ضد {away_entry['name']}"
        )
        field_data["home-team"] = home_entry["id"]
        field_data["away-team"] = away_entry["id"]

        log_lines.append(("teams", "RESOLVED"))

    else:

        log_lines.append(
            ("teams", "MISSING_ARABIC_TEAM " + ",".join(missing))
        )

    league_ar = ARABIC_LEAGUE_NAMES.get(base["league"])

    if league_ar:

        field_data["league"] = league_ar

        log_lines.append(("league", "MAPPED"))

    else:

        log_lines.append(
            ("league", "UNMAPPED (" + (base["league"] or "empty") + ")")
        )

    return field_data, log_lines, missing


def _arabic_value(value):

    return "" if value is None else str(value)


# ============================================================
# ARABIC SYNC
#
# Entirely additive and isolated from the English pass:
#   - Only called when ARABIC_SYNC_ENABLED is True; ARABIC_SYNC_DRY_RUN
#     additionally turns every write into a log line.
#   - A fixture is only considered if this run's English pass processed
#     it (so old fixtures outside the SportMonks window are never
#     touched) and its Primary item is not archived.
#   - The Arabic row is found by ITEM ID (an Arabic variant shares the
#     Primary item's id). No row -> create the variant on that same id;
#     row -> update it. Never a second variant: if any other Arabic row
#     already carries this sportsmonks-id, the fixture is skipped.
#   - An existing Arabic row is only updated if it is already linked to
#     Arabic Team items (home-team AND away-team set). Rows without them
#     — the 42 legacy Arabic fixtures — are never touched.
#   - Updates send only the fields whose value actually differs.
#   - Writes go through update_webflow_item(cms_locale_id=Arabic) /
#     create_webflow_item_arabic_variant() only: the primary locale is
#     structurally unreachable. Nothing is ever published, and Team CMS
#     is never written.
#   - Any failure is caught locally so the completed English sync and its
#     publish step are never affected.
# ============================================================

def sync_fixtures_arabic(
    fixtures_en,
    item_id_by_fixture_id,
    primary_archived_by_fixture_id=None,
    primary_slug_by_fixture_id=None,
    primary_teams=None,
    primary_logos_by_fixture_id=None
):

    print()
    print("[AR] START")
    print("[AR] Dry run:", "YES" if ARABIC_SYNC_DRY_RUN else "NO")

    primary_archived_by_fixture_id = (
        primary_archived_by_fixture_id or {}
    )

    primary_slug_by_fixture_id = (
        primary_slug_by_fixture_id or {}
    )

    primary_logos_by_fixture_id = (
        primary_logos_by_fixture_id or {}
    )

    stats = {
        "considered": 0,
        "matched": 0,
        "updated": 0,
        "unchanged": 0,
        "would_create": 0,
        "created": 0,
        "would_update": 0,
        "blocked_missing_arabic_team": 0,
        "blocked_missing_slug": 0,
        "partial_missing_arabic_team": 0,
        "skipped_unmanaged_variant": 0,
        "skipped_duplicate_risk": 0,
        "skipped_archived_variant": 0,
        "skipped_archived_primary": 0,
        "skipped_not_in_run": 0,
        "skipped_missing_required_field": 0,
        "api_errors": 0,
    }

    try:

        arabic_index = load_arabic_team_index(primary_teams)

        arabic_items = wf_items_arabic()

    except Exception as err:

        print("[AR] Webflow read failed:", err)
        print("[AR] Arabic CMS preserved, Arabic sync skipped this run")

        stats["api_errors"] += 1

        return stats

    if any(
        item.get("cmsLocaleId") != ARABIC_CMS_LOCALE_ID
        for item in arabic_items
    ):

        print(
            "[AR] Webflow returned a row that is not in the Arabic"
            " locale — cannot trust the read, Arabic sync skipped"
        )

        stats["api_errors"] += 1

        return stats

    arabic_by_item_id = {}

    arabic_item_ids_by_fixture_id = {}

    for item in arabic_items:

        arabic_by_item_id[item.get("id")] = item

        sportsmonks_id = safe_text(
            (item.get("fieldData") or {}).get("sportsmonks-id")
        )

        if sportsmonks_id:

            arabic_item_ids_by_fixture_id.setdefault(
                sportsmonks_id, set()
            ).add(item.get("id"))

    fixtures_en_by_id = {
        safe_text(f.get("id")): f
        for f in fixtures_en
    }

    for fixture_id, primary_item_id in item_id_by_fixture_id.items():

        stats["considered"] += 1

        print()
        print("[AR] Fixture", fixture_id)

        if primary_archived_by_fixture_id.get(fixture_id):

            print("[AR] Primary item: ARCHIVED — SKIP")

            stats["skipped_archived_primary"] += 1

            continue

        fixture_en = fixtures_en_by_id.get(fixture_id)

        if not fixture_en:

            print("[AR] Fixture not present in this run's fetch — SKIP")

            stats["skipped_not_in_run"] += 1

            continue

        other_ids = (
            arabic_item_ids_by_fixture_id.get(fixture_id, set())
            - {primary_item_id}
        )

        if other_ids:

            print(
                "[AR] Another Arabic row already carries this"
                " sportsmonks-id — SKIP (duplicate risk)"
            )

            stats["skipped_duplicate_risk"] += 1

            continue

        field_data, log_lines, missing = fixture_field_data_arabic(
            fixture_en,
            arabic_index
        )

        for label, status in log_lines:
            print(f"[AR]   {label}: {status}")

        arabic_item = arabic_by_item_id.get(primary_item_id)

        # ====================================================
        # NO ARABIC VARIANT -> CREATE ON THE SAME ITEM ID
        # ====================================================

        if not arabic_item:

            print("[AR] Arabic variant: MISSING")

            if missing:

                print("[AR] Action: BLOCK CREATE")
                print("[AR] Reason: missing_arabic_team", missing)

                stats["blocked_missing_arabic_team"] += 1

                continue

            primary_slug = primary_slug_by_fixture_id.get(fixture_id)

            if not primary_slug:

                print("[AR] Action: BLOCK CREATE")
                print("[AR] Reason: missing_slug")

                stats["blocked_missing_slug"] += 1

                continue

            create_field_data = dict(field_data)

            create_field_data["slug"] = primary_slug
            create_field_data["sportsmonks-id"] = fixture_id

            for logo_field in ARABIC_LOGO_FIELDS:

                logo = (
                    primary_logos_by_fixture_id.get(fixture_id) or {}
                ).get(logo_field)

                if logo:
                    create_field_data[logo_field] = logo

            # Empty text values are omitted on create, never sent blank.
            create_field_data = {
                key: value
                for key, value in create_field_data.items()
                if value not in ("", None)
            }

            assert_arabic_payload(
                create_field_data,
                ARABIC_CREATE_FIELDS
            )

            if ARABIC_SYNC_DRY_RUN:

                print("[AR] Action: DRY-RUN CREATE (no write performed)")

                stats["would_create"] += 1

            else:

                try:

                    create_webflow_item_arabic_variant(
                        primary_item_id,
                        create_field_data
                    )

                    print("[AR] Action: CREATE")

                    stats["created"] += 1

                except ValueError as err:

                    print("[AR] Create blocked:", err)

                    stats["skipped_missing_required_field"] += 1

                except Exception as err:

                    print("[AR] Webflow Arabic create failed:", err)

                    stats["api_errors"] += 1

            continue

        # ====================================================
        # ARABIC VARIANT EXISTS -> GUARDS, THEN UPDATE
        # ====================================================

        if arabic_item.get("isArchived"):

            print("[AR] Arabic variant: ARCHIVED — SKIP")

            stats["skipped_archived_variant"] += 1

            continue

        existing_data = arabic_item.get("fieldData") or {}

        if not (
            existing_data.get("home-team")
            and existing_data.get("away-team")
        ):

            print(
                "[AR] Arabic variant has no Arabic Team references —"
                " not managed by this sync, SKIP"
            )

            stats["skipped_unmanaged_variant"] += 1

            continue

        print("[AR] Arabic variant: FOUND")

        stats["matched"] += 1

        if missing:

            print(
                "[AR] WARNING: missing Arabic Team variant",
                missing,
                "— names/references left as they are, technical"
                " fields only"
            )

            stats["partial_missing_arabic_team"] += 1

        changes = {
            key: value
            for key, value in field_data.items()
            if _arabic_value(existing_data.get(key))
            != _arabic_value(value)
        }

        if not changes:

            print("[AR] Changes: none")

            stats["unchanged"] += 1

            continue

        assert_arabic_payload(changes, ARABIC_UPDATE_FIELDS)

        print("[AR] Changes:", ", ".join(sorted(changes)))

        if ARABIC_SYNC_DRY_RUN:

            print("[AR] Action: DRY-RUN UPDATE (no write performed)")

            stats["would_update"] += 1

            continue

        try:

            update_webflow_item(
                primary_item_id,
                changes,
                cms_locale_id=ARABIC_CMS_LOCALE_ID
            )

            print("[AR] Action: UPDATE")

            stats["updated"] += 1

        except Exception as err:

            print("[AR] Webflow Arabic update failed:", err)

            stats["api_errors"] += 1

    print()
    print("[AR] SUMMARY")

    for key, value in stats.items():

        print(f"{key}: {value}")

    print("Published: 0")

    return stats


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

    # Team CMS -> {sportsmonks-team-id: item id}. Empty (and Team CMS is
    # not even read) unless TEAM_REFERENCES_ENABLED; empty as well if the
    # read fails, in which case no reference is written this run.
    team_map = load_team_map()

    team_ref_stats = {"fixtures": 0, "linked": 0, "missing": {}}

    created = 0
    updated = 0
    skipped = 0
    failed = 0

    changes_made = False
    touched_item_ids = []

    # Tracks fixture_id -> Webflow (primary) item id for every fixture
    # processed this run, so the Arabic sub-pass can match by the
    # immutable sportsmonks-id without re-deriving anything.
    item_id_by_fixture_id = {}

    # Tracks fixture_id -> primary item's isArchived flag, so the Arabic
    # sub-pass can skip an archived primary explicitly rather than
    # relying only on it being absent from a live SportMonks fetch.
    primary_archived_by_fixture_id = {}

    # Tracks fixture_id -> primary item's own slug, so the Arabic CREATE
    # path can reuse it verbatim (a required technical value, never a
    # translation) without a second Webflow read.
    primary_slug_by_fixture_id = {}

    # Tracks fixture_id -> the three logo values of the primary item, so a
    # newly created Arabic variant shows the same logos as English (an
    # Arabic row does not inherit them).
    primary_logos_by_fixture_id = {}

    # --------------------------------------------------------
    # Process fixtures
    # --------------------------------------------------------

    for fixture in fixtures:

        fixture_id = safe_text(
            fixture.get("id")
        )

        if not fixture_id:
            skipped += 1
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

            team_refs = team_reference_fields(
                fixture,
                team_map,
                team_ref_stats
            )

            update_fixture_with_team_refs(
                existing["id"],
                field_data,
                team_refs
            )

            touched_item_ids.append(
                existing["id"]
            )

            item_id_by_fixture_id[
                fixture_id
            ] = existing["id"]

            primary_archived_by_fixture_id[
                fixture_id
            ] = existing.get("isArchived", False)

            primary_slug_by_fixture_id[
                fixture_id
            ] = (
                existing.get("fieldData") or {}
            ).get("slug")

            primary_logos_by_fixture_id[
                fixture_id
            ] = {
                key: (existing.get("fieldData") or {}).get(key)
                for key in ARABIC_LOGO_FIELDS
            }

            updated += 1
            changes_made = True

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

            team_refs = team_reference_fields(
                fixture,
                team_map,
                team_ref_stats
            )

            new_item_id = create_fixture_with_team_refs(
                field_data,
                team_refs
            )

            if new_item_id:
                touched_item_ids.append(
                    new_item_id
                )

                item_id_by_fixture_id[
                    fixture_id
                ] = new_item_id

                # A newly created item is never archived.
                primary_archived_by_fixture_id[
                    fixture_id
                ] = False

                primary_slug_by_fixture_id[
                    fixture_id
                ] = field_data.get("slug")

                primary_logos_by_fixture_id[
                    fixture_id
                ] = {
                    key: field_data.get(key)
                    for key in ARABIC_LOGO_FIELDS
                }

            created += 1
            changes_made = True

    if TEAM_REFERENCES_ENABLED:

        print_team_reference_summary(team_ref_stats)

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
        f"Skipped (no fixture id): {skipped}"
    )

    # NOTE: "failed" stays 0 by design in this file's current error-handling
    # style — every Webflow/SportMonks call above uses raise_for_status()
    # uncaught, so a real create/update failure stops the run immediately
    # (non-zero exit) rather than being counted and continuing to the next
    # fixture. The counter is kept here for a clear, consistent summary
    # line and so it's available if that behavior is ever intentionally
    # changed later — it is not a sign this run continued past a failure.
    print(
        f"Failed: {failed}"
    )

    print(
        "========================================"
    )

    # --------------------------------------------------------
    # Arabic sync
    #
    # Entirely additive and isolated from everything above. Only runs
    # at all when ARABIC_SYNC_ENABLED is True; wrapped so that any
    # failure here can never affect the English create/update work
    # already completed, or the Publish step immediately below.
    # --------------------------------------------------------

    if ARABIC_SYNC_ENABLED:

        try:

            sync_fixtures_arabic(
                fixtures,
                item_id_by_fixture_id,
                primary_archived_by_fixture_id,
                primary_slug_by_fixture_id,
                primary_teams=team_map,
                primary_logos_by_fixture_id=primary_logos_by_fixture_id
            )

        except Exception as err:

            print()
            print(
                "[AR] Arabic sync raised an unexpected error:",
                err
            )
            print(
                "[AR] English sync unaffected, continuing to publish"
            )

    # --------------------------------------------------------
    # Publish
    #
    # Only publish when at least one item was actually created or
    # updated this run. No changes -> no publish call at all.
    # --------------------------------------------------------

    print()

    if changes_made:

        print("Changes detected: Yes")
        print("Publishing changes...")

        publish_webflow_items(touched_item_ids)

        print("Publish successful.")

    else:

        print("Changes detected: No")
        print("Publish skipped.")


# ============================================================
# MAIN
# ============================================================

def main():

    sync_fixtures()


if __name__ == "__main__":

    main()
