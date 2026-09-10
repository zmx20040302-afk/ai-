"""模型层：代理模型、不确定度、主动学习与模型注册。

P0 已实现 ``surrogate``（训练/评分卡/模型卡/注册）。
后续阶段：``active``（主动学习采样）、``calibrate``（实验校准）、``registry``（状态机与门禁）。
"""

from .surrogate import (  # noqa: F401
    MIN_ROWS_FOR_TRAINING,
    ScoreCard,
    SurrogateEnsemble,
    discover_columns,
    grouped_split,
    load_samples,
    new_model_id,
    register_model,
    save_model,
    score,
    write_model_card,
)

__all__ = [
    "MIN_ROWS_FOR_TRAINING",
    "ScoreCard",
    "SurrogateEnsemble",
    "discover_columns",
    "grouped_split",
    "load_samples",
    "new_model_id",
    "register_model",
    "save_model",
    "score",
    "write_model_card",
]
