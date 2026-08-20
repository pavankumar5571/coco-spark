"""What a YouTube API adapter must survive, specified before one exists.

G03 records losslessly and G02 judges what it is handed. G04 is the only layer that ever
speaks to YouTube — so it is the only place where a real-world response becomes our data,
and every lie it tells is permanent. Neither module below can detect a translation error:
they will faithfully preserve and carefully judge whatever this layer invents.

Written against an INTERFACE, so the adapter is built to the contract rather than the
contract being fitted to the adapter. Runs today and prints the spec; becomes an attack
when `adapter.py` lands.

    python test_adapter_contract.py

THE RULE: the adapter reports what it ASKED and what it WAS TOLD, separately, and marks
everything it did not receive as not received. It converts. It does not complete.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

try:
    import adapter                                        # noqa: F401
    HAVE = True
except ModuleNotFoundError:
    adapter = None
    HAVE = False

CASES = []


def case(name, why):
    def wrap(fn):
        CASES.append((name, why, fn))
        return fn
    return wrap


def _ok(name, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name:54s}{'' if cond else '  <-- ' + detail}")
    return bool(cond)


# --------------------------------------------------------------------------------------
# PAGINATION

@case("a nextPageToken that points backwards terminates",
      "A token loop is not hypothetical: mirrors, proxies and quota errors all return "
      "stale tokens, and a paginator that trusts the token it was handed will fetch "
      "forever. It must track tokens it has already followed and stop, recording that it "
      "stopped for that reason rather than reporting a complete traversal.")
def token_loop_terminates(a, T):
    t = T(pages={None: (["v1"], "tokA"), "tokA": (["v2"], "tokA")})
    batch = a.search(query="q", region="US", language="en", transport=t)
    return t.calls <= 4 and batch.get("complete") is not True


@case("overlapping pages do not double-count a video",
      "Search pagination overlaps routinely. G03 deduplicates what it is given, but the "
      "adapter must not report a page count or an item count that includes the "
      "duplicate, or every downstream total is inflated by the overlap.")
def overlap_not_double_counted(a, T):
    t = T(pages={None: (["v1", "v2"], "tokA"), "tokA": (["v2", "v3"], None)})
    batch = a.search(query="q", region="US", language="en", transport=t)
    return sorted(batch["video_ids"]) == ["v1", "v2", "v3"]


@case("more than 50 ids becomes several calls and one result",
      "videos.list caps at 50 ids per request. 120 ids must become three calls whose "
      "results merge with nothing lost and nothing repeated. Silently truncating at 50 "
      "would make every large query look like a small market — the same failure shape as "
      "a truncated batch, arriving through arithmetic instead of an error.")
def batching_over_fifty(a, T):
    ids = [f"v{i}" for i in range(120)]
    t = T(stats={i: {"viewCount": "10"} for i in ids})
    out = a.fetch_statistics(ids, transport=t)
    return len(out) == 120 and t.calls == 3


# --------------------------------------------------------------------------------------
# WHAT CAME BACK, AND WHAT DID NOT

@case("ids that came back from search but not from statistics are recorded, not dropped",
      "A video can be deleted or made private between the search call and the statistics "
      "call. Returning 47 rows for 50 ids is normal. Dropping the three silently makes "
      "them never have existed; substituting zeros makes them dead. Both are claims. The "
      "adapter must say which ids it asked for and did not receive.")
def missing_from_statistics(a, T):
    t = T(stats={"v1": {"viewCount": "10"}, "v3": {"viewCount": "30"}})
    out = a.fetch_statistics(["v1", "v2", "v3"], transport=t)
    return "v2" not in out and "v2" in a.last_unreturned_ids()


@case("an absent likeCount is absent, not zero",
      "statistics omits likeCount entirely when likes are hidden — the key is missing, "
      "not null. A parser using .get(key, 0) turns every hidden-like video into a video "
      "nobody liked, and G03 will faithfully preserve that zero forever.")
def absent_like_count(a, T):
    t = T(stats={"v1": {"viewCount": "1000"}})            # no likeCount key at all
    out = a.fetch_statistics(["v1"], transport=t)
    return out["v1"]["likes"] is None and out["v1"]["views"] == 1000


@case("a malformed duration or timestamp is not silently repaired",
      "PT0S, an empty string and a missing publishedAt all appear in real responses. A "
      "duration that fails to parse must not become 0 and a timestamp that fails must "
      "not become now() — a fabricated publishedAt makes an old video look new, which is "
      "precisely the incumbent-masquerading-as-breakout case G02 exists to refuse.")
def malformed_values(a, T):
    t = T(details={"v1": {"duration": "not-a-duration", "publishedAt": ""}})
    out = a.fetch_details(["v1"], transport=t)
    return out["v1"]["duration_seconds"] is None and out["v1"]["published_at"] is None


# --------------------------------------------------------------------------------------
# WHAT WE ASKED

@case("provenance is what we asked, never what the response echoed",
      "region and language are REQUEST parameters. If the adapter reads them back off the "
      "response, a server that ignores or normalises them silently rewrites our "
      "provenance, and G02's query-family check starts comparing fields the API chose.")
def provenance_is_the_request(a, T):
    t = T(pages={None: (["v1"], None)}, echo_region="IN", echo_language="hi")
    batch = a.search(query="q", region="US", language="en", transport=t)
    return batch["region"] == "US" and batch["language"] == "en"


@case("one clock read per batch, not one per item",
      "If each item is timestamped as it is parsed, a 120-id batch spreads across seconds "
      "or minutes of wall clock. G03's minimum-interval and same-instant rules then see "
      "drift that describes our parsing loop rather than the platform. One observation "
      "moment per collection.")
def one_clock_per_batch(a, T):
    t = T(stats={f"v{i}": {"viewCount": "10"} for i in range(60)})
    out = a.fetch_statistics([f"v{i}" for i in range(60)], transport=t)
    return len({row["observed_at"] for row in out.values()}) == 1


# --------------------------------------------------------------------------------------
# WHEN IT GOES WRONG

@case("a failure mid-pagination becomes a failed page, not a short success",
      "Quota exhaustion and 5xx arrive in the middle of a traversal. The adapter must "
      "hand G03 the failed page index so the batch is refused, because G03 fails closed "
      "on exactly that signal. An adapter that catches the error and returns what it has "
      "converts a broken collection into evidence of a small market.")
def failure_becomes_failed_page(a, T):
    t = T(pages={None: (["v1"], "tokA"), "tokA": RuntimeError("quota")})
    batch = a.search(query="q", region="US", language="en", transport=t)
    return batch.get("complete") is False and batch.get("failed_pages")


@case("a retry that succeeds is recorded as a retry",
      "If attempt two overwrites attempt one, the record says collection succeeded "
      "cleanly. It did not. Whether a number required three attempts is evidence about "
      "the collection, and it is the only warning we will get before quota runs out "
      "mid-run for real.")
def retry_is_visible(a, T):
    t = T(pages={None: [RuntimeError("500"), (["v1"], None)]})
    batch = a.search(query="q", region="US", language="en", transport=t, retries=1)
    return batch.get("attempts", 1) > 1 or batch.get("retried_pages")


@case("no test can reach the network",
      "Every case here injects a transport. The adapter must have no path that opens a "
      "socket when one is supplied, and asking for the network without a transport must "
      "raise rather than quietly construct a real client. A battle suite that COULD hit "
      "YouTube is a suite that will, on somebody's machine, against somebody's quota.")
def no_network_without_transport(a, T):
    try:
        a.search(query="q", region="US", language="en")
        return False
    except Exception as exc:
        return "transport" in str(exc).lower() or isinstance(exc, TypeError)


def main():
    print("  G04 ADAPTER CONTRACT — 11 cases, specified before the implementation")
    if not HAVE:
        print("  adapter.py not present. The contract, in order:\n")
        for i, (name, why, _) in enumerate(CASES, 1):
            print(f"  {i:2d}. {name}")
            for line in _wrap(why):
                print(f"      {line}")
            print()
        print("  A fake transport must be supplied by the implementation as adapter.FakeTransport,")
        print("  accepting pages / stats / details / echo_* and counting calls.")
        return 0
    results = []
    for name, _why, fn in CASES:
        try:
            results.append(_ok(name, fn(adapter, adapter.FakeTransport)))
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
