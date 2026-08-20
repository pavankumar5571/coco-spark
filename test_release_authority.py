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
import contextlib, io, json, sys, tempfile
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
    # CAPABILITY AND POLICY ARE DIFFERENT QUESTIONS, and an earlier version of this test
    # confused them. It asserted the broad .../auth/youtube scope was "unrelated" — but
    # Google documents it as "Manage your YouTube account", a SUPERSET that could very
    # plausibly perform both operations. It is capability-sufficient and policy-refused:
    # we mint least privilege, so a credential carrying more than the declared pair is not
    # the credential we agreed to hold, and scope_preflight is a POLICY check.
    broad = {"https://www.googleapis.com/auth/youtube"}
    out.append(_ok("a broader scope is refused by POLICY, not judged unrelated",
                   len(_quiet(yt.scope_preflight, broad)) == 2))
    out.append(_ok("policy is exact least privilege, not substring containment",
                   all(s in yt.OPERATION_SCOPES.values()
                       for s in yt.SCOPE.split()) and not broad & set(yt.SCOPE.split())))

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


class FakeUploader:
    """Counts external mutations. Any call at all is an irreversible act on YouTube.

    The suite asserts the COUNTER, not the return value. A guard that logs a refusal and
    uploads anyway would pass an assertion about messages and fail this one.
    """
    def __init__(self):
        self.calls = 0
        self.privacies = []

    def __call__(self, video_path, metadata, privacy="private"):
        self.calls += 1
        self.privacies.append(privacy)          # what the PROVIDER was actually told
        return f"FAKEID{self.calls}"


def _episode_dir(root, episode="E99", body=b"pretend master bytes", meta=None):
    d = root / "out" / episode / "release"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{episode}_master.mp4").write_bytes(body)
    (d / "metadata.json").write_text(json.dumps(
        meta if meta is not None else {"title": "T", "made_for_kids": True, "tags": []}),
        encoding="utf-8")
    (d / "private_test_audit.json").write_text(json.dumps({"all_pass": True}), encoding="utf-8")
    return d


