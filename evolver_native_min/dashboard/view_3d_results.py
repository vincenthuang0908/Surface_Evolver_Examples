"""Display a selected experiment with the shared CAD viewer and a headless FreeCAD worker."""

import argparse
import hashlib
from importlib import import_module
from itertools import chain
import json
from math import isclose
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from pcbsim.common import ComponentError, cli_entry, read_json, section, sha256, write_json


METRICS = (
    ("Height above pad", "maximum_height_above_pad_mm", "mm"),
    ("Top-fillet volume", "fillet_volume_mm3", "mm³"),
    ("Total solder volume", "volume_mm3", "mm³"),
)


def joint_index(solids: list[dict], reference: dict) -> int | None:
    """Require a unique match in world coordinates, independent of STEP solid order."""
    locations = ["bounds_mm", "center_mm"] if "center_mm" in reference else ["bounds_mm"]
    expected = list(chain.from_iterable(reference[key] for key in locations))
    matches = [
        solid["index"] for solid in solids
        if solid["face_count"] == reference["face_count"]
        and isclose(solid["volume_mm3"], reference["volume_mm3"], rel_tol=1e-6, abs_tol=1e-7)
        and all(isclose(actual, target, rel_tol=0, abs_tol=1e-6)
                for actual, target in zip(chain.from_iterable(solid[key] for key in locations), expected))
    ]
    return matches[0] if len(matches) == 1 else None


def build_scene(step, solder_step, world_mesh, backend, settings):
    from pcbsim.mesh import read_off, signed_volume

    cad_debug = import_module("dashboard.3d_visualize_cad.cad_debug")
    shape = backend.load(step)
    bounds = backend.bounds(shape)
    shapes = backend.solids(shape)
    signatures = [{**backend.signature(solid), "index": index} for index, solid in enumerate(shapes)]
    index = None
    if solder_step:
        try:
            reference = backend.solids(backend.load(solder_step))
        except ComponentError:
            reference = []
        if len(reference) == 1:
            index = joint_index(signatures, backend.signature(reference[0]))
    if index is None and world_mesh:
        try:
            vertices, faces = read_off(world_mesh)
            index = joint_index(signatures, {
                "bounds_mm": [*vertices.min(axis=0), *vertices.max(axis=0)],
                "face_count": len(faces),
                "volume_mm3": signed_volume(vertices, faces),
            })
        except ComponentError:
            pass
    # Measure the CAD solids before tessellation and keep solder out of connection detection.
    original_ids = [solid_id for solid_id in range(len(shapes)) if solid_id != index]
    original_shapes = [shapes[solid_id] for solid_id in original_ids]
    signatures_by_shape = {id(solid): signature for solid, signature in zip(shapes, signatures)}
    detector = SimpleNamespace(
        solids=lambda _: original_shapes, bounds=lambda solid: signatures_by_shape[id(solid)]["bounds_mm"],
        volume=backend.volume,
        cylindrical_faces=backend.cylindrical_faces, planar_faces=backend.planar_faces,
        signature=lambda solid: signatures_by_shape[id(solid)],
    )
    roles = {}
    try:
        board, connections = cad_debug.detect_connections(shape, settings, backend=detector)
    except ComponentError as exc:
        connections, detection_error = [], str(exc)
    else:
        detection_error = None
        roles[original_ids[board]] = ("pcb", [])
        for connection in connections:
            for role in ("board", "pin", "pad"):
                key = f"{role}_solid_index"
                connection[key] = original_ids[connection[key]]
                if role != "board":
                    _, pins = roles.setdefault(connection[key], (role, []))
                    pins.append(connection["pin_index"])
    solids = []
    for i, solid in enumerate(shapes):
        role, pins = roles.get(i, ("other", []))
        solids.append(cad_debug.mesh_solid(solid, detector, role, i, pins))
    return {"bounds_mm": bounds, "solids": solids, "joint_index": index,
            "connections": connections, "detection_error": detection_error}


