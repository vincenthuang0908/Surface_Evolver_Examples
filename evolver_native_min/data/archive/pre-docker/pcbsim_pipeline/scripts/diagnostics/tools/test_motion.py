import sys,json,concurrent.futures
from pathlib import Path
sys.path.insert(0,str(Path('..').resolve()))
from pcbsim.components import surface_evolver_runner as r
original=r.build_commands
meta=json.loads(Path('../experiments/run_004/fe/model.json').read_text())
def build(m,s):
 text=original(m,s)
 if s.get('normal'):text=text.replace('recalc\n','recalc\nnormal_motion on\n',1)
 if s.get('swaps'):
  text=text.replace('if lab_passes == 0 then g 1000;', 'if lab_passes == 0 then { equiangulate edge ee where min(ee.facet,pcbsim_region)==1 and max(ee.facet,pcbsim_region)==1; conj_grad off; conj_grad on; g 1000; };')
 return text
r.build_commands=build
for name,settings in [('normal_cg',dict(normal=True)),('normal_gradient',dict(normal=True,conjugate_gradient=False)),('swaps_cg',dict(swaps=True))]:
 config=dict(executable="C:/Evolver/evolver.exe",minimization_steps=1000,timeout_seconds=300,**settings)
 report=r.run_surface_evolver('../experiments/run_004/fe/model.fe',config,Path('diagnostics')/(name+'_v2'))
 metrics_path=Path(report['outputs'].get('metrics','missing'))
 metrics=json.loads(metrics_path.read_text()) if metrics_path.is_file() else {}
 print(name,report['status'],report.get('error'),{k:metrics.get(k) for k in ['energy_scaled','max_move_mm','convergence_checks']},metrics.get('mesh',{}).get('minimum_triangle_area_mm2'),flush=True)

