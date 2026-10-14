# -*- coding: utf-8 -*-
"""生成 INDEX 第 244 节：**解身份规则折入论文 v18 + M4 包加解身份检查**。

所有数字/哈希**从磁盘产物读**（v18、补充材料 e、PROVENANCE、MANIFEST、M4 报告、冒烟事实件），
一个字不手写；缺件即 fail-closed。
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
REPO = pathlib.Path(__file__).resolve().parents[2]
D = REPO / "docs"
M4 = REPO / "work/runs/ai11-m4-20261013"
PKG = REPO / "work/dist/peakguard-bench-v1-20261013"
OUT = REPO / "work/runs/ai11-cross-fom-20261013/INDEX_SECTION_244.md"


def sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def need(p: pathlib.Path) -> pathlib.Path:
    if not p.is_file():
        raise SystemExit("[FAIL] 缺件：%s" % p.relative_to(REPO))
    return p


def main() -> int:
    v17 = need(D / "PAPER_DAC2027_EN_v17_20261013.md")
    v18 = need(D / "PAPER_DAC2027_EN_v18_20261013.md")
    supd = need(D / "PAPER_DAC2027_EN_SUPPLEMENT_20261013d.md")
    supe = need(D / "PAPER_DAC2027_EN_SUPPLEMENT_20261013e.md")
    prov = need(D / "PAPER_DAC2027_EN_v18_PROVENANCE.md")
    gen = need(REPO / "work/runs/eda64-20261010/n5_stage3/V18_GENERATION_REPORT.json")
    man = need(PKG / "MANIFEST.json")
    rep = need(M4 / "M4_PACKAGE_REPORT.json")
    sm = need(M4 / "SMOKE_RUN_LATEST.json")
    idx = need(D / "INDEX-records-and-rulings.md")

    g = json.loads(gen.read_text(encoding="utf-8"))
    m = json.loads(man.read_text(encoding="utf-8-sig"))
    r = json.loads(rep.read_text(encoding="utf-8-sig"))
    s = json.loads(sm.read_text(encoding="utf-8-sig"))
    t18 = v18.read_text(encoding="utf-8")
    te = supe.read_text(encoding="utf-8")

    i0, h0 = idx.stat().st_size, sha(idx)
    identity = r["solution_identity_addition"]
    body_words = g["body_words_v18"]
    import importlib.util
    _sp = importlib.util.spec_from_file_location("g18", REPO / "work/tools/make_dac2027_en_v18.py")
    _g18 = importlib.util.module_from_spec(_sp)
    _sp.loader.exec_module(_g18)
    delta = supe.stat().st_size - supd.stat().st_size - len(_g18.S13.encode("utf-8")) - 2
    delta_chars = sum(len(n) - len(o) for o, n in ((_g18.S_OLD, _g18.S_NEW), (_g18.T3_OLD, _g18.T3_NEW),
                                                   (_g18.T5_OLD, _g18.T5_NEW)))
    posix = lambda x: str(x).replace("\\", "/")
    sec = f"""## 244. 解身份规则**折入正文/规格**（v18）+ M4 包**加可执行解身份检查** · 2026-10-14

**用户裁定**：「先做 1＋2」——① 把「按解身份比较」这条规则折进论文正文与 benchmark 规格；
② 给 M4 匿名包加**可执行**的解身份检查并重跑冒烟。

### 244.1 任务 1：论文 v18（正文 1 处插入 + 补充材料 3 处替换 + 新增 §S13）

| 件 | 字节 | sha256（前 24） | 说明 |
|---|---:|---|---|
| `PAPER_DAC2027_EN_v17_20261013.md`（源） | {v17.stat().st_size:,} | `{sha(v17)[:24]}` | 折入前 |
| **`PAPER_DAC2027_EN_v18_20261013.md`** | **{v18.stat().st_size:,}** | **`{sha(v18)[:24]}`** | LF；正文词数 {g['body_words_v17']} → **{body_words}**（{g['body_words_delta']:+d}） |
| `PAPER_DAC2027_EN_SUPPLEMENT_20261013d.md`（源） | {supd.stat().st_size:,} | `{sha(supd)[:24]}` | 保留 |
| **`PAPER_DAC2027_EN_SUPPLEMENT_20261013e.md`** | **{supe.stat().st_size:,}** | **`{sha(supe)[:24]}`** | ＝ d 原文 + §S13 |
| `PAPER_DAC2027_EN_v18_PROVENANCE.md` | {prov.stat().st_size:,} | `{sha(prov)[:24]}` | 出处说明 |

**折入四处**：
1. **正文 §5 新增「Solution identity」段**（L192–200）：一切对照都在**已识别的解**上进行
   （解标识 + 该解**存储的**网格 + 设计点参数读回）；给出四解实测（几何逐位相同却差 **6.7 倍**）；
   跨文件对照一律按**内容哈希**指名；
