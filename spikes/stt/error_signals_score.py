import json, sys, numpy as np, collections
d=json.load(open(sys.argv[1])); R=d["rows"]; T=d["timing"]
print("whisper",d["whisper"],"words",len(R),"forced present",sum(r["forced"] is not None for r in R),"margin present",sum(r["margin"] is not None for r in R))
def auc(score,y):
    s=np.array(score,float); y=np.array(y); pos=s[y==1]; neg=s[y==0]
    if not len(pos) or not len(neg): return float("nan")
    return float(np.mean([(p<neg).mean()+0.5*(p==neg).mean() for p in pos]))
def recall_at(score,y,fpr=0.05):
    s=np.array(score,float); y=np.array(y); neg=np.sort(s[y==0]); thr=neg[int(len(neg)*fpr)]
    return float((s[y==1]<thr).mean()), float(thr)
groups={"all":R,"read":[r for r in R if r["set"]=="read"],"noisy(tv/music/far)":[r for r in R if r["set"] not in("read","kept")],"kept (owner)":[r for r in R if r["set"]=="kept"]}
for g,rows in groups.items():
    y=[r["wrong"] for r in rows]; n=len(rows); e=sum(y)
    clips=collections.defaultdict(list)
    for r in rows: clips[r["clip"]].append(r)
    print(f"\n== {g}: {len(clips)} clips, {n} words, {e} wrong ({e/n:.1%}); deletions {sum(c[0]['dels'] for c in clips.values())}; parakeet right {sum(c[0]['p_right'] for c in clips.values())}, whisper right {sum(c[0]['w_right'] for c in clips.values())}")
    w=[r for r in rows if r["wrong"]]; ok=[r for r in rows if not r["wrong"]]
    if not w: continue
    for name,get in (("parakeet p",lambda r:r["p"]),("top-2 margin",lambda r:r["margin"]),("whisper forced p",lambda r:r["forced"] if r["forced"] is not None else 0.0)):
        rr=[r for r in rows if get(r) is not None]; s=[get(r) for r in rr]; yy=[r["wrong"] for r in rr]
        rc,thr=recall_at(s,yy); print(f"  {name:18} AUC {auc(s,yy):.2f}  catches {rc:.0%} of wrong words at 5% false flags (thr {thr:.2f})")
    for nm,f in (("whisper disagrees",lambda r:r["disagree"]),("existing p<0.4",lambda r:r["p"]<0.4),("p<0.4 OR disagree",lambda r:r["p"]<0.4 or r["disagree"]),("p<0.4 AND disagree",lambda r:r["p"]<0.4 and r["disagree"]),("disagree AND forced<0.5",lambda r:r["disagree"] and (r["forced"] or 0)<0.5)):
        print(f"  {nm:24}: {np.mean([bool(f(r)) for r in w]):.0%} of wrong words, {np.mean([bool(f(r)) for r in ok]):.1%} of right words")
    bad=[c for c in clips.values() if not c[0]["p_right"]]; good=[c for c in clips.values() if c[0]["p_right"]]
    print(f"  wrong sentences {len(bad)}: any p<0.4 in {sum(any(r['p']<0.4 for r in c) for c in bad)}, any disagree in {sum(any(r['disagree'] for r in c) for c in bad)} | right sentences {len(good)}: any p<0.4 in {sum(any(r['p']<0.4 for r in c) for c in good)}, any disagree in {sum(any(r['disagree'] for r in c) for c in good)}")
rd=groups["read"]
print("\nread set, right words whisper disputes:", sorted({r["word"] for r in rd if not r["wrong"] and r["disagree"]})[:40])
print("read set, wrong words whisper agrees with:", sorted({r["word"] for r in rd if r["wrong"] and not r["disagree"]})[:30])
print("read set, wrong words:", sorted({r["word"] for r in rd if r["wrong"]})[:60])
for k,v in T.items(): print(k, "p50 %.2f p90 %.2f"%(np.percentile(v,50),np.percentile(v,90)))
