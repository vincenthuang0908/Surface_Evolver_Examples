from __future__ import annotations
import json
import math
from pathlib import Path
import numpy as np
from .geometry import annulus_mesh

PI=math.pi


def topology(faces):
    edges=[]; lookup={}; face_edges=[]
    for face in faces:
        oriented=[]
        for a,b in zip(face,np.roll(face,-1)):
            a=int(a);b=int(b); key=tuple(sorted((a,b)))
            if key not in lookup:
                lookup[key]=len(edges)+1;edges.append((a,b))
            eid=lookup[key]
            oriented.append(eid if edges[eid-1]==(a,b) else -eid)
        face_edges.append(oriented)
    return edges,face_edges


def revolve(profile,nphi=32,annular=False):
    """Triangulate r,z meridian; outward side, or upward annular graph."""
    profile=np.asarray(profile,float)
    has_apex=abs(profile[-1,0])<1e-12
    nr=len(profile)-1 if has_apex else len(profile)
    vertices=[]
    for r,z in profile[:nr]:
        vertices.extend([[r*math.cos(2*PI*j/nphi),r*math.sin(2*PI*j/nphi),z] for j in range(nphi)])
    faces=[]
    for i in range(nr-1):
        for j in range(nphi):
            k=(j+1)%nphi
            a=i*nphi+j;b=i*nphi+k;c=(i+1)*nphi+k;d=(i+1)*nphi+j
            tris=[[a,b,c],[a,c,d]]
            if annular: tris=[t[::-1] for t in tris]
            faces.extend(tris)
    if has_apex:
        apex=len(vertices);vertices.append([0,0,profile[-1,1]])
        for j in range(nphi): faces.append([(nr-1)*nphi+j,(nr-1)*nphi+(j+1)%nphi,apex])
    return np.array(vertices),np.array(faces,dtype=int)


def write_obj(path,vertices,faces):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w') as out:
        out.write('# Open liquid-air surface only; not a watertight manufacturing solid.\n')
        for x,y,z in vertices:out.write(f'v {x:.12g} {y:.12g} {z:.12g}\n')
        for a,b,c in faces:out.write(f'f {a+1} {b+1} {c+1}\n')


