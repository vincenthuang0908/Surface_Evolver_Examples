"""Browser interface for the PCB experiment pipeline."""
import csv
from datetime import datetime, timezone
from importlib import import_module
import io
import json
from pathlib import Path

import streamlit as st

import job_runner as runner
from configuration import guided_configuration, load_advanced_draft, load_guided
from measurement_workflow import show_measurement_workflow
from tutorial import show_tutorial
from view_3d_results import show_results_viewer

st.set_page_config(page_title="PCB solder experiments", page_icon="🔬", layout="centered")
runner.register_shutdown()

STAGES = {
    "cad_extractor": "Extract connection",
    "material_manager": "Set solder properties",
    "fe_generator": "Generate model",
    "surface_evolver": "Relax solder surface",
    "cad_converter": "Export STEP",
    "evaluation": "Evaluate result",
}
INPUT_UPLOADS = {
    "step_file": ("Original STEP", ("step", "stp")),
    "extracted_step": ("Extracted STEP", ("step", "stp")),
    "geometry_file": ("Geometry JSON", ("json",)),
    "parameters_file": ("Normalized materials JSON", ("json",)),
    "model_file": ("Surface Evolver model", ("fe",)),
    "model_metadata_file": ("Model metadata JSON", ("json",)),
    "solder_mesh_file": ("Solder mesh", ("off",)),
    "metrics_file": ("Solver metrics JSON", ("json",)),
    "measurements_file": ("Measured observations JSON", ("json",)),
}


@st.cache_data(max_entries=6, show_spinner=False)
def download_data(path: str, modified: int) -> bytes:
    return Path(path).read_bytes()


def combined_step(run: Path, report: dict) -> Path | None:
    conversion = report.get("components", {}).get("cad_converter", {})
    relative = conversion.get("outputs", {}).get("combined_step", "output/pcb_with_solder.step")
    path = run / relative
    if not path.is_file():
        path = run / relative.replace("\\", "/")  # Some archived reports use backslashes.
    if path.resolve().is_relative_to((run / "output").resolve()) and path.is_file():
        return path
    return None


def show_experiment(run: Path, active: dict) -> None:
    report = runner.load_json(run / "exp_report.json")
    record = runner.load_json(run / "dashboard.json")
    if active.get("experiment_dir") == str(run):
        record = active
    status = record.get("status") or report.get("status", "starting")
    evaluation = runner.load_json(run / "evaluation/automated_test_results.json")
    metrics = runner.load_json(run / "simulation/metrics.json")
    accepted = report.get("status") == "completed" and evaluation.get("passed") and metrics.get("numerical_pass")
    if status == "completed" and report.get("execution_scope") == "selected_stages":
        st.success("Completed selected stages")
    elif status == "completed" and accepted:
        st.success("Completed · numerical and CAD checks passed")
    elif status in {"failed", "interrupted"}:
        st.error(f"{status.title()}: {record.get('error') or report.get('error') or 'See logs below.'}")
    elif status == "completed":
        st.warning("Execution completed; passing numerical and CAD checks are not confirmed.")
    else:
        st.info("Experiment running. You can leave this page and return later.")
    elapsed = report.get("duration_seconds")
    if elapsed is None and report.get("start_time"):
        elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(report["start_time"])).total_seconds()
    if elapsed is not None:
        st.caption(f"Elapsed: {elapsed:.0f} seconds")
    if report.get("failed_component"):
        st.caption(f"Failed stage: {STAGES.get(report['failed_component'], report['failed_component'])}")
    st.dataframe([
        {"Stage": label, "Status": report.get("components", {}).get(key, {}).get("status", "pending")}
        for key, label in STAGES.items()
    ], hide_index=True, width="stretch")

    outputs = runner.load_json(run / "simulation/selected_outputs.json")
    if outputs:
        rows = outputs["outputs"]
        if rows:
            st.dataframe([
                {"Output": row["label"], "Value": row["value"], "Unit": row["unit"], "Type": row["category"]}
                for row in rows
            ], hide_index=True, width="stretch")
            if any(row["value"] is None for row in rows):
                st.caption("Blank values are unavailable for this model or mesh.")
            csv_buffer = io.StringIO()
            writer = csv.DictWriter(csv_buffer, fieldnames=["metric", "label", "value", "unit", "category"])
            writer.writeheader()
            writer.writerows(rows)
            st.download_button("Download selected outputs (CSV)", csv_buffer.getvalue(),
                               f"{run.name}_outputs.csv", "text/csv", key=f"outputs_csv_{run}", on_click="ignore")
        download_artifact(run, "Download selected outputs (JSON)", run / "simulation/selected_outputs.json", "application/json")
    elif metrics:
        columns = st.columns(3)
        for column, label, key, unit in (
            (columns[0], "Height above pad", "maximum_height_above_pad_mm", "mm"),
            (columns[1], "Top-fillet volume", "fillet_volume_mm3", "mm³"),
            (columns[2], "Total solder volume", "volume_mm3", "mm³"),
        ):
            value = metrics.get(key)
            column.metric(label, f"{value:.6f} {unit}" if value is not None else "—")
        st.caption("These are equilibrium predictions; agreement with real measurements has not been established.")

    exports = (
        ("Download PCB with solder", combined_step(run, report), "application/step"),
        ("Download solder only", run / "output/solder_only.step", "application/step"),
        ("Download saved settings", run / "input/config.original.json", "application/json"),
    )
    for label, path, mime in exports:
        if path:
            download_artifact(run, label, path, mime)
    if st.toggle("Show intermediate files and reports", key=f"artifacts_{run}"):
        for label, relative, mime in (
            ("Connection catalog", "geometry/connections.json", "application/json"),
            ("Geometry", "geometry/geometry.json", "application/json"),
            ("Extracted connection STEP", "geometry/extracted.step", "application/step"),
            ("Normalized materials", "parameters/materials.json", "application/json"),
            ("Surface Evolver model", "fe/model.fe", "text/plain"),
            ("Model metadata", "fe/model.json", "application/json"),
            ("Initial mesh", "fe/initial_mesh.off", "text/plain"),
            ("Relaxed solder mesh", "simulation/solder_mesh.off", "text/plain"),
            ("Solver metrics", "simulation/metrics.json", "application/json"),
            ("Evaluation report", "evaluation/automated_test_results.json", "application/json"),
            ("Effective configuration", "input/config.json", "application/json"),
            ("Experiment report", "exp_report.json", "application/json"),
        ):
            download_artifact(run, label, run / relative, mime)
    with st.expander("Logs and settings"):
        launcher = Path(record.get("log", str(run / "launcher.log")))
        text = runner.tail(run / "experiment.log") or runner.tail(launcher)
        st.code(text or "Waiting for the pipeline to create its log.", language="text")
        solver_log = runner.tail(run / "simulation/stdout.log")
        if solver_log:
            st.caption("Surface Evolver output")
            st.code(solver_log, language="text")
        config = runner.load_json(run / "input/config.original.json")
        if config:
            st.json(config, expanded=False)


