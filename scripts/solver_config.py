# -*- coding: utf-8 -*-
"""求解器底层配置的命令行入口（**不做任何求解**，只做配置与门禁）。

用法：
    python -B scripts\\solver_config.py init   --solver-id pmut-f1 [--export-dir work\\exports]
    python -B scripts\\solver_config.py validate --spec work\\runs\\solver\\pmut-f1\\solver_spec.json
    python -B scripts\\solver_config.py summary  --spec <同上>
    python -B scripts\\solver_config.py state    --spec <同上> [--evidence ev.json] [--apply]
                                                [--sign-by 张三 --scope "只含 N2=5..8"]
                                                [--drift]
    python -B scripts\\solver_config.py solve    --spec <同上> --params '{"N_w_te2":6}'

为什么单独一个脚本：底层配置要能被**人**审阅与签字（红线 5），所以入口必须显式、
可复制、可审计；也方便在没有 GUI/没有 MCP 的情况下核对。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))


def _mod():
    from memsharness import solver
    return solver


def cmd_init(a) -> int:
    s = _mod()
    out = pathlib.Path(a.out) if a.out else (
        s.SOLVER_ROOT / a.solver_id / "solver_spec.json")
    if out.is_file() and not a.force:
        print("[FAIL] 已存在（不覆盖）：%s —— 要重写请加 --force" % out)
        return 2
    fields = [{"name": "u", "unit": "m", "note": "结构位移场（占位，按实际导出改）"}]
    ps = None
    if a.export_dir:
        ps, msg = _derive_point_set(pathlib.Path(a.export_dir))
        print("  点集推导：%s" % msg)
    spec = s.new_spec_template(solver_id=a.solver_id, fields=fields, point_set_spec=ps)
    spec["note"] = ("draft 配置：model_id / 点集 / 适用范围 / 阈值四项需人确认后才能推进状态。"
                    "场级解由用户导出中；导出到位后用 init --export-dir 重新推导点集。")
    spec["not_a_solver"] = ("本配置用于 AI 求解器，但**未获放行前不得出现场解**；"
                            "不得声称等价于 COMSOL，不得用于工程绝对值。")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(spec, ensure_ascii=False, indent=1) + "\n",
                   encoding="utf-8", newline="\n")
    print("已写出草稿：%s（state=%s）" % (out, spec["state"]))
    print("下一步：填 model_id / point_set / applicability / thresholds 后跑 `validate`。")
    return 0


def _derive_point_set(d: pathlib.Path) -> tuple[dict | None, str]:
    """从场导出目录**推导**公共点集规格。取不到就如实说，不猜。"""
    if not d.is_dir():
        return None, "导出目录不存在：%s" % d
    npz = sorted(d.rglob("*.npz"))
    if not npz:
        return None, "目录里没有 .npz 场快照（%s）" % d
    try:
        import numpy as np
        z = np.load(npz[0])
        pts = next((z[k] for k in ("points", "coords", "xyz", "pod_points")
                    if k in z.files), None)
        if pts is None:
            return None, ("快照里找不到坐标键（现有键：%s）⇒ 点集规格待补"
                          % ", ".join(z.files[:8]))
        pts = np.asarray(pts)
        return ({"note": "由 %s 推导" % npz[0].name, "n_points": int(pts.shape[0]),
                 "shape": list(pts.shape)}, "从 %s 取到 %d 个点"
                % (npz[0].name, pts.shape[0]))
    except Exception as exc:
        return None, "读取快照失败（如实记录）：%s: %s" % (type(exc).__name__, exc)


def cmd_validate(a) -> int:
    s = _mod()
    try:
        spec = s.load_spec(a.spec)
    except Exception as exc:
        print("[FAIL] %s: %s" % (type(exc).__name__, exc))
        return 2
    print("[OK]  规格合法：solver_id=%s state=%s method=%s"
          % (spec["solver_id"], spec["state"], spec["method"]))
    print("      场：%s" % ", ".join("%s(%s)" % (f["name"], f["unit"]) for f in spec["fields"]))
    print("      点集：%s ｜ 掩膜策略=%s"
          % (spec["point_set"].get("points_file"), spec["point_set"]["mask_policy"]))
    print("      适用范围：%s" % json.dumps(spec["applicability"], ensure_ascii=False)[:200])
    return 0


def cmd_summary(a) -> int:
    s = _mod()
    print(json.dumps(s.spec_summary(s.load_spec(a.spec)), ensure_ascii=False, indent=1))
    return 0


def cmd_state(a) -> int:
    s = _mod()
    ev = {}
    if a.evidence:
        ev = json.loads(pathlib.Path(a.evidence).read_text(encoding="utf-8"))
    sign = ({"by": a.sign_by, "scope": a.scope} if a.sign_by else None)
    r = s.apply_state(a.spec, evidence=ev, sign_off=sign, drift_detected=a.drift,
                      write=a.apply)
    print(json.dumps(r, ensure_ascii=False, indent=1))
    if not r.get("allowed"):
        print("\n⇒ 门禁：**不跃迁**（原因见上）。这是期望行为，不是故障。")
    return 0 if (r.get("allowed") or not a.apply) else 2


def cmd_solve(a) -> int:
    s = _mod()
    spec = s.load_spec(a.spec)
    params = json.loads(a.params or "{}")
    r = s.solve(spec, params)
    print(json.dumps(r, ensure_ascii=False, indent=1))
    return 0 if r.get("refused") else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="AI 求解器底层配置（不做求解，只做配置与门禁）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="写出 draft 规格")
    p.add_argument("--solver-id", required=True)
    p.add_argument("--out", default=None)
    p.add_argument("--export-dir", default=None, help="场导出目录（用于推导公共点集）")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_init)

    p = sub.add_parser("validate", help="校验规格（fail-closed）")
    p.add_argument("--spec", required=True)
    p.set_defaults(fn=cmd_validate)

    p = sub.add_parser("summary", help="一页摘要")
    p.add_argument("--spec", required=True)
    p.set_defaults(fn=cmd_summary)

    p = sub.add_parser("state", help="算/应用放行状态跃迁")
    p.add_argument("--spec", required=True)
    p.add_argument("--evidence", default=None, help="S0–S5 证据 JSON")
    p.add_argument("--apply", action="store_true", help="真的写台账并回写 state")
    p.add_argument("--sign-by", default=None, help="人工签字者（approved_solver 必需）")
    p.add_argument("--scope", default=None, help="签字覆盖的适用范围")
    p.add_argument("--drift", action="store_true", help="本轮复检命中漂移 ⇒ 降级 suspended")
    p.set_defaults(fn=cmd_state)

    p = sub.add_parser("solve", help="演示门禁（未放行/越界会拒答）")
    p.add_argument("--spec", required=True)
    p.add_argument("--params", default="{}")
    p.set_defaults(fn=cmd_solve)

    a = ap.parse_args(argv)
    return int(a.fn(a))


if __name__ == "__main__":
    raise SystemExit(main())
