import json, time, urllib.request
B = "http://127.0.0.1:8877"
def post(p, o):
    req = urllib.request.Request(B+p, data=json.dumps(o).encode("utf-8"),
                                 headers={"Content-Type":"application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=180) as r:
        return r.status, json.loads(r.read().decode("utf-8"))
def get(p):
    with urllib.request.urlopen(B+p, timeout=120) as r:
        return json.loads(r.read().decode("utf-8"))
# 「允许执行」按钮走的正是这条路径
c, r = post("/api/run", {"task":"fpeak_stats","args":{"confirm":True}})
print("submit", c, r.get("job_id"))
for _ in range(120):
    j = get("/api/job/"+r["job_id"])
    if j.get("status") != "running":
        break
    time.sleep(0.4)
res = j.get("result") or {}
print("status", j.get("status"), "dur", j.get("duration_s"), "s")
for k in ("n_total","n_with_first_peak","median_MHz","hist_MHz","within_18_22MHz"):
    print(" ", k, "=", res.get(k))
print("def:", (res.get("definition") or "")[:110])
print("artifact:", [(a["path"].split("\\")[-1], a["sha256"][:10]) for a in res.get("artifacts",[])])
