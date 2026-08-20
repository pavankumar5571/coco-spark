"""Undo an unrequested rigid zoom, non-destructively.

Three of six paid clips crept inward on shots whose contract says "Locked static camera".
A rigid zoom is invertible, so the footage is correctable rather than dead — but the
correction produces a NEW artifact with its own bytes, its own provenance and its own QC
verdict. The original is never touched, because a verdict that judged one set of pixels
cannot speak for a different set.

STABILISED TO THE FINAL FRAMING, deliberately. The camera pushed IN, so the last frame
sees the least; only that region exists in every frame. Matching the end means the LAST
FRAME PASSES THROUGH UNCHANGED, which preserves the tail that downstream shots inherit or
reference. Matching the start would require inventing border that was never photographed.
"""
from __future__ import annotations

import json, subprocess, tempfile
from pathlib import Path

import numpy as np
from PIL import Image

import camera_probe as cp

STABILISER_VERSION = "1"


def _probe_at(clip, t, first_png, tmp):
    p = tmp / f"t{t}.png"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(t), "-i", str(clip),
                    "-vframes", "1", str(p)], check=True)
    return cp.measure(str(first_png), str(p))


def fit_zoom_rate(clip, seconds, tmp, samples=7):
    """Fit zoom-per-second through the origin.

    Through the origin on purpose: at t=0 the frame IS the reference, so any fitted
    intercept would be measurement noise promoted to a fact.
    """
    f0 = tmp / "f0.png"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(clip), "-vframes", "1",
                    str(f0)], check=True)
    ts, zs = [], []
    for i in range(1, samples + 1):
        t = round(seconds * i / (samples + 1), 3)
        m = _probe_at(clip, t, f0, tmp)
        if m.get("zoom") is None:
            continue
        ts.append(t); zs.append(m["zoom"])
    ts, zs = np.array(ts), np.array(zs)

    def fit(deg):
        # every term passes through the origin: at t=0 the frame IS the reference, so an
        # intercept would be measurement noise promoted to a fact
        A = np.stack([ts ** (d + 1) for d in range(deg)], axis=1)
        coef, *_ = np.linalg.lstsq(A, zs, rcond=None)
        pred = A @ coef
        ss_res = float(((zs - pred) ** 2).sum())
        ss_tot = float(((zs - zs.mean()) ** 2).sum())
        return coef, (1.0 - ss_res / ss_tot if ss_tot > 0 else 1.0), ss_res

    c1, r1, e1 = fit(1)
    c2, r2_, e2 = fit(2)
    # Take the curve ONLY when it explains materially more. A linear creep and an
    # accelerating creep are different physical behaviours, and fitting a quadratic to
    # straight data would just chase noise.
    if e2 < 0.5 * e1:
        return {"coef": c2.tolist(), "degree": 2}, r2_, list(zip(ts.tolist(), zs.tolist()))
    return {"coef": c1.tolist(), "degree": 1}, r1, list(zip(ts.tolist(), zs.tolist()))


def stabilise(clip, dest, seconds, fps=24):
    tmp = Path(tempfile.mkdtemp())
    model, r2, samples = fit_zoom_rate(clip, seconds, tmp)
    coef = model["coef"]
    zoom_at = lambda t: sum(c * (t ** (d + 1)) for d, c in enumerate(coef))
    total = zoom_at(seconds)

    frames = tmp / "in"; frames.mkdir()
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(clip),
                    str(frames / "%05d.png")], check=True)
    files = sorted(frames.glob("*.png"))
    n = len(files)
    out = tmp / "out"; out.mkdir()
    W, H = Image.open(files[0]).size

    for i, f in enumerate(files):
        t = seconds * i / max(1, n - 1)
        z = zoom_at(t)
        # bring THIS frame to the END framing: crop the centre by how much zoom is still
        # to come, then rescale. At the last frame the factor is 1 and nothing changes.
        k = (1.0 + z) / (1.0 + total)
        cw, ch = W * k, H * k
        x0, y0 = (W - cw) / 2.0, (H - ch) / 2.0
        im = Image.open(f).crop((round(x0), round(y0), round(x0 + cw), round(y0 + ch)))
        im.resize((W, H), Image.LANCZOS).save(out / f.name)

    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-framerate", str(fps),
                    "-i", str(out / "%05d.png"), "-c:v", "libx264", "-preset", "slow",
                    "-crf", "16", "-pix_fmt", "yuv420p", str(dest)], check=True)
    return {"stabiliser": STABILISER_VERSION, "model": model,
            "total_zoom_pct": round(total * 100, 3), "linearity_r2": round(r2, 4),
            "frames": n, "samples": samples,
            "stabilised_to": "FINAL_FRAMING",
            "note": "last frame unchanged; opening framing cropped by the total zoom"}
