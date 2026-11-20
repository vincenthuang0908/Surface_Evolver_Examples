"""Headless FreeCAD worker for the dashboard's CAD inspection workspace."""

import argparse
from base64 import b64encode
import os
from pathlib import Path
import sys

import numpy as np

from pcbsim.common import ComponentError, cli_entry, load_config, read_json, require_file, section, sha256, write_json
from pcbsim.components.cad_extractor import detect_connections, extract_cad


def mesh_solid(solid, backend, role, index, pins=()):
    metadata = backend.signature(solid)
    low, high = np.reshape(metadata["bounds_mm"], (2, 3))
    # Use a finer relative tolerance for small parts while limiting assembly size.
    deflection = min(0.08, max(0.01, float(max(high - low)) / 250))
    vertices, triangles = solid.tessellate(deflection)
    return {
        **metadata, "index": index, "role": role, "pin_indices": list(pins),
        "dimensions_mm": (high - low).tolist(),
        "positions": b64encode(np.asarray([tuple(v) for v in vertices], dtype="<f4").tobytes()).decode("ascii"),
        "indices": b64encode(np.asarray(triangles, dtype="<u4").tobytes()).decode("ascii"),
    }


def inspect_step(source, config, backend):
    source = require_file(source, "original STEP")
    shape = backend.load(source)
    solids = backend.solids(shape)
    bounds = backend.bounds(shape)
    try:
        board, connections = detect_connections(shape, section(config, "cad_extractor"), backend=backend)
        detection_error = None
    except ComponentError as exc:
        board, connections = None, []
        detection_error = str(exc)
    roles = {board: ("pcb", [])}
    for row in connections:
        for role in ("pin", "pad"):
            _, indices = roles.setdefault(row[f"{role}_solid_index"], (role, []))
            indices.append(row["pin_index"])
    meshes = []
    for index, solid in enumerate(solids):
        role, pins = roles.get(index, ("other", []))
        meshes.append(mesh_solid(solid, backend, role, index, pins))
    return {"source_sha256": sha256(source), "connections": connections,
            "detection_error": detection_error, "solids": meshes, "bounds_mm": bounds}


def signature_delta(source, target):
    return {
        "bounds_mm": max(abs(a - b) for a, b in zip(source["bounds_mm"], target["bounds_mm"])),
        "center_mm": max(abs(a - b) for a, b in zip(source["center_mm"], target["center_mm"])),
        "volume_mm3": abs(source["volume_mm3"] - target["volume_mm3"]),
    }


def compare_extracted_step(path, geometry, backend):
    shape = backend.load(path)
    solids = backend.solids(shape)
    bounds = backend.bounds(shape)
    signatures = [backend.signature(solid) for solid in solids]
    available = set(range(len(solids)))
    pin_index = geometry["selection"]["pin_index"]
    meshes, checks = [], {}
    length_tolerance, volume_tolerance = 1e-5, 1e-6
    for role in ("pin", "pad"):
        source = geometry["original_selected_solids"][role]
        deltas = {i: signature_delta(source, signatures[i]) for i in available}
        index = min(available, key=lambda i: (deltas[i]["bounds_mm"], deltas[i]["center_mm"], i))
        available.remove(index)
        delta = deltas[index]
        valid = backend.valid(solids[index])
        checks[role] = {"max_delta": delta, "valid_solid": valid,
                        "passed": valid and delta["bounds_mm"] <= length_tolerance
                        and delta["center_mm"] <= length_tolerance and delta["volume_mm3"] <= volume_tolerance}
        meshes.append(mesh_solid(solids[index], backend, role, index, (pin_index,)))

    selection = geometry["selection"]
    cx, cy = selection["center_xy_mm"]
    pcb = geometry["pcb"]
    thickness = pcb["thickness_mm"]
    z_min = pcb["world_z_range_mm"][0]
    probe = backend.cylinder(selection["pcb_drill_radius_mm"] * 0.99, thickness, (cx, cy, z_min))
    crop_valid = bool(available)
    pcb_lows, pcb_highs = [], []
    overlap = volume = 0.0
    for index in sorted(available):
        solid = solids[index]
        low, high = np.reshape(signatures[index]["bounds_mm"], (2, 3))
        pcb_lows.append(low)
        pcb_highs.append(high)
        crop_valid = crop_valid and backend.valid(solid)
        volume += signatures[index]["volume_mm3"]
        overlap += abs(backend.volume(backend.intersect(solid, probe)))
        meshes.append(mesh_solid(solid, backend, "pcb", index))
    crop_bounds = np.concatenate((np.min(pcb_lows, axis=0), np.max(pcb_highs, axis=0))) if available else np.zeros(6)
    bounds_delta = float(np.max(np.abs(crop_bounds - pcb["section_bounds_mm"])))
    volume_delta = abs(volume - pcb["section_volume_mm3"])
    z_span = float(crop_bounds[5] - crop_bounds[2])
    checks["pcb"] = {"valid_crop": crop_valid, "thickness_mm": z_span, "expected_thickness_mm": thickness,
                     "hole_overlap_mm3": overlap, "max_bounds_delta_mm": bounds_delta,
                     "volume_delta_mm3": volume_delta,
                     "passed": crop_valid and abs(z_span - thickness) <= length_tolerance
                     and bounds_delta <= length_tolerance and volume_delta <= volume_tolerance and overlap <= 1e-7}
    return {"solids": meshes, "bounds_mm": bounds, "pin_index": pin_index,
            "validation": {"passed": all(check["passed"] for check in checks.values()), "checks": checks,
                           "position_tolerance_mm": length_tolerance, "volume_tolerance_mm3": volume_tolerance}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("inspect", "extract"))
    parser.add_argument("--input-step", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--pin-index", type=int)
    args = parser.parse_args()
    if args.mode == "extract" and args.pin_index is None:
        parser.error("extract requires --pin-index")

    freecad_lib = os.getenv("PCBSIM_FREECAD_LIB")
    if freecad_lib:
        sys.path.insert(0, freecad_lib)
    from .freecad_backend import FreeCADBackend

    backend = FreeCADBackend()
    settings = section(load_config(args.config), "cad_extractor")
    if args.mode == "inspect":
        scene = inspect_step(args.input_step, settings, backend)
    else:
        settings["selection"] = {**settings.get("selection", {}), "pin_index": args.pin_index}
        report = extract_cad(args.input_step, settings, args.output_dir, backend=backend)
        geometry = read_json(report["outputs"]["geometry"])
        scene = compare_extracted_step(report["outputs"]["extracted_step"], geometry, backend)
    path = write_json(args.output_dir / "scene.json", scene)
    return {"scene": str(path)}


if __name__ == "__main__":
    cli_entry(main)
