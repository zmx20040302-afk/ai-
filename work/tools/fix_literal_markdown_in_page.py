# -*- coding: utf-8 -*-
"""把页面里**用户可见**的字面 markdown 星号 `**x**` 改成 `<b>x</b>`。

为什么：HTML/`innerHTML` 不解析 markdown，`**绝不下发前端**` 会**原样显示星号**。
之前只在后端 note 上做了 `mdInline()`，但页面自己写的文案里还有一批漏网
（2026-09-29 由 `peaks_panel_text.mjs` 的渲染检查暴露）。

⚠️ **代码注释里的 `**` 不动**（注释不显示，且是我惯用的强调写法）。
⚠️ 必须用 `newline="\\n"` 写回：`Path.write_text` 在 Windows 上会把 `\\n` 翻成 `\\r\\n`，
   而页面一旦含 CRLF，`verify_web_services.py` 的"字节一致"检查就会永久失败（前面踩过）。
"""
import pathlib
import sys

P = pathlib.Path("scripts/webapp_page.html")

# (旧串, 新串, 说明) —— 每条都要求**恰好出现一次**，否则报错退出（不做静默部分替换）
EDITS = [
    ("（**会被拒答**：隔离角点）", "（<b>会被拒答</b>：隔离角点）", "示例按钮 L106"),
    ("（**会被拒答**：N2=6 层没有 N1=7）", "（<b>会被拒答</b>：N2=6 层没有 N1=7）", "示例按钮 L107"),
    ("拒答域内的请求**不会返回任何数字**，", "拒答域内的请求<b>不会返回任何数字</b>，", "拒答说明 L109"),
    ("一次把**三维参数网格**全算完，", "一次把<b>三维参数网格</b>全算完，", "DOE 说明 L129"),
    ("**不判定谁对**", "<b>不判定谁对</b>", "哨兵说明 L154"),
    ("页面可能**不是**从 8877 打开的", "页面可能<b>不是</b>从 8877 打开的", "诊断文案 L216"),
    ("服务端只对**回环来源**回 CORS 头", "服务端只对<b>回环来源</b>回 CORS 头", "CORS 说明 L220"),
    ("请在浏览器地址栏**直接打开** ", "请在浏览器地址栏<b>直接打开</b> ", "横幅 L252"),
    ("密钥只存在服务端，**绝不下发前端**；", "密钥只存在服务端，<b>绝不下发前端</b>；", "模式提示 L363"),
    ("+'LLM **不参与裁决**——", "+'LLM <b>不参与裁决</b>——", "模式提示 L364"),
    ("'**离线模式**：不发任何网络请求，全部本地计算。对话框**降级为本地关键词路由**，'",
     "'<b>离线模式</b>：不发任何网络请求，全部本地计算。对话框<b>降级为本地关键词路由</b>，'",
     "模式提示 L365"),
    ("（**身份由内容摘要定**，与文件字节布局无关）",
     "（<b>身份由内容摘要定</b>，与文件字节布局无关）", "任务卡 L453"),
    ("代理**不返回任何数字**，只说明为什么不适用：",
     "代理<b>不返回任何数字</b>，只说明为什么不适用：", "拒答卡 L491"),
    # 唯一一处走 esc() 的调用点：改成 mdInline（先转义再吃 markdown，既不漏星号也不引入注入）
    ("esc(peaksFilterText(fq))", "mdInline(peaksFilterText(fq))", "筛选文案调用点 L840"),
]


def main() -> int:
    t = P.read_text(encoding="utf-8")
    fail = []
    for old, new, why in EDITS:
        n = t.count(old)
        if n != 1:
            fail.append("%s：出现 %d 次（要求恰好 1 次）—— %s" % (why, n, old[:40]))
            continue
        t = t.replace(old, new)
    if fail:
        print("❌ 未做任何写入，以下条目不满足「恰好一次」：")
        for f in fail:
            print("   " + f)
        return 1
    with P.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(t)
    raw = P.read_bytes()
    print("已替换 %d 处" % len(EDITS))
    print("CRLF =", raw.count(b"\r\n"), "（必须为 0）")
    print("字节 =", len(raw),
          "｜ 原始与 read_text 重新编码一致 =", raw == P.read_text(encoding="utf-8").encode("utf-8"))
    # 复核：用户可见文本里不应再残留 markdown 星号（注释除外）
    left = []
    for i, ln in enumerate(t.splitlines(), 1):
        s = ln.strip()
        if "**" not in ln:
            continue
        if s.startswith(("/*", "//", "*", "+'/*")) or "/*" in ln[:ln.find("**")] or "//" in ln[:ln.find("**")]:
            continue
        left.append((i, s[:100]))
    print("仍含 `**` 的**非注释**行数 =", len(left))
    for i, s in left:
        print("   L%-4d %s" % (i, s))
    return 0


if __name__ == "__main__":
    sys.exit(main())
