"""How far the built surface drifted from the drawing that was approved.

    python assets/design/silhouette_error.py --character coco --masks out/gate1d

Gate 1-D fuses separate tubes into one deformable surface with a voxel remesh. That is a
lossy operation by construction: anything finer than a voxel is rounded away, and the
question is never whether the shape moved but how far, and whether that is inside what we
are willing to accept.

So this compares the fused surface's own orthographic silhouette against the approved
turnaround, in two independent ways:

    PER-BAND WIDTH ERROR   at every height, how much wider or narrower the built shape is
                           than the drawing, in millimetres
    INTERSECTION OVER      how much of the two silhouettes actually coincide, which
    UNION                  catches a shape that is the right width in the wrong place

Both are normalised by content height, so neither depends on the render's framing. A mask
photographed slightly larger is the same shape, and a metric that says otherwise is
measuring the camera.

THE THRESHOLDS ARE DECLARED, NOT DISCOVERED. They are stated below with the reasoning, and
they are stated before the numbers are looked at, because a tolerance chosen after seeing
the result is not a tolerance.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
import measure

ROOT = Path(__file__).resolve().parents[2]

# A voxel remesh cannot hold a feature smaller than its own grid, so an error of one voxel
# is the method working, not failing. Three voxels of worst-case width error is the point
# at which a feature has visibly moved rather than been rounded.
MAX_MEAN_ERROR_VOXELS = 1.0
MAX_WORST_ERROR_VOXELS = 3.0
# Two silhouettes of the right widths can still sit apart. 0.97 leaves room for the
# rounding a voxel grid must do at every edge, and no room for a limb in the wrong place.
MIN_IOU = 0.97
BANDS = 200


def _normalised_alpha(path, height_px=512):
    """A silhouette scaled so its CONTENT is height_px tall, cropped to its content box."""
    with Image.open(path) as im:
        alpha = im.convert("RGBA").getchannel("A")
    box = alpha.point(lambda v: 255 if v >= measure.ALPHA_FLOOR else 0).getbbox()
    if box is None:
        raise SystemExit(f"  {path} has no silhouette to compare")
    cropped = alpha.crop(box)
    scale = height_px / cropped.height
    resized = cropped.resize((max(1, round(cropped.width * scale)), height_px),
                             Image.LANCZOS)
    return resized.point(lambda v: 255 if v >= measure.ALPHA_FLOOR else 0)


def _iou(first, second):
    """Overlap of two normalised silhouettes, aligned on content centre and base."""
    width = max(first.width, second.width)
    canvas = (width, first.height)
    placed = []
    for image in (first, second):
        sheet = Image.new("L", canvas, 0)
        sheet.paste(image, ((width - image.width) // 2, 0))
        placed.append(sheet.tobytes())
    a, b = placed
    intersection = sum(1 for x, y in zip(a, b) if x and y)
    union = sum(1 for x, y in zip(a, b) if x or y)
    return (intersection / union) if union else 0.0


def compare(character, masks_dir, bands=BANDS):
    manifest = measure.load_manifest(character)
    height_m = float(manifest["standing_height_m"])
    fuse_report = json.loads((masks_dir / "fuse.json").read_text(encoding="utf-8"))
    voxel_m = float(fuse_report["voxel_size_m"])

    views = {}
    for view in ("front", "side"):
        approved = ROOT / manifest["views"][view]["path"]
        rendered = masks_dir / f"mask_{view}.png"
        if not rendered.exists():
            raise SystemExit(f"  no rendered mask for {view}: {rendered}")

        reference = measure.profile(approved, height_m, bands)["bands"]
        built = measure.profile(rendered, height_m, bands)["bands"]
        by_fraction = {round(b["height_fraction"], 4): b for b in built}

        errors = []
        for band in reference:
            other = by_fraction.get(round(band["height_fraction"], 4))
            if other is None:
                continue
            errors.append({"height_fraction": band["height_fraction"],
                           "reference_m": band["width_m"], "built_m": other["width_m"],
                           "error_m": round(other["width_m"] - band["width_m"], 5)})
        magnitudes = [abs(e["error_m"]) for e in errors]
        # DIAGNOSIS, NOT A SECOND CHANCE. The verdict stays the verdict; this only says
        # whether a failure is everywhere or in one place, which is the difference between
        # a wrong method and a wrong feature.
        over = [e["height_fraction"] for e in errors
                if abs(e["error_m"]) > MAX_WORST_ERROR_VOXELS * voxel_m]
        worst = max(errors, key=lambda e: abs(e["error_m"])) if errors else None
        views[view] = {
            "bands_compared": len(errors),
            "mean_error_mm": round(1000 * sum(magnitudes) / len(magnitudes), 3),
            "worst_error_mm": round(1000 * abs(worst["error_m"]), 3),
            "worst_at_height_fraction": worst["height_fraction"],
            "mean_error_voxels": round((sum(magnitudes) / len(magnitudes)) / voxel_m, 3),
            "worst_error_voxels": round(abs(worst["error_m"]) / voxel_m, 3),
            "iou": round(_iou(_normalised_alpha(approved), _normalised_alpha(rendered)), 5),
            "bands_over_worst_tolerance": len(over),
            "bands_over_worst_tolerance_pct": round(100.0 * len(over) / len(errors), 1),
            "over_tolerance_heights": [round(f, 4) for f in over[:12]],
        }

    passes = all(v["mean_error_voxels"] <= MAX_MEAN_ERROR_VOXELS
                 and v["worst_error_voxels"] <= MAX_WORST_ERROR_VOXELS
                 and v["iou"] >= MIN_IOU for v in views.values())
    return {
        "kind": "SILHOUETTE_ERROR_V1",
        "character": character,
        "voxel_size_m": voxel_m,
        "thresholds": {"max_mean_error_voxels": MAX_MEAN_ERROR_VOXELS,
                       "max_worst_error_voxels": MAX_WORST_ERROR_VOXELS,
                       "min_iou": MIN_IOU,
                       "declared": "stated before the numbers were looked at"},
        "views": views,
        "within_tolerance": passes,
        "one_connected_surface": fuse_report.get("one_connected_surface"),
        "watertight": fuse_report.get("watertight"),
        "rig_ready": bool(passes and fuse_report.get("one_connected_surface")
                          and fuse_report.get("watertight")),
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--character", required=True)
    p.add_argument("--masks", type=Path, required=True,
                   help="the Gate 1-D output directory holding fuse.json and the masks")
    p.add_argument("--bands", type=int, default=BANDS)
    args = p.parse_args(argv)

    masks_dir = args.masks if args.masks.is_absolute() else (ROOT / args.masks)
    report = compare(args.character, masks_dir, args.bands)
    out = masks_dir / "silhouette_error.json"
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print(f"  SILHOUETTE ERROR - {report['character']}, "
          f"voxel {report['voxel_size_m'] * 1000:.2f} mm")
    for view, data in report["views"].items():
        print(f"    {view:6s} mean {data['mean_error_mm']:6.2f} mm "
              f"({data['mean_error_voxels']:.2f} voxels)   "
              f"worst {data['worst_error_mm']:6.2f} mm "
              f"({data['worst_error_voxels']:.2f}) at "
              f"{data['worst_at_height_fraction']:.0%}   IoU {data['iou']:.4f}")
    print(f"    within declared tolerance: {report['within_tolerance']}")
    print(f"    RIG READY: {report['rig_ready']}")
    print(f"    -> {out.relative_to(ROOT) if out.is_relative_to(ROOT) else out}")
    return 0 if report["rig_ready"] else 1


if __name__ == "__main__":
    sys.exit(main())
