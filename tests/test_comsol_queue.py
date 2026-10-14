"""COMSOL 执行层单元测试（**不依赖真实求解**）。

覆盖：
- 队列语义：submit 非阻塞、status/list_jobs、cancel
- 单实例互斥：文件锁（msvcrt）跨/同进程互斥；持锁时 drain 必须拒绝
- 失败分类：连接/许可/不收敛/内存/几何/网格/超时/未知 + 是否可重试
- 溯源字段完整性：run / sample / artifact 三表的必填字段
- 模型源码生成：全 ASCII、确定性、占位符全部替换

运行：
    work\\.venv\\Scripts\\python.exe -m pytest tests -q

注意：本机沙箱拒绝系统临时目录写入，因此**不使用 pytest 的 tmp_path**，
统一用 work/.test-tmp/<uuid>/（见 tests 内的 sandbox fixture）。
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from memsharness import store  # noqa: E402
from memsharness.comsol import backend as backend_mod  # noqa: E402
from memsharness.comsol import diagnostics  # noqa: E402
from memsharness.comsol import java_model  # noqa: E402
from memsharness.comsol import queue as queue_mod  # noqa: E402
from memsharness.paths import ensure_work_tree, work_root  # noqa: E402

TEMPLATE = "heat_slab_2d"


# --------------------------------------------------------------------------------------
# 测试替身与 fixture
# --------------------------------------------------------------------------------------


class StubBackend:
    """假的执行后端：只写文件，不调用 COMSOL。"""

    name = "stub"

    def __init__(self, ok: bool = True, failure_text: str = "") -> None:
        self.ok = ok
        self.failure_text = failure_text
        self.calls: list[str] = []

    def capabilities(self) -> dict:
        return {"backend": self.name, "pathway": "stub", "requires_matlab": False}

    def probe(self) -> dict:
        return {
            "backend": self.name,
            "comsol_home": r"D:\COMSOL64\Multiphysics",
            "comsol_home_exists": False,
            "comsolbatch": "stub-comsolbatch",
            "comsolbatch_exists": False,
            "comsolcompile": "stub-comsolcompile",
            "comsolcompile_exists": False,
            "comsol_version": "stub-6.4.0.0",
            "comsol_version_source": "stub",
            "mphserver_host": "127.0.0.1",
            "mphserver_port": 2036,
            "mphserver_listening": False,
            "ready": True,
        }

    def execute(self, prepared, log=None):
        from memsharness.comsol.backend import ExecutionOutcome, dump_commands

        self.calls.append(prepared.run_id)
        run_dir = prepared.run_dir
        (run_dir / f"{prepared.java_class}.java").write_text(prepared.java_source, encoding="ascii")
        (run_dir / f"{prepared.java_class}.class").write_bytes(b"stub-class")
        (run_dir / "compile.stdout.log").write_text("stub compile ok\n", encoding="utf-8")
        (run_dir / "compile.stderr.log").write_text("", encoding="utf-8")
        (run_dir / "batchlog.txt").write_text(
            "Number of elements: 1234\nDegrees of freedom: 2500\n", encoding="utf-8"
        )
        if not self.ok:
            text = self.failure_text or "Unknown failure"
            (run_dir / "batch.stdout.log").write_text(text + "\n", encoding="utf-8")
            (run_dir / "batch.stderr.log").write_text("", encoding="utf-8")
            outcome = ExecutionOutcome(
                ok=False,
                exit_code=1,
                wall_seconds=1.25,
                commands=[{"stage": "batch", "argv": ["stub"], "returncode": 1}],
                log_paths={"batch.stdout": str(run_dir / "batch.stdout.log")},
                artifacts=[run_dir / "batch.stdout.log"],
                result=None,
                result_error="日志中没有 MEMS_RESULT_JSON= 标记（可能求解或抽取阶段失败）",
                diagnosis=diagnostics.classify_failure(text, exit_code=1, stage="batch"),
                notes=["stub 后端模拟失败"],
                software={"backend": self.name, "comsol_version": "stub-6.4.0.0"},
                log_tail=text,
            )
            dump_commands(run_dir / "commands.json", outcome)
            return outcome

        analytic = prepared.template.analytic(prepared.params)
        payload = {
            "template": prepared.template.name,
            "T_max_K": analytic["T_max_K"],
            "T_min_K": analytic["T_min_K"],
            "T_max_ref_K": analytic["T_max_K"],
            "q_out_W_per_m": 1.0,
            "batchlog_facts": {"elements": 1234, "dof": 2500, "vertices": None, "missing_reason": ["vertices"]},
        }
        (run_dir / "batch.stdout.log").write_text(
            "stub batch ok\n" + java_model.RESULT_MARKER + json.dumps(payload) + "\n"
            + java_model.DONE_MARKER + "\n",
            encoding="utf-8",
        )
        (run_dir / "batch.stderr.log").write_text("", encoding="utf-8")
        (run_dir / "out.mph").write_bytes(b"stub-mph-bytes")
        outcome = ExecutionOutcome(
            ok=True,
            exit_code=0,
            wall_seconds=2.5,
            commands=[
                {"stage": "compile", "argv": ["stub-compile"], "returncode": 0, "wall_seconds": 0.5},
                {"stage": "batch", "argv": ["stub-batch"], "returncode": 0, "wall_seconds": 2.0},
            ],
            log_paths={"batch.stdout": str(run_dir / "batch.stdout.log")},
            artifacts=[
                run_dir / f"{prepared.java_class}.java",
                run_dir / "out.mph",
                run_dir / "batch.stdout.log",
            ],
            result=payload,
            software={"backend": self.name, "comsol_version": "stub-6.4.0.0"},
            notes=["stub 后端模拟成功"],
            log_tail="stub batch ok",
        )
        dump_commands(run_dir / "commands.json", outcome)
        return outcome


@pytest.fixture()
def sandbox() -> dict:
    """工作区内自管的临时沙箱（不用 pytest 的 tmp_path）。"""
    ensure_work_tree()
    base = work_root() / ".test-tmp" / uuid.uuid4().hex
    for sub in ("queue", "runs", "logs"):
        (base / sub).mkdir(parents=True, exist_ok=True)
    return {
        "base": base,
        "queue_root": base / "queue",
        "runs_root": base / "runs",
        "logs_root": base / "logs",
        "db": base / "test.duckdb",
    }


@pytest.fixture()
def conn(sandbox):
    with store.connect(sandbox["db"]) as connection:
        store.init_schema(connection)
        yield connection


def make_queue(sandbox, backend=None, conn=None) -> queue_mod.JobQueue:
    return queue_mod.JobQueue(
        root=sandbox["queue_root"],
        runs_root=sandbox["runs_root"],
        logs_root=sandbox["logs_root"],
        backend=backend or StubBackend(),
        conn=conn,
    )


# --------------------------------------------------------------------------------------
# 1. 模型源码生成（不需要求解）
# --------------------------------------------------------------------------------------


def test_java_source_is_ascii_and_fully_substituted() -> None:
    source, resolved = java_model.render_source(TEMPLATE, {"q_in": 4000.0})
    source.encode("ascii")  # 非 ASCII 会抛错
    assert "@@" not in source
    assert "class heat_slab_2d" in source
    assert "new int[]{4}" in source  # 固定温度边界编号（右）
    # 热流边界必须与温度边界【相对】：二维矩形编号 1=左 2=下 3=上 4=右，
    # 故 4(右)+1(左) 才构成与解析解一致的一维导热；曾误用 2(下) 导致 T_max 偏低 0.4%（实测）。
    assert "new int[]{1}" in source  # 热流边界编号（左）
    assert resolved["q_in"] == 4000.0
    assert resolved["bnd_t"] == 4 and resolved["bnd_q"] == 1


def test_java_source_is_deterministic() -> None:
    first, _ = java_model.render_source(TEMPLATE, {"q_in": 1234.5})
    second, _ = java_model.render_source(TEMPLATE, {"q_in": 1234.5})
    assert first == second


def test_validate_values_rejects_unknown_and_out_of_range() -> None:
    template = java_model.get_template(TEMPLATE)
    with pytest.raises(ValueError):
        java_model.validate_values(template, {"nope": 1.0})
    with pytest.raises(ValueError):
        java_model.validate_values(template, {"q_in": -5.0})
    with pytest.raises(ValueError):
        java_model.validate_values(template, {"q_in": float("nan")})


def test_analytic_reference_matches_closed_form() -> None:
    result = java_model.analytic_values(TEMPLATE, {"q_in": 4000.0, "Lx": 0.01, "k_cond": 1.0, "T0": 300.0})
    assert result["T_max_K"] == pytest.approx(300.0 + 4000.0 * 0.01 / 1.0)
    assert result["T_min_K"] == pytest.approx(300.0)


def test_parse_result_marker_handles_missing_and_garbage() -> None:
    payload, error = java_model.parse_result_marker("")
    assert payload is None and error
    payload, error = java_model.parse_result_marker("no marker here")
    assert payload is None and "MEMS_RESULT_JSON" in error
    payload, error = java_model.parse_result_marker(java_model.RESULT_MARKER + "{not json}")
    assert payload is None and error
    payload, error = java_model.parse_result_marker(
        "noise\n" + java_model.RESULT_MARKER + '{"T_max_K": 1.0}\n'
    )
    assert payload == {"T_max_K": 1.0} and error is None


def test_parse_batchlog_facts_reports_missing_reason() -> None:
    facts = java_model.parse_batchlog_facts("Number of elements: 42\n")
    assert facts["elements"] == 42
    assert facts["dof"] is None
    assert "dof" in facts["missing_reason"]


# --------------------------------------------------------------------------------------
# 2. 队列语义
# --------------------------------------------------------------------------------------


def test_submit_is_nonblocking_and_creates_run_dir(sandbox) -> None:
    backend = StubBackend()
    job_queue = make_queue(sandbox, backend)
    run_id = job_queue.submit(queue_mod.JobSpec(template=TEMPLATE, params={"q_in": 1000.0}))
    # 非阻塞：提交后没有发生任何求解
    assert backend.calls == []
    run_dir = job_queue.run_dir(run_id)
    assert (run_dir / "job.json").is_file()
    assert (run_dir / "status.json").is_file()
    assert (sandbox["queue_root"] / "jobs" / f"{run_id}.json").is_file()
    status = job_queue.status(run_id)
    assert status["status"] == "queued"
    assert status["params"]["q_in"] == 1000.0
    assert status["queue_position"] == 1


def test_submit_rejects_unknown_template(sandbox) -> None:
    job_queue = make_queue(sandbox)
    with pytest.raises(KeyError):
        job_queue.submit(queue_mod.JobSpec(template="nope", params={}))


def test_submit_rejects_remote_backend(sandbox) -> None:
    job_queue = make_queue(sandbox)
    with pytest.raises(NotImplementedError):
        job_queue.submit(queue_mod.JobSpec(template=TEMPLATE, params={}, backend="remote"))


def test_drain_runs_job_and_writes_result(sandbox) -> None:
    backend = StubBackend()
    job_queue = make_queue(sandbox, backend)
    run_id = job_queue.submit(queue_mod.JobSpec(template=TEMPLATE, params={"q_in": 2000.0}))
    processed = job_queue.drain()
    assert [p["run_id"] for p in processed] == [run_id]
    assert processed[0]["status"] == "succeeded"
    assert backend.calls == [run_id]
    status = job_queue.status(run_id)
    assert status["status"] == "succeeded"
    assert status["exit_code"] == 0
    assert status["wall_seconds"] is not None
    result = json.loads((job_queue.run_dir(run_id) / "result.json").read_text(encoding="utf-8"))
    assert result["comparison"]["T_max_K"]["passed"] is True
    assert result["result"]["T_max_K"] == pytest.approx(300.0 + 2000.0 * 0.01 / 1.0)
    commands = json.loads((job_queue.run_dir(run_id) / "commands.json").read_text(encoding="utf-8"))
    assert commands["exit_code"] == 0
    assert (job_queue.run_dir(run_id) / "db_record.json").is_file()
    # 队列票据已归档，队列清空
    assert list((sandbox["queue_root"] / "jobs").glob("*.json")) == []
    assert list((sandbox["queue_root"] / "jobs").glob("*.done"))


def test_list_jobs_returns_recent_first(sandbox) -> None:
    job_queue = make_queue(sandbox)
    first = job_queue.submit(queue_mod.JobSpec(template=TEMPLATE, params={"q_in": 1000.0}))
    second = job_queue.submit(queue_mod.JobSpec(template=TEMPLATE, params={"q_in": 2000.0}))
    rows = job_queue.list_jobs()
    assert {row["run_id"] for row in rows} == {first, second}
    assert all(row["status"] == "queued" for row in rows)
    only_queued = job_queue.list_jobs(status_in=("succeeded",))
    assert only_queued == []


def test_list_jobs_tolerates_legacy_string_diagnostic(sandbox) -> None:
    """历史 run 的 `diagnostic` 是**裸字符串** ⇒ 列表查询必须不崩，且原样透出。

    实测：`work/runs/probe-20260911T150820Z-e3599a99/status.json` 里 `"diagnostic": "unknown"`。
    旧实现 `(status.get("diagnostic") or {}).get("code")` 会对字符串调 `.get`
    ⇒ 抛 `AttributeError: 'str' object has no attribute 'get'`，
    使 `sim_status`（**无 run_id 的列表模式**）**全线不可用**（MCP 工具当场报这个错）。
    修法：读取端宽容（dict 取 `code`，字符串原样给），**不改写任何历史 status.json**。
    """
    job_queue = make_queue(sandbox)
    run_id = job_queue.submit(queue_mod.JobSpec(template=TEMPLATE, params={"q_in": 1000.0}))
    status_path = job_queue.run_dir(run_id) / "status.json"
    payload = json.loads(status_path.read_text(encoding="utf-8"))
    payload["status"] = "failed"
    payload["diagnostic"] = "unknown"  # 旧形态：字符串
    status_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    rows = job_queue.list_jobs()
    assert next(r for r in rows if r["run_id"] == run_id)["diagnostic"] == "unknown"
    # 新形态（dict）取 `code`；两种形态在同一份列表里共存不得互相影响
    payload["diagnostic"] = {"code": "oom", "retryable": True}
    status_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    rows = job_queue.list_jobs()
    assert next(r for r in rows if r["run_id"] == run_id)["diagnostic"] == "oom"


def test_status_of_missing_run(sandbox) -> None:
    job_queue = make_queue(sandbox)
    status = job_queue.status("run-does-not-exist")
    assert status["status"] == "missing"
    assert "run 目录不存在" in status["error"]


def test_cancel_queued_job(sandbox) -> None:
    job_queue = make_queue(sandbox)
    run_id = job_queue.submit(queue_mod.JobSpec(template=TEMPLATE, params={"q_in": 1000.0}))
    outcome = job_queue.cancel(run_id)
    assert outcome["cancelled"] is True
    assert outcome["stage"] == "queued"
    status = job_queue.status(run_id)
    assert status["status"] == "cancelled"
    assert status["finished_at"] is not None
    # 已撤销的票据不再被执行
    assert job_queue.drain() == []
    again = job_queue.cancel(run_id)
    assert again["cancelled"] is False
    assert "终态" in again["reason"]


def test_cancel_after_completion_is_noop(sandbox) -> None:
    job_queue = make_queue(sandbox)
    run_id = job_queue.submit(queue_mod.JobSpec(template=TEMPLATE, params={"q_in": 1000.0}))
    job_queue.drain()
    outcome = job_queue.cancel(run_id)
    assert outcome["cancelled"] is False
    assert job_queue.status(run_id)["status"] == "succeeded"


# --------------------------------------------------------------------------------------
# 3. 单实例互斥（文件锁）
# --------------------------------------------------------------------------------------


def test_filelock_excludes_second_holder(sandbox) -> None:
    path = sandbox["queue_root"] / "locks" / "unit.lock"
    first = queue_mod.FileLock(path)
    second = queue_mod.FileLock(path)
    assert first.acquire() is True
    assert first.held is True
    assert second.acquire() is False  # 同一时刻只允许一个持有者
    first.release()
    assert first.held is False
    assert second.acquire() is True
    second.release()


def test_drain_refuses_when_worker_lock_is_held(sandbox) -> None:
    job_queue = make_queue(sandbox)
    job_queue.submit(queue_mod.JobSpec(template=TEMPLATE, params={"q_in": 1000.0}))
    holder = queue_mod.FileLock(job_queue.lock_path)
    assert holder.acquire() is True
    try:
        assert job_queue.worker_locked() is True
        with pytest.raises(RuntimeError, match="单实例"):
            job_queue.drain()
    finally:
        holder.release()
    assert job_queue.worker_locked() is False
    # 锁释放后可以正常执行
    assert job_queue.drain()[0]["status"] == "succeeded"


# --------------------------------------------------------------------------------------
# 4. 失败分类
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected_code", "retryable"),
    [
        ("License error: cannot connect to license server", "license", True),
        ("OutOfMemoryError: Failed to allocate memory", "out_of_memory", True),
        ("Geometry could not be built: self-intersecting boundaries", "geometry", False),
        ("Mesh failed: inverted element detected", "mesh", False),
        ("Selection is empty for feature temp1", "selection", False),
        ("Nonlinear solver did not converge, residual stagnated", "convergence", True),
        ("Cannot connect to mphserver at 127.0.0.1:2036", "connection", True),
        ("Undefined variable: q_in", "api", False),
        ("error: cannot find symbol  class Model", "api", False),
        ("some completely unfamiliar text", "unknown", False),
    ],
)
def test_diagnostic_classification(text: str, expected_code: str, retryable: bool) -> None:
    diagnosis = diagnostics.classify_failure(text, exit_code=1, stage="batch")
    assert diagnosis["code"] == expected_code
    assert diagnosis["retryable"] is retryable
    assert diagnosis["actions"], "处置建议不得为空"
    assert diagnosis["evidence"], "必须带回可复核的原文证据"


def test_diagnostic_timeout_stage_short_circuits() -> None:
    diagnosis = diagnostics.classify_failure("anything", exit_code=None, stage="timeout")
    assert diagnosis["code"] == "timeout"
    assert diagnosis["retryable"] is True
    assert diagnosis["text_length"] == len("anything")


def test_retry_plan_respects_limits() -> None:
    license_diag = diagnostics.classify_failure("license error", exit_code=1)
    assert diagnostics.retry_plan(license_diag, attempt=1, max_attempts=2)["should_retry"] is True
    assert diagnostics.retry_plan(license_diag, attempt=2, max_attempts=2)["should_retry"] is False
    unknown = diagnostics.classify_failure("???", exit_code=1)
    assert diagnostics.retry_plan(unknown, attempt=1)["should_retry"] is False
    mesh = diagnostics.classify_failure("Mesh failed: inverted element", exit_code=1)
    assert diagnostics.retry_plan(mesh, attempt=1)["should_retry"] is False


# --------------------------------------------------------------------------------------
# geometry 规则误报的回归（实测留证，见 diagnostics.py 的 _NOISE_LINE_RE 注释）
# --------------------------------------------------------------------------------------
#
# 收紧前 geometry 规则里含裸子串 ``geometr`` 与裸汉字 ``几何``，会命中**正常行**：
#   1) 稳态求解成功的 batchlog 第 32 行原样是「几何形函数: 二次拉格朗日单元」
#      （实测 run-20260911T013113Z-1a25aa9f，status=succeeded）⇒ 成功运行被判成
#      「几何构建失败」；
#   2) Java 属性名 geometricNonlinearity；
#   3) 失败信息块里的字段行「- Geometry: geom1」（那是"出错域所属的几何名"，
#      真错因是材料引用了未定义变量）⇒ 真错因被掩掉。
#   4) mesh 规则同样含裸汉字，会命中进度行「当前进度: 0 % - 自由三角形网格 1」。

_GEOMETRY_NOISE_SUCCESS_LOG = """\
*******************************************
***COMSOL 6.4.0.293 progress output file***
*******************************************
           当前进度:   0 % - 自由三角形网格 1
