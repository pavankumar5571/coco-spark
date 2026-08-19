"""Runtime firewall: injects a fake client into the REAL stage functions.

test_firewall.py mutates shot plans and asserts the validator rejects them. That proves
the planning half only. This proves the runtime half by executing stage_portraits,
stage_frames, stage_video and stage_assemble against a counting fake provider, in a
temporary working directory, with artifacts deliberately corrupted.

Two properties, both required:
    invalid deterministic state  ->  ZERO paid calls
    valid cached state           ->  ZERO duplicate paid calls

Offline. No key. No cost.
"""
import json, shutil, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))


class FakeClient:
    """Counts every paid invocation. Any unauthorised call is a firewall breach."""
    def __init__(self):
        self.image_calls, self.video_calls = 0, 0
        outer = self

        class _Models:
            def generate_content(self, **kw):
                outer.image_calls += 1
                return _resp()
            def generate_videos(self, **kw):
                outer.video_calls += 1
                raise RuntimeError("fake provider: video not implemented")
        self.models = _Models()

    @property
    def calls(self):
        return self.image_calls + self.video_calls


def _valid_png():
    """A real 1x1 PNG. An invalid one makes Image.open() throw inside the stage, which
    aborts the loop and makes the harness — not the code — look like a failure."""
    import io
    from PIL import Image as _I
    buf = io.BytesIO(); _I.new("RGB", (8, 8), (10, 20, 30)).save(buf, "PNG")
    return buf.getvalue()


def _resp():
    png = _valid_png()
    class P:  inline_data = type("D", (), {"data": png})()
    class C:  content = type("X", (), {"parts": [P()]})()
    return type("R", (), {"candidates": [C()]})()


def fresh_env(budget):
    """A throwaway working dir with its own ledger and budget."""
    tmp = Path(tempfile.mkdtemp())
    import make, config
    make.OUT = tmp
    make.PORTRAITS = tmp / "portraits"
    make.PORTRAITS.mkdir(parents=True)
    make.LEDGER = tmp / "ledger.json"
    # Tests must not read production briefs. They previously called the real load_ep,
    # so the moment episodes/E01.yaml gained a CAMERA_VARIATION requirement four positive
    # controls started failing against a brief they never meant to assert anything about.
    make.load_ep = lambda eid: {
        "id": eid, "mode": "BEDTIME_STORY", "title": "fixture",
        "location": "cottage_night", "locations": ["cottage_night"],
        "cast": ["coco"], "shots": 1,
        "idea": "Fixture episode for the runtime firewall."}
    config.BUDGET_INR = budget
    config.REQUIRE_CLEAN_TREE = False   # exercising other properties; see the dedicated
                                        # dirty-tree case below
    return tmp, make


def run(name, budget, setup=None, expect_calls=0):
    tmp, make = fresh_env(budget)
    fake = FakeClient()
    make.client = lambda: fake
    try:
        if setup:
            setup(tmp, make)
        make.stage_portraits()
    except SystemExit as e:
        pass
    except Exception:
        pass
    ok = fake.calls == expect_calls
    print(f"  {'PASS' if ok else 'FAIL'}  {name:52s} calls={fake.calls} (want {expect_calls})")
    shutil.rmtree(tmp, ignore_errors=True)
    return ok


# ── frame / video / assembly paths ───────────────────────────────────────────
def _shots():
    import copy
    s = {
        "id": "s01", "cast": ["coco"], "coverage_role": "SUBJECT",
        "focus": {"type": "CHARACTER", "ids": ["coco"]},
        "frame": "f", "motion": "m", "camera": "static",
        "boundary": {"type": "CONTINUOUS"}, "events": [],
        "start_state": {
            "location_id": "cottage_night", "population": ["coco"],
            "characters": {"coco": {"awareness": "AWAKE", "posture": "SITTING_UP",
                                    "zone": "BED"}},
            "props": {},
            "visual": {"camera_setup_id": "A", "composition_id": "CHARACTER:COCO",
                       "shot_size": "MEDIUM", "camera_angle": "EYE_LEVEL"}},
    }
    s["end_state"] = copy.deepcopy(s["start_state"])
    return [s]


