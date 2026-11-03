#!/usr/bin/env python3
"""Invoke the actual Surface Evolver executable, or record unavailability."""
import argparse
import json
from pathlib import Path
from pcb_evolver.native import run_native
ROOT=Path(__file__).resolve().parent

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--model',type=Path,help='one .fe model; otherwise run all generated models')
    ap.add_argument('--executable',help='path to evolver, evolver-nox, or evolver.exe')
    ap.add_argument('--output',type=Path,default=ROOT/'results/native')
    ap.add_argument('--timeout',type=int,default=180)
    ap.add_argument('--refinements',type=int,default=2)
    args=ap.parse_args()
    models=[args.model] if args.model else sorted((ROOT/'models').glob('*.fe'))
    if not models:raise SystemExit('Generate models first: python generate_models.py')
    outcomes=[]
    for model in models:
        m=run_native(model,args.output/model.stem,args.executable,args.timeout,args.refinements)
        outcomes.append(m);print(model.name,m['status'])
    args.output.mkdir(parents=True,exist_ok=True)
    (args.output/'summary.json').write_text(json.dumps(outcomes,indent=2))
    return 0 if all(m.get('numerical_pass') for m in outcomes) else 2
if __name__=='__main__':raise SystemExit(main())
