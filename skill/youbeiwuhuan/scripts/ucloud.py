# -*- coding: utf-8 -*-
"""教学云平台（ucloud.bupt.edu.cn「云课堂」）作业抓取。

登录链与接口契约移植自公开的开源客户端实现（where_to_study 的 Android/桌面版，
GPL-3.0），流程：
    1. GET  CAS 登录页，取 execution 参数与会话 Cookie
    2. POST 学号 + 密码，从 302 Location 里取 ticket
    3. POST /ykt-basics/oauth/token（grant_type=third）换取 access_token + user_id
    4. GET  当前课程列表 → 逐课程 POST 取作业列表 → GET 未交汇总，合并去重

纯标准库 HTTP，无浏览器依赖。对外接口：
    fetch(cfg, force=False) -> (items, error)
        items : list[dict]  {id, 标题, 课程, 截止("YYYY-MM-DD HH:MM:SS"), 状态, 未交(bool)}
        error : None 或失败说明（供上层记录并告警）

结果缓存「刷新间隔小时」（默认 2 小时）；失败后 30 分钟内不重试，
避免频繁登录触发学校防火墙限流（HTTP 423）。
"""

import gzip
import html as html_lib
import json
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

CAS_URL = ("https://auth.bupt.edu.cn/authserver/login"
           "?service=https%3A%2F%2Fucloud.bupt.edu.cn")
API = "https://apiucloud.bupt.edu.cn"
SERVICE_ORIGIN = "https://ucloud.bupt.edu.cn"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

# 网页端内置的门户凭据（公开固定常量，非个人密码）
PORTAL_AUTH = "Basic  cG9ydGFsOnBvcnRhbF9zZWNyZXQ="

FONT = ("font-family:-apple-system,BlinkMacSystemFont,'PingFang SC',"
        "'Microsoft YaHei',sans-serif;")

CACHE = {"at": 0.0, "tried": 0.0, "items": None, "error": None}
FAIL_RETRY_SEC = 30 * 60


class CloudError(Exception):
    def __init__(self, msg, http_status=None, auth_expired=False):
        super().__init__(msg)
        self.http_status = http_status
        self.auth_expired = auth_expired


