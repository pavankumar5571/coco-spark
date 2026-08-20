"""Measure what the camera ACTUALLY did between two frames, and say how sure we are.

Built after a detector that aligned tiles by TRANSLATION ONLY scored a deliberate, rigid
6% push-in as "unstable" — the same score as footage we then wrongly concluded was a
deforming room. A zoom moves every tile away from the centre: incoherent as translations,
perfectly coherent as one scale change. The lesson is not "add a zoom term". It is that a
detector which can only express one kind of motion will describe every other kind as chaos.

So this returns a TYPED verdict, never the word "unstable", and it reports the residual it
could not explain rather than folding that into a single score.
"""
from __future__ import annotations

import numpy as np
from PIL import Image

STATIC = "STATIC"
RIGID_TRANSLATION = "RIGID_TRANSLATION"
RIGID_ZOOM = "RIGID_ZOOM"
RIGID_AFFINE = "RIGID_AFFINE"                    # zoom AND translation together
NON_RIGID_OR_UNEXPLAINED = "NON_RIGID_OR_UNEXPLAINED"
INSUFFICIENT_CONFIDENCE = "INSUFFICIENT_CONFIDENCE"

# A camera contract says "locked static". These are the tolerances at which we are willing
# to call a measured motion nothing. Below them the motion is smaller than our own
# measurement noise, so claiming it exists would be over-reading the instrument.
STATIC_ZOOM = 0.004        # 0.4% scale
STATIC_SHIFT = 1.5         # pixels
MIN_TILES = 12             # fewer usable tiles than this and we decline to answer
MAX_RESIDUAL = 1.6         # px of unexplained motion before we stop calling it rigid


def _gray(im, size=512):
    im = im.convert("L")
    im = im.resize((size, size), Image.LANCZOS)
    return np.asarray(im, dtype=np.float32) / 255.0


def _tile_shift(a, b, cx, cy, half, search):
    """Best integer (dx,dy) aligning b's tile onto a's, by minimum absolute difference.

    Returns None when the tile is featureless — a flat wall matches everywhere, and a
    confident answer from a flat tile is noise wearing a number.
    """
    ref = a[cy - half:cy + half, cx - half:cx + half]
    if ref.std() < 0.015:
        return None
    best, bd = None, np.inf
    for dy in range(-search, search + 1):
        for dx in range(-search, search + 1):
            y0, x0 = cy - half + dy, cx - half + dx
            if y0 < 0 or x0 < 0 or y0 + 2 * half > b.shape[0] or x0 + 2 * half > b.shape[1]:
                continue
            d = np.abs(b[y0:y0 + 2 * half, x0:x0 + 2 * half] - ref).mean()
            if d < bd:
                bd, best = d, (dx, dy)
    return best


def _solve(X, Y, DX, DY):
    """One uniform scale and one translation, solved jointly. Shared by the robust loop and
    the final fit so they can never diverge."""
    A = np.zeros((2 * len(X), 3))
    A[:len(X), 0] = X; A[:len(X), 1] = 1.0
    A[len(X):, 0] = Y; A[len(X):, 2] = 1.0
    rhs = np.concatenate([DX, DY])
    (k, tx, ty), *_ = np.linalg.lstsq(A, rhs, rcond=None)
    return float(k), float(tx), float(ty)


