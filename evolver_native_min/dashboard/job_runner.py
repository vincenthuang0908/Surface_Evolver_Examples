"""Small Linux/Docker process controller; simulation remains in pcbsim."""
from __future__ import annotations

import atexit
import copy
import fcntl
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
import uuid

import psutil

from pcbsim.common import ComponentError, expand_step_configs, integer, read_json, resolve_path, utc_now, write_json
from pcbsim.components.experiment_manager import requested_stages, validate_experiment_id
from pcbsim.components.material_manager import normalize_materials

_state_lock = threading.RLock()
_monitors: dict[str, threading.Thread] = {}
_shutdown_registered = False
BUSY_STATES = {"starting", "running"}


def data_dir() -> Path:
    return Path(os.environ.get("PCBSIM_DATA_DIR", "/data"))


def app_dir() -> Path:
    return Path(os.environ.get("PCBSIM_APP_DIR", "/app"))


def base_config_path() -> Path:
    return Path(os.environ.get("PCBSIM_BASE_CONFIG", str(app_dir() / "pipeline.json"))).resolve()


def base_config() -> dict:
    return read_json(base_config_path())


def load_json(path: Path) -> dict:
    try:
        return read_json(path)
    except ComponentError:
        return {}


def _state_path() -> Path:
    return data_dir() / ".dashboard-active.json"


def _lock_path() -> Path:
    return Path(os.environ.get("PCBSIM_LOCK_PATH", "/tmp/pcbsim-dashboard.lock"))


def _process(record: dict) -> psutil.Process | None:
    """Check creation time too, so an unrelated reused PID is never controlled."""
    if not record.get("pid") or record.get("process_created") is None:
        return None
    try:
        process = psutil.Process(record["pid"])
        if (abs(process.create_time() - record["process_created"]) < .001
                and process.is_running() and process.status() != psutil.STATUS_ZOMBIE):
            return process
    except psutil.Error:
        pass
    return None


def _successful(run: Path, report: dict, record: dict) -> bool:
    return (report.get("status") == "completed"
            and (not record.get("require_full_checks", True)
                 or (load_json(run / "simulation/metrics.json").get("numerical_pass") is True
                     and load_json(run / "evaluation/automated_test_results.json").get("passed") is True)))


def _same_job(first: dict, second: dict) -> bool:
    if "submission_id" in first or "submission_id" in second:
        return first.get("submission_id") == second.get("submission_id")
    return (first.get("id"), first.get("experiment_dir")) == (second.get("id"), second.get("experiment_dir"))


def _cleanup_success(record: dict) -> None:
    """Remove only dashboard bookkeeping; experiment inputs/results stay intact."""
    run = Path(record["experiment_dir"])
    if not run.is_absolute() or run.name != record["id"]:
        return
    launch_id = record.get("submission_id", record["id"])
    for path in (data_dir() / f".{launch_id}.launcher.log", run / "launcher.log", run / "dashboard.json"):
        path.unlink(missing_ok=True)
    # A new submission can start as soon as the pipeline exits. Never remove
    # its shared request/state, even if the previous monitor finishes later.
    with _lock_path().open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        if _same_job(load_json(_state_path()), record):
            (data_dir() / ".dashboard-request.json").unlink(missing_ok=True)
            _state_path().unlink(missing_ok=True)


def active_job() -> dict:
    with _state_lock:
        record = load_json(_state_path())
        if record.get("status") == "completed" and _process(record) is None:
            run = Path(record["experiment_dir"])
            if _successful(run, load_json(run / "exp_report.json"), record):
                _cleanup_success(record)
                return {}
        if record.get("status") not in BUSY_STATES:
            return record
        if _process(record) is not None:
            return record
        monitor = _monitors.get(record.get("submission_id", record.get("id")))
        if monitor is not None and monitor.is_alive():
            return record  # Let the monitor capture the actual exit code first.
        if not record.get("pid") and time.time() - record.get("submitted_epoch", 0) < 10:
            return record
        run = Path(record["experiment_dir"])
        report = load_json(run / "exp_report.json")
        if _successful(run, report, record):
            _cleanup_success(record)
            return {}
        record["status"] = "failed" if report.get("status") in {"completed", "failed"} else "interrupted"
        record["error"] = report.get("error") or (
            "The pipeline process stopped before completing." if record["status"] == "interrupted" else None)
        record["finished_at"] = utc_now()
        write_json(_state_path(), record)
        return record


