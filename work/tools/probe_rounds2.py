import json, pathlib
A6 = pathlib.Path("work/runs/remote-exported-20260922/a6")
# round1: S1 单个 dict，看看有哪些键
d1 = json.loads((A6/"a6_debug_result.json").read_text(encoding="utf-8"))
s = d1["targets"]["S1_cross_family"]["spl_20MHz_dB"]
print("R1 S1 spl_20MHz_dB keys:", list(s))
print(json.dumps({k: (round(v,6) if isinstance(v,float) else v) for k,v in s.items() if not isinstance(v,(list,dict))}, ensure_ascii=False, indent=1))
print()
for n in ("a6_round2_result.json","a6_round3_result.json"):
    d = json.loads((A6/n).read_text(encoding="utf-8"))
    print("#"*70); print(n, "top keys:", list(d))
    for k in list(d):
        v = d[k]
        if isinstance(v, dict): print("  %s/ keys=%s" % (k, list(v)[:12]))
        elif isinstance(v, list): print("  %s [list len=%d]  [0] keys=%s" % (k, len(v), list(v[0])[:14] if v and isinstance(v[0],dict) else None))
        else: print("  %s = %r" % (k, v))
