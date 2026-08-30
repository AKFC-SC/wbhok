import os
import re

import requests


# ============================================================
# CONFIG
#
# Fully isolated from sync.py and sync_u21.py on purpose: this script only ever
# touches Players CMS items whose slug starts with "u21-player-" (a deterministic,
# SportMonks-player-id-based slug), so it can never edit or delete an existing
# First Team player record even if this file has a bug.
# ============================================================

SM_TOKEN = os.environ["SPORTSMONKS_API_TOKEN"]
WF_TOKEN = os.environ["WEBFLOW_API_TOKEN"]

TEAM_ID = 280646  # Al Kholood U21

PLAYERS_COLLECTION_ID = "6a7ca1efe845ffc70a7d6607"

TEAM_OPTION_ID_U21 = "46a756f2ac0ecfc8f206b56fe1cb217f"

POSITION_OPTION_IDS = {
    "Goalkeeper": "737538f149cd0869f42f92e7e77a05e6",
    "Defender": "3af5e5c53796fdb728911ca4fddb6fb8",
    "Midfielder": "797ef0d0b88cf4c583c47f39971308a3",
    "Attacker": "723a51e269c1582ac562f38f17d80b9f",
}
DEFAULT_POSITION_OPTION_ID = POSITION_OPTION_IDS["Midfielder"]

SM_BASE = "https://api.sportmonks.com/v3/football"
WF_BASE = "https://api.webflow.com/v2"

SLUG_PREFIX = "u21-player-"


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


def slugify_extra(text):
    text = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return text


def player_slug(player_id):
    return f"{SLUG_PREFIX}{player_id}"


# ============================================================
# SPORTSMONKS — U21 SQUAD
# ============================================================

def sm_squad():
    url = f"{SM_BASE}/squads/teams/{TEAM_ID}"
    params = {
        "api_token": SM_TOKEN,
        "include": "player;position",
    }

    print()
    print("SPORTSMONKS REQUEST (U21 squad):", TEAM_ID)

    response = requests.get(url, params=params, headers=sm_headers(), timeout=30)
    print("SPORTSMONKS STATUS:", response.status_code)

    if not response.ok:
        print("SPORTSMONKS RESPONSE:", response.text)
        response.raise_for_status()

    data = response.json()
    squad = data.get("data") or []
    print("Squad entries returned:", len(squad))

    return squad


def squad_entry_field_data(entry):
    player = entry.get("player") or {}
    position = entry.get("position") or {}

    player_id = entry.get("player_id")
    full_name = safe_text(player.get("display_name") or player.get("name") or "").upper()
    jersey_number = entry.get("jersey_number")
    image_path = player.get("image_path")

    position_name = position.get("name")
    position_option = POSITION_OPTION_IDS.get(position_name, DEFAULT_POSITION_OPTION_ID)

    field_data = {
        "name": full_name or f"U21 Player {player_id}",
        "slug": player_slug(player_id),
        "player-name": full_name,
        "player-number": safe_text(jersey_number),
        "postion": position_option,
        "team": TEAM_OPTION_ID_U21,
        "order-2": jersey_number if isinstance(jersey_number, int) else 0,
    }

    if image_path:
        field_data["player-image"] = {"url": image_path, "alt": full_name}

    return field_data, player_id


# ============================================================
# WEBFLOW
# ============================================================

def wf_u21_player_items():
    url = f"{WF_BASE}/collections/{PLAYERS_COLLECTION_ID}/items"
    params = {"limit": 100}
    response = requests.get(url, headers=wf_headers(), params=params, timeout=30)
    print("ITEMS STATUS:", response.status_code)
    if not response.ok:
        print("ITEMS RESPONSE:", response.text)
        response.raise_for_status()
    data = response.json()
    items = data.get("items") or []
    # Only ever look at items this script itself created — identified purely by
    # the deterministic "u21-player-<id>" slug prefix. Never touches anything else.
    u21_items = [
        item for item in items
        if safe_text((item.get("fieldData") or {}).get("slug")).startswith(SLUG_PREFIX)
    ]
    print("Existing U21 Webflow player items:", len(u21_items))
    return u21_items