def generate_fe(kind,params,path,n=8,nphi=24):
    """Generate frozen-input .fe plus a JSON topology sidecar.

    Regenerate when changing geometry: not all interior starting coordinates
    are symbolic. Model parameter declarations control constraints/energies.
    """
    p=dict(params);path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    vattr={}; egroup={}; header=[]; volume=None
    def ring(ids,attribute):
        ids=list(ids)
        for j,k in zip(ids,ids[1:]+ids[:1]):egroup[tuple(sorted((j,k)))]=attribute
    if kind in ('drop','gravity','patterned','hard_pad'):
        volume=float(p.get('volume',.2));theta=float(p.get('theta_deg',60));bond=float(p.get('bond',0))
        h=.8*volume**(1/3);a=math.sqrt(3*volume/(2*PI*h))
        phi=np.linspace(0,PI/2,n+1)
        rr=a*np.cos(phi);zz=h*np.sin(phi);rr[-1]=0
        if kind in ('patterned','hard_pad'):
            pad=float(p.get('pad_radius',.5));a=min(a,pad*.95)
            rr=a*np.cos(phi);rr[-1]=0;h=3*volume/(2*PI*a*a);zz=h*np.sin(phi)
        vertices,faces=revolve(np.column_stack([rr,zz]),nphi)
        header=[f'parameter volume_target = {volume:.17g}',f'parameter theta_pad = {theta:.17g}',
                f'gravity_constant {bond:.17g}']
        wet='cos(theta_pad*pi/180)'
        if kind=='patterned':
            mask=float(p.get('mask_theta_deg',120))
            header += [f'parameter pad_radius = {pad:.17g}',f'parameter theta_mask = {mask:.17g}',
                       '#define WETC ((x^2+y^2 <= pad_radius^2) ? cos(theta_pad*pi/180) : (cos(theta_mask*pi/180)+(cos(theta_pad*pi/180)-cos(theta_mask*pi/180))*pad_radius^2/(x^2+y^2)))']
            wet='WETC'
        header += ['constraint 1','formula: z = 0','energy:',f'e1: 0.5*({wet})*y',f'e2: -0.5*({wet})*x','e3: 0']
        attr='constraint 1'
        if kind=='hard_pad':
            header += [f'parameter pad_radius = {pad:.17g}','constraint 2 nonpositive','formula: x^2+y^2-pad_radius^2']
            attr='constraints 1 2'
        for j in range(nphi):vattr[j]=attr
        ring(range(nphi),attr)
    elif kind in ('catenoid','bridge'):
        R=float(p.get('radius',1));H=float(p.get('height',1))
        z=np.linspace(0,H,n+1);rr=R*(1+.05*np.sin(PI*z/H))
        vertices,faces=revolve(np.column_stack([rr,z]),nphi)
        header=[f'parameter ring_radius = {R:.17g}',f'parameter plate_height = {H:.17g}','gravity_constant 0',
                'boundary 1 parameters 1','x1: ring_radius*cos(p1)','x2: ring_radius*sin(p1)','x3: 0',
                'boundary 2 parameters 1','x1: ring_radius*cos(p1)','x2: ring_radius*sin(p1)','x3: plate_height']
        if kind=='bridge':
            volume=float(p.get('volume',PI));header += ['content:','c1: 0','c2: -plate_height*x','c3: 0']
            header.insert(0,f'parameter volume_target = {volume:.17g}')
        for j in range(nphi):
            vattr[j]=f'{2*PI*j/nphi:.17g} boundary 1 fixed'
            vattr[n*nphi+j]=f'{2*PI*j/nphi:.17g} boundary 2 fixed'
        ring(range(nphi),'boundary 1 fixed');ring(range(n*nphi,(n+1)*nphi),'boundary 2 fixed')
    elif kind=='fillet':
        a=float(p.get('pin_radius',.25));b=float(p.get('pad_radius',.75));off=float(p.get('offset',0))
        theta=float(p.get('theta_pin_deg',60));volume=float(p.get('volume',.2))
        xy,faces=annulus_mesh(a,b,off,n,nphi)
        heights=np.repeat(1-np.linspace(0,1,n+1),nphi)
        vertices=np.column_stack([xy,heights])
        tri=vertices[faces];cross=np.cross(tri[:,1]-tri[:,0],tri[:,2]-tri[:,0])
        init_volume=float(np.sum(cross[:,2]/2*np.mean(tri[:,:,2],axis=1)))
        vertices[:,2]*=volume/init_volume
        header=[f'parameter volume_target = {volume:.17g}',f'parameter pin_radius = {a:.17g}',
                f'parameter pad_radius = {b:.17g}',f'parameter pin_offset = {off:.17g}',
                f'parameter theta_pin = {theta:.17g}','gravity_constant 0',
                '// Constant pad wetting energy is omitted: outer contact line is pinned.',
                'constraint 1','formula: (x-pin_offset)^2+y^2-pin_radius^2','energy:',
                'e1: -cos(theta_pin*pi/180)*z*y/pin_radius',
                'e2: cos(theta_pin*pi/180)*z*(x-pin_offset)/pin_radius','e3: 0',
                'boundary 2 parameters 1','x1: pad_radius*cos(p1)','x2: pad_radius*sin(p1)','x3: 0']
        for j in range(nphi):
            vattr[j]='constraint 1'
            vattr[n*nphi+j]=f'{2*PI*j/nphi:.17g} boundary 2 fixed'
        ring(range(nphi),'constraint 1');ring(range(n*nphi,(n+1)*nphi),'boundary 2 fixed')
    else: raise ValueError(f'Unknown model family {kind}')
    edges,face_edges=topology(faces)
    lines=['// GENERATED research prototype.',
           '// Length unit L0=1 mm; energy unit gamma*L0^2; gamma is scaled to 1.',
           '// Inputs: '+json.dumps(p,sort_keys=True),
           '// Geometry edits require regeneration.']+header+['','vertices']
    for i,(x,y,z) in enumerate(vertices):
        attr=vattr.get(i,'')
        if 'boundary' in attr:lines.append(f'{i+1} {attr}')
        else:lines.append(f'{i+1} {x:.17g} {y:.17g} {z:.17g} {attr}')
    lines += ['','edges']
    for i,(a,b) in enumerate(edges):lines.append(f'{i+1} {a+1} {b+1} {egroup.get(tuple(sorted((a,b))),"")}')
    lines += ['','faces']
    for i,es in enumerate(face_edges):lines.append(f'{i+1} '+ ' '.join(map(str,es)))
    if volume is not None:
        lines+=['','bodies','1 '+' '.join(str(i+1) for i in range(len(faces)))+' volume volume_target density 1']
    lines += ['','read','// Native batch runner supplies minimization, logging and export commands.','']
    path.write_text('\n'.join(lines))
    sidecar=dict(kind=kind,parameters=p,vertices=vertices.tolist(),faces=faces.tolist(),
                 vertex_attributes={str(k):v for k,v in vattr.items()},
                 n=n,nphi=nphi,body_volume_target=volume,native_execution_status='not_executed')
    path.with_suffix('.json').write_text(json.dumps(sidecar,indent=2))
    return sidecar


def check_topology(sidecar):
    """Static checks only: NOT a native .fe parser or a native runtime test."""
    v=np.array(sidecar['vertices']);f=np.array(sidecar['faces']);edges,fe=topology(f)
    counts={i+1:[] for i in range(len(edges))}
    for es in fe:
        for eid in es:counts[abs(eid)].append(1 if eid>0 else -1)
    internal=[s for s in counts.values() if len(s)==2]
    nonmanifold=sum(len(s)>2 for s in counts.values())
    area=np.linalg.norm(np.cross(v[f[:,1]]-v[f[:,0]],v[f[:,2]]-v[f[:,0]]),axis=1)/2
    boundary_count=sum(len(s)==1 for s in counts.values())
    # Verify open boundary loops have degree two, and all triangles are connected.
    boundary=[edges[k-1] for k,s in counts.items() if len(s)==1]
    deg={}
    for a,b in boundary:deg[a]=deg.get(a,0)+1;deg[b]=deg.get(b,0)+1
    return dict(static_pass=bool(nonmanifold==0 and all(sum(s)==0 for s in internal)
                and min(area)>1e-14 and all(d==2 for d in deg.values())),
                n_vertices=len(v),n_faces=len(f),boundary_edges=boundary_count,
                nonmanifold_edges=nonmanifold,min_triangle_area=float(min(area)),
                native_syntax_checked=False)
