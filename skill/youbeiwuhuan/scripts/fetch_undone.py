# -*- coding: utf-8 -*-
"""邮备无患 · 未交作业抓取（纯标准库，直接复用已跑通的教学云模块）。

用法：python fetch_undone.py
输出 JSON：
  {"ok": true, "学号": "2026xxxxxx", "未交": [{"标题","课程","截止","未交"}...]}
验证码/密码错等失败时：
  {"ok": false, "错误": "..."}
"""
import json
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ucloud  # 同目录，教学云登录+作业接口（已实测可用）
import login_playwright  # 学校加瑞数反爬后的浏览器兜底


def main():
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        with open(os.path.join(base, "config.json"), "r", encoding="utf-8-sig") as f:
            cfg = json.load(f)
    except Exception:
        print(json.dumps({"ok": False, "错误": "没找到 config.json，请先配置学号和教务密码"},
                         ensure_ascii=False))
        return 1
    账号 = cfg.get("账号") or {}
    sno = str(账号.get("学号") or "").strip()
    pwd = str((cfg.get("教学云") or {}).get("密码") or 账号.get("密码") or "")
    if not sno or not pwd:
        print(json.dumps({"ok": False, "错误": "config.json 里没填学号或密码"}, ensure_ascii=False))
        return 1
    items, err = None, None
    # 1) 优先用缓存的登录凭证（不弹窗、最快）
    try:
        items, err = login_playwright.fetch_cached()
    except Exception as e:
        err = str(e)
    if err:
        # 2) 缓存失效 → 真实浏览器重新登录（弹窗一次，登录后重新缓存）
        try:
            items, err = login_playwright.fetch(sno, pwd)
        except Exception as e:
            err = str(e)
    if err:
        # 3) 兜底：纯 HTTP（万一学校反爬撤了）
        try:
            items, err = ucloud.fetch({"账号": {"学号": sno, "密码": pwd},
                                       "教学云": {"启用": True}}, force=True)
        except Exception as e:
            err = str(e)
    if err:
        print(json.dumps({"ok": False, "错误": err}, ensure_ascii=False))
        return 1
    undone = [i for i in (items or []) if i.get("未交")]
    print(json.dumps({"ok": True, "学号": sno, "未交": undone}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())