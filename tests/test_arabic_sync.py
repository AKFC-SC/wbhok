"""Offline tests for the Arabic fixture sync (sync_fixtures_arabic).

Run:  python3 tests/test_arabic_sync.py

Every HTTP call goes through a fake transport; anything unexpected raises.
Nothing here touches Webflow or SportMonks.
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

AR = sync.ARABIC_CMS_LOCALE_ID
EN = sync.PRIMARY_CMS_LOCALE_ID


def check(label, condition):
    print(("[PASS] " if condition else "[FAIL] ") + label)
    if not condition:
        FAILURES.append(label)


class Resp:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self.ok = status < 400
        self._body = body if body is not None else {}
        self.text = str(self._body)

    def json(self):
        return self._body

    def raise_for_status(self):
        if not self.ok:
            raise requests.exceptions.HTTPError("err", response=self)


class Transport:
    def __init__(self, fixtures_en, fixtures_ar, teams_en, teams_ar):
        self.rows = {
            (sync.COLLECTION_ID, EN): list(fixtures_en),
            (sync.COLLECTION_ID, AR): list(fixtures_ar),
            (sync.TEAM_COLLECTION_ID, EN): list(teams_en),
            (sync.TEAM_COLLECTION_ID, AR): list(teams_ar),
        }
        self.calls = []

    def get(self, url, headers=None, params=None, timeout=None):
        params = params or {}
        self.calls.append(("GET", url, dict(params), None))
        parts = url.split("/collections/")[1].split("/")
        cid = parts[0]
        if len(parts) == 1:
            return Resp(200, {"fields": []})
        loc = params.get("cmsLocaleId") or EN
        items = self.rows[(cid, loc)]
        return Resp(200, {"items": items, "pagination": {"total": len(items)}})

    def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append(("POST", url, None, json))
        if url.endswith("/items/insert"):
            item = json["items"][0]
            return Resp(200, {"items": [{"id": item["id"],
                                         "cmsLocaleId": item["cmsLocaleIds"][0]}]})
        if url.endswith("/items/publish"):
            return Resp(200, {})
        return Resp(200, {"id": "NEW-EN"})

    def patch(self, url, headers=None, json=None, timeout=None):
        self.calls.append(("PATCH", url, None, json))
        return Resp(200, {})

    def install(self):
        requests.get, requests.post, requests.patch = self.get, self.post, self.patch

    def arabic_writes(self):
        out = []
        for m, url, _, body in self.calls:
            if m == "POST" and url.endswith("/items/insert"):
                out.append((m, url, body))
            if m == "PATCH" and body and body.get("cmsLocaleId"):
                out.append((m, url, body))
        return out

    def en_patches(self):
        return [c for c in self.calls if c[0] == "PATCH" and not (c[3] or {}).get("cmsLocaleId")]


# ---------------------------------------------------------------- builders

def team_en(item_id, sm_id, name):
    return {"id": item_id, "cmsLocaleId": EN, "isArchived": False, "isDraft": False,
            "lastPublished": "2026-01-01T00:00:00Z",
            "fieldData": {"sportsmonks-team-id": sm_id, "name": name}}


def team_ar(item_id, name, **kw):
    return {"id": item_id, "cmsLocaleId": AR, "isArchived": kw.get("archived", False),
            "isDraft": True, "lastPublished": None,
            "fieldData": {"name": name}}


TEAMS_EN = [
    team_en("T-KH", "232744", "Al Kholood"),
    team_en("T-SH", "16184", "Al Shabab"),
    team_en("T-JD", "148884", "Jeddah"),
]
TEAMS_AR = [
    team_ar("T-KH", "الخلود"),
    team_ar("T-SH", "الشباب"),
    team_ar("T-JD", "جدة"),
]


def sm_fixture(fid, home, away, league="Pro League", state="Not Started", venue="Ar-Rass Stadium"):
    return {
        "id": fid,
        "starting_at": "2027-02-01 16:00:00",
        "state": {"name": state},
        "scores": [],
        "venue": {"name": venue},
        "league": {"name": league, "image_path": "https://img/league.png"},
        "participants": [
            {"id": home[0], "name": home[1], "image_path": "https://img/h.png",
             "meta": {"location": "home"}},
            {"id": away[0], "name": away[1], "image_path": "https://img/a.png",
             "meta": {"location": "away"}},
        ],
    }


KH = (232744, "Al Kholood")
SH = (16184, "Al Shabab")
JD = (148884, "Jeddah")
UNKNOWN = (999999, "Some New Club")

LOGOS = {
    "opposing-team-logo": {"fileId": "f1", "url": "https://cdn/h.png"},
    "away-team-logo": {"fileId": "f2", "url": "https://cdn/a.png"},
    "tournament-logo": {"fileId": "f3", "url": "https://cdn/l.png"},
}


def en_row(item_id, fid, **fd):
    return {"id": item_id, "cmsLocaleId": EN, "isArchived": False, "isDraft": False,
            "fieldData": {"sportsmonks-id": str(fid), "slug": f"fixture-{fid}", **LOGOS, **fd}}


def ar_row(item_id, fid, managed=True, **fd):
    data = {"sportsmonks-id": str(fid), "slug": f"fixture-{fid}", **fd}
    if managed:
        data.setdefault("home-team", "T-KH")
        data.setdefault("away-team", "T-SH")
    return {"id": item_id, "cmsLocaleId": AR, "isArchived": False, "isDraft": True,
            "lastPublished": None, "fieldData": data}


def run(t, fixtures, arabic=True, dry=False, teams_flag=True):
    t.install()
    sync.sm_fixtures = lambda locale=None: fixtures
    sync.TEAM_REFERENCES_ENABLED = teams_flag
    sync.ARABIC_SYNC_ENABLED = arabic
    sync.ARABIC_SYNC_DRY_RUN = dry
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        sync.sync_fixtures()
    return buf.getvalue()


def fresh(fixtures_en, fixtures_ar):
    return Transport(fixtures_en, fixtures_ar, TEAMS_EN, TEAMS_AR)


# ============================================================ 1. CREATE
f1 = sm_fixture(1001, KH, SH, league="Pro League")
t = fresh([en_row("E1", 1001)], [])
out = run(t, [f1])
w = t.arabic_writes()
check("create: exactly one Arabic write", len(w) == 1)
m, url, body = w[0]
item = body["items"][0]
fd = item["fieldData"]
check("create: insert endpoint on the SAME item id", url.endswith("/items/insert") and item["id"] == "E1")
check("create: Arabic locale only, draft, not archived",
      item["cmsLocaleIds"] == [AR] and item["isDraft"] is True and item["isArchived"] is False)
check("create: Arabic names and title from Arabic Team CMS",
      fd["home-team-name"] == "الخلود" and fd["away-team-name"] == "الشباب"
      and fd["name"] == "الخلود ضد الشباب")
check("create: references are the Arabic-variant item ids", fd["home-team"] == "T-KH" and fd["away-team"] == "T-SH")
check("create: league Pro League -> دوري روشن", fd["league"] == "دوري روشن")
check("create: primary slug, sportsmonks-id, venue, status copied from EN",
      fd["slug"] == "fixture-1001" and fd["sportsmonks-id"] == "1001"
      and fd["venue"] == "Ar-Rass Stadium" and fd["status"] == "Not Started")
check("create: logos copied from the primary item", all(fd.get(k) == LOGOS[k] for k in LOGOS))
check("create: no match-hub-link", "match-hub-link" not in fd)
check("create: payload inside the allow-list", set(fd) <= set(sync.ARABIC_CREATE_FIELDS))
check("create: no SportMonks locale=ar request is made",
      not any(c[2] and c[2].get("locale") == "ar" for c in t.calls if c[0] == "GET"))
check("create: Arabic Team CMS is read with the Arabic locale",
      any(c[0] == "GET" and sync.TEAM_COLLECTION_ID in c[1] and c[2].get("cmsLocaleId") == AR for c in t.calls))
check("create: Team CMS never written",
      not any(sync.TEAM_COLLECTION_ID in c[1] for c in t.calls if c[0] in ("POST", "PATCH")))

# Kings Cup + Jeddah
f2 = sm_fixture(1002, JD, KH, league="Kings Cup")
t = fresh([en_row("E2", 1002)], [])
run(t, [f2])
fd = t.arabic_writes()[0][2]["items"][0]["fieldData"]
check("Jeddah -> جدة, title جدة ضد الخلود", fd["home-team-name"] == "جدة" and fd["name"] == "جدة ضد الخلود")
check("Kings Cup -> كأس الملك", fd["league"] == "كأس الملك")
check("Jeddah reference is its Arabic variant", fd["home-team"] == "T-JD")

# Unknown league: field omitted, no English fallback
f3 = sm_fixture(1003, KH, SH, league="Some Other Cup")
t = fresh([en_row("E3", 1003)], [])
run(t, [f3])
fd = t.arabic_writes()[0][2]["items"][0]["fieldData"]
check("unmapped league: omitted, English name never used", "league" not in fd)

# Empty venue omitted on create
f4 = sm_fixture(1004, KH, SH, venue="")
t = fresh([en_row("E4", 1004)], [])
run(t, [f4])
fd = t.arabic_writes()[0][2]["items"][0]["fieldData"]
check("create: empty venue/scores omitted", "venue" not in fd and "home-team-score" not in fd)

# ============================================================ 2. MISSING ARABIC TEAM
f5 = sm_fixture(1005, KH, UNKNOWN)
t = fresh([en_row("E5", 1005)], [])
out = run(t, [f5])
check("missing team (not in Team CMS): create blocked, no Arabic write", t.arabic_writes() == [])
check("missing team: no Team CMS item created",
      not any(sync.TEAM_COLLECTION_ID in c[1] for c in t.calls if c[0] in ("POST", "PATCH")))

teams_en_extra = TEAMS_EN + [team_en("T-NEW", "999999", "Some New Club")]
t = Transport([en_row("E5", 1005)], [], teams_en_extra, TEAMS_AR)   # Primary exists, no Arabic variant
out = run(t, [f5])
check("Primary team without Arabic variant: create blocked", t.arabic_writes() == [])
check("Primary team without Arabic variant: warning logged", "no usable Arabic Team variant" in out)
check("Primary team item is never used inside an Arabic write",
      not any("T-NEW" in str(c[3]) for c in t.calls if c[0] in ("POST", "PATCH") and "insert" in c[1]))

t = Transport([en_row("E5", 1005)], [], teams_en_extra, TEAMS_AR + [team_ar("T-NEW", "  ")])
run(t, [f5])
check("Arabic Team variant with empty name is not usable", t.arabic_writes() == [])

t = Transport([en_row("E5", 1005)], [], teams_en_extra, TEAMS_AR + [team_ar("T-NEW", "نادي", archived=True)])
run(t, [f5])
check("archived Arabic Team variant is not usable", t.arabic_writes() == [])

# ============================================================ 3. UPDATE
f6 = sm_fixture(1006, KH, SH, state="Full Time")
existing = ar_row("E6", 1006, **{"name": "الخلود ضد الشباب", "home-team-name": "الخلود",
                                 "away-team-name": "الشباب", "league": "دوري روشن",
                                 "status": "Not Started", "venue": "Ar-Rass Stadium",
                                 "date-time": "2027-02-01T16:00:00.000Z", "time-3": "07:00 PM"})
t = fresh([en_row("E6", 1006)], [existing])
run(t, [f6])
w = t.arabic_writes()
check("update: one PATCH, Arabic locale", len(w) == 1 and w[0][0] == "PATCH" and w[0][2]["cmsLocaleId"] == AR)
check("update: only the changed field(s) sent",
      "status" in w[0][2]["fieldData"] and "name" not in w[0][2]["fieldData"]
      and "slug" not in w[0][2]["fieldData"])
check("update: no insert (no duplicate variant)", not any(x[0] == "POST" for x in w))
check("update: payload inside the allow-list", set(w[0][2]["fieldData"]) <= set(sync.ARABIC_UPDATE_FIELDS))

# Identical row -> no write
f7 = sm_fixture(1007, KH, SH)
same = ar_row("E7", 1007, **{"name": "الخلود ضد الشباب", "home-team-name": "الخلود",
                             "away-team-name": "الشباب", "league": "دوري روشن",
                             "status": "Not Started", "venue": "Ar-Rass Stadium",
                             "date-time": "2027-02-01T16:00:00.000Z", "time-3": "07:00 PM",
                             "home-team-score": None, "away-team-score": None})
t = fresh([en_row("E7", 1007)], [same])
out = run(t, [f7])
check("update: identical Arabic row -> no write", t.arabic_writes() == [])

# Stale references are corrected
stale = ar_row("E7", 1007, **{**same["fieldData"], "away-team": "T-JD"})
t = fresh([en_row("E7", 1007)], [stale])
run(t, [f7])
w = t.arabic_writes()
check("update: wrong reference corrected to the Arabic variant",
      len(w) == 1 and w[0][2]["fieldData"].get("away-team") == "T-SH")

# Update with a missing Arabic team: technical only, names/refs untouched
f8 = sm_fixture(1008, KH, UNKNOWN, state="Full Time")
managed = ar_row("E8", 1008, **{"name": "x", "status": "Not Started"})
t = fresh([en_row("E8", 1008)], [managed])
out = run(t, [f8])
w = t.arabic_writes()
check("update + missing Arabic team: technical fields only",
      len(w) == 1 and not (set(w[0][2]["fieldData"]) & {"name", "home-team", "away-team",
                                                        "home-team-name", "away-team-name"}))

# ============================================================ 4. LEGACY / GUARDS
f9 = sm_fixture(1009, KH, SH, state="Full Time")
legacy = ar_row("E9", 1009, managed=False, **{"slug": "al-ittihad-gw1", "status": "Not Started"})
t = fresh([en_row("E9", 1009)], [legacy])
run(t, [f9])
check("legacy Arabic row (no Arabic Team refs) is never touched", t.arabic_writes() == [])

# Duplicate risk: an unlinked Arabic row with the same sportsmonks-id exists
f10 = sm_fixture(1010, KH, SH)
other = ar_row("OTHER", 1010, managed=False)
t = fresh([en_row("E10", 1010)], [other])
run(t, [f10])
check("no duplicate: other Arabic row with same sportsmonks-id -> skipped", t.arabic_writes() == [])

# Second run after create: variant now exists -> update path, never a second insert
created = ar_row("E1", 1001, **{"name": "الخلود ضد الشباب"})
t = fresh([en_row("E1", 1001)], [created])
run(t, [f1])
check("re-run: no second insert for an existing variant",
      not any(x[0] == "POST" for x in t.arabic_writes()))

# Archived variant / archived primary
arch = ar_row("E11", 1011, **{"name": "n"})
arch["isArchived"] = True
t = fresh([en_row("E11", 1011)], [arch])
run(t, [sm_fixture(1011, KH, SH, state="Full Time")])
check("archived Arabic variant is skipped", t.arabic_writes() == [])

t = fresh([en_row("E12", 1012, )], [])
t.rows[(sync.COLLECTION_ID, EN)][0]["isArchived"] = True
run(t, [sm_fixture(1012, KH, SH)])
check("archived primary: no Arabic create", t.arabic_writes() == [])

# ============================================================ 5. EN UNTOUCHED / NO PUBLISH
t = fresh([en_row("E1", 1001)], [])
run(t, [f1])
en_locale_writes = [c for c in t.calls
                    if c[0] in ("POST", "PATCH")
                    and (c[3] or {}).get("cmsLocaleId") == EN]
check("no write ever targets the primary locale", en_locale_writes == [])
check("no insert includes the primary locale",
      not any(EN in (i.get("cmsLocaleIds") or []) for c in t.calls
              if c[0] == "POST" and c[1].endswith("/insert") for i in c[3]["items"]))
publishes = [c for c in t.calls if c[0] == "POST" and c[1].endswith("/items/publish")]
check("publish only carries plain English item ids (no locale ids, no Arabic)",
      all(set(c[3]) == {"itemIds"} for c in publishes))

# EN pass writes are the same whether Arabic is on or off
t_on = fresh([en_row("E1", 1001)], [])
run(t_on, [f1], arabic=True)
t_off = fresh([en_row("E1", 1001)], [])
run(t_off, [f1], arabic=False)
def en_calls(t):
    return [(c[0], c[1], c[3]) for c in t.calls if c[0] in ("POST", "PATCH") and not c[1].endswith("/insert")]
check("English writes identical with Arabic sync on and off", en_calls(t_on) == en_calls(t_off))
check("Arabic off: no Arabic write and no Arabic reads",
      t_off.arabic_writes() == []
      and not any(c[0] == "GET" and (c[2] or {}).get("cmsLocaleId") == AR for c in t_off.calls))

# ============================================================ 6. DRY RUN
t = fresh([en_row("E1", 1001), en_row("E6", 1006)], [existing])
out = run(t, [f1, f6], dry=True)
check("dry run: zero Arabic writes", t.arabic_writes() == [])
check("dry run: reports would-create / would-update",
      "DRY-RUN CREATE" in out and "DRY-RUN UPDATE" in out)

# ============================================================ 7. READ SAFETY
t = fresh([en_row("E1", 1001)], [])
t.rows[(sync.COLLECTION_ID, AR)] = [en_row("E1", 1001)]        # Webflow returns a non-Arabic row
out = run(t, [f1])
check("non-Arabic row in the Arabic read: Arabic sync aborts, no write", t.arabic_writes() == [])

t = fresh([en_row("E1", 1001)], [])
out = run(t, [f1], teams_flag=False)
check("Team CMS unavailable: no Arabic write", t.arabic_writes() == [])

# ============================================================ 8. DIRECT GUARDS
try:
    sync.assert_arabic_payload({"name": "x", "match-hub-link": "u"}, sync.ARABIC_CREATE_FIELDS)
    check("allow-list rejects match-hub-link", False)
except AssertionError:
    check("allow-list rejects match-hub-link", True)

try:
    sync.create_webflow_item_arabic_variant("E1", {"slug": "s", "name": "n", "seo-title": "t"})
    check("create refuses fields outside the allow-list", False)
except AssertionError:
    check("create refuses fields outside the allow-list", True)

print()
print("=" * 60)
if FAILURES:
    print(f"RESULT: {len(FAILURES)} FAILURE(S)")
    for f in FAILURES:
        print(" -", f)
    sys.exit(1)
print("RESULT: ALL CHECKS PASSED")
