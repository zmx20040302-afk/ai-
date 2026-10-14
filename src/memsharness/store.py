"""溯源数据层：DuckDB 元数据库与表结构。

对应 WORKING_PLAN.md 第 4.2 节的表设计。本模块在 P0 只负责：
1. 建立稳定表结构（后续阶段只增列不破坏）
2. 提供最小读写助手（运行记录、样本、查询）
3. 强制 append-only 与「来源标注」约定

注意：数值能否入库取决于是否携带溯源信息；缺失溯源的样本由调用方拒绝，
本模块不做静默补全。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import duckdb

from .paths import db_path, ensure_work_tree

# 允许的 sample 来源类型（红线 4：来源永不混同）
# ai_solver 是**第六种**来源（WORKING_PLAN 红线 8）：AI 求解值与 COMSOL 仿真值在可信度与
# 验证要求上根本不同，混为一类会污染数据层，因此必须分列。
SOURCE_TYPES = ("simulation", "analytic", "literature", "experiment", "human_feedback", "ai_solver")

# 溯源链强制要求（红线 1：没有证据就不出数字）
# - analytic 来自公式与抽取器版本，不需要运行/实验 ID，但 extractor 必填（见 insert_sample）
# - ai_solver 必须挂到**具体模型版本**（model_id），否则无法回答"这个解是哪个模型哪一版给的"
REQUIRED_TRACEABILITY: dict[str, str | None] = {
    "simulation": "run_id",
    "literature": "evidence_id",
    "experiment": "experiment_id",
    "human_feedback": "feedback_id",
    "ai_solver": "model_id",
    "analytic": None,
}

# 模型状态机（第 4.4 / 6.3 节）：晋升必须经人工门禁
MODEL_STATES = (
    "draft",
    "validated_on_holdout",
    "calibrated_to_experiment",
    "approved_for_use",
    "deprecated",
)

SCHEMA_SQL: tuple[str, ...] = (
    # 任务：一次人类需求
    """
    CREATE TABLE IF NOT EXISTS task (
        task_id      VARCHAR PRIMARY KEY,
        request      VARCHAR NOT NULL,
        constraints  VARCHAR,
        created_by   VARCHAR,
        created_at   TIMESTAMP,
        status       VARCHAR
    )
    """,
    # 设计点：参数向量 + 单位
    """
    CREATE TABLE IF NOT EXISTS design (
        design_id    VARCHAR PRIMARY KEY,
        params       VARCHAR NOT NULL,   -- JSON: {name: value}
        units        VARCHAR,            -- JSON: {name: unit}
        geometry_family VARCHAR,         -- 防泄漏分组键
        source_type  VARCHAR,
        created_at   TIMESTAMP
    )
    """,
    # 运行：一次求解尝试（可复现单元）
    """
    CREATE TABLE IF NOT EXISTS run (
        run_id       VARCHAR PRIMARY KEY,
        design_id    VARCHAR,
        owner        VARCHAR,            -- 多人使用预留（WORKING_PLAN 4.10）：谁提交的
        backend      VARCHAR,            -- local | remote
        pathway      VARCHAR,            -- livelink | comsolbatch | template
        model_path   VARCHAR,
        model_sha256 VARCHAR,
        software     VARCHAR,            -- JSON: 版本/授权/端口等
        settings     VARCHAR,            -- JSON: 网格/求解器设置快照
        status       VARCHAR,            -- queued|running|succeeded|failed|cancelled
        exit_code    INTEGER,
        diagnostic   VARCHAR,            -- 失败分类（诊断码）
        wall_seconds DOUBLE,
        run_dir      VARCHAR,
        started_at   TIMESTAMP,
        finished_at  TIMESTAMP
    )
    """,
    # 样本：抽取后的输入/输出向量（训练与查询的基本单位）
    """
    CREATE TABLE IF NOT EXISTS sample (
        sample_id    VARCHAR PRIMARY KEY,
        run_id       VARCHAR,            -- simulation 的来源
        design_id    VARCHAR,
        evidence_id  VARCHAR,            -- literature 的来源（必须带原文摘录）
        experiment_id VARCHAR,           -- experiment 的来源
        feedback_id  VARCHAR,            -- human_feedback 的来源
        model_id     VARCHAR,            -- ai_solver 的来源（必须挂到具体模型版本）
        fidelity     VARCHAR,            -- F0|F1|F2|F3
        source_type  VARCHAR NOT NULL,   -- SOURCE_TYPES 之一
        inputs       VARCHAR NOT NULL,   -- JSON
        outputs      VARCHAR NOT NULL,   -- JSON
        uncertainty  VARCHAR,            -- JSON: 各输出的不确定度
        extractor    VARCHAR,            -- 抽取器名称+版本
        quality      VARCHAR,            -- JSON: 校验标记
        contract_status VARCHAR,         -- 契约状态：NULL | 'legacy_pre_contract'
                                         --   'legacy_pre_contract' = 该样本写于 schemas/ 契约生效（2026-09-14）之前，
                                         --   其 uncertainty **按缺失处理**（不得当 0、不得据此给误差界）。
                                         --   只加列不改数值；修正只能新增记录（append-only）。
        created_at   TIMESTAMP
    )
    """,
    # 产物：文件级溯源
    """
    CREATE TABLE IF NOT EXISTS artifact (
        artifact_id  VARCHAR PRIMARY KEY,
        run_id       VARCHAR,
        kind         VARCHAR,            -- mph|csv|fig|log|other
        sha256       VARCHAR,
        path         VARCHAR,
        bytes        BIGINT,
        created_at   TIMESTAMP
    )
    """,
    # 数据集：冻结的样本集合（训练/评估输入）
    """
    CREATE TABLE IF NOT EXISTS dataset (
        dataset_id   VARCHAR PRIMARY KEY,
        version      VARCHAR,
        purpose      VARCHAR,            -- train | holdout | calibration
        sample_ids   VARCHAR,            -- JSON 数组
        filters      VARCHAR,            -- JSON: 构造规则
        report       VARCHAR,            -- JSON: 校验结果（含泄漏检查）
        created_by   VARCHAR,            -- 多人使用预留：谁建的
        created_at   TIMESTAMP
    )
    """,
    # 模型与模型卡
    """
    CREATE TABLE IF NOT EXISTS model (
        model_id     VARCHAR PRIMARY KEY,
        version      VARCHAR,
        dataset_id   VARCHAR,
        algorithm    VARCHAR,
        hyperparams  VARCHAR,            -- JSON
        metrics      VARCHAR,            -- JSON：评分卡
        uq_method    VARCHAR,
        scope        VARCHAR,            -- JSON：适用范围（变量上下界）
        state        VARCHAR,            -- MODEL_STATES 之一
        card_path    VARCHAR,
        approved_by  VARCHAR,            -- 多人使用预留：放行审批人（红线 5）
        approved_at  TIMESTAMP,
        created_at   TIMESTAMP
    )
    """,
    # 预测：每次对外输出的记录（含不确定度与 OOD）
    """
    CREATE TABLE IF NOT EXISTS prediction (
        prediction_id VARCHAR PRIMARY KEY,
        model_id      VARCHAR,
        inputs        VARCHAR,
        outputs       VARCHAR,
        interval      VARCHAR,
        ood_score     DOUBLE,
        created_at    TIMESTAMP
    )
    """,
    # 实验：真实测量（P5 起）
    """
    CREATE TABLE IF NOT EXISTS experiment (
        experiment_id VARCHAR PRIMARY KEY,
        device        VARCHAR,
        conditions    VARCHAR,            -- JSON
        data_path     VARCHAR,
        uncertainty   VARCHAR,
        operator      VARCHAR,
        created_at    TIMESTAMP
    )
    """,
    # 证据：文献/文档摘录（强制页码与原文）
    """
    CREATE TABLE IF NOT EXISTS evidence (
        evidence_id  VARCHAR PRIMARY KEY,
        kind         VARCHAR,            -- literature|doc|case
        citation     VARCHAR,
        locator      VARCHAR,            -- 页码/章节/行号
        quote        VARCHAR NOT NULL,   -- 原文摘录：没有摘录就不算证据
        claim        VARCHAR,
        confidence   VARCHAR,
        created_at   TIMESTAMP
    )
    """,
    # 人反馈（append-only）
    """
    CREATE TABLE IF NOT EXISTS feedback (
        feedback_id  VARCHAR PRIMARY KEY,
        target_kind  VARCHAR,            -- model|prediction|report|run
        target_id    VARCHAR,
        verdict      VARCHAR,            -- accept|reject|correct|prefer
        correction   VARCHAR,
        reason       VARCHAR,
        author       VARCHAR,
        created_at   TIMESTAMP
    )
    """,
    # 验证记录（L0–L5）
    """
    CREATE TABLE IF NOT EXISTS validation (
        validation_id VARCHAR PRIMARY KEY,
        target_kind   VARCHAR,
        target_id     VARCHAR,
        level         VARCHAR,            -- L0..L5
        method        VARCHAR,
        result        VARCHAR,            -- JSON
        threshold     VARCHAR,
        passed        BOOLEAN,
        created_at    TIMESTAMP
    )
    """,
)

# 旧库补齐（幂等）：``CREATE TABLE IF NOT EXISTS`` 不会给已存在的表加列，
# 因此新增的溯源列必须显式 ALTER，否则老库上 insert_sample 会失败。
MIGRATIONS: tuple[str, ...] = (
    "ALTER TABLE sample ADD COLUMN IF NOT EXISTS evidence_id VARCHAR",
    "ALTER TABLE sample ADD COLUMN IF NOT EXISTS experiment_id VARCHAR",
    "ALTER TABLE sample ADD COLUMN IF NOT EXISTS feedback_id VARCHAR",
    # A4：第六来源 ai_solver 的溯源列
    "ALTER TABLE sample ADD COLUMN IF NOT EXISTS model_id VARCHAR",
    # 契约状态（2026-09-14）：给契约生效前的存量样本打 'legacy_pre_contract'。
    # 缺此迁移会让「存量已标记」这件事在**新建库/迁移**时静默消失（不报错、但事实已变），
    # 因此与其它列一样：SCHEMA_SQL 建新库 + MIGRATIONS 补旧库，两处都要有。
    "ALTER TABLE sample ADD COLUMN IF NOT EXISTS contract_status VARCHAR",
    # A4：多人使用预留字段（事后补会断掉历史归属，故第一天就加）
    "ALTER TABLE run ADD COLUMN IF NOT EXISTS owner VARCHAR",
    "ALTER TABLE dataset ADD COLUMN IF NOT EXISTS created_by VARCHAR",
    "ALTER TABLE model ADD COLUMN IF NOT EXISTS approved_by VARCHAR",
    "ALTER TABLE model ADD COLUMN IF NOT EXISTS approved_at TIMESTAMP",
    "ALTER TABLE task ADD COLUMN IF NOT EXISTS created_by VARCHAR",
)


def connect(path: Path | str | None = None, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    """连接元数据库；默认路径为 ``work/store/mems.duckdb``。"""
    target = Path(path) if path else db_path()
    if not read_only:
        target.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(target), read_only=read_only)


def init_schema(conn: duckdb.DuckDBPyConnection) -> list[str]:
    """建立全部表结构（幂等），并补齐旧库缺失的列。"""
    for statement in SCHEMA_SQL:
        conn.execute(statement)
    for statement in MIGRATIONS:
        conn.execute(statement)
    return list_tables(conn)


def list_tables(conn: duckdb.DuckDBPyConnection) -> list[str]:
    rows = conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main' ORDER BY table_name"
    ).fetchall()
    return [row[0] for row in rows]


def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _json(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)


def insert_run(conn: duckdb.DuckDBPyConnection, **fields: Any) -> str:
    """写入一条运行记录（状态类字段由调用方负责，含必需的溯源元数据）。"""
    columns = (
        "run_id", "design_id", "backend", "pathway", "model_path", "model_sha256",
        "software", "settings", "status", "exit_code", "diagnostic", "wall_seconds",
        "run_dir", "started_at", "finished_at",
    )
    payload = {key: fields.get(key) for key in columns}
    for json_key in ("software", "settings"):
        payload[json_key] = _json(payload[json_key])
    payload.setdefault("status", "queued")
    placeholders = ", ".join("?" for _ in columns)
    conn.execute(
        f"INSERT INTO run ({', '.join(columns)}) VALUES ({placeholders})",
        [payload[key] for key in columns],
    )
    return str(payload["run_id"])


def insert_sample(conn: duckdb.DuckDBPyConnection, **fields: Any) -> str:
    """写入一条样本。

    强制四条契约（与 ``.dsh/skills/dataset-contract`` 一致）：
    1. ``source_type`` 必须是六种之一（红线 4：来源永不混同）；
    2. 该来源类型对应的溯源 ID 必须存在（红线 1：没有证据就不出数字）；
    3. ``inputs`` 与 ``outputs`` 必须同时非空，且 ``extractor`` 必须能追溯版本；
    4. ``ai_solver`` 来源必须带 ``uncertainty``（红线 7：免求解器输出必须带误差界）。
    """
    source_type = fields.get("source_type")
    if source_type not in SOURCE_TYPES:
        raise ValueError(f"source_type 必须是 {SOURCE_TYPES} 之一，收到: {source_type!r}")

    required = REQUIRED_TRACEABILITY.get(source_type)
    if required and not fields.get(required):
        raise ValueError(
            f"source_type={source_type!r} 的样本必须携带 {required}"
            f"（红线：没有证据就不出数字；缺失溯源链的数值不得入库）"
        )

    if not fields.get("inputs") or not fields.get("outputs"):
        raise ValueError("样本必须同时携带 inputs 与 outputs（禁止空样本入库）")
    if not fields.get("extractor"):
        raise ValueError("样本必须记录 extractor（抽取器名称+版本），否则无法追溯抽取逻辑")
    if source_type == "ai_solver" and not fields.get("uncertainty"):
        raise ValueError(
            "ai_solver 样本必须携带 uncertainty（场级/量级误差界）"
            "——红线 7：免 COMSOL 出解必须有界，无误差界的 AI 解不得入库"
        )

    columns = (
        "sample_id", "run_id", "design_id", "evidence_id", "experiment_id", "feedback_id",
        "model_id", "fidelity", "source_type", "inputs", "outputs", "uncertainty",
        "extractor", "quality", "created_at",
    )
    payload = {key: fields.get(key) for key in columns}
    for json_key in ("inputs", "outputs", "uncertainty", "quality"):
        payload[json_key] = _json(payload[json_key])
    payload.setdefault("created_at", now_utc())
    placeholders = ", ".join("?" for _ in columns)
    conn.execute(
        f"INSERT INTO sample ({', '.join(columns)}) VALUES ({placeholders})",
        [payload[key] for key in columns],
    )
    return str(payload["sample_id"])


def query(
    conn: duckdb.DuckDBPyConnection,
    sql: str,
    params: Iterable[Any] | None = None,
    limit: int = 200,
) -> list[dict]:
    """只读查询，强制行数上限（防止把整库塞进上下文）。"""
    capped = max(1, min(int(limit), 1000))
    cursor = conn.execute(sql, list(params or []))
    columns = [desc[0] for desc in cursor.description or []]
    rows = cursor.fetchmany(capped)
    return [dict(zip(columns, row)) for row in rows]


def store_stats(conn: duckdb.DuckDBPyConnection) -> dict[str, int]:
    """各表行数统计（MCP 工具用于报告平台状态）。"""
    stats: dict[str, int] = {}
    for table in list_tables(conn):
        stats[table] = int(conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0])
    return stats


def bootstrap(path: Path | str | None = None) -> list[str]:
    """确保运行区与表结构就绪，返回表清单。"""
    ensure_work_tree()
    with connect(path) as conn:
        return init_schema(conn)


if __name__ == "__main__":
    tables = bootstrap()
    print("元数据库已就绪，表：", ", ".join(tables))