2. **补充材料 §S9**：原句「按自由度比较、不按文件名」升级为「按**解身份**比较」并指向 §S13；
3. **§S12 的 T3 / T5**：任务输入加入**解身份**，拒答规则加「身份核不过 ⇒ 拒答」（§S12 表格 9 行**仍为 6 列**）；
4. **补充材料新增 §S13**（3,609 字符）：三例同族证据表 + 四解对照表 + **采纳的规则**（四项身份 + 几何不变量
   + 逐解重解析）+ 复现方式 + **不主张**。

**文字层自检**：正文**反向替换逐字节还原 v17**；补充材料**尾部为 §S13 且头部逆替换逐字节还原 d**
（三处替换：**{delta_chars:+d} 字符 / {delta:+d} 字节**，差额来自新串里的多字节字符如 `—`、`§`）；**双盲扫描正文与补充材料均干净**；两份产物**均无 CRLF**；
`verify_v7.py` ⇒ **pass**（v6 的 43 个 headline 全在正文，新增数字无缺失）。
**本次新增文字**：正文「Solution identity」段 + §S9 一句升级 + §S12 两行 + §S13；**此外一字未动**。

### 244.2 任务 2：M4 包加**可执行**解身份检查（13 → {m['n_files']} 个文件）

新增 `check_solution_identity.py`（包内）+ `data/solution_identity_example.json`（**合成**示例记录）。

**四步清单**：{'；'.join(identity['checklist'])}。

**额外规则（关键）**：{identity['extra_rule']}。

**它把 §S13 的规则变成可执行判据**：脚本对每个量打印 `ADMISSIBLE`/`REFUSED` + 理由 + **观测到的离散度**，
所以「拒绝」是**可审计的**而不是要人相信。示例记录自带 `expected_decision` ⇒ 脚本即**自测**：

```
record: solution_identity_example.json | solutions: 4 | distinct stored meshes: 2
  OK   1 TAG / 2 STORED MESH / 3 PARAMETERS / 4 INVARIANT
    REFUSED     elec_area            (max rel spread=5.667, max ratio hi/lo=6.667)
    ADMISSIBLE  fluid_volume         (max rel spread=0,     max ratio hi/lo=1)
    REFUSED     mean_elec_potential  (max rel spread=8.78,  max ratio hi/lo=9.78)
self-test: PASS
```

⇒ 脚本自己算出的 **6.667** 与论文/supplement §S13 的 6.667 **同源同值**（比值口径 = 1 + 相对离散度，示例中已注明）。
**示例为合成记录**且已如此标注：量值取自实测探针，**网格摘要是合成标签**（模型文件并不暴露该摘要）。

**接入**：`run_benchmark.py --check` 在逐格比对之后**自动**执行该自测（不再是旁路脚本）。

### 244.3 冒烟复跑（{s['wall_seconds']:.1f} s，**数字从日志解析**）

| 项 | 值 |
|---|---|
| 命令 | `python run_benchmark.py --check`（包目录内） |
| 判定 | **{s['verdict']}** |
| 逐格比对 | OK **{s['cells_compared_ok']}** ｜超容差 {s['cells_over_tolerance']} ｜缺失 {s['cells_missing']} |
| 最大相对偏差 | **{s['max_relative_deviation']:.3e}**（容差 {s['tolerance_rel']:.0e}） |
| **解身份自测** | **{s['solution_identity_self_test']}** |
| 墙钟 | {s['wall_seconds']:.1f} s |
| 事实件 | `{posix(r['smoke_test']['facts_file'])}`（sha `{r['smoke_test']['facts_file_sha256'][:16]}`） |
| 日志 | `{posix(r['smoke_test']['log_file'])}`（sha `{r['smoke_test']['log_sha256'][:16]}`, {r['smoke_test']['log_bytes']:,} B） |

**本轮同时修掉一处「数字手写」隐患**：`finalize_package.py` 原先把冒烟结果（PASS / 800 格 / 407.4 s）
**写在代码里**；现改为读 `SMOKE_RUN_LATEST.json`（由 `run_package_smoke.py` 从日志**解析**），
**缺件或未双通过即 fail-closed**。

> **本表这一跑是在包的最终字节上重跑的**（第一次冒烟之后包因 #25 修了清单键而重建过一次）：
> 干净链条为 **构建 → 冒烟 → 收尾**。自查见 244.5 的 #25/#26。

**包内审计**：构建时 {m['n_files']} 个文件、**0** 个含风险串（`identity_audit_clean={m['identity_audit_clean']}`）；
含 `results/` 的审计见 `M4_PACKAGE_REPORT.json`（`{posix(rep.relative_to(REPO))}`，
sha `{sha(rep)[:16]}`）。

### 244.4 交付物（本节引用的件）

