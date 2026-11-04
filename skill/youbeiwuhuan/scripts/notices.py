# -*- coding: utf-8 -*-
"""校园通知抓取：学生处(静态页，纯 HTTP) + 信息门户(需登录，走真实浏览器绕过瑞数)。

纯标准库 + playwright（仅门户登录时用到）。输出 JSON：
    {"ok": true, "通知": [{"标题","日期","来源","链接"}...]}

用法：python notices.py  （默认抓最近 14 天）
"""
import gzip
import json
import re
import ssl
import sys
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

STATIC_SOURCES = [
    ("学生处·通知公告", "https://xsc.bupt.edu.cn/xgdt/tzgg.htm"),
]

PORTAL_SOURCES = [
    ("信息门户·校内通知",
     "http://my.bupt.edu.cn/list.jsp?urltype=tree.TreeTempUrl&wbtreeid=1154"),
    ("信息门户·公示公告",
     "http://my.bupt.edu.cn/list.jsp?urltype=tree.TreeTempUrl&wbtreeid=1305"),
]


def _http_get(url, timeout=25):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"})
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
        raw = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
    head = raw[:2048].decode("ascii", "ignore").lower()
    m = re.search(r'charset=["\']?([\w-]+)', head)
    for enc in ([m.group(1)] if m else []) + ["utf-8", "gb18030"]:
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", "replace")


def _strip(tag):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", tag or "")).strip()


# 博达(VSB)列表容器：只解析列表区，避免把顶部导航菜单当通知
VSB_CONTAINER = (r'class="text-list"[^>]*>\s*(?:<script[^>]*>[^<]*</script>\s*)?'
                 r'<[Uu][Ll]>(.*?)</[Uu][Ll]>')
PORTAL_CONTAINER = r'<[Uu][Ll]\s+class="newslist[^"]*"[^>]*>(.*?)</[Uu][Ll]>'


def _parse_li_list(html, base, container_pat=None):
    """通用解析：从 <li> 里取 <a href>标题</a> 与 <span class=...dat/time...>日期</span>。

    指定 container_pat 时先切出列表容器，避免抓进导航菜单。
    """
    if container_pat:
        m = re.search(container_pat, html, re.S)
        if m:
            html = m.group(1)
    items, seen = [], set()
    for m in re.finditer(r"<li[^>]*>(.*?)</li>", html, re.S):
        block = m.group(1)
        a = re.search(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block, re.S)
        if not a:
            continue
        href = a.group(1).strip()
        if href.startswith(("javascript:", "#")) or not href:
            continue
        tag = a.group(0)
        tm = re.search(r'title="([^"]+)"', tag)
        title = tm.group(1) if tm else _strip(a.group(2))
        if len(title) < 4:
            continue
        link = urllib.parse.urljoin(base, href)
        if link in seen:
            continue
        seen.add(link)
        dm = re.search(r'<span[^>]*class="[^"]*(?:dat|time)[^"]*"[^>]*>(.*?)</span>',
                       block, re.S)
        items.append({"标题": title, "链接": link,
                      "日期": _strip(dm.group(1)) if dm else ""})
    return items


def fetch_static():
    out = []
    for name, url in STATIC_SOURCES:
        try:
            html = _http_get(url)
            for it in _parse_li_list(html, url, VSB_CONTAINER):
                it["来源"] = name
                out.append(it)
        except Exception as e:
            out.append({"标题": "（%s 抓取失败：%s）" % (name, e),
                        "链接": "", "日期": "", "来源": name})
    return out


def fetch_portal(sno, pwd):
    """playwright 登录信息门户，抓两个栏目的列表。"""
    from playwright.sync_api import sync_playwright
    out = []
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=["--no-proxy-server",
                  "--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context()
        page = ctx.new_page()

        # 打开第一个栏目 → 被跳转到 CAS 登录页
        page.goto(PORTAL_SOURCES[0][1], wait_until="domcontentloaded", timeout=45000)
        page.wait_for_load_state("networkidle", timeout=45000)
        page.wait_for_timeout(8000)  # 等瑞数 JS 执行

        # JS 填值 + 提交（绕过瑞数动态隐藏导致不可见的问题）
        page.evaluate("""([s, pw]) => {
            const u = document.querySelector('input[name="username"]');
            const w = document.querySelector('input[name="password"]');
            if (u) u.value = s;
            if (w) w.value = pw;
        }""", [sno, pwd])
        page.evaluate("""() => {
            const s = document.querySelector('input[name="submit"]');
            if (s) s.click();
        }""")

        deadline = time.time() + 20
        while time.time() < deadline and "auth.bupt.edu.cn" in page.url:
            page.wait_for_timeout(500)
        page.wait_for_timeout(3000)

        for name, url in PORTAL_SOURCES:
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(2000)
                for it in _parse_li_list(page.content(), url, PORTAL_CONTAINER):
                    it["来源"] = name
                    out.append(it)
            except Exception as e:
                out.append({"标题": "（%s 抓取失败：%s）" % (name, e),
                            "链接": "", "日期": "", "来源": name})
        browser.close()
    return out


def _dedupe(items):
    seen, out = set(), []
    for it in items:
        key = it.get("链接") or (it.get("标题") + "|" + it.get("日期"))
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def main():
    cfg = {}
    p = os.path.join(BASE, "config.json")
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8-sig") as f:
                cfg = json.load(f)
        except Exception:
            pass
    a = cfg.get("账号") or {}
    sno = str(a.get("学号") or "").strip()
    pwd = str((cfg.get("教学云") or {}).get("密码") or a.get("密码") or "")

    items = fetch_static()
    if sno and pwd:
        items += fetch_portal(sno, pwd)

    items = _dedupe(items)
    items.sort(key=lambda x: x.get("日期") or "", reverse=True)

    # 日期过滤：只保留能解析出日期、且在最近 N 天内的
    days = 14
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    keep = []
    for it in items:
        d = str(it.get("日期") or "")[:10]
        if d and d >= cutoff:
            keep.append(it)
    if not keep:  # 都没日期就全保留，交给上层看
        keep = items[:30]

    print(json.dumps({"ok": True, "通知": keep}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
