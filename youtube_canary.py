"""Bounded live read canary for adapter -> collector; never claims opportunity from n=1."""
from __future__ import annotations

import argparse
import json

import adapter
from collector import Collector
from live_transport import LiveTransport
from opportunity import select_opportunity


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--query", default="preschool counting song")
    p.add_argument("--region", default="US")
    p.add_argument("--language", default="en")
    p.add_argument("--max-results", type=int, default=3)
    args = p.parse_args()
    transport = LiveTransport(max_results=args.max_results)
    batch = adapter.search(query=args.query, region=args.region, language=args.language,
                           transport=transport, retries=0, max_pages=1)
    # A one-page canary is intentionally not a complete market collection. Inspect the
    # preserved retry IDs while keeping the production opportunity handoff empty.
    ids = batch["video_ids"] or batch["retry_video_ids"]
    stats = adapter.fetch_statistics(ids, transport=transport)
    details = adapter.fetch_details(ids, transport=transport)
    collector = Collector()
    evidence_videos = []
    for video_id in ids:
        collector.record_discovery(video_id=video_id, query=batch["query"],
                                   region=batch["region"], language=batch["language"])
        row = stats.get(video_id)
        if row and row["views"] is not None:
            collector.record_observation(
                video_id=video_id, observed_at=row["observed_at"], views=row["views"],
                likes=row["likes"], comments=row["comments"])
        detail = details.get(video_id, {})
        snapshots = collector.snapshots(video_id)
        evidence_videos.append({
            "video_id": video_id, "channel_id": detail.get("channel_id"),
            "title": detail.get("title") or "", "query": batch["query"],
            "region": batch["region"], "language": batch["language"],
            "channel_owner_hint": None,
            "snapshots": [{"observed_hour": index, "views": snap["views"]}
                          for index, snap in enumerate(snapshots)],
            "channel_peer_velocities": [], "cohort_peer_velocities": [],
        })
    evidence = select_opportunity({
        "candidate": {"candidate_id": "live_canary_only",
                      "match_any_phrases": ["song"], "mode_markers": {}},
        "videos": evidence_videos,
    })
    report = {
        "kind": "YOUTUBE_LIVE_CANARY_V1", "complete": batch["complete"],
        "query": batch["query"], "region": batch["region"],
        "language": batch["language"], "api_calls": transport.calls,
        "searched_ids": len(ids), "statistics_rows": len(stats),
        "details_rows": len(details), "unreturned_statistics": adapter.last_unreturned_ids(),
        "metadata_rows_with_title_channel": sum(
            bool(x.get("title") and x.get("channel_id")) for x in details.values()),
        "evidence_status": evidence["status"],
        "evidence_matched_videos": evidence["metrics"]["matched_videos"],
        "termination_reason": batch["termination_reason"],
        "first_observation_only": True, "opportunity_proof_allowed": False,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    bounded_partial = batch["termination_reason"] == "page_limit_reached"
    metadata_complete = all(x.get("title") and x.get("channel_id") for x in details.values())
    if (not (batch["complete"] or bounded_partial) or not ids or not stats or not details
            or not metadata_complete or evidence["status"] != "OPPORTUNITY_UNPROVEN"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
