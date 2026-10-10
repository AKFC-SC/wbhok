"""Offline tests for the empty-SportMonks-response guard in sync.py.

Run:  python3 tests/test_empty_fixture_guard.py

Every HTTP call goes through a fake transport; anything unexpected raises.
Nothing here touches Webflow or SportMonks.
"""

import contextlib
import io
import os
import sys
from datetime import datetime, timedelta, timezone

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

# The exact body SportMonks returns for an empty / not-subscribed range.
SM_EMPTY = {
    "message": (
        "No result(s) found matching your request. Either the query did "
        "not return any results or you don't have access to it via your "
        "current subscription."
    )
}


def check(label, condition):
    print(("[PASS] " if condition else "[FAIL] ") + label)
    if not condition:
        FAILURES.append(label)


def iso_days_from_today(days):
    day = datetime.now(timezone.utc) + timedelta(days=days)
    return day.strftime("%Y-%m-%dT13:50:00.000Z")


def item(fixture_id, days, archived=False):
    return {
        "id": f"wf-{fixture_id}",
        "isArchived": archived,
        "fieldData": {
            "sportsmonks-id": str(fixture_id),
            "date-time": iso_days_from_today(days),
        },
    }


def raises(fn):
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            fn()
    except RuntimeError as err:
        return str(err)
    return None


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
    """SportMonks returns SM_EMPTY; Webflow returns `items`. Writes are recorded."""

    def __init__(self, items):
        self.items = items
        self.writes = []

    def get(self, url, params=None, headers=None, timeout=None):
        if "api.sportmonks.com" in url:
            return Resp(200, SM_EMPTY)
        if url.endswith(f"/collections/{sync.COLLECTION_ID}"):
            return Resp(200, {"fields": []})
        if url.endswith(f"/collections/{sync.COLLECTION_ID}/items"):
            return Resp(200, {
                "items": self.items,
                "pagination": {"total": len(self.items)},
            })
        raise AssertionError(f"unexpected GET {url}")

    def write(self, method):
        def _write(url, *args, **kwargs):
            self.writes.append((method, url))
            return Resp(200, {})
        return _write


@contextlib.contextmanager
def fake_http(transport):
    saved = (sync.requests.get, sync.requests.post, sync.requests.patch)
    sync.requests.get = transport.get
    sync.requests.post = transport.write("POST")
    sync.requests.patch = transport.write("PATCH")
    try:
        yield
    finally:
        sync.requests.get, sync.requests.post, sync.requests.patch = saved


# ------------------------------------------------------------------
# Unit: assert_fixtures_not_silently_empty
# ------------------------------------------------------------------

guard = sync.assert_fixtures_not_silently_empty

err = raises(lambda: guard([], [item(19778731, -1), item(19778742, 5)]))
check("empty SportMonks + CMS fixtures in window -> raises", err is not None)
check("error names the window and an example fixture id",
      err is not None and "19778731" in err and "0 fixtures" in err)

check("empty SportMonks + only fixtures before window -> passes",
      raises(lambda: guard([], [item(1, -(sync.LOOKBACK_DAYS + 3))])) is None)

check("empty SportMonks + only archived fixtures in window -> passes",
      raises(lambda: guard([], [item(2, 5, archived=True)])) is None)

check("empty SportMonks + empty CMS (off-season) -> passes",
      raises(lambda: guard([], [])) is None)

check("item without date-time is ignored",
      raises(lambda: guard([], [{"id": "x", "fieldData": {}}])) is None)

check("non-empty SportMonks -> passes even with CMS fixtures in window",
      raises(lambda: guard([{"id": 19778731}], [item(19778731, 5)])) is None)

check("boundary: fixture exactly on window start counts",
      raises(lambda: guard([], [item(3, -sync.LOOKBACK_DAYS)])) is not None)

# ------------------------------------------------------------------
# End to end: sync_fixtures() with SportMonks returning the empty body
# ------------------------------------------------------------------

transport = Transport([item(19778731, -1), item(19778742, 5)])
out = io.StringIO()
with fake_http(transport):
    try:
        with contextlib.redirect_stdout(out):
            sync.sync_fixtures()
        e2e_err = None
    except RuntimeError as e:
        e2e_err = str(e)

check("sync_fixtures() fails (non-zero exit) instead of silent success",
      e2e_err is not None)
check("no Webflow create/update/publish was attempted",
      transport.writes == [])
check("SportMonks message is printed in the log",
      "SPORTSMONKS MESSAGE:" in out.getvalue())

transport = Transport([item(1, -(sync.LOOKBACK_DAYS + 30))])
out = io.StringIO()
with fake_http(transport):
    try:
        with contextlib.redirect_stdout(out):
            sync.sync_fixtures()
        e2e_err = None
    except RuntimeError as e:
        e2e_err = str(e)

check("sync_fixtures() still succeeds when the window is genuinely empty",
      e2e_err is None)
check("...and writes/publishes nothing", transport.writes == [])
check("...and reports 'Publish skipped.'", "Publish skipped." in out.getvalue())

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILURE(S)")
    sys.exit(1)
print("ALL PASSED")
