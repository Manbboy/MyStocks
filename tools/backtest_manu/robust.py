import json, sys, random
sys.argv=['x']; import os; os.chdir(os.path.dirname(os.path.abspath(__file__))); exec(open('filters.py').read().split("rnd=random.Random(5)")[0])
rule=RULES['tendance + RSI ≥ 50']
syms=sorted({e['sym'] for e in data}); A=set(syms[::2])
for tp,sl in [(0.05,0.03),(0.08,0.03),(0.05,0.05)]:
  out={}
  for seed in (5,6,7):
    rnd=random.Random(seed)
    for e in data:
        rows=series(e['sym']); I=ind(e['sym']); t=e['t']; C=e['C']
        per='2021-23' if e['date']<'2024-01-01' else '2024-26'; grp='valeurs A' if e['sym'] in A else 'valeurs B'
        for g in top3(groups(e['votes'],C)):
            if not(g['mid']<C and g['hi']<C*0.995): continue
            d=abs(g['mid']/C-1)*rnd.uniform(0.6,1.4); m=C*(1-d)
            for key in (per,grp,'tout'):
                if seed==5:
                    x=trade(rows,I,t,g['lo'],g['hi'],rule,tp=tp,sl=sl)
                    if x is not None: out.setdefault((key,'Manu'),[]).append(x)
                y=trade(rows,I,t,m*0.985,m*1.015,rule,tp=tp,sl=sl)
                if y is not None: out.setdefault((key,'hasard'),[]).append(y)
  print(f"--- objectif +{tp:.0%} / stop {sl:.0%} sous la zone")
  for k in sorted(out):
      v=out[k]; print(f"  {k[0]:10} {k[1]:7} trades {len(v):5}  gagnants {sum(1 for x in v if x>=tp-0.0001)/len(v):5.1%}  gain moyen {sum(v)/len(v):+.2%}")
