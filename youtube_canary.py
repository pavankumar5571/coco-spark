"""Bounded live read canary for adapter -> collector; never claims opportunity from n=1."""
from __future__ import annotations

import argparse
import json
import os

import adapter
from collector import Collector


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--query", default="preschool counting song")
    p.add_argument("--region", default="US")
    p.add_argument("--language", default="en")
    p.add_argument("--max-results", type=int, default=3)
    args = p.parse_args()
    key = os.environ.get("AIS_YOUTUBE_API_KEY") or os.environ.get("YOUTUBE_API_KEY")
    if not key:
        raise SystemExit("AIS_YOUTUBE_API_KEY or YOUTUBE_API_KEY is required")
    transport = adapter.YouTubeTransport(key, max_results=args.max_results)
    batch = adapter.search(query=args.query, region=args.region, language=args.language,
                           transport=transport, retries=0)
    ids = batch["video_ids"]
    stats = adapter.fetch_statistics(ids, transport=transport)
    details = adapter.fetch_details(ids, transport=transport)
    collector = Collector()
    for video_id in ids:
        collector.record_discovery(video_id=video_id, query=batch["query"],
                                   region=batch["region"], language=batch["language"])
        row = stats.get(video_id)
        if row and row["views"] is not None:
            collector.record_observation(
                video_id=video_id, observed_at=row["observed_at"], views=row["views"],
                likes=row["likes"], comments=row["comments"])
    report = {
        "kind": "YOUTUBE_LIVE_CANARY_V1", "complete": batch["complete"],
        "query": batch["query"], "region": batch["region"],
        "language": batch["language"], "api_calls": transport.calls,
        "searched_ids": len(ids), "statistics_rows": len(stats),
        "details_rows": len(details), "unreturned_statistics": adapter.last_unreturned_ids(),
        "first_observation_only": True, "opportunity_proof_allowed": False,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    if not batch["complete"] or not ids or not stats or not details:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
