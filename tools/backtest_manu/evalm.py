import json, sys, random, re, glob
from collections import defaultdict
import os
ROOT=os.path.join(os.path.dirname(os.path.abspath(__file__)),'../../data/series/')
RW = None   # poids par sous-type (None = poids d'origine)

def subtype(v):
    lo,hi,w,fam,txt=v[:5]
    tf = 'D' if ' jour' in txt else 'W' if ' hebdo' in txt else 'M' if 'mensuel' in txt else 'Q' if 'trimestriel' in txt else '?'
    if fam=='ma': m=re.match(r'MM(\d+)',txt); return f"ma{m.group(1)}{tf}"
    if fam=='flip': return ('rs' if 'R→S' in txt else 'sr')+tf
    if fam=='sr': return ('sup' if txt.startswith('Support') else 'res')+tf
    if fam=='tl': return ('tlsup' if 'support' in txt else 'tlres')+tf
    if fam=='chan': return ('chlo' if txt.startswith('Bas') else 'chup')+tf
    return fam

def groups(votes, C, W=None, minscore=3, gap=0.01, width=0.04, decay=0.5, core=0.015):
    V=[]
    for v in votes:
        st=subtype(v); w=v[2] if W is None else W.get(st, v[2])
        if w<=0: continue
        V.append(dict(lo=v[0],hi=v[1],w=w,fam=v[3],st=st,mid=(v[0]+v[1])/2))
    V.sort(key=lambda x:x['mid']); G=[]
    for v in V:
        g=G[-1] if G else None
        if g and v['lo']<=g['hi']+C*gap and max(g['hi'],v['hi'])-min(g['lo'],v['lo'])<=C*width:
            g['v'].append(v); g['lo']=min(g['lo'],v['lo']); g['hi']=max(g['hi'],v['hi'])
        else: G.append(dict(lo=v['lo'],hi=v['hi'],v=[v]))
    for g in G:
        seen=set(); sc=0
        for v in sorted(g['v'],key=lambda x:-x['w']):
            sc+=v['w']*(decay if v['fam'] in seen else 1); seen.add(v['fam'])
        W_=sum(v['w'] for v in g['v']); mid=sum(v['mid']*v['w'] for v in g['v'])/W_
        g['score']=sc; g['mid']=mid; g['lo']=max(g['lo'],mid*(1-core)); g['hi']=min(g['hi'],mid*(1+core))
        if g['hi']-g['lo']<mid*0.006: g['lo'],g['hi']=mid*0.997,mid*1.003
        g['fams']=len(seen); g['n']=len(g['v'])
    return G

def top3(G, minscore=3):
    best=sorted([g for g in G if g['score']>=minscore and g['n']>=2],key=lambda g:-g['score']); keep=[]
    for g in best:
        if any(g['lo']<k['hi']*1.01 and g['hi']>k['lo']*0.99 for k in keep): continue
        keep.append(g)
        if len(keep)==3: break
    return keep

def outcome(rows, t, lo, hi, buy, H=20, R=10, up=0.03, stop=0.02):
    n=len(rows)
    for k in range(t+1, min(n, t+1+H)):
        if (buy and rows[k][3]<=hi) or (not buy and rows[k][2]>=lo):
            for j in range(k, min(n, k+R+1)):
                if buy:
                    if rows[j][4]<lo*(1-stop): return 'fail'
                    if rows[j][2]>=hi*(1+up): return 'ok'
                else:
                    if rows[j][4]>hi*(1+stop): return 'fail'
                    if rows[j][3]<=lo*(1-up): return 'ok'
            return 'neutral'
    return 'notouch'

_cache={}
def series(sym):
    if sym not in _cache: _cache[sym]=json.load(open(ROOT+re.sub(r'[.^=]','_',sym)+'.json'))['rows']
    return _cache[sym]

def run(data, W=None, minscore=3, buckets=(3,5,7,10,99), allgroups=False, seed=1):
    rnd=random.Random(seed)
    st=defaultdict(lambda: defaultdict(int)); base=defaultdict(int)
    for e in data:
        rows=series(e['sym']); t=e['t']; C=e['C']
        G=groups(e['votes'],C,W)
        sel = [g for g in G if g['n']>=2] if allgroups else top3(G,minscore)
        for g in sel:
            buy=g['mid']<C
            if buy and g['hi']>=C*0.995: continue        # zone sous les pieds
            if not buy and g['lo']<=C*1.005: continue
            o=outcome(rows,t,g['lo'],g['hi'],buy)
            b=next(x for x in buckets if g['score']<x)
            st[('achat' if buy else 'résist', b)][o]+=1
            # témoin : zone au hasard à la même distance, de l'autre côté du hasard
            d=abs(g['mid']/C-1)*rnd.uniform(0.6,1.4); mid=C*(1-d) if buy else C*(1+d)
            o2=outcome(rows,t,mid*0.985,mid*1.015,buy); base[('achat' if buy else 'résist',o2)]+=1
    return st, base

def rate(c):
    tch=c['ok']+c['fail']+c['neutral']; tot=tch+c['notouch']
    return tch, (c['ok']/tch if tch else 0), (c['fail']/tch if tch else 0), (tch/tot if tot else 0)

if __name__=='__main__':
    data=[]
    for f in sys.argv[1:]: data+=json.load(open(f))
    print('dates', len(data))
    st,base=run(data)
    for k in sorted(st):
        n,ok,fl,tr=rate(st[k]); print(f"{k[0]:7} force<{k[1]:3}  zones touchées {n:5}  réussite {ok:5.1%}  échec {fl:5.1%}  (touchée {tr:4.0%})")
    for side in ('achat','résist'):
        c={o:base[(side,o)] for o in ('ok','fail','neutral','notouch')}; n,ok,fl,tr=rate(c)
        print(f"témoin {side}: touchées {n}  réussite {ok:5.1%} échec {fl:5.1%}")
