import sys,json
from pathlib import Path
sys.path.insert(0,str(Path('..').resolve()))
from pcbsim.components.surface_evolver_runner import run_surface_evolver
report=run_surface_evolver('../experiments/run_004/fe/model.fe',dict(executable='C:/Evolver/evolver.exe',minimization_steps=1000,conjugate_gradient=False,timeout_seconds=300,max_convergence_batches=20),'diagnostics/adaptive_gradient')
print(report['status'],report.get('error'))
