"""任意 COMSOL 模型的参数读取 / 写入 / 效验层（技能 ``model-io`` 的代码实现）。

设计基线（严格沿用既有通路，不另起一套）：

- **只读优先**：原模型永不改动。所有操作先把 ``.mph`` 复制到 ``work\\models\\...`` 暂存区
  （复用 :func:`memsharness.onboard.stage_model` 的递增副本 + WinError 32 处理），
  记录源路径与 SHA256，并在结束后核对原件哈希未变。
- **执行通路**：与 :mod:`memsharness.comsol.java_model` / :mod:`memsharness.comsol.queue`
  一致——生成**全 ASCII** 的 Java 源码 → ``comsolcompile.exe`` → ``comsolbatch.exe``，
  结果通过 stdout 上的 ``MEMS_RESULT_JSON={...}`` 标记回传，
  运行目录固定为 ``work\\runs\\<run_id>\\``（含 ``commands.json`` / ``status.json`` /
  ``batch.stdout.log``）；命令构造与日志解码复用 :class:`memsharness.comsol.backend.LocalComsolBackend`，
  失败归因复用 :func:`memsharness.comsol.diagnostics.classify_failure`。
- **Java 侧不接收任何路径**：``ModelUtil.load("input.mph")`` / ``model.save("...")`` 一律用
  **相对文件名**，调用方把工作目录设为 run 目录。中文路径因此永远不进命令行，绕开
  「中文路径 + 参数编码」的不确定性。
- **诚实失败**（AGENTS.md 红线 3）：读不到的项一律进 ``readback`` 列表并附
  ``source``（用了哪个 API）与 ``reason``，绝不根据文件名、目录名或行业惯例推断模型内部设置。
- **两个权威来源不合并**：``parse_matlab_export``（GUI 导出的 Model M-file，权威文本）
  与 ``probe_model``（运行时 API 读回，权威运行时）经 :func:`cross_check` **只报差异**，
  不取平均、不选一个当作对的。
- **第三个权威来源：本地 schema**。COMSOL 自带的 API 补全数据
  ``<comsol home>/data/completion/physics.xml`` 是**离线权威 schema**：它给出每个物理场
  特征的**真实属性名**、默认值、**合法枚举值**与人类可读标签。由
  :func:`lookup_feature_schema` / :func:`lookup_enum` / :func:`validate_enum_value` 查询，
  并被 :func:`parse_matlab_export` 与 :func:`cross_check` 用作**枚举合法性校验**
  （非法取值必须报出来，不得因为"文本与运行态一致"就放过）。
  找不到该文件时**优雅降级并说明缺失**（``available=False`` + 探测记录），绝不静默假装通过。

已知实测坑（本模块内已规避，勿重复试错）：

- 生成源码必须全 ASCII：运行时读回的中文字符串（参数描述、物理场标签）在写进 Java 前
  统一做 ``\\uXXXX`` 转义（转义序列本身全是 ASCII，JVM 运行时复原为真实字符），
  因此既过了 ASCII 守卫，又不丢中文。
- 批处理暴露的 ``PhysicsFeature`` **没有** ``getEnum()``：枚举原文（如 ``forceType``）只能
  用 ``getString()`` 回读；本模块只读这类属性，改参一律走全局参数表。
- 属性名不可猜：探针先用 ``properties()`` 取真实属性清单，再逐项 ``getString()`` 回读；
  单项失败只记录**该项**，不影响整块结果。
- 2D 边界载荷没有 ``Fy``、向量属性 ``F`` 要求长度 3：属于模板层写属性的事，本模块不碰。
- **``set("forceType", "Pressure")`` 是非法值**：2D 结构力学 ``BoundaryLoad`` 的合法取值里
  没有 ``Pressure``（压力载荷的枚举是 ``FollowerPressure``）。写入非法值时 ``set()`` 抛异常，
  若被 ``catch`` 吞掉，``forceType`` 就停在默认值 ``ForceArea``，而该模式下 ``pressure``
  属性不生效 ⇒ **载荷为零、位移恒为 0**（实测 run-20260911T030051Z-08e8921a：6410 单元、
  26954 自由度、d_tip=0.0）。注意人类标签 ``descrs`` 里确实出现过 ``Pressure`` 字样——
  它是**标签**不是**取值**，只看标签就会误判。这正是本模块引入 schema 校验要防的错误类型。
- ``MeshSequence.getVertex()`` 返回 ``[ndim][nvertices]``（列主序），不是 ``[nvertices][ndim]``：
  按行主序读会得到假包围盒（实测过一次 ``[0,0]×[0,1.25e-05]``）。
- ``Selection.entities()`` 返回 ``int[]``，不是 ``String[]``（用 ``javap`` 对 6.4 的 jar 实测确认）。

失败模式（概览；每个函数 docstring 有更细的说明）：

模型不存在 / 扩展名不是 ``.mph`` → :class:`FileNotFoundError` / :class:`ModelIOError`（**无 run_id**，
因为任务根本没发出）；COMSOL 可执行文件缺失 → :class:`ModelIOError`；编译失败 / 批处理非零退出 /
超时 → 返回 ``ok=False`` + ``diagnostic`` + ``run_id``（可查日志）；参数名不存在 → 整体拒绝并回列
合法参数名；参数名命中保留名黑名单 → 直接拒绝；表达式含换行 → :class:`ValueError`；
补全数据 XML 缺失/损坏 → schema 查询 ``available=False`` + 探测记录、枚举校验 ``checked=False``
（**未校验 ≠ 通过**）。不存在「静默返回空结果冒充成功」的路径。
"""

from __future__ import annotations

import glob
import json
import os
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from . import store as store_mod
from .comsol import diagnostics
from .comsol import java_model
from .comsol.backend import LocalComsolBackend, sha256_file
from .onboard import COMSOL_HOME, EFFECT_TOL, GEOMETRY_TOL, sha256_of, stage_model
from .paths import work_root as default_work_root

__all__ = [
    "MODELIO_VERSION",
    "PROBE_MARKER",
    "SET_MARKER",
    "RESERVED_PARAM_NAMES",
    "ModelIOError",
    "render_probe_source",
    "render_set_source",
    "probe_model",
    "set_parameters",
    "effect_audit",
    "extract_outputs_from_log",
    "parse_matlab_export",
    "cross_check",
    "save_probe",
    "find_completion_xml",
    "schema_available",
    "schema_source",
    "lookup_feature_schema",
    "lookup_enum",
    "lookup_feature_type_doc",
    "validate_enum_value",
    "clear_schema_cache",
    "build_enum_validation",
]

# 抽取器版本：读取/解析逻辑一改，此版本必须变（dataset-contract 第 4 节）
MODELIO_VERSION = "memsharness.modelio@0.2.0"

# stdout 标记（沿用 java_model 的 MEMS_* 约定）
PROBE_MARKER = "MEMS_RESULT_JSON="
SET_MARKER = "MEMS_SAVED="
GEOMETRY_MARKER = "MEMS_GEOMETRY="
SELECTIONS_MARKER = "MEMS_NAMED_SELECTIONS="
DONE_MARKER = "MEMS_DONE=1"

# 保留名黑名单：命中即拒绝写入（技能 model-io 的实测踩坑，不是推测）
RESERVED_PARAM_NAMES = frozenset({"h", "E", "nu", "rho", "T", "k"})

_JOB_PROBE = "probe"
_JOB_SET = "set_parameters"


class ModelIOError(RuntimeError):
    """模型读写的前置条件不满足（文件缺失/扩展名错/COMSOL 不可用/命中保留名）。

    与「求解失败」区分：本异常表示**根本没能发出任务**，因此不会有 run_id；
    求解失败则返回带 ``run_id`` + ``diagnostic`` 的字典，可去 run 目录查日志（红线 1）。
    """


# ======================================================================================
# Java 探针模板（全 ASCII；运行时字符串走 \uXXXX 转义）
# ======================================================================================

_PROBE_TEMPLATE = r'''import com.comsol.model.*;
import com.comsol.model.util.*;

/**
 * Auto-generated READ-ONLY model probe (memsharness.modelio @@VERSION@@).
 * ASCII-only on purpose: javac reads sources in the platform code page.
 *
 * Loads the .mph given as a RELATIVE file name in the working directory and prints
 * exactly one machine-readable line: @@MARKER@@{...}
 * Everything the batch API cannot read is recorded in "readback" with the API that
 * was tried and the reason it failed. Nothing is inferred from the file name.
 */
public class @@CLASS@@ {

  private static final java.util.List<String> READBACK = new java.util.ArrayList<String>();
  private static final java.util.List<String> NOTES = new java.util.ArrayList<String>();

  private static void note(String level, String item, String source, String reason) {
    StringBuilder sb = new StringBuilder("{");
    sb.append("\"level\":").append(esc(level));
    sb.append(",\"item\":").append(esc(item));
    sb.append(",\"source\":").append(esc(source));
    sb.append(",\"reason\":").append(esc(reason));
    sb.append("}");
    READBACK.add(sb.toString());
  }

  private static void ok(String item, String source) {
    note("read", item, source, null);
  }

  private static void failed(String item, String source, Throwable e) {
    note("unreadable", item, source, e == null ? "unknown" : (e.getClass().getName() + ": " + e.getMessage()));
  }

  private static String esc(String s) {
    if (s == null) return "null";
    StringBuilder sb = new StringBuilder("\"");
    for (int i = 0; i < s.length(); i++) {
      char c = s.charAt(i);
      if (c == '"') sb.append("\\\"");
      else if (c == '\\') sb.append("\\\\");
      else if (c == '\n') sb.append("\\n");
      else if (c == '\r') sb.append("\\r");
      else if (c == '\t') sb.append("\\t");
      else if (c < 32 || c > 126) sb.append(String.format("\\u%04x", (int) c));
      else sb.append(c);
    }
    return sb.append('"').toString();
  }

  private static String num(Double x) {
    if (x == null || x.isNaN() || x.isInfinite()) return "null";
    return String.format(java.util.Locale.ROOT, "%.12g", x);
  }

  private static String intArr(int[] values) {
    StringBuilder sb = new StringBuilder("[");
    for (int i = 0; i < values.length; i++) {
      if (i > 0) sb.append(",");
      sb.append(values[i]);
    }
    return sb.append("]").toString();
  }

  private static String strArr(String[] values) {
    StringBuilder sb = new StringBuilder("[");
    for (int i = 0; i < values.length; i++) {
      if (i > 0) sb.append(",");
      sb.append(esc(values[i]));
    }
    return sb.append("]").toString();
  }

  // NOTE: ModelUtil.Selection.entities() returns int[] (verified with javap against the
  // COMSOL 6.4 jars: "public abstract int[] entities();"), so entity ids are used directly.

  // MeshSequence.getVertex() returns [ndim][nvertices] (COLUMN-major), verified live against
  // COMSOL 6.4: for the measured 2D beam it returned length 2 with 3534 entries per row, i.e.
  // row 0 = all x coordinates, row 1 = all y coordinates - NOT a vertex-major coordinate list.
  // Reading it as [nvertices][ndim] silently produced a bogus box ([0,0] x [0,1.25e-05]).
  private static String box(double[][] pts, int axis) {
    if (pts == null || pts.length <= axis) return "null";
    double[] row = pts[axis];
    if (row == null || row.length == 0) return "null";
    double lo = row[0];
    double hi = row[0];
    for (int i = 1; i < row.length; i++) {
      if (row[i] < lo) lo = row[i];
      if (row[i] > hi) hi = row[i];
    }
    return "[" + String.format(java.util.Locale.ROOT, "%.10g", lo)
        + "," + String.format(java.util.Locale.ROOT, "%.10g", hi) + "]";
  }

  /** Number of vertex columns (the longest row; equals nvertices for the measured mesh). */
  private static int nVertexColumns(double[][] pts) {
    if (pts == null) return 0;
    int best = 0;
    for (int i = 0; i < pts.length; i++) {
      if (pts[i] != null && pts[i].length > best) best = pts[i].length;
    }
    return best;
  }

  private static String typeOf(Object o) {
    try {
      return String.valueOf(o.getClass().getMethod("getType").invoke(o));
    } catch (Exception e) {
      return null;
    }
  }

  private static String labelOf(Object o) {
    try {
      return String.valueOf(o.getClass().getMethod("label").invoke(o));
    } catch (Exception e) {
      return null;
    }
  }

  private static String[] entitiesOf(Object o) {
    try {
      return (String[]) o.getClass().getMethod("entities").invoke(o);
    } catch (Exception e) {
      return null;
    }
  }

  public static Model run() throws java.io.IOException {
    // loadCopy keeps the on-disk .mph free of the load-time lock that a plain load()
    // would take (the copy lives inside the run directory, so either way the ORIGINAL
    // model is never touched).
    Model model = ModelUtil.loadCopy("Model", "@@INPUT@@");
    ok("model", "ModelUtil.loadCopy(@@INPUT@@)");

    // ---- global parameters ------------------------------------------------------
    String[] pnames = new String[0];
    try {
      pnames = model.param().varnames();
      ok("parameters", "model.param().varnames()");
    } catch (Exception e) {
      failed("parameters", "model.param().varnames()", e);
    }
    StringBuilder params = new StringBuilder("[");
    for (int i = 0; i < pnames.length; i++) {
      String pk = pnames[i];
      if (i > 0) params.append(",");
      String pexpr = null;
      try {
        pexpr = model.param().get(pk);
      } catch (Exception e) {
        failed("parameter[" + pk + "].expression", "model.param().get", e);
      }
      String pdesc = null;
      try {
        pdesc = model.param().descr(pk);
      } catch (Exception e) {
        failed("parameter[" + pk + "].description", "model.param().descr", e);
      }
      Double pval = null;
      String perr = null;
      try {
        pval = Double.valueOf(model.param().evaluate(pk));
      } catch (Exception e) {
        perr = e.getClass().getName() + ": " + e.getMessage();
        failed("parameter[" + pk + "].value", "model.param().evaluate", e);
      }
      params.append("{\"name\":").append(esc(pk));
      params.append(",\"expression\":").append(esc(pexpr));
      params.append(",\"description\":").append(esc(pdesc));
      params.append(",\"value\":").append(num(pval));
      params.append(",\"value_error\":").append(esc(perr)).append("}");
    }
    params.append("]");

    // ---- components, geometry entity counts -------------------------------------
    String[] components = new String[0];
    try {
      components = model.modelNode().tags();
      ok("components", "model.modelNode().tags()");
    } catch (Exception e) {
      failed("components", "model.modelNode().tags()", e);
    }
    StringBuilder geom = new StringBuilder("[");
    StringBuilder bbox = new StringBuilder("[");
    StringBuilder mesh = new StringBuilder("[");
    boolean firstBox = true;
    boolean firstMesh = true;
    for (int ci = 0; ci < components.length; ci++) {
      String ct = components[ci];

      String[] gtags = new String[0];
      try {
        gtags = model.component(ct).geom().tags();
      } catch (Exception e) {
        failed("component[" + ct + "].geom.tags", "component.geom().tags()", e);
      }
      for (int gi = 0; gi < gtags.length; gi++) {
        String gt = gtags[gi];
        Integer dim = null;
        Integer nv = null;
        Integer ne = null;
        Integer nb = null;
        Integer nd = null;
        try {
          dim = Integer.valueOf(model.component(ct).geom(gt).getSDim());
        } catch (Exception e) {
          failed("geom[" + ct + "/" + gt + "].space_dim", "geom.getSDim()", e);
        }
        try {
          nv = Integer.valueOf(model.component(ct).geom(gt).getNVertices());
        } catch (Exception e) {
          failed("geom[" + ct + "/" + gt + "].n_vertices", "geom.getNVertices()", e);
        }
        try {
          ne = Integer.valueOf(model.component(ct).geom(gt).getNEdges());
        } catch (Exception e) {
          failed("geom[" + ct + "/" + gt + "].n_edges", "geom.getNEdges()", e);
        }
        try {
          nb = Integer.valueOf(model.component(ct).geom(gt).getNBoundaries());
        } catch (Exception e) {
          failed("geom[" + ct + "/" + gt + "].n_boundaries", "geom.getNBoundaries()", e);
        }
        try {
          nd = Integer.valueOf(model.component(ct).geom(gt).getNDomains());
        } catch (Exception e) {
          failed("geom[" + ct + "/" + gt + "].n_domains", "geom.getNDomains()", e);
        }
        if (geom.length() > 1) geom.append(",");
        geom.append("{\"component\":").append(esc(ct));
        geom.append(",\"tag\":").append(esc(gt));
        geom.append(",\"space_dim\":").append(dim == null ? "null" : dim.toString());
        geom.append(",\"n_vertices\":").append(nv == null ? "null" : nv.toString());
        geom.append(",\"n_edges\":").append(ne == null ? "null" : ne.toString());
        geom.append(",\"n_boundaries\":").append(nb == null ? "null" : nb.toString());
        geom.append(",\"n_domains\":").append(nd == null ? "null" : nd.toString());
        geom.append("}");
      }

      // bounding box from mesh vertex coordinates (dimension-independent)
      String[] mtags = new String[0];
      try {
        mtags = model.component(ct).mesh().tags();
      } catch (Exception e) {
        failed("component[" + ct + "].mesh.tags", "component.mesh().tags()", e);
      }
      for (int mi = 0; mi < mtags.length; mi++) {
        String mt = mtags[mi];
        double[][] pts = null;
        try {
          pts = model.component(ct).mesh(mt).getVertex();
          ok("mesh[" + ct + "/" + mt + "].vertex_coordinates", "mesh.getVertex()");
        } catch (Exception e) {
          failed("mesh[" + ct + "/" + mt + "].vertex_coordinates", "mesh.getVertex()", e);
        }
        if (!firstBox) bbox.append(",");
        firstBox = false;
        bbox.append("{\"component\":").append(esc(ct));
        bbox.append(",\"mesh\":").append(esc(mt));
        bbox.append(",\"n_vertices\":").append(
            pts == null ? "null" : Integer.toString(nVertexColumns(pts)));
        bbox.append(",\"x\":").append(box(pts, 0));
        bbox.append(",\"y\":").append(box(pts, 1));
        bbox.append(",\"z\":").append(box(pts, 2));
        bbox.append("}");

        Integer nel = null;
        Integer nvt = null;
        String nelErr = null;
        try {
          nel = Integer.valueOf(model.component(ct).mesh(mt).getNumElem());
          ok("mesh[" + ct + "/" + mt + "].num_elements", "mesh.getNumElem()");
        } catch (Exception e) {
          nelErr = e.getClass().getName() + ": " + e.getMessage();
          failed("mesh[" + ct + "/" + mt + "].num_elements", "mesh.getNumElem()", e);
        }
        try {
          nvt = Integer.valueOf(model.component(ct).mesh(mt).getNumVertex());
          ok("mesh[" + ct + "/" + mt + "].num_vertices", "mesh.getNumVertex()");
        } catch (Exception e) {
          failed("mesh[" + ct + "/" + mt + "].num_vertices", "mesh.getNumVertex()", e);
        }
        if (!firstMesh) mesh.append(",");
        firstMesh = false;
        mesh.append("{\"component\":").append(esc(ct));
        mesh.append(",\"tag\":").append(esc(mt));
        mesh.append(",\"num_elements\":").append(nel == null ? "null" : nel.toString());
        mesh.append(",\"num_vertices\":").append(nvt == null ? "null" : nvt.toString());
        mesh.append(",\"num_elements_error\":").append(esc(nelErr));
        mesh.append(",\"computed_in_this_run\":false}");
      }
    }
    geom.append("]");
    bbox.append("]");
    mesh.append("]");

    // ---- physics interfaces, features, property names AND values ----------------
    StringBuilder phys = new StringBuilder("[");
    boolean firstPhys = true;
    for (int ci = 0; ci < components.length; ci++) {
      String ct = components[ci];
      String[] ptags = new String[0];
      try {
        ptags = model.component(ct).physics().tags();
      } catch (Exception e) {
        failed("component[" + ct + "].physics.tags", "component.physics().tags()", e);
      }
      for (int pi = 0; pi < ptags.length; pi++) {
        String pt = ptags[pi];
        if (!firstPhys) phys.append(",");
        firstPhys = false;
        phys.append("{\"component\":").append(esc(ct));
        phys.append(",\"tag\":").append(esc(pt));
        String ptype = null;
        try {
          ptype = model.component(ct).physics(pt).getType();
        } catch (Exception e) {
          failed("physics[" + ct + "/" + pt + "].type", "physics.getType()", e);
        }
        phys.append(",\"type\":").append(esc(ptype));
        String[] psel = new String[0];
        boolean pselRead = true;
        int[] pselInt = new int[0];
        try {
          pselInt = model.component(ct).physics(pt).selection().entities();
        } catch (Exception e) {
          pselRead = false;
          failed("physics[" + ct + "/" + pt + "].selection", "physics.selection().entities()", e);
        }
        phys.append(",\"selection\":").append(intArr(pselInt));
        phys.append(",\"selection_readable\":").append(pselRead ? "true" : "false");
        phys.append(",\"features\":[");
        String[] feats = new String[0];
        try {
          feats = model.component(ct).physics(pt).feature().tags();
        } catch (Exception e) {
          failed("physics[" + ct + "/" + pt + "].feature.tags", "physics.feature().tags()", e);
        }
        for (int fi = 0; fi < feats.length; fi++) {
          String ft = feats[fi];
          if (fi > 0) phys.append(",");
          phys.append("{\"tag\":").append(esc(ft));
          String ftype = null;
          try {
            ftype = model.component(ct).physics(pt).feature(ft).getType();
          } catch (Exception e) {
            failed("feature[" + ct + "/" + pt + "/" + ft + "].type", "feature.getType()", e);
          }
          phys.append(",\"type\":").append(esc(ftype));
          String flabel = null;
          try {
            flabel = model.component(ct).physics(pt).feature(ft).label();
          } catch (Exception e) {
            failed("feature[" + ct + "/" + pt + "/" + ft + "].label", "feature.label()", e);
          }
          phys.append(",\"label\":").append(esc(flabel));
          int[] fsel = new int[0];
          boolean fselRead = true;
          try {
            fsel = model.component(ct).physics(pt).feature(ft).selection().entities();
          } catch (Exception e) {
            fselRead = false;
            failed("feature[" + ct + "/" + pt + "/" + ft + "].selection",
                   "feature.selection().entities()", e);
          }
          phys.append(",\"selection\":").append(intArr(fsel));
          phys.append(",\"selection_readable\":").append(fselRead ? "true" : "false");
          // NOTE: the batch-exposed PhysicsFeature has NO getEnum() (measured: cannot find
          // symbol). Enumerations are read back with getString() below.
          String[] props = new String[0];
          try {
            props = model.component(ct).physics(pt).feature(ft).properties();
            ok("feature[" + ct + "/" + pt + "/" + ft + "].properties", "feature.properties()");
          } catch (Exception e) {
            failed("feature[" + ct + "/" + pt + "/" + ft + "].properties", "feature.properties()", e);
          }
          phys.append(",\"properties\":[");
          for (int qi = 0; qi < props.length; qi++) {
            String pn = props[qi];
            if (qi > 0) phys.append(",");
            String pv = null;
            String perr = null;
            try {
              pv = model.component(ct).physics(pt).feature(ft).getString(pn);
            } catch (Exception e) {
              perr = e.getClass().getName() + ": " + e.getMessage();
              failed("feature[" + ct + "/" + pt + "/" + ft + "].property[" + pn + "]",
                     "feature.getString(" + pn + ")", e);
            }
            phys.append("{\"name\":").append(esc(pn));
            phys.append(",\"value\":").append(esc(pv));
            phys.append(",\"value_error\":").append(esc(perr)).append("}");
          }
          phys.append("]}");
        }
        phys.append("]}");
      }

      // NamedSelection nodes are read separately: a physics selection never enumerates them.
      String[] stags = new String[0];
      try {
        stags = model.component(ct).selection().tags();
        ok("component[" + ct + "].selection.tags", "component.selection().tags()");
      } catch (Exception e) {
        failed("component[" + ct + "].selection.tags", "component.selection().tags()", e);
      }
      for (int si = 0; si < stags.length; si++) {
        String st = stags[si];
        if (!firstPhys) phys.append(",");
        firstPhys = false;
        phys.append("{\"component\":").append(esc(ct));
        phys.append(",\"tag\":").append(esc(st));
        phys.append(",\"kind\":\"named_selection\"");
        phys.append(",\"type\":").append(esc(typeOf(model.component(ct).selection(st))));
        int[] entsInt = new int[0];
        boolean sentsRead = true;
        try {
          entsInt = model.component(ct).selection(st).entities();
        } catch (Exception e) {
          sentsRead = false;
          failed("named_selection[" + ct + "/" + st + "].entities",
                 "selection.entities()", e);
        }
        phys.append(",\"selection\":").append(intArr(entsInt));
        phys.append(",\"selection_readable\":").append(sentsRead ? "true" : "false");
        phys.append(",\"features\":[]}");
      }
    }
    phys.append("]");

    // ---- studies, steps, solvers ------------------------------------------------
    String[] studies = new String[0];
    try {
      studies = model.study().tags();
      ok("studies", "model.study().tags()");
    } catch (Exception e) {
      failed("studies", "model.study().tags()", e);
    }
    StringBuilder study = new StringBuilder("[");
    for (int si = 0; si < studies.length; si++) {
      String st = studies[si];
      if (si > 0) study.append(",");
      study.append("{\"tag\":").append(esc(st));
      String stlabel = null;
      try {
        stlabel = model.study(st).label();
      } catch (Exception e) {
        failed("study[" + st + "].label", "study.label()", e);
      }
      study.append(",\"label\":").append(esc(stlabel));
      study.append(",\"steps\":[");
      String[] steps = new String[0];
      try {
        steps = model.study(st).feature().tags();
      } catch (Exception e) {
        failed("study[" + st + "].feature.tags", "study.feature().tags()", e);
      }
      for (int ki = 0; ki < steps.length; ki++) {
        String kt = steps[ki];
        if (ki > 0) study.append(",");
        study.append("{\"tag\":").append(esc(kt));
        String ktype = null;
        try {
          ktype = model.study(st).feature(kt).getType();
        } catch (Exception e) {
          failed("study[" + st + "/" + kt + "].type", "study.feature.getType()", e);
        }
        study.append(",\"type\":").append(esc(ktype));
        String[] kprops = new String[0];
        try {
          kprops = model.study(st).feature(kt).properties();
        } catch (Exception e) {
          failed("study[" + st + "/" + kt + "].properties", "study.feature.properties()", e);
        }
        study.append(",\"properties\":").append(strArr(kprops));
        study.append("}");
      }
      study.append("]}");
    }
    study.append("]");

    String[] solvers = new String[0];
    try {
      solvers = model.sol().tags();
      ok("solvers", "model.sol().tags()");
    } catch (Exception e) {
      failed("solvers", "model.sol().tags()", e);
    }

    String version = null;
    try {
      version = ModelUtil.getComsolVersion();
      ok("comsol_version", "ModelUtil.getComsolVersion()");
    } catch (Exception e) {
      failed("comsol_version", "ModelUtil.getComsolVersion()", e);
    }

    StringBuilder out = new StringBuilder();
    out.append("{\"probe_version\":").append(esc("@@VERSION@@"));
    out.append(",\"source\":{\"input_file\":").append(esc("@@INPUT@@"));
    out.append(",\"source_path\":").append(esc(@@SOURCE@@));
    out.append(",\"source_sha256\":").append(esc(@@SOURCE_SHA@@));
    out.append(",\"staged_path\":").append(esc(@@STAGED@@));
    out.append(",\"staged_sha256\":").append(esc(@@STAGED_SHA@@));
    out.append(",\"lock_present\":@@LOCK@@");
    out.append(",\"read_only_copy\":true}");
    out.append(",\"comsol_version\":").append(esc(version));
    out.append(",\"parameters\":").append(params.toString());
    out.append(",\"components\":").append(strArr(components));
    out.append(",\"geometry\":").append(geom.toString());
    out.append(",\"bounding_box\":").append(bbox.toString());
    out.append(",\"physics\":").append(phys.toString());
    out.append(",\"studies\":").append(study.toString());
    out.append(",\"solvers\":").append(strArr(solvers));
    out.append(",\"mesh\":").append(mesh.toString());
    out.append(",\"readback\":[");
    for (int i = 0; i < READBACK.size(); i++) {
      if (i > 0) out.append(",");
      out.append(READBACK.get(i));
    }
    out.append("],\"notes\":[");
    for (int i = 0; i < NOTES.size(); i++) {
      if (i > 0) out.append(",");
      out.append(esc(NOTES.get(i)));
    }
    out.append("]}");
    System.out.println("@@MARKER@@" + out.toString());
    System.out.println("@@DONEMARKER@@");
    return model;
  }

  public static void main(String[] args) {
    try {
      run();
    } catch (Throwable err) {
      System.out.println("MEMS_PROBE_ERROR=" + err.getClass().getName() + ": " + err.getMessage());
      err.printStackTrace();
      System.exit(1);
    } finally {
      // Release the in-memory model so the batch process does not hold the file open.
      // remove() must never mask the real failure, hence the nested try/catch.
      try {
        ModelUtil.remove("Model");
      } catch (Throwable ignored) {
      }
    }
  }
}
'''


