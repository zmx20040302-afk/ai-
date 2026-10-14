// 页面运行时诊断（Node，最小 DOM 桩 + 真 fetch 打到跑着的服务）。
//
// 为什么需要它：`node --check` 只能发现**语法**错误。用户在页面上"点预测没反应"这类问题
// 是**运行时**的——最常见的是 `boot()` 里某个 await 抛错，导致后面的
// `$('#bPred').onclick = predict` **根本没执行**（异步函数里异常不会打印到页面）。
// 本脚本把事件绑定**记录下来**，从而能直接回答"处理器绑上了吗"。
//
// 用法：
//   node work/tools/page_runtime_check.mjs [baseUrl] [pagePath]
import fs from "node:fs";
import path from "node:path";

const BASE = process.argv[2] || "http://127.0.0.1:8877";
const PAGE = process.argv[3] || "scripts/webapp_page.html";

const els = new Map();
function mk(id) {
  const e = {
    id, innerHTML: "", textContent: "", className: "", value: "",
    style: {}, dataset: {}, disabled: false, children: [],
    onclick: null, onchange: null, oninput: null,
    classList: { toggle() {}, add() {}, remove() {}, contains() { return false; } },
    appendChild(c) { this.children.push(c); return c; },
    removeChild() {}, setAttribute() {}, getAttribute() { return null; },
    addEventListener(t, f) { this["on" + t] = f; },
    querySelectorAll() { return []; },
    querySelector() { return null; },
    scrollIntoView() {}, focus() {}, click() { if (this.onclick) this.onclick(); },
  };
  // `<select>` 在真浏览器里**永远**有 `options`（HTMLSelectElement.options）。
  // 桩里漏了它 ⇒ 页面里 `sel.options.length` 抛 `Cannot read properties of
  // undefined (reading 'length')`，被报成"数据字典面板坏了"，其实坏的是桩
  // （2026-09-30 实测：node 报的列号正好落在 `length` 上，才定位到是桩缺字段）。
  // 这里按 innerHTML 里的 `<option` 个数**动态**算，好让"第二次点不再重复填"这类
  // 幂等逻辑也真的被走到。
  Object.defineProperty(e, "options", {
    configurable: true,
    get() { return { length: (String(this.innerHTML).match(/<option/g) || []).length }; },
  });
  return e;
}
const get = (sel) => { if (!els.has(sel)) els.set(sel, mk(sel)); return els.get(sel); };

const docListeners = [];
globalThis.document = {
  querySelector: (s) => get(s),
  querySelectorAll: () => [],
  createElement: () => mk("_new"),
  getElementById: (id) => get("#" + id),
  // ⚠️ 桩里漏了 `document.addEventListener` ⇒ 页面里 `document.addEventListener('keydown',…)`
  // 抛 TypeError，**把 bindAll 后面所有按钮的绑定全带走**（实测：bMcCard/bMcScreen/
  // bAgents/bAgBuild 四个按钮变"未绑定"）。真浏览器里有这个 API，所以是**桩不全**造成的
  // 假失败——本文件里同类假失败已经是第三次（前两次：缺 window/location、缺 options）。
  addEventListener(t, f) { docListeners.push([t, typeof f, f]); },
  removeEventListener() {},
};
globalThis.alert = (m) => console.log("[alert]", m);
globalThis.confirm = () => true;
// ⚠️ 页面里有 `window.addEventListener('error'|'unhandledrejection', …)`（#errBanner 那套）
// 与 `navigator.clipboard.writeText`（复制诊断按钮）。**桩里不给这两个全局**时，
// eval 会以 `ReferenceError: window is not defined` 在最顶层就炸，
// 于是所有 onclick 都"未绑定"——报出来的假象是"页面坏了"，其实坏的是本诊断脚本
// （2026-09-29 实测：该脚本自加上全局错误捕获后就一直误报 FAIL）。
const winListeners = [];
globalThis.window = globalThis;
globalThis.addEventListener = (t, f) => { winListeners.push([t, typeof f, f]); };
// Node ≥21 自带只读的 `navigator`（getter-only）⇒ 直接赋值会 `TypeError`。
// 页面用的是 `navigator.clipboard && …` 守卫式调用，缺失也能跑，故只在能定义时才注入。
try {
  Object.defineProperty(globalThis, "navigator", {
    value: { clipboard: { writeText: async () => {} }, userAgent: "node-diag" },
    configurable: true, writable: true,
  });
} catch { /* 用 Node 自带 navigator 亦可：页面对 clipboard 有存在性守卫 */ }
// 页面用 `location.origin` 做**多源回退**（`detectApiBase`）。桩里必须给，否则
// `connect()` 一开始就抛 `ReferenceError: location is not defined`，
// 首页各面板全空 —— 看起来像"页面坏了"，实际是桩不全。
// 令 origin === BASE 很关键：这样首个候选就是"同源"，`detectApiBase` 返回相对 base，
// 后面所有请求才会走下面那个 `BASE + p` 的 fetch 转发（绝对 URL 会拼成畸形串）。
try {
  Object.defineProperty(globalThis, "location", {
    // `search` 设成诊断标记：本探针会**故意**打出域外拒答，若不加这个标记，
    // 每跑一次探针就会往失败通道台账里塞一条 refusal（生产台账被机器噪音稀释）。
    value: { origin: BASE, href: BASE + "/", pathname: "/", search: "?no_incident=1",
             hash: "", reload() {} },
    configurable: true, writable: true,
  });
} catch { /* 若 Node 已定义只读 location，则沿用 */ }
const realFetch = globalThis.fetch;
globalThis.fetch = (p, o) => realFetch(BASE + p, o);

