# -*- coding: utf-8 -*-
"""**索引单写者**：给 `docs/INDEX-records-and-rulings.md` 的追加加互斥。

## 事故背景（实测，`INDEX §104`）

两条线**同时**往索引追加，发生一次**节号竞争**（各自的追加前读到的 `## <n>.` 最大节号相同
⇒ 都想占同一个号）。追加器 `scripts\\append_record_section.py` 只保证「同标题前缀已存在即拒收」
「追加后字符数只增不减」「回读校验」，但它**读 max → 写**这一段不是原子的 —— 竞争窗口就在那里。

## 做法（**不改追加器本身的判定逻辑**）

* 本轮**没有**改 `append_record_section.py` 一个字节（它刚在 §110 被修过且有用例），
  而是新增包装脚本 `scripts\\append_record_locked.py`：
  **先拿独占锁 → 在锁内读 max → 调原追加器的 `main()` → 释放锁**。
* 锁 = 一个**独占创建**的锁文件（`os.open(..., O_CREAT | O_EXCL)`）。拿不到锁
  ⇒ **拒绝写入并提示重试**（`IndexLockBusy`），**不抢锁、不自动破锁**
  （唯一的例外是显式 `break_stale=True`，且只有锁确实超龄时才允许，并把「破了谁的锁」记进结果）。
* 写完后**复核**「新文本以旧文本开头」（append-only）与「字符数只增」：即使有人**不走锁**
  直接追加，异常改写也会在这里被报出来（如实声明：锁是**协作机制**，
  对不拿锁的写入者没有强制力；这一点在报告里写清，不假装锁能挡住所有并发写）。
"""
from __future__ import annotations

import contextlib
import datetime as _dt
import hashlib
import importlib.util
import io
import json
import os
import pathlib
import re
import socket
import sys
import time
from typing import Callable

from .paths import repo_root

__all__ = [
    "IndexLockBusy", "IndexLock", "index_text_sha256", "max_section_number",
    "next_heading", "declared_section_number", "default_lock_path", "locked_append",
    "appender_path",
]

_HEADING_RE = re.compile(r"(?m)^##\s+(\d+)\.")
_SECTION_NUM_RE = re.compile(r"^\s*##\s+(\d+)\.")


class IndexLockBusy(RuntimeError):
    """拿不到锁 ⇒ **拒绝写入**（调用方应提示稍后重试）。"""

    def __init__(self, message: str, holder: dict | None = None) -> None:
        super().__init__(message)
        self.holder = holder


