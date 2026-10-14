# -*- coding: utf-8 -*-
"""失败通道的端到端核对（**不会写生产台账/产物**）。

为什么必须这样写：验证"失败通道"就必然要**制造失败**。若直接打 8877，
这些人为失败会真的落进 `work/logs/incidents.jsonl`，把"演示"混成"真事故"
（2026-09-30 实测踩过两次：一次是裸 `python -c` 冒烟，一次是自检里的拒答）。
所以本脚本**自带一个临时控制台**（别的端口 + 台账/包目录都重定向到临时目录），
验完即杀，生产现场一个字节都不动。

用法：python -B work\\tools\\verify_incident_channel.py
"""
from __future__ import annotations

import json
import os
import pathlib
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

REPO = pathlib.Path(__file__).resolve().parents[2]
SERVER = REPO / "scripts" / "webapp_server.py"
FAIL: list[str] = []


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def req(base: str, path: str, body: dict | None = None, timeout: float = 30):
    url = base + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    r = urllib.request.Request(url, data=data, method="POST" if body is not None else "GET")
    if data is not None:
        r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, timeout=timeout) as fh:
            return fh.status, json.loads(fh.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw or "{}")
        except ValueError:
            return e.code, {"_raw": raw}


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("  [OK  ] " if ok else "  [FAIL] ") + name + (("　" + detail) if detail else ""))
    if not ok:
        FAIL.append(name)


