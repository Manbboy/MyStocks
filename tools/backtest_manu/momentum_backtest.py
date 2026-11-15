import json, re, statistics as stt, bisect
import os
ROOT=os.path.join(os.path.dirname(os.path.abspath(__file__)),'../../data/series/')
syms=open(os.path.join(os.path.dirname(os.path.abspath(__file__)),'syms.txt')).read().split()
S={}
for s in syms:
    try: r=json.load(open(ROOT+re.sub(r'[.^=]','_',s)+'.json'))['rows']
    except: continue
    if len(r)>600: S[s]=([x[0] for x in r],[x[4] for x in r])
dates=sorted({d for v in S.values() for d in v[0]})
months=[]; 
for i,d in enumerate(dates[:-1]):
    if dates[i+1][:7]!=d[:7]: months.append(d)          # dernier jour de bourse du mois
def px(s,d):
    ds,cs=S[s]; i=bisect.bisect_right(ds,d)-1
    return (cs[i],i) if i>=0 else (None,-1)
def back(s,i,k):
    ds,cs=S[s]; return cs[i-k] if i-k>=0 else None
def rsi_w(s,i):     # RSI 14 hebdo approx. : RSI sur une clôture tous les 5 jours
    ds,cs=S[s]; c=cs[max(0,i-5*60):i+1][::-1][::5][::-1]
    if len(c)<20: return None
    g=l=0
    for j in range(1,len(c)):
        d=c[j]-c[j-1]; gg=max(d,0); ll=max(-d,0)
        if j<=14: g+=gg/14; l+=ll/14
        else: g=(g*13+gg)/14; l=(l*13+ll)/14
    return 100-100/(1+g/l) if l else 100
def score(s,d,kind):
    c,i=px(s,d)
    if c is None or i<260: return None
    m200=sum(S[s][1][i-199:i+1])/200
    if kind=='6m': v=c/back(s,i,126)-1
    elif kind=='12-1': v=back(s,i,21)/back(s,i,252)-1
    elif kind=='3m': v=c/back(s,i,63)-1
    elif kind=='rsiW': v=rsi_w(s,i)
    return v, c>m200
def backtest(kind=None, top=10, filt=False, start='2017-12-31'):
    ms=[m for m in months if m>=start]
    eq=1.0; peak=1; mdd=0; hold={}; curve=[]
    for a,b in zip(ms,ms[1:]):
        if kind is None:   # référence : toutes les actions à parts égales
            pick=[s for s in S if px(s,a)[0] is not None and px(s,a)[1]>=260]
        else:
            sc=[(score(s,a,kind),s) for s in S]; sc=[(v[0],v[1],s) for v,s in sc if v and v[0] is not None]
            if filt: sc=[x for x in sc if x[1]]
            pick=[s for _,_,s in sorted(sc,reverse=True)[:top]]
        new={s:1/len(pick) for s in pick} if pick else {}
        turn=sum(abs(new.get(s,0)-hold.get(s,0)) for s in set(new)|set(hold))
        eq*=1-0.001*turn
        r=sum(w*(px(s,b)[0]/px(s,a)[0]-1) for s,w in new.items()) if new else 0.0
        eq*=1+r; hold=new; peak=max(peak,eq); mdd=max(mdd,1-eq/peak); curve.append((b,eq))
    yrs=len(ms)/12
    return eq-1, eq**(1/yrs)-1, mdd, curve
def sub(curve,a,b):
    pts=[e for d,e in curve if a<=d<=b]; prev=[e for d,e in curve if d<a]
    s0=prev[-1] if prev else 1.0
    return pts[-1]/s0-1 if pts else 0
tests=[('Garder tout (parts égales)',None,0,False)]
for kind in ('6m','12-1','3m','rsiW'):
    for top in (10,20):
        for filt in (False,True): tests.append((f"Top {top} · {kind}{' · au-dessus MM200' if filt else ''}",kind,top,filt))
print(f"{'stratégie':40} {'total':>8} {'par an':>7} {'pire baisse':>11} {'2018-21':>8} {'2022-26':>8}")
for name,kind,top,filt in tests:
    t,cg,dd,cv=backtest(kind,top,filt)
    print(f"{name:40} {t*100:7.0f}% {cg*100:6.1f}% {dd*100:10.0f}% {sub(cv,'2018-01-01','2021-12-31')*100:7.0f}% {sub(cv,'2022-01-01','2026-12-31')*100:7.0f}%")
