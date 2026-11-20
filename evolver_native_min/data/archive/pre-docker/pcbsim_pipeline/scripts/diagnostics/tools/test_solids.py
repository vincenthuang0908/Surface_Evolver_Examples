import sys
from pathlib import Path
sys.path.insert(0,str(Path('..').resolve()))
from pcbsim.components.cad_converter import mesh_to_solid
from pcbsim.mesh import read_off
for run,mesh in [('run_004','fe/initial_mesh.off'),('run_004','simulation/solder_mesh.off'),('run_005','simulation/solder_mesh.off')]:
 try:
  v,f=read_off(Path('../experiments')/run/mesh);solid=mesh_to_solid(v,f);print(run,mesh,'VALID',flush=True)
 except Exception as e:print(run,mesh,str(e),flush=True)
