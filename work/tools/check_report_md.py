# -*- coding: utf-8 -*-
"""交付版 md 报告的自检：路径存在性、代码块闭合、措辞红线、指纹。

为什么需要它：报告要发给外部审阅方，**里面引用的每个仓库路径都必须真实存在**，
否则对方无法核验；代码围栏（```）不成对会让渲染错乱；红线措辞一旦泄漏到报告里
（例如把"代理"说成"AI 求解器"）就是事故。这些都能静态查出来。

用法：python -B work/tools/check_report_md.py docs/<报告>.md [更多.md ...]
"""
from __future__ import annotations

import hashlib
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]

#: 报告中**不得出现**的措辞（红线：代理不是求解器）。
#: ⚠️ 但**禁止声明本身必须允许出现**（"不得称 AI 求解器/免 COMSOL 出解"）——
#: 所以按**行**判断：该行若含否定词，则视为"声明禁止"，不算违规。
FORBIDDEN = ("免 COMSOL 出解", "已验证等价", "可以替代 COMSOL", "solver_certified",
             "AI 求解器", "AI求解器")
#: 否定语境标记（出现在同一行即认为是"在声明禁止/未做"，而不是"在宣称能力"）
NEGATION = ("不得", "禁止", "不是", "非求解器", "红线", "不可", "避免", "不许", "≠",
            "未讨论", "未涉及", "尚未", "未做", "待")

PATH_RE = re.compile(r"`((?:work|docs|src|scripts|tests|schemas)/[^`\s]+?)`")
#: 取「路径」后面的紧跟上下文，用于识别**已声明的**例外
PATH_CTX_RE = re.compile(r"`((?:work|docs|src|scripts|tests|schemas)/[^`\s]+?)`([^\n]{0,60})")
#: 路径后 60 字内出现这些词 ⇒ 作者**已声明**该路径不存在/已更正，不计入"缺失"判定。
#: 目的：允许文档**如实留痕**一个已知失效的引用，而不是逼作者把名字藏起来
#: （藏起来才是真正危险的做法——读者会以为该引用可用）。
DISCLOSED_MISSING = ("不存在", "缺失", "已更正", "已注明", "无从核对")


#: 疑问句标记：在提问（"如何把 X 从 fail 推进到 partial？"）**不是**在宣称可用。
QUESTION = ("？", "?", "是否", "多少", "哪个", "如何", "请给", "能不能")
#: 否定/疑问只看**当行 + 前 3 行**：markdown 列表项常从上一级标题/引导句继承否定
#: （实测：`- **任何"AI 求解器可用/已验证"**的说法` 位于「### 6.2 不可信 / 不得声称」之下，
#:  只看当行必误判为"违规宣称"）。窗口内命中的行会**单独列出**，不静默放过。
CTX_BACK = 3


def contextual_hits(t: str) -> tuple[list[tuple[int, str, str]], list[tuple[int, str, str]]]:
    """返回 (违规行, 声明禁止/疑问的行)。

    违规 = 含禁用措辞，且**当行与前 3 行**内都没有否定词、也不是疑问句。
    """
    bad, declared = [], []
    lines = t.splitlines()
    for i, line in enumerate(lines, 1):
        for w in FORBIDDEN:
            if w not in line:
                continue
            win = lines[max(0, i - 1 - CTX_BACK):i]
            if any(n in win[j] for j in range(len(win)) for n in NEGATION):
                declared.append((i, w, "[上文否定] " + line.strip()[:100]))
            elif any(q in line for q in QUESTION):
                declared.append((i, w, "[疑问句] " + line.strip()[:100]))
            else:
                bad.append((i, w, line.strip()[:110]))
    return bad, declared


