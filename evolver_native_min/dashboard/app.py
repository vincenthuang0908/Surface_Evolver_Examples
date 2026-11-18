"""Minimal browser interface for the existing PCB experiment pipeline."""
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

import job_runner as runner

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


@st.cache_data(max_entries=6, show_spinner=False)
def download_data(path: str, modified: int) -> bytes:
    return Path(path).read_bytes()


def show_experiment(run: Path, active: dict) -> None:
    report = runner.load_json(run / "exp_report.json")
    record = runner.load_json(run / "dashboard.json")
    if active.get("id") == run.name:
        record = active
    status = record.get("status") or report.get("status", "starting")
    evaluation = runner.load_json(run / "evaluation/automated_test_results.json")
    metrics = runner.load_json(run / "simulation/metrics.json")
    accepted = report.get("status") == "completed" and evaluation.get("passed") and metrics.get("numerical_pass")
    if status == "completed" and accepted:
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

    if metrics:
        columns = st.columns(3)
        for column, label, key, unit in (
            (columns[0], "Height above pad", "maximum_height_above_pad_mm", "mm"),
            (columns[1], "Top-fillet volume", "fillet_volume_mm3", "mm³"),
            (columns[2], "Total solder volume", "volume_mm3", "mm³"),
        ):
            value = metrics.get(key)
            column.metric(label, f"{value:.6f} {unit}" if value is not None else "—")
        st.caption("These are equilibrium predictions; agreement with real measurements has not been established.")

    for label, relative, mime in (
        ("Download PCB with solder", "output/pcb_with_solder.step", "application/step"),
        ("Download solder only", "output/solder_only.step", "application/step"),
        ("Download saved settings", "input/config.original.json", "application/json"),
    ):
        path = run / relative
        if path.is_file():
            st.download_button(label, download_data(str(path), path.stat().st_mtime_ns),
                               file_name=f"{run.name}_{path.name}", mime=mime, on_click="ignore",
                               key=f"download_{run.name}_{relative}")
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


st.title("PCB solder experiments")
st.caption("Run one through-hole solder experiment and download its CAD results.")


@st.fragment(run_every="2s")
def dashboard() -> None:
    active = runner.active_job()
    if active:
        st.session_state["current_run"] = active["experiment_dir"]
    shown_run = st.session_state.get("current_run")
    busy = runner.is_busy()
    new_tab, history_tab = st.tabs(["Run experiment", "Experiments"])
    with new_tab:
        if busy:
            st.info("An experiment is active. New submissions are available after it finishes.")
        source = st.radio("PCB source", ["Supplied Pico example", "Upload STEP"], horizontal=True, key="source")
        upload = None
        if source == "Upload STEP":
            upload = st.file_uploader("PCB assembly", type=["step", "stp"], key="upload")
        with st.form("experiment"):
            pin = st.number_input("Connection index", min_value=1, value=1, step=1,
                                  help="Geometric catalog index, not an electrical pin number. The Pico example has 40 connections.")
            volume = st.number_input("Top-fillet solder volume (mm³)", min_value=0.000001,
                                     value=0.025, step=0.005, format="%.6f")
            angle = st.number_input("Pin contact angle (degrees)", min_value=0.1, max_value=179.9,
                                    value=80.0, step=1.0)
            submitted = st.form_submit_button("Run experiment", disabled=busy, type="primary")
        with st.expander("Model assumptions"):
            st.write("One top-side fillet; full barrel; mobile pin contact line; fixed pad perimeter; gravity disabled. "
                     "Material and solver settings use the verified baseline. Material values are illustrative.")
            st.write("STEP geometry must have a horizontal PCB, vertical circular plated holes, and aligned rectangular pins. "
                     "Unsupported geometry is reported during extraction.")
        if submitted:
            try:
                if source == "Upload STEP":
                    if upload is None:
                        raise ValueError("Upload a STEP assembly first.")
                    step = runner.save_upload(upload.getvalue())
                else:
                    step = Path(runner.base_config()["inputs"]["step_file"])
                active = runner.start_experiment(step, int(pin), float(volume), float(angle))
                st.session_state["current_run"] = active["experiment_dir"]
                st.rerun()
            except (ValueError, RuntimeError, OSError) as exc:
                st.error(str(exc))
        if shown_run:
            st.subheader(Path(shown_run).name)
            show_experiment(Path(shown_run), active)

    with history_tab:
        root = runner.data_dir() / "experiments"
        runs = sorted((p for p in root.iterdir() if p.is_dir() and (p / "exp_report.json").is_file()),
                      key=lambda p: p.stat().st_mtime, reverse=True) if root.exists() else []
        if runs:
            choice = st.selectbox("Experiment", [p.name for p in runs], key="history_choice")
            # Separate keys when the same active result appears in both tabs.
            if shown_run and Path(shown_run).name == choice:
                st.info("This experiment's results are shown in Run experiment.")
            else:
                show_experiment(root / choice, active)
        else:
            st.caption("No saved experiments yet.")


dashboard()
