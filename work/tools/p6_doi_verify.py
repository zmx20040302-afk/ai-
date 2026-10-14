# -*- coding: utf-8 -*-
"""P6：参考文献 DOI 核验（走 Crossref REST，逐条给"存在/标题/年份/出处"）。

为什么要机器核验：论文引用的 DOI 一旦错，审稿人会当作**编造引用**处理。
本脚本只做**只读**核验，不修改任何稿件；核验不通过的条目**如实列出**，不猜、不替换。
产物：`work/runs/eda64-20261010/p6_paper/DOI_VERIFICATION.json`。
"""
from __future__ import annotations

import io
import json
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
REPO = pathlib.Path(__file__).resolve().parents[2]
SRC = REPO / "docs/PMUT_DAC2027_初稿_v11_20261010.md"
OUT = REPO / "work/runs/eda64-20261010/p6_paper"
UA = "mems-harness-doi-check/1.0 (offline literature audit; contact: local user)"


def refs() -> list[dict]:
    t = io.open(SRC, encoding="utf-8").read()
    i = t.find("参考文献")
    block = t[i:]
    out = []
    for m in re.finditer(r"^\[(\d+)\]\s+(.*?)(?=^\[\d+\]\s|\Z)", block, re.M | re.S):
        body = " ".join(m.group(2).split())
        doi = re.search(r"doi:\s*(10\.[^\s.]+/[^\s.]+?)\.?$", body)
        if not doi:
            doi = re.search(r"doi:\s*(10\.\S+?)\.?(?:\s|$)", body)
        out.append({"n": int(m.group(1)), "text": body,
                    "doi": (doi.group(1).rstrip(".") if doi else None)})
    return out


def crossref(doi: str) -> dict:
    url = "https://api.crossref.org/works/" + urllib.parse.quote(doi)
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            msg = json.loads(r.read().decode("utf-8"))["message"]
        return {"http": r.status, "ok": True,
                "title": (msg.get("title") or [""])[0],
                "container": (msg.get("container-title") or [""])[0],
                "year": ((msg.get("issued") or {}).get("date-parts") or [[None]])[0][0],
                "type": msg.get("type"), "doi": msg.get("DOI")}
    except urllib.error.HTTPError as e:
        return {"http": e.code, "ok": False, "error": "HTTP %s" % e.code}
    except Exception as e:  # noqa: BLE001
        return {"http": None, "ok": False, "error": "%s: %s" % (type(e).__name__, e)}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    rs = refs()
    print("解析到 %d 条参考文献" % len(rs))
    res = []
    for r in rs:
        rec = dict(r)
        if not r["doi"]:
            rec["check"] = {"ok": False, "error": "文中没有 DOI"}
        else:
            rec["check"] = crossref(r["doi"])
            time.sleep(0.4)  # 对公共 API 温和
        res.append(rec)
        c = rec["check"]
        print("[%2d] %-42s %s" % (r["n"], (r["doi"] or "(无 DOI)"),
                                  ("OK  %s | %s | %s" % (c.get("year"), c.get("type"),
                                                         (c.get("title") or "")[:70]))
                                  if c.get("ok") else "FAIL " + str(c.get("error"))))
    out = {"kind": "p6_doi_verification", "generated": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
           "source": str(SRC.relative_to(REPO)), "n_refs": len(res),
           "n_ok": sum(1 for r in res if r["check"].get("ok")), "refs": res,
           "caliber": "Crossref REST /works/{doi}；200 且返回元数据才算通过；**不通过不猜**"}
    (OUT / "DOI_VERIFICATION.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n",
                                               encoding="utf-8")
    print("== %d/%d 通过；写出 %s" % (out["n_ok"], out["n_refs"], OUT / "DOI_VERIFICATION.json"))
    return 0


if __name__ == "__main__":
    import urllib.parse  # noqa: E402  (供 crossref 使用)
    raise SystemExit(main())