def _java_escape(text: str) -> str:
    """把任意文本转成**全 ASCII** 的 Java 字符串字面量（非 ASCII → ``\\uXXXX``）。

    为什么必须这样：生成源码要按 ASCII 写入（否则 javac 在中文代码页下解析失败，
    实测 ``UnicodeEncodeError`` 会炸在很深的地方）；而运行时读回的中文描述/标签必须原样保留，
    因此用 Java 的 unicode 转义（转义序列本身全是 ASCII 字符），由 JVM 在运行时复原。
    """
    out: list[str] = ['"']
    for ch in text:
        code = ord(ch)
        if ch == '"':
            out.append('\\"')
        elif ch == "\\":
            out.append("\\\\")
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif code < 32 or code > 126:
            out.append(f"\\u{code:04x}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def _safe_java_filename(name: str) -> str:
    """校验交给 Java 的相对文件名：必须是纯 ASCII 的纯文件名。

    失败模式：含目录分量、非 ASCII 字符、引号或反斜杠 → :class:`ModelIOError`。
    （模型原件可以待在中文路径下；我们只把**副本**以 ASCII 文件名放进 run 目录。）
    """
    if not name or name != Path(name).name:
        raise ModelIOError(f"交给 Java 的输入文件名必须是纯文件名（不含目录），收到 {name!r}")
    if not name.isascii():
        raise ModelIOError(
            f"交给 Java 的输入文件名必须全 ASCII，收到 {name!r}；"
            "中文路径的模型请由 Python 侧摆好 ASCII 副本（暂存区已保证这一点）。"
        )
    if any(ch in name for ch in '"\\\''):
        raise ModelIOError(f"输入文件名不能含引号或反斜杠：{name!r}")
    return name


def _assert_ascii_source(source: str, label: str) -> str:
    """渲染后置校验：生成源码必须全 ASCII，并保证占位符全部替换。

    失败模式：存在未替换占位符或非 ASCII 字符 → ``ValueError``（绝不写出坏源码）。
    """
    leftover = sorted(set(re.findall(r"@@[A-Z_]+@@", source)))
    if leftover:
        raise ValueError(f"{label} 存在未替换占位符：{leftover}")
    for lineno, line in enumerate(source.splitlines(), start=1):
        if not line.isascii():
            bad = "".join(ch for ch in line if not ch.isascii())
            raise ValueError(
                f"{label} 第 {lineno} 行含非 ASCII 字符 {bad!r}；"
                "生成源码必须全 ASCII（注释也不例外）。"
            )
    return source


def render_probe_source(
    *,
    java_class: str,
    input_name: str,
    source_path: str,
    source_sha256: str,
    staged_path: str,
    staged_sha256: str,
    lock_present: bool,
) -> str:
    """渲染探针 Java 源码（全 ASCII）。

    失败模式：``input_name`` 非法 → :class:`ModelIOError`；
    占位符未替换干净或结果含非 ASCII → ``ValueError``。
    """
    _safe_java_filename(input_name)
    subs = {
        "@@SOURCE_SHA@@": _java_escape(source_sha256),
        "@@STAGED_SHA@@": _java_escape(staged_sha256),
        "@@VERSION@@": MODELIO_VERSION,
        "@@SOURCE@@": _java_escape(source_path),
        "@@STAGED@@": _java_escape(staged_path),
        "@@INPUT@@": input_name,
        "@@CLASS@@": java_class,
        "@@LOCK@@": "true" if lock_present else "false",
        "@@MARKER@@": PROBE_MARKER,
        "@@DONEMARKER@@": DONE_MARKER,
    }
    return _assert_ascii_source(_substitute(_PROBE_TEMPLATE, subs), "探针 Java 模板")


def _substitute(template: str, subs: Mapping[str, str]) -> str:
    """按 token 长度降序替换（避免 ``@@INPUT@@`` 吃掉 ``@@INPUT_LIT@@`` 的前缀）。"""
    source = template
    for token in sorted(subs, key=len, reverse=True):
        source = source.replace(token, subs[token])
    return source


# ======================================================================================
# Java 改参模板
# ======================================================================================

_SET_TEMPLATE = r'''import com.comsol.model.*;
import com.comsol.model.util.*;

/**
 * Auto-generated parameter WRITER (memsharness.modelio @@VERSION@@).
 * ASCII-only on purpose: javac reads sources in the platform code page.
 *
 * Loads @@INPUT@@ (a fresh staged COPY), rejects unknown parameter names outright,
 * sets the requested values, READS THEM BACK (a swallowed set() is only visible in the
 * read-back), rebuilds geometry+mesh (so a geometry-class change is visible), saves
 * @@OUTPUT_LIT@@ in the working directory and prints one machine-readable diff line.
 * The source model is never touched: Python only ever hands over a copy.
 */
public class @@CLASS@@ {

  private static final String[] NAMES = new String[]{@@NAMES@@};
  private static final String[] WANTED = new String[]{@@WANTED@@};

  private static String esc(String s) {
    if (s == null) return "null";
    StringBuilder sb = new StringBuilder("\"");
    for (int i = 0; i < s.length(); i++) {
      char c = s.charAt(i);
      if (c == '"') sb.append("\\\"");
      else if (c == '\\') sb.append("\\\\");
      else if (c == '\n') sb.append("\\n");
      else if (c == '\r') sb.append("\\r");
      else if (c == '\t') sb.append("\\t");
      else if (c < 32 || c > 126) sb.append(String.format("\\u%04x", (int) c));
      else sb.append(c);
    }
    return sb.append('"').toString();
  }

  /** JSON number or null for a read-back value (NaN/Infinity are NOT values: emit null). */
  private static String num(Double x) {
    if (x == null || x.isNaN() || x.isInfinite()) return "null";
    return String.format(java.util.Locale.ROOT, "%.12g", x);
  }

  // getVertex() is [ndim][nvertices] (column-major) - verified live against COMSOL 6.4:
  // reading it as [nvertices][ndim] yields a bogus box (measured: [0,0] x [0, 1.25e-05]).
  private static String boxJson(double[][] pts, int axis) {
    if (pts == null || pts.length <= axis) return "null";
    double[] row = pts[axis];
    if (row == null || row.length == 0) return "null";
    double lo = row[0];
    double hi = row[0];
    for (int i = 1; i < row.length; i++) {
      if (row[i] < lo) lo = row[i];
      if (row[i] > hi) hi = row[i];
    }
    return "[" + String.format(java.util.Locale.ROOT, "%.10g", lo)
        + "," + String.format(java.util.Locale.ROOT, "%.10g", hi) + "]";
  }

  public static Model run() throws java.io.IOException {
    Model model = ModelUtil.loadCopy("Model", @@INPUT_LIT@@);

    java.util.List<String> known = new java.util.ArrayList<String>();
    try {
      String[] names = model.param().varnames();
      for (int i = 0; i < names.length; i++) known.add(names[i]);
    } catch (Exception e) {
      System.out.println("MEMS_ERROR_UNREADABLE=parameters:" + e);
      throw new RuntimeException("cannot enumerate the parameter table: " + e);
    }

    // REJECT unknown names outright: there is deliberately no "create if missing" path,
    // because inventing a parameter would fabricate model internals (red line 3).
    java.util.List<String> missing = new java.util.ArrayList<String>();
    for (int i = 0; i < NAMES.length; i++) {
      if (!known.contains(NAMES[i])) missing.add(NAMES[i]);
    }
    if (!missing.isEmpty()) {
      StringBuilder error = new StringBuilder();
      error.append("{\"ok\":false,\"error\":\"unknown_parameter\",\"unknown\":[");
      for (int i = 0; i < missing.size(); i++) {
        if (i > 0) error.append(",");
        error.append(esc(missing.get(i)));
      }
      error.append("],\"legal_parameter_names\":[");
      for (int i = 0; i < known.size(); i++) {
        if (i > 0) error.append(",");
        error.append(esc(known.get(i)));
      }
      error.append("]}");
      System.out.println("@@MARKER@@" + error.toString());
      System.out.println("MEMS_SET_REJECTED=1");
      return model;
    }

    StringBuilder out = new StringBuilder();
    out.append("{\"ok\":true,\"input_file\":").append(esc(@@INPUT_LIT@@));
    out.append(",\"output_file\":").append(esc(@@OUTPUT_LIT@@));
    // Each parameter gets TWO INDEPENDENT read-backs: the before state and the after state are
    // collected and serialized separately, never through a shared variable.
    // Historical defect (measured, audit case 01: changing v0 gave value_before=2.0 and
    // value_after=2.0 while the pre-change value was 1.0): beforeValue's evaluate() used to sit
    // AFTER set(), so the "before" number was really a re-evaluation of the new state - the
    // provenance record lied. The order is now:
    //   read expression before -> read value before -> set -> read expression after -> read value after
    // The two groups use different variables, so they cannot stand in for each other any more.
    out.append(",\"readbacks\":[");
    for (int i = 0; i < NAMES.length; i++) {
      String name = NAMES[i];
      if (i > 0) out.append(",");

      // ---- BEFORE read-back (read-only: the model is not touched here) ----
      String beforeExpr = null;
      String beforeExprError = null;
      try {
        beforeExpr = model.param().get(name);
      } catch (Exception e) {
        beforeExprError = e.getClass().getName() + ": " + e.getMessage();
        System.out.println("MEMS_ERROR_UNREADABLE=parameter_expression_before:" + name + ":" + e);
      }
      Double beforeValue = null;
      String beforeValueError = null;
      try {
        beforeValue = Double.valueOf(model.param().evaluate(name));
      } catch (Exception e) {
        beforeValueError = e.getClass().getName() + ": " + e.getMessage();
        System.out.println("MEMS_ERROR_UNREADABLE=parameter_value_before:" + name + ":" + e);
      }

      // ---- WRITE ----
      String applyError = null;
      try {
        model.param().set(name, WANTED[i]);
      } catch (Exception e) {
        applyError = e.getClass().getName() + ": " + e.getMessage();
      }

      // ---- AFTER read-back ----
      String afterExpr = null;
      String afterExprError = null;
      try {
        afterExpr = model.param().get(name);
      } catch (Exception e) {
        afterExprError = e.getClass().getName() + ": " + e.getMessage();
        System.out.println("MEMS_ERROR_UNREADABLE=parameter_expression_after:" + name + ":" + e);
      }
      Double afterValue = null;
      String afterValueError = null;
      try {
        afterValue = Double.valueOf(model.param().evaluate(name));
      } catch (Exception e) {
        afterValueError = e.getClass().getName() + ": " + e.getMessage();
        System.out.println("MEMS_ERROR_UNREADABLE=parameter_value_after:" + name + ":" + e);
      }

      out.append("{\"name\":").append(esc(name));
      out.append(",\"requested\":").append(esc(WANTED[i]));
      out.append(",\"apply_error\":").append(applyError == null ? "null" : esc(applyError));
      out.append(",\"before_readback\":{\"read\":true");
      out.append(",\"expression\":").append(esc(beforeExpr));
      out.append(",\"expression_error\":").append(esc(beforeExprError));
      out.append(",\"value\":").append(num(beforeValue));
      out.append(",\"value_error\":").append(esc(beforeValueError)).append("}");
      out.append(",\"after_readback\":{\"read\":").append(afterExpr == null ? "false" : "true");
      out.append(",\"expression\":").append(esc(afterExpr));
      out.append(",\"expression_error\":").append(esc(afterExprError));
      out.append(",\"value\":").append(num(afterValue));
      out.append(",\"value_error\":").append(esc(afterValueError)).append("}");
      out.append("}");
    }
    out.append("]}");

    // Geometry + mesh rebuild: a parameter that moves the geometry is a geometry-class
    // change, and a silent geometry change can invalidate selections (skills/model-io).
    StringBuilder geom = new StringBuilder();
    String[] components = new String[0];
    try {
      components = model.modelNode().tags();
    } catch (Exception e) {
      System.out.println("MEMS_ERROR_UNREADABLE=components:" + e);
    }
    boolean rebuilt = true;
    String rebuildError = null;
    for (int ci = 0; ci < components.length; ci++) {
      String ct = components[ci];
      try {
        String[] gtags = model.component(ct).geom().tags();
        for (int gi = 0; gi < gtags.length; gi++) model.component(ct).geom(gtags[gi]).run();
        String[] mtags = model.component(ct).mesh().tags();
        for (int mi = 0; mi < mtags.length; mi++) model.component(ct).mesh(mtags[mi]).run();
      } catch (Exception e) {
        rebuilt = false;
        rebuildError = e.getClass().getName() + ": " + e.getMessage();
        System.out.println("MEMS_ERROR_UNREADABLE=rebuild:" + ct + ":" + e);
      }
    }
    geom.append("{\"rebuilt_ok\":").append(rebuilt ? "true" : "false");
    geom.append(",\"rebuild_error\":").append(rebuildError == null ? "null" : esc(rebuildError));
    geom.append(",\"bounding_box\":[");
    boolean firstBox = true;
    for (int ci = 0; ci < components.length; ci++) {
      String ct = components[ci];
      String[] mtags = new String[0];
      try {
        mtags = model.component(ct).mesh().tags();
      } catch (Exception e) {
        System.out.println("MEMS_ERROR_UNREADABLE=mesh_tags:" + ct + ":" + e);
      }
      for (int mi = 0; mi < mtags.length; mi++) {
        double[][] pts = null;
        try {
          pts = model.component(ct).mesh(mtags[mi]).getVertex();
        } catch (Exception e) {
          System.out.println("MEMS_ERROR_UNREADABLE=bbox:" + ct + "/" + mtags[mi] + ":" + e);
          continue;
        }
        if (pts == null || pts.length == 0) continue;
        if (!firstBox) geom.append(",");
        firstBox = false;
        geom.append("{\"component\":").append(esc(ct));
        geom.append(",\"mesh\":").append(esc(mtags[mi]));
        geom.append(",\"n_vertices\":").append(Integer.toString(pts[0].length));
        geom.append(",\"x\":").append(boxJson(pts, 0));
        geom.append(",\"y\":").append(boxJson(pts, 1));
        geom.append(",\"z\":").append(boxJson(pts, 2));
        geom.append("}");
      }
    }
    geom.append("]}");

    StringBuilder nsel = new StringBuilder("[");
    boolean firstSel = true;
    for (int ci = 0; ci < components.length; ci++) {
      String ct = components[ci];
      String[] tags = new String[0];
      try {
        tags = model.component(ct).selection().tags();
      } catch (Exception e) {
        System.out.println("MEMS_ERROR_UNREADABLE=named_selection_tags:" + ct + ":" + e);
        continue;
      }
      for (int si = 0; si < tags.length; si++) {
        if (!firstSel) nsel.append(",");
        firstSel = false;
        int[] ents = new int[0];
        try {
          ents = model.component(ct).selection(tags[si]).entities();
        } catch (Exception e) {
          System.out.println("MEMS_ERROR_UNREADABLE=named_selection_entities:"
              + tags[si] + ":" + e);
        }
        nsel.append("{\"component\":").append(esc(ct));
        nsel.append(",\"tag\":").append(esc(tags[si]));
        nsel.append(",\"entities\":[");
        for (int ei = 0; ei < ents.length; ei++) {
          if (ei > 0) nsel.append(",");
          nsel.append(Integer.toString(ents[ei]));
        }
        nsel.append("]}");
      }
    }
    nsel.append("]");

    model.save(@@OUTPUT_LIT@@);
    System.out.println("@@MARKER@@" + out.toString());
    System.out.println("@@GEOMETRYMARKER@@" + geom.toString());
    System.out.println("@@SELECTIONMARKER@@" + nsel.toString());
    System.out.println("@@SAVEDMARKER@@" + @@OUTPUT_LIT@@);
    System.out.println("@@DONEMARKER@@");
    return model;
  }

  public static void main(String[] args) {
    try {
      run();
    } catch (Throwable err) {
      System.out.println("MEMS_WRITE_ERROR=" + err.getClass().getName() + ": " + err.getMessage());
      err.printStackTrace();
      System.exit(1);
    } finally {
      try {
        ModelUtil.remove("Model");
      } catch (Throwable ignored) {
      }
    }
  }
}
'''


def render_set_source(
    *,
    java_class: str,
    input_name: str,
    output_name: str,
    names: Iterable[str],
    wanted: Iterable[str],
) -> str:
    """渲染改参 Java 源码（全 ASCII）。

    失败模式：``names`` 与 ``wanted`` 长度不一致、参数表达式含换行/回车、
    文件名非法（:class:`ModelIOError`）、占位符残留或结果含非 ASCII → ``ValueError``。
    """
    names = list(names)
    wanted = list(wanted)
    if len(names) != len(wanted):
        raise ValueError("names 与 wanted 长度不一致")
    if not names:
        raise ValueError("names 为空：拒绝生成「什么都不改」的改参任务")
    for value in wanted:
        if "\n" in value or "\r" in value:
            raise ValueError(f"参数表达式不能含换行：{value!r}")
    _safe_java_filename(input_name)
    _safe_java_filename(output_name)
    subs = {
        "@@NAMES@@": ", ".join(_java_escape(n) for n in names),
        "@@WANTED@@": ", ".join(_java_escape(w) for w in wanted),
        "@@INPUT_LIT@@": _java_escape(input_name),
        "@@OUTPUT_LIT@@": _java_escape(output_name),
        "@@INPUT@@": input_name,
        "@@VERSION@@": MODELIO_VERSION,
        "@@CLASS@@": java_class,
        "@@MARKER@@": PROBE_MARKER,
        "@@GEOMETRYMARKER@@": GEOMETRY_MARKER,
        "@@SELECTIONMARKER@@": SELECTIONS_MARKER,
        "@@SAVEDMARKER@@": SET_MARKER,
        "@@DONEMARKER@@": DONE_MARKER,
    }
    return _assert_ascii_source(_substitute(_SET_TEMPLATE, subs), "改参 Java 模板")


# ======================================================================================
# 编译 + 批处理执行（复用 backend 的命令构造、日志落盘与诊断分类）
# ======================================================================================


class _JavaRun:
    """一次 Java 执行的完整事实（普通类，避免 dataclass 的可变默认值歧义）。"""

    def __init__(
        self,
        *,
        run_id: str,
        run_dir: Path,
        ok: bool,
        exit_code: int | None,
        wall_seconds: float,
        stdout: str,
        stderr: str,
        payload: dict[str, Any] | None,
        payload_error: str | None,
        saved_file: str | None,
        diagnosis: dict[str, Any] | None,
        commands: list[dict[str, Any]],
        notes: list[str],
        log_tail: str,
    ) -> None:
        self.run_id = run_id
        self.run_dir = run_dir
        self.ok = ok
        self.exit_code = exit_code
        self.wall_seconds = wall_seconds
        self.stdout = stdout
        self.stderr = stderr
        self.payload = payload
        self.payload_error = payload_error
        self.saved_file = saved_file
        self.diagnosis = diagnosis
        self.commands = commands
        self.notes = notes
        self.log_tail = log_tail


def _new_run_id(prefix: str) -> str:
    """run_id（与 ``queue.new_run_id`` 同格式，便于统一排序与检索）。"""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}-{stamp}-{uuid.uuid4().hex[:8]}"


def _tail(text: str, lines: int = 40) -> str:
    parts = (text or "").splitlines()
    return "\n".join(parts[-lines:])


def _parse_prefixed_json(stdout: str, prefix: str) -> tuple[Any | None, str | None]:
    """解析 ``PREFIX{json}`` / ``PREFIX[json]`` 形式的标记行（只认最后一条）。

    失败模式：无标记 / 标记后不是 JSON → 返回 ``(None, 原因)``，不返回空结构冒充成功。
    """
    line = None
    for raw in (stdout or "").splitlines():
        if prefix in raw:
            line = raw.split(prefix, 1)[1].strip()
    if line is None:
        return None, f"日志中没有 {prefix} 标记"
    match = re.search(r"[\[{].*[\]}]", line)
    if not match:
        return None, f"{prefix} 标记后不是 JSON：{line[:200]!r}"
    try:
        return json.loads(match.group(0)), None
    except json.JSONDecodeError as exc:
        return None, f"{prefix} 后的 JSON 解析失败：{exc}"


