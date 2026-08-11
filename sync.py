def sm_fixtures():

    today = datetime.now(timezone.utc).date()
    end = today + timedelta(days=90)

    url = (
        f"{SM_BASE}/fixtures/between/"
        f"{today.isoformat()}/"
        f"{end.isoformat()}"
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
        "filter": f"participantIds:{TEAM_ID}",
        "per_page": 100,
    }

    response = requests.get(
        url,
        params=params,
        headers=sm_headers(),
        timeout=30,
    )

    print("SPORTSMONKS STATUS:", response.status_code)

    if not response.ok:
        print("SPORTSMONKS RESPONSE:", response.text)
        response.raise_for_status()

    data = response.json()

    fixtures = data.get("data") or []

    print(
        "Al Kholood fixtures:",
        len(fixtures)
    )

    for fixture in fixtures:

        home, away = get_participants(fixture)

        print(
            "KHOLOOD FIXTURE:",
            fixture.get("id"),
            "|",
            participant_name(home),
            "vs",
            participant_name(away)
        )

    return fixtures
