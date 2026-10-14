# -*- coding: utf-8 -*-
"""从**注册结果件**自动抽取「任务期望值」→ `expected/EXPECTED_TASKS.json`。

为什么不能直接把注册件放进包：它们含 `inputs: {"work/runs/...": sha256}` 这类**内部路径键**，
会触发包的身份/双盲审计（RISK: work/runs）。

做法：深度复制注册件 → **剥离**（不是改写）下列键 → 校验剥离后不含任何内路径/用户名/主机名。
剥离清单是**显式**的，并随件写出，供人审计：
  * 任何名为 `seconds` 或以 `_seconds` 结尾的键（墙钟计时）
  * `created_utc` / `created_local` / `duration_*`
  * `inputs`（整体）与 `data_facts.inputs`（整体）
  * `prereg`：指向**不随包分发**的预注册件（包内无法复核其 sha，故不作为可比字段）
  * `registered_result`：指向**包内重生文件**的路径与自身摘要（sha 随行尾等打包细节变化，属溯源指纹）
  * `notes.pchip`（含内部源路径的说明文字）
其余**一律保留**（包括所有数字、结构、键名），使比对可以做**深度相等**而不是只比数值叶。
被剥掉的每一类都在 `removed_keys` 里逐条给出键路径与理由。
"""
from __future__ import annotations

import copy
import hashlib
import json
import pathlib
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
R = pathlib.Path(__file__).resolve().parents[2]
M13 = R / "work/runs/ai11-m1m3-20261013"
T15 = R / "work/runs/ai11-t1t2t5-20261013"
T7 = R / "work/runs/ai11-t7-multiseed-20261013"
M4 = R / "work/runs/ai11-m4-20261013"
OUT = M4 / "EXPECTED_TASKS.json"

STRIP_EXACT = {"created_utc", "created_local", "inputs", "duration_s", "wall_seconds",
               "total_wall_seconds", "elapsed_seconds", "duration_seconds",
               # 溯源块：指向**不随包分发**的上游件，或指向包内重生文件的自身摘要
               "prereg", "registered_result"}
STRIP_SUFFIX = ("_seconds", "_wall_s")
STRIP_PATHS = {("data_facts", "inputs"), ("notes", "pchip")}

# **逐输出**剥离：仅对某个输出件成立的、结构上不可能对上的键（理由随件写出）
STRIP_PER_OUTPUT: dict[str, dict[str, str]] = {
    "results/T7_RESULT.json": {
        "kind": ("the package's T7 task is a SOLVER-FREE REPLAY, a different artifact from the registered "
                 "multi-seed analysis; reporting the registered artifact name as this file's own type would "
                 "misdescribe it"),
        "new_calls_in_extension": ("a count of NEW SOLVES made by the registered extension; the replay makes "
                                   "none, and reports its own counters under oracle.n_solves / n_calls_replayed"),
        "ledger_new_sha256": "digest of the registered solve ledger's new part; the replay writes no ledger",
        "ledger_old_sha256": "digest of the registered solve ledger's old part; the replay reads no ledger",
    },
}

# 任务 → [(输出文件相对路径, 注册参考件)]
TASKS = {
    "label_validity": [("results/label_validity.json", None)],
    "m1_m2_m3": [("results/M1_RESULT_V2.json", M13 / "M1_RESULT_V2.json"),
                 ("results/M2_RESULT.json", M13 / "M2_RESULT.json"),
                 ("results/M3_RESULT.json", M13 / "M3_RESULT.json")],
    "t1_t2": [("results/T1_T2_RESULT.json", T15 / "T1_T2_RESULT.json"),
              ("results/T1_T2_SPACING_RESULT.json", T15 / "T1_T2_SPACING_RESULT.json")],
    "t5": [("results/T5_RESULT.json", T15 / "T5_RESULT.json")],
    "t7_scheduling": [("results/T7_RESULT.json", T7 / "T7_MULTISEED_RESULT.json")],
}

RISK = [("内路径", re.compile(r"work[/\\]runs")),
        ("仓库名", re.compile(r"memsharness")),
        ("用户名", re.compile(r"\bzmx\b|zhangmx", re.I)),
        ("主机名", re.compile(r"node0\d|10\.180\.7\.46|ubuntu-10-180-7-46")),
        ("Windows 绝对路径", re.compile(r"[A-Za-z]:[\\/]")),
        ("模型文件", re.compile(r"[A-Za-z0-9_\-]+\.mph\b"))]

