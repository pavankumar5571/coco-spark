"""Bounded live read canary for adapter -> collector; never claims opportunity from n=1."""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path

import adapter
from collector import Collector
from live_transport import LiveTransport
from opportunity import select_opportunity


def evidence_snapshots(snapshots):
    """Preserve real elapsed hours; never turn sequence position into elapsed time."""
    if not snapshots:
        return []
    start = datetime.fromisoformat(snapshots[0]["observed_at"].replace("Z", "+00:00"))
    return [{"observed_hour": (
                datetime.fromisoformat(snap["observed_at"].replace("Z", "+00:00")) - start
             ).total_seconds() / 3600,
             "views": snap["views"]} for snap in snapshots]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--query", default="preschool counting song")
    p.add_argument("--region", default="US")
    p.add_argument("--language", default="en")
    p.add_argument("--max-results", type=int, default=3)
    p.add_argument("--state-db", type=Path, required=True)
    p.add_argument("--refresh-existing", action="store_true",
                   help="skip search and re-observe only IDs already persisted in state-db")
    args = p.parse_args()
    collector = Collector(store_path=args.state_db)
    transport = LiveTransport(max_results=args.max_results)
    if args.refresh_existing:
        ids = collector.observed_video_ids()
        if not ids:
            collector.close()
            raise SystemExit("state DB contains no observation IDs to refresh")
        first_discovery = collector.discoveries(ids[0])
        provenance = first_discovery[0] if first_discovery else {
            "query": args.query, "region": args.region.upper(),
            "language": args.language.casefold()}
        batch = {**provenance, "complete": True,
                 "termination_reason": "existing_ids_only"}
    else:
        batch = adapter.search(query=args.query, region=args.region, language=args.language,
                               transport=transport, retries=0, max_pages=1)
        # A one-page canary is intentionally not a complete market collection. Inspect the
        # preserved retry IDs while keeping the production opportunity handoff empty.
        ids = batch["video_ids"] or batch["retry_video_ids"]
    stats = adapter.fetch_statistics(ids, transport=transport)
    details = adapter.fetch_details(ids, transport=transport)
    unreturned_details = adapter.last_unreturned_detail_ids()
    evidence_videos = []
    for video_id in ids:
        if not args.refresh_existing:
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
            "snapshots": evidence_snapshots(snapshots),
            "channel_peer_velocities": [], "cohort_peer_velocities": [],
        })
    evidence = select_opportunity({
        "candidate": {"candidate_id": "live_canary_only",
                      "match_any_phrases": ["song"], "mode_markers": {}},
        "videos": evidence_videos,
    })
    unreturned_statistics = adapter.last_unreturned_ids()
    observations_complete = len(stats) == len(ids) and not unreturned_statistics
    details_complete = len(details) == len(ids) and not unreturned_details
    report = {
        "kind": "YOUTUBE_LIVE_CANARY_V1",
        "search_complete": batch["complete"] if not args.refresh_existing else None,
        "observations_complete": observations_complete,
        "details_complete": details_complete,
        "query": batch["query"], "region": batch["region"],
        "language": batch["language"], "api_calls": transport.calls,
        "searched_ids": len(ids), "statistics_rows": len(stats),
        "details_rows": len(details), "unreturned_statistics": unreturned_statistics,
        "unreturned_details": unreturned_details,
        "metadata_rows_with_title_channel": sum(
            bool(x.get("title") and x.get("channel_id")) for x in details.values()),
        "evidence_status": evidence["status"],
        "evidence_matched_videos": evidence["metrics"]["matched_videos"],
        "termination_reason": batch["termination_reason"],
        "first_observation_only": all(len(collector.snapshots(i)) < 2 for i in ids),
        "opportunity_proof_allowed": all(len(collector.snapshots(i)) >= 2 for i in ids),
        "persistent_state_db": str(args.state_db),
        # Sanitized transport diagnostics contain endpoint, public query/id prefix and
        # HTTP status only. They never contain the API key or request URL.
        "transport": transport.report(),
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    collector.close()
    bounded_partial = batch["termination_reason"] in {
        "page_limit_reached", "existing_ids_only"}
    metadata_complete = (details_complete and
                         all(x.get("title") and x.get("channel_id")
                             for x in details.values()))
    if (not (batch["complete"] or bounded_partial) or not ids or not stats or not details
            or not observations_complete or not metadata_complete
            or evidence["status"] not in {"OPPORTUNITY_UNPROVEN", "OPPORTUNITY_PROVEN"}):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
