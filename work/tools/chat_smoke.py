import json, urllib.request, sys
B = "http://127.0.0.1:8877"
def get(p):
    with urllib.request.urlopen(B+p, timeout=60) as r:
        return r.status, json.loads(r.read().decode("utf-8"))
def post(p, o):
    import urllib.error
    req = urllib.request.Request(B+p, data=json.dumps(o).encode("utf-8"),
                                 headers={"Content-Type":"application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))
with urllib.request.urlopen(B+"/", timeout=30) as r:
    html = r.read().decode("utf-8")
print("index", r.status, len(html.encode("utf-8")), "bytes")
for n in ['id="log"','id="inp"','id="tasks"','id="mode"','/api/chat','/api/chat/mode','允许执行']:
    print("  has", n, n in html)
print("jobs ->", list(json.loads(urllib.request.urlopen(B+"/api/jobs", timeout=30).read().decode("utf-8"))["tasks"]))
print("mode ->", get("/api/chat/mode"))
print("state ->", get("/api/task/state"))
c, r = post("/api/chat", {"message":"一阶谐振在多少 MHz？"})
print("chat", c, "mode=", r.get("mode"), "trace=", [t.get("task") for t in r.get("tool_trace",[])])
print("reply:", (r.get("reply") or "")[:400])
