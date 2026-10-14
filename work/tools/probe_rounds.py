import json, pathlib
A6 = pathlib.Path("work/runs/remote-exported-20260922/a6")
def walk(o, p="", d=0, maxd=3):
    if d > maxd: return
    if isinstance(o, dict):
        for k, v in list(o.items())[:14]:
            if isinstance(v, (dict, list)):
                print("  "*d + "%s/ (%s, len=%d)" % (k, type(v).__name__, len(v))); walk(v, p+"/"+k, d+1, maxd)
            else:
                print("  "*d + "%s = %r" % (k, v if not isinstance(v,float) else round(v,6)))
    elif isinstance(o, list) and o:
        print("  "*d + "[0] ->"); walk(o[0], p+"[0]", d+1, maxd)
for n in ("a6_debug_result.json","a6_round2_result.json","a6_round3_result.json"):
    p = A6/n
    print("#"*80); print(n, p.stat().st_size, "B")
    d = json.loads(p.read_text(encoding="utf-8"))
    print("top keys:", list(d)[:20])
    walk(d, maxd=2)