def is_busy() -> bool:
    """The OS lock covers all browser sessions and survives a UI process restart."""
    with _lock_path().open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
    return False


def save_upload(content: bytes, suffix: str = ".step") -> Path:
    if not content:
        raise ValueError("The uploaded file is empty.")
    path = data_dir() / "uploads" / (hashlib.sha256(content).hexdigest() + suffix)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation avoids concurrent uploads truncating an existing input.
    with _state_lock:
        try:
            with path.open("xb") as stream:
                stream.write(content)
        except FileExistsError:
            if path.read_bytes() != content:
                raise ValueError("Stored upload does not match its content hash.")
    return path


def _finish(process: subprocess.Popen, record: dict) -> None:
    code = process.wait()  # A controller thread waits; the Streamlit UI never does.
    with _state_lock:
        current = load_json(_state_path())
        report = load_json(Path(record["experiment_dir"]) / "exp_report.json")
        interrupted = _same_job(current, record) and current.get("status") == "interrupted"
        if not interrupted and code == 0 and _successful(Path(record["experiment_dir"]), report, record):
            _cleanup_success(record)
            return
        record.update(status="interrupted" if interrupted else
                      "failed",
                      returncode=code, finished_at=utc_now())
        record["error"] = (current.get("error") if interrupted else
                           report.get("error") or (f"Pipeline exited with code {code}." if code else
                                                   "Pipeline did not pass all numerical and CAD checks."))
        run = Path(record["experiment_dir"])
        if run.is_dir():
            log = Path(record["log"])
            destination = run / "launcher.log"
            if log.exists():
                shutil.move(str(log), destination)
                record["log"] = str(destination)
            write_json(run / "dashboard.json", record)
        if _same_job(current, record):
            write_json(_state_path(), record)


def start_experiment(source: Path, pin_index: int, volume: float, angle: float) -> dict:
    config = base_config()
    source = source.resolve()
    if not source.is_file():
        raise ValueError("Choose an existing STEP file.")
    config["inputs"]["step_file"] = str(source)
    config["experiments_dir"] = str(data_dir() / "experiments")
    config["steps"]["cad_extractor"]["selection"]["pin_index"] = integer(pin_index, "Connection index", 1)
    config["steps"]["material_manager"]["simulation"]["fillet_volume_mm3"] = volume
    config["steps"]["material_manager"]["material"]["pin_contact_angle_deg"] = angle
    return start_configured_experiment(config, require_full_checks=True)


