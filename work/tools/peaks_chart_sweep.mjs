// 筛选组合 × 出图能力 的**穷举自检**：对每组筛选，跑一遍 loadPeaks，
// 数一数真实渲染出的 <svg> 个数、每张图里的图元数，以及有没有抛错。
// 目的：回答「筛选之后是不是就画不出图了」——用实测，而不是读代码猜。
import fs from "node:fs";

const BASE = process.argv[2] || "http://127.0.0.1:8877";
const els = new Map();
const mk = (id) => ({
  id, innerHTML: "", textContent: "", className: "", value: "", style: {}, dataset: {},
  disabled: false, children: [], onclick: null, onchange: null, oninput: null,
  classList: { toggle() {}, add() {}, remove() {}, contains: () => false },
  appendChild(c) { this.children.push(c); return c; },
  removeChild() {}, setAttribute() {}, getAttribute: () => null,
  addEventListener(t, f) { this["on" + t] = f; },
  querySelectorAll: () => [], querySelector: () => null,
  scrollIntoView() {}, focus() {}, click() { if (this.onclick) this.onclick(); },
});
const get = (s) => { if (!els.has(s)) els.set(s, mk(s)); return els.get(s); };
globalThis.document = { querySelector: (s) => get(s), querySelectorAll: () => [],
  createElement: () => mk("_n"), getElementById: (i) => get("#" + i) };
globalThis.alert = () => {}; globalThis.confirm = () => true;
globalThis.window = globalThis; globalThis.addEventListener = () => {};
try { Object.defineProperty(globalThis, "navigator",
  { value: { clipboard: { writeText: async () => {} } }, configurable: true, writable: true }); } catch {}
try { Object.defineProperty(globalThis, "location",
  { value: { origin: BASE, href: BASE + "/", search: "", hash: "", reload() {} },
    configurable: true, writable: true }); } catch {}
const rf = globalThis.fetch;
globalThis.fetch = (p, o) => rf(BASE + p, o);

const html = fs.readFileSync("scripts/webapp_page.html", "utf8");
const js = html.match(/<script>([\s\S]*?)<\/script>/)[1];
try { await new Function("return (async () => {" + js + "})()")(); }
catch (e) { console.log("[启动抛错]", e.message); }
await new Promise((r) => setTimeout(r, 2500));

// [batch, metric, xmin, xmax, n1min, n1max, n2, 说明]
const CASES = [
  ["C", "bandwidth_Hz", "", "", "", "", "", "无筛选（默认）"],
  ["C", "bandwidth_Hz", "0.40", "0.60", "", "", "", "只筛 x 区间"],
  ["C", "bandwidth_Hz", "", "", "2", "3", "", "只筛 N1 区间"],
  ["C", "bandwidth_Hz", "", "", "", "", "8", "只筛 N2"],
  ["C", "abs_w_m", "0.55", "0.55", "", "", "", "x 取**单点**"],
  ["C", "abs_p_per_V_Pa", "", "", "1", "1", "", "N1 取**单点**"],
  ["C", "bandwidth_Hz", "0.55", "0.55", "1", "1", "7", "x/N1/N2 全取单点"],
  ["C", "bandwidth_Hz", "0.20", "0.20", "", "", "", "x=0.20（端点，多无峰）"],
  ["C", "bandwidth_Hz", "0.28", "0.30", "", "", "", "低 x（多为无峰）"],
  ["C", "Q_factor", "0.9", "1.0", "7", "7", "8", "极端角（池可能为 0）"],
  ["A", "bandwidth_Hz", "", "", "", "", "", "批 A 无筛选"],
  ["A", "abs_w_m", "0.5", "0.5", "", "", "8", "批 A 单点"],
];

console.log("用例".padEnd(24) + "SVG数  圆的点数  矩形格数  结果");
console.log("-".repeat(92));
for (const [b, m, x0, x1, n10, n11, n2, desc] of CASES) {
  get("#kBatch").value = b; get("#kMetric").value = m;
  get("#kXmin").value = x0; get("#kXmax").value = x1;
  get("#kN1min").value = n10; get("#kN1max").value = n11; get("#kN2").value = n2;
  let err = "";
  try { await get("#bPeaks").onclick(); } catch (e) { err = e.message; }
  await new Promise((r) => setTimeout(r, 900));
  const out = els.get("#peaks").innerHTML || "";
  const svgs = [...out.matchAll(/<svg[\s\S]*?<\/svg>/g)].map((x) => x[0]);
  const circles = svgs.reduce((a, s) => a + (s.match(/<circle/g) || []).length, 0);
  const rects = svgs.reduce((a, s) =>
    a + (s.match(/<rect[^>]*rx="2"/g) || []).length, 0);
  const notice = /card notice/.test(out) && svgs.length === 0;
  let verdict;
  if (err) verdict = "**抛错** " + err;
  else if (svgs.length === 0) verdict = notice ? "不出图，只给提示（预期：无数据）" : "**没有图也没提示**";
  else verdict = "出图 OK";
  console.log(desc.padEnd(24) + String(svgs.length).padEnd(7) + String(circles).padEnd(10)
    + String(rects).padEnd(10) + verdict);
}