# 自由文本英文化表（**包内同一份**：构建器会把它复制为 tasks/_text.py，任务脚本 import 它）
def _load_text():
    import importlib.util
    p = R / "work/runs/ai11-m4-20261013/pkg_src/_text.py"
    if not p.is_file():
        raise SystemExit("[FAIL] 缺 %s" % p)
    spec = importlib.util.spec_from_file_location("_pkg_text", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m, p


TEXT, TEXT_PATH = _load_text()

REMOVED: list[tuple[str, str]] = []

# 每一类的**准确**理由（审计轨迹里写错理由本身就是缺陷）。包是英文件，理由也写英文。
WHY = {"created_utc": "timestamp (differs on every run)",
       "created_local": "timestamp literal (fixed in the registered artifact, but still run metadata)",
       "inputs": "upstream input inventory: internal path keys plus source-file digests (paths are rewritten "
                 "to package-relative in the package, so the digests change)",
       "prereg": "names a pre-registration file that is NOT distributed with the package (unverifiable "
                 "inside the package, therefore not a comparable field)",
       "registered_result": "names an in-package regenerated file and its own digest (the digest moves with "
                            "packaging details such as line endings; provenance fingerprint)",
       "duration_s": "wall-clock duration", "wall_seconds": "wall-clock duration",
       "total_wall_seconds": "wall-clock duration", "elapsed_seconds": "wall-clock duration",
       "duration_seconds": "wall-clock duration"}
NESTED_WHY = {("data_facts", "inputs"): "upstream data-facts inventory (contains internal path keys)",
              ("notes", "pchip"): "explanatory text containing an internal source path"}


def why_for(k: str, path: str) -> str:
    if k in WHY:
        return WHY[k]
    if any(k.endswith(s) for s in STRIP_SUFFIX):
        return "wall-clock duration (key ends with %s)" % [s for s in STRIP_SUFFIX if k.endswith(s)][0]
    return "stripped by policy"


def strip(o, path="", rel=""):
    if isinstance(o, dict):
        out = {}
        for k, v in o.items():
            here = path + "." + k if path else k
            np_ = (path.lstrip("."), k)
            extra = STRIP_PER_OUTPUT.get(rel) or {}
            if k in STRIP_EXACT or any(k.endswith(s) for s in STRIP_SUFFIX):
                REMOVED.append((here, why_for(k, path)))
                continue
            if k in extra:
                REMOVED.append((here, extra[k]))
                continue
            if np_ in STRIP_PATHS:
                REMOVED.append((here, NESTED_WHY[np_]))
                continue
            out[k] = strip(v, here, rel)
        return out
    if isinstance(o, list):
        return [strip(x, path + "[]", rel) for x in o]
    return o


def main() -> int:
    # label_validity：新任务，期望值 = 产物本身（外部锚点是论文 §6.1 的 259/1782 与 69/223，
    # 该锚点在包外，是本任务唯一的独立核对；注释放 sources，**不放进对比树**，否则深度比对会失败）
    lv_ref = json.loads((M4 / "tasks_dev/_harness/results/label_validity.json").read_text(encoding="utf-8"))
    lv_anchor = ("paper sections 6.1/5: C 259 of 1,782 not closed (14.5 %), A 69 of 223 (30.9 %); "
                 "this anchor lives outside the package and is the only independent check on this task")

    exp = {"kind": "peakguard_bench_expected_tasks",
           "note": ("The expected values for every task are **extracted automatically** from the registered "
                    "result artifacts (never typed by hand), with timing / timestamp / internal-path keys "
                    "stripped; every stripped key is listed in removed_keys for audit. Comparison is a "
                    "**deep equality** over structure, key names and values; see tolerance_rel."),
           "tolerance_rel": 1e-6,
           "identifier_note": ("The `kind` field of each output (e.g. `ai11_t5_refusal_behaviour`) and "
                               "`created_local` are **internal series identifiers** and are kept verbatim: "
                               "renaming them would stop the produced output from being comparable with the "
                               "registered artifact bit-for-bit, and they contain neither author information "
                               "nor paths. A reader can use them together with sources.origin_sha256 to trace "
                               "each output back to its registered artifact."),
           "text_rendering_note": ("Free-text caliber / non-claim / per-cell note strings were written in "
                                   "Chinese by the internal pipeline. This package is an English artifact, so "
                                   "those strings are rendered in English by an explicit table "
                                   "(`tasks/_text.py`, %d entries, sha256 %s), applied identically to the "
                                   "produced outputs and to these expected values. Only the values of those "
                                   "free-text strings change; no number, key name or structure does."
                                   % (len(TEXT.MAP), hashlib.sha256(TEXT_PATH.read_bytes()).hexdigest())),
           "strip_policy": {"exact_keys": sorted(STRIP_EXACT),
                            "suffixes": list(STRIP_SUFFIX),
                            "nested_paths": [".".join(p) for p in sorted(STRIP_PATHS)],
                            "per_output": STRIP_PER_OUTPUT},
           "removed_keys": [], "tasks": {}, "sources": {}}

    for task, items in TASKS.items():
        exp["tasks"][task] = {}
        for rel, ref in items:
            if ref is None:
                exp["tasks"][task][rel] = TEXT.to_en(lv_ref)
                exp["sources"][rel] = {"origin": "computed from package data",
                                       "external_anchor": lv_anchor,
                                       "external_anchor_holds": (lv_ref["per_batch"]["C_5-50MHz"]["n_bandwidth_not_closed"] == 259
                                                                 and lv_ref["per_batch"]["C_5-50MHz"]["n_rows"] == 1782
                                                                 and lv_ref["per_batch"]["A_5-35MHz"]["n_bandwidth_not_closed"] == 69
                                                                 and lv_ref["per_batch"]["A_5-35MHz"]["n_rows"] == 223)}
                continue
            raw = json.loads(ref.read_text(encoding="utf-8"))
            exp["sources"][rel] = {"origin_registered_file": ref.name,
                                  "origin_sha256": hashlib.sha256(ref.read_bytes()).hexdigest(),
                                  "origin_bytes": ref.stat().st_size}
            REMOVED.clear()
            stripped = strip(copy.deepcopy(raw), rel=rel)
            exp["tasks"][task][rel] = TEXT.to_en(stripped)     # 与任务侧**同一张表**
            for p, why in REMOVED:
                exp["removed_keys"].append({"output": rel, "key": p, "why": why})

    blob = json.dumps(exp, ensure_ascii=False)
    bad = [(n, rx.findall(blob)[:3]) for n, rx in RISK if rx.search(blob)]
    left = TEXT.unmapped_cjk(exp["tasks"])
    print("剥离键数: %d" % len(exp["removed_keys"]))
    for r in exp["removed_keys"][:8]:
        print("   - %-34s %s" % (r["key"], r["why"]))
    if len(exp["removed_keys"]) > 8:
        print("   … 共 %d 条" % len(exp["removed_keys"]))
    print("风险串扫描: %s" % (bad if bad else "干净 ✓"))
    if bad:
        raise SystemExit("[FAIL] 剥离后仍有风险串，禁止写出")
    print("残留中文（对比树内）: %d 条" % len(left))
    for p, sv in left[:10]:
        print("   ! %s -> %s" % (p, sv[:80]))
    if left or TEXT.CJK_WIDE.search(blob):
        raise SystemExit("[FAIL] 包内期望件仍含中日韩字符/全角标点（本包为英文件）——补 tasks/_text.py 的映射表")
    # 包内件统一 **LF**（与本包其它 JSON 一致：构建器全部用 .encode("utf-8") 写出）。
    # 「运行产物用 CRLF」的约定针对 work/runs 下的 run 产物；本件是**包内输入件**，随包走 LF。
    blob_out = (json.dumps(exp, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
    if b"\r\n" in blob_out:
        raise SystemExit("[FAIL] 期望件不应含 CRLF")
    OUT.write_bytes(blob_out)
    print("写出 %s（%d B，LF）" % (OUT.relative_to(R), OUT.stat().st_size))
    for t, items in exp["tasks"].items():
        for rel in items:
            print("   %-16s %s" % (t, rel))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
