import json, urllib.request
for name, url in (("对话控制台", "http://127.0.0.1:8877/"),
                  ("静态看板",   "http://127.0.0.1:8899/")):
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            b = r.read()
        print("%-8s %s -> %s  %d bytes" % (name, url, r.status, len(b)))
    except Exception as e:
        print("%-8s %s -> FAIL %s" % (name, url, e))
with urllib.request.urlopen("http://127.0.0.1:8877/api/task/state", timeout=20) as r:
    print("chat state:", json.loads(r.read().decode("utf-8")))
with urllib.request.urlopen("http://127.0.0.1:8877/api/chat/mode", timeout=20) as r:
    print("chat mode :", json.loads(r.read().decode("utf-8")))
