#!/usr/bin/env python3
"""Generate the native .fe files and run static mesh topology checks."""
import json
from pathlib import Path
from pcb_evolver.models import generate_fe,check_topology
ROOT=Path(__file__).resolve().parent

def main():
    cfg=json.loads((ROOT/'config/native_models.json').read_text());report=[]
    for case in cfg['models']:
        file=ROOT/'models'/f"{case['id']}.fe"
        meta=generate_fe(case['kind'],case['parameters'],file,n=8,nphi=24)
        checks=check_topology(meta);report.append(dict(model=case['id'],**checks))
        print(case['id'],checks)
    (ROOT/'results/static_model_checks.json').write_text(json.dumps(report,indent=2))
    return int(not all(r['static_pass'] for r in report))
if __name__=='__main__':raise SystemExit(main())
