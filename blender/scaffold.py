"""Coco's modelling scaffold, built by script rather than by hand.

Run headless:

    blender -b -P blender/scaffold.py -- --out out/gate1b

WHY THIS IS A SCRIPT. A .blend is a binary. If the scene were assembled by clicking, the
only record of how Coco's references were placed, scaled and lit would be the file itself,
and nobody could review a change to it in a diff. Everything deterministic about this
project is code for that reason, and a character scaffold is no different: the .blend
becomes an OUTPUT, regenerable from this file, and the modelled mesh is the only thing a
human actually has to author.

WHAT IT DOES NOT DO. It does not invent Coco's proportions. An earlier attempt measured
the silhouette's width profile and concluded the head was 47% of the figure; that number
was the WAIST, which is the narrowest point of the front view and sits nowhere near the
neck. A stylised bear has no neck to find. So the script places the four canonical views
as reference planes at a known common scale and stops — the geometry is modelled against
them, which is the only honest source for a shape nobody has ever measured.

SCALE. assets/tripo/coco/manifest.json records that every view was normalised so the
CHARACTER's content height is 901px on a 1024px canvas. So one Blender unit is defined as
the character's height, and each plane is sized 1024/901 to make its content span exactly
that. The four views therefore agree with each other by construction rather than by eye.
"""
import json
import math
import os
import sys
from pathlib import Path

import bpy

ROOT = Path(bpy.path.abspath("//")) if bpy.data.filepath else Path.cwd()
MANIFEST = ROOT / "assets" / "tripo" / "coco" / "manifest.json"

# Where each view's camera stood, in degrees around Z, and which way the plane faces.
# THREE_QUARTER is excluded from the reference planes on purpose: message 253 of the
# design record graded it AMBIGUOUS for the asymmetric marker because the stylised pose
# made its orientation unreadable. An ambiguous reference is worse than no reference —
# it invites modelling to a view nobody can state the angle of.
VIEWS = {
    "front": {"yaw": 0.0, "note": "camera on +Y looking back at the character"},
    "side": {"yaw": 90.0, "note": "camera on +X; this is the character's RIGHT side"},
    "back": {"yaw": 180.0, "note": "camera on -Y"},
}


def _args():
    """Absolute, always. Blender resolves a relative render path against its own working
    directory, not the caller's — the first run wrote four turntable frames to C:\\out
    while reporting success against out/gate1b. A path that is right in the log and wrong
    on disk is the worst kind, because nothing fails."""
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    out = "out/gate1b"
    if "--out" in argv:
        out = argv[argv.index("--out") + 1]
    return (ROOT / out).resolve() if not os.path.isabs(out) else Path(out)


def clear():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def reference_planes(manifest):
    """One image empty per view, at the scale the manifest already normalised them to."""
    canvas = float(manifest["canvas"])
    planes = []
    for name, spec in VIEWS.items():
        rec = manifest["views"][name]
        img_path = ROOT / rec["path"]
        if not img_path.exists():
            raise SystemExit(f"  reference missing: {img_path}")
        content = float(rec["scaled_to"])           # character height, in pixels
        size = canvas / content                     # so the CHARACTER spans 1.0 unit

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
        empty.location = (-math.sin(yaw) * 1.5, math.cos(yaw) * -1.5, 0.5)

        bpy.context.collection.objects.link(empty)
        planes.append((name, size, empty.location))
    return planes


def lighting():
    """Preschool key/fill/rim. Bright, soft, no drama, nothing hidden in shadow."""
    specs = [
        ("key", "AREA", (2.2, -2.6, 3.0), 600.0, 4.0),
        ("fill", "AREA", (-3.0, -1.6, 1.4), 200.0, 5.0),
        ("rim", "AREA", (0.0, 3.2, 2.6), 300.0, 3.0),
    ]
    for name, kind, loc, power, size in specs:
        d = bpy.data.lights.new(name, type=kind)
        d.energy, d.size = power, size
        d.color = (1.0, 0.96, 0.90) if name == "key" else (0.92, 0.95, 1.0)
        o = bpy.data.objects.new(name, d)
        o.location = loc
        # point it at the character's mid height
        dx, dy, dz = -loc[0], -loc[1], 0.55 - loc[2]
        o.rotation_euler = (math.atan2(math.hypot(dx, dy), -dz), 0.0, math.atan2(dy, dx) + math.pi / 2)
        bpy.context.collection.objects.link(o)

    world = bpy.data.worlds.new("coco_world")
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


def place_camera(cam, yaw_deg, dist=3.4, height=0.62):
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
    out = _args()
    out.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    clear()
    planes = reference_planes(manifest)
    lighting()
    cam = camera()
    render_settings()

    # THE FROZEN TURNTABLE OBSERVATIONS, the same four angles Gate 1-A was graded on, so
    # a Blender-modelled Coco is judged against exactly what the reconstruction was.
    angles = {"front": 0, "right": 90, "back": 180, "left": 270}
    rendered = []
    for name, deg in angles.items():
        place_camera(cam, deg)
        bpy.context.scene.render.filepath = str(out / f"turntable_{name}.png")
        bpy.ops.render.render(write_still=True)
        rendered.append(f"turntable_{name}.png")

    blend = out / "coco_scaffold.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))

    report = {
        "kind": "GATE_1B_SCAFFOLD",
        "unit": "1.0 Blender unit = Coco's full height, from the manifest's 901px norm",
        "reference_planes": [{"view": n, "plane_size": round(s, 5),
                              "location": [round(v, 3) for v in loc]} for n, s, loc in planes],
        "excluded": {"three_quarter": "graded AMBIGUOUS for orientation; an ambiguous "
                                      "reference invites modelling to an unstateable angle"},
        "renders": rendered,
        "blend": blend.name,
        "mesh_objects": [o.name for o in bpy.data.objects if o.type == "MESH"],
        "engine": bpy.context.scene.render.engine,
    }
    (out / "scaffold.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("  GATE 1-B SCAFFOLD")
    for n, s, loc in planes:
        print(f"    ref {n:6s} plane {s:.4f} units at {tuple(round(v,2) for v in loc)}")
    print(f"    engine {bpy.context.scene.render.engine}")
    print(f"    meshes {report['mesh_objects'] or 'NONE - geometry is not invented here'}")
    print(f"    -> {out}")


if __name__ == "__main__":
    main()