def _run_java_model(
    *,
    job_kind: str,
    java_class: str,
    source: str,
    run_dir: Path,
    timeout_seconds: int,
    backend: LocalComsolBackend,
) -> _JavaRun:
    """编译并批处理执行一份生成的 Java 模型源码；命令与日志全部落进 ``run_dir``。

    与 :meth:`LocalComsolBackend.execute` 同一套命令构造与日志命名，
    但没有把结果标记硬编码成「模板结果」——本层的标记是探针/改参两类。

    失败模式（**都不抛异常**，而是如实写进返回值并落到 ``status.json``）：
    编译超时 / 编译未产出 ``.class`` / batch 非零退出 / batch 超时 /
    结果标记缺失或非法 JSON。三种情况都带 ``diagnostic``（diagnostics.classify_failure）。
    """
    run_dir.mkdir(parents=True, exist_ok=True)
    run_id = run_dir.name
    commands: list[dict[str, Any]] = []
    notes: list[str] = []
    java_path = java_model.write_source(run_dir / f"{java_class}.java", source)

    def log(message: str) -> None:
        with (run_dir / "driver.log").open("a", encoding="utf-8") as handle:
            handle.write(f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} {message}\n")

    log(f"[{run_id}] kind={job_kind} class={java_class}")
    try:
        backend.probe()
    except Exception as exc:  # pragma: no cover - 探测本身异常
        log(f"probe() 抛出：{type(exc).__name__}: {exc}")

    compile_out = run_dir / "compile.stdout.log"
    compile_err = run_dir / "compile.stderr.log"
    compile_argv = [str(backend.comsolcompile), java_path.name]
    rc, wall, c_out, c_err, timed = backend._run_command(
        compile_argv,
        cwd=run_dir,
        timeout=min(900, timeout_seconds),
        stdout_path=compile_out,
        stderr_path=compile_err,
        log=log,
    )
    commands.append(
        {
            "stage": "compile",
            "argv": compile_argv,
            "cwd": str(run_dir),
            "returncode": rc,
            "wall_seconds": wall,
            "timed_out": timed,
            "stdout": compile_out.name,
            "stderr": compile_err.name,
        }
    )
    class_path = run_dir / f"{java_class}.class"
    if timed or rc != 0 or not class_path.exists():
        combined = (c_out or "") + "\n" + (c_err or "")
        notes.append(
            f"编译未产出 {class_path.name}（rc={rc}, timed_out={timed}）；"
            f"目录下已有 class：{sorted(p.name for p in run_dir.glob('*.class'))}"
        )
        return _JavaRun(
            run_id=run_id,
            run_dir=run_dir,
            ok=False,
            exit_code=rc,
            wall_seconds=wall,
            stdout=c_out,
            stderr=c_err,
            payload=None,
            payload_error="Java 源码编译失败，未进入批处理阶段",
            saved_file=None,
            diagnosis=diagnostics.classify_failure(
                combined, exit_code=rc, stage="timeout" if timed else "compile"
            ),
            commands=commands,
            notes=notes,
            log_tail=_tail(combined),
        )

    batch_out = run_dir / "batch.stdout.log"
    batch_err = run_dir / "batch.stderr.log"
    batchlog = run_dir / "batchlog.txt"
    batch_argv = [
        str(backend.comsolbatch),
        "-inputfile",
        class_path.name,
        "-outputfile",
        "batch_out.mph",
        "-batchlog",
        batchlog.name,
        "-stoptime",
        str(int(timeout_seconds)),
    ]
    rc, wall, b_out, b_err, timed = backend._run_command(
        batch_argv,
        cwd=run_dir,
        timeout=timeout_seconds,
        stdout_path=batch_out,
        stderr_path=batch_err,
        log=log,
    )
    commands.append(
        {
            "stage": "batch",
            "argv": batch_argv,
            "cwd": str(run_dir),
            "returncode": rc,
            "wall_seconds": wall,
            "timed_out": timed,
            "stdout": batch_out.name,
            "stderr": batch_err.name,
        }
    )
    payload, payload_error = java_model.parse_result_marker(b_out)
    saved_file = None
    for raw in (b_out or "").splitlines():
        if SET_MARKER in raw:
            saved_file = raw.split(SET_MARKER, 1)[1].strip() or None
    combined = "\n".join(part for part in (b_out, b_err) if part)
    ok = rc == 0 and payload is not None and not timed
    diagnosis = None
    if not ok:
        diagnosis = diagnostics.classify_failure(
            combined or f"exit_code={rc}", exit_code=rc, stage="timeout" if timed else "batch"
        )
    if timed:
        notes.append(f"batch 阶段在 {timeout_seconds} s 内未结束，已终止进程。")
    if payload is not None and payload_error:
        notes.append(f"结果标记解析告警：{payload_error}")
    return _JavaRun(
        run_id=run_id,
        run_dir=run_dir,
        ok=ok,
        exit_code=rc,
        wall_seconds=wall,
        stdout=b_out,
        stderr=b_err,
        payload=payload,
        payload_error=payload_error,
        saved_file=saved_file,
        diagnosis=diagnosis,
        commands=commands,
        notes=notes,
        log_tail=_tail(combined),
    )


