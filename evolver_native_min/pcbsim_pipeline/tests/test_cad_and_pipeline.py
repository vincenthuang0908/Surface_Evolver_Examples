import copy
from pathlib import Path
import sys
import numpy as np
import pytest
from pcbsim.common import ComponentError, read_json, write_json, sha256
from pcbsim.mesh import read_off, write_off
from pcbsim.components.experiment_manager import run_pipeline, reproduce_experiment, _create_run
from pcbsim.components.cad_converter import convert_cad, mesh_to_solid, verify_faceted_geometry
from pcbsim.components.cad_extractor import extract_cad

@pytest.mark.cad
def test_actual_extraction_contract(synthetic_extraction):
    g=read_json(synthetic_extraction['outputs']['geometry'])
    assert synthetic_extraction['connection_count']==1
    assert g['validation']['hole_preserved']
    assert g['hole']['radius_mm']==pytest.approx(.5)
    assert g['hole']['pcb_drill_radius_mm']==pytest.approx(.55)
    assert g['pin']['width_mm']==pytest.approx(.64)
    assert g['coordinate_system']['local_to_world'][2][3]==pytest.approx(.05)

@pytest.mark.cad
def test_invalid_pin_selection(synthetic_step,tmp_path):
    with pytest.raises(ComponentError,match='pin_index'):
        extract_cad(synthetic_step,{'selection':{'pin_index':99}},tmp_path/'bad')

@pytest.mark.cad
def test_tetra_to_brep_exact(tetrahedron):
    pytest.importorskip('cadquery')
    v,f=tetrahedron;solid=mesh_to_solid(v,f)
    assert solid.isValid() and solid.Volume()==pytest.approx(1/6)
    assert verify_faceted_geometry(solid,v,f,1e-7)['surface_deviation_bound_mm']<1e-7

@pytest.mark.cad
def test_cad_roundtrip_preserves_originals(synthetic_step,synthetic_extraction,synthetic_fe,tmp_path):
    output=tmp_path/'result.step'
    report=convert_cad(synthetic_fe['outputs']['initial_mesh'],synthetic_step,
                       synthetic_extraction['outputs']['geometry'],{},output)
    assert report['status']=='success' and report['step_reopened']
    assert report['original_solid_count']==3 and report['output_solid_count']==4
    assert report['original_geometry_preserved'] and report['self_intersections_checked']
    assert report['reopened_geometric_check']['surface_deviation_bound_mm']<1e-7
    assert all(check['volume_mm3']<1e-7 for check in report['original_interference_checks'])
    assert sha256(synthetic_step)==report['source_sha256']

@pytest.mark.cad
def test_cad_open_mesh_fails_with_report(synthetic_step,synthetic_extraction,synthetic_fe,tmp_path):
    v,f=read_off(synthetic_fe['outputs']['initial_mesh']);mesh=write_off(tmp_path/'open.off',v,f[:-1])
    with pytest.raises(ComponentError,match='closed'):
        convert_cad(mesh,synthetic_step,synthetic_extraction['outputs']['geometry'],{},tmp_path/'bad/result.step')
    assert read_json(tmp_path/'bad/conversion_report.json')['status']=='failed'
    assert not (tmp_path/'bad/result.step').exists()

@pytest.mark.cad
def test_wrong_original_step_is_rejected(synthetic_step,synthetic_extraction,synthetic_fe,tmp_path):
    altered=tmp_path/'modified.step';altered.write_bytes(synthetic_step.read_bytes()+b'\n')
    with pytest.raises(ComponentError,match='differs'):
        convert_cad(synthetic_fe['outputs']['initial_mesh'],altered,synthetic_extraction['outputs']['geometry'],{},tmp_path/'bad/result.step')


def test_manager_material_only(tmp_path):
    cfg=write_json(tmp_path/'config.json',{'inputs':{},'experiments_dir':'experiments','steps':{}})
    report=run_pipeline(cfg,only=['material_manager'])
    assert report['status']=='completed'
    assert report['components']['cad_extractor']['status']=='skipped'
    root=Path(report['experiment_dir'])
    assert (root/'parameters/materials.json').is_file()
    assert (root/'exp_report.json').read_bytes()==(root/'experiment.json').read_bytes()
    assert (root/'exp_execution_steps.log').read_bytes()==(root/'experiment.log').read_bytes()


