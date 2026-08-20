"""Lossless, provider-neutral observation collector for opportunity evidence.

This module deliberately performs no network calls and derives no market metrics. API
adapters translate provider responses into these record methods; G02 computes rates later
from eligible raw counters.
"""
from __future__ import annotations

from datetime import datetime, timezone


MINIMUM_INTERVAL_SECONDS = 3600


def _instant(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("observed_at must include a timezone")
    return parsed.astimezone(timezone.utc)


class ObservationConflict(ValueError):
    """The platform supplied different counters for one video at one instant."""


class Collector:
    def __init__(self, minimum_interval_seconds: int = MINIMUM_INTERVAL_SECONDS):
        if minimum_interval_seconds <= 0:
            raise ValueError("minimum_interval_seconds must be positive")
        self.minimum_interval_seconds = minimum_interval_seconds
        self._channels: dict[str, dict] = {}
        self._raw: dict[str, dict[datetime, dict]] = {}
        self._discoveries: dict[str, dict[tuple[str, str, str], dict]] = {}

    def record_channel(self, *, channel_id: str, title: str,
                       hidden_subscriber_count: bool = False,
                       subscriber_count: int | None = None,
                       channel_owner_hint: str | None = None) -> dict:
        if not channel_id:
            raise ValueError("channel_id is required")
        if hidden_subscriber_count:
            subscriber_count = None
        elif subscriber_count is not None and subscriber_count < 0:
            raise ValueError("subscriber_count cannot be negative")
        record = {"channel_id": channel_id, "title": title,
                  "hidden_subscriber_count": bool(hidden_subscriber_count),
                  "subscriber_count": subscriber_count,
                  # This is accepted only when an upstream authority explicitly supplies it.
                  "channel_owner_hint": channel_owner_hint}
        self._channels[channel_id] = record
        return dict(record)

    def record_discovery(self, *, video_id: str, query: str, region: str,
                         language: str) -> dict:
        if not all((video_id, query, region, language)):
            raise ValueError("video_id, query, region and language are required")
        record = {"video_id": video_id, "query": query,
                  "region": region.upper(), "language": language.casefold()}
        key = (record["query"], record["region"], record["language"])
        self._discoveries.setdefault(video_id, {})[key] = record
        return dict(record)

    def discoveries(self, video_id: str) -> list[dict]:
        return [dict(x) for x in self._discoveries.get(video_id, {}).values()]

    def record_observation(self, *, video_id: str, observed_at: str | datetime,
                           views: int, likes: int | None = None,
                           comments: int | None = None) -> dict:
        when = _instant(observed_at)
        if views < 0 or likes is not None and likes < 0 or comments is not None and comments < 0:
            raise ValueError("public counters cannot be negative")
        record = {"video_id": video_id,
                  "observed_at": when.isoformat().replace("+00:00", "Z"),
                  "views": views, "likes": likes, "comments": comments,
                  "below_minimum_interval": False}
        by_time = self._raw.setdefault(video_id, {})
        if when in by_time:
            existing = by_time[when]
            comparable = {k: existing[k] for k in ("views", "likes", "comments")}
            incoming = {k: record[k] for k in ("views", "likes", "comments")}
            if comparable != incoming:
                raise ObservationConflict(
                    f"conflicting counters for {video_id} at {record['observed_at']}")
            return dict(existing)
        eligible_times = [t for t, item in by_time.items()
                          if not item["below_minimum_interval"]]
        if eligible_times:
            elapsed = (when - max(eligible_times)).total_seconds()
            if 0 < elapsed < self.minimum_interval_seconds:
                record["below_minimum_interval"] = True
        by_time[when] = record
        return dict(record)

    def raw_snapshots(self, video_id: str) -> list[dict]:
        by_time = self._raw.get(video_id, {})
        return [dict(by_time[t]) for t in sorted(by_time)]

    def snapshots(self, video_id: str) -> list[dict]:
        return [x for x in self.raw_snapshots(video_id)
                if not x["below_minimum_interval"]]

    def ingest_search_pages(self, *, query: str, region: str, language: str,
                            pages: list[list[dict] | None]) -> dict:
        video_ids = []
        seen = set()
        failed_pages = []
        for index, page in enumerate(pages):
            if page is None:
                failed_pages.append(index)
                continue
            for item in page:
                video_id = item.get("video_id")
                if not video_id:
                    continue
                self.record_discovery(video_id=video_id, query=query,
                                      region=region, language=language)
                if video_id not in seen:
                    seen.add(video_id)
                    video_ids.append(video_id)
        complete = not failed_pages
        return {"query": query, "region": region.upper(), "language": language.casefold(),
                "video_ids": video_ids, "complete": complete,
                "failed_pages": failed_pages,
                # Partial data remains auditable but cannot prove absence or market size.
                "usable_for_opportunity": complete}
