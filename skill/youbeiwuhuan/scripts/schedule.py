# -*- coding: utf-8 -*-
"""日程管理：本地 schedule.json 的增删查，供小管家通过自然语言读写日程。

用法：
    python schedule.py list                列出全部日程（按时间排序）
    python schedule.py today               只看今天（含今天到期的）
    python schedule.py add "事项" "2026-11-05 15:00" [备注]
    python schedule.py done <id>           标记完成
    python schedule.py del <id>            删除

时间格式：YYYY-MM-DD 或 YYYY-MM-DD HH:MM。相对时间（今天/明天/后天）交给上层
自然语言理解转成标准格式再传进来，本脚本只认标准格式，保证可复现。
"""
import json
import os
import sys
import uuid
from datetime import datetime, date

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "schedule.json")


def load():
    if not os.path.exists(DATA):
        return []
    try:
        with open(DATA, "r", encoding="utf-8-sig") as f:
            d = json.load(f)
        return d.get("日程") or []
    except Exception:
        return []


def save(items):
    with open(DATA, "w", encoding="utf-8") as f:
        json.dump({"日程": items}, f, ensure_ascii=False, indent=2)


def parse_time(text):
    text = str(text or "").strip()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    return None


def _fmt(it, now):
    t = parse_time(it.get("时间", ""))
    d = dict(it)
    ts = str(it.get("时间", "") or "").strip()
    if len(ts) == 10:  # 只写了日期、没写时刻：当天不算过期
        d["过期"] = bool(t is not None and t.date() < now.date())
    else:
        d["过期"] = bool(t is not None and t < now)
    d["今天"] = bool(t is not None and t.date() == now.date())
    return d


def cmd_list():
    items = load()
    now = datetime.now()
    out = [_fmt(it, now) for it in items if parse_time(it.get("时间", ""))]
    out.sort(key=lambda x: x["时间"])
    print(json.dumps({"ok": True, "日程": out}, ensure_ascii=False))
    return 0


def cmd_today():
    items = load()
    today = date.today().isoformat()
    now = datetime.now()
    out = [_fmt(it, now) for it in items
           if str(it.get("时间", ""))[:10] == today]
    out.sort(key=lambda x: x["时间"])
    print(json.dumps({"ok": True, "今天": today, "日程": out}, ensure_ascii=False))
    return 0


def cmd_add(name, when, note="", cat="其他"):
    name = str(name or "").strip()
    if not name:
        print(json.dumps({"ok": False, "错误": "事项不能为空"}, ensure_ascii=False))
        return 1
    if parse_time(when) is None:
        print(json.dumps({"ok": False,
                          "错误": "时间格式应为 YYYY-MM-DD 或 YYYY-MM-DD HH:MM，收到：%s" % when},
                         ensure_ascii=False))
        return 1
    items = load()
    it = {"id": uuid.uuid4().hex[:8], "事项": name, "时间": when,
          "备注": str(note or "").strip(), "完成": False,
          "分类": str(cat or "其他").strip()}
    items.append(it)
    save(items)
    print(json.dumps({"ok": True, "已添加": it}, ensure_ascii=False))
    return 0


def cmd_done(id):
    items = load()
    for it in items:
        if it.get("id") == id:
            it["完成"] = True
            save(items)
            print(json.dumps({"ok": True, "已标记完成": it}, ensure_ascii=False))
            return 0
    print(json.dumps({"ok": False, "错误": "没找到 id=%s" % id}, ensure_ascii=False))
    return 1


def cmd_del(id):
    items = load()
    new = [it for it in items if it.get("id") != id]
    if len(new) == len(items):
        print(json.dumps({"ok": False, "错误": "没找到 id=%s" % id}, ensure_ascii=False))
        return 1
    save(new)
    print(json.dumps({"ok": True, "已删除": id}, ensure_ascii=False))
    return 0


def main():
    args = sys.argv[1:]
    if not args:
        print(json.dumps({"ok": False, "用法": "list|today|add|done|del"},
                         ensure_ascii=False))
        return 1
    cmd = args[0]
    if cmd == "list":
        return cmd_list()
    if cmd == "today":
        return cmd_today()
    if cmd == "add":
        if len(args) < 3:
            print(json.dumps({"ok": False, "用法": "add 事项 时间 [备注] [分类]"},
                             ensure_ascii=False))
            return 1
        return cmd_add(args[1], args[2], args[3] if len(args) > 3 else "",
                       args[4] if len(args) > 4 else "其他")
    if cmd == "done":
        return cmd_done(args[1]) if len(args) > 1 else 1
    if cmd == "del":
        return cmd_del(args[1]) if len(args) > 1 else 1
    print(json.dumps({"ok": False, "未知命令": cmd}, ensure_ascii=False))
    return 1


if __name__ == "__main__":
    sys.exit(main())