def test_manager_missing_upstream_records_failure(tmp_path):
    cfg=write_json(tmp_path/'config.json',{'inputs':{},'steps':{}})
    report=run_pipeline(cfg,only=['fe_generator'])
    assert report['status']=='failed' and report['failed_component']=='fe_generator'
    root=Path(report['experiment_dir'])
    assert read_json(root/'exp_report.json')['status']=='failed'
    assert 'Missing extracted STEP' in (root/'experiment.log').read_text()


def test_manager_config_rejects_conflicting_artifact(tmp_path):
    cfg=write_json(tmp_path/'config.json',{'inputs':{'model_file':'some.fe'},'steps':{}})
    with pytest.raises(ComponentError,match='conflicts'):run_pipeline(cfg)


def test_manager_unknown_stage_rejected(tmp_path):
    cfg=write_json(tmp_path/'config.json',{'inputs':{},'steps':{'typo':{}}})
    with pytest.raises(ComponentError,match='Unknown pipeline'):run_pipeline(cfg)


def test_run_ids_do_not_overwrite_or_traverse(tmp_path):
    assert _create_run(tmp_path).name=='run001'
    assert _create_run(tmp_path).name=='run002'
    (tmp_path / "run_006").mkdir()
    assert _create_run(tmp_path).name == "run007"
    with pytest.raises(ComponentError):_create_run(tmp_path,'run001')
    with pytest.raises(ComponentError):_create_run(tmp_path,'../escape')

@pytest.mark.cad
@pytest.mark.protocol
def test_full_pipeline_and_reproduction_with_test_process_only(synthetic_step,tmp_path,fake_native_process):
    cfg=write_json(tmp_path/'pipeline.json',{
        'inputs':{'step_file':str(synthetic_step)},'experiments_dir':'experiments',
        'steps':{'surface_evolver':{'refinements':0,'minimization_steps':1},
                 'cad_converter':{'output_filename':'custom.stp'}}})
    first=run_pipeline(cfg)
    assert first['status']=='completed',first.get('error')
    assert all(v['status']=='success' for v in first['components'].values())
    root=Path(first['experiment_dir'])
    assert first['components']['cad_converter']['outputs']['combined_step'] == str(Path('output/custom.stp'))
    assert (root/'output/custom.stp').is_file()
    assert 'TEST-ONLY PROTOCOL STUB' in (root/'simulation/stdout.log').read_text()
    comparison=reproduce_experiment(root)
    assert comparison['passed'],comparison
    assert comparison['candidate_run']!=comparison['reference_run']
    assert not comparison['code_changed']
    # A modified frozen input must never be silently used for reproduction.
    with (root/'input/config.json').open('a') as stream:stream.write('\n')
    with pytest.raises(ComponentError,match='Saved input was modified'):reproduce_experiment(root)

@pytest.mark.native
@pytest.mark.cad
def test_real_native_generated_model_smoke(synthetic_fe,tmp_path):
    from pcbsim.components.surface_evolver_runner import run_surface_evolver,find_executable
    executable=find_executable()
    if executable is None:pytest.skip('Real Surface Evolver is not installed; no native execution claimed')
    report=run_surface_evolver(synthetic_fe['outputs']['model'],
          {'executable':executable,'refinements':0,'minimization_steps':100,'require_numerical_pass':False},tmp_path/'native')
    assert report['status']=='success',report
    assert read_json(tmp_path/'native/metrics.json')['mesh']['closed']

@pytest.mark.slow
@pytest.mark.cad
def test_supplied_pico_geometry_to_step_roundtrip(tmp_path):
    """Real CAD integration on INITIAL geometry, not a simulated result."""
    from pcbsim.components.material_manager import manage_materials
    from pcbsim.components.fe_generator import generate_fe
    source=Path(__file__).parents[1]/'inputs/raspberry_pico_2H.step'
    extracted=extract_cad(source,{},tmp_path/'geometry')
    assert extracted['connection_count']==40
    parameters=tmp_path/'materials.json';manage_materials({},parameters)
    model=generate_fe(extracted['outputs']['extracted_step'],extracted['outputs']['geometry'],parameters,{},tmp_path/'fe/model.fe')
    report=convert_cad(model['outputs']['initial_mesh'],source,extracted['outputs']['geometry'],{},tmp_path/'output/initial_geometry_only.step')
    assert report['original_solid_count']==420 and report['output_solid_count']==421
    assert report['step_reopened'] and report['original_geometry_preserved']
