"""COMSOL 求解失败分类（诊断码 + 处置建议 + 是否可重试）。

设计原则（AGENTS.md 红线 1/3）：分类只能依据**实际读到的日志/退出码文本**，
不得根据「一般是网格问题」这类惯例凭空归因。因此每个诊断结果都带上
``evidence``（命中的原文片段）与 ``matched_pattern``，便于人工复核。

分类码（``code``）：
- ``timeout``      超出时限被终止
- ``license``      许可证不可用 / 检出失败
- ``connection``   mphserver / 客户端-服务端连接失败
- ``out_of_memory``内存不足
- ``geometry``     几何构建失败或退化
- ``mesh``         网格未生成或网格错误
- ``selection``    选择集为空 / 失效
- ``convergence``  求解器不收敛（残差停滞、奇异矩阵、迭代上限）
- ``api``          脚本/API 属性错误（参数未定义、属性值不兼容）
- ``artifact``     求解结束但没有产出预期文件
- ``unknown``      未分类（必须看完整日志）

判定顺序说明：license 先于 connection（许可证服务器错误常同时含 "cannot connect"），
out_of_memory 先于 convergence（内存耗尽也会报 solver 失败），
geometry/mesh/selection 先于 convergence（设置错常被误报成不收敛）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

__all__ = ["Diagnosis", "RULES", "classify_failure", "retry_plan"]


@dataclass(frozen=True)
class Diagnosis:
    """一条失败分类结果。"""

    code: str
    title: str
    summary: str
    actions: tuple[str, ...]
    retryable: bool
    stage: str
    matched_pattern: str | None = None
    evidence: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "title": self.title,
            "summary": self.summary,
            "actions": list(self.actions),
            "retryable": self.retryable,
            "stage": self.stage,
            "matched_pattern": self.matched_pattern,
            "evidence": self.evidence,
        }


# 规则表：按顺序匹配，先命中先返回。正则一律忽略大小写，对中文与英文同时覆盖。
RULES: tuple[tuple[str, str, str, tuple[str, ...], bool, str], ...] = (
    (
        "timeout",
        "求解超时",
        "任务在配置的时限内未完成；常见原因是网格过密、非线性过强或求解器收敛困难。",
        (
            "先在粗网格上跑基线，确认模型本身可解。",
            "查看 batchlog 中最后一次残差/时间步，判断是「慢」还是「卡」。",
            "确认可解后再放宽时限重试，并把时限调整记录进 run.settings。",
        ),
        True,
        r"timed?\s*out|timeout|超时|time limit exceeded|stoptime|killed after",
    ),
    (
        "license",
        "COMSOL 许可证错误",
        "许可证不可用、已用尽或未包含本模型所需模块。",
        (
            "检查 licenseinfo.ini 与本机 license.dat 的有效期。",
            "确认没有其它进程占用并发许可（本平台要求单实例串行）。",
            "确认所需模块（如 Heat Transfer）在授权清单内。",
            "许可证恢复后可直接重试。",
        ),
        True,
        r"license|licen[cs]e|许可证|授权|error\s*-?\s*(9|15|96)\b|license manager|检出.*失败",
    ),
    (
        "out_of_memory",
        "内存不足",
        "求解进程无法分配内存（OutOfMemory / Failed to allocate）。",
        (
            "降低自由度：用对称性降维、改 2D 轴对称、移除无关域。",
            "粗化网格或改用低阶单元，并记录精度影响。",
            "改迭代求解器 + 预条件子替代直接求解器。",
            "必要时改用更高内存机器或 remote 后端（当前未实现）。",
        ),
        True,
        r"out\s*of\s*memory|outofmemoryerror|failed to allocate|cannot allocate|内存不足|not enough memory|swap",
    ),
    (
        "geometry",
        "几何构建失败",
        "几何无法构建，或参数取值产生退化/自相交几何。",
        (
            "检查参数是否使厚度/间隙趋近 0。",
            "检查布尔运算顺序与容差。",
            "几何修复后必须重新核对全部选择集。",
            "该参数区间应显式排除并记录。",
        ),
        False,
        # 收紧前的规则里含裸子串 ``geometr`` 与裸汉字 ``几何``，会把**正常行**判成几何失败
        # （实测两例，见文件末尾「几何规则误报」注释）：
        #   1) 稳态成功运行的 batchlog 第 32 行原样写着「几何形函数: 二次拉格朗日单元」；
        #   2) 失败信息块里有字段行「- Geometry: geom1」（那是**发生问题的域所属几何名**，
        #      不是几何构建失败），当时的真错因是材料引用了未定义变量 comp1.mat1.def.E。
        # 现在只保留"几何构建失败"本身的措辞，不再用裸词兜底。
        r"geometry could not be built|could not be built.*geometr|"
        r"failed to (build|create|generate).{0,20}geometr|"
        r"invalid geometr|ill-formed geometr|self-?intersect|zero-?thickness|"
        r"degenerate (geometr|entit|domain|edge|face)|"
        r"geometry (is )?(empty|invalid)|"
        r"几何(构建|建模|创建|生成)?(失败|错)|无法(构建|创建|生成)几何|几何不合法|"
        r"几何数据无效|没有有效几何|实体数量为 ?0|no domains",
    ),
    (
        "mesh",
        "网格错误",
        "网格未生成、网格质量不足或元素导致求解失败。",
        (
            "确认几何已构建且网格序列对正确维度操作。",
            "先用粗网格验证边界与物理场，再逐步加密。",
            "检查最小单元质量、偏斜度与负体积单元。",
        ),
        False,
        r"\bmesh\b|mesh(ing)? failed|element quality|inverted element|网格|没有有效网格|no elements",
    ),
    (
        "selection",
        "选择集为空或失效",
        "边界条件/材料指派绑定的选择集没有实体，或被静默改变。",
        (
            "回到图形窗口逐个核对选择集（SOP 第 4 节）。",
            "几何改动后重建选择集，优先用与拓扑无关的选择方式。",
            "修复后必须重跑该点全部求解，不得复用旧结果。",
        ),
        False,
        r"selection is empty|empty selection|selection.*(empty|invalid)|选择集|no entities selected",
    ),
    (
        "convergence",
        "求解器不收敛",
        "残差停滞或振荡、矩阵奇异、达到迭代上限。",
        (
            "先确认几何/边界/选择集正确（收敛问题常源于设置错误）。",
            "检查是否存在刚体位移或悬浮域（缺约束）。",
            "改逐步加载、更初值或更换求解器，并记录改动。",
            "放宽容差必须记录，不得静默修改。",
            "仍失败则作为负样本入库，不伪造结果。",
        ),
        True,
        r"did not converge|not converged|failed to converge|nonlinear solver|singular matrix|"
        r"maximum number of iterations|residual|不收敛|求解器.*失败|ill-conditioned",
    ),
    (
        "connection",
        "COMSOL 服务连接失败",
        "无法连接 mphserver 或客户端-服务端通路中断。",
        (
            "先探测 127.0.0.1:2036 是否监听（env.tcp_probe）。",
            "确认 comsolmphserver 进程存活且版本与批处理一致。",
            "服务恢复后可重试。",
        ),
        True,
        r"mphserver|connection refused|cannot connect|unable to connect|connect(ion)? (failed|error)|"
        r"无法连接|连接失败|socket|broken pipe|server.*not.*running",
    ),
    (
        "api",
        "脚本/API 属性错误",
        "脚本引用了不存在的变量、参数或属性值不被当前版本接受。",
        (
            "核对参数名、单位表达式与物理场属性键。",
            "避免使用与 COMSOL 内部变量冲突的名字（如 E、T、k）。",
            "读取本机原生示例的同一节点属性后修正生成器。",
        ),
        False,
        r"undefined variable|unknown parameter|invalid (property|parameter|value)|"
        r"not a valid|unrecognized|api.*error|未定义|参数值无效|未知参数|compilation failed|"
        r"error:\s|cannot find symbol|class, interface",
    ),
    (
        "artifact",
        "缺少预期产物",
        "求解流程结束但没有得到预期的输出文件。",
        (
            "检查输出目录写权限与产物路径。",
            "确认 model.save() 的目标路径在工作目录内。",
            "查看 batch 日志末尾判断是否提前退出。",
        ),
        True,
        r"artifact|output file.*(missing|not found)|no such file|file not found|未生成|找不到文件",
    ),
)

_COMPILED: tuple[tuple[re.Pattern[str], tuple[str, str, str, tuple[str, ...], bool]], ...] = tuple(
    (re.compile(pattern, re.IGNORECASE), (code, title, summary, actions, retryable))
    for code, title, summary, actions, retryable, pattern in RULES
)

# 从日志中截取多少字符作为证据片段
EVIDENCE_WINDOW = 400

# 识别性噪声行（**不是错误**，但含"几何/网格"字眼，会污染 geometry/mesh 规则）。
# 实测依据：
#   1) 成功运行的 batchlog 第 32 行：「几何形函数: 二次拉格朗日单元」
#      —— 这是"单元几何阶数"的说明行，与几何构建无关（run-20260911T013113Z-1a25aa9f）；
#   2) Java 属性名 ``geometricNonlinearity``（几何非线性开关）；
#   3) batchlog 的**进度行**：「           当前进度:   0 % - 自由三角形网格 1」之类
#      —— 与成功与否无关的信息行，命中 mesh 规则（"网格"）造成误报；
#   4) 本模块自己写在 stdout 上的标记行（探针的诊断数据，不是求解器输出）。
# 用「等同长度空白」替换而不是删行：保持字符下标不变，证据片段仍能定位回原文。
_NOISE_LINE_RE = re.compile(
    r"[^\n]*(?:"
    r"几何形函数|几何非线|geometric\s*nonlinearity|"
    r"当前进度\s*:|"
    r"MEMS_GEOMETRY=|MEMS_NAMED_SELECTIONS="
    r")[^\n]*",
    re.IGNORECASE,
)


def _evidence(text: str, match: re.Match[str]) -> str:
    """截取命中位置附近的原文，作为可复核证据。"""
    start = max(0, match.start() - EVIDENCE_WINDOW // 2)
    end = min(len(text), match.end() + EVIDENCE_WINDOW // 2)
    return text[start:end].strip()


def classify_failure(
    text: str | None,
    *,
    exit_code: int | None = None,
    stage: str = "execution",
) -> dict[str, Any]:
    """把失败文本分类成结构化诊断。

    参数：
        text: 日志文本（stdout/stderr/batchlog 拼接后的内容）。``None`` 视为空。
        exit_code: 进程退出码，仅用于记录，不参与猜测归因。
        stage: 发生阶段（``compile`` / ``batch`` / ``timeout`` / ``validate`` …）。

    返回：``Diagnosis.to_dict()`` 加 ``exit_code`` 与 ``text_length``。
    """
    raw = text or ""
    base: dict[str, Any] = {
        "stage": stage,
        "exit_code": exit_code,
        "text_length": len(raw),
    }
    # 阶段本身是超时（调用方用超时终止了进程），直接判 timeout，不进正则匹配
    if stage == "timeout":
        diag = Diagnosis(
            code="timeout",
            title="求解超时",
            summary="调用方在配置时限内终止了进程（未读到 COMSOL 自身的报错文本）。",
            actions=(
                "查看 batch 日志最后一行，判断是否仍在正常迭代。",
                "确认时限设置是否过紧（run.settings.timeout_seconds）。",
                "可重试：先降低网格密度跑通基线。",
            ),
            retryable=True,
            stage=stage,
            matched_pattern=None,
            evidence=None,
        )
        return {**diag.to_dict(), **base}

    # 噪声屏蔽 + 标记文本归一（实测依据：run-20260911T025541Z-0435e10f）
    # batchlog 在真实报错之后常追加 "java.net.SocketException: Connection reset"：
    # 那是模型类已跑完、桥接通道正常关闭时的噪声，不是失败原因。
    # 若直接用整段文本按顺序匹配，先命中的连接规则会把运行期 API 报错误判成 connection。
    # 因此：文本里存在 COMSOL 结构化报错时，连接类规则不参与匹配。
    comsol_block = (
        "FlException" in raw
        or "com.comsol.util.exceptions" in raw
        or re.search(r"(?m)^Messages:\s*$", raw) is not None
    )
    # worker 把异常写成单行 ERROR_MARKER::<Exception>（空格被替换为下划线），
    # 这里额外拼一份「去下划线」副本专供匹配，避免 Duplicate_variable_name 漏配。
    match_text = raw
    if "ERROR_MARKER::" in raw:
        marked = [
            line.split("ERROR_MARKER::", 1)[1]
            for line in raw.splitlines()
            if "ERROR_MARKER::" in line
        ]
        if marked:
            match_text = raw + "\n" + "\n".join(part.replace("_", " ") for part in marked)

    # 识别性噪声行：这些**不是错误**，但有"几何/网格"字眼，会让 geometry/mesh 规则误报。
    # 用「等同长度的空白」替换而不是删除，避免把相邻两行粘成一行、造出跨行的假匹配。
    masked = _NOISE_LINE_RE.sub(lambda m: " " * len(m.group(0)), match_text)
    scan_text = masked if masked.strip() else match_text

    for pattern, (code, title, summary, actions, retryable) in _COMPILED:
        if code == "connection" and comsol_block:
            continue
        match = pattern.search(scan_text)
        if match:
            diag = Diagnosis(
                code=code,
                title=title,
                summary=summary,
                actions=actions,
                retryable=retryable,
                stage=stage,
                matched_pattern=pattern.pattern,
                evidence=_evidence(match_text, match),
            )
            return {**diag.to_dict(), **base}

    diag = Diagnosis(
        code="unknown",
        title="未分类执行错误",
        summary="未命中任何已知规则；必须人工查看完整日志后再归因。",
        actions=(
            "打开 run_dir 下的完整 stdout/stderr/batchlog。",
            "定位日志中**最先出现**的错误行（后续错误常是其连锁反应）。",
            "在 diagnostics.py 的 RULES 中补一条规则并附上证据文本。",
        ),
        retryable=False,
        stage=stage,
        matched_pattern=None,
        evidence=raw[-EVIDENCE_WINDOW:] if raw else None,
    )
    return {**diag.to_dict(), **base}


def retry_plan(diagnosis: dict[str, Any], attempt: int = 1, max_attempts: int = 2) -> dict[str, Any]:
    """给出是否重试与如何重试（不执行任何改动，只是建议）。"""
    retryable = bool(diagnosis.get("retryable"))
    code = str(diagnosis.get("code") or "unknown")
    allowed = retryable and attempt < max_attempts and code != "unknown"
    return {
        "should_retry": allowed,
        "attempt": attempt,
        "max_attempts": max_attempts,
        "reason": (
            "可重试且未达上限"
            if allowed
            else (
                "该分类不可重试（需要先修正模型/脚本）"
                if not retryable
                else (
                    "已达重试上限"
                    if attempt >= max_attempts
                    else "未分类错误不自动重试（避免掩盖真实原因）"
                )
            )
        ),
        "code": code,
    }
