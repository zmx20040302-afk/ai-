# -*- coding: utf-8 -*-
"""从**冻结的 T7 预注册件**程序化生成 `tasks/t7_frozen_protocol.py`（只含复放所需的结构性数据）。

为什么不随包分发预注册件本身：它是**内部件**（含内部路径与模型名），且 48 条散文（958 汉字）
是给人读的，复放用不到。也不把这类内容手打进代码：本生成器直接读冻结件，逐字段取出，
再断言取出的内容能重建**同一条池哈希**（该哈希在源脚本里本就是硬校验）。
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
R = pathlib.Path(__file__).resolve().parents[2]
SRC = R / "work/runs/ai11-m4-20261013/tasks_dev/t7/tasks/PREREG_T7.json"
DST = R / "work/runs/ai11-m4-20261013/pkg_src/t7_frozen_protocol.py"


def pool_hash(pool) -> str:
    h = hashlib.sha256()
    for x, a, b in pool:
        h.update(("%.2f|%d|%d\n" % (x, a, b)).encode("ascii"))
    return h.hexdigest()


def main() -> int:
    d = json.loads(SRC.read_text(encoding="utf-8"))
    cp = d["candidate_pool"]
    xs = [round(float(v), 2) for v in cp["x_values"]]
    pairs = [[int(a), int(b)] for a, b in cp["n1n2_pairs"]]
    pool = [(x, a, b) for x in xs for (a, b) in pairs]
    ph = pool_hash(pool)
    if ph != cp["sha256"]:
        raise SystemExit("[FAIL] 重建的池哈希 %s != 冻结值 %s" % (ph, cp["sha256"]))
    if len(pool) != cp["size"]:
        raise SystemExit("[FAIL] 池规模 %d != %d" % (len(pool), cp["size"]))
    doe = [[round(float(a), 2), int(b), int(c)] for a, b, c in d["design"]["shared_doe"]]
    arms = {k: [int(s) for s in v["seeds"]] for k, v in d["design"]["arms"].items()}
    budget = {k: v for k, v in d["design"]["budget"].items() if not isinstance(v, str)}
    src_sha = hashlib.sha256(SRC.read_bytes()).hexdigest()

    body = f'''# -*- coding: utf-8 -*-
"""Structural content of the frozen closed-loop pre-registration, as data (no prose).

WHY THIS FILE, AND WHY IT IS SAFE TO TRUST
The pre-registration document itself is **not distributed** with this package: it is an internal
artifact that carries internal paths and a model filename, and its prose exists for human readers
rather than for replay. What the replay actually needs is structure: the candidate pool, the shared
DOE, the per-arm seed lists and the call budget. Those are reproduced here as data.

This file was **generated** from the frozen document by `emit_t7_frozen_protocol.py`, never typed by
hand. The generator asserts that rebuilding the pool from these values reproduces the pool sha256 that
`t7_scheduling.py` checks at run time, and that the pool size matches; if either failed it refused to
write this file. So the numbers here are not a transcription claim - they are checked against the
frozen pre-registration's own digest.

Frozen pre-registration identity:
    file   : PREREG_T7.json (not distributed)
    sha256 : {src_sha}
"""
from __future__ import annotations

SOURCE_SHA256 = "{src_sha}"
KIND = "{d['kind']}"
STATUS = "{d['status']}"

# 36 x-values x N pool pairs = {cp['size']} candidate designs
X_VALUES = {xs!r}
N1N2_PAIRS = {pairs!r}
POOL_SIZE = {int(cp['size'])}
POOL_SHA256 = "{cp['sha256']}"

SHARED_DOE = {doe!r}
ARM_SEEDS = {arms!r}
BUDGET = {budget!r}
'''
    if re.search(r"[\u4e00-\u9fff]", body):
        raise SystemExit("[FAIL] 生成内容含中文")
    DST.write_bytes(body.encode("utf-8"))
    print("写出 %s（%d B，LF）" % (DST.relative_to(R), DST.stat().st_size))
    print("  池哈希重建一致 ✓  size=%d  x=%d  pairs=%d  doe=%d  arms=%d" %
          (len(pool), len(xs), len(pairs), len(doe), len(arms)))
    print("  arms:", json.dumps(arms))
    print("  budget:", json.dumps(budget))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
