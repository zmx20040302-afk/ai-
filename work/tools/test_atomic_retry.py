"""证明 `atomic_write_json` 的重试**被真正触发过**（本地压测，不启动 COMSOL）。

要求（父 agent 裁定）：不能只证明"失败消失了"，必须证明**重试确实被触发并成功**。
做法：多写者 + 多读者同时压同一个目标文件，统计
  - 失败次数（要求 0）
  - `retries > 0` 的调用次数（要求 > 0，否则本轮不构成修复证据）
并保留触发时的现场。

用法：python work/tools/test_atomic_retry.py [--out <dir>] [--writers 4] [--readers 4] [--secs 6]
退出码：0 = 0 失败且 retries>0 出现过；3 = 未压到竞态（不构成证据）；1 = 仍有失败
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rt_gate import atomic_write_json  # noqa: E402

STATS = {"ok": 0, "fail": 0, "retried": 0, "max_retries": 0, "attempts_sum": 0}
LOCK = threading.Lock()
SAMPLES: list[dict] = []


def writer(target: Path, stop: threading.Event, wid: int) -> None:
    i = 0
    while not stop.is_set():
        i += 1
        r = atomic_write_json(target, {"writer": wid, "seq": i, "payload": "x" * 512})
        with LOCK:
            if r.get("ok"):
                STATS["ok"] += 1
                STATS["attempts_sum"] += int(r.get("attempts", 1))
                if int(r.get("retries", 0)) > 0:
                    STATS["retried"] += 1
                    STATS["max_retries"] = max(STATS["max_retries"], int(r["retries"]))
                    if len(SAMPLES) < 5:
                        SAMPLES.append({"attempts": r["attempts"], "retries": r["retries"]})
            else:
                STATS["fail"] += 1
                if len(SAMPLES) < 5:
                    SAMPLES.append({"ok": False, "error": r.get("error")})
        time.sleep(0.001)


def reader(target: Path, stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            target.read_bytes()
        except OSError:
            pass
        time.sleep(0.001)


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent.parent /
                                        "runs" / "test-atomic-retry"))
    ap.add_argument("--writers", type=int, default=4)
    ap.add_argument("--readers", type=int, default=4)
    ap.add_argument("--secs", type=float, default=6.0)
    args = ap.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    target = out / "contended.json"
    target.write_text("{}", encoding="utf-8")

    stop = threading.Event()
    ths = ([threading.Thread(target=writer, args=(target, stop, i), daemon=True)
            for i in range(args.writers)]
           + [threading.Thread(target=reader, args=(target, stop), daemon=True)
              for _ in range(args.readers)])
    for t in ths:
        t.start()
    time.sleep(args.secs)
    stop.set()
    for t in ths:
        t.join(timeout=3)

    doc = {"writers": args.writers, "readers": args.readers, "seconds": args.secs,
           "stats": STATS, "retry_samples": SAMPLES,
           "verdict": ("PASS_RETRY_TRIGGERED_AND_NO_FAILURE"
                       if STATS["fail"] == 0 and STATS["retried"] > 0
                       else ("NO_CONTENTION_OBSERVED_NOT_EVIDENCE" if STATS["fail"] == 0
                             else "FAIL_STILL_FAILING")),
           "note": "压测率不代表生产故障率；本测试只证明重试被触发过且失败为 0"}
    p = out / "atomic_retry_test.json"
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({**doc["stats"], "verdict": doc["verdict"],
                      "samples": SAMPLES[:3],
                      "json_bytes": p.stat().st_size,
                      "json_sha256": hashlib.sha256(p.read_bytes()).hexdigest()},
                     ensure_ascii=False), flush=True)
    if STATS["fail"]:
        return 1
    return 0 if STATS["retried"] > 0 else 3


if __name__ == "__main__":
    sys.exit(main())
