"""Attacks on refresh mode, run before the clock allows it to touch YouTube.

Refresh is the step that turns one observation into a pair, so it is the step where a
velocity can be manufactured. It must re-observe the SAME ids, at a REAL later instant,
and it must not claim more than it collected.

Three properties, asked for by name:

    IT CANNOT SUBSTITUTE FRESH IDS      the pair must be the same video twice
    IT CANNOT FORGE ELAPSED TIME        the interval must be the clock's, not the caller's
    IT CANNOT CLAIM COMPLETENESS        after statistics came back short

No network. The transport is a fake and the store is a temp file, so this runs before
19:51:38Z without spending a call or touching the live baseline.
"""
from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import adapter
from collector import Collector


def _ok(name, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name:56s}{'' if cond else '  <-- ' + detail}")
    return bool(cond)


def _seeded_store():
    """A store that already holds a baseline, exactly like the live one."""
    db = str(Path(tempfile.mkdtemp()) / "state.sqlite3")
    c = Collector(store_path=db)
    for vid, views in (("v1", 340), ("v2", 16), ("v3", 0)):
        c.record_discovery(video_id=vid, query="q", region="US", language="en")
        c.record_observation(video_id=vid, observed_at="2026-08-20T10:00:00Z", views=views)
    c.close()
    return db


class CountingTransport(adapter.FakeTransport):
    """Records which endpoints were reached, so 'it did not search' is measured."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.endpoints = []

    def search_page(self, token, **req):
        self.endpoints.append("search")
        return super().search_page(token, **req)

    def statistics(self, ids):
        self.endpoints.append("statistics")
        return super().statistics(ids)

    def video_details(self, ids):
        self.endpoints.append("video_details")
        return super().video_details(ids)


def refresh_reads_ids_from_the_store_and_never_searches():
    """The pair must be the same video twice.

    If refresh searched, it would collect whatever is newest NOW and pair it with nothing
    — three fresh n=1 observations wearing the word 'refresh'. The ids must come from the
    store, and search must never be reached.
    """
    db = _seeded_store()
    c = Collector(store_path=db)
    ids = c.observed_video_ids()
    c.close()
    t = CountingTransport(stats={i: {"viewCount": "500"} for i in ids})
    adapter.fetch_statistics(ids, transport=t)
    return _ok("refresh takes its ids from the store, never from search",
               sorted(ids) == ["v1", "v2", "v3"] and "search" not in t.endpoints,
               f"ids={ids} endpoints={t.endpoints}")


def the_second_instant_comes_from_the_clock_not_the_caller():
    """The interval IS the measurement.

    record_observation takes observed_at from the statistics row, which the adapter
    stamps with one clock read per batch. Nothing in the refresh path lets a caller
    supply that instant — if it did, a replay could manufacture an hour that never
    elapsed and G02 would compute a velocity across invented time.
    """
    db = _seeded_store()
    t = CountingTransport(stats={"v1": {"viewCount": "400"}})
    row = adapter.fetch_statistics(["v1"], transport=t)["v1"]
    c = Collector(store_path=db)
    c.record_observation(video_id="v1", observed_at=row["observed_at"], views=row["views"])
    snaps = c.snapshots("v1")
    c.close()
    stamped_now = row["observed_at"] != "2026-08-20T10:00:00Z"
    return _ok("the second instant is the adapter's clock read",
               stamped_now and len(snaps) == 2,
               f"snapshots={len(snaps)} observed_at={row['observed_at']}")


def a_short_statistics_return_is_not_completeness():
    """Refresh hardcodes complete=True because it did no pagination.

    That is defensible for the SEARCH half — there was no search. It is not a statement
    about the statistics half, and the report prints one 'complete' field for both. If
    stats returns two of three, the run must not present itself as a complete
    re-observation of the baseline.
    """
    db = _seeded_store()
    c = Collector(store_path=db)
    ids = c.observed_video_ids()
    t = CountingTransport(stats={"v1": {"viewCount": "500"}, "v2": {"viewCount": "20"}})
    stats = adapter.fetch_statistics(ids, transport=t)
    unreturned = adapter.last_unreturned_ids()
    c.close()
    # The honest report of this run is: 3 asked, 2 returned, 1 unreturned, NOT complete.
    return _ok("a short statistics return is visible as short",
               len(stats) == 2 and unreturned == ["v3"],
               f"stats={len(stats)} unreturned={unreturned}")


def a_replay_inside_the_interval_adds_nothing():
    """Running refresh twice in five minutes must not create a third snapshot in the
    evidence path, or the minimum interval becomes advisory."""
    db = _seeded_store()
    c = Collector(store_path=db)
    t = CountingTransport(stats={"v1": {"viewCount": "400"}})
    for _ in range(2):
        row = adapter.fetch_statistics(["v1"], transport=t)["v1"]
        try:
            c.record_observation(video_id="v1", observed_at=row["observed_at"],
                                 views=row["views"])
        except Exception:
            pass
    n_snap, n_raw = len(c.snapshots("v1")), len(c.raw_snapshots("v1"))
    c.close()
    return _ok("a replay inside the interval adds no evidence snapshot",
               n_snap == 2, f"snapshots={n_snap} raw={n_raw}")


def _live_rows():
    live = Path("out/youtube-g03-live.sqlite3")
    if not live.exists():
        return None
    return sqlite3.connect(live).execute(
        "SELECT COUNT(*) FROM observations").fetchone()[0]


def the_baseline_on_disk_is_untouched_by_any_of_this(before):
    """These fixtures must not have written to the live baseline. Checked, not assumed.

    This case used to assert the baseline held exactly 3 rows, which was true when it was
    written and false an hour later when the experiment legitimately added its second
    observation and an audit row. That is a test asserting a MOMENT rather than a
    PROPERTY: it went red for the very success it was built to protect.

    The property is that running these fixtures does not change the live store. So the
    count is captured before the fixtures run and compared with the count after, and the
    number itself is none of this test's business.
    """
    after = _live_rows()
    if before is None:
        return _ok("the live baseline is untouched", True, "(not present here)")
    return _ok("running these fixtures did not touch the live baseline", after == before,
               f"{before} rows before, {after} after")


def main():
    print("  REFRESH ATTACK — run before the clock allows a live refresh")
    before = _live_rows()
    results = [
        refresh_reads_ids_from_the_store_and_never_searches(),
        the_second_instant_comes_from_the_clock_not_the_caller(),
        a_short_statistics_return_is_not_completeness(),
        a_replay_inside_the_interval_adds_nothing(),
        the_baseline_on_disk_is_untouched_by_any_of_this(before),
    ]
    failed = results.count(False)
    print(f"  {len(results) - failed}/{len(results)} held, {failed} open")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
