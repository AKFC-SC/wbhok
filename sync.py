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
TEAM_REFERENCES_ENABLED = False

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

ARABIC_SYNC_ENABLED = False
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
# ARABIC — TRANSLATION CLASSIFICATION
#
# No manual glossary and no English fallback ever happens here. A value
# is only ever written to the Arabic CMS locale when SportMonks' own
# locale=ar response genuinely differs from the English value for that
# same field. Missing or fallback-identical values are classified and
# simply left out of the write payload — never replaced with "" and
# never replaced with the English value.
# ============================================================

def classify_arabic_value(en_value, ar_value):

    if not ar_value:
        return "MISSING"

    if ar_value == en_value:
        return "FALLBACK"

    return "TRANSLATED"


# ============================================================
# ARABIC — FIELD DATA
#
# Builds the fieldData dict for an Arabic CMS write. Language fields are
# included ONLY when classify_arabic_value() returns "TRANSLATED" for
# that field. Technical/dynamic fields are always included, sourced from
# the already-fetched English fixture (fixture_en) — never requested a
# second time from SportMonks, and never subject to translation logic
# since they are locale-independent facts (a score is a score).
# ============================================================

def fixture_field_data_arabic(fixture_en, fixture_ar):

    home_en, away_en = get_participants(fixture_en)
    home_ar, away_ar = get_participants(fixture_ar)

    field_data = {}

    log_lines = []

    home_en_name = participant_name(home_en)
    home_ar_name = participant_name(home_ar)
    home_status = classify_arabic_value(
        home_en_name,
        home_ar_name
    )

    if home_status == "TRANSLATED":
        field_data["home-team-name"] = home_ar_name

    log_lines.append(("home-team-name", home_status))

    away_en_name = participant_name(away_en)
    away_ar_name = participant_name(away_ar)
    away_status = classify_arabic_value(
        away_en_name,
        away_ar_name
    )

    if away_status == "TRANSLATED":
        field_data["away-team-name"] = away_ar_name

    log_lines.append(("away-team-name", away_status))

    # "name" is only regenerated when BOTH team names are genuinely
    # translated this run — never a half-English/half-Arabic title.
    if (
        home_status == "TRANSLATED"
        and away_status == "TRANSLATED"
    ):
        field_data["name"] = f"{home_ar_name} ضد {away_ar_name}"

    venue_en = safe_text(
        (fixture_en.get("venue") or {}).get("name", "")
    )
    venue_ar = safe_text(
        (fixture_ar.get("venue") or {}).get("name", "")
    )
    venue_status = classify_arabic_value(
        venue_en,
        venue_ar
    )

    if venue_status == "TRANSLATED":
        field_data["venue"] = venue_ar

    log_lines.append(("venue", venue_status))

    league_en = safe_text(
        (fixture_en.get("league") or {}).get("name", "")
    )
    league_ar = safe_text(
        (fixture_ar.get("league") or {}).get("name", "")
    )
    league_status = classify_arabic_value(
        league_en,
        league_ar
    )

    if league_status == "TRANSLATED":
        field_data["league"] = league_ar

    log_lines.append(("league", league_status))

    # ========================================================
    # TECHNICAL / DYNAMIC FIELDS
    #
    # Always sourced from the EN response — never translated, never
    # requested a second time. Kept in sync so Arabic never shows a
    # stale status/score/date relative to the live English fixture.
    # ========================================================

    home_id_en = participant_id(home_en)
    away_id_en = participant_id(away_en)

    state_en = fixture_en.get("state") or {}

    field_data["status"] = safe_text(
        state_en.get("name", "")
    )

    field_data["home-team-score"] = get_score(
        fixture_en,
        home_id_en
    )

    field_data["away-team-score"] = get_score(
        fixture_en,
        away_id_en
    )

    field_data["date-time"] = fixture_date(fixture_en)

    field_data["time-3"] = fixture_time(fixture_en)

    return field_data, log_lines


# ============================================================
# ARABIC SYNC
#
# Entirely additive and isolated from the English pass:
#   - Only called when ARABIC_SYNC_ENABLED is True.
#   - Only ever calls update_webflow_item() — never create_collection_items.
#   - Only targets fixtures whose Webflow item already has an Arabic
#     locale row (wf_items_arabic()) AND that row is not archived.
#   - Every Webflow write goes through update_webflow_item() with
#     cms_locale_id=ARABIC_CMS_LOCALE_ID, which asserts it is never the
#     primary locale (see update_webflow_item()).
#   - Never appends to touched_item_ids, so Arabic items are never
#     published by the existing publish_webflow_items() call.
#   - Any failure here (SportMonks request, Webflow request, or an
#     unexpected exception) is caught locally so the already-completed
#     English sync and its publish step are never affected.
# ============================================================

