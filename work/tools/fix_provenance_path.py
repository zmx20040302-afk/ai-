"""纠正入库记录里的取证错误：`gui-sweep` run 的 model_path 指向了不存在的路径。

事实：
    入库时写的是 `C:\\Users\\zmx\\Desktop\\换能器\\b_GE_task3_2newyizu.mph`（**不存在**）；
    实际被扫描的模型是 `C:\\Users\\zmx\\Desktop\\b_GE_task3_2-newyizu.mph`
    （4,454 MB，sha256 `a9a177ad775c12a53c3b7b6e444a77d87f99ebcb8cd7b8d0ff02485c6db2e44f`），
    其名称与导出表元信息 `% Model,b_GE_task3_2-newyizu.mph` 一致。

纠正方式（**不静默覆盖**）：
    - 保留原字段不动，新增 `model_mph_path_corrected` / `model_mph_sha256` / `model_path_correction_note`；
    - 同步把纠正追加进 run 目录的 provenance.json 的 `corrections` 数组。
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb

WS = Path(r"C:\Users\zmx\Desktop\memsharness")
DB = WS / "work" / "store" / "mems.duckdb"
RUN = "gui-sweep-20260912T113936Z-bd387a56"
CORRECT = r"C:\Users\zmx\Desktop\b_GE_task3_2-newyizu.mph"
CORRECT_SHA = "a9a177ad775c12a53c3b7b6e444a77d87f99ebcb8cd7b8d0ff02485c6db2e44f"

con = duckdb.connect(str(DB))
row = con.execute("select settings from run where run_id = ?", [RUN]).fetchone()
settings = json.loads(row[0])
wrong = settings.get("model_mph_path")

settings["model_mph_path_corrected"] = CORRECT
settings["model_mph_sha256"] = CORRECT_SHA
settings["model_mph_sha256_note"] = (
    "2026-09-13 补哈希（当时误以为该文件被 GUI 占用；实测被占用的是 b_GE_task3_2new.mph）"
)
settings["model_path_correction_note"] = (
    f"入库时写入的路径 {wrong!r} 不存在，已纠正为 {CORRECT!r}；"
    "依据：导出表元信息 `% Model,b_GE_task3_2-newyizu.mph` + 冻结哈希记录 freeze_inputs.json"
)
con.execute("update run set settings = ? where run_id = ?", [json.dumps(settings, ensure_ascii=False), RUN])
con.close()
print("已纠正 run.settings：")
print(f"  原值（保留）    : {wrong}")
print(f"  纠正为          : {CORRECT}")
print(f"  哈希            : {CORRECT_SHA[:16]}…")

prov = WS / "work" / "runs" / RUN / "provenance.json"
data = json.loads(prov.read_text(encoding="utf-8"))
data.setdefault("corrections", []).append(
    {
        "at": "2026-09-13",
        "field": "model_mph",
        "wrong_value": wrong,
        "correct_value": CORRECT,
        "correct_sha256": CORRECT_SHA,
        "reason": "入库时把不存在的路径当成被扫描模型；以导出表元信息与冻结哈希为准",
    }
)
data["model_mph"] = {"path": CORRECT, "sha256": CORRECT_SHA}
prov.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"已追加纠正到 {prov}")