def download_artifact(run: Path, label: str, path: Path, mime: str) -> None:
    if path.is_file():
        st.download_button(label, download_data(str(path), path.stat().st_mtime_ns),
                           file_name=f"{run.name}_{path.name}", mime=mime,
                           on_click="ignore", key=f"download_{path}")


def show_submitted_run(record: dict) -> None:
    st.session_state["current_run"] = record["experiment_dir"]
    st.session_state["history_root"] = str(Path(record["experiment_dir"]).parent)
    st.rerun()


def queue_guided_editor(config, base) -> None:
    st.session_state["pending_guided_config"] = (config, base)
    st.rerun()


def load_editor_config() -> None:
    upload = st.session_state.get("config_upload")
    if upload is not None:
        try:
            st.session_state["config_editor"] = upload.getvalue().decode("utf-8-sig")
            st.session_state.pop("config_upload_error", None)
        except UnicodeError:
            st.session_state["config_upload_error"] = "Upload a UTF-8 JSON configuration."


def configured_run(busy: bool) -> None:
    st.file_uploader("Load pipeline JSON", type=["json"], key="config_upload", on_change=load_editor_config)
    if error := st.session_state.get("config_upload_error"):
        st.error(error)
    if "config_editor" not in st.session_state:
        st.session_state["config_editor"] = json.dumps(runner.base_config(), indent=2)
    with st.expander("Attach input files"):
        keys = st.multiselect("Input files to upload", list(INPUT_UPLOADS),
                              format_func=lambda key: INPUT_UPLOADS[key][0], key="config_upload_keys")
        uploads = {
            key: st.file_uploader(INPUT_UPLOADS[key][0], type=INPUT_UPLOADS[key][1], key=f"upload_{key}")
            for key in keys
        }
        st.caption("Uploads replace the matching keys under inputs. Upload the metadata separately with a model, "
                   "or use container paths for the model and its adjacent metadata or dependencies.")
    with st.form("configured_experiment"):
        config_text = st.text_area("Pipeline JSON", height=460, key="config_editor")
        st.caption("Edit inputs, experiments_dir, and stage settings here. Set a stage's enabled field to false to skip it. "
                   "Use steps.cad_converter.output_filename to name the combined STEP.")
        if "config_base" not in st.session_state:
            st.session_state["config_base"] = str(runner.base_config_path().parent)
        base = st.text_input("Base directory for relative paths", key="config_base",
                             help="Use paths inside the container. The host data folder is mounted at /data.")
        experiment_id = st.text_input("Experiment ID", placeholder="Generated when blank", key="config_experiment_id")
        stop_after = st.selectbox("Stop after", [None, *STAGES],
                                  format_func=lambda stage: STAGES[stage] if stage else "Last enabled stage",
                                  key="config_stop_after")
        only = st.multiselect("Run only these stages", list(STAGES), format_func=STAGES.__getitem__,
                              help="Leave empty to run all enabled stages. The pipeline keeps its usual stage order.",
                              key="config_only")
        submitted = st.form_submit_button("Run configured experiment", disabled=busy, type="primary")
    if submitted:
        try:
            config = json.loads(config_text)
            if not isinstance(config, dict) or not isinstance(config.get("inputs", {}), dict):
                raise ValueError("Pipeline JSON and its inputs must be JSON objects.")
            for key, upload in uploads.items():
                if upload is None:
                    raise ValueError(f"Upload {INPUT_UPLOADS[key][0]} or remove it from the upload selection.")
                suffix = "." + INPUT_UPLOADS[key][1][0]
                config.setdefault("inputs", {})[key] = str(runner.save_upload(upload.getvalue(), suffix).resolve())
            show_submitted_run(runner.start_configured_experiment(
                config, config_base=base.strip(), experiment_id=experiment_id.strip() or None,
                stop_after=stop_after, only=only))
        except (ValueError, RuntimeError, OSError) as exc:
            st.error(str(exc))


