"""Dashboard workflow for comparing measurements and rerunning fitted settings."""
from __future__ import annotations

from pathlib import Path

import streamlit as st

import job_runner as runner
from configuration import ERRORS, guided_base, json_download, json_upload, save_settings, saved_files
from pcbsim.common import ComponentError, sha256
from pcbsim.components.calibration import FIT_PARAMETERS
from pcbsim.components.evaluation import MEASURABLE, compare_measurements, measurements_from_csv, validate_measurements
from pcbsim.components.experiment_manager import requested_stages
from pcbsim.components.material_manager import normalize_materials
from pcbsim.components.observables import OBSERVABLES


def _metric_label(key):
    metric = OBSERVABLES[key]
    return f"{metric.label} ({metric.unit})"


def _dataset_controls(run, allowed):
    scope = f"dataset_{run}"
    if scope not in st.session_state and (saved := runner.load_json(run / "input/measurements.json")):
        try:
            st.session_state[scope] = validate_measurements(saved, allowed=allowed)
        except ComponentError:
            pass  # Advanced CLI runs may contain observations outside the guided output selection.
    with st.expander("Enter or load measurements", expanded=True):
        source = st.radio("Measurement input", ["Enter values", "Upload JSON or CSV", "Saved dataset"],
                          horizontal=True, key=f"{scope}_input")
        if source == "Enter values":
            keys = st.multiselect("Observed quantities", allowed, format_func=_metric_label, key=f"{scope}_keys")
            with st.form(f"{scope}_manual"):
                reference = st.text_input("Measurement source and conditions",
                                          help="Record a specimen ID, instrument, datum, and measurement method.")
                observations = {}
                for key in keys:
                    value, tolerance = st.columns(2)
                    observations[key] = {
                        "value": value.number_input(_metric_label(key), value=None, format="%.8g", key=f"{scope}_{key}"),
                        "absolute_tolerance": tolerance.number_input(
                            f"Absolute tolerance ({OBSERVABLES[key].unit})", value=None, format="%.8g",
                            key=f"{scope}_{key}_tolerance"),
                    }
                if st.form_submit_button("Use measurements", disabled=not keys):
                    _use_dataset(scope, {"source": reference, "observations": observations}, allowed)
        elif source == "Upload JSON or CSV":
            upload = st.file_uploader("Measured observations", type=["json", "csv"], key=f"{scope}_upload")
            st.caption("CSV columns are metric, value, unit, and absolute_tolerance. Use the metric keys below.")
            st.code(", ".join(allowed), language=None)
            if st.button("Use uploaded measurements", disabled=upload is None, key=f"{scope}_read_upload"):
                try:
                    if upload.name.lower().endswith(".csv"):
                        data = measurements_from_csv(upload.getvalue().decode("utf-8-sig"))
                        data["source"] = upload.name
                    else:
                        data = json_upload(upload)
                    _use_dataset(scope, data, allowed)
                except ERRORS as exc:
                    st.error(str(exc))
        else:
            paths = saved_files("measurements")
            if (run / "input/measurements.json").is_file():
                paths.insert(0, run / "input/measurements.json")
            selection = st.selectbox("Saved observations", [None, *paths], key=f"{scope}_saved",
                                     format_func=lambda path: (
                                         f"{runner.load_json(path).get('source') or 'Dataset'} · {path.stem[:12]}"
                                         if path else "Choose observations"))
            if st.button("Use saved measurements", disabled=selection is None, key=f"{scope}_read_saved"):
                try:
                    _use_dataset(scope, runner.read_json(selection), allowed)
                except ERRORS as exc:
                    st.error(str(exc))
    return st.session_state.get(scope)


def _use_dataset(scope, dataset, allowed):
    try:
        st.session_state[scope] = validate_measurements(dataset, allowed=allowed)
    except ComponentError as exc:
        st.error(str(exc))


