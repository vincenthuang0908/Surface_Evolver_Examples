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
    base = app / "pipeline.json"
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
p.add_argument('--only', nargs='+'); p.add_argument('--stop-after')
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
if a.only or a.stop_after:
    (run/'exp_report.json').write_text(json.dumps({
        'status':'completed', 'execution_scope':'selected_stages',
        'only':a.only, 'stop_after':a.stop_after}))
    sys.exit(0)
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
    assert first == "run001"
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
    (data / "experiments" / "run004").mkdir()
    next(button for button in app.button if button.label == "Run experiment").click().run()
    next_report = data / "experiments" / "run005" / "exp_report.json"
    wait_until(lambda: runner.load_json(next_report).get("status") == "completed")


def test_ui_advanced_config_paths_and_partial_run(isolated):
    source, data = isolated
    settings = source.with_name("materials.json")
    settings.write_text('{"simulation":{"seed":17}}')
    config = {
        "inputs": {"step_file": "source.step"},
        "experiments_dir": "../data/custom",
        "steps": {"material_manager": {"config_file": "materials.json"}},
    }
    app = AppTest.from_file(str(Path(__file__).with_name("app.py"))).run()
    next(item for item in app.selectbox if item.label == "Configuration mode").set_value("Advanced JSON").run()
    app.text_area[0].set_value(json.dumps(config))
    next(item for item in app.text_input if item.label == "Experiment ID").set_value("materials")
    next(item for item in app.selectbox if item.label == "Stop after").set_value("material_manager")
    next(item for item in app.multiselect if item.label == "Run only these stages").set_value(["material_manager"])
    next(button for button in app.button if button.label == "Run configured experiment").click().run()
    assert not app.exception
    assert not app.error
    wait_until(lambda: (data / "ready").exists())
    run = data / "custom" / "materials"
    assert runner.active_job()["experiment_dir"] == str(run)
    request = runner.load_json(data / ".dashboard-request.json")
    assert request["inputs"]["step_file"] == str(source)
    assert request["steps"]["material_manager"]["config_file"] == str(settings)
    assert request["experiments_dir"] == str(run.parent)
    (data / "release").touch()
    wait_until(lambda: not runner.active_job())
    report = runner.load_json(run / "exp_report.json")
    assert report["only"] == ["material_manager"]
    assert report["stop_after"] == "material_manager"
    app.run()
    assert any("Completed selected stages" in message.value for message in app.success)
    assert next(item for item in app.text_input if item.label == "Experiment directory").value == str(run.parent)
    app.toggle[0].set_value(True).run()
    assert any(button.label == "Experiment report" for button in app.get("download_button"))


@pytest.mark.parametrize("reported_path, filename", [
    ("output/different.stp", "different.stp"),
    (r"output\pcb_with_solder.step", "pcb_with_solder.step"),
])
def test_ui_offers_combined_step_from_run_report(isolated, reported_path, filename):
    _, data = isolated
    run = data / "experiments" / "custom"
    export = run / "output" / filename
    export.parent.mkdir(parents=True)
    export.write_text("TEST ONLY")
    runner.write_json(run / "exp_report.json", {
        "status": "completed",
        "components": {"cad_converter": {"outputs": {"combined_step": reported_path}}},
    })
    app = AppTest.from_file(str(Path(__file__).with_name("app.py"))).run()
    assert not app.exception
    assert any(button.label == "Download PCB with solder" for button in app.get("download_button"))


def test_tutorial_loads_run_six_and_clears_previous_stage_filters(isolated):
    _, data = isolated
    app = AppTest.from_file(str(Path(__file__).with_name("app.py"))).run()
    assert any(tab.label == "Tutorial & Documentation" for tab in app.tabs)
    app.selectbox(key="config_mode").set_value("Advanced JSON").run()
    app.selectbox(key="config_stop_after").set_value("material_manager")
    app.multiselect(key="config_only").set_value(["material_manager"])
    app.text_input(key="config_experiment_id").set_value("previous")
    next(button for button in app.button if button.label == "Load Run 6 into Advanced JSON").click().run()
    assert not app.exception
    assert app.selectbox(key="config_mode").value == "Advanced JSON"
    assert app.selectbox(key="config_stop_after").value is None
    assert app.multiselect(key="config_only").value == []
    assert app.text_input(key="config_experiment_id").value == ""
    config = json.loads(app.text_area(key="config_editor").value)
    assert config["experiments_dir"] == str(data / "experiments")
    assert config["steps"]["cad_extractor"]["selection"]["pin_index"] == 1
    assert config["steps"]["material_manager"]["simulation"]["fillet_volume_mm3"] == 0.025
    assert config["steps"]["surface_evolver"]["minimization_steps"] == 1000
    assert not runner.is_busy()