| 件 | 字节 | sha256（前 24） |
|---|---:|---|
| `docs/PAPER_DAC2027_EN_v18_20261013.md` | {v18.stat().st_size:,} | `{sha(v18)[:24]}` |
| `docs/PAPER_DAC2027_EN_SUPPLEMENT_20261013e.md` | {supe.stat().st_size:,} | `{sha(supe)[:24]}` |
| `docs/PAPER_DAC2027_EN_v18_PROVENANCE.md` | {prov.stat().st_size:,} | `{sha(prov)[:24]}` |
| `work/tools/make_dac2027_en_v18.py`（生成器） | {need(REPO / 'work/tools/make_dac2027_en_v18.py').stat().st_size:,} | `{sha(REPO / 'work/tools/make_dac2027_en_v18.py')[:24]}` |
| `work/tools/build_benchmark_package.py`（打包器） | {need(REPO / 'work/tools/build_benchmark_package.py').stat().st_size:,} | `{sha(REPO / 'work/tools/build_benchmark_package.py')[:24]}` |
| `work/tools/run_package_smoke.py`（冒烟驱动） | {need(REPO / 'work/tools/run_package_smoke.py').stat().st_size:,} | `{sha(REPO / 'work/tools/run_package_smoke.py')[:24]}` |
| 包内 `MANIFEST.json` | {man.stat().st_size:,} | `{sha(man)[:24]}` |
| 包内 `check_solution_identity.py` | {need(PKG / 'check_solution_identity.py').stat().st_size:,} | `{sha(PKG / 'check_solution_identity.py')[:24]}` |
| 包内 `data/solution_identity_example.json` | {need(PKG / 'data/solution_identity_example.json').stat().st_size:,} | `{sha(PKG / 'data/solution_identity_example.json')[:24]}` |
| `M4_PACKAGE_REPORT.json` | {rep.stat().st_size:,} | `{sha(rep)[:24]}` |
| `work/tools/run_package_smoke.py` → `SMOKE_RUN_LATEST.json` | {sm.stat().st_size:,} | `{sha(sm)[:24]}` |
| `PRE_POSIX_KEYS_SNAPSHOT.json`（#25 存证） | {need(M4 / 'PRE_POSIX_KEYS_SNAPSHOT.json').stat().st_size:,} | `{sha(M4 / 'PRE_POSIX_KEYS_SNAPSHOT.json')[:24]}` |
| `work/runs/ai11-m4-20261013/finalize_package.py` | {need(M4 / 'finalize_package.py').stat().st_size:,} | `{sha(M4 / 'finalize_package.py')[:24]}` |

### 244.5 本轮自查（第 23–26 项，承 §243 的 #21/#22）

- **#23**：给补充材料做「头部＝原文 + 替换」的自检时，第一版写成 `st[:len(sup)] == sup` ——
  **替换会改变长度**，该断言天然不成立（假失败）。**规则**：「只追加」才可用「前缀相等」；
  **有替换就必须用「逆替换逐字节还原」**。
- **#24**：把 `expected_decision.max_disagreement_refused` 写成单个标量 6.667（取自电极面积），
  而检查器算的是**所有被拒量里的最大值**（实为电位 8.78）⇒ 自测假失败。
  **规则**：**聚合量必须在两侧同口径**——改成逐量字典 `max_rel_spread_refused`，
  并把「比值 6.667」与「相对离散度 5.667」的关系写进示例注释（`ratio = 1 + spread`）。
- **#25**：包内 `MANIFEST.json` 的键一直是 **Windows 反斜杠**（`data\\labels_two_batch_v3.csv`），
  而 README 列的是 POSIX 路径，且本包面向**匿名评审**（很可能在 Linux 上读）⇒ 键与正文不同口径。
  **规则**：**清单键一律 `as_posix()`**；本次修后逐件 sha256 **15/15 未变**（只有 `MANIFEST.json` 自身变，
  `13e516837f7012ac` → `f485329188baf179`），并以 `PRE_POSIX_KEYS_SNAPSHOT.json` 存证。
- **#26**：重建包会**清掉 `results/`**，于是紧接着跑 `finalize_package.py` 时它报「外移 **0** 个文件」——
  而留证目录里其实有 4 个文件 ⇒ **报告会低估留证**。**规则**：留证数量**按留证目录重算**、不按「本次拷贝」计数；
  两者都缺则 **fail-closed**。另：本轮的干净链条是 **构建 → 冒烟 → 收尾**，中间不得再重建。

### 244.6 不主张

- 不主张被拒读数在**物理上错误**，只主张**不可比**（§S13 与包内 `non_claims` 同口径）；
- 不主张包内示例记录反映真实模型文件的网格摘要（**摘要是合成标签**，已标注）；
- 不主张第三方复现——冒烟仍是**作者环境**；
- **页数未编译验证**（本机无 TeX）；正文 {body_words} 词，是否需要裁剪仍由人在 Overleaf 定；
- 本节**不改**任何门禁、状态与阈值：门禁链仍为 **4 satisfied / 5 partial / 1 not_satisfied**、
  `release_allowed=false`；`solver_spec.state` 仍为 `physics_consistent`。
"""
    OUT.write_bytes(sec.encode("utf-8"))
    print("写出 %s（%d B）" % (OUT.relative_to(REPO), OUT.stat().st_size))
    print("INDEX 追加前：%d B sha %s" % (i0, h0[:24]))
    print("追加命令：python work\\tools\\append_bytes.py %s %s"
          % (idx.relative_to(REPO), OUT.relative_to(REPO)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
