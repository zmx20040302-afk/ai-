# -*- coding: utf-8 -*-
"""**证明**网页控制台真的活着（而不是"启动后 4 秒看了一眼"）。

为什么需要它（2026-09-29 实测教训）：我用 `serve_detached.ps1 -Action start` 启动，
然后**在 4 秒内**探测端口、看到 HTTP 200 就宣布"已跑起来"。结果进程在一两分钟后被终止，
用户去打开时端口已经关了——**"启动成功"不等于"持续可用"**。
所以本工具默认：探测 → 等 `--settle` 秒 → **再探测一次** → 两次都通过才算通过。

检查项：
1. 端口在监听（TCP connect）；
2. `GET /` 返回 200，且**字节与磁盘上的 `scripts/webapp_page.html` 完全一致**（防止旧页缓存）；
3. `Cache-Control` 含 `no-store`；
4. `GET /api/mode` 必须 `network_allowed=false`（默认离线）；
5. `POST /api/surrogate/predict` 一个**接受**例：必须带 `model_id`/`certified`/`band_simultaneous_dB`；
6. 一个**拒答**例（角点）：必须 `refused=true` 且**不含任何数字**；
7. 等待 `--settle` 秒后**重复 1–2**，确认进程没死。

用法：
    python -B work/tools/verify_web_services.py
    python -B work/tools/verify_web_services.py --port 8877 --settle 180
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import socket
import sys
import time
import urllib.request

REPO = pathlib.Path(__file__).resolve().parents[2]
PAGE = REPO / "scripts/webapp_page.html"


def _probe(port: int) -> bool:
    s = socket.socket()
    s.settimeout(2.0)
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    finally:
        s.close()


def _get(url: str, timeout: int = 10):
    # `X-MEMS-No-Incident`：如实声明"这是例行复检，不是人的操作"。
    # 否则每跑一次复检，它那条例行**拒答**用例就会被失败通道收进生产台账
    # （实测：一次两轮复检就往 work/logs/incidents.jsonl 里塞了 2 条）。
    req = urllib.request.Request(url, headers={"X-MEMS-No-Incident": "1"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read(), dict(r.headers)


def _post(url: str, body: dict, timeout: int = 120):
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json",
                                          "X-MEMS-No-Incident": "1"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def one_round(port: int) -> list[tuple[str, bool, str]]:
    base = "http://127.0.0.1:%d" % port
    out: list[tuple[str, bool, str]] = []
    ok = _probe(port)
    out.append(("端口 %d 在监听" % port, ok, "" if ok else "连不上（服务没在跑）"))
    if not ok:
        return out
    try:
        st, body, hdr = _get(base + "/")
        same = (PAGE.is_file() and hashlib.sha256(body).hexdigest()
                == hashlib.sha256(PAGE.read_bytes()).hexdigest())
        out.append(("首页 200 且与磁盘页面逐字节一致", st == 200 and same,
                    "HTTP %s / %d B / 一致=%s" % (st, len(body), same)))
        cc = hdr.get("Cache-Control") or ""
        out.append(("HTML 带 no-store（防旧页缓存）", "no-store" in cc, cc))
    except Exception as exc:
        out.append(("首页可读", False, "%s: %s" % (type(exc).__name__, exc)))
    try:
        st, m = _get_json(base + "/api/mode")
        out.append(("默认离线（network_allowed=false）",
                    m.get("mode") == "offline" and m.get("network_allowed") is False,
                    "mode=%s key_present=%s" % (m.get("mode"), m.get("key_present"))))
    except Exception as exc:
        out.append(("/api/mode 可读", False, "%s: %s" % (type(exc).__name__, exc)))
    try:
        st, p = _post(base + "/api/surrogate/predict",
                      {"x": 0.55, "N1": 1, "N2": 6, "alpha": 0.10})
        good = (p.get("accepted") and p.get("model_id") and "certified" in p
                and p.get("band_simultaneous_dB") is not None)
        out.append(("预测（接受例）带 model_id/certified/区间", bool(good),
                    "SPL20=%s ±%s 同时=%s" % (p.get("spl20_dB"),
                                             p.get("spl20_band_per_dim_dB"),
                                             p.get("band_simultaneous_dB"))))
    except Exception as exc:
        out.append(("预测（接受例）", False, "%s: %s" % (type(exc).__name__, exc)))
    try:
        st, r = _post(base + "/api/surrogate/predict",
                      {"x": 0.20, "N1": 1, "N2": 8, "alpha": 0.10})
        clean = r.get("refused") is True and not any(
            k in r for k in ("spl_dB", "spl20_dB", "p20_Pa", "band_simultaneous_dB"))
        out.append(("拒答例 refused=true 且不含任何数字", clean,
                    str(r.get("reason"))[:60]))
    except Exception as exc:
        out.append(("拒答例", False, "%s: %s" % (type(exc).__name__, exc)))
    return out


def _get_json(url: str):
    st, body, _h = _get(url)
    return st, json.loads(body.decode("utf-8"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="证明网页控制台真的活着（含 settle 后复检）")
    ap.add_argument("--port", type=int, default=8877)
    ap.add_argument("--settle", type=int, default=180,
                    help="第一次检查后等多少秒再复检（默认 180；0 = 只查一次）")
    args = ap.parse_args(argv)

    print("== 第 1 轮（t=0）==")
    r1 = one_round(args.port)
    for name, ok, detail in r1:
        print("  [%s] %s%s" % ("OK  " if ok else "FAIL", name,
                               ("　" + detail) if detail else ""))
    ok1 = all(o for _, o, _ in r1)
    if args.settle <= 0:
        print("判定：%s" % ("**通过**" if ok1 else "**不通过**"))
        return 0 if ok1 else 1

    print("\n等待 %d 秒后复检（关键：'启动成功' ≠ '持续可用'）…" % args.settle)
    time.sleep(args.settle)
    print("== 第 2 轮（t=%ds）==" % args.settle)
    r2 = one_round(args.port)
    for name, ok, detail in r2:
        print("  [%s] %s%s" % ("OK  " if ok else "FAIL", name,
                               ("　" + detail) if detail else ""))
    ok2 = all(o for _, o, _ in r2)
    both = ok1 and ok2
    print("判定：%s" % ("**通过**（两轮都活着且健康）" if both
                       else "**不通过**（第1轮 %s / 第2轮 %s）" % (ok1, ok2)))
    if not both:
        # ⚠️ 括号不能省：`REPO / "work/logs/webapp-%d.log" % port` 会被解析成
        # `(REPO / "...") % port` ⇒ `WindowsPath % int` → TypeError。
        # 后果很坏：**恰好在"验证失败、最需要看原因"的那条路径上崩掉**，
        # 把真实失败原因盖成一个无关的 TypeError（2026-09-29 实测踩到）。
        log = REPO / ("work/logs/webapp-%d.log" % args.port)
        if log.is_file():
            print("--- 日志尾部 ---")
            for ln in log.read_text(encoding="utf-8", errors="replace").splitlines()[-10:]:
                print("  " + ln)
    return 0 if both else 1


if __name__ == "__main__":
    sys.exit(main())
