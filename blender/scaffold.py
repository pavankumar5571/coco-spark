"""A character's modelling scaffold, built by script rather than by hand.

Run headless, naming the character whose approved turnaround is to be staged:

    blender -b -P blender/scaffold.py -- --character coco --out out/gate1b

THE CHARACTER IS AN ARGUMENT, WITH NO DEFAULT. An earlier version of this file hardcoded
one character's manifest path, which made a general staging tool look general while being
usable for exactly one cast member. There is deliberately no default: a default is how the
hardcoding comes back, wearing a fallback.

WHY THIS IS A SCRIPT. A .blend is a binary. If the scene were assembled by clicking, the
only record of how the references were placed, scaled and lit would be the file itself,
and nobody could review a change to it in a diff. Everything deterministic about this
project is code for that reason, and a character scaffold is no different: the .blend
becomes an OUTPUT, regenerable from this file, and the modelled mesh is the only thing a
human actually has to author.

WHAT IT DOES NOT DO. It does not invent proportions. An earlier attempt measured
the silhouette's width profile and concluded the head was 47% of the figure; that number
was the WAIST, which is the narrowest point of the front view and sits nowhere near the
neck. A stylised bear has no neck to find. So the script places the four canonical views
as reference planes at a known common scale and stops — the geometry is modelled against
them, which is the only honest source for a shape nobody has ever measured.

SCALE. assets/design/<character>/manifest.json records the scaled content height of each
view, and the height the character stands at.
The sheet was scaled by ONE factor from the front, so a view that is legitimately taller —
the profile, whose ear stands proud of the crown — stays taller instead of being shrunk to
agree. Normalising each view separately would have quietly cost the body 1.3% of its depth.
"""
import json
import math
import os
import sys
from pathlib import Path

import bpy

ROOT = Path(bpy.path.abspath("//")) if bpy.data.filepath else Path.cwd()
DESIGN = ROOT / "assets" / "design"

# Where each view's camera stood, in degrees around Z, and which way the plane faces.
# THREE_QUARTER is excluded from the reference planes on purpose: message 253 of the
# design record graded it AMBIGUOUS for the asymmetric marker because the stylised pose
# made its orientation unreadable. An ambiguous reference is worse than no reference —
# it invites modelling to a view nobody can state the angle of.
FOOT_PLANE_LOCAL_Z = 0.0

# Where each named view's camera stood. These are properties of a turnaround sheet, not of
# any particular character, so they stay in code. WHICH of them is usable is a property of
# the sheet, and therefore lives in that character's manifest: a view whose orientation
# cannot be read is excluded there, as data, with its reason recorded beside it.
VIEWS = {
    "front": {"yaw": 0.0, "note": "camera on +Y looking back at the character"},
    "three_quarter": {"yaw": 45.0, "note": "camera between +X and +Y"},
    "side": {"yaw": 90.0, "note": "camera on +X; this is the character's RIGHT side"},
    "back": {"yaw": 180.0, "note": "camera on -Y"},
}


def _args():
    """Absolute, always. Blender resolves a relative render path against its own working
    directory, not the caller's — the first run wrote four turntable frames to C:\\out
    while reporting success against out/gate1b. A path that is right in the log and wrong
    on disk is the worst kind, because nothing fails."""
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if "--character" not in argv:
        raise SystemExit("  --character is required; there is no default character")
    character = argv[argv.index("--character") + 1]
    out = "out/gate1b"
    if "--out" in argv:
        out = argv[argv.index("--out") + 1]
    out = (ROOT / out).resolve() if not os.path.isabs(out) else Path(out)
    return character, out


def load_manifest(character):
    """Read the character's design manifest, and refuse to guess anything it omits."""
    path = DESIGN / character / "manifest.json"
    if not path.exists():
        raise SystemExit(f"  no design manifest for {character!r}: {path}")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if "standing_height_m" not in manifest:
        # A default here would be a number nobody decided, applied to a character nobody
        # measured, in the units the whole stage is authored in.
        raise SystemExit(f"  {path} has no standing_height_m; the stage is metric and this "
                         f"height is a design decision, not a fallback")
    return manifest


def clear():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def reference_planes(manifest, standing_height_m):
    """One image empty per usable view, at the scale the manifest already normalised to."""
    canvas = float(manifest["canvas"])
    planes = []
    excluded = {}
    for name, spec in VIEWS.items():
        rec = manifest["views"].get(name)
        if rec is None:
            continue                      # this sheet simply does not carry that view
        if rec.get("reference_use") == "EXCLUDED":
            excluded[name] = rec.get("reference_use_reason", "excluded by the manifest")
            continue
        img_path = ROOT / rec["path"]
        if not img_path.exists():
            raise SystemExit(f"  reference missing: {img_path}")
        # Each view keeps its TRUE height; the sheet was scaled by one factor, so the
        # profile's taller ear is real rather than an inconsistency to normalise away.
        content = float(rec.get("scaled_content_h", rec.get("scaled_to")))
        # METRES, agreed with the stage. This used to make the character span 1.0 unit,
        # which was fine while he was the only thing in the file and wrong the moment a
        # bed existed: a metre-tall cub next to metre-scaled furniture, with nothing
        # raising an error. The stage is authored in metres, so he is too.
        size = (canvas / content) * standing_height_m

        img = bpy.data.images.load(str(img_path))
        empty = bpy.data.objects.new(f"ref_{name}", None)
        empty.empty_display_type = "IMAGE"
        empty.data = img
        empty.empty_display_size = size
        empty.empty_image_depth = "DEFAULT"
        empty.use_empty_image_alpha = True
        empty.color[3] = 0.35                        # visible, never mistaken for geometry

        yaw = math.radians(spec["yaw"])
        # Stand the plane upright, then rotate it to the angle its camera stood at.
        empty.rotation_euler = (math.radians(90.0), 0.0, yaw)
        # Push it behind the character so geometry is modelled in front of it, and lift it
        # so the character's FEET sit on z=0 rather than its centre.
        empty.location = (-math.sin(yaw) * 1.5 * standing_height_m,
                          math.cos(yaw) * -1.5 * standing_height_m,
                          0.5 * standing_height_m)

        bpy.context.collection.objects.link(empty)
        planes.append((name, size, empty.location))
    if not planes:
        raise SystemExit("  no usable reference views in the manifest")
    return planes, excluded


