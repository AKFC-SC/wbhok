import os

import requests


# ============================================================
# MATCH STATISTICS SYNC
#
# Fills the EXISTING "Match Statistics" collection from SportMonks for
# fixtures that already exist in the Fixtures CMS. Nothing here creates a
# Fixture, a Team, a Player or any other collection's item.
#
#   Fixtures CMS item (matched by sportsmonks-id, status "Full Time")
#     -> Match Statistics item, linked through its `fixture` Reference
#     -> Arabic variant of that Match Statistics item (same item id)
#
# Statistics are numbers, so the Arabic variant carries exactly the same
# values as the Primary one. Nothing is requested in a SportMonks Arabic
# locale. The Arabic `fixture` Reference points at the same Fixture item,
# which has an Arabic variant; Arabic team names / competition come from
# that Arabic Fixture variant, never from a translation.
#
# The stat type ids are the ones confirmed against a real SportMonks
# response in worker/src/mapper.js (STAT_TYPE_IDS). A value SportMonks does
# not return is simply left out — never sent as 0. "Clearances" is not
# available on this plan and is never written.
#
# Runs as the last step of .github/workflows/sync.yml. An existing item is
# only PATCHed when SportMonks disagrees with what it holds (SportMonks is the
# source of truth); fields SportMonks has no value for are never cleared.
# MATCH_STATS_SYNC_ENABLED=False switches it off; MATCH_STATS_SYNC_DRY_RUN=True
# turns every write into a log line.
# ============================================================

SM_TOKEN = os.environ["SPORTSMONKS_API_TOKEN"]
WF_TOKEN = os.environ["WEBFLOW_API_TOKEN"]

FIXTURES_COLLECTION_ID = "6a671465e31c8cf8983d3d36"
STATS_COLLECTION_ID = "6a84e508b00e99eb71d4836e"

PRIMARY_CMS_LOCALE_ID = "6a671465e31c8cf8983d3d0c"
ARABIC_CMS_LOCALE_ID = "6a671465e31c8cf8983d3d0d"

MATCH_STATS_SYNC_ENABLED = True
MATCH_STATS_SYNC_DRY_RUN = False

FINISHED_STATUS = "Full Time"

SM_BASE = "https://api.sportmonks.com/v3/football"
WF_BASE = "https://api.webflow.com/v2"
WF_PAGE_SIZE = 100

# CMS field suffix -> SportMonks statistic type id (home-<suffix> / away-<suffix>)
STAT_TYPE_IDS = {
    "possession": 45,
    "shots": 42,
    "shots-on-target": 86,
    "big-chances": 580,
    "corners": 34,
    "offsides": 51,
    "passes": 80,
    "completed-passes": 81,
    "pass-accuracy": 82,
    "tackles": 78,
    "duels-won": 106,
    "saves": 57,
    "blocks": 58,
    "throw-ins": 60,
    "yellow-cards": 84,
    "red-cards": 83,
}
FOULS_TYPE_ID = 56  # one value per team = fouls that team committed

NUMERIC_SUFFIXES = tuple(STAT_TYPE_IDS) + ("fouls-committed", "fouls-suffered")

# Fields that change from run to run (values). Everything else is written
# once, on create.
VALUE_FIELDS = frozenset(
    [f"{side}-{s}" for side in ("home", "away") for s in NUMERIC_SUFFIXES]
    + ["home-score", "away-score"]
)
STATIC_FIELDS = frozenset(
    ["fixture", "name", "slug", "home-team-name", "away-team-name",
     "home-logo", "away-logo", "competition"]
)
ALLOWED_FIELDS = VALUE_FIELDS | STATIC_FIELDS


