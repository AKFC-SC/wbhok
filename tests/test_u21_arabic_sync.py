"""Offline tests for the U21 Arabic mirror in sync_u21.py.

Run:  python3 tests/test_u21_arabic_sync.py
Every HTTP call goes through a fake transport; nothing touches Webflow/SportMonks.
"""

import contextlib
import io
import os
import sys

os.environ["SPORTSMONKS_API_TOKEN"] = "placeholder"
os.environ["WEBFLOW_API_TOKEN"] = "placeholder"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import requests  # noqa: E402

import sync_u21 as u21  # noqa: E402

FAILURES = []
AR, EN = u21.ARABIC_CMS_LOCALE_ID, u21.PRIMARY_CMS_LOCALE_ID


def check(label, cond):
    print(("[PASS] " if cond else "[FAIL] ") + label)
    if not cond:
        FAILURES.append(label)


class Resp:
    def __init__(self, status=200, body=None):
        self.status_code, self.ok, self._b, self.text = status, status < 400, body or {}, ""

    def json(self):
        return self._b

    def raise_for_status(self):
        if not self.ok:
            raise requests.exceptions.HTTPError("e", response=self)


class Transport:
    def __init__(self, primary, arabic):
        self.primary, self.arabic, self.calls = primary, arabic, []

    def get(self, url, headers=None, params=None, timeout=None):
        params = params or {}
        self.calls.append(("GET", url, dict(params), None))
        if url.endswith(f"/collections/{u21.COLLECTION_ID}"):
            return Resp(200, {"fields": []})
        rows = self.arabic if params.get("cmsLocaleId") == AR else self.primary
        return Resp(200, {"items": rows})

    def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append(("POST", url, None, json))
        return Resp(200, {"id": "NEW"})

    def patch(self, url, headers=None, json=None, timeout=None):
        self.calls.append(("PATCH", url, None, json))
        return Resp(200, {})

    def install(self):
        requests.get, requests.post, requests.patch = self.get, self.post, self.patch

    def arabic_patches(self):
        return [c for c in self.calls if c[0] == "PATCH" and (c[3] or {}).get("cmsLocaleId")]

    def primary_patches(self):
        return [c for c in self.calls if c[0] == "PATCH" and not (c[3] or {}).get("cmsLocaleId")]


def sm(fid, state="Not Started", goals=None, venue="Stadium"):
    scores = []
    if goals is not None:
        scores = [{"participant_id": 1, "description": "CURRENT", "score": {"goals": goals[0]}},
                  {"participant_id": 2, "description": "CURRENT", "score": {"goals": goals[1]}}]
    return {"id": fid, "starting_at": "2027-01-01T15:00:00Z", "state": {"name": state},
            "scores": scores, "venue": {"name": venue}, "league": {"name": "U21 Elite League"},
            "league_id": u21.LEAGUE_ID,
            "participants": [{"id": 1, "name": "Al Kholood U21", "meta": {"location": "home"}},
                             {"id": 2, "name": "Damac U21", "meta": {"location": "away"}}]}


def row(item_id, fid, locale, **fd):
    base = {"fixture-id": str(fid), "name": "n", "slug": f"u21-fixture-{fid}",
            "home-team-name": "Al Kholood U21", "away-team-name": "Damac U21",
            "starting-at": "2027-01-01T15:00:00.000Z", "time": "06:00 PM", "venue": "Stadium",
            "state": "Not Started", "league": "U21 Elite League"}
    base.update(fd)
    return {"id": item_id, "cmsLocaleId": locale, "isArchived": False, "isDraft": True,
            "fieldData": base}


def run(t, fixtures, enabled=True, dry=False):
    t.install()
    u21.sm_fixtures = lambda: fixtures
    u21.U21_ARABIC_SYNC_ENABLED = enabled
    u21.U21_ARABIC_SYNC_DRY_RUN = dry
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        u21.sync_u21_fixtures()
    return buf.getvalue()