def check(p: pathlib.Path, profile: str = "report") -> tuple[bool, list[str]]:
    msgs: list[str] = []
    if not p.is_file():
        return False, ["文件不存在：%s" % p]
    raw = p.read_bytes()
    t = raw.decode("utf-8")
    msgs.append("字节 %d ｜ 行 %d ｜ sha256 %s"
                % (len(raw), len(t.splitlines()), hashlib.sha256(raw).hexdigest()[:16]))
    fences = t.count("```")
    msgs.append("代码围栏 ``` 计数 = %d（必须为偶数）%s" % (fences, "" if fences % 2 == 0 else "  **不闭合**"))
    bad, declared = contextual_hits(t)
    msgs.append("**违规措辞（无否定语境的宣称）** = %s" % (bad if bad else "（无）"))
    for i, w, line in bad:
        msgs.append("    L%-4d [%s] %s" % (i, w, line))
    msgs.append("声明为禁止的措辞（合规） = %d 处" % len(declared))
    for i, w, line in declared[:6]:
        msgs.append("    L%-4d [%s] %s" % (i, w, line))
    refs = sorted(set(PATH_RE.findall(t)))
    # ⚠️ **通配/花括号/竖线写法是"模式"不是"具体路径"**，不能拿 `exists()` 判缺失
    # （否则 `work/runs/**`、`remote_{inventory,headers,params}.sh` 会被报成"缺失路径"，
    #  把一篇本来合规的报告判成不通过 —— 2026-09-29 实测的假阳性）。
    # 这类模式单独列出并**不计入**判定，但必须显示出来，避免"悄悄放过真缺失"。
    is_pattern = lambda r: any(ch in r for ch in "*?{}[]|")
    concrete = [r for r in refs if not is_pattern(r)]
    patterns = [r for r in refs if is_pattern(r)]
    # ⚠️ `path::symbol`（pytest 节点 id 风格）指向的是**文件里的符号**：
    # 判存在性只能查 `::` 之前那段，否则 `tests/x.py::CONST` 会被报成"缺失路径"
    # （2026-09-29 实测的假阳性）。符号部分单独列出，便于人工核对。
    symbols = {r: r.split("::", 1)[1] for r in concrete if "::" in r}
    files_only = [r.split("::", 1)[0] for r in concrete]
    concrete, seen = [], set()
    for f in files_only:
        if f not in seen:
            seen.add(f)
            concrete.append(f)
    # ⚠️ 同一个路径在文中可能出现多次（原文 + 更正注记）。必须取**所有**出现处的上下文，
    # 只要**任意一处**声明了失效就算"已声明"——用 setdefault 只留第一处会让更正注记失效
    # （2026-09-29 实测：更正写在原文之后，却被原文那次的上下文覆盖）。
    ctx: dict[str, str] = {}
    for m in PATH_CTX_RE.finditer(t):
        ctx[m.group(1)] = ctx.get(m.group(1), "") + " " + m.group(2)
    hard_missing = [r for r in concrete if not (REPO / r).exists()]
    disclosed = [r for r in hard_missing
                 if any(k in ctx.get(r, "") for k in DISCLOSED_MISSING)]
    missing = [r for r in hard_missing if r not in disclosed]
    msgs.append("引用的**具体**仓库路径 %d 个，缺失 %d 个%s"
                % (len(concrete), len(missing), ("：" + ", ".join(missing)) if missing else ""))
    if disclosed:
        msgs.append("已声明的失效引用 %d 个（**不计入判定**，但必须留痕）：%s"
                    % (len(disclosed), ", ".join(disclosed)))
    if patterns:
        msgs.append("通配/多选模式 %d 个（不判存在性）：%s"
                    % (len(patterns), ", ".join(patterns[:6])))
    if symbols:
        msgs.append("文件内符号引用 %d 个（只校验文件存在）：%s"
                    % (len(symbols), ", ".join("%s::%s" % (k.split("::", 1)[0], v)
                                               for k, v in list(symbols.items())[:4])))
    heads = [l for l in t.splitlines() if l.startswith("## ")]
    msgs.append("二级标题 %d 个" % len(heads))
    if profile == "records":
        # 历史记录/日志（如 `INDEX-records-and-rulings.md`）**必然**要写出任务名
        # 「AI 求解器第 4 步」、文件名、以及 `solver_certified=false` 这类否定状态。
        # 措辞规则是为**报告**设计的（防"宣称能力"），套到记录上只会产生成片假阳性
        # ⇒ records 档下措辞规则**只提示、不判失败**，并显式说明，避免被误读为"已通过"。
        if bad:
            msgs.append("（records 档：措辞规则**仅提示、不判失败**——记录里出现"
                        "「AI 求解器第 N 步」等任务名与 `solver_certified=false` 属正常）")
        ok = fences % 2 == 0 and not missing and len(heads) >= 3
    else:
        ok = fences % 2 == 0 and not bad and not missing and len(heads) >= 3
    return ok, msgs


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    profile = "report"
    if "--records" in argv:
        profile = "records"
        argv = [a for a in argv if a != "--records"]
    if not argv:
        print("用法：python -B work/tools/check_report_md.py <报告.md> [...] [--records]")
        print("  --records：**非报告类文档**（历史记录 / 计划 / 需求 / 任务书）。")
        print("     措辞规则**仅提示不判失败**：这类文档必然要**点名**计划中的组件")
        print("     （如「AI 求解器」「免 COMSOL 出解」是**待交付项的名字**，不是能力宣称），")
        print("     以及 `solver_certified=false` 这类否定状态。")
        print("     **路径存在性与代码围栏仍然强制**。")
        return 2
    all_ok = True
    for a in argv:
        p = pathlib.Path(a)
        if not p.is_absolute():
            p = REPO / a
        print("== %s ==" % p.name)
        ok, msgs = check(p, profile=profile)
        for m in msgs:
            print("   " + m)
        print("   判定：%s%s" % ("**通过**" if ok else "**不通过**",
                                "（records 档）" if profile == "records" else ""))
        all_ok = all_ok and ok
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
