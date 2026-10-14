"""M0：锁定唯一母版 + 建立工作副本 + 生成 model_build_manifest.json 与 effective_parameter_ledger.csv。

依据 Codex《模型搭建启动与执行指令》§2 / §2.1：
- **先算源文件 SHA256，不等于 0f75ca…9552d 就立即停止**（禁止凭文件名猜）；
- 不覆盖源模型；工作副本落在 `work\models\`（仓库内、gitignore）；
- 参数账本：同名取**最后一次赋值**；扫描下游引用（几何/材料/物理场/网格）；
  早期效验中"位移恰为 0.0"的参数标 `unverified_or_inactive`。

用法：python work\\tools\\m0_lock_master.py
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
import sys
import time
from pathlib import Path

REPO = Path(r"C:\Users\zmx\Desktop\memsharness")
SOURCE = Path(r"C:\Users\zmx\Desktop\b_GE_task3_2new.mph")
DECOY = Path(r"C:\Users\zmx\Desktop\换能器\b_GE_task3_2-new.mph")
M_TEXT = Path(r"C:\Users\zmx\Desktop\b_GE_task3_2new.m")   # 该母版的 .m 文本导出（静态权威来源）
MODELS = REPO / "work" / "models"
WORK_MODEL = MODELS / "b_GE_task3_2new_currentdrive_fmax45_v1.mph"
EXPECT_SHA = "0f75ca1df9262f27a79d69e4e1ede4f4ac321a2e1c14b4ccdadf4f07df09552d"

# 早期 14 参数效验（run audit-…fffb8987）结论：仅 v0 有效，下列 13 个位移恰为 0.0
ZERO_MOVE = {"h_tox", "h_box", "h_handle", "N_p_te1", "V_te1", "N_p_te2", "V_te2",
             "p_be1", "V_be1", "x_scale_2", "c_air", "f_min", "f_max"}
GEOM_EFFECTIVE = {"h_te", "h_pzt", "h_device", "h_parylene", "W_min", "N_mem",
                  "N_w_te1", "N_w_te2", "x_scale", "c_water", "fmax"}

SET_RX = re.compile(r"^model\.param\.set\('([^']+)',\s*'([^']*)'(?:,\s*'([^']*)')?\);\s*$")
SETIDX_RX = re.compile(r"^model\.param\.set\('([^']+)',\s*(.+?)\);\s*$")
REF_RX = re.compile(r"^model\.param\.set\('([^']+)',\s*(.*)\);\s*$")


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for blk in iter(lambda: fh.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def main() -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    MODELS.mkdir(parents=True, exist_ok=True)

    # ---------- M0.1 源模型身份校验（不通过即停）----------
    out = {"source_model": str(SOURCE), "source_bytes": None, "source_sha256": None,
           "expected_sha256": EXPECT_SHA, "identity_ok": False}
    if not SOURCE.is_file():
        print(f"[STOP] 源模型不存在：{SOURCE}")
        return 2
    out["source_bytes"] = SOURCE.stat().st_size
    out["source_sha256"] = sha256(SOURCE)
    out["identity_ok"] = out["source_sha256"] == EXPECT_SHA
    print(f"源模型 {SOURCE.name}｜{out['source_bytes']} B")
    print(f"  sha256 = {out['source_sha256']}")
    print(f"  期望   = {EXPECT_SHA}")
    print(f"  身份校验 = {'通过' if out['identity_ok'] else '不通过'}")
    if not out["identity_ok"]:
        print("[STOP] 源模型 SHA256 与 Codex 指定的母版不符 —— 按指令立即停止，不按文件名猜测。")
        return 2

    if DECOY.is_file():
        dec = sha256(DECOY)
        print(f"易混模型 {DECOY.name}｜{DECOY.stat().st_size} B｜sha256 {dec[:16]}…"
              f"（{'与母版不同，保持原状' if dec != EXPECT_SHA else '⚠ 与母版相同！'}）")
        out["decoy"] = {"path": str(DECOY), "bytes": DECOY.stat().st_size, "sha256": dec}

    # ---------- M0 工作副本（不覆盖源；已存在则只读复用，不重复改名）----------
    t0 = time.strftime("%Y-%m-%dT%H:%M:%S")
    if WORK_MODEL.is_file():
        print(f"工作副本已存在，沿用（不覆盖）：{WORK_MODEL}")
    else:
        shutil.copy2(SOURCE, WORK_MODEL)
        print(f"已建立工作副本：{WORK_MODEL}")
    manifest = {
        "kind": "model_build_manifest",
        "phase": "M0",
        "source_model_path": str(SOURCE),
        "source_model_sha256": out["source_sha256"],
        "source_model_bytes": out["source_bytes"],
        "working_model_path": str(WORK_MODEL),
        "working_model_sha256_before_change": sha256(WORK_MODEL),
        "working_model_sha256_after_change": None,   # M2 改 fmax 后回填
        "copy_time": t0,
        "comsol_version": "6.4",
        "mph_version": "1.4.0",
        "change_log": [],
        "rules": {
            "overwrite_source": False,
            "drive_modes_must_not_share_file": True,
            "current_drive_mode": "circuit_terminal_1ohm_current_model",
            "ideal_reverse_drive_requires_new_branch": True,
        },
        "m_text_source": {"path": str(M_TEXT), "sha256": sha256(M_TEXT) if M_TEXT.is_file() else None,
                          "note": "该母版的静态 .m 文本导出；参数账本的同名取最后一次赋值即基于此文件"},
    }

    # ---------- M0.1 参数生效账本 ----------
    ledger = []
    if M_TEXT.is_file():
        lines = M_TEXT.read_text(encoding="utf-8", errors="replace").splitlines()
        last: dict[str, tuple[int, str]] = {}
        all_loc: dict[str, list[int]] = {}
        for i, raw in enumerate(lines, start=1):
            s = raw.strip()
            if not s.startswith("model.param.set("):
                continue
            m = SET_RX.match(s) or SETIDX_RX.match(s)
            if not m:
                continue
            name = m.group(1)
            val = m.group(2).rstrip(",").strip().strip("'")
            all_loc.setdefault(name, []).append(i)
            last[name] = (i, val)
        usage: dict[str, dict[str, list[int]]] = {}
        for i, raw in enumerate(lines, start=1):
            s = raw.strip()
            if not s.startswith("model.") or s.startswith("model.param."):
                continue
            for name in last:
                if re.search(rf"\b{re.escape(name)}\b", s):
                    for key, pat in (("geometry", ".geom("), ("material", ".material("),
                                     ("physics", ".physics("), ("mesh", ".mesh("),
                                     ("variable", ".variable("), ("study", ".study("),
                                     ("selection", ".selection(")):
                        if pat in s:
                            usage.setdefault(name, {}).setdefault(key, []).append(i)
                            break
                    else:
                        usage.setdefault(name, {}).setdefault("other", []).append(i)
        for name in sorted(last):
            line, val = last[name]
            u = usage.get(name, {})
            if name in ZERO_MOVE:
                status = "unverified_or_inactive"
            elif name in GEOM_EFFECTIVE or name == "v0":
                status = "active_confirmed_or_evidence_backed"
            else:
                status = "active_unverified"
            unit = "—"
            mu = re.match(r"^[-+0-9.eE]+\s*\[?([a-zA-Z%]+)\]?$", val)
            if mu:
                unit = mu.group(1)
            ledger.append({
                "parameter_name": name,
                "final_effective_value": val,
                "unit": unit,
                "all_assignment_locations": ";".join(f"L{i}" for i in all_loc[name]),
                "last_assignment_location": f"L{line}",
                "downstream_geometry_references": ";".join(f"L{i}" for i in u.get("geometry", [])) or "",
                "downstream_material_references": ";".join(f"L{i}" for i in u.get("material", [])) or "",
                "downstream_physics_references": ";".join(f"L{i}" for i in u.get("physics", [])) or "",
                "downstream_mesh_references": ";".join(f"L{i}" for i in u.get("mesh", [])) or "",
                "perturbation_test_before": ("仅 v0：相对变化 5.000e-02（=扰动幅度，线性）"
                                             if name == "v0" else
                                             ("0.0（位移恰为 0，run audit-…fffb8987）"
                                              if name in ZERO_MOVE else "未测")),
                "perturbation_test_after": "待在新分支重做基准扰动签名（M0.1 要求）",
                "activation_status": status,
            })
        manifest["ledger_stats"] = {
            "n_parameters": len(ledger),
            "n_unverified_or_inactive": sum(1 for r in ledger if r["activation_status"] == "unverified_or_inactive"),
            "n_evidence_backed": sum(1 for r in ledger
                                     if r["activation_status"] == "active_confirmed_or_evidence_backed"),
        }

    (MODELS / "model_build_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    if ledger:
        with (MODELS / "effective_parameter_ledger.csv").open("w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=list(ledger[0]))
            w.writeheader()
            w.writerows(ledger)

    print(f"\nmanifest → {MODELS / 'model_build_manifest.json'}")
    print(f"ledger   → {MODELS / 'effective_parameter_ledger.csv'}"
          f"（{len(ledger)} 参数；{manifest.get('ledger_stats')}）")
    print("\n关键参数（含末次覆盖）：")
    for r in ledger:
        if r["parameter_name"] in ("N_w_te2", "x_scale", "N_w_te1", "W_min", "N_mem", "fmax", "v0"):
            print(f"  {r['parameter_name']:<10} = {r['final_effective_value']:<18}"
                  f" 末次 {r['last_assignment_location']:<7} 赋值处 {r['all_assignment_locations']:<14}"
                  f" → {r['activation_status']}")
    print(f"\n[脚本与产物哈希]")
    print(f"  m0_lock_master.py = {sha256(Path(__file__).resolve())[:16]}…")
    print(f"  working model     = {manifest['working_model_sha256_before_change'][:16]}…")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
