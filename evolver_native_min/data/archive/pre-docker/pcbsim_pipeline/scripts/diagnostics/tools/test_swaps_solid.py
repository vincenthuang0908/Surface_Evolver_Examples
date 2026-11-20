import sys,json
from pathlib import Path
sys.path.insert(0,str(Path('..').resolve()))
from pcbsim.components.cad_converter import mesh_to_solid
from pcbsim.mesh import read_off
p=Path('diagnostics/swaps_cg_v2');m=json.loads((p/'metrics.json').read_text());print(m['mesh']['minimum_triangle_area_mm2'])
v,f=read_off(p/'solder_mesh.off');s=mesh_to_solid(v,f);print('SWAPS CAD VALID',s.Volume())
