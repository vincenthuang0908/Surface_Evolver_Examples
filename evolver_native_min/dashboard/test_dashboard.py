"""Controller/UI tests with a TEST-ONLY process, not a physics simulation."""
import importlib.util
import json
from pathlib import Path
import sys
import time

import psutil
import pytest
from streamlit.testing.v1 import AppTest

sys.path.insert(0, str(Path(__file__).parent))
import job_runner as runner


def wait_until(predicate, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.05)
    raise AssertionError("Timed out waiting for test process")


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    app = tmp_path / "app"
    app.mkdir()
    source = app / "source.step"
    source.write_text("TEST ONLY; not a CAD input")
    config = {"inputs": {"step_file": str(source)}, "steps": {
        "cad_extractor": {"selection": {"pin_index": 1}},
        "material_manager": {"material": {}, "simulation": {}}}}
    base = app / "pipeline.docker.json"
    base.write_text(json.dumps(config))
    monkeypatch.setenv("PCBSIM_APP_DIR", str(app))
    monkeypatch.setenv("PCBSIM_BASE_CONFIG", str(base))
    monkeypatch.setenv("PCBSIM_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PCBSIM_LOCK_PATH", str(tmp_path / "lock"))
    (app / "run_pipeline.py").write_text('''
import argparse, json, os, subprocess, sys, time
from pathlib import Path
p = argparse.ArgumentParser()
p.add_argument('--config'); p.add_argument('--experiment-id')
a = p.parse_args()
c = json.loads(Path(a.config).read_text())
data = Path(c['experiments_dir']).parent
run = Path(c['experiments_dir']) / a.experiment_id
run.mkdir(parents=True)
(run/'exp_report.json').write_text(json.dumps({'status':'running'}))
if os.environ.get('DASHBOARD_TEST_CHILD'):
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], start_new_session=True)
    (data/'child.pid').write_text(str(child.pid))
(data/'ready').write_text('TEST ONLY process ready')
deadline = time.monotonic() + 30
while not (data/'release').exists() and time.monotonic() < deadline:
    time.sleep(.05)
outcome = os.environ.get('DASHBOARD_TEST_OUTCOME', 'success')
if outcome == 'failure':
    (run/'exp_report.json').write_text(json.dumps({'status':'failed', 'error':'TEST ONLY failure'}))
    sys.exit(1)
(run/'simulation').mkdir()
(run/'evaluation').mkdir()
(run/'simulation/metrics.json').write_text(json.dumps({'numerical_pass':outcome != 'rejected'}))
(run/'evaluation/automated_test_results.json').write_text(json.dumps({'passed':outcome != 'rejected'}))
(run/'exp_report.json').write_text(json.dumps({'status':'completed'}))
print('TEST ONLY process completed')
sys.exit(1 if outcome == 'nonzero' else 0)
''')
    yield source, tmp_path / "data"
    runner.shutdown()


def test_rejects_invalid_settings_before_launch(isolated):
    source, data = isolated
    with pytest.raises(RuntimeError, match="positive"):
        runner.start_experiment(source, 1, 0, 80)
    with pytest.raises(RuntimeError, match="between 0 and 180"):
        runner.start_experiment(source, 1, .025, 180)
    assert not data.exists()


def test_lock_and_recovery_across_controllers(isolated):
    source, data = isolated
    record = runner.start_experiment(source, 1, .025, 80)
    wait_until(lambda: (data / "ready").exists())
    assert runner.is_busy()
    with pytest.raises(RuntimeError, match="already running"):
        runner.start_experiment(source, 1, .030, 80)
    spec = importlib.util.spec_from_file_location("another_controller", runner.__file__)
    another = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(another)
    assert another.active_job()["id"] == record["id"]
    assert another.is_busy()
    (data / "release").touch()
    wait_until(lambda: not runner.active_job())
    run = Path(record["experiment_dir"])
    assert (run / "exp_report.json").is_file()
    assert not (run / "launcher.log").exists()
    assert not (run / "dashboard.json").exists()
    assert not Path(record["log"]).exists()
    assert not (data / ".dashboard-active.json").exists()
    assert not (data / ".dashboard-request.json").exists()
    assert not runner.is_busy()
    assert not (data / "jobs").exists()


