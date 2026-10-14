# -*- coding: utf-8 -*-
"""通过 HTTP 真跑两个任务（证明控制台端到端可用）。"""
import json
import time
import urllib.request

BASE = "http://127.0.0.1:8877"


def post(payload):
    req = urllib.request.Request(BASE + "/api/run", data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    return json.loads(urllib.request.urlopen(req, timeout=30).read().decode())


def wait(jid, timeout=300):
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = json.loads(urllib.request.urlopen(BASE + "/api/job/" + jid, timeout=30).read().decode())
        if j.get("status") != "running":
            return j
        time.sleep(0.4)
    raise SystemExit("超时：" + jid)


for task, args in (("fpeak_stats", {"confirm": True}),
                   ("remote_inventory", {"confirm": True})):
    j = post({"task": task, "args": args})
    print("提交 %-18s → %s" % (task, j.get("job_id") or j))
    done = wait(j["job_id"])
    r = done.get("result", {})
    print("  状态=%s 耗时=%ss" % (done["status"], done.get("duration_s")))
    if task == "fpeak_stats":
        print("  一阶峰：有峰 %s/%s，中位 %s MHz，18–22 MHz 内 %s 个"
              % (r.get("n_with_first_peak"), r.get("n_total"), r.get("median_MHz"),
                 r.get("within_18_22MHz")))
        print("  直方图：", r.get("hist_MHz"))
    else:
        print("  远端：", r.get("parsed"))
    print("  证据：", [(a["path"].split("\\")[-1], a["sha256"][:10]) for a in r.get("artifacts", [])])
    print("  脚本：", (r.get("script") or {}).get("path"), (r.get("script") or {}).get("sha256", "")[:10])
print("\n结论：两个任务都经 HTTP 提交→轮询→拿到结构化结果与哈希证据。")
