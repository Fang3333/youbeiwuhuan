# -*- coding: utf-8 -*-
"""今日总览：课表 + 未交作业 + 今日日程 + 近期截止，一把输出。

dsh 里问「我今天的安排 / 今天要干嘛」就调它，把 JSON 变成人话：
结论先行，按 课表 → 作业 → 日程 → 近期截止 依次说，没有就说没有。
"""
import json
import os
import subprocess
import sys
from datetime import date

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(BASE, "scripts")
sys.path.insert(0, SCRIPTS)
import schedule  # noqa: E402


def _run(script, *args):
    try:
        proc = subprocess.run(
            [sys.executable, os.path.join(SCRIPTS, script)] + list(args),
            capture_output=True, timeout=120)
        out = proc.stdout.decode("utf-8", "replace").strip()
        return json.loads(out) if out else {}
    except Exception as e:
        return {"错误": str(e)}


def _upcoming(limit=30):
    """所有还没完成、还没过期（未来）的任务，按截止时间从近到远，取前 N 条。

    覆盖大赛报名、网课截止、期中考试等「未来几周内」的硬截止。
    """
    items = schedule.load()
    today = date.today()
    out = []
    for it in items:
        if it.get("完成"):
            continue
        t = schedule.parse_time(it.get("时间", ""))
        if t is None:
            continue
        gap = (t.date() - today).days
        if gap < 0:  # 已过期，跳过
            continue
        d = dict(it)
        d["剩余天数"] = gap
        out.append(d)
    out.sort(key=lambda x: x["时间"])
    return out[:limit]


def main():
    result = {"日期": date.today().isoformat()}

    # 1) 今日课表
    result["课表"] = _run("courses.py")

    # 2) 未交作业（fetch_undone 自带缓存凭证，失效才弹窗重登）
    result["作业"] = _run("fetch_undone.py")

    # 3) 今日日程（含健身/比赛/学习等分类）
    result["日程"] = _run("schedule.py", "today")

    # 4) 近期截止（未来所有硬截止：大赛报名、网课、期中考试等）
    result["近期截止"] = _upcoming()

    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
