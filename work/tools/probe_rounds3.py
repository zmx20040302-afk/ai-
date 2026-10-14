import json, pathlib
A6 = pathlib.Path("work/runs/remote-exported-20260922/a6")
for n in ("a6_round2_result.json","a6_round3_result.json"):
    d = json.loads((A6/n).read_text(encoding="utf-8"))
    print("#"*78); print(n)
    sp = d["splits"]["R2-S1o"]
    print("R2-S1o keys:", list(sp))
    if "models" in sp:
        for m, v in sp["models"].items():
            print("   %-4s keys=%s" % (m, list(v)[:12]))
            break
    if n.startswith("a6_round2"):
        print("T_C R2-S1o keys:", list(d["T_C"]["R2-S1o"]))
        mk = list(d["T_C"]["R2-S1o"])[:6]
        for m in mk:
            v = d["T_C"]["R2-S1o"][m]
            print("   T_C %s -> %s" % (m, json.dumps(v, ensure_ascii=False)[:200]))