const problems = [];
process.on("unhandledRejection", (e) => problems.push("unhandledRejection: " + (e && e.stack || e)));
process.on("uncaughtException", (e) => problems.push("uncaughtException: " + (e && e.stack || e)));

const html = fs.readFileSync(PAGE, "utf8");
const m = html.match(/<script>([\s\S]*?)<\/script>/);
if (!m) { console.log("[FAIL] 页面里找不到 <script> 块"); process.exit(2); }
const js = m[1];

const t0 = Date.now();
try {
  // 顶层 await 需要 async 包裹；用间接 eval 保留全局作用域语义
  const runner = new Function("return (async () => {" + js + "})()");
  await runner();
} catch (e) {
  problems.push("同步/顶层抛错: " + (e && e.stack || e));
}
// 等 boot() 里的若干 await 落地
await new Promise((r) => setTimeout(r, 2500));

const ids = ["#pMode", "#pStat", "#pMid", "#modeNotice", "#tasks", "#card", "#pred", "#cov",
  "#cmp", "#doe", "#sen", "#data", "#bPred", "#bCov", "#bCmp", "#bDoe", "#bSen", "#bData",
  "#bOff", "#bOn", "#bSend"];
const bound = {};
for (const id of ids) {
  const e = els.get(id);
  bound[id] = e ? { onclick: typeof e.onclick === "function", html_len: (e.innerHTML || "").length } : null;
}
console.log("=== 绑定与内容 ===");
for (const id of ids) {
  const b = bound[id];
  console.log("  " + id.padEnd(12) + (b ? ("onclick=" + (b.onclick ? "YES" : "-") + "  html=" + b.html_len) : "（未创建）"));
}
console.log("=== 启动期间的问题（" + problems.length + "）===");
for (const p of problems) console.log("  " + String(p).split("\n").slice(0, 4).join("\n  "));