def _comparison(run, metrics, measurements):
    if not metrics.get("numerical_pass"):
        st.warning("The solver checks did not pass. This comparison is diagnostic.")
    if metrics.get("pin_height_limit_reached"):
        st.warning("The relaxed surface reached the straight-pin height limit. The excluded pin tip may affect these predictions.")
    comparison = compare_measurements(metrics, measurements)
    rows = [{
        "Observable": _metric_label(row["metric"]), "Prediction": row["predicted"], "Measured": row["measured"],
        "Absolute error": row["absolute_difference"], "Absolute error (%)": row["absolute_percentage_error"],
        "Tolerance": row["absolute_tolerance"], "Within tolerance": row["passed"],
        "Signed error / tolerance": row["signed_error_over_tolerance"],
    } for row in comparison["observations"]]
    if measurements.get("source"):
        st.caption(f"Dataset source · {measurements['source']}")
    st.dataframe(rows, hide_index=True, width="stretch")
    st.bar_chart(rows, x="Observable", y="Signed error / tolerance", horizontal=True)
    st.caption(f"Mean squared error in tolerance units · {comparison['mean_normalized_squared_error']:.5g}. "
               "Bars within ±1 meet the tolerance. Percentage error is undefined when the measured value is zero.")
    left, right = st.columns(2)
    receipt = {
        "schema_version": 1, "experiment": str(run), "measurements": measurements,
        "metrics_sha256": sha256(run / "simulation/metrics.json"), "comparison": comparison,
    }
    if left.button("Save dataset", key=f"save_data_{run}"):
        path = save_settings("measurements", measurements)
        left.success(f"Saved dataset · {path.stem[:12]}")
    if right.button("Save comparison", key=f"save_comparison_{run}"):
        path = save_settings("comparisons", receipt)
        right.success(f"Saved comparison · {path.stem[:12]}")
    json_download("Download dataset", measurements, "measurements.json", f"dataset_download_{run}")
    json_download("Download comparison", receipt, f"{run.name}_comparison.json", f"comparison_download_{run}")


def _calibration_controls(run, metrics, measurements, busy, queue_editor):
    baseline = run / "input/config.json"
    config = runner.load_json(baseline)
    if not config:
        st.caption("Rerunning this experiment requires its saved effective configuration.")
        return
    stages = requested_stages(config)
    if not {"cad_extractor", "material_manager", "fe_generator", "surface_evolver"}.issubset(stages):
        st.caption("Guided reruns and fitting require an experiment generated from STEP geometry.")
        return
    normalized = normalize_materials(config)
    material = normalized["material"]
    simulation = normalized["simulation"]
    if st.button("Edit settings and rerun", key=f"manual_rerun_{run}"):
        if measurements:
            config["inputs"]["measurements_file"] = str(save_settings("measurements", measurements).resolve())
            config["steps"].setdefault("evaluation", {})["require_measurement_agreement"] = False
        queue_editor(config, baseline.parent)
    with st.expander("Automated parameter optimization"):
        if not measurements:
            st.caption("Load a measurement dataset to define the objective.")
            return
        st.write("Try a grid of candidate values and minimize the mean squared error in tolerance units.")
        st.caption("At zero gravity, density and surface tension do not affect the predicted geometry. "
                   "A pinned pin contact line makes its Young angle ineffective. "
                   "Fitting volume uses a prescribed quantity and may mask errors in shape.")
        choices = st.multiselect("Parameters to fit", FIT_PARAMETERS.keys(), key=f"fits_{run}",
                                 format_func=lambda path: FIT_PARAMETERS[path][0])
        with st.form(f"grid_{run}"):
            values = {}
            for path in choices:
                label, property_key = FIT_PARAMETERS[path]
                baseline_value = (material if ".material." in path else simulation)[property_key]
                values[path] = st.text_input(label, f"{baseline_value:g}", key=f"grid_{run}_{property_key}",
                                             help="Comma-separated candidate values in the stated units.")
            limit = st.number_input("Maximum candidate simulations", min_value=1, max_value=1000, value=16, step=1)
            launch = st.form_submit_button("Run calibration", disabled=busy or not metrics.get("numerical_pass") or not choices)
        if launch:
            grid = {}
            total = 1
            for path, entered in values.items():
                try:
                    candidates = [float(item) for item in entered.split(",")]
                except ValueError as exc:
                    raise ComponentError(f"Enter comma-separated numbers for {FIT_PARAMETERS[path][0]}.") from exc
                if len(candidates) != len(set(candidates)):
                    raise ComponentError(f"Candidate values for {FIT_PARAMETERS[path][0]} must be distinct.")
                grid[path] = candidates
                total *= len(candidates)
            if total > limit:
                raise ComponentError(f"The grid contains {total} candidates and the limit is {limit}.")
            # Material values may have come from defaults or top-level overrides.
            # Write explicit step values before fitting without changing the reference run.
            prepared = config["steps"].setdefault("material_manager", {})
            prepared["material"] = material
            prepared["simulation"] = simulation
            snapshot = save_settings("calibration_baselines", guided_base(config, baseline.parent))
            record = runner.start_calibration(snapshot, measurements, {
                "parameters": grid, "maximum_runs": limit, "require_cad_validation": "cad_converter" in stages,
            })
            st.session_state["calibration_study"] = record["experiment_dir"]
            st.rerun()


