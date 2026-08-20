"""What a YouTube observation collector must survive, written before one exists.

G02 judges preserved observations. G03 produces them — so every defect here is upstream
of every judgement, and a collector that quietly rounds, fills or invents will make the
evidence engine confident about fiction. G02 cannot detect that: it only sees what this
layer hands it.

These cases are the contract. They are written against an INTERFACE rather than an
implementation, deliberately, so that the implementation is built to them instead of them
being fitted to whatever it happens to do. Run now, it skips and prints the spec. Run when
`collector.py` lands, it attacks it.

    python test_collector_contract.py

THE ONE RULE UNDERNEATH ALL OF THEM: a collector records what the platform said and what
it was asked. It never computes a rate, never substitutes a zero for a silence, and never
infers a relationship it was not told.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

try:
    import collector                                     # noqa: F401
    HAVE = True
except ModuleNotFoundError:
    collector = None
    HAVE = False


CASES = []


def case(name, why):
    def wrap(fn):
        CASES.append((name, why, fn))
        return fn
    return wrap


def _ok(name, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name:52s}{'' if cond else '  <-- ' + detail}")
    return bool(cond)


# --------------------------------------------------------------------------------------
# WHAT THE PLATFORM SAYS

@case("views can go DOWN and both readings survive",
      "YouTube revises counts downward after spam removal. A collector that treats a "
      "decrease as an error, a zero, or a reason to overwrite the earlier reading has "
      "destroyed the only evidence that the revision happened. G02 already refuses to "
      "compute velocity across a decrease — it can only do that if it SEES the decrease.")
def counter_regression(c):
    obs = c.record_observation(video_id="v1", observed_at="2026-08-20T10:00:00Z", views=5000)
    obs2 = c.record_observation(video_id="v1", observed_at="2026-08-20T12:00:00Z", views=4200)
    snaps = c.snapshots("v1")
    return (len(snaps) == 2 and snaps[-1]["views"] == 4200
            and "velocity" not in obs2 and "views_per_hour" not in obs2)


@case("a hidden subscriber count is null, never zero",
      "YouTube returns hiddenSubscriberCount for channels that hide it. Zero is a CLAIM "
      "that nobody subscribes; null is the truth, which is that we were not told. G02's "
      "peer baselines divide by these numbers, so a fabricated zero becomes a fabricated "
      "breakout — the exact defect that let 96 views authorise production.")
def hidden_subscribers(c):
    ch = c.record_channel(channel_id="c1", title="X", hidden_subscriber_count=True,
                          subscriber_count=None)
    return ch["subscriber_count"] is None


@case("missing likes and comments stay missing",
      "Disabled comments and hidden likes are common on kids content and are not zeros. "
      "An engagement rate computed from a substituted zero is a measurement of our own "
      "default.")
def missing_engagement(c):
    o = c.record_observation(video_id="v1", observed_at="2026-08-20T10:00:00Z",
                             views=5000, likes=None, comments=None)
    return o["likes"] is None and o["comments"] is None


# --------------------------------------------------------------------------------------
# WHAT WE ASKED, AND WHAT WE MAY NOT INFER

@case("a video found by two queries records both discoveries",
      "G02 refuses a cluster that came from a single query family. That check is only "
      "meaningful if discovery context ACCUMULATES: if the second query overwrites the "
      "first, a video found five ways looks like a video found one way, and a genuine "
      "multi-query cluster gets refused as a single-query artefact.")
def discovery_accumulates(c):
    c.record_discovery(video_id="v1", query="five little stars", region="US", language="en")
    c.record_discovery(video_id="v1", query="counting stars song", region="US", language="en")
    d = c.discoveries("v1")
    return len({x["query"] for x in d}) == 2


@case("channel ownership is never inferred from channel_id",
      "Three channel ids is not three owners. G02 now demands an explicit "
      "channel_owner_hint and says channel_independence_unverified without one. If the "
      "collector manufactures that hint from the id, it hands G02 a guarantee nobody "
      "made, and the one honest 'we do not know' in the whole pipeline disappears.")
def no_inferred_ownership(c):
    ch = c.record_channel(channel_id="c1", title="X")
    return ch.get("channel_owner_hint") is None


# --------------------------------------------------------------------------------------
# TIME

@case("two readings at the same instant do not become two observations",
      "A retry, a re-run, or an overlapping schedule collects the same moment twice. "
      "Two rows at one timestamp are not two observations, and G02's confidence counts "
      "observations — so a duplicate is free confidence in evidence that never grew.")
def idempotent_at_one_instant(c):
    c.record_observation(video_id="v1", observed_at="2026-08-20T10:00:00Z", views=5000)
    c.record_observation(video_id="v1", observed_at="2026-08-20T10:00:00Z", views=5000)
    return len(c.snapshots("v1")) == 1


@case("readings closer than the minimum interval are refused or marked",
      "Two counts three minutes apart measure rounding and propagation delay, not "
      "demand. A rate computed from them is noise wearing a decimal point.")
def minimum_interval(c):
    c.record_observation(video_id="v1", observed_at="2026-08-20T10:00:00Z", views=5000)
    second = c.record_observation(video_id="v1", observed_at="2026-08-20T10:03:00Z",
                                  views=5004)
    snaps = c.snapshots("v1")
    return len(snaps) == 1 or second.get("below_minimum_interval") is True


# --------------------------------------------------------------------------------------
# WHAT WENT WRONG WHILE COLLECTING

@case("the same video on two pages is one video",
      "Paginated search returns overlaps routinely. Counted twice, one video becomes two "
      "of the three G02 requires, and the third can then come from anywhere.")
def pagination_dedup(c):
    batch = c.ingest_search_pages(query="q", region="US", language="en", pages=[
        [{"video_id": "v1"}, {"video_id": "v2"}],
        [{"video_id": "v2"}, {"video_id": "v3"}],
    ])
    return len(batch["video_ids"]) == 3


@case("a batch that lost a page says so",
      "Quota exhaustion and transient failure truncate results silently — the response "
      "is simply shorter. A short batch that does not know it is short becomes evidence "
      "of a small market rather than evidence of a failed collection.")
def partial_failure_is_declared(c):
    batch = c.ingest_search_pages(query="q", region="US", language="en",
                                  pages=[[{"video_id": "v1"}], None, [{"video_id": "v3"}]])
    return batch.get("complete") is False and batch.get("failed_pages") == [1]


@case("the collector never emits a rate",
      "Velocity belongs to G02, computed from raw counters it can audit. A rate emitted "
      "here cannot be recomputed or challenged downstream — it arrives as a fact. Every "
      "number this layer produces should be one the platform said.")
def no_derived_rates(c):
    o = c.record_observation(video_id="v1", observed_at="2026-08-20T10:00:00Z", views=5000)
    forbidden = {"velocity", "views_per_hour", "vph", "breakout_score", "confidence",
                 "acceleration"}
    return not (forbidden & set(o))


def main():
    print("  G03 COLLECTOR CONTRACT — 10 cases, written before the implementation")
    if not HAVE:
        print("  collector.py not present. The contract, in order:\n")
        for i, (name, why, _) in enumerate(CASES, 1):
            print(f"  {i:2d}. {name}")
            for line in _wrap(why):
                print(f"      {line}")
            print()
        print("  Run again when collector.py lands and these become attacks.")
        return 0

    results = []
    for name, _why, fn in CASES:
        try:
            results.append(_ok(name, fn(collector.Collector())))
        except Exception as exc:
            results.append(_ok(name, False, f"{type(exc).__name__}: {exc}"))
    failed = results.count(False)
    print(f"  {len(results) - failed}/{len(results)} held, {failed} open")
    return 1 if failed else 0


def _wrap(text, width=86):
    words, line, out = text.split(), "", []
    for w in words:
        if len(line) + len(w) + 1 > width:
            out.append(line); line = w
        else:
            line = f"{line} {w}".strip()
    if line:
        out.append(line)
    return out


if __name__ == "__main__":
    sys.exit(main())
