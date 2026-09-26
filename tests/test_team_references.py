"""Offline tests for the Team CMS reference feature and wf_items pagination.

Run:  python3 tests/test_team_references.py
Set SYNC_DIR to test a different copy of sync.py.

Every HTTP call goes through a fake transport; anything unexpected raises.
"""

import contextlib
import io
import os
import sys

os.environ["SPORTSMONKS_API_TOKEN"] = "placeholder"
os.environ["WEBFLOW_API_TOKEN"] = "placeholder"

sys.path.insert(
    0,
    os.environ.get(
        "SYNC_DIR",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."),
    ),
)

import requests  # noqa: E402

import sync  # noqa: E402

FAILURES = []


def check(label, condition):
    print(("[PASS] " if condition else "[FAIL] ") + label)
    if not condition:
        FAILURES.append(label)


class FakeResponse:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self.ok = status < 400
        self._body = body if body is not None else {}
        self.text = str(self._body)

    def json(self):
        return self._body

    def raise_for_status(self):
        if not self.ok:
            raise requests.exceptions.HTTPError(
                f"{self.status_code} error", response=self
            )


class Transport:
    """Routes the sync's Webflow calls to in-memory data and records them."""

    def __init__(self, fixture_items=(), team_items=(), team_error=None,
                 reject_refs_status=None):
        self.fixture_items = list(fixture_items)
        self.team_items = list(team_items)
        self.team_error = team_error
        self.reject_refs_status = reject_refs_status
        self.gets, self.posts, self.patches = [], [], []

    def _page(self, items, params):
        limit = params.get("limit", 100)
        offset = params.get("offset", 0)
        return FakeResponse(200, {
            "items": items[offset:offset + limit],
            "pagination": {"limit": limit, "offset": offset,
                           "total": len(items)},
        })

    def get(self, url, headers=None, params=None, timeout=None):
        params = params or {}
        self.gets.append((url, dict(params)))
        if url.endswith(f"/collections/{sync.TEAM_COLLECTION_ID}/items"):
            if self.team_error:
                raise self.team_error
            return self._page(self.team_items, params)
        if url.endswith(f"/collections/{sync.COLLECTION_ID}/items"):
            return self._page(self.fixture_items, params)
        if url.endswith(f"/collections/{sync.COLLECTION_ID}"):
            return FakeResponse(200, {"fields": []})
        raise AssertionError(f"unexpected GET {url}")

    def _write(self, log, url, json):
        log.append((url, json))
        fd = (json or {}).get("fieldData") or {}
        refs = ("home-team" in fd) or ("away-team" in fd)
        if refs and self.reject_refs_status:
            return FakeResponse(self.reject_refs_status, {"msg": "rejected"})
        return FakeResponse(200, {"id": "NEW-" + str(fd.get("sportsmonks-id"))})

    def post(self, url, headers=None, json=None, timeout=None):
        if url.endswith("/items/publish"):
            self.posts.append((url, json))
            return FakeResponse(200, {})
        return self._write(self.posts, url, json)

    def patch(self, url, headers=None, json=None, timeout=None):
        return self._write(self.patches, url, json)


def install(transport):
    requests.get = transport.get
    requests.post = transport.post
    requests.patch = transport.patch


def team(item_id, smid, **over):
    item = {"id": item_id, "isArchived": False, "isDraft": False,
            "lastPublished": "2026-09-05T15:15:08.031Z",
            "fieldData": {"sportsmonks-team-id": smid, "name": "T" + smid}}
    item.update(over)
    return item


def fixture(fid, home_id, away_id):
    return {
        "id": fid, "starting_at": "2026-11-01 18:00:00",
        "state": {"name": "Not Started"}, "scores": [],
        "venue": {"name": "V"}, "league": {"name": "L"},
        "participants": [
            {"id": home_id, "name": f"H{home_id}", "meta": {"location": "home"}},
            {"id": away_id, "name": f"A{away_id}", "meta": {"location": "away"}},
        ],
    }


def existing(item_id, fid, **fd):
    return {"id": item_id, "isArchived": False, "isDraft": False,
            "fieldData": {"sportsmonks-id": str(fid), **fd}}


