"""核对基线求解的落档：停用验证、参数回读、7 个频点、目标量数组的长度与逐频点摘要。"""

from __future__ import annotations

import json
from pathlib import Path

RUN = Path(
    r"C:\Users\zmx\Desktop\memsharness\work\runs\baseline-20260912T024332Z-8ab4eb6e\baseline.json"
)
data = json.loads(RUN.read_text(encoding="utf-8"))

print(f"文件大小：{RUN.stat().st_size/1e6:.2f} MB")
print(f"run_id={data['run_id']}  study={data['study']}  kept={data['kept_steps']}")
print(f"solve_ok={data['solve_ok']}  solve_seconds={data['solve_seconds']}  wall={data['wall_seconds']}")
print(f"server_started_by_script={data.get('server_started_by_script')}")
print(f"n_solutions={data['n_solutions']}  用解数量验证步已停用={data['steps_disabled_verified_by_solution_count']}")

print("\n== 停用明细 ==")
for d in data["disabled_steps"]:
    print(f"  {d['tag']}: method={d['method']} verified_inactive={d['verified_inactive']} error={d['error']}")

print("\n== steps_before ==")
for s in data["steps_before"]:
    print(f"  {s['tag']} type={s['type']} active_before={s.get('active_before')}")

print(f"\n== 基线参数（{len(data['baseline_parameters'])} 个，非空 {sum(1 for v in data['baseline_parameters'].values() if v)}）==")
for k in ("x_scale", "x_scale_2", "N_w_te1", "N_w_te2", "N_mem", "W_min", "R_mem", "v0", "V_te1", "V_te2", "V_be1", "fmax"):
    print(f"  {k:10s} = {data['baseline_parameters'].get(k)}")

print(f"\n== 频率点 ==")
print(f"  {data['frequencies_hz']}")

print("\n== 目标量（probe_targets 的标量摘要 = 求值集上的最大幅值）==")
for k, v in data["targets"].items():
    print(f"  {k:8s} = {v:.6g}")

print("\n== target_series 数组长度（判断是逐频点还是逐节点）==")
for k, arr in data["target_series"].items():
    n = len(arr) if isinstance(arr, list) else None
    print(f"  {k:8s} len={n}" + (f"  前 7 个={[f'{x:.4g}' for x in arr[:7]]}" if n else ""))

print("\n== 落档文件 ==")
for p in sorted(RUN.parent.iterdir()):
    print(f"  {p.name:16s} {p.stat().st_size/1e6:.2f} MB")
