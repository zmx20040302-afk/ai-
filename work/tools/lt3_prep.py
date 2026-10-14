"""LT3 前置管线（准备性工作，**不调用 COMSOL**）：质检 → 指标拆分 → 归一化契约 → Pareto。

本脚本是 `docs\\TO_CODEX_order-20260913-LT0-LT3.md` §5（LT3-A/B/C/D）的**可执行化前置件**，
目的是在 LT2 反相驱动 504 点数据到位之前，把**代码与口径**先建好并用**已有的批次2（legacy 驱动）
数据**跑通；数据到位后同一条命令即可套用。

============================ 授权限制（写进代码，不只写在文档） ============================

依据：
  - `docs\\TO_CODEX_order-20260913-LT0-LT3.md` §4「LT2未完全通过时不得制作『正式反相粗扫排名』」；
  - `docs\\TO_CODEX_order-20260914-LT2-superseding-LT2B-LT2D.md` §7「LT2 = BLOCKED_BEFORE_PRODUCTION」。

因此本脚本内置两道**fail-closed** 守卫：

  1. `FORMAL_RANKING_AUTHORIZED = False`（常量，不可由命令行打开）。
     任何带 `--formal` / `--allow-formal-ranking` 的调用**直接拒绝退出**（exit 2）。
  2. 驱动模式守卫：
     - 检测到**反相驱动**数据（`dual_electrode_antiphase_voltage_drive`）⇒ **拒绝输出任何排名/Pareto**，
       只允许输出「对比用中间量」(`lt3_intermediate_comparison.csv`)，退出码 3；
     - 检测到 **legacy 驱动**数据（用户批次2 导出所用的旧驱动）⇒ 允许输出排名/Pareto，
       但**每一行都强制携带** `drive_mode = legacy_1ohm_to_reference` 与
       `status = provisional_legacy_not_formal`、`formal_ranking = false`。

产物一律落在 `--out-dir`（默认 `work\\lt3`，**只写这个目录**）；本脚本**不写 `work\\runs\\`**。

============================ 归一化口径（LT3-D） ============================

    Ptot_norm = Ptot / |Vdiff|^2      [W/V^2]
    Vave_norm = Vave / |Vdiff|        [(m/s)/V]

`|Vdiff|` 对反相驱动 = |V_outer - V_inner| = 2*vamp = 2 V（`work\\models\\drive_change_manifest.json`）。
对 **legacy 批次2 导出**：导出表**没有**任何电位/差分电压列（实核：列只有
`x_scale, N_w_te1, freq(Hz), Zin1_R/X, Zin2_R/X, Ptot(W), V_center(m/s), Vave(m/s)`）
⇒ `Ptot_norm`/`Vave_norm` **无法计算**，一律留空并写明原因，**不填推测值**。

用法：
    work\\.venv\\Scripts\\python.exe work\\tools\\lt3_prep.py ^
        --input "work\\reports\\analysis_decision\\newrange005\\raw_source_table.csv" ^
        --source-run-id "batch2-legacy-newrange005" ^
        --precheck "work\\runs\\precheck-b2-phase2-v5-aggregate\\geometry_selection_precheck.json" ^
        --out-dir "work\\lt3"

    # 反相数据（LT2 到位后）：同一条命令，脚本会自动拒绝正式排名
    work\\.venv\\Scripts\\python.exe work\\tools\\lt3_prep.py ^
        --input "<reverse_drive_coarse_raw>.csv|xlsx" --source-run-id "<run_id>" --out-dir "work\\lt3"
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import re
import shutil
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

# 控制台多为 GBK：Emoji/生僻字降级输出，避免 UnicodeEncodeError 中断整条管线（2026-09-13 实测踩坑）
try:
    sys.stdout.reconfigure(errors="replace")  # type: ignore[union-attr]
    sys.stderr.reconfigure(errors="replace")  # type: ignore[union-attr]
except Exception:
    pass

# ======================================================================================
# 授权限制常量 —— 不得由命令行放宽
# ======================================================================================
#: LT3 正式排名授权总开关。2026-09-14 状态：LT2 = BLOCKED_BEFORE_PRODUCTION ⇒ 恒为 False。
#: 只有当 LT2-E 聚合验收全通过并由人工/工单正式放行后，才允许把这里改为 True（属代码变更，需留痕）。
FORMAL_RANKING_AUTHORIZED: bool = False

#: 本条守卫的依据文件（报告里引用其 sha256，保证守卫不是"口头约定"）
AUTHORITY_DOCS = [
    "docs/TO_CODEX_order-20260913-LT0-LT3.md",
    "docs/TO_CODEX_order-20260914-LT2-superseding-LT2B-LT2D.md",
]

#: 本脚本允许的两种驱动口径（规范名）
LEGACY_DRIVE_MODE = "legacy_1ohm_to_reference"
REVERSE_DRIVE_MODE = "dual_electrode_antiphase_voltage_drive"

#: 兼容既有产物里出现过的等价写法（**只做别名归一，不改变语义**）
LEGACY_DRIVE_ALIASES = {
    "legacy_1ohm_to_reference",
    "inner_fixed_minus_v0_outer_circuit_terminal_1ohm_to_reference",
    "circuit_terminal_1ohm_current_model",
    "legacy",
    "1ohm_circuit",
}
REVERSE_DRIVE_ALIASES = {
    "dual_electrode_antiphase_voltage_drive",
    "reverse",
    "antiphase_voltage_drive",
}

#: 强制性状态标签：legacy 数据只能出"临时排名"
PROVISIONAL_STATUS = "provisional_legacy_not_formal"
REFUSED_STATUS = "refused_reverse_drive_lt2_incomplete"

#: LT0-C 实测 KCL（依据 `work/models/lt0_audit.json`）⇒ 电气指标排除
KCL_MAX_RELATIVE_OBSERVED = 0.18863816663610675
KCL_TOLERANCE = 0.01
ELECTRICAL_EXCLUSION_REASON = "LT0_C_KCL_relative_gt_1pct"

#: 反相驱动标称电位
REVERSE_VAMP_V = 1.0
REVERSE_VDIFF_V = 2.0 * REVERSE_VAMP_V

# --------------------------------------------------------------------------------------
# legacy 侧 |Vdiff| 的**人反馈**口径（2026-09-14）
# --------------------------------------------------------------------------------------
#: legacy 批次2 的 |Vdiff| 来自**用户人反馈**，不是导出表、不是模型读数。
#: 依据：`docs/TO_USER-feedback-20260914-legacy-drive-amplitude.md`。
LEGACY_VDIFF_SOURCE_TYPE = "human_feedback"
LEGACY_VDIFF_FEEDBACK_ID = "fb-20260914-legacy-drive-amplitude"
LEGACY_VDIFF_FEEDBACK_DOC = "docs/TO_USER-feedback-20260914-legacy-drive-amplitude.md"
LEGACY_VDIFF_DECLARED_V = 1.0
LEGACY_VDIFF_QUOTE = ("legacy 批次2使用 v0=1 V；实际工况为内电极 −1 V，外电极经 1 Ω 支路近接 0 V，"
                      "所以有效差分激励约为 1 V。该数据不是 ±1 V 反相驱动。")

#: **必须随产物保留的限制**（写进代码，不只写在文档里）
LEGACY_VDIFF_LIMITATION = (
    "用户原话为『约 1 V』。外电极经 1 Ω 支路接参考端时其电位并非精确 0 V（有电流即有压降），"
    "故 |Vdiff| 严格小于 1 V ⇒ 用 1.000 V 做分母引入一个**方向已知、量级未量化**的系统偏差。"
    "该量级**无法从现有资料界定**：本应由电气电流/阻抗量估计，而那些量已因 LT0-C 实测 "
    "KCL 相对误差 16.6–18.9% > 1% 被整体排除。**不得编造 V_outer 数值**；只能如实标为未量化的限制。"
)
LEGACY_VDIFF_NON_COMPUTABLE_REASON = "legacy_export_lacks_Vdiff__normalization_not_computable"

# ======================================================================================
# 列识别规则
# ======================================================================================
KEY_PATTERNS = {
    "x_scale": r"x[\s_-]*scale",
    "N_w_te1": r"n[\s_-]*w[\s_-]*te1",
    "freq": r"freq",
}
#: **声学指标**（参与排名/Pareto）
ACOUSTIC_PATTERNS = {
    "Ptot": r"^ptot",
    "Vave": r"^v[\s_-]*ave",
    "V_center": r"^v[\s_-]*center",
}
#: **被排除的电气指标**（LT0-C：KCL 相对误差 16.6–18.9% > 1%）——**不得参与排名**
ELECTRICAL_PATTERNS = {
    "Zin1_R": r"^zin1[\s_-]*r",
    "Zin1_X": r"^zin1[\s_-]*x",
    "Zin2_R": r"^zin2[\s_-]*r",
    "Zin2_X": r"^zin2[\s_-]*x",
    "I_inner_abs": r"^i[\s_-]*inner",
    "I_outer_abs": r"^i[\s_-]*outer",
    "I_ref_abs": r"^i[\s_-]*ref",
    "I01": r"^i01",
    "I02": r"^i02",
}
#: 反相驱动签名列（存在即说明该批不是 legacy 导出）
REVERSE_SIGNATURE_PATTERNS = {
    "Vdiff_abs": r"^v[\s_-]*diff",
    "V_outer_re": r"^v[\s_-]*outer[\s_-]*re",
    "V_inner_re": r"^v[\s_-]*inner[\s_-]*re",
}
DRIVE_MODE_COLUMN_PATTERN = r"^drive[\s_-]*mode"
SOURCE_RUN_ID_PATTERN = r"^source[\s_-]*run[\s_-]*id"


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    """文件 sha256；读不到就抛错，**不返回假值**。"""
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- 读表（CSV / XLSX，仅标准库）
NS_M = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
CELL_RX = re.compile(r"^([A-Z]+)(\d+)$")


def _xlsx_col_index(ref: str) -> int:
    letters = CELL_RX.match(ref).group(1)
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def read_xlsx_rows(path: Path) -> list[list[str]]:
    """只用标准库读 .xlsx（zip + XML）——本机 venv 无 openpyxl。复用 `work\\tools\\xlsx_to_csv.py` 的做法。"""
    with zipfile.ZipFile(path) as zf:
        sst: list[str] = []
        if "xl/sharedStrings.xml" in zf.namelist():
            root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in root.findall("m:si", NS_M):
                sst.append("".join(t.text or "" for t in si.iter(f"{{{NS_M['m']}}}t")))
        # 取第一张工作表
        sheets = sorted(p for p in zf.namelist() if p.startswith("xl/worksheets/sheet"))
        if not sheets:
            raise SystemExit(f"[错误] {path} 内找不到工作表")
        root = ET.fromstring(zf.read(sheets[0]))
        out: list[list[str]] = []
        for row in root.iter(f"{{{NS_M['m']}}}row"):
            cells: dict[int, str] = {}
            for c in row.findall("m:c", NS_M):
                ref = c.get("r")
                if not ref:
                    continue
                ctype = c.get("t")
                if ctype == "s":
                    v = c.find("m:v", NS_M)
                    val = sst[int(v.text)] if v is not None and v.text is not None else ""
                elif ctype == "inlineStr":
                    el = c.find("m:is", NS_M)
                    val = "".join(t.text or "" for t in el.iter(f"{{{NS_M['m']}}}t")) if el is not None else ""
                else:
                    v = c.find("m:v", NS_M)
                    val = v.text if v is not None and v.text is not None else ""
                cells[_xlsx_col_index(ref)] = val
            if cells:
                out.append([cells.get(i, "") for i in range(max(cells) + 1)])
        return out


def read_grid(path: Path) -> tuple[list[list[str]], str, str]:
    """返回 (网格行, 编码, 分隔符)。CSV/TSV 走解码级联，XLSX 走标准库解析。"""
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        return read_xlsx_rows(path), "xlsx(zip+xml)", "n/a"
    raw = path.read_bytes()
    used = None
    text = ""
    for enc in ("utf-8-sig", "utf-8", "gb18030", "cp936", "latin-1"):
        try:
            text = raw.decode(enc)
            used = enc
            break
        except UnicodeDecodeError:
            continue
    if used is None:
        text, used = raw.decode("utf-8", errors="replace"), "utf-8(replace)"
    delim = "\t" if text.count("\t") > text.count(",") else ","
    grid = [r for r in csv.reader(io.StringIO(text), delimiter=delim) if r]
    return grid, used, ("tab" if delim == "\t" else "comma")


def locate_header(grid: list[list[str]]) -> int:
    """定位表头行：第一个首列匹配 `x_scale` 的行。"""
    for i, r in enumerate(grid):
        if r and re.search(KEY_PATTERNS["x_scale"], r[0], re.I):
            return i
    raise SystemExit(f"[错误] 找不到表头行（首列应匹配 {KEY_PATTERNS['x_scale']!r}）")


def map_columns(header: list[str]) -> dict[str, str]:
    """把表头映射到语义键。同义列只取第一个匹配（并记录全部匹配以便报告）。"""
    mapping: dict[str, str] = {}
    for group in (KEY_PATTERNS, ACOUSTIC_PATTERNS, ELECTRICAL_PATTERNS, REVERSE_SIGNATURE_PATTERNS):
        for key, pat in group.items():
            for col in header:
                if re.search(pat, col.strip(), re.I):
                    mapping[key] = col
                    break
    for key, pat in (("drive_mode", DRIVE_MODE_COLUMN_PATTERN), ("source_run_id", SOURCE_RUN_ID_PATTERN)):
        for col in header:
            if re.search(pat, col.strip(), re.I):
                mapping[key] = col
                break
    return mapping


def parse_complex(text: str) -> complex | None:
    """解析 COMSOL 导出的复数（形如 `-4.7e-6-0.00437i`）。无法解析返回 None（不猜）。"""
    body = (text or "").strip().replace(" ", "")
    if not body:
        return None
    if not body.endswith("i"):
        try:
            return complex(float(body), 0.0)
        except ValueError:
            return None
    head = body[:-1]
    split = None
    for i, ch in enumerate(head):
        if ch in "+-" and i > 0 and head[i - 1] not in "eE":
            split = i
    if split is None:
        try:
            return complex(0.0, float(head))
        except ValueError:
            return None
    try:
        return complex(float(head[:split]), float(head[split:]))
    except ValueError:
        return None


def to_float(text: str) -> float | None:
    body = (text or "").strip()
    if not body:
        return None
    try:
        return float(body)
    except ValueError:
        return None


# ---------------------------------------------------------------- 频率单位归一（禁止 Hz/MHz 混列）
def freq_scale_to_hz(colname: str, values: list[float]) -> tuple[float, str, bool]:
    """判定频率列的单位 → 返回 (换算到 Hz 的系数, 判定方法, 是否为启发式假设)。

    优先按**列名**判定（`freq_MHz` / `freq (Hz)` 等）；列名无单位时按数值量级启发式判定，
    并把 `heuristic_assumption=True` 留痕（dataset-contract §5：禁止把 Hz 与 MHz 混为同一列，
    也不得静默猜测）。
    """
    c = (colname or "").lower()
    if "ghz" in c:
        return 1e9, "column_name_ghz", False
    if "mhz" in c:
        return 1e6, "column_name_mhz", False
    if "khz" in c:
        return 1e3, "column_name_khz", False
    if "hz" in c:
        return 1.0, "column_name_hz", False
    mx = max((abs(v) for v in values), default=0.0)
    if mx and mx < 1e4:
        return 1e6, "heuristic_magnitude_assumed_mhz", True
    return 1.0, "heuristic_magnitude_assumed_hz", True


def normalize_freq_column(rows: list[dict], freq_col: str) -> dict:
    """把频率列就地换算成 **Hz**（内部 SI），供后续 `f/1e6 -> MHz` 统一处理。"""
    vals = [v for v in (to_float(r.get(freq_col, "")) for r in rows) if v is not None]
    scale, how, assumed = freq_scale_to_hz(freq_col, vals)
    if scale != 1.0:
        for r in rows:
            v = to_float(r.get(freq_col, ""))
            if v is not None:
                r[freq_col] = repr(v * scale)
    return {"column": freq_col, "scale_applied_to_hz": scale, "method": how,
            "heuristic_assumption": assumed,
            "note": "内部一律 Hz；MHz 列表会乘以 1e6 后再统一按 Hz 处理"}


# ---------------------------------------------------------------- 驱动模式判定
def normalize_drive(raw: str) -> str:
    key = (raw or "").strip().lower()
    if key in LEGACY_DRIVE_ALIASES:
        return LEGACY_DRIVE_MODE
    if key in REVERSE_DRIVE_ALIASES:
        return REVERSE_DRIVE_MODE
    return "unknown"


def infer_drive_mode(mapping: dict[str, str], declared: str) -> dict:
    """从列结构推断驱动口径。**明确标注这是启发式推断**，不是模型读数。"""
    has_reverse_sig = any(k in mapping for k in ("Vdiff_abs", "V_outer_re", "V_inner_re"))
    has_electrical = any(k in mapping for k in ("Zin1_R", "Zin2_R"))
    if has_reverse_sig:
        inferred, how = REVERSE_DRIVE_MODE, "columns_contain_Vdiff_or_electrode_voltage"
    elif has_electrical:
        inferred, how = LEGACY_DRIVE_MODE, "columns_contain_Zin_without_Vdiff"
    else:
        inferred, how = "unknown", "no_drive_signature_column"
    declared_norm = normalize_drive(declared) if declared and declared != "auto" else "unknown"
    effective = declared_norm if declared_norm != "unknown" else inferred
    mismatch = bool(declared_norm != "unknown" and inferred != "unknown" and declared_norm != inferred)
    return {
        "declared": declared_norm,
        "inferred": inferred,
        "inference_method": how,
        "effective": effective,
        "declaration_vs_inference_mismatch": mismatch,
        "caveat": "推断仅依据导出列结构；不是 COMSOL 模型读数（红线 3：不猜测模型内部）",
    }


# ---------------------------------------------------------------- 归一化契约
def normalization_contract(legacy_vdiff: dict | None = None) -> dict:
    """两套驱动下 `Ptot`/`Vave` 的归一化口径，以及**可/不可跨驱动比较**的清单与依据。

    `legacy_vdiff` 为 None ⇒ legacy 侧分母不可得（归一化不可计算，原判）。
    `legacy_vdiff` 非 None ⇒ 分母来自**人反馈**（`source_type = human_feedback`）；
    **分子（Ptot/Vave）来自导出表**，两者来源不同，必须分列标注（红线 4）。
    """
    legacy_norm_ok = legacy_vdiff is not None
    return {
        "formulas": {
            "Ptot_norm": "Ptot / abs(Vdiff)^2   # 单位 W/V^2（功率量）",
            "Vave_norm": "Vave / abs(Vdiff)     # 单位 (m/s)/V（幅值量）",
        },
        "dB_rules": {
            "amplitude": "20*log10  （用于 Vave / Vave_norm / V_center）",
            "power": "10*log10     （用于 Ptot / Ptot_norm）",
            "rule": "幅值与功率绝不混用（sweep-analysis SOP §0 铁律 1）",
        },
        # ---- 红线 4：归一化量的分子与分母来源不同，必须显式分离 ----
        "source_separation": {
            "numerator": {
                "quantities": ["Ptot", "Vave"],
                "source_type": "simulation",
                "origin": "COMSOL 导出表列（批次2 xlsx；sha256 见 quality_report.source_file_sha256）",
            },
            "denominator_legacy": {
                "quantity": "abs(Vdiff)",
                "source_type": LEGACY_VDIFF_SOURCE_TYPE if legacy_norm_ok else "unavailable",
                "value_V": legacy_vdiff["value_V"] if legacy_norm_ok else None,
                "feedback_id": legacy_vdiff["feedback_id"] if legacy_norm_ok else None,
                "evidence_file": legacy_vdiff["evidence_file"] if legacy_norm_ok else None,
                "evidence_sha256": legacy_vdiff["evidence_sha256"] if legacy_norm_ok else None,
                "quote": LEGACY_VDIFF_QUOTE,
                "not_from": ["COMSOL 模型读数", "导出表列", "模型参数（V0 曾报『未知参数』）"],
                "limitation": LEGACY_VDIFF_LIMITATION,
            },
            "denominator_reverse": {
                "quantity": "abs(Vdiff)",
                "source_type": "simulation",
                "value_V": REVERSE_VDIFF_V,
                "origin": "反相导出含 Vdiff_abs 列；与 work/models/drive_change_manifest.json 一致",
            },
            "rule": "归一化量是**混合来源**（分子 simulation + 分母 human_feedback）；"
                    "任何统计/报告必须显式声明该混用，**不得**写成『由模型或导出表得到』",
        },
        "drives": {
            LEGACY_DRIVE_MODE: {
                "alias_full": "inner_fixed_minus_v0_outer_circuit_terminal_1ohm_to_reference",
                "vamp_V": None,
                "Vdiff_V": legacy_vdiff["value_V"] if legacy_norm_ok else None,
                "Vdiff_available_in_export": False,
                "Vdiff_source_type": LEGACY_VDIFF_SOURCE_TYPE if legacy_norm_ok else "unavailable",
                "evidence": "批次2 导出表列实核：x_scale,N_w_te1,freq(Hz),Zin1_R/X,Zin2_R/X,Ptot(W),V_center(m/s),Vave(m/s) "
                            "——**无任何电位/差分电压列**；故分母改由人反馈提供"
                            + (f"（{LEGACY_VDIFF_FEEDBACK_ID}）" if legacy_norm_ok else ""),
                "Ptot_norm": "computable_denominator_from_human_feedback" if legacy_norm_ok else "not_computable",
                "Vave_norm": "computable_denominator_from_human_feedback" if legacy_norm_ok else "not_computable",
                "reason": LEGACY_VDIFF_LIMITATION if legacy_norm_ok
                          else f"{LEGACY_VDIFF_NON_COMPUTABLE_REASON}（导出未记录 Vdiff，且未提供人反馈分母）",
            },
            REVERSE_DRIVE_MODE: {
                "alias_full": "dual_electrode_antiphase_voltage_drive",
                "vamp_V": REVERSE_VAMP_V,
                "Vdiff_V": REVERSE_VDIFF_V,
                "Vdiff_available_in_export": True,
                "Vdiff_source_type": "simulation",
                "evidence": "work/models/drive_change_manifest.json：V_outer=+vamp, V_inner=-vamp, V_reference=0, Vdiff=2*vamp",
                "Ptot_norm": "computable",
                "Vave_norm": "computable",
                "reason": "",
            },
        },
        "cross_drive_comparable": [
            {
                "quantity": "Ptot_norm = Ptot/|Vdiff|^2",
                "comparable": "conditional",
                "conditions": [
                    "两侧都必须有 |Vdiff|（legacy 侧来自人反馈，反相侧来自导出/manifest）",
                    "控制面必须同一：intop5==swr1==efc1 且 area_ptot/bbox 唯一（批次2 phase2 聚合已验：area_ptot 唯一值 1 个，bbox 唯一 1 个）",
                    "网格上界必须同一（本批 mesh fmax = 35 MHz）",
                    "几何族/选择语义必须可比（同 model family，不同 model_sha256 不得合并统计）",
                ],
            },
            {
                "quantity": "Vave_norm = Vave/|Vdiff|",
                "comparable": "conditional",
                "conditions": ["同 Ptot_norm 的四条条件", "Vave 定义为面平均法向速度（响应量），不得称往返/脉冲回波/阵列带宽"],
            },
        ],
        "cross_drive_not_comparable": [
            {"quantity": "Ptot（原始 W）", "why": "legacy 约 1 V 单端电路驱动 vs 反相 ±1 V（Vdiff=2 V）⇒ 电压口径不同，约 4 倍功率差是驱动电压造成的（4 = 2^2），不是结构收益（LT3-D 明文禁止）"},
            {"quantity": "Vave（原始 m/s）", "why": "同上，缺少 |Vdiff| 归一，幅值不可直接并列"},
            {"quantity": "Zin1_*/Zin2_*/I_*（电气量）", "why": "LT0-C 实测 KCL 相对误差 16.6–18.9% > 1% 门槛 ⇒ 电气指标整体排除，既不参与排名也不参与跨驱动比较；归一化只作用于声学量，不改变该排除"},
            {"quantity": "反相 vs legacy 的绝对电平差", "why": "来源永不混同（红线 4）：两批 model_sha256 不同（legacy 0f75ca1d… vs 反相 cbe9ccc1…），只能并排对照，不得合并统计"},
        ],
        "authority": {
            "ok_to_rank": FORMAL_RANKING_AUTHORIZED,
            "legacy_vs_reverse_status": "provisional_legacy_vs_reverse_normalized_not_formal",
            "reason": "LT2 = BLOCKED_BEFORE_PRODUCTION（docs/TO_CODEX_order-20260914-LT2-superseding-LT2B-LT2D.md §7）"
                      "⇒ 对照表只是诊断/中间产物，不得升级为正式排名",
        },
    }


# ---------------------------------------------------------------- 主流程
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="LT3 前置管线（质检/指标拆分/归一化/Pareto；无 COMSOL）")
    ap.add_argument("--input", required=True, help="导出表：.csv / .tsv / .xlsx（用户原始导出或已转出 CSV）")
    ap.add_argument("--out-dir", default="work\\lt3", help="产物目录（只写这里；默认 work\\lt3）")
    ap.add_argument("--precheck", default=None,
                    help="几何/选择预检 JSON（如 work\\runs\\precheck-b2-phase2-v5-aggregate\\geometry_selection_precheck.json）")
    ap.add_argument("--source-run-id", required=True, help="本批数据来源 run_id（写进每行）")
    ap.add_argument("--drive-mode", default="auto",
                    help=f"驱动口径：auto（默认，按列推断）| {LEGACY_DRIVE_MODE} | {REVERSE_DRIVE_MODE} | 既有别名")
    ap.add_argument("--target-mhz", type=float, default=20.0)
    ap.add_argument("--pareto-metrics", default="Ptot_20MHz_W,Vave_20MHz",
                    help="两个声学指标（逗号分隔，均取最大化）。可选：Ptot_20MHz_W,Ptot_peak_W,Vave_20MHz,Vave_peak,V_center_20MHz")
    ap.add_argument("--no-copy-inputs", action="store_true", help="不把输入复制到 <out-dir>\\inputs\\（默认复制）")
    # ---- legacy 侧 |Vdiff| 的**人反馈**分母（红线 4：分子/分母来源必须分离）----
    ap.add_argument("--legacy-vdiff-V", type=float, default=None,
                    help="legacy 侧 |Vdiff|（V）。**该值来自人反馈**，不是导出表/模型读数；"
                         "提供时必须同时给出 --legacy-vdiff-feedback-id 与 --legacy-vdiff-feedback-doc")
    ap.add_argument("--legacy-vdiff-feedback-id", default=None, help="人反馈 ID，如 fb-20260914-legacy-drive-amplitude")
    ap.add_argument("--legacy-vdiff-feedback-doc", default=None, help="人反馈记录文件（必须存在，会取 sha256 写进产物）")
    # ---- 频段界参数化（默认 = 从输入数据自动探测，与参数化前逐位一致）----
    ap.add_argument("--band-min-mhz", type=float, default=None,
                    help="频段下界 (MHz)。默认 None ⇒ 从输入数据的频点集合**自动探测**（per-combo 最小频点）")
    ap.add_argument("--band-max-mhz", type=float, default=None,
                    help="频段上界 (MHz)。默认 None ⇒ 从输入数据**自动探测**（per-combo 最大频点）。"
                         "给定值时 band_source=cli；**绝不外推**：界外无数据则边频仍标 not_found")
    ap.add_argument("--compare-reverse", default=None,
                    help="反相驱动数据表（如 work\\runs\\lt1-reverse-sample\\lt1_validated_results_v2.csv）；"
                         "提供则产出 legacy_vs_reverse_normalized.csv 并排对照表")
    # ---- 守卫：任何试图开启正式排名的参数一律拒绝 ----
    ap.add_argument("--formal", action="store_true", help="[禁止] 请求正式排名；本会话恒被拒绝")
    ap.add_argument("--allow-formal-ranking", action="store_true", help="[禁止] 同上（别名）")
    args = ap.parse_args(argv)

    out_dir = Path(args.out_dir)
    if "runs" in [p.lower() for p in out_dir.parts]:
        print("[拒绝] --out-dir 不得位于 work\\runs\\ 之下（另一 agent 正在该目录跑验收与冻结）")
        return 2

    # ============================ 守卫 1：正式排名总开关 ============================
    if args.formal or args.allow_formal_ranking:
        print("[拒绝] 请求了正式排名（--formal / --allow-formal-ranking）⇒ 直接退出，不产出任何排名。")
        print(f"[拒绝] FORMAL_RANKING_AUTHORIZED = {FORMAL_RANKING_AUTHORIZED}")
        print("        依据 docs\\TO_CODEX_order-20260913-LT0-LT3.md §4 与")
        print("             docs\\TO_CODEX_order-20260914-LT2-superseding-LT2B-LT2D.md §7（LT2 = BLOCKED_BEFORE_PRODUCTION）")
        return 2
    if not FORMAL_RANKING_AUTHORIZED:
        print(f"[守卫] FORMAL_RANKING_AUTHORIZED = {FORMAL_RANKING_AUTHORIZED}")
        print("       依据 docs\\TO_CODEX_order-20260913-LT0-LT3.md §4 与")
        print("            docs\\TO_CODEX_order-20260914-LT2-superseding-LT2B-LT2D.md §7（LT2 = BLOCKED_BEFORE_PRODUCTION）")
        print("       ⇒ LT2 未完全通过前，不得制作『正式反相粗扫排名』。")
        print("       ⇒ 本脚本只输出 status = provisional_legacy_not_formal 的临时排名（且仅限 legacy 数据）。")

    src = Path(args.input)
    if not src.is_file():
        print(f"[错误] 输入不存在：{src}")
        return 2
    out_dir.mkdir(parents=True, exist_ok=True)

    # ============================ 0. 复制只读输入到 work\lt3\inputs ============================
    inputs_dir = out_dir / "inputs"
    copied: list[dict] = []
    if not args.no_copy_inputs:
        inputs_dir.mkdir(parents=True, exist_ok=True)
        for p in [src] + ([Path(args.precheck)] if args.precheck else []):
            if not p.is_file():
                continue
            dst = inputs_dir / p.name
            if dst.exists() and sha256_file(dst) == sha256_file(p):
                copied.append({"src": str(p), "dst": str(dst), "sha256": sha256_file(p), "action": "already_present"})
                continue
            shutil.copy2(p, dst)
            a, b = sha256_file(p), sha256_file(dst)
            copied.append({"src": str(p), "dst": str(dst), "sha256": a,
                           "sha256_copy": b, "copy_verified": a == b, "action": "copied"})
            if a != b:
                print(f"[错误] 复制校验失败：{p} -> {dst}")
                return 2

    # ============================ 1. 读表与列映射 ============================
    grid, enc, delim = read_grid(src)
    hi = locate_header(grid)
    header = [c.strip().lstrip("% ").strip() for c in grid[hi]]
    mapping = map_columns(header)
    rows = [dict(zip(header, r)) for r in grid[hi + 1:] if len(r) >= len(header) and r[0].strip()]
    freq_unit_norm = normalize_freq_column(rows, mapping["freq"])
    if freq_unit_norm["scale_applied_to_hz"] != 1.0:
        print(f"频率单位：列 {freq_unit_norm['column']!r} 按 {freq_unit_norm['method']} "
              f"×{freq_unit_norm['scale_applied_to_hz']:g} 归一到 Hz")

    missing_keys = [k for k in ("x_scale", "N_w_te1", "freq") if k not in mapping]
    if missing_keys:
        print(f"[错误] 关键列缺失：{missing_keys}；实际表头={header}")
        return 2
    missing_acoustic = [k for k in ("Ptot", "Vave") if k not in mapping]
    if missing_acoustic:
        print(f"[错误] 必需声学量列缺失：{missing_acoustic}（无法计算声学指标）")
        return 2

    drive = infer_drive_mode(mapping, args.drive_mode)
    effective = drive["effective"]
    if effective == "unknown":
        print("[拒绝] 无法判定驱动口径（既无 Vdiff/电极电压列，也无 Zin 列），且未用 --drive-mode 显式声明。"
              "fail-closed：不出任何排名。")
        return 2
    if drive["declaration_vs_inference_mismatch"]:
        print(f"[拒绝] 声明的驱动口径（{drive['declared']}）与数据列推断（{drive['inferred']}）矛盾。"
              "来源永不混同（红线 4）⇒ fail-closed，不出任何排名。")
        return 2

    # ============================ 1b. legacy 侧人反馈分母（红线 4：来源分离） ============================
    legacy_vdiff: dict | None = None
    if args.legacy_vdiff_V is not None:
        if effective != LEGACY_DRIVE_MODE:
            print(f"[拒绝] --legacy-vdiff-V 只适用于 legacy 数据（当前 effective={effective}）⇒ fail-closed。")
            return 2
        if not args.legacy_vdiff_feedback_id or not args.legacy_vdiff_feedback_doc:
            print("[拒绝] 提供 --legacy-vdiff-V 时必须同时给出 --legacy-vdiff-feedback-id 与 "
                  "--legacy-vdiff-feedback-doc（红线 4：人反馈值必须带可追溯 ID 与记录文件）。")
            return 2
        fb_doc = Path(args.legacy_vdiff_feedback_doc)
        if not fb_doc.is_file():
            print(f"[拒绝] 人反馈记录文件不存在：{fb_doc} ⇒ fail-closed（不得凭声明值出数）。")
            return 2
        legacy_vdiff = {
            "value_V": float(args.legacy_vdiff_V),
            "source_type": LEGACY_VDIFF_SOURCE_TYPE,
            "feedback_id": args.legacy_vdiff_feedback_id,
            "evidence_file": str(fb_doc.resolve()),
            "evidence_sha256": sha256_file(fb_doc),
            "quote": LEGACY_VDIFF_QUOTE,
            "limitation": LEGACY_VDIFF_LIMITATION,
            "declared_as_approximate": True,
        }
        print(f"[来源分离] legacy 归一化分母 |Vdiff| = {legacy_vdiff['value_V']} V "
              f"来自 source_type={LEGACY_VDIFF_SOURCE_TYPE}（{legacy_vdiff['feedback_id']}，"
              f"依据 {fb_doc.name} sha256 {legacy_vdiff['evidence_sha256'][:12]}…）——**不是**模型/导出表读数")
        print(f"[限制] {LEGACY_VDIFF_LIMITATION}")
    else:
        print(f"[提示] 未提供 --legacy-vdiff-V ⇒ legacy 侧归一化维持不可计算（{LEGACY_VDIFF_NON_COMPUTABLE_REASON}）")

    src_sha = sha256_file(src)
    authority_hashes = {}
    for d in AUTHORITY_DOCS:
        p = Path(d)
        authority_hashes[d] = sha256_file(p) if p.is_file() else None

    print(f"输入：{src}（{len(rows)} 数据行，{len(mapping)} 列识别，编码 {enc}，分隔符 {delim}）")
    print(f"      源 sha256 {src_sha}")
    print(f"驱动：declared={drive['declared']} inferred={drive['inferred']} → effective={effective}"
          f"（{drive['inference_method']}）")

    # ============================ 2. 预检（排名资格） ============================
    precheck: dict[tuple[float, float], dict] = {}
    precheck_sha = None
    precheck_src = None
    if args.precheck and Path(args.precheck).is_file():
        precheck_src = str(Path(args.precheck).resolve())
        precheck_sha = sha256_file(Path(args.precheck))
        spec = json.loads(Path(args.precheck).read_text(encoding="utf-8"))
        # 兼容两种结构：聚合（phase2_rows）与一级（rows / phase1_rows_with_pattern_id）。
        # **优先级**：phase2_rows 最后载入 ⇒ 对同一组合覆盖/补充 phase1 记录（phase2 含控制面证据），
        # 而 phase1 覆盖全部 162 组合 ⇒ 剩余组合仍保留资格判定（不丢信息）。
        for key in ("phase1_rows_with_pattern_id", "rows", "phase2_rows"):
            for r in spec.get(key, []) or []:
                if "x_scale" in r and "N_w_te1" in r:
                    k = (round(float(r["x_scale"]), 6), int(float(r["N_w_te1"])))
                    precheck[k] = r
        print(f"预检：载入 {len(precheck)} 个组合（sha256 {precheck_sha[:12]}…，来源 {Path(args.precheck).name}）")
    else:
        print("[!] 未提供 --precheck：排名资格无法判定 ⇒ 排名显式降级为『临时且未过几何/选择预检』")

    def classify(k: tuple[float, float]) -> tuple[str, bool, str]:
        """返回 (precheck_class, eligible_for_ranking, reason)。未提供预检时资格为未知 ⇒ 不阻止输出，但标注。"""
        r = precheck.get(k)
        if r is None:
            if precheck:
                return "precheck_missing", False, "该组合不在预检清单内"
            return "precheck_not_provided", True, "未提供预检文件；资格未判定"
        elig = r.get("eligible_for_ranking")
        if elig is None:
            elig = r.get("eligibility_level") in ("full",) or r.get("mesh_status") == "ok"
        cls = r.get("classification") or r.get("eligibility_level") or r.get("design_status") or "unknown"
        reason = r.get("eligibility_reason") or r.get("design_status") or ""
        return str(cls), bool(elig), str(reason)

    # ============================ 3. 质检 ============================
    combos: dict[tuple[float, float], list[dict]] = {}
    dup_keys = 0
    seen_pairs: set[tuple[float, float, float]] = set()
    for r in rows:
        x = to_float(r[mapping["x_scale"]])
        n = to_float(r[mapping["N_w_te1"]])
        f = to_float(r[mapping["freq"]])
        if x is None or n is None or f is None:
            continue
        k = (round(x, 6), int(n))
        combos.setdefault(k, []).append(r)
        pk = (round(x, 6), int(n), round(f, 3))
        if pk in seen_pairs:
            dup_keys += 1
        seen_pairs.add(pk)

    xs_sorted = sorted({k[0] for k in combos})
    ns_sorted = sorted({k[1] for k in combos})
    freqs_sorted = sorted({round(to_float(r[mapping["freq"]]) or 0.0, 3) for r in rows})

    rows_per_combo: dict[int, int] = {}
    for _, g in combos.items():
        rows_per_combo[len(g)] = rows_per_combo.get(len(g), 0) + 1
    freq_uniform = len(rows_per_combo) == 1

    # 频率严格递增检查
    freq_not_increasing = 0
    for k, g in combos.items():
        fs = [to_float(r[mapping["freq"]]) for r in g]
        if any(a is None or b is None or b <= a for a, b in zip(fs, fs[1:])):
            freq_not_increasing += 1

    # 空值 / NaN / Inf / 不可解析复数
    null_counts = {q: 0 for q in list(ACOUSTIC_PATTERNS) + list(ELECTRICAL_PATTERNS)}
    nan_counts = {q: 0 for q in list(ACOUSTIC_PATTERNS) + list(ELECTRICAL_PATTERNS)}
    inf_counts = {q: 0 for q in list(ACOUSTIC_PATTERNS) + list(ELECTRICAL_PATTERNS)}
    bad_complex_counts = {q: 0 for q in ("Vave", "V_center")}

    def _bump(d: dict, q: str) -> None:
        d[q] = d.get(q, 0) + 1

    for r in rows:
        for q, col in ((q, mapping.get(q)) for q in list(ACOUSTIC_PATTERNS) + list(ELECTRICAL_PATTERNS)):
            if not col:
                continue
            raw = (r.get(col) or "").strip()
            if not raw:
                _bump(null_counts, q)
                continue
            if q in ("Vave", "V_center"):
                c = parse_complex(raw)
                if c is None:
                    _bump(bad_complex_counts, q)
                elif not (math.isfinite(c.real) and math.isfinite(c.imag)):
                    _bump(nan_counts, q)
            else:
                v = to_float(raw)
                if v is None:
                    _bump(bad_complex_counts, q)
                elif math.isnan(v):
                    _bump(nan_counts, q)
                elif math.isinf(v):
                    _bump(inf_counts, q)

    ptot_vals = [to_float(r[mapping["Ptot"]]) for r in rows]
    ptot_vals = [v for v in ptot_vals if v is not None]
    negative_ptot_rows = sum(1 for v in ptot_vals if v < 0)
    zero_ptot_rows = sum(1 for v in ptot_vals if v == 0)

    # Zin1 ≡ Zin2（已知公式缺陷）
    zin_equal_rows = 0
    zin_checked_rows = 0
    if all(k in mapping for k in ("Zin1_R", "Zin1_X", "Zin2_R", "Zin2_X")):
        for r in rows:
            a_r, a_x = to_float(r[mapping["Zin1_R"]]), to_float(r[mapping["Zin1_X"]])
            b_r, b_x = to_float(r[mapping["Zin2_R"]]), to_float(r[mapping["Zin2_X"]])
            if None in (a_r, a_x, b_r, b_x):
                continue
            zin_checked_rows += 1
            if a_r == b_r and a_x == b_x:
                zin_equal_rows += 1

    # 驱动失配
    drive_mismatch_row_count = 0
    declared_drive_values: list[str] = []
    if "drive_mode" in mapping:
        for r in rows:
            v = (r.get(mapping["drive_mode"]) or "").strip()
            declared_drive_values.append(v)
            if normalize_drive(v) != effective:
                drive_mismatch_row_count += 1

    # 反相驱动额外校验：V_outer=+vamp, V_inner=-vamp, |Vdiff|=2
    voltage_check = {"applicable": False}
    if effective == REVERSE_DRIVE_MODE:
        voltage_check = {"applicable": True, "vamp_expected_V": REVERSE_VAMP_V,
                         "Vdiff_expected_V": REVERSE_VDIFF_V,
                         "rows_checked": 0, "rows_voltage_mismatch": 0, "rows_vdiff_mismatch": 0,
                         "tolerance": 1e-6, "note": "反相驱动电位一致性（LT1-C: drive_voltage_mismatch 必须为 0）"}
        for r in rows:
            vo = to_float(r.get(mapping.get("V_outer_re", ""), ""))
            vi = to_float(r.get(mapping.get("V_inner_re", ""), ""))
            vd = to_float(r.get(mapping.get("Vdiff_abs", ""), ""))
            if vo is None or vi is None:
                continue
            voltage_check["rows_checked"] += 1
            if abs(vo - REVERSE_VAMP_V) > 1e-6 or abs(vi + REVERSE_VAMP_V) > 1e-6:
                voltage_check["rows_voltage_mismatch"] += 1
            if vd is not None and abs(vd - REVERSE_VDIFF_V) > 1e-5:
                voltage_check["rows_vdiff_mismatch"] += 1
    else:
        voltage_check = {"applicable": False,
                         "reason": "legacy 导出无 V_outer/V_inner/Vdiff 列 ⇒ 驱动电位一致性不可核验"}

    # 缺失组合（期望网格）
    expected_keys: list[tuple[float, int]] = []
    missing_combo_keys: list[list] = []
    extra_combo_keys: list[list] = []
    if precheck:
        precheck_grid = sorted(precheck)
        present = set(combos)
        missing_combo_keys = [[x, n] for (x, n) in precheck_grid if (x, n) not in present]
        extra_combo_keys = [[x, n] for (x, n) in present if (x, n) not in set(precheck_grid)]
        expected_keys = precheck_grid
    print(f"网格：x_scale {len(xs_sorted)} 档 × N_w_te1 {len(ns_sorted)} 档 × freq {len(freqs_sorted)} 点"
          f" = {len(combos)} 组合 / {len(rows)} 行；重复键 {dup_keys}；缺失组合 {len(missing_combo_keys)}")

    # ============================ 4. 逐组合指标（声学 vs 电气物理分离） ============================
    def metric_row(k: tuple[float, float], g: list[dict]) -> dict:
        x, n = k
        g = sorted(g, key=lambda r: to_float(r[mapping["freq"]]) or 0.0)
        freqs = [to_float(r[mapping["freq"]]) or 0.0 for r in g]
        ptot = [to_float(r[mapping["Ptot"]]) for r in g]
        vave = [None if (c := parse_complex(r.get(mapping["Vave"], ""))) is None else abs(c) for r in g]
        vcent = [None if (c := parse_complex(r.get(mapping.get("V_center", ""), ""))) is None else abs(c) for r in g]

        def pick(values: list, target: float) -> tuple[float | None, bool]:
            """在 target（Hz）处取值：命中采样点则直接返回；否则在相邻点间线性插值（interpolated=True）。"""
            for f, v in zip(freqs, values):
                if abs(f - target) < 1.0:
                    return v, False
            pts = [(f, v) for f, v in zip(freqs, values) if v is not None]
            if len(pts) < 2 or target < pts[0][0] or target > pts[-1][0]:
                return None, False
            for (f0, v0), (f1, v1) in zip(pts, pts[1:]):
                if f0 <= target <= f1 and f1 != f0:
                    frac = (target - f0) / (f1 - f0)
                    return v0 + frac * (v1 - v0), True
            return None, False

        tgt = args.target_mhz * 1e6
        ptot_20, ptot_20_interp = pick(ptot, tgt)
        vave_20, vave_20_interp = pick(vave, tgt)
        vcent_20, _ = pick(vcent, tgt)
        fpk_p = fp_pk = fpk_v = v_pk = None
        if any(v is not None for v in ptot):
            i = max(range(len(ptot)), key=lambda j: (-math.inf if ptot[j] is None else ptot[j]))
            fpk_p, fp_pk = freqs[i] / 1e6, ptot[i]
        if any(v is not None for v in vave):
            i = max(range(len(vave)), key=lambda j: (-math.inf if vave[j] is None else vave[j]))
            fpk_v, v_pk = freqs[i] / 1e6, vave[i]
        cls, elig, reason = classify(k)
        # ---- 归一化：分子来自导出表（simulation），分母来源可能是人反馈（human_feedback）----
        vdiff = None
        denom_source = "unavailable"
        if effective == REVERSE_DRIVE_MODE:
            vdiff, denom_source = REVERSE_VDIFF_V, "simulation"
            if "Vdiff_abs" not in mapping:
                denom_source = "simulation_drive_manifest_constant"
        elif "Vdiff_abs" in mapping:
            vd = [to_float(r.get(mapping["Vdiff_abs"], "")) for r in g]
            vd = [v for v in vd if v is not None]
            vdiff, denom_source = (max(vd) if vd else None), "simulation"
        elif legacy_vdiff is not None:
            vdiff, denom_source = legacy_vdiff["value_V"], LEGACY_VDIFF_SOURCE_TYPE
        ptot_norm = (ptot_20 / (vdiff ** 2)) if (ptot_20 is not None and vdiff) else None
        vave_norm = (vave_20 / vdiff) if (vave_20 is not None and vdiff) else None
        norm_reason = "" if vdiff else LEGACY_VDIFF_NON_COMPUTABLE_REASON

        src_run_ids = sorted({(r.get(mapping.get("source_run_id", "")) or "").strip()
                              for r in g if mapping.get("source_run_id")})
        return {
            # ---- 溯源（每行必带）----
            "source_run_id": args.source_run_id,
            "source_file_sha256": src_sha,
            "source_file": str(src),
            "drive_mode": effective,
            "status": PROVISIONAL_STATUS,
            "formal_ranking": False,
            "artifact_role": "provisional_ranking_only",
            # ---- 键 ----
            "x_scale": x, "N_w_te1": n,
            "frequency_count": len(g),
            # ---- 声学指标（参与排名/Pareto）----
            "Ptot_20MHz_W": ptot_20, "Ptot_20MHz_interpolated": ptot_20_interp,
            "Ptot_peak_W": fp_pk, "f_peak_Ptot_MHz": fpk_p,
            "Vave_20MHz": vave_20, "Vave_20MHz_interpolated": vave_20_interp,
            "Vave_peak": v_pk, "f_peak_Vave_MHz": fpk_v,
            "V_center_20MHz": vcent_20,
            "Ptot_norm_20MHz_W_per_V2": ptot_norm,
            "Vave_norm_20MHz_per_V": vave_norm,
            # ---- 归一化来源分离（红线 4）：分子/分母来源不同，必须分列标注 ----
            "Vdiff_V": vdiff,
            "normalization_numerator_source_type": "simulation",
            "normalization_denominator_source": denom_source,
            "normalization_denominator_feedback_id": legacy_vdiff["feedback_id"] if denom_source == LEGACY_VDIFF_SOURCE_TYPE else "",
            "normalization_denominator_quote": LEGACY_VDIFF_QUOTE if denom_source == LEGACY_VDIFF_SOURCE_TYPE else "",
            "normalization_denominator_evidence_sha256": legacy_vdiff["evidence_sha256"] if denom_source == LEGACY_VDIFF_SOURCE_TYPE else "",
            "normalization_limitation": LEGACY_VDIFF_LIMITATION if denom_source == LEGACY_VDIFF_SOURCE_TYPE else "",
            "normalization_reason": norm_reason,
            # ---- 排除项（物理分离，不参与排名）----
            "electrical_metrics_excluded": True,
            "electrical_metrics_exclusion_reason": ELECTRICAL_EXCLUSION_REASON,
            "excluded_columns_present": ";".join(sorted(c for q, c in mapping.items() if q in ELECTRICAL_PATTERNS)),
            # ---- 排名资格（预检）----
            "precheck_class": cls,
            "eligible_for_ranking": elig,
            "eligibility_reason": reason,
        }

    metrics = [metric_row(k, g) for k, g in sorted(combos.items())]

    # ============================ 4b. 频响形状指标（LT3-B） ============================
    # 频段界：默认 per-combo 自动探测（与参数化前一致）；--band-*-mhz 可显式覆盖
    band_override = {"min": args.band_min_mhz, "max": args.band_max_mhz}
    if band_override["min"] is not None and band_override["max"] is not None \
            and band_override["min"] >= band_override["max"]:
        print(f"[错误] --band-min-mhz ({band_override['min']}) 必须小于 --band-max-mhz ({band_override['max']})")
        return 2
    data_max_mhz = max(freqs_sorted) / 1e6 if freqs_sorted else None
    data_min_mhz = min(freqs_sorted) / 1e6 if freqs_sorted else None
    band_override_exceeds_data = bool(
        (band_override["max"] is not None and data_max_mhz is not None and band_override["max"] > data_max_mhz)
        or (band_override["min"] is not None and data_min_mhz is not None and band_override["min"] < data_min_mhz))
    if band_override_exceeds_data:
        print(f"[!] 频段界覆盖超出数据范围：数据 {data_min_mhz}–{data_max_mhz} MHz，"
              f"给定 {band_override['min']}–{band_override['max']} MHz")
        print("    本脚本**绝不外推**：界外无数据 ⇒ 界外边频仍标 `*_bound_not_found`，不生成任何界外数值。")
    resp_by_key: dict[tuple[float, int], dict] = {}
    for k, g in sorted(combos.items()):
        gg = sorted(g, key=lambda r: to_float(r[mapping["freq"]]) or 0.0)
        fsq = [to_float(r[mapping["freq"]]) or 0.0 for r in gg]
        ppq = [to_float(r[mapping["Ptot"]]) for r in gg]
        vvq = [None if (c := parse_complex(r.get(mapping["Vave"], ""))) is None else abs(c) for r in gg]
        resp_by_key[k] = response_metrics(fsq, ppq, vvq,
                                          band_min_override=band_override["min"],
                                          band_max_override=band_override["max"])

    # 口径一致性核对：metric_row 与 response_metrics 两处**独立**算的峰值/峰位必须一致
    peak_check = {"rows_checked": 0, "peak_value_mismatch": 0, "peak_freq_mismatch": 0,
                  "max_peak_rel_diff": 0.0,
                  "note": "两处独立实现（metric_row vs response_metrics）；不一致即口径分歧，须修而非掩盖"}
    for m in metrics:
        rm = resp_by_key.get((m["x_scale"], m["N_w_te1"]), {})
        for pk, fp, rpk, rfp in (("Ptot_peak_W", "f_peak_Ptot_MHz", "resp_Ptot_peak", "resp_f_peak_Ptot_MHz"),
                                 ("Vave_peak", "f_peak_Vave_MHz", "resp_Vave_peak", "resp_f_peak_Vave_MHz")):
            a, b = m.get(pk), rm.get(rpk)
            if a is None or b is None:
                continue
            peak_check["rows_checked"] += 1
            rel = abs(a - b) / (max(abs(a), abs(b)) or 1.0)
            peak_check["max_peak_rel_diff"] = max(peak_check["max_peak_rel_diff"], rel)
            if rel > 1e-12:
                peak_check["peak_value_mismatch"] += 1
            if m.get(fp) != rm.get(rfp):
                peak_check["peak_freq_mismatch"] += 1
    for m in metrics:
        m.update(resp_by_key.get((m["x_scale"], m["N_w_te1"]), {}))
    response_keys = sorted({kk for rm in resp_by_key.values() for kk in rm if not kk.startswith("resp_")})
    print(f"频响指标：{len(response_keys)} 列 / {len(resp_by_key)} 组合（主插值口径 {PRIMARY_INTERP}）")
    print(f"峰值口径核对：{peak_check['rows_checked']} 项，值不一致 {peak_check['peak_value_mismatch']}，"
          f"峰位不一致 {peak_check['peak_freq_mismatch']}，最大相对差 {peak_check['max_peak_rel_diff']:.3g}")

    # ============================ 5. 守卫 2：反相数据 ⇒ 拒绝排名 ============================
    if effective == REVERSE_DRIVE_MODE:
        inter = [{kk: m[kk] for kk in (
            "source_run_id", "source_file_sha256", "drive_mode", "status", "formal_ranking", "artifact_role",
            "x_scale", "N_w_te1", "Ptot_norm_20MHz_W_per_V2", "Vave_norm_20MHz_per_V",
            "precheck_class", "eligible_for_ranking")} for m in metrics]
        for m in inter:
            m["Vdiff_V"] = REVERSE_VDIFF_V
            m["artifact_role"] = "comparison_intermediate_only__no_ranking"
        write_csv(out_dir / "lt3_intermediate_comparison.csv", inter)
        refusal = {
            "guard": "reverse_drive_formal_ranking_blocked",
            "status": REFUSED_STATUS,
            "formal_ranking": False,
            "drive_mode": effective,
            "reason": "检测到反相驱动数据；LT2 未完全通过（BLOCKED_BEFORE_PRODUCTION）⇒ 拒绝输出任何正式排名/Pareto。",
            "authority": authority_hashes,
            "source_run_id": args.source_run_id,
            "source_file": str(src),
            "source_file_sha256": src_sha,
            "rows": len(rows),
            "combos": len(combos),
            "allowed_outputs": ["lt3_intermediate_comparison.csv（对比用中间量，含归一化量，无排序/无 Pareto）",
                                "lt3_quality_report.json（质检）", "lt3_normalization_contract.md（口径）"],
            "forbidden_outputs": ["lt3_ranking.csv", "lt3_pareto.csv", "lt3_pareto_dominance.csv"],
            "exit_code": 3,
        }
        (out_dir / "lt3_guard_refusal.json").write_text(
            json.dumps(refusal, ensure_ascii=False, indent=2), encoding="utf-8")
        q = build_quality(args, src, src_sha, enc, delim, rows, combos, xs_sorted, ns_sorted, freqs_sorted,
                          rows_per_combo, dup_keys, null_counts, nan_counts, inf_counts, bad_complex_counts,
                          negative_ptot_rows, zero_ptot_rows, zin_equal_rows, zin_checked_rows,
                          freq_not_increasing, drive, drive_mismatch_row_count, declared_drive_values,
                          voltage_check, precheck, precheck_src, precheck_sha, missing_combo_keys,
                          extra_combo_keys, authority_hashes, copied, mapping, header, hi)
        q["freq_unit_normalization"] = freq_unit_norm
        (out_dir / "lt3_quality_report.json").write_text(
            json.dumps(q, ensure_ascii=False, indent=2), encoding="utf-8")
        write_csv(out_dir / "lt3_metrics.csv", metrics)
        (out_dir / "lt3_normalization_contract.md").write_text(
            render_contract(normalization_contract(legacy_vdiff), args, src, src_sha, effective, refused=True),
            encoding="utf-8")
        write_manifest(out_dir, args, src, src_sha)
        print(f"\n[fail-closed] 反相驱动数据 ⇒ 已拒绝输出排名/Pareto（exit 3）。")
        print(f"  仅输出对比用中间量：{out_dir / 'lt3_intermediate_comparison.csv'}")
        return 3

    # ============================ 6. Pareto（两个声学指标，仅 eligible 子集） ============================
    wanted = [s.strip() for s in args.pareto_metrics.split(",") if s.strip()]
    if len(wanted) != 2:
        print(f"[错误] --pareto-metrics 必须恰好两个声学指标，收到 {wanted}")
        return 2
    for w in wanted:
        if w.startswith("Zin") or w.startswith("I_"):
            print(f"[错误] {w} 属被排除的电气指标（{ELECTRICAL_EXCLUSION_REASON}）⇒ 不得参与排名/Pareto")
            return 2

    pool = [m for m in metrics if m["eligible_for_ranking"]]
    excluded_ineligible = len(metrics) - len(pool)
    pts: dict[tuple[float, int], list[float]] = {}
    for m in pool:
        vals = [m.get(w) for w in wanted]
        if any(v is None for v in vals):
            continue
        pts[(m["x_scale"], m["N_w_te1"])] = [float(v) for v in vals]

    dom_pairs: list[dict] = []
    pareto_keys: list[tuple[float, int]] = []
    dom_count: dict[tuple[float, int], int] = {k: 0 for k in pts}
    dom_by: dict[tuple[float, int], list[str]] = {k: [] for k in pts}
    for a in pts:
        for b in pts:
            if a == b:
                continue
            ge = all(pts[b][i] >= pts[a][i] for i in range(2))
            gt = any(pts[b][i] > pts[a][i] for i in range(2))
            if ge and gt:
                dom_count[a] += 1
                dom_by[a].append(f"x={b[0]:g},N={b[1]}")
                dom_pairs.append({"x_scale": a[0], "N_w_te1": a[1],
                                  wanted[0]: pts[a][0], wanted[1]: pts[a][1],
                                  "dominated_by_x_scale": b[0], "dominated_by_N_w_te1": b[1],
                                  "dominated_by_metric_0": pts[b][0], "dominated_by_metric_1": pts[b][1],
                                  "metric_0": wanted[0], "metric_1": wanted[1],
                                  "source_run_id": args.source_run_id, "source_file_sha256": src_sha,
                                  "drive_mode": effective, "status": PROVISIONAL_STATUS, "formal_ranking": False})
    for k in pts:
        if dom_count[k] == 0:
            pareto_keys.append(k)

    pareto_rows = []
    for m in metrics:
        k = (m["x_scale"], m["N_w_te1"])
        row = dict(m)
        row["pareto_metrics"] = ";".join(wanted)
        row["metric_0_value"] = pts[k][0] if k in pts else None
        row["metric_1_value"] = pts[k][1] if k in pts else None
        row["pareto_front"] = k in pareto_keys
        row["dominated_by_count"] = dom_count.get(k)
        row["dominated_by"] = ";".join(dom_by.get(k, [])) if k in pts else ""
        row["pareto_exclusion_reason"] = ("" if k in pts else
                                          ("not_eligible_for_ranking" if not m["eligible_for_ranking"]
                                           else "missing_pareto_metric_value"))
        pareto_rows.append(row)

    write_csv(out_dir / "lt3_metrics.csv", metrics)
    write_csv(out_dir / "lt3_pareto.csv", pareto_rows)
    write_csv(out_dir / "lt3_pareto_dominance.csv", dom_pairs if dom_pairs else
              [{"note": "无可比较的支配对（被支配关系为空）", "source_run_id": args.source_run_id,
                "source_file_sha256": src_sha, "drive_mode": effective,
                "status": PROVISIONAL_STATUS, "formal_ranking": False}])

    # ---- 多指标排名表（**不做加权总分**；只给各声学指标在 eligible 子集内的名次）----
    rank_metrics = ["Ptot_20MHz_W", "Vave_20MHz", "Ptot_peak_W", "Vave_peak"]
    rank_metrics = [k for k in rank_metrics if any(m.get(k) is not None for m in pool)]
    ranks: dict[str, dict[tuple[float, int], int]] = {}
    for mk in rank_metrics:
        vals = sorted(((m[mk], (m["x_scale"], m["N_w_te1"])) for m in pool if m.get(mk) is not None),
                      key=lambda t: -t[0])
        r: dict[tuple[float, int], int] = {}
        for i, (_, key) in enumerate(vals, start=1):
            r[key] = i
        ranks[mk] = r
    ranking_rows = []
    for m in pool:
        k = (m["x_scale"], m["N_w_te1"])
        row = {"source_run_id": args.source_run_id, "source_file_sha256": src_sha,
               "drive_mode": effective, "status": PROVISIONAL_STATUS, "formal_ranking": False,
               "x_scale": k[0], "N_w_te1": k[1], "precheck_class": m["precheck_class"],
               "eligible_for_ranking": m["eligible_for_ranking"],
               "pareto_front": k in pareto_keys, "dominated_by_count": dom_count.get(k)}
        for mk in rank_metrics:
            row[mk] = m.get(mk)
            row[f"rank_{mk}"] = ranks[mk].get(k)
        ranking_rows.append(row)
    sort_key = [f"rank_{mk}" for mk in rank_metrics]
    ranking_rows.sort(key=lambda r: tuple(r[s] if r[s] is not None else 10 ** 9 for s in sort_key))
    for i, row in enumerate(ranking_rows, start=1):
        row["row_order"] = i
    write_csv(out_dir / "lt3_ranking.csv", ranking_rows)
    q_rank_note = ("多指标名次表：每个声学指标独立排名，**不合成加权总分**（sweep-analysis SOP §4）；"
                   f"排序仅按 {sort_key} 依次排列，不代表优劣综合结论")

    q = build_quality(args, src, src_sha, enc, delim, rows, combos, xs_sorted, ns_sorted, freqs_sorted,
                      rows_per_combo, dup_keys, null_counts, nan_counts, inf_counts, bad_complex_counts,
                      negative_ptot_rows, zero_ptot_rows, zin_equal_rows, zin_checked_rows,
                      freq_not_increasing, drive, drive_mismatch_row_count, declared_drive_values,
                      voltage_check, precheck, precheck_src, precheck_sha, missing_combo_keys,
                      extra_combo_keys, authority_hashes, copied, mapping, header, hi)
    q["pareto"] = {
        "metrics": wanted,
        "directions": ["maximize", "maximize"],
        "n_eligible": len(pool),
        "n_ineligible_excluded": excluded_ineligible,
        "n_with_both_metrics": len(pts),
        "n_pareto_front": len(pareto_keys),
        "n_dominated": len(pts) - len(pareto_keys),
        "n_dominance_pairs": len(dom_pairs),
        "pareto_front_keys": [[k[0], k[1]] for k in sorted(pareto_keys)],
        "note": "只在预检 eligible 子集内计算；不做无依据加权总分（sweep-analysis SOP §4）",
    }
    q["ranking_table"] = {
        "file": "lt3_ranking.csv",
        "metrics": rank_metrics,
        "n_rows": len(ranking_rows),
        "directions": "全部 maximize（名次 1 = 该指标最大）",
        "composite_score": False,
        "note": q_rank_note,
    }
    # ---- LT3-B：频响指标专表 + 指标对 Pareto（含退化如实报告）----
    resp_out = []
    for m in metrics:
        row = {kk: m[kk] for kk in ("source_run_id", "source_file_sha256", "drive_mode", "status",
                                    "formal_ranking", "x_scale", "N_w_te1", "precheck_class",
                                    "eligible_for_ranking")}
        row.update({kk: m.get(kk) for kk in response_keys})
        # 峰值/峰位的**权威列**（由 metric_row 产出）+ 独立复算列（供口径一致性审计）
        for extra in ("Ptot_peak_W", "f_peak_Ptot_MHz", "Vave_peak", "f_peak_Vave_MHz",
                      "resp_Ptot_peak", "resp_f_peak_Ptot_MHz", "resp_Vave_peak", "resp_f_peak_Vave_MHz"):
            row[extra] = m.get(extra)
        resp_out.append(row)
    write_csv(out_dir / "lt3_response_metrics.csv", resp_out)

    pair_rows, pair_summary = pareto_pairs(metrics, PARETO_PAIRS)
    write_csv(out_dir / "lt3_pareto_pairs.csv", pair_rows)

    resp_summ = response_summary(metrics, freqs_sorted)
    # ---- 频段界登记（参数化）+ data gap 登记 ----
    _bsrc = "cli" if (band_override["min"] is not None or band_override["max"] is not None) else "auto_detected"
    resp_summ["band"] = {
        "band_min_MHz": (band_override["min"] if band_override["min"] is not None else data_min_mhz),
        "band_max_MHz": (band_override["max"] if band_override["max"] is not None else data_max_mhz),
        "band_source": _bsrc,
        "band_cli_override": {"min": band_override["min"], "max": band_override["max"]},
        "auto_detected_band_MHz": [data_min_mhz, data_max_mhz],
        "override_exceeds_data_range": band_override_exceeds_data,
        "no_extrapolation": True,
        "note": ("默认 band_source = auto_detected（从输入数据频点集合探测，与参数化前口径逐位一致）；"
                 "显式给 --band-min-mhz/--band-max-mhz 时 band_source = cli。"
                 "任何情况下都**不外推**：界外无数据即标 `*_bound_not_found`，不生成界外数值。"),
    }
    resp_summ["frequency_domain_coverage"] = {
        "input_freq_set_MHz": [round(f / 1e6, 6) for f in freqs_sorted],
        "input_freq_points": len(freqs_sorted),
        "input_freq_min_MHz": data_min_mhz, "input_freq_max_MHz": data_max_mhz,
        "data_gap_45MHz": {
            "status": "DATA_ABSENT",
            "statement": "**45 MHz 计算数据当前不存在**（本批输入频段仅到 35 MHz）。",
            "evidence_file": "work/lt3/lt3_45mhz_data_gap.json",
            "evidence_note": "全仓结果表扫描：3140 张表，频率最大值 >36 MHz 的表 **0** 张；"
                             "最大值恰为 35 MHz（批次2 导出与 gui-sweep 源表）。"
                             "45 MHz 仅出现在**精扫计划/口径文档**（`5–45 MHz @0.5 MHz = 81 点`），"
                             "**不是已算数据**。",
            "policy": "本轮**不跑 COMSOL、不改 fmax、不生成任何 45 MHz 数值、不推测 45 MHz 带宽**。",
        },
    }

    (out_dir / "lt3_response_metrics_contract.md").write_text(
        render_response_contract(resp_summ, metrics), encoding="utf-8")

    q["response_metrics"] = resp_summ
    q["response_metrics"]["peak_caliber_consistency_check"] = peak_check
    q["pareto_pairs"] = pair_summary

    # ---- LT3-D：legacy vs 反相**归一化**并排对照（来源不同 ⇒ 只能并排，不得合并）----
    q["freq_unit_normalization"] = freq_unit_norm
    compare_info = {"produced": False, "reason": "未提供 --compare-reverse"}
    if args.compare_reverse:
        compare_info = build_comparison(args, src, src_sha, rows, mapping, effective,
                                        legacy_vdiff, out_dir, precheck)
        q["legacy_vs_reverse_normalized"] = compare_info
    q["normalization_source_separation"] = {
        "numerator": {"quantities": ["Ptot", "Vave"], "source_type": "simulation",
                      "origin": "COMSOL 导出表", "source_file_sha256": src_sha},
        "denominator_legacy": ({"quantity": "abs(Vdiff)", "value_V": legacy_vdiff["value_V"],
                                "source_type": LEGACY_VDIFF_SOURCE_TYPE,
                                "feedback_id": legacy_vdiff["feedback_id"],
                                "evidence_file": legacy_vdiff["evidence_file"],
                                "evidence_sha256": legacy_vdiff["evidence_sha256"],
                                "quote": LEGACY_VDIFF_QUOTE,
                                "limitation": LEGACY_VDIFF_LIMITATION,
                                "must_not_be_described_as": "由模型或导出表得到"}
                               if legacy_vdiff else
                               {"quantity": "abs(Vdiff)", "value_V": None, "source_type": "unavailable",
                                "reason": LEGACY_VDIFF_NON_COMPUTABLE_REASON}),
        "denominator_reverse": {"quantity": "abs(Vdiff)", "value_V": REVERSE_VDIFF_V, "source_type": "simulation"},
        "note": "归一化量是**混合来源**（分子 simulation + 分母 human_feedback）；声明混用是红线 4 的强制要求",
    }
    (out_dir / "lt3_quality_report.json").write_text(json.dumps(q, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "lt3_ranking_status.json").write_text(json.dumps({
        "status": PROVISIONAL_STATUS,
        "formal_ranking": False,
        "formal_ranking_authorized": FORMAL_RANKING_AUTHORIZED,
        "drive_mode": effective,
        "drive_mode_declared": drive["declared"],
        "drive_mode_inferred": drive["inferred"],
        "authority": authority_hashes,
        "authority_note": "LT2 未完全通过 ⇒ 不得制作『正式反相粗扫排名』（LT0-LT3 工单 §4；LT2 后继令 §7）",
        "source_run_id": args.source_run_id,
        "source_file": str(src),
        "source_file_sha256": src_sha,
        "rows": len(rows),
        "combos": len(combos),
        "ranking_scope": "precheck eligible subset only",
        "n_ranked": len(pts),
        "n_pareto_front": len(pareto_keys),
        "excluded_metrics": sorted(ELECTRICAL_PATTERNS),
        "excluded_reason": ELECTRICAL_EXCLUSION_REASON,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "lt3_normalization_contract.md").write_text(
        render_contract(normalization_contract(legacy_vdiff), args, src, src_sha, effective, refused=False),
        encoding="utf-8")
    write_manifest(out_dir, args, src, src_sha)

    print(f"\n结果：eligible {len(pool)}/{len(metrics)}；可算两指标 {len(pts)}")
    print(f"      Pareto 前沿 {len(pareto_keys)} 个；被支配 {len(pts) - len(pareto_keys)} 个；支配对 {len(dom_pairs)}")
    print(f"      状态：{PROVISIONAL_STATUS}（formal_ranking=False）")
    print(f"产物：{out_dir.resolve()}")
    return 0


# ---------------------------------------------------------------- LT3-D 并排对照
COMPARE_STATUS = "provisional_legacy_vs_reverse_normalized_not_formal"
COMPARE_NOTE = ("原始 Ptot/Vave 的约 4 倍差 = 驱动电压所致（4 = 2^2：反相 |Vdiff|=2 V vs legacy |Vdiff|=1 V）；"
                "归一化后才可并排。两批 model_sha256 不同 ⇒ 只能并排对照，不得合并成同一来源的统计。")


def _read_table_auto(path: Path) -> tuple[list[dict], dict, str, str, dict]:
    """读任意导出表 → (行, 列映射, 编码, 分隔符, 频率单位归一信息)。频率列已归一到 Hz。"""
    grid, enc, delim = read_grid(path)
    hi = locate_header(grid)
    header = [c.strip().lstrip("% ").strip() for c in grid[hi]]
    mp = map_columns(header)
    # 补充**字面列名**映射（map_columns 的关键词规则不覆盖这些列）
    for extra in ("model_sha256", "script_sha256", "Ptot_norm", "Vave_norm",
                  "invariant_criteria_hash", "sweep_spec_hash"):
        col = _direct_col(header, extra)
        if col and extra not in mp:
            mp[extra] = col
    rr = [dict(zip(header, r)) for r in grid[hi + 1:] if len(r) >= len(header) and r[0].strip()]
    if "freq" in mp:
        fun = normalize_freq_column(rr, mp["freq"])
    else:
        fun = {"column": None, "scale_applied_to_hz": 1.0, "method": "freq_column_absent",
               "heuristic_assumption": False}
    return rr, mp, enc, delim, fun


def _direct_col(header_or_map, name: str) -> str | None:
    """按**字面列名**（忽略大小写与空格）查列，用于 map_columns 未覆盖的列（如 model_sha256）。"""
    if isinstance(header_or_map, dict):
        cands = list(header_or_map.values())
    else:
        cands = list(header_or_map)
    target = re.sub(r"[\s_-]", "", name).lower()
    for col in cands:
        if re.sub(r"[\s_-]", "", str(col)).lower() == target:
            return col
    return None


def build_comparison(args, src: Path, src_sha: str, legacy_rows: list[dict], legacy_mapping: dict,
                     legacy_drive: str, legacy_vdiff: dict | None, out_dir: Path,
                     precheck: dict) -> dict:
    """产出 `legacy_vs_reverse_normalized.csv`：两批归一化量并排（**不合并统计**）。

    - 分子 `Ptot`/`Vave`：两批均来自各自导出表（`source_type = simulation`）；
    - 分母 legacy 来自**人反馈**（`source_type = human_feedback`），反相来自导出/manifest；
    - 状态恒为 `provisional_legacy_vs_reverse_normalized_not_formal`，`formal_ranking = False`。
    """
    rev_path = Path(args.compare_reverse)
    if not rev_path.is_file():
        return {"produced": False, "reason": f"--compare-reverse 不存在：{rev_path}"}

    rev_rows, rev_map, rev_enc, rev_delim, rev_freqnorm = _read_table_auto(rev_path)
    rev_keys = {k for k in ("x_scale", "N_w_te1", "freq", "Ptot", "Vave") if k in rev_map}
    if not {"x_scale", "N_w_te1", "freq", "Ptot", "Vave"} <= rev_keys:
        return {"produced": False, "reason": f"反相表列不足：{sorted(rev_keys)}（表头 {list(rev_map)}）"}
    rev_sha = sha256_file(rev_path)

    # 守卫：反相侧必须真的是反相驱动（若有 drive_mode 列，逐个核验）
    rev_drive_vals = sorted({(r.get(rev_map.get("drive_mode", "")) or "").strip()
                             for r in rev_rows if rev_map.get("drive_mode")})
    rev_drive_vals = [v for v in rev_drive_vals if v]
    if rev_drive_vals and any(normalize_drive(v) != REVERSE_DRIVE_MODE for v in rev_drive_vals):
        return {"produced": False,
                "reason": f"反相表内含非反相驱动行：{rev_drive_vals} ⇒ fail-closed，不出对照表"}

    # 反相 |Vdiff|：优先用导出列，缺失则退到反相标称 2 V
    rev_vdiff_col = rev_map.get("Vdiff_abs")
    rev_vd_vals = []
    if rev_vdiff_col:
        rev_vd_vals = [v for v in (to_float(r.get(rev_vdiff_col, "")) for r in rev_rows) if v is not None]
    rev_vdiff = max(rev_vd_vals) if rev_vd_vals else REVERSE_VDIFF_V
    rev_vdiff_source = "simulation_export_column_Vdiff_abs" if rev_vd_vals else "drive_manifest_constant_2V"

    # legacy 侧模型 sha256（证据：预检聚合 manifest 的 source_model_sha256）
    legacy_model_sha = ""
    agg_manifest = Path(args.precheck).parent / "aggregate_manifest.json" if args.precheck else None
    if agg_manifest and agg_manifest.is_file():
        try:
            legacy_model_sha = json.loads(agg_manifest.read_text(encoding="utf-8")).get("source_model_sha256", "") or ""
        except Exception:
            legacy_model_sha = ""
    rev_model_sha_col = _direct_col(list(rev_map.values()), "model_sha256") or rev_map.get("model_sha256")
    rev_model_sha = sorted({(r.get(rev_model_sha_col, "") or "").strip()
                            for r in rev_rows if rev_model_sha_col})
    rev_model_sha = [v for v in rev_model_sha if v]
    rev_model_sha_s = rev_model_sha[0] if len(rev_model_sha) == 1 else (";".join(rev_model_sha) or "")

    # legacy 行索引：(x, N1, freq_Hz)
    legacy_idx: dict[tuple[float, int, float], dict] = {}
    for r in legacy_rows:
        x, n, f = to_float(r[legacy_mapping["x_scale"]]), to_float(r[legacy_mapping["N_w_te1"]]), to_float(r[legacy_mapping["freq"]])
        if None in (x, n, f):
            continue
        legacy_idx[(round(x, 6), int(n), round(f, 3))] = r

    out: list[dict] = []
    unmatched: list[dict] = []
    n_norm_checked = n_norm_mismatch = 0
    for r in sorted(rev_rows, key=lambda r: (float(r[rev_map["x_scale"]]), int(float(r[rev_map["N_w_te1"]])),
                                             float(r[rev_map["freq"]]))):
        x, n, f = to_float(r[rev_map["x_scale"]]), to_float(r[rev_map["N_w_te1"]]), to_float(r[rev_map["freq"]])
        if None in (x, n, f):
            continue
        ni = int(n)
        lr = legacy_idx.get((round(x, 6), ni, round(f, 3)))
        rev_ptot = to_float(r[rev_map["Ptot"]])
        rev_vave = None if (c := parse_complex(r.get(rev_map["Vave"], ""))) is None else abs(c)
        # 与反相表自带 Ptot_norm/Vave_norm 交叉核对（若存在）
        if "Ptot_norm" in rev_map and rev_ptot is not None:
            given = to_float(r.get(rev_map["Ptot_norm"], ""))
            if given is not None:
                n_norm_checked += 1
                if abs(given - rev_ptot / rev_vdiff ** 2) > 1e-12 * max(1.0, abs(given)):
                    n_norm_mismatch += 1
        row = {
            "source_run_id_legacy": args.source_run_id,
            "source_file_sha256_legacy": src_sha,
            "source_run_id_reverse": (r.get(rev_map.get("source_run_id", "")) or "").strip() or rev_path.stem,
            "source_file_sha256_reverse": rev_sha,
            "x_scale": x, "N_w_te1": ni, "freq_MHz": f / 1e6,
            "legacy_drive_mode": legacy_drive,
            "reverse_drive_mode": REVERSE_DRIVE_MODE,
            "status": COMPARE_STATUS,
            "formal_ranking": False,
            "artifact_role": "diagnostic_intermediate_not_a_ranking",
            # ---- 来源分离（红线 4）----
            "normalization_numerator_source_type": "simulation",
            "normalization_denominator_source_legacy": (LEGACY_VDIFF_SOURCE_TYPE if legacy_vdiff else "unavailable"),
            "normalization_denominator_source_reverse": rev_vdiff_source,
            "normalization_denominator_feedback_id": legacy_vdiff["feedback_id"] if legacy_vdiff else "",
            "normalization_denominator_quote": LEGACY_VDIFF_QUOTE if legacy_vdiff else "",
            "normalization_denominator_evidence_sha256": legacy_vdiff["evidence_sha256"] if legacy_vdiff else "",
            "normalization_limitation": LEGACY_VDIFF_LIMITATION if legacy_vdiff else "",
            # ---- 分母 ----
            "legacy_Vdiff_V": legacy_vdiff["value_V"] if legacy_vdiff else None,
            "reverse_Vdiff_V": rev_vdiff,
            # ---- 反相侧 ----
            "reverse_Ptot_W": rev_ptot,
            "reverse_Ptot_norm_W_per_V2": None if rev_ptot is None else rev_ptot / rev_vdiff ** 2,
            "reverse_Vave_mps": rev_vave,
            "reverse_Vave_norm_per_V": None if rev_vave is None else rev_vave / rev_vdiff,
            # ---- legacy 侧 ----
            "legacy_Ptot_W": None, "legacy_Ptot_norm_W_per_V2": None,
            "legacy_Vave_mps": None, "legacy_Vave_norm_per_V": None,
            "legacy_precheck_class": "", "legacy_model_sha256": legacy_model_sha,
            "reverse_model_sha256": rev_model_sha_s,
            # ---- 可比性前提（逐条）----
            "precondition_control_surface_intop5_eq_swr1": None,
            "precondition_control_surface_intop5_eq_efc1": None,
            "precondition_control_surface_area_bbox_unique": None,
            "precondition_mesh_fmax_same_35MHz": "declared_not_independently_verified",
            "precondition_geometry_family_comparable": "declared_same_device_family_not_independently_verified",
            "precondition_model_sha256_differ": (bool(legacy_model_sha and rev_model_sha_s
                                                      and legacy_model_sha != rev_model_sha_s)
                                                 if (legacy_model_sha and rev_model_sha_s) else None),
            "comparability_note": COMPARE_NOTE,
        }
        if lr is None:
            unmatched.append({"x_scale": x, "N_w_te1": ni, "freq_MHz": f / 1e6,
                              "why": "legacy 批次2 中无此 (x_scale, N_w_te1, freq) 行"})
        else:
            lp = to_float(lr[legacy_mapping["Ptot"]])
            lv = None if (c := parse_complex(lr.get(legacy_mapping["Vave"], ""))) is None else abs(c)
            row["legacy_Ptot_W"] = lp
            row["legacy_Vave_mps"] = lv
            if legacy_vdiff:
                lvd = legacy_vdiff["value_V"]
                row["legacy_Ptot_norm_W_per_V2"] = None if lp is None else lp / lvd ** 2
                row["legacy_Vave_norm_per_V"] = None if lv is None else lv / lvd
            cls = precheck.get((round(x, 6), int(n)))
            if cls:
                row["legacy_precheck_class"] = str(cls.get("classification") or cls.get("eligibility_level") or "")
                row["precondition_control_surface_intop5_eq_swr1"] = cls.get("intop5_eq_swr1")
                row["precondition_control_surface_intop5_eq_efc1"] = cls.get("intop5_eq_efc1")
                bb = cls.get("ptot_boundary_bounding_box")
                row["precondition_control_surface_area_bbox_unique"] = ("single_value_in_aggregate" if bb else None)
        # 比值
        for tag, lk, rk in (("raw_Ptot", "legacy_Ptot_W", "reverse_Ptot_W"),
                            ("raw_Vave", "legacy_Vave_mps", "reverse_Vave_mps"),
                            ("norm_Ptot", "legacy_Ptot_norm_W_per_V2", "reverse_Ptot_norm_W_per_V2"),
                            ("norm_Vave", "legacy_Vave_norm_per_V", "reverse_Vave_norm_per_V")):
            a, b = row.get(lk), row.get(rk)
            row[f"ratio_{tag}"] = (b / a) if (a not in (None, 0) and b is not None) else None
        out.append(row)

    write_csv(out_dir / "legacy_vs_reverse_normalized.csv", out)
    ratios_np = [r["ratio_norm_Ptot"] for r in out if r["ratio_norm_Ptot"] is not None]
    ratios_nv = [r["ratio_norm_Vave"] for r in out if r["ratio_norm_Vave"] is not None]
    raw_p = [r["ratio_raw_Ptot"] for r in out if r["ratio_raw_Ptot"] is not None]
    info = {
        "produced": True,
        "file": "legacy_vs_reverse_normalized.csv",
        "status": COMPARE_STATUS,
        "formal_ranking": False,
        "artifact_role": "diagnostic_intermediate_not_a_ranking",
        "n_rows": len(out),
        "n_combos": len({(r["x_scale"], r["N_w_te1"]) for r in out}),
        "freqs_MHz": sorted({r["freq_MHz"] for r in out}),
        "reverse_source_file": str(rev_path.resolve()),
        "reverse_source_file_sha256": sha256_file(rev_path),
        "reverse_rows_total": len(rev_rows),
        "reverse_encoding": rev_enc, "reverse_delimiter": rev_delim,
        "reverse_freq_unit_normalization": rev_freqnorm,
        "unmatched_reverse_rows": unmatched,
        "legacy_model_sha256": legacy_model_sha,
        "reverse_model_sha256": rev_model_sha_s,
        "reverse_internal_norm_consistency": {"rows_checked": n_norm_checked, "rows_mismatch": n_norm_mismatch},
        "ratio_norm_Ptot_range": [min(ratios_np), max(ratios_np)] if ratios_np else None,
        "ratio_norm_Vave_range": [min(ratios_nv), max(ratios_nv)] if ratios_nv else None,
        "ratio_raw_Ptot_range": [min(raw_p), max(raw_p)] if raw_p else None,
        "scope_warning": ("**示范性对照**：反相侧目前只有 lt1-reverse-sample 的 "
                          f"{len(rev_rows)} 点（{len({(r['x_scale'], r['N_w_te1']) for r in out})} 组合 × "
                          f"{len({r['freq_MHz'] for r in out})} 频点），LT2 的 504 点尚不存在 ⇒ "
                          "本表只证明管线与口径可用，**不构成完整反相 vs legacy 对比**"),
        "note": COMPARE_NOTE,
    }
    (out_dir / "lt3_legacy_vs_reverse_normalized.md").write_text(
        render_comparison_md(info, out, legacy_vdiff), encoding="utf-8")
    print(f"\n[LT3-D] 对照表 {info['n_rows']} 行（{info['n_combos']} 组合 × {len(info['freqs_MHz'])} 频点）"
          f"｜status={COMPARE_STATUS}｜formal_ranking=False")
    if raw_p:
        print(f"        原始 Ptot 比值范围 {min(raw_p):.4g}–{max(raw_p):.4g}（≈4 = 2^2，驱动电压所致，不是结构收益）")
    return info


def render_comparison_md(info: dict, rows: list[dict], legacy_vdiff: dict | None) -> str:
    L = ["# legacy vs 反相 归一化并排对照（LT3-D，**诊断性中间产物**）", ""]
    L.append(f"- 状态：`{COMPARE_STATUS}`｜`formal_ranking = false`｜角色：`{info['artifact_role']}`")
    L.append(f"- ⚠️ **仍不得制作正式反相排名**（LT2 未通过，`BLOCKED_BEFORE_PRODUCTION`）。")
    L.append(f"- 反相侧来源：`{info['reverse_source_file']}`（sha256 `{info['reverse_source_file_sha256']}`，"
             f"{info['reverse_rows_total']} 行）")
    L.append(f"- legacy 侧来源：见 `lt3_quality_report.json` 的 `source_file_sha256`")
    L.append("")
    L.append("## 1. 来源分离（红线 4，**必须如此表述**）")
    L.append("")
    L.append("| 组成 | 来源 `source_type` | 说明 |")
    L.append("|---|---|---|")
    L.append("| 分子 `Ptot`/`Vave` | `simulation` | 两批各自的 COMSOL 导出表列 |")
    if legacy_vdiff:
        L.append(f"| 分母 legacy `abs(Vdiff)` = {legacy_vdiff['value_V']} V | "
                 f"**`human_feedback`** | `feedback_id = {legacy_vdiff['feedback_id']}`；"
                 f"依据 `{Path(legacy_vdiff['evidence_file']).name}` "
                 f"sha256 `{legacy_vdiff['evidence_sha256']}` |")
    else:
        L.append("| 分母 legacy `abs(Vdiff)` | 不可用 | 未提供人反馈值 ⇒ legacy 归一化不可计算 |")
    L.append(f"| 分母反相 `abs(Vdiff)` = {REVERSE_VDIFF_V} V | `simulation` | 反相导出 `Vdiff_abs` 列 / drive manifest |")
    L.append("")
    L.append("> 归一化量是**混合来源**（分子 simulation + 分母 human_feedback）。")
    L.append("> **不得**把 legacy 的归一化量写成「由模型或导出表得到」——导出表里没有电位列（已实测），")
    L.append("> 该分母来自人反馈；若写成导出/模型来源，即为来源混同。")
    L.append("")
    L.append("## 2. 用户原话")
    L.append("")
    L.append(f"> {LEGACY_VDIFF_QUOTE}")
    L.append("")
    L.append("## 3. 必须保留的限制（不得省略）")
    L.append("")
    L.append(f"{LEGACY_VDIFF_LIMITATION}")
    L.append("")
    L.append("## 4. 为什么原始量不可直接比较")
    L.append("")
    L.append(f"- {COMPARE_NOTE}")
    if info.get("ratio_raw_Ptot_range"):
        r = info["ratio_raw_Ptot_range"]
        L.append(f"- 本表实测原始 `Ptot` 比值范围：**{r[0]:.4g} – {r[1]:.4g}**（理论 ~4 = 2²）。")
    L.append(f"- 归一化后 `Ptot_norm` 比值范围：{info.get('ratio_norm_Ptot_range')}")
    L.append(f"- 归一化后 `Vave_norm` 比值范围：{info.get('ratio_norm_Vave_range')}")
    L.append("")
    rn = info.get("ratio_norm_Ptot_range")
    if rn and not (0.9 <= rn[0] and rn[1] <= 1.1):
        L.append("> **重要观察（不得省略）**：归一化后两批**并不可比到一致**——`Ptot_norm` 比值仍跨 "
                 f"{rn[0]:.3g}–{rn[1]:.3g}（非 1），`Vave_norm` 比值跨 "
                 f"{(info.get('ratio_norm_Vave_range') or [float('nan')])[0]:.3g}–"
                 f"{(info.get('ratio_norm_Vave_range') or [float('nan'), float('nan')])[1]:.3g}。")
        L.append("> 归一化只消去了**驱动电压因子**（理论 4 = 2²）；**残余偏差来自两批的模型/选择/网格差异**"
                 "（`model_sha256` 不同）。")
        L.append("> ⇒ **不得**把归一化后的差异解读为结构收益或结构劣势；本表只能说明『电压口径已对齐』，"
                 "不能说明『两批物理一致』。")
        L.append("> 另外，原始 `Ptot` 比值本身也不恒为 4（本表实测 "
                 f"{(info.get('ratio_raw_Ptot_range') or [float('nan')])[0]:.3g}–"
                 f"{(info.get('ratio_raw_Ptot_range') or [float('nan'), float('nan')])[1]:.3g}），"
                 "说明两批差异并非纯电压缩放。")
        L.append("")
    L.append("## 5. 可比性前提（逐条）")
    L.append("")
    L.append("| 前提 | 状态 |")
    L.append("|---|---|")
    L.append("| 控制面同一（`intop5==swr1==efc1`） | 逐行见 CSV 的 `precondition_control_surface_*`（来自 level-2 预检聚合） |")
    L.append("| `area_ptot`/bbox 唯一 | 见 CSV（聚合 manifest：`area_ptot` 唯一值 1 个、bbox 唯一 1 个） |")
    L.append("| 网格上界同一（`fmax = 35 MHz`） | `declared_not_independently_verified`（本脚本未独立核验网格） |")
    L.append("| 几何族可比 | `declared_same_device_family_not_independently_verified` |")
    L.append(f"| `model_sha256` 不同 | legacy `{info.get('legacy_model_sha256') or '(未取到)'}` vs "
             f"反相 `{info.get('reverse_model_sha256') or '(未取到)'}` ⇒ 只能并排，**不得合并统计** |")
    L.append("")
    L.append("## 6. 对照范围（**不是完整对比**）")
    L.append("")
    L.append(f"- {info['scope_warning']}")
    L.append("")
    if info.get("unmatched_reverse_rows"):
        L.append("### 反相侧未能在 legacy 批次2 中匹配的行")
        L.append("")
        for u in info["unmatched_reverse_rows"]:
            L.append(f"- x={u['x_scale']:g}, N1={u['N_w_te1']}, f={u['freq_MHz']:g} MHz —— {u['why']}")
        L.append("")
    L.append("## 7. 归一化量（全表）")
    L.append("")
    L.append("| x_scale | N1 | f (MHz) | legacy Ptot_norm (W/V²) | reverse Ptot_norm (W/V²) | "
             "legacy Vave_norm ((m/s)/V) | reverse Vave_norm ((m/s)/V) | 原始 Ptot 比 |")
    L.append("|---|---|---|---|---|---|---|---|")
    for r in rows:
        def fmt(v, p=6):
            return "—" if v is None else f"{v:.{p}g}"
        L.append(f"| {r['x_scale']:g} | {r['N_w_te1']} | {r['freq_MHz']:g} | "
                 f"{fmt(r['legacy_Ptot_norm_W_per_V2'])} | {fmt(r['reverse_Ptot_norm_W_per_V2'])} | "
                 f"{fmt(r['legacy_Vave_norm_per_V'])} | {fmt(r['reverse_Vave_norm_per_V'])} | "
                 f"{fmt(r['ratio_raw_Ptot'], 4)} |")
    L.append("")
    L.append("> 5 MHz 间隔结果只作粗筛。本表**不含** `-6 dB` 带宽 / `FBW` / 7R 声压。")
    L.append("> 单 PMUT 单元模型结论**不得**外推为阵列性能。")
    L.append("")
    return "\n".join(L)


# ======================================================================================
# 频响形状类指标（LT3-B）：−6 dB 带宽 / FBW / 带内平坦度 / 峰值与峰位 / 比值峰 / 带宽交叠
# ======================================================================================
#: 主插值口径（与 `scripts/analyze_sweep.py::cross_6db` 一致）
PRIMARY_INTERP = "dB_domain_linear"
INTERP_CONVENTIONS = {
    "dB_domain_linear": "主口径：先把曲线转成 dB（功率 10log10、幅值 20log10，各自对**本曲线峰值**归一），"
                        "再在相邻频点的 dB 值之间做**线性插值**求 −6 dB 交点"
                        "（沿用 `scripts/analyze_sweep.py::cross_6db`）",
    "linear_domain_linear": "对照口径：把 −6 dB 还原成物理量阈值（功率 peak*10^(-6/10)、"
                            "幅值 peak*10^(-6/20)），在**物理量**上线性插值求交点",
}
RESOLUTION_LIMITATION = (
    "本批只有 **7 个频点（5–35 MHz，步长 5 MHz）**。因此："
    "① 任何『−6 dB 带宽』都是**粗估**，边频由相邻频点**插值**得到，不是扫出来的；"
    "② 插值域的选择（dB 域线性 vs 物理量线性）会改变边频，故同时给两套口径与其差值"
    "（`interp_edge_spread_*` / `BW_interp_spread_*` / `FBW_interp_spread_*`）作为该假设的不确定度；"
    "③ 20/35 MHz 这类采样点上的取值是精确命中，但**带宽边频几乎总落在采样点之间** ⇒ 仍是插值值；"
    "④ 曲线若在上/下边界仍未回落 6 dB，标 `lower/upper_bound_not_found`，"
    "**不得**把边界当交点，**更不得**解释为无限带宽"
    "（另有 `*_peak_at_*_boundary` 与 `*_bandwidth_boundary_warning` 显式打标）；"
    "⑤ 5 MHz 步长下带宽/FBW 的相对不确定度可与 FBW 本身同阶 ⇒ 本批带宽指标只用于**粗筛与候选区分**，"
    "不得作为工程指标对外引用。"
)
BOUNDARY_WARNING = "peak_or_edge_at_frequency_band_boundary__not_interpretable_as_unbounded"
FLATNESS_DEF = (
    "`flatness_<band>_<q>_dB = max(dB_band) − min(dB_band)`（带内**极差**）。"
    "dB 曲线对**整条 5–35 MHz 曲线的峰值**（每量各自）归一；"
    "极差**平移不变** ⇒ 该值与参考电平**无关**（这是选它的原因）。"
    "同时给 `flatness_<band>_<q>_std_dB`（带内 dB 的**总体标准差 σ**，分母 n）"
    "与 `band_min_dB_rel_global_peak_<band>_<q>`（相对**全带峰值**的最低电平，**依赖参考电平**，须成对解读）。"
)
BW_DEF = (
    "`f_low`/`f_high` = 从**曲线峰值**向两侧首次跌破 −6 dB 的频率（相邻频点线性插值）；"
    "`BW_<q>_MHz = f_high − f_low`；"
    "`fc_<q>_MHz = (f_low + f_high)/2`（**上下边频的算术中心**，不是峰值频率、不是几何平均）；"
    "`FBW_<q>_percent = (f_high − f_low)/fc × 100`，即**相对上下边频算术中心**的相对带宽。"
    "`BW`/`FBW` 只在**上下边频都取到**（`bandwidth_closed = true`）时给出，否则留空。"
)
OVERLAP_DEF = (
    "`band_overlap_Ptot_Vave_MHz` = `Ptot` 的 −6 dB 频带与 `Vave` 的 −6 dB 频带的**交集长度**；"
    "物理含义：**两者同时**处于各自峰值 6 dB 以内的公共通带宽度——『输出不掉、响应也不掉』的可用频段，"
    "对换能器通带最有工程意义。`band_overlap_fraction_of_union` = 交集/并集（Jaccard 型，0–1）。"
    "任一侧带宽未闭合 ⇒ 留空（**不得**用单侧带宽冒充）。"
    "另给 `Ptot/|Vave|` 与 `Ptot/|Vave|^2` 的峰值与峰位（工单 LT3-B 要求）："
    "`Ptot/|Vave|^2` ∝ 给定模态下的**辐射电导**（单位 kg/s），是与驱动电平无关的效率**形状**量；"
    "`Ptot/|Vave|` 仍含 `|Vave|` 因子，**只作形状参考**，不得当作效率。"
)

#: 「若把频段上界扩到 45 MHz 需要重做什么」——**只列，不在本轮执行**
BAND_45MHZ_REDO_CHECKLIST = [
    "**网格上界与 `fmax` 口径变更 ⇒ 网格可比性失效**：现有 35 MHz 网格的 `mesh_element_count`"
    "（106,212–157,390）与 45 MHz 网格**不是同一离散**，两批的 `Ptot`/`Vave` 与带宽**不得并排**"
    "（`source_type` 同为 `simulation` 但离散口径不同）；必须先做网格收敛或桥接证据。",
    "**LT2-C 控制面/选择集需要重新预检**：`intop5==swr1==efc1`、`area_ptot`、bbox 与选择集是"
    "**按网格/几何状态**记录的；重建网格后必须对新网格重新跑几何/选择预检，"
    "旧证据（`precheck-b2-phase2-v5-aggregate`）**不得**直接沿用。",
    "**带宽 / `fB` / 平坦度全部重算**：现有 9/162（`Ptot`）与 49/162（`Vave`）闭合的带宽"
    "是在 5–35 MHz 上算的；新频段下 `f_high`、`fc`、`FBW`、`flatness_15_25`、`flatness_10_30`、"
    "`band_overlap_*`、`Ptot/|Vave|²` 峰位**全部**会变，不能复用任何旧值。",
    "**峰值顶边界问题是否缓解：需重新统计，不得预设**。当前 83/162（`Ptot`）与 72/162（`Vave`）"
    "峰位顶在 35 MHz、153/162 与 111/162 上边频未找到；扩到 45 MHz 只是**有可能**把这些上边频包进来，"
    "但没有数据前**无法断言**——必须用新数据重跑 `*_upper_bound_not_found` / `*_peak_at_upper_boundary` 统计。",
    "**两批（legacy / 反相）口径是否仍可比：需重新论证**。legacy 批是 35 MHz 网格产出的；"
    "若反相批用 45 MHz 网格，则两批 `model_sha256` 不同**且网格离散不同** ⇒ 归一化对照"
    "（`legacy_vs_reverse_normalized`）的前提从『控制面同一 + 网格上界同一』退化为**不成立**；"
    "在拿到 legacy 侧的 45 MHz 数据（或网格桥接证据）前，跨批对照**不得**继续。",
    "**插值口径与不确定度需重估**：45 MHz 若仍按 5 MHz 步长，插值不确定度同阶问题不解决；"
    "若改为 0.5 MHz 步长（工单精扫计划为 5–45 MHz @0.5 MHz = 81 点），"
    "则 `interp_edge_spread_*` 需按新步长重算，且『粗估』的定性结论应相应降级/更新。",
    "**归一化与来源分离不受影响但需复述**：驱动口径（legacy `|Vdiff|` 来自人反馈 `fb-20260914-...`、"
    "反相 2 V）与频段无关；重算产物仍须逐行带 `source_run_id`/`source_file_sha256` 与来源分离标注。",
    "**授权状态需重新判定**：即便 45 MHz 数据到位，**LT2 未通过前仍不得制作正式反相排名**；"
    "`FORMAL_RANKING_AUTHORIZED` 不得因扩频段而放宽。",
    "**7R 轴向声压仍缺**：扩到 45 MHz **不解决**最终主判据问题——"
    "`H_p(f)=|p(f,0,0,7R)|/|V|` 仍需 COMSOL 场级导出与坐标原点平移，本轮**未实现**。",
]


def _peak_ref(values: list) -> float | None:
    fin = [v for v in values if v is not None and math.isfinite(v) and v > 0]
    return max(fin) if fin else None


def _mult(kind: str) -> float:
    """dB 乘子：功率 10log10、幅值 20log10 —— **绝不混用**。"""
    return 10.0 if kind == "power" else 20.0


def _cross_once(pts3: list, i_pk: int, side: str, use_db: bool, thr_lin: float) -> float | None:
    """从峰值向一侧扫，找首次跌破 −6 dB 的相邻点对并线性插值。pts3 = [(freq_MHz, value, dB)]。"""
    n = len(pts3)
    rng = range(i_pk, 0, -1) if side == "low" else range(i_pk, n - 1)
    for i in rng:
        j = i - 1 if side == "low" else i + 1
        fa, va, da = pts3[i]
        fb, vb, db_ = pts3[j]
        if use_db:
            if da is None or db_ is None:
                continue
            if da >= -6.0 > db_:
                return fa + (da + 6.0) / (da - db_) * (fb - fa)
        else:
            if va >= thr_lin > vb:
                return fa + (va - thr_lin) / (va - vb) * (fb - fa)
    return None


def response_metrics(freqs_hz: list, ptot: list, vave: list,
                     band_min_override: float | None = None,
                     band_max_override: float | None = None,
                     band_source_default: str = "auto_detected") -> dict:
    """单组合的频响形状指标（两套插值口径 + 平坦度 + 峰值/峰位 + 比值峰 + 带宽交叠）。

    **频段上/下界已参数化**：
      - 未给 override ⇒ 从**该组合自身的频点集合**自动探测（`band_source = auto_detected`），
        与参数化之前的行为**逐位一致**（默认口径不变，保可复算性）；
      - 给了 override ⇒ 用给定界并置 `band_source = cli`。
    **绝不外推**：界外的曲线一律不生成数值；界外的 −6 dB 边频仍标 `*_bound_not_found`。
    """
    out: dict = {}
    fs = [f / 1e6 for f in freqs_hz]
    fmin_data = min(fs) if fs else None
    fmax_data = max(fs) if fs else None
    band_min = band_min_override if band_min_override is not None else fmin_data
    band_max = band_max_override if band_max_override is not None else fmax_data
    band_source = ("cli" if (band_min_override is not None or band_max_override is not None)
                   else band_source_default)
    out["band_min_MHz"] = band_min
    out["band_max_MHz"] = band_max
    out["band_source"] = band_source
    out["band_data_fmin_MHz"] = fmin_data
    out["band_data_fmax_MHz"] = fmax_data
    fmin_mhz, fmax_mhz = band_min, band_max

    for q, kind, vals in (("Ptot", "power", ptot), ("Vave", "amplitude", vave)):
        mult = _mult(kind)
        ref = _peak_ref(vals)
        pts3 = [(f / 1e6, v, (mult * math.log10(v / ref) if ref else None))
                for f, v in zip(freqs_hz, vals)
                if v is not None and math.isfinite(v) and v > 0 and ref]
        # 注：峰值/峰位的**权威列**由 metric_row 产出（`Ptot_peak_W` / `Vave_peak` / `f_peak_*_MHz`）；
        # 此处用 `resp_` 前缀独立再算一遍，供 main() 做**口径一致性核对**（避免同名覆盖掩盖分歧）。
        out[f"resp_{q}_peak"] = ref
        if ref is None or len(pts3) < 2:
            out[f"resp_f_peak_{q}_MHz"] = None
            out[f"{q}_peak_at_lower_boundary"] = out[f"{q}_peak_at_upper_boundary"] = None
            out[f"f_low_{q}_MHz"] = out[f"f_high_{q}_MHz"] = None
            out[f"f_low_{q}_lininterp_MHz"] = out[f"f_high_{q}_lininterp_MHz"] = None
            out[f"BW_{q}_MHz"] = out[f"fc_{q}_MHz"] = out[f"FBW_{q}_percent"] = None
            out[f"BW_{q}_lininterp_MHz"] = out[f"FBW_{q}_lininterp_percent"] = None
            out[f"{q}_lower_bound_not_found"] = out[f"{q}_upper_bound_not_found"] = True
            out[f"{q}_bandwidth_closed"] = False
            out[f"interp_edge_spread_low_{q}_MHz"] = out[f"interp_edge_spread_high_{q}_MHz"] = None
            out[f"BW_interp_spread_{q}_MHz"] = out[f"FBW_interp_spread_{q}_percent"] = None
            out[f"{q}_interp_convention_agreement"] = "insufficient_points"
            out[f"{q}_bandwidth_boundary_warning"] = (
                f"insufficient_points_for_bandwidth | {BOUNDARY_WARNING}")
            for tag in ("10_30", "15_25", "full"):
                out[f"flatness_{tag}_{q}_dB"] = out[f"flatness_{tag}_{q}_std_dB"] = None
                out[f"band_min_dB_rel_global_peak_{tag}_{q}"] = None
                out[f"flatness_{tag}_{q}_n_points"] = 0
            continue

        i_pk = max(range(len(pts3)), key=lambda i: pts3[i][1])
        f_pk = pts3[i_pk][0]
        out[f"resp_f_peak_{q}_MHz"] = f_pk
        out[f"{q}_peak_at_lower_boundary"] = bool(fmin_mhz is not None and abs(f_pk - fmin_mhz) < 1e-9)
        out[f"{q}_peak_at_upper_boundary"] = bool(fmax_mhz is not None and abs(f_pk - fmax_mhz) < 1e-9)
        thr_lin = ref * (10 ** (-6.0 / 10.0) if kind == "power" else 10 ** (-6.0 / 20.0))
        edges = {(t, s): _cross_once(pts3, i_pk, s, t == "dBinterp", thr_lin)
                 for t in ("dBinterp", "lininterp") for s in ("low", "high")}
        out[f"f_low_{q}_MHz"] = edges[("dBinterp", "low")]
        out[f"f_high_{q}_MHz"] = edges[("dBinterp", "high")]
        out[f"f_low_{q}_lininterp_MHz"] = edges[("lininterp", "low")]
        out[f"f_high_{q}_lininterp_MHz"] = edges[("lininterp", "high")]
        lo, hi = out[f"f_low_{q}_MHz"], out[f"f_high_{q}_MHz"]
        lo2, hi2 = out[f"f_low_{q}_lininterp_MHz"], out[f"f_high_{q}_lininterp_MHz"]
        out[f"{q}_lower_bound_not_found"] = lo is None
        out[f"{q}_upper_bound_not_found"] = hi is None
        out[f"{q}_bandwidth_closed"] = (lo is not None and hi is not None)
        if out[f"{q}_bandwidth_closed"]:
            bw = hi - lo
            fc = (hi + lo) / 2.0
            out[f"BW_{q}_MHz"] = bw
            out[f"fc_{q}_MHz"] = fc
            out[f"FBW_{q}_percent"] = (bw / fc * 100.0) if fc else None
        else:
            out[f"BW_{q}_MHz"] = out[f"fc_{q}_MHz"] = out[f"FBW_{q}_percent"] = None
        if lo2 is not None and hi2 is not None:
            bw2 = hi2 - lo2
            fc2 = (hi2 + lo2) / 2.0
            out[f"BW_{q}_lininterp_MHz"] = bw2
            out[f"FBW_{q}_lininterp_percent"] = (bw2 / fc2 * 100.0) if fc2 else None
        else:
            out[f"BW_{q}_lininterp_MHz"] = out[f"FBW_{q}_lininterp_percent"] = None
        out[f"interp_edge_spread_low_{q}_MHz"] = (abs(lo - lo2) if (lo is not None and lo2 is not None) else None)
        out[f"interp_edge_spread_high_{q}_MHz"] = (abs(hi - hi2) if (hi is not None and hi2 is not None) else None)
        if out[f"BW_{q}_MHz"] is not None and out[f"BW_{q}_lininterp_MHz"] is not None:
            out[f"BW_interp_spread_{q}_MHz"] = abs(out[f"BW_{q}_MHz"] - out[f"BW_{q}_lininterp_MHz"])
            a, b = out[f"FBW_{q}_percent"], out[f"FBW_{q}_lininterp_percent"]
            out[f"FBW_interp_spread_{q}_percent"] = abs(a - b) if (a is not None and b is not None) else None
            out[f"{q}_interp_convention_agreement"] = "both_closed"
        else:
            out[f"BW_interp_spread_{q}_MHz"] = None
            out[f"FBW_interp_spread_{q}_percent"] = None
            out[f"{q}_interp_convention_agreement"] = (
                "neither_closed" if (out[f"BW_{q}_MHz"] is None and out[f"BW_{q}_lininterp_MHz"] is None)
                else "one_convention_only")
        warn = []
        if out[f"{q}_upper_bound_not_found"]:
            warn.append(f"upper_edge_not_found_within_{fmax_mhz:g}MHz_band")
        if out[f"{q}_lower_bound_not_found"]:
            warn.append(f"lower_edge_not_found_within_{fmin_mhz:g}MHz_band")
        if out[f"{q}_peak_at_upper_boundary"]:
            warn.append("peak_at_upper_frequency_boundary")
        if out[f"{q}_peak_at_lower_boundary"]:
            warn.append("peak_at_lower_frequency_boundary")
        out[f"{q}_bandwidth_boundary_warning"] = (";".join(warn) + f" | {BOUNDARY_WARNING}") if warn else ""
        # 带内平坦度（10–30 / 15–25 / 全带）
        for lo_m, hi_m, tag in ((10.0, 30.0, "10_30"), (15.0, 25.0, "15_25"),
                                (fmin_mhz or 0.0, fmax_mhz or 0.0, "full")):
            band = [(f, v) for f, v, _ in pts3 if lo_m - 1e-9 <= f <= hi_m + 1e-9]
            if len(band) < 2:
                out[f"flatness_{tag}_{q}_dB"] = out[f"flatness_{tag}_{q}_std_dB"] = None
                out[f"band_min_dB_rel_global_peak_{tag}_{q}"] = None
                out[f"flatness_{tag}_{q}_n_points"] = len(band)
                continue
            dbs = [mult * math.log10(v / ref) for _, v in band]
            mean = sum(dbs) / len(dbs)
            var = sum((x - mean) ** 2 for x in dbs) / len(dbs)
            out[f"flatness_{tag}_{q}_dB"] = max(dbs) - min(dbs)
            out[f"flatness_{tag}_{q}_std_dB"] = math.sqrt(var)
            out[f"band_min_dB_rel_global_peak_{tag}_{q}"] = min(dbs)
            out[f"flatness_{tag}_{q}_n_points"] = len(band)

    # ---- 比值峰（工单 LT3-B：Ptot/Vave 峰值与峰值频率）----
    for tag, power in (("Ptot_over_Vave", 1), ("Ptot_over_Vave2", 2)):
        ser = [(f, p / (v ** power)) for f, p, v in zip(freqs_hz, ptot, vave)
               if p is not None and v is not None and math.isfinite(p) and math.isfinite(v) and v > 0]
        if ser:
            i = max(range(len(ser)), key=lambda j: ser[j][1])
            out[f"{tag}_peak"] = ser[i][1]
            out[f"f_peak_{tag}_MHz"] = ser[i][0] / 1e6
        else:
            out[f"{tag}_peak"] = out[f"f_peak_{tag}_MHz"] = None

    # ---- 带宽交叠（Ptot 带 ∩ Vave 带）----
    pl, ph = out.get("f_low_Ptot_MHz"), out.get("f_high_Ptot_MHz")
    vl, vh = out.get("f_low_Vave_MHz"), out.get("f_high_Vave_MHz")
    if None not in (pl, ph, vl, vh):
        inter = min(ph, vh) - max(pl, vl)
        union = max(ph, vh) - min(pl, vl)
        out["band_overlap_Ptot_Vave_MHz"] = inter if inter > 0 else 0.0
        out["band_overlap_fraction_of_union"] = (inter / union) if union > 0 else None
    else:
        out["band_overlap_Ptot_Vave_MHz"] = None
        out["band_overlap_fraction_of_union"] = None
    out["band_overlap_applicable"] = out["band_overlap_Ptot_Vave_MHz"] is not None
    return out


#: Pareto 指标对（含方向与选用理由）——**不做加权总分**
PARETO_PAIRS = [
    {"id": "P1", "metrics": ["Ptot_peak_W", "FBW_Ptot_percent"], "directions": [1, 1],
     "why": "工单指定：峰值声功率 × 功率 −6 dB 相对带宽（输出–带宽经典权衡）"},
    {"id": "P2", "metrics": ["FBW_Vave_percent", "flatness_15_25_Vave_dB"], "directions": [1, -1],
     "why": "本管线选择（更有物理意义）：响应 −6 dB 相对带宽 × 带内平坦度（15–25 MHz）。"
            "通带的两个正交要求——『够宽』与『够平』——在单膜/单振子结构上通常此消彼长，"
            "且都是**形状量**，不依赖驱动电平，比峰值类指标更能区分候选"},
    {"id": "P3", "metrics": ["FBW_Vave_percent", "Vave_peak"], "directions": [1, 1],
     "why": "响应带宽 × 响应峰值（灵敏度–带宽权衡），用于核对 P2 结论是否稳健"},
    {"id": "P4", "metrics": ["FBW_Ptot_percent", "flatness_15_25_Ptot_dB"], "directions": [1, -1],
     "why": "功率侧对应 P2，用于核对结论是否只来自 Vave 口径"},
]


def pareto_pairs(rows: list[dict], pairs: list[dict]) -> tuple[list[dict], dict]:
    """对每个指标对在 **eligible 子集**内算 Pareto；**如实报告是否退化**（不为好看换指标）。"""
    out_rows: list[dict] = []
    summary = {"pairs": [], "degenerate_pairs": [],
               "note": "只在预检 eligible 子集内计算；不做加权总分；退化则如实报告"}
    for spec in pairs:
        m0, m1 = spec["metrics"]
        d0, d1 = spec["directions"]
        n_elig = sum(1 for r in rows if r.get("eligible_for_ranking"))
        pool = [r for r in rows
                if r.get("eligible_for_ranking") and r.get(m0) is not None and r.get(m1) is not None]
        pts = {(r["x_scale"], r["N_w_te1"]): (float(r[m0]) * d0, float(r[m1]) * d1) for r in pool}
        keys = list(pts)
        dom: dict = {k: [] for k in keys}
        for a in keys:
            for b in keys:
                if a == b:
                    continue
                if all(pts[b][i] >= pts[a][i] for i in range(2)) and \
                   any(pts[b][i] > pts[a][i] for i in range(2)):
                    dom[a].append(b)
        front = [k for k in keys if not dom[k]]
        front_set = set(front)
        info = {
            "pair_id": spec["id"], "metrics": [m0, m1], "directions": spec["directions"], "why": spec["why"],
            "n_eligible": n_elig, "n_with_both_metrics": len(pool),
            "n_excluded_missing_metric_0": sum(1 for r in rows if r.get("eligible_for_ranking") and r.get(m0) is None),
            "n_excluded_missing_metric_1": sum(1 for r in rows if r.get("eligible_for_ranking") and r.get(m1) is None),
            "n_pareto_front": len(front), "n_dominated": len(pool) - len(front),
            "n_dominance_pairs": sum(len(v) for v in dom.values()),
            "pareto_front_keys": [[k[0], k[1]] for k in sorted(front)],
            "degenerate": len(front) == 1,
            "degenerate_reason": ("前沿只有 1 个点：该指标对在本批仍不构成权衡" if len(front) == 1 else
                                  ("无可用点（前沿为空）：至少一个指标在本批全部不可算"
                                   "（带宽未闭合时 FBW 全空）" if len(front) == 0 else "")),
            "usable": len(front) >= 2,
        }
        summary["pairs"].append(info)
        if info["degenerate"] or len(front) == 0:
            summary["degenerate_pairs"].append(spec["id"])
        for r in pool:
            k = (r["x_scale"], r["N_w_te1"])
            out_rows.append({
                "pair_id": spec["id"], "metric_0": m0, "metric_1": m1,
                "direction_0": "maximize" if d0 > 0 else "minimize",
                "direction_1": "maximize" if d1 > 0 else "minimize",
                "source_run_id": r["source_run_id"], "source_file_sha256": r["source_file_sha256"],
                "drive_mode": r["drive_mode"], "status": r["status"], "formal_ranking": False,
                "x_scale": r["x_scale"], "N_w_te1": r["N_w_te1"],
                "precheck_class": r["precheck_class"],
                "value_0": r[m0], "value_1": r[m1],
                "pareto_front": k in front_set,
                "dominated_by_count": len(dom.get(k, [])),
                "dominated_by": ";".join(f"x={b[0]:g},N={b[1]}" for b in sorted(dom.get(k, []))),
                "degenerate_pair": info["degenerate"],
            })
    return out_rows, summary


def _stats(vals: list) -> dict:
    xs = sorted(v for v in vals if v is not None)
    if not xs:
        return {"n": 0, "min": None, "median": None, "max": None}
    return {"n": len(xs), "min": xs[0], "median": xs[len(xs) // 2], "max": xs[-1]}


def response_summary(metrics: list[dict], freqs_sorted: list[float]) -> dict:
    """频响指标汇总：口径声明、分辨率限制、**插值假设带来的不确定度（实测）**、边界打标计数。"""
    fs_mhz = sorted({round(f / 1e6, 6) for f in freqs_sorted})
    step = round(fs_mhz[1] - fs_mhz[0], 6) if len(fs_mhz) > 1 else None
    s: dict = {
        "primary_interpolation": PRIMARY_INTERP,
        "conventions": INTERP_CONVENTIONS,
        "definitions": {"bandwidth_and_fbw": BW_DEF, "flatness": FLATNESS_DEF, "overlap_and_ratios": OVERLAP_DEF},
        "resolution": {
            "freq_points": len(fs_mhz), "freq_grid_MHz": fs_mhz, "freq_step_MHz": step,
            "limitation": RESOLUTION_LIMITATION,
            "empirical_uncertainty_source": "两套插值口径的差值（下节 interp_uncertainty），"
                                            "**不是**网格收敛或 Richardson 外推，也**不是**实验/文献依据",
        },
        "seven_R_axial_pressure": "**需 COMSOL，未实现**（本机当前处于 no-COMSOL 窗口；"
                                  "`H_p(f)=|p(f,0,0,7R)|/|V|` 需场级求解与坐标原点平移）",
        "boundary_marking": {"warning_code": BOUNDARY_WARNING,
                             "policy": "峰位或边频落在频段边界时，只标 warning；"
                                       "不把边界当交点、不解释为无限带宽"},
        "per_quantity": {},
    }
    for q in ("Ptot", "Vave"):
        peak_key = "Ptot_peak_W" if q == "Ptot" else "Vave_peak"
        n = sum(1 for m in metrics if m.get(peak_key) is not None)
        s["per_quantity"][q] = {
            "n_with_peak": n,
            "authoritative_peak_columns": [peak_key, f"f_peak_{q}_MHz"],
            "n_bandwidth_closed": sum(1 for m in metrics if m.get(f"{q}_bandwidth_closed")),
            "n_lower_bound_not_found": sum(1 for m in metrics if m.get(f"{q}_lower_bound_not_found")),
            "n_upper_bound_not_found": sum(1 for m in metrics if m.get(f"{q}_upper_bound_not_found")),
            "n_peak_at_lower_boundary": sum(1 for m in metrics if m.get(f"{q}_peak_at_lower_boundary")),
            "n_peak_at_upper_boundary": sum(1 for m in metrics if m.get(f"{q}_peak_at_upper_boundary")),
            "n_with_boundary_warning": sum(1 for m in metrics if m.get(f"{q}_bandwidth_boundary_warning")),
            "interp_convention_agreement": {
                "both_closed": sum(1 for m in metrics if m.get(f"{q}_interp_convention_agreement") == "both_closed"),
                "one_convention_only": sum(1 for m in metrics
                                           if m.get(f"{q}_interp_convention_agreement") == "one_convention_only"),
                "neither_closed": sum(1 for m in metrics
                                      if m.get(f"{q}_interp_convention_agreement") == "neither_closed"),
            },
            "dB_multiplier": ("10*log10（功率）" if q == "Ptot" else "20*log10（幅值）"),
        }
    s["interp_uncertainty"] = {
        "edge_spread_low_Ptot_MHz": _stats([m.get("interp_edge_spread_low_Ptot_MHz") for m in metrics]),
        "edge_spread_high_Ptot_MHz": _stats([m.get("interp_edge_spread_high_Ptot_MHz") for m in metrics]),
        "edge_spread_low_Vave_MHz": _stats([m.get("interp_edge_spread_low_Vave_MHz") for m in metrics]),
        "edge_spread_high_Vave_MHz": _stats([m.get("interp_edge_spread_high_Vave_MHz") for m in metrics]),
        "BW_spread_Ptot_MHz": _stats([m.get("BW_interp_spread_Ptot_MHz") for m in metrics]),
        "BW_spread_Vave_MHz": _stats([m.get("BW_interp_spread_Vave_MHz") for m in metrics]),
        "FBW_spread_Ptot_percent": _stats([m.get("FBW_interp_spread_Ptot_percent") for m in metrics]),
        "FBW_spread_Vave_percent": _stats([m.get("FBW_interp_spread_Vave_percent") for m in metrics]),
        "relative_uncertainty_note": "相对量级 = FBW_spread / FBW（逐行可比）；"
                                     "因只有 7 点、步长 5 MHz，该相对量级可与 FBW 本身同阶，"
                                     "故带宽类指标只用于粗筛。",
    }
    s["flatness_bands"] = {}
    for tag in ("10_30", "15_25", "full"):
        for q in ("Ptot", "Vave"):
            s["flatness_bands"][f"{tag}_{q}"] = {
                "definition": FLATNESS_DEF,
                "range_dB": _stats([m.get(f"flatness_{tag}_{q}_dB") for m in metrics]),
                "std_dB": _stats([m.get(f"flatness_{tag}_{q}_std_dB") for m in metrics]),
                "min_dB_rel_global_peak": _stats([m.get(f"band_min_dB_rel_global_peak_{tag}_{q}") for m in metrics]),
            }
    s["band_overlap"] = {
        "definition": OVERLAP_DEF,
        "n_applicable": sum(1 for m in metrics if m.get("band_overlap_applicable")),
        "n_not_applicable": sum(1 for m in metrics if not m.get("band_overlap_applicable")),
        "overlap_MHz": _stats([m.get("band_overlap_Ptot_Vave_MHz") for m in metrics]),
        "overlap_fraction_of_union": _stats([m.get("band_overlap_fraction_of_union") for m in metrics]),
    }
    s["ratio_peaks"] = {
        "Ptot_over_Vave_peak": _stats([m.get("Ptot_over_Vave_peak") for m in metrics]),
        "f_peak_Ptot_over_Vave_MHz": _stats([m.get("f_peak_Ptot_over_Vave_MHz") for m in metrics]),
        "Ptot_over_Vave2_peak": _stats([m.get("Ptot_over_Vave2_peak") for m in metrics]),
        "f_peak_Ptot_over_Vave2_MHz": _stats([m.get("f_peak_Ptot_over_Vave2_MHz") for m in metrics]),
    }
    return s


def render_response_contract(s: dict, metrics: list[dict]) -> str:
    L = ["# LT3 频响形状指标口径（−6 dB 带宽 / FBW / 平坦度 / 峰值峰位 / 带宽交叠）", ""]
    L.append(f"- 生成脚本：`work/tools/lt3_prep.py`（sha256 `{sha256_file(Path(__file__).resolve())}`）")
    L.append(f"- 主插值口径：`{s['primary_interpolation']}`")
    L.append(f"- 组合数：{len(metrics)}（此表覆盖全部组合；排名只取 eligible 子集）")
    L.append(f"- `status = {PROVISIONAL_STATUS}`｜`formal_ranking = false`"
             "（LT2 未通过 ⇒ **不得**制作正式反相排名）")
    L.append("")
    L.append("## 1. 定义式（写进代码：`BW_DEF` / `FLATNESS_DEF` / `OVERLAP_DEF`）")
    L.append("")
    L.append("### 1.1 −6 dB 带宽与 FBW")
    L.append("")
    L.append(f"{s['definitions']['bandwidth_and_fbw']}")
    L.append("")
    L.append("dB 规则：`Ptot` 用 **10·log10**（功率量）；`Vave` 用 **20·log10**（幅值量）；**绝不混用**。")
    L.append("")
    L.append("### 1.2 带内平坦度")
    L.append("")
    L.append(f"{s['definitions']['flatness']}")
    L.append("")
    L.append("### 1.3 交叠/交叉类指标与比值峰（含物理含义）")
    L.append("")
    L.append(f"{s['definitions']['overlap_and_ratios']}")
    L.append("")
    L.append("## 2. 两种插值口径")
    L.append("")
    L.append("| 口径 | 做法 |")
    L.append("|---|---|")
    for k, v in s["conventions"].items():
        mark = "（**主口径**，进入正式列）" if k == s["primary_interpolation"] else "（对照，仅用于估不确定度）"
        L.append(f"| `{k}`{mark} | {v} |")
    L.append("")
    L.append("## 3. 分辨率限制（**不得省略**）")
    L.append("")
    L.append(f"{s['resolution']['limitation']}")
    L.append("")
    L.append(f"- 频点：{s['resolution']['freq_grid_MHz']} MHz（{s['resolution']['freq_points']} 点，"
             f"步长 {s['resolution']['freq_step_MHz']} MHz）")
    L.append("")
    if "band" in s:
        b = s["band"]
        L.append("### 3.1 频段界（**已参数化**）")
        L.append("")
        L.append(f"- `band_min_MHz = {b['band_min_MHz']}`｜`band_max_MHz = {b['band_max_MHz']}`"
                 f"｜`band_source = {b['band_source']}`")
        L.append(f"- `--band-min-mhz` = {b['band_cli_override']['min']}｜"
                 f"`--band-max-mhz` = {b['band_cli_override']['max']}（None = 未覆盖）")
        L.append(f"- 自动探测到的界：{b['auto_detected_band_MHz']} MHz"
                 f"（本批每组合频点相同 ⇒ 与覆盖值一致）")
        L.append(f"- 覆盖是否超出数据范围：**{b['override_exceeds_data_range']}**"
                 f"｜不外推：**{b['no_extrapolation']}**")
        L.append("")
        L.append(f"{b['note']}")
        L.append("")
    if "frequency_domain_coverage" in s:
        cov = s["frequency_domain_coverage"]
        g = cov["data_gap_45MHz"]
        L.append("### 3.2 data gap 登记：**45 MHz 计算数据当前不存在**")
        L.append("")
        L.append(f"- 本批输入频点集合：{cov['input_freq_set_MHz']} MHz"
                 f"（{cov['input_freq_points']} 点，{cov['input_freq_min_MHz']}–{cov['input_freq_max_MHz']} MHz）")
        L.append(f"- 状态：`{g['status']}` —— {g['statement']}")
        L.append(f"- 检索证据：{g['evidence_note']}（磁盘文件 `{g['evidence_file']}`）")
        L.append(f"- 口径：{g['policy']}")
        L.append("")
        L.append("#### 若扩到 45 MHz 需要重做什么（**只列，未执行**）")
        L.append("")
        for i, item in enumerate(BAND_45MHZ_REDO_CHECKLIST, start=1):
            L.append(f"{i}. {item}")
        L.append("")
    L.append("## 4. 插值假设带来的**实测**不确定度")
    L.append("")
    L.append(f"- 不确定度来源：{s['resolution']['empirical_uncertainty_source']}")
    L.append("")
    L.append("| 量 | n | 最小 | 中位 | 最大 |")
    L.append("|---|---|---|---|---|")
    for key, lab in (
        ("edge_spread_low_Ptot_MHz", "下边频口径差 Ptot (MHz)"),
        ("edge_spread_high_Ptot_MHz", "上边频口径差 Ptot (MHz)"),
        ("edge_spread_low_Vave_MHz", "下边频口径差 Vave (MHz)"),
        ("edge_spread_high_Vave_MHz", "上边频口径差 Vave (MHz)"),
        ("BW_spread_Ptot_MHz", "BW 口径差 Ptot (MHz)"),
        ("BW_spread_Vave_MHz", "BW 口径差 Vave (MHz)"),
        ("FBW_spread_Ptot_percent", "FBW 口径差 Ptot (百分点)"),
        ("FBW_spread_Vave_percent", "FBW 口径差 Vave (百分点)"),
    ):
        d = s["interp_uncertainty"][key]
        f = lambda x: "—" if x is None else f"{x:.4g}"
        L.append(f"| {lab} | {d['n']} | {f(d['min'])} | {f(d['median'])} | {f(d['max'])} |")
    L.append("")
    L.append(f"{s['interp_uncertainty']['relative_uncertainty_note']}")
    L.append("")
    L.append("## 5. 边界打标结果（峰值/边频顶在频段边界）")
    L.append("")
    L.append(f"打标代码：`{s['boundary_marking']['warning_code']}`。{s['boundary_marking']['policy']}")
    L.append("")
    L.append("| 量 | 有峰 | 带宽闭合 | 下界未找到 | 上界未找到 | 峰位在下边界 | 峰位在上边界 | 带 warning |")
    L.append("|---|---|---|---|---|---|---|---|")
    for q, d in s["per_quantity"].items():
        L.append(f"| {q} | {d['n_with_peak']} | {d['n_bandwidth_closed']} | {d['n_lower_bound_not_found']} | "
                 f"{d['n_upper_bound_not_found']} | {d['n_peak_at_lower_boundary']} | "
                 f"{d['n_peak_at_upper_boundary']} | {d['n_with_boundary_warning']} |")
    L.append("")
    for q, d in s["per_quantity"].items():
        L.append(f"- `{q}` 插值口径一致性：{d['interp_convention_agreement']}（dB 乘子 {d['dB_multiplier']}）")
    L.append("")
    L.append("## 6. 带内平坦度分布（dB 极差 / σ）")
    L.append("")
    L.append("| 带 | 量 | 极差 min | 极差中位 | 极差 max | σ 中位 | 相对全带峰值最低电平 中位 |")
    L.append("|---|---|---|---|---|---|---|")
    for key, d in s["flatness_bands"].items():
        tag, q = key.rsplit("_", 1)
        f = lambda x: "—" if x is None else f"{x:.4g}"
        L.append(f"| {tag.replace('_','–')} MHz | {q} | {f(d['range_dB']['min'])} | {f(d['range_dB']['median'])} | "
                 f"{f(d['range_dB']['max'])} | {f(d['std_dB']['median'])} | "
                 f"{f(d['min_dB_rel_global_peak']['median'])} |")
    L.append("")
    L.append("## 7. 带宽交叠与比值峰")
    L.append("")
    L.append(f"- 带宽交叠可用组合：{s['band_overlap']['n_applicable']}；"
             f"不可用（任一侧带宽未闭合）：{s['band_overlap']['n_not_applicable']}")
    bo = s["band_overlap"]["overlap_MHz"]
    L.append(f"- 交叠宽度（MHz）：n={bo['n']}，中位 {bo['median']}，最大 {bo['max']}")
    for key in ("Ptot_over_Vave_peak", "Ptot_over_Vave2_peak"):
        d = s["ratio_peaks"][key]
        L.append(f"- `{key}`：n={d['n']}，中位 {d['median']}")
    L.append("")
    L.append("## 8. 未实现（明确声明）")
    L.append("")
    L.append(f"- **7R 轴向声压** `H_p(f)=|p(f,0,0,7R)|/|V|`：{s['seven_R_axial_pressure']}")
    L.append("- 网格收敛性分析：**未做**（无多网格数据）。")
    L.append("- 反相驱动侧的频响指标：仅 LT1 的 15 点（3 频点）——**点数不足以算 −6 dB 带宽**，")
    L.append("  故**不**对反相侧出带宽结论（LT2 的 504 点尚不存在）。")
    L.append("")
    L.append("## 9. 命名与使用限制")
    L.append("")
    L.append("- `Vave` 的 −6 dB 带宽只能称**响应带宽**；`Ptot` 的只能称**功率带宽**。")
    L.append("  **禁止**称往返带宽 / 脉冲回波带宽 / 阵列带宽（单 PMUT 单元模型不支持这些说法）。")
    L.append("- 带宽/平坦度只是**形状**量；最终主判据是 7R 轴向声压（**未实现**）。")
    L.append("- 本文件的指标**不得**外推为阵列性能。")
    L.append("")
    return "\n".join(L)


# ---------------------------------------------------------------- 质检装配
def build_quality(args, src, src_sha, enc, delim, rows, combos, xs, ns, freqs, rows_per_combo, dup_keys,
                  null_counts, nan_counts, inf_counts, bad_complex, neg_ptot, zero_ptot,
                  zin_eq, zin_checked, freq_nonincreasing, drive, drive_mismatch_rows, declared_drive_values,
                  voltage_check, precheck, precheck_src, precheck_sha, missing_combos, extra_combos,
                  authority_hashes, copied, mapping, header, header_index) -> dict:
    return {
        "kind": "lt3_prep_quality_report",
        "schema_version": "1",
        "tool": "work/tools/lt3_prep.py",
        "tool_sha256": sha256_file(Path(__file__).resolve()),
        "source_run_id": args.source_run_id,
        "source_file": str(src),
        "source_file_sha256": src_sha,
        "source_file_bytes": src.stat().st_size,
        "source_encoding": enc,
        "source_delimiter": delim,
        "header_row_index_0based": header_index,
        "header": header,
        "column_mapping": mapping,
        "drive_mode": drive,
        "inputs_copied_to_lt3": copied,
        "counts": {
            "data_rows": len(rows),
            "combos": len(combos),
            "x_scale_levels": len(xs), "N_w_te1_levels": len(ns), "freq_points": len(freqs),
            "unique_keys": len(combos) * len(freqs) if len(rows_per_combo) == 1 else None,
            "duplicate_keys": dup_keys,
            "missing_combo_keys": len(missing_combos),
            "extra_combo_keys": len(extra_combos),
            "rows_per_combo_distribution": rows_per_combo,
            "freq_uniform_across_combos": len(rows_per_combo) == 1,
        },
        "grid": {"x_scale": xs, "N_w_te1": ns, "freq_Hz": freqs},
        "missing_combo_keys": missing_combos,
        "extra_combo_keys": extra_combos,
        "nulls_nan_inf": {
            "empty_or_missing": null_counts, "nan": nan_counts, "inf": inf_counts,
            "unparsable": bad_complex,
        },
        "acoustic_quantity_gate": {
            "required": ["Ptot", "Vave"],
            "required_columns_present": [k for k in ("Ptot", "Vave") if k in mapping],
            "Ptot_empty_rows": null_counts.get("Ptot", 0),
            "Vave_empty_rows": null_counts.get("Vave", 0),
            "Ptot_positive": neg_ptot == 0,
            "negative_Ptot_rows": neg_ptot,
            "zero_Ptot_rows": zero_ptot,
            "note": "Ptot 负值只标记、不取绝对值（sweep-analysis SOP §2）；负值行仍进表并带标志",
        },
        "electrical_metrics_exclusion": {
            "excluded": True,
            "columns_present": sorted(c for q, c in mapping.items() if q in ELECTRICAL_PATTERNS),
            "excluded_semantic_keys": sorted(ELECTRICAL_PATTERNS),
            "reason": ELECTRICAL_EXCLUSION_REASON,
            "kcl_max_relative_observed": KCL_MAX_RELATIVE_OBSERVED,
            "kcl_tolerance": KCL_TOLERANCE,
            "evidence_file": "work/models/lt0_audit.json",
            "evidence_note": "LT0-C：KCL 相对误差 0.1662 / 0.1797 / 0.1886（5/20/35 MHz）> 1% 门槛 ⇒ 电气指标整体排除",
            "Zin2_known_formula_defect": {
                "zin_equal_rows": zin_eq, "rows_checked": zin_checked,
                "note": "Zin2 定义为 v0/I01（与 Zin1 相同），已知公式缺陷；本管线不使用任何一个 Zin",
            },
        },
        "drive_consistency": {
            "drive_mismatch_rows": drive_mismatch_rows,
            "declared_drive_values_distinct": sorted(set(declared_drive_values))[:10],
            "declaration_vs_inference_mismatch": drive["declaration_vs_inference_mismatch"],
            "voltage_consistency": voltage_check,
        },
        "frequency_order": {
            "combos_not_strictly_increasing": freq_nonincreasing,
            "note": "频点不递增的组合必须查明原因，禁止插值补齐",
        },
        "precheck": {
            "provided": bool(precheck),
            "file": precheck_src,
            "sha256": precheck_sha,
            "combos_loaded": len(precheck),
            "eligible_count": sum(1 for k in combos if precheck.get(k) and
                                  (precheck[k].get("eligible_for_ranking") is True
                                   or precheck[k].get("eligibility_level") == "full")),
            "class_field_used": "classification（若存在）否则 eligibility_level",
            "class_semantics": {
                "full": "预检全量合格（等价于 sweep-analysis SOP 的 `clean` 排名资格）",
                "ineligible": "预检判定不可参与排名（如 design_region_reversed / boundary_coincident）",
                "precheck_missing": "该组合不在预检清单内",
                "precheck_not_provided": "未提供预检文件，资格未判定",
            },
            "merge_policy": "同键以 phase2_rows（含控制面证据）覆盖/补充 phase1 记录；phase1 覆盖全部 162 组合，资格判定不丢",
            "policy": "只在预检 eligible 子集内排名；未提供预检时排名显式降级",
        },
        "authority": {
            "formal_ranking_authorized": FORMAL_RANKING_AUTHORIZED,
            "authority_docs_sha256": authority_hashes,
            "status_label": PROVISIONAL_STATUS,
        },
        "units": {
            "Ptot": "W", "Ptot_norm": "W/V^2", "Vave": "m/s", "Vave_norm": "(m/s)/V",
            "freq": "Hz（导出原始列）；报告中按 MHz",
            "note": "内部 SI；导出表列名已含单位，符合 dataset-contract §5",
        },
        "not_verified": [
            "归一化 Ptot_norm/Vave_norm 对 legacy 批次2 不可计算（导出无 Vdiff）",
            "跨驱动可比性只有归一化量在原理上可比；因 legacy 缺 Vdiff，实际对照不可完成",
            "-6 dB 带宽/FBW 未在本脚本内计算（LT3-B 指标，待数据到位后补）",
            "7R 轴向声压 H_p(f) 未计算（需 COMSOL，当前窗口禁止）",
        ],
    }


# ---------------------------------------------------------------- 输出工具
def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("（空表）\n", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def render_contract(c: dict, args, src: Path, src_sha: str, effective: str, refused: bool) -> str:
    L: list[str] = []
    L.append("# LT3 归一化与可比性口径（口径说明）")
    L.append("")
    L.append(f"- 生成脚本：`work/tools/lt3_prep.py`（sha256 `{sha256_file(Path(__file__).resolve())}`）")
    L.append(f"- 数据源：`{src}`（sha256 `{src_sha}`）")
    L.append(f"- `source_run_id`：`{args.source_run_id}`")
    L.append(f"- `drive_mode`（effective）：`{effective}`")
    L.append(f"- `status`：`{PROVISIONAL_STATUS if not refused else REFUSED_STATUS}`"
             f"｜`formal_ranking = False`")
    L.append("")
    L.append("> ⚠️ **授权限制**：依据 `docs/TO_CODEX_order-20260913-LT0-LT3.md` §4 与")
    L.append("> `docs/TO_CODEX_order-20260914-LT2-superseding-LT2B-LT2D.md` §7，")
    L.append("> **LT2 未完全通过前不得制作『正式反相粗扫排名』**。本文件描述的排名一律是")
    L.append(f"> `status = {PROVISIONAL_STATUS}` 的**临时**结果，且只对 legacy 数据成立；")
    L.append("> 反相驱动数据会被脚本 fail-closed 拒绝排名（只出对比用中间量）。")
    L.append("")
    L.append("## 1. 归一化公式")
    L.append("")
    for k, v in c["formulas"].items():
        L.append(f"- `{k} = {v}`")
    L.append("")
    L.append("## 2. dB 口径")
    L.append("")
    L.append(f"- {c['dB_rules']['amplitude']}")
    L.append(f"- {c['dB_rules']['power']}")
    L.append(f"- **{c['dB_rules']['rule']}**")
    L.append("")
    L.append("## 3. 两套驱动的归一化可得性")
    L.append("")
    L.append("| 驱动 | Vdiff | 导出含 Vdiff | 分母来源 `source_type` | Ptot_norm | Vave_norm |")
    L.append("|---|---|---|---|---|---|")
    for name, d in c["drives"].items():
        L.append(f"| `{name}` | {d['Vdiff_V']} | {d['Vdiff_available_in_export']} | "
                 f"`{d.get('Vdiff_source_type', 'n/a')}` | {d['Ptot_norm']} | {d['Vave_norm']} |")
    L.append("")
    for name, d in c["drives"].items():
        if d["reason"]:
            L.append(f"- `{name}`：{d['reason']}")
        L.append(f"  - 依据：{d['evidence']}")
    L.append("")
    # ---- 红线 4：来源分离 ----
    ss = c["source_separation"]
    L.append("## 3b. 来源分离（红线 4）——归一化量是**混合来源**")
    L.append("")
    L.append("| 角色 | 量 | `source_type` | 值 | 证据 |")
    L.append("|---|---|---|---|---|")
    L.append(f"| 分子 | {', '.join(ss['numerator']['quantities'])} | `simulation` | — | {ss['numerator']['origin']} |")
    dl = ss["denominator_legacy"]
    L.append(f"| 分母（legacy） | `abs(Vdiff)` | **`{dl['source_type']}`** | "
             f"{dl['value_V']} V | `feedback_id = {dl['feedback_id']}`；"
             f"`{Path(dl['evidence_file']).name if dl['evidence_file'] else '—'}` "
             f"sha256 `{dl['evidence_sha256']}` |")
    dr = ss["denominator_reverse"]
    L.append(f"| 分母（反相） | `abs(Vdiff)` | `{dr['source_type']}` | {dr['value_V']} V | {dr['origin']} |")
    L.append("")
    L.append(f"**{ss['rule']}**")
    L.append("")
    L.append("用户原话：")
    L.append("")
    L.append(f"> {dl['quote']}")
    L.append("")
    L.append("**legacy 侧的归一化**（`Ptot_norm = Ptot/1^2`、`Vave_norm = Vave/1`）**不得**写成")
    L.append("「由模型或导出表得到」：批次2 导出表**没有**任何电位/差分电压列（已实测），")
    L.append(f"该分母来自**人反馈**（`{dl['feedback_id']}`）。")
    L.append("")
    L.append("### 3c. 必须随产物保留的限制（不得省略）")
    L.append("")
    L.append(f"{dl['limitation']}")
    L.append("")
    L.append("## 4. **可**跨驱动比较的量（有条件）")
    L.append("")
    for item in c["cross_drive_comparable"]:
        L.append(f"### `{item['quantity']}` — {item['comparable']}")
        for cond in item["conditions"]:
            L.append(f"- {cond}")
        L.append("")
    L.append("## 5. **不可**跨驱动比较的量（硬禁止）")
    L.append("")
    for item in c["cross_drive_not_comparable"]:
        L.append(f"- **`{item['quantity']}`**：{item['why']}")
    L.append("")
    L.append("## 6. 当前批次的实际结论")
    L.append("")
    if effective == LEGACY_DRIVE_MODE:
        L.append("- 本批为 **legacy 驱动**导出，**未记录** `V_outer/V_inner/Vdiff`（表头实核）。")
        if c["drives"][LEGACY_DRIVE_MODE]["Ptot_norm"].startswith("computable"):
            L.append("- 本次运行**提供了人反馈分母** ⇒ 归一化**可计算**：")
            L.append("  - `Ptot_norm = Ptot / 1^2`、`Vave_norm = Vave / 1`（除数为 1，**数值不变但量纲变为 W/V² 与 (m/s)/V**）；")
            L.append(f"  - 分母 `source_type = {LEGACY_VDIFF_SOURCE_TYPE}`（`{LEGACY_VDIFF_FEEDBACK_ID}`），"
                     "分子 `source_type = simulation` ⇒ **混合来源**，产物逐行标注；")
            L.append("  - `normalization_reason` 为空（不再是 not_computable）；")
            L.append("  - ⚠️ 但**限制照旧**：见 §3c（用户原话为『约 1 V』，引入方向已知、量级未量化的系统偏差）。")
        else:
            L.append("- ⇒ `Ptot_norm = Ptot/|Vdiff|^2` 与 `Vave_norm = Vave/|Vdiff|` **均不可计算**；")
            L.append(f"  产物中这两列**留空**并写 `normalization_reason = {LEGACY_VDIFF_NON_COMPUTABLE_REASON}`。")
            L.append("- ⇒ 若要解除该判定，须提供**人反馈**分母（`--legacy-vdiff-V` + `feedback_id` + 证据文件），")
            L.append("  且必须在产物里按 `source_type` 分离标注，**不得**写成由模型/导出表得到。")
    else:
        L.append("- 本批为**反相驱动**：`|Vdiff| = 2 V`（`V_outer=+1 V`, `V_inner=-1 V`, `V_ref=0 V`）。")
        L.append("- 归一化量可计算；但**排名被 fail-closed 拒绝**（LT2 未完全通过），只输出对比用中间量。")
    L.append("")
    L.append("## 7. 不确定度与未验证项")
    L.append("")
    for t in [
        "驱动口径由**导出列结构启发式推断**，不是 COMSOL 模型读数（红线 3）；若与模型实际不符，本报告全部结论作废。",
        "legacy 批次的 `Ptot`/`Vave` 与反相批次**来源不同**（`model_sha256` 不同），只能并排对照，严禁合并统计（红线 4）。",
        "Pareto 只在预检 eligible 子集内计算；未提供预检时排名为『临时且未过几何/选择预检』。",
        "本文件不含 `-6 dB` 带宽 / `FBW` / 7R 声压：这些属 LT3-B 指标，待数据到位后按同一口径补算。",
    ]:
        L.append(f"- {t}")
    if c["drives"][LEGACY_DRIVE_MODE]["Ptot_norm"].startswith("computable"):
        L.append("")
        L.append("### 7b. legacy 归一化分母的未量化限制（**必须随结论声明**）")
        L.append("")
        L.append(f"{LEGACY_VDIFF_LIMITATION}")
        L.append("")
        L.append("- **不得**用任何电气量把该偏差『算出来』：电气量已因 LT0-C 被整体排除。")
        L.append("- **不得**编造 `V_outer`；本目录内**没有**该数值。")
    L.append("")
    return "\n".join(L)


def write_manifest(out_dir: Path, args, src: Path, src_sha: str) -> None:
    # 排除以 `_` 开头的辅助子目录（守卫验证、快照、参数化演示等），只登记本次运行的产物与 inputs
    files = sorted(p for p in out_dir.rglob("*")
                   if p.is_file() and p.name != "lt3_manifest.json"
                   and not any(part.startswith("_") for part in p.relative_to(out_dir).parts))
    man = {
        "kind": "lt3_prep_manifest",
        "tool": "work/tools/lt3_prep.py",
        "tool_sha256": sha256_file(Path(__file__).resolve()),
        "source_run_id": args.source_run_id,
        "source_file": str(src),
        "source_file_sha256": src_sha,
        "formal_ranking_authorized": FORMAL_RANKING_AUTHORIZED,
        "status": PROVISIONAL_STATUS,
        "artifacts": [{"path": str(p), "relative": str(p.relative_to(out_dir)),
                       "bytes": p.stat().st_size, "sha256": sha256_file(p)} for p in files],
    }
    (out_dir / "lt3_manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
