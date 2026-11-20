"""Guided editor for the native through-hole pipeline configuration."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import streamlit as st

import job_runner as runner
from pcbsim.common import ComponentError, expand_step_configs, positive, resolve_path
from pcbsim.components.experiment_manager import requested_stages
from pcbsim.components.material_manager import (
    ALLOY_PRESETS, ALLOY_PROPERTY_DEFAULTS, MATERIAL_PROPERTIES, PROPERTY_BASES, normalize_materials,
)
from pcbsim.components.observables import OBSERVABLES, selected_outputs
from pcbsim.components.surface_evolver_runner import build_commands

ERRORS = (ValueError, RuntimeError, OSError)
_GUIDED_STAGES = {"cad_extractor", "material_manager", "fe_generator", "surface_evolver"}
_LABELS = {
    "assumed": "Assumed", "measured": "Measured", "literature": "Literature",
    "calibrated_effective": "Calibrated effective",
}


def json_upload(upload):
    data = json.loads(upload.getvalue().decode("utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError("Upload a JSON object.")
    return data


def json_download(label, value, filename, key):
    st.download_button(label, json.dumps(value, indent=2, allow_nan=False) + "\n",
                       filename, "application/json", key=key, on_click="ignore")


def saved_files(folder):
    return sorted((runner.data_dir() / folder).glob("*.json"), key=lambda path: path.stat().st_mtime_ns, reverse=True)


def save_settings(folder, data):
    content = (json.dumps(data, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    return runner.save_upload(content, ".json", folder=folder)


def guided_base(config, base):
    effective = copy.deepcopy(expand_step_configs(config, base))
    if not _GUIDED_STAGES.issubset(requested_stages(effective)):
        raise ComponentError("The guided editor needs STEP extraction, material normalization, model generation, and simulation. Use Advanced JSON for other pipelines.")
    inputs = effective.setdefault("inputs", {})
    if "step_file" not in inputs:
        raise ComponentError("Guided configurations require inputs.step_file.")
    for key, value in inputs.items():
        if key != "model_dependencies":
            inputs[key] = str(resolve_path(value, base))
    settings = effective.setdefault("steps", {}).setdefault("surface_evolver", {})
    executable = settings.get("executable")
    if executable and isinstance(executable, str) and ("/" in executable or "\\" in executable):
        settings["executable"] = str(resolve_path(executable, base))
    effective["experiments_dir"] = str(resolve_path(effective.get("experiments_dir", runner.data_dir() / "experiments"), base))
    normalize_materials(effective)
    selected_outputs(settings)
    return effective


def load_guided(config, base):
    st.session_state["guided_config"] = guided_base(config, base)
    st.session_state["guided_revision"] = st.session_state.get("guided_revision", 0) + 1


def load_advanced_draft(config_text, base):
    st.session_state.update(
        config_mode="Advanced JSON", config_editor=config_text, config_base=str(base),
        config_experiment_id="", config_stop_after=None, config_only=[], config_upload_keys=[],
        experiment_tab="Inputs & Configuration",
    )
    st.session_state.pop("config_upload_error", None)


def _load_config_controls():
    with st.expander("Load simulation configuration"):
        upload = st.file_uploader("Simulation configuration JSON", type=["json"], key="guided_upload")
        base = st.text_input("Directory for relative paths", str(runner.base_config_path().parent), key="guided_base")
        paths = saved_files("configurations")
        def label(path):
            if path is None:
                return "Choose a configuration"
            steps = runner.load_json(path).get("steps", {})
            material = steps.get("material_manager", {}).get("material", {}).get("name", "Material")
            pin = steps.get("cad_extractor", {}).get("selection", {}).get("pin_index", 1)
            return f"{material} · connection {pin} · {path.stem[:8]}"
        saved = st.selectbox("Saved configuration", [None, *paths], format_func=label)
        try:
            if st.button("Load configuration", disabled=upload is None and saved is None):
                load_guided(json_upload(upload) if upload else runner.read_json(saved), base if upload else saved.parent)
                st.rerun()
            if st.button("Restore supplied example"):
                load_guided(_default_config(), runner.base_config_path().parent)
                st.rerun()
        except ERRORS as exc:
            st.error(str(exc))


def _default_config():
    config = runner.base_config()
    config["experiments_dir"] = str((runner.data_dir() / "experiments").resolve())
    return config


def _clear_starter_provenance(key, starter):
    if (st.session_state[key] != starter["value"]
            and st.session_state.get(f"{key}_basis") == starter["basis"]
            and st.session_state.get(f"{key}_source") == starter["source"]):
        st.session_state[f"{key}_basis"] = "assumed"
        st.session_state[f"{key}_source"] = ""


def _material_controls(material, revision):
    with st.expander("Material", expanded=True):
        options = [None, *ALLOY_PRESETS]
        alloy = st.selectbox("Alloy preset", options, index=options.index(material.get("alloy")),
                             format_func=lambda key: key or "Custom / illustrative", key=f"alloy_{revision}")
        preset = ALLOY_PRESETS.get(alloy)
        starter = ALLOY_PROPERTY_DEFAULTS.get(alloy, {})
        if preset:
            if starter:
                st.caption(f"{preset['composition']}. Bulk starting values are for 250 °C. "
                           "Enter the contact angle for your pin finish and soldering conditions.")
            else:
                st.caption(f"{preset['composition']}. Enter liquid properties for your temperature and pin finish.")
            st.markdown(f"[Indium Corporation alloy composition]({preset['source']})")
        else:
            st.caption("The supplied example uses illustrative assumptions. Record a source and conditions for each property.")
        default_name = alloy if alloy and material.get("alloy") != alloy else material["name"]
        name = st.text_input("Material name", default_name, key=f"material_name_{revision}_{alloy}")
        provenance = {}
        output = {"name": name, "alloy": alloy}
        for field, (label, unit) in MATERIAL_PROPERTIES.items():
            value_col, basis_col, source_col = st.columns([3, 2, 3])
            same_alloy = alloy == material.get("alloy")
            prior = material.get("provenance", {}).get(field, {}) if same_alloy else starter.get(field, {})
            default = material[field] if same_alloy else prior.get("value")
            key = f"{field}_{revision}_{alloy}"
            callback = {"on_change": _clear_starter_provenance, "args": (key, starter[field])} if field in starter else {}
            output[field] = value_col.number_input(f"{label} ({unit})", value=default, format="%.8g", key=key, **callback)
            basis = basis_col.selectbox(f"Basis · {unit}", PROPERTY_BASES,
                                        index=PROPERTY_BASES.index(prior.get("basis", "assumed")),
                                        format_func=_LABELS.__getitem__, key=f"{key}_basis")
            source = source_col.text_input(f"Source and conditions · {unit}",
                                           prior.get("source", ""), key=f"{key}_source",
                                           help="Record a reference or measurement ID and the temperature, atmosphere, flux, or pin finish as applicable.")
            provenance[field] = {"basis": basis, "source": source}
        output["provenance"] = provenance
    return output


def _preset_controls(config, material):
    with st.expander("Saved material presets"):
        paths = saved_files("materials")
        saved = st.selectbox("Saved material", [None, *paths], format_func=lambda path:
                             f"{runner.load_json(path).get('material', {}).get('name', 'Material')} · {path.stem[:8]}"
                             if path else "Choose a material")
        upload = st.file_uploader("Material preset JSON", type=["json"], key="material_upload")
        try:
            if st.button("Load material", disabled=upload is None and saved is None):
                preset = json_upload(upload) if upload else runner.read_json(saved)
                if (preset.get("schema_version", 1) != 1 or not isinstance(preset.get("material"), dict)
                        or MATERIAL_PROPERTIES.keys() - preset["material"].keys()):
                    raise ComponentError("A schema version 1 material preset needs all three physical properties.")
                updated = copy.deepcopy(config)
                updated["steps"].setdefault("material_manager", {})["material"] = preset["material"]
                load_guided(updated, runner.base_config_path().parent)
                st.rerun()
            if all(material[key] is not None for key in MATERIAL_PROPERTIES):
                preset = {"schema_version": 1, "material": material}
                normalize_materials({"material": material})
                if st.button("Save material preset"):
                    path = save_settings("materials", preset)
                    st.success(f"Saved {material['name']} · {path.stem[:8]}")
                json_download("Download material preset", preset, "material.json", "material_download")
        except ERRORS as exc:
            st.error(str(exc))


def _physics_controls(simulation, revision):
    with st.expander("Simulation physics and boundaries", expanded=True):
        left, right = st.columns(2)
        sim = copy.deepcopy(simulation)
        sim.pop("effective_fillet_volume_mm3", None)
        fields = (
            ("fillet_volume_mm3", "Top-fillet solder volume (mm³)", left, 0.005),
            ("gravity_m_per_s2", "Downward gravity (m/s²)", right, 0.1),
            ("volume_multiplier", "Fillet volume multiplier", left, 0.1),
            ("contact_angle_delta_deg", "Pin angle offset (°)", right, 1.0),
        )
        for name, label, column, step in fields:
            sim[name] = column.number_input(label, value=float(sim[name]), step=step, format="%.8g",
                                            key=f"{name}_{revision}")
        for name in ("fillet_volume_mm3", "gravity_m_per_s2"):
            prior = sim.get("provenance", {}).get(name, {})
            basis_col, source_col = st.columns([1, 3])
            label = "Solder amount" if name == "fillet_volume_mm3" else "Gravity"
            basis = basis_col.selectbox(f"{label} basis", PROPERTY_BASES,
                                        index=PROPERTY_BASES.index(prior.get("basis", "assumed")),
                                        format_func=_LABELS.__getitem__, key=f"{name}_basis_{revision}")
            source = source_col.text_input(f"{label} source", prior.get("source", ""), key=f"{name}_source_{revision}")
            sim.setdefault("provenance", {})[name] = {"basis": basis, "source": source}
        modes = ["mobile", "pinned"]
        sim["pin_contact_line"] = st.radio("Pin contact line", modes, index=modes.index(sim["pin_contact_line"]),
                                          horizontal=True, key=f"contact_line_{revision}")
        st.caption("The pad edge is pinned. The barrel is fully filled and fixed. Gravity acts toward −z. "
                   "In pinned mode, the pin contact line stays at its initialized height and the Young angle does not set the shape.")
    return sim


def _solver_controls(fe, solver, simulation, revision):
    with st.expander("Mesh and solver"):
        cols = st.columns(2)
        fields = (
            (fe, "radial_segments", "Initial radial segments", 5, 2, 100),
            (fe, "segments_per_pin_side", "Initial segments per pin side", 8, 2, 128),
            (solver, "refinements", "Mesh refinements", 1, 0, 5),
            (solver, "minimization_steps", "Minimization steps per pass", 300, 1, 100000),
            (solver, "warmup_steps", "Initial relaxation steps", 30, 0, 100000),
            (solver, "convergence_check_steps", "Convergence window steps", 30, 1, 10000),
            (solver, "max_convergence_batches", "Maximum check batches", 10, 2, 100),
            (solver, "consecutive_convergence_checks", "Consecutive passing checks", 2, 2, 100),
            (simulation, "seed", "Initial perturbation seed", 0, 0, 2147483647),
        )
        for index, (settings, key, label, default, minimum, maximum) in enumerate(fields):
            settings[key] = cols[index % 2].number_input(label, minimum, maximum, int(settings.get(key, default)),
                                                        step=1, key=f"{key}_{revision}")
        fields = (
            (fe, "initial_perturbation_mm", "Initial perturbation amplitude (mm)", 0.0),
            (fe, "boundary_chord_tolerance_mm", "Maximum pad chord error (mm)", 0.01),
            (solver, "volume_relative_tolerance", "Relative volume tolerance", 1e-7),
            (solver, "energy_drift_tolerance", "Scaled energy drift tolerance", 1e-7),
            (solver, "max_move_tolerance_mm", "Maximum movement tolerance (mm)", 1e-5),
            (solver, "timeout_seconds", "Solver timeout (s)", 180.0),
        )
        for index, (settings, key, label, default) in enumerate(fields):
            settings[key] = cols[index % 2].number_input(label, value=float(settings.get(key, default)),
                                                        format="%.8g", key=f"{key}_{revision}")
        solver["conjugate_gradient"] = st.checkbox("Conjugate gradient", solver.get("conjugate_gradient", True),
                                                   key=f"cg_{revision}")
        solver["improve_free_surface_mesh"] = st.checkbox("Improve free-surface mesh between retries",
                                                           solver.get("improve_free_surface_mesh", True),
                                                           key=f"mesh_improvement_{revision}")


def guided_configuration(busy, submitted):
    _load_config_controls()
    revision = st.session_state.get("guided_revision", 0)
    if "guided_config" not in st.session_state:
        st.session_state["guided_config"] = guided_base(_default_config(), runner.base_config_path().parent)
    config = copy.deepcopy(st.session_state["guided_config"])
    steps = config["steps"]
    material_settings = steps.setdefault("material_manager", {})
    normalized = normalize_materials(config)
    default_source = str(resolve_path(runner.base_config()["inputs"]["step_file"], runner.base_config_path().parent))
    sources = ["Supplied Pico example", "Upload STEP", "Saved input STEP"]
    source = st.radio("PCB source", sources, index=0 if config["inputs"]["step_file"] == default_source else 2,
                      horizontal=True, key=f"source_{revision}")
    upload = st.file_uploader("PCB assembly", type=["step", "stp"], key=f"step_{revision}") if source == sources[1] else None
    if source == sources[2]:
        st.caption(config["inputs"]["step_file"])
    extraction = steps.setdefault("cad_extractor", {}).setdefault("selection", {})
    extraction["pin_index"] = st.number_input("Connection index", min_value=1, value=extraction.get("pin_index", 1),
                                              step=1, key=f"connection_{revision}")
    material = _material_controls(normalized["material"], revision)
    _preset_controls(config, material)
    material_settings["material"] = material
    simulation = _physics_controls(normalized["simulation"], revision)
    material_settings["simulation"] = simulation
    try:
        preview = normalize_materials(config)
    except ComponentError:
        pass
    else:
        st.caption(f"Effective top-fillet volume {preview['simulation']['effective_fillet_volume_mm3']:.6g} mm³ · "
                   f"Effective pin input angle {preview['material']['effective_pin_contact_angle_deg']:.6g}°")
    fe = steps.setdefault("fe_generator", {})
    solver = steps.setdefault("surface_evolver", {})
    _solver_controls(fe, solver, simulation, revision)
    with st.expander("Numerical outputs", expanded=True):
        options = selected_outputs(solver)
        selected = []
        for category in ("Geometry", "Derived model quantity", "Solver diagnostic"):
            keys = [key for key, metric in OBSERVABLES.items() if metric.category == category]
            selected.extend(st.multiselect(category, keys, [key for key in options if key in keys],
                                          format_func=lambda key: f"{OBSERVABLES[key].label} ({OBSERVABLES[key].unit})",
                                          key=f"{category}_{revision}"))
        solver["outputs"] = selected
        st.caption("Contact angles are mesh estimates along the contact lines. Energy and pressure are derived quantities. "
                   "The solver always records the diagnostics required for its checks.")
    if "measurements_file" in config["inputs"] and not st.checkbox(
            "Carry attached measurements into this run", value=True, key=f"carry_measurements_{revision}"):
        config["inputs"].pop("measurements_file")
    converter = steps.setdefault("cad_converter", {})
    converter["enabled"] = st.checkbox("Export and validate STEP", converter.get("enabled", True), key=f"export_{revision}")
    save_col, copy_col, run_col = st.columns(3)
    save = save_col.button("Save configuration")
    copy_to_editor = copy_col.button(
        "Copy to Advanced JSON",
        help="Replace the Advanced JSON draft with these settings so you can name or edit the run.",
    )
    run = run_col.button("Run experiment", disabled=busy, type="primary")
    try:
        if save or copy_to_editor or run:
            missing = [label.lower() for field, (label, _) in MATERIAL_PROPERTIES.items() if material[field] is None]
            if missing:
                raise ComponentError(f"Enter values for {', '.join(missing)} before continuing.")
            checked = normalize_materials(config)
            build_commands({"body_volume_target": checked["simulation"]["effective_fillet_volume_mm3"],
                            "has_pcbsim_region": True}, solver)
            positive(solver["timeout_seconds"], "Solver timeout")
            positive(fe["boundary_chord_tolerance_mm"], "Boundary chord tolerance")
            positive(fe["initial_perturbation_mm"], "Initial perturbation", allow_zero=True)
            if source == sources[1]:
                if upload is None:
                    raise ValueError("Upload a STEP assembly first.")
                config["inputs"]["step_file"] = str(runner.save_upload(upload.getvalue()).resolve())
            elif source == sources[0]:
                config["inputs"]["step_file"] = default_source
            if copy_to_editor:
                load_guided(config, runner.base_config_path().parent)
                st.session_state["pending_advanced_config"] = config
                st.rerun()
            if save:
                path = save_settings("configurations", config)
                st.session_state["last_guided_save"] = str(path)
                st.rerun()
            if run:
                submitted(runner.start_configured_experiment(config, require_full_checks=(
                    converter["enabled"] and steps.get("evaluation", {}).get("enabled", True))))
    except ERRORS as exc:
        st.error(str(exc))
    if saved := st.session_state.get("last_guided_save"):
        st.caption(f"Last saved configuration · {Path(saved).stem[:8]}")
        json_download("Download saved configuration", runner.load_json(Path(saved)), "pipeline.json", "guided_config_download")
