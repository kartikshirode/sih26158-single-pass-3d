import sys, os, numpy as np
sys.path.insert(0,'src/pipeline')
from render_views import upright_frame

def analyse(name, d):
    P=np.load(f'out/{d}/points_fused.npy').astype(np.float64)
    cen=np.load(f'out/{d}/cam_centres.npy').astype(np.float64)
    c=P.mean(0)
    print(f'\n=== {name} ===')
    for tag, up in (('PCA thin axis (what we ship)', upright_frame(P,cen)[1]),
                    ('camera-derived up',            (cen.mean(0)-c)/np.linalg.norm(cen.mean(0)-c))):
        y = (P-c)@up
        # robust ground plane in the plane orthogonal to `up`
        t=np.array([1.,0,0]) if abs(up[0])<0.9 else np.array([0,1.,0])
        e1=np.cross(up,t); e1/=np.linalg.norm(e1); e2=np.cross(up,e1)
        u,v=(P-c)@e1,(P-c)@e2
        lo=y<np.percentile(y,40)
        coef,*_=np.linalg.lstsq(np.c_[u[lo],v[lo],np.ones(lo.sum())],y[lo],rcond=None)
        h=y-(coef[0]*u+coef[1]*v+coef[2])
        print(f'  {tag:28s} relief p90 {np.percentile(h,90):5.2f}  p99 {np.percentile(h,99):5.2f}  '
              f'p99.9 {np.percentile(h,99.9):5.2f}  max {h.max():6.2f}   >1.5m: {(h>1.5).mean():6.3%}')
    ang=np.degrees(np.arccos(np.clip(abs(upright_frame(P,cen)[1]@((cen.mean(0)-c)/np.linalg.norm(cen.mean(0)-c))),0,1)))
    print(f'  angle between the two "up" estimates: {ang:.1f} deg')
    print(f'  camera track length {np.linalg.norm(cen[1:]-cen[:-1],axis=1).sum():6.1f} m   '
          f'mean height above scene {np.mean((cen-c)@upright_frame(P,cen)[1]):5.1f} m')

analyse('Kolu  (45 views, good survey pass)','kolu3d')
analyse('Short full clip (45 views / 57 s)','yt3d')
analyse('Short dense window (42 views / 16 s)','ytd3d')
