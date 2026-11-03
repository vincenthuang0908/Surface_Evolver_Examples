"""Geometry-only mesh helpers for native Surface Evolver model generation.
"""
import math
import numpy as np

PI = math.pi

def annulus_mesh(pin_radius=0.25,pad_radius=0.75,offset=0.0,nr=8,nphi=24):
    if abs(offset)+pin_radius>=pad_radius:
        raise ValueError("Pin intersects or touches the outer contact line")
    phi=np.arange(nphi)*2*PI/nphi; t=np.linspace(0,1,nr+1)
    radius=pin_radius+(pad_radius-pin_radius)*t
    xy=np.array([[(1-tj)*offset+rj*math.cos(p),rj*math.sin(p)]
                 for tj,rj in zip(t,radius) for p in phi])
    faces=[]
    for i in range(nr):
        for j in range(nphi):
            k=(j+1)%nphi
            aa=i*nphi+j;bb=(i+1)*nphi+j;cc=(i+1)*nphi+k;dd=i*nphi+k
            faces.extend([[aa,bb,cc],[aa,cc,dd]])
    return xy,np.array(faces,dtype=int)
