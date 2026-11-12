"""Test fixtures. Process stubs are TEST ONLY and never production fallbacks."""
from __future__ import annotations
import json
from pathlib import Path
import subprocess
import sys
import numpy as np
import pytest
from pcbsim.common import write_json, read_json
from pcbsim.mesh import read_off, signed_volume

@pytest.fixture
def tetrahedron():
    return (np.array([[0,0,0],[1,0,0],[0,1,0],[0,0,1]],float),
            np.array([[0,2,1],[0,1,3],[0,3,2],[1,2,3]],int))

@pytest.fixture
def geometry_contract():
    return {"schema_version":1,"units":"mm","model_family":"rectangular_pin_circular_plated_hole",
            "coordinate_system":{"local_to_world":np.eye(4).tolist()},
            "pad":{"outer_radius_mm":.7},"hole":{"radius_mm":.5,"depth_mm":1.1},
            "pin":{"cross_section":"rectangle","width_mm":.64,"depth_mm":.64,
                   "center_xy_mm":[0,0],"max_straight_height_mm":.15}}

@pytest.fixture(scope="session")
def synthetic_step(tmp_path_factory):
    cq = pytest.importorskip("cadquery")
    root = tmp_path_factory.mktemp("synthetic_cad")
    board = cq.Workplane("XY").box(8,8,1).translate((0,0,-.5))
    drill = cq.Workplane("XY").circle(.55).extrude(1.2).translate((0,0,-1.1))
    board = board.cut(drill).val()
    barrel = cq.Workplane("XY").circle(.55).circle(.5).extrude(1.1).translate((0,0,-1.05))
    top = cq.Workplane("XY").circle(.7).circle(.5).extrude(.05)
    bottom = cq.Workplane("XY").circle(.7).circle(.5).extrude(.05).translate((0,0,-1.05))
    pad = barrel.union(top).union(bottom).val()
    pin = cq.Workplane("XY").box(.64,.64,4,centered=(True,True,False)).translate((0,0,-3)).val()
    assembly = cq.Assembly(name="synthetic_test_assembly")
    assembly.add(board,name="board"); assembly.add(pad,name="plated_pad"); assembly.add(pin,name="square_pin")
    path = root/"synthetic.step"; assembly.export(str(path))
    return path

@pytest.fixture(scope="session")
def synthetic_extraction(synthetic_step, tmp_path_factory):
    from pcbsim.components.cad_extractor import extract_cad
    out = tmp_path_factory.mktemp("synthetic_extract")
    return extract_cad(synthetic_step,{},out)

@pytest.fixture(scope="session")
def synthetic_fe(synthetic_extraction,tmp_path_factory):
    from pcbsim.components.material_manager import manage_materials
    from pcbsim.components.fe_generator import generate_fe
    root=tmp_path_factory.mktemp("synthetic_fe")
    parameters=root/"parameters.json"; manage_materials({},parameters)
    outputs=synthetic_extraction['outputs']
    return generate_fe(outputs['extracted_step'], outputs['geometry'],parameters,{},root/'model.fe')


def protocol_output(vertices,faces,regions=None,energy_drift=0.0):
    volume=signed_volume(vertices,faces)
    lines=['TEST-ONLY PROTOCOL STUB - NO NATIVE SOLVER WAS EXECUTED',
           f'LAB_INITIAL_ENERGY 1',f'LAB_INITIAL_VOLUME {volume:.17g}',
           'LAB_ENERGY 0.5',f'LAB_ENERGY_DRIFT {energy_drift}', 'LAB_MAX_MOVE 0',
           'LAB_AREA 1',f'LAB_FACETS {len(faces)}',f'LAB_VOLUME {volume:.17g}',
           'LAB_PRESSURE 2', 'LAB_CONVERGENCE_CHECKS 2', 'LAB_CONVERGENCE_PASSES 2']
    for i,row in enumerate(vertices,1): lines.append('LAB_VERTEX '+str(i)+' '+' '.join(f'{x:.17g}' for x in row))
    for i,row in enumerate(faces,1): lines.append('LAB_FACE '+str(i)+' '+' '.join(str(int(x)+1) for x in row))
    if regions:
        for i,region in enumerate(regions,1): lines.append(f'PCS_REGION {i} {region}')
    lines.append('LAB_COMPLETE 1')
    return '\n'.join(lines)+'\n'

@pytest.fixture
def fake_native_process(monkeypatch):
    """Exercise the production adapter, but replace Popen only inside tests."""
    from pcbsim.components import surface_evolver_runner as runner
    state={'text':None,'returncode':0,'timeout':False,'stopped':False}
    class StubProcess:
        def __init__(self,command,**kwargs):
            self.returncode=state['returncode'];self.pid=-999;self.command=command;self.stream=kwargs['stdout']
        def communicate(self,stdin,timeout):
            if state['timeout']:
                self.stream.write('partial TEST ONLY stdout\n');self.stream.flush()
                raise subprocess.TimeoutExpired(self.command,timeout)
            text=state['text']
            if text is None:
                model=Path(self.command[-1]);v,f=read_off(model.parent/'initial_mesh.off')
                data=model.read_text().split('\nfaces\n')[1].split('\nbodies\n')[0]
                regions=[int(line.split('pcbsim_region ')[1].split()[0]) for line in data.splitlines() if line.strip()]
                text=protocol_output(v,f,regions)
            self.stream.write(text);self.stream.flush()
            return None,None
        def wait(self): return self.returncode
    monkeypatch.setattr(runner,'find_executable',lambda requested=None:sys.executable)
    monkeypatch.setattr(runner.subprocess,'Popen',StubProcess)
    monkeypatch.setattr(runner,'_stop_process',lambda process:state.update(stopped=True))
    return state
