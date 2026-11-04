# -*- coding: utf-8 -*-
"""今日总览：课表 + 未交作业 + 今日日程，一把输出。

dsh 里问「我今天的安排 / 今天要干嘛」就调它，把 JSON 变成人话：
结论先行，按 课表 → 作业 → 日程 依次说，没有就说没有。
"""
import json
import os
import subprocess
import sys
from datetime import date

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(BASE, "scripts")


def _run(script, *args):
    try:
        proc = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, script)] + list(args),
            capture_output=True, timeout=120)
        out = proc.stdout.decode("utf-8", "replace").strip()
        return json.loads(out) if out else {}
    except Exception as e:
        return {"错误": str(e)}


def main():
    result = {"日期": date.today().isoformat()}

    # 1) 今日课表
    result["课表"] = _run("courses.py")

    # 2) 未交作业（fetch_undone 自带缓存凭证，失效才弹窗重登）
    result["作业"] = _run("fetch_undone.py")

    # 3) 今日日程（含健身/比赛/学习等分类）
    result["日程"] = _run("schedule.py", "today")

    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
