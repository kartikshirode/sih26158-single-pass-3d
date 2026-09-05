import sys, json, numpy as np
sys.path.insert(0,'src/pipeline')
from render_views import upright_frame

def report(name, d, raw):
    P=np.load(f'out/{d}/points_fused.npy').astype(np.float64)
    cen=np.load(f'out/{d}/cam_centres.npy') if __import__('os').path.exists(f'out/{d}/cam_centres.npy') else None
    B=upright_frame(P,cen); Q=(P-P.mean(0))@B.T
    x,y,z=Q[:,0],Q[:,1],Q[:,2]          # y is up
    fx,fz=np.ptp(x),np.ptp(z)
    # local ground = 5th pct height in each cell of a 40x40 grid over the footprint
    n=40
    ix=np.clip(((x-x.min())/(fx+1e-9)*n).astype(int),0,n-1)
    iz=np.clip(((z-z.min())/(fz+1e-9)*n).astype(int),0,n-1)
    cell=ix*n+iz
    order=np.argsort(cell); cs=cell[order]; ys=y[order]
    edges=np.searchsorted(cs,np.arange(n*n+1))
    g=np.full(n*n,np.nan)
    for i in range(n*n):
        a,b=edges[i],edges[i+1]
        if b-a>=20: g[i]=np.percentile(ys[a:b],5)
    rel=y-g[cell]
    ok=np.isfinite(rel)
    F=np.load(f'out/{raw}/conf.npy')
    s=np.linalg.svd(Q[::17]-Q[::17].mean(0),full_matrices=False)[1]
    print(f'{name}')
    print(f'   conf  median {np.median(F):8.3f}   p30 {np.percentile(F,30):8.3f}   at-floor {(F==F.min()).mean():5.1%}')
    print(f'   fused points {len(P):>9,}   footprint {fx:6.1f} x {fz:6.1f}   relief/footprint {np.ptp(y)/max(fx,fz):.3f}')
    print(f'   flatness {s[2]/s[0]:.3f}   above local ground >0.5 units: {(rel[ok]>0.5).mean():6.2%}   >1.0: {(rel[ok]>1.0).mean():6.2%}')
    print(f'   density {len(P)/(fx*fz):7.1f} pts/sq-unit')

report('Kolu  full clip  (45 views, good pass)','kolu3d','kolu_raw')
report('Short full clip  (45 views over 57 s)','yt3d','yt_raw')
report('Short dense 16 s (42 views, tight baseline)','ytd3d','ytd_raw')
