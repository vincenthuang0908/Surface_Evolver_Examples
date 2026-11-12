import copy
import hashlib
import json
from pathlib import Path
import numpy as np
import pytest
from pcbsim.common import ComponentError, positive, read_json, write_json
from pcbsim.mesh import read_off, write_off, inspect_mesh, require_valid_mesh, rigid_transform
from pcbsim.components.material_manager import normalize_materials
from pcbsim.components.fe_generator import build_model
from pcbsim.components.evaluation import compare_measurements, _compare_meshes

@pytest.mark.parametrize('value',[float('nan'),float('inf'),-1,0,True,'garbage'])
def test_positive_rejects_bad_numbers(value):
    with pytest.raises(ComponentError):positive(value,'test')

def test_atomic_json_roundtrip(tmp_path):
    p=tmp_path/'value.json';write_json(p,{'a':1});write_json(p,{'a':2})
    assert read_json(p)=={'a':2}
    with pytest.raises(ValueError):write_json(p,{'bad':float('nan')})
    assert read_json(p)=={'a':2}

def test_off_roundtrip(tmp_path,tetrahedron):
    v,f=tetrahedron;p=write_off(tmp_path/'t.off',v,f);vv,ff=read_off(p)
    assert np.array_equal(v,vv) and np.array_equal(f,ff)
    info=require_valid_mesh(vv,ff,closed=True)
    assert info['signed_volume_mm3']==pytest.approx(1/6)
    assert info['boundary_edge_count']==0

@pytest.mark.parametrize('content',[
    'NOPE\n', 'OFF\n4 4 0\n',
    'OFF\n3 1 0\n0 0 0\n1 0 0\n0 1 0\n4 0 1 2 3\n',
    'OFF\n3 1 0\n0 0 0\n1 0 0\n0 1 0\n3 0 1 9\n',
    'OFF\n3 1 0\nNaN 0 0\n1 0 0\n0 1 0\n3 0 1 2\n'])
def test_malformed_off(tmp_path,content):
    p=tmp_path/'bad.off';p.write_text(content)
    with pytest.raises(ComponentError):read_off(p)

def test_open_mesh_rejected(tetrahedron):
    v,f=tetrahedron
    assert inspect_mesh(v,f[:-1])['boundary_edge_count']==3
    with pytest.raises(ComponentError):require_valid_mesh(v,f[:-1],closed=True)

def test_duplicate_faces_rejected(tetrahedron):
    v,f=tetrahedron
    with pytest.raises(ComponentError):require_valid_mesh(v,np.vstack([f,f[0]]))

def test_orientation_rejected(tetrahedron):
    v,f=tetrahedron;f=f.copy();f[0]=f[0,::-1]
    with pytest.raises(ComponentError):require_valid_mesh(v,f)

def test_degenerate_faces_rejected(tetrahedron):
    v,f=tetrahedron;f=f.copy();f[0]=[0,0,1]
    with pytest.raises(ComponentError):require_valid_mesh(v,f)

def test_transform_is_rigid(tetrahedron):
    v,_=tetrahedron;t=np.eye(4);t[:3,3]=[10,20,30]
    assert np.allclose(rigid_transform(v,t),v+[10,20,30])
    t[0,0]=2
    with pytest.raises(ComponentError):rigid_transform(v,t)

def test_material_scaling():
    p=normalize_materials({'simulation':{'gravity_m_per_s2':9.81,'volume_multiplier':.5}})
    assert p['scales']['energy_J']==pytest.approx(.5e-6)
    assert p['scales']['pressure_Pa']==pytest.approx(500)
    assert p['scales']['gravity_coefficient']==pytest.approx(7400*9.81*1e-6/.5)
    assert p['simulation']['effective_fillet_volume_mm3']==pytest.approx(.0125)

@pytest.mark.parametrize('config',[
    {'material':{'pin_contact_angle_deg':180}},
    {'simulation':{'barrel_fill':'partial'}},
    {'simulation':{'pin_contact_line':'mystery'}},
    {'simulation':{'fillet_volume_mm3':-1}},
    {'simulation':{'seed':1.1}}])
def test_bad_materials(config):
    with pytest.raises(ComponentError):normalize_materials(config)

def test_fe_is_closed_and_volume_correct(geometry_contract):
    text,meta,v,f=build_model(geometry_contract,normalize_materials({}),{})
    assert meta['initial_mesh']['closed']
    assert meta['initial_mesh']['signed_volume_mm3']==pytest.approx(meta['body_volume_target'])
    assert meta['body_volume_target']-meta['barrel_volume_mm3']==pytest.approx(.025)
    assert 'tension (-cos(theta_pin*pi/180))' in text
    assert 'constraint 1' in text and 'constraint 4' in text
    assert not meta['native_syntax_checked']

def test_fe_repeatability_and_perturbation(geometry_contract):
    p=normalize_materials({'simulation':{'seed':123}})
    a=build_model(geometry_contract,p,{'initial_perturbation_mm':.0001})
    b=build_model(geometry_contract,p,{'initial_perturbation_mm':.0001})
    assert a[0]==b[0]
    p['simulation']['seed']=124
    c=build_model(geometry_contract,p,{'initial_perturbation_mm':.0001})
    assert a[0]!=c[0]
    assert a[1]['body_volume_target']==pytest.approx(c[1]['body_volume_target'])

def test_pin_height_limit(geometry_contract):
    p=normalize_materials({'simulation':{'fillet_volume_mm3':10}})
    with pytest.raises(ComponentError,match='straight pin'):build_model(geometry_contract,p,{})

def test_chord_tolerance(geometry_contract):
    with pytest.raises(ComponentError,match='chord'):build_model(geometry_contract,normalize_materials({}),{'segments_per_pin_side':2})

def test_pin_interference_rejected(geometry_contract):
    geometry_contract['pin']['center_xy_mm']=[.2,0]
    with pytest.raises(ComponentError,match='Pin corner'):build_model(geometry_contract,normalize_materials({}),{})

def test_measurement_comparison():
    data={'observations':{'volume_mm3':{'value':.2,'absolute_tolerance':.01}}}
    assert compare_measurements({'volume_mm3':.205},data)['status']=='passed'
    assert compare_measurements({'volume_mm3':.25},data)['status']=='failed'
    with pytest.raises(ComponentError):compare_measurements({},data)
    with pytest.raises(ComponentError):compare_measurements({}, {'observations':{}})

def test_mesh_comparison_supports_renumbering(tmp_path,tetrahedron):
    v,f=tetrahedron;order=np.array([2,0,3,1]);inverse=np.argsort(order)
    a=write_off(tmp_path/'a.off',v,f);b=write_off(tmp_path/'b.off',v[order],inverse[f])
    assert _compare_meshes(a,b,1e-9)['passed']
    write_off(b,v[order]+.01,inverse[f])
    assert not _compare_meshes(a,b,1e-9)['passed']

def test_vendored_files_match_user_archive():
    root=Path(__file__).parents[1]/'pcbsim/_vendor'
    origin=read_json(root/'ORIGIN.json')
    for name,expected in origin['files_sha256'].items():
        assert hashlib.sha256((root/'evolver_native'/name).read_bytes()).hexdigest()==expected

def test_unknown_physics_parameter_is_not_silently_ignored():
    with pytest.raises(ComponentError,match='Unsupported physical'):
        normalize_materials({'material':{'unimplemented_viscosity':1}})

def test_nonnumeric_contact_angle_rejected():
    with pytest.raises(ComponentError,match='Contact angles'):
        normalize_materials({'material':{'pin_contact_angle_deg':None}})