def seed_episode(tmp, make, valid_frame=True, valid_clip=False):
    """Build a working episode dir: shots.json, portrait, frame (+ optional clip)."""
    import config, yaml
    d = tmp / "E01"
    for sub in ("frames", "clips", "transitions"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    shots = _shots()
    (d / "shots.json").write_text(json.dumps(shots))

    bible = make.BIBLE
    for key, c in bible["cast"].items():
        dest = make.PORTRAITS / f"{key}.png"
        make.write_atomic(dest, _valid_png())
        (make.PORTRAITS / f"{key}.provenance.json").write_text(json.dumps(
            {"status": "COMPLETE", "sha": make.sha_file(dest),
             "input_hash": make.input_hash(character=c, style=bible["style_lock"],
                 model=config.IMAGE_MODEL, aspect=config.IMAGE_ASPECT)}))

    ep = make.load_ep("E01")
    loc = bible["locations"][(ep.get("locations") or [ep["location"]])[0]]
    f = d / "frames" / "s01.png"
    make.write_atomic(f, _valid_png())
    # Call the REAL identity function. Duplicating the formula here is the same mistake
    # that silently broke preflight: two copies drift the moment the real one changes.
    ref_ids = [("identity", k, make.sha_file(make.PORTRAITS / f"{k}.png"))
               for k in shots[0]["cast"]]
    ih = make.frame_identity(shots[0], bible, loc, ref_ids)
    (d / "frames" / "s01.provenance.json").write_text(json.dumps(
        {"status": "COMPLETE", "sha": make.sha_file(f),
         "input_hash": ih if valid_frame else "0" * 16}))

    if valid_clip:
        c = d / "clips" / "s01.mp4"
        make.write_atomic(c, b"FAKEMP4" * 32)
        (d / "clips" / "s01.provenance.json").write_text(json.dumps(
            {"status": "COMPLETE", "sha": make.sha_file(c),
             "input_hash": make.input_hash(shot=shots[0], frame_sha=make.sha_file(f),
                 model=config.VIDEO_MODEL, res=config.VIDEO_RES,
                 secs=config.VIDEO_SECONDS)}))
    return d


def run_stage(name, stage, budget, setup, expect_calls=0, **stage_kw):
    tmp, make = fresh_env(budget)
    shutil.copytree(ROOT / "episodes", tmp.parent / "eps", dirs_exist_ok=True)
    fake = FakeClient()
    make.client = lambda: fake
    try:
        setup(tmp, make)
        getattr(make, stage)("E01", **stage_kw)
    except SystemExit:
        pass
    except Exception:
        pass
    ok = fake.calls == expect_calls
    print(f"  {'PASS' if ok else 'FAIL'}  {name:52s} calls={fake.calls} (want {expect_calls})")
    shutil.rmtree(tmp, ignore_errors=True)
    return ok


def main():
    results = []

    # 1. budget below the reserved image cost -> provider must never be invoked
    results.append(run("budget below reserved image cost", budget=0.5, expect_calls=0))

    # 2. sufficient budget, nothing cached -> exactly one call per cast member
    import yaml
    n_cast = len(yaml.safe_load((ROOT / "bible.yaml").read_text())["cast"])
    results.append(run("empty cache, funded", budget=10_000, expect_calls=n_cast))

    # 3. valid cached portraits -> ZERO duplicate calls
    def seed_valid(tmp, make):
        import config
        bible = make.BIBLE
        for key, c in bible["cast"].items():
            dest = make.PORTRAITS / f"{key}.png"
            make.write_atomic(dest, _valid_png())
            ih = make.input_hash(character=c, style=bible["style_lock"],
                                 model=config.IMAGE_MODEL, aspect=config.IMAGE_ASPECT)
            (make.PORTRAITS / f"{key}.provenance.json").write_text(json.dumps(
                {"status": "COMPLETE", "input_hash": ih, "sha": make.sha_file(dest)}))
    results.append(run("valid cache -> no duplicate spend", budget=10_000,
                       setup=seed_valid, expect_calls=0))

    # 4. altered checksum -> cache rejected, regenerated
    def tamper(tmp, make):
        seed_valid(tmp, make)
        first = sorted(make.PORTRAITS.glob("*.png"))[0]
        import io
        from PIL import Image as _I
        buf = io.BytesIO(); _I.new("RGB", (8, 8), (99, 99, 99)).save(buf, "PNG")
        first.write_bytes(buf.getvalue())            # valid png, WRONG checksum
    results.append(run("altered portrait checksum -> regenerate", budget=10_000,
                       setup=tamper, expect_calls=1))

    # 5. stale input hash (bible changed) -> cache rejected
    def stale(tmp, make):
        seed_valid(tmp, make)
        for pv in make.PORTRAITS.glob("*.provenance.json"):
            d = json.loads(pv.read_text()); d["input_hash"] = "0" * 16
            pv.write_text(json.dumps(d))
    results.append(run("stale input hash -> regenerate all", budget=10_000,
                       setup=stale, expect_calls=n_cast))

    # 6. provenance missing entirely -> never silently reused
    def no_prov(tmp, make):
        seed_valid(tmp, make)
        for pv in make.PORTRAITS.glob("*.provenance.json"):
            pv.unlink()
    results.append(run("missing provenance -> regenerate all", budget=10_000,
                       setup=no_prov, expect_calls=n_cast))

    # 7. provenance marked incomplete (crashed mid-write) -> not reused
    def partial(tmp, make):
        seed_valid(tmp, make)
        for pv in make.PORTRAITS.glob("*.provenance.json"):
            d = json.loads(pv.read_text()); d["status"] = "PARTIAL"
            pv.write_text(json.dumps(d))
    results.append(run("PARTIAL status -> regenerate all", budget=10_000,
                       setup=partial, expect_calls=n_cast))

    # ── frame path ──────────────────────────────────────────────────────────
    results.append(run_stage("stale frame hash -> no video call", "stage_video", 10_000,
        lambda tmp, mk: seed_episode(tmp, mk, valid_frame=False), 0))

    def bad_checksum(tmp, mk):
        d = seed_episode(tmp, mk)
        (d / "frames" / "s01.png").write_bytes(_valid_png() + b"\x00")
    results.append(run_stage("altered frame checksum -> no video call", "stage_video",
        10_000, bad_checksum, 0))

    def no_frame_prov(tmp, mk):
        d = seed_episode(tmp, mk)
        (d / "frames" / "s01.provenance.json").unlink()
    results.append(run_stage("missing frame provenance -> no video call", "stage_video",
        10_000, no_frame_prov, 0))

    results.append(run_stage("budget below video reservation -> no video call",
        "stage_video", 1.0, lambda tmp, mk: seed_episode(tmp, mk), 0))

    # ── reference integrity: the portrait -> frame dependency ───────────────
    def bad_portrait_sha(tmp, mk):
        seed_episode(tmp, mk)
        first = sorted(mk.PORTRAITS.glob("*.png"))[0]
        first.write_bytes(_valid_png() + b"\x01")     # checksum no longer matches
    results.append(run_stage("altered portrait checksum -> no frame call", "stage_frames",
        10_000, bad_portrait_sha, 0))

    def stale_portrait_prov(tmp, mk):
        seed_episode(tmp, mk)
        for pv in mk.PORTRAITS.glob("*.provenance.json"):
            j = json.loads(pv.read_text()); j["input_hash"] = "0" * 16
            pv.write_text(json.dumps(j))
    results.append(run_stage("stale portrait provenance -> no frame call", "stage_frames",
        10_000, stale_portrait_prov, 0))

    def portrait_swapped(tmp, mk):
        """Same bible, same model — but the portrait BYTES changed. The dependent frame
        must go stale, because its identity authority is different."""
        d = seed_episode(tmp, mk)
        import config
        key = "coco"
        dest = mk.PORTRAITS / f"{key}.png"
        import io
        from PIL import Image as _I
        buf = io.BytesIO(); _I.new("RGB", (8, 8), (1, 2, 3)).save(buf, "PNG")
        mk.write_atomic(dest, buf.getvalue())
        (mk.PORTRAITS / f"{key}.provenance.json").write_text(json.dumps(
            {"status": "COMPLETE", "sha": mk.sha_file(dest),
             "input_hash": mk.input_hash(character=mk.BIBLE["cast"][key],
                 style=mk.BIBLE["style_lock"], model=config.IMAGE_MODEL,
                 aspect=config.IMAGE_ASPECT)}))
    results.append(run_stage("portrait replaced -> dependent frame regenerates",
        "stage_frames", 10_000, portrait_swapped, 1))

    results.append(run_stage("CONTROL current refs + missing frame -> ONE image call",
        "stage_frames", 10_000,
        lambda tmp, mk: (seed_episode(tmp, mk),
                         (tmp / "E01" / "frames" / "s01.png").unlink()), 1))

    results.append(run_stage("CONTROL same frame + same refs -> no duplicate image call",
        "stage_frames", 10_000, lambda tmp, mk: seed_episode(tmp, mk), 0))

    results.append(run_stage("budget below planner reservation -> no planner call",
        "stage_plan", 0.5, lambda tmp, mk: seed_episode(tmp, mk), 0))

    # ── tail integrity, proven with a locally-made mp4, no Veo required ──────
    def stale_tail(tmp, mk):
        """s02 would inherit s01's tail. The tail is valid for the ORIGINAL clip; then the
        clip changes. The stale tail must not be consumed — s02 regenerates instead."""
        import copy
        d = seed_episode(tmp, mk, valid_clip=True)
        shots = json.loads((d / "shots.json").read_text())
        s2 = copy.deepcopy(shots[0]); s2["id"] = "s02"
        shots.append(s2)
        (d / "shots.json").write_text(json.dumps(shots))
        clip = d / "clips" / "s01.mp4"
        tail = d / "transitions" / "s01_LAST.png"
        mk.write_atomic(tail, _valid_png())
        (d / "transitions" / "s01_LAST.provenance.json").write_text(json.dumps(
            {"status": "COMPLETE", "sha": mk.sha_file(tail),
             "input_hash": mk.input_hash(source_clip_sha=mk.sha_file(clip),
                                         extractor="ffmpeg-sseof-0.1-v1")}))
        clip.write_bytes(b"DIFFERENTMP4" * 32)   # source changed; tail now orphaned
    # s01 is cached and current, so exactly one call: s02, generated rather than
    # inheriting the orphaned tail.
    results.append(run_stage("source clip changed -> FAIL CLOSED, no substitute frame",
        "stage_frames", 10_000, stale_tail, 0))

    # CONTROL. Without this every "0 calls" result above could be passing vacuously —
    # a stage that exits early for an unrelated reason also makes zero calls.
    results.append(run_stage("CONTROL valid frame + funded -> exactly one video call",
        "stage_video", 10_000, lambda tmp, mk: seed_episode(tmp, mk), 1))

    results.append(run_stage("CONTROL valid clip cached -> no duplicate video call",
        "stage_video", 10_000,
        lambda tmp, mk: seed_episode(tmp, mk, valid_clip=True), 0))

    # ── clip / assembly path ────────────────────────────────────────────────
    def stale_clip(tmp, mk):
        d = seed_episode(tmp, mk, valid_clip=True)
        pv = d / "clips" / "s01.provenance.json"
        j = json.loads(pv.read_text()); j["input_hash"] = "0" * 16
        pv.write_text(json.dumps(j))
    results.append(run_stage("stale clip -> refuse to assemble", "stage_assemble",
        10_000, stale_clip, 0))

    def no_clip_prov(tmp, mk):
        d = seed_episode(tmp, mk, valid_clip=True)
        (d / "clips" / "s01.provenance.json").unlink()
    results.append(run_stage("clip without provenance -> refuse to assemble",
        "stage_assemble", 10_000, no_clip_prov, 0))

    # ── ChatGPT's A-D: inheritance identity + truncated-context regression ────
    def two_shot(tmp, mk, break_tail=False, bad_prev_hash=False):
        """s01 rendered with a tail; s02 would INHERIT it (identical material+visual)."""
        import copy, config
        d = seed_episode(tmp, mk, valid_clip=True)
        shots = json.loads((d / "shots.json").read_text())
        s2 = copy.deepcopy(shots[0]); s2["id"] = "s02"
        shots.append(s2)
        (d / "shots.json").write_text(json.dumps(shots))
        clip = d / "clips" / "s01.mp4"
        tail = d / "transitions" / "s01_LAST.png"
        mk.write_atomic(tail, _valid_png())
        (d / "transitions" / "s01_LAST.provenance.json").write_text(json.dumps(
            {"status": "COMPLETE", "sha": mk.sha_file(tail),
             "input_hash": mk.input_hash(source_clip_sha=mk.sha_file(clip),
                                         extractor="ffmpeg-sseof-0.1-v1")}))
        if break_tail:
            mk.write_atomic(tail, _valid_png() + b"\x02")     # tail bytes changed
        if bad_prev_hash:
            pv = d / "frames" / "s01.provenance.json"
            j = json.loads(pv.read_text()); j["input_hash"] = "0" * 16
            pv.write_text(json.dumps(j))
        return d

    # A. s02 inherits from a valid tail -> free, zero paid calls
    results.append(run_stage("A inherited frame from valid tail -> zero image calls",
        "stage_frames", 10_000, lambda tmp, mk: two_shot(tmp, mk), 0))

    # B. inherited frame must go stale when the SOURCE TAIL changes
    def inherited_then_tail_changes(tmp, mk):
        d = two_shot(tmp, mk)
        import make as _m
        _m.stage_frames("E01")                     # produce the inherited s02
        tail = d / "transitions" / "s01_LAST.png"
        mk.write_atomic(tail, _valid_png() + b"\x03")   # source pixels now different
    results.append(run_stage("B source tail changed -> FAIL CLOSED, no substitute frame",
        "stage_frames", 10_000, inherited_then_tail_changes, 0))

    # C. tail unusable AND predecessor frame stale -> refuse, spend nothing
    # C. A stale predecessor is REGENERATED rather than consumed. The invariant is that
    # no stale reference reaches a paid call, not that the run refuses to proceed.
    # C. s01 is stale and legitimately regenerates; s02 is PREDECESSOR_PIXELS and must
    # NOT substitute independently generated pixels for the tail it was meant to copy.
    results.append(run_stage("C stale predecessor repairs, inheritance fails closed",
        "stage_frames", 10_000,
        lambda tmp, mk: two_shot(tmp, mk, break_tail=True, bad_prev_hash=True), 1))

    # ── ChatGPT's two final cases ────────────────────────────────────────────
    def temporal_stale_tail(tmp, mk):
        """TEMPORAL_REFERENCE (composition changes, so no inheritance): stale tail
        present, predecessor frame valid. The request must use the FRAME, and the
        recorded provenance must say so — the stale tail SHA must appear nowhere."""
        import copy
        d = seed_episode(tmp, mk, valid_clip=True)
        shots = json.loads((d / "shots.json").read_text())
        s2 = copy.deepcopy(shots[0]); s2["id"] = "s02"
        s2["start_state"]["visual"]["shot_size"] = "CLOSE"      # composition changes
        s2["end_state"]["visual"]["shot_size"] = "CLOSE"
        s2["start_state"]["visual"]["camera_setup_id"] = "B"
        s2["end_state"]["visual"]["camera_setup_id"] = "B"
        s2["start_state"]["visual"]["composition_id"] = "CHARACTER:NANA"
        s2["end_state"]["visual"]["composition_id"] = "CHARACTER:NANA"
        shots.append(s2)
        (d / "shots.json").write_text(json.dumps(shots))
        # the tail must be BYTE-DISTINCT from the s01 frame, or their SHAs collide and
        # the assertion cannot tell which artifact was actually referenced
        import io
        from PIL import Image as _I
        buf = io.BytesIO(); _I.new("RGB", (8, 8), (200, 30, 30)).save(buf, "PNG")
        tail = d / "transitions" / "s01_LAST.png"
        mk.write_atomic(tail, buf.getvalue())
        (d / "transitions" / "s01_LAST.provenance.json").write_text(json.dumps(
            {"status": "COMPLETE", "sha": mk.sha_file(tail),
             "input_hash": "0" * 16}))                          # stale tail
        return d

    tmp, mk = fresh_env(10_000)
    fake = FakeClient(); mk.client = lambda: fake
    d = temporal_stale_tail(tmp, mk)
    try:
        mk.stage_frames("E01")
    except Exception:
        pass
    prov = json.loads((d / "frames" / "s02.provenance.json").read_text()) \
        if (d / "frames" / "s02.provenance.json").exists() else {}
    stale_sha = mk.sha_file(d / "transitions" / "s01_LAST.png")
    used = [r for r in prov.get("ref_ids", []) if r[0] == "temporal"]
    ok = (fake.calls == 1
          and used and used[0][2] != stale_sha
          and used[0][2] == mk.sha_file(d / "frames" / "s01.png"))
    print(f"  {'PASS' if ok else 'FAIL'}  "
          f"{'1 stale tail -> provenance records the FRAME, not the tail':52s} "
          f"calls={fake.calls}")
    results.append(ok)
    shutil.rmtree(tmp, ignore_errors=True)

    # the attribution guard itself: a dirty tree must not spend
    tmp, mk = fresh_env(10_000)
    import config
    config.REQUIRE_CLEAN_TREE = True
    fake = FakeClient(); mk.client = lambda: fake
    seed_episode(tmp, mk)
    mk.build_revision = lambda: {"commit": "deadbeef", "dirty": True, "tag": None,
                                 "sources": {}}
    try:
        mk.stage_video("E01")
    except SystemExit:
        pass
    except Exception:
        pass
    ok = fake.calls == 0
    print(f"  {'PASS' if ok else 'FAIL'}  "
          f"{'dirty working tree -> zero paid calls':52s} calls={fake.calls} (want 0)")
    results.append(ok)
    config.REQUIRE_CLEAN_TREE = False
    shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n  {sum(results)}/{len(results)} runtime properties hold")

    # D. targeted video on shot 2 must not treat it as the first shot
    def targeted_second(tmp, mk):
        d = two_shot(tmp, mk)
        import make as _m
        _m.stage_frames("E01")                     # both frames now exist and are current
    results.append(run_stage("D targeted stage_video(only=s02) keeps full context",
        "stage_video", 10_000, targeted_second, 1, only="s02"))

    # the attribution guard itself: a dirty tree must not spend
    tmp, mk = fresh_env(10_000)
    import config
    config.REQUIRE_CLEAN_TREE = True
    fake = FakeClient(); mk.client = lambda: fake
    seed_episode(tmp, mk)
    mk.build_revision = lambda: {"commit": "deadbeef", "dirty": True, "tag": None,
                                 "sources": {}}
    try:
        mk.stage_video("E01")
    except SystemExit:
        pass
    except Exception:
        pass
    ok = fake.calls == 0
    print(f"  {'PASS' if ok else 'FAIL'}  "
          f"{'dirty working tree -> zero paid calls':52s} calls={fake.calls} (want 0)")
    results.append(ok)
    config.REQUIRE_CLEAN_TREE = False
    shutil.rmtree(tmp, ignore_errors=True)

    results += ledger_properties()

    print(f"\n  {sum(results)}/{len(results)} runtime properties hold")
    if not all(results):
        sys.exit(1)
    print("  RUNTIME FIREWALL HELD")


def _ok(name, cond):
    print(f"  {'PASS' if cond else 'FAIL'}  {name:52s} {'' if cond else '<-- '}")
    return bool(cond)


def ledger_properties():
    """Money accounting, isolated from any provider path.

    These guard the two ways a cost ledger silently lies: holding the safety margin
    forever (so every op reads 1.5x its real cost), and losing track of which episode an
    op belonged to (so per-episode spend is unanswerable).
    """
    out = []
    tmp, make = fresh_env(10_000)

    i = make.reserve("video", "clip:E09/s01", 32.0)
    held = make.ledger()["spent_inr"]
    out.append(_ok("reserve holds the safety-margined worst case", abs(held - 48.0) < 1e-6))

    make.settle(i, 32.0)
    L = make.ledger()
    out.append(_ok("settle releases the unused margin, books actual",
                   abs(L["spent_inr"] - 32.0) < 1e-6 and abs(L["ops"][i]["inr"] - 32.0) < 1e-6))
    out.append(_ok("settled op keeps what it originally reserved",
                   abs(L["ops"][i]["reserved"] - 48.0) < 1e-6))

    j = make.reserve("image", "frame:E09/s02", 5.0)
    make.settle(j, None)
    L = make.ledger()
    out.append(_ok("released hold returns the whole reservation",
                   abs(L["spent_inr"] - 32.0) < 1e-6 and L["ops"][j]["state"] == "RELEASED"))
    out.append(_ok("a released op contributes nothing to spend",
                   make.op_spent(L["ops"][j]) == 0.0))

    out.append(_ok("reserve stamps the episode at authorisation time",
                   L["ops"][i]["episode"] == "E09"))

    cases = {("frame:E01/s01", "image"): "E01", ("clip:P01B/s01", "video"): "P01B",
             ("plan:E02", "llm"): "E02", ("portrait:coco", "image"): "SHARED",
             ("frame:s01", "image"): "UNATTRIBUTED"}
    out.append(_ok("episode attribution reads structure, not a name list",
                   all(make.op_episode({"detail": d, "kind": k}) == want
                       for (d, k), want in cases.items())))

    total = sum(make.op_spent(o) for o in L["ops"])
    out.append(_ok("per-op spend reconciles to the ledger total",
                   abs(total - L["spent_inr"]) < 1e-6))

    shutil.rmtree(tmp, ignore_errors=True)
    return out


if __name__ == "__main__":
    main()
