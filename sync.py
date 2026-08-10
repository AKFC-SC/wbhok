import os
from datetime import datetime, timedelta, timezone

import requests


SM_TOKEN = os.environ["SPORTSMONKS_API_TOKEN"]
WF_TOKEN = os.environ["WEBFLOW_API_TOKEN"]

TEAM_ID = 232744
COLLECTION_ID = "6a671465e31c8cf8983d3d36"

SM_BASE = "https://api.sportmonks.com/v3/football/fixtures/between"
WF_BASE = "https://api.webflow.com/v2"

def sm_fixtures():
    start = datetime.now(timezone.utc).date()
    end = start + timedelta(days=365)

    url = f"{SM_BASE}/{start.isoformat()}/{end.isoformat()}/{TEAM_ID}"

    params = {
        "api_token": SM_TOKEN,
        "include": "participants;venue;league;state",
    }

    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()

    return response.json().get("data", [])


def wf_headers():
    return {
        "Authorization": f"Bearer {WF_TOKEN}",
        "Content-Type": "application/json",
    }


def wf_items():
    url = f"{WF_BASE}/collections/{COLLECTION_ID}/items"

    response = requests.get(
        url,
        headers=wf_headers(),
        params={"limit": 100},
        timeout=30,
    )

    response.raise_for_status()
    return response.json().get("items", [])


def fixture_name(fixture):
    return fixture.get("name") or f"Fixture {fixture.get('id')}"


def fixture_slug(fixture):
    fixture_id = fixture.get("id")
    return f"fixture-{fixture_id}"


def fixture_date(fixture):
    value = fixture.get("starting_at")

    if not value:
        return ""

    return value


def fixture_field_data(fixture):
    name = fixture_name(fixture)

    return {
        "name": name,
        "slug": fixture_slug(fixture),
        "fixture-id": str(fixture.get("id", "")),
        "starting-at": fixture_date(fixture),
        "venue": (fixture.get("venue") or {}).get("name", ""),
        "league": (fixture.get("league") or {}).get("name", ""),
        "state": (fixture.get("state") or {}).get("name", ""),
    }


def create_webflow_item(field_data):
    url = f"{WF_BASE}/collections/{COLLECTION_ID}/items"

    payload = {
        "fieldData": field_data,
    }

    response = requests.post(
        url,
        headers=wf_headers(),
        json=payload,
        timeout=30,
    )

    if not response.ok:
        print("WEBFLOW STATUS:", response.status_code)
        print("WEBFLOW RESPONSE:", response.text)
        response.raise_for_status()



def update_webflow_item(item_id, field_data):
    url = f"{WF_BASE}/collections/{COLLECTION_ID}/items/{item_id}"

    payload = {
        "fieldData": field_data,
    }

    response = requests.patch(
        url,
        headers=wf_headers(),
        json=payload,
        timeout=30,
    )

    response.raise_for_status()
    return response.json()


def sync_fixtures():
    fixtures = sm_fixtures()
    existing_items = wf_items()

    existing_by_fixture_id = {}

    for item in existing_items:
        field_data = item.get("fieldData") or {}
        fixture_id = field_data.get("fixture-id")

        if fixture_id:
            existing_by_fixture_id[str(fixture_id)] = item

    created = 0
    updated = 0

    for fixture in fixtures:
        fixture_id = str(fixture.get("id", ""))

        if not fixture_id:
            continue

        field_data = fixture_field_data(fixture)
        existing = existing_by_fixture_id.get(fixture_id)

        if existing:
            update_webflow_item(existing["id"], field_data)
            updated += 1
        else:
            create_webflow_item(field_data)
            created += 1

    print(f"Fixtures received: {len(fixtures)}")
    print(f"Webflow items created: {created}")
    print(f"Webflow items updated: {updated}")

def test_collection():
    url = f"{WF_BASE}/collections/{COLLECTION_ID}"

    r = requests.get(
        url,
        headers=wf_headers(),
        timeout=30
    )

    print("COLLECTION STATUS:", r.status_code)
    print("COLLECTION RESPONSE:", r.text)

    r.raise_for_status()
 
def main():
    sync_fixtures()


if __name__ == "__main__":
    test_collection()
