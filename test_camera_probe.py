"""Ground-truth controls for the camera probe. Zero paid calls, zero network.

The previous detector was trusted because it produced numbers, and its numbers were
wrong in a way nobody could see: it called a deliberate rigid zoom "unstable" and a
session then promoted that into "the room is deforming". A measuring instrument gets to
become a production gate only after it has been shown a motion whose truth we already
know and has recovered it.

Every fixture here is SYNTHESISED, so the ground truth is not an opinion.
"""
from __future__ import annotations

import math, sys, tempfile
from pathlib import Path

import numpy as np
from PIL import Image

import camera_probe as cp

TMP = Path(tempfile.mkdtemp())
N = 512


def world(seed=7):
    """A textured 'room': enough structure for tiles to lock onto, no repeating pattern
    that would let a wrong alignment score as well as the right one."""
    rng = np.random.default_rng(seed)
    a = rng.random((N // 8, N // 8)).astype(np.float32)
    im = Image.fromarray((a * 255).astype(np.uint8)).resize((N, N), Image.BICUBIC)
    a = np.asarray(im, dtype=np.float32) / 255.0
    yy, xx = np.mgrid[0:N, 0:N]
    a += 0.25 * np.sin(xx / 37.0) + 0.25 * np.cos(yy / 29.0)          # low-freq structure
    a[N // 3: N // 3 + 60, N // 5: N // 5 + 90] = 0.05                # hard landmarks
    a[2 * N // 3: 2 * N // 3 + 40, 3 * N // 5: 3 * N // 5 + 120] = 0.95
    a = (a - a.min()) / (a.max() - a.min())
    return a


def save(arr, name):
    p = TMP / name
    Image.fromarray((np.clip(arr, 0, 1) * 255).astype(np.uint8)).save(p)
    return p


def transform(a, scale=1.0, tx=0.0, ty=0.0):
    """Render the world as seen by a camera that zoomed by `scale` and panned by (tx,ty).

    Inverse-mapped so the OUTPUT grid is filled exactly, which keeps ground truth exact
    rather than approximate.
    """
    yy, xx = np.mgrid[0:N, 0:N].astype(np.float32)
    c = N / 2.0
    sx = (xx - c - tx) / scale + c
    sy = (yy - c - ty) / scale + c
    x0 = np.clip(sx.astype(int), 0, N - 2); y0 = np.clip(sy.astype(int), 0, N - 2)
    fx = np.clip(sx - x0, 0, 1); fy = np.clip(sy - y0, 0, 1)
    return (a[y0, x0] * (1 - fx) * (1 - fy) + a[y0, x0 + 1] * fx * (1 - fy)
            + a[y0 + 1, x0] * (1 - fx) * fy + a[y0 + 1, x0 + 1] * fx * fy)


def particles(a, n=140, seed=3):
    """Bright motes over a static world — the defect that made us doubt the room."""
    rng = np.random.default_rng(seed)
    out = a.copy()
    for _ in range(n):
        x, y = rng.integers(6, N - 6, 2)
        r = rng.integers(2, 5)
        yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
        m = (xx ** 2 + yy ** 2) <= r * r
        out[y - r:y + r + 1, x - r:x + r + 1][m] = 1.0
    return out


def character(a, cx, cy):
    """An opaque blob that MOVES while the camera does not. A camera detector that cannot
    ignore a moving subject will report every performance as a camera move."""
    out = a.copy()
    yy, xx = np.mgrid[0:N, 0:N]
    m = ((xx - cx) ** 2 / 3600.0 + (yy - cy) ** 2 / 8100.0) <= 1.0
    out[m] = 0.15
    return out


def nonrigid(a, amp=9.0):
    """Genuine non-rigid warp: different regions move differently. No single camera model
    can explain this, and the honest answer is to refuse rather than fit something."""
    yy, xx = np.mgrid[0:N, 0:N].astype(np.float32)
    sx = xx + amp * np.sin(yy / 45.0)
    sy = yy + amp * np.cos(xx / 51.0)
    x0 = np.clip(sx.astype(int), 0, N - 2); y0 = np.clip(sy.astype(int), 0, N - 2)
    return a[y0, x0]


CASES = []


def case(name, first, last, want, check=None):
    CASES.append((name, first, last, want, check))


def main():
    w = world()

    case("perfectly static -> STATIC",
         save(w, "s_a.png"), save(w.copy(), "s_b.png"), cp.STATIC)

    case("known +2% push-in -> RIGID_ZOOM, recovered within 0.6%",
         save(w, "z_a.png"), save(transform(w, scale=1.02), "z_b.png"), cp.RIGID_ZOOM,
         lambda m: abs(m["zoom_pct"] - 2.0) < 0.6 and m["direction"] == "PUSH_IN")

    case("known -2.5% pull-back -> RIGID_ZOOM, direction PULL_BACK",
         save(w, "p_a.png"), save(transform(w, scale=0.975), "p_b.png"), cp.RIGID_ZOOM,
         lambda m: m["direction"] == "PULL_BACK")

    case("known 8px pan -> RIGID_TRANSLATION, recovered within 2px",
         save(w, "t_a.png"), save(transform(w, tx=8.0), "t_b.png"), cp.RIGID_TRANSLATION,
         lambda m: abs(m["shift_px"] - 8.0) < 2.0)

    case("pan AND zoom together -> RIGID_AFFINE, both recovered",
         save(w, "a_a.png"), save(transform(w, scale=1.02, tx=7.0), "a_b.png"),
         cp.RIGID_AFFINE,
         lambda m: abs(m["zoom_pct"] - 2.0) < 0.8 and abs(m["shift_px"] - 7.0) < 2.5)

    case("MOVING CHARACTER over a static world -> still STATIC",
         save(character(w, 200, 300), "c_a.png"),
         save(character(w, 260, 300), "c_b.png"), cp.STATIC)

    case("PARTICLES over a static world -> still STATIC",
         save(particles(w, seed=1), "pa_a.png"),
         save(particles(w, seed=2), "pa_b.png"), cp.STATIC)

    case("character AND particles, static camera -> still STATIC",
         save(particles(character(w, 200, 300), seed=1), "cp_a.png"),
         save(particles(character(w, 260, 300), seed=2), "cp_b.png"), cp.STATIC)

    case("genuine NON-RIGID warp -> must REFUSE to call it a camera move",
         save(w, "n_a.png"), save(nonrigid(w), "n_b.png"),
         cp.NON_RIGID_OR_UNEXPLAINED)

    case("featureless flat frame -> INSUFFICIENT_CONFIDENCE, not a confident STATIC",
         save(np.full((N, N), 0.5, np.float32), "f_a.png"),
         save(np.full((N, N), 0.5, np.float32), "f_b.png"), cp.INSUFFICIENT_CONFIDENCE)

    fails = []
    for name, fa, fb, want, check in CASES:
        m = cp.measure(fa, fb)
        got = m["verdict"]
        ok = got == want and (check is None or check(m))
        detail = (f"zoom={m.get('zoom_pct')}% shift={m.get('shift_px')}px "
                  f"resid={m.get('residual_px')} tiles={m.get('tiles')}")
        print(f"  {'PASS' if ok else 'FAIL'}  {name:62} {got:26} {detail}")
        if not ok:
            fails.append(name)

    print(f"\n  {len(CASES) - len(fails)}/{len(CASES)} ground-truth controls hold")
    if fails:
        print("  DETECTOR NOT TRUSTWORTHY — do not use as a release gate")
        sys.exit(1)
    print("  camera probe recovers known motion and refuses what it cannot explain")


if __name__ == "__main__":
    main()