def mutation_properties():
    """The guards that stand in front of an irreversible external write.

    Every one of these was written and none was tested, which is the same shape as building
    verify() and minting a credential that defeats it. The duplicate guard turned out to be
    dead on arrival: prepare() overwrote the manifest before upload_private read it.
    """
    import os, shutil
    out = []
    root = Path(tempfile.mkdtemp())
    cwd = os.getcwd()
    real_probe, real_upload, real_scopes = release._probe, yt.upload, yt.granted_scopes
    saved_env = {k: os.environ.get(k) for k in
                 ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN")}
    try:
        os.chdir(root)
        for k in saved_env:
            os.environ[k] = "test-value"          # presence is checked, never the value
        release._probe = lambda p: {"duration": 12.0, "video": {}, "audio": {}}
        yt.granted_scopes = lambda: {UPLOAD, READONLY}

        d = _episode_dir(root)
        manifest = d / "upload_manifest.json"

        fake = FakeUploader(); yt.upload = fake
        vid = release.upload_private("E99")
        out.append(_ok("first upload performs exactly one external call", fake.calls == 1))
        out.append(_ok("the video id is recorded against the bytes",
                       _read(manifest).get("youtube_video_id") == vid))

        # THE REGRESSION. prepare() is documented as touching no network; it must also not
        # destroy what the network already told us.
        release.prepare("E99")
        out.append(_ok("prepare does NOT erase the recorded video id",
                       _read(manifest).get("youtube_video_id") == vid))

        fake2 = FakeUploader(); yt.upload = fake2
        out.append(_ok("second upload of identical bytes REFUSES",
                       _exits(release.upload_private, "E99")))
        out.append(_ok("...and performs ZERO external calls", fake2.calls == 0))

        # Different bytes are a different artifact: not a duplicate, and the old
        # observations must not be inherited by them.
        _episode_dir(root, body=b"different master bytes entirely")
        fake3 = FakeUploader(); yt.upload = fake3
        release.upload_private("E99")
        m = _read(manifest)
        out.append(_ok("different bytes upload, and do not inherit old observations",
                       fake3.calls == 1 and "observed" not in m))
        out.append(_ok("...while the earlier attempt survives in history",
                       [a["youtube_video_id"] for a in m["attempts"]][0] == vid
                       and len(m["attempts"]) == 2))

        # NEGATIVE CONTROLS. Both are the authority guard, and both must fail CLOSED.
        _episode_dir(root, body=b"third distinct master")
        fake4 = FakeUploader(); yt.upload = fake4
        yt.granted_scopes = lambda: {READONLY}                     # upload scope withdrawn
        out.append(_ok("missing upload scope refuses the mutation",
                       _exits(release.upload_private, "E99")))
        out.append(_ok("...and performs ZERO external calls", fake4.calls == 0))

        # PRIVACY IS A SECURITY PROPERTY, NOT A CONVENTION. The command is named
        # upload-private; these three assert the name is load-bearing. This is
        # children's content — the cost of an accidental public upload is not a bug
        # report, and no test previously covered it.
        _episode_dir(root, episode="E97", body=b"public request",
                     meta={"title": "T", "privacy": "public", "made_for_kids": True})
        fakeP = FakeUploader(); yt.upload = fakeP
        yt.granted_scopes = lambda: {UPLOAD, READONLY}
        out.append(_ok("metadata asking for PUBLIC refuses",
                       _exits(release.upload_private, "E97")))
        out.append(_ok("...and performs ZERO external calls", fakeP.calls == 0))

        _episode_dir(root, episode="E96", body=b"no privacy stated",
                     meta={"title": "T", "made_for_kids": True})
        fakeQ = FakeUploader(); yt.upload = fakeQ
        release.upload_private("E96")
        out.append(_ok("metadata omitting privacy sends the provider 'private'",
                       fakeQ.privacies == ["private"]))

        _episode_dir(root, episode="E95", body=b"explicit private",
                     meta={"title": "T", "privacy": "private", "made_for_kids": True})
        fakeR = FakeUploader(); yt.upload = fakeR
        release.upload_private("E95")
        out.append(_ok("the ordinary case sends the provider exactly 'private'",
                       fakeR.privacies == ["private"]))

        # ATTEMPTS ARE APPEND-ONLY. Three uploads of three different masters must leave
        # three records, not the newest one wearing the others' place.
        man95 = root / "out" / "E95" / "release" / "upload_manifest.json"
        for n, body in enumerate([b"second master 95", b"third master 95"], start=2):
            _episode_dir(root, episode="E95", body=body,
                         meta={"title": "T", "privacy": "private", "made_for_kids": True})
            yt.upload = FakeUploader()
            release.upload_private("E95")
        j = _read(man95)
        out.append(_ok("three uploads leave three immutable attempts",
                       [a["attempt_id"] for a in j["attempts"]] ==
                       ["E95-001", "E95-002", "E95-003"]))
        out.append(_ok("every attempt keeps the bytes it was made from",
                       len({a["master_sha256"] for a in j["attempts"]}) == 3))
        out.append(_ok("current_attempt_id points at the newest",
                       j["current_attempt_id"] == "E95-003"))
        out.append(_ok("every attempt records the privacy the provider was told",
                       all(a["privacy_requested"] == "private" for a in j["attempts"])))

        # verify() with no recorded id must refuse LOCALLY. It built a query with
        # id=None and asked YouTube — an invalid deterministic state reaching a provider,
        # the same class as everything else here. Counted, not read from the message.
        reads = {"n": 0}
        def _counted_scopes():
            reads["n"] += 1
            return {UPLOAD, READONLY}
        yt.granted_scopes = _counted_scopes
        _episode_dir(root, episode="E98")
        out.append(_ok("verify with no recorded id refuses locally",
                       _exits(release.verify, "E98")))
        out.append(_ok("...and performs ZERO network reads", reads["n"] == 0))
        yt.granted_scopes = lambda: {READONLY}

        fake5 = FakeUploader(); yt.upload = fake5
        def _revoked():
            raise RuntimeError("invalid_grant: token revoked")
        yt.granted_scopes = _revoked                               # the realistic failure
        raised = False
        try:
            release.upload_private("E99")
        except (RuntimeError, SystemExit):
            raised = True
        out.append(_ok("a revoked credential fails closed", raised))
        out.append(_ok("...and performs ZERO external calls", fake5.calls == 0))
    finally:
        release._probe, yt.upload, yt.granted_scopes = real_probe, real_upload, real_scopes
        for k, v in saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        os.chdir(cwd)
        shutil.rmtree(root, ignore_errors=True)
    return out


def _read(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def _exits(fn, *a):
    """True if the call refused via sys.exit. Silences the refusal message."""
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            fn(*a)
    except SystemExit:
        return True
    return False


def secret_properties():
    """Credentials must not reach an artifact, a log line, or an exception message.

    Not "the manifest looks clean" — the credentials are replaced with sentinels no real
    value could resemble, and stdout, stderr, the written manifest and the text of any
    raised exception are all searched for them. This repository is PUBLIC; a secret that
    reaches a commit here is world-readable within seconds and cannot be un-published.
    """
    import os, shutil
    out = []
    root = Path(tempfile.mkdtemp())
    cwd = os.getcwd()
    real_probe, real_upload, real_scopes = release._probe, yt.upload, yt.granted_scopes
    saved = {k: os.environ.get(k) for k in
             ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN")}
    sentinels = {"YOUTUBE_CLIENT_ID": "SENTINEL-CLIENT-ID-ZZZ1",
                 "YOUTUBE_CLIENT_SECRET": "SENTINEL-CLIENT-SECRET-ZZZ2",
                 "YOUTUBE_REFRESH_TOKEN": "SENTINEL-REFRESH-TOKEN-ZZZ3"}
    try:
        os.chdir(root)
        os.environ.update(sentinels)
        release._probe = lambda p: {"duration": 12.0, "video": {}, "audio": {}}
        yt.granted_scopes = lambda: {UPLOAD, READONLY}
        yt.upload = FakeUploader()
        d = _episode_dir(root, episode="E94")

        so, se, exc = io.StringIO(), io.StringIO(), ""
        try:
            with contextlib.redirect_stdout(so), contextlib.redirect_stderr(se):
                release.prepare("E94")
                release.upload_private("E94")
                release.verify("E94")
        except BaseException as e:                      # SystemExit included, deliberately
            exc = f"{type(e).__name__}: {e}"

        surfaces = {"stdout": so.getvalue(), "stderr": se.getvalue(), "exception": exc,
                    "manifest": (d / "upload_manifest.json").read_text(encoding="utf-8")}
        for name, text in surfaces.items():
            leaked = [k for k, v in sentinels.items() if v in text]
            out.append(_ok(f"no credential value reaches {name}", not leaked))

        # And the inverse: prepare must still ASSERT the credentials are present, or
        # "no secrets found" would be trivially satisfied by never reading them.
        for k in sentinels:
            os.environ.pop(k, None)
        with contextlib.redirect_stdout(io.StringIO()):
            m = release.prepare("E94")
        out.append(_ok("absent credentials are reported as blockers, by NAME only",
                       any("YOUTUBE_REFRESH_TOKEN" in b for b in m["blockers"])))
    finally:
        release._probe, yt.upload, yt.granted_scopes = real_probe, real_upload, real_scopes
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        os.chdir(cwd)
        shutil.rmtree(root, ignore_errors=True)
    return out


def wiring_properties():
    """The seam that actually broke, end to end, without pretending to simulate consent.

    Human approval cannot be faked and should not be. Everything AFTER it can: a token
    response arrives, its granted scopes are checked, the token is stored, the process
    forgets it, and the loader is asked what the credential now is.
    """
    import os, shutil
    out = []
    root = Path(tempfile.mkdtemp())
    env = root / ".env"
    env.write_text("YOUTUBE_REFRESH_TOKEN=OLD_UPLOAD_ONLY\n", encoding="utf-8")

    # A consent that came back short must never reach storage.
    short = {UPLOAD}
    if not _quiet(yt.scope_preflight, short):
        yt._write_env("YOUTUBE_REFRESH_TOKEN", "SHOULD_NOT_BE_STORED", path=str(env))
    out.append(_ok("a short grant never reaches storage",
                   "SHOULD_NOT_BE_STORED" not in env.read_text(encoding="utf-8")))

    # A full grant does, and takes effect in a process that has never seen it.
    full = {UPLOAD, READONLY}
    if not _quiet(yt.scope_preflight, full):
        yt._write_env("YOUTUBE_REFRESH_TOKEN", "NEW_FULL_GRANT", path=str(env))
    os.environ.pop("YOUTUBE_REFRESH_TOKEN", None)
    yt._load_env_file(str(env))
    out.append(_ok("a full grant is stored and is what the loader returns",
                   os.environ.get("YOUTUBE_REFRESH_TOKEN") == "NEW_FULL_GRANT"))
    os.environ.pop("YOUTUBE_REFRESH_TOKEN", None)
    shutil.rmtree(root, ignore_errors=True)
    return out


def main():
    print("  C01 PUBLISHING AUTHORITY")
    results = (scope_properties() + env_properties() + duration_properties()
               + mutation_properties() + secret_properties() + wiring_properties())
    if not all(results):
        print(f"  {results.count(False)} FAILED")
        sys.exit(1)
    print(f"  ALL {len(results)} HELD")


if __name__ == "__main__":
    main()
