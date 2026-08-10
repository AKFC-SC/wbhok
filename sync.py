import os
from datetime import datetime, timedelta, timezone
import requests

SM_TOKEN = os.environ["OwEeRineBkybfvjhErbpLC9XPselqjFdGSkqJRa2Tg1dOwPAnc4kdXFtGE3O"]
WF_TOKEN = os.environ["f02b9e2660c8cb1598211689ffdf102f3aeee1d8183c1cbe5089a8d36500a883"]

TEAM_ID = 232744
COLLECTION_ID = "68c415c140c71006d646fbe3"
SM_URL = "https://api.sportmonks.com/v3/football/fixtures/date"
WF_BASE = "https://api.webflow.com/v2"

def sm_fixtures():
    start = datetime.now(timezone.utc).date()
    end = start + timedelta(days=365)
    params = {
        "api_token": SM_TOKEN,
        "team_id": TEAM_ID,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "include": "state;venue;participants;league",
    }
    r = requests.get(SM_URL, params=params, timeout=30)
    r.raise_for_status()
    return r.json().get("data", [])

def wf_headers():
    return {"Authorization": f"Bearer {WF_TOKEN}", "Content-Type": "application/json"}

def wf_items():
    r = requests.get(
        f"{WF_BASE}/collections/{COLLECTION_ID}/items",
        headers=wf_headers(),
        params={"limit": 100},
        timeout=30,
    )
    r.raise_for_status()
    return r.json().get("items", [])

def normalize(x):
    parts = x.get("participants") or []
    home = next((p for p in parts if (p.get("meta") or {}).get("location") == "home"), None)
    away = next((p for p in parts if (p.get("meta") or {}).get("location") == "away"), None)
    if not home and parts: home = parts[0]
    if not away and len(parts) > 1: away = parts[1]
    state = x.get("state") or {}
    venue = x.get("venue") or {}
    league = x.get("league") or {}
    return {
        "sportsmonks_id": str(x.get("id", "")),
        "home_name": (home or {}).get("name", ""),
        "away_name": (away or {}).get("name", ""),
        "home_logo": (home or {}).get("image_path", ""),
        "away_logo": (away or {}).get("image_path", ""),
        "competition": league.get("name", ""),
        "starting_at": x.get("starting_at", ""),
        "venue": venue.get("name", ""),
        "status": state.get("short_name") or state.get("name") or "",
    }

def fields(f):
    # Replace these keys with your exact Webflow CMS field slugs.
    return {
        "sportsmonks-id": f["sportsmonks_id"],
        "status": f["status"],
        "home-team-name": f["home_name"],
        "away-team-name": f["away_name"],
        "date-time": f["starting_at"],
        "venue": f["venue"],
        "time": f["starting_at"],
    }

def main():
    fixtures = sm_fixtures()
    existing = {}
    for item in wf_items():
        fd = item.get("fieldData") or {}
        if fd.get("sportsmonks-id"):
            existing[str(fd["sportsmonks-id"])] = item

    for x in fixtures:
        f = normalize(x)
        if not f["sportsmonks_id"]:
            continue
        data = {"fieldData": fields(f)}
        old = existing.get(f["sportsmonks_id"])
        if old:
            r = requests.patch(
                f"{WF_BASE}/collections/{COLLECTION_ID}/items/{old['id']}",
                headers=wf_headers(), json=data, timeout=30)
        else:
            data.update({"isArchived": False, "isDraft": True})
            r = requests.post(
                f"{WF_BASE}/collections/{COLLECTION_ID}/items",
                headers=wf_headers(), json=data, timeout=30)
        r.raise_for_status()
        print(("Updated " if old else "Created ") + f["sportsmonks_id"])

if __name__ == "__main__":
    main()
