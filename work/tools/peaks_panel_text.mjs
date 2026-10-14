// 「一阶峰」面板的**文字渲染检查**：把面板真实渲染出的文字与图内标注打出来，
// 用来回答"这页到底看不看得懂"——不需要浏览器，也不靠读源码猜。
//
// 为什么需要它：可读性问题（`N1=1.000` 这种多余小数、`1.16e+6` 这种读不出的刻度、
// 后端 note 里的 markdown 星号漏成字面 `**不填 0**`）**只有把渲染结果打出来才看得见**。
// 直接读 JS 源码时这些都"看起来没问题"（2026-09-29 实测：这三处都是本工具抓到的）。
//
// 用法：
//   node work/tools/peaks_panel_text.mjs [baseUrl]
// 前提：服务在跑（scripts/serve_detached.ps1 -Action start）且已 restart 到最新页面。
import fs from "node:fs";

const BASE = process.argv[2] || "http://127.0.0.1:8877";
const els = new Map();
function mk(id) {
  return {
    id, innerHTML: "", textContent: "", className: "", value: "",
    style: {}, dataset: {}, disabled: false, children: [],
    onclick: null, onchange: null, oninput: null,
    classList: { toggle() {}, add() {}, remove() {}, contains() { return false; } },
    appendChild(c) { this.children.push(c); return c; },
    removeChild() {}, setAttribute() {}, getAttribute() { return null; },
    addEventListener(t, f) { this["on" + t] = f; },
    querySelectorAll() { return []; }, querySelector() { return null; },
    scrollIntoView() {}, focus() {}, click() { if (this.onclick) this.onclick(); },
  };
}
const get = (sel) => { if (!els.has(sel)) els.set(sel, mk(sel)); return els.get(sel); };
globalThis.document = {
  querySelector: (s) => get(s), querySelectorAll: () => [],
  createElement: () => mk("_new"), getElementById: (id) => get("#" + id),
};
globalThis.alert = () => {};
globalThis.confirm = () => true;
globalThis.window = globalThis;
globalThis.addEventListener = () => {};
try {
  Object.defineProperty(globalThis, "navigator", {
    value: { clipboard: { writeText: async () => {} }, userAgent: "diag" },
    configurable: true, writable: true });
} catch {}
try {
  Object.defineProperty(globalThis, "location", {
    value: { origin: BASE, href: BASE + "/", search: "", hash: "", reload() {} },
    configurable: true, writable: true });
} catch {}
const rf = globalThis.fetch;
globalThis.fetch = (p, o) => rf(BASE + p, o);

const html = fs.readFileSync("scripts/webapp_page.html", "utf8");
const js = html.match(/<script>([\s\S]*?)<\/script>/)[1];
try { await new Function("return (async () => {" + js + "})()")(); }
catch (e) { console.log("[启动抛错]", e.message); }
await new Promise((r) => setTimeout(r, 2500));

const toText = (s) => String(s)
  .replace(/<title>[\s\S]*?<\/title>/g, "")
  .replace(/<svg[\s\S]*?<\/svg>/g, "⟦图⟧")
  .replace(/<[^>]+>/g, " ")
  .replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"')
  .replace(/[ \t]+/g, " ").replace(/\n{2,}/g, "\n").trim();

// 用例：① 无筛选（必须写明"全局口径"）② 带筛选（必须写明"条件前沿"，且池确实变小）。
// 筛选语义若不出现在界面上，筛选后的结果就会被误读成全局最优——所以要逐条检查文字。
for (const [batch, metric, n2, xmin, xmax, n1max] of
     [["C", "bandwidth_Hz", "", "", "", ""],
      ["C", "bandwidth_Hz", "8", "0.4", "0.6", "3"]]) {
  get("#kBatch").value = batch; get("#kMetric").value = metric;
  get("#kN2").value = n2; get("#kXmin").value = xmin; get("#kXmax").value = xmax;
  get("#kN1min").value = ""; get("#kN1max").value = n1max;
  await get("#bPeaks").onclick();
  await new Promise((r) => setTimeout(r, 2500));
  const out = els.get("#peaks").innerHTML || "";
  const tag = (xmin || n2) ? "（带筛选）" : "（无筛选）";
  console.log("\n" + "=".repeat(96));
  console.log("批次 " + batch + " / 指标 " + metric + " " + tag + "　原始 HTML " + out.length + " 字");
  console.log("=".repeat(96));
  const text = toText(out);
  console.log(text.slice(0, 1000));
  const flag = (re) => (re.test(text) ? "有" : "**缺**");
  console.log("  [检查] 全局口径: " + flag(/全局口径|无筛选/)
    + " ｜ 已启用筛选: " + flag(/已启用筛选/)
    + " ｜ 条件前沿: " + flag(/条件前沿/)
    + " ｜ 筛选说明: " + flag(/筛选：/));
  // 图里的文字标注（轴、图例、说明）单列出来，确认刻度是工程值而不是 1.2e+7
  const svgs = [...out.matchAll(/<svg[\s\S]*?<\/svg>/g)].map((m) => m[0]);
  svgs.forEach((sv, k) => {
    const texts = [...sv.matchAll(/<text[^>]*>([\s\S]*?)<\/text>/g)]
      .map((m) => m[1].replace(/<[^>]+>/g, "").replace(/&amp;/g, "&").trim())
      .filter(Boolean);
    console.log("  --- SVG " + (k + 1) + " 的文字标注 ---");
    texts.forEach((t) => console.log("     " + t));
  });
}
