# -*- coding: utf-8 -*-
"""模型身份标识（裁定：SHA-256 作为最终硬标识）。

裁定来源（append-only）：
* `feedback` `fb-20260923T110333Z-e0a59352`（用户原话：同一模型、结构相同、只是改参数扫描）
* `feedback` `fb-20260923T142102Z-4bd9fd86`（接受 SHA-256 硬标识；哈希取得前 `base_model_id` 保持
  NULL 并标 `pending_sha256`；**不得用文件名冒充 `base_model_id`**）

层级（六个字段，各管一件事，不得互相替代）：

| 字段 | 是什么 | 现在有吗 |
|---|---|---|
| `base_model_id` | 公共基础模型/模板文件的 SHA-256 | **NULL**（`pending_sha256`） |
| `artifact_sha256` | 每个具体 `.mph` 的 SHA-256 | **NULL**（`pending_sha256`） |
| `configuration_id` | 材料/物理场/边界/电极/网格/研究设置的配置指纹 | **NULL**（`pending_profile`） |
| `parameter_set_id` | `x_scale`/`N_w_te1`/`N_w_te2` 组合的指纹 | ✅ **可算**（本模块） |
| `measurement_profile_id` | 测量点/面/表达式/单位的指纹 | **NULL**（`pending_profile`） |
| `run_id` | 单次求解/扫描标识 | ✅ 已有（`store.run.run_id`） |

**本模块的职责是"守卫"，不是"补值"**：拿不到哈希就保持 NULL，
绝不允许把文件名/路径塞进 `base_model_id` 来"看起来完整"。
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping, Sequence

HEX64 = re.compile(r"^[0-9a-f]{64}$")

#: `base_model_id` 允许的取值状态
STATUS_OK = "sha256_present"
STATUS_PENDING = "pending_sha256"
STATUS_PENDING_PROFILE = "pending_profile"

#: 身份字段（统一骨架里必须原样携带，不得被省略）
IDENTITY_FIELDS: tuple[str, ...] = (
    "base_model_id", "base_model_id_status", "artifact_sha256",
    "configuration_id", "parameter_set_id", "measurement_profile_id",
    "run_id", "identity_basis", "source_file", "source_path", "run_name",
)

#: 文件名/路径的痕迹（出现即判为"拿文件名冒充"）
_FILENAME_HINTS = (".mph", ".m", ".txt", ".csv", ".json", "/", "\\")


class IdentityViolation(ValueError):
    """身份字段被伪装（例如用文件名当 `base_model_id`）。"""


def is_sha256(value: Any) -> bool:
    return isinstance(value, str) and bool(HEX64.match(value.strip().lower()))


def assert_base_model_id(value: Any, *, field: str = "base_model_id") -> str | None:
    """校验 `base_model_id`：**只接受 64 位十六进制 SHA-256 或 NULL**。

    用途：把"不得用文件名冒充最终 base_model_id"这条裁定变成**代码事实**，
    而不是文档里的一句话。若传入 `foo.mph` / `path/to/model` / `cell_te2_9_v1` 等一律抛错。
    """
    if value is None or (isinstance(value, str) and value.strip() == ""):
        return None
    if not isinstance(value, str):
        raise IdentityViolation("%s 必须是 SHA-256 字符串或 None，收到 %r" % (field, type(value)))
    v = value.strip()
    if is_sha256(v):
        return v.lower()
    hint = next((h for h in _FILENAME_HINTS if h in v), None)
    raise IdentityViolation(
        "%s 收到非 SHA-256 值 %r%s ⇒ 拒绝（裁定：哈希取得前保持 NULL + pending_sha256，"
        "不得用文件名/路径冒充）" % (field, v, "（含 %r 痕迹）" % hint if hint else ""))


def pending_identity(*, identity_basis: str, source_file: str | None = None,
                     source_path: str | None = None, run_name: str | None = None,
                     run_id: str | None = None) -> dict[str, Any]:
    """哈希/配置指纹尚未取得时的**标准身份块**（全 NULL + 明确状态码）。"""
    return {
        "base_model_id": None,
        "base_model_id_status": STATUS_PENDING,
        "artifact_sha256": None,
        "configuration_id": None,
        "parameter_set_id": None,
        "measurement_profile_id": None,
        "run_id": run_id,
        "identity_basis": identity_basis,
        "source_file": source_file,
        "source_path": source_path,
        "run_name": run_name,
    }


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def stable_hash(obj: Any, *, n: int = 16) -> str:
    """对任意可 JSON 化对象取稳定短哈希（键序无关）。"""
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()[:n]


def parameter_set_id(params: Mapping[str, Any] | Sequence[Any]) -> str:
    """`x_scale`/`N_w_te1`/`N_w_te2` 组合的指纹。

    这是**能算的**：参数值本身就在数据里，不需要任何外部信息。
    浮点先规整到 1e-9，避免 0.30000000000000004 与 0.3 得到不同 id。
    """
    def norm(v: Any) -> Any:
        if isinstance(v, float):
            r = round(v, 9)
            return int(r) if r == int(r) else r
        if isinstance(v, int):
            return v
        return v
    if isinstance(params, Mapping):
        obj = {k: norm(v) for k, v in params.items()
               if k in ("x_scale", "N_w_te1", "N_w_te2")}
    else:
        obj = [norm(v) for v in params]
    missing = [k for k in ("x_scale", "N_w_te1", "N_w_te2") if k not in obj] \
        if isinstance(obj, dict) else []
    if missing:
        raise ValueError("parameter_set_id 缺参数：%s" % missing)
    return "ps-" + stable_hash(obj)


def measurement_profile_id(*, point_m: Sequence[float] | None = None,
                           surface: str | None = None,
                           expressions: Mapping[str, str] | None = None,
                           units: Mapping[str, str] | None = None) -> tuple[str | None, str]:
    """测量/输出定义的指纹。**拿不到定义就不给 id**（返回 `(None, pending_profile)`）。

    裁定要求"测量点/面/表达式/单位"四样齐全才算一个可比的 profile；
    缺任意一样 ⇒ NULL，不得用"看起来像"的默认值补齐。
    """
    if not (point_m and surface and expressions and units):
        return None, STATUS_PENDING_PROFILE
    return "mp-" + stable_hash({"point_m": [round(float(x), 12) for x in point_m],
                                "surface": surface,
                                "expressions": dict(expressions),
                                "units": dict(units)}), STATUS_OK
