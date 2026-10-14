import json, time, urllib.request
B = "http://127.0.0.1:8877"
def post(p, o):
    req = urllib.request.Request(B+p, data=json.dumps(o).encode("utf-8"),
                                 headers={"Content-Type":"application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=600) as r:
        return r.status, json.loads(r.read().decode("utf-8"))
def get(p):
    with urllib.request.urlopen(B+p, timeout=300) as r:
        return json.loads(r.read().decode("utf-8"))
c, r = post("/api/run", {"task":"sweep_analysis","args":{"confirm":True}})
print("submit", c, r.get("job_id"))
for _ in range(300):
    j = get("/api/job/"+r["job_id"])
    if j.get("status") != "running":
        break
    time.sleep(0.5)
res = j.get("result") or {}
print("status", j.get("status"), "dur", j.get("duration_s"))
print("verdict", res.get("verdict"), "released_families", res.get("released_families"))
print("verdict_by_family", json.dumps(res.get("verdict_by_family"), ensure_ascii=False))
for t in (res.get("tops") or [])[:4]:
    print("  ", t.get("family"), t.get("metric"), t.get("caliber"), t.get("n_available"), t.get("n_excluded"))
print("artifacts", [(a["path"].split("\\")[-1], a["sha256"][:8]) for a in res.get("artifacts",[])])
print("script", res.get("script",{}).get("path"), (res.get("script",{}).get("sha256") or "")[:8])
