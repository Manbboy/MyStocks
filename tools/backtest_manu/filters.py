import json, sys, random
sys.argv=['x']; import os; os.chdir(os.path.dirname(os.path.abspath(__file__))); exec(open('evalm.py').read().split("if __name__")[0])
data=json.load(open('va.json'))+json.load(open('vb.json'))
IND={}
def ind(sym):
    if sym in IND: return IND[sym]
    r=series(sym); n=len(r); c=[x[4] for x in r]
    def sma(k):
        out=[None]*n; s=0
        for i in range(n):
            s+=c[i]
            if i>=k: s-=c[i-k]
            if i>=k-1: out[i]=s/k
        return out
    rsi=[None]*n; g=l=0
    for i in range(1,n):
        d=c[i]-c[i-1]; gg=max(d,0); ll=max(-d,0)
        if i<=14: g+=gg/14; l+=ll/14
        else: g=(g*13+gg)/14; l=(l*13+ll)/14
        if i>=14: rsi[i]=100-100/(1+g/l) if l else 100
    vol=[x[5] if len(x)>5 else 0 for x in r]; v20=[None]*n; s=0
    for i in range(n):
        s+=vol[i]
        if i>=20: s-=vol[i-20]
        if i>=19: v20[i]=s/20
    IND[sym]=dict(m50=sma(50),m200=sma(200),rsi=rsi,v20=v20,vol=vol); return IND[sym]

RULES = {
 'réaction seule':        lambda r,I,j: True,
 'tendance haussière':    lambda r,I,j: I['m200'][j] and r[j][4]>I['m200'][j] and I['m50'][j]>I['m200'][j],
 'RSI Trends vert':       lambda r,I,j: I['rsi'][j] and I['rsi'][j]>=60,
 'RSI ≥ 50':              lambda r,I,j: I['rsi'][j] and I['rsi'][j]>=50,
 'tendance + RT vert':    lambda r,I,j: I['m200'][j] and r[j][4]>I['m200'][j] and I['m50'][j]>I['m200'][j] and I['rsi'][j]>=60,
 'tendance + RSI ≥ 50':   lambda r,I,j: I['m200'][j] and r[j][4]>I['m200'][j] and I['m50'][j]>I['m200'][j] and I['rsi'][j]>=50,
 'bougie franche':        lambda r,I,j: r[j][4]>r[j][1] and r[j][4]>r[j-1][2],
 'tendance + bougie':     lambda r,I,j: I['m200'][j] and r[j][4]>I['m200'][j] and I['m50'][j]>I['m200'][j] and r[j][4]>r[j][1] and r[j][4]>r[j-1][2],
 'volume ≥ 1,3×':         lambda r,I,j: I['v20'][j] and I['vol'][j]>=1.3*I['v20'][j],
 'tendance + volume':     lambda r,I,j: I['m200'][j] and r[j][4]>I['m200'][j] and I['m50'][j]>I['m200'][j] and I['v20'][j] and I['vol'][j]>=1.3*I['v20'][j],
}
def trade(rows,I,t,lo,hi,rule,H=20,W=5,R=20,tp=0.05,sl=0.03):
    n=len(rows)
    for k in range(t+1,min(n,t+1+H)):
        if rows[k][3]<=hi:
            for j in range(k,min(n,k+W+1)):
                if rows[j][4]<lo*(1-sl): return None
                if rows[j][4]>hi:
                    if not rule(rows,I,j): return None     # réaction sans le filtre : pas d'achat
                    e=rows[j][4]; stop=lo*(1-sl)
                    for q in range(j+1,min(n,j+R+1)):
                        if rows[q][3]<=stop: return stop/e-1
                        if rows[q][2]>=e*(1+tp): return tp
                    return rows[min(n-1,j+R)][4]/e-1
            return None
    return None
rnd=random.Random(5)
res={(nm,w):[] for nm in RULES for w in ('Manu','hasard','Manu ★★★')}
for e in data:
    rows=series(e['sym']); I=ind(e['sym']); t=e['t']; C=e['C']
    zs=[g for g in top3(groups(e['votes'],C)) if g['mid']<C and g['hi']<C*0.995]
    rz=[]
    for g in zs:
        d=abs(g['mid']/C-1)*rnd.uniform(0.6,1.4); m=C*(1-d); rz.append((m*0.985,m*1.015))
    for nm,rule in RULES.items():
        for g,(rlo,rhi) in zip(zs,rz):
            x=trade(rows,I,t,g['lo'],g['hi'],rule)
            if x is not None:
                res[(nm,'Manu')].append(x)
                if g['score']>=7: res[(nm,'Manu ★★★')].append(x)
            y=trade(rows,I,t,rlo,rhi,rule)
            if y is not None: res[(nm,'hasard')].append(y)
print(f"{'règle':22} {'qui':9} {'trades':>6} {'gagnants':>9} {'gain moyen':>11}")
for nm in RULES:
    for w in ('Manu','Manu ★★★','hasard'):
        v=res[(nm,w)]
        if not v: continue
        print(f"{nm:22} {w:9} {len(v):6} {sum(1 for x in v if x>=0.0499)/len(v):9.1%} {sum(v)/len(v):+10.2%}")