def worker_main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--step", required=True, type=Path)
    parser.add_argument("--solder-step", type=Path)
    parser.add_argument("--world-mesh", type=Path)
    parser.add_argument("--settings", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    if freecad_lib := os.getenv("PCBSIM_FREECAD_LIB"):
        sys.path.insert(0, freecad_lib)
    backend = import_module("dashboard.3d_visualize_cad.freecad_backend").FreeCADBackend()
    paths = [args.step, args.solder_step, args.world_mesh]
    hashes = [sha256(path) if path else None for path in paths]
    settings = read_json(args.settings) if args.settings else {}
    scene = build_scene(args.step, args.solder_step, args.world_mesh, backend, settings)
    if hashes != [sha256(path) if path else None for path in paths]:
        raise ComponentError("A CAD artifact changed during tessellation.")
    scene["source_hashes"] = hashes
    write_json(args.output, scene)
    return {"scene": str(args.output)}


def file_hash(path: Path, stamp: tuple[int, int, int]) -> str:
    return sha256(path)


def artifact(path: Path) -> tuple[str, str]:
    stat = path.stat()
    signature = stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns
    return str(path), file_hash(path, signature)


def load_scene(python: str, step: tuple[str, str], solder: tuple[str, str] | None,
               world_mesh: tuple[str, str] | None, settings: dict) -> dict:
    with TemporaryDirectory(prefix="pcbsim-results-") as workdir:
        output = Path(workdir) / "scene.json"
        request = write_json(Path(workdir) / "settings.json", settings)
        command = [python, "-m", "dashboard.view_3d_results", "--step", step[0],
                   "--output", str(output), "--settings", str(request)]
        if solder:
            command.extend(["--solder-step", solder[0]])
        if world_mesh:
            command.extend(["--world-mesh", world_mesh[0]])
        try:
            process = subprocess.run(
                command, cwd=Path(__file__).resolve().parents[1], stdin=subprocess.DEVNULL,
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180,
                env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("FreeCAD did not finish importing the assembly within 3 minutes.") from exc
        if process.returncode:
            detail = process.stderr.strip() or process.stdout.strip() or f"exit status {process.returncode}"
            raise RuntimeError(f"FreeCAD could not prepare the assembly. {detail[-1200:]}")
        scene = read_json(output)
        if scene["source_hashes"] != [entry[1] if entry else None for entry in (step, solder, world_mesh)]:
            raise RuntimeError("A CAD artifact changed during import. The viewer will retry on refresh.")
        return scene


def show_joint_metrics(run: Path, conversion: dict, step_hash: str | None = None) -> None:
    try:
        metrics = read_json(run / "simulation" / "metrics.json")
    except ComponentError:
        st.info("Simulation metrics are unavailable for this experiment.")
        return

    export_hashes = conversion.get("output_sha256", {})
    export_hash = export_hashes.get("combined_step") if isinstance(export_hashes, dict) else export_hashes
    converted_mesh = conversion.get("mesh_sha256")
    metrics_mesh = metrics.get("mesh_sha256")
    if ((step_hash and export_hash and step_hash != export_hash)
            or (converted_mesh and metrics_mesh and converted_mesh != metrics_mesh)):
        st.warning("The saved metrics could not be matched to this CAD export.")
        return

    try:
        pin = read_json(run / "geometry" / "geometry.json").get("selection", {}).get("pin_index")
    except ComponentError:
        pin = None
    st.markdown(f"**Simulated solder joint · Pin #{pin}**" if pin is not None else "**Simulated solder joint**")
    if not any(metrics.get(key) is not None for _, key, _ in METRICS):
        st.info("Solder measurements are unavailable for this experiment.")
    else:
        for column, (label, key, unit) in zip(st.columns(len(METRICS)), METRICS):
            value = metrics.get(key)
            column.metric(label, f"{value:.6f} {unit}" if type(value) in (int, float) else "—")
    if metrics.get("numerical_pass") is False:
        st.warning("This simulation did not pass its numerical checks.")


def show_part_details(scene: dict, selected: dict) -> None:
    solids = {solid["index"]: solid for solid in scene["solids"]}
    solid_id = selected.get("solid_index")
    if solid_id not in solids:
        return

    display_dimensions = import_module("3d_visualize_cad.cad_workspace").display_dimensions
    display_dimensions(solids[solid_id])
    connection = next((row for row in scene["connections"] if row["pin_index"] == selected.get("pin_index")), None)
    if connection:
        pin = connection["pin_index"]
        st.write(f"**Pin #{pin} connection** · "
                 f"Pin {connection['pin_width_mm']:.4f} × {connection['pin_depth_mm']:.4f} mm · "
                 f"Plated bore Ø{2 * connection['hole_radius_mm']:.4f} mm · "
                 f"Pad Ø{2 * connection['pad_radius_mm']:.4f} mm")
        with st.expander(f"Pin #{pin} detection metadata"):
            st.json(connection)
            for role in ("pin", "pad", "board"):
                related = connection[f"{role}_solid_index"]
                if related != solid_id:
                    display_dimensions(solids[related])


def show_results_viewer(run: Path, step: Path | None, report: dict) -> None:
    st.subheader("3D PCB result")
    comparison_key = "pcb_results_solder_comparison"
    if st.session_state.get(comparison_key, (None, None))[0] != run:
        st.session_state[comparison_key] = (run, None)
    conversion = report.get("components", {}).get("cad_converter", {})
    if step is None:
        st.info("A combined PCB and solder STEP export is unavailable for this experiment.")
        show_joint_metrics(run, conversion)
        return

    python = os.getenv("PCBSIM_FREECAD_PYTHON")
    if not python:
        st.info("3D rendering requires the dashboard's FreeCAD worker.")
        show_joint_metrics(run, conversion)
        return

    cad_assets = Path(os.getenv("PCBSIM_CAD_VIEWER", str(
        Path(__file__).with_name("3d_visualize_cad") / "cad_viewer"
    )))
    try:
        settings = section(read_json(run / "input" / "config.json"), "cad_extractor")
    except (ComponentError, AttributeError, TypeError, ValueError):
        settings = {}
    try:
        source = artifact(step)
        solder = step.parent / "solder_only.step"
        mesh = step.parent / "solder_world.off"
        scene = load_scene(python, source, artifact(solder) if solder.is_file() else None,
                           artifact(mesh) if mesh.is_file() else None, settings)
        if not (cad_assets / "three").is_dir():
            raise FileNotFoundError(f"Three.js assets are unavailable in {cad_assets}.")
    except (OSError, RuntimeError) as exc:
        st.warning(f"The 3D result could not be loaded. {exc}")
        show_joint_metrics(run, conversion)
        return

    scene_id = hashlib.sha256(json.dumps([str(run), scene["source_hashes"], settings], sort_keys=True).encode()).hexdigest()
    viewer = declare_component("pcb_results_viewer", path=str(cad_assets))
    key = f"pcb_results_{scene_id}"
    first = next(iter(scene["connections"]), {})
    default = {"pin_index": first.get("pin_index"), "solid_index": first.get("pin_solid_index")}
    joint = scene["joint_index"]
    extracted = None
    if joint is not None:
        comparing = st.session_state[comparison_key][1] == scene_id
        st.button("Hide solder joint comparison" if comparing else "Extract solder joint",
                  key=f"{key}_extract_solder", on_click=st.session_state.__setitem__,
                  args=(comparison_key, (run, None if comparing else scene_id)))
        if comparing:
            solid = next(part for part in scene["solids"] if part["index"] == joint)
            extracted = {"kind": "solder", "bounds_mm": solid["bounds_mm"], "solids": [solid]}
    selected = viewer(original={**scene, "source_sha256": source[1]}, extracted=extracted,
                      solder_solid_index=joint, selection=st.session_state.get(key) or default,
                      key=key, default=default)
    if scene["detection_error"]:
        st.warning(scene["detection_error"])
    if joint is None:
        st.info("The simulated solder joint could not be identified in this STEP.")
        show_joint_metrics(run, conversion, source[1])
    elif selected.get("solid_index") == joint:
        show_joint_metrics(run, conversion, source[1])
    else:
        st.caption("Select the blue-gray solder joint to see its simulation results.")
    if joint is None or selected.get("solid_index") != joint:
        show_part_details(scene, selected)


if __name__ == "__main__":
    cli_entry(worker_main)
else:
    # The FreeCAD Python environment does not include Streamlit.
    import streamlit as st
    from streamlit.components.v1 import declare_component

    file_hash = st.cache_data(max_entries=32, show_spinner=False)(file_hash)
    load_scene = st.cache_data(max_entries=4, show_spinner="Preparing the 3D PCB assembly…")(load_scene)