def start_configured_experiment(config: dict, *, config_base: str | Path | None = None,
                                experiment_id: str | None = None, stop_after: str | None = None,
                                only: list[str] | None = None, require_full_checks: bool = False) -> dict:
    """Rebase browser configuration before staging it in the shared data directory."""
    base = resolve_path(config_base or base_config_path().parent, app_dir())
    config = copy.deepcopy(config)
    expanded = expand_step_configs(config, base)
    stages = requested_stages(expanded, stop_after=stop_after, only=only)
    if "material_manager" in stages:
        normalize_materials(expanded)
    validate_experiment_id(experiment_id)

    for key, value in config.get("inputs", {}).items():
        if key != "model_dependencies":
            config["inputs"][key] = str(resolve_path(value, base))
    for settings in config.get("steps", {}).values():
        if "config_file" in settings:
            settings["config_file"] = str(resolve_path(settings["config_file"], base))
    executable = expanded.get("steps", {}).get("surface_evolver", {}).get("executable")
    if executable is not None and not isinstance(executable, str):
        raise ValueError("The Surface Evolver executable must be a path or command name.")
    if executable and ("/" in executable or "\\" in executable):
        config["steps"]["surface_evolver"]["executable"] = str(resolve_path(executable, base))
    output_dir = config.get("experiments_dir", str(data_dir() / "experiments"))
    if not isinstance(output_dir, str) or not output_dir.strip():
        raise ValueError("experiments_dir must be a directory path.")
    root = resolve_path(output_dir, base)
    config["experiments_dir"] = str(root)

    with _lock_path().open("a+") as lock, _state_lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("An experiment is already running. Wait for it to finish.") from exc
        submission_id = uuid.uuid4().hex
        run_id = experiment_id or time.strftime("run_%Y%m%d_%H%M%S_") + submission_id[:8]
        run = root / run_id
        if run.exists() or run.is_symlink():
            raise ValueError(f"Experiment already exists: {run}")
        data_dir().mkdir(parents=True, exist_ok=True)
        config_path = data_dir() / ".dashboard-request.json"
        write_json(config_path, config)
        record = dict(id=run_id, submission_id=submission_id, status="starting", submitted_at=utc_now(),
                      submitted_epoch=time.time(), experiment_dir=str(run), require_full_checks=require_full_checks,
                      log=str(data_dir() / f".{submission_id}.launcher.log"))
        write_json(_state_path(), record)
        command = [sys.executable, str(app_dir() / "run_pipeline.py"),
                   "--config", str(config_path), "--experiment-id", run_id]
        if stop_after:
            command.extend(["--stop-after", stop_after])
        if only:
            command.extend(["--only", *only])
        try:
            with Path(record["log"]).open("w", encoding="utf-8") as log:
                process = subprocess.Popen(
                    command,
                    cwd=app_dir(), stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                    start_new_session=True, pass_fds=(lock.fileno(),))
            record.update(pid=process.pid, process_created=psutil.Process(process.pid).create_time(), status="running")
            write_json(_state_path(), record)
        except Exception as exc:
            if "process" in locals():
                _terminate(process.pid)
                process.wait()
            record.update(status="failed", error=f"Unable to launch pipeline: {exc}", finished_at=utc_now())
            write_json(_state_path(), record)
            raise RuntimeError(record["error"]) from exc
        for previous, monitor in list(_monitors.items()):
            if not monitor.is_alive():
                _monitors.pop(previous)
        monitor = threading.Thread(target=_finish, args=(process, record.copy()), daemon=True)
        _monitors[submission_id] = monitor
        monitor.start()
        # Closing only our FD leaves the inherited lock held by the pipeline
        # until it exits, even if Streamlit is refreshed or unexpectedly stops.
        return record


def _terminate(pid: int) -> None:
    try:
        parent = psutil.Process(pid)
        processes = parent.children(recursive=True)[::-1] + [parent]
    except psutil.Error:
        return
    for process in processes:
        try:
            process.terminate()
        except psutil.Error:
            pass
    _, alive = psutil.wait_procs(processes, timeout=3)
    for process in alive:
        try:
            process.kill()
        except psutil.Error:
            pass
    psutil.wait_procs(alive, timeout=2)


def shutdown() -> None:
    with _state_lock:
        record = load_json(_state_path())
        process = _process(record)
        if process is None:
            return
        record.update(status="interrupted", error="Dashboard server stopped.", finished_at=utc_now())
        write_json(_state_path(), record)
    _terminate(process.pid)  # Includes the solver, which starts its own session.


def register_shutdown() -> None:
    global _shutdown_registered
    if not _shutdown_registered:
        atexit.register(shutdown)
        _shutdown_registered = True


def tail(path: Path, limit: int = 12000) -> str:
    try:
        with path.open("rb") as stream:
            stream.seek(0, 2)
            stream.seek(max(0, stream.tell() - limit))
            return stream.read().decode("utf-8", errors="replace")
    except OSError:
        return ""
