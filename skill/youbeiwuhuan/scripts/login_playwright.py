# -*- coding: utf-8 -*-
"""用真实浏览器（Playwright）绕过瑞数反爬，登录教学云并抓作业。

学校 auth.bupt.edu.cn 登录页加了瑞数 JS 挑战（$_ts），纯 HTTP POST 会被 401。
本模块用 headful chromium 执行 JS 完成登录，并拦截前端换取 access_token 的响应，
拿到 token 后复用 ucloud._fetch_all 抓作业。

对外接口：
    fetch(sno, pwd, headless=False) -> (items 或 None, error 或 None)
"""
import sys, os, json, time
from playwright.sync_api import sync_playwright

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ucloud

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAS_URL = ("https://auth.bupt.edu.cn/authserver/login"
           "?service=https%3A%2F%2Fucloud.bupt.edu.cn")
TOKEN_CACHE = os.path.join(BASE, "token_cache.json")


def _save_token(token, uid):
    try:
        with open(TOKEN_CACHE, "w", encoding="utf-8") as f:
            json.dump({"token": token, "uid": uid,
                       "时间": time.strftime("%Y-%m-%d %H:%M:%S")},
                      f, ensure_ascii=False)
    except Exception:
        pass


def _load_token():
    try:
        with open(TOKEN_CACHE, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d.get("token"), d.get("uid")
    except Exception:
        return None, None


def fetch_cached():
    """用缓存的 access_token 直接抓作业，不弹窗、不重新登录。

    返回 (items 或 None, error 或 None)。token 失效（401）时返回 error，
    由调用方决定是否重新登录。
    """
    token, uid = _load_token()
    if not token or not uid:
        return None, "无缓存凭证"
    try:
        items = ucloud._fetch_all(token, uid)
        return items, None
    except Exception as e:
        return None, str(e)


def fetch(sno, pwd, headless=False):
    captured = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=headless,
            args=["--no-proxy-server",
                  "--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context()
        page = ctx.new_page()

        def handle(route):
            if "oauth/token" in route.request.url:
                resp = route.fetch()
                try:
                    captured["json"] = resp.text()
                except Exception:
                    pass
                route.fulfill(response=resp)
            else:
                route.continue_()

        page.route("**/*", handle)
        page.goto(CAS_URL, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_load_state("networkidle", timeout=45000)
        page.wait_for_timeout(8000)

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

        deadline = time.time() + 25
        while time.time() < deadline and "json" not in captured:
            page.wait_for_timeout(500)
        browser.close()

    if "json" not in captured:
        return None, "登录未成功（可能被反爬拦截）"
    try:
        root = json.loads(captured["json"])
    except ValueError:
        return None, "token 响应不是 JSON"
    token = ucloud._text(root.get("access_token"))
    uid = ucloud._text(root.get("user_id") or root.get("userId"))
    if not token or not uid:
        return None, "未拿到 access_token"
    _save_token(token, uid)  # 缓存凭证，下次免登录
    try:
        items = ucloud._fetch_all(token, uid)
        return items, None
    except Exception as e:
        return None, "抓作业失败：%s" % e


def main():
    cfg = json.load(open(os.path.join(BASE, "config.json"), encoding="utf-8-sig"))
    sno = cfg["账号"]["学号"]
    pwd = cfg["账号"]["密码"]
    headless = os.environ.get("PW_HEADLESS", "0") == "1"
    items, err = fetch(sno, pwd, headless=headless)
    if err:
        print("error:", err)
        return 1
    undone = [i for i in items if i.get("未交")]
    print("共 %d 项作业，未交 %d 项" % (len(items), len(undone)))
    for it in sorted(undone, key=lambda x: x["截止"]):
        print("  ", it["截止"], "|", it["课程"], "|", it["标题"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
