import json, numpy as np
def roughness(d, v, label):
    r=json.load(open(f'{d}/mapanything_result.json'))
    H,W=r['view_shapes'][0]; n=H*W
    P=np.load(f'{d}/points.npy'); cams=np.load(f'{d}/cameras.npy')
    M=np.load(f'{d}/mask.npy')[v*n:(v+1)*n].reshape(H,W)
    F=np.load(f'{d}/conf.npy')[v*n:(v+1)*n].reshape(H,W)
    g=P[v*n:(v+1)*n].reshape(H,W,3).astype(np.float64)
    D=np.linalg.norm(g-cams[v][:3,3],axis=2)
    D[~M]=np.nan                                   # drop sky / ambiguous
    sp=np.linalg.norm(g[:,1:]-g[:,:-1],axis=2)
    gsd=float(np.median(sp[np.isfinite(sp)&(sp>0)]))
    print(f'\n{label}   grid {H}x{W}   depth {np.nanmedian(D):.1f} m   GSD {gsd*100:.2f} cm/px'
          f'   valid {np.isfinite(D).mean():.0%}   conf med {np.median(F):.1f}')
    print(f'{"window":>8} {"ground size":>12} {"detrended relief (MEDIAN |resid|)":>34}')
    prev=None
    for k in (3,5,9,17,33,65,129):
        Hc,Wc=(H//k)*k,(W//k)*k
        B=D[:Hc,:Wc].reshape(Hc//k,k,Wc//k,k).transpose(0,2,1,3).reshape(-1,k,k)
        yy,xx=np.mgrid[0:k,0:k]
        A=np.c_[xx.ravel(),yy.ravel(),np.ones(k*k)]
        Q,_=np.linalg.qr(A)
        f=B.reshape(-1,k*k).T
        ok=np.isfinite(f).all(0)                   # only fully-valid blocks
        f=f[:,ok]
        resid=f-Q@(Q.T@f)
        med=float(np.median(np.abs(resid)))
        gr=f'  x{med/prev:4.2f}' if prev else ''
        print(f'{k:>6}px {k*gsd*100:>10.1f} cm {med*100:>28.2f} cm{gr}   ({ok.sum():,} blocks)')
        prev=med
roughness('out/ytd_raw',20,'Short dense window, view 20')
roughness('out/kolu_raw',22,'Kolu survey pass, view 22')