def _write_run_meta(run: _JavaRun, *, kind: str, extras: Mapping[str, Any]) -> dict[str, Any]:
    """把 run 的机器可读事实写进 run 目录（``commands.json`` / ``status.json``）。

    失败模式：目录不可写 → ``OSError``（不吞掉，否则会丢掉审计记录）。
    """
    payload: dict[str, Any] = {
        "run_id": run.run_id,
        "kind": kind,
        "run_dir": str(run.run_dir),
        "ok": run.ok,
        "exit_code": run.exit_code,
        "wall_seconds": round(float(run.wall_seconds), 3),
        "commands": run.commands,
        "diagnosis": run.diagnosis,
        "payload_error": run.payload_error,
        "saved_file": run.saved_file,
        "notes": run.notes,
    }
    payload.update(extras)
    (run.run_dir / "commands.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    status = {
        "run_id": run.run_id,
        "kind": kind,
        "status": "succeeded" if run.ok else "failed",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "exit_code": run.exit_code,
        "wall_seconds": round(float(run.wall_seconds), 3),
        "diagnostic": (run.diagnosis or {}).get("code"),
        "notes": run.notes,
    }
    for key, value in extras.items():
        if key != "commands":
            status[key] = value
    (run.run_dir / "status.json").write_text(
        json.dumps(status, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    return payload


# ======================================================================================
# 1. 只读探针
# ======================================================================================


def _backend_ready(comsol_home: str | Path | None = None) -> bool:
    """COMSOL 批处理工具是否就绪（只读探测，不启动进程）。"""
    backend = LocalComsolBackend(comsol_home) if comsol_home else LocalComsolBackend()
    return bool(backend.probe()["ready"])


def _backend(comsol_home: str | Path | None = None) -> LocalComsolBackend:
    """构造本机 COMSOL 批处理后端。

    失败模式：``comsolcompile.exe`` 或 ``comsolbatch.exe`` 缺失 → :class:`ModelIOError`，
    并把实际探测结果写进消息（便于区分「装在别处」与「路径写错」）。
    """
    backend = LocalComsolBackend(comsol_home) if comsol_home else LocalComsolBackend()
    probe = backend.probe()
    if not probe["ready"]:
        raise ModelIOError(
            "COMSOL 批处理工具不可用，未发出任何任务："
            f"comsolcompile={probe['comsolcompile']}（存在={probe['comsolcompile_exists']}），"
            f"comsolbatch={probe['comsolbatch']}（存在={probe['comsolbatch_exists']}）。"
        )
    return backend


def _stage_model_into(source: Path, target_dir: Path) -> dict[str, Any]:
    """把模型复制到**指定**目录（:func:`onboard.stage_model` 的目录可控版本）。

    递增语义与 ``stage_model`` 一致：命名冲突时换名 ``x_2.mph`` / ``x_3.mph``——
    上一次的副本可能仍被 mphserver 持有（实测 WinError 32），因此**绝不覆盖历史副本**。

    失败模式：源文件缺失 → :class:`FileNotFoundError`；目标目录不可写 → ``OSError``。
    """
    if not source.is_file():
        raise FileNotFoundError(f"模型文件不存在：{source}")
    target_dir.mkdir(parents=True, exist_ok=True)
    staged = target_dir / source.name
    counter = 1
    while staged.exists():
        try:
            staged.unlink()
            break
        except OSError:
            counter += 1
            staged = target_dir / f"{source.stem}_{counter}{source.suffix}"
    shutil.copy2(source, staged)
    return {
        "source": str(source),
        "source_sha256": sha256_of(source),
        "staged": str(staged),
        "staged_sha256": sha256_of(staged),
        "copy_index": counter,
        "source_lock_present": source.with_suffix(source.suffix + ".lock").exists(),
        "staged_at": datetime.now().isoformat(timespec="seconds"),
        "note": "原文件只读引用；所有改动只作用于本副本；副本按次递增保留作为操作历史",
    }


def _same_hash(path: Path, expected: Any) -> bool | None:
    """核对原件哈希是否仍等于操作前记录值（``None`` = 无法核对，不是「没变」）。"""
    if not isinstance(expected, str) or not expected:
        return None
    try:
        return sha256_file(path) == expected
    except OSError:
        return None


def _validate_mph(mph_path: str | Path) -> Path:
    """校验模型路径。

    失败模式：不存在 → :class:`FileNotFoundError`；不是文件或扩展名不是 ``.mph`` →
    :class:`ModelIOError`（不猜测其它格式，也不尝试按内容嗅探）。
    """
    source = Path(mph_path)
    if not source.exists():
        raise FileNotFoundError(f"模型文件不存在：{source}")
    if not source.is_file():
        raise ModelIOError(f"不是文件：{source}")
    if source.suffix.lower() != ".mph":
        raise ModelIOError(f"只接受 .mph 模型文件，收到 {source.name!r}（不猜测其它格式）")
    return source


def probe_model(mph_path: str | Path, *, work_root: Path | str | None = None) -> dict[str, Any]:
    """**只读**读取任意 ``.mph``：参数表、物理场、选择集、研究/求解器、网格统计、COMSOL 版本。

    流程：校验路径 → 检测 ``.mph.lock`` → 复制到暂存区（**绝不改动原件**，记录源路径与 SHA256）
    → 生成全 ASCII 的 Java 探针类（``ModelUtil.load`` 载入 ASCII 副本）→ 走既有
    ``comsolcompile`` + ``comsolbatch`` 流水线 → 解析 stdout 上的单行 JSON 标记。

    返回（键名稳定，供 :func:`cross_check` / :func:`effect_audit` 复用）::

        {
          "ok": bool, "run_id": str, "run_dir": str,
          "source": {"path","sha256","staged_path","staged_sha256","lock_present",
                     "original_untouched"},
          "comsol_version": str|None,
          "parameters": [{"name","expression","description","value","value_error"}],
          "components": [...],
          "geometry": [{"component","tag","space_dim","n_vertices","n_edges",
                        "n_boundaries","n_domains"}],
          "bounding_box": [{"component","mesh","n_vertices","x","y","z"}],
          "physics": [{"component","tag","type","selection","features":[{"tag","type",
                        "label","selection","properties":[{"name","value","value_error"}]}]},
                      {"kind":"named_selection", ...}],
          "studies": [{"tag","label","steps":[{"tag","type","properties"}]}],
          "solvers": [...], "mesh": [{"component","tag","num_elements","num_vertices",...}],
          "readback": [{"level":"read"|"unreadable","item","source","reason"}],
          "schema_source": {"available","path","sha256","features_parsed",...},
          "enum_validation": {"available","checked_count","enum_checked","illegal",
                              "variant_dependent","unresolved",...},
          "diagnostic": {...}|None, "log_tail": str, "notes": [...]
        }

    ``schema_source`` 是**本地权威 schema**（COMSOL 自带的 API 补全数据
    ``data/completion/physics.xml``）的可用性与路径/哈希：它是离线可查的"真实属性名 +
    合法枚举值"来源，报告里应标注。``enum_validation`` 用它校验运行时读回的枚举属性
    （如 ``BoundaryLoad.forceType``），非法取值与"只在部分变体合法"的取值都会列出。

    失败模式：

    - 路径不存在 / 不是 ``.mph`` / 不是文件 → :class:`FileNotFoundError` / :class:`ModelIOError`
      （**没有 run_id**：任务根本没发出）；
    - COMSOL 可执行文件缺失 → :class:`ModelIOError`；
    - 编译失败、批处理非零退出、超时 → ``ok=False`` + ``run_id`` + ``diagnostic`` + ``log_tail``，
      日志在 ``run_dir``（``compile.*.log`` / ``batch.*.log`` / ``batchlog.txt``），
      绝不返回半个结果冒充成功；
    - 标记行缺失或非合法 JSON → 字段为 ``None``、``payload_error`` 写明原因、``ok=False``；
    - 单项读不到（属性不可回读、网格统计为 NaN/NULL 等）→ **不抛错**，进 ``readback``
      并标 ``"level":"unreadable"``，附 ``source``（哪个 API）与 ``reason``；
      绝不根据文件名或惯例推断模型内部设置（红线 3）；
    - 补全数据 XML 缺失/损坏 → ``schema_source.available=False`` + ``probes``（逐条探测记录），
      ``enum_validation.available=False`` 且 ``checked_count=0``：**明确"未校验"**，
      不静默当成"没有枚举限制"。
    """
    source = _validate_mph(mph_path)
    root = Path(work_root) if work_root is not None else default_work_root()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if work_root is None:
        stage = stage_model(source, f"{source.stem}-probe-{stamp}")
    else:
        stage = _stage_model_into(source, root / "models" / f"{source.stem}-probe-{stamp}")
    staged = Path(stage["staged"])

    backend = _backend()
    run_id = _new_run_id("probe")
    run_dir = root / "runs" / run_id
    input_name = "input.mph"
    _copy_for_java(staged, run_dir / input_name)
    java_class = "model_probe"
    src = render_probe_source(
        java_class=java_class,
        input_name=input_name,
        source_path=str(source),
        source_sha256=str(stage.get("source_sha256")),
        staged_path=str(staged),
        staged_sha256=str(stage.get("staged_sha256")),
        lock_present=bool(stage.get("source_lock_present")),
    )
    run = _run_java_model(
        job_kind=_JOB_PROBE,
        java_class=java_class,
        source=src,
        run_dir=run_dir,
        timeout_seconds=900,
        backend=backend,
    )
    # 输入副本刻意留在 run 目录里：这样 run 目录是自洽的复现单元
    # （源码 + 输入模型 + 命令 + 日志 + 结果），不会被后续清理掉。

    _write_run_meta(
        run,
        kind=_JOB_PROBE,
        extras={
            "source_model": str(source),
            "source_sha256": stage.get("source_sha256"),
            "staged_model": str(staged),
            "staged_sha256": stage.get("staged_sha256"),
            "input_file": input_name,
        },
    )
    (run_dir / "payload.json").write_text(
        json.dumps(run.payload or {}, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    facts = run.payload
    result: dict[str, Any] = {
        "ok": bool(run.ok and facts is not None),
        "run_id": run_id,
        "run_dir": str(run_dir),
        "probe_version": MODELIO_VERSION,
        "source": {
            "path": str(source),
            "sha256": stage.get("source_sha256"),
            "staged_path": str(staged),
            "staged_sha256": stage.get("staged_sha256"),
            "lock_present": bool(stage.get("source_lock_present")),
            "original_untouched": _same_hash(source, stage.get("source_sha256")),
        },
        "payload_error": run.payload_error,
        "diagnostic": run.diagnosis,
        "exit_code": run.exit_code,
        "wall_seconds": round(float(run.wall_seconds), 3),
        "commands": run.commands,
        "log_tail": run.log_tail,
        "notes": run.notes,
    }
    if facts is None:
        result.update(
            {
                "comsol_version": None,
                "parameters": None,
                "components": None,
                "geometry": None,
                "bounding_box": None,
                "physics": None,
                "studies": None,
                "solvers": None,
                "mesh": None,
                "readback": [
                    {
                        "level": "unreadable",
                        "item": "probe_payload",
                        "source": f"stdout {PROBE_MARKER}",
                        "reason": run.payload_error
                        or "未取到探针 JSON（见 log_tail 与 run_dir 内日志）",
                    }
                ],
            }
        )
        return result

    for key in (
        "comsol_version",
        "parameters",
        "components",
        "geometry",
        "bounding_box",
        "physics",
        "studies",
        "solvers",
        "mesh",
        "readback",
    ):
        result[key] = facts.get(key)
    result["notes"] = list(run.notes) + list(facts.get("notes") or [])
    # 本地权威 schema（COMSOL 自带补全数据）是否可用：写进结果便于报告标注来源，
    # 并用它校验运行时读回的枚举属性（如 forceType），非法值必须显式报出来。
    result["schema_source"] = schema_source()
    result["enum_validation"] = build_enum_validation(result.get("physics"))
    if not result["schema_source"]["available"]:
        result["notes"].append(
            "本地权威 schema（COMSOL 补全数据 physics.xml）不可用：枚举合法性未校验；"
            f"原因：{result['schema_source']['error']}；探测记录见 schema_source.probes。"
        )
    return result


def _copy_for_java(staged: Path, target: Path) -> Path:
    """把副本以**纯 ASCII 文件名**放进 run 目录（Java 侧只用相对文件名）。

    失败模式：目标不可写 → ``OSError``。
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(staged, target)
    return target


# ======================================================================================
# 2. 写参数（新副本 + 参数 diff）
# ======================================================================================


def set_parameters(
    mph_path: str | Path,
    values: Mapping[str, str],
    *,
    work_root: Path | str | None = None,
    timeout_seconds: int = 900,
    baseline_geometry: bool = True,
) -> dict[str, Any]:
    """把一个 ``.mph`` 的**副本**改参后另存为新 ``.mph``，返回新路径与参数 diff。

    ``values`` 是「参数名 → 表达式字符串」（如 ``{"L": "0.0045[m]"}``）；表达式原样写入，
    不做单位换算、不做数值解析（写进去的必须是 COMSOL 读得懂的表达式）。

    ``baseline_geometry=True``（默认）时额外跑两次探针：源模型（基线）与新副本（写后），
    用**同一读取通路、同一口径**比较包围盒，从而判定这个改动是不是几何类改动。
    关掉可以省两次批处理（各约十余秒），但 ``geometry_changing`` 会变成 ``None``
    （含义是「无法判定」，**不是「几何没变」**）。

    返回::

        {
          "ok": bool, "rejected": bool, "run_id": str, "run_dir": str,
          "source_path","source_sha256","source_original_untouched",
          "staged_path","staged_sha256","output_path","output_sha256",
          "diff": [{"name","requested","expression_before","expression_after",
                    "value_before","value_after","applied","apply_error"}],
          "unknown_parameters": [...],       # 非空 ⇒ 整体拒绝
          "legal_parameter_names": [...],    # 被拒时回列的合法参数名
          "baseline_bounding_box","after_bounding_box",   # 两次真实探针的读数
          "geometry_relative_shift": float|None,
          "geometry_changing": bool|None, "required_reverification": bool|None,
          "geometry_after_set": {...}|None,  # 改参任务自报的重建结果（旁证）
          "named_selections_after": [...]|None,
          "diagnostic","payload_error","exit_code","log_tail","commands","notes"
        }

    失败模式：

    - 路径/扩展名不合法 → :class:`FileNotFoundError` / :class:`ModelIOError`（无 run_id）；
    - ``values`` 为空 → :class:`ValueError`；
    - 参数名命中保留名黑名单（``h``/``E``/``nu``/``rho``/``T``/``k``）→ **直接拒绝**
      （技能 model-io 实测：这些名字与 COMSOL 内建变量/材料属性别名冲突，编译期报错，
      不允许试错）；抛 :class:`ModelIOError`；
    - 参数名不在模型参数表里 → Java 侧**整体拒绝**且不创建新参数（凭空造参数等于伪造
      模型内部），返回 ``rejected=True`` + ``unknown_parameters`` + ``legal_parameter_names``；
    - 表达式含换行 → :class:`ValueError`（防止破坏 Java 字面量）；
    - COMSOL 不可用 / 编译失败 / 批处理失败 / 超时 → ``ok=False`` + ``diagnostic`` + 日志；
    - 设值被静默吞掉（``set`` 不报错但回读不变）→ 该条 ``applied=False``，**以回读值为事实**；
    - 输出文件未生成 → ``output_path=None``（不假装已保存）；
    - 几何包围盒读不到 → ``geometry_changing=None``（「无法判定」，不是「没有变化」）。
    """
    source = _validate_mph(mph_path)
    if not values:
        raise ValueError("values 为空：没有任何参数要改（拒绝产生无意义的副本）")
    requested = {str(k): str(v) for k, v in values.items()}
    bad_expr = sorted(k for k, v in requested.items() if "\n" in v or "\r" in v)
    if bad_expr:
        raise ValueError(f"参数表达式不能含换行：{bad_expr}")
    reserved = sorted(set(requested) & RESERVED_PARAM_NAMES)
    if reserved:
        raise ModelIOError(
            f"参数名命中保留名黑名单 {reserved}：这些名字与 COMSOL 内建变量/材料属性别名冲突"
            "（h = 网格尺寸内建变量；E/nu/rho = 材料属性自身别名；T/k = 温度与热导率常规内建名）。"
            "处置方式是内部名加后缀（h_beam / E_young / nu_pois / rho_beam），**不得试错写入**。"
        )
    # 便宜的校验全部前置：保留名/空值/换行都在**复制之前**判掉，
    # 这样被拒绝的请求不会在暂存区留下任何副本（拒绝即无副作用）。
    if not _backend_ready():
        raise ModelIOError(
            "COMSOL 批处理工具不可用（comsolcompile/comsolbatch 缺失），未发出任何任务、未产生副本。"
        )

    root = Path(work_root) if work_root is not None else default_work_root()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if work_root is None:
        stage = stage_model(source, f"{source.stem}-set-{stamp}")
    else:
        stage = _stage_model_into(source, root / "models" / f"{source.stem}-set-{stamp}")
    staged = Path(stage["staged"])

    baseline_bbox: dict[str, Any] | None = None
    baseline_bbox_error: str | None = None
    baseline_probe_run: str | None = None
    if baseline_geometry:
        baseline_bbox, baseline_bbox_error, baseline_probe_run = _probe_bbox(
            source, work_root=root
        )

    backend = _backend()
    run_id = _new_run_id("setparam")
    run_dir = root / "runs" / run_id
    input_name = "input.mph"
    output_name = f"{_ascii_stem(source.stem)}_modified.mph"
    _copy_for_java(staged, run_dir / input_name)
    java_class = "model_set_parameters"
    names = sorted(requested)
    src = render_set_source(
        java_class=java_class,
        input_name=input_name,
        output_name=output_name,
        names=names,
        wanted=[requested[name] for name in names],
    )
    run = _run_java_model(
        job_kind=_JOB_SET,
        java_class=java_class,
        source=src,
        run_dir=run_dir,
        timeout_seconds=timeout_seconds,
        backend=backend,
    )
    # 同 probe：输入副本留在 run 目录，保证该目录自洽可复现。

    facts = run.payload or {}
    rejected = bool(facts) and facts.get("error") == "unknown_parameter"
    unknown = [str(x) for x in (facts.get("unknown") or [])]
    # diff 由**纯函数**从 Java 的两组独立读回组装（before 一组、after 一组），
    # 结构上不可能再出现 "用 after 顶替 before"。
    diff = build_parameter_diff(facts.get("readbacks") or [])
    geometry, geometry_error = _parse_prefixed_json(run.stdout, GEOMETRY_MARKER)
    selections, selections_error = _parse_prefixed_json(run.stdout, SELECTIONS_MARKER)
    output_path = run_dir / output_name
    saved_ok = bool(run.saved_file) and output_path.is_file()
    # 写后几何的**权威**来源是对新副本跑一次探针（与基线同一条读取通路、同一口径）；
    # 改参任务里的 bbox 只是自报，作为旁证保留在 ``geometry_after_set``。
    after_bbox: dict[str, Any] | None = None
    after_bbox_error: str | None = None
    after_probe_run: str | None = None
    if baseline_geometry and saved_ok:
        after_bbox, after_bbox_error, after_probe_run = _probe_bbox(output_path, work_root=root)
    geom_shift = _geometry_shift(baseline_bbox, after_bbox)

    changed = bool(geom_shift is not None and geom_shift > GEOMETRY_TOL)
    notes = list(run.notes)
    if changed:
        notes.append(
            "几何类参数变更：使用本副本前必须重新核对全部选择集（技能 model-io 第 8 步）；"
            "几何变更需人工批准。"
        )
    if baseline_geometry and geom_shift is None:
        notes.append(
            "几何变化未判定：基线或写后包围盒读不到（见 baseline_bounding_box_error / "
            "after_bounding_box_error），**不得当作「几何没变」**。"
        )
    result: dict[str, Any] = {
        "ok": bool(run.ok and saved_ok and not rejected),
        "rejected": rejected,
        "run_id": run_id,
        "run_dir": str(run_dir),
        "mode": "new_staged_copy",
        "source_path": str(source),
        "source_sha256": stage.get("source_sha256"),
        "source_original_untouched": _same_hash(source, stage.get("source_sha256")),
        "staged_path": str(staged),
        "staged_sha256": stage.get("staged_sha256"),
        "output_path": str(output_path) if saved_ok else None,
        "output_sha256": sha256_file(output_path) if saved_ok else None,
        "diff": diff,
        "unknown_parameters": unknown,
        "legal_parameter_names": [str(x) for x in (facts.get("legal_parameter_names") or [])],
        "rejected_reserved": reserved,
        "requested_expressions": requested,
        "geometry_after_set": geometry,
        "geometry_after_set_error": geometry_error,
        "named_selections_after": selections,
        "named_selections_error": selections_error,
        "baseline_bounding_box": baseline_bbox,
        "baseline_bounding_box_error": baseline_bbox_error,
        "baseline_probe_run_id": baseline_probe_run,
        "after_bounding_box": after_bbox,
        "after_bounding_box_error": after_bbox_error,
        "after_probe_run_id": after_probe_run,
        "geometry_relative_shift": geom_shift,
        "geometry_changing": None if geom_shift is None else bool(changed),
        "required_reverification": None if geom_shift is None else bool(changed),
        "diagnostic": run.diagnosis,
        "payload_error": run.payload_error,
        "exit_code": run.exit_code,
        "wall_seconds": round(float(run.wall_seconds), 3),
        "commands": run.commands,
        "log_tail": run.log_tail,
        "notes": notes,
    }
    _write_run_meta(
        run,
        kind=_JOB_SET,
        extras={
            "source_model": str(source),
            "source_sha256": stage.get("source_sha256"),
            "staged_model": str(staged),
            "output_file": output_name if saved_ok else None,
            "output_sha256": result["output_sha256"],
            "requested": requested,
            "unknown_parameters": unknown,
            "rejected": rejected,
            "geometry_relative_shift": geom_shift,
            "geometry_changing": result["geometry_changing"],
            "baseline_probe_run_id": baseline_probe_run,
            "after_probe_run_id": after_probe_run,
        },
    )
    (run_dir / "diff.json").write_text(
        json.dumps(result["diff"], ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    return result


def _ascii_stem(stem: str) -> str:
    """把源文件名 stem 转成 ASCII 安全的名字（用于 output 文件名）。

    失败模式：stem 里全是非 ASCII 时不抛错，而是退化为 ``model``——
    输出文件名不是证据（哈希与 run 目录才是），因此这里只保证合法，不保证可读性。
    """
    cleaned = "".join(ch if (ch.isascii() and (ch.isalnum() or ch in "-_")) else "_" for ch in stem)
    cleaned = re.sub(r"_{2,}", "_", cleaned).strip("_")
    return cleaned or "model"


def _reading(
    readback: Any, field: str, *, error_field: str | None = None
) -> tuple[Any, str | None]:
    """从一段读回字典里取一个字段，返回 ``(值, 原因)``。

    值取不到时**返回 None 并给出原因**，绝不用另一侧的值顶替。
    失败模式：``readback`` 不是 Mapping / 字段缺失 / 读回自报 ``read=false`` → ``(None, 原因)``。
    """
    if not isinstance(readback, Mapping):
        return None, "读回结构缺失（该侧没有读数）"
    value = readback.get(field)
    if value is not None:
        return value, None
    if error_field:
        err = readback.get(error_field)
        if err:
            return None, str(err)
    if readback.get("read") is False:
        return None, "该侧读回失败（read=false），无读数"
    return None, f"该侧读数缺失（字段 {field!r} 为 null 且未记录原因）"


def build_parameter_diff(readbacks: Iterable[Mapping[str, Any]] | None) -> list[dict[str, Any]]:
    """把"写前读回"和"写后读回"组装成参数 diff（**纯函数**，便于回归测试）。

    ``readbacks`` 每项形如::

        {"name": "v0", "requested": "2[V]",
         "apply_error": None,
         "before_readback": {"read": true, "expression": "1[V]", "expression_error": null,
                             "value": 1.0, "value_error": null},
         "after_readback":  {"read": true, "expression": "2[V]", "expression_error": null,
                             "value": 2.0, "value_error": null}}

    返回的每条 diff::

        {"name", "requested",
         "expression_before", "expression_before_source", "expression_before_reason",
         "expression_after",  "expression_after_source",  "expression_after_reason",
         "value_before",      "value_before_source",      "value_before_reason",
         "value_after",       "value_after_source",       "value_after_reason",
         "applied", "apply_error"}

    **铁律：before 侧只来自 ``before_readback``，after 侧只来自 ``after_readback``。**
    一侧读不到就写 ``None`` + 原因，**不得用另一侧顶替、也不得静默省略**——
    这个字段是溯源证据（红线 1：没有证据不出数字；历史 append-only 才能回溯）。

    ``applied`` 的判据是"写后读回表达式 == 请求表达式"（**只依赖 after 侧**）；
    当某侧表达式读不到时为 ``None``（未判定），不是 ``False``。

    失败模式：``readbacks`` 为 None/空 → 返回空列表（调用方会发现 diff 为空，而不是拿到假条目）；
    非 Mapping 的条目 → 跳过（不猜它的内容）。
    """
    diff: list[dict[str, Any]] = []
    for item in readbacks or []:
        if not isinstance(item, Mapping):
            continue
        name = item.get("name")
        if name is None:
            continue
        before = item.get("before_readback")
        after = item.get("after_readback")
        expr_before, expr_before_reason = _reading(
            before, "expression", error_field="expression_error"
        )
        value_before, value_before_reason = _reading(
            before, "value", error_field="value_error"
        )
        expr_after, expr_after_reason = _reading(
            after, "expression", error_field="expression_error"
        )
        value_after, value_after_reason = _reading(after, "value", error_field="value_error")
        requested = item.get("requested")
        applied: bool | None
        if expr_after is None:
            applied = None
        else:
            applied = _normalize_expr(requested) == _normalize_expr(expr_after)
        entry: dict[str, Any] = {
            "name": str(name),
            "requested": requested,
            "expression_before": expr_before,
            "expression_before_source": "before_readback",
            "expression_before_reason": expr_before_reason,
            "expression_after": expr_after,
            "expression_after_source": "after_readback",
            "expression_after_reason": expr_after_reason,
            "value_before": value_before,
            "value_before_source": "before_readback",
            "value_before_reason": value_before_reason,
            "value_after": value_after,
            "value_after_source": "after_readback",
            "value_after_reason": value_after_reason,
            "applied": applied,
            "apply_error": item.get("apply_error"),
        }
        if value_before is None and value_after is not None:
            # 显式写清"这不是 after 顶替"：审计时最容易被误读的一处。
            entry["value_before_note"] = (
                "写前数值读不到，因此为 None；**没有**用写后值顶替（见 value_before_reason）"
            )
        diff.append(entry)
    return diff


def _probe_bbox(
    mph_path: Path, *, work_root: Path
) -> tuple[dict[str, Any] | None, str | None, str | None]:
    """用探针读一次模型的几何包围盒（改参前后对比用）。

    失败模式：探针失败 → ``(None, 原因, run_id)``——调用方必须把它当成「无法判定」，
    不得据此断言几何没变。
    """
    try:
        probe = probe_model(mph_path, work_root=work_root)
    except (ModelIOError, FileNotFoundError) as exc:
        return None, f"{type(exc).__name__}: {exc}", None
    run_id = probe.get("run_id")
    if not probe.get("ok"):
        code = (probe.get("diagnostic") or {}).get("code")
        return None, f"探针失败：run_id={run_id} diagnostic={code}", run_id
    boxes = probe.get("bounding_box") or []
    axes: dict[str, list[float]] = {}
    for axis in ("x", "y", "z"):
        values = [item.get(axis) for item in boxes if item.get(axis)]
        if values:
            axes[axis] = [min(v[0] for v in values), max(v[1] for v in values)]
    return {"axes": axes, "per_component": boxes, "probe_run_id": run_id}, None, run_id


def _geometry_shift(
    baseline: Mapping[str, Any] | None, after: Mapping[str, Any] | None
) -> float | None:
    """两次包围盒测的最大相对偏移（阈值判据复用 ``onboard.GEOMETRY_TOL``）。

    口径与 ``onboard._bbox_shift`` 一致：逐轴比较 ``|Δmin|`` 与 ``|Δmax|`` 相对**基线跨度**
    （跨度退化为 0 时用 1e-12 兜底），取最大值。任一侧读不到 → ``None``（= 无法判定）。

    失败模式：结构不符合预期（不是 mapping / 缺 ``axes``）→ ``None``，不抛错也不猜。
    """
    if not baseline or not after:
        return None
    base_axes = baseline.get("axes", baseline)
    after_axes = after.get("axes", after)
    if not isinstance(base_axes, Mapping) or not isinstance(after_axes, Mapping):
        return None
    worst: float | None = None
    for axis in ("x", "y", "z"):
        span = base_axes.get(axis)
        now = after_axes.get(axis)
        if not isinstance(span, (list, tuple)) or len(span) < 2:
            continue
        if not isinstance(now, (list, tuple)) or len(now) < 2:
            continue
        lo_a, hi_a = float(span[0]), float(span[1])
        lo_b, hi_b = float(now[0]), float(now[1])
        scale = max(abs(hi_a - lo_a), 1e-12)
        worst = max(worst or 0.0, abs(lo_b - lo_a) / scale, abs(hi_b - hi_a) / scale)
    return worst


# ======================================================================================
# 3. 参数效验分类（阈值全部复用 onboard）
# ======================================================================================


def _default_log_reader(log: Any) -> str:
    """把日志入参统一成文本（``Path`` 读文件、``bytes`` 解码、其它 ``str()``）。"""
    if log is None:
        return ""
    if isinstance(log, Path):
        return log.read_text(encoding="utf-8", errors="replace") if log.is_file() else ""
    if isinstance(log, (bytes, bytearray)):
        try:
            return bytes(log).decode("utf-8")
        except UnicodeDecodeError:
            return bytes(log).decode("gbk", errors="replace")
    return str(log)


def extract_outputs_from_log(log: Any) -> dict[str, float]:
    """从 run 日志里读回 ``MEMS_RESULT_JSON=`` 的标量输出（供 :func:`effect_audit` 用）。

    失败模式：日志为空 / 无标记 / JSON 非法 → 返回**空字典**，并在调用方体现为
    「输出不可用」；绝不补 0 或默认值冒充读数。
    """
    payload, _ = java_model.parse_result_marker(_default_log_reader(log))
    if not payload:
        return {}
    return {
        key: float(value)
        for key, value in payload.items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    }


def _param_expressions(probe: Mapping[str, Any] | None) -> dict[str, str]:
    """从探针字典取「参数名 → 表达式」。"""
    if not probe:
        return {}
    rows = probe.get("parameters")
    if isinstance(rows, Mapping):
        return {str(k): ("" if v is None else str(v)) for k, v in rows.items()}
    out: dict[str, str] = {}
    for row in rows or []:
        if isinstance(row, Mapping) and row.get("name") is not None:
            out[str(row["name"])] = "" if row.get("expression") is None else str(row["expression"])
    return out


def _relative_shift(baseline: Any, changed: Any) -> float | None:
    """相对变化（口径与 ``onboard.relative_shift`` 一致：以基线幅值为尺度）。

    ``None`` 的含义是「无法计算」（缺值或基线为 0），调用方不得当成 0。
    """
    if not isinstance(baseline, (int, float)) or not isinstance(changed, (int, float)):
        return None
    if isinstance(baseline, bool) or isinstance(changed, bool):
        return None
    if float(baseline) == 0.0:
        return None
    return abs(float(changed) - float(baseline)) / max(abs(float(baseline)), 1e-30)


def _classify_effect(
    *, geometry_shift: float | None, max_shift: float | None, solve_ok: bool | None
) -> str:
    """效验分类纯函数（顺序即优先级；阈值来自 ``onboard.GEOMETRY_TOL``/``EFFECT_TOL``）。

    - ``solve_failed``：改参后求解失败 → 没有可信输出，不能谈有效/惰性；
    - ``geometry_changing``：包围盒偏移超 ``GEOMETRY_TOL`` → 必须重核选择集；
    - ``unknown_no_effect_measurement``：没有可用输出 → 无法判定（**不冒充 inert**）；
    - ``effective`` / ``inert``：输出变化是否超 ``EFFECT_TOL``。
    """
    if solve_ok is False:
        return "solve_failed"
    if geometry_shift is not None and geometry_shift > GEOMETRY_TOL:
        return "geometry_changing"
    if max_shift is None:
        return "unknown_no_effect_measurement"
    if max_shift > EFFECT_TOL:
        return "effective"
    return "inert"


def effect_audit(
    baseline_probe: Mapping[str, Any] | None = None,
    changed_probe: Mapping[str, Any] | None = None,
    *,
    baseline_log: Any = None,
    changed_log: Any = None,
    baseline_outputs: Mapping[str, Any] | None = None,
    changed_outputs: Mapping[str, Any] | None = None,
    params: Iterable[str] = (),
    solve_ok: bool | None = None,
    geometry_shift: float | None = None,
    selection_intact: bool | None = None,
) -> dict[str, Any]:
    """对每个改动过的参数给出四分类 + **支撑该分类的数值证据**。

    分类（判据阈值全部复用 :mod:`memsharness.onboard`，不另造一套）：

    - ``geometry_changing``：几何包围盒相对偏移 > ``GEOMETRY_TOL``（必须重核选择集、人工批准）；
    - ``effective``：目标输出相对变化 > ``EFFECT_TOL``（可进寻优空间）；
    - ``inert``：几何不变、有输出读数但变化低于阈值（**只是本次实测结论**，不等于物理上无效）；
    - ``unknown_no_effect_measurement``：没有可用输出 → 无法判定，**不冒充 inert**；
    - ``solve_failed``：改参后求解失败（附 run_id 与诊断码）。

    输入二选一（或同时给）：``baseline_probe``/``changed_probe``（自动 diff 参数表达式），
    或 ``baseline_outputs``/``changed_outputs`` 与 ``params``；日志可给
    ``baseline_log``/``changed_log``（``Path`` 或文本），会自动解析 ``MEMS_RESULT_JSON``。

    返回::

        {"thresholds": {"geometry_tol","effect_tol"},
         "output_deltas": {name: {"baseline","changed","relative_shift"}},
         "params": [{"name","expression_before","expression_after","classification",
                     "evidence": {"parameter_changed","expression_before","expression_after",
                                  "geometry_relative_shift","selection_intact","output_shifts",
                                  "max_output_relative_shift","run_id_baseline","run_id_changed"}}],
         "run_ids": {"baseline","changed"},
         "note": "..."}

    失败模式：两侧输入全缺 → :class:`ValueError`（拒绝产出无证据的分类）；
    输出不可用 → 分类为 ``unknown_no_effect_measurement``；基线为 0 的输出 → 相对变化记
    ``None`` 并写明「相对变化无定义」，不伪造一个数值。
    """
    base_out: dict[str, float] = {
        str(k): float(v)
        for k, v in (baseline_outputs or {}).items()
        if isinstance(v, (int, float)) and not isinstance(v, bool)
    }
    new_out: dict[str, float] = {
        str(k): float(v)
        for k, v in (changed_outputs or {}).items()
        if isinstance(v, (int, float)) and not isinstance(v, bool)
    }
    if baseline_outputs is None and baseline_log is not None:
        base_out.update(extract_outputs_from_log(baseline_log))
    if changed_outputs is None and changed_log is not None:
        new_out.update(extract_outputs_from_log(changed_log))

    changed_params = _param_expressions(changed_probe)
    baseline_params = _param_expressions(baseline_probe)
    if changed_params:
        names = sorted(changed_params)
    elif params:
        names = sorted(str(p) for p in params)
    else:
        names = []
    if (
        not names
        and baseline_probe is None
        and changed_probe is None
        and not base_out
        and not new_out
    ):
        raise ValueError(
            "effect_audit 没有任何可用输入（既无 probe 也无 outputs/log）："
            "无法产出带证据的分类，拒绝凭猜测给结论。"
        )

    run_ids = {
        "baseline": (baseline_probe or {}).get("run_id") if baseline_probe else None,
        "changed": (changed_probe or {}).get("run_id") if changed_probe else None,
    }
    entries: list[dict[str, Any]] = []
    for name in names:
        expr_before = baseline_params.get(name)
        expr_after = changed_params.get(name)
        if expr_before is not None and _normalize_expr(expr_after) == _normalize_expr(expr_before):
            continue
        shifts: dict[str, Any] = {}
        for key, value in sorted(new_out.items()):
            if key not in base_out:
                shifts[key] = {
                    "baseline": None,
                    "changed": value,
                    "relative_shift": None,
                    "reason": "基线无该输出，无法比较（不是「没有变化」）",
                }
                continue
            rel = _relative_shift(base_out[key], value)
            shifts[key] = {
                "baseline": base_out[key],
                "changed": value,
                "relative_shift": rel,
                "reason": None if rel is not None else "基线值为 0，相对变化无定义",
            }
        worst = max(
            (s["relative_shift"] for s in shifts.values() if s["relative_shift"] is not None),
            default=None,
        )
        entries.append(
            {
                "name": name,
                "expression_before": expr_before,
                "expression_after": expr_after,
                "classification": _classify_effect(
                    geometry_shift=geometry_shift, max_shift=worst, solve_ok=solve_ok
                ),
                "evidence": {
                    "parameter_changed": name,
                    "expression_before": expr_before,
                    "expression_after": expr_after,
                    "geometry_relative_shift": geometry_shift,
                    "selection_intact": selection_intact,
                    "output_shifts": shifts,
                    "max_output_relative_shift": worst,
                    "outputs_available": bool(new_out),
                    "solve_ok": solve_ok,
                    "run_id_baseline": run_ids["baseline"],
                    "run_id_changed": run_ids["changed"],
                },
            }
        )

    return {
        "thresholds": {"geometry_tol": GEOMETRY_TOL, "effect_tol": EFFECT_TOL},
        "output_deltas": {
            key: {
                "baseline": base_out.get(key),
                "changed": new_out.get(key),
                "relative_shift": _relative_shift(base_out.get(key), new_out.get(key)),
            }
            for key in sorted(set(base_out) | set(new_out))
        },
        "params": entries,
        "run_ids": run_ids,
        "note": (
            "分类只表示「本次实测到的效验」：inert 是实测未观测到变化，不等于物理上无效；"
            "geometry_changing 必须重新核对选择集并人工批准后才可使用；"
            "unknown_no_effect_measurement 不得当作 inert 使用。"
        ),
    }


# ======================================================================================
# 3.5 COMSOL API 补全数据（本地权威 schema 来源）
# ======================================================================================
#
# ``data/completion/physics.xml``（COMSOL 自带，本机 6.256 MB / 38018 行）是**离线权威
# schema**：它给出每个物理场特征的**真实属性名**、默认值、**合法枚举值**与人类可读标签。
# 本能力的直接动因（排查耗费多轮，必须写死在注释里防复发）：
#
#   2D 结构力学 ``BoundaryLoad`` 的 ``forceType``，在 ``topic="solid_bndl"`` 的 9 个变体里
#   合法值分别是
#     ForceArea|ForceDefArea|TotalForce|Resultant
#     ForceArea|ForceDefArea|TotalForce|FollowerPressure|Resultant
#     ForceArea|ForceDefArea|ForceLength|ForceDefLength|TotalForce|FollowerPressure|Resultant
#     ForceArea|ForceDefArea|TotalForce|FollowerPressure
#     ForceArea|ForceDefArea|TotalForce
#   共同点是 **``Pressure`` 不是任何变体的合法值**（压力载荷的枚举是 FollowerPressure）。
#   写入 ``set("forceType", "Pressure")`` 会抛异常，若被 ``catch`` 吞掉，``forceType`` 就停在
#   默认值 ``ForceArea``；而 ``ForceArea`` 模式下 ``pressure`` 属性**不生效** ⇒ 载荷为零、
#   位移恒为 0（实测 run-20260911T030051Z-08e8921a：6410 单元、26954 自由度、d_tip=0.0）。
#   注意 ``descrs``（人类标签）里确实有 ``Pressure`` 一词——它是**标签**不是**取值**，
#   只看标签就会误判，因此本模块一律以 ``values`` 为准。
#
# XML 结构（属性名极易误读，这里写清）：
#   特征索引：``<ydfewaae descr="Boundary_load" id="bndl" name="BoundaryLoad"
#                    props="radfwtcr ..." topic="solid_bndl"/>``
#     —— ``id`` 是**混淆 id**（如 ``bndl``），``props`` 是**属性混淆 id 列表**（不是属性值）；
#   属性定义：``<radfwtcr default="ForceArea" descr="Load_type"
#                    descrs="Force_per_area|Total_force|Pressure" name="forceType"
#                    type="String" values="ForceArea|TotalForce|FollowerPressure"/>``
#     —— tag 名（``radfwtcr``）是被引用时用的 key；``name`` 才是真实属性名。
#   同名特征有多个变体（不同 topic / 不同几何维数 / 不同物理场），必须能按 topic 过滤。

_COMPLETION_XML_NAME = "physics.xml"
_COMPLETION_XML_RELATIVE = ("data", "completion", _COMPLETION_XML_NAME)
_COMPLETION_ENV_KEY = "MEMS_COMSOL_COMPLETION_XML"

# 解析缓存：{key: (payload, error)}；key 为 规范路径 或 None（表示路径未找到）
_COMPLETION_CACHE: dict[Any, tuple[dict[str, Any] | None, str | None]] = {}


def find_completion_xml(explicit: Any = None) -> tuple[Path | None, list[dict[str, Any]]]:
    """定位 ``data/completion/physics.xml``，返回 ``(路径或 None, 候选探测记录)``。

    探测顺序：显式参数 → 环境变量 ``MEMS_COMSOL_COMPLETION_XML`` → 环境变量
    ``MEMS_COMSOL_HOME`` → :data:`memsharness.onboard.COMSOL_HOME` 的默认安装 →
    ``C:\\Program Files\\COMSOL\\COMSOL*`` 通配。

    失败模式：**任何一步都不抛异常**，找不到就返回 ``(None, 记录)``；
    ``记录`` 里逐条列出试探过的路径与「不存在 / 不是文件」的原因，
    便于「优雅降级 + 说明缺失」，绝不静默当成"没有枚举限制"。
    """
    candidates: list[tuple[str, Path]] = []
    explicit_path: Path | None = None
    if explicit:
        explicit_path = Path(explicit)
        candidates.append(("explicit", explicit_path))
    env_xml = os.environ.get(_COMPLETION_ENV_KEY)
    if env_xml:
        candidates.append((_COMPLETION_ENV_KEY, Path(env_xml)))
    for env_key in ("MEMS_COMSOL_HOME", "COMSOL_HOME"):
        base = os.environ.get(env_key)
        if base:
            candidates.append((env_key, Path(base).joinpath(*_COMPLETION_XML_RELATIVE)))
    candidates.append(("default_install", Path(COMSOL_HOME).joinpath(*_COMPLETION_XML_RELATIVE)))
    for pattern in (r"C:\Program Files\COMSOL\COMSOL*\Multiphysics", r"C:\Program Files\COMSOL\COMSOL*"):
        for base in sorted(glob.glob(pattern)):
            candidates.append(("glob:" + pattern, Path(base).joinpath(*_COMPLETION_XML_RELATIVE)))

    probes: list[dict[str, Any]] = []
    seen: set[str] = set()
    for origin, path in candidates:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        if path.is_file():
            probes.append({"source": origin, "path": key, "exists": True, "reason": None})
            return path, probes
        probes.append(
            {
                "source": origin,
                "path": key,
                "exists": False,
                "reason": "路径不存在" if not path.exists() else "存在但不是文件（目录？）",
            }
        )
        if explicit_path is not None and origin == "explicit":
            # 显式给了路径却不存在：**不许**悄悄退回到默认安装去找另一份 schema——
            # 那会让人误以为"我指定的就是它"，进而把来源标错（红线 1/3）。
            break
    return None, probes


def _parse_completion_xml(path: Path) -> dict[str, Any]:
    """解析补全 XML，返回 ``{"features":…, "props":…, "root_tag":…, "file":…}``。

    失败模式：XML 损坏 → :class:`ModelIOError`；根标签不是 ``COMSOLCompletionData`` →
    同样报错（不把别的 XML 当补全数据用）。
    """
    import xml.etree.ElementTree as ET

    features: dict[str, list[dict[str, Any]]] = {}
    props: dict[str, dict[str, Any]] = {}
    root_tag: str | None = None
    try:
        context = ET.iterparse(str(path), events=("start", "end"))
        for event, elem in context:
            if event == "start":
                if root_tag is None:
                    root_tag = elem.tag
                continue
            name = elem.get("name")
            if name:
                if "props" in elem.attrib:
                    prop_ids = [p for p in (elem.get("props") or "").split() if p]
                    features.setdefault(name, []).append(
                        {
                            "name": name,
                            "tag": elem.tag,
                            "id": elem.get("id"),
                            "topic": elem.get("topic"),
                            "descr": elem.get("descr"),
                            "prop_ids": prop_ids,
                        }
                    )
                else:
                    # ``<tag name="..." type="String"/>``（没有 props）：**属性定义行**，
                    # 只是没有 values → 不是枚举属性。必须收下来，否则"属性存在但不是枚举"
                    # 会退化成"属性不存在"，两者对调用方的含义完全不同（实测踩过）。
                    raw_values = [v for v in (elem.get("values") or "").split("|")]
                    raw_descrs = [d for d in (elem.get("descrs") or "").split("|")]
                    labels = (
                        [d for d in raw_descrs if d != ""]
                        if raw_descrs and len(raw_descrs) == len(raw_values)
                        else []
                    )
                    props[elem.tag] = {
                        "prop_id": elem.tag,
                        "name": name,
                        "type": elem.get("type"),
                        "default": elem.get("default"),
                        "descr": elem.get("descr"),
                        "descrs": elem.get("descrs"),
                        "values": [v for v in raw_values if v != ""],
                        "labels": labels,
                        "labels_aligned": len(raw_descrs) == len(raw_values),
                    }
            if root_tag is not None and elem is not context.root:
                elem.clear()
    except ET.ParseError as exc:
        raise ModelIOError(f"补全 XML 解析失败（文件可能损坏或不是 XML）：{path}：{exc}") from exc
    if root_tag is None or not str(root_tag).endswith("COMSOLCompletionData"):
        raise ModelIOError(
            f"{path} 的根标签是 {root_tag!r}，不是 COMSOLCompletionData："
            "拒绝把它当作 COMSOL 补全数据使用（不猜格式）。"
        )
    return {"file": str(path), "root_tag": root_tag, "features": features, "props": props}


def _completion_data(path: Any = None) -> tuple[dict[str, Any] | None, str | None, list[dict[str, Any]]]:
    """取（带缓存的）补全数据；``(数据|None, 缺失原因|None, 探测记录)``。"""
    resolved, probes = find_completion_xml(path)
    if resolved is None:
        return None, "未找到 COMSOL 补全数据 physics.xml", probes
    key: Any = str(resolved)
    if key not in _COMPLETION_CACHE:
        try:
            _COMPLETION_CACHE[key] = (_parse_completion_xml(resolved), None)
        except ModelIOError as exc:
            _COMPLETION_CACHE[key] = (None, str(exc))
    data, error = _COMPLETION_CACHE[key]
    return data, error, probes


def clear_schema_cache() -> None:
    """清空补全数据的解析缓存（测试与「装了新版本 COMSOL」后刷新用）。"""
    _COMPLETION_CACHE.clear()


def schema_available(explicit: Any = None) -> bool:
    """本地权威 schema 是否可用（**只读**探测，不抛错）。

    失败模式：路径缺失 / 文件损坏 → 返回 ``False``（原因用 :func:`schema_source` 查）。
    """
    data, _error, _probes = _completion_data(explicit)
    return data is not None


def schema_source(explicit: Any = None) -> dict[str, Any]:
    """schema 来源的**可报告**描述：是否可用、路径、文件哈希/大小、解析规模、缺失原因。

    这是给报告标注"schema 来自哪里、能不能用"用的，因此路径与原因都要能直接贴进报告。
    失败模式：不可用时 ``available=False`` + ``error`` + ``probes``（逐条试探记录），
    ``features_parsed`` 为 0——**不静默返回空结果假装成功**。
    """
    resolved, probes = find_completion_xml(explicit)
    data, error, _ = _completion_data(explicit)
    payload: dict[str, Any] = {
        "available": data is not None,
        "path": str(resolved) if resolved else None,
        "expected_relative_path": "/".join(_COMPLETION_XML_RELATIVE),
        "env_override": _COMPLETION_ENV_KEY,
        "error": error,
        "probes": probes,
        "root_tag": (data or {}).get("root_tag"),
        "features_parsed": len((data or {}).get("features") or {}),
        "variants_parsed": sum(len(v) for v in ((data or {}).get("features") or {}).values()),
        "enum_properties_parsed": len((data or {}).get("props") or {}),
        "size_bytes": None,
        "sha256": None,
        "note": (
            "本地权威 schema = COMSOL 自带的 API 补全数据；"
            "它给出真实属性名、默认值、合法枚举值与人类标签。"
        ),
    }
    if resolved is not None and resolved.is_file():
        try:
            payload["size_bytes"] = resolved.stat().st_size
        except OSError:
            payload["size_bytes"] = None
        payload["sha256"] = sha256_file(resolved)
    return payload


def _empty_feature_schema(feature_name: str, topic: Any, reason: str, probes: Any) -> dict[str, Any]:
    """schema 不可用时返回的结构（显式标注 ``schema_available=False`` + 原因）。"""
    return {
        "available": False,
        "ok": False,
        "feature_name": feature_name,
        "topic_filter": topic,
        "reason": reason,
        "probes": list(probes or []),
        "topics": [],
        "variant_count": 0,
        "variants": [],
        "docs": {},
        "enum_union": {},
        "enum_intersection": {},
        "note": "schema 不可用：无法给出属性名/枚举合法性；调用方必须按「未校验」处理，不得当作通过。",
    }


def lookup_feature_schema(
    feature_name: str,
    *,
    topic: Any = None,
    feature_type: Any = None,
    path: Any = None,
) -> dict[str, Any]:
    """查某个物理场特征的**真实属性 schema**（属性名、默认值、合法枚举值、人类标签）。

    ``feature_name`` 是特征类型名（如 ``"BoundaryLoad"``）；``topic`` 可按物理场族过滤
    （如 ``"solid_bndl"``），因为同名特征有多个变体；``feature_type`` 是**别名**参数，
    便于直接把探针读回的 ``getType()`` 结果传进来。

    返回::

        {
          "available": bool, "ok": bool, "feature_name": str, "topic_filter": str|None,
          "topics": [...], "variant_count": int,
          "variants": [{"name","tag","id","topic","descr","prop_ids","properties":[
                {"name","prop_id","type","default","descr","values","labels",
                 "labels_aligned","is_enum"}]}],
          "docs": {prop_name: [{"prop_id","default","type","descr","values","labels",
                                "topics":[...]}]},
          "enum_union": {prop_name: [值...]},        # 所有变体的并集（真正的非法校验口径）
          "enum_intersection": {prop_name: [值...]},  # 所有变体的交集（最保守口径）
          "enum_variant_dependent": {prop_name: [在部分变体才合法的值...]},
          "reason": str|None, "probes": [...]         # 不可用时的探测记录
        }

    **同名属性在不同变体里可能对应不同 prop_id**（实测：``solid_bndl`` 的 ``BoundaryLoad``
    9 个变体里 ``forceType`` 分别指向 ``bdvtsfte`` / ``rrqtqsuq`` / ``aetxyrcp`` /
    ``tdrzsrsu`` / ``ewurvfbe``），因此不能靠"某个 prop_id 的 values"来判合法性，
    必须按**属性名**跨变体取并集；并集里没有就是非法值。

    失败模式：

    - 找不到 XML → ``available=False``、``ok=False``、``reason`` 写明"未找到"、
      ``probes`` 给出逐条探测记录（**不静默返回空 success**）；
    - XML 损坏 → ``available=True``（路径是有的，因为探测到了）、``ok=False`` + ``reason``；
    - 特征名不存在 → ``available=True``、``ok=False``、``reason="…not in completion data"``；
    - ``topic`` 过滤后为空 → ``ok=False`` + ``reason`` 列出可用 topics（不退回"全部变体"，
      因为伪造成"就是它"比报错更危险）。
    """
    name = str(feature_type or feature_name or "").strip()
    if not name:
        raise ValueError("lookup_feature_schema 需要非空的 feature_name（特征类型名）")
    data, error, probes = _completion_data(path)
    if data is None:
        return _empty_feature_schema(name, topic, error or "补全数据不可用", probes)

    variants = list((data.get("features") or {}).get(name) or [])
    if not variants:
        result = _empty_feature_schema(name, topic, f"补全数据里没有特征 {name!r}", probes)
        result["available"] = True
        result["known_feature_examples"] = sorted((data.get("features") or {}).keys())[:0]
        return result

    topics = sorted({str(v.get("topic")) for v in variants if v.get("topic")})
    if topic is not None:
        wanted = str(topic)
        variants = [v for v in variants if str(v.get("topic")) == wanted]
        if not variants:
            result = _empty_feature_schema(
                name, topic, f"特征 {name!r} 存在但没有 topic={wanted!r} 的变体", probes
            )
            result["available"] = True
            result["topics"] = topics
            result["variant_count"] = 0
            return result

    props_by_id = data.get("props") or {}
    docs: dict[str, list[dict[str, Any]]] = {}
    doc_head: dict[str, dict[str, Any]] = {}
    rendered: list[dict[str, Any]] = []
    for variant in variants:
        properties = []
        for prop_id in variant["prop_ids"]:
            prop = props_by_id.get(prop_id)
            if prop is None:
                properties.append(
                    {
                        "name": None,
                        "prop_id": prop_id,
                        "type": None,
                        "default": None,
                        "descr": None,
                        "values": None,
                        "labels": None,
                        "labels_aligned": None,
                        "is_enum": None,
                        "unresolved": (
                            f"prop_id {prop_id!r} 在补全数据里没有定义行（只有被引用）："
                            "本模块不猜它的属性名与枚举"
                        ),
                    }
                )
                continue
            entry = dict(prop)
            entry["is_enum"] = bool(entry.get("values"))
            properties.append(entry)
            docs.setdefault(entry["name"], []).append({**entry, "topic": variant.get("topic")})
            doc_head.setdefault(entry["name"], entry)
        rendered.append({**variant, "properties": properties})

    enum_union: dict[str, list[str]] = {}
    enum_intersection: dict[str, list[str]] = {}
    enum_variant_dependent: dict[str, list[str]] = {}
    for prop_name, entries in docs.items():
        value_sets = [set(e["values"]) for e in entries if e.get("values")]
        if not value_sets:
            continue
        union: list[str] = []
        for entry in entries:
            for value in entry.get("values") or []:
                if value not in union:
                    union.append(value)
        inter = [v for v in union if all(v in s for s in value_sets)]
        enum_union[prop_name] = union
        enum_intersection[prop_name] = inter
        dependent = [v for v in union if v not in inter]
        if dependent:
            enum_variant_dependent[prop_name] = dependent

    return {
        "available": True,
        "ok": True,
        "feature_name": name,
        "topic_filter": None if topic is None else str(topic),
        "topics": topics,
        "variant_count": len(rendered),
        "variants": rendered,
        "docs": docs,
        "enum_union": enum_union,
        "enum_intersection": enum_intersection,
        "enum_variant_dependent": enum_variant_dependent,
        "reason": None,
        "probes": probes,
        "note": (
            "同名属性在不同变体里可能是不同 prop_id；合法性判据用 enum_union（并集），"
            "enum_variant_dependent 里的取值只在部分变体合法（依赖几何维数/物理场族），"
            "写入前应显式确认命中哪个变体。"
        ),
    }


def lookup_enum(
    property_name: str,
    *,
    feature: Any = None,
    feature_type: Any = None,
    topic: Any = None,
    path: Any = None,
) -> dict[str, Any]:
    """查某个属性的**合法枚举值**（及对应人类标签）。

    给了 ``feature``/``feature_type`` 就按该特征（可选 ``topic`` 过滤）取并集；
    没给就在全表里按属性名收集所有定义行。

    返回::

        {"available","ok","property_name","feature","topic_filter","values",
         "labels","descr","default","variant_count","union_values","union_variant_count",
         "intersection_values","variant_dependent_values","definitions":[…],"reason","probes"}

    ``values`` 是**判据口径**：给了 feature 就是该特征所有变体的并集；
    没有 feature 时是"同名属性的全部定义行"的并集——口径不同，报告里要说明。

    失败模式：schema 缺失/损坏 → ``available``/``ok`` 与 ``reason``（附探测记录）；
    属性名不存在 → ``ok=False`` + ``reason``（不返回空 ``values`` 冒充"无枚举限制"）；
    属性存在但不是枚举（``values`` 为空）→ ``ok=True`` 但 ``values=[]`` 且 ``is_enum=False``
    ——**这两种情况必须分开**，否则调用方会把"没查到"当成"随便写"。
    """
    name = str(property_name or "").strip()
    if not name:
        raise ValueError("lookup_enum 需要非空的 property_name")

    if feature or feature_type:
        schema = lookup_feature_schema(
            str(feature or feature_type), topic=topic, path=path
        )
        if not schema.get("ok"):
            return {
                "available": schema.get("available", False),
                "ok": False,
                "property_name": name,
                "feature": str(feature or feature_type),
                "topic_filter": None if topic is None else str(topic),
                "values": None,
                "labels": None,
                "definitions": [],
                "reason": schema.get("reason"),
                "probes": schema.get("probes") or [],
                "note": "特征 schema 不可用：**未做枚举校验**，不得当作通过。",
            }
        docs = (schema.get("docs") or {}).get(name)
        if not docs:
            return {
                "available": True,
                "ok": False,
                "property_name": name,
                "feature": schema["feature_name"],
                "topic_filter": schema.get("topic_filter"),
                "values": None,
                "labels": None,
                "definitions": [],
                "reason": (
                    f"特征 {schema['feature_name']!r} 的属性清单里没有 {name!r}"
                    f"（共 {len(schema.get('docs') or {})} 个属性），不猜它是否存在枚举限制"
                ),
                "probes": schema.get("probes") or [],
            }
        head = docs[0]
        union = list(schema["enum_union"].get(name) or [])
        if not union:
            # 属性存在但不是枚举：``ok=True`` + 空 values，与"查不到该属性"（ok=False）严格区分。
            return {
                "available": True,
                "ok": True,
                "property_name": name,
                "feature": schema["feature_name"],
                "topic_filter": schema.get("topic_filter"),
                "is_enum": False,
                "values": [],
                "union_values": [],
                "union_variant_count": len(docs),
                "intersection_values": [],
                "variant_dependent_values": [],
                "labels": list(head.get("labels") or []),
                "descrs_raw": head.get("descrs"),
                "descr": head.get("descr"),
                "default": head.get("default"),
                "type": head.get("type"),
                "variant_count": len(docs),
                "definitions": docs,
                "reason": None,
                "probes": schema.get("probes") or [],
                "note": (
                    "该属性在 schema 里**没有枚举取值**（不是枚举属性或未定义取值）："
                    "没有可校验的合法取值列表，调用方须按「无枚举限制可查」处理。"
                ),
            }
        return {
            "available": True,
            "ok": True,
            "property_name": name,
            "feature": schema["feature_name"],
            "topic_filter": schema.get("topic_filter"),
            "is_enum": bool(head.get("values")),
            "values": union,
            "union_values": union,
            "union_variant_count": len(docs),
            "intersection_values": list(schema["enum_intersection"].get(name) or []),
            "variant_dependent_values": list(
                schema["enum_variant_dependent"].get(name) or []
            ),
            "labels": list(head.get("labels") or []),
            "descrs_raw": head.get("descrs"),
            "descr": head.get("descr"),
            "default": head.get("default"),
            "type": head.get("type"),
            "variant_count": len(docs),
            "definitions": docs,
            "reason": None,
            "probes": schema.get("probes") or [],
            "note": (
                "values = 该特征所有变体的**并集**；intersection_values 是最保守口径；"
                "variant_dependent_values 里的取值只在部分变体合法。"
            ),
        }

    data, error, probes = _completion_data(path)
    if data is None:
        return {
            "available": False,
            "ok": False,
            "property_name": name,
            "feature": None,
            "topic_filter": None,
            "values": None,
            "labels": None,
            "definitions": [],
            "reason": error or "补全数据不可用",
            "probes": probes,
            "note": "schema 不可用：**未做枚举校验**，不得当作通过。",
        }
    definitions = [
        prop for prop in (data.get("props") or {}).values() if prop.get("name") == name
    ]
    if not definitions:
        return {
            "available": True,
            "ok": False,
            "property_name": name,
            "feature": None,
            "topic_filter": None,
            "values": None,
            "labels": None,
            "definitions": [],
            "reason": f"补全数据里没有名为 {name!r} 的枚举属性定义行",
            "probes": probes,
        }
    union: list[str] = []
    for prop in definitions:
        for value in prop.get("values") or []:
            if value not in union:
                union.append(value)
    head = definitions[0]
    intersection = [v for v in union if all(v in (p.get("values") or []) for p in definitions)]
    return {
        "available": True,
        "ok": True,
        "property_name": name,
        "feature": None,
        "topic_filter": None,
        "is_enum": bool(union),
        "values": union,
        "union_values": union,
        "union_variant_count": len(definitions),
        "intersection_values": intersection,
        "variant_dependent_values": [v for v in union if v not in intersection],
        "labels": list(head.get("labels") or []),
        "descrs_raw": head.get("descrs"),
        "descr": head.get("descr"),
        "default": head.get("default"),
        "type": head.get("type"),
        "variant_count": len(definitions),
        "definitions": definitions,
        "reason": None,
        "probes": probes,
        "note": (
            "未指定 feature：``values`` 是**全表同名属性**的并集，口径比按特征查询更宽；"
            "报告里必须写明口径。"
        ),
    }


def validate_enum_value(
    feature_name: Any,
    property_name: str,
    value: Any,
    *,
    topic: Any = None,
    path: Any = None,
) -> dict[str, Any]:
    """校验一个枚举取值是否合法（供 M-file 解析与交叉校验共用）。

    判据（全部基于 ``values``，**绝不**用人类标签 ``descrs`` 判合法性）：

    - ``checked=False``：schema 缺失/损坏，或该特征/属性在 schema 里查不到
      ⇒ **未校验**，必须显式上报，不能当作通过；
    - ``value in enum_union`` 为假 ⇒ ``in_union=False``（真正的非法值，例如 ``"Pressure"``）；
    - ``in_union`` 真但不在 ``enum_intersection`` 里 ⇒ ``variant_dependent=True``
      （只在部分变体合法，写入前要确认命中哪个变体）。

    失败模式：``feature_name`` 为空 → :class:`ValueError`；其余情况一律返回结构而不抛错，
    由调用方把 ``checked=False`` 当成"没验证过"如实上报。
    """
    feature = str(feature_name or "").strip()
    if not feature:
        raise ValueError("validate_enum_value 需要非空的 feature_name")
    enum = lookup_enum(property_name, feature=feature, topic=topic, path=path)
    result: dict[str, Any] = {
        "feature": feature,
        "property": str(property_name),
        "value": value,
        "topic_filter": None if topic is None else str(topic),
        "schema_available": enum.get("available"),
        "checked": False,
        "in_union": None,
        "variant_dependent": None,
        "legal_values": None,
        "intersection_values": None,
        "reason": enum.get("reason"),
        "source": "COMSOL completion data (physics.xml)",
    }
    if not enum.get("ok"):
        if enum.get("values") == []:
            # 属性存在、但不是枚举属性（例如数值属性）——这是**可区分**的情况：
            # 不是"没查到"，而是"它本来就没有枚举限制"。
            result["checked"] = True
            result["legal_values"] = []
            result["reason"] = (
                f"属性 {property_name!r} 在 schema 里存在但没有枚举取值"
                "（不是枚举属性），因此没有【合法取值】可校验"
            )
        return result
    values = list(enum.get("values") or [])
    if not values:
        # 属性存在、但不是枚举属性：`checked` 为 **True**（查过了，结论是"没有枚举限制"），
        # 与"查不到该属性/属性名未知"（`ok=False` 分支，`checked=False`）严格区分。
        result["checked"] = True
        result["legal_values"] = []
        result["reason"] = (
            f"属性 {property_name!r} 在 schema 里没有枚举取值（不是枚举属性或未定义）："
            "没有【合法取值】可校验，调用方须按「无枚举限制可查」处理"
        )
        return result
    text = None if value is None else str(value)
    result["checked"] = True
    result["legal_values"] = values
    result["intersection_values"] = list(enum.get("intersection_values") or [])
    result["in_union"] = text in values
    result["variant_dependent"] = bool(
        text in values and text not in set(result["intersection_values"] or [])
    )
    if not result["in_union"]:
        result["reason"] = (
            f"{text!r} 不是 {feature} 的属性 {property_name} 的合法取值；"
            f"合法取值（并集）={values}"
        )
    elif result["variant_dependent"]:
        result["reason"] = (
            f"{text!r} 只在部分变体中合法（交集={result['intersection_values']}）："
            "写入前必须确认命中的是哪个变体"
        )
    return result


def lookup_feature_type_doc(feature_type: str, *, topic: Any = None) -> dict[str, Any]:
    """对某个特征类型做一次 schema 查询并只返回**报告用**的摘要（可用性与属性数）。

    失败模式：与 :func:`lookup_feature_schema` 相同（不抛错，返回 ``ok=False`` + 原因）。
    """
    schema = lookup_feature_schema(feature_type, topic=topic)
    return {
        "feature_type": feature_type,
        "topic_filter": None if topic is None else str(topic),
        "available": schema.get("available"),
        "ok": schema.get("ok"),
        "topics": schema.get("topics"),
        "variant_count": schema.get("variant_count"),
        "property_names": sorted(schema.get("docs") or {}),
        "enum_properties": sorted(schema.get("enum_union") or {}),
        "reason": schema.get("reason"),
        "probes": schema.get("probes"),
    }


def _topic_family_hint(interface_type: Any, interface_tag: Any = None) -> str | None:
    """由物理场接口类型/标签推出**族前缀**（如 ``SolidMechanics`` → ``"solid"``）。

    只用于给报告提示"该在哪个物理场族里核对"，**绝不**用来把某个变体的枚举当成唯一判据
    （那会把"不确定"伪装成"确定"）。
    """
    text = str(interface_type or "")
    lowered = text.lower()
    for token, family in (
        ("solidmechanics", "solid"),
        ("solid", "solid"),
        ("heattransfer", "ht"),
        ("acoustic", "acpr"),
        ("pressurese", "pelw"),
        ("electriccurrents", "ec"),
    ):
        if token in lowered:
            return family
    tag = str(interface_tag or "").lower()
    return tag or None


def _property_in_detail_table(property_name: str, *, path: Any = None) -> dict[str, Any]:
    """该属性名是否在补全数据的属性定义表里出现（不论取值是否为枚举）。

    用来把「特征变体没列这个属性」与「这个属性本来就没有枚举」分开。

    失败模式：schema 不可用 → ``{"available": False, "found": None}``（未知，不是"没有"）。
    """
    data, error, probes = _completion_data(path)
    if data is None:
        return {"available": False, "found": None, "error": error, "probes": probes}
    found = [
        prop
        for prop in (data.get("props") or {}).values()
        if prop.get("name") == property_name
    ]
    return {
        "available": True,
        "found": bool(found),
        "definition_count": len(found),
        "has_enum_values": any(prop.get("values") for prop in found),
        "probes": probes,
    }


def _property_in_feature_schema(
    feature_name: str, property_name: str, *, path: Any = None
) -> dict[str, Any]:
    """该属性的枚举取值是否出现在**该特征的任意变体**里（不限 topic）。

    用于区分「这个特征里根本没有这个枚举属性」与「只是当前变体没列它」。

    失败模式：schema 不可用/特征不存在 → ``found=False`` + ``available``/``reason``。
    """
    schema = lookup_feature_schema(feature_name, path=path)
    if not schema.get("ok"):
        return {
            "available": schema.get("available"),
            "found": False,
            "reason": schema.get("reason"),
            "probes": schema.get("probes"),
        }
    union = schema.get("enum_union") or {}
    return {
        "available": True,
        "found": property_name in union,
        "legal_values": list(union.get(property_name) or []),
        "topics_with_property": sorted(
            {
                str(entry.get("topic"))
                for entry in (schema.get("docs") or {}).get(property_name, [])
                if entry.get("values")
            }
        ),
        "probes": schema.get("probes"),
    }


def build_enum_validation(
    physics: Iterable[Mapping[str, Any]] | None,
    *,
    path: Any = None,
    feature_override: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """对解析出的物理场特征逐个做**枚举合法性**校验（用本地权威 schema）。

    ``feature_override`` 可用于人工指定 tag → 特征类型的映射（默认取解析出的 ``type``）。

    返回::

        {
          "available": bool, "schema": {...schema_source()...},
          "checked_count": int, "enum_checked": int, "illegal": [...],
          "variant_dependent": [...], "unresolved": [...],
          "by_feature": [{"tag","feature_type","topic_hint","items":[...]}],
          "error": str|None, "notes": [...]
        }

    失败模式：

    - schema 不可用/损坏 → ``available=False`` + ``error`` + ``schema.probes``，
      ``checked_count=0``，``notes`` 明确写"未校验"（**不得**被当成通过）；
    - 特征类型在 schema 里查不到 → 该属性进 ``unresolved``（附原因），不计入已校验；
    - 属性是枚举但取值不在并集内 → 进 ``illegal``（真正的错误）；
    - 取值在并集但不在交集 → 进 ``variant_dependent``（只在部分变体合法，需人工确认）；
    - 属性在**其它变体**里才有枚举 → ``resolution="enum_property_not_in_current_topic"``
      （变体未定，无法校验，附 ``topics_with_property`` 与全变体合法取值）；
    - 属性根本不该有枚举（全表里都没有 values）→ ``resolution="not_an_enum_property"``
      （**无需**校验，与"查不到"区分）。
    """
    rows = list(physics or [])
    source = schema_source(path)
    payload: dict[str, Any] = {
        "available": bool(source.get("available")),
        "schema": source,
        "error": source.get("error"),
        "checked_count": 0,
        "enum_checked": 0,
        "illegal": [],
        "variant_dependent": [],
        "unresolved": [],
        "by_feature": [],
        "notes": [],
    }
    if not payload["available"]:
        payload["notes"].append(
            "本地权威 schema 不可用：所有枚举赋值**未校验**；"
            "不得把未校验当成合法（红线 3/1）。"
        )
        return payload

    for iface in rows:
        if not isinstance(iface, Mapping):
            continue
        iface_type = iface.get("interface_type")
        iface_tag = iface.get("interface_tag")
        topic_hint = _topic_family_hint(iface_type, iface_tag)
        for feature in iface.get("features") or []:
            if not isinstance(feature, Mapping):
                continue
            tag = feature.get("tag")
            ftype = (feature_override or {}).get(str(tag)) or feature.get("type")
            entry: dict[str, Any] = {
                "tag": tag,
                "feature_type": ftype,
                "interface_type": iface_type,
                "topic_hint": topic_hint,
                "items": [],
            }
            for prop in feature.get("properties") or []:
                if not isinstance(prop, Mapping):
                    continue
                pname = prop.get("name")
                pvalue = prop.get("value")
                if not pname or not ftype:
                    continue
                payload["checked_count"] += 1
                check = validate_enum_value(str(ftype), str(pname), pvalue, path=path)
                item = {
                    "feature_type": ftype,
                    "feature_tag": tag,
                    "property": pname,
                    "value": pvalue,
                    "checked": check["checked"],
                    "in_union": check["in_union"],
                    "variant_dependent": check["variant_dependent"],
                    "legal_values": check["legal_values"],
                    "reason": check["reason"],
                }
                if not check["checked"]:
                    # 查不到"当前 topic 下的该特征 + 属性"这一组合，有三种情况要分开：
                    #   (a) 该特征**其它变体**里有这个枚举属性 → 变体相关，无法在未定变体时校验；
                    #   (b) 属性名在全表里存在但没有枚举取值 → 本来就无需枚举校验；
                    #   (c) 属性名在全表里都不存在 → 真·查不到（可能暴露同义词/别名问题）。
                    any_variant = _property_in_feature_schema(str(ftype), str(pname), path=path)
                    if any_variant.get("found"):
                        item["resolution"] = "enum_property_not_in_current_topic"
                        item["legal_values_all_variants"] = any_variant.get("legal_values")
                        item["topics_with_property"] = any_variant.get("topics_with_property")
                        item["reason"] = (
                            f"属性 {pname!r} 只在 {ftype} 的**其它变体**里有枚举取值"
                            f"（变体 topics={any_variant.get('topics_with_property')}），"
                            "当前未确定变体（topic）故无法校验；调用方须显式确认命中哪个变体"
                        )
                    else:
                        in_detail = _property_in_detail_table(str(pname), path=path)
                        if not in_detail["found"] and in_detail["available"]:
                            item["resolution"] = "not_an_enum_property"
                            item["reason"] = (
                                f"属性 {pname!r} 在补全数据的属性表里存在但**没有枚举取值**："
                                "无需枚举校验（不同于「查不到」）"
                            )
                            item["legal_values"] = []
                        else:
                            item["resolution"] = "unresolved"
                            item["property_in_detail_table"] = in_detail["found"]
                            payload["unresolved"].append(item)
                    entry["items"].append(item)
                    continue
                if check["legal_values"] == []:
                    # 属性存在但不是枚举（例如数值属性）：不算校验、也不算错误
                    item["resolution"] = "not_an_enum_property"
                    entry["items"].append(item)
                    continue
                payload["enum_checked"] += 1
                if not check["in_union"]:
                    item["resolution"] = "illegal_enum_value"
                    payload["illegal"].append(item)
                elif check["variant_dependent"]:
                    item["resolution"] = "variant_dependent"
                    payload["variant_dependent"].append(item)
                else:
                    item["resolution"] = "legal"
                entry["items"].append(item)
            payload["by_feature"].append(entry)
    if payload["unresolved"]:
        payload["notes"].append(
            f"{len(payload['unresolved'])} 项**未能校验**：该属性名在补全数据的属性表里存在，"
            "但没有挂到该特征（type）的任何变体下——说明补全数据自身的特征→属性映射不完整，"
            "不是这些取值合法。这些项不得当作已校验。"
        )
    return payload


# ======================================================================================
# 4. COMSOL GUI 导出的 MATLAB Model M-file 解析（权威文本来源）
# ======================================================================================

# 顶层 block 函数名 → 内部区域键
_M_BLOCK_FUNCS = {
    "model_parameters": "parameters",
    "model_geometry": "geometry",
    "model_mesh": "mesh",
    "model_material": "materials",
    "model_physics": "physics",
    "model_multiphysics": "multiphysics",
    "model_study": "study",
    "model_results": "results",
}

# COMSOL 导出的 M 文件里主函数写作 ``function out = model``，子函数写作
# ``function model = model_parameters(model)``；两者都必须识别，否则整个导出会被归到
# 一个错误的块里（实测踩过：只认 ``function <name> =`` 时主函数被识别成 ``out``，
# 于是 parameters/geometry/physics 块全部落空）。
_FUNC_DEF_RE = re.compile(r"^\s*function\s+(?:[\w\[\]]+\s*=\s*)?([A-Za-z_]\w*)\s*(?:\(|$)")
# 主函数的几种可能名字（不同 COMSOL 版本的导出习惯不同）
_MAIN_FUNC_NAMES = frozenset({"model", "out"})

# 研究/求解器的语句特征。物理场解析器必须跳过这类行，否则 ``model.study('std1')
# .feature('freq').set('plist', 'range(1[MHz],…,35[MHz])')`` 与
# ``model.sol('sol1').feature('st1').set('study','std1')`` 会被误记成"指向未见过的
# 物理场特征"（实测：真实导出 bGEtask2.m 里有 244 条这样的假 unknown）。
_STUDY_OR_SOLVER_STMT = re.compile(r"\.study\s*\(|\.sol\s*\(")

# 几何/网格的语句也大量使用 ``...feature('x').set(...)``（work plane 的尺寸、revolve 的角度…）。
# 物理场解析器同样必须跳过：实测真实导出里有 117 条几何 feature 的 set 被误记成
# "指向未见过的物理场特征"，而它们其实已由 ``_parse_geometry`` 正确收下。
_GEOM_OR_MESH_STMT = re.compile(r"\.geom\s*\(|\.geom\.|\.mesh\s*\(|\.mesh\.")

# 后处理（``model.result('pg1').feature('surf1').set('expr', …)``）同样是 ``...feature(...).set(...)``
# 形状；物理场解析器跳过，由 ``_parse_results`` 收成"结果节点清单"（实测 42 条被误记）。
_RESULT_STMT = re.compile(r"\.result\s*\(|\.result\.")


def _strip_comment(line: str) -> str:
    """去掉 MATLAB 行注释（只处理字符串外的 ``%``）。"""
    out: list[str] = []
    in_string = False
    idx = 0
    while idx < len(line):
        ch = line[idx]
        if ch == "'":
            if in_string and idx + 1 < len(line) and line[idx + 1] == "'":
                out.append("''")
                idx += 2
                continue
            in_string = not in_string
            out.append(ch)
        elif ch == "%" and not in_string:
            break
        else:
            out.append(ch)
        idx += 1
    return "".join(out)


def _bracket_depth(text: str) -> int:
    """字符串外的括号净深度（``'...'`` 内的括号不计）。"""
    depth = 0
    in_string = False
    idx = 0
    while idx < len(text):
        ch = text[idx]
        if ch == "'":
            if in_string and idx + 1 < len(text) and text[idx + 1] == "'":
                idx += 2
                continue
            in_string = not in_string
        elif not in_string:
            if ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth -= 1
        idx += 1
    return depth


def _matlab_statements(text: str) -> list[tuple[int, str]]:
    """把 M 文件切成逻辑语句：拼接续行（``...``）、括号未闭合、行尾逗号。

    返回 ``[(起始行号, 语句文本)]``。失败模式：只做文本切分，不解析语义——
    无法识别的行原样留着，由上层决定是否记进 ``unknown_assignments``。
    """
    statements: list[tuple[int, str]] = []
    buffer: list[str] = []
    start = 0
    for lineno, raw in enumerate(text.splitlines(), start=1):
        stripped = _strip_comment(raw).rstrip()
        if not buffer and not stripped.strip():
            continue
        if not buffer:
            start = lineno
        piece = stripped
        if piece.endswith("..."):
            buffer.append(piece[:-3])
            continue
        buffer.append(piece)
        joined = " ".join(part.strip() for part in buffer if part.strip())
        if _bracket_depth(joined) > 0 or joined.endswith(","):
            continue
        if joined:
            statements.append((start, joined))
        buffer = []
    if buffer:
        joined = " ".join(part.strip() for part in buffer if part.strip())
        if joined:
            statements.append((start, joined))
    return statements


def _split_top_level(text: str, sep: str = ",", *, split_whitespace: bool = False) -> list[str]:
    """按顶层分隔符切分（字符串与括号内的分隔符不切）。

    ``split_whitespace=True`` 时同时把**字符串外的空白**当分隔符——MATLAB 的单元数组
    写作 ``{'solid' 'on' 'ht' 'off'}``（空格分隔，不是逗号），只按逗号切会把整段
    粘成一个字符串 ``"solid' 'on' 'ht' 'off"``（实测踩过）。
    """
    parts: list[str] = []
    buffer: list[str] = []
    depth = 0
    in_string = False
    idx = 0
    while idx < len(text):
        ch = text[idx]
        if ch == "'":
            if in_string and idx + 1 < len(text) and text[idx + 1] == "'":
                buffer.append("''")
                idx += 2
                continue
            in_string = not in_string
            buffer.append(ch)
        elif not in_string and ch in "([{":
            depth += 1
            buffer.append(ch)
        elif not in_string and ch in ")]}":
            depth -= 1
            buffer.append(ch)
        elif not in_string and depth == 0 and (ch == sep or (split_whitespace and ch.isspace())):
            parts.append("".join(buffer).strip())
            buffer = []
        else:
            buffer.append(ch)
        idx += 1
    tail = "".join(buffer).strip()
    if tail:
        parts.append(tail)
    return [part for part in parts if part != ""]


def _matlab_value(token: str) -> Any:
    """把一个 MATLAB 字面量转成 Python 值（字符串 / 数值 / 向量 / 单元数组 / 裸标识符）。

    字符串**原样返回**（内部 ``''`` 还原为 ``'``），以保证 ``forceType`` 这类枚举原文
    不被改写、不被大小写归一。``[...]`` 与 ``{...}`` 都转成列表——
    COMSOL 导出的字符串向量就是单元数组 ``{'solid' 'on'}``。
    """
    token = token.strip()
    if len(token) >= 2 and token.startswith("'") and token.endswith("'"):
        return token[1:-1].replace("''", "'")
    if len(token) >= 2 and token[0] in "[{" and token[-1] in "]}":
        inner = token[1:-1].strip()
        if not inner:
            return []
        # MATLAB 向量/单元数组都用**空白**分隔元素（``[4 5]``、``{'solid' 'on'}``），
        # 只按逗号切会把整段粘成一个字符串（实测踩过）；含逗号时才按逗号切。
        if "," in inner:
            return [_matlab_value(part) for part in _split_top_level(inner)]
        return [_matlab_value(part) for part in _split_top_level(inner, split_whitespace=True)]
    try:
        return float(token)
    except ValueError:
        return token


def _is_quoted_literal(token: str) -> bool:
    """token 是否是 MATLAB 字符串字面量（``'x'``）。"""
    token = token.strip()
    return len(token) >= 2 and token.startswith("'") and token.endswith("'")


def _iter_calls(stmt: str, method: str) -> list[tuple[str, str]]:
    """从一条语句抽出所有 ``<target>.<method>(<args>)``（顶层括号匹配）。

    ``target`` 是**完整接收者链**，例如
    ``model.component('comp1').physics('solid').feature('load1')``。
    向左回溯时按括号配平跨过 ``(...)`` 段、允许 ``.`` 与标识符——
    只按标识符回溯会在第一个 ``)`` 处停下，target 退化成 ``.feature`` 这种碎片，
    组件 tag 与物理场 tag 全部丢失（实测踩过）。
    """
    calls: list[tuple[str, str]] = []
    marker = f".{method}("
    idx = 0
    while True:
        pos = stmt.find(marker, idx)
        if pos < 0:
            break
        left = pos
        depth = 0
        while left > 0:
            prev = stmt[left - 1]
            if prev == ")":
                depth += 1
            elif prev == "(":
                depth -= 1
            elif depth == 0 and not (prev.isalnum() or prev in "_."):
                break
            left -= 1
        target = stmt[left:pos]
        arg_start = pos + len(marker)
        depth = 1
        cursor = arg_start
        while cursor < len(stmt) and depth > 0:
            if stmt[cursor] == "(":
                depth += 1
            elif stmt[cursor] == ")":
                depth -= 1
            cursor += 1
        args = stmt[arg_start: cursor - 1] if depth == 0 else stmt[arg_start:]
        calls.append((target, args))
        idx = cursor if cursor > pos else pos + 1
    return calls


def _string_arg(args: str) -> str | None:
    """取参数里的第一个字符串字面量（``selection('bnd1')`` → ``bnd1``）。"""
    for part in _split_top_level(args):
        value = _matlab_value(part)
        if isinstance(value, str):
            return value
    return None


def _entities_from_args(args: str) -> list[int] | None:
    """从参数里抽实体编号：``selection.set([4 5])`` / ``selection.set(1)`` / ``set(4,5)``。

    标量写法（``set(1)``）与向量写法（``set([4 5])``）都接受——
    只认列表会把标量选择集读成「无选择」（实测踩过）。
    """
    parts = _split_top_level(args)
    if not parts:
        return None
    if len(parts) == 1:
        value = _matlab_value(parts[0])
        if isinstance(value, list):
            numbers = [int(v) for v in value if isinstance(v, (int, float))]
            return numbers or None
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return [int(value)]
        return None
    numbers = []
    for part in parts:
        value = _matlab_value(part)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            numbers.append(int(value))
    return numbers or None


def _component_of(target: str) -> str | None:
    """从 ``model.component('comp1').geom('geom1')...`` 里取组件 tag。"""
    match = re.search(r"\.component\(\s*'([^']*)'\s*\)", target)
    return match.group(1) if match else None


def _ends_with_tagged_call(target: str, method: str) -> bool:
    """``target`` 是否以 ``.<method>('tag')`` 结尾（即带 tag 的接收者调用）。

    这是区分「几何序列 / 物理场接口 / 特征 / 研究」的唯一可靠信号：
    - ``...component('comp1').geom('geom1').create('r1','Rectangle')``
      → target ``...geom('geom1')`` 以带 tag 的 ``.geom(...)`` 结尾 ⇒ 那是**几何特征**；
    - ``...component('comp1').geom.create('geom1', 2)``
      → target ``...component('comp1').geom`` ⇒ 那是**几何序列本身**。
    早期用 ``\\.geom$`` 判断，结果永远不匹配（带 tag 的写法结尾是 ``('geom1')``）。
    """
    return re.search(rf"\.{method}\(\s*'[^']*'\s*\)$", target) is not None


def _tag_of(target: str, method: str) -> str | None:
    """取 ``.geom('geom1')`` / ``.physics('ht')`` / ``.feature('load1')`` 里的 tag。

    必须匹配**最后一次**出现（前缀用贪婪 ``.*``）：同一条接收者链里同一方法名可能多次
    出现——``...physics('solid').feature('load1')`` 取 ``feature`` 时要拿到 ``load1``。
    """
    match = re.search(rf".*\.{method}\(\s*'([^']*)'\s*\)", target)
    return match.group(1) if match else None


def parse_matlab_export(source: str | Path, *, validate_enums: bool = True) -> dict[str, Any]:
    """解析 COMSOL 导出的 MATLAB Model M-file（``.m``）为结构化 spec。

    ``source`` 可以是路径（存在则读文件）或 M 文件**文本**。这是与运行时读回并列的
    **权威文本来源**：它保留物理场属性的准确键名与**枚举原文**（例如 ``forceType`` 的
    ``FollowerPressure`` / ``ForceArea``）、选择集实体编号，以及研究步骤。

    ``validate_enums=True`` 时用本地权威 schema（COMSOL 自带的
    ``data/completion/physics.xml``，见 :func:`lookup_feature_schema`）校验每个
    "枚举型属性的赋值"是否落在合法取值内，结果放在 ``enum_validation``；
    **schema 不可用时标注为未校验**（``checked=False``），不静默放过——因为
    ``set("forceType", "Pressure")`` 这类非法值会被 COMSOL 抛异常、异常被吞掉后
    属性停在默认值，最终载荷为零、位移恒为 0（真实踩坑，见本节顶部注释）。

    返回::

        {
          "parse_version","source_kind":"path"|"text","source_path","sha256",
          "parsed": bool, "reason": str|None, "model_tag": str|None,
          "parameters": [{"name","expression","description"}],
          "geometry":   [{"component","tag","dimension","features":[{"tag","type"}]}],
          "materials":  [{"component","tag","label","property_groups":[{"tag","properties"}]}],
          "physics":    [{"component","interface_tag","interface_type",
                          "features":[{"tag","type","doc_name",
                                       "properties":[{"name","value"}],
                                       "selection":{"tag","entities"}|None}]}],
          "selections": [{"owner","tag","entities","line"}],
          "study":      [{"tag","label","steps":[{"tag","type","properties",
                          "activated_physics":[{"interface","active"}]}]}],
          "solvers":    [{"tag","study","features":[{"tag","type","properties"}]}],
          "unknown_assignments": [...],   # 识别不了的赋值（保留原文 + 行号）
          "enum_validation": {...},       # 枚举合法性校验（含 schema 可用性）
          "notes": [...]
        }

    **研究段与求解器段都在主函数里**：真实 GUI 导出（``File > Save As → *.m``）不生成
    ``model_study`` 子函数，``model.study.create`` / ``…feature('freq').set('plist',…)`` /
    ``model.sol('sol1').study('std1')`` 全部写在 ``function out = model`` 里，
    因此主函数的行必须同时喂给 geometry / materials / physics / study / solvers 五个解析器
    （实测踩过：只喂 ``blocks["study"]`` 时 study 解析为空列表，且 244 条研究/求解器赋值
    被物理场解析器误记为"指向未见过的物理场特征"）。

    失败模式：

    - 路径不存在 → :class:`FileNotFoundError`；
    - 文本里没有 ``function`` 定义 → 返回 ``{"parsed": False, "reason": ...}``，
      **不抛错也不猜内容**；
    - 单条赋值解析不了 → 进 ``unknown_assignments``（原文 + 行号），不中断整体解析；
    - 枚举/字符串值一律原样保留，不做同义归一（交叉校验必须暴露差异）；
    - schema 缺失/损坏 → ``enum_validation.available=False`` + ``error`` + 探测记录，
      ``checked`` 全部为 ``False``：**未校验 ≠ 通过**。
    """
    text: str
    source_kind: str
    source_path: str | None = None
    digest: str | None = None
    as_path: Path | None = None
    if isinstance(source, Path):
        as_path = source
    elif isinstance(source, str) and "\n" not in source:
        candidate = Path(source)
        if candidate.exists():
            as_path = candidate
    if as_path is not None:
        if not as_path.is_file():
            raise FileNotFoundError(f"M 文件不存在：{as_path}")
        text = as_path.read_text(encoding="utf-8", errors="replace")
        source_kind = "path"
        source_path = str(as_path)
        digest = sha256_file(as_path)
    else:
        text = str(source)
        source_kind = "text"

    result: dict[str, Any] = {
        "parse_version": MODELIO_VERSION,
        "source_kind": source_kind,
        "source_path": source_path,
        "sha256": digest,
        "parsed": False,
        "reason": None,
        "model_tag": None,
        "parameters": [],
        "geometry": [],
        "materials": [],
        "physics": [],
        "selections": [],
        "study": [],
        "solvers": [],
        "results": [],
        "unknown_assignments": [],
        "enum_validation": None,
        "notes": [],
    }

    statements = _matlab_statements(text)
    if not statements:
        result["reason"] = "文件中没有任何可解析语句（空文件或全部是注释）"
        return result
    if not any(_FUNC_DEF_RE.match(stmt) for _, stmt in statements):
        result["reason"] = (
            "未发现 MATLAB function 定义：这不像是 COMSOL 导出的 Model M-file"
            "（GUI 用法：File > Save As → *.m）。不猜测其内容。"
        )
        return result

    blocks: dict[str, list[tuple[int, str]]] = {"main": []}
    current = "main"
    for lineno, stmt in statements:
        match = _FUNC_DEF_RE.match(stmt)
        if match:
            name = match.group(1)
            # 主函数（``function out = model`` / ``function model = model()``）保持 "main"；
            # 其余按已知的块函数名映射，未知函数名原样建块（不猜测归属）。
            if name in _MAIN_FUNC_NAMES:
                current = "main"
            else:
                current = _M_BLOCK_FUNCS.get(name, name)
            blocks.setdefault(current, [])
            continue
        blocks.setdefault(current, []).append((lineno, stmt))
    result["parsed"] = True

    # ---- 参数表（**所有块**都要扫，不能只扫 parameters/main） --------------------
    # ⚠️ 实测缺陷（2026-09-12）：这里原本只遍历 ``("parameters", "main")`` 两个块，
    # 而 COMSOL 导出时**函数名跟随文件名**——``File > Save As`` 存成 ``foo.m`` 时导出的是
    # ``function out = foo``，既不叫 ``model`` 也不叫 ``model_parameters``，于是参数块被
    # 整段漏掉、``parameters`` 变成空表（只留一句提示），下游 cross_check 会把所有参数记成
    # ``missing_in_spec``。其它各段早就用 ``all_rows``（全部块），唯独参数表漏了。
    # 现在按「parameters → main → 其余块（按名排序）」扫全部块，块名仍如实记录。
    block_names = ["parameters", "main"] + sorted(
        name for name in blocks if name not in ("parameters", "main")
    )
    for block in block_names:
        for lineno, stmt in blocks.get(block, []):
            for target, args in _iter_calls(stmt, "set"):
                if not re.search(r"(^|\.)param$", target) and not target.endswith("model.param"):
                    continue
                raw_args = _split_top_level(args)
                values = [_matlab_value(part) for part in raw_args]
                if len(values) < 2 or not isinstance(values[0], str):
                    result["unknown_assignments"].append(
                        {
                            "line": lineno,
                            "block": block,
                            "text": stmt,
                            "reason": "param.set 的首参不是字符串字面量，无法确定参数名",
                        }
                    )
                    continue
                if not _is_quoted_literal(raw_args[0]):
                    # 名字是裸变量（如 ``param.set(name_var, ...)``）：名字此刻**不可知**，
                    # 必须如实记成未解析项，不得把变量名当成参数名（红线 3）。
                    result["unknown_assignments"].append(
                        {
                            "line": lineno,
                            "block": block,
                            "text": stmt,
                            "reason": (
                                f"param.set 的参数名是变量 {raw_args[0]!r} 而非字符串字面量："
                                "名字在运行前不可知，故不登记该参数"
                            ),
                        }
                    )
                    continue
                result["parameters"].append(
                    {
                        "name": values[0],
                        "expression": values[1],
                        "description": values[2] if len(values) > 2 else "",
                        "block": block,
                    }
                )

    # ---- 主函数的 model 创建（用于取 model_tag） --------------------------------
    for _, stmt in blocks.get("main", []):
        inner = re.search(r"ModelUtil\.create\(\s*'([^']*)'", stmt)
        if inner:
            result["model_tag"] = inner.group(1)

    # ---- 选择集索引（全局，按 owner+tag 去重；实体编号合并） ----------------------
    # 导出里选择集有两种写法，都要收：
    #   a) ``...feature('load1').selection.set([4 5])``  → owner 以 ``.selection`` 结尾
    #   b) ``model.component('comp1').selection('sel1').set(2)`` → 命名选择集
    selections: dict[tuple[str, str], dict[str, Any]] = {}
    for _, rows in blocks.items():
        for lineno, stmt in rows:
            for target, args in _iter_calls(stmt, "selection"):
                owner = re.sub(r"\.selection$", "", target)
                sel_tag = _string_arg(args)
                entities = _entities_from_args(args)
                entry = selections.setdefault(
                    (owner, sel_tag or ""),
                    {"owner": owner, "tag": sel_tag, "entities": None, "lines": []},
                )
                entry["lines"].append(lineno)
                if entities is not None and entry["entities"] is None:
                    entry["entities"] = entities
                # 链式写法 ``.selection('sel1').set(...)`` 的选择在**下一个**调用里
                if not _ends_with_tagged_call(target, "selection"):
                    continue
                chained = re.compile(
                    re.escape(target) + r"\.(?:set|setIndex)\(([^;]*)\)"
                ).search(stmt)
                if chained:
                    chained_entities = _entities_from_args(chained.group(1))
                    if chained_entities is not None and entry["entities"] is None:
                        entry["entities"] = chained_entities
            for target, args in _iter_calls(stmt, "set"):
                # 写法 a：``...feature('load1').selection.set([4 5])``。
                # 这里只登记选择集索引；物理场特征上的选择由 _parse_physics 写入特征本身。
                if not target.endswith(".selection"):
                    continue
                owner = re.sub(r"\.selection$", "", target)
                entry = selections.setdefault(
                    (owner, ""), {"owner": owner, "tag": None, "entities": None, "lines": []}
                )
                entry["lines"].append(lineno)
                entities = _entities_from_args(args)
                if entities is not None and entry["entities"] is None:
                    entry["entities"] = entities
    result["selections"] = [
        {
            "owner": item["owner"],
            "tag": item["tag"],
            "entities": item["entities"],
            "line": item["lines"][0] if item["lines"] else None,
            "occurrences": len(item["lines"]),
        }
        for item in (selections[key] for key in sorted(selections, key=lambda k: (k[0], k[1] or "")))
    ]

    # 主函数里也会出现几何/物理场/研究/求解器的声明（``geom.create('geom1', 2)``、
    # ``study.create('std1')`` 就在 main 里），所以把 main 的行也交给各块解析器——
    # 否则维度、接口类型、研究步骤会全部读不到。
    #
    # 实测踩过（真实 GUI 导出 ``bGEtask2.m``，sha256 03a8629…c44d0）：
    # ``study`` 之前**只**拿 ``blocks["study"]``，而该文件根本没有 ``model_study`` 子函数，
    # 结果 study 段解析为**空列表**，同时 244 条 ``model.study(...)/model.sol(...)`` 赋值
    # 被 ``_parse_physics`` 当成"指向未见过的物理场特征"记进 unknown_assignments。
    # 根因正是这一行漏了 ``main_rows``（几何/材料/物理场三行都加了，唯独研究段落下了）。
    # 去重：一条语句只属于一个块，但多个解析器都要吃主函数的行。若同一个行号被同一个
    # 解析器处理两次（例如 physics 块 + main 块里重复出现），会产生重复条目甚至把同一个
    # 步骤/特征记成"孤儿"（实测踩过：研究步骤被算两次，多出 14 条假 unknown）。
    def _unique(*groups: list[tuple[int, str]]) -> list[tuple[int, str]]:
        seen: set[int] = set()
        merged: list[tuple[int, str]] = []
        for group in groups:
            for lineno, stmt in group:
                if lineno in seen:
                    continue
                seen.add(lineno)
                merged.append((lineno, stmt))
        return merged

    all_rows = _unique(*(rows for rows in blocks.values()))
    result["geometry"] = _parse_geometry(all_rows, result)
    result["materials"] = _parse_materials(all_rows, result)
    result["physics"] = _parse_physics(all_rows, result)
    result["study"] = _parse_study(all_rows, result)
    result["solvers"] = _parse_solvers(all_rows, result)
    result["results"] = _parse_results(all_rows, result)
    result["enum_validation"] = (
        build_enum_validation(result["physics"]) if validate_enums else None
    )
    if validate_enums and result["enum_validation"] and not result["enum_validation"]["available"]:
        result["notes"].append(
            "枚举合法性**未校验**：本地权威 schema（COMSOL 补全数据 physics.xml）不可用。"
            f"原因：{result['enum_validation'].get('error')}；探测记录见 enum_validation.probes。"
        )
    if not result["physics"]:
        result["notes"].append(
            "physics 块里没有解析到物理场接口：该导出可能未包含物理场设置（或导出选项被关闭）。"
            "不得据此断言模型没有物理场（红线 3）。"
        )
    if not result["parameters"]:
        result["notes"].append("参数表为空：导出可能不含参数块，或参数写在别处（见 unknown_assignments）。")
    return result


def _parse_geometry(rows: list[tuple[int, str]], result: dict[str, Any]) -> list[dict[str, Any]]:
    """解析 geometry 块：geom 标签/维度、几何特征（tag/type）与属性赋值。

    失败模式：识别不了的赋值进 ``unknown_assignments``（原文 + 块名 + 行号）。
    """
    geoms: dict[str, dict[str, Any]] = {}
    for lineno, stmt in rows:
        for target, args in _iter_calls(stmt, "create"):
            if ".geom" not in target:
                # 例如 ``ModelUtil.create('Model')`` 这类与几何无关的 create：
                # 只按「create 的参数长相」判断会把它误收成几何（实测踩过）。
                continue
            values = [_matlab_value(part) for part in _split_top_level(args)]
            if not values or not isinstance(values[0], str):
                continue
            if _ends_with_tagged_call(target, "geom"):
                # 两种都落这里：
                #   ``...geom('geom1').create('r1','Rectangle')``            → 几何**特征**
                #   ``...feature('wp1').geom.create('r1','Rectangle')``      → 工作平面内的**局部**几何
                # 局部几何的次参是特征类型（'Rectangle'）而不是维数，**不能**当维数写进
                # ``dimension``（实测踩过：dimension 变成 'Rectangle'）。
                key = _geom_key(target)
                entry = geoms.setdefault(
                    key,
                    {
                        "component": _component_of(target),
                        "tag": _tag_of(target, "geom"),
                        "dimension": None,
                        "features": [],
                        "properties": [],
                    },
                )
                _append_unique_feature(
                    entry["features"],
                    {"tag": values[0], "type": values[1] if len(values) > 1 else None},
                )
            elif _ends_with_tagged_call(target, "feature"):
                # ``...geom('geom1').feature('r1').create(...)``：特征的子特征
                key = _geom_key(target)
                entry = geoms.setdefault(
                    key,
                    {
                        "component": _component_of(target),
                        "tag": _tag_of(target, "geom"),
                        "dimension": None,
                        "features": [],
                        "properties": [],
                    },
                )
                _append_unique_feature(
                    entry["features"],
                    {"tag": values[0], "type": values[1] if len(values) > 1 else None},
                )
            else:
                # ``...component('comp1').geom.create('geom1', 2)``：几何**序列**本身
                key = _geom_key(target, values[0])
                entry = geoms.setdefault(
                    key,
                    {
                        "component": _component_of(target),
                        "tag": values[0],
                        "dimension": None,
                        "features": [],
                        "properties": [],
                    },
                )
                # 维数必须是**数值**：只认数字，避免把特征类型名当成维数。
                if entry["dimension"] is None and len(values) > 1 and isinstance(
                    values[1], (int, float)
                ):
                    entry["dimension"] = int(values[1])
        for target, args in _iter_calls(stmt, "set"):
            values = [_matlab_value(part) for part in _split_top_level(args)]
            if len(values) < 2 or not isinstance(values[0], str):
                continue
            key = _geom_key(re.sub(r"\.set$", "", target))
            if key in geoms:
                geoms[key]["properties"].append({"name": values[0], "value": values[1]})
    return [geoms[key] for key in sorted(geoms)]


def _append_unique_feature(bucket: list[dict[str, Any]], feature: dict[str, Any]) -> None:
    """按 tag 去重地追加特征（导出里同一个 tag 会被反复 create/set，实测会重复 9 次）。"""
    for existing in bucket:
        if existing.get("tag") == feature.get("tag"):
            if existing.get("type") is None and feature.get("type") is not None:
                existing["type"] = feature["type"]
            return
    bucket.append(feature)


def _geom_key(target: str, fallback_tag: Any = None) -> str:
    """几何块的稳定键：``<component>/<geom tag>``。

    ``fallback_tag`` 用于 ``...component('comp1').geom.create('geom1', 3)`` 这种
    创建语句——那时接收者链里还没有 tag，tag 只能取 create 的首参；早先直接用整条
    接收者链当 tag，导致同一次创建在表里落到 ``comp1/model.component('comp1').geom``
    这个错键上、维数丢失（实测踩过）。
    """
    component = _component_of(target) or "?"
    tag = _tag_of(target, "geom") or (
        str(fallback_tag) if isinstance(fallback_tag, str) else None
    ) or target
    return f"{component}/{tag}"


def _parse_materials(rows: list[tuple[int, str]], result: dict[str, Any]) -> list[dict[str, Any]]:
    """解析 material 块：材料 tag/类型/标签、属性组与属性赋值。

    失败模式：属性写在未知 owner 上时忽略该属性；材料节点本身仍会保留。
    """
    materials: dict[str, dict[str, Any]] = {}
    for lineno, stmt in rows:
        for target, args in _iter_calls(stmt, "create"):
            if _ends_with_tagged_call(target, "material"):
                continue
            if not target.endswith(".material"):
                continue
            values = [_matlab_value(part) for part in _split_top_level(args)]
            if not values or not isinstance(values[0], str):
                continue
            key = f"{_component_of(target)}/{values[0]}"
            materials.setdefault(
                key,
                {
                    "component": _component_of(target),
                    "tag": values[0],
                    "material_type": values[1] if len(values) > 1 else None,
                    "label": None,
                    "property_groups": {},
                },
            )
        for target, args in _iter_calls(stmt, "label"):
            if not _ends_with_tagged_call(target, "material"):
                continue
            tag = _tag_of(target, "material")
            key = f"{_component_of(target)}/{tag}"
            if key in materials:
                materials[key]["label"] = _string_arg(args)
        for target, args in _iter_calls(stmt, "propertyGroup"):
            match = re.search(r"\.material\(\s*'([^']*)'\s*\)", target)
            values = [_matlab_value(part) for part in _split_top_level(args)]
            if not match or not values or not isinstance(values[0], str):
                continue
            key = f"{_component_of(target)}/{match.group(1)}"
            entry = materials.setdefault(
                key,
                {
                    "component": _component_of(target),
                    "tag": match.group(1),
                    "material_type": None,
                    "label": None,
                    "property_groups": {},
                },
            )
            entry["property_groups"].setdefault(values[0], [])
        for target, args in _iter_calls(stmt, "set"):
            match = re.search(r"\.material\(\s*'([^']*)'\s*\)\.propertyGroup\(\s*'([^']*)'\s*\)$", target)
            if not match:
                continue
            values = [_matlab_value(part) for part in _split_top_level(args)]
            if len(values) < 2 or not isinstance(values[0], str):
                continue
            key = f"{_component_of(target)}/{match.group(1)}"
            if key not in materials:
                result["unknown_assignments"].append(
                    {
                        "line": lineno,
                        "block": "materials",
                        "text": stmt,
                        "reason": "属性赋值指向未声明的材料（未见对应 material.create）",
                    }
                )
                continue
            materials[key]["property_groups"].setdefault(match.group(2), []).append(
                {"name": values[0], "value": values[1]}
            )
    out: list[dict[str, Any]] = []
    for key in sorted(materials):
        item = materials[key]
        item["property_groups"] = [
            {"tag": tag, "properties": props}
            for tag, props in sorted(item["property_groups"].items())
        ]
        out.append(item)
    return out


def _parse_physics(rows: list[tuple[int, str]], result: dict[str, Any]) -> list[dict[str, Any]]:
    """解析物理场接口（tag/type/选择）与特征（tag/type/属性/选择）。

    枚举原文（如 ``forceType`` 的取值）**原样保留**，绝不做同义归并。

    失败模式：属性赋值指向未见过的特征 → 进 ``unknown_assignments``（原文 + 行号）；
    研究/求解器的行（``.study(...)`` / ``.sol(...)``）在本函数里**按行整体跳过**，
    因此它们不会污染物理场结果，也不会被误记成"未见过的物理场特征"。
    """
    interfaces: dict[str, dict[str, Any]] = {}
    features: dict[str, dict[str, Any]] = {}

    def iface_key(target: str) -> str:
        return f"{_component_of(target)}/{_tag_of(target, 'physics')}"

    def feat_key(target: str) -> str:
        return f"{iface_key(target)}/{_tag_of(target, 'feature')}"

    for lineno, stmt in rows:
        # 研究/求解器/几何/网格/后处理的行也形如 ``...feature('x').set(...)``，但它们不属于
        # 物理场。不排掉就会把 ``model.study('std1').feature('freq').set('plist',…)``、
        # ``model.sol('sol1').feature('st1').set('study','std1')``、
        # ``geom('geom1').feature('wp1').set('unite', true)``、
        # ``result('pg1').feature('surf1').set('expr', …)`` 统统误记成"指向未见过的物理场特征"
        # （实测踩过：真实导出 bGEtask2.m 里这类假 unknown 共 244+117+42 条）。
        if (_STUDY_OR_SOLVER_STMT.search(stmt) or _GEOM_OR_MESH_STMT.search(stmt)
                or _RESULT_STMT.search(stmt)):
            continue
        for target, args in _iter_calls(stmt, "create"):
            if ".physics" not in target and ".feature" not in target:
                continue
            values = [_matlab_value(part) for part in _split_top_level(args)]
            if not values or not isinstance(values[0], str):
                continue
            if _ends_with_tagged_call(target, "feature"):
                # ``...physics('solid').feature('load1').create(...)``：特征的子特征
                key = f"{iface_key(target)}/{values[0]}"
                features.setdefault(
                    key,
                    {
                        "tag": values[0],
                        "type": values[1] if len(values) > 1 else None,
                        "doc_name": values[2]
                        if len(values) > 2 and isinstance(values[2], str)
                        else None,
                        "properties": [],
                        "selection": None,
                        "interface_key": iface_key(target),
                    },
                )
            elif _ends_with_tagged_call(target, "physics"):
                # ``...physics('solid').create('load1','BoundaryLoad',1)``：物理场特征
                key = f"{iface_key(target)}/{values[0]}"
                features.setdefault(
                    key,
                    {
                        "tag": values[0],
                        "type": values[1] if len(values) > 1 else None,
                        "doc_name": values[2]
                        if len(values) > 2 and isinstance(values[2], str)
                        else None,
                        "properties": [],
                        "selection": None,
                        "interface_key": iface_key(target),
                    },
                )
            else:
                # ``...component('comp1').physics.create('solid','SolidMechanics','geom1')``
                key = f"{_component_of(target)}/{values[0]}"
                interfaces.setdefault(
                    key,
                    {
                        "component": _component_of(target),
                        "interface_tag": values[0],
                        "interface_type": values[1] if len(values) > 1 else None,
                        "selection": None,
                        "features": [],
                    },
                )
        for target, args in _iter_calls(stmt, "selection"):
            if _ends_with_tagged_call(target, "feature"):
                # ``...feature('load1').selection('bnd1')``：按名字指定选择集来源。
                # 名字来自导出文本，**不等于**运行时实体编号（那要由探针读）。
                key = feat_key(target)
                if key in features:
                    features[key]["selection"] = {
                        "tag": _string_arg(args),
                        "entities": _entities_from_args(args),
                    }
            elif _ends_with_tagged_call(target, "physics"):
                key = f"{_component_of(target)}/{_tag_of(target, 'physics')}"
                if key in interfaces:
                    interfaces[key]["selection"] = {
                        "tag": _string_arg(args),
                        "entities": _entities_from_args(args),
                    }
        for target, args in _iter_calls(stmt, "set"):
            # 写法 a：``...feature('load1').selection.set([4 5])``——
            # 实体编号写在链式调用的 ``set`` 里，只看 ``selection(...)`` 会全漏（实测踩过）。
            if target.endswith(".selection"):
                owner = re.sub(r"\.selection$", "", target)
                entities = _entities_from_args(args)
                if entities is None:
                    continue
                if _ends_with_tagged_call(owner, "feature"):
                    key = feat_key(owner)
                    if key in features:
                        features[key]["selection"] = {"tag": None, "entities": entities}
                elif _ends_with_tagged_call(owner, "physics"):
                    key = f"{_component_of(owner)}/{_tag_of(owner, 'physics')}"
                    if key in interfaces:
                        interfaces[key]["selection"] = {"tag": None, "entities": entities}
                continue
            owner = target
            values = [_matlab_value(part) for part in _split_top_level(args)]
            if len(values) < 2 or not isinstance(values[0], str):
                continue
            if not _ends_with_tagged_call(owner, "feature"):
                continue
            key = feat_key(owner)
            if key not in features:
                result["unknown_assignments"].append(
                    {
                        "line": lineno,
                        "block": "physics",
                        "text": stmt,
                        "reason": "属性赋值指向未见过的物理场特征（未见对应 feature.create）",
                    }
                )
                continue
            features[key]["properties"].append({"name": values[0], "value": values[1]})

    for key, item in features.items():
        parent = interfaces.get(item["interface_key"])
        if parent is not None and key not in parent["features"]:
            parent["features"].append(key)
    out: list[dict[str, Any]] = []
    for key in sorted(interfaces):
        item = interfaces[key]
        item["features"] = [
            {
                "tag": features[fk]["tag"],
                "type": features[fk]["type"],
                "doc_name": features[fk]["doc_name"],
                "properties": features[fk]["properties"],
                "selection": features[fk]["selection"],
            }
            for fk in item["features"]
            if fk in features
        ]
        out.append(item)
    # 没有父接口的特征也要报出来（否则会被静默丢弃）
    orphans = [
        features[k]
        for k in sorted(features)
        if features[k]["interface_key"] not in interfaces
    ]
    if orphans:
        result["notes"].append(
            f"{len(orphans)} 个物理场特征的父接口未在导出中出现（已收入 unknown_assignments 之外的 notes，"
            "不猜测其归属）。"
        )
        for item in orphans:
            result["unknown_assignments"].append(
                {
                    "line": None,
                    "block": "physics",
                    "text": f"feature({item['tag']}) type={item['type']}",
                    "reason": f"父接口 {item['interface_key']} 没有 physics.create 语句",
                }
            )
    return out


def _parse_study(rows: list[tuple[int, str]], result: dict[str, Any]) -> list[dict[str, Any]]:
    """解析研究（tag/label）与步骤（tag/type/属性/激活的物理场）。

    **必须喂入主函数的行**：真实 GUI 导出（``File > Save As → *.m``）把整个研究段写在
    主函数里，没有 ``model_study`` 子函数；只喂 ``blocks["study"]`` 会得到空列表（实测踩过）。

    除 ``set`` 外还收集 ``activate``：``…feature('freq').activate('acpr', true)`` 是"研究步
    激活了哪些物理场接口"，与运行时读回的 interface tags 正好可以交叉校验；只收 ``set``
    会把这类语义整段丢掉。

    失败模式：步骤属性写在未知步骤上 → 忽略该属性（研究结构本身仍保留，不猜归属）。
    """
    studies: dict[str, dict[str, Any]] = {}
    steps: dict[str, dict[str, Any]] = {}

    def ensure_step(study_tag: str, step_tag: str, step_type: Any) -> dict[str, Any]:
        key = f"{study_tag}/{step_tag}"
        entry = steps.setdefault(
            key,
            {
                "tag": step_tag,
                "type": step_type,
                "properties": [],
                "activated_physics": [],
                "study_tag": study_tag,
            },
        )
        if entry.get("type") is None and step_type is not None:
            entry["type"] = step_type
        return entry

    for lineno, stmt in rows:
        # 只处理真正挂在研究下的语句：
        #   - 必须有 ``.study(``（``model.study('std1')...``）；``model.study.create(...)``
        #     这种不带 tag 的写法要放行；
        #   - 不能含 ``.sol(``（求解器段交给 ``_parse_solvers``），否则
        #     ``sol.feature('st1').set('studystep','freq')`` 会被当成研究步骤属性。
        # 不这样限定就会把 ``geom.create('mslc1')``、``mesh.feature('ftri1')``、
        # ``sol.feature('st1')`` 都误收进来（实测踩过：凭空多出 mslc1/r1/rev1 三个假研究
        # 与 14 条假孤儿步骤）。
        if ".sol(" in stmt:
            continue
        if ".study(" not in stmt and not stmt.lstrip().startswith("model.study.create"):
            continue
        for target, args in _iter_calls(stmt, "create"):
            values = [_matlab_value(part) for part in _split_top_level(args)]
            if not values or not isinstance(values[0], str):
                continue
            if _ends_with_tagged_call(target, "study"):
                # ``...study('std1').create('stat', 'Stationary')``：首参是步骤 tag，
                # 次参才是类型（实测：把首参当类型会把 study tag 当成步骤类型）
                ensure_step(_tag_of(target, "study") or "?", values[0],
                            values[1] if len(values) > 1 else None)
            elif _ends_with_tagged_call(target, "feature"):
                # ``...study('std1').feature('f1').create('st1', 'Stationary')``：嵌套子步骤
                parent_tag = _tag_of(target, "feature") or "?"
                child_tag = values[0]
                composite = f"{parent_tag}/{child_tag}"
                entry = ensure_step(
                    _tag_of(target, "study") or "?", composite,
                    values[1] if len(values) > 1 else None,
                )
                entry.setdefault("parent", parent_tag)
            elif target.endswith(".study"):
                # ``model.study.create('std1')``：研究本身
                studies.setdefault(
                    values[0],
                    {"tag": values[0], "label": None, "steps": []},
                )
        for target, args in _iter_calls(stmt, "label"):
            if not _ends_with_tagged_call(target, "study"):
                continue
            tag = _tag_of(target, "study")
            if tag and tag in studies:
                label = _string_arg(args)
                if label is not None:
                    studies[tag]["label"] = label
        for method, bucket, payload_key in (
            ("set", "properties", "value"),
            ("activate", "activated_physics", "active"),
        ):
            for target, args in _iter_calls(stmt, method):
                if not _ends_with_tagged_call(target, "feature"):
                    continue
                study_tag = _tag_of(target, "study")
                step_tag = _tag_of(target, "feature")
                if not study_tag or not step_tag:
                    continue
                values = [_matlab_value(part) for part in _split_top_level(args)]
                if len(values) < 2 or not isinstance(values[0], str):
                    continue
                entry = ensure_step(study_tag, step_tag, None)
                if payload_key == "value":
                    entry["properties"].append({"name": values[0], "value": values[1]})
                else:
                    entry["activated_physics"].append({
                        "interface": values[0],
                        "active": values[1],
                    })
    for key in sorted(steps):
        item = steps[key]
        study = studies.get(item["study_tag"])
        if study is None:
            # 步骤的前置研究没被解析出来（导出残缺）：如实记一笔，不猜它属于谁。
            result["unknown_assignments"].append(
                {
                    "line": None,
                    "block": "study",
                    "text": f"study({item['study_tag']}).feature({item['tag']})",
                    "reason": "步骤归属的研究没有对应的 study.create 语句",
                }
            )
            continue
        # 导出是**按操作顺序**记录的：同一个属性会被 set 多次（实测 bGEtask2.m 里
        # ``plist`` 出现 12 次，是不同扫频范围的历史）。``properties`` 保留**全部历史**，
        # ``last_wins`` 给"最后一次赋值"的速查口径；两者都留着，因为只有运行时的
        # 求解结果才能判定哪一次真正生效（不得替用户挑一个当定论）。
        last_wins: dict[str, Any] = {}
        for prop in item["properties"]:
            last_wins[str(prop["name"])] = prop["value"]
        study["steps"].append(
            {
                "tag": item["tag"],
                "type": item["type"],
                "properties": item["properties"],
                "last_wins": last_wins,
                "activated_physics": item["activated_physics"],
                **({"parent": item["parent"]} if item.get("parent") else {}),
            }
        )
    return [studies[key] for key in sorted(studies)]


def _parse_results(rows: list[tuple[int, str]], result: dict[str, Any]) -> list[dict[str, Any]]:
    """解析后处理节点（``model.result('pg1')`` 及其 ``feature('surf1')``）的 tag/type/属性。

    这类语句的形状与物理场特征一模一样，混在一起会互相污染；单独收下来既能避免误报，
    又保留了"模型里定义了哪些绘图组/数据集"这一事实。

    失败模式：属性写在未见过的节点上 → 忽略该属性（已解析到的结构仍保留）。
    """
    groups: dict[str, dict[str, Any]] = {}
    features: dict[str, dict[str, Any]] = {}

    def ensure_group(tag: str) -> dict[str, Any]:
        return groups.setdefault(tag, {"tag": tag, "type": None, "features": []})

    for lineno, stmt in rows:
        if not _RESULT_STMT.search(stmt):
            continue
        for target, args in _iter_calls(stmt, "create"):
            if not (target.endswith(".result") or _ends_with_tagged_call(target, "result")):
                continue
            values = [_matlab_value(part) for part in _split_top_level(args)]
            if not values or not isinstance(values[0], str):
                continue
            if target.endswith(".result"):
                ensure_group(values[0])
            else:
                group = _tag_of(target, "result") or "?"
                key = f"{group}/{values[0]}"
                entry = ensure_group(group)
                features.setdefault(
                    key,
                    {
                        "tag": values[0],
                        "type": values[1] if len(values) > 1 else None,
                        "properties": [],
                        "group": group,
                    },
                )
                if key not in entry["features"]:
                    entry["features"].append(key)
        for target, args in _iter_calls(stmt, "set"):
            group = _tag_of(target, "result")
            feat = _tag_of(target, "feature")
            if not group or not feat:
                continue
            values = [_matlab_value(part) for part in _split_top_level(args)]
            if len(values) < 2 or not isinstance(values[0], str):
                continue
            key = f"{group}/{feat}"
            entry = features.setdefault(
                key, {"tag": feat, "type": None, "properties": [], "group": group}
            )
            entry["properties"].append({"name": values[0], "value": values[1]})
    for key, feature in sorted(features.items()):
        group = groups.get(feature["group"])
        if group is None:
            result["unknown_assignments"].append(
                {
                    "line": None,
                    "block": "results",
                    "text": f"result('{feature['group']}').feature('{feature['tag']}')",
                    "reason": "后处理特征的父绘图组没有对应的 result.create 语句",
                }
            )
            continue
        group["features"].append(
            {"tag": feature["tag"], "type": feature["type"], "properties": feature["properties"]}
        )
    return [groups[key] for key in sorted(groups)]


def _parse_solvers(rows: list[tuple[int, str]], result: dict[str, Any]) -> list[dict[str, Any]]:
    """解析求解器序列（``model.sol('sol1')...``）：序列 tag、特征 tag/type、占位名与属性。

    为什么需要它：真实导出把"研究 → 求解器"的绑定写在求解器侧
    （``model.sol('sol1').study('std1')``、``feature('st1').set('studystep','freq')``），
    这是**参数扫描/扫频**这类研究的可追溯信息；不解析它就只能靠猜。
    占位名（``v1`` 因变量、``s1`` 稳态、``t1`` 瞬态、``e1`` 特征值、``p1`` 参数…）也一并读出，
    便于交叉校验时按类型配对而不是按 tag 配对。

    失败模式：属性写在未见过的求解器/特征上 → 忽略该属性（已解析到的结构仍保留）。
    """
    solvers: dict[str, dict[str, Any]] = {}
    features: dict[str, dict[str, Any]] = {}

    def ensure_solver(tag: str) -> dict[str, Any]:
        return solvers.setdefault(
            tag, {"tag": tag, "study": None, "features": [], "study_binding_lines": []}
        )

    for lineno, stmt in rows:
        if ".sol" not in stmt:
            continue
        for target, args in _iter_calls(stmt, "create"):
            if not (target.endswith(".sol") or _ends_with_tagged_call(target, "sol")):
                continue
            values = [_matlab_value(part) for part in _split_top_level(args)]
            if not values or not isinstance(values[0], str):
                continue
            sol_tag = _tag_of(target, "sol") or values[0]
            entry = ensure_solver(sol_tag)
            if target.endswith(".sol"):
                entry["create_call"] = stmt
            else:
                key = f"{sol_tag}/{values[0]}"
                features.setdefault(
                    key,
                    {
                        "tag": values[0],
                        "type": values[1] if len(values) > 1 else None,
                        "properties": [],
                        "sol_tag": sol_tag,
                    },
                )
                if key not in entry["features"]:
                    entry["features"].append(key)
        for target, args in _iter_calls(stmt, "study"):
            sol_tag = _tag_of(target, "sol")
            if not sol_tag:
                continue
            entry = ensure_solver(sol_tag)
            study_tag = _string_arg(args)
            if study_tag is not None and entry["study"] is None:
                entry["study"] = study_tag
            entry["study_binding_lines"].append(lineno)
        for target, args in _iter_calls(stmt, "set"):
            sol_tag = _tag_of(target, "sol")
            feat_tag = _tag_of(target, "feature")
            if not sol_tag or not feat_tag:
                continue
            values = [_matlab_value(part) for part in _split_top_level(args)]
            if len(values) < 2 or not isinstance(values[0], str):
                continue
            key = f"{sol_tag}/{feat_tag}"
            entry = features.setdefault(
                key,
                {
                    "tag": feat_tag,
                    "type": None,
                    "properties": [],
                    "sol_tag": sol_tag,
                },
            )
            entry["properties"].append({"name": values[0], "value": values[1]})
            if values[0] == "study" and isinstance(values[1], str):
                ensure_solver(sol_tag)["study"] = values[1]
    out: list[dict[str, Any]] = []
    for sol_tag in sorted(solvers):
        entry = solvers[sol_tag]
        rendered = []
        for key in entry["features"]:
            feature = features.get(key)
            if feature is None:
                continue
            rendered.append(
                {
                    "tag": feature["tag"],
                    "type": feature["type"],
                    "properties": feature["properties"],
                }
            )
        entry["features"] = rendered
        out.append(entry)
    orphans = [key for key in sorted(features) if features[key]["sol_tag"] not in solvers]
    for key in orphans:
        feature = features[key]
        result["unknown_assignments"].append(
            {
                "line": None,
                "block": "solvers",
                "text": f"sol('{feature['sol_tag']}').feature('{feature['tag']}')",
                "reason": "求解器特征的父序列没有对应的 sol.create 语句",
            }
        )
    return out


# ======================================================================================
# 5. 交叉校验（只报差异）
# ======================================================================================


_UNIT_RE = re.compile(r"^\s*([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?(?:\s*[*/^]\s*[-+]?\d+(?:\.\d+)?)*)\s*(\[[^\]]*\])\s*$")


def _number_and_unit(value: Any) -> tuple[float | None, str | None]:
    """从参数表达式里取 (数值, 单位)：``"0.01[m]"`` → ``(0.01, "[m]")``。

    纯数字字面量 → ``(数值, None)``（**单位未声明**，不是「无量纲」）；
    派生表达式 → ``(None, None)``（含其它参数或运算，本函数不做代数化简）。
    """
    if isinstance(value, bool):
        return (None, None)
    if isinstance(value, (int, float)):
        return (float(value), None)
    if not isinstance(value, str):
        return (None, None)
    text = value.strip()
    try:
        return (float(text), None)
    except ValueError:
        pass
    match = _UNIT_RE.match(text)
    if match:
        try:
            return (float(match.group(1).replace(" ", "")), match.group(2))
        except ValueError:
            return (None, None)
    return (None, None)


def _normalize_expr(value: Any) -> Any:
    """表达式/属性值归一：只消空白、把整数的 ``.0`` 尾巴去掉。

    **不**改运算符、单位、枚举原文（``Pressure`` ≠ ``pressure`` ≠ ``ForceArea``）。
    归一的目的仅是消除 ``4[m]`` 与 ``4.0[m]`` 这类纯格式差异——若把它报成差异，
    真正的实质差异会被淹没。这是唯一的归一，绝不合并语义。
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return float(value)
    text = " ".join(str(value).split())
    match = re.match(r"^([-+]?\d+)\.0+(\D.*)?$", text)
    if match:
        return match.group(1) + (match.group(2) or "")
    return text


def _spec_feature_index(spec: Mapping[str, Any]) -> dict[str, Any]:
    """spec 侧特征索引：``tag:<tag>`` 与 ``type:<type>`` 两种键都建。"""
    index: dict[str, Any] = {}
    for iface in spec.get("physics") or []:
        for feature in iface.get("features") or []:
            tag, ftype = feature.get("tag"), feature.get("type")
            if tag:
                index.setdefault(f"tag:{tag}", feature)
            if ftype:
                index.setdefault(f"type:{ftype}", feature)
    return index


def _probe_feature_index(probe: Mapping[str, Any]) -> dict[str, Any]:
    """probe 侧特征索引（含命名选择集节点，它们的 tag 同样可查）。"""
    index: dict[str, Any] = {}
    for iface in probe.get("physics") or []:
        if iface.get("kind") == "named_selection":
            if iface.get("tag"):
                index.setdefault(f"tag:{iface['tag']}", iface)
            continue
        for feature in iface.get("features") or []:
            tag, ftype = feature.get("tag"), feature.get("type")
            if tag:
                index.setdefault(f"tag:{tag}", feature)
            if ftype:
                index.setdefault(f"type:{ftype}", feature)
    return index


def _probe_param_index(probe: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    rows = probe.get("parameters")
    if isinstance(rows, Mapping):
        return {str(k): {"name": str(k), "expression": v} for k, v in rows.items()}
    return {
        str(row.get("name")): dict(row)
        for row in (rows or [])
        if isinstance(row, Mapping) and row.get("name") is not None
    }


def _probe_prop_index(feature: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for prop in feature.get("properties") or []:
        if isinstance(prop, Mapping) and prop.get("name") is not None:
            out[str(prop["name"])] = prop.get("value")
    return out


def cross_check(
    spec: Mapping[str, Any] | None, probe: Mapping[str, Any] | None
) -> list[dict[str, Any]]:
    """比较静态 spec（:func:`parse_matlab_export`）与运行时 probe（:func:`probe_model`）。

    **只报差异**：不合并、不取平均、不选一个当作对的。任一侧缺失时只报告「缺哪些项」，
    绝不把缺失当成「一致」（红线 3）。差异条目::

        {"dimension": "...", "key": "...",
         "kind": "value_mismatch"|"missing_in_probe"|"missing_in_spec"|
                 "unreadable_in_probe"|"missing_side"|"spec_not_parsed",
         "spec_value": ..., "probe_value": ..., "reason": str, "evidence": str}

    比较口径：

    - 参数：按名字配对比较表达式（归一仅限空白与 ``4``/``4.0``）；名字只在某一侧出现 →
      ``missing_in_*``；表达式一致但 probe 侧求值失败 → ``unreadable_in_probe``（**不等于一致**）。
    - 物理场特征：按 tag 配对（tag 未命中时退回 type 配对），比较属性键/属性值
      （枚举原文按字符串严格比较）与选择集实体；spec 侧没有选择集 → 报 ``missing_in_spec``，
      不假定「没记就是没选」。
    - 研究步骤：按 tag 配对比较 type。
    - 命名选择集：spec 里出现的同名选择集才比对实体编号。
    - probe 的 ``readback`` 里 ``unreadable`` 项全部传播成 ``unreadable_in_probe``。

    失败模式：``spec`` 或 ``probe`` 为 ``None`` → 返回单条 ``missing_side`` 差异（不抛错，
    也不假定一致）；spec 的 ``parsed`` 为 ``False`` → 额外返回一条 ``spec_not_parsed``。
    """
    if spec is None or probe is None:
        missing = [name for name, value in (("spec", spec), ("probe", probe)) if value is None]
        return [
            {
                "dimension": "input",
                "key": ",".join(missing),
                "kind": "missing_side",
                "spec_value": None if spec is None else "<present>",
                "probe_value": None if probe is None else "<present>",
                "reason": f"缺少 {missing}：无法交叉校验；不得因此认定两侧一致。",
                "evidence": "cross_check 收到 None",
            }
        ]

    diffs: list[dict[str, Any]] = []
    if not spec.get("parsed", False):
        diffs.append(
            {
                "dimension": "input",
                "key": "spec.parsed",
                "kind": "spec_not_parsed",
                "spec_value": False,
                "probe_value": True,
                "reason": str(spec.get("reason") or "spec 未解析成功"),
                "evidence": "parse_matlab_export(...)[\"parsed\"] is False",
            }
        )

    # ---- 参数 ------------------------------------------------------------------
    probe_params = _probe_param_index(probe)
    seen: set[str] = set()
    for row in spec.get("parameters") or []:
        name = str(row.get("name"))
        seen.add(name)
        other = probe_params.get(name)
        if other is None:
            diffs.append(
                {
                    "dimension": "parameter.expression",
                    "key": name,
                    "kind": "missing_in_probe",
                    "spec_value": row.get("expression"),
                    "probe_value": None,
                    "reason": "运行时探针的参数表里没有该参数（.m 导出与运行态不一致）",
                    "evidence": f"spec parameter({name}) = {row.get('expression')!r}",
                }
            )
            continue
        if _normalize_expr(row.get("expression")) != _normalize_expr(other.get("expression")):
            # 先看是不是「同一个数、只因一侧未声明单位」——那要报成显式差异，
            # 但必须写清口径，不能当成纯格式差异吞掉（红线 3：不猜内部设置）。
            spec_num, spec_unit = _number_and_unit(row.get("expression"))
            probe_num, probe_unit = _number_and_unit(other.get("expression"))
            same_number = (
                spec_num is not None
                and probe_num is not None
                and abs(spec_num - probe_num) <= 1e-12 * max(1.0, abs(spec_num))
            )
            if same_number and spec_unit != probe_unit:
                diffs.append(
                    {
                        "dimension": "parameter.unit",
                        "key": name,
                        "kind": "unit_mismatch",
                        "spec_value": spec_unit,
                        "probe_value": probe_unit,
                        "reason": (
                            "数值相同但单位声明不同（None = 该侧未在表达式里声明单位）；"
                            "本模块不做单位换算，也不假定两侧等价。"
                        ),
                        "evidence": (
                            f"spec={row.get('expression')!r} probe={other.get('expression')!r}"
                        ),
                    }
                )
            else:
                diffs.append(
                    {
                        "dimension": "parameter.expression",
                        "key": name,
                        "kind": "value_mismatch",
                        "spec_value": row.get("expression"),
                        "probe_value": other.get("expression"),
                        "reason": "两侧的参数表达式不同（除格式归一外未做任何折算）",
                        "evidence": (
                            f"spec={row.get('expression')!r} probe={other.get('expression')!r}"
                        ),
                    }
                )
        elif other.get("value_error"):
            diffs.append(
                {
                    "dimension": "parameter.value",
                    "key": name,
                    "kind": "unreadable_in_probe",
                    "spec_value": row.get("expression"),
                    "probe_value": None,
                    "reason": f"probe 侧 param().evaluate() 失败：{other.get('value_error')}",
                    "evidence": str(other.get("value_error")),
                }
            )
    for name in sorted(set(probe_params) - seen):
        diffs.append(
            {
                "dimension": "parameter.expression",
                "key": name,
                "kind": "missing_in_spec",
                "spec_value": None,
                "probe_value": probe_params[name].get("expression"),
                "reason": "运行时参数表里有该参数，但 .m 文本里没有（导出可能不完整）",
                "evidence": f"probe parameter({name}) = {probe_params[name].get('expression')!r}",
            }
        )

    # ---- 物理场特征 -------------------------------------------------------------
    probe_index = _probe_feature_index(probe)
    matched_tags: set[str] = set()
    for iface in spec.get("physics") or []:
        for feature in iface.get("features") or []:
            tag, ftype = feature.get("tag"), feature.get("type")
            other = probe_index.get(f"tag:{tag}") if tag else None
            if other is None and ftype:
                other = probe_index.get(f"type:{ftype}")
            label = tag or ftype or "<unnamed>"
            if other is None:
                diffs.append(
                    {
                        "dimension": "physics.feature",
                        "key": label,
                        "kind": "missing_in_probe",
                        "spec_value": {"tag": tag, "type": ftype},
                        "probe_value": None,
                        "reason": "运行时 API 里找不到该物理场特征（tag 与 type 均未命中）",
                        "evidence": f"spec feature tag={tag!r} type={ftype!r}",
                    }
                )
                continue
            if other.get("tag"):
                matched_tags.add(str(other["tag"]))
            probe_tag = other.get("tag")
            if tag and probe_tag and tag != probe_tag:
                diffs.append(
                    {
                        "dimension": "physics.feature.tag",
                        "key": label,
                        "kind": "value_mismatch",
                        "spec_value": tag,
                        "probe_value": probe_tag,
                        "reason": "按 type 配对成功但 tag 不同（同一接口里可能被改名/重排）",
                        "evidence": f"spec.tag={tag!r} probe.tag={probe_tag!r}",
                    }
                )
            probe_props = _probe_prop_index(other)
            for prop in feature.get("properties") or []:
                pname = str(prop.get("name"))
                if pname not in probe_props:
                    diffs.append(
                        {
                            "dimension": "physics.feature.property",
                            "key": f"{label}.{pname}",
                            "kind": "missing_in_probe",
                            "spec_value": prop.get("value"),
                            "probe_value": None,
                            "reason": "运行时 properties() 清单里没有该属性名",
                            "evidence": f"spec set({pname!r}, {prop.get('value')!r})",
                        }
                    )
                    continue
                if _normalize_expr(prop.get("value")) != _normalize_expr(probe_props[pname]):
                    diffs.append(
                        {
                            "dimension": "physics.feature.property",
                            "key": f"{label}.{pname}",
                            "kind": "value_mismatch",
                            "spec_value": prop.get("value"),
                            "probe_value": probe_props[pname],
                            "reason": "属性值不同（枚举原文按字符串严格比较，未做同义归并）",
                            "evidence": f"spec={prop.get('value')!r} probe={probe_props[pname]!r}",
                        }
                    )
            spec_sel = (feature.get("selection") or {}).get("entities")
            probe_sel = other.get("selection")
            if spec_sel is None:
                diffs.append(
                    {
                        "dimension": "physics.feature.selection",
                        "key": label,
                        "kind": "missing_in_spec",
                        "spec_value": None,
                        "probe_value": probe_sel,
                        "reason": "spec 里没有该特征的选择集实体（无法比对，**不等于一致**）",
                        "evidence": "spec feature.selection.entities is None",
                    }
                )
            elif list(spec_sel) != list(probe_sel or []):
                diffs.append(
                    {
                        "dimension": "physics.feature.selection",
                        "key": label,
                        "kind": "value_mismatch",
                        "spec_value": list(spec_sel),
                        "probe_value": probe_sel,
                        "reason": "特征绑定的实体编号不同（几何变更后选择集静默改变是已知风险）",
                        "evidence": f"spec={list(spec_sel)} probe={probe_sel}",
                    }
                )
    for key in sorted(probe_index):
        if not key.startswith("tag:"):
            continue
        tag = key.split(":", 1)[1]
        other = probe_index[key]
        if tag in matched_tags or other.get("kind") == "named_selection":
            continue
        diffs.append(
            {
                "dimension": "physics.feature",
                "key": tag,
                "kind": "missing_in_spec",
                "spec_value": None,
                "probe_value": {"tag": other.get("tag"), "type": other.get("type")},
                "reason": "运行时存在该物理场特征，但 .m 文本里没有（导出不完整或版本差异）",
                "evidence": f"probe feature tag={other.get('tag')!r} type={other.get('type')!r}",
            }
        )

    # ---- 命名选择集（spec 里出现过的同名选择集才比对） ---------------------------
    spec_sel = {
        str(sel.get("tag")): sel
        for sel in spec.get("selections") or []
        if sel.get("tag") and sel.get("entities") is not None
    }
    for iface in probe.get("physics") or []:
        if iface.get("kind") != "named_selection" or not iface.get("tag"):
            continue
        ref = spec_sel.get(str(iface["tag"]))
        if ref is None:
            continue
        if list(ref["entities"]) != list(iface.get("selection") or []):
            diffs.append(
                {
                    "dimension": "selection.entities",
                    "key": str(iface["tag"]),
                    "kind": "value_mismatch",
                    "spec_value": list(ref["entities"]),
                    "probe_value": iface.get("selection"),
                    "reason": "同名选择集的实体编号不同",
                    "evidence": f"spec={list(ref['entities'])} probe={iface.get('selection')}",
                }
            )

    # ---- 研究步骤 ---------------------------------------------------------------
    spec_steps = {
        str(step["tag"]): step
        for study in spec.get("study") or []
        for step in study.get("steps") or []
        if step.get("tag")
    }
    probe_steps = {
        str(step["tag"]): step
        for study in probe.get("studies") or []
        for step in study.get("steps") or []
        if step.get("tag")
    }
    for tag in sorted(spec_steps):
        step = spec_steps[tag]
        other = probe_steps.get(tag)
        if other is None:
            diffs.append(
                {
                    "dimension": "study.step",
                    "key": tag,
                    "kind": "missing_in_probe",
                    "spec_value": step.get("type"),
                    "probe_value": None,
                    "reason": "运行时研究里没有该步骤 tag",
                    "evidence": f"spec step({tag}) type={step.get('type')!r}",
                }
            )
            continue
        if _normalize_expr(step.get("type")) != _normalize_expr(other.get("type")):
            diffs.append(
                {
                    "dimension": "study.step.type",
                    "key": tag,
                    "kind": "value_mismatch",
                    "spec_value": step.get("type"),
                    "probe_value": other.get("type"),
                    "reason": "研究步骤类型不同",
                    "evidence": f"spec={step.get('type')!r} probe={other.get('type')!r}",
                }
            )
    for tag in sorted(set(probe_steps) - set(spec_steps)):
        diffs.append(
            {
                "dimension": "study.step",
                "key": tag,
                "kind": "missing_in_spec",
                "spec_value": None,
                "probe_value": probe_steps[tag].get("type"),
                "reason": "运行时研究里有该步骤，但 .m 文本里没有",
                "evidence": f"probe step({tag}) type={probe_steps[tag].get('type')!r}",
            }
        )

    # ---- 枚举合法性：两侧都按本地权威 schema 校验 -------------------------------
    # 这条是「防止 set("forceType","Pressure") 被静默吞掉」的检查：非法枚举值必须报出来，
    # 不能因为"文本与运行态一致"就当成通过（文本与运行态可能一起错）。
    diffs.extend(_enum_validation_diffs(spec, probe))

    # ---- 运行时读不到的项必须显式传播 -------------------------------------------
    for item in probe.get("readback") or []:
        if isinstance(item, Mapping) and item.get("level") == "unreadable":
            diffs.append(
                {
                    "dimension": "probe.readback",
                    "key": str(item.get("item")),
                    "kind": "unreadable_in_probe",
                    "spec_value": None,
                    "probe_value": None,
                    "reason": str(item.get("reason")),
                    "evidence": str(item.get("source")),
                }
            )
    return diffs


def _enum_validation_diffs(
    spec: Mapping[str, Any], probe: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """把两侧的枚举校验结果转成差异条目（合法/未校验的不报，非法与待确认的必报）。

    失败模式：schema 不可用 → 返回**一条** ``enum_validation_unavailable`` 差异
    （把"没校验"显式暴露，而不是静默没有差异）；没有任何可校验项 → 同样返回一条
    ``enum_validation_no_targets`` 提示，避免"零差异"被误读成"全都合法"。
    """
    diffs: list[dict[str, Any]] = []
    reports: list[tuple[str, Mapping[str, Any] | None]] = [
        ("spec", spec.get("enum_validation")),
        ("probe", probe.get("enum_validation")),
    ]
    any_report = False
    for side, report in reports:
        if not isinstance(report, Mapping):
            diffs.append(
                {
                    "dimension": "enum.validation",
                    "key": side,
                    "kind": "enum_validation_missing",
                    "spec_value": None,
                    "probe_value": None,
                    "reason": (
                        f"{side} 侧没有枚举校验结果：该侧的枚举赋值**未校验**"
                        "（调用 parse_matlab_export(validate_enums=True) 或让探针带上 schema）"
                    ),
                    "evidence": f"{side}.enum_validation is None",
                }
            )
            continue
        any_report = True
        if not report.get("available"):
            diffs.append(
                {
                    "dimension": "enum.validation",
                    "key": side,
                    "kind": "enum_validation_unavailable",
                    "spec_value": None,
                    "probe_value": None,
                    "reason": (
                        f"{side} 侧本地权威 schema 不可用，枚举合法性**未校验**："
                        f"{report.get('error')}"
                    ),
                    "evidence": json.dumps(report.get("schema") or {}, ensure_ascii=False)[:600],
                }
            )
            continue
        for bad in report.get("illegal") or []:
            diffs.append(
                {
                    "dimension": "enum.illegal",
                    "key": f"{bad.get('feature_tag')}.{bad.get('property')}",
                    "kind": "illegal_enum_value",
                    "spec_value": bad.get("value") if side == "spec" else None,
                    "probe_value": bad.get("value") if side == "probe" else None,
                    "reason": (
                        f"[{side}] {bad.get('reason')}"
                        "；非法枚举值会让 set() 抛异常/停在默认值，最终结果可能静默错误"
                    ),
                    "evidence": (
                        f"{side} feature_type={bad.get('feature_type')!r} "
                        f"tag={bad.get('feature_tag')!r} {bad.get('property')}={bad.get('value')!r} "
                        f"legal={bad.get('legal_values')}"
                    ),
                }
            )
        for risky in report.get("variant_dependent") or []:
            diffs.append(
                {
                    "dimension": "enum.variant_dependent",
                    "key": f"{risky.get('feature_tag')}.{risky.get('property')}",
                    "kind": "variant_dependent_enum_value",
                    "spec_value": risky.get("value") if side == "spec" else None,
                    "probe_value": risky.get("value") if side == "probe" else None,
                    "reason": (
                        f"[{side}] {risky.get('reason')}；"
                        "这不是错误，但必须人工确认命中的变体后才能采信"
                    ),
                    "evidence": (
                        f"{side} {risky.get('property')}={risky.get('value')!r} "
                        f"legal_union={risky.get('legal_values')}"
                    ),
                }
            )
        for unresolved in report.get("unresolved") or []:
            diffs.append(
                {
                    "dimension": "enum.unresolved",
                    "key": f"{unresolved.get('feature_tag')}.{unresolved.get('property')}",
                    "kind": "enum_not_checked",
                    "spec_value": unresolved.get("value") if side == "spec" else None,
                    "probe_value": unresolved.get("value") if side == "probe" else None,
                    "reason": (
                        f"[{side}] {unresolved.get('reason')}；该项**未校验**，"
                        "不得当作合法"
                    ),
                    "evidence": (
                        f"{side} feature_type={unresolved.get('feature_type')!r} "
                        f"{unresolved.get('property')}={unresolved.get('value')!r}"
                    ),
                }
            )
    if any_report and not diffs:
        if all((r or {}).get("enum_checked", 0) == 0 for _, r in reports if isinstance(r, Mapping)):
            diffs.append(
                {
                    "dimension": "enum.validation",
                    "key": "targets",
                    "kind": "enum_validation_no_targets",
                    "spec_value": None,
                    "probe_value": None,
                    "reason": "两侧都没有可校验的枚举属性赋值：本次没有任何枚举被验证过",
                    "evidence": "enum_checked == 0",
                }
            )
    return diffs


# ======================================================================================
# 留档助手
# ======================================================================================


def save_probe(probe: Mapping[str, Any], *, name: str | None = None) -> Path:
    """把一次探针结果写到 ``work/reports/modelio/``（留档复核，不覆盖历史）。

    失败模式：``probe`` 不含 ``run_id`` → :class:`ValueError`
    （没有 run_id 的成果不得落档：红线 1）。
    """
    run_id = probe.get("run_id")
    if not run_id:
        raise ValueError("probe 结果里没有 run_id：拒绝落档（红线 1：没有证据就不出数字）")
    target_dir = default_work_root() / "reports" / "modelio"
    target_dir.mkdir(parents=True, exist_ok=True)
    label = name or str(run_id)
    path = target_dir / f"{label}.json"
    counter = 1
    while path.exists():
        counter += 1
        path = target_dir / f"{label}_{counter}.json"
    path.write_text(
        json.dumps(dict(probe), ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    return path


def store_note() -> str:
    """说明本模块与元数据库的关系（参数读写本身不进样本表）。"""
    return (
        "modelio 不直接写样本表：参数读写是模型层动作，样本必须由带 run_id 的求解经 "
        f"queue.ingest_run 入库（source_type 校验见 {store_mod.__name__}）。"
    )
