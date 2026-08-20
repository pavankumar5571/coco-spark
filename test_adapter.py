"""Codex policy and cross-boundary controls for G04."""
import adapter
from collector import Collector


# A token loop is incomplete and the production-shaped field fails closed, while partial
# work remains available exclusively for retry.
t = adapter.FakeTransport(pages={None: (["v1"], "a"), "a": (["v2"], "a")})
batch = adapter.search(query="q", region="us", language="EN", transport=t)
assert batch["complete"] is False and batch["video_ids"] == []
assert batch["retry_video_ids"] == ["v1", "v2"]
assert batch["termination_reason"] == "pagination_token_loop"

# Default policy is three total attempts. Exhaustion is explicit and cannot hand partial
# population into the collector's production field.
t = adapter.FakeTransport(pages={None: [RuntimeError("x"), RuntimeError("x"),
                                        RuntimeError("x")]})
batch = adapter.search(query="q", region="US", language="en", transport=t)
assert batch["attempts"] == 3 and batch["failed_pages"] == [0]
assert batch["video_ids"] == []

# Successful retry remains usable, but its history is retained.
t = adapter.FakeTransport(pages={None: [RuntimeError("x"), (["v1"], None)]})
batch = adapter.search(query="q", region="US", language="en", transport=t)
assert batch["complete"] is True and batch["video_ids"] == ["v1"]
assert batch["attempts"] == 2 and batch["retried_pages"] == [0]
successful_batch = batch

# Page-size and page-count are separate bounds. A one-page canary never follows the token,
# remains unusable for market proof and preserves only retry/inspection IDs.
t = adapter.FakeTransport(pages={None: (["v1"], "a"), "a": (["v2"], None)})
batch = adapter.search(query="q", region="US", language="en", transport=t,
                       retries=0, max_pages=1)
assert t.calls == 1 and batch["complete"] is False and batch["video_ids"] == []
assert batch["retry_video_ids"] == ["v1"]
assert batch["termination_reason"] == "page_limit_reached"

# The accepted collector can ingest the adapter's request provenance without using server
# echoes or manufacturing an owner relationship.
c = Collector()
for video_id in successful_batch["video_ids"]:
    c.record_discovery(video_id=video_id, query=successful_batch["query"],
                       region=successful_batch["region"], language=successful_batch["language"])
assert c.discoveries("v1") == [{"video_id": "v1", "query": "q",
                                "region": "US", "language": "en"}]

# One malformed/negative counter makes only that measurement unknown. Raw provider values
# survive, valid neighbours continue, and no fabricated zero enters G03.
t = adapter.FakeTransport(stats={
    "bad": {"viewCount": "abc", "likeCount": "-5", "commentCount": "1.2e3"},
    "good": {"viewCount": "1200", "likeCount": "12", "commentCount": "3"},
})
rows = adapter.fetch_statistics(["bad", "good"], transport=t)
assert (rows["bad"]["views"], rows["bad"]["likes"], rows["bad"]["comments"]) == (None, None, None)
assert rows["bad"]["raw_statistics"] == {
    "viewCount": "abc", "likeCount": "-5", "commentCount": "1.2e3"}
assert (rows["good"]["views"], rows["good"]["likes"], rows["good"]["comments"]) == (1200, 12, 3)

# Metadata required by G02 crosses the adapter boundary, while the socket-owning transport
# remains a separate explicit module rather than a fallback hidden in adapter.py.
t = adapter.FakeTransport(details={"v": {"title": "Counting Song", "channelId": "channel",
                                                 "duration": "PT1M", "publishedAt": "2026-08-20T00:00:00Z"}})
detail = adapter.fetch_details(["v"], transport=t)["v"]
assert detail["title"] == "Counting Song" and detail["channel_id"] == "channel"
assert not hasattr(adapter, "YouTubeTransport")

# Channel cohorts retain the platform's hidden/null distinction, public zero, and never
# manufacture common ownership from a shared identifier or title.
t = adapter.FakeTransport(channels={
    "hidden": {"title": "Hidden", "hiddenSubscriberCount": True,
               "subscriberCount": "999"},
    "zero": {"title": "New", "hiddenSubscriberCount": False,
             "subscriberCount": "0"},
    "unknown": {"title": "Unknown", "hiddenSubscriberCount": "true",
                "subscriberCount": "5"},
})
channels = adapter.fetch_channels(["hidden", "zero", "unknown", "missing"], transport=t)
assert channels["hidden"]["subscriber_count"] is None
assert channels["hidden"]["hidden_subscriber_count"] is True
assert channels["zero"]["subscriber_count"] == 0
assert channels["zero"]["hidden_subscriber_count"] is False
assert channels["zero"]["channel_owner_hint"] is None
assert channels["unknown"]["hidden_subscriber_count"] is True
assert channels["unknown"]["subscriber_count"] is None
assert "missing" not in channels
assert adapter.last_unreturned_channel_ids() == ["missing"]

# Provider/proxy responses cannot inject IDs outside the request provenance, and every
# fetcher exposes requested rows that did not return.
class InjectingTransport(adapter.FakeTransport):
    def statistics(self, _ids):
        return {"stranger": {"viewCount": "999"}}

    def video_details(self, _ids):
        return {"stranger": {"title": "Wrong"}}

    def channel_details(self, _ids):
        return {"stranger": {"title": "Wrong", "subscriberCount": "999"}}


t = InjectingTransport()
assert adapter.fetch_statistics(["wanted"], transport=t) == {}
assert adapter.last_unreturned_ids() == ["wanted"]
assert adapter.fetch_details(["wanted"], transport=t) == {}
assert adapter.last_unreturned_detail_ids() == ["wanted"]
assert adapter.fetch_channels(["wanted"], transport=t) == {}
assert adapter.last_unreturned_channel_ids() == ["wanted"]

class RaisingTransport(adapter.FakeTransport):
    def statistics(self, _ids): raise RuntimeError("fail")
    def video_details(self, _ids): raise RuntimeError("fail")
    def channel_details(self, _ids): raise RuntimeError("fail")


t = RaisingTransport()
for fetch, missing in [
    (adapter.fetch_statistics, adapter.last_unreturned_ids),
    (adapter.fetch_details, adapter.last_unreturned_detail_ids),
    (adapter.fetch_channels, adapter.last_unreturned_channel_ids),
]:
    try:
        fetch(["new"], transport=t)
    except RuntimeError:
        pass
    else:
        raise AssertionError("transport failure was swallowed")
    assert missing() == []

print("adapter policy controls passed: loop / retries / provenance / malformed counters")
