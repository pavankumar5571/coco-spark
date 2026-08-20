"""Measure a character's approved views, and refuse to name what it measures.

    python assets/design/measure.py --character coco

WHY THIS EXISTS. blender/scaffold.py stages the approved views as reference planes and
stops, because it invents no geometry. Modelling then needs numbers, and the last time
numbers were produced by eye here, a band was reported as "the head is 47% of the figure".
That number was the WAIST — the narrowest point of the front view, nowhere near a neck.

The lesson was not measure more carefully. It was that the measurement was fine and the
NAME was invented. A stylised character has no anatomical landmark a program can find; it
has a silhouette, and a silhouette has extents.

So this reports geometry and no anatomy. A band at 82% of height is called a band at 82%
of height. Whoever models decides what lives there.

WHAT IT MEASURES, per view, from the alpha channel:

    the content bounding box, and the height that box spans
    the width profile at every step of height, as a fraction and in metres
    where the widest band falls, and how wide it is
    the horizontal centre of each band, so a lean or an off-centre feature is visible

METRES COME FROM THE MANIFEST. The same standing_height_m the scaffold stages to, so a
measurement and a reference plane can never disagree about scale. A view the manifest
excludes is measured anyway and marked excluded — an unreadable ORIENTATION does not make
a silhouette unmeasurable, and refusing to look would throw away real information.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
DESIGN = ROOT / "assets" / "design"
ALPHA_FLOOR = 8            # below this an "edge" is anti-aliasing, not silhouette


def load_manifest(character):
    path = DESIGN / character / "manifest.json"
    if not path.exists():
        raise SystemExit(f"  no design manifest for {character!r}: {path}")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if "standing_height_m" not in manifest:
        raise SystemExit(f"  {path} has no standing_height_m; a measurement in metres "
                         f"cannot be invented from a sheet")
    return manifest


def rows_with_content(alpha, width, height):
    """For each row, the first and last opaque pixel, or None for an empty row."""
    spans = []
    for y in range(height):
        base = y * width
        left = right = None
        for x in range(width):
            if alpha[base + x] >= ALPHA_FLOOR:
                if left is None:
                    left = x
                right = x
        spans.append(None if left is None else (left, right))
    return spans


def rows_with_runs(alpha, width, height):
    """For each row, EVERY separate opaque run, not just the outer extent.

    The extent alone is a lie wherever a silhouette is disconnected. An arm held away from
    the body, a gap between two legs, or the space under a chin all read as solid to a
    min/max measurement — and anything built from that measurement would fill the gap with
    geometry that was never drawn.

    A row of three runs cannot be described by one convex section. Recording the runs is
    what lets a later stage SAY SO instead of quietly producing a blob.
    """
    rows = []
    for y in range(height):
        base = y * width
        runs, start = [], None
        for x in range(width):
            opaque = alpha[base + x] >= ALPHA_FLOOR
            if opaque and start is None:
                start = x
            elif not opaque and start is not None:
                runs.append((start, x - 1))
                start = None
        if start is not None:
            runs.append((start, width - 1))
        rows.append(runs)
    return rows


def profile(image_path, standing_height_m, steps):
    """The width profile of one view, measured and unnamed."""
    with Image.open(image_path) as im:
        im = im.convert("RGBA")
        width, height = im.size
        alpha = im.getchannel("A").tobytes()

    spans = rows_with_content(alpha, width, height)
    runs_by_row = rows_with_runs(alpha, width, height)
    filled = [y for y, s in enumerate(spans) if s is not None]
    if not filled:
        raise SystemExit(f"  {image_path.name} has no opaque pixels to measure")

    top, bottom = filled[0], filled[-1]
    content_h = bottom - top + 1
    metres_per_px = standing_height_m / content_h

    lefts = [spans[y][0] for y in filled]
    rights = [spans[y][1] for y in filled]
    box_left, box_right = min(lefts), max(rights)
    content_w = box_right - box_left + 1

    bands = []
    for i in range(steps + 1):
        # 0.0 is the FEET and 1.0 is the crown, because that is how a standing figure is
        # described. Image rows run the other way, so this is flipped deliberately here
        # rather than left for a reader to trip over later.
        frac = i / steps
        y = int(round(bottom - frac * (content_h - 1)))
        span = spans[y]
        if span is None:
            bands.append({"height_fraction": round(frac, 4), "width_px": 0,
                          "width_m": 0.0, "centre_offset_m": None})
            continue
        left, right = span
        w = right - left + 1
        centre = (left + right) / 2.0
        runs = runs_by_row[y]
        bands.append({
            "height_fraction": round(frac, 4),
            "width_px": w,
            "width_m": round(w * metres_per_px, 4),
            # Every separate opaque run at this height, as metres from the box centre.
            # One run means a single convex section is a fair description here. More than
            # one means it is not, and whatever builds geometry has to know that.
            "runs_m": [[round((a - (box_left + box_right) / 2.0) * metres_per_px, 4),
                        round((b - (box_left + box_right) / 2.0) * metres_per_px, 4)]
                       for a, b in runs],
            "run_count": len(runs),
            # Positive means the band sits right of the bounding box's centre. A lean, a
            # raised arm or an ear that stands proud shows up here and nowhere else.
            "centre_offset_m": round((centre - (box_left + box_right) / 2.0)
                                     * metres_per_px, 4),
        })

    widest = max(bands, key=lambda b: b["width_px"])
    disjoint = [b["height_fraction"] for b in bands if b["run_count"] > 1]
    return {
        "image": str(image_path.relative_to(ROOT)).replace("\\", "/"),
        "canvas_px": [width, height],
        "content_box_px": [box_left, top, box_right, bottom],
        "content_height_px": content_h,
        "content_width_px": content_w,
        "metres_per_pixel": round(metres_per_px, 6),
        "content_width_m": round(content_w * metres_per_px, 4),
        "widest_band": {"height_fraction": widest["height_fraction"],
                        "width_m": widest["width_m"]},
        "disjoint_bands": disjoint,
        "bands": bands,
    }


def measure(character, steps=20):
    manifest = load_manifest(character)
    standing_height_m = float(manifest["standing_height_m"])
    views = {}
    for name, rec in manifest["views"].items():
        image_path = ROOT / rec["path"]
        if not image_path.exists():
            raise SystemExit(f"  view {name} missing its image: {image_path}")
        view = profile(image_path, standing_height_m, steps)
        if rec.get("reference_use") == "EXCLUDED":
            # Measured anyway. An unreadable ORIENTATION does not make a silhouette
            # unmeasurable, and the width profile is still real information.
            view["excluded_as_reference"] = rec.get("reference_use_reason", "excluded")
        views[name] = view
    return {
        "kind": "SILHOUETTE_MEASUREMENT_V1",
        "character": character,
        "standing_height_m": standing_height_m,
        "steps": steps,
        "alpha_floor": ALPHA_FLOOR,
        "names_no_landmarks": "Bands are reported by height fraction only. No band is "
                              "called a head, a waist or a shoulder: a stylised character "
                              "has no landmark a program can find, and naming one is how "
                              "a waist was once reported as a head.",
        "views": views,
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--character", required=True,
                   help="a character with an approved sheet under assets/design/")
    p.add_argument("--steps", type=int, default=20,
                   help="bands from feet to crown; 20 gives every 5%% of height")
    p.add_argument("--out", type=Path, default=None)
    args = p.parse_args(argv)

    report = measure(args.character, args.steps)
    out = args.out or (DESIGN / args.character / "measurement.json")
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print(f"  SILHOUETTE MEASUREMENT — {report['character']}, "
          f"{report['standing_height_m']:.2f} m standing")
    for name, view in report["views"].items():
        mark = "  (excluded as reference)" if "excluded_as_reference" in view else ""
        print(f"\n    {name}{mark}")
        print(f"      content {view['content_width_m']:.3f} m wide, "
              f"widest at {view['widest_band']['height_fraction']:.0%} of height "
              f"= {view['widest_band']['width_m']:.3f} m")
        for band in view["bands"]:
            if band["height_fraction"] * 100 % 10:      # print every 10% to stay readable
                continue
            bar = "#" * max(1, round(band["width_px"] / view["content_width_px"] * 40))
            print(f"      {band['height_fraction']:5.0%}  {band['width_m']:6.3f} m  {bar}")
    print(f"\n    -> {out.relative_to(ROOT) if out.is_relative_to(ROOT) else out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