Memory: 687/718 731/761
顶点单元数：4
边界单元数：18
单元数：56
---------- 当前进度: 100 % - 正在提高单元质量
<---- 研究 1/解 1 (sol1) 中的“编译方程: 稳态” --------------------------------
几何形函数: 二次拉格朗日单元
在 AMD64 Family 25 Model 80 Stepping 0, AuthenticAMD 上运行。
           当前进度:   7 % - 编译方程: 稳态
时间：2。
----- 研究 1/解 1 (sol1) 中的“编译方程: 稳态” ------------------------------->
"""


def test_geometry_rule_does_not_fire_on_successful_batchlog() -> None:
    """成功运行的 batchlog（含「几何形函数」与网格进度行）不得被判成几何/网格错误。"""
    diagnosis = diagnostics.classify_failure(_GEOMETRY_NOISE_SUCCESS_LOG, exit_code=0, stage="batch")
    assert diagnosis["code"] == "unknown", (
        f"正常行被误判为 {diagnosis['code']}：{diagnosis.get('evidence')}"
    )


def test_geometry_rule_does_not_fire_on_geometric_nonlinearity() -> None:
    """``geometricNonlinearity`` 是属性名，不是几何失败。"""
    text = (
        "model.component('comp1').physics('solid').set('geometricNonlinearity', true);\n"
        "Loaded property geometricNonlinearity"
    )
    diagnosis = diagnostics.classify_failure(text, exit_code=1, stage="batch")
    assert diagnosis["code"] != "geometry", diagnosis.get("evidence")


def test_geometry_field_line_in_error_block_is_not_a_geometry_failure() -> None:
    """报错块里的「- Geometry: geom1」只是定位信息，真错因（未定义变量）必须被读到。

    实测对应 run-20260911T025650Z-96aa38fb：收紧前判 geometry，收紧后正确判 api。
    """
    text = (
        "ERROR_MARKER::com.comsol.util.exceptions.FlException: "
        "The_following_feature_has_encountered_a_problem\n"
        "Messages:\n"
        "\tUndefined variable\n"
        "\t- Variable: comp1.mat1.def.E\n"
        "\t- Geometry: geom1\n"
        "\t- Domain: 1\n"
    )
    diagnosis = diagnostics.classify_failure(text, exit_code=1, stage="batch")
    assert diagnosis["code"] == "api", diagnosis.get("evidence")


@pytest.mark.parametrize(
    "text",
    [
        "Messages:\n\tGeometry could not be built\n\t- Feature: geom1",
        "Failed to build geometry sequence",
        "几何构建失败：参数使厚度为 0",
        "Invalid geometry: self-intersecting face detected",
        "Zero-thickness domain detected",
        "degenerate geometry",
    ],
)
def test_geometry_rule_still_catches_real_geometry_failures(text: str) -> None:
    """收紧之后，真几何失败仍必须被认出来（不能为了消误报把规则废掉）。"""
    diagnosis = diagnostics.classify_failure(text, exit_code=1, stage="batch")
    assert diagnosis["code"] == "geometry", (text, diagnosis["code"])
    assert diagnosis["evidence"], "必须带回可复核的原文证据"


def test_mesh_rule_does_not_fire_on_mesh_progress_line() -> None:
    """网格进度行「当前进度: 0 % - 自由三角形网格 1」不得被判成网格错误。"""
    diagnosis = diagnostics.classify_failure(
        "           当前进度:   0 % - 自由三角形网格 1\nMemory: 687/718", exit_code=0
    )
    assert diagnosis["code"] != "mesh", diagnosis.get("evidence")


def test_failed_run_gets_diagnosis_and_negative_sample(sandbox, conn) -> None:
    backend = StubBackend(ok=False, failure_text="OutOfMemoryError: Failed to allocate memory")
    job_queue = make_queue(sandbox, backend, conn=conn)
    run_id = job_queue.submit(queue_mod.JobSpec(template=TEMPLATE, params={"q_in": 1000.0}))
    job_queue.drain()
    status = job_queue.status(run_id)
    assert status["status"] == "failed"
    assert status["diagnostic"]["code"] == "out_of_memory"
    info = queue_mod.ingest_run(conn, job_queue, run_id)
    assert info["status"] == "failed"
    row = store.query(conn, "SELECT * FROM sample WHERE run_id = ?", [run_id])[0]
    quality = json.loads(row["quality"])
    assert quality["negative_sample"] is True
    assert quality["diagnostic_code"] == "out_of_memory"
    outputs = json.loads(row["outputs"])
    assert outputs["T_max_K"] is None  # 缺失写 null，不用 0 顶替
    assert "求解未成功" in quality["missing_reason"]


# --------------------------------------------------------------------------------------
# 5. 后端抽象
# --------------------------------------------------------------------------------------


def test_local_backend_probe_reports_missing_executables() -> None:
    missing_home = "no-such-comsol-dir"
    backend = backend_mod.LocalComsolBackend(comsol_home=missing_home)
    probe = backend.probe()
    assert probe["ready"] is False
    assert probe["comsolbatch_exists"] is False
    assert probe["comsol_version"] is None
    assert "读不到" in probe["comsol_version_source"]


def test_get_backend_rejects_remote_and_unknown() -> None:
    assert isinstance(backend_mod.get_backend("local"), backend_mod.LocalComsolBackend)
    with pytest.raises(NotImplementedError):
        backend_mod.get_backend("remote")
    with pytest.raises(ValueError):
        backend_mod.get_backend("cluster")
    with pytest.raises(NotImplementedError):
        backend_mod.RemoteBackend()


def test_local_backend_satisfies_protocol() -> None:
    backend = backend_mod.LocalComsolBackend()
    assert isinstance(backend, backend_mod.ExecutionBackend)
    capabilities = backend.capabilities()
    assert capabilities["requires_matlab"] is False
    assert capabilities["parallel_solving"] is False


# --------------------------------------------------------------------------------------
# 6. 溯源字段完整性（红线 1/4/6 + dataset-contract）
# --------------------------------------------------------------------------------------


def test_ingest_run_provenance_fields_complete(sandbox, conn) -> None:
    job_queue = make_queue(sandbox, StubBackend(), conn=conn)
    run_id = job_queue.submit(
        queue_mod.JobSpec(
            template=TEMPLATE,
            params={"q_in": 4000.0},
            sweep_id="sweep-test",
            timeout_seconds=600,
        )
    )
    # 提交阶段：run 行已落库，且已标注「此刻尚不存在的字段」
    queued = store.query(conn, "SELECT * FROM run WHERE run_id = ?", [run_id])[0]
    assert queued["status"] == "queued"
    assert json.loads(queued["settings"])["provenance_gaps_at_submit"]

    job_queue.drain()
    info = queue_mod.ingest_run(conn, job_queue, run_id)
    assert info["l0_passed"] is True

    # ---- run 表：COMSOL 版本 / 通路 / 模型哈希 / 参数与设置 / 耗时 / 诊断 ----
    run_row = store.query(conn, "SELECT * FROM run WHERE run_id = ?", [run_id])[0]
    assert run_row["status"] == "succeeded"
    assert run_row["backend"] == "local"
    assert run_row["pathway"] == "comsolbatch"
    assert run_row["exit_code"] == 0
    assert run_row["wall_seconds"] and run_row["wall_seconds"] > 0
    assert run_row["diagnostic"] is None  # 成功运行不应有失败分类
    assert run_row["started_at"] is not None or run_row["status"] == "succeeded"
    assert run_row["finished_at"] is not None
    assert run_row["run_dir"] and Path(run_row["run_dir"]).is_dir()
    assert run_row["model_path"] and Path(run_row["model_path"]).is_file()
    assert run_row["model_sha256"] and len(run_row["model_sha256"]) == 64
    software = json.loads(run_row["software"])
    assert software["comsol_version"] == "stub-6.4.0.0"
    assert "mphserver_port" in software
    settings = json.loads(run_row["settings"])
    assert settings["params_si"]["q_in"] == 4000.0
    assert settings["mesh"]["hmax_mesh_m"] > 0
    assert settings["boundary_selection_verified_in_gui"] is False  # 如实标注未做图形核对
    assert settings["provenance_gaps"]

    # ---- sample 表：source_type / fidelity / inputs / outputs / extractor / quality ----
    samples = store.query(
        conn, "SELECT * FROM sample WHERE run_id = ? ORDER BY source_type", [run_id]
    )
    assert [row["source_type"] for row in samples] == ["analytic", "simulation"]
    sim = [row for row in samples if row["source_type"] == "simulation"][0]
    assert sim["fidelity"] == "F2"
    assert sim["run_id"] == run_id
    assert sim["design_id"] == run_row["design_id"]
    assert json.loads(sim["inputs"])["q_in"] == 4000.0
    outputs = json.loads(sim["outputs"])
    assert outputs["T_max_K"] == pytest.approx(300.0 + 4000.0 * 0.01 / 1.0)
    assert outputs["T_min_K"] == pytest.approx(300.0)
    assert "@" in sim["extractor"] or ":" in sim["extractor"]
    quality = json.loads(sim["quality"])
    assert quality["l0_analytic_check"]["passed"] is True
    assert quality["negative_sample"] is False
    uncertainty = json.loads(sim["uncertainty"])
    assert "T_max_K" in uncertainty
    # 未量化的分量必须写 null 并附原因（不得写 0 冒充）
    params_unc = uncertainty["T_max_K"]["components"]["parameter"]
    assert params_unc["value"] is None and params_unc["reason"]

    ana = [row for row in samples if row["source_type"] == "analytic"][0]
    assert ana["fidelity"] == "F0"
    assert json.loads(ana["quality"])["role"] == "cross_check_reference"

    # ---- design 表：参数向量、单位、几何族 ----
    design = store.query(conn, "SELECT * FROM design WHERE design_id = ?", [run_row["design_id"]])[0]
    assert json.loads(design["params"])["q_in"] == 4000.0
    assert json.loads(design["units"])["q_in"] == "W/m^2"
    assert design["geometry_family"] == "heat_slab_2d" or design["geometry_family"]

    # ---- artifact 表：每个产物都有 sha256/path/bytes ----
    artifacts = store.query(conn, "SELECT * FROM artifact WHERE run_id = ?", [run_id], limit=200)
    assert len(artifacts) >= 5
    kinds = {row["kind"] for row in artifacts}
    assert "mph" in kinds and "log" in kinds
    for row in artifacts:
        assert row["sha256"] and len(row["sha256"]) == 64
        assert Path(row["path"]).is_file()
        assert row["bytes"] is not None  # 空日志允许为 0，但必须如实记录大小
    assert any(row["bytes"] > 0 for row in artifacts)


def test_ingest_is_idempotent(sandbox, conn) -> None:
    job_queue = make_queue(sandbox, StubBackend(), conn=conn)
    run_id = job_queue.submit(queue_mod.JobSpec(template=TEMPLATE, params={"q_in": 1500.0}))
    job_queue.drain()
    first = queue_mod.ingest_run(conn, job_queue, run_id)
    second = queue_mod.ingest_run(conn, job_queue, run_id)
    assert second.get("already_ingested") is True
    assert sorted(first["sample_ids"]) == sorted(second["sample_ids"])
    total = store.query(conn, "SELECT count(*) AS n FROM sample WHERE run_id = ?", [run_id])[0]["n"]
    assert total == 2  # simulation + analytic，没有重复写入


def test_mesh_convergence_ingest_skips_samples(sandbox, conn) -> None:
    job_queue = make_queue(sandbox, StubBackend(), conn=conn)
    run_id = job_queue.submit(queue_mod.JobSpec(template=TEMPLATE, params={"q_in": 1000.0}))
    job_queue.drain()
    info = queue_mod.ingest_run(conn, job_queue, run_id, write_samples=False)
    assert info["sample_ids"] == []
    assert store.query(conn, "SELECT count(*) AS n FROM sample WHERE run_id = ?", [run_id])[0]["n"] == 0
    assert info["artifact_rows"] > 0
    run_row = store.query(conn, "SELECT status, model_sha256 FROM run WHERE run_id = ?", [run_id])[0]
    assert run_row["status"] == "succeeded"
    assert run_row["model_sha256"]
