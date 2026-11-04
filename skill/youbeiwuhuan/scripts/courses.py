# -*- coding: utf-8 -*-
"""课表：调用 WTS-bupt-mcp 的 today-courses.mjs / week-courses.mjs 抓移动教务课表。

用法：
    python courses.py          今天的课
    python courses.py --week   整周课表（周一~周日）

node 与 WTS 目录优先读 config.json 的「个人课表」段，读不到就用本机默认路径。
"""
import json
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WTS_DIR = r"d:\北京邮电\AI产物\Trae\07-校园工具\WTS-bupt-mcp"
DEFAULT_NODE = r"d:\北京邮电\AI产物\Trae\07-校园工具\node\node.exe"
SCRIPT_TODAY = "today-courses.mjs"
SCRIPT_WEEK = "week-courses.mjs"


def fetch(mode="today"):
    cfg = {}
    p = os.path.join(BASE, "config.json")
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8-sig") as f:
                cfg = json.load(f)
        except Exception:
            pass
    kb = cfg.get("个人课表") or {}
    node = str(kb.get("node") or DEFAULT_NODE)
    wts = str(kb.get("wts目录") or WTS_DIR)
    script = os.path.join(wts, SCRIPT_WEEK if mode == "week" else SCRIPT_TODAY)
    if not (os.path.exists(node) and os.path.exists(script)):
        return None, "找不到课表脚本或 node.exe（见 config.json 的个人课表配置）"
    flags = 0x08000000 if os.name == "nt" else 0
    try:
        proc = subprocess.run([node, script], capture_output=True,
                              timeout=int(kb.get("超时秒", 60)), creationflags=flags)
    except Exception as e:
        return None, "课表抓取异常：%s" % e
    if proc.returncode != 0:
        return None, "课表脚本报错：" + proc.stderr.decode("utf-8", "replace")[:200]
    try:
        return json.loads(proc.stdout.decode("utf-8", "replace")), None
    except ValueError:
        return None, "课表输出不是 JSON"


def main():
    mode = "week" if "--week" in sys.argv else "today"
    data, err = fetch(mode)
    if err:
        print(json.dumps({"ok": False, "错误": err}, ensure_ascii=False))
        return 1
    key = "课表" if mode == "today" else "整周课表"
    print(json.dumps({"ok": True, key: data}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
