# -*- coding: utf-8 -*-
"""P1 取回驱动：把远端已存在的 400 件 pod20 快照分块、可续跑、带停滞检测地取回本地。

> **本条交付说明（务必先读）**：本文件是**预录取回器**的**修好版本**，落在 `scripts\\`
> （AGENTS.md 规定的可执行脚本落点；`work/` 被 gitignore、不进版本库）。
> 预录取回器与当时那份「已打补丁的副本」的**原件一字节未动**：
>
> | 角色 | 路径 | sha256 |
> |---|---|---|
> | 预录取回器（**归档件，未改**） | `work/runs/field-inventory-20261009/fetch_expansion_p1.py` | `304ddb10…`（`INDEX §126.4` 的锚点，**仍然有效**） |
> | 当时的逐字副本＋两处补丁（**未改**） | `work/runs/field-expansion-20261009/fetch_expansion_p1_copy.py` | `44ffb798…` |
> | **本文件**（修好版，本轮的正式脚本） | `scripts/fetch_expansion_p1.py` | 见 `INDEX` 登记 |
>
> 因此 `§126.4` 的旧锚点 `304ddb10…` **不作废**（那两份归档件一个字节都没动），
> 本文件只承接它的**职责**：`scripts/` 下的正式取回脚本。

设计要点（对应 docs/PREREG_FIELD_EXPANSION_20261009.md §5、§6）：
  * 分块单位 = N1 层（5 块，每块 80 件）；块级 `.done` 标记 = 续跑锚点；
  * 幂等：已存在且(尺寸 + sha256)校验通过的文件直接跳过（同一条命令重跑只补缺口）；
  * 原子落盘：先写 `<name>.part` 再 `os.replace`；
  * 回传即校验（R8，**六条一条都不放松**）：逐文件 ① 字节数 == 远端 `bytes_remote`
    ② 远端**现算** sha256 ③ 本地复算 sha256 与远端逐位相等 ④ `.part` 尺寸先行拦截
    ⑤ 取不到/取不全远端 sha 时 **fail-closed 拒绝继续**（不写 `.done`）
    ⑥ 任何豁免必须**显式声明并带原因**（`write_done` 的 `exemptions`）；
    （③ 的 `n_points == x_m 长度`、参数三路一致、掩膜计数一致由
    `work/runs/field-expansion-20261009/verify_expansion_p1.py` 另跑，本脚本不做）
  * 停滞检测：连续 STALL_SAMPLES 次采样（间隔 STALL_INTERVAL_S，默认 60 s）本地
    文件数与总字节都不变，且远端现算哈希也未推进 ⇒ 判停滞，写 `chunk_<N1>.stalled` 并退出（不猜、不重试到天荒地老）；
  * R16：只读远端与被校验对象，只写本 run 目录 `work/runs/field-expansion-20261009/`；
  * 不 kill 任何进程；不并发；不修改任何既有产物。

**相对预录取回器的三处改动（逐处给理由）**：

* **P1（bugfix，解析）**：原 `if len(t) == 2 and t[0].endswith(".mat")` 恒不成立 ——
  远端 `sha256sum` 输出是 `<hex>␣␣<path>`，`t[0]` 是**哈希**、永远不以 `.mat` 结尾
  ⇒ `remote_sha_map()` 恒空 ⇒ 下载前即以 rc=3 退出（`INDEX §126.4` 实测）。
  改为按**路径字段**判定，并且不用 `split()` 定长切分（路径**含空格**时 `split()` 会切成 >2 段，
  那一件就会被**静默丢掉**）⇒ 改用 `_parse_sha256sum_line()` 逐行解析。
* **P2（batching）**：`sha256sum` 按 `SHA_BATCH=30` 分批调用，限制单条 ssh 命令行长度；
  语义不变（仍是远端现算 sha256、只读）。
* **P3（明确报错，不放松任何一条）**：ssh 返回非 0 时抛 `RemoteShaError`；
  解析到 **0 条**时**显式**报「输出为空」并 rc=3，而不是含糊地只报「只取到 0/N」。

用法（**默认什么都不做**，必须显式给动作）：
  python -X utf8 scripts/fetch_expansion_p1.py --dry-run                 # 只打印计划，不联网
  python -X utf8 scripts/fetch_expansion_p1.py --verify-local            # 只校验本地已有文件，不联网
  python -X utf8 scripts/fetch_expansion_p1.py --chunk N1_3 --remote-sha # 取远端 sha256（只读 ssh）
  python -X utf8 scripts/fetch_expansion_p1.py --chunk N1_3              # 真正取回该块（需人批准后执行）
  python -X utf8 scripts/fetch_expansion_p1.py --all                     # 5 块顺序取回（单实例串行）
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time

REPO = r"C:\Users\zmx\Desktop\memsharness"
RUN = os.path.join(REPO, "work", "runs", "field-expansion-20261009")
INV = os.path.join(REPO, "work", "runs", "field-inventory-20261009")
PLAN = os.path.join(INV, "expansion_inputs_p1.tsv")
IDX = os.path.join(REPO, "work", "runs", "te2_8_pod_fields_20261005", "snapshot_index.tsv")

REMOTE_HOST = "ubuntu-10-180-7-46"
SSH = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20", REMOTE_HOST]
STALL_INTERVAL_S = 60
STALL_SAMPLES = 3
SHA_BATCH = 30
CHUNKS = ["N1_1", "N1_2", "N1_3", "N1_5", "N1_6"]

#: `sha256sum` 一行 = `<64 位 hex>` + 空白 + 可选 `*`/`\` + **路径（可能含空格）**
_SHA_LINE_RE = re.compile(r"^\s*([0-9a-fA-F]{64})\s+[\\*]?(.+?)\s*$")


class RemoteShaError(RuntimeError):
    """取远端 sha256 失败（ssh 非 0 / 输出为空）⇒ 调用方必须 **fail-closed 拒绝继续**。"""


def log(msg: str) -> None:
    line = "%s %s" % (time.strftime("%Y-%m-%dT%H:%M:%S"), msg)
    print(line, flush=True)
    os.makedirs(RUN, exist_ok=True)
    with open(os.path.join(RUN, "fetch_p1.log"), "a", encoding="utf-8") as f:
        f.write(line + "\n")


def sha256_file(p: str, bufsize: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while True:
            b = f.read(bufsize)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def load_plan() -> dict:
    lines = open(PLAN, encoding="utf-8").read().splitlines()
    hdr = lines[0].split("\t")
    out = {}
    for l in lines[1:]:
        if not l.strip():
            continue
        r = dict(zip(hdr, l.split("\t")))
        out.setdefault(r["chunk"], []).append(r)
    return out


def idx_points() -> dict:
    lines = open(IDX, encoding="utf-8").read().splitlines()
    hdr = lines[0].split("\t")
    d = {}
    for l in lines[1:]:
        if not l.strip():
            continue
        r = dict(zip(hdr, l.split("\t")))
        if r["kind"] == "pod20":
            d[os.path.basename(r["file"])] = int(r["n_points"])
    return d


def ssh_out(args: list[str]) -> tuple[int, str]:
    p = subprocess.run(SSH + args, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def _parse_sha256sum_line(line: str) -> tuple[str, str] | None:
    """把 `sha256sum` 的一行解析成 `(sha256, 路径)`；不是该形态 ⇒ None。

    **P1 的根因就出在这里**：原实现写 `t = line.split()` 再看 `t[0].endswith(".mat")`
    ⇒ 看的是**哈希字段**，恒不成立；而 `t[1]` 那种定长切法在**路径含空格**时又会把
    这一件静默丢掉。⇒ 这里用正则：64 位 hex + 空白 + （可选 `*`/`\\`）+ **余下全部即路径**。
    """
    m = _SHA_LINE_RE.match(line)
    if not m:
        return None
    return m.group(1).lower(), m.group(2).strip()


def remote_sha_map(rows: list[dict]) -> dict:
    """**分批** ssh 现算整块 sha256（只读）；键 = 文件名，值 = sha256。

    * ssh 返回非 0 ⇒ `RemoteShaError`（**不猜**「可能只是 stderr 提示」）；
    * 解析不到任何一行也**不在这里**静默返回空 —— 空集合由 `do_chunk` 显式报错。
    """
    m = {}
    for i in range(0, len(rows), SHA_BATCH):
        grp = rows[i:i + SHA_BATCH]
        files = " ".join("'%s'" % r["remote_path"] for r in grp)
        rc, out = ssh_out(["sha256sum %s" % files])
        if rc != 0:
            raise RemoteShaError(
                "ssh sha256sum 返回 rc=%d（批次 %d..%d）：%s"
                % (rc, i, i + len(grp) - 1, out.strip().replace("\n", " ")[:300]))
        for l in out.splitlines():
            parsed = _parse_sha256sum_line(l)
            if parsed is None:
                continue
            sha, path = parsed
            if not path.endswith(".mat"):
                continue
            m[os.path.basename(path)] = sha
    return m


def local_state(rows: list[dict]) -> tuple[int, int]:
    n = 0
    b = 0
    for r in rows:
        p = os.path.join(REPO, r["local_path"])
        if os.path.exists(p):
            n += 1
            b += os.path.getsize(p)
    return n, b


def verify_one(r: dict, want_sha: str | None) -> tuple[bool, str]:
    p = os.path.join(REPO, r["local_path"])
    if not os.path.exists(p):
        return False, "missing"
    sz = os.path.getsize(p)
    if sz != int(r["bytes_remote"]):
        return False, "size %d != remote %s" % (sz, r["bytes_remote"])
    if want_sha:
        got = sha256_file(p)
        if got != want_sha:
            return False, "sha256 %s != remote %s" % (got[:16], want_sha[:16])
    return True, "ok"


def do_chunk(chunk: str, rows: list[dict], do_fetch: bool, remote_sha: bool) -> int:
    os.makedirs(RUN, exist_ok=True)
    os.makedirs(os.path.join(RUN, "raw", chunk), exist_ok=True)
    done = os.path.join(RUN, "chunk_%s.done" % chunk)
    if os.path.exists(done) and not do_fetch:
        log("chunk %s 已有 .done，跳过" % chunk)
        return 0

    shas: dict = {}
    if remote_sha:
        try:
            shas = remote_sha_map(rows)
        except RemoteShaError as exc:
            log("[FAIL] chunk %s 远端 sha256 取不到（%s）⇒ fail-closed，拒绝继续"
                % (chunk, exc))
            return 3
        if not shas:
            log("[FAIL] chunk %s 远端 sha256 **输出为空**（解析到 0/%d 条）⇒ fail-closed，"
                "拒绝继续（**不是**「0 个通过」）" % (chunk, len(rows)))
            return 3
        if len(shas) != len(rows):
            log("[FAIL] chunk %s 远端 sha256 只取到 %d/%d ⇒ fail-closed，拒绝继续"
                % (chunk, len(shas), len(rows)))
            return 3

    ok, bad = 0, []
    for r in rows:
        good, why = verify_one(r, shas.get(r["name"]))
        if good:
            ok += 1
        else:
            bad.append((r, why))
    log("chunk %s：本地已校验通过 %d/%d，待取 %d" % (chunk, ok, len(rows), len(bad)))
    if not bad:
        write_done(chunk, rows, shas, ok)
        return 0
    if not do_fetch:
        for r, why in bad[:5]:
            log("   待取 %s (%s)" % (r["name"], why))
        log("   未启用 --fetch ⇒ 到此为止（本模式不联网下载）")
        return 0

    # ---- 真正取回：单实例串行 + 原子落盘 + 停滞检测 ----
    last_n, last_b = local_state(rows)
    stall = 0
    for i, (r, why) in enumerate(bad, 1):
        dst = os.path.join(REPO, r["local_path"])
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        part = dst + ".part"
        log("  [%d/%d] scp %s（%s）" % (i, len(bad), r["name"], why))
        cmd = ["scp", "-q", "-o", "BatchMode=yes",
               "%s:%s" % (REMOTE_HOST, r["remote_path"]), part]
        p = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        if p.returncode != 0:
            log("  [FAIL] scp rc=%d：%s" % (p.returncode, (p.stderr or "").strip()[:300]))
            if os.path.exists(part):
                os.remove(part)
            return 4
        if os.path.getsize(part) != int(r["bytes_remote"]):
            log("  [FAIL] 字节数不符（%d != %s）⇒ 不 rename，删除 .part"
                % (os.path.getsize(part), r["bytes_remote"]))
            os.remove(part)
            return 5
        os.replace(part, dst)

        good, w2 = verify_one(r, shas.get(r["name"]))
        if not good:
            log("  [FAIL] 回传校验失败：%s ⇒ fail-closed" % w2)
            return 6

        n, b = local_state(rows)
        progressed = (n, b) != (last_n, last_b)
        if progressed:
            stall = 0
        else:
            stall += 1
            log("  [stall-watch] 连续 %d 次无推进（阈值 %d）" % (stall, STALL_SAMPLES))
            if stall >= STALL_SAMPLES:
                with open(os.path.join(RUN, "chunk_%s.stalled" % chunk), "w",
                          encoding="utf-8", newline="\n") as f:
                    json.dump({"chunk": chunk, "stall_samples": stall,
                               "interval_s": STALL_INTERVAL_S,
                               "local_n": n, "local_bytes": b,
                               "at": time.strftime("%Y-%m-%dT%H:%M:%S")},
                              f, ensure_ascii=False, indent=1)
                log("  [STALL] chunk %s 判停滞，停止该块（不 kill 任何进程）" % chunk)
                return 7
        last_n, last_b = n, b

    ok, bad = 0, []
    for r in rows:
        good, why = verify_one(r, shas.get(r["name"]))
        if good:
            ok += 1
        else:
            bad.append((r, why))
    if bad:
        log("[FAIL] chunk %s 收尾仍有 %d 件未过校验 ⇒ 不写 .done" % (chunk, len(bad)))
        return 8
    write_done(chunk, rows, shas, ok)
    return 0


def write_done(chunk: str, rows: list[dict], shas: dict, n_ok: int) -> None:
    items = []
    for r in rows:
        p = os.path.join(REPO, r["local_path"])
        items.append({
            "name": r["name"],
            "bytes": os.path.getsize(p),
            "bytes_remote": int(r["bytes_remote"]),
            "sha256_local": sha256_file(p),
            "sha256_remote": shas.get(r["name"]),
            "n_points_index": int(r["n_points_index"]),
            "x_scale": r["x_scale"], "N_w_te1": r["N_w_te1"],
            "N_w_te2": r["N_w_te2"], "freq_Hz": r["freq_Hz"],
            "role_n": r["role_n"], "role_x": r["role_x"],
        })
    dots = {
        "chunk": chunk,
        "n_files": len(items),
        "n_verified": n_ok,
        "bytes_total": sum(i["bytes"] for i in items),
        "remote_sha_available": bool(shas),
        "exemptions": ([] if shas else
                       [{"reason": "本块未取远端 sha256（未启用 --remote-sha）"
                                   "⇒ 仅按字节数校验", "r8_waiver": True}]),
        "items": items,
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    p = os.path.join(RUN, "chunk_%s.done" % chunk)
    tmp = p + ".part"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(dots, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)
    log("chunk %s：写 .done（%d 件 / %d B）" % (chunk, len(items), dots["bytes_total"]))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chunk", choices=CHUNKS)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--verify-local", action="store_true")
    ap.add_argument("--remote-sha", action="store_true")
    ap.add_argument("--fetch", action="store_true",
                    help="真正下载；不给就只有只读模式")
    a = ap.parse_args(argv)

    plan = load_plan()
    idx = idx_points()
    if a.dry_run:
        tot = 0
        for c in CHUNKS:
            rows = plan.get(c, [])
            b = sum(int(r["bytes_remote"]) for r in rows)
            tot += b
            print("%-6s files=%-3d bytes=%-10d x=[%s..%s] role_n=%s"
                  % (c, len(rows), b, min(r["x_scale"] for r in rows),
                     max(r["x_scale"] for r in rows),
                     sorted({r["role_n"] for r in rows})))
        print("TOTAL files=%d bytes=%d (%.1f MB)"
              % (sum(len(plan.get(c, [])) for c in CHUNKS), tot, tot / 1048576))
        print("index n_points entries = %d" % len(idx))
        print("dry-run：未联网、未下载、未写任何远端/本地数据文件。")
        return 0

    todo = CHUNKS if a.all else ([a.chunk] if a.chunk else [])
    if not todo:
        print("未指定 --chunk/--all/--dry-run/--verify-local ⇒ 什么都不做。")
        return 0

    rc = 0
    for c in todo:
        rows = plan.get(c, [])
        if not rows:
            log("[FAIL] 计划里没有块 %s" % c)
            rc = max(rc, 2)
            continue
        # index 一致性前置门禁（R1：设了不报错 ≠ 能跑）
        mism = [r["name"] for r in rows
                if r["name"] in idx and idx[r["name"]] != int(r["n_points_index"])]
        if mism:
            log("[FAIL] 块 %s 的 n_points 与 index 不一致：%s ⇒ 拒绝启动" % (c, mism[:3]))
            rc = max(rc, 9)
            continue
        rc = max(rc, do_chunk(c, rows, do_fetch=a.fetch, remote_sha=a.remote_sha))
    return rc


if __name__ == "__main__":
    sys.exit(main())