# --------------------------------------------------------------------------- 索引文本工具
def index_text_sha256(text: str) -> str:
    """文本的 sha256。

    ⚠️ 口径说明（实测）：本仓库索引是 **CRLF** 行尾，而 `Path.read_text()` 会把 `\\r\\n`
    归一化成 `\\n` ⇒ 同一个文件「文件字节的 sha256」与「归一化文本的 sha256」**不同**
    （实测 641,524 B 的文件：字节 sha `509b030a…`，归一化文本 sha 与之不等）。
    本函数只用于**同一进程内**的前后比对（读写都用归一化文本），**不得**当作「文件哈希」引用。
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def max_section_number(text: str) -> int:
    """索引里 `## <n>.` 形式的**最大节号**（没有则 0）。"""
    return max((int(m.group(1)) for m in _HEADING_RE.finditer(text)), default=0)


def next_heading(text: str, step: int = 1) -> str:
    """下一个可用标题（形如 `## 113.`）：现有最大节号 + step。

    ⚠️ **必须在锁内调用**：锁外读到 max 之后、写之前可能已被别人占号
    （§104 的竞争窗口）。
    """
    return "## %d." % (max_section_number(text) + int(step))


def declared_section_number(section_text: str) -> int | None:
    """片段**首行**自称的节号（`## 113. 标题` → 113）；没有 ⇒ None。"""
    for line in section_text.splitlines():
        if not line.strip():
            continue
        m = _SECTION_NUM_RE.match(line)
        return int(m.group(1)) if m else None
    return None


def appender_path() -> pathlib.Path:
    return repo_root() / "scripts" / "append_record_section.py"


def default_lock_path(repo: str | os.PathLike | None = None,
                      index_name: str = "INDEX-records-and-rulings.md") -> pathlib.Path:
    """锁文件缺省落在 `work/locks/`（运行区，不进版本库，也不靠近被写的文档）。"""
    base = pathlib.Path(repo) if repo is not None else repo_root()
    return base / "work" / "locks" / ("%s.lock" % index_name)


# --------------------------------------------------------------------------- 锁本身
class IndexLock:
    """独占锁文件。`acquire()` 失败即抛 `IndexLockBusy`（fail-closed）。

    * `timeout_s=0`（默认）⇒ **只试一次**，拿不到就拒 —— 「拒绝写入并提示重试」；
    * `timeout_s>0` ⇒ 在时限内轮询（0.05 s 起，逐步放宽到 0.25 s）；
    * `break_stale=True` 且锁**确实超龄**（> `stale_after_s`）⇒ 破锁一次并留痕；
      否则**绝不**动别人的锁。
    """

    def __init__(self, path: str | os.PathLike | None = None, *,
                 stale_after_s: float = 900.0, break_stale: bool = False,
                 timeout_s: float = 0.0, purpose: str = "append_record_section") -> None:
        self.path = pathlib.Path(path) if path is not None else default_lock_path()
        self.stale_after_s = float(stale_after_s)
        self.break_stale = bool(break_stale)
        self.timeout_s = float(timeout_s)
        self.purpose = purpose
        self._acquired = False
        self.broke_stale: dict | None = None

    # ---------------------------------------------------------------- 读锁状态
    def holder(self) -> dict | None:
        """锁文件的持有者信息（读不出 JSON 也返回原文，**不静默**）。"""
        try:
            raw = self.path.read_text(encoding="utf-8")
        except OSError:
            return None
        try:
            info = json.loads(raw)
            if isinstance(info, dict):
                info.setdefault("raw", raw.strip()[:200])
                return info
        except ValueError:
            pass
        return {"raw": raw.strip()[:200], "unparsable": True}

    def age_s(self) -> float | None:
        """锁文件的存在时长（秒）；不存在 ⇒ None。"""
        try:
            return time.time() - self.path.stat().st_mtime
        except OSError:
            return None

    def is_stale(self) -> bool:
        age = self.age_s()
        return age is not None and age > self.stale_after_s

    def describe_holder(self) -> str:
        h = self.holder() or {}
        bits = []
        for k, label in (("pid", "pid"), ("started_at", "起于"), ("host", "主机"),
                         ("purpose", "用途"), ("script", "发起脚本")):
            if h.get(k):
                bits.append("%s=%s" % (label, h[k]))
        if not bits and h.get("raw"):
            bits.append("锁内容=%r" % h["raw"])
        age = self.age_s()
        if age is not None:
            bits.append("已持锁 %.0f s" % age)
        return "，".join(bits) or "（锁文件无内容）"

    # ---------------------------------------------------------------- 取/放
    def _payload(self) -> str:
        return json.dumps({
            "pid": os.getpid(),
            "started_at": _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat(),
            "host": socket.gethostname(),
            "script": pathlib.Path(sys.argv[0]).name if sys.argv and sys.argv[0] else "?",
            "purpose": self.purpose,
        }, ensure_ascii=False)

    def _try_create(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            return False
        try:
            os.write(fd, self._payload().encode("utf-8"))
        finally:
            os.close(fd)
        self._acquired = True
        return True

    def acquire(self) -> "IndexLock":
        """取锁；拿不到 ⇒ `IndexLockBusy`（消息里带持锁者信息与「请稍后重试」）。"""
        deadline = time.monotonic() + max(0.0, self.timeout_s)
        delay = 0.05
        while True:
            if self._try_create():
                return self
            if self.break_stale and self.is_stale():
                victim = self.holder()
                age = self.age_s()
                try:
                    self.path.unlink()
                except OSError as exc:
                    raise IndexLockBusy(
                        "锁已超龄但**删不掉**（%s: %s）⇒ 拒绝写入" % (type(exc).__name__, exc),
                        holder=victim) from exc
                self.broke_stale = {"holder": victim, "age_s": age}
                if self._try_create():
                    return self
            if time.monotonic() >= deadline:
                raise IndexLockBusy(
                    "索引正在被另一执行者追加，**拿不到锁 ⇒ 拒绝写入，请稍后重试**"
                    "（本包装脚本不抢锁、不自动破锁）。锁文件：%s；持锁者：%s"
                    % (self.path, self.describe_holder()),
                    holder=self.holder())
            time.sleep(delay)
            delay = min(0.25, delay * 1.5)

    def try_acquire(self) -> tuple[bool, str]:
        """不抛版本：`(是否拿到, 说明)`。"""
        try:
            self.acquire()
            return True, "拿到锁：%s" % self.path
        except IndexLockBusy as exc:
            return False, str(exc)

    def release(self) -> bool:
        """放锁（只放自己拿到的锁；没拿到就什么都不做）。返回是否删除了锁文件。"""
        if not self._acquired:
            return False
        self._acquired = False
        try:
            self.path.unlink()
            return True
        except FileNotFoundError:
            return False
        except OSError:
            return False

    def __enter__(self) -> "IndexLock":
        return self.acquire()

    def __exit__(self, *exc_info) -> None:
        self.release()


# --------------------------------------------------------------------------- 追加（锁内）
def _default_invoke(index_path: pathlib.Path, section_path: pathlib.Path,
                    heading: str, repo: pathlib.Path) -> dict:
    """调用**原追加器**（`scripts\\append_record_section.py`）的 `main()`，不改它一行逻辑。

    做法：从磁盘加载该脚本模块 → 把它的 `REPO` / `IDX` 指向本次目标
    （缺省就是仓库根与真索引，语义与直接跑脚本**完全一致**）→ 设 `sys.argv` → 调 `main()`。
    它的三道守卫（重复拒收 / 字符数只增 / 回读校验）原样生效。
    """
    p = appender_path()
    if not p.is_file():
        return {"rc": 2, "stdout": "", "error": "找不到追加器：%s" % p}
    spec = importlib.util.spec_from_file_location("_append_record_section_locked", p)
    if spec is None or spec.loader is None:
        return {"rc": 2, "stdout": "", "error": "无法加载追加器：%s" % p}
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.REPO = pathlib.Path(repo)
    mod.IDX = pathlib.Path(index_path)
    argv = ["append_record_section.py", "--section", str(section_path),
            "--heading", heading]
    saved = sys.argv
    buf = io.StringIO()
    try:
        sys.argv = argv
        with contextlib.redirect_stdout(buf):
            rc = int(mod.main())
    except SystemExit as exc:                      # main() 只在 __main__ 分支 sys.exit
        rc = int(exc.code or 0)
    finally:
        sys.argv = saved
    return {"rc": rc, "stdout": buf.getvalue()}


def locked_append(index_path: str | os.PathLike, section_path: str | os.PathLike, *,
                  heading: str | None = None, repo: str | os.PathLike | None = None,
                  lock_path: str | os.PathLike | None = None,
                  invoke: Callable[..., dict] | None = None,
                  timeout_s: float = 0.0, break_stale: bool = False,
                  max_retry: int = 3) -> dict:
    """**在锁内**读 max 节号并追加；拿不到锁 ⇒ `status="refused"`（**不写一个字节**）。

    返回（**不抛**，除 `invoke` 自身崩了以外的所有情况都结构化返回）：
    `{"ok", "status", "message", "heading", "chars_before", "chars_after",
      "sha256_before", "sha256_after", "appender_stdout", "appender_rc",
      "lock_path", "broke_stale", "n_retry"}`

    `chars_*` / `sha256_*` 都是**行尾归一化文本**的口径（与追加器自己打印的字符数一致，
    见 `index_text_sha256()` 的说明）；要「文件字节」口径请自己读 bytes 再算。

    `status`：`appended` / `skipped`（号已被占）/ `refused`（锁）/ `failed`（追加器或复核失败）。
    """
    idx = pathlib.Path(index_path)
    sec = pathlib.Path(section_path)
    if not idx.is_absolute():
        idx = (pathlib.Path(repo) if repo is not None else repo_root()) / idx
    if not sec.is_absolute():
        sec = (pathlib.Path(repo) if repo is not None else repo_root()) / sec
    repo_p = pathlib.Path(repo) if repo is not None else repo_root()
    runner = invoke or _default_invoke
    lock_p = pathlib.Path(lock_path) if lock_path is not None \
        else default_lock_path(repo_p, idx.name)

    out: dict = {"ok": False, "status": "failed", "heading": heading or "",
                 "index": str(idx), "section": str(sec), "lock_path": str(lock_p),
                 "n_retry": 0, "broke_stale": None, "appender_stdout": "",
                 "appender_rc": None, "chars_before": None, "chars_after": None,
                 "sha256_before": None, "sha256_after": None}

    lock = IndexLock(lock_p, timeout_s=timeout_s, break_stale=break_stale,
                     purpose="locked_append:%s" % idx.name)
    try:
        lock.acquire()
    except IndexLockBusy as exc:
        out.update(status="refused", ok=False,
                   message="%s（**索引未被改动**）" % exc)
        return out
    out["broke_stale"] = lock.broke_stale

    try:
        text_before = idx.read_text(encoding="utf-8")
        out["chars_before"] = len(text_before)
        out["sha256_before"] = index_text_sha256(text_before)
        try:
            sec_text = sec.read_text(encoding="utf-8")
        except OSError as exc:
            out.update(status="failed", message="读不出片段文件 %s（%s）" % (sec, exc))
            return out

        # ---- 节号必须在**锁内**确定，且必须与片段首行一致（否则宁可拒写）
        auto = heading is None
        if auto:
            declared = declared_section_number(sec_text)
            expected = max_section_number(text_before) + 1
            if declared is None:
                out.update(status="failed",
                           message="片段首行不是 `## <n>. 标题` ⇒ 无法自动定节号"
                                   "（锁内读到的下一个可用号是 ## %d.）" % expected)
                return out
            if declared != expected:
                out.update(status="failed",
                           message="**节号不合法**：片段自称 §%d，而锁内读到索引最大节号 = %d "
                                   "⇒ max+1 = §%d（防跳号/撞号，拒绝写入；请改片段标题或显式"
                                   "--heading）" % (declared, expected - 1, expected))
                return out
            head = "## %d." % declared
        else:
            head = heading
            first = next((ln for ln in sec_text.splitlines() if ln.strip()), "")
            if not first.lstrip().startswith(head.strip()):
                out.update(status="failed",
                           message="**片段与标题不对应**：片段首行 %r 不以标题 %r 开头 "
                                   "⇒ 拒绝写入（该形态在原追加器里会「先写盘、再回读失败」，"
                                   "退出码报错但字节已经落盘 ⇒ 这里**写前**拦住）"
                                   % (first.strip()[:60], head))
                return out
        out["heading"] = head
        for attempt in range(max(1, int(max_retry) if auto else 1)):
            out["n_retry"] = attempt
            res = runner(index_path=idx, section_path=sec, heading=head, repo=repo_p)
            out["appender_rc"] = res.get("rc")
            out["appender_stdout"] = res.get("stdout", "")
            if res.get("error"):
                out.update(status="failed", message="追加器没能跑起来：%s" % res["error"])
                return out
            text_after = idx.read_text(encoding="utf-8")
            out["chars_after"] = len(text_after)
            out["sha256_after"] = index_text_sha256(text_after)
            if out["appender_rc"] != 0:
                changed = text_after != text_before
                out["index_changed_on_failure"] = changed
                out.update(status="failed",
                           message="追加器 rc=%s；索引%s（输出见 appender_stdout）"
                                   % (out["appender_rc"],
                                      "**已被改动**（字符 %d -> %d）⇒ 可能部分写入，需人工核对"
                                      % (len(text_before), len(text_after)) if changed
                                      else "未被改动"))
                return out
            # ---- 先判「追加器自己拒收/跳过了」：那时它**一个字节都没写**
            if "[SKIP]" in out["appender_stdout"]:
                if auto and attempt + 1 < max(1, int(max_retry)):
                    # 号被并发写入者占了 ⇒ 重读 max 再试（我们没写，所以文本没变）
                    out["n_retry"] = attempt + 1
                    text_before = text_after
                    continue
                out.update(status="skipped",
                           message="标题 %r 已被占用（并发追加？）⇒ 未写入：%s"
                                   % (head, out["appender_stdout"].strip()[:200]))
                return out
            # ---- 复核 ①：append-only（新文本必须以旧文本开头，既有字节不得被改写）
            if not text_after.startswith(text_before):
                out.update(status="failed",
                           message="**复核失败**：追加后索引不再以原文本开头 ⇒ 既有字节被改写"
                                   "（很可能有**不走锁**的写入者并发写了同一个文件）")
                return out
            # ---- 复核 ②：字符数只增
            if len(text_after) <= len(text_before):
                out.update(status="skipped",
                           message="追加器报告未追加（字符数未增）：%s"
                                   % out["appender_stdout"].strip()[:200])
                return out
            # ---- 复核 ③：本节标题真的在
            if not re.search(r"(?m)^%s(\s|$)" % re.escape(head), text_after):
                out.update(status="failed",
                           message="**复核失败**：追加后找不到标题行 %r" % head)
                return out
            out.update(status="appended", ok=True,
                       message="已追加 %s ｜ 字符 %d -> %d ｜ 锁 %s"
                               % (head, out["chars_before"], out["chars_after"], lock_p))
            return out
        return out
    except (OSError, UnicodeDecodeError) as exc:
        out.update(status="failed", message="读写索引失败：%s: %s" % (type(exc).__name__, exc))
        return out
    finally:
        lock.release()