st.title("PCB solder experiments")


@st.fragment(run_every="2s")
def dashboard() -> None:
    active = runner.active_job()
    if active and active.get("kind") != "calibration":
        st.session_state["current_run"] = active["experiment_dir"]
    shown_run = st.session_state.get("current_run")
    busy = runner.is_busy()
    if shown_run and not busy and not Path(shown_run).is_dir():
        st.session_state.pop("current_run", None)
        shown_run = None
    editor_error = None
    if pending := st.session_state.pop("pending_advanced_config", None):
        load_advanced_draft(json.dumps(pending, indent=2), runner.base_config_path().parent)
    if pending := st.session_state.pop("pending_guided_config", None):
        try:
            load_guided(*pending)
            st.session_state["config_mode"] = "Guided setup"
            st.session_state["experiment_tab"] = "Inputs & Configuration"
        except (ValueError, RuntimeError, OSError) as exc:
            editor_error = str(exc)
    new_tab, history_tab, evaluate_tab, tutorial_tab = st.tabs(
        ["Inputs & Configuration", "Results", "Evaluation & Calibration", "Tutorial & Documentation"],
        key="experiment_tab", on_change="rerun"
    )
    with new_tab:
        if editor_error:
            st.error(editor_error)
        if busy:
            st.info("An experiment or calibration is active. New submissions are available after it finishes.")
        mode = st.selectbox("Configuration mode", ["Guided setup", "Advanced JSON"], key="config_mode")
        if mode == "Advanced JSON":
            configured_run(busy)
        else:
            try:
                guided_configuration(busy, show_submitted_run)
            except (ValueError, RuntimeError, OSError) as exc:
                st.error(str(exc))
        if shown_run:
            st.subheader(Path(shown_run).name)
            show_experiment(Path(shown_run), active)

    with history_tab:
        if "history_root" not in st.session_state:
            last_run = Path(shown_run).parent if shown_run else runner.data_dir() / "experiments"
            st.session_state["history_root"] = str(last_run)
        root = Path(st.text_input("Experiment directory", key="history_root")).expanduser().resolve()
        runs = sorted((p for p in root.iterdir() if p.is_dir() and (p / "exp_report.json").is_file()),
                      key=lambda p: runner.load_json(p / "exp_report.json").get("start_time") or "",
                      reverse=True) if root.is_dir() else []
        if runs:
            choice = st.selectbox("Experiment", runs, format_func=lambda run: run.name, key="history_choice")
            if history_tab.open:
                report = runner.load_json(choice / "exp_report.json")
                show_results_viewer(choice, combined_step(choice, report), report)
            # The current run's status and downloads already appear in Run experiment.
            if not shown_run or Path(shown_run).resolve() != choice:
                show_experiment(choice, active)
        else:
            st.caption("No saved experiments yet.")

    with evaluate_tab:
        show_measurement_workflow(runs, busy, active, queue_guided_editor)

    with tutorial_tab:
        show_tutorial()


workspace = st.segmented_control("Workspace", ["Experiments", "CAD Debug"], default="Experiments",
                                 selection_mode="single")
if workspace == "CAD Debug":
    st.set_page_config(layout="wide")
    import_module("3d_visualize_cad.cad_workspace").show_cad_workspace()
else:
    dashboard()
