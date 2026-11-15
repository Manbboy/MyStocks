import json, re, statistics as stt
import os
ROOT=os.path.join(os.path.dirname(os.path.abspath(__file__)),'../../data/series/')
syms=open(os.path.join(os.path.dirname(os.path.abspath(__file__)),'syms.txt')).read().split()
FEE=0.001
def rsi(c,n=14):
    out=[None]*len(c); g=l=0
    for i in range(1,len(c)):
        d=c[i]-c[i-1]; gg=max(d,0); ll=max(-d,0)
        if i<=n: g+=gg/n; l+=ll/n
        else: g=(g*(n-1)+gg)/n; l=(l*(n-1)+ll)/n
        if i>=n: out[i]=100-100/(1+g/l) if l else 100
    return out
def sma(c,n):
    out=[None]*len(c); s=0
    for i,v in enumerate(c):
        s+=v
        if i>=n: s-=c[i-n]
        if i>=n-1: out[i]=s/n
    return out
def weekly_rsi_daily(rows):
    # RSI hebdo de la dernière semaine TERMINÉE, pour chaque jour (pas de futur)
    import datetime
    wk=[];key=None
    for r in rows:
        d=datetime.date.fromisoformat(r[0]); k=d.isocalendar()[:2]
        if k!=key: wk.append([r[4]]); key=k
        else: wk[-1].append(r[4])
    wc=[w[-1] for w in wk]; wr=rsi(wc)
    out=[]; wi=-1; key=None
    for r in rows:
        d=datetime.date.fromisoformat(r[0]); k=d.isocalendar()[:2]
        if k!=key: wi+=1; key=k
        out.append(wr[wi-1] if wi>=1 else None)
    return out
def run(rows, rule):
    o=[r[1] for r in rows]; c=[r[4] for r in rows]; n=len(c)
    R=rsi(c); M50=sma(c,50); M200=sma(c,200); WR=weekly_rsi_daily(rows) if rule==4 else None
    start=200
    pos=False; entry=0; eq=1.0; peak=1.0; mdd=0; trades=0; wins=0
    curve=[]
    for t in range(start,n-1):
        st=1 if R[t]>=60 else -1 if R[t]<=40 else 0
        buy=sell=False
        if rule==0: buy= st==1 and c[t]>M200[t]; sell= st==-1
        if rule==1: buy= st==1 and c[t]>M200[t]; sell= c[t]<M200[t]
        if rule==2: buy= st==1; sell= st==-1
        if rule==3: buy= st==1 and c[t]>M200[t]; sell= st==-1 and c[t]<M50[t]
        if rule==4: buy= st==1 and WR[t] is not None and WR[t]>=50; sell= WR[t] is not None and WR[t]<40
        if rule==5: buy= M50[t]>M200[t]; sell= M50[t]<M200[t]
        if rule==6: buy= c[t]>M200[t]; sell= c[t]<M200[t]
        if not pos and buy:
            pos=True; entry=o[t+1]*(1+FEE); trades+=1
        elif pos and sell:
            r=o[t+1]*(1-FEE)/entry; eq*=r; wins+= r>1; pos=False
        val=eq*(c[t+1]/entry if pos else 1)
        peak=max(peak,val); mdd=max(mdd,1-val/peak)
    if pos: r=c[-1]/entry; eq*=r; wins+=r>1
    hold=c[-1]/o[start+1]-1
    # baisse max de « garder »
    pk=0; hm=0
    for v in c[start+1:]: pk=max(pk,v); hm=max(hm,1-v/pk)
    years=(n-1-start)/252
    return eq-1, hold, trades, wins, mdd, hm, years
NAMES={0:'RT actuelle',1:'RT + sortie MM200',2:'RT sans filtre',3:'RT + sortie confirmée MM50',4:'RT + tendance hebdo',5:'Croisement MM50/MM200',6:'Cours / MM200'}
data={}
for s in syms:
    try: data[s]=json.load(open(ROOT+re.sub(r'[.^=]','_',s)+'.json'))['rows']
    except: pass
data={s:r for s,r in data.items() if len(r)>800}
print('actions',len(data))
res={}
for rule in NAMES:
    out=[run(r,rule) for r in data.values()]
    tot=[x[0] for x in out]; hold=[x[1] for x in out]
    beat=sum(1 for x in out if x[0]>x[1]); cagr=[(1+x[0])**(1/x[6])-1 for x in out]
    res[rule]=out
    print(f"{NAMES[rule]:28} médiane {stt.median(tot)*100:6.0f} %  moyenne {stt.mean(tot)*100:6.0f} %  par an (méd.) {stt.median(cagr)*100:5.1f} %  bat garder {beat:3}/{len(out)}  trades/action {stt.mean([x[2] for x in out]):5.1f}  gagnants {sum(x[3] for x in out)/max(1,sum(x[2] for x in out))*100:4.0f} %  pire baisse (méd.) {stt.median([x[4] for x in out])*100:4.0f} %")
out=res[0]; hold=[x[1] for x in out]
print(f"{'Garder':28} médiane {stt.median(hold)*100:6.0f} %  moyenne {stt.mean(hold)*100:6.0f} %  par an (méd.) {stt.median([(1+x[1])**(1/x[6])-1 for x in out])*100:5.1f} %  pire baisse (méd.) {stt.median([x[5] for x in out])*100:4.0f} %")
json.dump({str(k):v for k,v in res.items()},open('rules_res.json','w'))