def measure(first_png, last_png, grid=7, half=34, search=22):
    """Fit ONE similarity transform (uniform scale + translation) to the tile field.

    A zoom about the frame centre predicts displacement proportional to distance FROM that
    centre. Solving scale and translation together in one least-squares means a push-in and
    a pan cannot be mistaken for each other, and whatever the model cannot explain stays
    visible as a residual instead of being absorbed into a verdict.
    """
    a, b = _gray(Image.open(first_png)), _gray(Image.open(last_png))
    n = a.shape[0]
    c = n / 2.0
    xs, ys, dxs, dys = [], [], [], []
    step = n // (grid + 1)
    for gy in range(1, grid + 1):
        for gx in range(1, grid + 1):
            cx, cy = gx * step, gy * step
            if cx - half - search < 0 or cy - half - search < 0:
                continue
            if cx + half + search > n or cy + half + search > n:
                continue
            s = _tile_shift(a, b, cx, cy, half, search)
            if s is None:
                continue
            xs.append(cx - c); ys.append(cy - c); dxs.append(s[0]); dys.append(s[1])

    if len(xs) < MIN_TILES:
        return {"verdict": INSUFFICIENT_CONFIDENCE, "tiles": len(xs),
                "why": "too few textured tiles to fit a camera model"}

    X = np.array(xs); Y = np.array(ys); DX = np.array(dxs, float); DY = np.array(dys, float)
    # ROBUST FIT. A character that moves while the camera does not drags its own tiles and
    # nothing else. A plain least-squares lets that minority pull the global model and then
    # reports the leftover as "non-rigid", i.e. it blames the room for the actor. So fit,
    # measure each tile against the fit, discard the tiles that disagree most, and refit on
    # what survives. The discarded ones are not noise — they are independent motion, and
    # counting them is how we tell a moving subject from a deforming world.
    keep = np.ones(len(X), bool)
    for _ in range(3):
        k_, tx_, ty_ = _solve(X[keep], Y[keep], DX[keep], DY[keep])
        rx = DX - (k_ * X + tx_)
        ry = DY - (k_ * Y + ty_)
        per_tile = np.hypot(rx, ry)
        med = np.median(per_tile[keep])
        thresh = max(1.2, 3.0 * max(med, 0.3))
        new_keep = per_tile <= thresh
        if new_keep.sum() < MIN_TILES or (new_keep == keep).all():
            break
        keep = new_keep
    moving_tiles = int((~keep).sum())
    # If a LOT of tiles disagree with any single camera model, it is not one actor moving.
    if moving_tiles > 0.45 * len(X):
        return {"verdict": NON_RIGID_OR_UNEXPLAINED, "tiles": len(X),
                "independent_tiles": moving_tiles,
                "why": "too much of the frame moves independently for one camera model"}
    X, Y, DX, DY = X[keep], Y[keep], DX[keep], DY[keep]
    # dx = k*X + tx ; dy = k*Y + ty   with a single shared k, so scale is not fitted
    # independently per axis — a real lens zoom is uniform, and letting the axes disagree
    # would let a stretch masquerade as a zoom.
    k, tx, ty = _solve(X, Y, DX, DY)
    rhs = np.concatenate([DX, DY])
    pred = np.concatenate([k * X + tx, k * Y + ty])
    resid = rhs - pred
    resid_px = float(np.sqrt((resid ** 2).mean()))
    raw_px = float(np.sqrt((rhs ** 2).mean()))

    zoom = float(k)                      # +ve => features move outward => PUSH IN
    shift = float(np.hypot(tx, ty))
    explained = 0.0 if raw_px < 1e-6 else max(0.0, 1.0 - (resid_px ** 2) / (raw_px ** 2))

    out = {"tiles": len(X), "independent_tiles": moving_tiles,
           "zoom": round(zoom, 5), "zoom_pct": round(zoom * 100, 3),
           "shift_px": round(shift, 3), "residual_px": round(resid_px, 3),
           "raw_px": round(raw_px, 3), "explained": round(explained, 3)}

    if resid_px > MAX_RESIDUAL and explained < 0.5:
        out["verdict"] = NON_RIGID_OR_UNEXPLAINED
        out["why"] = ("one uniform scale plus translation cannot account for the tile "
                      "field; the motion is not a single rigid camera move")
        return out

    zoomed = abs(zoom) > STATIC_ZOOM
    shifted = shift > STATIC_SHIFT
    if zoomed and shifted:
        out["verdict"] = RIGID_AFFINE
    elif zoomed:
        out["verdict"] = RIGID_ZOOM
    elif shifted:
        out["verdict"] = RIGID_TRANSLATION
    else:
        out["verdict"] = STATIC
    out["direction"] = ("PUSH_IN" if zoom > 0 else "PULL_BACK") if zoomed else None
    return out


def honours_locked_static(m):
    """A 'Locked static camera' contract is met only by STATIC. Anything else is a breach,
    including motion small enough to look tidy in a table."""
    return m.get("verdict") == STATIC