def lighting(character, standing_height_m):
    """Preschool key/fill/rim. Bright, soft, no drama, nothing hidden in shadow."""
    specs = [
        ("key", "AREA", (1.21, -1.43, 1.65), 180.0, 2.2),
        ("fill", "AREA", (-1.65, -0.88, 0.77), 60.0, 2.75),
        ("rim", "AREA", (0.0, 1.76, 1.43), 90.0, 1.65),
    ]
    for name, kind, loc, power, size in specs:
        d = bpy.data.lights.new(name, type=kind)
        d.energy, d.size = power, size
        d.color = (1.0, 0.96, 0.90) if name == "key" else (0.92, 0.95, 1.0)
        o = bpy.data.objects.new(name, d)
        o.location = loc
        # point it at the character's mid height
        dx, dy, dz = -loc[0], -loc[1], 0.55 * standing_height_m - loc[2]
        o.rotation_euler = (math.atan2(math.hypot(dx, dy), -dz), 0.0, math.atan2(dy, dx) + math.pi / 2)
        bpy.context.collection.objects.link(o)

    world = bpy.data.worlds.new(f"{character}_world")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (0.86, 0.90, 0.97, 1.0)
    world.node_tree.nodes["Background"].inputs[1].default_value = 0.6
    bpy.context.scene.world = world


def camera():
    d = bpy.data.cameras.new("turntable")
    d.lens = 60.0                       # long enough that a large head does not distort
    o = bpy.data.objects.new("turntable", d)
    bpy.context.collection.objects.link(o)
    bpy.context.scene.camera = o
    return o


def place_camera(cam, yaw_deg, standing_height_m):
    dist = 3.4 * standing_height_m
    height = 0.62 * standing_height_m
    yaw = math.radians(yaw_deg)
    cam.location = (math.sin(yaw) * dist, -math.cos(yaw) * dist, height)
    cam.rotation_euler = (math.radians(88.0), 0.0, yaw)


def render_settings(res=640):
    s = bpy.context.scene
    s.render.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in \
        {i.identifier for i in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items} \
        else "BLENDER_EEVEE"
    s.render.resolution_x = s.render.resolution_y = res
    s.render.film_transparent = False
    s.render.image_settings.file_format = "PNG"


def main():
    character, out = _args()
    out.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest(character)
    standing_height_m = float(manifest["standing_height_m"])

    clear()
    planes, excluded = reference_planes(manifest, standing_height_m)
    lighting(character, standing_height_m)
    cam = camera()
    render_settings()

    # THE FROZEN TURNTABLE OBSERVATIONS: the same four angles an approved turnaround was
    # graded on, so a modelled character is judged against exactly what was approved.
    angles = {"front": 0, "right": 90, "back": 180, "left": 270}
    rendered = []
    for name, deg in angles.items():
        place_camera(cam, deg, standing_height_m)
        bpy.context.scene.render.filepath = str(out / f"turntable_{name}.png")
        bpy.ops.render.render(write_still=True)
        rendered.append(f"turntable_{name}.png")

    blend = out / f"{character}_scaffold.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))

    report = {
        "kind": "GATE_1B_SCAFFOLD",
        "character": character,
        "unit": "METRES, agreed with the stage. %s stands %.2f m."
                % (character, standing_height_m),
        "standing_height_m": standing_height_m,
        "foot_plane_local_z": FOOT_PLANE_LOCAL_Z,
        "reference_planes": [{"view": n, "plane_size": round(s, 5),
                              "location": [round(v, 3) for v in loc]} for n, s, loc in planes],
        "excluded": excluded,
        "renders": rendered,
        "blend": blend.name,
        "mesh_objects": [o.name for o in bpy.data.objects if o.type == "MESH"],
        "engine": bpy.context.scene.render.engine,
    }
    (out / "scaffold.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"  GATE 1-B SCAFFOLD - {character}")
    for n, s, loc in planes:
        print(f"    ref {n:6s} plane {s:.4f} units at {tuple(round(v,2) for v in loc)}")
    print(f"    engine {bpy.context.scene.render.engine}")
    print(f"    meshes {report['mesh_objects'] or 'NONE - geometry is not invented here'}")
    print(f"    -> {out}")


if __name__ == "__main__":
    main()
