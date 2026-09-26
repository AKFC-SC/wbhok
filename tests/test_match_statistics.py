"""Offline tests for sync_match_statistics.py.

Run:  python3 tests/test_match_statistics.py
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

import sync_match_statistics as ms  # noqa: E402

FAILURES = []
AR, EN = ms.ARABIC_CMS_LOCALE_ID, ms.PRIMARY_CMS_LOCALE_ID
FIX, STATS = ms.FIXTURES_COLLECTION_ID, ms.STATS_COLLECTION_ID


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
    def __init__(self, fixtures, fixtures_ar, stats_en, stats_ar, sm):
        self.rows = {(FIX, EN): fixtures, (FIX, AR): fixtures_ar,
                     (STATS, EN): stats_en, (STATS, AR): stats_ar}
        self.sm, self.calls = sm, []

    def get(self, url, headers=None, params=None, timeout=None):
        params = params or {}
        self.calls.append(("GET", url, dict(params), None))
        if "sportmonks" in url:
            fid = url.rsplit("/", 1)[1]
            if fid not in self.sm:
                return Resp(404)
            return Resp(200, {"data": self.sm[fid]})
        cid = url.split("/collections/")[1].split("/")[0]
        items = self.rows[(cid, params.get("cmsLocaleId") or EN)]
        return Resp(200, {"items": items, "pagination": {"total": len(items)}})

    def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append(("POST", url, None, json))
        if url.endswith("/items/insert"):
            it = json["items"][0]
            return Resp(200, {"items": [{"id": it["id"], "cmsLocaleId": it["cmsLocaleIds"][0]}]})
        return Resp(200, {"id": "NEW-STATS"})

    def patch(self, url, headers=None, json=None, timeout=None):
        self.calls.append(("PATCH", url, None, json))
        return Resp(200, {})

    def install(self):
        requests.get, requests.post, requests.patch = self.get, self.post, self.patch

    def writes(self):
        return [c for c in self.calls if c[0] in ("POST", "PATCH")]


def st(pid, type_id, value):
    return {"type_id": type_id, "participant_id": pid, "data": {"value": value}}


def sm_fixture(fid, with_stats=True):
    stats = []
    if with_stats:
        for pid, base in ((1, 10), (2, 5)):
            stats += [st(pid, 45, 55.4 if pid == 1 else 44.6), st(pid, 42, base), st(pid, 86, base // 2),
                      st(pid, 34, 4), st(pid, 56, 9 if pid == 1 else 12), st(pid, 84, 2)]
    return {"id": int(fid), "league": {"name": "Pro League"},
            "scores": [{"participant_id": 1, "description": "CURRENT", "score": {"goals": 2}},
                       {"participant_id": 2, "description": "CURRENT", "score": {"goals": 1}}],
            "statistics": stats,
            "participants": [{"id": 1, "name": "Home FC", "image_path": "https://i/h.png", "meta": {"location": "home"}},
                             {"id": 2, "name": "Away FC", "image_path": "https://i/a.png", "meta": {"location": "away"}}]}


def fixture_row(item_id, fid, locale=EN, status="Full Time", **fd):
    d = {"sportsmonks-id": str(fid), "status": status}
    d.update(fd)
    return {"id": item_id, "cmsLocaleId": locale, "isArchived": False, "isDraft": False, "fieldData": d}


AR_FIX = lambda item_id, fid: fixture_row(item_id, fid, AR, **{"home-team-name": "الأول", "away-team-name": "الثاني", "league": "دوري روشن"})


def run(t, enabled=True, dry=False):
    t.install()
    ms.MATCH_STATS_SYNC_ENABLED = enabled
    ms.MATCH_STATS_SYNC_DRY_RUN = dry
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        result = ms.sync_match_statistics()
    return buf.getvalue(), result


check("defaults: enabled and live", ms.MATCH_STATS_SYNC_ENABLED is True and ms.MATCH_STATS_SYNC_DRY_RUN is False)
_wf = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".github", "workflows", "sync.yml")).read()
check("sync.yml runs the statistics sync after the fixture syncs",
      "python sync_match_statistics.py" in _wf and _wf.index("python sync.py") < _wf.index("python sync_u21.py") < _wf.index("python sync_match_statistics.py"))
check("sync.yml keeps its cron and manual trigger", 'cron: "17 * * * *"' in _wf and "workflow_dispatch" in _wf)

# ------------------------------------------------ values
v = ms.build_values(sm_fixture("100"))
check("possession rounded to integer", v["home-possession"] == 55 and v["away-possession"] == 45)
check("fouls committed = own fouls; suffered = opponent's",
      v["home-fouls-committed"] == 9 and v["away-fouls-committed"] == 12
      and v["home-fouls-suffered"] == 12 and v["away-fouls-suffered"] == 9)
check("scores from CURRENT", v["home-score"] == "2" and v["away-score"] == "1")
check("a stat SportMonks did not return is omitted (not 0)", "home-saves" not in v and "home-tackles" not in v)
check("clearances is never produced", not any("clearances" in k for k in v))
check("no statistics -> nothing produced", ms.build_values(sm_fixture("100", with_stats=False)) == {})
check("every produced key is in the allow-list", set(v) <= set(ms.ALLOWED_FIELDS))

# ------------------------------------------------ create Primary + Arabic
t = Transport([fixture_row("F1", 100)], [AR_FIX("F1", 100)], [], [], {"100": sm_fixture("100")})
out, r = run(t)
posts = [c for c in t.calls if c[0] == "POST"]
prim = [c for c in posts if c[1].endswith(f"/collections/{STATS}/items")]
ins = [c for c in posts if c[1].endswith("/items/insert")]
check("create: one Primary item, linked to the fixture item", len(prim) == 1 and prim[0][3]["fieldData"]["fixture"] == "F1")
check("create: name/slug/logos/competition set", prim[0][3]["fieldData"]["slug"] == "fixture-100-stats"
      and "home-logo" in prim[0][3]["fieldData"] and prim[0][3]["fieldData"]["competition"] == "Pro League")
check("create: Arabic variant on the SAME (new) item id, Arabic locale only, draft",
      len(ins) == 1 and ins[0][3]["items"][0]["id"] == "NEW-STATS"
      and ins[0][3]["items"][0]["cmsLocaleIds"] == [AR] and ins[0][3]["items"][0]["isDraft"] is True)
ar_fd = ins[0][3]["items"][0]["fieldData"]
check("create: Arabic names/competition come from the Arabic Fixture variant",
      ar_fd["home-team-name"] == "الأول" and ar_fd["competition"] == "دوري روشن")
check("create: Arabic numbers equal the Primary numbers",
      all(ar_fd[k] == prim[0][3]["fieldData"][k] for k in v))
check("create: only Primary is published", [c[3] for c in posts if c[1].endswith("/items/publish")] == [{"itemIds": ["NEW-STATS"]}])
check("create: never a SportMonks Arabic locale",
      not any(c[2].get("locale") for c in t.calls if c[0] == "GET"))

# ------------------------------------------------ existing stats: update only differences
pri = {"id": "S1", "cmsLocaleId": EN, "isArchived": False, "fieldData": dict(v, fixture="F1", name="n", slug="s")}
pri["fieldData"]["home-shots"] = 99                       # stale value
arb = {"id": "S1", "cmsLocaleId": AR, "isArchived": False, "fieldData": dict(v, fixture="F1", name="n", slug="s")}
arb["fieldData"]["home-shots"] = 98                       # stale Arabic value
t = Transport([fixture_row("F1", 100)], [AR_FIX("F1", 100)], [pri], [arb], {"100": sm_fixture("100")})
out, r = run(t)
pw = [c for c in t.calls if c[0] == "PATCH"]
check("update: primary PATCH only the changed field", any(c[3]["fieldData"] == {"home-shots": 10} and "cmsLocaleId" not in c[3] for c in pw))
check("update: Arabic PATCH carries the same corrected value, Arabic locale",
      any(c[3].get("cmsLocaleId") == AR and c[3]["fieldData"] == {"home-shots": 10} for c in pw))
check("update: no create, no new variant", not any(c[0] == "POST" and (c[1].endswith("/items") or c[1].endswith("/insert")) for c in t.calls))

# ------------------------------------------------ no change -> no writes
pri["fieldData"]["home-shots"] = 10
arb["fieldData"]["home-shots"] = 10
t = Transport([fixture_row("F1", 100)], [AR_FIX("F1", 100)], [pri], [arb], {"100": sm_fixture("100")})
out, r = run(t)
check("no change: zero writes, zero publish", t.writes() == [] and r["unchanged"] == 1 and r["arabic_unchanged"] == 1)

# ------------------------------------------------ scope guards
t = Transport([fixture_row("F1", 100, status="Not Started"), fixture_row("F2", 101, status="Full Time")],
              [], [], [], {"101": sm_fixture("101", with_stats=False)})
out, r = run(t)
check("only finished fixtures are in scope", r["fixtures_in_scope"] == 1)
check("no statistics from SportMonks: skipped, nothing written", r["skipped_no_statistics"] == 1 and t.writes() == [])

archived = fixture_row("F3", 102)
archived["isArchived"] = True
t = Transport([archived], [], [], [], {"102": sm_fixture("102")})
out, r = run(t)
check("archived fixture is ignored", r["fixtures_in_scope"] == 0 and t.writes() == [])

dup = [{"id": "S1", "cmsLocaleId": EN, "fieldData": {"fixture": "F1"}}, {"id": "S2", "cmsLocaleId": EN, "fieldData": {"fixture": "F1"}}]
t = Transport([fixture_row("F1", 100)], [AR_FIX("F1", 100)], dup, [], {"100": sm_fixture("100")})
out, r = run(t)
check("two stats items linking one fixture: skipped, no write (no duplicate)", r["skipped_duplicate_link"] == 1 and t.writes() == [])

# Arabic Fixture variant missing -> Primary still written, Arabic skipped
t = Transport([fixture_row("F1", 100)], [], [], [], {"100": sm_fixture("100")})
out, r = run(t)
check("no Arabic Fixture variant: Primary created, Arabic skipped",
      r["primary_created"] == 1 and r["skipped_arabic_no_fixture_variant"] == 1
      and not any(c[1].endswith("/items/insert") for c in t.calls))

# SportMonks failure -> counted, nothing written
t = Transport([fixture_row("F1", 100)], [AR_FIX("F1", 100)], [], [], {})
out, r = run(t)
check("SportMonks error: counted, no write", r["errors"] == 1 and t.writes() == [])

# ------------------------------------------------ dry run / disabled / safety
t = Transport([fixture_row("F1", 100)], [AR_FIX("F1", 100)], [], [], {"100": sm_fixture("100")})
out, r = run(t, dry=True)
check("dry run: zero writes", t.writes() == [] and r["would_create"] == 1 and r["arabic_would_create"] == 1)

t = Transport([fixture_row("F1", 100)], [AR_FIX("F1", 100)], [], [], {"100": sm_fixture("100")})
out, r = run(t, enabled=False)
check("disabled: no request at all", t.calls == [])

t = Transport([fixture_row("F1", 100)], [AR_FIX("F1", 100)], [], [], {"100": sm_fixture("100")})
t.rows[(STATS, AR)] = [{"id": "S9", "cmsLocaleId": EN, "fieldData": {}}]
out, r = run(t)
check("non-Arabic row in the Arabic read: abort, no write", t.writes() == [] and r["errors"] == 1)

check("no write ever targets the Fixtures collection",
      not any(c[0] in ("POST", "PATCH") and FIX in c[1] for c in t.calls))
try:
    ms.update_item("S1", {"home-shots": 1}, cms_locale_id=EN)
    check("primary locale refused", False)
except AssertionError:
    check("primary locale refused", True)
try:
    ms.assert_payload({"home-shots": 1, "match-hub-link": "x"})
    check("allow-list rejects unknown fields", False)
except AssertionError:
    check("allow-list rejects unknown fields", True)

print()
print("=" * 60)
if FAILURES:
    print(f"RESULT: {len(FAILURES)} FAILURE(S)")
    for f in FAILURES:
        print(" -", f)
    sys.exit(1)
print("RESULT: ALL CHECKS PASSED")