def sync_fixtures_arabic(
    fixtures_en,
    item_id_by_fixture_id
):

    print()
    print("[AR] START")
    print("[AR] SportMonks locale=ar")

    stats = {
        "fetched": 0,
        "matched": 0,
        "updated": 0,
        "skipped_missing_variant": 0,
        "skipped_archived_variant": 0,
        "api_errors": 0,
    }

    try:

        fixtures_ar = sm_fixtures_arabic()

    except Exception as err:

        print(
            "[AR] SportMonks Arabic request failed:",
            err
        )
        print("[AR] Arabic CMS preserved, Arabic sync skipped this run")

        stats["api_errors"] += 1

        return stats

    stats["fetched"] = len(fixtures_ar)

    print(
        "[AR] Fixtures fetched:",
        stats["fetched"]
    )

    try:

        arabic_items = wf_items_arabic()

    except Exception as err:

        print(
            "[AR] Webflow Arabic items request failed:",
            err
        )
        print("[AR] Arabic CMS preserved, Arabic sync skipped this run")

        stats["api_errors"] += 1

        return stats

    arabic_by_fixture_id = {}

    for item in arabic_items:

        field_data = (
            item.get("fieldData")
            or {}
        )

        fixture_id = field_data.get(
            "sportsmonks-id"
        )

        if fixture_id:

            arabic_by_fixture_id[
                safe_text(fixture_id)
            ] = item

    fixtures_ar_by_id = {
        safe_text(f.get("id")): f
        for f in fixtures_ar
    }

    fixtures_en_by_id = {
        safe_text(f.get("id")): f
        for f in fixtures_en
    }

    for fixture_id, primary_item_id in item_id_by_fixture_id.items():

        print()
        print(
            "[AR] Fixture",
            fixture_id
        )

        # ====================================================
        # ARABIC VARIANT EXISTENCE / ARCHIVED CHECK
        #
        # Missing and archived variants are both SKIP + LOG only.
        # No create, no unarchive, no recreate, no publish.
        # ====================================================

        arabic_item = arabic_by_fixture_id.get(
            fixture_id
        )

        if not arabic_item:

            print("[AR] Arabic variant: MISSING")
            print("[AR] Action: SKIP")

            stats["skipped_missing_variant"] += 1

            continue

        if arabic_item.get("isArchived"):

            print("[AR] Arabic variant: ARCHIVED")
            print("[AR] Action: SKIP")

            stats["skipped_archived_variant"] += 1

            continue

        if arabic_item.get("id") != primary_item_id:

            # Should never happen — same logical item, same id across
            # locales. Treat as a hard skip rather than guess.
            print(
                "[AR] Arabic item id mismatch, unexpected — SKIP"
            )

            stats["skipped_missing_variant"] += 1

            continue

        fixture_en = fixtures_en_by_id.get(
            fixture_id
        )
        fixture_ar = fixtures_ar_by_id.get(
            fixture_id
        )

        if not fixture_en or not fixture_ar:

            print(
                "[AR] Fixture not present in this run's fetch — SKIP"
            )

            stats["skipped_missing_variant"] += 1

            continue

        print("[AR] Arabic variant: FOUND")

        stats["matched"] += 1

        field_data, log_lines = fixture_field_data_arabic(
            fixture_en,
            fixture_ar
        )

        changed_fields = [
            field
            for field in field_data
            if field not in (
                "status",
                "home-team-score",
                "away-team-score",
                "date-time",
                "time-3",
            )
        ]

        for label, status in log_lines:
            print(
                f"[AR]   {label}: {status}"
            )

        if changed_fields:
            print(
                "[AR] Changes:",
                ", ".join(changed_fields)
            )
        else:
            print(
                "[AR] Changes: (none — only technical fields synced)"
            )

        if ARABIC_SYNC_DRY_RUN:

            print("[AR] Action: DRY-RUN (no write performed)")

        else:

            try:

                update_webflow_item(
                    primary_item_id,
                    field_data,
                    cms_locale_id=ARABIC_CMS_LOCALE_ID
                )

                print("[AR] Action: UPDATE")

                stats["updated"] += 1

            except Exception as err:

                print(
                    "[AR] Webflow Arabic update failed:",
                    err
                )

                stats["api_errors"] += 1

        print("[AR] Publish: SKIPPED")

    print()
    print("[AR] SUMMARY")
    print("Fetched:", stats["fetched"])
    print("Matched:", stats["matched"])
    print("Updated:", stats["updated"])
    print(
        "Skipped (missing variant):",
        stats["skipped_missing_variant"]
    )
    print(
        "Skipped (archived variant):",
        stats["skipped_archived_variant"]
    )
    print("Errors:", stats["api_errors"])
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
                item_id_by_fixture_id
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
