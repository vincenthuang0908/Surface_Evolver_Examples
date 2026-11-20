"""Streamlit controls for inspecting STEP geometry with the FreeCAD worker."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

import streamlit as st
from streamlit.components.v1 import declare_component

import job_runner as runner
from pcbsim.common import load_config, read_json, resolve_path, section, sha256, write_json


@st.cache_data(max_entries=8, show_spinner=False)
def freecad_request(source: str, source_hash: str, settings: dict, pin_index: int | None = None) -> dict:
    python = os.getenv("PCBSIM_FREECAD_PYTHON")
    if not python:
        raise RuntimeError("Start the project's Docker image to use the headless FreeCAD worker.")
    with TemporaryDirectory(prefix="pcbsim-cad-") as temp:
        out = Path(temp)
        config = write_json(out / "request.json", {"steps": {"cad_extractor": settings}})
        mode = "inspect" if pin_index is None else "extract"
        command = [python, "-m", "dashboard.3d_visualize_cad.cad_debug", mode, "--input-step", source,
                   "--output-dir", str(out), "--config", str(config)]
        if pin_index is not None:
            command.extend(["--pin-index", str(pin_index)])
        try:
            process = subprocess.run(command, cwd=Path(__file__).resolve().parents[2], stdin=subprocess.DEVNULL,
                                     capture_output=True, text=True, encoding="utf-8", errors="replace",
                                     env={**os.environ, "QT_QPA_PLATFORM": "offscreen"}, timeout=180)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("FreeCAD did not finish processing this STEP within 3 minutes.") from exc
        if process.returncode:
            detail = process.stderr.strip() or process.stdout.strip() or f"exit status {process.returncode}"
            raise RuntimeError(f"FreeCAD {mode} failed. {detail[-2400:]}")
        scene = read_json(out / "scene.json")
        if mode == "inspect":
            actual_hash = scene["source_sha256"]
            result = {"scene": scene}
        else:
            geometry = (out / "geometry.json").read_bytes()
            actual_hash = json.loads(geometry)["source"]["sha256"]
            result = {"scene": scene, "step": (out / "extracted.step").read_bytes(), "geometry": geometry}
        if actual_hash != source_hash:
            raise RuntimeError("The STEP changed while FreeCAD was processing it. Load the STEP again.")
        return result


def display_dimensions(solid: dict) -> None:
    low, high = solid["bounds_mm"][:3], solid["bounds_mm"][3:]
    st.write(f"**{solid['role'].upper()} · Solid {solid['index']}**")
    st.table([
        {"Axis": axis, "Minimum (mm)": round(start, 6), "Maximum (mm)": round(end, 6),
         "Size (mm)": round(size, 6), "Center of mass (mm)": round(center, 6)}
        for axis, start, end, size, center in zip("XYZ", low, high, solid["dimensions_mm"], solid["center_mm"])
    ])
    st.caption(f"Volume {solid['volume_mm3']:.6f} mm³ · {solid['face_count']} faces")


def show_comparison(comparison: dict, pin_index: int) -> None:
    validation = comparison["scene"]["validation"]
    label = f"Pin #{pin_index} STEP round-trip"
    if validation["passed"]:
        st.success(f"{label} passed. Pin and pad dimensions, positions, and volumes match within tolerance. "
                   "The cropped PCB retains its thickness and open through-hole.")
    else:
        st.error(f"{label} failed one or more geometry checks.")
    with st.expander("Round-trip measurements"):
        st.json(validation)
        for solid in comparison["scene"]["solids"]:
            display_dimensions(solid)
    step, geometry = st.columns(2)
    step.download_button("Download extracted STEP", data=comparison["step"], mime="application/step",
                         file_name=f"pin_{pin_index}_extracted.step", on_click="ignore")
    geometry.download_button("Download geometry JSON", data=comparison["geometry"], mime="application/json",
                             file_name=f"pin_{pin_index}_geometry.json", on_click="ignore")


def show_cad_workspace() -> None:
    source = st.radio("PCB source", ["Supplied Pico example", "Upload STEP"], horizontal=True, key="cad_source")
    upload = st.file_uploader("PCB assembly", type=["step", "stp"], key="cad_upload") if source == "Upload STEP" else None
    source_id = (source, upload.file_id if upload else None)
    if st.button("Load STEP", type="primary", disabled=source == "Upload STEP" and upload is None):
        st.session_state.pop("cad_loaded", None)
        st.session_state.pop("cad_comparison", None)
        try:
            path = runner.base_config_path()
            config = load_config(path)
            step = (runner.save_upload(upload.getvalue()) if upload is not None
                    else resolve_path(config["inputs"]["step_file"], path.parent))
            source_hash = sha256(step)
            settings = section(config, "cad_extractor")
            with st.spinner("Importing and tessellating STEP in FreeCAD…"):
                freecad_request(str(step), source_hash, settings)
            viewer_id = hashlib.sha256(json.dumps([source_hash, settings], sort_keys=True).encode()).hexdigest()
            st.session_state["cad_loaded"] = (source_id, str(step), source_hash, settings, viewer_id)
        except (KeyError, OSError, RuntimeError, ValueError) as exc:
            st.error(str(exc))

    loaded = st.session_state.get("cad_loaded")
    if not loaded or loaded[0] != source_id:
        return
    _, step, source_hash, settings, viewer_id = loaded
    try:
        scene = freecad_request(step, source_hash, settings)["scene"]
    except (OSError, RuntimeError, ValueError) as exc:
        st.error(str(exc))
        return
    connections = {row["pin_index"]: row for row in scene["connections"]}
    solids = {row["index"]: row for row in scene["solids"]}
    st.caption(f"{len(solids)} solids · {len(connections)} detected connections · "
               "Dimensions in millimeters. Pin indices follow geometric order.")
    if scene["detection_error"]:
        st.warning(scene["detection_error"])

    first = next(iter(connections.values()), {})
    default = {"pin_index": first.get("pin_index"), "solid_index": first.get("pin_solid_index", 0)}
    viewer_key = f"cad_viewer_{viewer_id}"
    selection = st.session_state.get(viewer_key) or default
    pin_index = selection["pin_index"]
    saved = st.session_state.get("cad_comparison")
    comparison = saved[2] if saved and saved[:2] == (viewer_id, pin_index) else None
    component_dir = os.getenv("PCBSIM_CAD_VIEWER", str(Path(__file__).with_name("cad_viewer")))
    viewer = declare_component("pcb_cad_viewer", path=component_dir)
    viewer(original=scene, extracted=comparison["scene"] if comparison else None,
           selection=selection, key=viewer_key, default=default)

    if pin_index in connections and st.button(f"Extract pin #{pin_index}", type="primary"):
        try:
            with st.spinner(f"Extracting pin #{pin_index} in FreeCAD…"):
                extracted = freecad_request(step, source_hash, settings, pin_index)
            st.session_state["cad_comparison"] = (viewer_id, pin_index, extracted)
            st.rerun()
        except (OSError, RuntimeError, ValueError) as exc:
            st.error(str(exc))
    if comparison:
        show_comparison(comparison, pin_index)
    st.subheader("Original geometry")
    if selection["solid_index"] in solids:
        display_dimensions(solids[selection["solid_index"]])
    if pin_index in connections:
        connection = connections[pin_index]
        st.write(f"**Pin #{pin_index} connection** · "
                 f"Pin {connection['pin_width_mm']:.4f} × {connection['pin_depth_mm']:.4f} mm · "
                 f"Plated bore Ø{2 * connection['hole_radius_mm']:.4f} mm · "
                 f"Pad Ø{2 * connection['pad_radius_mm']:.4f} mm")
        with st.expander(f"Pin #{pin_index} detection metadata"):
            st.json(connection)
            for role in ("pin", "pad", "board"):
                solid_id = connection[f"{role}_solid_index"]
                if solid_id != selection["solid_index"]:
                    display_dimensions(solids[solid_id])