check("defaults: enabled, live", u21.U21_ARABIC_SYNC_ENABLED is True and u21.U21_ARABIC_SYNC_DRY_RUN is False)

# changed score/state -> one Arabic PATCH with technical fields only
t = Transport([row("P1", 1, EN)], [row("P1", 1, AR)])
run(t, [sm(1, "Full Time", (2, 0))])
w = t.arabic_patches()
check("changed: exactly one Arabic PATCH", len(w) == 1)
body = w[0][3]
check("changed: Arabic locale, same item id", body["cmsLocaleId"] == AR and w[0][1].endswith("/items/P1"))
check("changed: only technical fields sent", set(body["fieldData"]) == {"state", "home-team-score", "away-team-score"})
check("changed: names/league/logos/slug never sent",
      not (set(body["fieldData"]) & {"name", "slug", "home-team-name", "away-team-name", "league",
                                     "home-team-logo", "away-team-logo", "tournament-logo"}))
check("english pass still updates the primary item", len(t.primary_patches()) == 1)

# unchanged -> no Arabic write
t = Transport([row("P1", 1, EN)], [row("P1", 1, AR)])
run(t, [sm(1)])
check("unchanged: no Arabic PATCH", t.arabic_patches() == [])

# translated (edited) Arabic fields are preserved
t = Transport([row("P1", 1, EN)], [row("P1", 1, AR, **{"home-team-name": "الخلود", "league": "دوري"})])
run(t, [sm(1, "Full Time", (1, 1))])
check("editorial Arabic text is never overwritten",
      all("home-team-name" not in c[3]["fieldData"] and "league" not in c[3]["fieldData"]
          for c in t.arabic_patches()))

# no Arabic variant -> skipped, nothing created
t = Transport([row("P1", 1, EN)], [])
out = run(t, [sm(1)])
check("missing variant: no create, no Arabic write",
      t.arabic_patches() == [] and not any(c[0] == "POST" for c in t.calls))
check("missing variant: reported as skipped", "no active Arabic variant" in out)

# new fixture (no primary item): english create only, no Arabic work for it
t = Transport([], [])
run(t, [sm(9)])
check("new fixture: created in English only", sum(1 for c in t.calls if c[0] == "POST") == 1 and t.arabic_patches() == [])

# archived Arabic variant skipped
arch = row("P1", 1, AR)
arch["isArchived"] = True
t = Transport([row("P1", 1, EN)], [arch])
run(t, [sm(1, "Full Time", (1, 0))])
check("archived Arabic variant: skipped", t.arabic_patches() == [])

# dry run
t = Transport([row("P1", 1, EN)], [row("P1", 1, AR)])
out = run(t, [sm(1, "Full Time", (1, 0))], dry=True)
check("dry run: no Arabic write", t.arabic_patches() == [] and "changes:" in out)

# disabled
t = Transport([row("P1", 1, EN)], [row("P1", 1, AR)])
run(t, [sm(1, "Full Time", (1, 0))], enabled=False)
check("disabled: no Arabic read, no Arabic write",
      t.arabic_patches() == [] and not any(c[2].get("cmsLocaleId") for c in t.calls if c[0] == "GET"))

# non-Arabic row in the Arabic read -> abort
t = Transport([row("P1", 1, EN)], [row("P1", 1, EN)])
run(t, [sm(1, "Full Time", (1, 0))])
check("non-Arabic row in Arabic read: abort", t.arabic_patches() == [])

# the primary locale can never be targeted explicitly
try:
    u21.update_webflow_item("P1", {"state": "x"}, cms_locale_id=EN)
    check("primary locale refused", False)
except AssertionError:
    check("primary locale refused", True)

print()
print("=" * 60)
if FAILURES:
    print(f"RESULT: {len(FAILURES)} FAILURE(S)")
    for f in FAILURES:
        print(" -", f)
    sys.exit(1)
print("RESULT: ALL CHECKS PASSED")
