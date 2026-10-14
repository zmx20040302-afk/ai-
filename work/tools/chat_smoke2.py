import json, urllib.request
B = "http://127.0.0.1:8877"
def post(p, o):
    req = urllib.request.Request(B+p, data=json.dumps(o).encode("utf-8"),
                                 headers={"Content-Type":"application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.status, json.loads(r.read().decode("utf-8"))
for q in ("跑一下 A5 排名，给我分族榜首", "看看远端镜像清单有多少文件"):
    c, r = post("/api/chat", {"message": q})
    print("=" * 70)
    print("Q:", q, "->", c, "mode=", r.get("mode"), "model=", (r.get("llm") or {}).get("model"))
    print("reply:", (r.get("reply") or "")[:500])
    print("ran :", [(t.get("task"), t.get("duration_s")) for t in r.get("tool_trace", [])])
    print("pend:", [(p.get("task"), p.get("title")) for p in r.get("pending", [])])
    print("key leaked:", "sk-" in json.dumps(r, ensure_ascii=False))
