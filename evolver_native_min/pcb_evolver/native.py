from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import time
import numpy as np
from .models import write_obj


def commands(has_body=True,refinements=2,steps=200):
    lines=['// This command file is preserved verbatim with every attempted run.',
           'recalc','printf "LAB_INITIAL_ENERGY %.17g\\n", total_energy']
    if has_body:lines+=['printf "LAB_INITIAL_VOLUME %.17g\\n", body[1].volume']
    lines+=['g 30']
    for k in range(refinements):lines+=['r','u',f'g {steps}']
    # Check energy drift and actual vertex displacement at a fixed final mesh.
    lines+=['define vertex attribute lab_x real','define vertex attribute lab_y real',
            'define vertex attribute lab_z real','set vertex lab_x x','set vertex lab_y y','set vertex lab_z z',
            'lab_old_energy := total_energy',f'g {steps}',
            'printf "LAB_ENERGY %.17g\\n", total_energy',
            'printf "LAB_ENERGY_DRIFT %.17g\\n", abs(total_energy-lab_old_energy)/(1+abs(total_energy))',
            'printf "LAB_MAX_MOVE %.17g\\n", max(vertex,sqrt((x-lab_x)^2+(y-lab_y)^2+(z-lab_z)^2))',
            'printf "LAB_AREA %.17g\\n", total_area',
            'printf "LAB_FACETS %d\\n", facet_count']
    if has_body:lines+=['printf "LAB_VOLUME %.17g\\n", body[1].volume','printf "LAB_PRESSURE %.17g\\n", body[1].pressure']
    lines+=['foreach vertex vv do printf "LAB_VERTEX %d %.17g %.17g %.17g\\n",vv.id,vv.x,vv.y,vv.z',
            'foreach facet ff do printf "LAB_FACE %d %d %d %d\\n",ff.id,ff.vertex[1].id,ff.vertex[2].id,ff.vertex[3].id',
            'dump "final.dmp"','printf "LAB_COMPLETE 1\\n"','quit 0','']
    return '\n'.join(lines)


def parse_output(text):
    metrics={};verts={};faces=[]
    # Echoed printf source contains LAB_* too: only parse output-shaped lines.
    for raw in text.splitlines():
        line=raw.strip()
        match=re.search(r'(?<!["\w])(LAB_\w+)\s+([-+0-9.eE]+(?:\s+[-+0-9.eE]+)*)\s*$',line)
        if not match:continue
        tag=match.group(1);vals=match.group(2).split()
        if tag=='LAB_VERTEX' and len(vals)==4:verts[int(vals[0])]=[float(v) for v in vals[1:]]
        elif tag=='LAB_FACE' and len(vals)==4:faces.append([int(v) for v in vals[1:]])
        elif len(vals)==1:metrics[tag[4:].lower()]=float(vals[0])
    if metrics.get('complete')!=1:raise ValueError('Missing LAB_COMPLETE sentinel: native run incomplete')
    if any(not math.isfinite(x) for x in metrics.values()):raise ValueError('Nonfinite native metric')
    if not verts or not faces:raise ValueError('Missing native mesh')
    ids=sorted(verts);lookup={old:i for i,old in enumerate(ids)}
    return metrics,np.array([verts[i] for i in ids]),np.array([[lookup[v] for v in f] for f in faces])


def run_native(model,output_dir,executable=None,timeout=180,refinements=2):
    model=Path(model).resolve();out=Path(output_dir).resolve();out.mkdir(parents=True,exist_ok=True)
    meta=json.loads(model.with_suffix('.json').read_text())
    script=out/'run.cmd';script.write_text(commands(meta['body_volume_target'] is not None,refinements))
    requested=executable or 'evolver'
    found=shutil.which(requested) or (shutil.which('evolver-nox') if executable is None else None)
    manifest=dict(backend='surface_evolver',model=str(model),command_file=str(script),
                  model_sha256=hashlib.sha256(model.read_bytes()).hexdigest(),
                  command_sha256=hashlib.sha256(script.read_bytes()).hexdigest(),
                  native_evolver_executed=False,status='not_executed',
                  desired_command=[requested,'-x',f'-f{script}',str(model)],
                  numerical_pass=False,physical_validation=False)
    if found is None:
        manifest.update(status='unavailable',reason='Surface Evolver executable not found; no fallback used')
    else:
        cmd=[found,'-x',f'-f{script}',str(model)];manifest['command']=cmd
        start=time.perf_counter()
        try:
            proc=subprocess.run(cmd,cwd=out,input='quit 0\n',text=True,capture_output=True,timeout=timeout,check=False)
            text=proc.stdout+'\n'+proc.stderr;(out/'stdout.log').write_text(text)
            manifest.update(native_evolver_executed=True,returncode=proc.returncode,wall_seconds=time.perf_counter()-start)
            if proc.returncode!=0 or re.search(r'(SYNTAX ERROR|DATAFILE ERROR|FATAL ERROR|WARNING)',text,re.I):
                manifest.update(status='failed',reason='Native return code, error or warning; inspect stdout.log')
            else:
                m,v,f=parse_output(text);write_obj(out/'mesh.obj',v,f)
                # Keep exact geometry for future native/Python comparisons.
                np.savez_compressed(out/'mesh.npz',vertices=v,faces=f)
                target=meta['body_volume_target'];err=abs(m.get('volume',0)-target)/target if target else 0
                manifest.update(status='executed',metrics=m,volume_relative_error=err,
                                numerical_pass=bool(err<1e-7 and m['energy_drift']<1e-7 and m['max_move']<1e-5),
                                numerical_gate_scope='volume, fixed-mesh energy drift, displacement only; Hessian and mesh study still required')
        except subprocess.TimeoutExpired:
            manifest.update(status='timeout',native_evolver_executed=True,reason=f'Native process exceeded {timeout}s; terminated')
        except (OSError,ValueError,KeyError) as exc:
            manifest.update(status='failed',reason=str(exc))
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2,allow_nan=False))
    return manifest
