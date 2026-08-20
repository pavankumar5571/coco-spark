"""Gate 1-C method attack. Run with Blender, not ordinary Python."""
from collections import Counter
import importlib.util
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("gate_mesh", ROOT / "blender" / "mesh.py")
gate_mesh = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate_mesh)


fractions = [0.0, 0.25, 0.5, 0.75]
front = []
for fraction in fractions:
    runs = [[-0.2, -0.05], [0.05, 0.2]] if fraction < 0.75 else [[-0.15, 0.15]]
    front.append({"height_fraction": fraction, "runs_m": runs})
side = [{"height_fraction": fraction, "width_m": 0.2, "centre_offset_m": 0.0}
        for fraction in fractions]
measurement = {"standing_height_m": 1.0,
               "views": {"front": {"bands": front}, "side": {"bands": side}}}
chains, stats = gate_mesh.components(measurement)
unique_chains = len({id(chain) for chain in chains})
print(f"synthetic merge: reported={len(chains)} unique_objects={unique_chains} stats={stats}")
failures = []
if unique_chains != len(chains):
    failures.append("merge emitted the same component chain more than once")


bpy.ops.wm.open_mainfile(filepath=str(ROOT / "out" / "gate1c" / "coco_base.blend"))
mesh = bpy.data.objects["coco_base"].data
coordinates = [tuple(round(value, 7) for value in vertex.co) for vertex in mesh.vertices]
duplicate_vertices = sum(count - 1 for count in Counter(coordinates).values() if count > 1)
print(f"real mesh: vertices={len(mesh.vertices)} duplicate_coordinate_vertices={duplicate_vertices}")
if duplicate_vertices:
    failures.append("real base mesh contains exact duplicate-coordinate vertices")
if failures:
    raise AssertionError("; ".join(failures))
