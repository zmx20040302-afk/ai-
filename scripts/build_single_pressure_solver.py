# -*- coding: utf-8 -*-
"""把冻结 x 族缓存打包成可加载的单一复声压场求解器。

该脚本不运行 COMSOL，只读取已有缓存、点集和独立验证报告。两个 N1 分支必须分别给出，
生成的注册表明确禁止跨分支插值。
"""

from __future__ import annotations

import argparse
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from memsharness.single_pressure_solver import build_branch, write_registry


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--points", required=True, help="冻结公共点 TSV")
    ap.add_argument("--cache-n1-4", required=True)
    ap.add_argument("--report-n1-4", required=True)
    ap.add_argument("--cache-n1-7", required=True)
    ap.add_argument("--report-n1-7", required=True)
    ap.add_argument("--out-dir", default=str(REPO / "work/dist/single-pressure-solver-v1"))
    a = ap.parse_args(argv)
    out = pathlib.Path(a.out_dir)
    m4 = build_branch(a.cache_n1_4, a.points, a.report_n1_4, out, n1=4)
    m7 = build_branch(a.cache_n1_7, a.points, a.report_n1_7, out, n1=7)
    registry = write_registry([m4, m7], out / "registry.json")
    print("已构建：%s" % registry)
    print("分支：N1=4、N1=7；固定 N2=8、20 MHz；状态 draft")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
