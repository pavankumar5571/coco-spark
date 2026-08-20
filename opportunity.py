"""Pure, auditable YouTube evidence -> production opportunity selection.

No network, database, provider, character, episode or topic assumptions live here. The
collector supplies preserved observations and peer velocities; this module refuses to turn
one popular video or one query match into a market claim.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import statistics
from pathlib import Path


def tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.casefold()))


def matches(title: str, candidate: dict) -> tuple[bool, list[str]]:
    folded = " ".join(title.casefold().split())
    title_tokens = tokens(title)
    reasons = []
    for phrase in candidate.get("match_any_phrases", []):
        if " ".join(phrase.casefold().split()) in folded:
            reasons.append(f"phrase:{phrase}")
    required = set(candidate.get("match_all_terms", []))
    if required and {x.casefold() for x in required} <= title_tokens:
        reasons.append("all_terms:" + ",".join(sorted(required)))
    return bool(reasons), reasons


def velocity(snapshots: list[dict]) -> float | None:
    if len(snapshots) < 2:
        return None
    points = sorted(snapshots, key=lambda x: x["observed_hour"])
    older, newer = points[-2:]
    elapsed = newer["observed_hour"] - older["observed_hour"]
    if elapsed <= 0 or newer["views"] < older["views"]:
        return None
    return (newer["views"] - older["views"]) / elapsed


def _median_positive(values: list[float]) -> float | None:
    clean = [float(x) for x in values if x >= 0 and math.isfinite(x)]
    return statistics.median(clean) if len(clean) >= 3 else None


def score_video(video: dict) -> dict:
    vph = velocity(video["snapshots"])
    channel_base = _median_positive(video.get("channel_peer_velocities", []))
    cohort_base = _median_positive(video.get("cohort_peer_velocities", []))
    valid = vph is not None and channel_base is not None and cohort_base is not None
    if not valid:
        return {"velocity_per_hour": vph, "breakout_score": 50.0,
                "confidence": 0.0, "valid_evidence": False}
    channel_ratio = vph / max(1.0, channel_base)
    cohort_ratio = vph / max(1.0, cohort_base)
    # A 1x baseline is neutral (50). Evidence must beat both baselines to cross 65.
    signal = (math.log2(max(channel_ratio, 0.125))
              + math.log2(max(cohort_ratio, 0.125))) / 2
    score = max(0.0, min(100.0, 50.0 + 18.0 * signal))
    time_confidence = min(1.0, (len(video["snapshots"]) - 1) / 2)
    peer_confidence = min(1.0, (len(video["channel_peer_velocities"])
                               + len(video["cohort_peer_velocities"])) / 10)
    confidence = time_confidence * (0.55 + 0.45 * peer_confidence)
    return {"velocity_per_hour": round(vph, 4),
            "channel_ratio": round(channel_ratio, 4),
            "cohort_ratio": round(cohort_ratio, 4),
            "breakout_score": round(score, 4),
            "confidence": round(confidence, 4), "valid_evidence": True}


def select_opportunity(payload: dict) -> dict:
    candidate = payload["candidate"]
    matched = []
    for video in payload["videos"]:
        is_match, mapping = matches(video["title"], candidate)
        if not is_match:
            continue
        scored = score_video(video)
        matched.append({"video_id": video["video_id"],
                        "channel_id": video["channel_id"], "title": video["title"],
                        "query": video["query"], "region": video["region"],
                        "language": video["language"], "mapping": mapping, **scored})

    valid = [x for x in matched if x["valid_evidence"]]
    channels = {x["channel_id"] for x in valid}
    strong = [x for x in valid if x["breakout_score"] >= 65 and x["confidence"] >= 0.6]
    enough = len(valid) >= 3 and len(channels) >= 3 and len(strong) / len(valid) >= 2 / 3
    median_score = statistics.median(x["breakout_score"] for x in valid) if valid else 0
    median_confidence = statistics.median(x["confidence"] for x in valid) if valid else 0
    proven = enough and median_score >= 65 and median_confidence >= 0.6

    marker_votes = {"SONG": 0, "EPISODE": 0}
    for item in valid:
        title_tokens = tokens(item["title"])
        for mode in marker_votes:
            markers = {x.casefold() for x in candidate.get("mode_markers", {}).get(mode, [])}
            marker_votes[mode] += len(title_tokens & markers)
    mode = "UNPROVEN"
    if proven:
        ordered = sorted(marker_votes.items(), key=lambda x: (-x[1], x[0]))
        if ordered[0][1] > 0 and ordered[0][1] >= ordered[1][1] + 2:
            mode = ordered[0][0]

    reasons = []
    if len(valid) < 3: reasons.append("fewer_than_3_valid_videos")
    if len(channels) < 3: reasons.append("fewer_than_3_independent_channels")
    if valid and len(strong) / len(valid) < 2 / 3: reasons.append("weak_cluster_breakout")
    if proven and mode == "UNPROVEN": reasons.append("format_evidence_ambiguous")
    if not valid: reasons.append("no_repeated_peer_supported_observations")

    return {
        "kind": "YOUTUBE_OPPORTUNITY_EVIDENCE_V1",
        "candidate_id": candidate["candidate_id"],
        "status": "OPPORTUNITY_PROVEN" if proven else "OPPORTUNITY_UNPROVEN",
        "selection": mode,
        "metrics": {"matched_videos": len(matched), "valid_videos": len(valid),
                    "independent_channels": len(channels), "strong_videos": len(strong),
                    "median_breakout_score": round(median_score, 4),
                    "median_confidence": round(median_confidence, 4)},
        "mode_votes": marker_votes, "reasons": reasons, "evidence": matched,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    result = select_opportunity(json.loads(args.input.read_text(encoding="utf-8")))
    rendered = json.dumps(result, indent=2, sort_keys=True)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