def test_tutorial_loads_pico_sample_and_submits_from_guided_setup(isolated):
    source, data = isolated
    app = AppTest.from_file(str(Path(__file__).with_name("app.py"))).run()
    app.selectbox(key="config_mode").set_value("Advanced JSON").run()
    next(button for button in app.button if button.label == "Load Pico sample into Guided setup").click().run()
    assert not app.exception and not app.error
    assert app.selectbox(key="config_mode").value == "Guided setup"
    assert app.session_state["experiment_tab"] == "Inputs & Configuration"
    assert app.radio(key="source_1").value == "Supplied Pico example"
    assert app.number_input(key="fillet_volume_mm3_1").value == .025
    assert not runner.is_busy()
    next(button for button in app.button if button.label == "Run experiment").click().run()
    wait_until(lambda: (data / "ready").exists())
    config = runner.read_json(data / ".dashboard-request.json")
    assert config["inputs"]["step_file"] == str(source)
    assert config["steps"]["cad_extractor"]["selection"]["pin_index"] == 1
    assert "pin_apparent_contact_angle_deg" in config["steps"]["surface_evolver"]["outputs"]
    assert config["steps"]["cad_converter"]["enabled"]
    (data / "release").touch()
    wait_until(lambda: not runner.active_job())


def test_tutorial_offers_valid_material_preset(isolated):
    from pcbsim.components.material_manager import MATERIAL_PROPERTIES, normalize_materials

    example = runner.read_json(Path(__file__).with_name("example_material.json"))
    assert example["schema_version"] == 1
    assert MATERIAL_PROPERTIES.keys() <= example["material"].keys()
    material = normalize_materials({"material": example["material"]})["material"]
    assert material["name"] == "Pico tutorial solder"
    assert all(entry["basis"] == "assumed" for entry in material["provenance"].values())
    app = AppTest.from_file(str(Path(__file__).with_name("app.py"))).run()
    assert not app.exception
    assert any(button.label == "Download example material JSON" for button in app.get("download_button"))


def test_copy_guided_setup_to_advanced_json_and_run_with_name(isolated):
    source, data = isolated
    app = AppTest.from_file(str(Path(__file__).with_name("app.py"))).run()
    app.selectbox(key="config_mode").set_value("Advanced JSON").run()
    app.selectbox(key="config_stop_after").set_value("material_manager")
    app.text_input(key="config_experiment_id").set_value("old-draft")
    app.selectbox(key="config_mode").set_value("Guided setup").run()
    app.number_input(key="fillet_volume_mm3_0").set_value(.03)
    app.number_input(key="connection_0").set_value(3)
    app.multiselect(key="Derived model quantity_0").set_value(["liquid_air_surface_energy_J"])
    next(button for button in app.button if button.label == "Copy to Advanced JSON").click().run()
    assert not app.exception and not app.error
    assert app.selectbox(key="config_mode").value == "Advanced JSON"
    assert app.selectbox(key="config_stop_after").value is None
    assert app.text_input(key="config_experiment_id").value == ""
    config = json.loads(app.text_area(key="config_editor").value)
    assert config["inputs"]["step_file"] == str(source)
    assert config["steps"]["cad_extractor"]["selection"]["pin_index"] == 3
    assert config["steps"]["material_manager"]["simulation"]["fillet_volume_mm3"] == .03
    assert "liquid_air_surface_energy_J" in config["steps"]["surface_evolver"]["outputs"]
    assert not runner.is_busy()

    app.text_input(key="config_experiment_id").set_value("named-pico")
    next(button for button in app.button if button.label == "Run configured experiment").click().run()
    wait_until(lambda: (data / "ready").exists())
    assert runner.active_job()["id"] == "named-pico"
    assert runner.read_json(data / ".dashboard-request.json") == config
    (data / "release").touch()
    wait_until(lambda: not runner.active_job())


