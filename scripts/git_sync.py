# -*- coding: utf-8 -*-
"""完成任务后把仓库同步到 GitHub —— 一条命令，且**提交后强制校验**。

为什么需要它（都是本项目实测过的坑）：
  * 本机 Shell 是 Windows PowerShell 5.1，**命令行里的中文会经控制台代码页损毁**
    ⇒ 本脚本把提交信息写成 UTF-8 文件，再用 `git commit -F`，不把中文放进 argv。
  * `git` 不在 PATH（装在 `C:\\Program Files\\Git\\cmd\\git.exe`）⇒ 自动探测。
  * 只看 `push` 的退出码不够：本脚本 `git fetch` 后比对 `HEAD` 与 `origin/<branch>`，
    并检查工作区干净，**两者任一不满足即判定失败**（AGENTS.md 第 8 节）。
  * 包面向匿名评审，**凭据/模型/字节码绝不能入库** ⇒ 提交前扫描暂存区，命中即拒绝提交。

用法
    python -X utf8 scripts/git_sync.py -m "简短标题"
    python -X utf8 scripts/git_sync.py -m "简短标题" -b work/logs/COMMIT_MSG_x.txt
    python -X utf8 scripts/git_sync.py --check-only     # 只校验远端一致性，不提交

退出码：0 = 已同步（或无需提交且已同步）；1 = 校验失败；2 = 被拒绝（危险文件/远端不符）。
"""
from __future__ import annotations

import argparse
import pathlib
import re
import shutil
import subprocess
import sys
import time

REPO = pathlib.Path(__file__).resolve().parents[1]
EXPECTED_REMOTE = "git@github.com:zmx20040302-afk/ai-.git"
# 绝不允许入库的东西（.gitignore 已挡；此处是**兜底**，防止有人 force-add）
FORBIDDEN = [
    (re.compile(r"(^|/)session\.jsonl$"), "会话流水"),
    (re.compile(r"\.mph$"), "COMSOL 生产模型"),
    (re.compile(r"(^|/)__pycache__/"), "字节码缓存（内嵌绝对路径与用户名）"),
    (re.compile(r"\.pyc$"), "字节码缓存"),
    (re.compile(r"(^|/)id_(rsa|ed25519|ecdsa)"), "SSH 私钥"),
    (re.compile(r"\.pem$"), "私钥/证书"),
    (re.compile(r"(^|/)memsharness-history\.bundle$"), "旧历史 bundle"),
]


def git(*args: str, check: bool = False) -> subprocess.CompletedProcess:
    exe = shutil.which("git") or r"C:\Program Files\Git\cmd\git.exe"
    return subprocess.run([exe, *args], cwd=str(REPO), capture_output=True,
                          text=True, encoding="utf-8", errors="replace", check=check)


def out(p: subprocess.CompletedProcess) -> str:
    return (p.stdout or "").strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-m", "--message", help="提交标题（必填，除非 --check-only）")
    ap.add_argument("-b", "--body", help="正文文件（UTF-8；可选）")
    ap.add_argument("--check-only", action="store_true", help="只校验，不提交")
    a = ap.parse_args()

    branch = out(git("rev-parse", "--abbrev-ref", "HEAD")) or "master"
    remote_url = out(git("remote", "get-url", "origin"))
    print("仓库   : %s" % REPO)
    print("分支   : %s" % branch)
    print("远端   : %s" % (remote_url or "（未配置 origin！）"))
    if not remote_url:
        print("[FAIL] 没有配置 origin，拒绝继续")
        return 2
    if remote_url != EXPECTED_REMOTE:
        print("[FAIL] origin 与预期不符（预期 %s）——拒绝推送，避免误传到别处" % EXPECTED_REMOTE)
        return 2

    if not a.check_only:
        if not a.message:
            print("[FAIL] 需要 -m 提交标题（或 --check-only）")
            return 2
        git("add", "-A")
        staged = [l for l in out(git("diff", "--cached", "--name-only")).split("\n") if l]
        hits = [(f, why) for f in staged for rx, why in FORBIDDEN if rx.search(f)]
        if hits:
            print("[FAIL] 暂存区含禁止入库的文件，已中止：")
            for f, why in hits:
                print("        %s  （%s）" % (f, why))
            return 2
        if not staged:
            print("\n工作区没有改动 ⇒ 无需提交（不造假提交）；仍会推送已有未同步提交")
        else:
            print("\n待提交 %d 件：" % len(staged))
            for f in staged[:12]:
                print("        %s" % f)
            if len(staged) > 12:
                print("        … 共 %d 件" % len(staged))
            msg = a.message
            if a.body:
                bp = pathlib.Path(a.body)
                if not bp.is_file():
                    print("[FAIL] 找不到正文文件 %s" % bp)
                    return 2
                msg = msg + "\n\n" + bp.read_text(encoding="utf-8").rstrip() + "\n"
            tmp = REPO / "work/logs" / ("git_sync_msg_%s.txt" % time.strftime("%Y%m%dT%H%M%S"))
            tmp.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_bytes(msg.encode("utf-8"))
            c = git("-c", "i18n.commitEncoding=UTF-8", "commit", "-F", str(tmp))
            print("\n" + out(c))
            if c.returncode != 0:
                print("[FAIL] 提交失败：%s" % (c.stderr or "").strip()[:400])
                return 1
        # 即使本轮没有新文件，也可能存在上一次因网络/SSH 失败而留下的未推送提交。
        # 因此非 check-only 模式始终尝试 push；空推送由 git 自身安全地报告 up-to-date。
        p = git("push", "origin", branch)
        print((p.stdout or "").strip() or (p.stderr or "").strip())
        if p.returncode != 0:
            print("[FAIL] 推送失败（退出码 %d）" % p.returncode)
            return 1

    # ---- 强制校验：远端一致 + 工作区干净 ----
    git("fetch", "origin")
    head = out(git("rev-parse", "HEAD"))
    rem = out(git("rev-parse", "origin/%s" % branch))
    dirty = out(git("status", "--porcelain"))
    print("\n本地 HEAD      : %s" % head)
    print("origin/%s : %s" % (branch, rem))
    print("工作区         : %s" % ("干净" if not dirty else "有 %d 项未提交" % len(dirty.split("\n"))))
    ok = (head == rem) and not dirty
    print("判定：", "已同步" if ok else "未同步")
    if not ok:
        if head != rem:
            print("  ✗ 本地与远端不一致——推送可能未生效")
        if dirty:
            print("  ✗ 工作区仍有改动（可能被 .gitignore 之外的原因遗漏）")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
