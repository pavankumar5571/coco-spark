"""Adversarial fixtures against the opportunity selector, written by the other agent.

Codex owns opportunity.py. These cases were designed from its CONTRACT rather than from
its code path, then run against the code — the point is to find inputs it accepts that it
should refuse, not to re-walk the branches it already tests.

Each case states the attack, the input that mounts it, and what a correct engine must do.
A case that FAILS here is a false positive route into paid production.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import opportunity as opp


def _snap(pairs):
    return [{"observed_hour": h, "views": v} for h, v in pairs]


def _video(vid, channel, title, snaps, chan_peers, cohort_peers,
           query="five little stars", region="US", language="en"):
    return {"video_id": vid, "channel_id": channel, "title": title,
            "snapshots": _snap(snaps), "channel_peer_velocities": chan_peers,
            "cohort_peer_velocities": cohort_peers,
            "query": query, "region": region, "language": language}


CANDIDATE = {"candidate_id": "counting_stars_bedtime",
             "match_any_phrases": ["little stars"],
             "mode_markers": {"SONG": ["song", "rhyme"], "EPISODE": ["story", "episode"]}}


def _ok(name, condition, detail=""):
    print(f"  {'PASS' if condition else 'FAIL'}  {name:56s}{'' if condition else '  <-- ' + detail}")
    return bool(condition)


def zero_peers_manufacture_a_breakout():
    """ATTACK: report the peers as zero and any velocity becomes a maximum breakout.

    _median_positive accepts 0.0 as a legitimate peer velocity, then both ratios are
    clamped by max(1.0, base) to divide by 1. A modest 64 views/hour becomes a ratio of
    64 against BOTH baselines, the log2 signal reaches 6, and the score saturates at 100.

    A peer set of all zeros is not evidence that a video is exceptional. It is evidence
    that peer collection failed, and it should invalidate the comparison rather than win
    it. This is the cheapest false positive in the module: it needs no traffic at all.
    """
    videos = [_video(f"v{i}", f"c{i}", "Five Little Stars Song",
                     [(0, 0), (1, 32), (2, 96)], [0.0] * 5, [0.0] * 5)
              for i in range(3)]
    r = opp.select_opportunity({"candidate": CANDIDATE, "videos": videos})
    scores = [e["breakout_score"] for e in r["evidence"]]
    return _ok("all-zero peer velocities do not prove a breakout",
               r["status"] != "OPPORTUNITY_PROVEN",
               f"status={r['status']} scores={scores}")


def confidence_counts_snapshots_velocity_never_reads():
    """ATTACK: confidence rises with snapshots that cannot affect the measurement.

    velocity() uses points[-2:] and nothing else. time_confidence uses
    (len(snapshots)-1)/2 and saturates at three. So two videos with IDENTICAL final
    pairs — one observed twice, one observed five times with a flat history — report
    different confidence for the same measured velocity.

    Confidence claimed from data the estimate never consumed is not confidence.
    """
    late_spike = _video("a", "c1", "Five Little Stars Song",
                        [(0, 1000), (1, 1000), (2, 1000), (3, 1000), (4, 1400)],
                        [10.0] * 3, [10.0] * 3)
    just_two = _video("b", "c2", "Five Little Stars Song",
                      [(3, 1000), (4, 1400)], [10.0] * 3, [10.0] * 3)
    a, b = opp.score_video(late_spike), opp.score_video(just_two)
    same_velocity = a["velocity_per_hour"] == b["velocity_per_hour"]
    return _ok("equal velocity does not get unequal confidence",
               same_velocity and a["confidence"] == b["confidence"],
               f"same vph={same_velocity} conf {a['confidence']} vs {b['confidence']}")


def one_query_is_not_a_market():
    """ATTACK: every matched video came back from a single search phrase.

    query/region/language are preserved on every evidence row and never read by any
    decision. A cluster discovered by ONE query is a property of the phrase the analyst
    typed, not of demand: the search engine was asked for these videos and duly returned
    them. Independent channels do not fix it, because the same query surfaced all of them.

    The module's own audit standard required 'preserved query, region, language' — but
    preserving a field and checking it are different things.
    """
    videos = [_video(f"v{i}", f"c{i}", "Five Little Stars Song",
                     [(0, 1000), (1, 1200), (2, 1400)], [10.0] * 5, [10.0] * 5,
                     query="five little stars")            # identical for all three
              for i in range(3)]
    r = opp.select_opportunity({"candidate": CANDIDATE, "videos": videos})
    queries = {e["query"] for e in r["evidence"]}
    flagged = any("quer" in x for x in r["reasons"])
    return _ok("a single-query cluster is flagged, not proven",
               len(queries) > 1 or flagged or r["status"] != "OPPORTUNITY_PROVEN",
               f"one query {queries} -> {r['status']}, reasons={r['reasons']}")


def three_channels_one_operator():
    """ATTACK: channel_id is trusted as proof of independence.

    Three ids is the whole independence test. A single operator running a network of
    brand channels — routine in kids content — satisfies it by uploading the same song
    three times. Nothing in the payload carries channel provenance, so the engine cannot
    tell a market from a publisher.

    This one may be unfixable inside this module; if so the CONTRACT must say that
    independence is asserted upstream and unverified here, rather than implying it is
    proven by a count of distinct strings.
    """
    videos = [_video(f"v{i}", f"c{i}", "Five Little Stars Song",
                     [(0, 1000), (1, 1200), (2, 1400)], [10.0] * 5, [10.0] * 5)
              for i in range(3)]
    for v in videos:
        v["channel_owner_hint"] = "same-network"          # ignored by the engine
    r = opp.select_opportunity({"candidate": CANDIDATE, "videos": videos})
    honest = (r["status"] != "OPPORTUNITY_PROVEN"
              or any("independen" in x for x in r["reasons"]))
    return _ok("common ownership is detected or declared unverifiable", honest,
               f"{r['status']} with 3 same-network channels, reasons={r['reasons']}")


def marker_gaming_is_self_confirming():
    """ATTACK: the same title text both matches the candidate and picks the format.

    matches() selects videos by phrase, then mode_markers counts tokens in those same
    titles. A candidate author who puts 'song' in the match terms AND in SONG's markers
    guarantees the format, because every video that could be counted was selected for
    containing it. The vote is over a population the marker itself defined.
    """
    rigged = dict(CANDIDATE, match_any_phrases=["stars song"],
                  mode_markers={"SONG": ["song"], "EPISODE": ["story"]})
    videos = [_video(f"v{i}", f"c{i}", "Little Stars Song for Kids",
                     [(0, 1000), (1, 1200), (2, 1400)], [10.0] * 5, [10.0] * 5)
              for i in range(3)]
    r = opp.select_opportunity({"candidate": rigged, "videos": videos})
    return _ok("format is not decided by the phrase that did the matching",
               r["selection"] == "UNPROVEN" or r["status"] != "OPPORTUNITY_PROVEN",
               f"selection={r['selection']} votes={r['mode_votes']}")


def main():
    print("  G02 ADVERSARIAL ATTACK — designed against the contract, run against fb711ce")
    results = [
        zero_peers_manufacture_a_breakout(),
        confidence_counts_snapshots_velocity_never_reads(),
        one_query_is_not_a_market(),
        three_channels_one_operator(),
        marker_gaming_is_self_confirming(),
    ]
    failed = results.count(False)
    print(f"  {len(results) - failed}/{len(results)} held, {failed} FALSE-POSITIVE ROUTES OPEN")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
