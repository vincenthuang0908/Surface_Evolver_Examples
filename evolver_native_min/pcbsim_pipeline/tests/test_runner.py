from pathlib import Path
import pytest
from pcbsim.common import ComponentError, read_json, write_json
from pcbsim.components.surface_evolver_runner import run_surface_evolver, build_commands
from pcbsim._vendor.evolver_native.native import parse_output
from conftest import protocol_output

@pytest.fixture
def model(tmp_path):
    path=tmp_path/'model.fe';path.write_text('// TEST ONLY: not executable FE input\n')
    write_json(path.with_suffix('.json'),{'body_volume_target':1/6,'body_id':1,'mesh_contract':'closed_shell'})
    return path

def test_saved_actual_legacy_stdout_is_parsed():
    root=Path(__file__).parent/'fixtures'
    metrics,v,f=parse_output((root/'legacy_pin_stdout.log').read_text())
    saved=read_json(root/'legacy_pin_manifest.json')['metrics']
    for name in ['energy','volume','pressure','facets']:assert metrics[name]==pytest.approx(saved[name])
    assert len(f)==int(metrics['facets'])

def test_command_adaptation():
    text=build_commands({'body_volume_target':1,'body_id':2},{'warmup_steps':11,'minimization_steps':43,'refinements':1})
    assert 'body[2].volume' in text and 'body[1]' not in text
    assert 'g 11' in text and 'g 43' in text
    assert '\nu\n' not in text

@pytest.mark.protocol
def test_protocol_success(model,tmp_path,tetrahedron,fake_native_process):
    fake_native_process['text']=protocol_output(*tetrahedron)
    report=run_surface_evolver(model,{},tmp_path/'out')
    assert report['status']=='success' and report['numerical_pass']
    metrics=read_json(tmp_path/'out/metrics.json')
    assert metrics['volume_mm3']==pytest.approx(1/6)
    assert not metrics['physical_validation']
    assert (tmp_path/'out/solder_mesh.off').is_file()
    with pytest.raises(ComponentError,match='reuse'):run_surface_evolver(model,{},tmp_path/'out')

@pytest.mark.protocol
@pytest.mark.parametrize('failure',['missing_sentinel','warning','nan','returncode','missing_metric'])
def test_bad_protocol_fails(model,tmp_path,tetrahedron,fake_native_process,failure):
    text=protocol_output(*tetrahedron)
    if failure=='missing_sentinel':text=text.replace('LAB_COMPLETE 1','')
    if failure=='warning':text+='WARNING 123: test warning\n'
    if failure=='nan':text=text.replace('LAB_ENERGY 0.5','LAB_ENERGY nan')
    if failure=='returncode':fake_native_process['returncode']=1
    if failure=='missing_metric':text=text.replace('LAB_PRESSURE 2','')
    fake_native_process['text']=text
    report=run_surface_evolver(model,{},tmp_path/'out')
    assert report['status']=='failed'
    assert read_json(tmp_path/'out/runner_report.json')['status']=='failed'

@pytest.mark.protocol
def test_numerical_gate_blocks_success(model,tmp_path,tetrahedron,fake_native_process):
    fake_native_process['text']=protocol_output(*tetrahedron,energy_drift=.01)
    report=run_surface_evolver(model,{},tmp_path/'out')
    assert report['status']=='failed' and not report['numerical_pass']
    assert (tmp_path/'out/metrics.json').is_file()

@pytest.mark.protocol
def test_timeout_preserves_log(model,tmp_path,fake_native_process):
    fake_native_process['timeout']=True
    report=run_surface_evolver(model,{},tmp_path/'out')
    assert report['status']=='timeout' and fake_native_process['stopped']
    assert 'partial' in (tmp_path/'out/stdout.log').read_text()

def test_unavailable_solver_no_fallback(model,tmp_path,monkeypatch):
    import pcbsim.components.surface_evolver_runner as module
    monkeypatch.setattr(module,'find_executable',lambda requested=None:None)
    report=run_surface_evolver(model,{},tmp_path/'out')
    assert report['status']=='unavailable' and not report['native_evolver_executed']
    assert not (tmp_path/'out/solder_mesh.off').exists()
    assert not (tmp_path/'out/metrics.json').exists()

def test_missing_metadata_is_explicit(tmp_path):
    model=tmp_path/'x.fe';model.write_text('// no sidecar\n')
    report=run_surface_evolver(model,{},tmp_path/'out')
    assert report['status']=='failed' and 'sidecar' in report['error']

def test_environment_executable_override(monkeypatch):
    import sys
    from pcbsim.components.surface_evolver_runner import find_executable
    monkeypatch.setenv('SURFACE_EVOLVER_EXE',sys.executable)
    assert find_executable('auto')==str(Path(sys.executable).resolve())


@pytest.mark.protocol
@pytest.mark.parametrize("passes", [0, 1])
def test_insufficient_consecutive_checks_blocks_success(model,tmp_path,tetrahedron,fake_native_process,passes):
    fake_native_process['text']=protocol_output(*tetrahedron).replace('LAB_CONVERGENCE_PASSES 2',f'LAB_CONVERGENCE_PASSES {passes}')
    report=run_surface_evolver(model,{},tmp_path/'out')
    assert report['status']=='failed' and not report['numerical_pass']

@pytest.mark.protocol
def test_missing_convergence_evidence_fails(model,tmp_path,tetrahedron,fake_native_process):
    fake_native_process['text']=protocol_output(*tetrahedron).replace('LAB_CONVERGENCE_PASSES 2','')
    report=run_surface_evolver(model,{},tmp_path/'out')
    assert report['status']=='failed' and 'convergence_passes' in report['error']


def test_fixed_check_window_and_bounded_relaxation():
    for steps in (300, 1000):
        text=build_commands({'body_volume_target':1}, {'minimization_steps':steps,'max_convergence_batches':4})
        assert 'conj_grad on' in text
        assert text.count('g 30;')==4
        assert text.count(f'if lab_passes == 0 then g {steps};')==3
        assert 'LAB_CONVERGENCE_PASSES' in text
    text=build_commands({'body_volume_target':None}, {'refinements':0,'minimization_steps':123,'conjugate_gradient':False})
    assert 'g 123;' in text and 'conj_grad on' not in text


def test_mesh_swaps_preserve_contact_regions():
    text=build_commands({'body_volume_target':1,'has_pcbsim_region':True},{'max_convergence_batches':2})
    assert 'min(ee.facet,pcbsim_region)==1 and max(ee.facet,pcbsim_region)==1' in text
    assert 'conj_grad off; conj_grad on;' in text
    text=build_commands({'body_volume_target':1,'has_pcbsim_region':True},{'improve_free_surface_mesh':False})
    assert 'equiangulate' not in text
