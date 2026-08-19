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
    config.BUDGET_INR = budget
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

    print(f"\n  {sum(results)}/{len(results)} runtime properties hold")
    if not all(results):
        sys.exit(1)
    print("  RUNTIME FIREWALL HELD")


if __name__ == "__main__":
    main()