def run_sync(transport, fixtures, enabled=True):
    install(transport)
    sync.sm_fixtures = lambda locale=None: fixtures
    sync.TEAM_REFERENCES_ENABLED = enabled
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        sync.sync_fixtures()
    return buf.getvalue()


TEAMS = [team("T-KHOLOOD", "232744"), team("T-SHABAB", "16184")]

# ---------------------------------------------------------------- defaults
sync.TEAM_REFERENCES_ENABLED = False
import importlib  # noqa: E402
importlib.reload(sync)
check("flag defaults to False", sync.TEAM_REFERENCES_ENABLED is False)
check("Arabic sync flag unchanged (False)", sync.ARABIC_SYNC_ENABLED is False)
check("team collection id", sync.TEAM_COLLECTION_ID == "6a9c2ff98dd513bfc472db69")

# ------------------------------------------------- build_team_map filtering
items = [
    team("A", "1"),
    team("B", "2", isArchived=True),
    team("C", "3", isDraft=True),
    team("D", "4", lastPublished=None),
    {"id": "E", "isArchived": False, "isDraft": False,
     "lastPublished": "x", "fieldData": {"name": "no id"}},
    team("F1", "9"), team("F2", "9"),
]
with contextlib.redirect_stdout(io.StringIO()) as out:
    tmap = sync.build_team_map(items)
log = out.getvalue()
check("only usable teams in map (archived/draft/unpublished/no-id/duplicate excluded)",
      tmap == {"1": "A"})
check("duplicate id logged as warning", "duplicate sportsmonks-team-id 9" in log)

# ------------------------------------------------------------- pagination
def paged(n):
    return [existing(f"I{i}", 1000 + i) for i in range(n)]


for n, expected_calls in ((0, 1), (99, 1), (100, 1), (101, 2), (250, 3)):
    tr = Transport(fixture_items=paged(n))
    install(tr)
    with contextlib.redirect_stdout(io.StringIO()):
        got = sync.wf_items()
    check(f"wf_items {n} items -> all returned ({len(got)})", len(got) == n)
    check(f"wf_items {n} items -> {expected_calls} request(s)",
          len(tr.gets) == expected_calls)
    if n:
        check(f"wf_items {n} items -> order preserved",
              [i["id"] for i in got] == [f"I{i}" for i in range(n)])

tr = Transport(fixture_items=paged(250))
install(tr)
with contextlib.redirect_stdout(io.StringIO()):
    sync.wf_items()
check("first page request has no offset (unchanged from before)",
      "offset" not in tr.gets[0][1] and tr.gets[0][1]["limit"] == 100)
check("later pages use offsets 100 and 200",
      [g[1].get("offset") for g in tr.gets[1:]] == [100, 200])

tr = Transport(team_items=[team(f"T{i}", str(i)) for i in range(130)])
install(tr)
with contextlib.redirect_stdout(io.StringIO()):
    got = sync.wf_items(collection_id=sync.TEAM_COLLECTION_ID)
check("Team CMS pagination (130 items across 2 pages)", len(got) == 130)
check("Team CMS reads target the team collection only",
      all(g[0].endswith(f"/collections/{sync.TEAM_COLLECTION_ID}/items")
          for g in tr.gets))

tr = Transport(fixture_items=paged(5))
install(tr)
with contextlib.redirect_stdout(io.StringIO()):
    sync.wf_items(cms_locale_id="LOC")
check("cmsLocaleId param still passed", tr.gets[0][1].get("cmsLocaleId") == "LOC")

# ------------------------------------------- e2e: found / missing / update
fx_update = fixture(100, 232744, 16184)       # both teams found
fx_missing = fixture(101, 148884, 232744)     # home team missing
fx_new = fixture(102, 232744, 16184)          # new fixture, both found
fx_new_missing = fixture(103, 16184, 148884)  # new fixture, away missing

