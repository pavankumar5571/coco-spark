"""Bounded live enrichment of persisted video IDs with stated channel metadata."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import adapter
from collector import Collector
from live_transport import LiveTransport


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-db", type=Path, required=True)
    args = parser.parse_args()

    collector = Collector(store_path=args.state_db)
    video_ids = collector.observed_video_ids()
    if not video_ids:
        collector.close()
        raise SystemExit("state DB contains no observed videos")

    transport = LiveTransport()
    details = adapter.fetch_details(video_ids, transport=transport)
    channel_ids = sorted({row.get("channel_id") for row in details.values()
                          if row.get("channel_id")})
    channels = adapter.fetch_channels(channel_ids, transport=transport)
    unreturned_channel_ids = adapter.last_unreturned_channel_ids()
    for channel_id, row in channels.items():
        if row["title"]:
            collector.record_channel(
                channel_id=channel_id, title=row["title"],
                hidden_subscriber_count=row["hidden_subscriber_count"],
                subscriber_count=row["subscriber_count"],
                channel_owner_hint=None)

    complete = (len(details) == len(video_ids) and len(channels) == len(channel_ids)
                and not unreturned_channel_ids
                and all(row.get("title") for row in channels.values()))
    report = {
        "kind": "YOUTUBE_CHANNEL_CANARY_V1",
        "video_ids_requested": len(video_ids),
        "video_details_returned": len(details),
        "channel_ids_requested": len(channel_ids),
        "channels_returned": len(channels),
        "unreturned_channel_ids": unreturned_channel_ids,
        "channels_persisted": len(collector.channels()),
        "complete": complete,
        "persistent_state_db": str(args.state_db),
        "transport": transport.report(),
    }
    collector.close()
    print(json.dumps(report, indent=2, sort_keys=True))
    if not complete or not channel_ids:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
