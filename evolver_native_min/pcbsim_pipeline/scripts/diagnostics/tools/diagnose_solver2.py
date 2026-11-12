import sys,json,subprocess,concurrent.futures
from pathlib import Path
sys.path.insert(0,str(Path('..').resolve()))
from pcbsim.components.surface_evolver_runner import build_commands
from pcbsim._vendor.evolver_native.native import parse_output
root=Path('diagnostics').resolve();root.mkdir(exist_ok=True)
model=Path('../experiments/run_004/fe/model.fe').resolve()
meta=json.loads(model.with_suffix('.json').read_text())
def run(name,cg,steps):
 out=root/name;out.mkdir(exist_ok=True)
 text=build_commands(meta,dict(minimization_steps=steps))
 text=text.replace('lab_old_energy := total_energy\ng '+str(steps),'lab_old_energy := total_energy\ng 30')
 if 'freeze' in name:text=text.replace('r\n','r\nfix vertex vv where max(vv.facet,pcbsim_region==2) and not max(vv.facet,pcbsim_region==1)\n')
 if cg:text=text.replace('g 30\nr','conj_grad on\ng 30\nr',1)
 text=text.replace('printf "LAB_ENERGY %.17g', 'foreach vertex vv do printf "MOVE %d %.17g\\n",vv.id,sqrt((vv.x-vv.lab_x)^2+(vv.y-vv.lab_y)^2+(vv.z-vv.lab_z)^2)\nprintf "LAB_ENERGY %.17g')
 script=out/'run.cmd';script.write_text(text)
 with (out/'stdout.log').open('w') as f:
  p=subprocess.run(['C:/Evolver/evolver.exe','-x','-f'+str(script),str(model)],input='quit 0\n',text=True,stdout=f,stderr=subprocess.STDOUT,cwd=out,timeout=180)
 try:
  m,v,f=parse_output((out/'stdout.log').read_text());print(name,{k:m[k] for k in ['energy','energy_drift','max_move','volume']},flush=True)
 except Exception as e:print(name,str(e),flush=True)
with concurrent.futures.ThreadPoolExecutor(3) as pool:list(pool.map(lambda a:run(*a),[('freeze_gradient1000',False,1000),('freeze_cg1000',True,1000),('cg_3000',True,3000)]))