tr = Transport(
    fixture_items=[existing("I100", 100), existing("I101", 101)],
    team_items=TEAMS,
)
out = run_sync(tr, [fx_update, fx_missing, fx_new, fx_new_missing])
upd = {p["fieldData"]["sportsmonks-id"]: p["fieldData"] for _, p in tr.patches}
crt = {p["fieldData"]["sportsmonks-id"]: p["fieldData"]
       for u, p in tr.posts if not u.endswith("/publish")}

check("UPDATE valid: both references written",
      upd["100"].get("home-team") == "T-KHOLOOD" and upd["100"].get("away-team") == "T-SHABAB")
check("UPDATE missing home: key absent (no null, nothing cleared)",
      "home-team" not in upd["101"] and upd["101"].get("away-team") == "T-KHOLOOD")
check("CREATE valid: both references written",
      crt["102"].get("home-team") == "T-KHOLOOD" and crt["102"].get("away-team") == "T-SHABAB")
check("CREATE missing away: fixture still created without that reference",
      "away-team" not in crt["103"] and crt["103"].get("home-team") == "T-SHABAB")
check("no reference value is ever None",
      all(v is not None for d in list(upd.values()) + list(crt.values())
          for k, v in d.items() if k in ("home-team", "away-team")))
check("TEAM_MISSING warning logged with id",
      "TEAM_MISSING home-team sportsmonks-team-id = 148884" in out
      and "TEAM_MISSING away-team sportsmonks-team-id = 148884" in out)
check("summary lists the missing team",
      "MISSING: 148884" in out and "Teams missing from Team CMS: 1" in out)
check("English fields unchanged by the feature (sportsmonks-id/name/slug present)",
      upd["100"]["slug"] == "fixture-100" and upd["100"]["home-team-name"] == "H232744")
check("Team CMS never written (all writes target Fixtures collection)",
      all(f"/collections/{sync.COLLECTION_ID}/" in u
          for u, _ in tr.posts + tr.patches))
check("Team CMS read only via GET, once",
      sum(1 for u, _ in tr.gets
          if u.endswith(f"/collections/{sync.TEAM_COLLECTION_ID}/items")) == 1)
check("publish still runs for touched items",
      any(u.endswith("/items/publish") for u, _ in tr.posts))

# ------------------------------------------ e2e: Team CMS read failure
tr = Transport(fixture_items=[existing("I100", 100)], team_items=TEAMS,
               team_error=RuntimeError("boom"))
out = run_sync(tr, [fx_update, fx_new])
check("Team CMS read failure: sync completes, fixtures still written",
      len(tr.patches) == 1 and len([1 for u, _ in tr.posts if not u.endswith("/publish")]) == 1)
check("Team CMS read failure: no reference keys sent (nothing cleared)",
      all("home-team" not in p["fieldData"] and "away-team" not in p["fieldData"]
          for _, p in tr.patches + [x for x in tr.posts if not x[0].endswith("/publish")]))
check("Team CMS read failure: warning logged", "Team CMS read failed" in out)

# ------------------------------------------ e2e: flag disabled (default)
tr = Transport(fixture_items=[existing("I100", 100)], team_items=TEAMS)
out = run_sync(tr, [fx_update, fx_new], enabled=False)
check("disabled: Team CMS is not read at all",
      not any(u.endswith(f"/collections/{sync.TEAM_COLLECTION_ID}/items") for u, _ in tr.gets))
check("disabled: no home-team/away-team written",
      all("home-team" not in p["fieldData"] and "away-team" not in p["fieldData"]
          for _, p in tr.patches + [x for x in tr.posts if not x[0].endswith("/publish")]))
check("disabled: UPDATE payload identical to legacy fixture_field_data()",
      tr.patches[0][1]["fieldData"] == sync.fixture_field_data(fx_update, include_logos=False))
check("disabled: no [TEAM] output", "[TEAM]" not in out)

# ------------------------------ e2e: duplicate team id in Team CMS
tr = Transport(fixture_items=[existing("I100", 100)],
               team_items=TEAMS + [team("T-DUP", "232744")])
out = run_sync(tr, [fx_update])
fd = tr.patches[0][1]["fieldData"]
check("duplicate team id: excluded, no random pick (home absent), other side written",
      "home-team" not in fd and fd.get("away-team") == "T-SHABAB")
