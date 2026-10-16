# Single Pressure Solver v1

这是 `p_total_Pa` 的有界 AI 场求解器产物，不是 COMSOL 解，也不是四物理场联合 ROM。

已注册两个互相隔离的分支：

- N1=4、N2=8、20 MHz；
- N1=7、N2=8、20 MHz。

两个分支都只在 `x_scale∈[0.33,0.93]` 内允许预测。跨 N1、N2、频率或越出 x 证据范围
都会拒答并返回 COMSOL 补点计划。当前模型状态为 `draft`，尚未人工提升为
`approved_for_use`；S1/S2 已通过，S5 仍为 `inconclusive`。

从仓库根运行示例：

```powershell
work\.venv\Scripts\python.exe -X utf8 -m memsharness.single_pressure_solver `
  --registry work\dist\single-pressure-solver-v1\registry.json `
  --x 0.60 --n1 4 --n2 8 --freq 20000000 `
  --out work\runs\single-pressure\n1_4_x060.npz
```

输出 NPZ 包含：冻结点集 `points_xyz_m`、公共掩膜 `mask` 和复声压场 `p_total_Pa`。
命令行 JSON 同时给出来源类型、模型状态、S 级和场级相对 L2 误差带。

重建产物使用 `scripts/build_single_pressure_solver.py`。详细证据和不主张范围见
`docs/SINGLE_PRESSURE_SOLVER_20261016.md`。
