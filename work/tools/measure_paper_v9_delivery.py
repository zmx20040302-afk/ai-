# -*- coding: utf-8 -*-
"""论文 v9 交付的**独立**测量（只读；不复用被中断那一条线的 verify_v9.py 逻辑）。

为什么另写一份：v9 的生成器与校验器出自同一条执行线，而该线**在写记录侧之前被中断**
（见 `PAPER_REVISION_LOG` §P.0 / `INDEX §156`）。对「交付是否完整、旧版本是否被动过、
锚点是否悬空」这类判断，必须换一份独立实现复算，而不是复述生产者自己的自检。

本脚本**只读**：不写任何被测量对象；唯一写入是 `--out` 指定的 JSON（缺省落在
`work\\tmp\\paper-v9-20261010\\delivery_measurements.json`）。

用法：
    work\\.venv\\Scripts\\python.exe -X utf8 work\\tools\\measure_paper_v9_delivery.py
    work\\.venv\\Scripts\\python.exe -X utf8 work\\tools\\measure_paper_v9_delivery.py --out <path>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import time

REPO = pathlib.Path(__file__).resolve().parents[2]
DOCS = REPO / "docs"

V1 = (pathlib.Path(r"C:\Users\zmx\.dsh\attachments\v1\files\37")
      / "3799b0a84abf5e7f119dba2dfb41f2e80c86d6ffc271c3b43ec27a9e62874513"
      / "PMUT_DAC2027方法论文初稿_v1_20261009.md")

VERSIONS = [
    ("v1", V1),
    ("v2", DOCS / "PMUT_DAC2027_初稿_v2_20261009.md"),
    ("v3", DOCS / "PMUT_DAC2027_初稿_v3_20261009.md"),
    ("v4", DOCS / "PMUT_DAC2027_初稿_v4_20261009.md"),
    ("v5", DOCS / "PMUT_DAC2027_初稿_v5_20261009.md"),
    ("v6", DOCS / "PMUT_DAC2027_初稿_v6_20261009.md"),
    ("v7", DOCS / "PMUT_DAC2027_初稿_v7_20261009.md"),
    ("v8", DOCS / "PMUT_DAC2027_初稿_v8_20261009.md"),
    ("v9", DOCS / "PMUT_DAC2027_初稿_v9_20261010.md"),
]

#: 既有登记值（来自 INDEX §151 / §145 / 交付链，用于「旧版本有没有被动过」的独立比对）
REGISTERED = {
    "v1": (29333, 448, "3799b0a84abf5e7f119dba2dfb41f2e80c86d6ffc271c3b43ec27a9e62874513"),
    "v2": (62516, 600, "329b3f942a5e54c6db99203c2fd5566e4f5b7c5e89806b2929ea23fc1db6e5e3"),
    "v3": (65357, 620, "76e274a8924f237891839312d00a104b9e4dd2df8aad01cb63d81d6f7bdda94c"),
    "v4": (66678, 622, "4472aa5b7e86528d2bc05d6f68c284cc45bc96b9eb1ec29b674c4e48374dce55"),
    "v5": (75057, 627, "9a488db5536fc36da76aab22e7554649543883492565dd9d08e4104075ba6d08"),
    "v6": (102590, 700, "07628a5814df1dc716f4e5628f7022ef7925ea3b72fc8dedad3b87b970f68ed0"),
    "v7": (117054, 705, "139f6e0ab70912f2a0c4509611148c8120fb76674efe336a417b1028b4d81207"),
    "v8": (152984, 744, "404354510dd4521bcc34289dfb625ff97e2b93b4a37773e46aa5268fa10a60b8"),
    "v9": (161772, 746, "7f9525961d32f020bb49d47637a9491defe2f3ec331e8adf6c913c2626b10a89"),
}

#: 这些「v8 旧事实」在 v9 里只能以**被标注为历史**的形式出现（逐处人工判据见 STALE_MARKERS）
STALE = ["2.272", "1.685", "≈1.77%", "0.827 ⇒", "8 档 / 56 有序对", "λ/11 在跑", "λ/11 已在跑",
         "l/11 已在跑"]
#: 出现同一行内若含下列任一 token，则该处**已按历史/禁止口径标注**（否则是「当现状陈述」的残留）
STALE_MARKERS = ["已更新", "已解除", "旧事实", "历史", "不得再", "取代", "v8 的"]
#: 另一种合规形态：把旧值写成**迁移的起点**（`旧值 → 新值` 或 `由 旧值 更新为 新值`）。
#: 实测案例：v9 L532「裁定集 8 档 / 56 有序对 → 9 档…/ 72 个有序对」——旧值只作 from 端出现。
STALE_TRANSITION = r"(?:{kw}\s*(?:→|->)|由\s*{kw})"

S4_CHECKS = [
    ("9 档 / 72 有序对", "9 档 / 72 有序对"),
    ("关键区 0.6753%", "0.6753%"),
    ("全域 1.5504%", "1.5504%"),
    ("最差对 ftet_l11 over combo_l7", "`ftet_l11` over `combo_l7`"),
    ("d_last 0.3792%", "0.3792%"),
    ("比值 0.7663", "0.7663"),
    ("比值 0.7907", "0.7907"),
    ("比值 0.7701", "0.7701"),
    ("比值 0.8270", "0.8270"),
    ("比值 0.7978", "0.7978"),
    ("R_est 1.3446%", "1.3446%"),
    ("R_est 1.4300%", "1.4300%"),
    ("R_est 1.4963%", "1.4963%"),
    ("全阶梯均值 0.7904", "0.7904"),
    ("λ/12 预测 0.3026%", "0.3026%"),
    ("单元 664,840", "664,840"),
    ("顶点 119,163", "119,163"),
    ("DOF 1,000,631", "1,000,631"),
    ("网格 6.04 s", "6.04 s"),
    ("buildoutput (16414, 652912)", "(16414, 652912)"),
    ("回归靶 §111 六档 0.013847", "0.013847"),
    ("回归靶 §145 八档 0.015152", "0.015152"),
    ("预算 304 s / 49.45 GB", "304 s / 49.45 GB"),
    ("上界 360 s / 60 GB", "360 s / 60 GB"),
    ("3.58×", "3.58×"),
    ("占上界 84%", "占上界 84%"),
    ("重启混淆项 20:04", "20:04"),
    ("未主张候选原因", "不主张任何一个"),
    ("源模型 sha 0f75ca1d…9552d", "0f75ca1df9262f27a79d69e4e1ede4f4ac321a2e1c14b4ccdadf4f07df09552d"),
    ("设计点 0.5 / 4 / 8", "`x = 0.5 / N1 = 4 / N2 = 8`"),
    ("不得声称网格无关", "不得声称网格无关"),
]


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def read_bytes(p: pathlib.Path) -> bytes:
    return p.read_bytes()


def line_of(txt: str, pos: int) -> int:
    return txt.count("\n", 0, pos) + 1


def audit_anchor(txt: str, heading: str) -> bool:
    """严格锚点存在性：**行首**匹配 `heading`（其后为行尾或空白）。

    不能用 `heading in txt`（子串包含），也不能用宽松正则 `^#+ P[\\s.]` —— 后者在本仓库
    实测会**假阳性**（`## M.` 一节正文里的行被误判为 `P` 节）。判据必须是完整标题行。
    """
    for ln in txt.split("\n"):
        if ln.startswith(heading) and len(ln) > len(heading):
            nxt = ln[len(heading)]
            if nxt.isspace():
                return True
        elif ln == heading:
            return True
    return False


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="论文 v9 交付的独立测量（只读）")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    out = pathlib.Path(args.out) if args.out else (
        REPO / "work" / "tmp" / "paper-v9-20261010" / "delivery_measurements.json")

    res: dict = {"generated": time.strftime("%Y-%m-%d %H:%M:%S"), "measurement": "parents[2]=repo root, read-only"}

    # ---- A. 九版哈希 / 字节 / 行数（旧版本有没有被动过）----
    vers = {}
    for name, p in VERSIONS:
        b = read_bytes(p)
        txt = b.decode("utf-8")
        n_lines = len(txt.split("\n"))
        if txt.endswith("\n"):
            n_lines -= 1                      # read 工具口径：以换行结尾时行数 = 分隔符数
        eb, el, eh = REGISTERED[name]
        vers[name] = {
            "path": str(p), "bytes": len(b), "lines": n_lines,
            "sha256": sha256_bytes(b), "mtime": time.strftime(
                "%Y-%m-%d %H:%M:%S", time.localtime(p.stat().st_mtime)),
            "registered_bytes": eb, "registered_lines": el, "registered_sha256": eh,
            "match_registered": (len(b) == eb and n_lines == el and sha256_bytes(b) == eh),
        }
    res["versions"] = vers
    res["all_versions_match_registered"] = all(v["match_registered"] for v in vers.values())

    # ---- B. v9 行尾与 v8→v9 的编辑清单 ----
    b9 = read_bytes(VERSIONS[-1][1])
    b8 = read_bytes(VERSIONS[-2][1])
    t9, t8 = b9.decode("utf-8"), b8.decode("utf-8")
    res["v9_line_endings"] = {
        "LF": b9.count(b"\n"), "CRLF": b9.count(b"\r\n"), "CR": b9.count(b"\r"),
        "pure_crlf": b9.count(b"\n") == b9.count(b"\r\n") == b9.count(b"\r")}
    l8 = t8.split("\n")[:-1]
    l9 = t9.split("\n")[:-1]
    replaced = [i + 1 for i, ln in enumerate(l8) if ln not in l9]
    res["edit_inventory"] = {
        "v8_lines": len(l8), "v9_lines": len(l9), "net_line_delta": len(l9) - len(l8),
        "v8_lines_verbatim_present_in_v9": len(l8) - len(replaced),
        "replaced_line_numbers": replaced, "n_replaced": len(replaced),
        "note": "「被替换」= v8 该行不再逐字出现在 v9 中（可能被改写，也可能是同一行被追加内容）；"
                "本口径不能区分「改写」与「同行追加」。",
    }

    # ---- C. 标记计数与逐处位置 ----
    marks = {}
    for mk in ("【待裁定】", "【待产物】", "【待补】"):
        pos = [(line_of(t9, m.start()), t9[m.start():m.start() + 60].split("\n")[0])
               for m in re.finditer(re.escape(mk), t9)]
        marks[mk] = {"total": t9.count(mk), "positions": pos}
    res["markers_v9"] = marks
    res["markers_v8"] = {mk: t8.count(mk) for mk in ("【待裁定】", "【待产物】", "【待补】")}

    # ---- D. v8 旧事实残留：逐处 + 是否已按历史口径标注 ----
    stale = {}
    for kw in STALE:
        occ = []
        l9_lines = t9.split("\n")
        for m in re.finditer(re.escape(kw), t9):
            ln = line_of(t9, m.start())
            line = l9_lines[ln - 1]
            occ.append({"line": ln,
                        "annotated_as_history": (
                            any(x in line for x in STALE_MARKERS)
                            or bool(re.search(STALE_TRANSITION.format(kw=re.escape(kw)), line))),
                        "ctx": line[:220]})
        stale[kw] = {"count": t9.count(kw), "occurrences": occ,
                     "all_annotated": bool(occ) and all(o["annotated_as_history"] for o in occ)}
    res["stale_facts"] = stale
    res["stale_all_annotated"] = all(
        (v["count"] == 0) or v["all_annotated"] for v in stale.values())

    # ---- E. S4 新事实是否逐条落地 ----
    res["s4_facts"] = {label: t9.count(needle) for label, needle in S4_CHECKS}
    res["s4_all_present"] = all(c >= 1 for c in res["s4_facts"].values())

    # ---- F. 状态锚点（不得提升）----
    sp = REPO / "work" / "runs" / "solver" / "pmut-f1" / "solver_spec.json"
    mp = REPO / "work" / "runs" / "multichannel-surrogate-20260929" / "multichannel_model.json"
    sb, mb = read_bytes(sp), read_bytes(mp)
    sj, mj = json.loads(sb.decode("utf-8")), json.loads(mb.decode("utf-8"))
    res["state_anchors"] = {
        "solver_spec": {"bytes": len(sb), "sha256": sha256_bytes(sb), "state": sj.get("state")},
        "multichannel_model": {
            "bytes": len(mb), "sha256": sha256_bytes(mb), "status": mj.get("status"),
            # ⚠️ 口径：该字段**不在顶层**。顶层探 `channels_without_lift` 会得到「键不存在」（None）；
            # 真实位置是 `evaluation.channels_without_lift`（实测）。引用模型内字段**必须给路径**，
            # 否则「键不存在」与「值为空」会被混为一谈（本仓库同类纪律：状态必须是测量出来的）。
            "channels_without_lift_toplevel_present": "channels_without_lift" in mj,
            "channels_without_lift_path": "evaluation.channels_without_lift",
            "channels_without_lift": ((mj.get("evaluation") or {}).get("channels_without_lift")
                                      if isinstance(mj.get("evaluation"), dict) else None),
        },
        "both_draft": sj.get("state") == "draft" and mj.get("status") == "draft",
    }

    # ---- G. 引用锚点审计（悬空锚点 = 交付缺陷）----
    log = (DOCS / "PAPER_REVISION_LOG_20261009.md").read_text(encoding="utf-8")
    idx = (DOCS / "INDEX-records-and-rulings.md").read_text(encoding="utf-8")
    log_cites = sorted(set(re.findall(r"PAPER_REVISION_LOG[^§\n]{0,6}§([A-Z](?:\.\d+)?)", t9)))
    idx_cites = sorted(set(re.findall(r"INDEX §(\d+)", t9)), key=int)
    log_audit = {c: audit_anchor(log, "## %s." % c) if "." not in c
                 else audit_anchor(log, "### %s" % c) for c in log_cites}
    idx_audit = {c: audit_anchor(idx, "## %s." % c) for c in idx_cites}
    res["citation_audit"] = {
        "log_sections_cited": log_cites, "log_sections_present": log_audit,
        "log_dangling": [c for c, ok in log_audit.items() if not ok],
        "log_top_sections_present": sorted(set(re.findall(r"(?m)^## ([A-Z])\.", log))),
        "index_sections_cited": idx_cites, "index_sections_present": idx_audit,
        "index_dangling": [c for c, ok in idx_audit.items() if not ok],
        "index_max_section": max(int(x) for x in re.findall(r"(?m)^## (\d+)\.", idx)),
        "index_mentions_v9": "v9" in idx,
    }

    # ---- H. 本轮产物哈希 ----
    arts = {}
    for label, p in [("paper_v9", VERSIONS[-1][1]),
                     ("generator", REPO / "work" / "tools" / "make_dac2027_v9_s4.py"),
                     ("verifier", REPO / "work" / "tmp" / "paper-v9-20261010" / "verify_v9.py"),
                     ("revision_log_before", DOCS / "PAPER_REVISION_LOG_20261009.md"),
                     ("index_before", DOCS / "INDEX-records-and-rulings.md")]:
        b = read_bytes(p)
        arts[label] = {"path": str(p), "bytes": len(b), "sha256": sha256_bytes(b),
                       "mtime": time.strftime("%Y-%m-%d %H:%M:%S",
                                              time.localtime(p.stat().st_mtime))}
    res["artifacts"] = arts

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes((json.dumps(res, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))

    verdict = (res["all_versions_match_registered"] and res["v9_line_endings"]["pure_crlf"]
               and res["stale_all_annotated"] and res["s4_all_present"]
               and res["state_anchors"]["both_draft"])
    print("== 九版哈希：%s" % ("全部与登记值逐位一致" if res["all_versions_match_registered"] else "有不一致"))
    print("== v9 行尾纯 CRLF：%s；v8→v9 行数 %d → %d（净 %+d）；被替换行 %d 行"
          % (res["v9_line_endings"]["pure_crlf"], len(l8), len(l9), len(l9) - len(l8), len(replaced)))
    print("== 标记：v9 %s（v8 %s）" % (res["markers_v9"]["【待产物】"]["total"], res["markers_v8"]["【待产物】"]))
    print("== 旧事实残留全部已按历史口径标注：%s" % res["stale_all_annotated"])
    print("== S4 新事实全部落地：%s" % res["s4_all_present"])
    print("== 状态仍 draft：%s" % res["state_anchors"]["both_draft"])
    print("== 悬空引用：log %s ／ INDEX %s" % (res["citation_audit"]["log_dangling"] or "无",
                                             res["citation_audit"]["index_dangling"] or "无"))
    print("== INDEX 是否已有 v9 登记：%s（现行最大节 = §%d）"
          % (res["citation_audit"]["index_mentions_v9"], res["citation_audit"]["index_max_section"]))
    print("== 产物：%s" % out)
    print("MEASURE_%s" % ("OK" if verdict else "ATTENTION"))
    return 0 if verdict else 2


if __name__ == "__main__":
    raise SystemExit(main())