def create_webflow_item(field_data):
    url = f"{WF_BASE}/collections/{PLAYERS_COLLECTION_ID}/items"
    payload = {"fieldData": field_data}
    response = requests.post(url, headers=wf_headers(), json=payload, timeout=30)
    if not response.ok:
        print("CREATE STATUS:", response.status_code)
        print("CREATE RESPONSE:", response.text)
        print("CREATE PAYLOAD:", field_data)
        response.raise_for_status()
    print("Created U21 player:", field_data.get("slug"))
    return response.json().get("id")


def update_webflow_item(item_id, field_data):
    url = f"{WF_BASE}/collections/{PLAYERS_COLLECTION_ID}/items/{item_id}"
    payload = {"fieldData": field_data}
    response = requests.patch(url, headers=wf_headers(), json=payload, timeout=30)
    print("UPDATE STATUS:", response.status_code)
    if not response.ok:
        print("UPDATE RESPONSE:", response.text)
        print("UPDATE PAYLOAD:", field_data)
        response.raise_for_status()
    print("Updated U21 player:", field_data.get("slug"))


def publish_webflow_items(item_ids):
    # Webflow items created/updated via the API land as Draft — this makes them
    # live so they actually render on the published site without a manual step.
    # Batched at 100 per request (Webflow's own limit); our squad is far smaller.
    if not item_ids:
        return
    url = f"{WF_BASE}/collections/{PLAYERS_COLLECTION_ID}/items/publish"
    for i in range(0, len(item_ids), 100):
        batch = item_ids[i:i + 100]
        response = requests.post(url, headers=wf_headers(), json={"itemIds": batch}, timeout=30)
        print("PUBLISH STATUS:", response.status_code)
        if not response.ok:
            print("PUBLISH RESPONSE:", response.text)
            # Non-fatal: the sync itself succeeded, only the publish step failed
            # (e.g. site plan doesn't support it). Don't fail the whole run over it.
            print("Publish failed for batch — items remain in Draft; publish manually if needed.")
        else:
            print("Published U21 player items:", len(batch))


# ============================================================
# SYNC
# ============================================================

def sync_u21_players():
    squad = sm_squad()
    existing_items = wf_u21_player_items()

    existing_by_slug = {
        (item.get("fieldData") or {}).get("slug"): item
        for item in existing_items
    }

    created = 0
    updated = 0
    skipped = 0
    touched_item_ids = []

    for entry in squad:
        field_data, player_id = squad_entry_field_data(entry)
        if not player_id:
            skipped += 1
            continue

        print()
        print("Processing U21 player:", player_id, field_data.get("player-name"))

        existing = existing_by_slug.get(field_data["slug"])

        if existing:
            # Never overwrite an image that was manually set in the CMS with a
            # blank one — only send player-image when SportMonks actually has one.
            update_payload = dict(field_data)
            if "player-image" not in update_payload:
                update_payload.pop("player-image", None)
            update_webflow_item(existing["id"], update_payload)
            touched_item_ids.append(existing["id"])
            updated += 1
        else:
            new_id = create_webflow_item(field_data)
            if new_id:
                touched_item_ids.append(new_id)
            created += 1

    publish_webflow_items(touched_item_ids)

    print()
    print("========================================")
    print(f"U21 squad entries received: {len(squad)}")
    print(f"U21 Webflow player items created: {created}")
    print(f"U21 Webflow player items updated: {updated}")
    print(f"Skipped (no player_id): {skipped}")
    print(f"Items published: {len(touched_item_ids)}")
    print("========================================")


def main():
    sync_u21_players()


if __name__ == "__main__":
    main()