check("duplicate team id: warning logged", "duplicate sportsmonks-team-id 232744" in out)

# --------------------------------------- reference rejection fallbacks
for status, expect_retry in ((400, True), (422, True), (404, True), (500, False)):
    tr = Transport(team_items=TEAMS, reject_refs_status=status)
    install(tr)
    calls = []
    with contextlib.redirect_stdout(io.StringIO()):
        try:
            new_id = sync.create_fixture_with_team_refs(
                {"sportsmonks-id": "7", "name": "n"},
                {"home-team": "T-KHOLOOD"})
            raised = False
        except requests.exceptions.HTTPError:
            raised = True
    posts = [p for u, p in tr.posts]
    if expect_retry:
        check(f"CREATE {status}: retried once without references",
              not raised and len(posts) == 2
              and "home-team" in posts[0]["fieldData"]
              and "home-team" not in posts[1]["fieldData"])
    else:
        check(f"CREATE {status}: NOT retried (no duplicate risk), error raised",
              raised and len(posts) == 1)

    tr = Transport(team_items=TEAMS, reject_refs_status=status)
    install(tr)
    with contextlib.redirect_stdout(io.StringIO()):
        try:
            sync.update_fixture_with_team_refs(
                "I1", {"sportsmonks-id": "7"}, {"away-team": "T-SHABAB"})
            raised = False
        except requests.exceptions.HTTPError:
            raised = True
    if expect_retry:
        check(f"UPDATE {status}: retried once without references",
              not raised and len(tr.patches) == 2
              and "away-team" not in tr.patches[1][1]["fieldData"])
    else:
        check(f"UPDATE {status}: NOT retried, error raised",
              raised and len(tr.patches) == 1)

# ----------------------------------------- team_reference_fields: id only
fx = fixture(200, 232744, 16184)
fx["participants"][0]["name"] = "Totally Different Name"
with contextlib.redirect_stdout(io.StringIO()):
    refs = sync.team_reference_fields(fx, {"232744": "T-KHOLOOD", "16184": "T-SHABAB"})
check("matching uses team id only, never the name",
      refs == {"home-team": "T-KHOLOOD", "away-team": "T-SHABAB"})
check("empty map (disabled/failed read) -> no refs",
      sync.team_reference_fields(fx, {}) == {})

# ------------------------------------- non-HTTP failures: never retried
# A retry without references after a network error / timeout / unexpected
# exception could duplicate a fixture (the first request may have reached
# Webflow). These go through the real create/update functions; only the
# transport raises.
NON_HTTP_FAILURES = (
    ("ConnectionError", requests.exceptions.ConnectionError("net down")),
    ("Timeout", requests.exceptions.Timeout("slow")),
    ("ReadTimeout", requests.exceptions.ReadTimeout("slow read")),
    ("RuntimeError", RuntimeError("unexpected")),
    ("ValueError", ValueError("unexpected")),
)


class RaisingTransport(Transport):
    """Every Webflow write raises `exc`, and every attempt is recorded."""

    def __init__(self, exc):
        super().__init__()
        self.exc = exc
        self.attempts = []

    def post(self, url, headers=None, json=None, timeout=None):
        self.attempts.append(("POST", json))
        raise self.exc

    def patch(self, url, headers=None, json=None, timeout=None):
        self.attempts.append(("PATCH", json))
        raise self.exc


def call_and_capture(fn):
    with contextlib.redirect_stdout(io.StringIO()):
        try:
            fn()
            return None
        except BaseException as err:  # noqa: BLE001
            return err


