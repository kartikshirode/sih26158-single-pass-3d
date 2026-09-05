import json, numpy as np, cv2
r=json.load(open('out/ytd_raw/mapanything_result.json'))
H,W=r['view_shapes'][0]; n=H*W; v=20
P=np.load('out/ytd_raw/points.npy'); cams=np.load('out/ytd_raw/cameras.npy')
g=P[v*n:(v+1)*n].reshape(H,W,3).astype(np.float64)
D=np.linalg.norm(g-cams[v][:3,3],axis=2)
sp=np.linalg.norm(g[:,1:]-g[:,:-1],axis=2); gsd=float(np.median(sp[np.isfinite(sp)&(sp>0)]))

def curve(D,label):
    out=[]
    for k in (3,5,9,17,33,65):
        Hc,Wc=(H//k)*k,(W//k)*k
        B=D[:Hc,:Wc].reshape(Hc//k,k,Wc//k,k).transpose(0,2,1,3).reshape(-1,k,k)
        yy,xx=np.mgrid[0:k,0:k]; A=np.c_[xx.ravel(),yy.ravel(),np.ones(k*k)]
        Q,_=np.linalg.qr(A); f=B.reshape(-1,k*k).T
        f=f[:,np.isfinite(f).all(0)]
        out.append(float(np.median(np.abs(f-Q@(Q.T@f)))))
    return out

ks=(3,5,9,17,33,65)
real=curve(D,'real')
# the control: throw away everything below one 14px patch, then put it back with the
# smooth interpolant a DPT head uses. If this reproduces the measured curve, the
# sub-patch regime is interpolation and carries no information.
lo=cv2.resize(D,(W//14,H//14),interpolation=cv2.INTER_AREA)
cub=cv2.resize(lo,(W,H),interpolation=cv2.INTER_CUBIC)
# and a pure smooth-curved-surface control: quadratic fit to the whole view
yy,xx=np.mgrid[0:H,0:W]
A=np.c_[xx.ravel(),yy.ravel(),(xx**2).ravel(),(yy**2).ravel(),(xx*yy).ravel(),np.ones(n)]
quad=(A@np.linalg.lstsq(A,D.ravel(),rcond=None)[0]).reshape(H,W)
ci=curve(cub,'cubic'); cq=curve(quad,'quad')
print(f'{"win":>4} {"ground":>8} {"MEASURED":>12} {"gr":>5} | {"14px+bicubic":>13} {"gr":>5} | {"pure quadratic":>15} {"gr":>5}')
for i,k in enumerate(ks):
    gr =f'x{real[i]/real[i-1]:4.2f}' if i else '    -'
    gi =f'x{ci[i]/ci[i-1]:4.2f}'     if i else '    -'
    gq =f'x{cq[i]/cq[i-1]:4.2f}'     if i else '    -'
    print(f'{k:>3}px {k*gsd*100:>7.1f}cm {real[i]*100:>11.3f}cm {gr} | '
          f'{ci[i]*100:>12.3f}cm {gi} | {cq[i]*100:>14.4f}cm {gq}')