def test_shutdown_stops_separate_session_solver_child(isolated, monkeypatch):
    source, data = isolated
    monkeypatch.setenv("DASHBOARD_TEST_CHILD", "1")
    record = runner.start_experiment(source, 1, .025, 80)
    wait_until(lambda: (data / "child.pid").exists())
    child = psutil.Process(int((data / "child.pid").read_text()))
    runner.shutdown()
    wait_until(lambda: not child.is_running() or child.status() == psutil.STATUS_ZOMBIE)
    wait_until(lambda: not runner.is_busy())
    assert runner.active_job()["status"] == "interrupted"
    assert not runner._process(record)


def test_stale_process_is_reported_as_interrupted(isolated):
    _, data = isolated
    runner.write_json(data / ".dashboard-active.json", {
        "id": "lost", "status": "running", "pid": 999999999,
        "process_created": 0, "experiment_dir": str(data / "experiments/lost")})
    assert runner.active_job()["status"] == "interrupted"


@pytest.mark.parametrize("outcome", ["failure", "rejected", "nonzero"])
def test_unsuccessful_runs_keep_diagnostics(isolated, monkeypatch, outcome):
    source, data = isolated
    monkeypatch.setenv("DASHBOARD_TEST_OUTCOME", outcome)
    record = runner.start_experiment(source, 1, .025, 80)
    wait_until(lambda: (data / "ready").exists())
    (data / "release").touch()
    wait_until(lambda: runner.active_job().get("status") == "failed")
    run = Path(record["experiment_dir"])
    assert (data / ".dashboard-active.json").exists()
    assert (data / ".dashboard-request.json").exists()
    assert (run / "dashboard.json").exists()
    assert (run / "launcher.log").exists()


def test_old_cleanup_cannot_delete_a_new_submission(isolated):
    _, data = isolated
    run = data / "experiments/previous"
    run.mkdir(parents=True)
    (run / "launcher.log").write_text("old launch log")
    runner.write_json(data / ".dashboard-active.json", {"id": "new"})
    runner.write_json(data / ".dashboard-request.json", {"new": "settings"})
    runner._cleanup_success({"id": "previous", "experiment_dir": str(run)})
    assert runner.load_json(data / ".dashboard-active.json") == {"id": "new"}
    assert runner.load_json(data / ".dashboard-request.json") == {"new": "settings"}
    assert not (run / "launcher.log").exists()


def test_ui_requires_upload_without_starting_process(isolated):
    app = AppTest.from_file(str(Path(__file__).with_name("app.py"))).run()
    assert not app.exception
    app.radio[0].set_value("Upload STEP").run()
    next(button for button in app.button if button.label == "Run experiment").click().run()
    assert not app.exception
    assert any("Upload a STEP" in error.value for error in app.error)
    assert not runner.is_busy()


def test_ui_submit_and_refresh_do_not_duplicate_run(isolated):
    _, data = isolated
    app = AppTest.from_file(str(Path(__file__).with_name("app.py"))).run()
    next(button for button in app.button if button.label == "Run experiment").click().run()
    assert not app.exception
    wait_until(lambda: (data / "ready").exists())
    first = runner.active_job()["id"]
    app.run()
    assert not app.exception
    assert runner.active_job()["id"] == first
    assert next(button for button in app.button if button.label == "Run experiment").disabled
    (data / "release").touch()
    wait_until(lambda: not runner.active_job())
    app.run()
    assert not app.exception
    assert any("Completed" in message.value for message in app.success)
    assert len(list((data / "experiments").iterdir())) == 1