for name, exc in NON_HTTP_FAILURES:
    # CREATE
    tr = RaisingTransport(exc)
    install(tr)
    err = call_and_capture(lambda: sync.create_fixture_with_team_refs(
        {"sportsmonks-id": "7", "name": "n"}, {"home-team": "T-KHOLOOD"}))
    check(f"CREATE {name}: attempts = 1 (no retry, no duplicate CREATE)",
          len(tr.attempts) == 1)
    check(f"CREATE {name}: the single attempt carried the references "
          "(no retry without them)",
          "home-team" in tr.attempts[0][1]["fieldData"])
    check(f"CREATE {name}: the original exception propagates unchanged",
          err is exc)

    # UPDATE
    tr = RaisingTransport(exc)
    install(tr)
    err = call_and_capture(lambda: sync.update_fixture_with_team_refs(
        "I1", {"sportsmonks-id": "7"}, {"away-team": "T-SHABAB"}))
    check(f"UPDATE {name}: attempts = 1 (no retry)", len(tr.attempts) == 1)
    check(f"UPDATE {name}: the single attempt carried the references "
          "(no retry without them)",
          "away-team" in tr.attempts[0][1]["fieldData"])
    check(f"UPDATE {name}: the original exception propagates unchanged",
          err is exc)

    # End to end through sync_fixtures: the run fails exactly as it did
    # before this feature (uncaught), after one write attempt only.
    for label, existing_items, fx_list in (
        ("CREATE", [], [fixture(300, 232744, 16184)]),
        ("UPDATE", [existing("I300", 300)], [fixture(300, 232744, 16184)]),
    ):
        tr = RaisingTransport(exc)
        tr.fixture_items = existing_items
        tr.team_items = TEAMS
        err = call_and_capture(lambda: run_sync(tr, fx_list))
        check(f"sync_fixtures {label} {name}: run fails as before, "
              "one write attempt, none without references",
              err is exc and len(tr.attempts) == 1
              and "home-team" in tr.attempts[0][1]["fieldData"])

# ------------------------------------------------- HTTP retry matrix
RETRY_MATRIX = (
    (400, True), (404, True), (422, True),
    (409, False), (429, False), (500, False), (502, False), (503, False),
)

for status, retried in RETRY_MATRIX:
    # CREATE
    tr = Transport(reject_refs_status=status)
    install(tr)
    err = call_and_capture(lambda: sync.create_fixture_with_team_refs(
        {"sportsmonks-id": "8", "name": "n"}, {"home-team": "T-KHOLOOD"}))
    posts = [p for _, p in tr.posts]
    if retried:
        check(f"CREATE {status}: retried ONCE without references",
              err is None and len(posts) == 2
              and "home-team" in posts[0]["fieldData"]
              and "home-team" not in posts[1]["fieldData"]
              and posts[1]["fieldData"]["sportsmonks-id"] == "8")
    else:
        check(f"CREATE {status}: NOT retried, HTTPError raised",
              isinstance(err, requests.exceptions.HTTPError)
              and err.response.status_code == status and len(posts) == 1)

    # UPDATE
    tr = Transport(reject_refs_status=status)
    install(tr)
    err = call_and_capture(lambda: sync.update_fixture_with_team_refs(
        "I1", {"sportsmonks-id": "8"}, {"away-team": "T-SHABAB"}))
    patches = [p for _, p in tr.patches]
    if retried:
        check(f"UPDATE {status}: retried ONCE without references",
              err is None and len(patches) == 2
              and "away-team" in patches[0]["fieldData"]
              and "away-team" not in patches[1]["fieldData"]
              and patches[1]["fieldData"]["sportsmonks-id"] == "8")
    else:
        check(f"UPDATE {status}: NOT retried, HTTPError raised",
              isinstance(err, requests.exceptions.HTTPError)
              and err.response.status_code == status and len(patches) == 1)

# ---------------------------------- Arabic untouched (structural checks)
import inspect  # noqa: E402
for name in ("sync_fixtures_arabic", "fixture_field_data_arabic", "sm_fixtures_arabic"):
    check(f"{name} does not reference the team feature",
          "team_map" not in inspect.getsource(getattr(sync, name))
          and "TEAM_REFERENCES" not in inspect.getsource(getattr(sync, name)))

print()
print("=" * 60)
if FAILURES:
    print(f"RESULT: {len(FAILURES)} FAILURE(S)")
    for f in FAILURES:
        print(" -", f)
    sys.exit(1)
print("RESULT: ALL CHECKS PASSED")
