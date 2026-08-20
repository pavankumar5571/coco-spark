"""Attacks on durability, written against the two properties I promised before seeing it.

A store is where guarantees go to die quietly. Everything G03 was built to protect —
a null that means "we were not told", a zero that means "nobody watched", an instant that
means "this is when we looked" — has to survive a round trip through a schema that has its
own opinions about types. SQLite is particularly good at accepting whatever you hand it.

Two properties, stated before the implementation existed:

    A RELOAD IS BYTE-FAITHFUL      including the nulls
    A RELOAD CANNOT FORGE TIME     a replay must not manufacture the interval

Everything below is one of those two wearing different clothes.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from collector import Collector


def _ok(name, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name:56s}{'' if cond else '  <-- ' + detail}")
    return bool(cond)


def _db():
    return str(Path(tempfile.mkdtemp()) / "state.sqlite3")


def null_is_not_zero_across_a_reload():
    """The whole of G03 in one case.

    likes=None means likes were hidden. likes=0 means nobody liked it. If the store
    cannot tell them apart, every guarantee upstream was theatre — the adapter refusing
    to substitute zero, the contract case forbidding it, the enterprise defect we
    refused. All of it is undone by one column with a DEFAULT 0.
    """
    db = _db()
    a = Collector(store_path=db)
    a.record_observation(video_id="v1", observed_at="2026-08-20T10:00:00Z",
                         views=1000, likes=None, comments=None)
    a.record_observation(video_id="v2", observed_at="2026-08-20T10:00:00Z",
                         views=0, likes=0, comments=0)
    b = Collector(store_path=db)
    s1 = b.snapshots("v1")[0]
    s2 = b.snapshots("v2")[0]
    return _ok("null and zero survive a reload as different things",
               s1["likes"] is None and s1["comments"] is None
               and s2["likes"] == 0 and s2["comments"] == 0 and s2["views"] == 0,
               f"v1 likes={s1['likes']!r} v2 likes={s2['likes']!r} v2 views={s2['views']!r}")


def a_hidden_subscriber_count_reloads_as_unknown():
    """Same defect, one table over. A channel that hides its subscriber count is not a
    channel with no subscribers, and G02 divides by these numbers."""
    db = _db()
    a = Collector(store_path=db)
    a.record_channel(channel_id="c1", title="X", hidden_subscriber_count=True,
                     subscriber_count=None)
    b = Collector(store_path=db)
    ch = b.channel("c1") if hasattr(b, "channel") else b.channels()["c1"]
    return _ok("a hidden subscriber count reloads as None",
               ch["subscriber_count"] is None, f"got {ch['subscriber_count']!r}")


def discoveries_still_accumulate_after_a_reload():
    """G03 case 4, put through the store.

    A video found by two queries must still show two. If the store keys discoveries by
    video alone, the second query overwrites the first and G02's single-query gate starts
    refusing genuine multi-query clusters — a false negative created by a schema.
    """
    db = _db()
    a = Collector(store_path=db)
    a.record_discovery(video_id="v1", query="five little stars", region="US", language="en")
    b = Collector(store_path=db)
    b.record_discovery(video_id="v1", query="counting stars song", region="US", language="en")
    c = Collector(store_path=db)
    return _ok("two queries survive as two discoveries",
               len({d["query"] for d in c.discoveries("v1")}) == 2,
               str(c.discoveries("v1")))


def a_replay_cannot_manufacture_an_interval():
    """The forgery case.

    Re-running yesterday's collection today must not produce two observations an hour
    apart. The timestamp belongs to the moment of observation, not to the moment of
    writing — so replaying an identical reading after a reload must remain ONE
    observation, and velocity must remain undefined.
    """
    db = _db()
    a = Collector(store_path=db)
    a.record_observation(video_id="v1", observed_at="2026-08-20T10:00:00Z", views=1000)
    b = Collector(store_path=db)
    b.record_observation(video_id="v1", observed_at="2026-08-20T10:00:00Z", views=1000)
    return _ok("an identical replay after reload stays one observation",
               len(b.snapshots("v1")) == 1, f"{len(b.snapshots('v1'))} snapshots")


def a_conflicting_replay_is_refused_across_the_reload():
    """Same instant, different count, different process. In one run this raises
    ObservationConflict. A store that silently upserts would make the guarantee
    process-local, which is the same as not having it."""
    db = _db()
    a = Collector(store_path=db)
    a.record_observation(video_id="v1", observed_at="2026-08-20T10:00:00Z", views=500)
    b = Collector(store_path=db)
    try:
        b.record_observation(video_id="v1", observed_at="2026-08-20T10:00:00Z", views=999)
        held = False
    except Exception:
        held = True
    return _ok("a conflicting replay is refused across the reload",
               held and b.snapshots("v1")[0]["views"] == 500,
               "silently overwrote" if not held else "")


def sub_interval_readings_stay_out_of_evidence_after_a_reload():
    """A reading inside the minimum interval is preserved in raw and withheld from
    snapshots. Both halves must survive: losing the raw destroys the audit, and promoting
    it into snapshots hands G02 three minutes of rounding as a velocity."""
    db = _db()
    a = Collector(store_path=db)
    a.record_observation(video_id="v1", observed_at="2026-08-20T10:00:00Z", views=1000)
    a.record_observation(video_id="v1", observed_at="2026-08-20T10:03:00Z", views=1004)
    b = Collector(store_path=db)
    return _ok("a sub-interval reading reloads into raw, not into snapshots",
               len(b.snapshots("v1")) == 1 and len(b.raw_snapshots("v1")) == 2,
               f"snapshots={len(b.snapshots('v1'))} raw={len(b.raw_snapshots('v1'))}")


def the_observed_instant_reloads_exactly():
    """A timestamp that loses its timezone or its precision is a timestamp that can be
    compared wrongly. The interval between two readings is the entire measurement."""
    db = _db()
    a = Collector(store_path=db)
    a.record_observation(video_id="v1", observed_at="2026-08-20T10:00:00Z", views=1000)
    a.record_observation(video_id="v1", observed_at="2026-08-20T11:30:00Z", views=1400)
    before = [s["observed_at"] for s in a.snapshots("v1")]
    after = [s["observed_at"] for s in Collector(store_path=db).snapshots("v1")]
    return _ok("observation instants reload identically", before == after,
               f"{before} vs {after}")


def main():
    print("  G03 PERSISTENCE ATTACK — byte-faithful reload, and no forged time")
    results = []
    for fn in (null_is_not_zero_across_a_reload,
               a_hidden_subscriber_count_reloads_as_unknown,
               discoveries_still_accumulate_after_a_reload,
               a_replay_cannot_manufacture_an_interval,
               a_conflicting_replay_is_refused_across_the_reload,
               sub_interval_readings_stay_out_of_evidence_after_a_reload,
               the_observed_instant_reloads_exactly):
        try:
            results.append(fn())
        except Exception as exc:
            results.append(_ok(fn.__name__, False, f"{type(exc).__name__}: {exc}"))
    failed = results.count(False)
    print(f"  {len(results) - failed}/{len(results)} held, {failed} open")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