// 直接调用预测处理器，看它是否真的发请求并写结果。
// ⚠️ **必须分别验两条语义**（2026-09-29 实测踩坑）：
//   ① 域内输入 → 必须产出**带 model_id/certified 的真预测**；
//   ② 域外输入 → 必须**拒答且不吐任何数字**。
// 旧版只在一组**空输入**下点按钮，前端校验正确地拒答了（"输入不在适用范围"），
// 而旧版只认「已拒答|SPL20|计算中」三种措辞 ⇒ 把**正确的 fail-closed 行为报成 FAIL**。
const pred = els.get("#bPred");
const FAIL = [];
if (pred && typeof pred.onclick === "function") {
  const cases = [
    { label: "域内（x=0.55,N1=1,N2=6,α=0.10）", vals:
      { "#px": 0.55, "#pn1": 1, "#pn2": 6, "#palpha": 0.1 },
      ok: (out) => /certified|SPL20|model_id/.test(out),
      want: "带 model_id / certified 的真预测" },
    { label: "域外（x=1.00 端点）", vals:
      { "#px": 1.0, "#pn1": 1, "#pn2": 6, "#palpha": 0.1 },
      ok: (out) => /不在适用范围|已拒答/.test(out),
      want: "拒答/范围提示" },
  ];
  for (const c of cases) {
    try {
      for (const [k, v] of Object.entries(c.vals)) get(k).value = String(v);
      await pred.onclick();
      await new Promise((r) => setTimeout(r, 1500));
      const out = els.get("#pred").innerHTML || "";
      const good = c.ok(out);
      console.log("=== 预测用例：" + c.label + " → " + (good ? "[OK]" : "[FAIL]")
        + " 期望 " + c.want + "（html " + out.length + " 字）===");
      console.log("  " + out.slice(0, 220).replace(/\n/g, " "));
      if (!good) FAIL.push(c.label);
    } catch (e) {
      console.log("=== 调用 #bPred.onclick **抛错**（" + c.label + "）===");
      console.log("  " + (e && e.stack || e));
      FAIL.push(c.label + "（抛错）");
    }
  }
  // 新增面板也必须**真的点得动**（否则"语法 OK"≠"功能可用"）。
  // 三个面板各点一次：模型卡 / 多通道预测 / 子智能体列表 / 生成载荷。
  const panelCases = [
    { btn: "#bMcCard", out: "#mc", label: "多通道模型卡",
      ok: (o) => /模型卡/.test(o) && /model_id/.test(o) && !/\*\*/.test(o) },
    { btn: "#bMc", out: "#mc", label: "多通道预测（给真参数）",
      vals: { "#mcX": 0.55, "#mcN1": 1, "#mcN2": 8 },
      ok: (o) => /正式目标/.test(o) && /区间/.test(o) && !/\*\*/.test(o) },
    { btn: "#bMcScreen", out: "#mc", label: "多通道网格筛查",
      ok: (o) => /按「/.test(o) && /可预测 \/ 拒答/.test(o)
        && /不含加权总分/.test(o) && !/\*\*/.test(o) },
    { btn: "#bAgents", out: "#agents", label: "子智能体列表",
      ok: (o) => /个角色/.test(o) && /离线/.test(o) && !/\*\*/.test(o) },
    { btn: "#bAgBuild", out: "#agOut", label: "生成载荷（离线）",
      vals: { "#agOutRoot": "work/runs/_runtime_check_agents",
              "#agLedgerPath": "work/runs/_runtime_check_agents/ledger.jsonl" },
      ok: (o) => /spawn_id/.test(o) && /不 spawn/.test(o) && !/\*\*/.test(o) },
    { btn: "#bGloss", out: "#gloss", label: "数据字典（覆盖自检 + 条目）",
      ok: (o) => /覆盖自检/.test(o) && /列名/.test(o) && /不做任何计算/.test(o)
        && !/\*\*/.test(o) },
    // 覆盖卡片只证明"头部渲染了"。条目正文在另一个容器里（`#glBody`，
    // 由 `renderGloss()` 同步写），必须单独点一次，否则"每一条都讲清楚了"没有运行时证据。
    { btn: "#bGloss", out: "#glBody", label: "数据字典（条目正文 / 别名 / 方向）",
      ok: (o) => /bandwidth_Hz/.test(o) && /表里也叫/.test(o) && /越大越好/.test(o)
        && !/\*\*/.test(o) },
    // ★ 失败弹窗必须由**真实的失败事件**触发：模拟一次页面异常（走 window 'error' →
    //   showError → 登记 → popFailure 这条真实路径），断言 `#popups` 里真的多出弹窗节点，
    //   且节点里带上报按钮。手工上报**不**弹窗（人已经选择上报了，再问一次是噪音）。
    { btn: "#bIncOpen", out: "#incList", label: "错误与上报对话框（历史列表）",
      ok: (o) => /只落本机/.test(o) && /已登记|还没有登记过/.test(o) && !/\*\*/.test(o) },
  ];
  for (const c of panelCases) {
    const b = els.get(c.btn);
    if (!b || typeof b.onclick !== "function") {
      console.log("  [FAIL] " + c.label + "：按钮未绑定（" + c.btn + "）");
      FAIL.push(c.label + "（未绑定）");
      continue;
    }
    try {
      if (c.btn === "#bAgBuild") {
        get("#agRole").value = get("#agRole").value || "a8-verification-freeze";
        get("#agTask").value = "验证沙盒：只生成载荷，不 spawn";
      }
      for (const [k, v] of Object.entries(c.vals || {})) get(k).value = String(v);
      await b.onclick();
      await new Promise((r) => setTimeout(r, 1500));
      const el = els.get(c.out);
      const out = (el && el.innerHTML) || "";
      // 动态创建的节点要看 `children`：`appendChild` 不会进 `innerHTML`（桩里也不合并）
      const kids = ((el && el.children) || []).filter((k) => k && typeof k === "object");
      const kidsHtml = kids.map((k) => k.innerHTML || "").join("");
      const kidsOk = (c.minChildren == null || kids.length >= c.minChildren)
        && (!c.childHas || c.childHas.test(kidsHtml));
      const good = c.ok(out) && kidsOk;
      console.log("=== 面板：" + c.label + " → " + (good ? "[OK]" : "[FAIL]")
        + "（html " + out.length + " 字）===");
      console.log("  " + out.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim().slice(0, 200));
      if (!good) FAIL.push(c.label);
    } catch (e) {
      console.log("=== 面板 " + c.label + " **抛错** ===");
      console.log("  " + (e && e.stack || e));
      FAIL.push(c.label + "（抛错）");
    }
  }
  // ★ 失败弹窗：直接调页面**唯一**暴露的诊断钩子 `window.__memsPop` 触发一次弹窗，
  //   断言 `#popups` 里真的多出节点、节点里带上报按钮与「不会自动上报」。
  //   为什么不走"真实异常 → 弹窗"：诊断模式下那条路被有意关掉（否则探针会写生产台账）；
  //   而"异常确实会调到 popFailure"这条**接线**由 pytest 静态断言守着。
  const pop = globalThis.window && globalThis.window.__memsPop;
  if (typeof pop !== "function") {
    console.log("=== [FAIL] 失败弹窗：页面没有暴露诊断钩子 window.__memsPop ===");
    FAIL.push("失败弹窗（无诊断钩子）");
  } else {
    try {
      pop({ incident_id: "inc-probe-popup", kind_zh: "代理拒答（超出适用范围）",
            symptom: "探针：验证失败弹窗里有没有上报按钮" });
      await new Promise((r) => setTimeout(r, 300));
      const box = els.get("#popups");
      const kids = ((box && box.children) || []).filter((k) => k && typeof k === "object");
      const kidsHtml = kids.map((k) => k.innerHTML || "").join("");
      const good = kids.length >= 1 && /上报给 DSH 分析/.test(kidsHtml)
        && /不会自动上报/.test(kidsHtml) && !/\*\*/.test(kidsHtml);
      console.log("=== 失败弹窗（自动弹出上报按钮） → " + (good ? "[OK]" : "[FAIL]")
        + "（弹窗节点 " + kids.length + " 个）===");
      console.log("  " + kidsHtml.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim().slice(0, 200));
      if (!good) FAIL.push("失败弹窗");
    } catch (e) {
      console.log("=== [FAIL] 失败弹窗：触发时抛错 ===");
      console.log("  " + (e && e.stack || e));
      FAIL.push("失败弹窗（抛错）");
    }
  }
} else {
  console.log("=== [FAIL] #bPred.onclick **没有绑定** ⇒ 点它当然没反应 ===");
  FAIL.push("未绑定");
}
console.log("耗时 %d ms；启动期问题 %d 条；用例失败 %d 个", Date.now() - t0, problems.length, FAIL.length);
process.exit(problems.length || FAIL.length ? 1 : 0);