def wf_headers():
    return {
        "Authorization": f"Bearer {WF_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def safe_text(value):
    return "" if value is None else str(value)


def _same(a, b):
    return safe_text(a) == safe_text(b)


def assert_payload(field_data):
    unexpected = set(field_data) - ALLOWED_FIELDS
    assert not unexpected, "outside the allow-list: " + ", ".join(sorted(unexpected))


# ============================================================
# WEBFLOW
# ============================================================

def wf_items(collection_id, cms_locale_id=None):
    url = f"{WF_BASE}/collections/{collection_id}/items"
    items, offset = [], 0

    while True:
        params = {"limit": WF_PAGE_SIZE}
        if offset:
            params["offset"] = offset
        if cms_locale_id:
            params["cmsLocaleId"] = cms_locale_id

        response = requests.get(url, headers=wf_headers(), params=params, timeout=30)
        if not response.ok:
            print("ITEMS RESPONSE:", response.text)
            response.raise_for_status()

        data = response.json()
        page = data.get("items") or []
        items.extend(page)
        offset += len(page)
        total = (data.get("pagination") or {}).get("total")

        if not page or len(page) < WF_PAGE_SIZE or (total is not None and offset >= total):
            break

    return items


def create_primary_item(field_data):
    assert_payload(field_data)
    url = f"{WF_BASE}/collections/{STATS_COLLECTION_ID}/items"
    response = requests.post(url, headers=wf_headers(), json={"fieldData": field_data}, timeout=30)
    if not response.ok:
        print("CREATE RESPONSE:", response.text)
        response.raise_for_status()
    return response.json().get("id")


def update_item(item_id, field_data, cms_locale_id=None):
    assert_payload(field_data)
    payload = {"fieldData": field_data}
    if cms_locale_id:
        assert cms_locale_id == ARABIC_CMS_LOCALE_ID
        payload["cmsLocaleId"] = cms_locale_id
    url = f"{WF_BASE}/collections/{STATS_COLLECTION_ID}/items/{item_id}"
    response = requests.patch(url, headers=wf_headers(), json=payload, timeout=30)
    if not response.ok:
        print("UPDATE RESPONSE:", response.text)
        response.raise_for_status()


def create_arabic_variant(item_id, field_data):
    assert item_id, "an Arabic variant is always created on an existing item id"
    assert_payload(field_data)
    url = f"{WF_BASE}/collections/{STATS_COLLECTION_ID}/items/insert"
    payload = {"items": [{
        "id": item_id,
        "cmsLocaleIds": [ARABIC_CMS_LOCALE_ID],
        "isDraft": True,
        "isArchived": False,
        "fieldData": field_data,
    }]}
    response = requests.post(url, headers=wf_headers(), json=payload, timeout=30)
    if not response.ok:
        print("CREATE ARABIC VARIANT RESPONSE:", response.text)
        response.raise_for_status()
    created = (response.json().get("items") or [{}])[0]
    if created.get("id") != item_id or created.get("cmsLocaleId") != ARABIC_CMS_LOCALE_ID:
        raise RuntimeError("Arabic variant create was not echoed back on the same item / locale")


def publish_primary_items(item_ids):
    # Primary locale only (itemIds). Arabic variants are never published here.
    url = f"{WF_BASE}/collections/{STATS_COLLECTION_ID}/items/publish"
    for i in range(0, len(item_ids), 100):
        response = requests.post(
            url, headers=wf_headers(), json={"itemIds": item_ids[i:i + 100]}, timeout=30
        )
        if not response.ok:
            print("PUBLISH RESPONSE:", response.text)
            response.raise_for_status()


# ============================================================
# SPORTMONKS
# ============================================================

def sm_fixture(fixture_id):
    response = requests.get(
        f"{SM_BASE}/fixtures/{fixture_id}",
        params={"api_token": SM_TOKEN, "include": "participants;league;scores;statistics"},
        headers={"Accept": "application/json"},
        timeout=30,
    )
    if not response.ok:
        # never print the URL: it carries the token
        raise RuntimeError(f"SportMonks HTTP {response.status_code}")
    return response.json().get("data") or {}


def participants(fixture):
    home = away = None
    for p in fixture.get("participants") or []:
        location = (p.get("meta") or {}).get("location")
        if location == "home":
            home = p
        elif location == "away":
            away = p
    return home, away


def stat_value(statistics, participant_id, type_id):
    for entry in statistics or []:
        if entry.get("type_id") == type_id and entry.get("participant_id") == participant_id:
            value = (entry.get("data") or {}).get("value")
            try:
                return int(round(float(value)))
            except (TypeError, ValueError):
                return None
    return None


def goals(fixture, participant_id):
    scores = fixture.get("scores") or []
    if isinstance(scores, dict):
        scores = scores.get("data") or []
    for score in scores:
        if score.get("participant_id") == participant_id and score.get("description") == "CURRENT":
            value = (score.get("score") or {}).get("goals")
            if value is not None:
                return safe_text(value)
    return None


def build_values(fixture):
    """Value fields for one fixture; a stat SportMonks did not return is omitted."""
    statistics = fixture.get("statistics") or []
    home, away = participants(fixture)
    if not statistics or not home or not away:
        return {}

    values = {}

    for side, team in (("home", home), ("away", away)):
        for suffix, type_id in STAT_TYPE_IDS.items():
            value = stat_value(statistics, team.get("id"), type_id)
            if value is not None:
                values[f"{side}-{suffix}"] = value

        score = goals(fixture, team.get("id"))
        if score is not None:
            values[f"{side}-score"] = score

    home_fouls = stat_value(statistics, home.get("id"), FOULS_TYPE_ID)
    away_fouls = stat_value(statistics, away.get("id"), FOULS_TYPE_ID)

    # A team's fouls suffered are the opponent's fouls committed.
    for key, value in (
        ("home-fouls-committed", home_fouls),
        ("away-fouls-committed", away_fouls),
        ("home-fouls-suffered", away_fouls),
        ("away-fouls-suffered", home_fouls),
    ):
        if value is not None:
            values[key] = value

    return values


def logo(participant):
    url = (participant or {}).get("image_path")
    return {"url": url, "alt": safe_text(participant.get("name"))} if url else None


# ============================================================
# SYNC
# ============================================================

def sync_match_statistics():
    stats = {
        "fixtures_in_scope": 0, "primary_created": 0, "primary_updated": 0,
        "would_create": 0, "would_update": 0, "unchanged": 0,
        "arabic_created": 0, "arabic_updated": 0, "arabic_would_create": 0,
        "arabic_would_update": 0, "arabic_unchanged": 0,
        "skipped_no_statistics": 0, "skipped_duplicate_link": 0,
        "skipped_arabic_no_fixture_variant": 0, "errors": 0,
    }

    if not MATCH_STATS_SYNC_ENABLED:
        print("Match statistics sync is disabled — nothing to do.")
        return stats

    print("[STATS] START | dry run:", "YES" if MATCH_STATS_SYNC_DRY_RUN else "NO")

    fixtures = wf_items(FIXTURES_COLLECTION_ID)
    arabic_fixtures = {
        i["id"]: i for i in wf_items(FIXTURES_COLLECTION_ID, ARABIC_CMS_LOCALE_ID)
        if i.get("cmsLocaleId") == ARABIC_CMS_LOCALE_ID
    }
    primary_stats = wf_items(STATS_COLLECTION_ID)
    arabic_stats_rows = wf_items(STATS_COLLECTION_ID, ARABIC_CMS_LOCALE_ID)

    if any(i.get("cmsLocaleId") != ARABIC_CMS_LOCALE_ID for i in arabic_stats_rows):
        print("[STATS] Arabic read returned a non-Arabic row — aborting, no write")
        stats["errors"] += 1
        return stats

    arabic_stats = {i["id"]: i for i in arabic_stats_rows}

    links = {}
    for item in primary_stats:
        ref = (item.get("fieldData") or {}).get("fixture")
        if ref:
            links.setdefault(ref, []).append(item)

    touched = []

    for fixture_item in fixtures:
        data = fixture_item.get("fieldData") or {}
        sportsmonks_id = safe_text(data.get("sportsmonks-id"))

        if (
            not sportsmonks_id
            or fixture_item.get("isArchived")
            or data.get("status") != FINISHED_STATUS
        ):
            continue

        stats["fixtures_in_scope"] += 1
        print()
        print("[STATS] Fixture", sportsmonks_id)

        linked = links.get(fixture_item["id"], [])

        if len(linked) > 1:
            print("[STATS] More than one Match Statistics item links this fixture — SKIP")
            stats["skipped_duplicate_link"] += 1
            continue

        try:
            fixture = sm_fixture(sportsmonks_id)
        except Exception as err:
            print("[STATS] SportMonks request failed:", err)
            stats["errors"] += 1
            continue

        values = build_values(fixture)

        if not values:
            print("[STATS] SportMonks returned no statistics — SKIP")
            stats["skipped_no_statistics"] += 1
            continue

        home, away = participants(fixture)
        primary = linked[0] if linked else None

        # -------------------------------------------- Primary item
        try:
            if primary is None:
                create_data = dict(values)
                create_data.update({
                    "fixture": fixture_item["id"],
                    "home-team-name": safe_text(home.get("name")),
                    "away-team-name": safe_text(away.get("name")),
                    "competition": safe_text((fixture.get("league") or {}).get("name")),
                    "name": f"{safe_text(home.get('name'))} vs {safe_text(away.get('name'))} - Match Stats",
                    "slug": f"fixture-{sportsmonks_id}-stats",
                })
                for key, team in (("home-logo", home), ("away-logo", away)):
                    if logo(team):
                        create_data[key] = logo(team)

                if MATCH_STATS_SYNC_DRY_RUN:
                    print("[STATS] Action: DRY-RUN CREATE")
                    stats["would_create"] += 1
                    primary_id, primary_data = None, create_data
                else:
                    primary_id = create_primary_item(create_data)
                    primary_data = create_data
                    touched.append(primary_id)
                    print("[STATS] Action: CREATE")
                    stats["primary_created"] += 1
            else:
                primary_id = primary["id"]
                primary_data = primary.get("fieldData") or {}
                changes = {
                    k: v for k, v in values.items() if not _same(primary_data.get(k), v)
                }
                if not changes:
                    print("[STATS] Changes: none")
                    stats["unchanged"] += 1
                elif MATCH_STATS_SYNC_DRY_RUN:
                    print("[STATS] Action: DRY-RUN UPDATE", sorted(changes))
                    stats["would_update"] += 1
                else:
                    update_item(primary_id, changes)
                    touched.append(primary_id)
                    print("[STATS] Action: UPDATE", sorted(changes))
                    stats["primary_updated"] += 1
        except Exception as err:
            print("[STATS] Webflow Primary write failed:", err)
            stats["errors"] += 1
            continue

        # -------------------------------------------- Arabic variant
        arabic_fixture = arabic_fixtures.get(fixture_item["id"])
        ar_fixture_data = (arabic_fixture or {}).get("fieldData") or {}

        if not arabic_fixture or not (
            ar_fixture_data.get("home-team-name") and ar_fixture_data.get("away-team-name")
        ):
            print("[STATS] Arabic: the Fixture has no usable Arabic variant — SKIP Arabic")
            stats["skipped_arabic_no_fixture_variant"] += 1
            continue

        arabic = arabic_stats.get(primary["id"]) if primary else None

        try:
            if arabic is None:
                ar_data = dict(values)
                ar_data.update({
                    "fixture": fixture_item["id"],
                    "home-team-name": ar_fixture_data["home-team-name"],
                    "away-team-name": ar_fixture_data["away-team-name"],
                    "name": primary_data.get("name"),
                    "slug": primary_data.get("slug"),
                })
                if ar_fixture_data.get("league"):
                    ar_data["competition"] = ar_fixture_data["league"]
                for key in ("home-logo", "away-logo"):
                    if primary_data.get(key):
                        ar_data[key] = {
                            k: primary_data[key][k]
                            for k in ("fileId", "url", "alt") if primary_data[key].get(k)
                        }

                if MATCH_STATS_SYNC_DRY_RUN or primary_id is None:
                    print("[STATS] Arabic: DRY-RUN CREATE")
                    stats["arabic_would_create"] += 1
                else:
                    create_arabic_variant(primary_id, ar_data)
                    print("[STATS] Arabic: CREATE (draft)")
                    stats["arabic_created"] += 1
            else:
                ar_existing = arabic.get("fieldData") or {}
                changes = {
                    k: v for k, v in values.items() if not _same(ar_existing.get(k), v)
                }
                if not changes:
                    stats["arabic_unchanged"] += 1
                elif MATCH_STATS_SYNC_DRY_RUN:
                    print("[STATS] Arabic: DRY-RUN UPDATE", sorted(changes))
                    stats["arabic_would_update"] += 1
                else:
                    update_item(primary_id, changes, cms_locale_id=ARABIC_CMS_LOCALE_ID)
                    print("[STATS] Arabic: UPDATE", sorted(changes))
                    stats["arabic_updated"] += 1
        except Exception as err:
            print("[STATS] Webflow Arabic write failed:", err)
            stats["errors"] += 1

    if touched and not MATCH_STATS_SYNC_DRY_RUN:
        publish_primary_items(touched)
        print("[STATS] Published Primary items:", len(touched))

    print()
    print("[STATS] SUMMARY")
    for key, value in stats.items():
        print(f"{key}: {value}")
    print("Arabic published: 0")

    return stats


def main():
    sync_match_statistics()


if __name__ == "__main__":
    main()