def test_guided_saves_loads_and_submits_material_physics_and_outputs(isolated):
    _, data = isolated
    app = AppTest.from_file(str(Path(__file__).with_name("app.py"))).run()
    app.selectbox(key="alloy_0").set_value("SAC305").run()
    assert app.number_input(key="surface_tension_N_per_m_0_SAC305").value == .4337
    assert app.number_input(key="density_kg_per_m3_0_SAC305").value == 7290.0
    assert app.number_input(key="pin_contact_angle_deg_0_SAC305").value is None
    assert app.selectbox(key="density_kg_per_m3_0_SAC305_basis").value == "literature"
    for name, value in {"surface_tension_N_per_m": .45, "density_kg_per_m3": 7300.0,
                        "pin_contact_angle_deg": 73.0}.items():
        app.number_input(key=f"{name}_0_SAC305").set_value(value)
    app.number_input(key="gravity_m_per_s2_0").set_value(9.81)
    app.multiselect(key="Derived model quantity_0").set_value(["liquid_air_surface_energy_J"])
    next(button for button in app.button if button.label == "Save configuration").click().run()
    assert not app.exception and not app.error
    saved = next((data / "configurations").glob("*.json"))
    config = runner.read_json(saved)
    assert config["steps"]["material_manager"]["material"]["alloy"] == "SAC305"
    assert config["steps"]["material_manager"]["material"]["surface_tension_N_per_m"] == .45
    assert config["steps"]["material_manager"]["material"]["provenance"]["surface_tension_N_per_m"]["basis"] == "assumed"
    assert config["steps"]["material_manager"]["simulation"]["gravity_m_per_s2"] == 9.81
    assert "liquid_air_surface_energy_J" in config["steps"]["surface_evolver"]["outputs"]
    next(box for box in app.selectbox if box.label == "Saved configuration").set_value(saved).run()
    next(button for button in app.button if button.label == "Load configuration").click().run()
    assert app.number_input(key="gravity_m_per_s2_1").value == 9.81
    next(button for button in app.button if button.label == "Run experiment").click().run()
    assert not app.exception and not app.error
    wait_until(lambda: (data / "ready").exists())
    request = runner.read_json(data / ".dashboard-request.json")
    assert request == config
    (data / "release").touch()
    wait_until(lambda: not runner.active_job())


def test_ui_evaluates_calibrates_and_reloads_settings(isolated, monkeypatch):
    source, data = isolated
    run = data / "experiments" / "example"
    height = "maximum_height_above_pad_mm"
    runner.write_json(run / "exp_report.json", {"status": "completed"})
    runner.write_json(run / "input/config.json", {"inputs": {"step_file": str(source)}, "steps": {}})
    runner.write_json(run / "simulation/metrics.json", {height: .06, "numerical_pass": True})
    runner.write_json(run / "simulation/selected_outputs.json", {"outputs": [
        {"metric": height, "label": "Height", "value": .06, "unit": "mm", "category": "Geometry"},
    ]})
    app = AppTest.from_file(str(Path(__file__).with_name("app.py"))).run()
    next(box for box in app.multiselect if box.label == "Observed quantities").set_value([height]).run()
    scope = f"dataset_{run}"
    app.number_input(key=f"{scope}_{height}").set_value(.05)
    app.number_input(key=f"{scope}_{height}_tolerance").set_value(.02)
    next(button for button in app.button if button.label == "Use measurements").click().run()
    assert not app.exception and not app.error
    next(button for button in app.button if button.label == "Save comparison").click().run()
    receipt = runner.read_json(next((data / "comparisons").glob("*.json")))
    assert receipt["comparison"]["observations"][0]["absolute_percentage_error"] == pytest.approx(20)

    study = data / "calibrations" / "study_test"
    fitted = "steps.material_manager.material.pin_contact_angle_deg"
    captured = {}

    def submit(config_path, measurements, grid):
        captured.update(config=runner.read_json(config_path), measurements=measurements, grid=grid)
        row = {"candidate": 1, "parameters": {fitted: 75}, "score": .25, "measurement_agreement": "passed"}
        runner.write_json(study / "calibration_report.json", {"status": "success", "candidates": [row], "best": row})
        best_config = captured["config"]
        best_config["steps"]["material_manager"]["material"]["pin_contact_angle_deg"] = 75
        runner.write_json(study / "best_pipeline.json", best_config)
        return {"experiment_dir": str(study)}

    monkeypatch.setattr(runner, "start_calibration", submit)
    app.multiselect(key=f"fits_{run}").set_value([fitted]).run()
    app.text_input(key=f"grid_{run}_pin_contact_angle_deg").set_value("75,85")
    next(button for button in app.button if button.label == "Run calibration").click().run()
    assert not app.exception and not app.error
    assert captured["grid"]["parameters"] == {fitted: [75.0, 85.0]}
    assert captured["measurements"]["observations"][height]["value"] == .05
    next(button for button in app.button if button.label == "Load best-fit settings for rerun").click().run()
    assert app.number_input(key="pin_contact_angle_deg_1_None").value == 75

    next(button for button in app.button if button.label == "Edit settings and rerun").click().run()
    assert not app.exception and not app.error
    assert app.session_state["experiment_tab"] == "Inputs & Configuration"
    config = app.session_state["guided_config"]
    assert config["inputs"]["step_file"] == str(source)
    observations = runner.read_json(Path(config["inputs"]["measurements_file"]))["observations"]
    assert observations[height]["value"] == .05
    assert config["steps"]["evaluation"]["require_measurement_agreement"] is False
