import sys,json,numpy as np
from pathlib import Path
sys.path.insert(0,str(Path('..').resolve()))
import matplotlib;matplotlib.use('Agg')
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
from pcbsim.mesh import read_off
root=Path('../experiments/run_006')
if not (root/'simulation/solder_mesh.off').is_file():root=Path('diagnostics/swaps_cg_v2')
else:root=root/'simulation'
v,f=read_off(root/'solder_mesh.off');tri=v[f];keep=tri[:,:,2].max(axis=1)>1e-8
fig=plt.figure(figsize=(9,7));ax=fig.add_subplot(111,projection='3d')
ax.add_collection3d(Poly3DCollection(tri[keep],facecolor='#d3dce5',edgecolor='#687c8c',linewidth=.18))
h=.32;corners=np.array([[h,-h],[h,h],[-h,h],[-h,-h]])
for i in range(4):
 a,b=corners[i],corners[(i+1)%4];ax.add_collection3d(Poly3DCollection([[[*a,0],[*b,0],[*b,.15],[*a,.15]]],facecolor='#bd9554',alpha=.5))
t=np.linspace(0,2*np.pi,160)
for radius,color,label in [(.7,'#a56d32','pad perimeter'),(.5,'#475569','hole perimeter')]:ax.plot(radius*np.cos(t),radius*np.sin(t),np.zeros_like(t),color=color,label=label)
ax.set(xlim=(-.75,.75),ylim=(-.75,.75),zlim=(0,.16),xlabel='x (mm)',ylabel='y (mm)',zlabel='z (mm)',title='Surface Evolver solder fillet — extracted PCB connection 1')
ax.set_box_aspect((1,1,.45));ax.view_init(28,-50);ax.legend(loc='upper left');fig.tight_layout();fig.savefig('diagnostics/solder_joint.png',dpi=160)

