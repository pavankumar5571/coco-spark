"""Battle test for C01: the controls that stand between us and an unprovable claim.

Every check here is OFFLINE. No key, no network, no cost — the credential is a set of
strings, because that is all scope_preflight ever reasoned about. If any of these needs a
token to run, the control is coupled to the thing it is supposed to police.

Four properties, one per defect this module actually shipped with:

    SCOPE          a credential that cannot prove an operation is refused, at acquisition
    DERIVATION     the requested scope set cannot drift from the declared operations
    ENV            a re-consented token REPLACES its predecessor, and takes effect
    DURATION       YouTube's stated duration is parsed, never assumed equal to ours

The third is the one worth keeping forever: the bug was not that the token failed to
write, it was that it wrote and did not take effect, while the flow printed success.
"""
import io, sys, tempfile, contextlib
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

import youtube_upload as yt
import release

UPLOAD = "https://www.googleapis.com/auth/youtube.upload"
READONLY = "https://www.googleapis.com/auth/youtube.readonly"


def _ok(name, cond):
    print(f"  {'PASS' if cond else 'FAIL'}  {name:58s} {'' if cond else '<-- '}")
    return bool(cond)


def _quiet(fn, *a, **kw):
    """scope_preflight prints its table. Run it without the noise."""
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a, **kw)


def scope_properties():
    out = []

    # The credential this project shipped with, and the one enterprise-ai-yt still holds.
    upload_only = {UPLOAD}
    both = {UPLOAD, READONLY}

    out.append(_ok("upload-only credential cannot satisfy verify",
                   [op for op, _ in _quiet(yt.scope_preflight, upload_only)] == ["verify"]))
    out.append(_ok("upload-only credential CAN satisfy upload",
                   _quiet(yt.scope_preflight, upload_only, ["upload"]) == []))
    out.append(_ok("a full grant satisfies every declared operation",
                   _quiet(yt.scope_preflight, both) == []))
    out.append(_ok("an empty grant fails every declared operation",
                   len(_quiet(yt.scope_preflight, set())) == len(yt.OPERATION_SCOPES)))
    # An unrelated scope must not be mistaken for coverage. Google returns scopes we did
    # not ask for often enough that substring reasoning would eventually pass a bad token.
    out.append(_ok("an unrelated scope is not coverage",
                   len(_quiet(yt.scope_preflight, {"https://www.googleapis.com/auth/youtube"})) == 2))

    # DERIVATION. If SCOPE is ever hand-edited back into a literal, the consent request and
    # the preflight would disagree and the disagreement would be invisible: consent would
    # ask for less than the preflight demands, and every future consent would be refused.
    out.append(_ok("requested SCOPE is derived from the declared operations",
                   set(yt.SCOPE.split()) == set(yt.OPERATION_SCOPES.values())))
    out.append(_ok("verify's declared scope grants no ability to change anything",
                   yt.OPERATION_SCOPES["verify"].endswith("youtube.readonly")))
    return out


def env_properties():
    """The defect: appending a re-consented token left the STALE one in force.

    _load_env_file uses setdefault, so the first line for a key wins. A flow that appends
    reports success, writes the right bytes, and changes nothing — the credential is
    replaced everywhere except in effect. So the assertion is not "the file contains the
    new token", it is "the loader returns the new token".
    """
    out = []
    tmp = Path(tempfile.mkdtemp())
    env = tmp / ".env"
    env.write_text("YOUTUBE_REFRESH_TOKEN=STALE\nOTHER=keep\n", encoding="utf-8")

    yt._write_env("YOUTUBE_REFRESH_TOKEN", "FRESH", path=str(env))
    lines = [l for l in env.read_text(encoding="utf-8").splitlines() if l.strip()]

    out.append(_ok("exactly one line for the rewritten key",
                   sum(l.startswith("YOUTUBE_REFRESH_TOKEN=") for l in lines) == 1))
    out.append(_ok("unrelated keys survive the rewrite", "OTHER=keep" in lines))

    # The property that matters: load it the way the code really loads it.
    import os
    os.environ.pop("YOUTUBE_REFRESH_TOKEN", None)
    yt._load_env_file(str(env))
    out.append(_ok("the loader returns the NEW token, not the stale one",
                   os.environ.get("YOUTUBE_REFRESH_TOKEN") == "FRESH"))
    os.environ.pop("YOUTUBE_REFRESH_TOKEN", None)

    # A real export must still win: that is the documented contract of _load_env_file.
    os.environ["YOUTUBE_REFRESH_TOKEN"] = "EXPORTED"
    yt._load_env_file(str(env))
    out.append(_ok("an exported value still beats the file",
                   os.environ.get("YOUTUBE_REFRESH_TOKEN") == "EXPORTED"))
    os.environ.pop("YOUTUBE_REFRESH_TOKEN", None)

    # UTF-8 is pinned, so a non-ASCII value round-trips identically on every machine.
    # It did not: the release path used the platform default, UTF-8 in the Codespace and
    # cp1252 on Windows, and the manifest was unreadable to the tool that owns it.
    yt._write_env("NOTE", "Coco — starlight", path=str(env))
    out.append(_ok("non-ASCII round-trips regardless of platform locale",
                   "Coco — starlight" in env.read_text(encoding="utf-8")))

    import shutil
    shutil.rmtree(tmp, ignore_errors=True)
    return out


def duration_properties():
    """YouTube states its own duration and it is not ours. Parse it; never assume it."""
    out = []
    cases = [("PT13S", 13.0), ("PT1M2S", 62.0), ("PT1H1M1S", 3661.0),
             ("PT2H", 7200.0), ("P1DT30S", 86430.0)]
    out.append(_ok("ISO 8601 durations parse across every unit",
                   all(release._iso8601_s(s) == v for s, v in cases)))
    # Absent or malformed input must be inert, not an exception: verify's job is to RECORD
    # what the platform said, and it must still record the rest if this one field is odd.
    out.append(_ok("absent or unparseable duration is inert, not fatal",
                   release._iso8601_s(None) == 0.0 and release._iso8601_s("13 seconds") == 0.0))
    # E01: a 12.000s master came back PT13S. The delta is EVIDENCE, not an error — and our
    # measured media duration stays authoritative for beat maps, assembly and compilations.
    out.append(_ok("E01's observed delta is exactly the one recorded",
                   release._iso8601_s("PT13S") - 12.0 == 1.0))
    return out


def main():
    print("  C01 PUBLISHING AUTHORITY")
    results = scope_properties() + env_properties() + duration_properties()
    if not all(results):
        print(f"  {results.count(False)} FAILED")
        sys.exit(1)
    print(f"  ALL {len(results)} HELD")


if __name__ == "__main__":
    main()