# ------------------------- HTTP 基础 -------------------------

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """不自动跟随重定向，把 302 交给上层读 Location（取 CAS 票据要用）。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _opener(follow):
    ctx = ssl.create_default_context()
    if follow:
        return urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=ctx))
    return urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=ctx), _NoRedirect())


def _request(url, method="GET", data=None, headers=None, timeout=25,
             follow=True):
    """发请求。返回 (状态码, headers, 文本)；3xx 在不跟随模式下原样返回。"""
    h = {"User-Agent": UA,
         "Accept": "application/json, text/plain, */*",
         "Accept-Language": "zh-CN,zh;q=0.9",
         "Connection": "close"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    opener = _opener(follow)
    try:
        with opener.open(req, timeout=timeout) as resp:
            raw = resp.read()
            if resp.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            return resp.status, resp.headers, raw.decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raw = b""
        try:
            raw = e.read()
        except Exception:
            pass
        if not follow and 300 <= e.code <= 399:
            return e.code, e.headers, raw.decode("utf-8", "replace")
        raise CloudError("HTTP %s" % e.code, e.code)


def _set_cookies(headers):
    vals = headers.get_all("Set-Cookie") or []
    return "; ".join(v.split(";")[0].strip() for v in vals
                     if v.split(";")[0].strip())


def _api_headers(token):
    h = {"Accept": "application/json, text/plain, */*",
         "Authorization": PORTAL_AUTH,
         "Tenant-Id": "000000",
         "Referer": SERVICE_ORIGIN + "/"}
    if token:
        h["Blade-Auth"] = token
    return h


# ------------------------- 登录 -------------------------

_INPUT_RE = re.compile(r"<input\b[^>]*>", re.I | re.S)
_ATTR_RE = re.compile(
    r"""\b(name|value)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""", re.I | re.S)


def _parse_execution(html_text):
    for tag in _INPUT_RE.findall(html_text):
        name = value = None
        for m in _ATTR_RE.finditer(tag):
            raw = next((g for g in m.groups()[1:] if g), None)
            if raw is None:
                continue
            if m.group(1).lower() == "name":
                name = html_lib.unescape(raw)
            else:
                value = html_lib.unescape(raw)
        if name == "execution" and value:
            return value
    return None


def _ticket_from(location):
    if not location:
        return None
    try:
        u = urllib.parse.urljoin(SERVICE_ORIGIN + "/", location)
        p = urllib.parse.urlparse(u)
        if p.scheme != "https" or p.hostname != "ucloud.bupt.edu.cn":
            return None
        for field in (p.query or "").split("&"):
            k, _, v = field.partition("=")
            if urllib.parse.unquote(k) == "ticket":
                return urllib.parse.unquote(v) or None
    except ValueError:
        return None
    return None


def _login(username, password, timeout=25):
    """CAS 登录并换 access_token。返回 (token, user_id)。"""
    _, headers, page = _request(CAS_URL, headers={"Accept": "text/html"},
                                timeout=timeout)
    execution = _parse_execution(page)
    if not execution:
        raise CloudError("统一认证登录页缺少 execution 参数")
    cookies = _set_cookies(headers)
    if not cookies:
        raise CloudError("统一认证未返回会话 Cookie")

    body = urllib.parse.urlencode({
        "username": username,
        "password": password,
        "type": "username_password",
        "execution": execution,
        "_eventId": "submit",
        "submit": "LOGIN",
    }).encode("utf-8")
    _, headers, _ = _request(
        CAS_URL, method="POST", data=body, follow=False, timeout=timeout,
        headers={"Content-Type": "application/x-www-form-urlencoded",
                 "Cookie": cookies, "Referer": CAS_URL,
                 "Accept": "text/html"})
    location = headers.get("Location") or ""
    ticket = _ticket_from(location)
    if not ticket:
        raise CloudError(
            "统一认证未返回票据：账号密码可能有误，或被要求输验证码"
            "（去浏览器登录一次 ucloud.bupt.edu.cn 再等下一轮重试）")

    tbody = urllib.parse.urlencode(
        {"ticket": ticket, "grant_type": "third"}).encode("utf-8")
    _, _, text = _request(
        API + "/ykt-basics/oauth/token", method="POST", data=tbody,
        timeout=timeout,
        headers=dict(_api_headers(None),
                     **{"Content-Type": "application/x-www-form-urlencoded"}))
    try:
        root = json.loads(text)
    except ValueError:
        raise CloudError("令牌接口返回的不是有效 JSON")
    token = _text(root.get("access_token"))
    uid = _text(root.get("user_id") or root.get("userId"))
    if not token or not uid:
        raise CloudError("令牌接口未返回 access_token / user_id")
    return token, uid


# ------------------------- 数据接口 -------------------------

def _text(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return ""
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return str(int(v)) if v.is_integer() else str(v)
    return str(v).strip()


def _api_root(text, status):
    try:
        root = json.loads(text)
    except ValueError:
        raise CloudError("接口未返回有效 JSON（HTTP %s）" % status)
    code = root.get("code")
    if code is not None and _text(code) != "200":
        raise CloudError("接口业务状态 %s" % _text(code),
                         auth_expired=(_text(code) == "401"))
    return root


def _api_get(path, params, token, timeout=30):
    url = API + path + "?" + urllib.parse.urlencode(params)
    status, _, text = _request(url, headers=_api_headers(token), timeout=timeout)
    return _api_root(text, status)


def _api_post(path, obj, token, timeout=30):
    body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    status, _, text = _request(API + path, method="POST", data=body, timeout=timeout,
                               headers=dict(_api_headers(token),
                                            **{"Content-Type": "application/json"}))
    return _api_root(text, status)


_RECORD_PATHS = ["data/records", "data/data/records", "records",
                 "data/undoneList", "data/data/undoneList", "undoneList"]


def _find_records(root):
    for path in _RECORD_PATHS:
        node = root
        for part in path.split("/"):
            node = node.get(part) if isinstance(node, dict) else None
            if node is None:
                break
        if isinstance(node, list):
            return node
    return []


def _parse_deadline(s):
    s = (s or "").strip()
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _status_text(v):
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return {99: "未提交", 0: "已提交", 1: "已批改", 2: "已驳回"}.get(int(v))
    s = str(v).strip()
    return s or None


def _item_from(raw, course_override, from_undone):
    kind = raw.get("type")
    if kind is not None:
        try:
            kv = int(kind)
        except (TypeError, ValueError):
            kv = 3
        if kv not in (3, 5):
            return None
    dt = _parse_deadline(_text(raw.get("assignmentEndTime")
                               or raw.get("endTime")))
    if dt is None:
        return None
    aid = _text(raw.get("id") or raw.get("assignmentId")
                or raw.get("activityId"))
    title = _text(raw.get("assignmentTitle") or raw.get("activityName")
                  or raw.get("title"))
    if not aid or not title:
        return None
    course = (_text(raw.get("siteName") or raw.get("courseName")
                    or raw.get("siteTitle")) or (course_override or ""))
    status = _status_text(raw.get("assignmentStatus"))
    if from_undone:
        undone = status not in ("已提交", "已批改")
    else:
        undone = status in ("未提交", "已驳回")
    return {
        "id": aid,
        "标题": title,
        "课程": course,
        "截止": dt.strftime("%Y-%m-%d %H:%M:%S"),
        "状态": status,
        "未交": undone,
    }


def _merge(items):
    """合并两个来源（课程列表 / 未交汇总）里的同一条作业。

    同一作业在两个接口里的 id 与截止秒数可能不一致，所以按
    「标题 + 截止日期」聚合；双方都有课程名且不同则视为两条。
    """
    merged = {}
    result = []
    for it in items:
        key = (it["标题"], it["截止"][:10])
        cur = merged.get(key)
        if cur is None:
            merged[key] = it
            result.append(it)
            continue
        c1, c2 = cur["课程"], it["课程"]
        if c1 and c2 and c1 != c2:
            result.append(it)  # 不同课程的同名作业，保留
            continue
        if not c1 and c2:
            cur["课程"] = c2
        if not cur.get("状态") and it.get("状态"):
            cur["状态"] = it["状态"]
        cur["未交"] = cur["未交"] or it["未交"]
        if it["截止"] < cur["截止"]:
            cur["截止"] = it["截止"]  # 取更早的时刻，稳妥
    return sorted(result, key=lambda x: x["截止"])


def _fetch_all(token, uid, timeout=30):
    root = _api_get("/ykt-site/site/list/student/current",
                    {"size": "9999", "current": "1", "userId": uid,
                     "siteRoleCode": "2"}, token, timeout)
    courses = []
    for r in _find_records(root):
        cid = _text(r.get("id") or r.get("siteId") or r.get("courseId"))
        name = _text(r.get("siteName") or r.get("courseName")
                     or r.get("siteTitle") or r.get("name"))
        if cid:
            courses.append({"id": cid, "name": name})
    courses = courses[:100]

    items = []
    ok_courses = 0
    first_err = None
    for c in courses:
        body = {
            "siteId": c["id"], "userId": uid, "keyword": "",
            "chapterId": "", "nodeId": "", "current": 1, "size": 9999,
            "studentAssignmentStatus": "", "status": "",
            "sortColumn": "", "sortType": "",
        }
        try:
            root = _api_post("/ykt-site/work/student/list", body, token, timeout)
            items.extend(x for x in (_item_from(r, c["name"], False)
                                     for r in _find_records(root))
                         if x is not None)
            ok_courses += 1
        except CloudError as e:
            if e.auth_expired:
                raise
            if first_err is None:
                first_err = e
        if len(items) >= 5000:
            break
    if courses and ok_courses == 0 and first_err is not None:
        raise first_err

    try:
        root2 = _api_get("/ykt-site/site/student/undone",
                         {"userId": uid}, token, timeout)
        items.extend(x for x in (_item_from(r, None, True)
                                 for r in _find_records(root2))
                     if x is not None)
    except CloudError as e:
        if e.auth_expired:
            raise
    return _merge(items)


# ------------------------- 对外接口 -------------------------

def fetch(cfg, force=False, timeout=25):
    """拉取作业，带缓存。返回 (items 或 None, error 或 None)。"""
    c = cfg.get("教学云") or {}
    if not c.get("启用", True):
        return None, None
    now = time.time()
    ttl = max(1, int(c.get("刷新间隔小时", 2))) * 3600
    if not force and CACHE["items"] is not None and now - CACHE["at"] < ttl:
        return CACHE["items"], None
    if not force and CACHE["error"] and now - CACHE["tried"] < FAIL_RETRY_SEC:
        return CACHE["items"], CACHE["error"]

    username = str(cfg.get("账号", {}).get("学号", "")).strip()
    password = str(c.get("密码") or "").strip() or \
        str(cfg.get("账号", {}).get("密码", ""))
    if not username or not password:
        return None, "未配置学号或密码"
    CACHE["tried"] = now
    try:
        token, uid = _login(username, password, timeout)
        items = _fetch_all(token, uid, timeout=30)
        CACHE.update(at=time.time(), items=items, error=None)
        return items, None
    except CloudError as e:
        msg = str(e)
        CACHE.update(error=msg)
        return CACHE["items"], msg
    except Exception as e:  # 网络抖动等：不让它打断整轮监控
        msg = "抓取异常：%s" % e
        CACHE.update(error=msg)
        return CACHE["items"], msg


# ------------------------- 渲染 -------------------------

def _deadline_dt(it):
    try:
        return datetime.strptime(it["截止"], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _entry_li(it, prefix, color):
    when = it["截止"][5:16]  # MM-DD HH:MM
    meta = " · ".join(x for x in [it.get("课程"), it.get("状态")] if x)
    return ('<li style="margin:0 0 8px;">'
            '<span style="color:%s;font-weight:600;">【%s】</span> %s'
            '<br><span style="color:#adb5bd;font-size:12px;">'
            '%s 截止%s</span></li>'
            % (color, prefix, html_lib.escape(it["标题"]),
               when, (" · " + html_lib.escape(meta)) if meta else ""))


def build_section_html(undone_items, max_show=12):
    """早报里的「教学云作业」段。传入的应已是未交条目。"""
    if not undone_items:
        return ""
    items = sorted(undone_items, key=lambda x: x["截止"])
    now = datetime.now()
    lis = []
    for it in items[:max_show]:
        dt = _deadline_dt(it)
        if dt and dt < now:
            prefix, color = "已逾期", "#e03131"
        elif dt and (dt - now).total_seconds() < 36 * 3600:
            prefix, color = "今天/明天", "#e8590c"
        elif dt and (dt - now).days <= 3:
            prefix, color = "快到了", "#e8590c"
        else:
            prefix, color = "待交", "#1971c2"
        lis.append(_entry_li(it, prefix, color))
    more = ("<p style=\"color:#ced4da;font-size:12px;margin:6px 0 0;\">"
            "还有 %d 项未列出（按截止排序）</p>" % (len(items) - max_show)
            ) if len(items) > max_show else ""
    return ('<div style="%sfont-size:15px;line-height:1.75;color:#212529;'
            'max-width:680px;border-bottom:1px dashed #dee2e6;'
            'padding-bottom:12px;margin-bottom:12px;">'
            '<p style="font-size:17px;font-weight:600;margin:0 0 8px;">'
            '&#128218; 教学云作业 · 未交 %d 项</p>'
            '<ul style="padding-left:20px;margin:0;">%s</ul>%s'
            '<p style="color:#ced4da;font-size:12px;margin:10px 0 0;">'
            '数据来自教学云平台自动抓取 · 提交入口 '
            'https://ucloud.bupt.edu.cn</p></div>'
            % (FONT, len(items), "".join(lis), more))


def build_new_html(new_items):
    """新作业即时推送。"""
    lis = [_entry_li(it, "新", "#2f9e44") for it in new_items[:20]]
    return ('<div style="%sfont-size:15px;line-height:1.75;color:#212529;">'
            '<p style="font-size:17px;font-weight:600;margin:0 0 8px;">'
            '&#128218; 教学云新作业 %d 项</p>'
            '<ul style="padding-left:20px;margin:0;">%s</ul>'
            '<p style="color:#ced4da;font-size:12px;margin:10px 0 0;">'
            '去教学云看看：https://ucloud.bupt.edu.cn</p></div>'
            % (FONT, len(new_items), "".join(lis)))


def build_evening_html(due_items):
    """晚提醒：今天到期 / 已逾期的未交作业。"""
    if not due_items:
        return ""
    lis = []
    for it in sorted(due_items, key=lambda x: x["截止"]):
        dt = _deadline_dt(it)
        if dt and dt < datetime.now():
            prefix, color = "已逾期", "#e03131"
        else:
            prefix, color = "今天到期", "#e8590c"
        lis.append(_entry_li(it, prefix, color))
    return ('<div style="%sfont-size:15px;line-height:1.75;color:#212529;">'
            '<p style="font-size:17px;font-weight:600;margin:0 0 8px;">'
            '&#128218; 作业还没交</p>'
            '<ul style="padding-left:20px;margin:0;">%s</ul>'
            '<p style="color:#ced4da;font-size:12px;margin:10px 0 0;">'
            '提交入口 https://ucloud.bupt.edu.cn</p></div>'
            % (FONT, "".join(lis)))


if __name__ == "__main__":
    import os
    base = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(base, "config.json"), "r",
              encoding="utf-8-sig") as f:
        _cfg = json.load(f)
    _items, _err = fetch(_cfg, force=True)
    print("error:", _err)
    if _items is not None:
        print("共 %d 项作业，未交 %d 项"
              % (len(_items), sum(1 for x in _items if x["未交"])))
        for _it in _items[:40]:
            print("  %s  [%s]  %s · %s"
                  % (_it["截止"], "未交" if _it["未交"] else (_it["状态"] or "?"),
                     _it["课程"], _it["标题"]))