def _show_studies(active, queue_editor):
    st.subheader("Calibration history")
    root = runner.data_dir() / "calibrations"
    studies = sorted(root.glob("study_*"), reverse=True)
    current = active.get("experiment_dir") if active.get("kind") == "calibration" else None
    current = current or st.session_state.get("calibration_study")
    if current and Path(current) not in studies:
        studies.insert(0, Path(current))
    if not studies:
        st.caption("No calibration studies yet.")
        return
    study = st.selectbox("Study", studies, format_func=lambda path: path.name)
    report = runner.load_json(study / "calibration_report.json")
    local = active if active.get("experiment_dir") == str(study) else runner.load_json(study / "dashboard.json")
    if local.get("status") in {"failed", "interrupted"}:
        st.error(local.get("error") or "Calibration ended before completion.")
    elif local.get("status") in runner.BUSY_STATES:
        st.progress(len(report.get("candidates", [])) / report.get("total_candidates", 1),
                    text="Running candidate simulations")
    elif report.get("status") == "running":
        st.warning("This study ended before completion. Candidate results below are partial.")
    if report:
        rows = [{
            "Candidate": row["candidate"], "Values": ", ".join(f"{key.rsplit('.', 1)[-1]} = {value}"
                                                               for key, value in row["parameters"].items()),
            "Score": row.get("score"), "Agreement": row.get("measurement_agreement"), "Exclusion": row.get("reason"),
            "Experiment": row.get("experiment_dir"),
        } for row in report["candidates"]]
        if rows:
            st.dataframe(rows, hide_index=True, width="stretch")
        if best := report.get("best"):
            st.write(f"Best eligible candidate · {best['candidate']} · score {best['score']:.5g} · "
                     f"measurement agreement {best['measurement_agreement']}")
            if report["status"] == "success":
                best_path = study / "best_pipeline.json"
                config = runner.load_json(best_path)
                if config:
                    json_download("Download best-fit configuration", config, "best_pipeline.json", "best_fit_download")
                    if st.button("Load best-fit settings for rerun"):
                        queue_editor(config, best_path.parent)
        json_download("Download calibration history", report, "calibration_report.json", "calibration_download")
    if local.get("status") in {"failed", "interrupted"}:
        log = runner.tail(Path(local.get("log", study / "launcher.log")))
        if log:
            with st.expander("Calibration log"):
                st.code(log, language="text")


def show_measurement_workflow(runs, busy, active, queue_editor):
    eligible = [run for run in runs if (run / "simulation/metrics.json").is_file()]
    if not eligible:
        st.info("Run a simulation to compare its selected geometry outputs with measurements.")
    else:
        run = st.selectbox("Experiment to evaluate", eligible, format_func=lambda path: path.name)
        metrics = runner.load_json(run / "simulation/metrics.json")
        outputs = runner.load_json(run / "simulation/selected_outputs.json")
        if outputs:
            allowed = [row["metric"] for row in outputs["outputs"] if row["value"] is not None and row["metric"] in MEASURABLE]
        else:
            allowed = [key for key in OBSERVABLES if key in MEASURABLE and metrics.get(key) is not None]
            metadata = runner.load_json(run / "simulation/model_metadata.json") or runner.load_json(run / "fe/model.json")
            if metadata.get("kind") != "pcbsim_through_hole" and "maximum_height_above_pad_mm" in allowed:
                allowed.remove("maximum_height_above_pad_mm")
        try:
            measurements = _dataset_controls(run, allowed) if allowed else None
            if measurements:
                _comparison(run, metrics, measurements)
            elif not allowed:
                st.caption("This run has no selected geometry outputs available for measurement comparison.")
            _calibration_controls(run, metrics, measurements, busy, queue_editor)
        except ERRORS as exc:
            st.error(str(exc))
    try:
        _show_studies(active, queue_editor)
    except ERRORS as exc:
        st.error(str(exc))