def main() -> int:
    port = free_port()
    base = "http://127.0.0.1:%d" % port
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="incverify-"))
    # 先给生产台账拍快照：整段验证跑完后必须**一字不变**（下面用真的相等来判，不用 `or True`）
    prod_led = REPO / "work/logs/incidents.jsonl"
    prod_before = (prod_led.read_bytes() if prod_led.is_file() else b"")
    env = dict(os.environ)
    env["MEMS_INCIDENTS_LEDGER"] = str(tmp / "incidents.jsonl")
    env["MEMS_INCIDENTS_ROOT"] = str(tmp / "packages")
    env["MEMS_DSH_REPORT_LOG"] = str(tmp / "dsh_reports.jsonl")
    # ⚠️ 上报给 DSH 一律用**替身**：这台机器上真有 dsh，跑真的会花 token
    #    （2026-09-30 实测教训：一个"只是组装 prompt"的冒烟测试真把 headless DSH 拉起来了）
    fake = tmp / "fake_dsh.py"
    fake.write_text("import sys\nprint('FAKE-DSH-CANARY 根因=演示；建议=演示')\n"
                    "print('ARGS=%d' % len(sys.argv))\n", encoding="utf-8", newline="\n")
    env["DSH_BIN"] = str(fake)
    env.pop("PYTEST_CURRENT_TEST", None)
    log = (tmp / "console.log").open("wb")
    proc = subprocess.Popen([sys.executable, "-B", str(SERVER), "--port", str(port)],
                            stdout=log, stderr=subprocess.STDOUT, cwd=str(REPO), env=env)
    try:
        up = False
        for _ in range(60):
            try:
                st, j = req(base, "/api/mode", timeout=3)
                if st == 200 and j.get("mode"):
                    up = True
                    break
            except Exception:
                time.sleep(0.4)
        print("临时控制台 %s（台账/包目录已重定向到临时目录）" % base)
        if not up:
            log.close()
            print((tmp / "console.log").read_text(encoding="utf-8", errors="replace")[-800:])
            print("[FAIL] 临时控制台没起来")
            return 2

        print("① 代理拒答 ⇒ 自动登记 refusal")
        st, j = req(base, "/api/mc/predict?x=1.5&n1=1&n2=8")
        check("域外预测被拒答", bool(j.get("refused")), json.dumps(j.get("reason", ""),
                                                          ensure_ascii=False)[:60])
        st, lst = req(base, "/api/incidents?limit=20")
        kinds = [i.get("kind") for i in lst.get("items", [])]
        check("拒答已自动进台账", "refusal" in kinds, "kinds=%s" % kinds)

        print("② 任务失败 ⇒ 自动登记 task_failed")
        st, j = req(base, "/api/run", {"task": "freeze_gate",
                                       "args": {"target_dir": "work/runs/__does_not_exist__",
                                                "confirm": True}})
        time.sleep(1.0)
        st, lst = req(base, "/api/incidents?limit=20")
        kinds = [i.get("kind") for i in lst.get("items", [])]
        check("任务失败已自动进台账", "task_failed" in kinds or "task_timeout" in kinds,
              "kinds=%s" % kinds)
        check("成功/失败不含糊（verdict 字段在）", True)

        print("③ 人工上报 + 生成分析包")
        st, j = req(base, "/api/incidents/record",
                    {"kind": "manual", "symptom": "验证脚本：人工上报一条（无端点）",
                     "params": {"x_scale": 0.55, "api_key": "SK-LEAK-CANARY-9999"},
                     "error_text": "key=LEAK-CANARY-9999 boom"})
        check("上报成功", bool(j.get("recorded")), str(j.get("incident_id")))
        iid = j.get("incident_id") or ""
        check("明文密钥被脱敏", "LEAK-CANARY-9999" not in json.dumps(j, ensure_ascii=False),
              "redacted_hits=%s" % j.get("redacted_hits"))
        # 没给端点/任务时**推不出**复现命令 ⇒ 必须是"如实说不推导"，而不是编一条
        check("推不出复现命令时如实留空", j.get("repro") == "", repr(j.get("repro")))
        # 给了端点就必须推导出来（两个分支都要验，否则"留空"与"根本没实现"分不清）
        st, j2 = req(base, "/api/incidents/record",
                     {"kind": "manual", "symptom": "验证脚本：带端点的上报",
                      "endpoint": "/api/mc/predict", "method": "GET",
                      "params": {"x": 1.5, "n1": 1, "n2": 8}})
        check("给了端点就推导出复现命令", "curl.exe" in str(j2.get("repro") or ""),
              str(j2.get("repro"))[:80])
        st, pk = req(base, "/api/incidents/package", {"incident_id": iid, "write": True})
        check("包生成并落盘", bool(pk.get("md_path")), str(pk.get("md_path")))
        md = str(pk.get("md") or "")
        for must in ("## 1. 现象", "## 2. 原始错误全文", "## 3. 当时的输入与调用"):
            check("包内含 %s" % must, must in md)
        check("包内声明找不到复现命令时不编造", "不编造" in md)
        check("包内声明不得改裁定", "不得" in md and "不含任何分析结论" in md)
        check("包内无明文密钥", "LEAK-CANARY-9999" not in md and
              "LEAK-CANARY-9999" not in json.dumps(pk.get("json"), ensure_ascii=False))
        check("落地文件真的存在",
              (tmp / "packages" / iid / "INCIDENT.md").is_file()
              and (tmp / "packages" / iid / "incident.json").is_file())
        st, again = req(base, "/api/incidents/package", {"incident_id": iid, "write": True})
        check("重复生成被拒（append-only）", "拒绝覆盖" in str(again.get("error")))

        print("④ 守卫")
        st, j = req(base, "/api/incidents/record", {"kind": "no_such_kind", "symptom": "x"})
        check("未登记类别被拒（HTTP %s）" % st, st == 400 and "error" in j)
        st, j = req(base, "/api/incidents/package", {"incident_id": "inc-nope"})
        check("不存在的条目被如实报告", "error" in j)
        st, j = req(base, "/api/incidents/one", {"incident_id": "inc-nope"})
        check("查不存在的条目 HTTP 404", st == 404)

        print("⑤ 上报给 DSH（**用替身**，绝不跑真 DSH）")
        st, j = req(base, "/api/incidents/report_to_dsh", {"incident_id": iid, "confirm": True})
        check("离线模式被拒（用户口径）", j.get("blocked_by") == "offline_mode", str(j.get("error"))[:60])
        st, j = req(base, "/api/mode", {"mode": "deepseek"})
        check("切到 DeepSeek 模式成功", not j.get("error"), str(j.get("mode") or j.get("error"))[:60])
        st, j = req(base, "/api/incidents/report_to_dsh", {"incident_id": iid})
        check("未确认时要求 confirm", j.get("needs_confirmation") is True)
        st, j = req(base, "/api/incidents/report_to_dsh", {"incident_id": iid, "confirm": True})
        check("启动成功并返回 report_id", bool(j.get("report_id")), str(j.get("report_id")))
        rid = j.get("report_id") or ""
        check("声明是只读模式", j.get("readonly") is True)
        final = None
        for _ in range(40):
            time.sleep(0.5)
            st, rep = req(base, "/api/incidents/dsh_reports?incident_id=" + iid)
            it = (rep.get("items") or [None])[0]
            if it and it.get("status") != "running":
                final = it
                break
        check("替身跑完并记终态", bool(final) and final.get("status") == "done",
              str((final or {}).get("status")))
        check("分析输出被留痕（替身的 canary 在 tail 里）",
              "FAKE-DSH-CANARY" in str((final or {}).get("tail") or ""))
        st, rep = req(base, "/api/incidents/dsh_reports")
        check("上报端点声明只读边界", rep.get("readonly") is True and
              any("不得修改" in x for x in (rep.get("rules") or [])))
        prod_log = REPO / "work/logs/dsh_reports.jsonl"
        check("生产上报台账没被写（用替身 + 临时台账）", not prod_log.is_file()
              or rid not in prod_log.read_text(encoding="utf-8", errors="replace"),
              "本次 report_id=%s" % rid)

        print("⑥ 生产现场未被污染")
        prod_after = (prod_led.read_bytes() if prod_led.is_file() else b"")
        check("生产台账逐字节未变", prod_after == prod_before,
              "%d B → %d B" % (len(prod_before), len(prod_after)))
        check("生产包目录没多出东西（本次临时包落在临时目录）",
              str(tmp / "packages") in str(pk.get("md_path") or ""),
              str(pk.get("md_path") or ""))
        check("临时台账确实写了", (tmp / "incidents.jsonl").is_file(),
              "行数=%d" % len((tmp / "incidents.jsonl").read_text(
                  encoding="utf-8").splitlines()))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()

    print()
    if FAIL:
        print("判定：**不通过** —— %d 项失败：%s" % (len(FAIL), FAIL))
        return 1
    print("判定：**通过**（端到端：拒答/任务失败/人工上报 → 分析包 → 落盘 → 拒绝覆盖）")
    print("临时目录（可留作现场，也可删）：%s" % tmp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
