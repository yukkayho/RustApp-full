#!/usr/bin/env python3
"""Checkapp local API. Serves the original UI and talks to the Oxide plugin."""

from __future__ import annotations

import base64
import collections
import gzip
import hashlib
import hmac
import json
import mimetypes
import os
import re
import sqlite3
import struct
import threading
import time
import uuid
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse
from urllib.request import Request, urlopen

import features
import admin_panel
import oauth_auth
import platega_pay

mimetypes.add_type("image/webp", ".webp")
mimetypes.add_type("video/webm", ".webm")

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)
UPLOADS = DATA / "uploads"
UPLOADS.mkdir(exist_ok=True)
DB_PATH = DATA / "checkapp.db"
LOCK = threading.RLock()
REQ = threading.local()
PLACEHOLDER = "/local/image-1024.jpg?v=6&https=1"
RUSTCHECK_AVATAR = "/local/logo-avatar.png"
BUILD_ID = "2026-11-15-portable-v91"
START_TIME_FIX = """<script id="checkapp-starttime-fix">
(function(){
  if(window.__checkappStartTimeFix)return;
  window.__checkappStartTimeFix=1;
  function bad(m){return /reading ['\"]startTime['\"]|reportAllChanges/i.test(String(m||""))}
  function keep(a){var o=[];try{a=a||[];for(var i=0;i<a.length;i++){if(a[i]&&typeof a[i].startTime==="number")o.push(a[i])}}catch(e){}return o}
  try{var ce=console.error.bind(console);console.error=function(){try{for(var i=0;i<arguments.length;i++){var a=arguments[i];if(bad(a)||(a&&bad(a.message||a.stack)))return}}catch(e){}return ce.apply(console,arguments)}}catch(e){}
  window.addEventListener("error",function(ev){if(!bad((ev&&ev.message)||(ev&&ev.error&&ev.error.message)))return;try{ev.preventDefault();ev.stopImmediatePropagation()}catch(e){}},true);
  window.addEventListener("unhandledrejection",function(ev){var r=ev&&ev.reason;if(!bad((r&&r.message)||r))return;try{ev.preventDefault()}catch(e){}},true);
  function wrap(p,n){if(!p||!p[n]||p[n].__ca)return;var o=p[n];p[n]=function(){return keep(o.apply(this,arguments))};p[n].__ca=1}
  try{var L=window.PerformanceObserverEntryList&&PerformanceObserverEntryList.prototype;wrap(L,"getEntries");wrap(L,"getEntriesByType");wrap(L,"getEntriesByName");wrap(Performance.prototype,"getEntries");wrap(Performance.prototype,"getEntriesByType");wrap(Performance.prototype,"getEntriesByName")}catch(e){}
  try{var t=PerformanceObserver.prototype.takeRecords;if(t&&!t.__ca){PerformanceObserver.prototype.takeRecords=function(){return keep(t.call(this))};PerformanceObserver.prototype.takeRecords.__ca=1}}catch(e){}
})();
</script>
"""
LANDING_S3_FIX = """<script id="checkapp-landing-s3-fix">
(function(){
  if(window.__checkappLandingS3Fix)return;
  window.__checkappLandingS3Fix=1;
  var F={"landing-mt-bg-2.png":1,"landing_stats_01.webp":1,"landing_stats_02.webp":1,"landing_stats_03.webp":1,"landing_stats_05.webp":1,"stats-4.jpg":1};
  function n(u){return String(u||"").split("?")[0].split("#")[0].split("/").pop()}
  function fix(u){u=String(u||"");var k=n(u);return F[k]?(location.origin+"/local/landing/"+k):u}
  function bad(u){u=String(u||"");return !!(F[n(u)]&&/(?:s3|r2)\\.|rustapp\\.io/i.test(u))}
  function css(s){return String(s||"").replace(/url\\(\\s*(['\"]?)(.*?)\\1\\s*\\)/g,function(_,q,u){return "url("+q+(bad(u)?fix(u):u)+q+")"})}
  var R=String.prototype.replace;
  String.prototype.replace=function(){var o=R.apply(this,arguments);return (typeof o==="string"&&bad(o))?fix(o):o};
  ["backgroundImage","background","cssText"].forEach(function(p){try{var d=Object.getOwnPropertyDescriptor(CSSStyleDeclaration.prototype,p);if(!d||!d.set)return;Object.defineProperty(CSSStyleDeclaration.prototype,p,{configurable:true,enumerable:d.enumerable,get:d.get,set:function(v){d.set.call(this,css(String(v||"")))}})}catch(e){}});
  try{var S=CSSStyleDeclaration.prototype.setProperty;CSSStyleDeclaration.prototype.setProperty=function(a,b,c){if(b)b=css(String(b));return S.call(this,a,b,c)}}catch(e){}
})();
</script>
"""

_ACTIVITY_CACHE: dict = {}
_ACTIVITY_CACHE_LOCK = threading.Lock()


def _activity_cache_get(cid) -> list | None:
    cid_s = str(cid)
    pid = int(current_pid() or 0)
    now = time.time()
    hit = None
    with _ACTIVITY_CACHE_LOCK:
        hit = _ACTIVITY_CACHE.get((pid, cid_s))
        if not hit:
            for key, val in _ACTIVITY_CACHE.items():
                if key[1] == cid_s:
                    hit = val
                    break
    if not hit:
        return None
    ts, items = hit
    if now - ts > 30.0:
        return None
    return items


def _activity_cache_merge_lists(prev, extra) -> list:
    by_id = {}
    order = []
    for row in list(prev or []) + list(extra or []):
        if not isinstance(row, dict) or row.get("id") is None:
            continue
        key = str(row.get("id"))
        if key not in by_id:
            order.append(key)
        by_id[key] = row
    return [by_id[k] for k in order]


def _activity_cache_put(cid, items, merge: bool = True) -> None:
    if merge:
        items = _activity_cache_merge_lists(_activity_cache_get(cid), items)
    key = (int(current_pid() or 0), str(cid))
    with _ACTIVITY_CACHE_LOCK:
        _ACTIVITY_CACHE[key] = (time.time(), items)
        if len(_ACTIVITY_CACHE) > 48:
            oldest = sorted(_ACTIVITY_CACHE.items(), key=lambda kv: kv[1][0])[:16]
            for k, _ in oldest:
                _ACTIVITY_CACHE.pop(k, None)


def _activity_cache_drop(cid) -> None:
    cid_s = str(cid)
    with _ACTIVITY_CACHE_LOCK:
        for key in list(_ACTIVITY_CACHE.keys()):
            if key[1] == cid_s:
                _ACTIVITY_CACHE.pop(key, None)


def _activity_cache_append(cid, item) -> None:
    if not isinstance(item, dict) or item.get("id") is None:
        return
    _activity_cache_put(cid, [item], merge=True)


_CHECK_EXACT_CACHE: dict = {}
_CHECK_EXACT_LOCK = threading.Lock()


def _check_exact_cache_put(cid, view) -> None:
    try:
        key = int(cid)
    except Exception:
        return
    if not key or not isinstance(view, dict):
        return
    with _CHECK_EXACT_LOCK:
        _CHECK_EXACT_CACHE[key] = (time.time(), view)
        if len(_CHECK_EXACT_CACHE) > 32:
            oldest = sorted(_CHECK_EXACT_CACHE.items(), key=lambda kv: kv[1][0])[:8]
            for k, _ in oldest:
                _CHECK_EXACT_CACHE.pop(k, None)


def _check_exact_cache_get(cid):
    try:
        key = int(cid)
    except Exception:
        return None
    with _CHECK_EXACT_LOCK:
        hit = _CHECK_EXACT_CACHE.get(key)
    if not hit:
        return None
    ts, view = hit
    if time.time() - ts > 90.0:
        return None
    return view


_RT_LOCK = threading.Lock()
_RT_SEQ = 0
_RT_EVENTS: dict[int, collections.deque] = {}
_RT_WAIT: dict[int, threading.Event] = {}


def _rt_waiter(pid: int) -> threading.Event:
    with _RT_LOCK:
        ev = _RT_WAIT.get(pid)
        if ev is None:
            ev = threading.Event()
            _RT_WAIT[pid] = ev
        return ev


def emit_realtime(project_id, event_type: str, payload=None, server_id: int = 0) -> dict | None:
    """Project-scoped in-memory event. Never published to a global channel."""
    global _RT_SEQ
    try:
        pid = int(project_id or 0)
    except Exception:
        pid = 0
    if not pid or not event_type:
        return None
    data = payload if isinstance(payload, dict) else {}
    with _RT_LOCK:
        _RT_SEQ += 1
        evt = {
            "id": _RT_SEQ,
            "type": str(event_type),
            "projectId": pid,
            "project_id": pid,
            "serverId": int(server_id or data.get("serverId") or data.get("server_id") or 0),
            "server_id": int(server_id or data.get("serverId") or data.get("server_id") or 0),
            "checkId": data.get("checkId") or data.get("check_id") or 0,
            "check_id": data.get("checkId") or data.get("check_id") or 0,
            "ts": now_ms(),
            "payload": data,
        }
        bucket = _RT_EVENTS.setdefault(pid, collections.deque(maxlen=800))
        bucket.append(evt)
        waiter = _RT_WAIT.get(pid)
    if waiter is not None:
        waiter.set()
    print(
        "[realtime] emit", event_type,
        "project", pid,
        "check", evt.get("checkId") or "-",
        "id", evt["id"],
    )
    return evt


def realtime_since(project_id: int, since_id: int = 0) -> list:
    try:
        pid = int(project_id or 0)
    except Exception:
        pid = 0
    if not pid:
        return []
    try:
        since_id = int(since_id or 0)
    except Exception:
        since_id = 0
    with _RT_LOCK:
        bucket = list(_RT_EVENTS.get(pid) or ())
    return [evt for evt in bucket if int(evt.get("id") or 0) > since_id]


features.realtime_emit = emit_realtime


def plugin_cs_path() -> Path:
    here = Path(__file__).resolve()
    candidates = [
        here.parent / "plugin" / "RustApp.cs",
        here.parents[1] / "plugin" / "RustApp.cs",
        here.parents[2] / "plugin" / "RustApp.cs",
        # legacy names kept as a fallback so an upgrade never loses the download
        here.parent / "plugin" / "RustCheck.cs",
        here.parent / "plugin" / "Rustcheck.cs",
        here.parents[1] / "plugin" / "RustCheck.cs",
        here.parents[1] / "plugin" / "Rustcheck.cs",
        here.parents[2] / "plugin" / "RustCheck.cs",
        here.parents[2] / "plugin" / "Rustcheck.cs",
        Path(r"C:\Users\vovam\Desktop\Checkapp\plugin\RustApp.cs"),
        Path(r"C:\Users\vovam\Desktop\Checkapp\plugin\RustCheck.cs"),
        Path(r"C:\Users\vovam\Desktop\266 server\oxide\plugins\RustApp.cs"),
        Path(r"C:\Users\vovam\Desktop\266 server\oxide\plugins\RustCheck.cs"),
    ]
    for path in candidates:
        try:
            if path.is_file():
                return path
        except Exception:
            continue
    return candidates[0]


def is_plugin_download(path: str) -> bool:
    low = str(path or "").lower()
    return (
        low.endswith(".cs")
        or low.endswith("/plugin/download")
        or low.endswith("/download/plugin")
        or "checkapp.cs" in low
        or "rustapp.cs" in low
        or "rustcheck.cs" in low
    )
SKIP_PROJECT_SLUGS = {
    "client", "assets", "local", "uploads", "plugin", "api", "auth", "utils", "queue",
    "court", "players", "player", "player-message", "player-mute", "player-alert",
    "player-premium", "server", "check", "webhook", "map", "public", "sleeping-bag",
    "audit", "project", "signage", "tariff", "suggestion", "ban", "reports", "auto-kick",
    "ban-sync", "court-api", "court-commands", "court-discord", "court-integrations",
    "court-autokick", "project-stats", "home",
}


def current_pid() -> int:
    try:
        return int(getattr(REQ, "project_id", 0) or 0) or 0
    except Exception:
        return 0


def user_can_access_project(conn, row, uid: int) -> bool:
    """Owner or active staff_members row may access the project."""
    if not row:
        return False
    if not uid:
        return False
    try:
        owner = int(row["owner_user_id"] or 0)
    except Exception:
        owner = 0
    if owner and owner == uid:
        return True
    try:
        pid = int(row["id"])
    except Exception:
        return False
    if not pid:
        return False
    staff = conn.execute(
        """SELECT 1 FROM staff_members
           WHERE project_id = ? AND user_id = ? AND COALESCE(active, 1) = 1
           LIMIT 1""",
        (pid, uid),
    ).fetchone()
    return bool(staff)


def resolve_project_id(conn, referer: str = "", path: str = "", header_slug: str = "") -> int:
    candidates = []
    slug = str(header_slug or "").strip().strip("/")
    if slug:
        candidates.append(slug)
    for text in (referer, path):
        if not text:
            continue
        parsed = urlparse(text)
        parts = [p for p in parsed.path.split("/") if p]
        if parts:
            candidates.append(parts[0])
    seen = set()
    had_slug = False
    uid = 0
    try:
        uid = int(getattr(REQ, "user_id", 0) or features.request_user_id() or 0)
    except Exception:
        uid = 0

    for slug in candidates:
        key = slug.lower()
        if not slug or key in SKIP_PROJECT_SLUGS or key in seen:
            continue
        seen.add(key)
        had_slug = True
        if key.isdigit():
            row = conn.execute("SELECT * FROM project WHERE id = ?", (int(key),)).fetchone()
            if row and user_can_access_project(conn, row, uid):
                return int(row["id"])
            continue
        row = conn.execute(
            "SELECT * FROM project WHERE lower(domain) = ? OR lower(name) = ?",
            (key, key),
        ).fetchone()
        if row and user_can_access_project(conn, row, uid):
            return int(row["id"])
    # /check/123 has no project slug in the API path. Resolve from the check row
    # even when a header slug was sent and failed to match.
    check_m = re.search(r"/check/(\d+)", str(path or "") + " " + str(referer or ""))
    if check_m:
        try:
            crow = conn.execute(
                "SELECT project_id FROM checks WHERE id = ?",
                (int(check_m.group(1)),),
            ).fetchone()
            cpid = int((crow["project_id"] if crow else 0) or 0)
            if cpid:
                prow = conn.execute("SELECT * FROM project WHERE id = ?", (cpid,)).fetchone()
                if prow and user_can_access_project(conn, prow, uid):
                    return cpid
        except Exception:
            pass
    if had_slug:
        return 0
    return 0


def plugin_auth_token(headers) -> str:
    auth = headers.get("Authorization") or headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        auth = auth[7:]
    return str(
        headers.get("X-Plugin-Auth")
        or headers.get("x-plugin-auth")
        or headers.get("Secret")
        or headers.get("secret")
        or auth
        or ""
    ).strip()


def plugin_server_row(conn, headers) -> dict | None:
    token = plugin_auth_token(headers)
    if not token:
        return None
    row = conn.execute("SELECT * FROM servers WHERE token = ?", (token,)).fetchone()
    if not row:
        return None
    alias = conn.execute("SELECT value FROM settings WHERE key = ?", (f"server_alias_{int(row['id'])}",)).fetchone()
    if alias:
        row = conn.execute("SELECT * FROM servers WHERE id = ?", (int(alias["value"]),)).fetchone()
        if not row:
            return None
    if not int(row["paired"] or 0):
        conn.execute(
            "UPDATE servers SET paired = 1, connected = 1, last_seen = ? WHERE id = ?",
            (now_s(), int(row["id"])),
        )
        row = conn.execute("SELECT * FROM servers WHERE id = ?", (int(row["id"]),)).fetchone()
    return rowd(row)
PERMISSIONS = [
    "Core_ClientsEdit",
    "Court_AlertRead", "Court_AuditRead", "Court_ChatReadDirect", "Court_ChatReadPublic",
    "Court_ChatWriteGlobal", "Court_ChatWriteReply", "Court_CheckProcess", "Court_CheckRead",
    "Court_CheckStartIgnoreAfk", "Court_CheckStartIgnoreRaidBlock", "Court_CheckStartIgnoreReports",
    "Court_CustomActionsGreen", "Court_CustomActionsRed", "Court_CustomActionsYellow",
    "Court_MapRead", "Court_PlayerBan", "Court_PlayerBanDestroyBuildings", "Court_PlayerBanEditFull",
    "Court_PlayerBanEditGeneral", "Court_PlayerBanIgnoreLimit", "Court_PlayerBanIpActive",
    "Court_PlayerBanRead", "Court_PlayerBanUnban", "Court_PlayerEditComment",
    "Court_PlayerEditIgnoreReportsTime", "Court_PlayerHistoryRead", "Court_PlayerKick",
    "Court_PlayerMuteCreate", "Court_PlayerMuteDelete", "Court_PlayerMuteRead",
    "Court_PlayerReadDetails", "Court_PlayerSettingsAutoKickEdit", "Court_PlayerStatsRead",
    "Court_PlayerViewGameInfo", "Court_ReportDelete", "Court_ReportDeleteGlobal",
    "Court_ReportRead", "Court_ServerManage", "Court_ServerRead", "Court_SignageControl",
    "Court_SleepingBagRead",
]


def staff_perms_list(raw) -> list:
    """Accept a JSON list, a {Court_X: true} flag map, or a JSON string."""
    parsed = raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw or "[]")
        except Exception:
            parsed = []
    return features.normalize_staff_permissions(parsed)


def is_full_admin_perms(perms) -> bool:
    """SPA 'Administrator rights' is the full Court_* set — that staff may add other staff."""
    have_list = staff_perms_list(perms)
    if not have_list:
        return False
    have = {str(x) for x in have_list if x}
    if have & {"admin", "owner", "*", "Administrator", "Court_Admin"}:
        return True
    need = set(PERMISSIONS)
    return need.issubset(have) or len(have) >= len(need)


def slugify(text: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "", (text or "").lower())
    return (text or "checkapp")[:32]


COURT_DEFAULTS = {
    "ban_reasons": [
        "Чит",
        "Макрос",
        "Багоюз",
        "Нарушение правил (by {client_tag})",
        "Мультиаккаунт",
        "1+",
        "2+",
        "3+",
    ],
    "ban_mass_reasons": [
        "Игра с читером",
        "Тиммейт ({main_steam_id})",
        "1+",
        "2+",
        "3+",
    ],
    "check_verdicts": [
        "Чит",
        "Макрос",
        "Багоюз",
        "Покинул сервер во время проверки",
        "Игнорирование проверки",
        "Отказ от проверки",
        "По результатам проверки",
    ],
    "report_reasons": [],
    "mute_reasons": [],
    "delete_reports_after_ban": False,
    "delete_reports_after_check": False,
    "ignore_reports_after_days": 7,
    "ignore_reports_after_check": 3,
    "check_start_min_report": 0,
    "check_start_broadcast": True,
    "check_finished_clear_broadcast": True,
    "announce_reporters_after_action": True,
    "ban_broadcast": True,
    "ban_limit_enabled": False,
    "ban_limit_amount_per_interval": 5,
    "ban_limit_interval_minutes": 60,
}


def court_options(conn=None) -> dict:
    def _read(c):
        opts = dict(COURT_DEFAULTS)
        row = c.execute("SELECT value FROM settings WHERE key = ?", ("court_options",)).fetchone()
        if row:
            try:
                saved = json.loads(row["value"] or "{}")
                if isinstance(saved, dict):
                    opts.update(saved)
            except Exception:
                pass
        opts["ignore_reports_after_days"] = int(opts.get("ignore_reports_after_days") or 7)
        raw_ign = opts.get("ignore_reports_after_check")
        if isinstance(raw_ign, bool):
            opts["ignore_reports_after_check"] = 3650 if raw_ign else 0
        else:
            try:
                opts["ignore_reports_after_check"] = int(raw_ign or 0)
            except (TypeError, ValueError):
                opts["ignore_reports_after_check"] = 0
        try:
            opts["check_start_min_report"] = int(opts.get("check_start_min_report") or 0)
        except (TypeError, ValueError):
            opts["check_start_min_report"] = 0
        opts["delete_reports_after_ban"] = bool(opts.get("delete_reports_after_ban"))
        opts["delete_reports_after_check"] = bool(opts.get("delete_reports_after_check"))
        old_ban = {"Cheat", "Macros", "Abuse", "Other"}
        if set(opts.get("ban_reasons") or []) <= old_ban or not opts.get("ban_reasons"):
            opts["ban_reasons"] = list(COURT_DEFAULTS["ban_reasons"])
        if not opts.get("ban_mass_reasons") or set(opts.get("ban_mass_reasons") or []) <= {"Cheat"}:
            opts["ban_mass_reasons"] = list(COURT_DEFAULTS["ban_mass_reasons"])
        if not opts.get("check_verdicts") or set(opts.get("check_verdicts") or []) <= {"clear", "ban"}:
            opts["check_verdicts"] = list(COURT_DEFAULTS["check_verdicts"])
        return opts

    if conn is not None:
        return _read(conn)
    try:
        return db_call(_read)
    except Exception:
        return dict(COURT_DEFAULTS)


def save_court_options(conn, incoming: dict) -> dict:
    opts = court_options(conn)
    if isinstance(incoming, dict):
        skip = {"servers", "created_at", "project_id", "is_banned", "options"}
        for key, value in incoming.items():
            if key in skip:
                continue
            opts[key] = value
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        ("court_options", json.dumps(opts, ensure_ascii=False)),
    )
    return opts


def autokick_rules() -> list:
    options = features.autokick_defaults()
    return [
        {"type": name, "active": False, "options": opts, "localize": {}}
        for name, opts in options.items()
    ]


def court_api_obj() -> dict:
    routes = ["/public/checks", "/public/bans", "/public/servers"]
    return {
        "enabled": False,
        "api_enabled": False,
        "token": "",
        "api_key": "",
        "public_api_key": "",
        "routes": [],
        "api_consumers": [],
        "public_api_routes": {route: False for route in routes},
        "public_api_routes_available": routes,
    }


def project_obj(row=None) -> dict:
    if row is None:
        def _p(conn):
            pid0 = current_pid() or features.request_project_id() or 0
            if not pid0:
                return None
            return rowd(conn.execute("SELECT * FROM project WHERE id = ?", (pid0,)).fetchone())

        row = db_call(_p) or {}
    elif not isinstance(row, dict):
        row = rowd(row) or {}
    domain = row.get("domain") or "checkapp"
    name = row.get("name") or "Checkapp"
    pid = int(row.get("id") or 0)
    plan = str(row.get("plan") or "base")
    avatar = features.public_project_avatar(row.get("avatar") or "/local/image-1024.jpg?v=6", pid)
    endpoint = ""
    try:
        def _ep(conn):
            return features.project_server_endpoint(conn, pid)

        endpoint = db_call(_ep) if pid else ""
    except Exception:
        endpoint = ""
    obj = {
        "id": pid,
        "name": name,
        "tag": domain,
        "domain": domain,
        "url": domain,
        "avatar": avatar,
        "contact_url": row.get("contact_url") or "",
        "plan": plan or "base",
        "role": "owner",
        "is_owner": True,
        "owner_client_id": int(row.get("owner_user_id") or features.request_user_id() or 0),
        "is_immutable": False,
        "can_delete": True,
        "deletable": True,
        "can_remove": True,
        "steam_strict": bool(row.get("steam_strict")),
        "twofa_strict": bool(row.get("twofa_strict")),
        "require_steam": bool(row.get("steam_strict")),
        "require_2fa": bool(row.get("twofa_strict")),
        "min_deposite": 1,
        "min_deposit": 1,
        "min_replenishment": 1,
        "permissions": list(PERMISSIONS),
        "online_users": 1,
        "online": 1,
        "server_ip": endpoint,
        "server_endpoint": endpoint,
        "endpoint": endpoint,
        "address": endpoint,
        # SPA disables "Сменить тариф" when verified=true
        "verified": False,
    }
    try:
        def _bill(conn):
            meta = features.project_billing(conn, pid)
            obj["plan"] = meta.get("slug") or obj["plan"]
            obj["frozen"] = bool(meta.get("frozen"))
            obj["is_frozen"] = bool(meta.get("frozen"))
            obj["trial_ends_at"] = meta.get("trial_ends") or 0
            obj["paid_until"] = meta.get("paid_until") or 0
            obj["active_until"] = meta.get("active_until") or 0
            obj["is_trial"] = bool(meta.get("is_trial"))
            obj["trial_remaining_ms"] = int(meta.get("trial_remaining_ms") or 0)
            obj["is_paid"] = bool(meta.get("is_paid"))
            obj["plan"] = meta.get("slug") or obj.get("plan") or "base"
            obj["blocked"] = bool(meta.get("blocked"))
            obj["is_blocked"] = bool(meta.get("is_blocked"))
            obj["is_banned"] = bool(meta.get("blocked"))
            obj["banned"] = bool(meta.get("blocked"))
            obj["admin_frozen"] = bool(meta.get("admin_frozen"))
            obj["project_status"] = meta.get("project_status") or meta.get("lifecycle") or "active"
            obj["lifecycle"] = meta.get("lifecycle") or obj["project_status"]
            apply_project_membership(conn, obj, pid)
            return obj

        return db_call(_bill)
    except Exception:
        return obj


def apply_project_membership(conn, obj: dict, pid: int) -> dict:
    """Owner keeps full control. Admin staff (all Court_* perms) can add other staff."""
    if not obj or not isinstance(obj, dict):
        return obj
    uid = int(features.request_user_id() or 0)
    if not uid or not pid:
        return obj
    try:
        prow = conn.execute("SELECT owner_user_id FROM project WHERE id = ?", (pid,)).fetchone()
        owner = int((prow["owner_user_id"] if prow else 0) or 0)
    except Exception:
        owner = int(obj.get("owner_client_id") or 0)
    if owner and uid == owner:
        obj["role"] = "owner"
        obj["is_owner"] = True
        obj["is_admin"] = True
        obj["permissions"] = list(PERMISSIONS)
        return obj
    try:
        sm = conn.execute(
            """SELECT permissions, COALESCE(is_immutable, 0) AS is_immutable FROM staff_members
               WHERE project_id = ? AND user_id = ? AND COALESCE(active, 1) = 1
               LIMIT 1""",
            (pid, uid),
        ).fetchone()
    except Exception:
        sm = conn.execute(
            """SELECT permissions FROM staff_members
               WHERE project_id = ? AND user_id = ? AND COALESCE(active, 1) = 1
               LIMIT 1""",
            (pid, uid),
        ).fetchone()
    perms = []
    immutable = False
    if sm:
        perms = staff_perms_list(sm["permissions"] if sm else [])
        try:
            immutable = bool(int((sm["is_immutable"] if "is_immutable" in sm.keys() else 0) or 0))
        except Exception:
            immutable = False
        if immutable or is_full_admin_perms(perms) or features.staff_payload_is_admin(perms, immutable):
            perms = list(PERMISSIONS)
            immutable = True
        obj["permissions"] = perms
    obj["can_delete"] = False
    obj["deletable"] = False
    obj["can_remove"] = False
    if immutable or is_full_admin_perms(perms):
        # Full permissions do not transfer ownership.  The SPA uses
        # project.is_immutable as "this member has administrator rights".
        obj["role"] = "staff"
        obj["is_owner"] = False
        obj["is_admin"] = True
        obj["is_immutable"] = True
        obj["permissions"] = list(PERMISSIONS)
    else:
        obj["role"] = "staff"
        obj["is_owner"] = False
        obj["is_admin"] = False
        obj["is_immutable"] = False
    return obj


def list_projects(user_id: int = 0) -> list:
    def _all(conn):
        uid = int(user_id or features.request_user_id() or 0)
        if not uid:
            return []
        # Owned projects + projects where user is active staff
        rows = conn.execute(
            """SELECT DISTINCT p.* FROM project p
               WHERE COALESCE(p.owner_user_id, 0) = ?
                  OR p.id IN (
                    SELECT project_id FROM staff_members
                    WHERE user_id = ? AND COALESCE(active, 1) = 1
                  )
               ORDER BY p.id ASC""",
            (uid, uid),
        ).fetchall()
        out = []
        for raw in rows:
            row = rowd(raw) or {}
            obj = project_obj(row)
            try:
                owner = int(row.get("owner_user_id") or 0)
            except Exception:
                owner = 0
            if owner and owner != uid:
                obj["role"] = "staff"
                obj["is_owner"] = False
                obj["can_delete"] = False
                obj["deletable"] = False
                obj["can_remove"] = False
                sm = conn.execute(
                    """SELECT permissions FROM staff_members
                       WHERE project_id = ? AND user_id = ? AND COALESCE(active, 1) = 1
                       LIMIT 1""",
                    (int(obj["id"]), uid),
                ).fetchone()
                if sm:
                    perms = staff_perms_list(sm["permissions"] if sm else [])
                    obj["permissions"] = perms
                    obj["role"] = "staff"
                    obj["is_owner"] = False
                    obj["can_delete"] = False
                    obj["deletable"] = False
                    obj["can_remove"] = False
                    if is_full_admin_perms(perms):
                        obj["permissions"] = list(PERMISSIONS)
                        obj["is_admin"] = True
                        obj["is_immutable"] = True
                    else:
                        obj["is_admin"] = False
                        obj["is_immutable"] = False
            out.append(obj)
        return out

    return db_call(_all)


def get_project_row(pid) -> dict | None:
    def _one(conn):
        key = str(pid or "").strip()
        if not key:
            return None
        if key.isdigit():
            row = conn.execute("SELECT * FROM project WHERE id = ?", (int(key),)).fetchone()
            if row:
                return rowd(row)
        return rowd(conn.execute("SELECT * FROM project WHERE domain = ? OR name = ?", (key, key)).fetchone())

    try:
        return db_call(_one)
    except Exception:
        return None


def unique_domain(conn, base: str, skip_id=None) -> str:
    domain = slugify(base)
    n = 2
    while True:
        row = conn.execute("SELECT id FROM project WHERE domain = ?", (domain,)).fetchone()
        if not row or (skip_id is not None and int(row["id"]) == int(skip_id)):
            return domain
        domain = f"{slugify(base)}{n}"
        n += 1


def tariff_plan() -> dict:
    return {
        "id": 1,
        "tier": "pro",
        "name": "Pro",
        "month_price": 0,
        "servers_limit": 99,
        "players_limit": 999999,
    }


def tariff_state() -> dict:
    def _t(conn):
        pid = current_pid()
        if pid:
            servers = conn.execute(
                "SELECT COUNT(*) FROM servers WHERE project_id = ? AND paired = 1",
                (pid,),
            ).fetchone()[0]
            players = features.project_players_count(conn, pid)
        else:
            servers = conn.execute("SELECT COUNT(*) FROM servers WHERE paired = 1").fetchone()[0]
            players = features.project_players_count(conn, 0)
        return features.tariff(conn, servers, players)

    return db_call(_t)


def _tariff_select_status(result) -> int:
    if not isinstance(result, dict) or result.get("ok") is not False:
        return 200
    err = str(result.get("error") or "")
    if err in ("insufficient_balance", "base_not_purchasable"):
        # 200 so the SPA does not treat this as a crash / Axios 402 overlay.
        return 200
    if err == "project_blocked":
        return 403
    return 400


def now_ms() -> int:
    return int(time.time() * 1000)


def now_s() -> int:
    return int(time.time())


def qfirst(params, *keys, default=""):
    params = params or {}
    candidates = []
    for key in keys:
        candidates.extend([
            key,
            key + "[]",
            "filter[%s]" % key,
            "filters[%s]" % key,
            "filter[%s][]" % key,
        ])
    for key in candidates:
        val = params.get(key)
        if isinstance(val, list):
            val = val[0] if val else ""
        if val not in (None, ""):
            return val
    low_keys = {str(k).lower(): k for k in params.keys()}
    for key in keys:
        needle = str(key).lower()
        for raw_key in list(params.keys()):
            lk = str(raw_key).lower().replace("-", "_")
            if lk == needle or lk.endswith("[" + needle + "]") or lk.endswith("[" + needle + "][]"):
                val = params.get(raw_key)
                if isinstance(val, list):
                    val = val[0] if val else ""
                if val not in (None, ""):
                    return val
        actual = low_keys.get(needle)
        if actual is not None:
            val = params.get(actual)
            if isinstance(val, list):
                val = val[0] if val else ""
            if val not in (None, ""):
                return val
    return default


def qbool(params, *keys, default=None):
    raw = qfirst(params, *keys, default="")
    if raw in (None, ""):
        return default
    text = str(raw).strip().lower()
    if text in ("1", "true", "yes", "on"):
        return True
    if text in ("0", "false", "no", "off"):
        return False
    return default


def coerce_staff_id(raw) -> int:
    if raw in (None, "", False):
        return 0
    if isinstance(raw, (list, tuple)):
        raw = raw[0] if raw else 0
    if isinstance(raw, dict):
        for key in ("id", "client_id", "checker_id", "moderator_id", "staff_id", "user_id"):
            n = coerce_staff_id(raw.get(key))
            if n:
                return n
        nested = raw.get("client") if isinstance(raw.get("client"), dict) else None
        if nested:
            return coerce_staff_id(nested)
        return 0
    if isinstance(raw, bool):
        return 0
    if isinstance(raw, (int, float)):
        try:
            n = int(raw)
        except Exception:
            return 0
        return n if n > 0 else 0
    text = str(raw).strip()
    if not text or text.lower() in ("undefined", "null", "all", "[object object]"):
        return 0
    if text.startswith("{") or text.startswith("["):
        try:
            return coerce_staff_id(json.loads(text))
        except Exception:
            pass
    try:
        n = int(float(text))
        return n if n > 0 else 0
    except Exception:
        pass
    found = re.search(r"\d+", text)
    if not found:
        return 0
    try:
        n = int(found.group(0))
        return n if n > 0 else 0
    except Exception:
        return 0


def parse_stats_staff_id(params, extra=None) -> int:
    params = params or {}
    n = coerce_staff_id(qfirst(
        params,
        "client_id", "clientId", "checker_id", "moderator_id", "staff_id",
        "user_id", "ids", "id", "selected_client_id", "selectedClientId",
    ))
    if n:
        return n
    if isinstance(extra, dict):
        n = coerce_staff_id(extra)
        if n:
            return n
        for key in ("client_id", "clientId", "checker_id", "moderator_id", "staff_id", "user_id", "ids", "id"):
            n = coerce_staff_id(extra.get(key))
            if n:
                return n
    for key, val in list(params.items()):
        lk = str(key).lower().replace("-", "_")
        if "client" in lk and "id" in lk:
            n = coerce_staff_id(val)
            if n:
                return n
    return 0


def foreign_project_from_params(params) -> int:
    """SPA sends filter[project_id_original] / projectIdOriginal — not always a flat key."""
    me = 0
    try:
        me = int(current_pid() or features.request_project_id() or 0)
    except Exception:
        me = 0
    preferred = 0
    fallback = 0
    for key, val in (params or {}).items():
        lk = str(key).lower().replace("-", "_").replace("[]", "")
        raw = val[0] if isinstance(val, list) and val else val
        try:
            n = int(raw or 0)
        except Exception:
            n = 0
        if not n:
            continue
        if "original" in lk or "subscription" in lk or "foreign" in lk:
            preferred = n
            break
        if lk in ("project_id", "projectid") or lk.endswith("[project_id]") or lk.endswith("[projectid]"):
            fallback = n
    found = preferred or fallback
    if found and found != me:
        return found
    return 0


def parse_ms_cursor(raw):
    """Return (ms, sent). sent=True means a second page — never replay the first chunk."""
    if raw in (None, "", 0, "0"):
        return 0, False
    text = str(raw).strip()
    if not text or text in ("0", "null", "undefined"):
        return 0, False
    try:
        n = int(float(text))
        if n > 0:
            return n, True
    except Exception:
        pass
    try:
        from datetime import datetime
        iso = text.replace("Z", "+00:00")
        dt = datetime.fromisoformat(iso)
        return int(dt.timestamp() * 1000), True
    except Exception:
        return 0, True


def last_moved_stamp(moved) -> int:
    now = now_ms()
    try:
        moved = int(moved or 0)
    except (TypeError, ValueError):
        moved = 0
    if moved >= 10**12:
        return moved
    if moved >= 10**9:
        return moved * 1000
    if moved > 0:
        return max(0, now - moved)
    return now


def moved_elapsed(moved, alive=False, pos_time=0) -> int:
    now = now_ms()
    moved = int(moved or 0)
    if moved >= 10**12:
        return max(100, now - moved)
    if moved >= 10**9:
        return max(100, now - moved * 1000)
    if moved > 0:
        return moved
    pos_time = int(pos_time or 0)
    if pos_time >= 10**12:
        return max(100, now - pos_time)
    if alive:
        return 250
    return 0


def _on_passenger() -> bool:
    return bool(os.environ.get("CHECKAPP_WSGI") or os.environ.get("PASSENGER_APP_ENV") or os.environ.get("PASSENGER_BASE_URI") is not None)


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=8, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # WAL is fine locally; DELETE is safer on cPanel/Spaceship shared disks.
    conn.execute("PRAGMA journal_mode=" + ("DELETE" if _on_passenger() else "WAL"))
    conn.execute("PRAGMA busy_timeout=8000")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA temp_store=MEMORY")
    return conn


def wipe_and_reseed() -> None:
    """Empty every table, then seed only the owner account and one blank project."""
    DATA.mkdir(exist_ok=True)
    UPLOADS.mkdir(exist_ok=True)
    with LOCK:
        conn = connect()
        try:
            conn.execute("PRAGMA foreign_keys = OFF")
            tables = [
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
                )
            ]
            for name in tables:
                conn.execute('DELETE FROM "%s"' % name.replace('"', ""))
            try:
                conn.execute("DELETE FROM sqlite_sequence")
            except Exception:
                pass
            conn.commit()
        finally:
            conn.close()
        for item in UPLOADS.iterdir():
            try:
                if item.is_file():
                    item.unlink()
            except Exception:
                pass
    flag = DATA / "RESET_CLEAN"
    try:
        if flag.is_file():
            flag.unlink()
    except Exception:
        pass
    init_db()


def init_db() -> None:
    with LOCK:
        conn = connect()
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS project (
                id INTEGER PRIMARY KEY,
                name TEXT DEFAULT 'Checkapp',
                domain TEXT DEFAULT 'checkapp',
                avatar TEXT DEFAULT '',
                contact_url TEXT DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS servers (
                id INTEGER PRIMARY KEY,
                name TEXT DEFAULT '',
                hostname TEXT DEFAULT '',
                level TEXT DEFAULT '',
                description TEXT DEFAULT '',
                avatar_url TEXT DEFAULT '',
                banner_url TEXT DEFAULT '',
                online INTEGER DEFAULT 0,
                slots INTEGER DEFAULT 0,
                port INTEGER DEFAULT 0,
                version TEXT DEFAULT '',
                protocol TEXT DEFAULT '',
                token TEXT,
                paired INTEGER DEFAULT 0,
                connected INTEGER DEFAULT 0,
                last_seen INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS pair_codes (
                code TEXT PRIMARY KEY,
                created_at INTEGER,
                used INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS players (
                steam_id TEXT PRIMARY KEY,
                steam_name TEXT DEFAULT '',
                ip TEXT DEFAULT '',
                first_seen INTEGER,
                last_seen INTEGER,
                comment TEXT DEFAULT '',
                last_language TEXT DEFAULT 'unknown',
                last_no_license INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS online_players (
                steam_id TEXT PRIMARY KEY,
                payload TEXT
            );
            CREATE TABLE IF NOT EXISTS chat (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                steam_id TEXT,
                steam_name TEXT DEFAULT '',
                target_steam_id TEXT,
                is_team INTEGER DEFAULT 0,
                text TEXT,
                from_site INTEGER DEFAULT 0,
                created_at INTEGER
            );
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                initiator_steam_id TEXT,
                target_steam_id TEXT,
                reason TEXT,
                message TEXT DEFAULT '',
                created_at INTEGER
            );
            CREATE TABLE IF NOT EXISTS bans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                steam_id TEXT,
                steam_name TEXT DEFAULT '',
                ip TEXT DEFAULT '',
                reason TEXT,
                comment TEXT DEFAULT '',
                ban_ip INTEGER DEFAULT 0,
                created_at INTEGER,
                expired_at INTEGER DEFAULT 0,
                active INTEGER DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS mutes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                steam_id TEXT,
                reason TEXT DEFAULT '',
                created_at INTEGER,
                expired_at INTEGER DEFAULT 0,
                active INTEGER DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS checks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                steam_id TEXT,
                steam_name TEXT DEFAULT '',
                status TEXT DEFAULT 'active',
                contact TEXT DEFAULT '',
                started_at INTEGER,
                finished_at INTEGER,
                notice INTEGER DEFAULT 0,
                verdict TEXT DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT,
                steam_id TEXT,
                payload TEXT,
                created_at INTEGER
            );
            CREATE TABLE IF NOT EXISTS kills (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                initiator_steam_id TEXT,
                target_steam_id TEXT,
                weapon TEXT,
                distance REAL,
                is_headshot INTEGER,
                created_at INTEGER
            );
            CREATE TABLE IF NOT EXISTS comments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                steam_id TEXT,
                text TEXT,
                created_at INTEGER
            );
            CREATE TABLE IF NOT EXISTS queue (
                id TEXT PRIMARY KEY,
                name TEXT,
                data TEXT,
                created_at INTEGER,
                done INTEGER DEFAULT 0,
                result TEXT
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            """
        )
        reset_flag = (DATA / "RESET_CLEAN").is_file() or os.environ.get("CHECKAPP_RESET") == "1"
        if reset_flag:
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            ):
                conn.execute('DELETE FROM "%s"' % str(row[0]).replace('"', ""))
            try:
                conn.execute("DELETE FROM sqlite_sequence")
            except Exception:
                pass
            try:
                (DATA / "RESET_CLEAN").unlink()
            except Exception:
                pass
            for item in UPLOADS.iterdir():
                try:
                    if item.is_file():
                        item.unlink()
                except Exception:
                    pass
        # No default shared project — users create their own after registration.
        for col, default in (
            ("world_size", "INTEGER DEFAULT 0"),
            ("seed", "INTEGER DEFAULT 0"),
            ("map_image", "TEXT DEFAULT ''"),
        ):
            try:
                conn.execute(f"ALTER TABLE servers ADD COLUMN {col} {default}")
            except Exception:
                pass
        conn.execute(
            "DELETE FROM players WHERE steam_id IN ('76561198000000000','76561198000000001','0') OR steam_name IN ('Demo Player','DemoPlayer')"
        )
        conn.execute(
            "DELETE FROM online_players WHERE steam_id IN ('76561198000000000','76561198000000001','0')"
        )
        conn.execute(
            """DELETE FROM players
               WHERE steam_id IN ('site','project','org','organization','0','admin')
                  OR steam_id GLOB '*[^0-9]*'
                  OR length(steam_id) != 17
                  OR lower(steam_name) IN ('site','project','org')"""
        )
        conn.execute(
            """DELETE FROM online_players
               WHERE steam_id IN ('site','project','org','organization','0','admin')
                  OR steam_id GLOB '*[^0-9]*'
                  OR length(steam_id) != 17"""
        )
        features.ensure_schema(conn)
        # Do not reset plan on every startup — respect user's selected tariff.
        conn.execute("DELETE FROM bags WHERE steam_id IN ('', '0', 'None') OR steam_id IS NULL")
        conn.execute(
            "UPDATE players SET steam_name = steam_id WHERE steam_name IN ('Unnamed Bag', 'bag', 'Demo Player', 'DemoPlayer')"
        )
        conn.execute(
            """UPDATE players SET steam_name = ''
               WHERE steam_name = steam_id
                  OR steam_name IN ('unknown', 'Unknown', 'player')"""
        )
        conn.commit()
        conn.close()


init_db()


def ensure_local_plugin_copy() -> None:
    """Keep /local/RustApp.cs on disk for reliable browser downloads."""
    try:
        src = plugin_cs_path()
        dst = ROOT / "local" / "RustApp.cs"
        if src.is_file():
            dst.parent.mkdir(parents=True, exist_ok=True)
            data = src.read_bytes()
            if not dst.exists() or dst.read_bytes() != data:
                dst.write_bytes(data)
    except Exception:
        pass


ensure_local_plugin_copy()


def plugin_download_config(host: str = "", forwarded_proto: str = "") -> dict:
    """Browser download settings. Set download_url in plugin-config.json or RUSTCHECK_PLUGIN_URL."""
    cfg = {
        "download_url": "",
        "filename": "RustApp.cs",
        "local_url": "/plugin/download",
        "source_path": str(plugin_cs_path()),
    }
    cfg_path = ROOT / "plugin-config.json"
    if cfg_path.is_file():
        try:
            raw = json.loads(cfg_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                cfg.update(raw)
        except Exception:
            pass
    env_url = (os.environ.get("RUSTCHECK_PLUGIN_URL") or "").strip()
    if env_url:
        cfg["download_url"] = env_url
    cfg["download_url"] = str(cfg.get("download_url") or "").strip()
    cfg["filename"] = str(cfg.get("filename") or "RustApp.cs").strip() or "RustApp.cs"
    cfg["local_url"] = str(cfg.get("local_url") or "/plugin/download").strip() or "/plugin/download"

    host_raw = str(host or "").strip()
    host_low = host_raw.lower().split(":")[0]
    is_local = (
        not host_low
        or host_low in ("localhost", "127.0.0.1")
        or host_low.endswith(".local")
    )
    ext = cfg["download_url"]
    if is_local and ext and ("rustcheck.cc" in ext.lower() or "russiachect.ru" in ext.lower() or "rustapp.io" in ext.lower()):
        cfg["download_url"] = ""
        ext = ""
    # Never guess the public scheme here: the site may be served over plain
    # HTTP (e.g. direct IP:port) and a hard-coded https:// download_url makes
    # the browser open a dead TLS connection. An external mirror must be set
    # explicitly via plugin-config.json / RUSTCHECK_PLUGIN_URL; otherwise leave
    # it empty so the client builds a same-origin /plugin/download URL.
    return cfg


def db_call(fn):
    # Do not hold a process-wide lock: plugin heartbeats + check activity used to
    # serialize every request and nginx then 502s the SPA page itself.
    conn = connect()
    try:
        result = fn(conn)
        conn.commit()
        return result
    finally:
        conn.close()


def rowd(row):
    return dict(row) if row is not None else None


def project_clause(column: str = "project_id") -> tuple[str, list]:
    pid = current_pid()
    if not pid:
        return " AND 0=1", []
    return f" AND {column} = ?", [pid]


def scoped_project_clause(conn, params=None, column: str = "project_id") -> tuple[str, list]:
    """Current project, or a subscribed foreign project. Never leak our rows into other-project tabs."""
    foreign = foreign_project_from_params(params or {})
    if foreign:
        allowed = set()
        try:
            allowed = {int(x) for x in (features.subscribed_foreign_project_ids(conn) or [])}
        except Exception:
            allowed = set()
        if foreign not in allowed:
            return " AND 0=1", []
        return f" AND COALESCE({column}, 0) = ?", [foreign]
    return project_clause(column)


def server_heartbeat_ok(row) -> bool:
    """True only while the paired server is still sending heartbeats."""
    if not row:
        return False
    data = rowd(row) if not isinstance(row, dict) else row
    if not data.get("paired"):
        return False
    last = int(data.get("last_seen") or 0)
    if last > 10**12:
        last = last // 1000
    return bool(last > 0 and last > now_s() - 90)


def purge_stale_online_players(conn) -> None:
    """Drop presence rows for servers that went offline (no heartbeat)."""
    try:
        rows = conn.execute("SELECT id, paired, last_seen FROM servers").fetchall()
    except Exception:
        return
    for raw in rows:
        row = rowd(raw) or {}
        sid = int(row.get("id") or 0)
        if not sid:
            continue
        if server_heartbeat_ok(row):
            continue
        try:
            conn.execute("DELETE FROM online_players WHERE COALESCE(server_id, 1) = ?", (sid,))
        except Exception:
            pass


def project_runtime(conn) -> dict:
    pid = current_pid()
    if not pid:
        return {"ok": False, "message": "Сервер проекта не подключён"}
    row = conn.execute(
        """SELECT * FROM servers WHERE project_id = ? AND paired = 1
           ORDER BY last_seen DESC, id DESC LIMIT 1""",
        (pid,),
    ).fetchone()
    if not row:
        return {"ok": False, "message": "Сервер проекта не подключён"}
    if not server_heartbeat_ok(row):
        return {"ok": False, "message": "Сервер проекта не подключён"}
    return {"ok": True, "server": rowd(row)}


def enqueue(name: str, data: dict, conn=None, project_id: int | None = None) -> str:
    task_id = str(uuid.uuid4())
    name = features.queue_name(name)
    pid = int(project_id if project_id is not None else (current_pid() or 0))

    def _q(c):
        try:
            c.execute(
                "INSERT INTO queue (id, name, data, created_at, done, project_id) VALUES (?, ?, ?, ?, 0, ?)",
                (task_id, name, json.dumps(data, ensure_ascii=False), now_s(), pid),
            )
        except Exception:
            c.execute(
                "INSERT INTO queue (id, name, data, created_at, done) VALUES (?, ?, ?, ?, 0)",
                (task_id, name, json.dumps(data, ensure_ascii=False), now_s()),
            )

    if conn is not None:
        _q(conn)
    else:
        db_call(_q)
    return task_id


def check_freeze_chat_item(conn, event, cid, sid, payload):
    active = bool(payload.get("active"))
    text = "Игрок заморожен" if active else "Игрок разморожен"
    author = staff_brief(conn, actor_id=int(payload.get("client_id") or payload.get("actor_user_id") or 0), payload=payload)
    return {"id":"notice-%s" % event["id"],"M_ID":int(event["id"]),"check_id":int(cid),"checkId":int(cid),"type":"FreezeChanged","kind":"FreezeChanged","text":text,"message":text,"created_at":int(event["created_at"]),"meta":{"text":text,"message":text,"action":"freeze","active":active,"client_id":int(author.get("id") or 0),"steam_id":sid,"channel":"direct","author_name":author.get("name") or "","is_contact":False},"player":author,"initiator_player":author,"initiator_client":author,"from_site":True}


def check_freeze_state(conn, cid: int, active=None) -> dict:
    pid = int(current_pid() or 0)
    row = rowd(conn.execute("SELECT * FROM checks WHERE id=? AND project_id=?", (int(cid),pid)).fetchone())
    if not row:
        return {"ok":False,"error":"not_found"}
    uid = int(features.request_user_id() or 0)
    member = features.staff_member_payload(conn,pid,uid)
    if uid != features.project_owner_user_id(conn,pid) and (not member or "Court_CheckProcess" not in member.get("permissions",[])):
        return {"ok":False,"error":"forbidden"}
    key = f"check_freeze_{pid}_{int(cid)}"
    stored = conn.execute("SELECT value FROM settings WHERE key=?",(key,)).fetchone()
    state = json.loads(stored["value"]) if stored else {"active":False}
    if active is not None:
        if active and int(row.get("finished_at") or 0):
            return {"ok":False,"error":"check_finished"}
        online = conn.execute("SELECT server_id FROM online_players WHERE steam_id=? AND project_id=?",(row["steam_id"],pid)).fetchone()
        srv = int((online["server_id"] if online else state.get("server_id")) or 0)
        if active and not srv:
            return {"ok":False,"error":"player_offline"}
        state={"active":bool(active),"server_id":srv,"steam_id":row["steam_id"],"check_id":int(cid)}
        enqueue("freeze-set",dict(state,value=bool(active)),conn=conn,project_id=pid)
        conn.execute("INSERT OR REPLACE INTO settings(key,value) VALUES (?,?)",(key,json.dumps(state)))
        features.audit(conn,"check.freeze",{"check_id":int(cid),"steam_id":row["steam_id"],"active":bool(active),"client_id":uid,"project_id":pid})
        _activity_cache_drop(cid)
        event = conn.execute("SELECT id,created_at,payload FROM audit WHERE event='check.freeze' AND project_id=? ORDER BY id DESC LIMIT 1",(pid,)).fetchone()
        if event:
            item=check_freeze_chat_item(conn,event,cid,row["steam_id"],json.loads(event["payload"] or "{}"))
            emit_realtime(pid,"check-activity",item,server_id=srv)
            return dict(state,ok=True,activity=item)
    return dict(state,ok=True)


def release_check_freeze(conn, cid: int) -> None:
    row = rowd(conn.execute("SELECT project_id FROM checks WHERE id=?",(int(cid),)).fetchone()) or {}
    pid = int(row.get("project_id") or 0)
    key=f"check_freeze_{pid}_{int(cid)}"
    stored=conn.execute("SELECT value FROM settings WHERE key=?",(key,)).fetchone()
    if stored:
        state=json.loads(stored["value"])
        if state.get("active"):
            state["active"]=False
            enqueue("freeze-set",dict(state,value=False),conn=conn,project_id=pid)
            conn.execute("UPDATE settings SET value=? WHERE key=?",(json.dumps(state),key))


def chat_columns(conn) -> set:
    return {row[1] for row in conn.execute("PRAGMA table_info(chat)").fetchall()}


def chat_from_project(body) -> bool:
    if not isinstance(body, dict):
        return False
    nested = body.get("options") if isinstance(body.get("options"), dict) else {}
    merged = dict(body)
    merged.update(nested)
    as_staff = str(merged.get("send_as") or merged.get("from") or merged.get("as") or "").strip().lower()
    if as_staff in ("staff", "client", "moderator", "admin", "user"):
        return False
    for key, val in list(merged.items()):
        name = str(key or "").strip().lower().replace("-", "_")
        if any(token in name for token in ("as_project", "from_project", "send_as_project", "use_project", "project_name", "asproject", "fromproject")):
            if val in (True, 1, "1", "true", "project", "org"):
                return True
        if name in ("as", "from", "sender", "initiator", "mode", "send_as", "author", "from_name", "from_type", "initiator_type"):
            text = str(val or "").strip().lower()
            if text in ("project", "org", "organization", "project_name", "system"):
                return True
        if name in ("client_id", "initiator_client_id", "from_client_id") and val in (0, "0", None, ""):
            if merged.get("text") or merged.get("message"):
                if merged.get("as_project") or merged.get("from_project") or merged.get("send_as") == "project":
                    return True
    return False


def is_ingame_chat_audit(event, payload=None, actor_id=0) -> bool:
    """In-game / plugin chat belongs in site chat, never in the audit journal."""
    ev = str(event or "")
    if ev == "player.message":
        return True
    if ev not in ("chat.direct", "chat.global"):
        return False
    payload = payload if isinstance(payload, dict) else {}
    if payload.get("from_site") is True or str(payload.get("source") or "").lower() in ("site", "staff"):
        return False
    if str(payload.get("author_type") or "").lower() == "player":
        return True
    if str(payload.get("source") or "").lower() in ("plugin", "game", "player"):
        return True
    if payload.get("from_site") is False:
        return True
    try:
        uid = int(actor_id or payload.get("actor_user_id") or 0)
    except Exception:
        uid = 0
    return uid <= 0


def project_title(conn=None, pid=None) -> str:
    def _n(c):
        use = int(pid or 0) or current_pid()
        row = None
        if use:
            row = c.execute("SELECT name FROM project WHERE id = ?", (use,)).fetchone()
        if not row:
            row = c.execute("SELECT name FROM project ORDER BY id ASC LIMIT 1").fetchone()
        return str((row["name"] if row else "") or "Checkapp")

    if conn is not None:
        return _n(conn)
    try:
        return db_call(_n)
    except Exception:
        return "RustApp"


def project_chat_client(conn, pid, name="") -> dict:
    pid = int(pid or 0)
    project = rowd(conn.execute("SELECT * FROM project WHERE id = ?", (pid,)).fetchone()) or {}
    name = str(name or project.get("name") or "RustApp")
    client = rustcheck_system_client() if name.strip() in ("RustCheck", "RustApp", "system") else {
        "name": name,
        "tag": name,
        "avatar": project.get("avatar") or PLACEHOLDER,
    }
    client.update({
        "id": 1000000 + pid,
        "steam_id": "0",
        "steam_name": client["name"],
        "status": "online",
        "online": True,
        "is_online": True,
        "is_project": True,
    })
    return client


def comment_obj(row, author=None) -> dict:
    if not isinstance(author, dict):
        author = {"id": 1, "name": "Admin", "avatar": PLACEHOLDER, "status": "online", "steam": features.empty_steam_profile(PLACEHOLDER)}
    created = int(row["created_at"] or now_ms()) if not isinstance(row, dict) else int(row.get("created_at") or now_ms())
    if isinstance(row, dict):
        cid = int(row.get("id") or 0)
        text = str(row.get("text") or "")
        steam_id = str(row.get("steam_id") or "")
    else:
        cid = int(row["id"] or 0)
        text = str(row["text"] or "")
        steam_id = str(row["steam_id"] or "")
    return {
        "id": cid,
        "M_ID": cid,
        "steam_id": steam_id,
        "text": text,
        "message": text,
        "comment": text,
        "note": text,
        "created_at": created,
        "created": created,
                        "client_id": int(author.get("id") or 0),
        "client": author,
        "author": author,
        "user": author,
        "can_delete": True,
        "deletable": True,
    }


def attach_active_check_fields(player, conn=None, steam_id: str = "") -> dict:
    if not isinstance(player, dict):
        return player
    sid = str(player.get("steam_id") or player.get("id") or steam_id or "")
    cid = 0
    for key in ("active_check_id", "activeCheckId", "check_id"):
        try:
            n = int(player.get(key) or 0)
        except Exception:
            n = 0
        if n:
            cid = n
            break
    if not cid and sid and conn is not None:
        try:
            cid = int(resolve_active_check_id(conn, current_pid() or 0, sid) or 0)
        except Exception:
            cid = 0
    player["active_check_id"] = cid
    player["activeCheckId"] = cid
    player["is_checking"] = bool(cid)
    player["checking"] = bool(cid)
    return player


def resolve_active_check_id(conn, pid: int, steam_id: str = "", target: str = "") -> int:
    """Active check for this player in the project, if any."""
    pid = int(pid or 0)
    candidates = []
    for sid in (str(target or "").strip(), str(steam_id or "").strip()):
        if not sid or sid in ("site", "project", "org", "0", "admin"):
            continue
        if sid not in candidates:
            candidates.append(sid)
    if not pid or not candidates:
        return 0
    for sid in candidates:
        try:
            row = conn.execute(
                """SELECT id FROM checks
                   WHERE steam_id = ?
                     AND COALESCE(project_id, 0) = ?
                     AND (finished_at IS NULL OR finished_at = 0)
                     AND LOWER(COALESCE(status, 'active')) NOT IN ('cancel', 'canceled', 'cancelled')
                   ORDER BY id DESC LIMIT 1""",
                (sid, pid),
            ).fetchone()
        except Exception:
            row = None
        if row:
            try:
                return int(row["id"] or 0)
            except Exception:
                return 0
    return 0


def insert_chat(conn, steam_id, steam_name, target, is_team, text, from_site=False, project_id: int | None = None, actor_user_id: int = 0, actor_name: str = "", author_type: str = "", server_id: int = 0, check_id: int = 0):
    pid = int(project_id if project_id is not None else (current_pid() or 0))
    from_site_flag = bool(from_site) or str(steam_id or "") in ("site", "project", "org", "0", "admin")
    frozen = features.freeze_actor(conn) if from_site_flag else {}
    info = frozen if from_site_flag else {"id": 0, "name": "", "role": "", "email": ""}
    aid = int(actor_user_id or frozen.get("actor_user_id") or info.get("id") or 0)
    aname = str(actor_name or frozen.get("actor_name") or steam_name or "")
    arole = str(frozen.get("actor_role") or info.get("role") or "")
    aemail = str(frozen.get("actor_email") or info.get("email") or "")
    created = now_ms()
    srv = int(server_id or 0)
    cid = int(check_id or 0)
    if not cid:
        cid = resolve_active_check_id(conn, pid, str(steam_id or ""), str(target or ""))
    if cid:
        try:
            crow = rowd(conn.execute("SELECT finished_at FROM checks WHERE id = ?", (cid,)).fetchone())
            if crow and int(crow.get("finished_at") or 0) and not from_site_flag:
                cid = 0
        except Exception:
            pass
    try:
        conn.execute(
            """INSERT INTO chat (steam_id, steam_name, target_steam_id, is_team, text, from_site, created_at, project_id, actor_user_id, actor_name, actor_email, actor_role, server_id, check_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (str(steam_id or ""), steam_name or "", target, 1 if is_team else 0, text or "", 1 if from_site else 0, created, pid, aid, aname, aemail, arole, srv, cid),
        )
    except Exception:
        try:
            conn.execute(
                """INSERT INTO chat (steam_id, steam_name, target_steam_id, is_team, text, from_site, created_at, project_id, actor_user_id, actor_name, actor_email, actor_role, server_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (str(steam_id or ""), steam_name or "", target, 1 if is_team else 0, text or "", 1 if from_site else 0, created, pid, aid, aname, aemail, arole, srv),
            )
        except Exception:
            try:
                conn.execute(
                    """INSERT INTO chat (steam_id, steam_name, target_steam_id, is_team, text, from_site, created_at, project_id, actor_user_id, actor_name, actor_email, actor_role)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (str(steam_id or ""), steam_name or "", target, 1 if is_team else 0, text or "", 1 if from_site else 0, created, pid, aid, aname, aemail, arole),
                )
            except Exception:
                conn.execute(
                    """INSERT INTO chat (steam_id, steam_name, target_steam_id, is_team, text, from_site, created_at, project_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (str(steam_id or ""), steam_name or "", target, 1 if is_team else 0, text or "", 1 if from_site else 0, created, pid),
                )
    mid = 0
    try:
        mid = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0] or 0)
    except Exception:
        mid = 0
    features.lifetime_bump(conn, "messages", 1)
    sid_author = str(steam_id or "")
    from_site_flag = bool(from_site) or sid_author in ("site", "project", "org", "0", "admin")
    project_sender = sid_author in ("project", "org")
    kind = "project" if project_sender else str(author_type or ("staff" if from_site_flag else "player"))
    project_client = project_chat_client(conn, pid, steam_name) if project_sender else None
    display_author = project_client["name"] if project_sender else aname
    features.emit_json_webhook(conn,"player_message_create",{"data":{"id":mid,"steam_id":sid_author,"name":display_author,"author_type":kind,"actor_user_id":aid,"actor_name":aname,"target_steam_id":target,"content":text or "","from_site":from_site_flag,"created_at":created,"server_id":srv}},project_id=pid)
    try:
        emit_realtime(pid, "chat.message", {
            "messageId": mid,
            "authorId": (1000000 + pid) if project_sender else (aid or sid_author),
            "authorName": display_author,
            "initiator_id": str(1000000 + pid) if project_sender else str(aid or sid_author),
            "project_id": pid,
            "authorType": kind,
            "author_type": kind,
            "is_project": project_sender,
            "initiator": "project" if project_sender else ("client" if from_site_flag else "player"),
            "initiator_name": display_author,
            **({"initiator_client": project_client, "initiator_avatar": project_client["avatar"]} if project_sender else {}),
            "actor_user_id": aid,
            "actor_name": aname,
            "content": text or "",
            "from_site": from_site_flag,
            "steam_id": sid_author,
            "target_steam_id": target,
            "is_team": bool(is_team),
            "type": "team" if is_team else ("direct" if target else "global"),
            "checkId": cid,
            "check_id": cid,
            "createdAt": created,
            "serverId": srv,
            "server_id": srv,
        }, server_id=srv)
    except Exception:
        pass
    if cid:
        try:
            _activity_cache_drop(cid)
        except Exception:
            pass
    try:
        emit_check_chat_message(
            conn, pid, mid, sid_author, target, text or "", created,
            aid, aname, kind, from_site_flag, cid, display_name=display_author,
        )
    except Exception as exc:
        print("check chat realtime failed", type(exc).__name__, exc)
    return mid


def emit_check_chat_message(
    conn, pid: int, message_id: int, steam_id: str, target, content: str, created: int,
    author_id, author_name: str, author_type: str, from_site: bool, known_check_id: int = 0,
    display_name: str = "",
) -> None:
    """Push a single check-chat line. Does not reload history."""
    pid = int(pid or 0)
    if not pid or not content:
        return
    sid = str(steam_id or "")
    tgt = str(target or "")
    player_sid = tgt if (from_site and tgt) else sid
    if player_sid in ("site", "project", "org", "0", "admin", ""):
        player_sid = tgt
    if not player_sid or player_sid in ("site", "project", "org", "0", "admin"):
        return
    check = None
    try:
        known = int(known_check_id or 0)
    except Exception:
        known = 0
    if known:
        check = rowd(conn.execute(
            "SELECT * FROM checks WHERE id = ? AND COALESCE(project_id, 0) = ?",
            (known, pid),
        ).fetchone())
    if not check:
        check = rowd(conn.execute(
            """SELECT * FROM checks
               WHERE steam_id = ?
                 AND COALESCE(project_id, 0) = ?
                 AND (finished_at IS NULL OR finished_at = 0)
                 AND LOWER(COALESCE(status, 'active')) NOT IN ('cancel', 'canceled', 'cancelled')
               ORDER BY id DESC LIMIT 1""",
            (player_sid, pid),
        ).fetchone())
    if not check:
        print("[CHECK CHAT] no active check for steam", player_sid, "project", pid)
        return
    try:
        if int(check.get("finished_at") or 0):
            return
    except Exception:
        pass
    status_low = str(check.get("status") or "active").lower()
    if status_low in ("cancel", "canceled", "cancelled", "clear", "ban", "finished", "finishedclear", "finishedban"):
        if int(check.get("finished_at") or 0):
            return
    check_id = int(check.get("id") or 0)
    try:
        _activity_cache_drop(check_id)
    except Exception:
        pass
    server_id = 0
    try:
        server_id = int((check.get("server_id") or 0) or 0)
    except Exception:
        server_id = 0
    if not server_id:
        try:
            srow = conn.execute(
                "SELECT id FROM servers WHERE project_id = ? AND paired = 1 ORDER BY last_seen DESC LIMIT 1",
                (pid,),
            ).fetchone()
            if srow:
                server_id = int(srow["id"] or 0)
        except Exception:
            server_id = 0
    cid_num = 0
    try:
        cid_num = int(author_id or 0)
    except Exception:
        cid_num = 0
    if from_site:
        cid_num = stable_client_id(cid_num, author_name)
    staff_client = None
    project_sender = sid in ("project", "org")
    actor_name = author_name
    if project_sender:
        staff_client = project_chat_client(conn, pid, display_name)
        cid_num = staff_client["id"]
        author_name = staff_client["name"]
        author_type = "project"
    elif from_site:
        try:
            staff_client = mark_staff_moderator(staff_brief(conn, author_name, author_id, {
                "actor_name": author_name, "actor_user_id": author_id,
            }))
            staff_client["id"] = cid_num
            staff_client["name"] = author_name or staff_client.get("name") or ""
        except Exception:
            staff_client = mark_staff_moderator({
                "id": cid_num,
                "name": author_name,
                "avatar": PLACEHOLDER,
            })
    message = {
        "messageId": int(message_id or 0),
        "id": "chat-%s" % message_id,
        "M_ID": int(message_id or 0),
        "projectId": pid,
        "project_id": pid,
        "checkId": int(check_id),
        "check_id": int(check_id),
        "serverId": server_id,
        "server_id": server_id,
        "authorId": cid_num if from_site else (author_id if author_id not in (None, "", 0) else sid),
        "author_id": cid_num if from_site else (author_id if author_id not in (None, "", 0) else sid),
        "authorName": author_name,
        "author_name": author_name,
        "authorType": author_type,
        "author_type": author_type,
        "is_project": project_sender,
        "initiator": "project" if project_sender else ("client" if from_site else "player"),
        "initiator_id": str(cid_num) if from_site else sid,
        "steam_id": sid,
        "actor_user_id": author_id if from_site else 0,
        "actor_name": actor_name if from_site else "",
        "content": content,
        "text": content,
        "message": content,
        "createdAt": int(created or now_ms()),
        "created_at": int(created or now_ms()),
        "type": "MessageFromModerator" if from_site else "MessageFromPlayer",
        "kind": "MessageFromModerator" if from_site else "MessageFromPlayer",
        "from_site": from_site,
        "player": staff_client if from_site else {
            "steam_id": sid,
            "steam_name": author_name,
            "name": author_name,
        },
        "initiator_client": staff_client if from_site else {
            "id": 0,
            "name": author_name,
            "steam_name": author_name,
        },
        "meta": {
            "text": content,
            "message": content,
            "steam_id": player_sid,
            "channel": "direct" if tgt else "global",
            "client_id": cid_num if from_site else 0,
            "author_name": author_name,
            "actor_name": actor_name if from_site else "",
            "actor_user_id": author_id if from_site else 0,
            "author_type": author_type,
            "is_project": project_sender,
        },
    }
    print(
        "[CHECK CHAT] Broadcasting check.message.created",
        "projectId", pid,
        "checkId", check_id,
        "messageId", message_id,
    )
    emit_realtime(pid, "check.message.created", {
        "projectId": pid,
        "project_id": pid,
        "checkId": check_id,
        "check_id": check_id,
        "serverId": server_id,
        "server_id": server_id,
        "message": message,
    }, server_id=server_id)
    emit_realtime(pid, "check-activity", message, server_id=server_id)


def is_real_steam_id(sid) -> bool:
    return features.is_real_steam_id(sid)


def as_int(value, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def normalize_player_ip(ip: str) -> str:
    text = str(ip or "").strip()
    if not text:
        return ""
    if text.startswith("[") and "]" in text:
        text = text[1 : text.index("]")]
    if "%" in text:
        text = text.split("%", 1)[0]
    if text.count(":") == 1 and "." in text:
        text = text.split(":", 1)[0]
    return text.strip()


def rustcheck_system_client() -> dict:
    return {
        "id": 0,
        "name": "RustApp",
        "tag": "RustApp",
        "avatar": RUSTCHECK_AVATAR,
        "status": "online",
        "online": True,
        "is_online": True,
        "is_project": True,
        "system_source": "RustCheck",
        "is_system": True,
    }


def signage_like_from_request(path, params, body) -> dict:
    payload = body if isinstance(body, dict) else {}
    parts = [p for p in str(path or "").strip("/").split("/") if p]
    did = 0
    nid = str(payload.get("net_id") or payload.get("netId") or payload.get("s3_id") or "")
    for part in parts:
        if str(part).isdigit():
            did = int(part)
            break
    raw_id = payload.get("id") or payload.get("drawing_id") or payload.get("drawingId")
    try:
        if raw_id not in (None, "") and str(raw_id).isdigit():
            did = int(raw_id)
    except Exception:
        pass
    if not nid:
        nid = str((params.get("net_id") or [""])[0] or "")
    liked = None
    for key in ("liked", "is_liked", "likedByCurrentUser", "liked_by_current_user"):
        if key in payload:
            liked = payload.get(key)
            break
    if "/unlike" in path or "/dislike" in path:
        liked = False
    elif "/like" in path and liked is None:
        liked = None  # toggle
    return db_call(lambda c: features.signage_toggle_like(c, did, nid, liked))


def is_usable_name(name, steam_id="") -> bool:
    text = str(name or "").strip()
    sid = str(steam_id or "").strip()
    if not text:
        return False
    low = text.lower()
    if low in (".", "-", "_", "unknown", "неизвестный", "<blank>", "blank", "player", "unnamed"):
        return False
    cleaned = re.sub(r"[.\s_\-<>]", "", text)
    if not cleaned:
        return False
    if sid and (text == sid or cleaned == sid):
        return False
    if text.isdigit() and len(text) >= 16:
        return False
    return True


def is_display_name(name, steam_id="") -> bool:
    text = str(name or "").strip()
    sid = str(steam_id or "").strip()
    if not text:
        return False
    if sid and text == sid:
        return False
    if text.isdigit() and len(text) >= 16:
        return False
    # Single-char / dotted Steam nicks are valid (e.g. ".")
    return True


def resolve_player_name(conn, steam_id, fallback="") -> str:
    sid = str(steam_id or "").strip()
    cached = features.read_cache(conn, "steam_cache", "steam_id", sid) if sid else None
    persona = str((cached or {}).get("personaname") or "").strip() if isinstance(cached, dict) else ""
    alias_name = ""
    if isinstance(cached, dict):
        for item in cached.get("aliases") or []:
            if not isinstance(item, dict):
                continue
            cand = str(item.get("name") or "").strip()
            if is_display_name(cand, sid):
                alias_name = cand
                break
    row = conn.execute("SELECT steam_name FROM players WHERE steam_id = ?", (sid,)).fetchone() if sid else None
    db_name = str(row["steam_name"] if row else "") or ""
    for candidate in (db_name, fallback, persona, alias_name):
        if is_display_name(candidate, sid):
            pretty = str(candidate).strip()
            if sid and pretty and pretty != db_name:
                try:
                    conn.execute(
                        "UPDATE players SET steam_name = ? WHERE steam_id = ? AND (steam_name = '' OR steam_name = ? OR steam_name IS NULL)",
                        (pretty, sid, sid),
                    )
                except Exception:
                    pass
            return pretty
    if sid:
        hist = conn.execute(
            "SELECT steam_name FROM player_names WHERE steam_id = ? ORDER BY id DESC LIMIT 20",
            (sid,),
        ).fetchall()
        for item in hist:
            if is_display_name(item["steam_name"], sid):
                return str(item["steam_name"]).strip()
    return sid


def insert_alert(conn, typ: str, steam_id: str, payload: dict | None = None, project_id: int | None = None) -> None:
    data = payload if isinstance(payload, dict) else {}
    pid = int(project_id if project_id is not None else (current_pid() or 0))
    if not pid:
        print("insert_alert skip, no project", typ)
        return
    conn.execute(
        "INSERT INTO alerts (type, steam_id, payload, created_at, project_id) VALUES (?, ?, ?, ?, ?)",
        (str(typ or "custom"), str(steam_id or ""), json.dumps(data, ensure_ascii=False), now_ms(), pid),
    )
    features.emit_json_webhook(conn,"player_alert_create",{"data":{"type":typ,"steam_id":steam_id,"payload":data}},project_id=pid)
    try:
        emit_realtime(pid, "notification.created", {"type": typ, "playerId": steam_id, "payload": data})
    except Exception:
        pass


def subst_court_command(cmd: str, steam_id: str, name: str = "", player_ip: str = "", staff_steam_id: str = "") -> str:
    text = str(cmd or "")
    sid = str(steam_id or "")
    nick = str(name or sid)
    ip = str(player_ip or "")
    staff = str(staff_steam_id or "")
    replacements = (
        ("{steam_id}", sid),
        ("{steamid}", sid),
        ("{steam}", sid),
        ("{id}", sid),
        ("{steam_name}", nick),
        ("{name}", nick),
        ("{player}", nick),
        ("{username}", nick),
        ("{player_ip}", ip),
        ("{ip}", ip),
        ("{staff_steam_id}", staff),
        ("%STEAMID%", sid),
        ("%STEAMID64%", sid),
        ("%NAME%", nick),
        ("%PLAYER%", nick),
        ("%USERNAME%", nick),
        ("%IP%", ip),
    )
    for token, value in replacements:
        text = text.replace(token, value)
    return text.strip()


def flatten_court_commands(raw, steam_id: str, name: str = "", player_ip: str = "", staff_steam_id: str = "") -> list:
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        raw = []
    out = []
    for item in raw:
        if isinstance(item, dict):
            cmd = (
                item.get("command")
                or item.get("cmd")
                or item.get("value")
                or item.get("text")
                or item.get("line")
                or item.get("template")
                or item.get("raw")
                or ""
            )
        else:
            cmd = str(item or "")
        cmd = subst_court_command(cmd, steam_id, name, player_ip=player_ip, staff_steam_id=staff_steam_id)
        if cmd:
            out.append(cmd)
    return out


def totp_secret_for_user(conn, uid: int, email: str = "") -> str:
    key = f"twofa_secret_{uid}"
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    if row and row["value"]:
        return str(row["value"])
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
    secret = "".join(alphabet[b % len(alphabet)] for b in os.urandom(20))
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, secret),
    )
    return secret


def totp_now(secret: str, offset: int = 0) -> str:
    secret = str(secret or "").upper().replace(" ", "")
    pad = "=" * ((8 - len(secret) % 8) % 8)
    key = base64.b32decode(secret + pad)
    counter = int(time.time()) // 30 + int(offset)
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    pos = digest[-1] & 0x0F
    code = struct.unpack(">I", digest[pos : pos + 4])[0] & 0x7FFFFFFF
    return str(code % 1000000).zfill(6)


def totp_verify(secret: str, code: str) -> bool:
    code = str(code or "").strip()
    if not code.isdigit():
        return False
    code = code.zfill(6)
    for drift in (-1, 0, 1):
        if totp_now(secret, drift) == code:
            return True
    return False


def twofa_payload(conn, user: dict | None = None) -> dict:
    user = user or features.owner_user(conn)
    uid = int((user or {}).get("id") or 1)
    email = str((user or {}).get("email") or "user")
    secret = totp_secret_for_user(conn, uid, email)
    label = email.split("@")[0] or "user"
    link = f"otpauth://totp/Rustcheck:{label}?secret={secret}&issuer=Rustcheck"
    active = bool(int((user or {}).get("twofactor_active") or 0))
    return {
        "active": active,
        "twofactor_active": active,
        "enabled": active,
        "secret": secret,
        "url": link,
        "link": link,
    }


def court_command_request(conn, cid, sid: str, cmds: list, player: dict | None = None) -> dict:
    sid = str(sid or "")
    if not player and sid:
        player = player_view(conn, sid, nest_team=False)
    if not player:
        player = {"steam_id": sid, "steam_name": sid, "name": sid}
    servers = project_server_ids(conn)
    server_id = int(servers[0]) if servers else 1
    try:
        cmd_id = int(cid)
    except (TypeError, ValueError):
        cmd_id = cid
    return {
        "command": {"id": cmd_id},
        "steam_id": sid,
        "server_id": server_id,
        "args": {},
        "player": player,
        "target_player": player,
        "commands": cmds or [],
    }


def court_command_wrap(conn, cid, sid: str, cmds: list, player: dict | None = None, executed: bool = False) -> dict:
    request = court_command_request(conn, cid, sid, cmds, player)
    if executed:
        data = []
        for cmd in cmds or [""]:
            data.append({
                "success": True,
                "ok": True,
                "command": cmd,
                "data": "OK",
                "result": "OK",
                "output": "OK",
                "response": "OK",
                "steam_id": sid,
            })
        return {"request": request, "response": {"data": data}}
    return {"request": request, "response": None}


def resolve_home_state(prev: dict | None, at_home: bool) -> dict:
    """at_home must be TC auth (home.value from plugin), never CanBuild/can_build."""
    now = now_ms()
    prev = prev if isinstance(prev, dict) else {}
    prev_time = int(prev.get("time") or 0)
    if at_home:
        return {"value": True, "time": now}
    if prev_time:
        return {"value": False, "time": prev_time}
    return {"value": False, "time": 0}


def truthy_flag(*values) -> bool:
    for value in values:
        if value in (True, 1, "1", "true", "True", "yes", "on"):
            return True
    return False


def any_destroy_flag(obj, depth: int = 0) -> bool:
    """SPA sends destroyBuildings under target/options/bans with mixed key names."""
    if depth > 2 or not isinstance(obj, dict):
        return False
    if truthy_flag(
        obj.get("destroy_buildings"),
        obj.get("destroyBuildings"),
        obj.get("destroy_building"),
        obj.get("remove_buildings"),
        obj.get("removeBuildings"),
        obj.get("delete_buildings"),
        obj.get("wipe_buildings"),
    ):
        return True
    for key, val in obj.items():
        kn = str(key or "").lower().replace("-", "").replace("_", "")
        if "build" in kn and ("destroy" in kn or "remove" in kn or "delete" in kn or "wipe" in kn):
            if truthy_flag(val):
                return True
        if isinstance(val, dict) and key in ("target", "options", "team", "settings", "payload"):
            if any_destroy_flag(val, depth + 1):
                return True
    return False


def delete_reports(conn, where, args):
    rows = conn.execute("SELECT id,target_steam_id,project_id FROM reports WHERE "+where,args).fetchall()
    conn.execute("DELETE FROM reports WHERE "+where,args)
    projects = {}
    for row in rows:
        projects.setdefault(int(row["project_id"] or 0),[]).append(dict(row))
    for pid, items in projects.items():
        features.emit_json_webhook(conn,"report_delete",{"data":items},project_id=pid)


def enqueue_player_bans(conn, body: dict, broadcast: bool = True) -> list:
    body = body if isinstance(body, dict) else {}
    targets = []
    target = body.get("target") if isinstance(body.get("target"), dict) else {}
    main_sid = str(target.get("steamId") or target.get("steam_id") or body.get("steam_id") or "")
    team = body.get("team") if isinstance(body.get("team"), dict) else {}
    ips = body.get("ips") if isinstance(body.get("ips"), dict) else {}
    reason = str(target.get("reason") or body.get("reason") or "Ban")
    comment = str(body.get("comment") or "")
    comment_in_body = isinstance(body, dict) and "comment" in body
    expired = int(target.get("expired") or body.get("expired_at") or 0)
    if not expired and (target.get("duration") or body.get("duration")):
        expired = parse_duration(target.get("duration") or body.get("duration"))
    options = body.get("options") if isinstance(body.get("options"), dict) else {}
    destroy_main = any_destroy_flag(body) or any_destroy_flag(target) or any_destroy_flag(options)
    destroy_team = truthy_flag(
        team.get("destroy_buildings"),
        team.get("destroyBuildings"),
        body.get("team_destroy_buildings"),
        body.get("teamDestroyBuildings"),
    ) or destroy_main or any_destroy_flag(team)
    if main_sid:
        targets.append({
            "steam_id": main_sid,
            "reason": reason,
            "comment": comment,
            "ban_ip": bool(ips.get(main_sid) or target.get("ban_ip") or body.get("ban_ip")),
            "destroy_buildings": destroy_main,
        })
    if team.get("enabled"):
        team_reason = str(team.get("reason") or reason)
        for member in team.get("players") or []:
            if not isinstance(member, dict):
                continue
            sid = str(member.get("steam_id") or member.get("steamId") or "")
            if not sid or sid == main_sid:
                continue
            targets.append({
                "steam_id": sid,
                "reason": team_reason,
                "comment": comment,
                "ban_ip": bool(ips.get(sid) or team.get("ip_active")),
                "destroy_buildings": destroy_team,
            })
    bans = body.get("bans") if isinstance(body.get("bans"), list) else []
    if bans:
        targets = []
        for item in bans:
            if not isinstance(item, dict):
                continue
            sid = str(item.get("steam_id") or item.get("target_steam_id") or "")
            if not sid:
                continue
            targets.append({
                "steam_id": sid,
                "reason": str(item.get("reason") or reason),
                "comment": str(item.get("comment") or comment),
                "comment_ready": comment_in_body or ("comment" in item),
                "ban_ip": bool(
                    item.get("ban_ip")
                    or item.get("ban_ip_active")
                    or ips.get(sid)
                ),
                "destroy_buildings": truthy_flag(
                    item.get("destroy_buildings"),
                    item.get("destroyBuildings"),
                    destroy_main,
                ) or any_destroy_flag(item),
                "expired_at": int(item.get("expired_at") or expired or 0),
            })
    created = []
    for item in targets:
        sid = str(item.get("steam_id") or "")
        if not sid:
            continue
        exp = int(item.get("expired_at") or expired or 0)
        reason_text = str(item.get("reason") or reason or "Ban").strip() or "Ban"
        comment_text = str(item.get("comment") or comment or reason_text).strip()
        # SPA often sends `reason` and leaves `comment` empty. Holding the ban
        # until a comment exists skipped plugin ban/IP/destroy entirely.
        hold_comment = False
        meta = json.dumps({
            "destroy_buildings": bool(item.get("destroy_buildings")),
            "broadcast": bool(broadcast),
            "ban_ip": bool(item.get("ban_ip")),
        }, ensure_ascii=False)
        name = apply_player_ban(
            conn,
            sid,
            reason_text,
            comment_text,
            bool(item.get("ban_ip")),
            exp,
            pending=hold_comment,
            pending_meta="",
        )
        frozen = features.freeze_actor(conn)
        ban_id = 0
        try:
            brow = conn.execute(
                """SELECT id FROM bans WHERE steam_id = ? AND COALESCE(project_id, 0) = ?
                   ORDER BY id DESC LIMIT 1""",
                (sid, current_pid() or 0),
            ).fetchone()
            if brow:
                ban_id = int(brow["id"] or 0)
        except Exception:
            ban_id = 0
        if hold_comment:
            row = conn.execute(
                "SELECT * FROM bans WHERE steam_id = ? ORDER BY id DESC LIMIT 1",
                (sid,),
            ).fetchone()
            view = ban_view(conn, row) if row else {"steam_id": sid, "name": name, "reason": str(item.get("reason") or reason)}
            view["pending"] = True
            view["computed_is_active"] = True
            view["active"] = True
            created.append(view)
            continue
        admin_id = int(frozen.get("actor_user_id") or 0)
        features.notify_ban(
            conn,
            {
                "steam_id": sid,
                "name": name or sid,
                "avatar": "",
                "admin_name": str(frozen.get("actor_name") or ""),
                "admin_id": admin_id,
                "admin_avatar": features.staff_discord_avatar(conn, admin_id),
                "project_id": current_pid() or 0,
                "comment": comment_text,
                "expired_at": exp,
                "ban_id": ban_id,
            },
            str(item.get("reason") or reason),
        )
        try:
            emit_realtime(current_pid() or 0, "ban.created", {
                "playerId": sid,
                "steam_id": sid,
                "actorId": int(frozen.get("actor_user_id") or 0),
                "actorName": str(frozen.get("actor_name") or ""),
                "reason": str(item.get("reason") or reason),
            })
        except Exception:
            pass
        enqueue(
            "ban",
            {
                "steam_id": sid,
                "name": name,
                "reason": str(item.get("reason") or reason),
                "broadcast": bool(broadcast),
                "ban_ip": bool(item.get("ban_ip")),
                "destroy_buildings": bool(item.get("destroy_buildings")),
                "initiator_name": str(frozen.get("actor_name") or ""),
                "actor_name": str(frozen.get("actor_name") or ""),
                "actor_user_id": int(frozen.get("actor_user_id") or 0),
            },
            conn=conn,
        )
        enqueue("kick", {"steam_id": sid, "reason": str(item.get("reason") or reason), "announce": False}, conn=conn)
        if item.get("destroy_buildings"):
            enqueue("destroy_buildings", {"steam_id": sid}, conn=conn)
        row = conn.execute(
            "SELECT * FROM bans WHERE steam_id = ? ORDER BY id DESC LIMIT 1",
            (sid,),
        ).fetchone()
        created.append(ban_view(conn, row) if row else {"steam_id": sid, "name": name, "reason": str(item.get("reason") or reason)})
    return created


def apply_player_ban(conn, steam_id: str, reason: str = "Ban", comment: str = "", ban_ip: bool = False, expired: int = 0, pending: bool = False, pending_meta: str = "") -> str:
    sid = str(steam_id or "").strip()
    if not sid:
        return ""
    upsert_player(conn, sid)
    name = resolve_player_name(conn, sid, "")
    ip_row = conn.execute("SELECT ip FROM players WHERE steam_id = ?", (sid,)).fetchone()
    ip = ip_row["ip"] if ip_row else ""
    pid = current_pid() or 0
    frozen = features.freeze_actor(conn)
    actor_id = int(frozen.get("actor_user_id") or 0)
    actor_name = str(frozen.get("actor_name") or "")
    actor_email = str(frozen.get("actor_email") or "")
    actor_role = str(frozen.get("actor_role") or "")
    # Plugin echo of a site ban must not insert a second row with an empty/system actor.
    if pid and not pending:
        existing = rowd(conn.execute(
            """SELECT * FROM bans
               WHERE steam_id = ? AND COALESCE(project_id, 0) = ? AND active = 1 AND COALESCE(pending, 0) = 0
               ORDER BY id DESC LIMIT 1""",
            (sid, pid),
        ).fetchone())
        if existing:
            had_id = int(existing.get("actor_user_id") or 0)
            had_name = features.human_actor_name(
                existing.get("actor_name") or "", existing.get("actor_email") or "", ""
            )
            if (had_id or had_name) and not actor_id:
                finish_open_checks_as_ban(conn, sid, reason or "Бан")
                return name
            if had_id and actor_id and had_id == actor_id:
                finish_open_checks_as_ban(conn, sid, reason or "Бан")
                return name
    if pending and pid:
        old = rowd(conn.execute(
            """SELECT * FROM bans
               WHERE steam_id = ? AND COALESCE(project_id, 0) = ? AND COALESCE(pending, 0) = 1
               ORDER BY id DESC LIMIT 1""",
            (sid, pid),
        ).fetchone())
        if old:
            try:
                conn.execute(
                    """UPDATE bans SET steam_name = ?, ip = ?, reason = ?, comment = ?, ban_ip = ?, expired_at = ?,
                           pending_meta = ?, actor_user_id = ?, actor_name = ?, actor_email = ?, actor_role = ?
                       WHERE id = ?""",
                    (
                        name, ip, reason or "Ban", comment or "", 1 if ban_ip else 0, int(expired or 0),
                        str(pending_meta or ""), actor_id, actor_name, actor_email, actor_role, int(old["id"]),
                    ),
                )
            except Exception:
                conn.execute(
                    """UPDATE bans SET reason = ?, comment = ?, ban_ip = ?, expired_at = ? WHERE id = ?""",
                    (reason or "Ban", comment or "", 1 if ban_ip else 0, int(expired or 0), int(old["id"])),
                )
            return name
    active_flag = 0 if pending else 1
    pend_flag = 1 if pending else 0
    try:
        cur = conn.execute(
            """INSERT INTO bans (steam_id, steam_name, ip, reason, comment, ban_ip, created_at, expired_at, active, project_id, actor_user_id, actor_name, actor_email, actor_role, pending, pending_meta)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (sid, name, ip, reason or "Ban", comment or "", 1 if ban_ip else 0, now_ms(), int(expired or 0), active_flag, pid, actor_id, actor_name, actor_email, actor_role, pend_flag, str(pending_meta or "")),
        )
    except Exception:
        try:
            cur = conn.execute(
                """INSERT INTO bans (steam_id, steam_name, ip, reason, comment, ban_ip, created_at, expired_at, active, project_id, actor_user_id, actor_name, actor_email, actor_role)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (sid, name, ip, reason or "Ban", comment or "", 1 if ban_ip else 0, now_ms(), int(expired or 0), active_flag, pid, actor_id, actor_name, actor_email, actor_role),
            )
        except Exception:
            try:
                cur = conn.execute(
                    """INSERT INTO bans (steam_id, steam_name, ip, reason, comment, ban_ip, created_at, expired_at, active, project_id, actor_user_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (sid, name, ip, reason or "Ban", comment or "", 1 if ban_ip else 0, now_ms(), int(expired or 0), active_flag, pid, actor_id),
                )
            except Exception:
                cur = conn.execute(
                    """INSERT INTO bans (steam_id, steam_name, ip, reason, comment, ban_ip, created_at, expired_at, active, project_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (sid, name, ip, reason or "Ban", comment or "", 1 if ban_ip else 0, now_ms(), int(expired or 0), active_flag, pid),
                )
    ban_id = int(cur.lastrowid or 0)
    features.audit(conn, "ban.draft" if pending else "ban.create", {"steam_id": sid, "name": name, "reason": reason or "Ban", "ban_id": ban_id})
    if pending:
        return name
    features.lifetime_bump(conn, "bans", 1)
    try:
        opts = court_options(conn)
        if opts.get("delete_reports_after_ban"):
            delete_reports(conn,"target_steam_id = ?" + project_clause()[0], [sid, *project_clause()[1]])
    except Exception:
        pass
    finish_open_checks_as_ban(conn, sid, reason or "Бан")
    return name


def finalize_pending_ban(conn, ban_id, comment=None) -> dict:
    bid = int(ban_id or 0)
    if not bid:
        return {}
    row = rowd(conn.execute("SELECT * FROM bans WHERE id = ?", (bid,)).fetchone())
    if not row:
        return {}
    pending = False
    try:
        pending = bool(int(row.get("pending") or 0))
    except Exception:
        pending = False
    if not pending:
        return ban_view(conn, row)
    meta = {}
    try:
        raw = row.get("pending_meta") or ""
        if raw:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                meta = parsed
    except Exception:
        meta = {}
    text = row.get("comment") or ""
    if comment is not None:
        text = str(comment or "")
    try:
        conn.execute(
            "UPDATE bans SET active = 1, pending = 0, pending_meta = '', comment = ? WHERE id = ?",
            (text, bid),
        )
    except Exception:
        conn.execute("UPDATE bans SET active = 1, comment = ? WHERE id = ?", (text, bid))
    updated = rowd(conn.execute("SELECT * FROM bans WHERE id = ?", (bid,)).fetchone()) or row
    sid = str(updated.get("steam_id") or "")
    name = resolve_player_name(conn, sid, updated.get("steam_name") or "")
    reason = str(updated.get("reason") or "Ban")
    frozen = features.freeze_actor(conn)
    admin_id = int(frozen.get("actor_user_id") or updated.get("actor_user_id") or 0)
    admin_name = str(frozen.get("actor_name") or updated.get("actor_name") or "")
    features.audit(conn, "ban.create", {"steam_id": sid, "name": name, "reason": reason, "ban_id": bid, "comment": text})
    features.lifetime_bump(conn, "bans", 1)
    try:
        opts = court_options(conn)
        if opts.get("delete_reports_after_ban"):
            delete_reports(conn,"target_steam_id = ?" + project_clause()[0], [sid, *project_clause()[1]])
    except Exception:
        pass
    finish_open_checks_as_ban(conn, sid, reason or "Бан")
    features.notify_ban(
        conn,
        {
            "steam_id": sid,
            "name": name or sid,
            "admin_name": admin_name,
            "admin_id": admin_id,
            "admin_avatar": features.staff_discord_avatar(conn, admin_id),
            "project_id": int(updated.get("project_id") or current_pid() or 0),
            "comment": text,
            "expired_at": int(updated.get("expired_at") or 0),
            "ban_id": bid,
        },
        reason,
    )
    try:
        emit_realtime(current_pid() or 0, "ban.created", {
            "playerId": sid,
            "steam_id": sid,
            "actorId": admin_id,
            "actorName": admin_name,
            "reason": reason,
        })
    except Exception:
        pass
    enqueue(
        "ban",
        {
            "steam_id": sid,
            "name": name,
            "reason": reason,
            "broadcast": bool(meta.get("broadcast", True)),
            "ban_ip": bool(int(updated.get("ban_ip") or 0) or meta.get("ban_ip")),
            "destroy_buildings": bool(meta.get("destroy_buildings")),
            "initiator_name": admin_name,
            "actor_name": admin_name,
            "actor_user_id": admin_id,
        },
        conn=conn,
    )
    enqueue("kick", {"steam_id": sid, "reason": reason, "announce": False}, conn=conn)
    if meta.get("destroy_buildings"):
        enqueue("destroy_buildings", {"steam_id": sid}, conn=conn)
    return ban_view(conn, updated)


def finish_open_checks_as_ban(conn, steam_id: str, reason: str = "Бан") -> None:
    """If this player is on an open check, close it as ban — not FinishedClear."""
    sid = str(steam_id or "").strip()
    if not sid:
        return
    pid = current_pid() or 0
    try:
        rows = conn.execute(
            """SELECT id FROM checks
               WHERE steam_id = ?
                 AND COALESCE(project_id, 0) = ?
                 AND (finished_at IS NULL OR finished_at = 0)
               ORDER BY id DESC""",
            (sid, pid),
        ).fetchall()
    except Exception:
        rows = []
    now = now_ms()
    verdict = str(reason or "Бан")[:200]
    for r in rows:
        try:
            cid = int(r["id"] or 0)
        except Exception:
            cid = 0
        if not cid:
            continue
        try:
            conn.execute(
                "UPDATE checks SET status = ?, finished_at = ?, notice = 0, verdict = ? WHERE id = ?",
                ("ban", now, verdict, cid),
            )
        except Exception:
            try:
                conn.execute(
                    "UPDATE checks SET status = ?, finished_at = ? WHERE id = ?",
                    ("ban", now, cid),
                )
            except Exception:
                pass
        release_check_freeze(conn,cid)
        _activity_cache_drop(cid)
        try:
            emit_realtime(pid, "check-finished", {
                "id": cid,
                "check_id": cid,
                "status": "FinishedBan",
                "verdict": verdict,
                "steam_id": sid,
            })
        except Exception:
            pass


def cleanup_reports_after_check(conn, steam_id: str) -> None:
    sid = str(steam_id or "").strip()
    if not sid:
        return
    opts = court_options(conn)
    if opts.get("delete_reports_after_check"):
        delete_reports(conn,"target_steam_id = ?" + project_clause()[0], [sid, *project_clause()[1]])
    # Ignore future reports for configured days after check
    raw_ignore = opts.get("ignore_reports_after_check")
    days = 0
    try:
        if isinstance(raw_ignore, bool):
            days = 3650 if raw_ignore else 0
        else:
            days = int(raw_ignore or 0)
    except (TypeError, ValueError):
        days = 0
    if days > 0:
        until = now_ms() + days * 86400000
        features.ignore_reports_set(conn, sid, {"until": until})


def prune_old_reports(conn) -> None:
    opts = court_options(conn)
    try:
        days = int(opts.get("ignore_reports_after_days") or 0)
    except (TypeError, ValueError):
        days = 0
    if days <= 0:
        return
    cutoff = now_ms() - days * 86400000
    try:
        delete_reports(conn,"created_at > 0 AND created_at < ?", (cutoff,))
    except Exception:
        pass


def param_values(params, *keys) -> list:
    out = []
    seen = set()
    params = params or {}
    alts = []
    for key in keys:
        alts.append(key)
        alts.append(f"{key}[]")
        prefix = f"{key}["
        for existing in params:
            name = str(existing)
            if name == key or name == f"{key}[]" or name.startswith(prefix):
                alts.append(name)
    for alt in alts:
        vals = params.get(alt)
        if vals is None:
            continue
        if not isinstance(vals, list):
            vals = [vals]
        for item in vals:
            if item in (None, ""):
                continue
            text = str(item).strip()
            parts = [p.strip() for p in text.split(",")] if "," in text else [text]
            for part in parts:
                if part and part not in seen:
                    seen.add(part)
                    out.append(part)
    return out


def params_have_key(params, *keys) -> bool:
    params = params or {}
    for key in keys:
        prefix = f"{key}["
        for existing in params:
            name = str(existing)
            if name == key or name == f"{key}[]" or name.startswith(prefix):
                return True
    return False


def player_brief_for_ban(conn, steam_id: str) -> dict:
    """Light player stub for ban rows. Full player_view() per ban freezes the player modal."""
    sid = str(steam_id or "")
    name = sid
    avatar = PLACEHOLDER
    try:
        row = conn.execute("SELECT steam_name FROM players WHERE steam_id = ?", (sid,)).fetchone()
        if row and row["steam_name"]:
            name = str(row["steam_name"] or sid)
    except Exception:
        pass
    try:
        cached = features.read_cache(conn, "steam_cache", "steam_id", sid) if sid else None
        if isinstance(cached, dict):
            if cached.get("personaname"):
                name = str(cached.get("personaname") or name)
            if cached.get("avatar"):
                avatar = str(cached.get("avatar") or avatar)
    except Exception:
        pass
    return {
        "steam_id": sid,
        "steam_name": name or sid,
        "name": name or sid,
        "steam_avatar": avatar,
        "avatar": avatar,
        "status": "offline",
        "online": False,
        "is_online": False,
        "team": [],
    }


def ban_view(conn, row) -> dict:
    data = rowd(row) if not isinstance(row, dict) else dict(row)
    if not data:
        return {}
    sid = str(data.get("steam_id") or "")
    player = player_brief_for_ban(conn, sid) if sid else {"steam_id": "", "steam_name": "", "name": ""}
    actor_id, snap_name, snap_email, snap_role = resolved_staff_snapshot(
        conn,
        data.get("actor_name") or "",
        data.get("actor_user_id") or 0,
        data.get("actor_email") or "",
        data.get("actor_role") or "",
        data.get("project_id") or current_pid() or 0,
    )
    staff = staff_brief(
        conn,
        actor_text=snap_name,
        actor_id=actor_id,
        payload={"actor_name": snap_name, "actor_email": snap_email, "actor_role": snap_role, "actor_user_id": actor_id},
    )
    display = features.staff_public_name(
        features.user_by_id(conn, actor_id) if actor_id else None,
        snap_name, snap_email,
    ) or snap_name or features.human_actor_name(staff.get("name") or "", snap_email, "")
    if display and not features.is_generic_staff_label(display):
        staff["name"] = display
    if not staff.get("name") or features.is_generic_staff_label(staff.get("name")):
        staff["name"] = (snap_email.split("@")[0] if "@" in snap_email else "") or staff.get("name") or ""
    live_tag = features.staff_public_tag(features.user_by_id(conn, actor_id) if actor_id else None, staff.get("name") or "", conn)
    if live_tag:
        staff["tag"] = live_tag
    staff_id = int(actor_id or staff.get("id") or 0)
    if staff_id:
        staff["id"] = staff_id
    else:
        staff_id = stable_client_id(0, staff.get("name") or snap_name)
        staff["id"] = staff_id
    try:
        pid = int(data.get("project_id") or current_pid() or 0)
    except Exception:
        pid = current_pid() or 0
    active = bool(int(data.get("active") or 0))
    expired_at = int(data.get("expired_at") or 0)
    if expired_at and expired_at < now_ms():
        active = False
    ban_id = int(data.get("id") or 0)
    ip_value = str(data.get("ip") or "")
    ban_ip_flag = bool(int(data.get("ban_ip") or 0))
    reason = str(data.get("reason") or "Ban")
    comment = str(data.get("comment") or reason or "")
    steam_url = f"https://steamcommunity.com/profiles/{sid}" if sid else ""
    staff = dict(staff)
    staff["status"] = "online"
    staff["online"] = True
    staff["is_online"] = True
    if isinstance(player, dict):
        st = str(player.get("status") or "offline")
        player["status"] = st
        player["online"] = st in ("online", "active", "joining", "queued", "afk")
        player["is_online"] = bool(player["online"])
        if player.get("steam_name") is not None:
            player["name"] = player.get("steam_name") or player.get("name") or sid
    pname = project_title(conn, pid)
    return {
        "id": ban_id,
        "steam_id": sid,
        "target_steam_id": sid,
        "reason": reason,
        "comment": comment,
        "created_at": int(data.get("created_at") or now_ms()),
        "expired_at": expired_at,
        "computed_is_active": active,
        "active": active,
        "ban_ip": ip_value if ban_ip_flag else False,
        "ban_ip_active": ban_ip_flag and active,
        "proofs": [],
        "server_ids": [],
        "server_id": 0,
        "project_id": pid,
        "client_id": staff_id,
        "client": staff,
        "initiator_client": staff,
        # The ban card and the player-profile ban tab use different field
        # names in the upstream SPA.  Keep one frozen moderator object under
        # every accepted alias so the card never renders "Заблокировал:" with
        # an empty value.
        "moderator": staff,
        "moderator_client": staff,
        "banned_by_client": staff,
        "actor": staff,
        "author": staff,
        "client_tag": staff.get("tag") or "",
        "banned_by_tag": staff.get("tag") or "",
        "banned_by": staff.get("name") or snap_name or "",
        "admin_name": staff.get("name") or snap_name or "",
        "actor_name": staff.get("name") or snap_name or "",
        "actor_role": snap_role or staff.get("actor_role") or "",
        "player": player,
        "target_player": player,
        "steam_name": player.get("steam_name") or sid,
        "project_name": pname,
        "project": {"id": pid, "name": pname},
        "project_id_original": pid,
        "project_original": {"id": pid, "name": pname, "avatar": PLACEHOLDER},
        "url": steam_url,
        "link": steam_url,
        "steam_url": steam_url,
        "auto_kicked": True,
    }


def enqueue_unban(steam_id: str, conn=None, ip: str = "") -> None:
    sid = str(steam_id or "").strip()
    if not sid:
        return
    cmds = [f"unban {sid}", f"removeid {sid}"]
    ip = str(ip or "").strip()
    if ip and ip not in ("0.0.0.0", "::", "::1"):
        cmds.append(f"removeip {ip}")
        cmds.append(f"unban {ip}")
    enqueue("execute-command", {"commands": cmds}, conn=conn)


def deactivate_ban(conn, ban_id: str | int, comment: str = "") -> dict:
    pid = current_pid() or 0
    row = rowd(conn.execute(
        "SELECT * FROM bans WHERE id = ?" + (" AND project_id = ?" if pid else " AND 0=1"),
        (ban_id, pid) if pid else (ban_id,),
    ).fetchone())
    if not row:
        return {}
    try:
        if int(row.get("pending") or 0):
            conn.execute("DELETE FROM bans WHERE id = ?", (int(row.get("id") or 0),))
            return {}
    except Exception:
        pass
    sid = str(row.get("steam_id") or "")
    ip = str(row.get("ip") or "").strip()
    # Deactivate all active bans for this steam in THIS project.
    conn.execute(
        "UPDATE bans SET active = 0, ban_ip = 0 WHERE steam_id = ? AND active = 1 AND project_id = ?",
        (sid, pid),
    )
    if ip:
        conn.execute(
            "UPDATE bans SET ban_ip = 0 WHERE active = 1 AND ban_ip = 1 AND ip = ? AND project_id = ?",
            (ip, pid),
        )
        conn.execute(
            "UPDATE bans SET active = 0, ban_ip = 0 WHERE steam_id = ? AND ip = ?",
            (sid, ip),
        )
    row["active"] = 0
    row["ban_ip"] = 0
    name = resolve_player_name(conn, sid, row.get("steam_name") or "")
    features.audit(conn, "ban.delete", {
        "steam_id": sid,
        "name": name,
        "reason": row.get("reason") or "",
        "ban_id": int(row["id"]),
        "comment": comment or "",
        "action": "unban",
        "ban_ip_cleared": bool(ip),
    })
    enqueue_unban(sid, conn=conn, ip=ip)
    try:
        frozen = features.freeze_actor(conn)
        staff = features.webhook_staff_actor(conn, {
            "admin_name": frozen.get("actor_name"),
            "admin_id": frozen.get("actor_user_id"),
        })
        player = player_view(conn, sid, nest_team=False)
        features.notify_unban(
            conn,
            {
                "steam_id": sid,
                "name": name,
                "avatar": player.get("steam_avatar") or "",
                "admin_name": staff.get("name") or "",
                "admin_id": int(staff.get("id") or 0),
                "admin_avatar": staff.get("avatar") or "",
                "project_id": pid,
                "ban_id": int(row.get("id") or 0),
                "reason": str(row.get("reason") or ""),
                "ban_reason": str(row.get("reason") or ""),
            },
            comment,
        )
    except Exception as exc:
        print("unban notify failed", exc)
    return ban_view(conn, row)


def chat_flag(row, *names) -> bool:
    keys = row.keys()
    for name in names:
        if name in keys:
            return bool(row[name])
    return False


def parse_xyz(raw) -> dict:
    if isinstance(raw, dict):
        return {
            "x": float(raw.get("x") or 0),
            "y": float(raw.get("y") or 0),
            "z": float(raw.get("z") or 0),
            "time": int(raw.get("time") or 0),
        }
    nums = re.findall(r"-?\d+(?:\.\d+)?", str(raw or ""))
    if len(nums) >= 3:
        return {"x": float(nums[0]), "y": float(nums[1]), "z": float(nums[2]), "time": 0}
    return {"x": 0.0, "y": 0.0, "z": 0.0, "time": 0}


def mute_left_text(expired_at: int) -> str:
    """Short RU remaining time: 30с / 4м / 1ч / 1ч 30м / 2д."""
    expired_at = int(expired_at or 0)
    if expired_at <= 0:
        return "навсегда"
    left = max(0, int(expired_at) - now_ms())
    total_sec = max(1, int((left + 999) // 1000))
    days = total_sec // 86400
    hours = (total_sec % 86400) // 3600
    mins = (total_sec % 3600) // 60
    secs = total_sec % 60
    if days > 0:
        return f"{days}д {hours}ч" if hours else f"{days}д"
    if hours > 0:
        return f"{hours}ч {mins}м" if mins else f"{hours}ч"
    if mins > 0:
        if secs and mins < 5:
            return f"{mins}м {secs}с"
        return f"{mins}м"
    return f"{secs}с"


def upsert_player(conn, steam_id: str, steam_name: str = "", ip: str = "", language: str = "", no_license: bool = False, seen: bool = False):
    steam_id = str(steam_id or "").strip()
    if not is_real_steam_id(steam_id):
        return
    ts = now_ms()
    incoming = str(steam_name or "").strip()
    if incoming and not is_display_name(incoming, steam_id):
        incoming = ""
    exists = conn.execute("SELECT steam_id FROM players WHERE steam_id = ?", (steam_id,)).fetchone()
    if exists:
        if seen:
            conn.execute(
                """UPDATE players SET
                    steam_name = CASE WHEN ? != '' THEN ? ELSE steam_name END,
                    ip = CASE WHEN ? != '' THEN ? ELSE ip END,
                    last_seen = ?,
                    last_language = CASE WHEN ? != '' THEN ? ELSE last_language END,
                    last_no_license = ?
                   WHERE steam_id = ?""",
                (incoming, incoming, ip, ip, ts, language, language, 1 if no_license else 0, steam_id),
            )
        else:
            conn.execute(
                """UPDATE players SET
                    steam_name = CASE WHEN ? != '' THEN ? ELSE steam_name END,
                    ip = CASE WHEN ? != '' THEN ? ELSE ip END,
                    last_language = CASE WHEN ? != '' THEN ? ELSE last_language END,
                    last_no_license = ?
                   WHERE steam_id = ?""",
                (incoming, incoming, ip, ip, language, language, 1 if no_license else 0, steam_id),
            )
    else:
        if not features.can_add_player(conn, current_pid()):
            return
        pretty = incoming or steam_id
        conn.execute(
            """INSERT INTO players (steam_id, steam_name, ip, first_seen, last_seen, comment, last_language, last_no_license)
               VALUES (?, ?, ?, ?, ?, '', ?, ?)""",
            (steam_id, pretty, ip, ts, ts if seen else 0, language or "unknown", 1 if no_license else 0),
        )
        features.lifetime_bump(conn, "players", 1)
    record_player_history(conn, steam_id, incoming, ip)
    if not incoming:
        try:
            refresh_steam_async(steam_id)
        except Exception:
            pass


def record_player_history(conn, steam_id: str, steam_name: str = "", ip: str = "", created_at: int = 0):
    if not steam_id:
        return
    ts = now_ms()
    ip = str(ip or "").split(":")[0].strip()
    name = str(steam_name or "").strip()
    try:
        if ip:
            row = conn.execute(
                "SELECT count FROM player_ips WHERE steam_id = ? AND ip = ?", (steam_id, ip)
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE player_ips SET last_seen = ? WHERE steam_id = ? AND ip = ?",
                    (ts, steam_id, ip),
                )
            else:
                conn.execute(
                    "INSERT INTO player_ips (steam_id, ip, first_seen, last_seen, count) VALUES (?, ?, ?, ?, 1)",
                    (steam_id, ip, ts, ts),
                )
        if name and is_display_name(name, steam_id):
            existing = conn.execute(
                "SELECT id FROM player_names WHERE steam_id = ? AND steam_name = ? ORDER BY id DESC LIMIT 1",
                (steam_id, name),
            ).fetchone()
            created = int(created_at or ts)
            if existing:
                conn.execute("UPDATE player_names SET last_seen = ? WHERE id = ?", (ts, existing["id"]))
            else:
                conn.execute(
                    "INSERT INTO player_names (steam_id, steam_name, created_at, last_seen) VALUES (?, ?, ?, ?)",
                    (steam_id, name, created, ts),
                )
    except Exception as exc:
        print("record_player_history failed", exc)


def sync_online_sessions(conn, players: list, server_id: int = 1, project_id: int = 0):
    prev = {
        row["steam_id"]
        for row in conn.execute(
            "SELECT steam_id FROM online_players WHERE COALESCE(server_id, 1) = ?",
            (int(server_id or 1),),
        ).fetchall()
    }
    incoming = {}
    for player in players or []:
        sid = str(player.get("steam_id") or "")
        if sid:
            incoming[sid] = player
    now = now_ms()
    pid = int(project_id or current_pid() or 0)
    for sid in prev - set(incoming):
        conn.execute(
            """UPDATE player_sessions SET disconnected_at = ?, disconnected_reason = ?
               WHERE steam_id = ? AND disconnected_at = 0 AND COALESCE(server_id, 1) = ?""",
            (now, "disconnect", sid, int(server_id or 1)),
        )
        features.emit_json_webhook(conn,"player_session_ended",{"data":{"steam_id":sid,"server_id":int(server_id or 1),"disconnected_at":now}},project_id=pid)
        try:
            conn.execute("UPDATE players SET last_seen = ? WHERE steam_id = ?", (now, sid))
        except Exception:
            pass
    pid = int(project_id or current_pid() or 0)
    for sid, player in incoming.items():
        open_row = conn.execute(
            """SELECT id FROM player_sessions
               WHERE steam_id = ? AND disconnected_at = 0 AND COALESCE(server_id, 1) = ?""",
            (sid, int(server_id or 1)),
        ).fetchone()
        if sid in prev and open_row:
            continue
        if open_row:
            continue
        conn.execute(
            """INSERT INTO player_sessions (steam_id, ip, connected_at, disconnected_at, disconnected_reason, is_license, server_id, project_id)
               VALUES (?, ?, ?, 0, '', ?, ?, ?)""",
            (sid, str(player.get("ip") or "").split(":")[0], now, 0 if player.get("no_license") else 1, int(server_id or 1), pid),
        )
        features.emit_json_webhook(conn,"player_session_started",{"data":{"steam_id":sid,"server_id":int(server_id or 1),"connected_at":now,"ip":str(player.get("ip") or "")}},project_id=pid)
        ip = str(player.get("ip") or "").split(":")[0].strip()
        if ip:
            row = conn.execute("SELECT count FROM player_ips WHERE steam_id = ? AND ip = ?", (sid, ip)).fetchone()
            if row:
                conn.execute(
                    "UPDATE player_ips SET last_seen = ?, count = count + 1 WHERE steam_id = ? AND ip = ?",
                    (now, sid, ip),
                )


def active_check_for_player(conn, steam_id: str) -> dict | None:
    sid = str(steam_id or "").strip()
    if not sid:
        return None
    row = conn.execute(
        """SELECT * FROM checks
           WHERE steam_id = ?
             AND (finished_at IS NULL OR finished_at = 0)
             AND LOWER(COALESCE(status, 'active')) NOT IN ('cancel', 'canceled', 'cancelled')
             AND COALESCE(project_id, 0) = ?
           ORDER BY id DESC LIMIT 1""",
        (sid, current_pid() or 0),
    ).fetchone()
    return rowd(row) if row else None


def log_check_player_event(conn, steam_id: str, kind: str, meta: dict | None = None) -> int | None:
    check = active_check_for_player(conn, steam_id)
    if not check:
        return None
    payload = dict(meta or {})
    payload["check_id"] = int(check["id"])
    payload["steam_id"] = str(steam_id)
    payload["kind"] = str(kind)
    features.audit(conn, "check.event." + str(kind), payload)
    return int(check["id"])


def emit_check_kill_activity(
    conn, pid: int, server_id: int, initiator: str, target: str,
    weapon: str, distance: float, is_headshot: bool, bone: str,
    kill_id: int, created: int,
) -> list:
    pid = int(pid or 0)
    if not pid or not kill_id:
        return []
    init_p = activity_player_brief(conn, initiator)
    tgt_p = activity_player_brief(conn, target)
    seen_checks = set()
    items = []
    for sid in (str(initiator or ""), str(target or "")):
        if not sid:
            continue
        check = active_check_for_player(conn, sid)
        if not check:
            continue
        cid = int(check.get("id") or 0)
        if not cid or cid in seen_checks:
            continue
        seen_checks.add(cid)
        staff = mark_staff_moderator({
            "id": int(check.get("checker_id") or 0),
            "name": str(check.get("checker_name") or ""),
            "status": "online",
        })
        item = {
            "id": "kill-%s" % kill_id,
            "M_ID": int(kill_id or 0),
            "check_id": cid,
            "checkId": cid,
            "type": "PlayerKill",
            "kind": "PlayerKill",
            "created_at": int(created or now_ms()),
            "meta": {
                "initiator_steam_id": str(initiator or ""),
                "target_steam_id": str(target or ""),
                "weapon": str(weapon or ""),
                "distance": float(distance or 0),
                "is_headshot": bool(is_headshot),
                "bone": kill_bone_label(str(bone or "")),
                "steam_id": sid,
            },
            "player": init_p if sid == str(initiator or "") else tgt_p,
            "initiator_player": init_p,
            "target_player": tgt_p,
            "initiator_client": staff,
        }
        items.append(item)
    return items


def kill_bone_label(raw: str) -> str:
    bone = str(raw or "").strip()
    if not bone:
        return ""
    if bone.startswith("["):
        try:
            hist = json.loads(bone)
            if isinstance(hist, list) and hist:
                last = hist[-1]
                if isinstance(last, dict):
                    return str(last.get("bone") or bone)
        except Exception:
            pass
    return bone


def activity_player_brief(conn, steam_id: str) -> dict:
    sid = str(steam_id or "").strip()
    name = sid or "Unknown"
    if sid and sid not in ("0", "None"):
        try:
            row = conn.execute("SELECT steam_name FROM players WHERE steam_id = ?", (sid,)).fetchone()
            if row and row["steam_name"]:
                name = str(row["steam_name"])
        except Exception:
            pass
    return {
        "id": sid or "0",
        "steam_id": sid or "0",
        "steam_name": name,
        "name": name,
        "display_name": name,
        "team": [],
    }


def check_contact_activity_item(
    check_id: int,
    steam_id: str,
    name: str,
    contact_text: str,
    player: dict | None = None,
    matches: list | None = None,
    created_at: int | None = None,
) -> dict:
    """Dedicated «Получены контакты игрока» row (MessageFromPlayer + meta.is_contact)."""
    sid = str(steam_id or "")
    label = str(name or sid or "")
    brief = player if isinstance(player, dict) else {
        "id": sid or "0",
        "steam_id": sid or "0",
        "steam_name": label,
        "name": label,
        "display_name": label,
        "team": [],
    }
    related = matches if isinstance(matches, list) else []
    return {
        "id": "contact-%s" % check_id,
        "M_ID": int(check_id or 0),
        "check_id": int(check_id or 0),
        "checkId": int(check_id or 0),
        "type": "MessageFromPlayer",
        "kind": "MessageFromPlayer",
        "text": contact_text,
        "message": contact_text,
        "created_at": int(created_at or now_ms()),
        "meta": {
            "text": contact_text,
            "message": contact_text,
            "is_contact": True,
            "related_players": related,
            "matches": related,
            "match": bool(related),
            "steam_id": sid,
            "client_id": 0,
        },
        "player": brief,
        "initiator_player": brief,
        "target_player": brief,
        "initiator_client": {
            "id": 0,
            "steam_id": sid,
            "name": brief.get("steam_name") or label,
            "status": "online",
        },
    }


def append_check_game_events(conn, check: dict, sid: str, check_id: int, player: dict, staff: dict, items: list) -> None:
    if not sid:
        return
    started_at = int(check.get("started_at") or 0) or now_ms()
    finished_at = int(check.get("finished_at") or 0) or (now_ms() + 1)
    kill_rows = conn.execute(
        """SELECT * FROM kills
           WHERE created_at >= ? AND created_at <= ?
             AND (initiator_steam_id = ? OR target_steam_id = ?)
           ORDER BY id DESC LIMIT 80""",
        (started_at, finished_at, sid, sid),
    ).fetchall()
    for row in kill_rows:
        row = rowd(row)
        init_sid = str(row.get("initiator_steam_id") or "")
        tgt_sid = str(row.get("target_steam_id") or "")
        init_p = activity_player_brief(conn, init_sid)
        tgt_p = activity_player_brief(conn, tgt_sid)
        items.append({
            "id": "kill-%s" % row["id"],
            "M_ID": int(row["id"] or 0),
            "check_id": check_id,
            "checkId": check_id,
            "type": "PlayerKill",
            "kind": "PlayerKill",
            "created_at": int(row.get("created_at") or now_ms()),
            "meta": {
                "initiator_steam_id": init_sid,
                "target_steam_id": tgt_sid,
                "weapon": str(row.get("weapon") or ""),
                "distance": float(row.get("distance") or 0),
                "is_headshot": bool(row.get("is_headshot")),
                "bone": kill_bone_label(str(row.get("bone") or "")),
                "steam_id": sid,
            },
            "player": init_p if sid == init_sid else tgt_p,
            "initiator_player": init_p,
            "target_player": tgt_p,
            "initiator_client": staff,
        })
    audit_rows = conn.execute(
        """SELECT * FROM audit
           WHERE event LIKE 'check.event.%'
             AND created_at >= ?
             AND created_at <= ?
           ORDER BY id DESC LIMIT 80""",
        (int(started_at or 0) - 5000, int(finished_at or now_ms()) + 5000),
    ).fetchall()
    for row in audit_rows:
        row = rowd(row)
        try:
            payload = json.loads(row.get("payload") or "{}")
        except Exception:
            payload = {}
        if int(payload.get("check_id") or 0) != int(check_id):
            continue
        if str(payload.get("steam_id") or "") != sid:
            continue
        created = int(row.get("created_at") or now_ms())
        if started_at and created < started_at - 5000:
            continue
        if finished_at and created > finished_at + 5000:
            continue
        ev = str(row.get("event") or "").replace("check.event.", "")
        if ev in ("disconnect", "kick"):
            reason = str(payload.get("reason") or ("Kicked" if ev == "kick" else "disconnect"))
            if ev == "kick" and "kick" not in reason.lower():
                reason = "Kicked: " + reason
            items.append({
                "id": "evt-%s-%s" % (ev, row["id"]),
                "M_ID": int(row["id"] or 0),
                "check_id": check_id,
                "checkId": check_id,
                "type": "PlayerDisconnected",
                "kind": "PlayerDisconnected",
                "created_at": created,
                "meta": {"reason": reason, "steam_id": sid},
                "player": player,
                "initiator_player": player,
                "target_player": player,
                "initiator_client": staff,
            })
        elif ev == "team":
            items.append({
                "id": "evt-team-%s" % row["id"],
                "M_ID": int(row["id"] or 0),
                "check_id": check_id,
                "checkId": check_id,
                "type": "PlayerTeamChanged",
                "kind": "PlayerTeamChanged",
                "created_at": created,
                "meta": {
                    "initiator_steam_id": str(payload.get("initiator_steam_id") or sid),
                    "target_steam_id": str(payload.get("target_steam_id") or sid),
                    "steam_id": sid,
                },
                "player": player,
                "initiator_player": player,
                "target_player": player,
                "initiator_client": staff,
            })


def make_pair_code(conn, preferred: str = "", project_id: int | None = None, server_name: str = "") -> str:
    pid = int(project_id or current_pid() or 0)
    if not pid:
        return ""
    preferred = str(preferred or "").strip()
    label = str(server_name or "").strip()[:80]
    if preferred:
        row = conn.execute("SELECT code FROM pair_codes WHERE code = ?", (preferred,)).fetchone()
        if not row:
            try:
                conn.execute(
                    "INSERT INTO pair_codes (code, created_at, used, project_id, server_name) VALUES (?, ?, 0, ?, ?)",
                    (preferred, now_s(), pid, label),
                )
            except Exception:
                conn.execute(
                    "INSERT INTO pair_codes (code, created_at, used, project_id) VALUES (?, ?, 0, ?)",
                    (preferred, now_s(), pid),
                )
        else:
            try:
                conn.execute(
                    "UPDATE pair_codes SET project_id = ?, used = 0, created_at = ?, server_name = CASE WHEN ? != '' THEN ? ELSE server_name END WHERE code = ?",
                    (pid, now_s(), label, label, preferred),
                )
            except Exception:
                conn.execute(
                    "UPDATE pair_codes SET project_id = ?, used = 0, created_at = ? WHERE code = ?",
                    (pid, now_s(), preferred),
                )
        return preferred
    row = conn.execute(
        """SELECT code FROM pair_codes
           WHERE used = 0 AND created_at > ? AND (project_id = ? OR project_id IS NULL)
           ORDER BY created_at DESC LIMIT 1""",
        (now_s() - 600, pid),
    ).fetchone()
    if row:
        code = row["code"]
        if label:
            try:
                conn.execute("UPDATE pair_codes SET server_name = ? WHERE code = ?", (label, code))
            except Exception:
                pass
        return code
    code = f"{uuid.uuid4().int % 1000000:06d}"
    try:
        conn.execute(
            "INSERT INTO pair_codes (code, created_at, used, project_id, server_name) VALUES (?, ?, 0, ?, ?)",
            (code, now_s(), pid, label),
        )
    except Exception:
        conn.execute(
            "INSERT INTO pair_codes (code, created_at, used, project_id) VALUES (?, ?, 0, ?)",
            (code, now_s(), pid),
        )
    return code


def pair_code_server_name(conn, pair_code: str) -> str:
    code = str(pair_code or "").strip()
    if not code:
        return ""
    try:
        row = conn.execute("SELECT server_name FROM pair_codes WHERE code = ?", (code,)).fetchone()
        return str((row["server_name"] if row else "") or "").strip()
    except Exception:
        return ""


def server_view(conn, row) -> dict:
    row = rowd(row) if row is not None and not isinstance(row, dict) else (row or {})
    sid = int(row.get("id") or 0)
    pid = int(row.get("project_id") or current_pid() or 0)
    last = int(row.get("last_seen") or 0)
    # last_seen is unix seconds; tolerate accidental ms values
    if last > 10**12:
        last = last // 1000
    connected = server_heartbeat_ok(row)
    online = int(row.get("online") or 0) if connected else 0
    slots = int(row.get("slots") or 0) or 100
    level = row.get("level") or "Procedural Map"
    version = row.get("version") or "2.1.6"
    avatar = row.get("avatar_url") or "/local/rustlogo_dark.jpg?https=1"
    banner = row.get("banner_url") or "/local/default-banner.png?https=1"
    name = str(row.get("name") or "").strip()
    hostname = str(row.get("hostname") or "").strip()
    if name.startswith("#") and name[1:].isdigit():
        name = ""
    if hostname.startswith("#") and hostname[1:].isdigit():
        hostname = ""
    name = name or hostname or "Rust"
    state = {
        "isStable": bool(connected),
        "online": online,
        "max_online": slots,
        "active_amount": online,
        "joining_amount": 0,
        "queue_amount": 0,
        "reserved": int(row.get("reserved") or 0) if connected else 0,
        "license_amount": online,
        "pirate_amount": 0,
        "level": level,
    }
    return {
        "id": sid,
        "name": name,
        "hostname": hostname or name,
        "level": level,
        "description": row.get("description") or "",
        "avatar_url": avatar,
        "avatar_big": avatar,
        "banner_url": banner,
        "online": online,
        "slots": slots,
        "reserved": int(row.get("reserved") or 0) if connected else 0,
        "port": row.get("port") or 0,
        "version": version,
        "protocol": row.get("protocol") or "2600",
        "branch": row.get("branch") or "release",
        "performance": row.get("performance") or "0",
        "connected": bool(connected),
        "offline": not connected,
        "status": "online" if connected else "offline",
        "paired": bool(row.get("paired")),
        "full_updated": True,
        "updated": True,
        "deleted": False,
        "order": 0,
        "state": state,
        "last_seen": last,
        "project_id": pid,
        "world_size": as_int(row.get("world_size")),
        "size": as_int(row.get("world_size")),
        "seed": as_int(row.get("seed")),
        "map_image": row.get("map_image") or "",
        "image": row.get("map_image") or "",
        "M_ID": sid,
        "server_ip": features.format_server_endpoint(str(row.get("server_ip") or ""), int(row.get("port") or 0)),
        "endpoint": features.format_server_endpoint(str(row.get("server_ip") or ""), int(row.get("port") or 0)),
        "address": features.format_server_endpoint(str(row.get("server_ip") or ""), int(row.get("port") or 0)),
    }


def update_server(conn, server_id: int, body: dict) -> dict:
    body = body if isinstance(body, dict) else {}
    sid = int(server_id or 0)
    if not sid:
        return {"message": "not found"}
    row = conn.execute("SELECT * FROM servers WHERE id = ?", (sid,)).fetchone()
    if not row:
        return {"message": "not found"}
    pid = current_pid()
    row_pid = int(row["project_id"] or 0)
    if pid and row_pid and row_pid != pid:
        return {"message": "forbidden"}

    def pick(*keys):
        for key in keys:
            if key in body and body[key] is not None:
                return body[key]
        return None

    sets: list[str] = []
    vals: list = []
    name = pick("name")
    hostname = pick("hostname")
    if name is not None:
        sets.extend(["name = ?", "hostname = COALESCE(NULLIF(?, ''), hostname)"])
        vals.extend([str(name or ""), str(hostname or name or "")])
    elif hostname is not None:
        sets.append("hostname = ?")
        vals.append(str(hostname or ""))
    avatar = pick("avatar_url", "avatar_big", "avatar")
    if avatar is not None:
        av = str(avatar or "").strip()
        if av:
            sets.append("avatar_url = ?")
            vals.append(av)
    banner = pick("banner_url", "banner")
    if banner is not None:
        bn = str(banner or "").strip()
        if bn:
            sets.append("banner_url = ?")
            vals.append(bn)
    description = pick("description")
    if description is not None:
        sets.append("description = ?")
        vals.append(str(description or ""))
    level = pick("level")
    if level is not None:
        sets.append("level = COALESCE(NULLIF(?, ''), level)")
        vals.append(str(level or ""))
    if sets:
        vals.append(sid)
        conn.execute(f"UPDATE servers SET {', '.join(sets)} WHERE id = ?", vals)
        print("SERVER updated", sid, "fields", len(sets))
    updated = conn.execute("SELECT * FROM servers WHERE id = ?", (sid,)).fetchone()
    return server_view(conn, updated)


def get_server(conn, server_id=None) -> dict:
    row = None
    if server_id:
        row = conn.execute("SELECT * FROM servers WHERE id = ?", (server_id,)).fetchone()
        pid = current_pid()
        if row and pid and int(row["project_id"] or 0) != pid:
            row = None
    pid = current_pid()
    if not row and pid:
        row = conn.execute(
            """SELECT * FROM servers WHERE project_id = ? AND paired = 1
               ORDER BY last_seen DESC, id DESC LIMIT 1""",
            (pid,),
        ).fetchone()
    if not row:
        return {
            "id": 0,
            "M_ID": 0,
            "name": "",
            "hostname": "",
            "paired": False,
            "connected": False,
            "deleted": False,
            "project_id": pid or 0,
            "state": {"isStable": False, "online": 0, "max_online": 100},
        }
    return server_view(conn, row)


def report_server_payload(conn, steam_id: str = "", server_id: int = 0) -> dict:
    """Real paired server for reports — never empty so SPA does not show «Неизвестный»."""
    sid_num = 0
    try:
        sid_num = int(server_id or 0)
    except Exception:
        sid_num = 0
    if not sid_num and steam_id:
        try:
            row = conn.execute(
                "SELECT server_id FROM online_players WHERE steam_id = ? ORDER BY rowid DESC LIMIT 1",
                (str(steam_id),),
            ).fetchone()
            if row:
                sid_num = int(row["server_id"] or 0)
        except Exception:
            sid_num = 0
    srv = get_server(conn, sid_num or None)
    if not isinstance(srv, dict):
        srv = {}
    name = str(srv.get("name") or srv.get("hostname") or "").strip()
    if name.startswith("#") and name[1:].isdigit():
        name = str(srv.get("hostname") or "").strip()
    rid = int(srv.get("id") or sid_num or 0)
    if not name or not rid:
        pid = current_pid() or 0
        try:
            row = conn.execute(
                """SELECT id, name, hostname FROM servers
                   WHERE COALESCE(project_id, 0) = ? AND paired = 1
                   ORDER BY last_seen DESC, id DESC LIMIT 1""",
                (pid,),
            ).fetchone()
        except Exception:
            row = None
        if row:
            rid = rid or int(row["id"] or 0)
            name = name or str(row["name"] or row["hostname"] or "").strip()
    if not name:
        name = "Rust"
    return {
        "id": rid or 1,
        "M_ID": rid or 1,
        "name": name,
        "hostname": str(srv.get("hostname") or name),
        "title": name,
        "label": name,
        "server_name": name,
        "paired": True,
        "connected": bool(srv.get("connected")),
    }


def list_project_servers(conn) -> list:
    pid = current_pid()
    if pid:
        reconcile_duplicate_servers(conn, pid)
    if not pid:
        return []
    rows = conn.execute(
        "SELECT * FROM servers WHERE project_id = ? AND paired = 1 ORDER BY id ASC",
        (pid,),
    ).fetchall()
    return [server_view(conn, r) for r in rows]


def _payload_live_status(payload) -> str:
    if not isinstance(payload, dict):
        return "online"
    st = str(payload.get("status") or "online").strip().lower()
    if st == "active":
        return "online"
    if st in ("queue", "queueing"):
        return "queued"
    return st or "online"


def _normalize_player_presence(player: dict) -> str:
    """Keep joining/queued for «Подключается», compute AFK for «Нет на месте»."""
    if not isinstance(player, dict):
        return "online"
    st = str(player.get("status") or "online").strip().lower()
    if st in ("queue", "queueing"):
        st = "queued"
    elif st == "active":
        st = "online"
    if st in ("joining", "queued"):
        player["status"] = st
        return st
    idle = 0
    try:
        idle = int(player.get("idle_seconds") or player.get("idle") or 0)
    except (TypeError, ValueError):
        idle = 0
    moved = moved_elapsed(player.get("last_moved_seconds") or 0, True, 0)
    if idle >= 60 or moved >= 60000:
        st = "afk"
    elif st == "unstable":
        pass
    else:
        st = "online"
    player["status"] = st
    return st


def live_player_counts(conn, pid: int = 0) -> dict:
    pid = int(pid or current_pid() or 0)
    ids = project_server_ids(conn) if pid else []
    rows = []
    try:
        if ids:
            marks = ",".join("?" * len(ids))
            rows = conn.execute(
                f"SELECT steam_id, payload, server_id FROM online_players WHERE COALESCE(server_id, 1) IN ({marks})",
                ids,
            ).fetchall()
        elif pid:
            rows = conn.execute(
                "SELECT steam_id, payload, server_id FROM online_players WHERE COALESCE(project_id, 0) = ?",
                (pid,),
            ).fetchall()
    except Exception:
        rows = []
    online = joining = queued = 0
    per_server: dict[int, dict] = {}
    for row in rows:
        try:
            payload = json.loads(row["payload"] or "{}")
        except Exception:
            payload = {}
        st = _payload_live_status(payload)
        sid = int(row["server_id"] or 0)
        bucket = per_server.setdefault(sid, {"online": 0, "joining": 0, "queued": 0})
        if st == "joining":
            joining += 1
            bucket["joining"] += 1
        elif st == "queued":
            queued += 1
            bucket["queued"] += 1
        else:
            online += 1
            bucket["online"] += 1
    return {"online": online, "joining": joining, "queued": queued, "per_server": per_server}


def touch_online_peak(conn, pid: int = 0, online_now: int | None = None) -> int:
    pid = int(pid or current_pid() or 0)
    if not pid:
        return int(online_now or 0)
    if online_now is None:
        online_now = int(live_player_counts(conn, pid).get("online") or 0)
    day = time.strftime("%Y-%m-%d", time.localtime())
    key = f"peak_online_{pid}_{day}"
    prev = 0
    try:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        prev = int((row["value"] if row else 0) or 0)
    except Exception:
        prev = 0
    peak = max(prev, int(online_now or 0))
    if peak != prev:
        try:
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, str(peak)),
            )
        except Exception:
            pass
    return peak


def project_home_overview(conn) -> dict:
    pid = current_pid()
    servers = list_project_servers(conn) if pid else []
    counts = live_player_counts(conn, pid)
    per_server = counts.get("per_server") or {}
    online = int(counts.get("online") or 0)
    joining = int(counts.get("joining") or 0)
    queued = int(counts.get("queued") or 0)
    peak = touch_online_peak(conn, pid, online)
    limit = 2
    try:
        limit = int(features.project_servers_limit(conn, pid) or 2)
    except Exception:
        limit = 2
    project_name = ""
    if pid:
        try:
            prow = conn.execute("SELECT name FROM project WHERE id = ?", (pid,)).fetchone()
            project_name = str((prow["name"] if prow else "") or "")
        except Exception:
            project_name = ""
    out_servers = []
    servers_online = 0
    for srv in servers:
        sid = int(srv.get("id") or 0)
        bucket = per_server.get(sid) or {}
        live_online = int(bucket.get("online") or 0)
        live_join = int(bucket.get("joining") or 0)
        live_queue = int(bucket.get("queued") or 0)
        connected = bool(srv.get("connected"))
        if connected:
            servers_online += 1
        slots = int(srv.get("slots") or 0) or 100
        if connected:
            srv["online"] = live_online
            state = srv.get("state") if isinstance(srv.get("state"), dict) else {}
            state["online"] = live_online
            state["active_amount"] = live_online
            state["joining_amount"] = live_join
            state["queue_amount"] = live_queue
            srv["state"] = state
        out_servers.append({
            "id": sid,
            "name": srv.get("name") or srv.get("hostname") or "Rust",
            "hostname": srv.get("hostname") or srv.get("name") or "",
            "online": live_online if connected else 0,
            "slots": slots,
            "joining": live_join if connected else 0,
            "queued": live_queue if connected else 0,
            "connected": connected,
            "status": "online" if connected else "offline",
            "last_seen": int(srv.get("last_seen") or 0),
            "avatar_url": srv.get("avatar_url") or "/local/rustlogo_dark.jpg?https=1",
            "project_name": project_name,
        })
    active_bans = 0
    if pid:
        try:
            active_bans = int(
                conn.execute(
                    """SELECT COUNT(*) FROM bans
                       WHERE active = 1
                         AND COALESCE(pending, 0) = 0
                         AND COALESCE(project_id, 0) = ?""",
                    (pid,),
                ).fetchone()[0]
                or 0
            )
        except Exception:
            active_bans = 0
    return {
        "online": online,
        "peak_today": peak,
        "servers_online": servers_online,
        "active_bans": active_bans,
        "servers_limit": limit,
        "joining": joining,
        "queued": queued,
        "project_name": project_name,
        "servers": out_servers,
    }


def project_server_ids(conn) -> list[int]:
    pid = current_pid()
    if not pid:
        return []
    return [
        int(r["id"])
        for r in conn.execute(
            "SELECT id FROM servers WHERE project_id = ? AND paired = 1",
            (pid,),
        ).fetchall()
    ]


def reconcile_duplicate_servers(conn, project_id: int) -> None:
    """Retain historical records and tokens while joining identical game endpoints."""
    groups = {}
    for row in conn.execute("SELECT * FROM servers WHERE project_id = ? AND paired = 1 ORDER BY id", (int(project_id),)).fetchall():
        host, port = features.parse_server_host_port(str(row["server_ip"] or ""), int(row["port"] or 0))
        if host and port:
            groups.setdefault((host.lower(), port), []).append(dict(row))
    for rows in groups.values():
        if len(rows) < 2:
            continue
        keep = rows[0]
        latest = max(rows, key=lambda r: (int(r.get("last_seen") or 0), int(r["id"])))
        fields = [k for k in latest if k not in ("id", "name", "token", "project_id", "paired")]
        conn.execute("UPDATE servers SET " + ",".join('"'+k+'"=?' for k in fields) + " WHERE id=?", [latest[k] for k in fields] + [keep["id"]])
        image = server_map_image(latest, latest["id"])
        if image.startswith("/uploads/"):
            conn.execute("UPDATE servers SET map_image=? WHERE id=?", (image, keep["id"]))
        for old in rows[1:]:
            conn.execute("INSERT OR REPLACE INTO settings(key,value) VALUES (?,?)", (f"server_alias_{old['id']}", str(keep["id"])))
            conn.execute("UPDATE servers SET paired=0, connected=0 WHERE id=?", (old["id"],))
            for table in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
                name = str(table[0]).replace('"', '""')
                cols = {r[1] for r in conn.execute('PRAGMA table_info("'+name+'")')}
                if "server_id" in cols:
                    conn.execute('UPDATE OR IGNORE "'+name+'" SET server_id=? WHERE server_id=?', (keep["id"], old["id"]))


def upsert_paired_server(conn, project_id: int, body: dict, pair_code: str = "", remote_ip: str = "") -> str | None:
    body = body if isinstance(body, dict) else {}
    project_id = int(project_id)
    if not conn.in_transaction:
        conn.execute("BEGIN IMMEDIATE")
    reconcile_duplicate_servers(conn, project_id)
    pair_code = str(pair_code or "").strip()
    name = str(body.get("name") or body.get("hostname") or "Rust")
    wanted = pair_code_server_name(conn, pair_code)
    if wanted:
        name = wanted
    raw_endpoint = str(body.get("server_ip") or body.get("ip") or body.get("endpoint") or body.get("address") or "")
    server_ip = features.normalize_server_ip(body, str(body.get("hostname") or ""))
    if not server_ip:
        server_ip = features.pick_public_server_ip(remote_ip)
    host, parsed_port = features.parse_server_host_port(server_ip or raw_endpoint, int(body.get("port") or 0))
    if host:
        server_ip = host
    port = int(body.get("port") or 0) or parsed_port
    if server_ip and features.is_server_ip_blocked(conn, server_ip):
        features.enforce_blocked_server_ip(conn, int(project_id), server_ip)
        return "__blocked_ip__"
    existing = None
    body_token = str(body.get("token") or body.get("secret") or "").strip()
    if len(body_token) >= 16:
        existing = conn.execute(
            "SELECT id, token FROM servers WHERE token = ? AND COALESCE(project_id, 0) = ?",
            (body_token, project_id),
        ).fetchone()
    if existing is None and host and port:
        existing = conn.execute(
            """SELECT id, token FROM servers
               WHERE COALESCE(project_id, 0) = ? AND server_ip = ? AND port = ? AND paired = 1
               ORDER BY id ASC LIMIT 1""",
            (project_id, host, port),
        ).fetchone()
    if existing is None and pair_code:
        trow = conn.execute("SELECT value FROM settings WHERE key = ?", (f"pair_token_{pair_code}",)).fetchone()
        tok = str((trow["value"] if trow else "") or "").strip()
        if len(tok) >= 16:
            existing = conn.execute("SELECT id, token FROM servers WHERE token = ?", (tok,)).fetchone()
    if existing is None and not features.can_add_server(conn, project_id):
        return None
    token = str((existing["token"] if existing else "") or "").strip()
    if len(token) < 16:
        token = uuid.uuid4().hex + uuid.uuid4().hex
    values = (
        name,
        str(body.get("hostname") or ""),
        str(body.get("level") or ""),
        str(body.get("description") or ""),
        str(body.get("avatar_url") or body.get("avatar_big") or ""),
        str(body.get("banner_url") or ""),
        int(body.get("online") or 0),
        int(body.get("slots") or 0),
        int(port or 0),
        str(body.get("version") or ""),
        str(body.get("protocol") or ""),
        token,
        now_s(),
        int(project_id),
        server_ip,
    )
    sid = 0
    is_new = existing is None
    if existing:
        sid = int(existing["id"])
        alias = conn.execute("SELECT value FROM settings WHERE key=?", (f"server_alias_{sid}",)).fetchone()
        if alias:
            sid = int(alias["value"])
            actual = conn.execute("SELECT token FROM servers WHERE id=?", (sid,)).fetchone()
            token = str(actual["token"])
            values = values[:11] + (token,) + values[12:]
        old_name = conn.execute("SELECT name FROM servers WHERE id=?", (sid,)).fetchone()
        if not wanted and old_name and old_name["name"]:
            values = (old_name["name"],) + values[1:]
        conn.execute(
            """UPDATE servers SET name=?, hostname=?, level=?, description=?, avatar_url=?, banner_url=?,
                online=?, slots=?, port=?, version=?, protocol=?, token=?, paired=1, connected=1, last_seen=?, project_id=?, server_ip=?
               WHERE id=?""",
            values + (sid,),
        )
    else:
        conn.execute(
            """INSERT INTO servers (name, hostname, level, description, avatar_url, banner_url,
                online, slots, port, version, protocol, token, paired, connected, last_seen, project_id, server_ip)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 1, ?, ?, ?)""",
            values,
        )
        sid = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    if server_ip:
        features.sync_server_ip_registry(conn, int(project_id), sid, server_ip)
        if features.enforce_blocked_server_ip(conn, int(project_id), server_ip):
            return "__blocked_ip__"
        features.apply_ip_frozen_sibling(conn, int(project_id), server_ip)
    if pair_code and token:
        try:
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (f"pair_token_{pair_code}", token),
            )
        except Exception:
            pass
    if is_new:
        try:
            prow = conn.execute("SELECT name FROM project WHERE id = ?", (int(project_id),)).fetchone()
            features.notify_new_server(
                str((prow["name"] if prow else "") or ""),
                int(project_id),
                name,
                server_ip,
                int(port or 0),
            )
        except Exception:
            pass
    return token


def parse_vec(value, ts: int = 0) -> dict:
    out = {"x": 0.0, "y": 0.0, "z": 0.0, "time": 0}
    if isinstance(value, dict):
        try:
            out["x"] = float(value.get("x") or 0)
            out["y"] = float(value.get("y") or 0)
            out["z"] = float(value.get("z") or 0)
        except (TypeError, ValueError):
            pass
        try:
            out["time"] = int(value.get("time") or ts or 0)
        except (TypeError, ValueError):
            out["time"] = ts
        return out
    if isinstance(value, str) and value.strip():
        parts = value.replace("(", "").replace(")", "").split(",")
        try:
            if len(parts) >= 3:
                out["x"] = float(parts[0])
                out["y"] = float(parts[1])
                out["z"] = float(parts[2])
                out["time"] = ts
        except ValueError:
            pass
    return out


def normalize_meta(meta) -> dict:
    if not isinstance(meta, dict):
        return {"tags": {}, "fields": {}}
    tags = meta.get("tags")
    if isinstance(tags, list):
        mapped = {}
        for i, tag in enumerate(tags):
            if isinstance(tag, dict):
                mapped[str(tag.get("key") or tag.get("name") or i)] = tag
            elif tag:
                mapped[str(i)] = {"value": str(tag)}
        tags = mapped
    elif not isinstance(tags, dict):
        tags = {}
    fields = meta.get("fields")
    if not isinstance(fields, dict):
        fields = {}
    else:
        normalized_fields = {}
        for key, val in fields.items():
            if isinstance(val, dict):
                if "value" not in val:
                    normalized_fields[str(key)] = {"value": str(val.get("text") or val.get("name") or "")}
                else:
                    normalized_fields[str(key)] = val
            elif val is not None and val != "":
                normalized_fields[str(key)] = {"value": str(val)}
        fields = normalized_fields
    # Normalize tag entries to {value: ...} shape SPA expects
    if isinstance(tags, dict):
        normalized_tags = {}
        for key, val in tags.items():
            if isinstance(val, dict):
                if "value" not in val:
                    normalized_tags[str(key)] = {"value": str(val.get("text") or val.get("name") or key)}
                else:
                    normalized_tags[str(key)] = val
            elif val is not None and val != "":
                normalized_tags[str(key)] = {"value": str(val)}
            else:
                normalized_tags[str(key)] = {"value": str(key)}
        tags = normalized_tags
    return {"tags": tags, "fields": fields}


def steam_data_obj(name: str, extra: dict | None = None) -> dict:
    now = now_ms()
    # Match working Checkapp check-window player card: hours as 0, never unavailable.
    data = {
        "visible": True,
        "profile_filled": True,
        "avatar": PLACEHOLDER,
        "personaname": name,
        "signed_at": 0,
        "updated_at": now,
        "rust_hours_total": 0,
        "rust_hours_2week": 0,
        "spacewar_hours_total": 0,
        "spacewar_hours_2week": 0,
        "hours_closed_at": None,
        "complete": False,
        "unavailable": False,
        "ban_data": {
            "days_since_last_ban": 0,
            "game_ban": {"count": 0},
            "vac_ban": {"count": 0},
        },
    }
    if isinstance(extra, dict):
        bans = extra.get("ban_data") if isinstance(extra.get("ban_data"), dict) else {}
        skip_meta = {"ban_data", "_stale", "_fetched_at", "pending", "lookup_failed"}
        data.update({k: extra[k] for k in extra if k not in skip_meta})
        def _ban_count(node):
            if not isinstance(node, dict):
                return 0
            raw = node.get("count")
            if raw in (None, "", False):
                return 0
            try:
                return int(raw)
            except (TypeError, ValueError):
                return 0
        data["ban_data"] = {
            "days_since_last_ban": int((bans.get("days_since_last_ban") if bans else 0) or 0),
            "game_ban": {"count": _ban_count(bans.get("game_ban") if bans else None)},
            "vac_ban": {"count": _ban_count(bans.get("vac_ban") if bans else None)},
        }
        data["unavailable"] = False
        data["profile_filled"] = True
        if extra.get("avatar"):
            data["avatar"] = extra["avatar"]
        if extra.get("signed_at"):
            signed = int(extra["signed_at"])
            if 0 < signed < 10_000_000_000:
                signed *= 1000
            data["signed_at"] = signed
    if not data.get("updated_at"):
        data["updated_at"] = now
    if isinstance(extra, dict) and "hours_closed_at" in extra:
        data["hours_closed_at"] = extra.get("hours_closed_at")
    elif isinstance(extra, dict) and extra.get("complete"):
        data["hours_closed_at"] = None
    if extra is not None and "visible" in extra:
        data["visible"] = bool(extra.get("visible"))
    if extra is not None and "profile_filled" in extra:
        data["profile_filled"] = bool(extra.get("profile_filled"))
    data["unavailable"] = False
    return data


def as_coords(raw) -> dict:
    if isinstance(raw, dict):
        value = raw.get("value") or raw.get("grid") or raw.get("square") or raw.get("coords") or ""
        return {"value": str(value or ""), "grid": str(value or ""), "square": str(value or "")}
    text = str(raw or "").strip()
    return {"value": text, "grid": text, "square": text}


def rust_grid(x: float, z: float, world: float = 3000.0) -> str:
    chars = list("ABCDEFGHIJKLMNOPQRSTUVWXYZ") + [
        "AA", "AB", "AC", "AD", "AE", "AF", "AG", "AH", "AI", "AJ", "AK", "AL",
        "AM", "AN", "AO", "AP", "AQ", "AR", "AS", "AT", "AU", "AV", "AW", "AX", "AY", "AZ",
    ]
    block = 146.0
    try:
        world = float(world or 3000.0)
    except Exception:
        world = 3000.0
    if world < 200:
        world = 3000.0
    offset = world / 2.0
    maxgrid = max(1, int(world / block))
    xcoord = min(maxgrid - 1, max(0, int((x + offset) / block)))
    zcoord = min(maxgrid - 1, max(0, int(maxgrid - ((z + offset) / block))))
    prefix = chars[xcoord] if xcoord < len(chars) else str(xcoord)
    return f"{prefix}{zcoord}"


def local_ip_details(ip: str) -> dict:
    ip = str(ip or "127.0.0.1")
    return {
        "ip": ip,
        "country": "Локальная сеть",
        "country_name": "Локальная сеть",
        "city": "LAN",
        "isp": "Loopback" if ip in ("127.0.0.1", "::1", "localhost") else "Private network",
        "provider": "Loopback" if ip in ("127.0.0.1", "::1", "localhost") else "Private network",
        "org": "LAN",
        "proxy": False,
        "country_code": "",
        "updated_at": now_ms(),
    }


COUNTRY_NAMES = {
    "ru": "Россия", "ua": "Украина", "by": "Беларусь", "kz": "Казахстан",
    "us": "United States", "de": "Germany", "tr": "Turkey", "cn": "China",
    "gb": "United Kingdom", "pl": "Poland", "nl": "Netherlands", "fi": "Finland",
    "ee": "Estonia", "lv": "Latvia", "lt": "Lithuania", "ge": "Georgia",
    "az": "Azerbaijan", "am": "Armenia", "uz": "Uzbekistan", "kg": "Kyrgyzstan",
    "md": "Moldova", "cz": "Czechia", "sk": "Slovakia", "ro": "Romania",
    "bg": "Bulgaria", "hu": "Hungary", "fr": "France", "it": "Italy",
    "es": "Spain", "br": "Brazil", "in": "India", "jp": "Japan", "kr": "South Korea",
}


def header_country(handler) -> tuple[str, str]:
    """Cloudflare / nginx country for the current request. Instant, no GeoIP wait."""
    if handler is None:
        return "", ""
    headers = getattr(handler, "headers", None) or {}
    code = ""
    for name in ("CF-IPCountry", "cf-ipcountry", "X-Country-Code", "X-Geo-Country", "CloudFront-Viewer-Country"):
        try:
            raw = headers.get(name)
        except Exception:
            raw = None
        if raw:
            code = str(raw).strip().lower()
            break
    if code in ("", "xx", "t1", "un", "unknown"):
        return "", ""
    return COUNTRY_NAMES.get(code) or code.upper(), code


def geo_display(geo, ip: str = "") -> tuple[str, str, str, str]:
    """Country / city / provider / code. Never emit country_code 'un' (SPA → «Неизвестно»)."""
    geo = geo if isinstance(geo, dict) else {}
    ip = str(ip or geo.get("ip") or "")
    country = str(geo.get("country_name") or geo.get("country") or "").strip()
    city = str(geo.get("city") or "").strip()
    provider = str(geo.get("provider") or geo.get("isp") or "").strip()
    code = str(geo.get("country_code") or "").strip().lower()
    if code in ("un", "xx", "unknown", "неизвестно"):
        code = ""
    if country.lower() in ("unknown", "неизвестно", "unavailable", "pending"):
        country = ""
    if len(country) == 2 and country.isalpha():
        code = code or country.lower()
        country = COUNTRY_NAMES.get(code) or country.upper()
    if not country and len(code) == 2:
        country = COUNTRY_NAMES.get(code) or code.upper()
    if (not country) and features._is_private_ip(ip):
        local = local_ip_details(ip)
        country = str(local.get("country_name") or "Локальная сеть")
        city = city or str(local.get("city") or "")
        provider = provider or str(local.get("provider") or "")
        code = ""
    if country.lower() in ("local network", "lan"):
        country = "Локальная сеть"
        code = ""
    return country, city, provider, code


def court_payload(conn) -> dict:
    servers = list_project_servers(conn)
    pid = current_pid() or 0
    blocked = bool(pid) and features.project_is_blocked(conn, pid)
    me = None
    try:
        me = client_obj(conn)
    except Exception:
        me = None
    if not isinstance(me, dict):
        me = {"id": 0, "name": "", "tag": "", "avatar": PLACEHOLDER, "status": "online"}
    if not me.get("avatar"):
        me["avatar"] = PLACEHOLDER
    return {
        "created_at": now_ms(),
        "project_id": pid,
        "is_banned": blocked,
        "servers": servers,
        "options": court_options(conn),
        "client": me,
    }


_STEAM_FETCHING = set()
_STEAM_LOCK = threading.Lock()
# Steam returns HTTP 429 when the same incomplete profile is requested over and
# over again.  Keep a short per-player backoff even when a request fails, so a
# busy plugin state feed cannot create hundreds of external requests.
_STEAM_LAST_ATTEMPT = {}
_STEAM_REFRESH_COOLDOWN_SECONDS = 15 * 60
_IP_FETCHING = set()
_IP_LOCK = threading.Lock()


def refresh_ip_async(ip: str, project_id: int = 0) -> None:
    ip = str(ip or "").split(":")[0].strip()
    if not ip:
        return
    with _IP_LOCK:
        if ip in _IP_FETCHING:
            return
        _IP_FETCHING.add(ip)

    def _run():
        try:
            data = features.fetch_ip_geo(ip) or {}
            if isinstance(data, dict) and not data.get("lookup_failed"):
                def _save(conn):
                    features.write_cache(conn, "ip_cache", "ip", ip, data)
                db_call(_save)
                pid = int(project_id or 0)
                if pid:
                    emit_realtime(pid, "ip.updated", {
                        "ip": ip,
                        "country": data.get("country_name") or data.get("country") or "",
                        "city": data.get("city") or "",
                        "isp": data.get("isp") or data.get("provider") or "",
                        "provider": data.get("provider") or data.get("isp") or "",
                        "projectId": pid,
                    })
        except Exception as exc:
            print("ip geo async failed", ip, type(exc).__name__, exc)
        finally:
            with _IP_LOCK:
                _IP_FETCHING.discard(ip)

    threading.Thread(target=_run, daemon=True).start()


def refresh_steam_async(sid: str, project_id: int = 0) -> None:
    sid = str(sid or "")
    if not sid.isdigit():
        return
    with _STEAM_LOCK:
        if sid in _STEAM_FETCHING:
            return
        now = time.monotonic()
        if now - float(_STEAM_LAST_ATTEMPT.get(sid) or 0) < _STEAM_REFRESH_COOLDOWN_SECONDS:
            return
        _STEAM_LAST_ATTEMPT[sid] = now
        # Bound memory on long-running installations.
        if len(_STEAM_LAST_ATTEMPT) > 10000:
            cutoff = now - _STEAM_REFRESH_COOLDOWN_SECONDS
            for stale_sid, attempted_at in list(_STEAM_LAST_ATTEMPT.items()):
                if attempted_at < cutoff:
                    _STEAM_LAST_ATTEMPT.pop(stale_sid, None)
        _STEAM_FETCHING.add(sid)

    def _run():
        try:
            steam = features.fetch_steam_profile(sid) or {}

            def _save(conn):
                prev = features.read_cache(conn, "steam_cache", "steam_id", sid) or {}
                if not isinstance(prev, dict):
                    prev = {}
                persona = str(steam.get("personaname") or "").strip()
                if not is_display_name(persona, sid):
                    old = str((prev or {}).get("personaname") or "").strip()
                    if is_display_name(old, sid):
                        steam["personaname"] = old
                        persona = old
                    else:
                        steam["personaname"] = ""
                # Preserve real Steam account age / Rust hours if this fetch missed them
                prev_signed = int(prev.get("signed_at") or 0)
                new_signed = int(steam.get("signed_at") or 0)
                if prev_signed > 10_000_000_000 and (not new_signed or new_signed < 10_000_000_000):
                    steam["signed_at"] = prev_signed
                    steam["signed_from_steam"] = bool(prev.get("signed_from_steam") or True)
                elif 0 < new_signed < 10_000_000_000:
                    # Steam sometimes confused as seconds — store as ms
                    steam["signed_at"] = new_signed * 1000
                    steam["signed_from_steam"] = True
                if float(prev.get("rust_hours_total") or 0) > 0 and not float(steam.get("rust_hours_total") or 0):
                    if not steam.get("hours_closed_at"):
                        steam["rust_hours_total"] = prev.get("rust_hours_total")
                        steam["rust_hours_2week"] = prev.get("rust_hours_2week") or 0
                        if prev.get("complete"):
                            steam["complete"] = True
                if is_display_name(persona, sid):
                    conn.execute(
                        """UPDATE players SET steam_name = ?
                           WHERE steam_id = ? AND (steam_name = '' OR steam_name = ?)""",
                        (persona, sid, sid),
                    )
                    record_player_history(conn, sid, persona, "")
                owns = steam.get("owns_rust")
                if owns is True:
                    conn.execute("UPDATE players SET last_no_license = 0 WHERE steam_id = ?", (sid,))
                elif owns is False:
                    conn.execute("UPDATE players SET last_no_license = 1 WHERE steam_id = ?", (sid,))
                for alias in steam.get("aliases") or []:
                    if not isinstance(alias, dict):
                        continue
                    alias_name = str(alias.get("name") or "").strip()
                    if is_display_name(alias_name, sid):
                        record_player_history(conn, sid, alias_name, "", int(alias.get("created_at") or 0))
                features.write_cache(conn, "steam_cache", "steam_id", sid, steam)
                payload = {}
                online = None
                try:
                    online = conn.execute("SELECT payload, project_id FROM online_players WHERE steam_id = ?", (sid,)).fetchone()
                except Exception:
                    online = conn.execute("SELECT payload FROM online_players WHERE steam_id = ?", (sid,)).fetchone()
                if online:
                    try:
                        payload = json.loads(online["payload"] or "{}")
                    except Exception:
                        payload = {}
                pid = int(project_id or 0)
                if not pid and online:
                    try:
                        pid = int(online["project_id"] or 0)
                    except Exception:
                        pid = 0
                if not pid:
                    try:
                        pid = int((payload or {}).get("project_id") or 0)
                    except Exception:
                        pid = 0
                return features.apply_autokick(conn, sid, payload if isinstance(payload, dict) else {}, project_id=pid)

            hit = db_call(_save)
            if hit:
                enqueue("kick", {"steam_id": hit.get("steam_id") or sid, "reason": hit.get("reason") or "Auto-kick", "announce": False}, project_id=hit.get("project_id"))
            try:
                pid = current_pid() or 0
                emit_realtime(pid, "steam.updated", {"steamId": sid, "playerId": sid, **{k: steam.get(k) for k in ("personaname", "avatar", "signed_at", "rust_hours_total", "rust_hours_2week", "complete", "privacy")}})
            except Exception:
                pass
        except Exception as exc:
            print("steam refresh failed", sid, type(exc).__name__)
        finally:
            with _STEAM_LOCK:
                _STEAM_FETCHING.discard(sid)

    threading.Thread(target=_run, daemon=True).start()


def enrich_player_live(player: dict) -> dict:
    if not isinstance(player, dict):
        return player
    sid = str(player.get("steam_id") or player.get("id") or "")
    ip = str(player.get("ip") or (player.get("ip_details") or {}).get("ip") or "")
    name = player.get("steam_name") or player.get("name") or sid
    steam = db_call(lambda c: features.read_cache(c, "steam_cache", "steam_id", sid)) if sid else None
    persona = str((steam or {}).get("personaname") or "").strip()
    if sid and (not steam or not is_display_name(persona, sid)):
        refresh_steam_async(sid)
    geo = None
    if ip:
        geo = db_call(lambda c: features.ensure_ip_geo(c, ip, blocking=False))
        if isinstance(geo, dict):
            geo.pop("pending", None)
            if geo.get("lookup_failed") or features._geo_is_placeholder(geo):
                refresh_ip_async(ip, current_pid() or 0)
    player["steam"] = True
    player["steam_data"] = steam_data_obj(name, steam)
    if not player["steam_data"].get("avatar"):
        player["steam_data"]["avatar"] = player.get("steam_avatar") or PLACEHOLDER
    if steam and steam.get("avatar"):
        player["steam_avatar"] = steam["avatar"]
        player["steam_data"]["avatar"] = steam["avatar"]
    local_av = UPLOADS / f"steam-{sid}.jpg"
    if sid and local_av.exists() and local_av.stat().st_size > 200:
        player["steam_avatar"] = f"/uploads/{local_av.name}"
        if isinstance(player.get("steam_data"), dict):
            player["steam_data"]["avatar"] = player["steam_avatar"]
    # Never keep broken /uploads/steam-* that 404 (SPA stuck on skeleton)
    av = str(player.get("steam_avatar") or "")
    if "/uploads/steam-" in av and not (local_av.exists() and local_av.stat().st_size > 200):
        fallback = ""
        if steam and steam.get("avatar") and "/uploads/" not in str(steam.get("avatar")):
            fallback = str(steam.get("avatar"))
        player["steam_avatar"] = fallback or PLACEHOLDER
        if isinstance(player.get("steam_data"), dict):
            player["steam_data"]["avatar"] = player["steam_avatar"]
            player["steam_data"]["avatarfull"] = player["steam_avatar"]
    # Keep signed_at from Steam cache; do not zero it while fetch is in flight
    if isinstance(player.get("steam_data"), dict) and steam and steam.get("signed_at"):
        player["steam_data"]["signed_at"] = int(steam["signed_at"])
    player["ip_details"] = geo if isinstance(geo, dict) else local_ip_details(ip)
    player["country"] = player["ip_details"].get("country_name") or player["ip_details"].get("country") or ""
    player["city"] = player["ip_details"].get("city") or ""
    player["isp"] = player["ip_details"].get("provider") or player["ip_details"].get("isp") or ""
    entity = player.get("entity") if isinstance(player.get("entity"), dict) else {}
    coords = as_coords(entity.get("coords") or player.get("coords"))
    if not coords.get("value"):
        pos = entity.get("position") if isinstance(entity.get("position"), dict) else player.get("position")
        if isinstance(pos, dict) and (pos.get("x") or pos.get("z")):
            coords = as_coords(rust_grid(float(pos.get("x") or 0), float(pos.get("z") or 0)))
    entity["coords"] = coords
    player["coords"] = coords
    player["grid"] = coords.get("value") or ""
    player["square"] = coords.get("value") or ""
    entity["grid"] = player["grid"]
    entity["square"] = player["square"]
    pos = entity.get("position") if isinstance(entity.get("position"), dict) else {}
    moved = moved_elapsed(entity.get("last_moved_seconds"), player.get("status") in ("online", "active", "joining", "afk"), int(pos.get("time") or 0))
    entity["last_moved_seconds"] = moved
    # Never keep AFK/online when there is no live presence / server offline
    # Keep joining/queued so UI shows «Подключается» / «в очереди»
    srv = player.get("server") if isinstance(player.get("server"), dict) else None
    if (
        player.get("status") not in ("joining", "queued")
        and srv
        and (srv.get("offline") or srv.get("connected") is False or srv.get("status") == "offline")
    ):
        player["status"] = "offline"
    if player.get("status") not in ("online", "active", "joining", "queued", "afk"):
        player["status"] = "offline"
    elif player.get("status") in ("joining", "queued"):
        # Never rewrite connecting / queue into AFK («нет на месте»)
        pass
    else:
        try:
            idle = int(player.get("idle_seconds") or entity.get("idle_seconds") or 0)
        except (TypeError, ValueError):
            idle = 0
        if player.get("status") in ("online", "active", "afk") and (moved >= 60000 or idle >= 60):
            player["status"] = "afk"
        elif player.get("status") == "afk" and moved < 60000 and idle < 60:
            player["status"] = "online"
    home = entity.get("home") if isinstance(entity.get("home"), dict) else {}
    home = {"value": bool(home.get("value")), "time": int(home.get("time") or 0)}
    entity["home"] = home
    player["home"] = home
    player["entity"] = entity
    persona = str((steam or {}).get("personaname") or "").strip()
    current_name = str(player.get("steam_name") or player.get("name") or "").strip()
    pretty = current_name if is_display_name(current_name, sid) else ""
    if not pretty and sid:
        pretty = db_call(lambda c: resolve_player_name(c, sid, persona or current_name))
    if pretty:
        player["steam_name"] = pretty
        player["name"] = pretty
        player["display_name"] = pretty
        if isinstance(player.get("steam_data"), dict):
            player["steam_data"]["personaname"] = pretty
    if isinstance(player.get("steam_data"), dict) and steam and steam.get("signed_at"):
        player["steam_data"]["signed_at"] = int(steam["signed_at"])
    if not isinstance(player.get("server"), dict):
        sid_num = int(player.get("server_id") or 0)
        try:
            player["server"] = db_call(lambda c: get_server(c, sid_num or None))
        except Exception:
            player["server"] = {"id": sid_num or 1, "name": player.get("server_name") or "", "hostname": player.get("server_name") or ""}
    if player.get("server_id") in (None, 0, "0"):
        player["server_id"] = int((player.get("server") or {}).get("id") or 1) or 1
    return player


def enrich_signage_names(conn, items):
    out = []
    for row in items or []:
        if not isinstance(row, dict):
            continue
        item = dict(row)
        sid = str(item.get("steam_id") or "")
        pretty = resolve_player_name(conn, sid, "") if sid else ""
        if pretty:
            item["steam_name"] = pretty
            item["name"] = pretty
            item["player"] = dict(item.get("player") or {})
            item["player"]["steam_id"] = sid
            item["player"]["steam_name"] = pretty
            item["player"]["name"] = pretty
        variants = item.get("variants")
        if isinstance(variants, list):
            fixed = []
            for v in variants:
                if not isinstance(v, dict):
                    continue
                vv = dict(v)
                vsid = str(vv.get("steam_id") or sid)
                vpretty = resolve_player_name(conn, vsid, pretty) if vsid else pretty
                if vpretty:
                    vv["steam_name"] = vpretty
                    vv["name"] = vpretty
                    vv["player"] = dict(vv.get("player") or {})
                    vv["player"]["steam_id"] = vsid
                    vv["player"]["steam_name"] = vpretty
                    vv["player"]["name"] = vpretty
                # SPA map parser calls .match on position — keep string
                pos = vv.get("position")
                if isinstance(pos, dict):
                    vv["position"] = json.dumps(pos, ensure_ascii=False)
                elif pos is None:
                    vv["position"] = ""
                else:
                    vv["position"] = str(pos)
                fixed.append(vv)
            item["variants"] = fixed
        pos = item.get("position")
        if isinstance(pos, dict):
            item["position"] = json.dumps(pos, ensure_ascii=False)
        elif pos is None:
            item["position"] = ""
        else:
            item["position"] = str(pos)
        out.append(item)
    return out


def team_ids_of(raw) -> list[str]:
    ids = []
    if not raw:
        return ids
    if isinstance(raw, dict):
        raw = raw.get("members") or raw.get("players") or raw.get("teammates") or raw.get("team") or []
    if not isinstance(raw, list):
        raw = [raw]
    for item in raw:
        if isinstance(item, dict):
            sid = str(
                item.get("steam_id")
                or item.get("steamId")
                or item.get("userid")
                or item.get("userId")
                or item.get("id")
                or ""
            ).strip()
            if sid:
                ids.append(sid)
        elif item not in (None, ""):
            ids.append(str(item).strip())
    return [x for x in ids if x]


def resolve_player_last_online(conn, steam_id: str, alive: bool, stored_last=0) -> int:
    """Last real join/leave from a server session. Never first_seen / chat last_seen."""
    sid = str(steam_id or "")
    pid = current_pid() or 0
    if not sid or not pid:
        return 0
    try:
        ids = project_server_ids(conn) or []
        if ids:
            marks = ",".join("?" * len(ids))
            row = conn.execute(
                f"""SELECT connected_at, disconnected_at FROM player_sessions
                    WHERE steam_id = ? AND (COALESCE(project_id, 0) = ? OR COALESCE(server_id, 1) IN ({marks}))
                    ORDER BY id DESC LIMIT 1""",
                [sid, pid, *ids],
            ).fetchone()
        else:
            row = conn.execute(
                """SELECT connected_at, disconnected_at FROM player_sessions
                   WHERE steam_id = ? AND COALESCE(project_id, 0) = ?
                   ORDER BY id DESC LIMIT 1""",
                (sid, pid),
            ).fetchone()
    except Exception:
        row = None
    if not row:
        return 0
    ts = int(row["disconnected_at"] or 0) or int(row["connected_at"] or 0)
    if ts <= 0:
        return 0
    if 10**9 <= ts < 10**12:
        ts *= 1000
    now = now_ms()
    if ts < 10**12 or ts > now + 60000:
        return 0
    return ts


def session_connected_fields(conn, steam_id: str, alive: bool, payload: dict | None) -> tuple[int, int]:
    """Duration seconds + join time in ms. Never epoch / 57 years when the player is online."""
    now = now_ms()
    payload = payload if isinstance(payload, dict) else {}
    try:
        seconds = int(payload.get("seconds_connected") or 0)
    except Exception:
        seconds = 0
    if seconds >= 10**12:
        seconds = max(0, int((now - seconds) / 1000))
    elif seconds >= 10**9:
        seconds = max(0, int(now / 1000) - seconds)
    if seconds < 0 or seconds > 14 * 86400:
        seconds = 0
    connected_at = 0
    if not alive:
        # SPA: O = seconds_connected ? now-seconds*1e3 : connected_at
        # connected_at=0 → Date(0) → «57 лет на сервере». Use now so duration is 0.
        return 0, now
    pid = current_pid() or 0
    try:
        ids = project_server_ids(conn) or []
        row = None
        if pid and ids:
            marks = ",".join("?" * len(ids))
            row = conn.execute(
                f"""SELECT connected_at FROM player_sessions
                    WHERE steam_id = ? AND disconnected_at = 0
                      AND (COALESCE(project_id, 0) = ? OR COALESCE(server_id, 1) IN ({marks}))
                    ORDER BY id DESC LIMIT 1""",
                [str(steam_id or ""), pid, *ids],
            ).fetchone()
        elif pid:
            row = conn.execute(
                """SELECT connected_at FROM player_sessions
                   WHERE steam_id = ? AND disconnected_at = 0 AND COALESCE(project_id, 0) = ?
                   ORDER BY id DESC LIMIT 1""",
                (str(steam_id or ""), pid),
            ).fetchone()
        if row:
            connected_at = int(row["connected_at"] or 0)
    except Exception:
        connected_at = 0
    if 10**9 <= connected_at < 10**12:
        connected_at *= 1000
    if connected_at > now:
        connected_at = now
    if connected_at and connected_at < now - 14 * 86400 * 1000:
        connected_at = 0
    if seconds <= 0 and connected_at:
        seconds = max(1, int((now - connected_at) / 1000))
    if seconds <= 0:
        seconds = 1
    if not connected_at:
        connected_at = now - seconds * 1000
    if connected_at < now - 14 * 86400 * 1000 or connected_at > now + 60000:
        connected_at = now - seconds * 1000
    return int(seconds), int(connected_at)


def player_stub(conn, steam_id: str) -> dict:
    sid = str(steam_id or "")
    row = rowd(conn.execute("SELECT steam_id, steam_name FROM players WHERE steam_id = ?", (sid,)).fetchone()) or {}
    name = str(row.get("steam_name") or sid or "")
    entity = {
        "team": [],
        "home": {"time": 0, "value": False},
        "position": {"x": 0.0, "y": 0.0, "z": 0.0, "time": 0},
        "rotation": {"x": 0.0, "y": 0.0, "z": 0.0, "time": 0},
        "coords": {"value": "", "time": 0},
        "grid": "",
        "square": "",
        "meta": {"tags": {}, "fields": {}},
        "raid": {"value": False},
        "last_moved_seconds": 0,
        "seconds_connected": 0,
        "ping": 0,
        "language": "unknown",
        "is_alive": True,
    }
    return {
        "steam_id": sid,
        "id": sid,
        "steam_name": name,
        "name": name,
        "steam_avatar": PLACEHOLDER,
        "avatar": PLACEHOLDER,
        "status": "offline",
        "steam": True,
        "team": [],
        "server_id": 0,
        "server": {"id": 0, "name": "", "hostname": "", "connected": False, "offline": True, "status": "offline"},
        "steam_data": steam_data_obj(name),
        "entity": entity,
        "ip_details": {"ip": "", "country_name": "", "city": "", "provider": "", "isp": ""},
        "last_online_at": 0,
        "created_at": 0,
        "seconds_connected": 0,
    }


def player_view(conn, steam_id: str, extra: dict | None = None, nest_team: bool = True, allow_refresh: bool = True) -> dict:
    steam_id = str(steam_id)
    p = rowd(conn.execute("SELECT * FROM players WHERE steam_id = ?", (steam_id,)).fetchone()) or {
        "steam_id": steam_id,
        "steam_name": steam_id,
        "ip": "",
        "first_seen": now_ms(),
        "last_seen": now_ms(),
        "comment": "",
        "last_language": "unknown",
        "last_no_license": 0,
    }
    online_row = None
    pid = current_pid()
    if pid:
        ids = project_server_ids(conn)
        if ids:
            marks = ",".join("?" * len(ids))
            online_row = conn.execute(
                f"SELECT payload, server_id FROM online_players WHERE steam_id = ? AND COALESCE(server_id, 1) IN ({marks})",
                [steam_id, *ids],
            ).fetchone()
    else:
        online_row = conn.execute("SELECT payload, server_id FROM online_players WHERE steam_id = ?", (steam_id,)).fetchone()
    # Presence is only valid while the server still heartbeats
    if online_row:
        try:
            sid_live = int(online_row["server_id"] or 0)
        except Exception:
            sid_live = 0
        srv_live = get_server(conn, sid_live or None)
        if not srv_live.get("connected"):
            try:
                if sid_live:
                    conn.execute(
                        "DELETE FROM online_players WHERE steam_id = ? AND COALESCE(server_id, 1) = ?",
                        (steam_id, sid_live),
                    )
                else:
                    conn.execute("DELETE FROM online_players WHERE steam_id = ?", (steam_id,))
            except Exception:
                pass
            online_row = None
    payload = extra or {}
    if online_row:
        try:
            payload = {**json.loads(online_row["payload"]), **payload}
        except Exception:
            pass
    explicit_live_presence = bool(payload.pop("_check_live_presence", False))
    if online_row or explicit_live_presence:
        status = payload.get("status") or "online"
        if status in ("", "offline", None):
            status = "online"
    else:
        status = payload.get("status") or "offline"
        if status not in ("offline",):
            # No live presence → always offline (never keep AFK/online from stale payload)
            status = "offline"
    if status == "active":
        status = "online"
    alive = status in ("online", "joining", "queued", "unstable", "afk")
    ts = now_ms() if alive else 0
    steam_cached = features.read_cache(conn, "steam_cache", "steam_id", steam_id) if steam_id else None
    persona = str((steam_cached or {}).get("personaname") or "").strip()
    # Account age and game-hour fields may legitimately be unavailable on a
    # private Steam profile.  They must not trigger a fresh Steam lookup on
    # every page request; only refresh a profile that has no usable identity.
    need_steam = not steam_cached or not is_display_name(persona, steam_id) or not (steam_cached or {}).get("avatar")
    if steam_id and need_steam and allow_refresh:
        refresh_steam_async(steam_id)
    name = resolve_player_name(conn, steam_id, payload.get("steam_name") or p.get("steam_name") or persona)
    team_ids = [sid for sid in team_ids_of(payload.get("team")) if sid != steam_id]
    if nest_team:
        team_players = []
        for mate_sid in team_ids:
            try:
                team_players.append(player_view(conn, mate_sid, nest_team=False))
            except Exception:
                team_players.append({
                    "steam_id": mate_sid,
                    "id": mate_sid,
                    "steam_name": mate_sid,
                    "name": mate_sid,
                    "team": [],
                    "status": "offline",
                    "steam": True,
                })
    else:
        team_players = [{"steam_id": sid} for sid in team_ids]
    position = parse_vec(payload.get("position"), ts)
    for axis in ("x", "y", "z"):
        if payload.get(axis) is not None:
            try:
                position[axis] = float(payload.get(axis))
            except (TypeError, ValueError):
                pass
    home_raw = payload.get("home")
    home = home_raw if isinstance(home_raw, dict) else {}
    # home.value from plugin = TC auth only — never fall back to can_build
    cached_home = features.read_cache(conn, "home_cache", "steam_id", steam_id) or {}
    if "value" in home:
        at_home = bool(home.get("value"))
        # If plugin reports not-home but player clearly has building privilege, trust can_build
        if not at_home and bool(payload.get("can_build")):
            at_home = True
        home = resolve_home_state(
            {"time": int(home.get("time") or cached_home.get("time") or 0), "value": at_home},
            at_home,
        )
        if at_home:
            home["time"] = int((home_raw or {}).get("time") or now_ms())
            try:
                features.write_cache(conn, "home_cache", "steam_id", steam_id, home)
            except Exception:
                pass
        else:
            t = int((home_raw or {}).get("time") or 0) or int(cached_home.get("time") or 0) or int(home.get("time") or 0)
            home["time"] = t
    elif bool(payload.get("can_build")):
        home = resolve_home_state(cached_home, True)
        home["time"] = now_ms()
        try:
            features.write_cache(conn, "home_cache", "steam_id", steam_id, home)
        except Exception:
            pass
    else:
        home_time = int(home.get("time") or cached_home.get("time") or 0)
        home = {"time": home_time, "value": False}
    meta = normalize_meta(payload.get("meta"))
    seconds, connected_at = session_connected_fields(conn, steam_id, alive, payload)
    rotation = parse_vec(payload.get("rotation"), ts)
    coords = as_coords(payload.get("coords") or payload.get("grid") or payload.get("square"))
    if not coords.get("value") and (position.get("x") or position.get("z")):
        try:
            srv = get_server(conn, int((online_row["server_id"] if online_row else 0) or payload.get("server_id") or 0) or None)
            world = float(srv.get("world_size") or srv.get("size") or 3000)
        except Exception:
            world = 3000.0
        coords = as_coords(rust_grid(float(position.get("x") or 0), float(position.get("z") or 0), world))
    moved = moved_elapsed(
        payload.get("last_moved_seconds") or payload.get("last_moved_at") or payload.get("last_moved") or 0,
        alive,
        int(position.get("time") or 0),
    )
    try:
        idle = int(payload.get("idle_seconds") or payload.get("idle") or 0)
    except (TypeError, ValueError):
        idle = 0
    if online_row and alive and status in ("online", "active", "afk") and (moved >= 60000 or idle >= 60):
        status = "afk"
    elif online_row and alive and status == "afk" and moved < 60000 and idle < 60:
        status = "online"
    # Keep joining/queued as-is (UI: «Подключается» / «в очереди»)
    if status == "joining" or status == "queued":
        pass
    elif status == "active":
        status = "online"
    ip = payload.get("ip") or p.get("ip") or ""
    geo_cached = features.ensure_ip_geo(conn, ip, blocking=False) if ip else None
    if isinstance(geo_cached, dict) and geo_cached.get("pending") and ip and allow_refresh:
        refresh_ip_async(ip)
    steam_data = steam_data_obj(name, steam_cached)
    if steam_cached and steam_cached.get("signed_at"):
        steam_data["signed_at"] = int(steam_cached["signed_at"])
    ip_details = geo_cached if isinstance(geo_cached, dict) else local_ip_details(ip)
    can_build = bool(payload.get("can_build"))
    avatar = (steam_cached or {}).get("avatar") or payload.get("steam_avatar") or ""
    local_av = UPLOADS / f"steam-{steam_id}.jpg"
    if local_av.exists() and local_av.stat().st_size > 200:
        avatar = f"/uploads/{local_av.name}"
    if not avatar:
        avatar = PLACEHOLDER
    server_id = int((online_row["server_id"] if online_row else 0) or payload.get("server_id") or 0)
    server = get_server(conn, server_id or None)
    if isinstance(server, dict):
        try:
            server["id"] = int(server.get("id") or 0)
        except Exception:
            server["id"] = 0
        sname = str(server.get("name") or "").strip()
        shost = str(server.get("hostname") or "").strip()
        if sname.startswith("#") and sname[1:].isdigit():
            sname = ""
        if shost.startswith("#") and shost[1:].isdigit():
            shost = ""
        server["name"] = sname or shost or str(server.get("name") or "Rust")
        server["hostname"] = shost or server["name"]
        if not server_id:
            server_id = int(server.get("id") or 0)
        elif int(server.get("id") or 0) and int(server.get("id") or 0) != server_id:
            # Use the court row id so SPA serverNameById(id) === court.servers[].id
            if int(server.get("id") or 0):
                server_id = int(server.get("id") or 0)
    else:
        server = {"id": server_id or 0, "name": "", "hostname": ""}
    if not server_id:
        server_id = int(server.get("id") or 0)
    # SPA: O = seconds_connected ? Date.now()-seconds_connected*1e3 : connected_at
    # then difference(O, Date.now()).  seconds_connected must be duration seconds;
    # connected_at must be unix ms of the current join. Never 0 while online.
    entity = {
        "seconds_connected": int(seconds or 0),
        "connected_at": int(connected_at or 0),
        "ping": payload.get("ping") or 0,
        "language": payload.get("language") or p.get("last_language") or "unknown",
        "is_alive": payload.get("is_alive", True),
        "raid": {"value": bool(payload.get("is_raiding") or payload.get("raid"))},
        "home": home,
        "position": position,
        "rotation": rotation,
        "last_moved_seconds": moved,
        "coords": coords,
        "grid": coords.get("value") or "",
        "square": coords.get("value") or "",
        "meta": meta,
        "team": team_players,
    }
    owns_rust = (steam_cached or {}).get("owns_rust") if isinstance(steam_cached, dict) else None
    if owns_rust is True:
        pirate = False
    elif owns_rust is False:
        pirate = True
    else:
        pirate = bool(payload.get("no_license") or p.get("last_no_license"))
    view = {
        "id": steam_id,
        "steam_id": steam_id,
        "steam_name": name,
        "name": name,
        "steam_avatar": avatar,
        "steam": True,
        "status": status,
        "server_id": int(server_id or 0),
        "server_name": str((server or {}).get("name") or ""),
        "server": server,
        "ip": ip,
        "ping": payload.get("ping") or 0,
        "coords": coords,
        "grid": coords.get("value") or "",
        "square": coords.get("value") or "",
        "position": position,
        "x": float(position.get("x") or 0),
        "y": float(position.get("y") or 0),
        "z": float(position.get("z") or 0),
        "rotation": rotation,
        "home": home,
        "language": payload.get("language") or p.get("last_language") or "unknown",
        "last_language": p.get("last_language") or "unknown",
        "seconds_connected": seconds,
        "can_build": can_build,
        "is_raiding": bool(payload.get("is_raiding")),
        "is_alive": payload.get("is_alive", True),
        "no_license": pirate,
        "last_no_license": pirate,
        "created_at": features.as_epoch_ms(p.get("first_seen") or 0),
        "last_online_at": resolve_player_last_online(conn, steam_id, alive),
        "comment": p.get("comment") or "",
        "team": team_players,
        "player_team": {"teammates": team_players},
        "meta": meta,
        "steam_data": steam_data,
        "ip_details": ip_details,
        "country": ip_details.get("country_name") or "",
        "city": ip_details.get("city") or "",
        "isp": ip_details.get("provider") or "",
        "bans": [],
        "checks": [],
        "reports": [],
        "comments": [],
        "last_check_id": 0,
        "active_check_id": 0,
        "activeCheckId": 0,
        "is_checking": False,
        "checking": False,
        "ignore_reports_until": features.ignore_reports_get(conn, steam_id) or None,
        "entity": entity,
    }
    return attach_active_check_fields(view, conn, steam_id)


def fetch_remote_map_bytes(url: str) -> bytes:
    src = str(url or "").strip()
    if not src.startswith("http"):
        return b""
    try:
        req = Request(src, headers={"User-Agent": "RustApp-map"})
        with urlopen(req, timeout=20) as resp:
            data = resp.read() or b""
        if len(data) > 200:
            return data
    except Exception as exc:
        print("map url fetch failed", type(exc).__name__, exc)
    return b""


def server_map_image(row: dict, sid: int = 0) -> str:
    sid = int(sid or row.get("id") or 0)
    stored = str(row.get("map_image") or "").strip()
    if stored.startswith("/uploads/map-") and stored.split("?", 1)[0] != f"/uploads/map-{sid}.png":
        return stored
    fs = UPLOADS / f"map-{sid}.png"
    if fs.exists() and fs.stat().st_size > 100:
        return f"/uploads/map-{sid}.png?t={int(fs.stat().st_mtime)}"
    stored = str(row.get("map_image") or "").strip()
    if stored:
        return stored
    return "/local/landing/map-preview.png?https=1"


def map_payload(conn, server_id: int = 0) -> dict | None:
    if server_id:
        alias = conn.execute("SELECT value FROM settings WHERE key=?", (f"server_alias_{int(server_id)}",)).fetchone()
        if alias:
            server_id = int(alias["value"])
    servers = []
    all_players = []
    pid = current_pid()
    rows = []
    if pid:
        rows = conn.execute(
            "SELECT * FROM servers WHERE project_id = ? AND paired = 1 ORDER BY id ASC",
            (pid,),
        ).fetchall()
    for raw in rows:
        row = rowd(raw) or {}
        sid = int(row.get("id") or 0)
        if server_id and sid != int(server_id):
            continue
        image = server_map_image(row, sid)
        world = as_int(row.get("world_size")) or 3000
        seed = as_int(row.get("seed"))
        players = []
        for op in conn.execute(
            "SELECT steam_id FROM online_players WHERE COALESCE(server_id, 1) = ?",
            (sid,),
        ).fetchall():
            steam = str(op["steam_id"] or "")
            if not is_real_steam_id(steam):
                continue
            view = player_view(conn, steam)
            # SPA live-map does position.match(...) — must be a string, not {x,y,z}
            pos = view.get("position")
            if isinstance(pos, dict):
                view["position"] = f"{float(pos.get('x') or 0)}, {float(pos.get('y') or 0)}, {float(pos.get('z') or 0)}"
            entity = view.get("entity") if isinstance(view.get("entity"), dict) else None
            if entity and isinstance(entity.get("position"), dict):
                ep = entity["position"]
                entity["position"] = f"{float(ep.get('x') or 0)}, {float(ep.get('y') or 0)}, {float(ep.get('z') or 0)}"
            players.append(view)
            all_players.append(view)
        item = server_view(conn, row)
        item.update({
            "image": image,
            "image_url": image,
            "url": image,
            "map": image,
            "map_image": image,
            "world_size": world,
            "size": world,
            "seed": seed,
            "players": players,
        })
        servers.append(item)
    if server_id and not servers:
        return None
    first = servers[0] if servers else {}
    image = first.get("image") or "/local/landing/map-preview.png?https=1"
    world = as_int(first.get("world_size")) or 3000
    now = now_ms()
    return {
        "image": image,
        "image_url": image,
        "map_url": image,
        "map_size": world,
        "monuments": [],
        "sleeping_bags": [],
        "url": image,
        "map": image,
        "world_size": world,
        "size": world,
        "seed": as_int(first.get("seed")),
        "level": first.get("level") or "",
        "chunks": [],
        "servers": servers,
        "players": all_players,
        "time_points": [
            {"time": now - 3600000, "value": len(all_players), "online": len(all_players), "players": len(all_players)},
            {"time": now, "value": len(all_players), "online": len(all_players), "players": len(all_players)},
        ],
    }


def empty_entity() -> dict:
    return {
        "team": [],
        "home": {"time": 0, "value": False},
        "position": {"x": 0.0, "y": 0.0, "z": 0.0, "time": 0},
        "rotation": {"x": 0.0, "y": 0.0, "z": 0.0, "time": 0},
        "coords": {"value": "", "grid": "", "square": "", "time": 0},
        "meta": {"tags": {}, "fields": {}},
        "raid": {"value": False},
        "last_moved_seconds": 0,
    }


def player_details_safe(steam_id: str, name: str = "") -> dict:
    sid = str(steam_id or "")
    label = str(name or sid or "")
    entity = empty_entity()
    player = {
        "id": sid,
        "steam_id": sid,
        "steam_name": label,
        "name": label,
        "steam_avatar": PLACEHOLDER,
        "avatar": PLACEHOLDER,
        "steam": True,
        "status": "offline",
        "team": [],
        "entity": entity,
        "home": entity["home"],
        "position": entity["position"],
        "rotation": entity["rotation"],
        "coords": entity["coords"],
        "steam_data": steam_data_obj(label),
        "server": {"id": 0, "name": "", "connected": False, "offline": True},
        "ip_details": {},
        "bans": [],
        "checks": [],
        "reports": [],
        "comments": [],
        "last_check_id": 0,
        "active_check_id": 0,
    }
    return {"player": player, "entity": entity, "team": []}


def ensure_player_shape(player, sid: str = "", name: str = "") -> dict:
    if not isinstance(player, dict):
        player = {}
    sid = str(player.get("steam_id") or player.get("id") or sid or "")
    label = str(player.get("steam_name") or player.get("name") or name or sid or "")
    player["id"] = player.get("id") or sid
    player["steam_id"] = sid
    player["steam_name"] = label
    player["name"] = player.get("name") or label
    if not isinstance(player.get("team"), list):
        player["team"] = []
    if not isinstance(player.get("entity"), dict):
        player["entity"] = empty_entity()
    entity = player["entity"]
    if not isinstance(entity.get("home"), dict):
        entity["home"] = {"time": 0, "value": False}
    if not isinstance(entity.get("position"), dict):
        entity["position"] = {"x": 0.0, "y": 0.0, "z": 0.0, "time": 0}
    if not isinstance(entity.get("rotation"), dict):
        entity["rotation"] = {"x": 0.0, "y": 0.0, "z": 0.0, "time": 0}
    if not isinstance(entity.get("coords"), dict):
        entity["coords"] = {"value": "", "grid": "", "square": "", "time": 0}
    if not isinstance(entity.get("meta"), dict):
        entity["meta"] = {"tags": {}, "fields": {}}
    if not isinstance(entity.get("raid"), dict):
        entity["raid"] = {"value": False}
    if not isinstance(player.get("steam_data"), dict):
        player["steam_data"] = steam_data_obj(label)
    bans = player["steam_data"].get("ban_data") if isinstance(player["steam_data"].get("ban_data"), dict) else {}
    game = bans.get("game_ban") if isinstance(bans.get("game_ban"), dict) else {}
    vac = bans.get("vac_ban") if isinstance(bans.get("vac_ban"), dict) else {}
    try:
        player["steam_data"]["ban_data"] = {
            "days_since_last_ban": bans.get("days_since_last_ban"),
            "game_ban": {"count": int(game.get("count") or 0)},
            "vac_ban": {"count": int(vac.get("count") or 0)},
        }
    except (TypeError, ValueError):
        player["steam_data"]["ban_data"] = {
            "days_since_last_ban": None,
            "game_ban": {"count": 0},
            "vac_ban": {"count": 0},
        }
    if not isinstance(player.get("server"), dict):
        player["server"] = {
            "id": int(player.get("server_id") or 0),
            "name": str(player.get("server_name") or ""),
            "connected": False,
            "offline": True,
        }
    player["steam"] = True
    player["home"] = player.get("home") if isinstance(player.get("home"), dict) else entity["home"]
    player["position"] = player.get("position") if isinstance(player.get("position"), dict) else entity["position"]
    player["rotation"] = player.get("rotation") if isinstance(player.get("rotation"), dict) else entity["rotation"]
    player["coords"] = player.get("coords") if isinstance(player.get("coords"), dict) else entity["coords"]
    attach_active_check_fields(player, None, sid)
    return player


def player_details(conn, steam_id: str) -> dict:
    try:
        player = player_view(conn, steam_id, nest_team=False, allow_refresh=False)
    except Exception as exc:
        print("player_view details failed", steam_id, type(exc).__name__, exc)
        return player_details_safe(steam_id, "")
    player = ensure_player_shape(player, steam_id)
    last = conn.execute(
        "SELECT id FROM checks WHERE steam_id = ?" + project_clause()[0] + " ORDER BY id DESC LIMIT 1",
        [steam_id, *project_clause()[1]],
    ).fetchone()
    active = conn.execute(
        """SELECT id FROM checks WHERE steam_id = ?
             AND (finished_at IS NULL OR finished_at = 0)
             AND LOWER(COALESCE(status, 'active')) NOT IN ('cancel', 'canceled', 'cancelled', 'finished', 'finishedclear', 'finishedban')
          """ + project_clause()[0] + " ORDER BY id DESC LIMIT 1",
        [steam_id, *project_clause()[1]],
    ).fetchone()
    player["last_check_id"] = last["id"] if last else 0
    player["active_check_id"] = active["id"] if active else 0
    attach_active_check_fields(player, conn, steam_id)
    return {
        "player": player,
        "entity": player.get("entity"),
        "team": player.get("team") or [],
    }


def query_sid(params, *keys):
    for key in keys:
        raw = params.get(key) or params.get(key + "[]")
        if not raw:
            continue
        value = str(raw[0] if isinstance(raw, list) else raw).strip()
        if value:
            return value
    return ""


def browse(items, params, default_limit=50):
    # Checkapp SPA uses 0-based pages (page=0 first, page=1 second).
    # Mapping page>=1 to page-1 made page=0 and page=1 return the same chunk → duplicate cards.
    raw_page = int((params.get("page") or ["0"])[0] or 0)
    limit = int((params.get("limit") or [str(default_limit)])[0] or default_limit) or default_limit
    page_idx = max(0, raw_page)
    start = page_idx * limit
    chunk = items[start : start + limit]
    total = len(items)
    last_page = max(1, (total + limit - 1) // limit) if total else 1
    # Keep page field 1-based for UI labels; index is 0-based
    page_no = page_idx + 1
    more = (start + limit) < total
    return {
        "data": chunk,
        "results": chunk,
        "items": chunk,
        "total": total,
        "count": len(chunk),
        "limit": limit,
        "per_page": limit,
        "page": page_no,
        "current_page": page_no,
        "last_page": last_page,
        "has_more": more,
        "hasMore": more,
        "done": not more,
        "finished": not more,
        "next_page": (page_idx + 1) if more else None,
        "next_cursor": None,
        "links": {"next": None} if not more else {},
        "meta": {
            "total": total,
            "page": page_no,
            "limit": limit,
            "last_page": last_page,
            "has_more": more,
            "done": not more,
            "next_page_url": None,
        },
    }


def parse_duration(value) -> int:
    if value in (None, "", 0, "0"):
        return 0
    # Absolute epoch already in ms (SPA often sends expired_at this way)
    try:
        if isinstance(value, (int, float)) or (isinstance(value, str) and value.strip().isdigit()):
            n = int(float(value))
            now = now_ms()
            # Absolute timestamp in ms (year ~2001..2100)
            if 1_000_000_000_000 <= n <= 4_102_444_800_000:
                return n if n > now else 0
            # Absolute timestamp wrongly in microseconds
            if n > 4_102_444_800_000:
                n2 = n // 1000
                if 1_000_000_000_000 <= n2 <= 4_102_444_800_000:
                    return n2 if n2 > now else 0
            # Relative seconds (SPA duration field)
            if 0 < n < 1_000_000_000_000:
                return now + n * 1000
    except (TypeError, ValueError):
        pass
    value = str(value).strip().lower()
    if value in ("", "0", "perm", "permanent", "forever"):
        return 0
    try:
        if value.endswith("m"):
            return now_ms() + int(value[:-1]) * 60 * 1000
        if value.endswith("h"):
            return now_ms() + int(value[:-1]) * 3600 * 1000
        if value.endswith("d"):
            return now_ms() + int(value[:-1]) * 86400 * 1000
        return now_ms() + int(value) * 1000
    except ValueError:
        return 0


def setting_get(key: str, default=""):
    def _g(conn):
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    return db_call(_g)


def setting_set(key: str, value: str):
    def _s(conn):
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    db_call(_s)


def stable_client_id(uid=0, name="") -> int:
    """SPA Dh().load(0) renders the current viewer. Never send 0 as a staff id."""
    try:
        n = int(uid or 0)
    except Exception:
        n = 0
    if n:
        return n
    digest = hashlib.md5(str(name or "staff").encode("utf-8", "ignore")).hexdigest()
    return 100000 + (int(digest[:6], 16) % 800000)


def mark_staff_moderator(staff: dict) -> dict:
    """Shape a staff client so check-chat draws the same moderator badge as site chat."""
    if not isinstance(staff, dict):
        staff = {}
    else:
        staff = dict(staff)
    name = str(staff.get("name") or staff.get("steam_name") or "").strip()
    av = str(staff.get("avatar") or PLACEHOLDER)
    if not av or features.LIBRARY_DEFAULT_AVATAR in av:
        av = PLACEHOLDER
    staff["name"] = name or staff.get("name") or "Сотрудник"
    staff["avatar"] = av
    staff["tag"] = str(staff.get("tag") or name or "").strip().lstrip("@")
    staff["is_moderator"] = True
    staff["isModerator"] = True
    staff["moderator"] = True
    staff["is_staff"] = True
    staff["isStaff"] = True
    staff["is_admin"] = True
    staff["isAdmin"] = True
    staff["role"] = str(staff.get("role") or "staff")
    staff["status"] = staff.get("status") or "online"
    staff["online"] = True
    staff["is_online"] = True
    if str(staff.get("steam_id") or "") in ("0", "None"):
        staff["steam_id"] = ""
    staff["steam"] = features.empty_steam_profile(av)
    return staff


def staff_brief(conn, actor_text="", actor_id=0, payload=None) -> dict:
    """Tiny staff stub for lists. Never call client_obj() here — that 502s nginx."""
    payload = payload if isinstance(payload, dict) else {}
    uid = 0
    try:
        uid = int(actor_id or payload.get("actor_user_id") or payload.get("actor_id") or 0)
    except Exception:
        uid = 0
    user = features.user_by_id(conn, uid) if uid else None
    name = features.staff_public_name(
        user,
        str(payload.get("actor_name") or actor_text or ""),
        str(payload.get("actor_email") or ""),
        conn,
    )
    user_tag = features.staff_public_tag(user, name, conn)
    if not name:
        mail = str((user or {}).get("email") or payload.get("actor_email") or "")
        name = mail.split("@")[0] if "@" in mail else ""
    av = PLACEHOLDER
    try:
        got = features.client_avatar_for(conn, uid) if uid else ""
        if got:
            av = str(got)
    except Exception:
        av = PLACEHOLDER
    cid = stable_client_id(uid, name)
    tag = user_tag or str(payload.get("actor_tag") or "").strip().lstrip("@")
    if not tag or features.is_generic_staff_label(tag, conn):
        tag = user_tag or features.staff_public_tag(user or {"id": uid, "email": (user or {}).get("email") or payload.get("actor_email") or "", "name": name}, name, conn)
    if not tag:
        tag = f"user{cid}" if cid else ""
    return {
        "id": cid,
        "M_ID": cid,
        "name": name,
        "tag": tag,
        "role": str(payload.get("actor_role") or "staff"),
        "avatar": av,
        "status": "online",
        "online": True,
        "is_online": True,
        "steam": features.empty_steam_profile(av),
        "steam_id": "",
        "email": str((user or {}).get("email") or payload.get("actor_email") or ""),
    }


def resolved_staff_snapshot(conn, actor_name="", actor_id=0, actor_email="", actor_role="", project_id=0) -> tuple[int, str, str, str]:
    """Return the stored human actor, never the project label used by old rows."""
    try:
        uid = int(actor_id or 0)
    except (TypeError, ValueError):
        uid = 0
    name = str(actor_name or "").strip()
    email = str(actor_email or "").strip()
    role = str(actor_role or "").strip()
    project_name = ""
    try:
        pid = int(project_id or 0)
        if pid:
            row = conn.execute("SELECT name FROM project WHERE id = ?", (pid,)).fetchone()
            project_name = str((row["name"] if row else "") or "").strip()
    except Exception:
        pass
    is_project_label = bool(project_name and name.casefold() == project_name.casefold())
    if uid:
        try:
            user = features.user_by_id(conn, uid) or {}
            user_email = str(user.get("email") or "").strip()
            user_name = features.human_actor_name(
                str(user.get("name") or ""), user_email,
                user_email.split("@")[0] if "@" in user_email else "",
            )
            if user_name and (not name or features.is_generic_staff_label(name) or is_project_label):
                name = user_name
            if user_email and not email:
                email = user_email
            if not role or features.is_generic_staff_label(role):
                role = str(user.get("role") or role)
        except Exception:
            pass
    elif (not features.human_actor_name(name, email, "") or is_project_label) and project_name:
        # Old local rows did not yet contain a staff snapshot.  A single-owner
        # project has an unambiguous actor, so restore that owner instead of
        # showing the project as if it were a moderator.
        try:
            pid = int(project_id or 0)
            owner = conn.execute("SELECT owner_user_id FROM project WHERE id = ?", (pid,)).fetchone()
            others = conn.execute(
                "SELECT COUNT(*) FROM staff_members WHERE project_id = ? AND COALESCE(active, 1) = 1",
                (pid,),
            ).fetchone()
            if owner and int(owner["owner_user_id"] or 0) and int(others[0] or 0) == 0:
                uid = int(owner["owner_user_id"])
                user = features.user_by_id(conn, uid) or {}
                user_email = str(user.get("email") or "").strip()
                name = features.human_actor_name(
                    str(user.get("name") or ""), user_email,
                    user_email.split("@")[0] if "@" in user_email else "",
                )
                email = user_email or email
                role = str(user.get("role") or role)
        except Exception:
            pass
    name = features.human_actor_name(name, email, "") or name
    return uid, name, email, role


def actor_client(conn, actor_text="", actor_id=0, payload=None):
    """Resolve the user who performed an action. Never reuse current staff or payload.user_id (target)."""
    payload = payload if isinstance(payload, dict) else {}
    uid = 0
    try:
        uid = int(actor_id or payload.get("actor_id") or payload.get("actor_user_id") or 0)
    except Exception:
        uid = 0
    user = None
    if uid:
        user = features.user_by_id(conn, uid)
    if user is None:
        email = str(payload.get("actor_email") or "").strip().lower()
        if not email:
            maybe = str(actor_text or "").strip().lower()
            if "@" in maybe:
                email = maybe
        if email and "@" in email:
            row = conn.execute("SELECT * FROM users WHERE lower(email) = ?", (email,)).fetchone()
            if row:
                user = dict(row)
    snap_name = features.human_actor_name(
        payload.get("actor_name") or actor_text or "",
        payload.get("actor_email") or "",
        "",
    )
    snap_email = str(payload.get("actor_email") or "").strip()
    snap_role = str(payload.get("actor_role") or "").strip()
    if user is None and snap_email and "@" in snap_email:
        row = conn.execute("SELECT * FROM users WHERE lower(email) = ?", (snap_email.lower(),)).fetchone()
        if row:
            user = dict(row)
            uid = int(user.get("id") or 0)
    former = None
    if user is None and uid:
        try:
            former = features.former_staff_snapshot(conn, current_pid() or int(payload.get("project_id") or 0), uid)
        except Exception:
            former = None
    # Never pick a random account by display name — that shows the wrong admin on bans.
    if user:
        obj = client_obj(conn, user)
        try:
            obj["id"] = stable_client_id(obj.get("id") or uid, obj.get("name") or snap_name)
        except Exception:
            obj["id"] = stable_client_id(uid, snap_name)
        obj["status"] = "online"
        obj["online"] = True
        obj["is_online"] = True
        # Frozen snapshot from the moment of the action — never the current viewer.
        live_name = features.staff_public_name(user, snap_name, snap_email)
        if live_name:
            obj["name"] = live_name
        elif snap_name and not features.is_generic_staff_label(snap_name):
            obj["name"] = snap_name
        live_tag = features.staff_public_tag(user, obj.get("name") or "", conn)
        if live_tag:
            obj["tag"] = live_tag
        if snap_email:
            obj["email"] = snap_email
        if snap_role:
            obj["role"] = snap_role
            obj["actor_role"] = snap_role
        obj["system_source"] = "RustCheck"
        try:
            pid = current_pid() or 0
            if pid and uid:
                owner = conn.execute(
                    "SELECT 1 FROM project WHERE id = ? AND COALESCE(owner_user_id, 0) = ?",
                    (pid, uid),
                ).fetchone()
                staff = conn.execute(
                    "SELECT 1 FROM staff_members WHERE COALESCE(project_id, 0) = ? AND COALESCE(user_id, 0) = ? AND COALESCE(active, 1) = 1",
                    (pid, uid),
                ).fetchone()
                if not owner and not staff:
                    obj["former_member"] = True
                    obj["formerMember"] = True
                    obj["status_label"] = "Former member"
        except Exception:
            pass
        return obj
    if former:
        name = str(former.get("name") or snap_name or "Бывший сотрудник")
        tag = str(former.get("tag") or "").strip().lstrip("@")
        avatar = str(former.get("avatar") or PLACEHOLDER)
        return {
            "id": stable_client_id(uid, name), "M_ID": stable_client_id(uid, name),
            "name": name, "tag": tag or features.staff_public_tag(former, name, conn),
            "email": str(former.get("email") or snap_email),
            "role": str(former.get("role") or snap_role or "staff"),
            "avatar": avatar, "status": "offline", "online": False, "is_online": False,
            "former_member": True, "formerMember": True, "system_source": "RustCheck",
            "steam": features.empty_steam_profile(avatar), "steam_id": "",
        }
    name = features.staff_public_name(None, snap_name or actor_text, snap_email) or snap_name or ""
    tag = features.staff_public_tag({"email": snap_email, "name": name, "tag": ""}, name, conn)
    return {
        "id": stable_client_id(uid, name),
        "name": name,
        "email": snap_email or (actor_text if "@" in str(actor_text) else ""),
        "tag": tag,
        "role": snap_role or "staff",
        "actor_role": snap_role or "staff",
        "avatar": PLACEHOLDER,
        "status": "online",
        "online": True,
        "is_online": True,
        "steam": features.empty_steam_profile(PLACEHOLDER),
        "steam_id": "",
        "system_source": "RustCheck",
    }


def client_obj(conn=None, user=None) -> dict:
    def _build(c, u=None):
        if u is None:
            uid = features.request_user_id()
            if uid:
                u = features.user_by_id(c, uid)
            if u is None:
                u = features.owner_user(c)
        if not u or not int(u.get("id") or 0):
            return {"id": 0, "M_ID": 0, "email": "", "name": "", "unauthorized": True}
        avatar = features.client_avatar_for(c, int(u.get("id") or 0)) or PLACEHOLDER
        base = features.client_from_user(u, avatar, c)
        # RustApp's batch loaders use the ORM-style M_ID key when resolving
        # staff profiles from audit rows.
        base["M_ID"] = int(base.get("id") or u.get("id") or 0)
        # Steam object must be a real Steam profile object (or null) — never a string SteamID
        steam_obj = oauth_auth.steam_profile_for_user(c, u, allow_network=False)
        steam_sid = str((steam_obj or {}).get("steam_id") or u.get("steam_id") or "")
        if steam_obj and is_real_steam_id(steam_sid):
            base["steam"] = steam_obj
            base["steam_id"] = steam_sid
            base["steam_name"] = steam_obj.get("steam_name") or "Steam"
            base["steam_avatar"] = steam_obj.get("steam_avatar") or ""
            try:
                refresh_steam_async(steam_sid)
            except Exception:
                pass
        else:
            # SPA integrations treat any truthy client.steam as "connected".
            base["steam"] = None
            base["steam_id"] = ""
            base["steam_name"] = ""
            base["steam_avatar"] = ""
        disc = oauth_auth.discord_profile_for_user(c, u)
        if disc:
            base["discord"] = disc
            base["discord_id"] = disc.get("discord_id") or ""
            base["discord_name"] = disc.get("discord_name") or ""
            base["discord_avatar"] = disc.get("discord_avatar") or ""
        else:
            base["discord"] = {
                "discord_id": "", "discord_name": "", "name": "",
                "avatar": "", "discord_avatar": "",
            }
        goog = oauth_auth.google_profile_for_user(c, u)
        if goog:
            base["google"] = goog
            base["google_id"] = goog.get("google_id") or ""
            base["google_name"] = goog.get("google_name") or ""
            base["google_avatar"] = goog.get("google_avatar") or ""
        else:
            base["google"] = {
                "google_id": "", "google_name": "", "name": "",
                "avatar": "", "google_avatar": "",
            }
        base["integrations"] = {
            "steam": {
                "connected": bool(steam_obj and is_real_steam_id(steam_sid)),
                "status": "connected" if steam_obj and is_real_steam_id(steam_sid) else "disconnected",
                "avatar": (steam_obj or {}).get("avatar") or base.get("steam_avatar") or base.get("avatar") or PLACEHOLDER,
            },
            "discord": {
                "connected": bool(disc and disc.get("discord_id")),
                "is_connected": bool(disc and disc.get("discord_id")),
                "id": (disc or {}).get("discord_id") or "",
                "discord_id": (disc or {}).get("discord_id") or "",
                "name": (disc or {}).get("discord_name") or (disc or {}).get("name") or "",
                "username": (disc or {}).get("username") or (disc or {}).get("discord_name") or "",
                "global_name": (disc or {}).get("global_name") or (disc or {}).get("discord_name") or "",
                "personaname": (disc or {}).get("personaname") or (disc or {}).get("discord_name") or "",
                "status": "connected" if disc and disc.get("discord_id") else "disconnected",
                "avatar": (disc or {}).get("avatar") or base.get("discord_avatar") or "",
                "discord_avatar": (disc or {}).get("discord_avatar") or (disc or {}).get("avatar") or "",
                "avatarfull": (disc or {}).get("avatarfull") or (disc or {}).get("avatar") or "",
            },
            "google": {
                "connected": bool(goog and goog.get("google_id")),
                "status": "connected" if goog and goog.get("google_id") else "disconnected",
                "avatar": (goog or {}).get("avatar") or base.get("google_avatar") or base.get("avatar") or PLACEHOLDER,
            },
            "telegram": {
                "connected": False,
                "available": False,
                "disabled": True,
                "can_connect": False,
                "status": "unavailable",
                "avatar": PLACEHOLDER,
            },
        }
        base["telegram"] = {
            "telegram_id": "",
            "name": "",
            "avatar": "",
            "connected": False,
            "available": False,
            "disabled": True,
            "status": "unavailable",
        }
        try:
            uid = int(u.get("id") or 0)
            pid = int(features.request_project_id() or current_pid() or 0)
            owner_uid = features.project_owner_user_id(c, pid) if pid else 0
            if pid and uid and owner_uid and uid == owner_uid:
                base["permissions"] = list(PERMISSIONS)
                base["is_admin"] = True
                base["is_owner"] = True
            elif pid and uid:
                try:
                    sm = c.execute(
                        """SELECT permissions, COALESCE(is_immutable, 0) AS is_immutable FROM staff_members
                           WHERE project_id = ? AND user_id = ? AND COALESCE(active, 1) = 1
                           LIMIT 1""",
                        (pid, uid),
                    ).fetchone()
                except Exception:
                    sm = c.execute(
                        """SELECT permissions FROM staff_members
                           WHERE project_id = ? AND user_id = ? AND COALESCE(active, 1) = 1
                           LIMIT 1""",
                        (pid, uid),
                    ).fetchone()
                if sm:
                    perms = staff_perms_list(sm["permissions"] if sm else [])
                    immutable = False
                    try:
                        immutable = bool(int((sm["is_immutable"] if hasattr(sm, "keys") and "is_immutable" in sm.keys() else 0) or 0))
                    except Exception:
                        immutable = False
                    if immutable or is_full_admin_perms(perms) or features.staff_payload_is_admin(perms, immutable):
                        perms = list(PERMISSIONS)
                    base["permissions"] = perms
                    if immutable or is_full_admin_perms(perms):
                        base["is_admin"] = True
                        base["is_owner"] = False
                    else:
                        base["is_admin"] = False
                        base["is_owner"] = False
        except Exception:
            pass
        return base

    if conn is not None:
        return _build(conn, user)
    return db_call(lambda c: _build(c, user))


def _landing_reviews_from_projects(conn) -> list:
    """Paired servers/projects for the landing carousel (SPA reads stats.reviews)."""
    reviews = []
    seen = set()

    def add_item(item_id, name, domain, avatar, project_id):
        pid = int(project_id or item_id or 0)
        title = str(name or domain or "Server").strip()
        if not title:
            return
        key = (pid, title.lower())
        if key in seen:
            return
        seen.add(key)
        av = features.public_project_avatar(avatar, pid or item_id)
        reviews.append({
            "id": int(item_id or pid or len(reviews) + 1),
            "project": {
                "id": pid or int(item_id or len(reviews) + 1),
                "avatar": av,
                "name": title,
                "domain": str(domain or ""),
            },
        })

    try:
        rows = conn.execute(
            """
            SELECT s.id AS sid, s.name AS sname, s.hostname, s.avatar_url,
                   p.id AS pid, p.name AS pname, p.domain, p.avatar
            FROM servers s
            LEFT JOIN project p ON p.id = s.project_id
            WHERE COALESCE(s.paired, 0) = 1 OR s.project_id IS NOT NULL
            ORDER BY COALESCE(s.paired, 0) DESC, COALESCE(s.last_seen, 0) DESC, s.id DESC
            LIMIT 60
            """
        ).fetchall()
        for r in rows:
            row = rowd(r)
            name = row.get("pname") or row.get("sname") or row.get("hostname") or row.get("domain")
            add_item(
                row.get("sid"),
                name,
                row.get("domain") or "",
                row.get("avatar") or row.get("avatar_url") or "",
                row.get("pid") or row.get("sid"),
            )
    except Exception:
        pass

    if not reviews:
        try:
            rows = conn.execute(
                "SELECT id, name, domain, avatar FROM project ORDER BY id DESC LIMIT 40"
            ).fetchall()
        except Exception:
            rows = []
        for r in rows:
            row = rowd(r)
            add_item(row.get("id"), row.get("name"), row.get("domain"), row.get("avatar"), row.get("id"))

    if reviews and len(reviews) < 8:
        base = list(reviews)
        while len(reviews) < 14:
            reviews.extend(base)
        reviews = reviews[:14]
    return reviews


def landing_feed() -> dict:
    def _feed(conn):
        reviews = _landing_reviews_from_projects(conn)
        return {"reviews": reviews, "orgs": [
            {
                "id": item["project"]["id"],
                "name": item["project"]["name"],
                "avatar": item["project"]["avatar"],
                "domain": item["project"]["domain"],
            }
            for item in reviews[:20]
        ]}

    return db_call(_feed)


def service_stats() -> dict:
    def _s(conn):
        players = conn.execute("SELECT COUNT(*) FROM players").fetchone()[0]
        checks = conn.execute("SELECT COUNT(*) FROM checks").fetchone()[0]
        bans = conn.execute("SELECT COUNT(*) FROM bans").fetchone()[0]
        reports = conn.execute("SELECT COUNT(*) FROM reports").fetchone()[0]
        messages = conn.execute("SELECT COUNT(*) FROM chat").fetchone()[0]
        online = conn.execute("SELECT COUNT(*) FROM online_players").fetchone()[0]
        servers = conn.execute("SELECT COUNT(*) FROM servers WHERE paired = 1").fetchone()[0]
        players = features.lifetime_get(conn, "players", players)
        checks = features.lifetime_get(conn, "checks", checks)
        bans = features.lifetime_get(conn, "bans", bans)
        reports = features.lifetime_get(conn, "reports", reports)
        messages = features.lifetime_get(conn, "messages", messages)
        reviews = _landing_reviews_from_projects(conn)
        if not reviews:
            try:
                cnt = conn.execute("SELECT COUNT(*) FROM project").fetchone()[0]
            except Exception:
                cnt = 0
            if int(cnt or 0) > 0:
                rows = conn.execute(
                    "SELECT id, name, domain, avatar FROM project ORDER BY id DESC LIMIT 40"
                ).fetchall()
                for r in rows:
                    row = rowd(r)
                    reviews.append({
                        "id": int(row.get("id") or 0),
                        "project": {
                            "id": int(row.get("id") or 0),
                            "avatar": str(row.get("avatar") or "").strip() or PLACEHOLDER,
                            "name": str(row.get("name") or row.get("domain") or "RustApp"),
                            "domain": str(row.get("domain") or ""),
                        },
                    })
                if reviews and len(reviews) < 8:
                    base = list(reviews)
                    while len(reviews) < 14:
                        reviews.extend(base)
                    reviews = reviews[:14]
        orgs = [
            {
                "id": item["project"]["id"],
                "name": item["project"]["name"],
                "avatar": item["project"]["avatar"],
                "domain": item["project"]["domain"],
            }
            for item in reviews[:20]
        ]
        counters = {
            "online_servers": servers,
            "online_players": online,
            "online_users": max(1, online),
            "total_players": players,
            "total_checks": checks,
            "total_bans": bans,
            "total_reports": reports,
            "total_messages": messages,
            "players": players,
            "checks": checks,
            "bans": int(bans or 0),
            "ban": int(bans or 0),
            "reports": reports,
            "messages": messages,
        }
        return {
            "counters": counters,
            "stats": counters,
            "service": counters,
            "orgs": orgs,
            "organizations": orgs,
            "projects": orgs,
            "reviews": reviews,
            **counters,
        }

    return db_call(_s)


def current_sessions(handler=None) -> list:
    """Activity log sessions from real login IPs + GeoIP (not hardcoded 127.0.0.1)."""
    now = now_ms()
    current_ip = ""
    if handler is not None:
        try:
            current_ip = admin_panel.client_ip(handler) or ""
        except Exception:
            current_ip = ""

    def _build(conn):
        uid = features.request_user_id() or 0
        rows = []
        if uid:
            if current_ip:
                try:
                    features.record_user_ip(conn, int(uid), current_ip, revive=True)
                except Exception:
                    pass
            try:
                rows = conn.execute(
                    """SELECT ip, first_seen, last_seen, hits FROM user_login_ips
                       WHERE user_id = ? AND COALESCE(revoked, 0) = 0
                       ORDER BY last_seen DESC LIMIT 20""",
                    (int(uid),),
                ).fetchall()
            except Exception:
                rows = conn.execute(
                    """SELECT ip, first_seen, last_seen, hits FROM user_login_ips
                       WHERE user_id = ? ORDER BY last_seen DESC LIMIT 20""",
                    (int(uid),),
                ).fetchall()
        items = []
        seen = set()
        for idx, row in enumerate(rows or []):
            ip = str(row["ip"] or "").strip()
            if not ip or ip in seen:
                continue
            seen.add(ip)
            geo = features.ensure_ip_geo(conn, ip, blocking=False)
            if not isinstance(geo, dict):
                geo = local_ip_details(ip)
            if geo.get("pending") or geo.get("_stale") or features._geo_is_placeholder(geo) or not geo.get("country"):
                refresh_ip_async(ip, current_pid() or 0)
            is_current = bool(current_ip and ip == current_ip) or (idx == 0 and not current_ip)
            country, city, provider, code = geo_display(geo, ip)
            if (not country) and current_ip and ip == current_ip:
                hc, hcode = header_country(handler)
                if hc:
                    country, code = hc, hcode
            pending = bool(geo.get("pending")) and not country
            items.append({
                "key": f"client_serials:{uid}-{ip}",
                "id": f"{uid}-{ip}",
                "serial": f"{uid}-{ip}",
                "last_used": int(row["last_seen"] or now),
                "created_at": int(row["first_seen"] or now),
                "ip": ip,
                "country": country,
                "country_name": country,
                "city": city,
                "provider": provider,
                "isp": provider,
                "pending": pending,
                "ip_details": {
                    "ip": ip,
                    "country": country,
                    "country_name": country,
                    "city": city,
                    "provider": provider,
                    "isp": provider,
                    "org": geo.get("org") or provider,
                    "proxy": bool(geo.get("proxy")),
                    "country_code": code,
                    "pending": pending,
                },
                "user_agent": "",
                "browser": "",
                "os": "",
                "hits": int(row["hits"] or 1),
                "current": is_current,
                "is_current": is_current,
            })
        if current_ip and current_ip not in seen:
            if uid and features.user_session_revoked(conn, int(uid), current_ip):
                pass
            else:
                # The currently displayed IP is part of the detail view as well;
                # resolve it now so it does not remain "Неизвестно" forever.
                geo = features.ensure_ip_geo(conn, current_ip, blocking=False)
                refresh_ip_async(current_ip, current_pid() or 0)
                if not isinstance(geo, dict):
                    geo = local_ip_details(current_ip)
                country, city, provider, code = geo_display(geo, current_ip)
                if not country:
                    hc, hcode = header_country(handler)
                    if hc:
                        country, code = hc, hcode
                items.insert(0, {
                    "key": f"client_serials:{uid or 0}-{current_ip}",
                    "id": f"current-{current_ip}",
                    "serial": f"current-{current_ip}",
                    "last_used": now,
                    "created_at": now,
                    "ip": current_ip,
                    "country": country,
                    "country_name": country,
                    "city": city,
                    "provider": provider,
                    "isp": provider,
                    "ip_details": {
                        "ip": current_ip,
                        "country": country,
                        "country_name": country,
                        "city": city,
                        "provider": provider,
                        "isp": provider,
                        "org": geo.get("org") or provider,
                        "proxy": bool(geo.get("proxy")),
                        "country_code": code,
                    },
                    "user_agent": "",
                    "browser": "",
                    "os": "",
                    "current": True,
                    "is_current": True,
                })
                if uid:
                    try:
                        features.record_user_ip(conn, int(uid), current_ip)
                    except Exception:
                        pass
        if not items:
            geo = features.ensure_ip_geo(conn, current_ip or "127.0.0.1", blocking=False)
            ip = (geo.get("ip") if isinstance(geo, dict) else None) or current_ip or "127.0.0.1"
            country, city, provider, code = geo_display(geo if isinstance(geo, dict) else {}, ip)
            if not country:
                hc, hcode = header_country(handler)
                if hc:
                    country, code = hc, hcode
            details = dict(geo if isinstance(geo, dict) else local_ip_details(ip))
            details["country"] = country
            details["country_name"] = country
            details["city"] = city or details.get("city") or ""
            details["provider"] = provider or details.get("provider") or ""
            details["isp"] = provider or details.get("isp") or ""
            details["country_code"] = code
            items.append({
                "key": "client_serials:1-checkapp-local",
                "id": "checkapp-local",
                "serial": "checkapp-local",
                "last_used": now,
                "created_at": now - 3600000,
                "ip": ip,
                "country": country,
                "country_name": country,
                "city": city or details.get("city") or "",
                "provider": provider,
                "isp": provider,
                "ip_details": details,
                "user_agent": "",
                "browser": "",
                "os": "",
                "current": True,
                "is_current": True,
            })
        return items

    return db_call(_build)


def player_stats_obj(conn, steam_id: str) -> dict:
    sid = str(steam_id)
    pid = current_pid() or 0
    kill_clause = " AND project_id = ?" if pid else " AND 0=1"
    kill_args = [pid] if pid else []
    kills = conn.execute(
        "SELECT COUNT(*) FROM kills WHERE initiator_steam_id = ?" + kill_clause, [sid, *kill_args]
    ).fetchone()[0]
    deaths = conn.execute(
        "SELECT COUNT(*) FROM kills WHERE target_steam_id = ?" + kill_clause, [sid, *kill_args]
    ).fetchone()[0]
    headshots = conn.execute(
        "SELECT COUNT(*) FROM kills WHERE initiator_steam_id = ? AND is_headshot = 1" + kill_clause,
        [sid, *kill_args],
    ).fetchone()[0]
    kd = round(kills / deaths, 2) if deaths else float(kills)
    hours = 0.0
    try:
        rows = conn.execute(
            "SELECT connected_at, disconnected_at FROM player_sessions WHERE steam_id = ?" + kill_clause,
            [sid, *kill_args],
        ).fetchall()
        total_ms = 0
        now = now_ms()
        for row in rows:
            start = int(row["connected_at"] or 0)
            end = int(row["disconnected_at"] or 0) or now
            if end > start:
                total_ms += end - start
        hours = round(total_ms / 3600000.0, 2)
    except Exception:
        pass
    reports = conn.execute(
        "SELECT COUNT(*) FROM reports WHERE target_steam_id = ?" + kill_clause, [sid, *kill_args]
    ).fetchone()[0]
    shots = max(kills, headshots)
    hits = kills
    body_hits = max(int(kills) - int(headshots), 0)
    limbs = 0
    try:
        bone_rows = conn.execute(
            "SELECT bone, COUNT(*) AS n FROM kills WHERE initiator_steam_id = ?" + kill_clause + " GROUP BY bone",
            [sid, *kill_args],
        ).fetchall()
        for brow in bone_rows:
            bone = str(brow["bone"] or "").lower()
            n = int(brow["n"] or 0)
            if "head" in bone or "jaw" in bone or "neck" in bone:
                headshots = int(headshots)
            elif any(part in bone for part in ("arm", "hand", "leg", "foot", "knee", "limb")):
                limbs += n
            elif bone and "head" not in bone:
                body_hits = max(body_hits, 0)
        if limbs:
            body_hits = max(int(kills) - int(headshots) - int(limbs), 0)
    except Exception:
        pass
    points = []
    try:
        day_hours = {}
        now = now_ms()
        for row in conn.execute(
            "SELECT connected_at, disconnected_at FROM player_sessions WHERE steam_id = ?" + kill_clause,
            [sid, *kill_args],
        ).fetchall():
            start = int(row["connected_at"] or 0)
            end = int(row["disconnected_at"] or 0) or now
            if end <= start:
                continue
            day = features._day_start(start)
            day_hours[day] = float(day_hours.get(day) or 0) + (end - start) / 3600000.0
        for i in range(7, -1, -1):
            t = features._day_start(now - i * 86400000)
            points.append({"time": t, "value": round(float(day_hours.get(t) or 0), 2), "hours": round(float(day_hours.get(t) or 0), 2)})
    except Exception:
        points = []
    if not points:
        now = now_ms()
        for i in range(7, -1, -1):
            t = features._day_start(now - i * 86400000)
            points.append({"time": t, "value": 0, "hours": 0})
    bone = {
        "head": int(headshots),
        "body": int(body_hits),
        "torso": int(body_hits),
        "limbs": int(limbs),
        "arms": int(limbs),
        "legs": int(limbs),
    }
    play_stats = {}
    for pt in points:
        t = int(pt.get("time") or 0)
        h = float(pt.get("hours") if pt.get("hours") is not None else pt.get("value") or 0)
        play_stats[str(t)] = {"date": t, "hours_played": round(h, 2)}
    kills_obj = {
        "steam_id": sid,
        "kills": int(kills),
        "deathes": int(deaths),
        "deaths": int(deaths),
        "kda": float(kd),
        "kd": float(kd),
        "kdr": float(kd),
        "bone_kills": bone,
        "headshots": int(headshots),
    }
    data = {
        # SPA Statistics tab (nested)
        "kills": kills_obj,
        "playTime": {"total": float(hours), "stats": play_stats},
        "reports": {"total_outcome": int(reports), "total": int(reports)},
        "steam": {"total_hours": float(hours)},
        # SPA small-stats / flat aliases
        "deathes": int(deaths),
        "deaths": int(deaths),
        "kd": float(kd),
        "kda": float(kd),
        "kdr": float(kd),
        "headshots": int(headshots),
        "in_head": int(headshots),
        "head": int(headshots),
        "body": int(body_hits),
        "in_body": int(body_hits),
        "in_torso": int(body_hits),
        "torso": int(body_hits),
        "limbs": int(limbs),
        "in_limbs": int(limbs),
        "in_limb": int(limbs),
        "shots": int(shots),
        "hits": int(hits),
        "hours": hours,
        "hours_played": hours,
        "hours_on_server": hours,
        "time_played": hours,
        "accuracy": round((hits / shots) * 100, 1) if shots else 0,
        "time_points": points,
        "playtime": points,
        "hours_chart": points,
        "bone_kills": bone,
        "hit_locations": {
            "head": int(headshots),
            "body": int(body_hits),
            "limbs": int(limbs),
        },
        "kills_deaths": {"kills": int(kills), "deaths": int(deaths)},
        "kills_count": int(kills),
    }
    data["stats"] = {
        "kills": int(kills),
        "deaths": int(deaths),
        "deathes": int(deaths),
        "kd": float(kd),
        "kda": float(kd),
        "hours": hours,
        "reports": int(reports),
        "bone_kills": bone,
    }
    data["data"] = dict(data)
    return data


def kill_ammo_for_weapon(weapon: str) -> str:
    w = str(weapon or "").lower()
    if any(x in w for x in ("glock", "python", "revolver", "pistol", "semiauto.pistol", "sap", "m92", "nailgun")):
        return "pistolbullet"
    if any(x in w for x in ("smg", "mp5", "thompson", "customsmg", "custom.smg")):
        return "pistolbullet"
    if any(x in w for x in ("shotgun", "spas", "pump", "waterpipe", "double")):
        return "handmade.shell"
    if any(x in w for x in ("bow", "crossbow", "legacy.bow")):
        return "arrow"
    return "riflebullet"


def kill_row_field(row, key, default=""):
    try:
        val = row[key]
    except Exception:
        return default
    return default if val is None else val


def _kill_lower_map(item: dict) -> dict:
    if not isinstance(item, dict):
        return {}
    return {str(k).lower(): v for k, v in item.items()}


def kill_pretty_name(name, steam_id: str = "") -> str:
    text = str(name or "").strip()
    sid = str(steam_id or "").strip()
    if not text or text == sid or text.isdigit():
        return ""
    if is_real_steam_id(text):
        return ""
    return text


def kill_id_and_name(val) -> tuple[str, str]:
    if isinstance(val, dict):
        m = _kill_lower_map(val)
        cand = ""
        for key in (
            "steam_id", "steamid", "steamid64", "steam_id64",
            "userid64", "steam", "userid", "user_id", "player_id", "id",
        ):
            raw = m.get(key)
            if raw in (None, "", False) or isinstance(raw, (dict, list)):
                continue
            text = str(raw).strip()
            if is_real_steam_id(text):
                cand = text
                break
            if text.isdigit() and not cand:
                cand = text
        nick = ""
        for key in ("steam_name", "name", "personaname", "display_name", "username", "player_name", "nick"):
            raw = kill_pretty_name(m.get(key), cand)
            if raw:
                nick = raw
                break
        return cand, nick
    if val not in (None, ""):
        text = str(val).strip()
        if is_real_steam_id(text) or text.isdigit():
            return text, ""
    return "", ""


def kill_party_ref(item: dict, *keys) -> tuple[str, str]:
    if not isinstance(item, dict):
        return "", ""
    m = _kill_lower_map(item)
    sid, name = "", ""
    for key in keys:
        got_sid, got_name = kill_id_and_name(m.get(str(key).lower()))
        if is_real_steam_id(got_sid) or (got_sid and not sid):
            sid = got_sid
        if got_name and not name:
            name = got_name
    return sid, name


def kill_steam_from_hits(hist: list, role: str) -> str:
    key = "attacker_steam_id" if role == "attacker" else "target_steam_id"
    if not isinstance(hist, list):
        return ""
    for hit in reversed(hist):
        if not isinstance(hit, dict):
            continue
        sid = str(hit.get(key) or "").strip()
        if is_real_steam_id(sid):
            return sid
    return ""


def resolve_kill_actor(conn, sid: str, fallback_name: str = "") -> tuple[str, str]:
    sid = str(sid or "").strip()
    name = kill_pretty_name(fallback_name, sid)
    if is_real_steam_id(sid):
        return sid, name
    if not sid.isdigit():
        return sid, name
    pid = current_pid() or 0
    if not pid:
        return sid, name
    try:
        ids = project_server_ids(conn) or []
        if ids:
            marks = ",".join("?" * len(ids))
            rows = conn.execute(
                f"SELECT steam_id, payload FROM online_players WHERE COALESCE(server_id, 1) IN ({marks})",
                ids,
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT steam_id, payload FROM online_players WHERE COALESCE(project_id, 0) = ?",
                (pid,),
            ).fetchall()
        needle = sid
        for row in rows:
            steam = str(row["steam_id"] or "")
            if not is_real_steam_id(steam):
                continue
            try:
                payload = json.loads(row["payload"] or "{}")
            except Exception:
                payload = {}
            if not isinstance(payload, dict):
                continue
            low = _kill_lower_map(payload)
            for key in ("userid", "user_id", "player_id", "id"):
                if str(low.get(key) or "").strip() == needle:
                    nick = kill_pretty_name(payload.get("steam_name") or payload.get("name"), steam)
                    return steam, nick or name
    except Exception:
        pass
    return sid, name


def kill_feed_player(conn, steam_id: str, fallback_name: str = "") -> dict:
    sid = str(steam_id or "").strip()
    pretty = ""
    if is_real_steam_id(sid):
        pretty = resolve_player_name(conn, sid, fallback_name)
    pretty = kill_pretty_name(pretty, sid) or kill_pretty_name(fallback_name, sid) or "Игрок"
    avatar = PLACEHOLDER
    if is_real_steam_id(sid):
        brief = player_brief_for_ban(conn, sid)
        avatar = str(brief.get("steam_avatar") or brief.get("avatar") or avatar)
        nick = kill_pretty_name(brief.get("steam_name") or "", sid)
        if nick:
            pretty = nick
    return {
        "id": sid or "0",
        "steam_id": sid or "0",
        "steamid": sid or "0",
        "steam_name": pretty,
        "name": pretty,
        "personaname": pretty,
        "display_name": pretty,
        "steam_avatar": avatar,
        "avatar": avatar,
        "status": "offline",
        "online": False,
        "is_online": False,
        "team": [],
    }


def kill_enrich_hits(hits: list, initiator_sid: str, target_sid: str, weapon: str = "") -> list:
    ammo = kill_ammo_for_weapon(weapon)
    out = []
    if not isinstance(hits, list):
        return out
    for hit in hits:
        if not isinstance(hit, dict):
            continue
        row = dict(hit)
        row["time"] = float(row.get("time") or 0)
        row["distance"] = float(row.get("distance") or 0)
        row["hp_old"] = float(row["hp_old"] if row.get("hp_old") is not None else 100)
        row["hp_new"] = float(row["hp_new"] if row.get("hp_new") is not None else 0)
        row["weapon"] = str(row.get("weapon") or weapon or "")
        row["ammo"] = str(row.get("ammo") or ammo or "riflebullet")
        bone = str(row.get("bone") or "spine")
        if bone.startswith("[") or bone in ("undefined", "null"):
            bone = "spine"
        row["bone"] = bone
        row["attacker"] = row.get("attacker") or "player"
        row["target"] = row.get("target") or "you"
        row["attacker_steam_id"] = str(row.get("attacker_steam_id") or initiator_sid or "")
        row["target_steam_id"] = str(row.get("target_steam_id") or target_sid or "")
        out.append(row)
    return out


def kill_hit_history(row, initiator_sid: str, target_sid: str) -> list:
    """SPA CombatlogModal needs full hit rows (time/hp/weapon/bone/distance)."""
    weapon = str(kill_row_field(row, "weapon") or "assets/prefabs/weapons/ak47u/ak47u.entity.prefab")
    ammo = kill_ammo_for_weapon(weapon)
    raw = None
    try:
        bone_val = str(kill_row_field(row, "bone") or "")
        if bone_val.strip().startswith("["):
            raw = bone_val
    except Exception:
        raw = None
    if isinstance(raw, str) and raw.strip().startswith("["):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list) and parsed:
                filled = kill_enrich_hits(parsed, initiator_sid, target_sid, weapon)
                if filled:
                    return filled
        except Exception:
            pass
    distance = float(kill_row_field(row, "distance", 0) or 0)
    is_hs = bool(kill_row_field(row, "is_headshot", 0))
    bone = str(kill_row_field(row, "bone") or "").strip()
    if bone.startswith("["):
        bone = ""
    if not bone:
        bone = "head" if is_hs else "spine"
    if bone.startswith("#bone_"):
        bone_key = bone
    else:
        bone_key = "#bone_" + bone.lstrip("#")
    hits = []
    if distance > 0 or weapon:
        hits.append({
            "time": 0.42,
            "attacker": "player",
            "attacker_steam_id": initiator_sid,
            "target": "you",
            "target_steam_id": target_sid,
            "weapon": weapon,
            "ammo": ammo,
            "bone": "#bone_spine" if is_hs else bone_key,
            "distance": max(distance * 0.85, 0.1),
            "hp_old": 100.0,
            "hp_new": 41.5,
            "info": "",
            "ad": False,
            "pi": 1,
            "pm": 0,
            "desync": 12,
            "proj_hits": 0,
            "proj_travel": 0.05,
        })
    hits.append({
        "time": 1.01,
        "attacker": "player",
        "attacker_steam_id": initiator_sid,
        "target": "you",
        "target_steam_id": target_sid,
        "weapon": weapon,
        "ammo": ammo,
        "bone": bone_key,
        "distance": max(distance, 0.1),
        "hp_old": 41.5 if hits else 100.0,
        "hp_new": 0.0,
        "info": "killed",
        "ad": False,
        "pi": 1,
        "pm": 0,
        "desync": 18,
        "proj_hits": 0,
        "proj_travel": 0.08,
    })
    return hits


def kill_names_from_hits(hist: list) -> tuple[str, str]:
    attacker, victim = "", ""
    if not isinstance(hist, list):
        return attacker, victim
    for hit in hist:
        if not isinstance(hit, dict):
            continue
        for key in ("attacker_name", "initiator_name", "killer_name"):
            nick = kill_pretty_name(hit.get(key))
            if nick:
                attacker = nick
        for key in ("target_name", "victim_name", "player_name"):
            nick = kill_pretty_name(hit.get(key))
            if nick:
                victim = nick
    return attacker, victim


def kill_feed_items(conn, steam_id: str) -> list:
    sid = str(steam_id)
    pid = current_pid() or 0
    kill_clause = " AND project_id = ?" if pid else " AND 0=1"
    kill_args = [pid] if pid else []
    items = []
    for row in conn.execute(
        """SELECT * FROM kills
           WHERE (initiator_steam_id = ? OR target_steam_id = ?)""" + kill_clause + """
           ORDER BY id DESC LIMIT 200""",
        [sid, sid, *kill_args],
    ).fetchall():
        a = str(kill_row_field(row, "initiator_steam_id") or "")
        b = str(kill_row_field(row, "target_steam_id") or "")
        weapon = str(kill_row_field(row, "weapon") or "")
        hist = kill_hit_history(row, a, b)
        steam_a = kill_steam_from_hits(hist, "attacker")
        steam_b = kill_steam_from_hits(hist, "target")
        if is_real_steam_id(steam_a):
            a = steam_a
        if is_real_steam_id(steam_b):
            b = steam_b
        hit_attacker, hit_victim = kill_names_from_hits(hist)
        a_name = kill_pretty_name(kill_row_field(row, "initiator_name"), a) or hit_attacker
        b_name = kill_pretty_name(kill_row_field(row, "target_name"), b) or hit_victim
        a, a_name = resolve_kill_actor(conn, a, a_name)
        b, b_name = resolve_kill_actor(conn, b, b_name)
        hist = kill_enrich_hits(hist, a, b, weapon)
        initiator = kill_feed_player(conn, a, a_name)
        target = kill_feed_player(conn, b, b_name)
        bone = str(kill_row_field(row, "bone") or "")
        if bone.startswith("[") or bone in ("undefined", "null"):
            bone = ""
        if not bone and hist:
            bone = str(hist[-1].get("bone") or "")
        ammo = str((hist[-1].get("ammo") if hist else "") or kill_ammo_for_weapon(weapon))
        items.append({
            "id": row["id"],
            "initiator_steam_id": a,
            "target_steam_id": b,
            "weapon": weapon,
            "ammo": ammo,
            "distance": float(kill_row_field(row, "distance", 0) or 0),
            "is_headshot": bool(kill_row_field(row, "is_headshot", 0)),
            "headshot": bool(kill_row_field(row, "is_headshot", 0)),
            "created_at": kill_row_field(row, "created_at", 0),
            "bone": bone,
            "hit_history": hist,
            "connected_steam_ids": [x for x in (a, b) if is_real_steam_id(x)],
            "initiator_player": initiator,
            "target_player": target,
            "initiator": initiator,
            "target": target,
            "server_id": 1,
        })
    return items


def require_plugin(headers) -> bool:
    token = plugin_auth_token(headers)
    if not token:
        print("PLUGIN auth missing x-plugin-auth")
        return False

    def _c(conn):
        return plugin_server_row(conn, headers) is not None

    ok = bool(db_call(_c))
    if not ok:
        print("PLUGIN auth rejected token_len", len(token))
    return ok


class Handler(SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def bind_auth_user(self):
        def _u(conn):
            auth = self.headers.get("Authorization") or self.headers.get("authorization") or ""
            if not str(auth or "").strip():
                cookie = str(self.headers.get("Cookie") or self.headers.get("cookie") or "")
                for part in cookie.split(";"):
                    key, _, val = part.strip().partition("=")
                    if key in ("access_token", "token"):
                        auth = unquote(val or "").strip()
                        break
            REQ.account_blocked = False
            payload = features.parse_access_token(auth)
            user = features.user_from_token_payload(conn, payload)
            uid = int((user or {}).get("id") or 0)
            if uid and features.is_protected_owner(conn, uid):
                pass
            elif uid and features.user_account_blocked(conn, uid):
                print("[RustApp] blocked account uid", uid)
                REQ.account_blocked = True
            ip = ""
            try:
                ip = admin_panel.client_ip(self)
            except Exception:
                ip = ""
            if ip and features.is_user_ip_blocked(conn, ip) and not features.is_protected_owner(conn, uid):
                if uid and not features.user_account_blocked(conn, uid):
                    features.set_user_account_blocked(conn, uid, True, "request_from_blocked_user_ip")
                print("[RustApp] blocked user IP rejected", ip)
                REQ.account_blocked = True
            REQ.user_id = uid
            features.set_request_user(uid)
            REQ.user = user
            if uid and ip and not REQ.account_blocked and features.user_session_revoked(conn, uid, ip):
                # Same public IP / current browser must stay signed in.
                # Revoking "all sessions" used to 401 handshake and gray-screen the SPA.
                print("[RustApp] revive current session uid", uid, "ip", ip)
                try:
                    features.record_user_ip(conn, uid, ip, revive=True)
                except Exception:
                    pass
            return user

        try:
            return db_call(_u)
        except Exception:
            REQ.user_id = 0
            REQ.user = None
            features.set_request_user(0)
            return None

    def bind_project(self):
        self.bind_auth_user()
        referer = self.headers.get("Referer") or self.headers.get("referer") or ""
        path = urlparse(self.path).path
        header_slug = self.headers.get("X-Checkapp-Project") or self.headers.get("x-checkapp-project") or ""

        def _b(conn):
            REQ.project_id = resolve_project_id(conn, referer, path, header_slug)
            token = plugin_auth_token(self.headers)
            if token:
                row = plugin_server_row(conn, self.headers)
                if row:
                    REQ.project_id = int(row.get("project_id") or 0) or REQ.project_id
            features.set_request_project(REQ.project_id)
            return REQ.project_id

        try:
            db_call(_b)
        except Exception:
            REQ.project_id = 0
            features.set_request_project(0)

    def _need_server(self):
        state = db_call(project_runtime)
        if state.get("ok"):
            return False
        # Allow queueing if this project has any server row (heartbeat / pair flag may lag)
        try:
            def _any_server(conn):
                pid = current_pid()
                if not pid:
                    return None
                return conn.execute(
                    """SELECT id FROM servers
                       WHERE project_id = ?
                       ORDER BY paired DESC, last_seen DESC, id DESC LIMIT 1""",
                    (pid,),
                ).fetchone()

            if db_call(_any_server):
                return False
        except Exception:
            pass
        self._json({"ok": False, "message": state.get("message") or "Сервер проекта не подключён"}, 400)
        return True

    def log_message(self, fmt, *args):
        msg = fmt % args if args else str(fmt)
        msg = re.sub(r"(access_token|token)=[^&\s]+", r"\1=REDACTED", str(msg), flags=re.I)
        print("[%s] %s" % (self.log_date_time_string(), msg))

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()

    def _json(self, data, status=200):
        raw = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _realtime_sse(self, params):
        """Long-lived SSE. Events are already scoped to current_pid()."""
        slug = ""
        try:
            slug = str((params.get("project") or params.get("slug") or [""])[0] or "")
        except Exception:
            slug = ""
        token = ""
        try:
            token = str((params.get("access_token") or params.get("token") or [""])[0] or "")
        except Exception:
            token = ""
        if token and not (self.headers.get("Authorization") or self.headers.get("authorization")):
            try:
                self.headers.replace_header("Authorization", "Bearer " + token.strip())
            except Exception:
                self.headers["Authorization"] = "Bearer " + token.strip()
        self.bind_auth_user()
        referer = self.headers.get("Referer") or self.headers.get("referer") or ""
        path = urlparse(self.path).path

        def _b(conn):
            REQ.project_id = resolve_project_id(conn, referer, path, slug)
            features.set_request_project(REQ.project_id)
            return REQ.project_id

        try:
            db_call(_b)
        except Exception:
            REQ.project_id = 0
            features.set_request_project(0)
        pid = current_pid() or 0
        if not pid:
            return self._json({"message": "no project", "events": []}, 401)
        since = 0
        try:
            since = int((params.get("since") or params.get("after") or ["0"])[0] or 0)
        except Exception:
            since = 0
        # Never hold a worker: nginx 502s /check/activity and chat GET while SSE blocks.
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.send_header("Retry-After", "3600")
        self.end_headers()
        try:
            self.wfile.write(b"retry: 3600000\n\n")
            self.wfile.flush()
        except Exception:
            pass

    def _html(self, body: bytes, status: int = 200, content_type: str = "text/html; charset=utf-8"):
        raw = body or b""
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _auth_public_base(self) -> str:
        host = self.headers.get("Host") or "127.0.0.1:8081"
        xf = (self.headers.get("X-Forwarded-Proto") or self.headers.get("x-forwarded-proto") or "").split(",")[0].strip()
        if xf in ("http", "https"):
            scheme = xf
        elif "localhost" in host or host.startswith("127.0.0.1"):
            scheme = "http"
        else:
            scheme = "https"
        return oauth_auth.public_base(scheme, host)

    def _record_auth_ip(self, uid: int) -> None:
        try:
            ip = admin_panel.client_ip(self)
            if ip and uid:
                db_call(lambda c: features.record_user_ip(c, int(uid), ip, revive=True))
        except Exception:
            pass

    def _auth_login_response(self, user: dict | None):
        if isinstance(user, dict):
            user.pop("_new", None)
            user.pop("_existing", None)
        if not user:
            return self._json({"message": "password.missmatch"}, 400)

        def _guard(conn):
            ip = admin_panel.client_ip(self)
            return oauth_auth.auth_login_denied(conn, user, ip)

        blocked = db_call(_guard)
        if blocked:
            return self._json(blocked, 403)
        token = oauth_auth.issue_login_token(user)
        REQ.user_id = int(user.get("id") or 0)
        features.set_request_user(REQ.user_id)
        self._record_auth_ip(int(user.get("id") or 0))
        return self._json(token)

    def _public_url(self, path: str) -> str:
        host = self.headers.get("Host") or "127.0.0.1:8081"
        if "https=" not in path:
            path = f"{path}{'&' if '?' in path else '?'}https=1"
        xf = (self.headers.get("X-Forwarded-Proto") or self.headers.get("x-forwarded-proto") or "").split(",")[0].strip()
        if xf in ("http", "https"):
            scheme = xf
        elif "localhost" in host or host.startswith("127.0.0.1"):
            scheme = "http"
        else:
            scheme = "https"
        return f"{scheme}://{host}{path}"

    def _save_upload(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        data = raw
        filename = ""
        if b"filename=" in raw:
            try:
                head = raw.split(b"\r\n\r\n", 1)[0].decode("utf-8", "ignore")
                m = re.search(r'filename="([^"]+)"', head)
                if m:
                    filename = m.group(1)
            except Exception:
                filename = ""
            parts = raw.split(b"\r\n\r\n", 1)
            if len(parts) > 1:
                data = parts[1]
                end = data.rfind(b"\r\n--")
                if end > 0:
                    data = data[:end]
        if not data:
            data = PLACEHOLDER.encode("utf-8")
        ext = ".jpg"
        low_name = str(filename or "").lower()
        for cand in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
            if low_name.endswith(cand):
                ext = cand
                break
        name = f"{uuid.uuid4().hex}{ext}"
        (UPLOADS / name).write_bytes(data)
        # SPA Urls.Images() keeps the value as-is only if it contains "https".
        url = f"/uploads/{name}?https=1"
        return self._json(url)

    def _read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except Exception:
            return {}

    def _parts(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        params = parse_qs(parsed.query)
        return path, params

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,PUT,PATCH,DELETE,OPTIONS")
        self.end_headers()

    def do_PATCH(self):
        # SPA may PATCH court/discord/options — treat as PUT
        return self.do_PUT()

    def is_api_path(self, path):
        prefixes = (
            "/admin/api",
            "/plugin", "/queue", "/ban", "/auth", "/utils", "/project", "/project-stats",
            "/court-autokick", "/court-api", "/court-commands", "/court-discord",
            "/court-integrations", "/court",
            "/players", "/player-alert", "/player-message", "/player-mute", "/player-premium",
            "/player", "/reports", "/server", "/check", "/signage",
            "/sleeping-bag", "/tariff", "/audit", "/suggestion", "/public", "/webhook",
            "/map", "/ban-sync", "/auto-kick", "/realtime", "/events",
            "/billing",
        )
        return any(path == p or path.startswith(p + "/") for p in prefixes)

    def _send_plugin_file(self):
        host = self.headers.get("Host") or ""
        xf = (self.headers.get("X-Forwarded-Proto") or self.headers.get("x-forwarded-proto") or "").split(",")[0].strip()
        cfg = plugin_download_config(host, xf)
        ext = str(cfg.get("download_url") or "").strip()
        filename = str(cfg.get("filename") or "RustApp.cs")
        if ext.startswith("http://") or ext.startswith("https://"):
            from urllib.parse import urlparse
            parsed = urlparse(ext)
            ext_host = (parsed.hostname or "").lower()
            req_host = host.lower().split(":")[0]
            same_site = (
                ext_host
                and req_host
                and ext_host == req_host
                and parsed.path.rstrip("/").endswith("/plugin/download")
            )
            if not same_site:
                self.send_response(302)
                self.send_header("Location", ext)
                self.end_headers()
                return
        path = plugin_cs_path()
        data = path.read_bytes() if path.is_file() else b"// RustApp plugin file is missing\n"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path, params = self._parts()
        if path in ("/billing/platega/return", "/billing/platega/fail"):
            loc = platega_pay.return_redirect(params)
            self.send_response(302)
            self.send_header("Location", loc)
            self.end_headers()
            return
        if path in ("/plugin/config", "/plugin/config/"):
            host = self.headers.get("Host") or ""
            xf = (self.headers.get("X-Forwarded-Proto") or self.headers.get("x-forwarded-proto") or "").split(",")[0].strip()
            return self._json(plugin_download_config(host, xf))
        if is_plugin_download(path):
            return self._send_plugin_file()
        if path == "/local/discord-webhook-info":
            return self._json({
                "channel_id": "1",
                "guild_id": "1",
                "name": "Rustcheck",
                "type": 1,
                "application_id": None,
            })
        accept = (self.headers.get("Accept") or "").lower()
        auth = self.headers.get("Authorization") or ""
        client_api = path in ("/client", "/client/profile", "/client/browse") and (
            auth.startswith("Bearer") or "application/json" in accept or path == "/client/browse"
        )
        if self.is_api_path(path) or client_api:
            try:
                return self.api_get(path, params)
            except Exception as exc:
                print("GET error", path, exc)
                return self._json({"message": str(exc)}, 500)
        try:
            return self.static_get()
        except Exception as exc:
            print("static GET error", path, exc)
            return self.send_error(500, "static")

    def do_POST(self):
        path, params = self._parts()
        if path == "/court-integrations/rcc" or (path.startswith("/players/") and path.endswith("/rcc")):
            return self._json({"message": "Интеграция удалена"}, 410)
        if path == "/utils/upload":
            return self._save_upload()
        ctype = (self.headers.get("Content-Type") or "").lower()
        if path.rstrip("/") == "/admin/api/chat" and "multipart/form-data" in ctype:
            length = int(self.headers.get("Content-Length") or 0)
            if length > 55 * 1024 * 1024:
                return self._json({"ok": False, "message": "Файл слишком большой (макс. 50 МБ)"}, 413)
            raw = self.rfile.read(length) if length else b""
            body = {
                "_multipart_raw": raw,
                "_content_type": self.headers.get("Content-Type") or "",
            }
            try:
                return self.api_post(path, params, body)
            except Exception as exc:
                print("POST error", path, exc)
                return self._json({"message": str(exc)}, 500)
        body = self._read_json()
        try:
            return self.api_post(path, params, body)
        except Exception as exc:
            print("POST error", path, exc)
            return self._json({"message": str(exc)}, 500)

    def do_PUT(self):
        path, params = self._parts()
        if path == "/court-integrations/rcc" or (path.startswith("/players/") and path.endswith("/rcc")):
            return self._json({"message": "Интеграция удалена"}, 410)
        body = self._read_json()
        try:
            return self.api_put(path, params, body)
        except Exception as exc:
            print("PUT error", path, exc)
            return self._json({"message": str(exc)}, 500)

    def do_DELETE(self):
        path, params = self._parts()
        if path == "/court-integrations/rcc" or (path.startswith("/players/") and path.endswith("/rcc")):
            return self._json({"message": "Интеграция удалена"}, 410)
        body = self._read_json()
        try:
            return self.api_delete(path, params, body)
        except Exception as exc:
            print("DELETE error", path, exc)
            return self._json({"message": str(exc)}, 500)

    def static_get(self):
        path = urlparse(self.path).path
        # Serve real landing at / so Checkapp landing patches (footer TG/DS, no map, etc.) load.
        if path in ("/", "/index.html", "/index.htm"):
            self.path = "/index.html"
            return self._send_index_no_cache()
        if path in ("/admin", "/admin/", "/admin.html"):
            return self._send_admin_no_cache()
        if path.startswith("/admin/") and not path.startswith("/admin/api"):
            sub = path[len("/admin/"):].split("/")[0].lower()
            if sub in ("admin.js", "admin.css") or sub == "admin.html":
                fs = ROOT / sub
                if fs.is_file():
                    ctype = "text/css; charset=utf-8" if sub.endswith(".css") else (
                        "text/html; charset=utf-8" if sub.endswith(".html") else "application/javascript; charset=utf-8"
                    )
                    return self._send_file_no_cache(fs, ctype)
            return self._send_admin_no_cache()
        if path in ("/admin.css", "/admin.js"):
            fs = ROOT / path.lstrip("/")
            if fs.is_file():
                ctype = "text/css; charset=utf-8" if path.endswith(".css") else "application/javascript; charset=utf-8"
                return self._send_file_no_cache(fs, ctype)
        if path.startswith("/uploads/"):
            name = path.split("/")[-1]
            fs = UPLOADS / name
            if fs.exists() and fs.is_file():
                data = fs.read_bytes()
                low = name.lower()
                ctype = "application/octet-stream"
                if low.endswith(".png"):
                    ctype = "image/png"
                elif low.endswith(".jpg") or low.endswith(".jpeg"):
                    ctype = "image/jpeg"
                elif low.endswith(".webp"):
                    ctype = "image/webp"
                elif low.endswith(".gif"):
                    ctype = "image/gif"
                elif low.endswith(".webm"):
                    ctype = "video/webm"
                elif low.endswith(".mp4"):
                    ctype = "video/mp4"
                elif low.endswith(".ogg"):
                    ctype = "audio/ogg"
                elif low.endswith(".mp3"):
                    ctype = "audio/mpeg"
                elif low.endswith(".wav"):
                    ctype = "audio/wav"
                elif low.endswith(".m4a"):
                    ctype = "audio/mp4"
                elif low.endswith(".mov"):
                    ctype = "video/quicktime"
                elif low.endswith(".svg"):
                    ctype = "image/svg+xml"
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "public, max-age=86400")
                self.end_headers()
                self.wfile.write(data)
                return
        if path.endswith("/onboarding") or path == "/onboarding":
            self.send_response(302)
            self.send_header("Location", path.rsplit("/onboarding", 1)[0] + "/players")
            self.end_headers()
            return
        if path == "/profile" or path.startswith("/profile/"):
            self.send_response(302)
            self.send_header("Location", "/client/profile")
            self.end_headers()
            return
        # JS bundles have explicit ?v= versions in index.html.  They must be
        # cacheable: forcing a new 4 MB download on every page navigation made
        # the remote panel feel much slower than the local copy.
        low = path.lower()
        if low in ("/mock-local.js", "/checkapp-gates.js", "/ml78.js") or low.endswith("/mock-local.js") or low.endswith("/checkapp-gates.js") or low.endswith("/ml78.js"):
            return self._send_file_cached(ROOT / path.lstrip("/").replace("/", os.sep), "application/javascript; charset=utf-8")
        if low.split("?")[0].endswith("/logo-mark.svg"):
            fs = ROOT / "local" / "image-1024.jpg"
            if fs.is_file():
                return self._send_file_no_cache(fs, "image/jpeg")
        if low.endswith(".js") or "index-ctjll1yw.js" in low:
            fs = ROOT / path.lstrip("/").replace("/", os.sep)
            if fs.exists() and fs.is_file():
                return self._send_file_cached(fs, "application/javascript; charset=utf-8")
        # Always use OS path separator — hardcoding "\\" breaks /local images on Linux VDS
        rel = path.lstrip("/").replace("/", os.sep)
        fs = ROOT / rel
        static_ext = (
            ".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg", ".ico",
            ".css", ".js", ".map", ".woff", ".woff2", ".ttf", ".webm", ".mp4",
        )
        if path != "/" and not fs.exists():
            if any(low.split("?")[0].endswith(ext) for ext in static_ext) or path.startswith(("/local/", "/uploads/", "/assets/")):
                if any(low.split("?")[0].endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg", ".ico")):
                    placeholder = ROOT / "local" / "image-1024.jpg"
                    if placeholder.is_file():
                        return self._send_file_no_cache(placeholder, "image/jpeg")
                self.send_error(404, "File not found")
                return
            if not path.startswith("/admin"):
                self.path = "/index.html"
                return self._send_index_no_cache()
        # Serve /local and other static files with correct Content-Type
        if fs.exists() and fs.is_file() and path.startswith(("/local/", "/assets/", "/uploads/")):
            ctype = mimetypes.guess_type(str(fs))[0] or "application/octet-stream"
            return self._send_file_cached(fs, ctype)
        self.path = "/" + rel.replace("\\", "/")
        return SimpleHTTPRequestHandler.do_GET(self)

    def _send_index_no_cache(self):
        data = (ROOT / "index.html").read_bytes()
        if b'id="checkapp-starttime-fix"' not in data:
            data = data.replace(b"<head>", b"<head>\n" + START_TIME_FIX.encode("utf-8"), 1)
        if b'id="checkapp-landing-s3-fix"' not in data:
            data = data.replace(b"<head>", b"<head>\n" + LANDING_S3_FIX.encode("utf-8"), 1)
        # Rewrite mock-local.js and checkapp-gates.js version params to match
        # BUILD_ID so cached copies are invalidated on every deploy.
        try:
            stamp = BUILD_ID.encode("utf-8")
            data = re.sub(rb'mock-local\.js\?v=[^"\']+', b'mock-local.js?v=' + stamp, data)
            data = re.sub(rb'checkapp-gates\.js\?v=[^"\']+', b'checkapp-gates.js?v=' + stamp, data)
            data = re.sub(rb'ml78\.js\?v=[^"\']+', b'ml78.js?v=' + stamp, data)
            # /assets/*.js is served with max-age=31536000, immutable and the
            # main bundle file name is not content-hashed, so it must carry a
            # deploy stamp too or returning visitors keep the old bundle.
            data = re.sub(rb'assets/index-map-avatars\.js\?v=[^"\']+', b'assets/index-map-avatars.js?v=' + stamp, data)
            data = re.sub(rb'assets/index-CtjlL1Yw\.js\?v=[^"\']+', b'assets/index-CtjlL1Yw.js?v=' + stamp, data)
        except Exception:
            pass
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.end_headers()
        self.wfile.write(data)

    def _send_admin_no_cache(self):
        data = (ROOT / "admin.html").read_bytes()
        stamp = str(int(time.time()))
        try:
            text = data.decode("utf-8")
            text = re.sub(r"admin\.js\?v=[^\"']+", "admin.js?v=" + stamp, text)
            text = re.sub(r"admin\.css\?v=[^\"']+", "admin.css?v=" + stamp, text)
            text = re.sub(r'src="/admin\.js"', 'src="/admin.js?v=' + stamp + '"', text)
            text = re.sub(r'href="/admin\.css"', 'href="/admin.css?v=' + stamp + '"', text)
            data = text.encode("utf-8")
        except Exception:
            pass
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.end_headers()
        self.wfile.write(data)

    def _send_file_no_cache(self, fs: Path, ctype: str):
        if not fs.exists() or not fs.is_file():
            self.send_error(404)
            return
        data = fs.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.end_headers()
        self.wfile.write(data)

    _GZIP_CACHE: dict = {}

    def _send_file_cached(self, fs: Path, ctype: str):
        if not fs.exists() or not fs.is_file():
            self.send_error(404)
            return
        raw = fs.read_bytes()
        accepts_gzip = "gzip" in (self.headers.get("Accept-Encoding") or "").lower()
        use_gzip = accepts_gzip and ("javascript" in ctype or ctype.startswith("text/") or "json" in ctype)
        mtime = fs.stat().st_mtime
        cache_key = str(fs) + ("|gz" if use_gzip else "")
        cached = self._GZIP_CACHE.get(cache_key)
        if cached and cached[0] == mtime:
            data = cached[1]
        elif use_gzip:
            data = gzip.compress(raw, compresslevel=6)
            self._GZIP_CACHE[cache_key] = (mtime, data)
        else:
            data = raw
            self._GZIP_CACHE[cache_key] = (mtime, data)
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "public, max-age=31536000, immutable")
        if use_gzip:
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Vary", "Accept-Encoding")
        self.end_headers()
        self.wfile.write(data)

    # ------------------------------------------------------------------ API
    def api_get(self, path, params):
        if path.startswith("/admin/api"):
            if admin_panel.handle_api(self, "GET", path, params, None):
                return
        if path == "/billing/platega/methods":
            def _methods(conn):
                platega_pay.ensure_schema(conn)
                return platega_pay.configured(conn)

            return self._json(db_call(_methods))
        if path == "/billing/platega/status":
            def _st(conn):
                return platega_pay.payment_status(conn, params)

            data, code = db_call(_st)
            return self._json(data, code)
        self.bind_project()
        if path in ("/plugin", "/plugin/"):
            if not require_plugin(self.headers):
                return self._json({"message": "authorization secret is corrupted"}, 401)

            def _ok(conn):
                row = plugin_server_row(conn, self.headers)
                if row:
                    conn.execute(
                        "UPDATE servers SET connected = 1, last_seen = ? WHERE id = ?",
                        (now_s(), int(row["id"])),
                    )
                return {"ok": True}

            return self._json(db_call(_ok))

        if path in ("/queue", "/queue/"):
            if not require_plugin(self.headers):
                return self._json({"message": "authorization secret is corrupted"}, 401)

            def _q(conn):
                row = plugin_server_row(conn, self.headers)
                if not row:
                    return []
                pid = int(row.get("project_id") or 0)
                conn.execute(
                    "UPDATE servers SET connected = 1, last_seen = ? WHERE id = ?",
                    (now_s(), int(row["id"])),
                )
                if not pid:
                    return []
                rows = conn.execute(
                    """SELECT id, name, data FROM queue
                       WHERE done = 0 AND COALESCE(project_id, 0) = ?
                       ORDER BY created_at ASC LIMIT 40""",
                    (pid,),
                ).fetchall()
                tasks = []
                for item in rows:
                    try:
                        data = json.loads(item["data"])
                    except Exception:
                        data = {}
                    if item["name"] == "freeze-set" and int(data.get("server_id") or 0) != int(row["id"]):
                        continue
                    tasks.append({"id": item["id"], "request": {"name": item["name"], "data": data}})
                return tasks

            return self._json(db_call(_q))

        if path == "/auth/classic/validate":
            email = (params.get("email") or [""])[0].lower()

            def _ex(conn):
                row = conn.execute("SELECT id FROM users WHERE lower(email) = ?", (email,)).fetchone()
                return {"exists": bool(row), "email": email}

            return self._json(db_call(_ex))

        if path == "/auth/steam/link":
            return_url = str((params.get("return_url") or [""])[0] or "").strip()
            if not return_url:
                return_url = self._auth_public_base() + "/client/auth"
            realm = return_url.split("?", 1)[0]
            url = oauth_auth.steam_openid_link(return_url, realm)
            return self._json(url)

        if path == "/auth/steam/validate":
            query = str((params.get("query") or [""])[0] or "")
            profile = oauth_auth.verify_steam_openid(query)
            if not profile:
                return self._json({"message": "steam.invalid", "exists": False}, 400)
            sid = str(profile.get("steam_id") or "")

            def _exists(conn):
                row = oauth_auth.find_user_by_steam(conn, sid)
                return {
                    "exists": bool(row),
                    "steam_id": sid,
                    "steam_name": profile.get("steam_name") or sid,
                    "steam_avatar": profile.get("steam_avatar") or PLACEHOLDER,
                }

            return self._json(db_call(_exists))

        if path == "/auth/discord/link":
            if not oauth_auth.discord_authorize_ready():
                print("discord link unavailable: DISCORD_CLIENT_ID missing")
                return self._json({"message": "discord.not.configured", "url": ""})
            return_url = str((params.get("return_url") or [""])[0] or "").strip()
            if not return_url:
                return_url = self._auth_public_base() + "/client/auth"
            callback = oauth_auth.discord_callback_url(
                (self.headers.get("X-Forwarded-Proto") or "https").split(",")[0].strip(),
                self.headers.get("Host") or "",
            )
            url = oauth_auth.discord_authorize_link(return_url, callback)
            return self._json(url)

        if path == "/auth/discord/callback":
            code = str((params.get("code") or [""])[0] or "")
            state = str((params.get("state") or [""])[0] or "")
            state_payload = oauth_auth.verify_oauth_state(state)
            if not code or not state_payload:
                return self._html(b"Invalid OAuth state", 400)
            callback = oauth_auth.discord_callback_url(
                (self.headers.get("X-Forwarded-Proto") or "https").split(",")[0].strip(),
                self.headers.get("Host") or "",
            )
            profile = oauth_auth.discord_exchange_code(code, callback)
            if not profile:
                return self._html(b"Discord authorization failed", 400)
            query = oauth_auth.pack_provider_query("discord", profile)
            self.bind_auth_user()
            try:
                uid = int(state_payload.get("uid") or getattr(REQ, "user_id", 0) or 0)
            except Exception:
                uid = 0
            if uid:
                def _link(conn):
                    user = features.user_by_id(conn, uid)
                    if not user:
                        return None
                    did = str(profile.get("discord_id") or "")
                    other = oauth_auth.find_user_by_discord(conn, did)
                    if other and int(other.get("id") or 0) != uid:
                        print("discord callback skipped: discord.busy", did)
                        return None
                    linked = oauth_auth.link_discord_to_user(
                        conn,
                        user,
                        did,
                        str(profile.get("discord_name") or did),
                        str(profile.get("discord_avatar") or ""),
                        str(profile.get("discord_username") or ""),
                    )
                    if linked:
                        features.audit(conn, "auth.discord_connect", {"discord_id": did, "user_id": uid, "via": "callback"})
                    return linked

                try:
                    db_call(_link)
                except Exception as exc:
                    print("discord callback link failed", type(exc).__name__, exc)
            return_url = str(state_payload.get("return_url") or "")
            return self._html(oauth_auth.discord_callback_html(query, return_url))

        if path == "/auth/discord/validate":
            query = str((params.get("query") or [""])[0] or "")
            profile = oauth_auth.verify_discord_query(query)
            if not profile:
                return self._json({"message": "discord.invalid", "exists": False}, 400)
            did = str(profile.get("discord_id") or "")

            def _exists(conn):
                row = oauth_auth.find_user_by_discord(conn, did)
                return {
                    "exists": bool(row),
                    "discord_id": did,
                    "discord_name": profile.get("discord_name") or did,
                    "discord_avatar": profile.get("discord_avatar") or PLACEHOLDER,
                }

            return self._json(db_call(_exists))

        if path == "/auth/google/config":
            return self._json(oauth_auth.google_public_config())

        if path == "/auth/google/link":
            if not oauth_auth.google_configured():
                return self._json({"message": "google.not.configured"}, 503)
            return_url = str((params.get("return_url") or [""])[0] or "").strip()
            if not return_url:
                return_url = self._auth_public_base() + "/client/auth"
            callback = oauth_auth.google_callback_url(
                (self.headers.get("X-Forwarded-Proto") or "https").split(",")[0].strip(),
                self.headers.get("Host") or "",
            )
            url = oauth_auth.google_authorize_link(return_url, callback)
            return self._json(url)

        if path == "/auth/google/callback":
            code = str((params.get("code") or [""])[0] or "")
            state = str((params.get("state") or [""])[0] or "")
            state_payload = oauth_auth.verify_oauth_state(state)
            if not code or not state_payload:
                return self._html(b"Invalid OAuth state", 400)
            callback = oauth_auth.google_callback_url(
                (self.headers.get("X-Forwarded-Proto") or "https").split(",")[0].strip(),
                self.headers.get("Host") or "",
            )
            profile = oauth_auth.google_exchange_code(code, callback)
            if not profile:
                return self._html(b"Google authorization failed", 400)
            query = oauth_auth.pack_provider_query("google", profile)
            return self._html(oauth_auth.google_callback_html(query))

        if path == "/auth/google/validate":
            query = str((params.get("query") or [""])[0] or "")
            credential = str((params.get("credential") or [""])[0] or "")
            profile = oauth_auth.verify_google_query(query or credential)
            if not profile and credential:
                profile = oauth_auth.google_verify_id_token(credential)
            if not profile:
                return self._json({"message": "google.invalid", "exists": False}, 400)
            gid = str(profile.get("google_id") or "")

            def _exists(conn):
                row = oauth_auth.find_user_by_google(conn, gid)
                if not row and profile.get("email"):
                    row = oauth_auth.find_user_by_google_email(conn, profile.get("email"))
                return {
                    "exists": bool(row),
                    "google_id": gid,
                    "google_name": profile.get("google_name") or profile.get("name") or gid,
                    "google_avatar": profile.get("google_avatar") or profile.get("avatar") or PLACEHOLDER,
                    "email": profile.get("email") or "",
                }

            return self._json(db_call(_exists))

        if path == "/auth/google-connect":
            self.bind_auth_user()
            uid = int(getattr(REQ, "user_id", 0) or features.request_user_id() or 0)
            if not uid:
                return self._json({"message": "unauthorized", "unauthorized": True}, 401)
            if not oauth_auth.google_configured():
                return self._json({"message": "google.not.configured"}, 503)
            return_url = str((params.get("return_url") or [""])[0] or "").strip()
            if not return_url:
                return_url = self._auth_public_base() + "/client/profile"
            callback = oauth_auth.google_callback_url(
                (self.headers.get("X-Forwarded-Proto") or "https").split(",")[0].strip(),
                self.headers.get("Host") or "",
            )
            url = oauth_auth.google_authorize_link(return_url, callback)
            return self._json(url)

        if path == "/auth/steam-connect":
            self.bind_auth_user()
            uid = int(getattr(REQ, "user_id", 0) or features.request_user_id() or 0)
            if not uid:
                return self._json({"message": "unauthorized", "unauthorized": True}, 401)
            return_url = str((params.get("return_url") or [""])[0] or "").strip()
            if not return_url:
                return_url = self._auth_public_base() + "/client/auth"
            realm = return_url.split("?", 1)[0]
            url = oauth_auth.steam_openid_link(return_url, realm)
            return self._json(url)

        if path == "/auth/discord-connect":
            self.bind_auth_user()
            uid = int(getattr(REQ, "user_id", 0) or features.request_user_id() or 0)
            if not uid:
                return self._json({"message": "unauthorized", "unauthorized": True}, 401)
            if not oauth_auth.discord_authorize_ready():
                print("discord connect unavailable: DISCORD_CLIENT_ID missing")
                return self._json({"message": "discord.not.configured", "url": ""})
            return_url = str((params.get("return_url") or [""])[0] or "").strip()
            if not return_url:
                return_url = str(self.headers.get("Referer") or self.headers.get("referer") or "").strip()
            if not return_url:
                return_url = self._auth_public_base() + "/client/profile"
            base = self._auth_public_base()
            parsed = urlparse(base)
            callback = oauth_auth.discord_callback_url(parsed.scheme or "http", parsed.netloc or (self.headers.get("Host") or ""))
            url = oauth_auth.discord_authorize_link(return_url, callback, uid=uid)
            return self._json(url)

        if path == "/auth/telegram-connect":
            return self._json({
                "url": "",
                "available": False,
                "disabled": True,
                "connected": False,
                "message": "telegram.unavailable",
            })

        if path == "/auth/handshake":
            user = getattr(REQ, "user", None)
            blocked = bool(getattr(REQ, "account_blocked", False))
            if blocked:
                payload = client_obj(user=user) if user else {
                    "id": 0, "unauthorized": True, "name": "", "email": "",
                }
                payload["account_blocked"] = True
                payload["blocked"] = True
                payload["code"] = "account.blocked"
                payload["message"] = "Ваш аккаунт заблокирован. Обратитесь в поддержку за помощью."
                payload["title"] = "Аккаунт заблокирован"
                return self._json(payload, 200 if user else 403)
            if not user:
                return self._json({"message": "unauthorized", "unauthorized": True}, 401)
            return self._json(client_obj(user=user))
        if path == "/auth/sessions":
            return self._json(current_sessions(self))
        if path == "/utils/exchange":
            return self._json(90)
        if path in ("/utils/build", "/utils/version"):
            plugin = plugin_cs_path()
            return self._json({
                "build": BUILD_ID,
                "realtime": "sse",
                "plugin": str(plugin),
                "plugin_exists": plugin.is_file(),
                "root": str(ROOT.resolve()),
            })
        if path == "/utils/stats":
            return self._json(service_stats())
        if path == "/utils/landing-feed":
            return self._json(landing_feed())
        if path == "/utils/countries":
            return self._json(["Russia", "Ukraine", "Germany", "United States", "China", "Turkey"])
        if path == "/utils/tariff":
            return self._json(tariff_state())
        if path == "/tariff" or path == "/tariff/":
            return self._json(tariff_state())
        if path == "/utils/can-project-create":
            def _can(conn):
                ok = features.can_create_project(conn)
                limit = features.account_projects_limit(conn)
                uid = features.request_user_id()
                if uid:
                    count = int(
                        conn.execute(
                            "SELECT COUNT(*) FROM project WHERE COALESCE(owner_user_id, 0) = ?",
                            (uid,),
                        ).fetchone()[0]
                    )
                else:
                    count = 0
                return {
                    "can": ok,
                    "allowed": ok,
                    "ok": ok,
                    "limit": limit,
                    "count": count,
                    "used": count,
                }

            return self._json(db_call(_can))
        if path == "/utils/permissions":
            return self._json(list(PERMISSIONS))
        if path == "/utils/news":
            return self._json(None)
        if path == "/utils/client-by-id" or path == "/utils/client-by-tag":
            tag = str((params.get("tag") or params.get("name") or params.get("nick") or [""])[0] or "").strip().lstrip("@")
            cid = str((params.get("id") or params.get("client_id") or [""])[0] or "").strip()

            def _lookup(conn):
                user = None
                if tag:
                    user = features.user_by_tag(conn, tag)
                if user is None and cid and str(cid).lstrip("-").isdigit():
                    user = features.user_by_id(conn, int(cid))
                if not user:
                    return None
                return client_obj(conn, user)

            found = db_call(_lookup)
            if not found or not int((found or {}).get("id") or 0):
                return self._json({"message": "Пользователь не найден", "error": "user_not_found"}, 404)
            return self._json(found)
        if path == "/client/browse":
            q = str((params.get("search") or params.get("tag") or params.get("q") or params.get("name") or [""])[0] or "").strip().lstrip("@")
            # ClientInline sends batched IDs (often as ids[]=1&ids[]=2).  The
            # previous handler only read the first scalar value and then fell
            # back to current staff, so old moderation records lost their real
            # author as soon as that person was removed from the project.
            requested_ids = []
            for value in param_values(params, "id", "ids", "client_id", "client_ids"):
                if str(value).lstrip("-").isdigit():
                    uid = int(value)
                    if uid not in requested_ids:
                        requested_ids.append(uid)
            cid = str(requested_ids[0]) if requested_ids else ""

            def _browse_clients(conn):
                if requested_ids:
                    out = []
                    for uid in requested_ids:
                        user = features.user_by_id(conn, uid)
                        if user:
                            out.append(client_obj(conn, user))
                            continue
                        name = "Удалённый сотрудник"
                        try:
                            prow = conn.execute(
                                "SELECT checker_name FROM checks WHERE checker_id = ? AND COALESCE(checker_name,'') != '' ORDER BY id DESC LIMIT 1",
                                (uid,),
                            ).fetchone()
                        except Exception:
                            prow = None
                        if prow:
                            name = str(prow["checker_name"] or name)
                        out.append({
                            "id": uid,
                            "M_ID": uid,
                            "name": name,
                            "tag": "staff",
                            "avatar": PLACEHOLDER,
                            "status": "offline",
                            "online": False,
                            "is_online": False,
                            "former_member": True,
                            "deleted": True,
                            "steam": features.empty_steam_profile(PLACEHOLDER),
                            "steam_id": "",
                        })
                    return out
                if q:
                    row = conn.execute(
                        "SELECT * FROM users WHERE lower(COALESCE(tag, '')) = ?",
                        (q.lower(),),
                    ).fetchone()
                    me = int(features.request_user_id() or 0)
                    if not row:
                        return []
                    if me and int(row["id"] or 0) == me:
                        return []
                    return [client_obj(conn, dict(row))]
                pid = current_pid() or features.request_project_id() or 0
                out = []
                seen = set()
                payload = features.staff_list_payload(conn, pid, list(PERMISSIONS)) if pid else {"active": []}
                for row in (payload.get("active") or []) + (payload.get("all") or []):
                    client = row.get("client") if isinstance(row, dict) else None
                    if not isinstance(client, dict):
                        continue
                    uid = int(client.get("id") or 0)
                    if not uid or uid in seen:
                        continue
                    seen.add(uid)
                    out.append(client)
                if not out:
                    me = client_obj(conn)
                    if int(me.get("id") or 0):
                        out.append(me)
                return out

            return self._json(db_call(_browse_clients))
        if path == "/project":
            return self._json(list_projects())
        if path.startswith("/project/") and path.endswith("/wallet"):
            key = path.split("/")[2]

            def _wallet(conn):
                pid = 0
                if str(key).isdigit():
                    pid = int(key)
                else:
                    row = get_project_row(key)
                    pid = int(row.get("id") or 0) if row else 0
                if not pid:
                    pid = int(current_pid() or features.request_project_id() or 0)
                bal = features.project_balance(conn, pid)
                return {"balance": bal, "amount": bal, "value": bal}

            return self._json(db_call(_wallet))
        if path.startswith("/project/") and path.endswith("/wallet-operations"):
            key = path.split("/")[2]

            def _ops(conn):
                pid = 0
                if str(key).isdigit():
                    pid = int(key)
                else:
                    row = conn.execute(
                        "SELECT id FROM project WHERE lower(domain) = ? OR lower(name) = ?",
                        (str(key).lower(), str(key).lower()),
                    ).fetchone()
                    if row:
                        pid = int(row["id"])
                if not pid:
                    pid = features.request_project_id() or current_pid()
                items = features.wallet_operations_list(conn, pid)
                return browse(items, params)

            return self._json(db_call(_ops))
        if path.startswith("/project/") and path.endswith("/general"):
            pid = path.split("/")[2]
            return self._json(project_obj(get_project_row(pid) or {"id": pid}))
        if path.startswith("/project/") and path.endswith("/clients-settings"):
            parts = [p for p in path.strip("/").split("/") if p]
            pid = 0
            if len(parts) >= 2 and parts[1].isdigit():
                pid = int(parts[1])
            elif len(parts) >= 2:
                row = get_project_row(parts[1])
                pid = int(row.get("id") or 0) if row else 0
            if not pid:
                pid = int(current_pid() or features.request_project_id() or 0)
            row = get_project_row(pid) if pid else None
            return self._json(project_obj(row or {"id": pid}))
        if path.startswith("/project/") and (path.endswith("/clients") or path.endswith("/clients-v2")):
            parts = [p for p in path.strip("/").split("/") if p]
            pid = 0
            if len(parts) >= 2 and parts[1].isdigit():
                pid = int(parts[1])
            elif len(parts) >= 2:
                row = get_project_row(parts[1])
                pid = int(row.get("id") or 0) if row else 0
            if not pid:
                pid = int(current_pid() or features.request_project_id() or 0)

            def _clients(conn):
                try:
                    return features.staff_list_payload(conn, pid, list(PERMISSIONS))
                except Exception as exc:
                    print("clients list failed", exc)
                    return {"active": [], "all": []}

            return self._json(db_call(_clients))
        parts = path.split("/")
        if len(parts) == 3 and parts[1] == "project":
            row = get_project_row(parts[2])
            if not row:
                return self._json({"message": "not found"}, 404)
            return self._json(project_obj(row))
        if path.startswith("/client/") and len(path.split("/")) == 3 and path.split("/")[2].isdigit():
            uid = int(path.split("/")[2])

            def _one_client(conn):
                user = features.user_by_id(conn, uid)
                if user:
                    return client_obj(conn, user)
                snap_name = ""
                snap_email = ""
                snap_role = "staff"
                for sql in (
                    """SELECT actor_name, actor_email, actor_role FROM bans
                       WHERE COALESCE(actor_user_id, 0) = ? AND COALESCE(actor_name,'') != ''
                       ORDER BY id DESC LIMIT 1""",
                    """SELECT actor_name, actor_email, actor_role FROM mutes
                       WHERE COALESCE(actor_user_id, 0) = ? AND COALESCE(actor_name,'') != ''
                       ORDER BY id DESC LIMIT 1""",
                    """SELECT checker_name AS actor_name, checker_email AS actor_email, '' AS actor_role FROM checks
                       WHERE COALESCE(checker_id, 0) = ? AND COALESCE(checker_name,'') != ''
                       ORDER BY id DESC LIMIT 1""",
                ):
                    try:
                        snap = conn.execute(sql, (uid,)).fetchone()
                    except Exception:
                        snap = None
                    if snap:
                        snap_name = str(snap["actor_name"] or "")
                        snap_email = str(snap["actor_email"] or "")
                        snap_role = str(snap["actor_role"] or "staff")
                        if snap_name:
                            break
                name = features.human_actor_name(snap_name, snap_email, "") or snap_name
                if features.is_generic_staff_label(name):
                    name = snap_email.split("@")[0] if "@" in snap_email else ""
                if not name:
                    name = "Удалённый сотрудник"
                tag = features.staff_public_tag({"name": name, "email": snap_email, "tag": ""}, name, conn)
                return {
                    "id": uid,
                    "M_ID": uid,
                    "name": name,
                    "email": snap_email,
                    "tag": tag,
                    "role": snap_role or "staff",
                    "avatar": PLACEHOLDER,
                    "status": "offline",
                    "online": False,
                    "is_online": False,
                    "former_member": True,
                    "deleted": not bool(snap_name),
                    "steam": features.empty_steam_profile(PLACEHOLDER),
                    "steam_id": "",
                }

            return self._json(db_call(_one_client))
        if path == "/client" or path == "/client/profile" or path == "/client/auth":
            user = getattr(REQ, "user", None)
            if not user:
                return self._json({"message": "unauthorized", "unauthorized": True}, 401)
            return self._json(client_obj(user=user))
        if path in ("/client/twofactor", "/client/2fa", "/auth/twofactor"):
            return self._json(db_call(twofa_payload))

        if path == "/court":
            return self._json(db_call(court_payload))
        if path == "/court-commands":
            return self._json(db_call(features.court_commands_list))
        if path in ("/court-commands/history", "/command-log", "/commands/history", "/command-history"):
            def _cl(conn):
                foreign = foreign_project_from_params(params)
                if foreign:
                    allowed = set(features.subscribed_foreign_project_ids(conn) or [])
                    if foreign not in allowed:
                        return browse([], params)
                    return browse(features.command_log_items(conn, project_id=foreign), params)
                return browse(features.command_log_items(conn), params)

            return self._json(db_call(_cl))
        if path == "/court-commands/preset":
            return self._json(features.court_commands_preset())
        if path == "/court-api":
            return self._json(db_call(features.court_api_state))
        if path == "/court/discord" or path == "/court-discord":
            return self._json(db_call(features.discord_list))
        if path == "/court/recap":
            return self._json({})
        if path == "/court-integrations/rcc":
            return self._json({"message": "Интеграция удалена"}, 410)
        if path.startswith("/court-autokick") or path.startswith("/auto-kick") or path in ("/court-autokick", "/auto-kick"):
            try:
                return self._json(db_call(features.autokick_list))
            except Exception as exc:
                print("autokick list failed", type(exc).__name__, exc)
                return self._json(autokick_rules())

        if path == "/server/overview":
            return self._json(db_call(project_home_overview))
        if path == "/server":
            return self._json(db_call(list_project_servers))
        if path.startswith("/server/") and path.endswith("/confirmation"):
            return self._json({"ok": True, "confirmed": True, "required": False, "token": "local"})
        if path.startswith("/server/") and path[8:].split("/")[0].isdigit():
            sid = path.split("/")[2]

            def _one(conn):
                row = conn.execute("SELECT * FROM servers WHERE id = ?", (sid,)).fetchone()
                if not row:
                    return {"message": "not found"}
                view = server_view(conn, row)
                pid = current_pid()
                if pid and int(view.get("project_id") or 0) != pid:
                    return {"message": "not found"}
                return view

            return self._json(db_call(_one))
        if path == "/server/pair":
            def _pair(conn):
                requested = str((params.get("code") or [""])[0] or "").strip()
                if requested:
                    padded = requested.zfill(6) if requested.isdigit() and len(requested) <= 6 else requested
                    row = conn.execute(
                        "SELECT * FROM pair_codes WHERE code = ? OR code = ?",
                        (requested, padded),
                    ).fetchone()
                    if not row:
                        return {"message": "Code not exists"}
                    wanted_name = str((params.get("name") or params.get("hostname") or [""])[0] or "").strip()
                    if wanted_name:
                        try:
                            conn.execute(
                                "UPDATE pair_codes SET server_name = ? WHERE code = ? OR code = ?",
                                (wanted_name, requested, padded),
                            )
                        except Exception:
                            pass
                    pid = int(row["project_id"] or 0) or current_pid() or 0
                    if not pid:
                        return {"message": "Code not exists"}
                    server = None
                    if int(row["used"] or 0):
                        linked = conn.execute("SELECT value FROM settings WHERE key=?", (f"pair_token_{row['code']}",)).fetchone()
                        srv = plugin_server_row(conn, {"X-Plugin-Auth": str(linked["value"] or "")}) if linked else None
                        if srv and int(srv.get("project_id") or 0) == pid:
                            server = server_view(conn, srv)
                    token_row = conn.execute(
                        "SELECT value FROM settings WHERE key = ?",
                        (f"pair_token_{requested}",),
                    ).fetchone()
                    token_val = str(token_row["value"] or "") if token_row else ""
                    return {
                        "code": requested,
                        "command": f"ra.pair {requested}",
                        "used": bool(row["used"]),
                        "server": server,
                        "plugin": server,
                        "token": token_val or None,
                    }
                if not features.can_add_server(conn, current_pid()):
                    return {
                        "message": "server-limit-exceeded",
                        "error": "server-limit-exceeded",
                        "code": "",
                        "command": "",
                        "used": False,
                        "server": None,
                        "token": None,
                    }
                wanted_name = str((params.get("name") or params.get("hostname") or [""])[0] or "")
                code = make_pair_code(conn, "", server_name=wanted_name)
                row = conn.execute("SELECT * FROM pair_codes WHERE code = ?", (code,)).fetchone()
                return {
                    "code": code,
                    "command": f"ra.pair {code}",
                    "used": bool(row and row["used"]),
                    "server": None,
                    "token": None,
                    "name": wanted_name or pair_code_server_name(conn, code),
                }

            return self._json(db_call(_pair))

        if path in ("/players/browse-full", "/players/browse-minimal"):
            return self._json(self._browse_players(params, full=path.endswith("full")))
        if path == "/players/find-by-ip":
            ips = param_values(params, "ips", "ip")
            # SPA DataLoader: array of { ip, result: { players, ip_details } }

            def _find_by_ip(conn):
                out = []
                for raw_ip in ips:
                    ip = str(raw_ip or "").strip()
                    if not ip:
                        continue
                    # Normalize common IPv4:port / [IPv6]:port
                    if ip.count(":") == 1 and "." in ip:
                        ip = ip.split(":", 1)[0].strip()
                    if ip.startswith("[") and "]" in ip:
                        ip = ip[1 : ip.index("]")]
                    if not ip or ip in ("0.0.0.0", "*", "%", "127.0.0.1"):
                        continue
                    # This endpoint is used by the player activity/IP panels.
                    # They need final geo data in their first response, not a
                    # temporary pending object which the SPA never refreshed.
                    geo = features.ensure_ip_geo(conn, ip, blocking=True)
                    if not isinstance(geo, dict):
                        geo = local_ip_details(ip)
                    if isinstance(geo, dict):
                        geo.pop("pending", None)
                    country, city, provider, code = geo_display(geo, ip)
                    if not country and features._is_private_ip(ip):
                        country, city, provider, code = "Локальная сеть", "LAN", "Private network", ""
                    ip_details = {
                        "ip": str((geo or {}).get("ip") or ip),
                        "country": country,
                        "country_name": country,
                        "city": city,
                        "provider": provider,
                        "isp": provider,
                        "org": (geo or {}).get("org") or provider,
                        "proxy": bool((geo or {}).get("proxy")),
                        "country_code": code,
                        "updated_at": int((geo or {}).get("updated_at") or now_ms()),
                    }
                    players = []
                    seen_sid = set()
                    # Exact IP, or that IPv4 with a trailing :port — never LIKE '%'
                    like_pat = ip + ":%" if "." in ip else None
                    if like_pat:
                        rows = conn.execute(
                            """SELECT DISTINCT steam_id FROM player_ips
                               WHERE ip = ? OR ip LIKE ?
                               ORDER BY last_seen DESC LIMIT 100""",
                            (ip, like_pat),
                        ).fetchall()
                    else:
                        rows = conn.execute(
                            """SELECT DISTINCT steam_id FROM player_ips
                               WHERE ip = ?
                               ORDER BY last_seen DESC LIMIT 100""",
                            (ip,),
                        ).fetchall()
                    for row in rows:
                        sid = str(row["steam_id"] or "").strip()
                        if not sid or sid in seen_sid:
                            continue
                        seen_sid.add(sid)
                        try:
                            players.append(player_view(conn, sid, nest_team=False))
                        except Exception:
                            players.append({
                                "steam_id": sid,
                                "steam_name": sid,
                                "name": sid,
                                "ip": ip,
                            })
                    # Also include online players currently on this IP (this project only)
                    try:
                        ids = project_server_ids(conn)
                        if ids:
                            marks = ",".join("?" * len(ids))
                            online_rows = conn.execute(
                                f"SELECT steam_id, payload FROM online_players WHERE COALESCE(server_id, 1) IN ({marks})",
                                ids,
                            ).fetchall()
                        else:
                            pid_now = current_pid() or 0
                            online_rows = conn.execute(
                                "SELECT steam_id, payload FROM online_players WHERE COALESCE(project_id, 0) = ?",
                                (pid_now,),
                            ).fetchall() if pid_now else []
                        for orow in online_rows:
                            sid = str(orow["steam_id"] or "").strip()
                            if not sid or sid in seen_sid:
                                continue
                            try:
                                payload = json.loads(orow["payload"] or "{}")
                            except Exception:
                                payload = {}
                            pip = str((payload or {}).get("ip") or "").strip()
                            if pip.count(":") == 1 and "." in pip:
                                pip = pip.split(":", 1)[0].strip()
                            if pip != ip:
                                continue
                            seen_sid.add(sid)
                            try:
                                players.append(player_view(conn, sid, nest_team=False))
                            except Exception:
                                players.append({
                                    "steam_id": sid,
                                    "steam_name": sid,
                                    "name": sid,
                                    "ip": ip,
                                })
                    except Exception:
                        pass
                    out.append({
                        "ip": ip,
                        "result": {
                            "players": players,
                            "ip_details": ip_details,
                        },
                    })
                return out

            return self._json(db_call(_find_by_ip))
        if path in ("/players/find-by-contact", "/players/find-by-discord"):
            raw = param_values(params, "contacts", "contact", "discord", "q")
            if not raw:
                raw = param_values(params, "values")

            def _find_contact(conn):
                out = []
                pid = current_pid() or 0
                for raw_c in raw:
                    key = features.normalize_contact(raw_c)
                    matches = features.find_contact_matches(conn, raw_c, "", pid) if key else []
                    out.append({
                        "contact": str(raw_c or "").strip(),
                        "normalized": key,
                        "result": {"players": matches, "matches": matches},
                    })
                return out

            return self._json(db_call(_find_contact))
        if path == "/players/kda":
            def _kda(conn):
                raw_ids = param_values(params, "steam_ids", "steam_ids[]", "steam_id")
                # axios may send steam_ids as comma-joined or repeated
                ids = []
                for raw in raw_ids:
                    for part in str(raw or "").split(","):
                        part = part.strip()
                        if part and part not in ids:
                            ids.append(part)
                if not ids:
                    ids = [r["steam_id"] for r in conn.execute("SELECT steam_id FROM players LIMIT 400").fetchall()]
                time_from = int((params.get("time_from") or ["0"])[0] or 0)
                time_to = int((params.get("time_to") or ["0"])[0] or 0) or now_ms()
                items = []
                for sid in ids:
                    sid = str(sid or "").strip()
                    if not sid:
                        continue
                    try:
                        if time_from > 0:
                            krow = conn.execute(
                                "SELECT COUNT(*) AS c FROM kills WHERE initiator_steam_id = ? AND created_at >= ? AND created_at <= ?",
                                (sid, time_from, time_to),
                            ).fetchone()
                            drow = conn.execute(
                                "SELECT COUNT(*) AS c FROM kills WHERE target_steam_id = ? AND created_at >= ? AND created_at <= ?",
                                (sid, time_from, time_to),
                            ).fetchone()
                            kills = int((krow["c"] if krow else 0) or 0)
                            deaths = int((drow["c"] if drow else 0) or 0)
                        else:
                            stats = player_stats_obj(conn, sid)
                            kills = int(stats.get("kills_count") or 0)
                            deaths = int(stats.get("deaths") or 0)
                    except Exception:
                        kills = deaths = 0
                    kd = round(kills / deaths, 2) if deaths else float(kills)
                    items.append({
                        "steam_id": sid,
                        "kills": kills,
                        "deaths": deaths,
                        "deathes": deaths,  # SPA typo in ReportsTable tooltip
                        "kd": kd,
                        "kda": kd,
                        "kdr": kd,
                    })
                return items

            return self._json(db_call(_kda))

        if path.startswith("/players/") and path.endswith("/details"):
            steam_id = path.split("/")[2]
            try:
                if not is_real_steam_id(steam_id):
                    return self._json(player_details_safe(steam_id, ""))
                details = db_call(lambda c: player_details(c, steam_id))
                if not isinstance(details, dict):
                    details = player_details_safe(steam_id, "")
                if details.get("player"):
                    try:
                        enrich_player_live(details["player"])
                    except Exception as exc:
                        print("enrich_player_live failed", steam_id, type(exc).__name__, exc)
                    details["player"] = ensure_player_shape(details["player"], steam_id)
                    details["entity"] = details["player"].get("entity")
                    details["team"] = details["player"].get("team") or []
                else:
                    details = player_details_safe(steam_id, "")
                return self._json(details)
            except Exception as exc:
                print("player details failed", steam_id, type(exc).__name__, exc)
                return self._json(player_details_safe(steam_id, ""))
        if path == "/player-premium/verify":
            return self._json({
                "exists": False,
                "premium": False,
                "is_premium": False,
                "verified": False,
                "active": False,
            })
        if path.startswith("/players/") and (path.endswith("/comments") or path.endswith("/notes")):
            steam_id = path.split("/")[2]

            def _cm(conn):
                author = staff_brief(conn)
                rows = conn.execute(
                    "SELECT * FROM comments WHERE steam_id = ?" + project_clause()[0] + " ORDER BY id DESC LIMIT 50",
                    [steam_id, *project_clause()[1]],
                ).fetchall()
                return [comment_obj(r, author) for r in rows]

            return self._json(db_call(_cm))
        if path.startswith("/players/") and path.endswith("/reports"):
            steam_id = path.split("/")[2]
            return self._json(self._browse_reports({"target_steam_id": [steam_id]}))
        if path.startswith("/players/") and path.endswith("/checks"):
            steam_id = path.split("/")[2]
            return self._json(self._browse_checks({"steam_id": [steam_id]}))
        if path.startswith("/players/") and path.endswith("/kill-feed"):
            steam_id = path.split("/")[2]

            def _kf(conn):
                items = kill_feed_items(conn, steam_id)
                n = len(items)
                return {
                    "data": items,
                    "results": items,
                    "items": items,
                    "total": n,
                    "count": n,
                    "limit": max(n + 1, 20),
                    "per_page": max(n + 1, 20),
                    "page": 1,
                    "current_page": 1,
                    "last_page": 1,
                    "has_more": False,
                    "hasMore": False,
                    "done": True,
                    "finished": True,
                    "next_cursor": None,
                    "next_page": None,
                    "links": {"next": None},
                    "meta": {
                        "total": n,
                        "page": 1,
                        "limit": max(n + 1, 20),
                        "last_page": 1,
                        "has_more": False,
                        "done": True,
                        "next_cursor": None,
                        "next_page_url": None,
                    },
                }

            return self._json(db_call(_kf))
        if path.startswith("/players/") and path.endswith("/stats"):
            steam_id = path.split("/")[2]
            return self._json(db_call(lambda c: player_stats_obj(c, steam_id)))
        if path.startswith("/players/") and path.endswith("/small-stats"):
            steam_id = path.split("/")[2]

            def _small(conn):
                data = dict(player_stats_obj(conn, steam_id))
                nested = data.get("kills")
                if isinstance(nested, dict):
                    # SPA overview calls kills.toString() — needs a number
                    data["kills"] = int(nested.get("kills") or 0)
                elif not isinstance(nested, (int, float)):
                    data["kills"] = int(data.get("kills_count") or 0)
                return data

            return self._json(db_call(_small))
        if path.startswith("/players/") and path.endswith("/team-history"):
            steam_id = path.split("/")[2]

            def _th(conn):
                items = features.team_history_items(conn, steam_id)
                # Backfill from live online team if history is empty — THIS project only
                if not items:
                    try:
                        pid = current_pid() or 0
                        ids = project_server_ids(conn)
                        online = []
                        if ids:
                            marks = ",".join("?" * len(ids))
                            online = conn.execute(
                                f"SELECT steam_id, payload FROM online_players WHERE COALESCE(server_id, 1) IN ({marks})",
                                ids,
                            ).fetchall()
                        elif pid:
                            online = conn.execute(
                                "SELECT steam_id, payload FROM online_players WHERE COALESCE(project_id, 0) = ?",
                                (pid,),
                            ).fetchall()
                        mates = []
                        for orow in online:
                            try:
                                payload = json.loads(orow["payload"] or "{}")
                            except Exception:
                                payload = {}
                            tids = team_ids_of(payload.get("team"))
                            osid = str(orow["steam_id"] or "")
                            if osid == steam_id:
                                mates = [m for m in tids if m != steam_id]
                                break
                            if steam_id in tids:
                                mates = [m for m in tids if m != steam_id]
                                if osid and osid != steam_id and osid not in mates:
                                    mates = [osid] + mates
                                break
                        if mates:
                            features.save_team_snapshot(conn, steam_id, mates, pid)
                            items = features.team_history_items(conn, steam_id)
                    except Exception as exc:
                        print("team history backfill failed", exc)
                cursor, cursor_sent = parse_ms_cursor(
                    qfirst(params, "last_seen_at", "ended_at", "created_at", "cursor", "next_cursor")
                )
                try:
                    page = int(qfirst(params, "page") or 0)
                except Exception:
                    page = 0
                try:
                    limit = int(qfirst(params, "limit") or 20) or 20
                except Exception:
                    limit = 20
                if cursor_sent:
                    if cursor:
                        items = [
                            x for x in items
                            if int((x or {}).get("last_seen_at") or (x or {}).get("ended_at") or (x or {}).get("started_at") or 0) < cursor
                        ]
                    else:
                        items = []
                    chunk = items[:limit]
                    more = len(items) > limit
                else:
                    start = max(0, page) * limit
                    chunk = items[start:start + limit]
                    more = (start + limit) < len(items)
                packed = {
                    "data": chunk,
                    "results": chunk,
                    "items": chunk,
                    "total": len(chunk) if not more else (len(chunk) + 1),
                    "count": len(chunk),
                    "limit": limit if more else max(limit, len(chunk) + 1),
                    "per_page": limit,
                    "page": page + 1,
                    "current_page": page + 1,
                    "last_page": (page + 1) if not more else (page + 2),
                    "has_more": more,
                    "hasMore": more,
                    "done": not more,
                    "finished": not more,
                    "next_cursor": None if not more else (
                        (chunk[-1] or {}).get("last_seen_at") if chunk else None
                    ),
                    "next_page": None if not more else (page + 1),
                    "links": {"next": None} if not more else {},
                    "meta": {
                        "total": len(chunk),
                        "page": page + 1,
                        "limit": limit if more else max(limit, len(chunk) + 1),
                        "last_page": (page + 1) if not more else (page + 2),
                        "has_more": more,
                        "done": not more,
                        "next_cursor": None if not more else True,
                        "next_page_url": None,
                    },
                }
                return packed

            return self._json(db_call(_th))
        if path.startswith("/players/") and path.endswith("/session-history"):
            steam_id = path.split("/")[2]

            def _sh(conn):
                items = []
                pid = current_pid() or 0
                if not pid:
                    return browse([], params)
                sql = "SELECT * FROM player_sessions WHERE steam_id = ? AND COALESCE(project_id, 0) = ? ORDER BY id DESC LIMIT 200"
                rows = conn.execute(sql, (steam_id, pid)).fetchall()
                servers = {}
                geo_by_ip = {}
                for srow in conn.execute(
                    "SELECT id, name, hostname, server_ip, port FROM servers WHERE project_id = ?",
                    (pid,),
                ).fetchall():
                    servers[int(srow["id"] or 0)] = srow
                for row in rows:
                    sid = int(row["server_id"] or 0)
                    srv = servers.get(sid)
                    if not srv and sid:
                        srv = conn.execute(
                            "SELECT id, name, hostname, server_ip, port FROM servers WHERE id = ? AND COALESCE(project_id, 0) = ?",
                            (sid, pid),
                        ).fetchone()
                    sname = ""
                    sip = ""
                    sport = 0
                    if srv:
                        sname = str(srv["name"] or srv["hostname"] or "").strip()
                        sip = str(srv["server_ip"] or "").strip()
                        try:
                            sport = int(srv["port"] or 0)
                        except Exception:
                            sport = 0
                    if not sname:
                        sname = features.format_server_endpoint(sip, sport) or ""
                    ip_raw = str(row["ip"] or "")
                    # These rows are rendered directly in the player's activity log.
                    # Returning a pending placeholder here left the UI permanently
                    # showing "Unknown" because the page does not refetch the row
                    # after the background lookup finishes. Resolve the (usually
                    # cached) value before returning this detail view.
                    if ip_raw not in geo_by_ip:
                        geo_by_ip[ip_raw] = features.ensure_ip_geo(conn, ip_raw, blocking=True) if ip_raw else {}
                    geo = geo_by_ip.get(ip_raw) or {}
                    if not isinstance(geo, dict):
                        geo = {}
                    country, city, provider, code = geo_display(geo, ip_raw)
                    ip_details = {
                        "ip": row["ip"] or "",
                        "country": country,
                        "country_name": country,
                        "city": city,
                        "provider": provider,
                        "isp": provider,
                        "org": geo.get("org") or provider,
                        "country_code": code,
                    }
                    is_lic = bool(row["is_license"])
                    try:
                        sc = features.read_cache(conn, "steam_cache", "steam_id", steam_id)
                        if isinstance(sc, dict) and sc.get("owns_rust") is True:
                            is_lic = True
                        elif isinstance(sc, dict) and sc.get("owns_rust") is False:
                            is_lic = False
                    except Exception:
                        pass
                    items.append({
                        "id": row["id"],
                        "steam_id": steam_id,
                        "ip": row["ip"] or "",
                        "connected_at": row["connected_at"],
                        "disconnected_at": row["disconnected_at"] or None,
                        "disconnected_reason": row["disconnected_reason"] or "",
                        "is_license": is_lic,
                        "project_id": pid,
                        "server_id": sid or None,
                        "server_name": sname,
                        "server_ip": sip,
                        "server_port": sport,
                        "country": country,
                        "country_name": country,
                        "city": city,
                        "provider": provider,
                        "isp": provider,
                        "ip_details": ip_details,
                        "computed_ip": ip_details,
                        "server": {
                            "id": sid,
                            "name": sname if sname and not (sname.startswith("#") and sname[1:].isdigit()) else (sip or "Rust"),
                            "hostname": sname,
                            "server_ip": sip,
                            "port": sport,
                        } if sid or sname else None,
                    })
                return browse(items, params)

            return self._json(db_call(_sh))
        if path.startswith("/players/") and path.endswith("/ip-history"):
            steam_id = path.split("/")[2]

            def _ih(conn):
                items = []
                pid = current_pid() or 0
                if not pid:
                    return browse([], params)
                # player_ips is keyed by steam+ip; restrict via sessions of this project when possible
                session_ips = {
                    str(r["ip"] or "")
                    for r in conn.execute(
                        "SELECT DISTINCT ip FROM player_sessions WHERE steam_id = ? AND COALESCE(project_id, 0) = ?",
                        (steam_id, pid),
                    ).fetchall()
                    if r["ip"]
                }
                rows = conn.execute(
                    "SELECT * FROM player_ips WHERE steam_id = ? ORDER BY last_seen DESC LIMIT 200", (steam_id,)
                ).fetchall()
                for row in rows:
                    ip = str(row["ip"] or "")
                    if session_ips and ip not in session_ips:
                        continue
                    # IP history is a detail screen, so send real geo fields with
                    # the first response instead of a transient pending stub.
                    geo = features.ensure_ip_geo(conn, ip, blocking=True) if ip else None
                    if not isinstance(geo, dict):
                        geo = local_ip_details(ip)
                    geo.pop("pending", None)
                    country, city, provider, code = geo_display(geo, ip)
                    if not country and features._is_private_ip(ip):
                        country, city, provider, code = "Локальная сеть", "LAN", "Private network", ""
                    items.append({
                        "id": f"{row['steam_id']}-{row['ip']}",
                        "steam_id": steam_id,
                        "ip": row["ip"],
                        "created_at": row["first_seen"],
                        "first_seen": row["first_seen"],
                        "last_seen": row["last_seen"],
                        "count": row["count"],
                        "country": country,
                        "country_name": country,
                        "city": city,
                        "provider": provider,
                        "isp": provider,
                        "org": geo.get("org") or provider,
                        "proxy": bool(geo.get("proxy")),
                        "country_code": code,
                        "ip_details": {
                            "ip": ip,
                            "country": country,
                            "country_name": country,
                            "city": city,
                            "provider": provider,
                            "isp": provider,
                            "org": geo.get("org") or provider,
                            "country_code": code,
                        },
                        "computed_ip": {
                            "ip": ip,
                            "country": country,
                            "country_name": country,
                            "city": city,
                            "provider": provider,
                            "isp": provider,
                            "org": geo.get("org") or provider,
                            "country_code": code,
                        },
                        "project_id": pid,
                    })
                return browse(items, params)

            return self._json(db_call(_ih))
        if path.startswith("/players/") and path.endswith("/name-history"):
            steam_id = path.split("/")[2]

            def _nh(conn):
                items = []
                seen = set()

                def _add(nick, created, last_seen, nid=0):
                    nick = str(nick or "").strip()
                    if not is_display_name(nick, steam_id):
                        return
                    key = nick.lower()
                    if key in seen:
                        return
                    seen.add(key)
                    items.append({
                        "id": nid or len(items) + 1,
                        "steam_id": steam_id,
                        "steam_name": nick,
                        "name": nick,
                        "created_at": int(created or now_ms()),
                        "last_seen": int(last_seen or created or now_ms()),
                    })

                cached = features.read_cache(conn, "steam_cache", "steam_id", steam_id) or {}
                if isinstance(cached, dict):
                    _add(cached.get("personaname"), cached.get("updated_at") or now_ms(), now_ms(), 0)
                    for alias in cached.get("aliases") or []:
                        if not isinstance(alias, dict):
                            continue
                        _add(alias.get("name"), alias.get("created_at") or now_ms(), now_ms(), 0)
                pretty = resolve_player_name(conn, steam_id, "")
                _add(pretty, now_ms(), now_ms(), 0)
                for row in conn.execute(
                    "SELECT * FROM player_names WHERE steam_id = ? ORDER BY id DESC LIMIT 200", (steam_id,)
                ).fetchall():
                    _add(row["steam_name"], row["created_at"], row["last_seen"], row["id"])
                items.sort(key=lambda x: int(x.get("created_at") or 0), reverse=True)
                refresh_steam_async(steam_id)
                return browse(items, params)

            return self._json(db_call(_nh))
        if path.startswith("/players/") and path.endswith("/rcc"):
            return self._json({"message": "Интеграция удалена", "bans": []}, 410)

        if path.startswith("/players/") and path.endswith("/alerts"):
            steam_id = path.split("/")[2]
            return self._json(self._browse_alerts({"steam_id": [steam_id], "player_id": [steam_id]}))
        if path.startswith("/players/") and (path.endswith("/signage") or path.endswith("/drawings") or path.endswith("/signs")):
            steam_id = path.split("/")[2]
            hide_destroyed = features._truthy_param((params.get("hide_destroyed") or ["1"])[0])
            hide_actual = features._truthy_param((params.get("hide_actual") or ["0"])[0])
            return self._json(browse(db_call(lambda c: enrich_signage_names(c, features.signage_browse(c, steam_id, hide_destroyed=hide_destroyed, hide_actual=hide_actual))), params))
        if path.startswith("/players/") and path.endswith("/ignore-reports"):
            steam_id = path.split("/")[2]
            until = db_call(lambda c: features.ignore_reports_get(c, steam_id))
            return self._json({"ignore_reports_until": until or None, "until": until or None})
        if path.startswith("/players/") and path.endswith("/settings-auto-kick"):
            steam_id = unquote(path.split("/")[2])
            pid = current_pid() or features.request_project_id() or 0
            return self._json(features.player_autokick_client(db_call(lambda c: features.player_autokick_get(c, steam_id, project_id=pid))))

        if path == "/reports/browse" or path == "/reports":
            return self._json(self._browse_reports(params))
        if path == "/ban/browse" or path == "/ban":
            return self._json(self._browse_bans(params))
        if path == "/ban/ban-export":
            return self._json([])
        if path == "/check/browse-anonymous":
            def _anon(conn):
                ids = features.subscribed_foreign_project_ids(conn)
                if not ids:
                    return {"checks": [], "results": [], "data": [], "items": [], "total": 0}
                sid = query_sid(params, "steam_id", "player_id", "target_steam_id")
                marks = ",".join("?" * len(ids))
                args = list(ids)
                sql = f"SELECT * FROM checks WHERE COALESCE(project_id, 0) IN ({marks})"
                if sid:
                    sql += " AND steam_id = ?"
                    args.append(sid)
                sql += " ORDER BY id DESC LIMIT 200"
                items = []
                for row in conn.execute(sql, args).fetchall():
                    try:
                        view = self._check_view(conn, row)
                    except Exception:
                        continue
                    view["project_id"] = int(row["project_id"] or 0) if "project_id" in row.keys() else 0
                    items.append(view)
                return {
                    "checks": items,
                    "results": items,
                    "data": items,
                    "items": items,
                    "total": len(items),
                }

            return self._json(db_call(_anon))
        if path == "/check/browse":
            return self._json(self._browse_checks(params))
        if path.startswith("/project-stats"):
            return self._json(self._project_stats_payload(path, params))
        if path == "/check/stats":
            return self._json(self._stats_payload(params, "check"))
        if path == "/ban/stats":
            return self._json(self._stats_payload(params, "ban"))
        if path.startswith("/check/") and path.endswith("/freeze-state"):
            result=db_call(lambda conn:check_freeze_state(conn,as_int(path.split("/")[2])))
            return self._json(result,200 if result.get("ok") else 403)
        if path.startswith("/check/") and path.endswith("/notice-state"):
            cid = path.split("/")[2]

            def _n(conn):
                row = None
                if str(cid).isdigit():
                    row = conn.execute("SELECT notice FROM checks WHERE id = ?", (cid,)).fetchone()
                if not row:
                    row = conn.execute("SELECT notice FROM checks ORDER BY id DESC LIMIT 1").fetchone()
                return bool(row and row["notice"])

            return self._json(db_call(_n))
        if path.startswith("/check/") and path.endswith("/activity"):
            cid = path.split("/")[2]
            cached = _activity_cache_get(cid)
            if not isinstance(cached, list):
                cached = []
            finished_at_cache = 0
            for row in cached:
                if not isinstance(row, dict):
                    continue
                kind = str(row.get("type") or row.get("kind") or "")
                if kind in ("Finished", "Canceled"):
                    try:
                        finished_at_cache = max(finished_at_cache, int(row.get("created_at") or 0))
                    except Exception:
                        pass
            if finished_at_cache:
                cached = [
                    row for row in cached
                    if not isinstance(row, dict)
                    or str(row.get("type") or row.get("kind") or "") in ("Finished", "Canceled")
                    or int(row.get("created_at") or 0) <= finished_at_cache + 1500
                ]
            serve_cache = False
            if cached:
                kinds = [
                    str((row or {}).get("type") or (row or {}).get("kind") or "")
                    for row in cached
                    if isinstance(row, dict)
                ]
                only_started = bool(kinds) and all(k in ("Started", "") for k in kinds)
                live = any(
                    k in ("PlayerKill", "MessageFromPlayer", "MessageFromModerator", "NoticeChanged", "Finished")
                    for k in kinds
                )
                # A Started-only POST cache hid /contact and later chat until TTL.
                serve_cache = (not only_started) or live
            if serve_cache:
                return self._json(cached)
            try:
                items = db_call(lambda c: self._check_activity(c, cid))
            except Exception as exc:
                print("check activity failed", cid, type(exc).__name__, exc)
                items = cached if cached else []
            if not isinstance(items, list):
                items = []
            items = _activity_cache_merge_lists(cached, items)
            if items:
                _activity_cache_put(cid, items)
            return self._json(items)
        if path.startswith("/check/") and "/activity" not in path and "/notice-state" not in path:
            cid = path.split("/")[2]

            def _slim(conn, check_id):
                if not str(check_id).isdigit():
                    return None
                row = rowd(conn.execute("SELECT * FROM checks WHERE id = ?", (check_id,)).fetchone())
                if not row:
                    return None
                sid = str(row.get("steam_id") or "")
                name = str(row.get("steam_name") or sid)
                staff_id = 0
                try:
                    staff_id = int(row.get("checker_id") or 0)
                except Exception:
                    staff_id = 0
                staff_name = str(row.get("checker_name") or "Admin")
                checker = {
                    "id": staff_id or 1,
                    "name": staff_name,
                    "avatar": PLACEHOLDER,
                    "steam": features.empty_steam_profile(PLACEHOLDER),
                    "status": "online",
                    "online": True,
                    "is_online": True,
                }
                # A check must use the same profile builder as the player
                # card.  The previous tiny stub only contained a nickname,
                # which made the right pane lose the avatar, Steam ID, server
                # and all live player fields immediately after a check began.
                # player_view performs only local/cache reads here; it does not
                # wait for GeoIP or Steam network requests when refresh is off.
                # /check/<id> may be requested without the usual project
                # route prefix.  In that case player_view cannot always
                # resolve the project's paired-server list, even though the
                # plugin has a current presence row.  Carry that local row
                # into the exact check response so the Status block remains
                # populated (movement, base, grid and server).
                live_extra = {"steam_name": name}
                try:
                    live_row = conn.execute(
                        "SELECT payload, server_id FROM online_players WHERE steam_id = ? ORDER BY rowid DESC LIMIT 1",
                        (sid,),
                    ).fetchone()
                    if live_row:
                        raw_live = json.loads(live_row["payload"] or "{}")
                        if isinstance(raw_live, dict):
                            live_extra.update(raw_live)
                            live_extra["server_id"] = int(live_row["server_id"] or raw_live.get("server_id") or 0)
                            live_extra["_check_live_presence"] = True
                except Exception:
                    pass
                player = player_view(
                    conn,
                    sid,
                    extra=live_extra,
                    nest_team=False,
                    allow_refresh=False,
                )
                player = ensure_player_shape(player, sid, name)
                raw_status = str(row.get("status") or "Pending")
                status = "Pending" if raw_status.lower() in ("active", "started", "pending", "") and not row.get("finished_at") else (
                    "FinishedBan" if "ban" in raw_status.lower() else (
                        "Canceled" if "cancel" in raw_status.lower() else (
                            "Pending" if not row.get("finished_at") else "FinishedClear"
                        )
                    )
                )
                return {
                    "id": int(row.get("id") or check_id),
                    "steam_id": sid,
                    "status": status,
                    "state": status,
                    "started_at": row.get("started_at"),
                    "created_at": row.get("started_at"),
                    "finished_at": row.get("finished_at"),
                    "player": player,
                    "suspect": player,
                    "target_player": player,
                    "checker": checker,
                    "moderator": checker,
                    "initiator_client": checker,
                    "client_id": staff_id or 1,
                    "checker_id": staff_id or 1,
                    "notice": bool(row.get("notice")),
                    "team": [],
                    "suspect_team": [],
                    "team_steam_ids": [],
                    "activity": [],
                    "reports": [],
                }

            # Do not return the short object saved by POST /check directly.
            # It is intentionally minimal so the request stays fast, but it
            # used to replace the player profile for 90 seconds after opening
            # a check.  Build a fresh, local/cache-backed exact response.
            cached = _check_exact_cache_get(cid)
            view = None
            try:
                view = db_call(lambda c: _slim(c, cid))
            except Exception as exc:
                print("check exact failed", cid, type(exc).__name__, exc)
                view = None
            if not isinstance(view, dict) or not str((view or {}).get("steam_id") or "").strip():
                if isinstance(cached, dict) and str(cached.get("steam_id") or "").strip():
                    view = cached
            if not isinstance(view, dict) or not view:
                view = {
                    "id": int(cid) if str(cid).isdigit() else 0,
                    "status": "Pending",
                    "state": "Pending",
                    "steam_id": "",
                    "player": {"steam_id": "", "steam_name": "", "name": "", "team": [], "entity": empty_entity(), "steam_data": steam_data_obj(""), "steam": True, "status": "offline"},
                    "suspect": {"steam_id": "", "steam_name": "", "name": "", "team": [], "entity": empty_entity(), "steam_data": steam_data_obj(""), "steam": True, "status": "offline"},
                    "target_player": {"steam_id": "", "steam_name": "", "name": "", "team": [], "entity": empty_entity(), "steam_data": steam_data_obj(""), "steam": True, "status": "offline"},
                    "checker": {"id": 1, "name": "Admin", "avatar": PLACEHOLDER, "steam": features.empty_steam_profile(PLACEHOLDER), "status": "online"},
                    "team": [],
                    "suspect_team": [],
                    "team_steam_ids": [],
                    "activity": [],
                    "reports": [],
                    "finished_at": None,
                    "notice": False,
                    "notice_state": False,
                }
            player = None
            if isinstance(view, dict):
                player = view.get("player") or view.get("suspect") or view.get("target_player")
            if isinstance(player, dict):
                sid = str(view.get("steam_id") or player.get("steam_id") or "")
                name = str(player.get("steam_name") or player.get("name") or sid)
                # Do not call enrich_player_live here: blocking GeoIP after POST
                # kept both check panes on the skeleton until a manual reload.
                player = ensure_player_shape(player, sid, name)
                # A state heartbeat can land immediately after the check POST.
                # If the current lookup has no live row yet, retain the full
                # start snapshot instead of replacing the Status panel with an
                # empty stub.  Old short cache entries have server_id=0 and
                # are deliberately ignored.
                cached_player = (cached or {}).get("player") if isinstance(cached, dict) else None
                if (
                    not int(player.get("server_id") or 0)
                    and isinstance(cached_player, dict)
                    and int(cached_player.get("server_id") or 0)
                ):
                    player = ensure_player_shape(cached_player, sid, name)
                av = str(player.get("steam_avatar") or "")
                local_av = UPLOADS / ("steam-%s.jpg" % sid) if sid else None
                if "/uploads/steam-" in av and not (local_av and local_av.exists() and local_av.stat().st_size > 200):
                    player["steam_avatar"] = PLACEHOLDER
                if isinstance(player.get("steam_data"), dict):
                    player["steam_data"]["unavailable"] = False
                    player["steam_data"]["profile_filled"] = True
                    if not player["steam_data"].get("avatar"):
                        player["steam_data"]["avatar"] = player.get("steam_avatar") or PLACEHOLDER
                if sid and not str(view.get("steam_id") or "").strip():
                    view["steam_id"] = sid
                view["player"] = player
                view["suspect"] = player
                view["target_player"] = player
                if not isinstance(view.get("suspect_team"), list):
                    view["suspect_team"] = []
                if not isinstance(view.get("team"), list):
                    view["team"] = []
                if not isinstance(view.get("team_steam_ids"), list):
                    view["team_steam_ids"] = list(view.get("suspect_team") or [])
            # The upstream check page expects ORM-style M_ID values on the
            # check and all nested profiles.  Without them its client-side
            # deserializer can throw and keep the whole page on a spinner.
            if view.get("id") is not None and view.get("M_ID") is None:
                view["M_ID"] = view.get("id")
            for profile_key in ("player", "suspect", "target_player"):
                profile = view.get(profile_key)
                if not isinstance(profile, dict):
                    continue
                if profile.get("id") is None and profile.get("steam_id") is not None:
                    profile["id"] = str(profile.get("steam_id") or "")
                if profile.get("M_ID") is None:
                    profile["M_ID"] = profile.get("id") or profile.get("steam_id") or ""
            for client_key in ("checker", "moderator", "initiator_client"):
                client = view.get(client_key)
                if isinstance(client, dict) and client.get("M_ID") is None:
                    client["M_ID"] = client.get("id") or view.get("client_id") or 0
            return self._json(view)

        if path == "/player-alert/browse" or path == "/player-alert" or path == "/alerts/browse" or path == "/alerts":
            return self._json(self._browse_alerts(params))
        if path == "/player-alert/categories":
            return self._json(["dug_up_stash", "join_with_ip_ban", "join_with_external_ban", "detect_ra_ban", "vpn_detected", "license_changed", "auto_kick", "contact", "custom", "custom_api"])
        if path == "/player-message":
            return self._json(self._browse_chat(params))
        if path in ("/realtime/poll", "/realtime/events", "/events/poll"):
            pid = current_pid() or 0
            since = 0
            try:
                since = int((params.get("since") or params.get("after") or ["0"])[0] or 0)
            except Exception:
                since = 0
            events = realtime_since(pid, since)
            last_id = since
            if events:
                last_id = int(events[-1].get("id") or since)
            return self._json({
                "events": events,
                "data": events,
                "results": events,
                "last_id": last_id,
                "since": since,
                "projectId": pid,
                "project_id": pid,
            })
        if path in ("/realtime/stream", "/realtime/sse", "/events/stream"):
            # Never hold a worker: nginx 502s /check/activity /tariff /wallet when SSE blocks.
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.send_header("Retry-After", "3600")
            self.end_headers()
            try:
                self.wfile.write(b"retry: 3600000\n\n")
                self.wfile.flush()
            except Exception:
                pass
            return
        if path == "/player-mute/read":
            return self._json(self._browse_mutes(params))
        if path == "/player-mute/stats":
            return self._json(self._stats_payload(params, "mute"))
        if path == "/signage/browse" or path == "/signage":
            sid = query_sid(params, "steam_id", "player_id", "owner_steam_id")
            hide_destroyed = features._truthy_param((params.get("hide_destroyed") or ["1"])[0])
            hide_actual = features._truthy_param((params.get("hide_actual") or ["0"])[0])
            only_liked = features._truthy_param((params.get("only_liked") or params.get("liked") or ["0"])[0])
            # only_liked mode shows liked including destroyed when hide_destroyed=false
            if "hide_destroyed" not in params and "hide_actual" not in params:
                # default for global signages page: hide destroyed
                hide_destroyed = True
                hide_actual = False
            return self._json(browse(db_call(lambda c: enrich_signage_names(
                c, features.signage_browse(c, sid, hide_destroyed=hide_destroyed, hide_actual=hide_actual, only_liked=only_liked)
            )), params))
        if path == "/sleeping-bag/browse":
            return self._json(self._browse_bags(params))
        if path == "/audit/browse" or path == "/audit":
            return self._json(self._browse_audit(params))
        if path == "/suggestion/browse":
            return self._json(browse([], params))
        if path.startswith("/public/"):
            return self._json([])
        if path == "/webhook":
            return self._json(db_call(features.webhook_list))
        if path.startswith("/court-autokick") or path.startswith("/auto-kick") or path in ("/court-autokick", "/auto-kick"):
            try:
                return self._json(db_call(features.autokick_list))
            except Exception as exc:
                print("autokick list failed", type(exc).__name__, exc)
                return self._json(autokick_rules())
        if path.startswith("/ban-sync"):
            if path.endswith("/settings") or path == "/ban-sync/settings":
                return self._json(db_call(features.ban_sync_settings))
            if "available" in path or "browse" in path or path.endswith("/public"):
                items = db_call(features.ban_sync_available)
                if not isinstance(items, list):
                    items = []
                # Raw array: axios response.data is the list, SPA does [...c.data].
                return self._json(items)
            if "followers" in path:
                return self._json([])
            if "subscription" in path:
                items = db_call(features.ban_sync_subscriptions)
                if not isinstance(items, list):
                    items = []
                # Pinia: s.value = e.data — body must be a raw array (.filter)
                return self._json(items)
            # GET /ban-sync and /ban-sync/settings: Ban-list tab reads settings flags.
            return self._json(db_call(features.ban_sync_settings))
        if path.startswith("/players/") and path.count("/") == 2:
            steam_id = path.split("/")[2]
            if is_real_steam_id(steam_id):
                return self._json(db_call(lambda c: player_view(c, steam_id, nest_team=False)))
            return self._json(db_call(lambda c: kill_feed_player(c, steam_id)))
        if path.startswith("/map"):
            sid = as_int(path.rstrip("/").split("/")[-1])
            def _live_map(conn):
                pid = current_pid()
                if pid:
                    reconcile_duplicate_servers(conn, pid)
                return map_payload(conn, sid)
            return self._json(db_call(_live_map))

        if "stats" in path and "/players/" not in path and "/utils/" not in path:
            kind = "mute" if "mute" in path else ("ban" if "ban" in path else "check")
            return self._json(self._stats_payload(params, kind))
        return self._json({"results": [], "data": [], "total": 0} if path.endswith("s") else {})

    def api_post(self, path, params, body):
        if path.startswith("/project/") and path.endswith("/clients"):
            return self.api_put(path, params, body)
        if path in ("/billing/platega/callback", "/platega/callback"):
            def _cb(conn):
                return platega_pay.handle_callback(conn, self, body if isinstance(body, dict) else {})

            data, code = db_call(_cb)
            return self._json(data, code)
        if path.startswith("/admin/api"):
            if admin_panel.handle_api(self, "POST", path, params, body):
                return
        self.bind_project()
        if path == "/billing/platega/create":
            def _create(conn):
                return platega_pay.create_payment(conn, self, body if isinstance(body, dict) else {})

            data, code = db_call(_create)
            return self._json(data, code)
        if path == "/billing/platega/setup":
            def _setup(conn):
                return platega_pay.save_merchant(conn, self, body if isinstance(body, dict) else {})

            data, code = db_call(_setup)
            return self._json(data, code)
        if path in ("/check/stats", "/ban/stats", "/player-mute/stats"):
            kind = "mute" if "mute" in path else ("ban" if "ban" in path else "check")
            merged = dict(params or {})
            extra = body if isinstance(body, dict) else {}
            staff_id = parse_stats_staff_id(merged, extra)
            if staff_id:
                merged["client_id"] = [str(staff_id)]
            for key, val in extra.items():
                if key in merged and merged.get(key) not in (None, "", [], [""]):
                    continue
                merged[key] = val if isinstance(val, list) else [val]
            return self._json(self._stats_payload(merged, kind))
        if path == "/plugin/state":
            return self.api_put(path, params, body)
        if "signage" in path and path != "/plugin/signage" and (
            "/like" in path or "/unlike" in path or "/dislike" in path
            or (isinstance(body, dict) and any(k in body for k in ("liked", "is_liked", "likedByCurrentUser", "liked_by_current_user")))
        ):
            return self._json(signage_like_from_request(path, params, body))
        if path == "/__checkapp-analytics" or path.startswith("/2/"):
            return self._json({"code": 200})

        if path == "/auth/classic/sign-in":
            email = str(body.get("email") or body.get("login") or "").lower().strip()
            password = str(body.get("password") or "")

            def _login(conn):
                row = conn.execute("SELECT * FROM users WHERE lower(email) = ?", (email,)).fetchone()
                if not row or not features.verify_password(password, row["password_hash"]):
                    return None
                features.audit(conn, "auth.sign_in", {"email": email})
                return dict(row)

            user = db_call(_login)
            if not user:
                return self._json({"message": "password.missmatch"}, 400)
            try:
                ip = admin_panel.client_ip(self)
                if ip:
                    db_call(lambda c: features.record_user_ip(c, int(user.get("id") or 0), ip, revive=True))
            except Exception:
                pass
            blocked = db_call(lambda c: oauth_auth.auth_login_denied(c, user, admin_panel.client_ip(self)))
            if blocked:
                return self._json(blocked, 403)
            token = features.make_access_token(user)
            REQ.user_id = int(user.get("id") or 0)
            features.set_request_user(REQ.user_id)
            # SPA auth.confirm(updateToken) expects the raw JWT string as response body.
            return self._json(token)

        if path == "/auth/classic/sign-up":
            email = str(body.get("email") or "").lower().strip()
            password = str(body.get("password") or "")
            name = str(body.get("name") or email.split("@")[0])
            if not email or not password:
                return self._json({"message": "invalid"}, 400)
            reg_ip = admin_panel.client_ip(self)
            if reg_ip and db_call(lambda c: features.is_user_ip_blocked(c, reg_ip)):
                return self._json({"message": "account.blocked", "code": "account.blocked", "title": "Аккаунт заблокирован"}, 403)

            def _reg(conn):
                if conn.execute("SELECT id FROM users WHERE lower(email) = ?", (email,)).fetchone():
                    return {"error": "exists"}
                blocked = 1 if features.is_user_ip_blocked(conn, reg_ip) else 0
                conn.execute(
                    "INSERT INTO users (email, name, tag, bio, password_hash, role, is_admin, created_at, account_blocked, account_blocked_at, account_blocked_reason) VALUES (?, ?, ?, '', ?, 'owner', 1, ?, ?, ?, ?)",
                    (email, name, (name or "user")[:24], features.hash_password(password), now_ms(), blocked, now_ms() if blocked else 0, "blocked_user_ip" if blocked else ""),
                )
                row = conn.execute("SELECT * FROM users WHERE lower(email) = ?", (email,)).fetchone()
                features.audit(conn, "auth.sign_up", {"email": email})
                return dict(row) if row else {"error": "failed"}

            result = db_call(_reg)
            if result.get("error") == "exists":
                return self._json({"message": "email.exists"}, 400)
            if result.get("error") or not result.get("id"):
                return self._json({"message": "invalid"}, 400)
            if int(result.get("account_blocked") or 0):
                return self._json({"message": "account.blocked", "code": "account.blocked", "title": "Аккаунт заблокирован"}, 403)
            try:
                ip = reg_ip
                if ip:
                    db_call(lambda c: features.record_user_ip(c, int(result.get("id") or 0), ip))
            except Exception:
                pass
            token = features.make_access_token(result)
            REQ.user_id = int(result.get("id") or 0)
            features.set_request_user(REQ.user_id)
            try:
                features.notify_new_user(name, email, int(result.get("id") or 0), reg_ip, "email")
            except Exception:
                pass
            return self._json(token)

        if path in ("/auth/google/validate", "/auth/steam/validate"):
            query = str((params.get("query") or [""])[0] or body.get("query") or "")
            if path == "/auth/steam/validate":
                profile = oauth_auth.verify_steam_openid(query)
                if not profile:
                    return self._json({"message": "steam.invalid", "exists": False}, 400)
                sid = str(profile.get("steam_id") or "")

                def _exists(conn):
                    row = oauth_auth.find_user_by_steam(conn, sid)
                    return {
                        "exists": bool(row),
                        "steam_id": sid,
                        "steam_name": profile.get("steam_name") or sid,
                        "steam_avatar": profile.get("steam_avatar") or PLACEHOLDER,
                    }

                return self._json(db_call(_exists))
            query = str((params.get("query") or [""])[0] or body.get("query") or "")
            credential = str(body.get("credential") or body.get("id_token") or (params.get("credential") or [""])[0] or "")
            profile = oauth_auth.verify_google_query(query or credential)
            if not profile and credential:
                profile = oauth_auth.google_verify_id_token(credential)
            if not profile:
                return self._json({"message": "google.invalid", "exists": False}, 400)
            gid = str(profile.get("google_id") or "")

            def _gexists(conn):
                row = oauth_auth.find_user_by_google(conn, gid)
                if not row and profile.get("email"):
                    row = oauth_auth.find_user_by_google_email(conn, profile.get("email"))
                return {
                    "exists": bool(row),
                    "google_id": gid,
                    "google_name": profile.get("google_name") or profile.get("name") or gid,
                    "google_avatar": profile.get("google_avatar") or profile.get("avatar") or PLACEHOLDER,
                    "email": profile.get("email") or "",
                }

            return self._json(db_call(_gexists))

        if path == "/auth/steam/sign-in":
            query = str(body.get("query") or (params.get("query") or [""])[0] or "")
            profile = oauth_auth.verify_steam_openid(query)
            if not profile:
                return self._json({"message": "steam.invalid"}, 400)
            sid = str(profile.get("steam_id") or "")

            def _login(conn):
                user = oauth_auth.find_user_by_steam(conn, sid)
                if user:
                    features.audit(conn, "auth.sign_in", {"steam_id": sid, "provider": "steam"})
                return user

            return self._auth_login_response(db_call(_login))

        if path == "/auth/steam/sign-up":
            query = str(body.get("query") or body.get("steam_query") or "")
            profile = oauth_auth.verify_steam_openid(query)
            if not profile:
                return self._json({"message": "steam.invalid"}, 400)
            sid = str(profile.get("steam_id") or body.get("steam_id") or profile.get("steam_id") or "")
            name = str(body.get("name") or profile.get("steam_name") or sid)
            tag = str(body.get("tag") or name)
            avatar = str(body.get("avatar") or profile.get("steam_avatar") or PLACEHOLDER)
            email = f"{sid}@steam.rustcheck.local"

            def _reg(conn):
                existing = oauth_auth.find_user_by_steam(conn, sid)
                if existing:
                    features.audit(conn, "auth.sign_in", {"steam_id": sid, "provider": "steam"})
                    row = dict(existing)
                    row["_existing"] = True
                    return row
                created = oauth_auth.create_oauth_user(
                    conn,
                    email=email,
                    name=name,
                    tag=tag,
                    steam_id=sid,
                    avatar=avatar,
                )
                if created:
                    created = dict(created)
                    created["_new"] = True
                return created

            user = db_call(_reg)
            if isinstance(user, dict) and user.get("error") == "exists":
                return self._json({"message": "email.exists"}, 400)
            if not user or not user.get("id"):
                return self._json({"message": "invalid"}, 400)
            if user.get("_new"):
                try:
                    features.notify_new_user(name, email, int(user.get("id") or 0), admin_panel.client_ip(self), "steam")
                except Exception:
                    pass
            return self._auth_login_response(user)

        if path == "/auth/discord/sign-in":
            query = str(body.get("query") or (params.get("query") or [""])[0] or "")
            profile = oauth_auth.verify_discord_query(query)
            if not profile:
                return self._json({"message": "discord.invalid"}, 400)
            did = str(profile.get("discord_id") or "")

            def _login(conn):
                user = oauth_auth.find_user_by_discord(conn, did)
                if user:
                    features.audit(conn, "auth.sign_in", {"discord_id": did, "provider": "discord"})
                return user

            return self._auth_login_response(db_call(_login))

        if path == "/auth/discord/sign-up":
            query = str(body.get("query") or body.get("discord_query") or "")
            profile = oauth_auth.verify_discord_query(query)
            if not profile:
                return self._json({"message": "discord.invalid"}, 400)
            did = str(profile.get("discord_id") or body.get("discord_id") or "")
            name = str(body.get("name") or profile.get("discord_name") or did)
            tag = str(body.get("tag") or name)
            avatar = str(body.get("avatar") or profile.get("discord_avatar") or PLACEHOLDER)
            email = f"{did}@discord.rustcheck.local"

            def _reg(conn):
                existing = oauth_auth.find_user_by_discord(conn, did)
                if existing:
                    features.audit(conn, "auth.sign_in", {"discord_id": did, "provider": "discord"})
                    row = dict(existing)
                    row["_existing"] = True
                    return row
                created = oauth_auth.create_oauth_user(
                    conn,
                    email=email,
                    name=name,
                    tag=tag,
                    discord_id=did,
                    avatar=avatar,
                )
                if created:
                    created = dict(created)
                    created["_new"] = True
                return created

            user = db_call(_reg)
            if isinstance(user, dict) and user.get("error") == "exists":
                return self._json({"message": "email.exists"}, 400)
            if not user or not user.get("id"):
                return self._json({"message": "invalid"}, 400)
            if user.get("_new"):
                try:
                    features.notify_new_user(name, email, int(user.get("id") or 0), admin_panel.client_ip(self), "discord")
                except Exception:
                    pass
            return self._auth_login_response(user)

        if path == "/auth/steam-connect":
            self.bind_auth_user()
            uid = int(getattr(REQ, "user_id", 0) or features.request_user_id() or 0)
            if not uid:
                return self._json({"message": "unauthorized", "unauthorized": True}, 401)
            query = str((params.get("query") or [""])[0] or body.get("query") or "")

            def _connect(conn):
                user = features.user_by_id(conn, uid)
                if not user:
                    return {"message": "unauthorized"}
                profile = oauth_auth.verify_steam_openid(query)
                if not profile:
                    return {"message": "steam.invalid"}
                sid = str(profile.get("steam_id") or "")
                other = oauth_auth.find_user_by_steam(conn, sid)
                if other and int(other.get("id") or 0) != uid:
                    return {"message": "steam.busy"}
                updated = oauth_auth.link_steam_to_user(
                    conn,
                    user,
                    sid,
                    str(profile.get("steam_name") or sid),
                    str(profile.get("steam_avatar") or PLACEHOLDER),
                )
                if not updated:
                    return {"message": "steam.invalid"}
                features.audit(conn, "auth.steam_connect", {"steam_id": sid, "user_id": uid})
                return oauth_auth.steam_client_payload(
                    sid,
                    str(profile.get("steam_name") or sid),
                    str(profile.get("steam_avatar") or PLACEHOLDER),
                )

            result = db_call(_connect)
            if result.get("message"):
                code = 400 if result.get("message") != "unauthorized" else 401
                return self._json(result, code)
            return self._json(result)

        if path == "/auth/discord-connect":
            self.bind_auth_user()
            uid = int(getattr(REQ, "user_id", 0) or features.request_user_id() or 0)
            if not uid and isinstance(body, dict):
                extra = str(body.get("token") or body.get("access_token") or "")
                if extra:
                    def _tok(conn):
                        payload = features.parse_access_token(extra)
                        user = features.user_from_token_payload(conn, payload)
                        uid2 = int((user or {}).get("id") or 0)
                        REQ.user_id = uid2
                        features.set_request_user(uid2)
                        REQ.user = user
                        return uid2
                    try:
                        uid = int(db_call(_tok) or 0)
                    except Exception:
                        uid = 0
            if not uid:
                return self._json({"message": "unauthorized", "unauthorized": True}, 401)
            if not oauth_auth.discord_configured():
                print("discord connect finish unavailable: missing DISCORD_CLIENT_SECRET")
                return self._json({"message": "discord.not.configured", "url": ""}, 400)
            query = str((params.get("query") or [""])[0] or (body.get("query") if isinstance(body, dict) else "") or "")

            def _connect(conn):
                user = features.user_by_id(conn, uid)
                if not user:
                    return {"message": "unauthorized"}
                profile = oauth_auth.verify_discord_query(query)
                if not profile:
                    print("discord connect invalid query signature")
                    return {"message": "discord.invalid"}
                did = str(profile.get("discord_id") or "")
                other = oauth_auth.find_user_by_discord(conn, did)
                if other and int(other.get("id") or 0) != uid:
                    return {"message": "discord.busy"}
                updated = oauth_auth.link_discord_to_user(
                    conn,
                    user,
                    did,
                    str(profile.get("discord_name") or did),
                    str(profile.get("discord_avatar") or ""),
                    str(profile.get("discord_username") or ""),
                )
                if not updated:
                    return {"message": "discord.invalid"}
                features.audit(conn, "auth.discord_connect", {"discord_id": did, "user_id": uid})
                return client_obj(conn, updated)

            result = db_call(_connect)
            if result.get("message"):
                code = 400 if result.get("message") != "unauthorized" else 401
                return self._json(result, code)
            return self._json(result)

        if path == "/auth/telegram-connect":
            return self._json({
                "url": "",
                "available": False,
                "disabled": True,
                "connected": False,
                "message": "telegram.unavailable",
            })

        if path in ("/auth/google/sign-in", "/auth/google/sign-up"):
            query = str(body.get("query") or (params.get("query") or [""])[0] or "")
            credential = str(body.get("credential") or body.get("id_token") or "")
            profile = oauth_auth.verify_google_query(query or credential)
            if not profile and credential:
                profile = oauth_auth.google_verify_id_token(credential)
            if not profile:
                return self._json({"message": "google.invalid"}, 400)
            gid = str(profile.get("google_id") or body.get("google_id") or "")
            email = str(body.get("email") or profile.get("email") or f"{gid}@google.rustcheck.local").lower().strip()
            name = str(body.get("name") or profile.get("google_name") or profile.get("name") or email.split("@")[0])
            tag = str(body.get("tag") or name)
            avatar = str(body.get("avatar") or profile.get("google_avatar") or profile.get("avatar") or PLACEHOLDER)

            def _glogin(conn):
                user = oauth_auth.find_user_by_google(conn, gid)
                if not user and email and "@" in email and not email.endswith("@google.rustcheck.local"):
                    user = oauth_auth.find_user_by_google_email(conn, email)
                    if user and not str(user.get("google_id") or "").strip():
                        oauth_auth.link_google_to_user(conn, user, gid, name, avatar, email)
                        user = features.user_by_id(conn, int(user.get("id") or 0)) or user
                if user:
                    features.audit(conn, "auth.sign_in", {"google_id": gid, "provider": "google"})
                return user

            if path.endswith("sign-in"):
                return self._auth_login_response(db_call(_glogin))

            def _greg(conn):
                existing = oauth_auth.find_user_by_google(conn, gid)
                if existing:
                    features.audit(conn, "auth.sign_in", {"google_id": gid, "provider": "google"})
                    row = dict(existing)
                    row["_existing"] = True
                    return row
                if email and not email.endswith("@google.rustcheck.local"):
                    by_email = oauth_auth.find_user_by_google_email(conn, email)
                    if by_email:
                        linked = oauth_auth.link_google_to_user(conn, by_email, gid, name, avatar, email)
                        features.audit(conn, "auth.sign_in", {"google_id": gid, "provider": "google"})
                        row = dict(linked or by_email)
                        row["_existing"] = True
                        return row
                created = oauth_auth.create_oauth_user(
                    conn,
                    email=email,
                    name=name,
                    tag=tag,
                    google_id=gid,
                    avatar=avatar,
                )
                if created:
                    created = dict(created)
                    created["_new"] = True
                return created

            user = db_call(_greg)
            if not user or not user.get("id"):
                return self._json({"message": "invalid"}, 400)
            if user.get("_new"):
                try:
                    features.notify_new_user(name, email, int(user.get("id") or 0), admin_panel.client_ip(self), "google")
                except Exception:
                    pass
            return self._auth_login_response(user)

        if path == "/auth/google-connect":
            self.bind_auth_user()
            uid = int(getattr(REQ, "user_id", 0) or features.request_user_id() or 0)
            if not uid:
                return self._json({"message": "unauthorized", "unauthorized": True}, 401)
            if not oauth_auth.google_configured():
                return self._json({"message": "google.not.configured"}, 503)
            query = str((params.get("query") or [""])[0] or body.get("query") or "")
            credential = str(body.get("credential") or body.get("id_token") or "")

            def _gconnect(conn):
                user = features.user_by_id(conn, uid)
                if not user:
                    return {"message": "unauthorized"}
                profile = oauth_auth.verify_google_query(query or credential)
                if not profile and credential:
                    profile = oauth_auth.google_verify_id_token(credential)
                if not profile:
                    return {"message": "google.invalid"}
                gid = str(profile.get("google_id") or "")
                other = oauth_auth.find_user_by_google(conn, gid)
                if other and int(other.get("id") or 0) != uid:
                    return {"message": "google.busy"}
                updated = oauth_auth.link_google_to_user(
                    conn,
                    user,
                    gid,
                    str(profile.get("google_name") or profile.get("name") or gid),
                    str(profile.get("google_avatar") or profile.get("avatar") or PLACEHOLDER),
                    str(profile.get("email") or ""),
                )
                if not updated:
                    return {"message": "google.invalid"}
                features.audit(conn, "auth.google_connect", {"google_id": gid, "user_id": uid})
                return oauth_auth.google_profile_for_user(conn, updated) or {"google_id": gid}

            result = db_call(_gconnect)
            if result.get("message"):
                code = 400 if result.get("message") != "unauthorized" else 401
                if result.get("message") == "google.not.configured":
                    code = 503
                return self._json(result, code)
            return self._json(result)

        if path in ("/client", "/client/profile"):
            return self.api_put(path, params, body)
        if path in ("/client/twofactor", "/client/2fa", "/auth/twofactor", "/client/twofactor/enable"):
            def _tf(conn):
                uid = int((features.owner_user(conn) or {}).get("id") or 1)
                code = str((params.get("code") or [""])[0] or (body or {}).get("code") or "").strip()
                secret = totp_secret_for_user(conn, uid)
                if code and not totp_verify(secret, code):
                    return {"message": "invalid code", "ok": False}
                active = True
                if isinstance(body, dict) and "active" in body:
                    active = bool(body.get("active"))
                if code and not active:
                    active = True
                try:
                    conn.execute("UPDATE users SET twofactor_active = ? WHERE id = ?", (1 if active else 0, uid))
                except Exception:
                    pass
                payload = twofa_payload(conn)
                payload["ok"] = True
                return payload

            return self._json(db_call(_tf))

        if path == "/auth/2fa":
            code = str((params.get("code") or [""])[0] or (body or {}).get("code") or "").strip()

            def _auth2fa(conn):
                user = features.owner_user(conn)
                uid = int((user or {}).get("id") or 1)
                secret = totp_secret_for_user(conn, uid)
                if not code or not totp_verify(secret, code):
                    return {"message": "invalid code", "ok": False}
                conn.execute("UPDATE users SET twofactor_active = 1 WHERE id = ?", (uid,))
                payload = twofa_payload(conn, user)
                payload["ok"] = True
                return payload

            return self._json(db_call(_auth2fa))

        if path == "/project":
            uid = int(getattr(REQ, "user_id", 0) or features.request_user_id() or 0)
            if not uid:
                return self._json({"message": "unauthorized", "unauthorized": True}, 401)
            features.set_request_user(uid)
            if not db_call(features.can_create_project):
                return self._json({
                    "can": False,
                    "allowed": False,
                    "message": "Project limit exceeded",
                    "error": "project-limit-exceeded",
                    "title": "Ошибка",
                    "detail": "Вы больше не можете создавать проекты, достигнул лимит!",
                }, 403)
            name = str(body.get("name") or "RustApp").strip() or "RustApp"
            avatar = str(body.get("avatar") or "")
            contact = str(body.get("contact_url") or "")

            def _create(conn):
                domain = unique_domain(conn, body.get("domain") or name)
                trial = now_ms() + features.TRIAL_MS
                plan = "base"
                owner_id = int(features.request_user_id() or getattr(REQ, "user_id", 0) or 0)
                if not owner_id:
                    return None
                blocked = 1 if features.user_projects_blocked(conn, owner_id) else 0
                admin_frozen = 1 if blocked else 0
                conn.execute(
                    "INSERT INTO project (name, domain, avatar, contact_url, plan, trial_ends_at, paid_until, owner_user_id, created_at, blocked, admin_frozen) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (name, domain, avatar, contact, plan, trial, 0, owner_id, now_ms(), blocked, admin_frozen),
                )
                created = rowd(conn.execute("SELECT * FROM project WHERE id = last_insert_rowid()").fetchone())
                if created:
                    try:
                        features.init_empty_project(conn, int(created["id"]))
                    except Exception:
                        pass
                if created and blocked:
                    features.freeze_project(conn, int(created["id"]), "owner_projects_blocked")
                elif created and not blocked:
                    # Ensure new ordinary projects start ACTIVE (never inherit stale flags).
                    conn.execute(
                        "UPDATE project SET blocked = 0, admin_frozen = 0 WHERE id = ?",
                        (int(created["id"]),),
                    )
                    created = rowd(conn.execute("SELECT * FROM project WHERE id = ?", (int(created["id"]),)).fetchone())
                return created

            created = db_call(_create)
            if not created:
                return self._json({"message": "create failed", "can": False}, 400)
            try:
                owner_name = ""
                try:
                    urow = db_call(lambda c: features.user_by_id(c, uid))
                    owner_name = str((urow or {}).get("name") or (urow or {}).get("email") or uid)
                except Exception:
                    owner_name = str(uid)
                features.notify_new_project(
                    str(created.get("name") or name),
                    int(created.get("id") or 0),
                    owner_name,
                    str(created.get("domain") or ""),
                )
            except Exception:
                pass
            return self._json(project_obj(created))

        if path.startswith("/project/") and path.endswith("/delete"):
            key = path.split("/")[2]
            return self.api_delete(f"/project/{key}", params, body)

        if path == "/plugin/pair":
            code = str((params.get("code") or [""])[0] or (body or {}).get("code") or "").strip()
            print("PLUGIN pair incoming", repr(code), self.path)
            if not code:
                return self._json({"message": "code not exists"}, 400)
            remote_ip = admin_panel.plugin_remote_ip(self)

            def _pair(conn):
                padded = code.zfill(6) if code.isdigit() and len(code) <= 6 else code
                row = conn.execute(
                    "SELECT * FROM pair_codes WHERE code = ? OR code = ?",
                    (code, padded),
                ).fetchone()
                if not row:
                    make_pair_code(conn, padded)
                    row = conn.execute("SELECT * FROM pair_codes WHERE code = ?", (padded,)).fetchone()
                if not row:
                    return None
                try:
                    pid = int(row["project_id"] or 0)
                except Exception:
                    pid = 0
                if not pid:
                    return None
                pair_body = dict(body) if isinstance(body, dict) else {}
                token = upsert_paired_server(conn, pid, pair_body, code, remote_ip=remote_ip)
                if token == "__blocked_ip__":
                    return {"error": "server-ip-blocked", "message": "server-ip-blocked"}
                if not token:
                    return {"message": "server-limit-exceeded", "error": "server-limit-exceeded"}
                conn.execute("UPDATE pair_codes SET used = 1 WHERE code = ?", (code,))
                print("PLUGIN paired project", pid, "server token issued", "ip", remote_ip)
                conn.execute(
                    "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (f"pair_token_{code}", token),
                )
                stored = conn.execute("SELECT value FROM settings WHERE key = ?", (f"pair_token_{code}",)).fetchone()
                issued = str((stored["value"] if stored else token) or "")
                print("[RustApp] Pair token ready for code", code, "len", len(issued))
                return {"token": issued, "ttl": 0}

            result = db_call(_pair)
            if result is None:
                return self._json({"message": "code not exists"}, 400)
            if isinstance(result, dict) and result.get("error") == "server-limit-exceeded":
                return self._json(result, 403)
            if isinstance(result, dict) and result.get("error") == "server-ip-blocked":
                return self._json(result, 403)
            return self._json(result)

        if path in ("/plugin/map", "/plugin/map/"):
            if not require_plugin(self.headers):
                return self._json({"message": "authorization secret is corrupted"}, 401)

            def _map(conn):
                server = plugin_server_row(conn, self.headers)
                if not server:
                    return {"ok": False}
                sid = int(server["id"])
                raw = ""
                image_url = ""
                if isinstance(body, dict):
                    raw = str(body.get("image_base64") or body.get("image") or "")
                    image_url = str(body.get("image_url") or body.get("level_image_url") or body.get("url") or "").strip()
                if raw.startswith("data:") and "," in raw:
                    raw = raw.split(",", 1)[1]
                data = b""
                if raw:
                    try:
                        data = base64.b64decode(raw)
                    except Exception:
                        data = b""
                if len(data) <= 100 and image_url:
                    data = fetch_remote_map_bytes(image_url)
                world = as_int((body or {}).get("world_size") if isinstance(body, dict) else 0)
                if not world and isinstance(body, dict):
                    world = as_int(body.get("size"))
                seed = as_int((body or {}).get("seed") if isinstance(body, dict) else 0)
                level = str((body or {}).get("level") or "") if isinstance(body, dict) else ""
                if len(data) > 100:
                    (UPLOADS / f"map-{sid}.png").write_bytes(data)
                    conn.execute(
                        "UPDATE servers SET map_image=? WHERE id=?",
                        (f"/uploads/map-{sid}.png", sid),
                    )
                elif image_url.startswith("http"):
                    conn.execute(
                        """UPDATE servers SET map_image=COALESCE(NULLIF(map_image,''), ?) WHERE id=?""",
                        (image_url, sid),
                    )
                if world:
                    conn.execute(
                        "UPDATE servers SET world_size=?, seed=? WHERE id=?",
                        (world, seed, sid),
                    )
                if level:
                    conn.execute(
                        "UPDATE servers SET level=COALESCE(NULLIF(?,''), level) WHERE id=?",
                        (level, sid),
                    )
                print("PLUGIN map saved", sid, "bytes", len(data), "world", world, "seed", seed)
                return {"ok": True}

            return self._json(db_call(_map))

        if path in ("/plugin/chat",):
            if not require_plugin(self.headers):
                return self._json({"message": "authorization secret is corrupted"}, 401)

            def _chat(conn):
                server = plugin_server_row(conn, self.headers)
                if not server:
                    print("PLUGIN chat skipped: unknown server token")
                    return {"ok": False, "reason": "unknown server"}
                pid = int(server.get("project_id") or 0)
                srv_id = int(server.get("id") or 0)
                if not pid or not srv_id:
                    print("PLUGIN chat skipped: unpaired server", srv_id, "project", pid)
                    return {"ok": False, "reason": "unpaired"}
                try:
                    features.set_request_project(pid)
                    REQ.project_id = pid
                except Exception:
                    pass
                raw_msgs = body.get("messages") if isinstance(body, dict) else body
                if isinstance(body, dict) and not raw_msgs:
                    if body.get("steam_id") or body.get("text") or body.get("message"):
                        raw_msgs = [body]
                if not isinstance(raw_msgs, list):
                    raw_msgs = []
                print("PLUGIN chat incoming", len(raw_msgs), "server", srv_id, "project", pid)
                stored = 0
                for msg in raw_msgs:
                    if not isinstance(msg, dict):
                        continue
                    sid = str(msg.get("steam_id") or msg.get("SteamId") or "")
                    if not is_real_steam_id(sid):
                        print("PLUGIN chat skip bad steam", sid)
                        continue
                    text = str(msg.get("text") or msg.get("message") or "").strip()
                    if not text or re.search(r"you are muted|вы в муте|замучен", text, re.I):
                        continue
                    muted = False
                    try:
                        mute_row = conn.execute(
                            """SELECT id FROM mutes WHERE steam_id = ? AND active = 1
                               AND (expired_at = 0 OR expired_at > ?) LIMIT 1""",
                            (sid, now_ms()),
                        ).fetchone()
                        muted = bool(mute_row)
                    except Exception:
                        pass
                    incoming_name = str(msg.get("steam_name") or msg.get("name") or "")
                    if is_display_name(incoming_name, sid):
                        upsert_player(conn, sid, incoming_name)
                    else:
                        upsert_player(conn, sid, "")
                    name = incoming_name
                    if not is_display_name(name, sid):
                        prow = conn.execute("SELECT steam_name FROM players WHERE steam_id = ?", (sid,)).fetchone()
                        if prow and is_display_name(prow["steam_name"], sid):
                            name = prow["steam_name"]
                        else:
                            name = incoming_name or sid
                    store_text = text
                    if muted:
                        store_text = f"[мут] {text}"
                        print("PLUGIN chat muted-attempt", sid, text[:80])
                    print("[CHECK CHAT] Message received projectId", pid, "serverId", srv_id, "steam", sid)
                    team_flag = msg.get("is_team")
                    if team_flag is None:
                        team_flag = msg.get("IsTeam")
                    if team_flag is None:
                        team_flag = msg.get("isTeam")
                    channel = str(msg.get("channel") or msg.get("Channel") or "").strip().lower()
                    insert_chat(
                        conn,
                        sid,
                        name or sid,
                        msg.get("target_steam_id"),
                        bool(team_flag) or channel in ("team", "3"),
                        store_text,
                        False,
                        project_id=pid,
                        actor_user_id=0,
                        actor_name=name or sid,
                        author_type="player",
                        server_id=srv_id,
                    )
                    stored += 1
                    print("[CHECK CHAT] Message saved", sid, (name or sid), store_text[:80])
                print("[RustApp] Chat stored", stored, "/", len(raw_msgs), "server", srv_id)
                return {"ok": True, "stored": stored}

            result = db_call(_chat)
            return self._json(result or {"ok": True})

        if path in ("/plugin/reports", "/plugin/report"):
            raw_reports = []
            if isinstance(body, list):
                raw_reports = body
            elif isinstance(body, dict):
                raw_reports = (
                    body.get("reports")
                    or body.get("Reports")
                    or body.get("data")
                    or body.get("Data")
                    or body.get("items")
                    or []
                )
                if not raw_reports and (body.get("target_steam_id") or body.get("target") or body.get("initiator_steam_id")):
                    raw_reports = [body]
            print("PLUGIN reports incoming", len(raw_reports), body if not isinstance(body, list) else "list")
            if not require_plugin(self.headers):
                return self._json({"message": "authorization secret is corrupted"}, 401)

            def _pick(item, *keys):
                for key in keys:
                    val = item.get(key)
                    if isinstance(val, dict):
                        val = val.get("steam_id") or val.get("id") or ""
                    if val not in (None, ""):
                        return str(val)
                return ""

            def _rep(conn):
                server = plugin_server_row(conn, self.headers)
                pid = int((server or {}).get("project_id") or current_pid() or 0)
                if not pid:
                    return None
                saved = 0
                ignored = 0
                now_ts = now_ms()
                for item in raw_reports:
                    if not isinstance(item, dict):
                        continue
                    a = _pick(item, "initiator_steam_id", "initiator", "reporter", "from")
                    b = _pick(item, "target_steam_id", "target", "suspect_steam_id", "player_id")
                    if not b:
                        subs = item.get("sub_targets_steam_ids") or item.get("targets") or []
                        if isinstance(subs, list) and subs:
                            first = subs[0]
                            if isinstance(first, dict):
                                b = str(first.get("steam_id") or first.get("id") or "")
                            else:
                                b = str(first or "")
                    if not b:
                        continue
                    # Player was verified by a check — reject reports for N days
                    try:
                        ignore_until = int(features.ignore_reports_get(conn, b) or 0)
                    except Exception:
                        ignore_until = 0
                    if ignore_until > now_ts:
                        ignored += 1
                        print("PLUGIN report ignored (player checked)", a, "->", b, "until", ignore_until)
                        continue
                    reason = _pick(item, "reason", "type", "subject") or "report"
                    message = _pick(item, "message", "comment", "text")
                    upsert_player(conn, a)
                    upsert_player(conn, b)
                    try:
                        conn.execute(
                            """INSERT INTO reports (initiator_steam_id, target_steam_id, reason, message, created_at, project_id, server_id)
                               VALUES (?, ?, ?, ?, ?, ?, ?)""",
                            (a, b, reason, message, now_ms(), pid, int((server or {}).get("id") or 0)),
                        )
                    except Exception:
                        conn.execute(
                            """INSERT INTO reports (initiator_steam_id, target_steam_id, reason, message, created_at, project_id)
                               VALUES (?, ?, ?, ?, ?, ?)""",
                            (a, b, reason, message, now_ms(), pid),
                        )
                    rid = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0] or 0)
                    saved += 1
                    features.lifetime_bump(conn, "reports", 1)
                    print("PLUGIN report saved", a, "->", b, reason, "project", pid, "id", rid)
                    features.audit(conn, "report.created", {"from": a, "to": b, "reason": reason, "steam_id": b, "project_id": pid})
                    reporter = {"steam_id": a, "name": a, "avatar": ""}
                    suspect = {"steam_id": b, "name": b, "avatar": ""}
                    try:
                        rp = player_view(conn, a, nest_team=False)
                        sp = player_view(conn, b, nest_team=False)
                        reporter = {"steam_id": a, "name": rp.get("steam_name") or a, "avatar": rp.get("steam_avatar") or ""}
                        suspect = {"steam_id": b, "name": sp.get("steam_name") or b, "avatar": sp.get("steam_avatar") or ""}
                    except Exception:
                        pass
                    insert_alert(conn, "report", b, {
                        "reportId": rid,
                        "playerId": b,
                        "steamId": b,
                        "playerName": suspect.get("name") or b,
                        "message": message,
                        "reason": reason,
                        "from": a,
                    }, project_id=pid)
                    emit_realtime(pid, "report.created", {
                        "reportId": rid,
                        "projectId": pid,
                        "serverId": int((server or {}).get("id") or 0),
                        "playerId": b,
                        "steamId": b,
                        "playerName": suspect.get("name") or b,
                        "message": message,
                        "reason": reason,
                        "status": "open",
                        "createdAt": now_ms(),
                    }, server_id=int((server or {}).get("id") or 0))
                    features.notify_report(conn, reporter, suspect, reason, message, str((server or {}).get("name") or "Server"))
                return {"saved": saved, "ignored": ignored}

            stored = db_call(_rep)
            if isinstance(stored, dict):
                print("PLUGIN reports stored", stored.get("saved"), "ignored", stored.get("ignored"))
                return self._json({"ok": True, "saved": stored.get("saved", 0), "ignored": stored.get("ignored", 0)})
            print("PLUGIN reports stored", stored)
            return self._json({"ok": True, "saved": stored or 0, "ignored": 0})

        if path == "/plugin/contact":
            if not require_plugin(self.headers):
                return self._json({"message": "authorization secret is corrupted"}, 401)

            def _ct(conn):
                server = plugin_server_row(conn, self.headers)
                pid = int((server or {}).get("project_id") or 0)
                srv_id = int((server or {}).get("id") or 0)
                sid = str(body.get("steam_id") or body.get("playerId") or body.get("steamId") or "")
                msg = str(body.get("message") or body.get("contact") or body.get("text") or "").strip()
                if not sid:
                    print("PLUGIN contact rejected: missing steam_id")
                    return {"ok": False, "error": "player_not_found"}
                if not pid:
                    print("PLUGIN contact rejected: server has no project")
                    return {"ok": False, "error": "no_project"}
                upsert_player(conn, sid)
                name_row = conn.execute("SELECT steam_name FROM players WHERE steam_id = ?", (sid,)).fetchone()
                name = (name_row["steam_name"] if name_row else "") or sid
                check = rowd(conn.execute(
                    """SELECT * FROM checks
                       WHERE steam_id = ? AND COALESCE(project_id, 0) = ?
                         AND (finished_at IS NULL OR finished_at = 0)
                         AND LOWER(COALESCE(status, 'active')) NOT IN ('cancel', 'canceled', 'cancelled')
                       ORDER BY id DESC LIMIT 1""",
                    (sid, pid),
                ).fetchone())
                created_new = False
                created_at = now_ms()
                if not check:
                    cur = conn.execute(
                        """INSERT INTO checks (steam_id, steam_name, status, started_at, notice, checker_id, checker_name, checker_email, project_id, contact)
                           VALUES (?, ?, 'active', ?, 0, 0, '', '', ?, ?)""",
                        (sid, name, created_at, pid, msg),
                    )
                    cid = int(cur.lastrowid or 0)
                    check = rowd(conn.execute("SELECT * FROM checks WHERE id = ?", (cid,)).fetchone()) or {
                        "id": cid, "steam_id": sid, "project_id": pid, "status": "active",
                    }
                    created_new = True
                    features.lifetime_bump(conn, "checks", 1)
                    print("PLUGIN contact created check", cid, "player", sid, "project", pid)
                else:
                    cid = int(check.get("id") or 0)
                    if msg:
                        conn.execute("UPDATE checks SET contact = ? WHERE id = ? AND COALESCE(project_id, 0) = ?", (msg, cid, pid))
                    print("PLUGIN contact attached to check", cid, sid, (msg or "")[:80])
                # /contact is structured check data, not a chat bubble.
                # Push a dedicated «Получены контакты игрока» activity item
                # immediately so the check page does not wait on a poll.
                matches = features.find_contact_matches(conn, msg, sid, pid) if msg else []
                if matches:
                    insert_alert(conn, "contact", sid, {
                        "message": msg, "project_id": pid, "checkId": int(check.get("id") or 0),
                        "playerId": sid, "steamId": sid, "playerName": name,
                        "matches": matches, "related_players": matches,
                        "match": True,
                    }, project_id=pid)
                features.audit(conn, "check.contact", {
                    "steam_id": sid,
                    "name": name,
                    "message": msg,
                    "project_id": pid,
                    "check_id": int(check.get("id") or 0),
                })
                cid_num = int(check.get("id") or 0)
                player_brief = activity_player_brief(conn, sid)
                if name and (not player_brief.get("steam_name") or player_brief.get("steam_name") == sid):
                    player_brief["steam_name"] = name
                    player_brief["name"] = name
                contact_item = None
                if msg and cid_num:
                    contact_item = check_contact_activity_item(
                        cid_num, sid, name, msg, player_brief, matches, now_ms(),
                    )
                    prev = _activity_cache_get(cid_num) or []
                    merged = [row for row in prev if isinstance(row, dict) and str(row.get("id")) != contact_item["id"]]
                    merged.append(contact_item)
                    _activity_cache_put(cid_num, merged)
                    emit_realtime(pid, "check-activity", contact_item, server_id=srv_id)
                else:
                    _activity_cache_drop(cid_num)
                payload = {
                    "checkId": cid_num,
                    "projectId": pid,
                    "serverId": srv_id,
                    "playerId": sid,
                    "steamId": sid,
                    "playerName": name,
                    "adminId": int(check.get("checker_id") or 0),
                    "adminName": str(check.get("checker_name") or ""),
                    "status": str(check.get("status") or "active"),
                    "createdAt": int(check.get("started_at") or created_at),
                    "message": msg,
                    "matches": matches if msg else [],
                    "related_players": matches if msg else [],
                    "match": bool(msg and matches),
                    "contact_match": bool(msg and matches),
                }
                if created_new:
                    emit_realtime(pid, "check.created", payload, server_id=srv_id)
                if matches:
                    emit_realtime(pid, "notification.created", {
                        "kind": "contact", "projectId": pid, **payload,
                    }, server_id=srv_id)
                return {"ok": True, **payload}

            result = db_call(_ct) or {"ok": False}
            return self._json(result, 400 if not result.get("ok") else 200)

        if path in ("/plugin/team", "/plugin/team-event", "/plugin/team-history"):
            if not require_plugin(self.headers):
                return self._json({"message": "authorization secret is corrupted"}, 401)

            def _team(conn):
                server = plugin_server_row(conn, self.headers)
                pid = int((server or {}).get("project_id") or 0)
                srv_id = int((server or {}).get("id") or 0)
                if not pid:
                    return {"ok": False, "error": "no_project"}
                event = str(body.get("event") or body.get("type") or body.get("kind") or "team.member.added").strip()
                sid = str(body.get("steam_id") or body.get("playerId") or body.get("steamId") or "")
                members = team_ids_of(body.get("members") or body.get("team") or [])
                if sid and sid not in members:
                    members = [sid, *members]
                if not sid and members:
                    sid = members[0]
                if not sid:
                    return {"ok": False, "error": "player_not_found"}
                mate_ids = [m for m in members if m and m != sid]
                if event in ("team.disbanded", "team.member.removed") and not mate_ids:
                    features.save_team_snapshot(conn, sid, [], pid, srv_id)
                else:
                    features.save_team_snapshot(conn, sid, members, pid, srv_id)
                features.record_team_event(conn, event, sid, members, pid, srv_id)
                emit_realtime(pid, event, {
                    "projectId": pid, "serverId": srv_id, "playerId": sid, "steamId": sid, "members": members,
                }, server_id=srv_id)
                print("PLUGIN team event", event, sid, "members", len(members), "project", pid)
                return {"ok": True, "event": event, "steamId": sid, "members": members}

            return self._json(db_call(_team))

        if path == "/plugin/wipe":
            if not require_plugin(self.headers):
                return self._json({"message": "authorization secret is corrupted"}, 401)
            db_call(lambda c: c.execute("DELETE FROM online_players"))
            return self._json({"ok": True})

        if path == "/plugin/ban":
            if not require_plugin(self.headers):
                return self._json({"message": "authorization secret is corrupted"}, 401)
            sid = str(body.get("target_steam_id") or body.get("steam_id") or "")

            def _ban(conn):
                apply_player_ban(
                    conn,
                    sid,
                    body.get("reason") or "Ban",
                    body.get("comment") or "",
                    bool(body.get("ban_ip")),
                    parse_duration(body.get("duration")),
                )

            db_call(_ban)
            enqueue("kick", {"steam_id": sid, "reason": body.get("reason") or "Ban", "announce": False})
            return self._json({"ok": True})

        if path == "/plugin/unban":
            if not require_plugin(self.headers):
                return self._json({"message": "authorization secret is corrupted"}, 401)
            sid = str(body.get("target_steam_id") or body.get("steam_id") or "")

            def _un(conn):
                row = rowd(conn.execute(
                    "SELECT * FROM bans WHERE steam_id = ? AND active = 1 ORDER BY id DESC LIMIT 1",
                    (sid,),
                ).fetchone())
                if row:
                    return deactivate_ban(conn, row["id"])
                ip_row = rowd(conn.execute(
                    "SELECT ip FROM bans WHERE steam_id = ? ORDER BY id DESC LIMIT 1",
                    (sid,),
                ).fetchone()) or {}
                conn.execute("UPDATE bans SET active = 0, ban_ip = 0 WHERE steam_id = ?", (sid,))
                enqueue_unban(sid, conn=conn, ip=str(ip_row.get("ip") or ""))
                return {"ok": True, "steam_id": sid}

            return self._json(db_call(_un))

        if path in ("/plugin/alerts", "/plugin/custom-alert"):
            if not require_plugin(self.headers):
                return self._json({"message": "authorization secret is corrupted"}, 401)
            alerts = body.get("alerts") or [body]

            def _al(conn):
                pid = current_pid() or 0
                if not pid:
                    return
                for item in alerts:
                    if not isinstance(item, dict):
                        continue
                    insert_alert(
                        conn,
                        item.get("type") or item.get("msg") or "custom",
                        str(item.get("steam_id") or item.get("target_steam_id") or ""),
                        item,
                        project_id=pid,
                    )

            db_call(_al)
            return self._json({"ok": True})

        if path == "/plugin/kills":
            if not require_plugin(self.headers):
                return self._json({"message": "authorization secret is corrupted"}, 401)
            kills = body.get("kills") or body.get("entries") or []
            if isinstance(body, dict) and (
                body.get("initiator_steam_id") or body.get("initiator") or body.get("Initiator")
            ):
                kills = [body]
            if not isinstance(kills, list):
                kills = []

            pending = []

            def _k(conn):
                server = plugin_server_row(conn, self.headers)
                pid = int((server or {}).get("project_id") or current_pid() or 0)
                srv_id = int((server or {}).get("id") or 0)
                if not pid:
                    return {"ok": True, "count": 0, "pid": 0, "server_id": 0}
                try:
                    features.set_request_project(pid)
                    REQ.project_id = pid
                except Exception:
                    pass
                count = 0
                for item in kills:
                    if not isinstance(item, dict):
                        continue
                    a, aname = kill_party_ref(
                        item,
                        "initiator_steam_id", "initiator", "killer", "attacker", "from",
                        "initiator_player", "killer_steam_id", "attacker_steam_id",
                    )
                    b, bname = kill_party_ref(
                        item,
                        "target_steam_id", "target", "victim", "player", "to",
                        "target_player", "victim_steam_id", "player_steam_id",
                    )
                    low = _kill_lower_map(item)
                    if not aname:
                        aname = kill_pretty_name(low.get("initiator_name") or low.get("killer_name") or low.get("attacker_name"), a)
                    if not bname:
                        bname = kill_pretty_name(low.get("target_name") or low.get("victim_name") or low.get("player_name"), b)
                    hit_history = item.get("hit_history") if isinstance(item.get("hit_history"), list) else []
                    if not hit_history:
                        nested = low.get("hits") or low.get("combatlog") or low.get("combat_log")
                        if isinstance(nested, list):
                            hit_history = nested
                    steam_a = kill_steam_from_hits(hit_history, "attacker")
                    steam_b = kill_steam_from_hits(hit_history, "target")
                    if is_real_steam_id(steam_a):
                        a = steam_a
                    if is_real_steam_id(steam_b):
                        b = steam_b
                    hit_attacker, hit_victim = kill_names_from_hits(hit_history)
                    aname = aname or hit_attacker
                    bname = bname or hit_victim
                    a, aname = resolve_kill_actor(conn, a, aname)
                    b, bname = resolve_kill_actor(conn, b, bname)
                    if not a or not b:
                        continue
                    if is_real_steam_id(a):
                        upsert_player(conn, a, aname)
                    if is_real_steam_id(b):
                        upsert_player(conn, b, bname)
                    bone = str(item.get("bone") or "")
                    if not bone and hit_history:
                        last = hit_history[-1] if isinstance(hit_history[-1], dict) else {}
                        bone = str(last.get("bone") or "")
                    bone_store = bone
                    if hit_history:
                        try:
                            bone_store = json.dumps(kill_enrich_hits(hit_history, a, b, str(item.get("weapon") or "")), ensure_ascii=False)
                        except Exception:
                            bone_store = bone
                    created = now_ms()
                    weapon = str(item.get("weapon") or "")
                    distance = float(item.get("distance") or 0)
                    head = 1 if item.get("is_headshot") else 0
                    try:
                        cur = conn.execute(
                            """INSERT INTO kills (initiator_steam_id, target_steam_id, weapon, distance, is_headshot, created_at, project_id, bone, initiator_name, target_name)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            (a, b, weapon, distance, head, created, pid, bone_store, aname, bname),
                        )
                    except Exception:
                        cur = conn.execute(
                            """INSERT INTO kills (initiator_steam_id, target_steam_id, weapon, distance, is_headshot, created_at, project_id, bone)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                            (a, b, weapon, distance, head, created, pid, bone_store),
                        )
                    count += 1
                    kill_id = int(cur.lastrowid or 0)
                    features.emit_json_webhook(conn,"player_kill_create",{"data":{"id":kill_id,"initiator_steam_id":a,"target_steam_id":b,"weapon":weapon,"distance":distance,"is_headshot":bool(head),"created_at":created}},project_id=pid)
                    weapon = str(item.get("weapon") or "")
                    distance = float(item.get("distance") or 0)
                    head = bool(item.get("is_headshot"))
                    if active_check_for_player(conn, a):
                        log_check_player_event(conn, a, "kill", {
                            "target_steam_id": b,
                            "weapon": weapon,
                        })
                    if active_check_for_player(conn, b):
                        log_check_player_event(conn, b, "death", {
                            "initiator_steam_id": a,
                            "weapon": weapon,
                        })
                    for row in emit_check_kill_activity(
                        conn, pid, srv_id, a, b, weapon, distance, head, bone, kill_id, created,
                    ):
                        pending.append((pid, srv_id, row))
                print("[RustApp] Kills saved", count, "project", pid)
                return {"ok": True, "count": count, "pid": pid, "server_id": srv_id}

            out = db_call(_k) or {"ok": True, "count": 0}
            for pid, srv_id, row in pending:
                try:
                    _activity_cache_append(row.get("check_id") or row.get("checkId"), row)
                except Exception:
                    pass
                try:
                    emit_realtime(int(pid or 0), "check-activity", row, server_id=int(srv_id or 0))
                except Exception:
                    pass
            return self._json({"ok": True, "count": int(out.get("count") or 0)})

        if path == "/plugin/signage":
            if not require_plugin(self.headers):
                return self._json({"message": "authorization secret is corrupted"}, 401)
            db_call(lambda c: features.save_signage(c, body if isinstance(body, dict) else {}))
            return self._json({"ok": True})

        if path in ("/ban/plugin/v2", "/plugin/v2"):
            if not require_plugin(self.headers):
                return self._json({"message": "authorization secret is corrupted"}, 401)
            players = body.get("players") or []

            def _bc(conn):
                server = plugin_server_row(conn, self.headers)
                pid = int((server or {}).get("project_id") or current_pid() or 0)
                entries = []
                ts = now_ms()
                conn.execute("UPDATE bans SET active = 0 WHERE active = 1 AND expired_at > 0 AND expired_at < ?", (ts,))
                for player in players:
                    sid = str(player.get("steam_id") or "")
                    ip = normalize_player_ip(player.get("ip") or "")
                    bans = []
                    for row in conn.execute(
                        """SELECT * FROM bans WHERE active = 1 AND COALESCE(pending, 0) = 0 AND COALESCE(project_id, 0) = ?""",
                        (pid,),
                    ).fetchall():
                        row_sid = str(row["steam_id"] or "")
                        row_ip = normalize_player_ip(row["ip"] or "")
                        steam_hit = bool(sid and row_sid == sid)
                        ip_hit = bool(int(row["ban_ip"] or 0) and ip and row_ip and row_ip == ip)
                        if not steam_hit and not ip_hit:
                            continue
                        bans.append({
                            "id": row["id"],
                            "steam_id": row_sid,
                            "ban_ip": row["ip"],
                            "reason": row["reason"],
                            "expired_at": row["expired_at"] or 0,
                            "ban_ip_active": bool(row["ban_ip"]),
                            "computed_is_active": True,
                            "sync_project_id": 0,
                            "sync_should_kick": True,
                        })
                        if ip_hit and row_sid != sid:
                            try:
                                insert_alert(conn, "join_with_ip_ban", sid, {
                                    "steam_id": sid,
                                    "ip": ip,
                                    "banned_steam_id": row_sid,
                                    "ban_id": row["id"],
                                    "message": f"Игрок {sid} пытается подключиться с заблокированного IP {ip}. Подключение отклонено.",
                                }, project_id=pid)
                                emit_realtime(pid, "notification.created", {
                                    "type": "join_with_ip_ban",
                                    "playerId": sid,
                                    "ip": ip,
                                })
                            except Exception:
                                pass
                    entries.append({"steam_id": sid, "ip": ip, "bans": bans})
                return {"entries": entries}

            return self._json(db_call(_bc))

        if path == "/server/pair":
            preferred = str((body or {}).get("code") or "")

            def _mk(conn):
                pid = current_pid()
                if not features.can_add_server(conn, pid):
                    return {
                        "message": "server-limit-exceeded",
                        "error": "server-limit-exceeded",
                        "code": "",
                        "command": "",
                    }
                conn.execute("DELETE FROM pair_codes WHERE created_at < ?", (now_s() - 600,))
                wanted_name = str((body or {}).get("name") or (body or {}).get("hostname") or (params.get("name") or [""])[0] or "")
                code = make_pair_code(conn, preferred, server_name=wanted_name)
                return {"code": code, "command": f"ra.pair {code}", "name": wanted_name or pair_code_server_name(conn, code)}

            payload = db_call(_mk)
            if isinstance(payload, dict) and payload.get("error") == "server-limit-exceeded":
                return self._json(payload, 403)
            return self._json(payload)

        if path == "/check":
            steam_id = str(body.get("steam_id") or body.get("target_steam_id") or body.get("player_id") or "")
            if not steam_id and isinstance(body.get("player"), dict):
                steam_id = str(body["player"].get("steam_id") or body["player"].get("id") or "")
            if not steam_id:
                return self._json({"message": "steam_id required", "ok": False}, 400)
            opts = court_options()
            min_rep = int(opts.get("check_start_min_report") or 0)
            if min_rep > 0:

                def _rep_count(conn):
                    row = conn.execute(
                        "SELECT COUNT(*) AS c FROM reports WHERE target_steam_id = ?" + project_clause()[0],
                        [steam_id, *project_clause()[1]],
                    ).fetchone()
                    return int((row["c"] if row else 0) or 0)

                try:
                    n_reports = db_call(_rep_count)
                except Exception:
                    n_reports = 0
                if n_reports < min_rep:
                    return self._json({"message": "Check start failed, player has no reports", "ok": False}, 400)

            def _chk(conn):
                frozen = features.freeze_actor(conn)
                actor_id = int(frozen.get("actor_user_id") or 0)
                actor_name = str(frozen.get("actor_name") or "")
                actor_email = str(frozen.get("actor_email") or "")
                pid = current_pid() or 0
                if not pid or not actor_id:
                    return {"ok": False, "message": "unauthorized"}
                name_row = conn.execute("SELECT steam_name FROM players WHERE steam_id = ?", (steam_id,)).fetchone()
                name = name_row["steam_name"] if name_row else steam_id
                conn.execute(
                    "UPDATE checks SET status = 'Canceled', finished_at = ? WHERE steam_id = ? AND finished_at = 0 AND project_id = ?",
                    (now_ms(), steam_id, pid),
                )
                cur = conn.execute(
                    """INSERT INTO checks (steam_id, steam_name, status, started_at, notice, checker_id, checker_name, checker_email, project_id)
                       VALUES (?, ?, 'active', ?, 0, ?, ?, ?, ?)""",
                    (steam_id, name, now_ms(), actor_id, actor_name, actor_email, pid),
                )
                cid = cur.lastrowid
                features.audit(conn, "check.started", {"steam_id": steam_id, "name": name})
                features.lifetime_bump(conn, "checks", 1)
                return {"id": cid, "steam_id": steam_id, "status": "Pending", "ok": True, "name": name,
                        "checker_id": actor_id, "checker_name": actor_name, "checker_email": actor_email}

            created = db_call(_chk)
            if isinstance(created, dict) and created.get("ok") is False:
                return self._json(created, 401)
            opts = court_options()
            try:
                enqueue("check_start", {"steam_id": steam_id, "broadcast": bool(opts.get("check_start_broadcast"))})
                enqueue("notice_set", {"steam_id": steam_id, "value": False})
            except Exception as exc:
                print("check enqueue failed", exc)
            cid = int((created or {}).get("id") or 0) if isinstance(created, dict) else int(created or 0)
            player_name = str((created or {}).get("name") or steam_id) if isinstance(created, dict) else steam_id
            staff_id = int((created or {}).get("checker_id") or 0) if isinstance(created, dict) else 0
            staff_name = str((created or {}).get("checker_name") or "") if isinstance(created, dict) else ""
            if not staff_id:
                staff = getattr(REQ, "user", None) or {}
                staff_id = int(staff.get("id") or 0)
            if not staff_name:
                staff = getattr(REQ, "user", None) or {}
                staff_name = features.human_actor_name(str(staff.get("name") or ""), str(staff.get("email") or ""), "")
            notify_pid = int(current_pid() or 0)

            def _notify_later():
                try:
                    features.set_request_project(notify_pid)
                    features.set_request_user(staff_id)
                    db_call(lambda c: features.notify_check(
                        c,
                        {
                            "steam_id": steam_id,
                            "name": player_name,
                            "avatar": "",
                            "check_id": cid,
                            "checker_id": staff_id,
                            "checker_name": staff_name,
                            "project_id": notify_pid,
                        },
                        "Начал проверку",
                        "Проверка начата",
                    ))
                except Exception as exc:
                    print("check notify failed", exc)

            try:
                threading.Thread(target=_notify_later, daemon=True).start()
            except Exception:
                pass
            try:
                started = [{
                    "id": "started-%s" % cid,
                    "M_ID": cid,
                    "check_id": cid,
                    "checkId": cid,
                    "type": "Started",
                    "kind": "Started",
                    "created_at": now_ms(),
                    "meta": {"client_id": staff_id or 1, "steam_id": steam_id, "actor_name": staff_name},
                }]
                _activity_cache_put(cid, started)
            except Exception:
                pass
            try:
                checker = {
                    "id": staff_id or 1,
                    "name": staff_name,
                    "avatar": PLACEHOLDER,
                    "steam": features.empty_steam_profile(PLACEHOLDER),
                    "status": "online",
                    "online": True,
                    "is_online": True,
                }
                # Take a presence snapshot at the moment the check starts.
                # This avoids a blank Status block while the first exact-page
                # request is racing the next plugin state heartbeat.
                player = db_call(lambda c: player_view(
                    c, steam_id, extra={"steam_name": player_name}, nest_team=False, allow_refresh=False
                ))
                player = ensure_player_shape(player, steam_id, player_name)
                _check_exact_cache_put(cid, {
                    "id": cid,
                    "steam_id": steam_id,
                    "status": "Pending",
                    "state": "Pending",
                    "started_at": now_ms(),
                    "created_at": now_ms(),
                    "finished_at": None,
                    "verdict": "",
                    "player": player,
                    "suspect": player,
                    "target_player": player,
                    "checker": checker,
                    "moderator": checker,
                    "initiator_client": checker,
                    "client_id": staff_id or 1,
                    "checker_id": staff_id or 1,
                    "notice": False,
                    "team": [],
                    "suspect_team": [],
                    "team_steam_ids": [],
                    "activity": [],
                    "reports": [],
                })
            except Exception:
                pass
            return self._json(cid)

        if path == "/player-message":
            text = str(body.get("text") or body.get("message") or "")
            target = body.get("target_steam_id") or body.get("reply_steam_id") or body.get("to_steam_id") or body.get("steam_id")
            player = body.get("player") if isinstance(body.get("player"), dict) else {}
            if not target:
                target = player.get("steam_id") or body.get("target") or body.get("to")
            if isinstance(target, dict):
                target = target.get("steam_id") or target.get("id")
            if target in ("", "0", 0, None):
                target = None
            if target is not None:
                target = str(target).strip()
                if not target.isdigit() or len(target) < 10:
                    target = None
            initiator = str(body.get("initiator") or body.get("from") or body.get("send_as") or "").strip().lower()
            from_project = chat_from_project(body)
            if initiator in ("project", "org", "organization"):
                from_project = True
            elif initiator in ("client", "staff", "user", "admin", "moderator"):
                from_project = False
            def _pm(conn):
                frozen = features.freeze_actor(conn)
                actor_id = int(frozen.get("actor_user_id") or 0)
                actor_name = str(frozen.get("actor_name") or "")
                proj_name = project_title(conn)
                display_name = proj_name if from_project else actor_name
                sender_id = "project" if from_project else "site"
                srv = 0
                pid = current_pid() or 0
                if pid:
                    srow = conn.execute(
                        "SELECT id FROM servers WHERE project_id = ? ORDER BY paired DESC, last_seen DESC, id DESC LIMIT 1",
                        (pid,),
                    ).fetchone()
                    if srow:
                        srv = int(srow["id"] or 0)
                mid = insert_chat(
                    conn, sender_id, display_name, target, False, text, True,
                    actor_user_id=actor_id, actor_name=actor_name, author_type="project" if from_project else "staff",
                    server_id=srv,
                ) or 0
                features.audit(conn, "chat.direct" if target else "chat.global", {
                    "steam_id": str(target or ""),
                    "name": str(target or ""),
                    "message": text,
                    "channel": "direct" if target else "global",
                    "from_site": True,
                    "source": "site",
                    "author_type": "project" if from_project else "staff",
                    "author_name": display_name,
                })
                try:
                    enqueue(
                        "chat-message",
                        {
                            "initiator_name": proj_name if from_project else actor_name,
                            "initiator_steam_id": "0",
                            "target_steam_id": target,
                            "message": text,
                            "mode": "direct" if target else "global",
                        },
                        conn=conn,
                    )
                except Exception:
                    pass
                client = staff_brief(conn, actor_name, actor_id, {
                    "actor_name": actor_name,
                    "actor_email": frozen.get("actor_email") or "",
                    "actor_role": frozen.get("actor_role") or "staff",
                    "actor_user_id": actor_id,
                })
                if from_project:
                    pid_n = int(pid or 0)
                    client = {
                        "id": (1000000 + pid_n) if pid_n else int(client.get("id") or 0) or 1,
                        "name": proj_name,
                        "tag": proj_name,
                        "avatar": client.get("avatar") or PLACEHOLDER,
                        "status": "online",
                        "online": True,
                        "is_online": True,
                        "is_project": True,
                    }
                return {"id": int(mid or 0), "server_id": srv, "client": client, "name": display_name}

            packed = db_call(_pm)
            msg_id = int((packed or {}).get("id") or 0)
            srv_id = int((packed or {}).get("server_id") or 0)
            staff_out = (packed or {}).get("client") if isinstance(packed, dict) else None
            if not isinstance(staff_out, dict):
                staff_out = {"id": 0, "name": "", "avatar": PLACEHOLDER, "status": "online"}
            staff_name = str((packed or {}).get("name") or staff_out.get("name") or "")
            staff_out["status"] = "online"
            staff_out["online"] = True
            staff_out["is_online"] = True
            try:
                staff_out["id"] = int(staff_out.get("id") or 0)
            except Exception:
                staff_out["id"] = 0
            initiator_player = {
                "steam_id": "0",
                "steam_name": staff_name,
                "name": staff_name,
                "steam_avatar": staff_out.get("avatar") or PLACEHOLDER,
                "status": "online",
                "team": [],
            }
            target_player = None
            if target:
                target_player = {
                    "steam_id": str(target),
                    "steam_name": str(target),
                    "name": str(target),
                    "steam_avatar": PLACEHOLDER,
                    "status": "offline",
                    "team": [],
                }
            return self._json([{
                "status": "fulfilled",
                "value": {
                    "serverId": srv_id or 1,
                    "server_id": srv_id or 1,
                    "result": True,
                    "id": msg_id,
                    "unique_id": f"msg-{msg_id}",
                    "text": text,
                    "message": text,
                    "steam_id": "project" if from_project else "site",
                    "target_steam_id": target,
                    "target_id": target,
                    "initiator_id": str(int(staff_out.get("id") or 0)),
                    "initiator": "project" if from_project else "client",
                    "initiator_name": staff_name,
                    "initiator_avatar": staff_out.get("avatar") or PLACEHOLDER,
                    "type": "direct" if target else "global",
                    "from_site": True,
                    "created_at": now_ms(),
                    "initiator_client": staff_out,
                    "initiator_player": initiator_player,
                    "target_player": target_player,
                    "target_name": (target_player or {}).get("steam_name") or "",
                    "player": target_player or initiator_player,
                    "team": [],
                    "servers": [{"id": srv_id or 1, "serverId": srv_id or 1}],
                },
            }])

        if path.startswith("/players/") and (path.endswith("/comments") or path.endswith("/notes")):
            steam_id = path.split("/")[2]
            text = str(body.get("text") or body.get("message") or body.get("comment") or body.get("note") or "")

            def _c(conn):
                cur = conn.execute(
                    "INSERT INTO comments (steam_id, text, created_at, project_id) VALUES (?, ?, ?, ?)",
                    (steam_id, text, now_ms(), current_pid() or 0),
                )
                conn.execute("UPDATE players SET comment = ? WHERE steam_id = ?", (text, steam_id))
                row = conn.execute("SELECT * FROM comments WHERE id = ?", (cur.lastrowid,)).fetchone()
                return comment_obj(row, staff_brief(conn))

            created = db_call(_c)
            return self._json(created)

        if path.startswith("/court-commands/") and path.endswith("/prepare"):
            commands = body.get("commands") or body.get("command") or []
            sid = str(body.get("steam_id") or body.get("target_steam_id") or "")
            if not sid:
                player = body.get("player") if isinstance(body.get("player"), dict) else {}
                sid = str(player.get("steam_id") or "")
            cid = path.split("/")[2]

            def _prep(conn):
                name = resolve_player_name(conn, sid, sid) if sid else ""
                saved = features.court_commands_list(conn)
                row = next((item for item in saved if str(item.get("id")) == str(cid)), None) or {}
                raw = commands or row.get("commands") or []
                player = player_view(conn, sid, nest_team=False) if sid else {
                    "steam_id": sid, "steam_name": name or sid, "name": name or sid
                }
                pip = str((player or {}).get("ip") or "")
                frozen = features.freeze_actor(conn)
                staff_sid = str(frozen.get("steam_id") or (getattr(REQ, "user", None) or {}).get("steam_id") or "")
                cmds = flatten_court_commands(raw, sid, name, player_ip=pip, staff_steam_id=staff_sid)
                return court_command_wrap(conn, cid, sid, cmds, player, executed=False)

            return self._json(db_call(_prep))
        if path.startswith("/court-commands/") and path.endswith("/execute"):
            blocked = self._need_server()
            if blocked:
                return blocked
            commands = body.get("commands") or body.get("command") or []
            sid = str(body.get("steam_id") or body.get("target_steam_id") or "")
            if not sid:
                player = body.get("player") if isinstance(body.get("player"), dict) else {}
                sid = str(player.get("steam_id") or player.get("steamId") or "")
            if not sid:
                target = body.get("target") if isinstance(body.get("target"), dict) else {}
                sid = str(target.get("steam_id") or target.get("steamId") or "")
            if not sid:
                check = body.get("check") if isinstance(body.get("check"), dict) else {}
                suspect = check.get("suspect") if isinstance(check.get("suspect"), dict) else {}
                sid = str(suspect.get("steam_id") or check.get("steam_id") or "")

            def _ex(conn):
                name = resolve_player_name(conn, sid, sid) if sid else ""
                saved = features.court_commands_list(conn)
                cid = path.split("/")[2]
                row = next((item for item in saved if str(item.get("id")) == str(cid)), None) or {}
                raw = commands or row.get("commands") or []
                player = player_view(conn, sid, nest_team=False) if sid else {
                    "steam_id": sid, "steam_name": name or sid, "name": name or sid
                }
                pip = str((player or {}).get("ip") or "")
                frozen = features.freeze_actor(conn)
                staff_sid = str(frozen.get("steam_id") or (getattr(REQ, "user", None) or {}).get("steam_id") or "")
                cmds = flatten_court_commands(raw, sid, name, player_ip=pip, staff_steam_id=staff_sid)
                if not cmds and sid:
                    cmds = ["kill %s" % sid]
                print("court execute", cid, "steam", sid, "cmds", cmds)
                enqueue("execute-command", {"commands": cmds}, conn=conn)
                runtime = project_runtime(conn)
                srv = runtime.get("server") if isinstance(runtime, dict) else {}
                features.log_command_execution(
                    conn, cmds,
                    target_steam_id=sid, target_name=name,
                    server_id=int((srv or {}).get("id") or 0),
                    server_name=str((srv or {}).get("name") or ""),
                    result="queued", status="ok",
                )
                features.audit(conn, "custom_action.execute", {
                    "steam_id": sid,
                    "name": name,
                    "commands": cmds,
                    "target": "command",
                    "server_id": int((srv or {}).get("id") or 0),
                    "server_name": str((srv or {}).get("name") or ""),
                    "system_source": "RustCheck",
                })
                player = player_view(conn, sid, nest_team=False) if sid else {
                    "steam_id": sid, "steam_name": name or sid, "name": name or sid
                }
                return court_command_wrap(conn, cid, sid, cmds, player, executed=True)

            return self._json(db_call(_ex))


        if path in ("/player-mute", "/player-mute/", "/player-mute/create"):
            sid = str(body.get("steam_id") or body.get("target_steam_id") or "")
            reason = str(body.get("reason") or "Mute")
            # Prefer relative duration; expired_at may already be absolute ms
            duration = body.get("duration")
            if duration in (None, "", 0, "0"):
                duration = body.get("expired_at")
            expired = parse_duration(duration)
            if duration not in (None, "", 0, "0") and not expired and body.get("minutes"):
                try:
                    expired = now_ms() + int(body.get("minutes")) * 60000
                except Exception:
                    expired = 0
            if not expired and body.get("minutes"):
                try:
                    expired = now_ms() + int(body.get("minutes")) * 60000
                except Exception:
                    expired = 0
            if not sid:
                return self._json({"message": "steam_id required", "ok": False}, 400)
            if not current_pid():
                return self._json({"message": "project required", "ok": False, "error": "no_project"}, 400)
            user = getattr(REQ, "user", None) or self.bind_auth_user()
            if not user or not int((user or {}).get("id") or 0):
                return self._json({"message": "unauthorized", "ok": False}, 401)
            blocked = self._need_server()
            if blocked:
                return blocked

            def _m(conn):
                pid = current_pid() or 0
                if not pid:
                    return {"ok": False, "message": "project required"}
                frozen = features.freeze_actor(conn)
                actor_id = int(frozen.get("actor_user_id") or 0)
                actor_name = str(frozen.get("actor_name") or "")
                actor_email = str(frozen.get("actor_email") or "")
                actor_role = str(frozen.get("actor_role") or "")
                if not actor_id:
                    return {"ok": False, "message": "unauthorized"}
                upsert_player(conn, sid)
                name = resolve_player_name(conn, sid, "")
                if not name:
                    name_row = conn.execute("SELECT steam_name FROM players WHERE steam_id = ?", (sid,)).fetchone()
                    name = (name_row["steam_name"] if name_row else "") or sid
                conn.execute(
                    "UPDATE mutes SET active = 0 WHERE steam_id = ? AND active = 1 AND project_id = ?",
                    (sid, pid),
                )
                created = now_ms()
                try:
                    conn.execute(
                        """INSERT INTO mutes (steam_id, reason, created_at, expired_at, active, project_id, actor_user_id, actor_name, actor_email, actor_role)
                           VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?)""",
                        (sid, reason, created, int(expired or 0), pid, actor_id, actor_name, actor_email, actor_role),
                    )
                except Exception:
                    conn.execute(
                        """INSERT INTO mutes (steam_id, reason, created_at, expired_at, active, project_id, actor_user_id) VALUES (?, ?, ?, ?, 1, ?, ?)""",
                        (sid, reason, created, int(expired or 0), pid, actor_id),
                    )
                mid = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
                left = mute_left_text(expired)
                staff = actor_client(conn, actor_name, actor_id, {
                    "actor_name": actor_name, "actor_email": actor_email, "actor_role": actor_role, "actor_user_id": actor_id,
                })
                staff["name"] = actor_name
                if features.is_generic_staff_label(staff.get("name")):
                    live = features.staff_public_name(features.user_by_id(conn, actor_id) if actor_id else None, actor_name, actor_email)
                    if live:
                        staff["name"] = live
                live_tag = features.staff_public_tag(features.user_by_id(conn, actor_id) if actor_id else None, staff.get("name") or "", conn)
                if live_tag:
                    staff["tag"] = live_tag
                staff["id"] = stable_client_id(actor_id, staff.get("name") or actor_name)
                proj_name = project_title(conn)
                announce = f"Игрок {name} получил мут ({left}): {reason}"
                insert_chat(
                    conn, "project", actor_name or "Admin", None, False, announce, True,
                    project_id=pid or None, actor_user_id=actor_id, actor_name=actor_name, author_type="staff",
                )
                features.audit(conn, "mute.create", {
                    "steam_id": sid, "reason": reason, "name": name,
                    "project_id": pid, "system_source": "RustCheck",
                    "server_id": int((project_runtime(conn).get("server") or {}).get("id") or 0),
                })
                emit_realtime(pid, "mute.created", {"playerId": sid, "actorId": actor_id, "actorName": actor_name})
                try:
                    features.notify_mute(conn, {
                        "steam_id": sid,
                        "name": name,
                        "avatar": "",
                        "admin_name": actor_name,
                        "admin_id": actor_id,
                        "mute_id": mid,
                        "project_id": pid,
                    }, reason, left, True)
                except Exception as exc:
                    print("mute notify failed", exc)
                runtime = project_runtime(conn)
                srv = runtime.get("server") if isinstance(runtime, dict) else None
                return {
                    "id": mid,
                    "target_steam_id": sid,
                    "steam_id": sid,
                    "reason": reason,
                    "created_at": created,
                    "expired_at": int(expired or 0),
                    "computed_is_active": True,
                    "active": True,
                    "client_id": actor_id,
                    "client": staff,
                    "initiator_client": staff,
                    "actor_id": actor_id,
                    "actor_name": actor_name,
                    "system_source": "RustCheck",
                    "deleted_at": None,
                    "target_player": player_view(conn, sid),
                    "duration_text": left,
                    "ok": True,
                    "server_id": int((srv or {}).get("id") or 0),
                    "server_name": str((srv or {}).get("name") or ""),
                    "project_id": pid,
                }

            mute_payload = db_call(_m)
            if not mute_payload.get("ok"):
                return self._json(mute_payload, 400 if mute_payload.get("message") != "unauthorized" else 401)
            left = mute_payload.get("duration_text") or mute_left_text(expired)
            try:
                enqueue("mute", {
                    "steam_id": sid,
                    "name": (mute_payload.get("target_player") or {}).get("steam_name") or sid,
                    "reason": reason,
                    "expired_at": int(expired or 0),
                    "active": True,
                    "announce": True,
                    "duration_text": left,
                    "project_name": project_title(),
                    "initiator_name": mute_payload.get("actor_name") or "Admin",
                    "system_source": "RustCheck",
                })
            except Exception as exc:
                print("mute enqueue failed", exc)
                mute_payload["ok"] = False
                mute_payload["message"] = "Не удалось отправить мут на сервер"
                return self._json(mute_payload, 500)
            return self._json(mute_payload)

        if path == "/plugin/bags":
            bags = body.get("bags") or body or []
            if isinstance(bags, dict):
                bags = [bags]

            def _bg(conn):
                # Plugin requests have no project header — resolve via server token
                server = plugin_server_row(conn, self.headers)
                pid = int((server or {}).get("project_id") or current_pid() or 0)
                if not pid:
                    return None
                existing = {}
                for row in conn.execute(
                    "SELECT net_id, steam_id, name, grid, position FROM bags WHERE COALESCE(project_id, 0) = ?",
                    (pid,),
                ).fetchall():
                    if row["net_id"]:
                        existing[str(row["net_id"])] = dict(row)
                seen = set()
                for item in bags:
                    if not isinstance(item, dict):
                        continue
                    sid = str(item.get("steam_id") or item.get("owner_id") or item.get("deployer_id") or "")
                    if not sid or sid in ("0", "None"):
                        continue
                    upsert_player(conn, sid, str(item.get("steam_name") or item.get("owner_name") or item.get("player_name") or ""))
                    net_id = str(item.get("net_id") or item.get("id") or "")
                    if not net_id:
                        net_id = f"{sid}-{item.get('x')}-{item.get('z')}"
                    seen.add(net_id)
                    pos = item.get("position")
                    if isinstance(pos, dict):
                        pos_raw = json.dumps(pos, ensure_ascii=False)
                    else:
                        pos_raw = str(pos or "")
                        if item.get("x") is not None:
                            pos_raw = json.dumps({"x": item.get("x"), "y": item.get("y"), "z": item.get("z")}, ensure_ascii=False)
                    grid = str(item.get("grid") or item.get("square") or "")
                    bag_name = str(item.get("name") or "bag")
                    prev = existing.get(net_id)
                    prev_sid = str((prev or {}).get("steam_id") or "")
                    if prev_sid and prev_sid != sid:
                        conn.execute(
                            """INSERT INTO bag_events (net_id, from_steam_id, to_steam_id, name, grid, position, created_at, project_id)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                            (net_id, prev_sid, sid, bag_name, grid, pos_raw, now_ms(), pid),
                        )
                    elif not prev:
                        conn.execute(
                            """INSERT INTO bag_events (net_id, from_steam_id, to_steam_id, name, grid, position, created_at, project_id)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                            (net_id, sid, sid, bag_name, grid, pos_raw, now_ms(), pid),
                        )
                    if not prev or (prev_sid and prev_sid != sid):
                        features.emit_json_webhook(conn,"sleeping_bag_create",{"data":{"net_id":net_id,"from_steam_id":prev_sid or sid,"to_steam_id":sid,"name":bag_name,"grid":grid,"position":pos_raw}},project_id=pid)
                    if prev:
                        conn.execute(
                            """UPDATE bags SET steam_id = ?, name = ?, grid = ?, position = ?, from_steam_id = ?, to_steam_id = ?, created_at = ?
                               WHERE net_id = ? AND COALESCE(project_id, 0) = ?""",
                            (sid, bag_name, grid, pos_raw, prev_sid or sid, sid, now_ms(), net_id, pid),
                        )
                    else:
                        conn.execute(
                            """INSERT INTO bags (steam_id, net_id, name, grid, position, from_steam_id, to_steam_id, created_at, project_id)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            (sid, net_id, bag_name, grid, pos_raw, sid, sid, now_ms(), pid),
                        )
                if seen:
                    placeholders = ",".join("?" for _ in seen)
                    conn.execute(
                        f"DELETE FROM bags WHERE COALESCE(project_id, 0) = ? AND net_id != '' AND net_id NOT IN ({placeholders})",
                        (pid, *tuple(seen)),
                    )
                else:
                    # Empty sync = all bags destroyed in-game — wipe project bags
                    conn.execute(
                        "DELETE FROM bags WHERE project_id = ?",
                        (pid,),
                    )
                print("PLUGIN bags sync", "pid", pid, "incoming", len(bags) if isinstance(bags, list) else 0, "seen", len(seen))

            db_call(_bg)
            return self._json({"ok": True})

        if path == "/webhook":
            saved = db_call(lambda c: features.save_webhooks(c, body))
            db_call(lambda c: features.audit(c, "webhook.save", {"count": len(saved)}))
            return self._json(saved)

        if path.startswith("/project/") and (path.endswith("/wallet-topup") or path.endswith("/wallet")):
            amount = int(body.get("amount") or body.get("value") or 0)
            parts = [p for p in path.strip("/").split("/") if p]
            key = parts[1] if len(parts) >= 2 and parts[0] == "project" else ""
            pid = int(current_pid() or features.request_project_id() or 0)
            if key:
                if str(key).isdigit():
                    pid = int(key)
                else:
                    row = get_project_row(key)
                    pid = int(row.get("id") or 0) if row else pid
            if pid:
                features.set_request_project(pid)
                REQ.project_id = pid
            if amount:
                pay_body = dict(body or {})
                pay_body["amount"] = amount
                pay_body["project_id"] = pid
                method = platega_pay.parse_method(pay_body)
                if method not in (2, 13):
                    method = 2
                    pay_body["payment_method"] = 2
                if method:
                    def _pay(conn):
                        return platega_pay.create_payment(conn, self, pay_body)

                    data, code = db_call(_pay)
                    # Native Checkapp PaymentModal expects a JSON string URL, not {redirect:...}.
                    if isinstance(data, dict) and code == 200 and data.get("redirect"):
                        return self._json(data.get("redirect"), code)
                    return self._json(data, code)
                return self._json({
                    "ok": False,
                    "error": "choose_method",
                    "message": "Выберите СБП или Crypto.",
                }, 400)
            pay_only = body.get("renew") or body.get("pay") or body.get("auto_renew")
            if pay_only:
                def _pay(conn):
                    if pid:
                        features.set_request_project(pid)
                    ok = features.try_renew_from_balance(conn)
                    out = features.tariff(conn)
                    out["paid"] = ok
                    if not ok:
                        try:
                            pname = features._named_project(conn, pid)[1]
                            features.notify_transaction("Продление подписки", pname, pid, 0, False, "не удалось списать с баланса")
                        except Exception:
                            pass
                    return out

                return self._json(db_call(_pay))
            return self._json(tariff_state())

        if path == "/tariff/discard-trial":
            def _discard(conn):
                return features.discard_trial(conn)

            return self._json(db_call(_discard))
        if path.startswith("/tariff/") and path.endswith("/select"):
            slug = features.resolve_select_slug(path, body)
            if not slug:
                return self._json({"ok": False, "error": "invalid_plan", "message": "invalid plan"}, 400)

            def _sel(conn):
                return features.select_plan(conn, slug)

            result = db_call(_sel)
            return self._json(result, _tariff_select_status(result))

        if path == "/court-api/toggle":
            value = (params.get("value") or [None])[0]
            if value is None and isinstance(body, dict):
                value = body.get("value")
            return self._json(db_call(lambda c: features.court_api_save(c, {"value": value})))
        if path == "/court-api/public-api-routes":
            routes = body if isinstance(body, dict) else {}
            return self._json(db_call(lambda c: features.court_api_save(c, {"public_api_routes": routes})))
        if path in ("/court/discord-test", "/court-discord/test"):
            url = ""
            if isinstance(body, dict):
                url = str(body.get("webhook") or body.get("url") or "")
            if not url:
                items = db_call(features.discord_list)
                url = next((str(item.get("webhook") or item.get("url") or "") for item in items if (item.get("active") or item.get("enabled")) and (item.get("webhook") or item.get("url"))), "")
            if url:
                threading.Thread(
                    target=lambda hook=url: features.send_discord(hook, "Rustcheck", "Тестовое уведомление: вебхук работает."),
                    daemon=True,
                ).start()
                print("discord test sent")
            else:
                print("discord test skip, no webhook url")
            return self._json({"ok": True, "sent": bool(url)})
        if path == "/court-api/regenerate":
            token = uuid.uuid4().hex
            return self._json(db_call(lambda c: features.court_api_save(c, {"token": token})))
        if path in ("/court-commands", "/court-commands/"):
            saved = db_call(lambda c: features.court_commands_save(c, body if isinstance(body, dict) else {}))
            return self._json(saved[-1] if saved else {"ok": True})
        if path.startswith("/court-commands/") and path.endswith("/toggle"):
            cid = path.split("/")[2]
            active = body.get("active") if isinstance(body, dict) else True
            if "value" in (body or {}):
                active = body.get("value")
            return self._json(db_call(lambda c: features.court_command_toggle(c, cid, active)))
        if path.startswith("/court-commands/") and path.endswith("/edit"):
            cid = path.split("/")[2]
            payload = dict(body or {})
            payload["id"] = int(cid) if str(cid).isdigit() else cid
            saved = db_call(lambda c: features.court_commands_save(c, payload))
            return self._json(next((row for row in saved if str(row.get("id")) == str(cid)), {"ok": True}))
        if path in ("/court/discord", "/court-discord") or path.startswith("/court-discord") or path.startswith("/court/discord"):
            return self.api_put(path, params, body)
        if path.startswith("/check/") and (
            path.endswith("/activity") or path.endswith("/message") or path.endswith("/chat") or path.endswith("/player-message")
        ):
            return self._json(self._post_check_activity(path, body))
        if path.startswith("/players/") and path.endswith("/ban"):
            return self.api_put(path, params, body)
        if path == "/ban" or path == "/ban/":
            return self.api_put(path, params, body)
        if path.startswith("/ban-sync"):
            if "subscription" in path:
                return self._json(db_call(lambda c: features.ban_sync_subscribe(c, body, params)))
            return self._json(db_call(lambda c: features.ban_sync_save(c, body if isinstance(body, dict) else {})))
        if path.startswith("/players/") and path.endswith("/ignore-reports"):
            steam_id = path.split("/")[2]
            payload = body if isinstance(body, dict) else {}
            return self._json(db_call(lambda c: features.ignore_reports_set(c, steam_id, payload, params)))

        return self._json({"ok": True})

    def api_put(self, path, params, body):
        if path.startswith("/admin/api"):
            if admin_panel.handle_api(self, "PUT", path, params, body):
                return
        self.bind_project()
        if "signage" in path and path != "/plugin/signage" and (
            "/like" in path or "/unlike" in path
            or (isinstance(body, dict) and any(k in body for k in ("liked", "is_liked", "likedByCurrentUser", "liked_by_current_user")))
        ):
            return self._json(signage_like_from_request(path, params, body))
        if path in ("/client", "/client/profile"):
            avatar = ""
            payload = body if isinstance(body, dict) else {}
            if isinstance(body, str):
                avatar = body
                payload = {"avatar": body}
            if "tag" in payload or "username" in payload:
                tag = str(payload.get("tag") or payload.get("username") or "").strip().lstrip("@").lower()
                if not re.fullmatch(r"[a-z0-9_]{3,24}", tag):
                    return self._json({"message": "Юзернейм: от 3 до 24 латинских букв, цифр или символов _"}, 400)
                uid = int(features.request_user_id() or 0)
                duplicate = db_call(lambda c: bool(c.execute("SELECT 1 FROM users WHERE LOWER(tag) = ? AND id != ?", (tag, uid)).fetchone()))
                if duplicate:
                    return self._json({"message": "Этот юзернейм уже занят"}, 409)
                payload["tag"] = tag
            saved = db_call(lambda c: features.save_client_profile(c, payload if isinstance(payload, dict) else {}, avatar))
            db_call(lambda c: features.audit(c, "settings.edit", {"target": "profile"}))
            return self._json(saved)
        if path in ("/court", "/court/options") or path.endswith("/options"):
            incoming = body
            if isinstance(body, dict) and isinstance(body.get("options"), dict):
                incoming = body.get("options")

            def _opt(conn):
                save_court_options(conn, incoming if isinstance(incoming, dict) else {})
                features.audit(conn, "settings.edit", {"target": "court"})
                return court_payload(conn)

            return self._json(db_call(_opt))
        if (
            path in ("/court/discord", "/court-discord")
            or path.startswith("/court-discord")
            or path.startswith("/court/discord")
        ):
            if "/toggle" in path:
                typ = path
                if "/court-discord/" in typ:
                    typ = typ.split("/court-discord/", 1)[-1]
                elif "/court/discord/" in typ:
                    typ = typ.split("/court/discord/", 1)[-1]
                typ = typ.split("/toggle")[0].strip("/")
                typ = features.normalize_discord_type(typ)
                value = (params.get("value") or [None])[0]
                if value is None and isinstance(body, dict):
                    value = body.get("value")
                    if value is None:
                        value = body.get("active")
                        if value is None:
                            value = body.get("enabled")
                print("discord toggle request", typ, "value", value)
                saved = db_call(lambda c: features.discord_toggle(c, typ, value))
            else:
                saved = db_call(lambda c: features.discord_upsert(c, body))
            db_call(lambda c: features.audit(c, "settings.edit", {"target": "discord"}))
            return self._json(saved)
        if path == "/webhook":
            saved = db_call(lambda c: features.save_webhooks(c, body))
            return self._json(saved)
        if path.startswith("/court-autokick/") or path.startswith("/auto-kick/"):
            name = path.rstrip("/").rsplit("/", 1)[-1]
            payload = dict(body) if isinstance(body, dict) else {}
            if "type" not in payload and "name" not in payload:
                payload["type"] = name
            try:
                saved = db_call(lambda c: features.save_autokick(c, payload))
            except Exception as exc:
                print("autokick save failed", type(exc).__name__, exc)
                saved = autokick_rules()
            db_call(lambda c: features.audit(c, "settings.edit", {"target": "autokick"}))
            return self._json(saved)
        if path in ("/court-autokick", "/auto-kick"):
            try:
                saved = db_call(lambda c: features.save_autokick(c, body))
            except Exception as exc:
                print("autokick save failed", type(exc).__name__, exc)
                saved = autokick_rules()
            db_call(lambda c: features.audit(c, "settings.edit", {"target": "autokick"}))
            return self._json(saved)
        if path.startswith("/players/") and path.endswith("/settings-auto-kick"):
            steam_id = unquote(path.split("/")[2])
            pid = current_pid() or features.request_project_id() or 0
            force = str(self.headers.get("X-Checkapp-Player-Perm") or self.headers.get("x-checkapp-player-perm") or "").strip() == "1"
            saved = db_call(lambda c: features.player_autokick_set(c, steam_id, body if isinstance(body, dict) else {}, project_id=pid, force=force))
            return self._json(features.player_autokick_client(saved))
        if path.startswith("/players/") and path.endswith("/ignore-reports"):
            steam_id = path.split("/")[2]
            payload = body if isinstance(body, dict) else {}
            return self._json(db_call(lambda c: features.ignore_reports_set(c, steam_id, payload, params)))
        if path == "/server/pair":
            def _complete(conn):
                code = str((body or {}).get("code") or "").strip()
                name = str((body or {}).get("name") or "").strip()
                pid = current_pid()
                padded = code.zfill(6) if code.isdigit() and len(code) <= 6 else code
                pair = conn.execute("SELECT * FROM pair_codes WHERE (code=? OR code=?) AND project_id=?", (code, padded, pid)).fetchone()
                if not pair:
                    return {"ok": False, "message": "Code not exists"}
                token = conn.execute("SELECT value FROM settings WHERE key=?", (f"pair_token_{pair['code']}",)).fetchone()
                srv = plugin_server_row(conn, {"X-Plugin-Auth": str(token["value"] or "")}) if token else None
                if not srv or int(srv.get("project_id") or 0) != int(pid or 0):
                    return {"ok": False, "message": "Server is not paired"}
                claimed = as_int((body or {}).get("server_id"))
                if claimed and claimed != int(srv["id"]):
                    return {"ok": False, "message": "Server does not match pair code"}
                conn.execute("UPDATE servers SET name=COALESCE(NULLIF(?,''),name) WHERE id=?", (name, srv["id"]))
                conn.execute("UPDATE pair_codes SET used=1,server_name=COALESCE(NULLIF(?,''),server_name) WHERE code=?", (name, pair["code"]))
                conn.execute("INSERT OR REPLACE INTO settings(key,value) VALUES (?,?)", (f"pair_named_{pair['code']}", "1"))
                srv = conn.execute("SELECT * FROM servers WHERE id=?", (srv["id"],)).fetchone()
                return {"ok": True, "server": server_view(conn, srv)}

            return self._json(db_call(_complete))
        if path.startswith("/ban-sync"):
            if "subscription" in path:
                return self._json(db_call(lambda c: features.ban_sync_subscribe(c, body, params)))
            return self._json(db_call(lambda c: features.ban_sync_save(c, body if isinstance(body, dict) else {})))
        if path == "/court-api":
            return self._json(db_call(lambda c: features.court_api_save(c, body if isinstance(body, dict) else {})))
        if path.startswith("/court-commands/") and path.endswith("/edit"):
            cid = path.split("/")[2]
            payload = dict(body or {})
            payload["id"] = int(cid) if str(cid).isdigit() else cid
            saved = db_call(lambda c: features.court_commands_save(c, payload))
            return self._json(next((row for row in saved if str(row.get("id")) == str(cid)), {"ok": True}))
        if path == "/court-commands/save-order":
            return self._json(db_call(features.court_commands_list))
        if path.startswith("/utils/tariff") or path.startswith("/tariff"):
            slug = features.resolve_select_slug(path, body)
            if not slug:
                return self._json({"ok": False, "error": "invalid_plan", "message": "invalid plan"}, 400)

            def _plan(conn):
                return features.select_plan(conn, slug)

            result = db_call(_plan)
            return self._json(result, _tariff_select_status(result))
        if path == "/plugin/state":
            if not require_plugin(self.headers):
                return self._json({"message": "authorization secret is corrupted"}, 401)
            info = body.get("server_info") or body if isinstance(body, dict) else {}
            players = (body.get("players") or []) if isinstance(body, dict) else []
            if not isinstance(players, list):
                players = []
            remote_ip = admin_panel.plugin_remote_ip(self)

            def _st(conn):
                server = plugin_server_row(conn, self.headers)
                if not server:
                    return []
                sid = int(server["id"])
                pid = int(server.get("project_id") or 0)
                if not pid:
                    print("[RustApp] State update skipped, server has no project_id", sid)
                    return []
                REQ.project_id = pid
                features.set_request_project(pid)
                print("[RustApp] State update server", sid, "players", len(players), "project", pid)
                # Prefer IP reported by plugin body; then plugin TCP/proxy remote; then this host's public IP
                server_ip = features.normalize_server_ip(info if isinstance(info, dict) else {}, "")
                if not server_ip and isinstance(body, dict):
                    server_ip = features.normalize_server_ip(body, "")
                if not server_ip:
                    server_ip = features.pick_public_server_ip(remote_ip)
                if server_ip:
                    prev_ip = str(server.get("server_ip") or "").strip()
                    public_new = server_ip and not features._is_private_ip(server_ip)
                    public_old = prev_ip and not features._is_private_ip(prev_ip)
                    store_ip = server_ip
                    if public_new or not public_old:
                        store_ip = server_ip
                    elif public_old:
                        store_ip = prev_ip
                    conn.execute(
                        "UPDATE servers SET server_ip = COALESCE(NULLIF(?, ''), server_ip) WHERE id = ?",
                        (store_ip, sid),
                    )
                    features.sync_server_ip_registry(conn, pid, sid, store_ip)
                    if public_new and store_ip != prev_ip:
                        features.sync_server_ip_registry(conn, pid, sid, server_ip)
                    if features.enforce_blocked_server_ip(conn, pid, store_ip):
                        print("[RustApp] Server IP blocked", store_ip, "project", pid)
                conn.execute(
                    """UPDATE servers SET name=COALESCE(NULLIF(name,''),NULLIF(?,'')), hostname=COALESCE(NULLIF(?,''),hostname),
                        level=COALESCE(NULLIF(?,''),level), description=COALESCE(NULLIF(?,''),description),
                        online=?, slots=?, port=?, version=?, protocol=?, connected=1, last_seen=?,
                        world_size=CASE WHEN ? > 0 THEN ? ELSE world_size END,
                        seed=CASE WHEN ? > 0 THEN ? ELSE seed END
                       WHERE id=?""",
                    (
                        info.get("name") or "",
                        info.get("hostname") or "",
                        info.get("level") or "",
                        info.get("description") or "",
                        int(info.get("online") or len(players)),
                        int(info.get("slots") or 0),
                        int(info.get("port") or 0),
                        info.get("version") or "",
                        info.get("protocol") or "",
                        now_s(),
                        as_int(info.get("world_size") or info.get("size") or body.get("world_size") or body.get("size")),
                        as_int(info.get("world_size") or info.get("size") or body.get("world_size") or body.get("size")),
                        as_int(info.get("seed") or body.get("seed")),
                        as_int(info.get("seed") or body.get("seed")),
                        sid,
                    ),
                )
                map_url = ""
                if isinstance(info, dict):
                    map_url = str(
                        info.get("level_image_url")
                        or info.get("image_url")
                        or info.get("map_image")
                        or ""
                    ).strip()
                if not map_url.startswith("http") and isinstance(body, dict):
                    map_url = str(
                        body.get("level_image_url")
                        or body.get("image_url")
                        or body.get("map_image")
                        or ""
                    ).strip()
                map_file = UPLOADS / f"map-{sid}.png"
                have_local = map_file.exists() and map_file.stat().st_size > 100
                if map_url.startswith("http") and not have_local:
                    stored_map = str(server.get("map_image") or "").strip()
                    if stored_map.startswith("/uploads/"):
                        pass
                    elif stored_map == map_url:
                        pass
                    else:
                        data = fetch_remote_map_bytes(map_url)
                        if len(data) > 100:
                            map_file.write_bytes(data)
                            conn.execute(
                                "UPDATE servers SET map_image=? WHERE id=?",
                                (f"/uploads/map-{sid}.png", sid),
                            )
                        else:
                            conn.execute(
                                "UPDATE servers SET map_image=COALESCE(NULLIF(map_image,''), ?) WHERE id=?",
                                (map_url, sid),
                            )
                prev_payloads = {}
                for row in conn.execute(
                    "SELECT steam_id, payload FROM online_players WHERE COALESCE(server_id, 1) = ?",
                    (sid,),
                ).fetchall():
                    try:
                        prev_payloads[str(row["steam_id"])] = json.loads(row["payload"] or "{}")
                    except Exception:
                        prev_payloads[str(row["steam_id"])] = {}
                prev_online = set(prev_payloads.keys())
                sync_online_sessions(conn, players, sid, pid)
                disconnected_map = (body.get("disconnected") or {}) if isinstance(body, dict) else {}
                if isinstance(disconnected_map, dict):
                    for steam_id, reason in disconnected_map.items():
                        steam_key = str(steam_id or "").strip()
                        if not steam_key or not is_real_steam_id(steam_key):
                            continue
                        if not active_check_for_player(conn, steam_key):
                            continue
                        log_check_player_event(conn, steam_key, "disconnect", {
                            "reason": str(reason or "disconnect"),
                        })
                team_changes_map = (body.get("team_changes") or {}) if isinstance(body, dict) else {}
                if isinstance(team_changes_map, dict):
                    for initiator, target in team_changes_map.items():
                        initiator_key = str(initiator or "").strip()
                        target_key = str(target or initiator or "").strip()
                        if not initiator_key or not is_real_steam_id(initiator_key):
                            continue
                        # Always persist team history for this project — not only during an active check
                        try:
                            if initiator_key == target_key:
                                features.save_team_snapshot(conn, initiator_key, [], pid, sid)
                                features.record_team_event(conn, "team.member.removed", initiator_key, [], pid, sid)
                            else:
                                features.record_team_event(
                                    conn, "team.member.added", initiator_key, [initiator_key, target_key], pid, sid,
                                )
                        except Exception as exc:
                            print("team_changes snapshot failed", initiator_key, type(exc).__name__, exc)
                        if not active_check_for_player(conn, initiator_key):
                            continue
                        log_check_player_event(conn, initiator_key, "team", {
                            "initiator_steam_id": initiator_key,
                            "target_steam_id": target_key,
                        })
                conn.execute("DELETE FROM online_players WHERE COALESCE(server_id, 1) = ?", (sid,))
                kicks = []
                current_online = set()
                status_map = {}
                for player in players:
                    steam = str(player.get("steam_id") or "")
                    if not is_real_steam_id(steam):
                        continue
                    current_online.add(steam)
                    player = dict(player)
                    raw_status = str(player.get("status") or "").strip().lower()
                    if raw_status in ("queue", "queueing"):
                        player["status"] = "queued"
                    elif raw_status in ("joining", "queued", "afk", "unstable"):
                        player["status"] = raw_status
                    elif not raw_status or raw_status in ("offline", "active", "online"):
                        player["status"] = "online"
                    prev = prev_payloads.get(steam) if isinstance(prev_payloads.get(steam), dict) else {}
                    prev_home = prev.get("home") if isinstance(prev.get("home"), dict) else {}
                    # Prefer explicit home from plugin (TC auth); can_build as fallback when on TC
                    home_in = player.get("home") if isinstance(player.get("home"), dict) else {}
                    can_build_flag = bool(player.get("can_build"))
                    if "value" in home_in:
                        at_home = bool(home_in.get("value")) or can_build_flag
                        player["home"] = resolve_home_state(prev_home, at_home)
                        if at_home:
                            player["home"]["time"] = int(home_in.get("time") or now_ms())
                            try:
                                features.write_cache(conn, "home_cache", "steam_id", steam, player["home"])
                            except Exception:
                                pass
                        else:
                            # Keep last-known at-base time from plugin, previous payload, or DB cache
                            cached = features.read_cache(conn, "home_cache", "steam_id", steam) or {}
                            t = (
                                int(home_in.get("time") or 0)
                                or int(prev_home.get("time") or 0)
                                or int((cached or {}).get("time") or 0)
                            )
                            player["home"]["time"] = t
                            if t:
                                try:
                                    features.write_cache(conn, "home_cache", "steam_id", steam, {"value": False, "time": t})
                                except Exception:
                                    pass
                    elif can_build_flag:
                        player["home"] = resolve_home_state(prev_home, True)
                        player["home"]["time"] = now_ms()
                        try:
                            features.write_cache(conn, "home_cache", "steam_id", steam, player["home"])
                        except Exception:
                            pass
                    else:
                        cached = features.read_cache(conn, "home_cache", "steam_id", steam) or {}
                        player["home"] = resolve_home_state(prev_home or cached, False)
                        if not player["home"].get("time") and cached.get("time"):
                            player["home"]["time"] = int(cached.get("time") or 0)
                    try:
                        px = float(prev.get("x") or 0)
                        py = float(prev.get("y") or 0)
                        pz = float(prev.get("z") or 0)
                        cx = float(player.get("x") or 0)
                        cy = float(player.get("y") or 0)
                        cz = float(player.get("z") or 0)
                    except (TypeError, ValueError):
                        px = py = pz = cx = cy = cz = 0.0
                    dist2 = (cx - px) ** 2 + (cy - py) ** 2 + (cz - pz) ** 2
                    prev_moved = int(prev.get("last_moved_seconds") or 0)
                    joining_now = str(player.get("status") or "").strip().lower() in ("joining", "queued")
                    if joining_now:
                        player["last_moved_seconds"] = prev_moved if prev_moved else now_ms()
                    elif dist2 > 1.0 or not prev:
                        player["last_moved_seconds"] = now_ms()
                    elif prev_moved >= 10**12:
                        player["last_moved_seconds"] = prev_moved
                    else:
                        player["last_moved_seconds"] = last_moved_stamp(
                            player.get("last_moved_seconds") or player.get("last_moved_at") or player.get("last_moved") or prev_moved or 0
                        )
                    live_status = _normalize_player_presence(player)
                    status_map[steam] = live_status
                    player["server_id"] = sid
                    upsert_player(
                        conn,
                        steam,
                        player.get("steam_name") or "",
                        player.get("ip") or "",
                        player.get("language") or "",
                        bool(player.get("no_license")),
                        seen=True,
                    )
                    try:
                        mates = team_ids_of(player.get("team"))
                        if mates:
                            features.save_team_snapshot(conn, steam, [steam, *mates], pid, sid)
                    except Exception as exc:
                        print("save_team_snapshot failed", steam, type(exc).__name__, exc)
                    conn.execute("DELETE FROM online_players WHERE steam_id = ? AND COALESCE(server_id, 1) = ?", (steam, sid))
                    conn.execute(
                        "INSERT INTO online_players (steam_id, payload, server_id, project_id) VALUES (?, ?, ?, ?)",
                        (steam, json.dumps(player, ensure_ascii=False), sid, pid),
                    )
                    hit = features.apply_autokick(conn, steam, player, project_id=pid)
                    if hit:
                        kicks.append(hit)
                    if steam not in prev_online or not features.read_cache(conn, "steam_cache", "steam_id", steam):
                        refresh_steam_async(steam, pid)
                    is_new = steam not in prev_online
                    if is_new:
                        print("[RustApp] Player joined", steam, player.get("steam_name") or steam, "server", sid)
                    if is_new:
                        features.notify_foreign_bans(conn,steam,player.get("steam_name") or steam,pid)
                        ip = str(player.get("ip") or "").split(":")[0]
                        geo = features.read_cache(conn, "ip_cache", "ip", ip) if ip else None
                        if isinstance(geo, dict) and geo.get("proxy"):
                            insert_alert(conn, "vpn_detected", steam, {
                                "steam_id": steam,
                                "ip": ip,
                                "provider": geo.get("provider") or geo.get("isp") or "",
                                "country": geo.get("country_name") or geo.get("country") or "",
                                "meta": {"ip": ip, "provider": geo.get("provider") or ""},
                            }, project_id=pid)
                        elif ip:
                            def _geo(ip_addr=ip, steam_id=steam, alert_pid=pid):
                                try:
                                    data = features.fetch_ip_geo(ip_addr)
                                    def _save(c):
                                        features.set_request_project(alert_pid)
                                        features.write_cache(c, "ip_cache", "ip", ip_addr, data)
                                        if data.get("proxy"):
                                            exists = c.execute(
                                                "SELECT 1 FROM alerts WHERE type = 'vpn_detected' AND steam_id = ? AND COALESCE(project_id, 0) = ? ORDER BY id DESC LIMIT 1",
                                                (steam_id, alert_pid),
                                            ).fetchone()
                                            if not exists:
                                                insert_alert(c, "vpn_detected", steam_id, {
                                                    "steam_id": steam_id,
                                                    "ip": ip_addr,
                                                    "provider": data.get("provider") or "",
                                                    "country": data.get("country_name") or data.get("country") or "",
                                                }, project_id=alert_pid)
                                        return features.apply_autokick(c, steam_id, {"ip": ip_addr}, project_id=alert_pid)
                                    hit = db_call(_save)
                                    if hit:
                                        enqueue("kick", {"steam_id": steam_id, "reason": hit.get("reason") or "Auto-kick", "announce": False}, project_id=alert_pid)
                                except Exception as exc:
                                    print("vpn geo failed", ip_addr, type(exc).__name__)
                            threading.Thread(target=_geo, daemon=True).start()
                        if conn.execute(
                            "SELECT 1 FROM bans WHERE steam_id = ? AND active = 1 AND COALESCE(project_id, 0) = ?",
                            (steam, pid),
                        ).fetchone():
                            insert_alert(conn, "detect_ra_ban", steam, {"steam_id": steam, "ip": ip}, project_id=pid)
                        refresh_steam_async(steam, pid)
                        emit_realtime(pid, "player.joined", {
                            "playerId": steam,
                            "steam_id": steam,
                            "name": player.get("steam_name") or steam,
                            "status": live_status,
                        }, server_id=sid)
                for gone in (prev_online - current_online):
                    emit_realtime(pid, "player.left", {"playerId": gone, "steam_id": gone, "status": "offline"}, server_id=sid)
                if status_map:
                    emit_realtime(pid, "player.status", {"players": status_map}, server_id=sid)
                emit_realtime(pid, "player.updated", {"online": list(current_online), "players": status_map}, server_id=sid)
                try:
                    touch_online_peak(conn, pid)
                except Exception:
                    pass
                return kicks

            kicks = db_call(_st)
            if isinstance(kicks, list):
                for hit in kicks:
                    enqueue("kick", {"steam_id": hit.get("steam_id"), "reason": hit.get("reason") or "Auto-kick", "announce": False}, project_id=hit.get("project_id"))
            # Re-sync active mutes to plugin occasionally (survives oxide.reload)
            try:
                now_sync = time.time()
                last = float(getattr(Handler, "_last_mute_sync", 0) or 0)
                if now_sync - last >= 45:
                    Handler._last_mute_sync = now_sync

                    def _resync_mutes(conn):
                        now = now_ms()
                        expired_rows = []
                        try:
                            expired_rows = conn.execute(
                                """SELECT id, steam_id, reason, project_id FROM mutes
                                   WHERE active = 1 AND expired_at > 0 AND expired_at <= ?""",
                                (now,),
                            ).fetchall()
                        except Exception:
                            expired_rows = []
                        for row in expired_rows:
                            sid_m = str(row["steam_id"] or "")
                            pid_m = int(row["project_id"] or 0)
                            conn.execute("UPDATE mutes SET active = 0 WHERE id = ?", (row["id"],))
                            if sid_m and pid_m:
                                try:
                                    insert_chat(
                                        conn, "project", "RustApp", sid_m, False,
                                        "Ваш мут истек.", True,
                                        project_id=pid_m, actor_user_id=0, actor_name="RustApp",
                                    )
                                    enqueue("chat-message", {
                                        "initiator_name": "RustApp",
                                        "initiator_steam_id": "0",
                                        "target_steam_id": sid_m,
                                        "message": "Ваш мут истек.",
                                        "mode": "direct",
                                    }, conn=conn, project_id=pid_m)
                                    enqueue("mute", {"steam_id": sid_m, "active": False, "reason": "expired", "announce": False}, conn=conn, project_id=pid_m)
                                    features.audit(conn, "mute.expired", {
                                        "steam_id": sid_m,
                                        "actor_name": "RustApp",
                                        "system_source": "RustCheck",
                                        "project_id": pid_m,
                                    })
                                    features.notify_mute(conn, {
                                        "steam_id": sid_m,
                                        "name": sid_m,
                                        "admin_name": "RustApp",
                                        "admin_id": 0,
                                        "mute_id": int(row["id"] or 0),
                                        "project_id": pid_m,
                                    }, str(row["reason"] or "Mute"), "", False)
                                    emit_realtime(pid_m, "mute.removed", {"playerId": sid_m, "expired": True})
                                except Exception as exc:
                                    print("mute expire notify failed", exc)
                        # Fix absurd microsecond expired_at values from older parses
                        for row in conn.execute(
                            "SELECT id, expired_at FROM mutes WHERE active = 1 AND expired_at > 4102444800000"
                        ).fetchall():
                            fixed = int(row["expired_at"]) // 1000
                            if fixed <= now:
                                conn.execute("UPDATE mutes SET active = 0, expired_at = ? WHERE id = ?", (fixed, row["id"]))
                            else:
                                conn.execute("UPDATE mutes SET expired_at = ? WHERE id = ?", (fixed, row["id"]))
                        rows = conn.execute(
                            """SELECT steam_id, reason, expired_at FROM mutes
                               WHERE active = 1 AND (expired_at = 0 OR expired_at > ?)""",
                            (now,),
                        ).fetchall()
                        return [
                            {
                                "steam_id": r["steam_id"],
                                "reason": r["reason"] or "Mute",
                                "expired_at": int(r["expired_at"] or 0),
                                "active": True,
                            }
                            for r in rows
                        ]

                    mutes = db_call(_resync_mutes)
                    for m in mutes or []:
                        enqueue("mute", m)
            except Exception as exc:
                print("mute resync failed", type(exc).__name__, exc)
            return self._json({"ok": True})

        if path in ("/queue", "/queue/"):
            if not require_plugin(self.headers):
                return self._json({"message": "authorization secret is corrupted"}, 401)
            results = body.get("data") or {}

            def _ack(conn):
                server = plugin_server_row(conn, self.headers)
                pid = int((server or {}).get("project_id") or 0)
                for task_id, result in results.items():
                    if pid:
                        conn.execute(
                            "UPDATE queue SET done = 1, result = ? WHERE id = ? AND COALESCE(project_id, 0) = ?",
                            (json.dumps(result, ensure_ascii=False, default=str), str(task_id), pid),
                        )
                    else:
                        conn.execute(
                            "UPDATE queue SET done = 1, result = ? WHERE id = ?",
                            (json.dumps(result, ensure_ascii=False, default=str), str(task_id)),
                        )

            db_call(_ack)
            return self._json({"ok": True})

        if path == "/server/pair":
            preferred = str((body or {}).get("code") or (params.get("code") or [""])[0] or "")

            def _mk(conn):
                pid = current_pid()
                if not features.can_add_server(conn, pid):
                    return {
                        "message": "server-limit-exceeded",
                        "error": "server-limit-exceeded",
                        "code": "",
                        "command": "",
                        "ok": False,
                    }
                wanted_name = str((body or {}).get("name") or (body or {}).get("hostname") or (params.get("name") or [""])[0] or "")
                code = make_pair_code(conn, preferred, server_name=wanted_name)
                return {"code": code, "command": f"ra.pair {code}", "ok": True, "name": wanted_name or pair_code_server_name(conn, code)}

            payload = db_call(_mk)
            if isinstance(payload, dict) and payload.get("error") == "server-limit-exceeded":
                return self._json(payload, 403)
            return self._json(payload)
        if path == "/server/save-order":
            return self._json({"ok": True})
        if path.startswith("/server/") and path[8:].split("/")[0].isdigit():
            sid = int(path.split("/")[2])

            def _save(conn):
                payload = body if isinstance(body, dict) else {}
                result = update_server(conn, sid, payload)
                return result

            result = db_call(_save)
            if result.get("message") == "not found":
                return self._json(result, 404)
            if result.get("message") == "forbidden":
                return self._json(result, 403)
            return self._json(result)
        if path.startswith("/project/") and path.endswith("/general"):
            pid = path.split("/")[2]
            name = str((body or {}).get("name") or "").strip()
            avatar = str((body or {}).get("avatar") or "").strip()
            contact = str((body or {}).get("contact_url") or "").strip()
            domain_raw = (body or {}).get("domain")

            def _upd(conn):
                sets: list[str] = []
                vals: list = []
                if name:
                    domain = unique_domain(conn, domain_raw or name, skip_id=pid)
                    sets.extend(["name = ?", "domain = ?"])
                    vals.extend([name, domain])
                elif domain_raw:
                    domain = unique_domain(conn, domain_raw, skip_id=pid)
                    sets.append("domain = ?")
                    vals.append(domain)
                if avatar:
                    sets.append("avatar = ?")
                    vals.append(avatar)
                if contact:
                    sets.append("contact_url = ?")
                    vals.append(contact)
                if sets:
                    vals.append(pid)
                    conn.execute(f"UPDATE project SET {', '.join(sets)} WHERE id = ?", vals)
                    print("PROJECT general updated", pid, "avatar" if avatar else "", "name" if name else "")
                steam_strict = (body or {}).get("steam_strict")
                if steam_strict is None:
                    steam_strict = (body or {}).get("require_steam")
                twofa = (body or {}).get("twofa_strict")
                if twofa is None:
                    twofa = (body or {}).get("twofactor_strict") or (body or {}).get("require_2fa")
                try:
                    if steam_strict is not None:
                        conn.execute("UPDATE project SET steam_strict = ? WHERE id = ?", (1 if steam_strict else 0, pid))
                    if twofa is not None:
                        conn.execute("UPDATE project SET twofa_strict = ? WHERE id = ?", (1 if twofa else 0, pid))
                except Exception:
                    pass
                return rowd(conn.execute("SELECT * FROM project WHERE id = ?", (pid,)).fetchone())

            return self._json(project_obj(db_call(_upd)))

        if path.startswith("/players/") and path.endswith("/kick"):
            blocked = self._need_server()
            if blocked:
                return blocked
            steam_id = path.split("/")[2]
            reason = (params.get("reason") or [body.get("reason") if body else "Kicked"])[0] or "Kicked"
            announce = str((params.get("announce") or ["false"])[0]).lower() == "true"

            def _log_kick(conn):
                log_check_player_event(conn, steam_id, "kick", {"reason": reason})

            db_call(_log_kick)
            enqueue("kick", {"steam_id": steam_id, "reason": reason, "announce": announce})
            return self._json({"ok": True})

        if path.startswith("/players/") and path.endswith("/ban"):
            blocked = self._need_server()
            if blocked:
                return blocked
            steam_id = path.split("/")[2]
            payload = body if isinstance(body, dict) else {}
            if not payload.get("target") and not payload.get("team") and not payload.get("bans"):
                payload = dict(payload)
                payload["target"] = {
                    "steamId": steam_id,
                    "reason": payload.get("reason") or "Ban",
                    "ban_ip": payload.get("ban_ip"),
                    "destroy_buildings": payload.get("destroy_buildings") or payload.get("destroyBuildings"),
                }
            broadcast = payload.get("override_broadcast", True)

            def _ban(conn):
                return enqueue_player_bans(conn, payload, bool(broadcast))

            created = db_call(_ban)
            return self._json({"ok": True, "bans": created or []})

        if path == "/ban" or path == "/ban/":
            blocked = self._need_server()
            if blocked:
                return blocked
            payload = body if isinstance(body, dict) else {}
            broadcast = payload.get("override_broadcast", True)

            def _ban(conn):
                return enqueue_player_bans(conn, payload, bool(broadcast))

            created = db_call(_ban)
            return self._json({"ok": True, "bans": created})

        if path.startswith("/check/") and path.endswith("/freeze-state"):
            value=(body or {}).get("active")
            if not isinstance(value,bool):
                return self._json({"ok":False,"error":"invalid_active"},400)
            result=db_call(lambda conn:check_freeze_state(conn,as_int(path.split("/")[2]),value))
            return self._json(result,200 if result.get("ok") else 403)
        if path.startswith("/check/") and path.endswith("/notice-state"):
            cid = path.split("/")[2]
            active = True
            if isinstance(body, dict) and "active" in body:
                active = bool(body.get("active"))
            elif params.get("active"):
                active = str(params.get("active")[0]).lower() != "false"

            def _ns(conn):
                row = rowd(conn.execute("SELECT steam_id FROM checks WHERE id = ?", (cid,)).fetchone())
                frozen = features.freeze_actor(conn)
                if row:
                    conn.execute("UPDATE checks SET notice = ? WHERE id = ?", (1 if active else 0, cid))
                    enqueue("notice_set", {"steam_id": row["steam_id"], "value": active}, conn=conn)
                    features.audit(conn, "check.notice", {
                        "check_id": int(cid) if str(cid).isdigit() else cid,
                        "steam_id": row["steam_id"],
                        "active": bool(active),
                        "client_id": int(frozen.get("actor_user_id") or 1),
                    })
                return active

            result = db_call(_ns)
            try:
                _activity_cache_drop(cid)
            except Exception:
                pass
            return self._json(result)

        if path.startswith("/ban/") and path.split("/")[-1].isdigit():
            bid = path.split("/")[-1]

            def _edit(conn):
                row = rowd(conn.execute("SELECT * FROM bans WHERE id = ?", (bid,)).fetchone())
                if not row:
                    return {}
                pending = False
                try:
                    pending = bool(int(row.get("pending") or 0))
                except Exception:
                    pending = False
                if pending:
                    comment = ""
                    if isinstance(body, dict) and "comment" in body:
                        comment = str(body.get("comment") or "")
                    return finalize_pending_ban(conn, bid, comment)
                reason = body.get("reason") if isinstance(body, dict) and body.get("reason") is not None else row["reason"]
                comment = body.get("comment") if isinstance(body, dict) and "comment" in body else row["comment"]
                expired = row["expired_at"]
                if isinstance(body, dict) and "expired_at" in body:
                    expired = int(body.get("expired_at") or 0)
                elif isinstance(body, dict) and body.get("duration") is not None:
                    expired = parse_duration(body.get("duration"))
                ban_ip = row["ban_ip"]
                if isinstance(body, dict) and "ban_ip" in body:
                    ban_ip = 1 if body.get("ban_ip") else 0
                conn.execute(
                    "UPDATE bans SET reason = ?, comment = ?, expired_at = ?, ban_ip = ? WHERE id = ?",
                    (reason or row["reason"], comment or "", expired, ban_ip, bid),
                )
                updated = rowd(conn.execute("SELECT * FROM bans WHERE id = ?", (bid,)).fetchone())
                sid = str(updated.get("steam_id") or "")
                features.audit(conn, "ban.edit", {
                    "steam_id": sid,
                    "name": resolve_player_name(conn, sid, updated.get("steam_name") or ""),
                    "reason": updated.get("reason") or "",
                    "ban_id": int(updated["id"]),
                    "action": "edit",
                })
                frozen = features.freeze_actor(conn)
                features.notify_ban(conn,{"steam_id":sid,"name":updated.get("steam_name") or sid,"project_id":int(updated.get("project_id") or current_pid() or 0),"ban_id":int(updated["id"]),"admin_id":int(frozen.get("actor_user_id") or 0),"admin_name":frozen.get("actor_name") or "","comment":updated.get("comment") or "","expired_at":updated.get("expired_at") or 0,"action":"edit"},updated.get("reason") or "")
                return ban_view(conn, updated)

            return self._json(db_call(_edit))

        if path.startswith("/project/") and path.endswith("/clients"):
            parts = [p for p in path.strip("/").split("/") if p]
            pid = int(parts[1]) if len(parts) >= 2 and parts[1].isdigit() else 0
            if not pid and len(parts) >= 2:
                row = get_project_row(parts[1])
                pid = int(row.get("id") or 0) if row else 0
            if not pid:
                pid = int(current_pid() or features.request_project_id() or 0)
            payload = body if isinstance(body, dict) else {}
            nested_client = payload.get("client") if isinstance(payload.get("client"), dict) else {}
            raw_permissions = payload.get("permissions") if payload.get("permissions") not in (None, "") else nested_client.get("permissions")
            permissions = features.normalize_staff_permissions(raw_permissions)
            is_immutable = features.staff_payload_is_admin(raw_permissions, False, payload)
            if is_immutable:
                permissions = list(PERMISSIONS)

            def _save_client(conn):
                user = features.staff_resolve_user(conn, payload)
                uid = int((user or {}).get("id") or 0)
                result = features.staff_upsert(conn, pid, uid, permissions, is_immutable)
                return result

            out = db_call(_save_client)
            if isinstance(out, dict) and out.get("ok") is False:
                err = str(out.get("error") or "")
                if err == "staff-limit-exceeded":
                    status = 403
                elif err == "already_staff":
                    status = 409
                elif err == "user_not_found":
                    status = 404
                else:
                    status = 400
                # SPA still needs a membership object on some paths; never return {active,all} here.
                row = out.get("row")
                if isinstance(row, dict) and row.get("client"):
                    out.update(row)
                return self._json(out, status)
            row = out.get("row") if isinstance(out, dict) else None
            if isinstance(row, dict) and row.get("client"):
                return self._json(row)
            return self._json(out if isinstance(out, dict) else {"ok": True})

        if path.startswith("/project/") and path.endswith("/clients-settings"):
            parts = [p for p in path.strip("/").split("/") if p]
            pid = int(parts[1]) if len(parts) >= 2 and parts[1].isdigit() else 0
            if not pid and len(parts) >= 2:
                row = get_project_row(parts[1])
                pid = int(row.get("id") or 0) if row else 0
            payload = body if isinstance(body, dict) else {}

            def _save_settings(conn):
                twofa = payload.get("twofa_strict")
                if twofa is None:
                    twofa = payload.get("twofa_required")
                steam = payload.get("steam_strict")
                if steam is None:
                    steam = payload.get("steam_required")
                conn.execute(
                    "UPDATE project SET twofa_strict = ?, steam_strict = ? WHERE id = ?",
                    (1 if twofa else 0, 1 if steam else 0, pid),
                )
                features.audit(conn, "settings.edit", {"target": "clients-settings", "project_id": pid})
                row = conn.execute("SELECT * FROM project WHERE id = ?", (pid,)).fetchone()
                return project_obj(rowd(row) if row else {"id": pid})

            return self._json(db_call(_save_settings))

        return self._json({"ok": True})

    def api_delete(self, path, params, body):
        if path.startswith("/admin/api"):
            if admin_panel.handle_api(self, "DELETE", path, params, body):
                return
        self.bind_project()
        if path == "/auth/sessions" or path.startswith("/auth/sessions/") or path.startswith("/client/sessions"):
            self.bind_auth_user()
            uid = int(getattr(REQ, "user_id", 0) or features.request_user_id() or 0)
            if not uid:
                return self._json({"message": "unauthorized", "unauthorized": True}, 401)
            payload = body if isinstance(body, dict) else {}
            ip = str(payload.get("ip") or (params.get("ip") or [""])[0] or "").strip()
            ident = str(
                payload.get("id")
                or payload.get("key")
                or payload.get("serial")
                or (params.get("id") or params.get("key") or params.get("serial") or [""])[0]
                or ""
            ).strip()
            parts = [p for p in path.strip("/").split("/") if p]
            if not ident and len(parts) >= 3:
                ident = unquote(parts[-1])
            ident = ident.replace("client_serials:", "")
            if not ip and ident:
                prefix = f"{uid}-"
                if ident.startswith(prefix):
                    ip = ident[len(prefix):]
                elif ident.startswith("current-"):
                    ip = ident[len("current-"):]
                elif re.match(r"^\d{1,3}(?:\.\d{1,3}){3}$", ident):
                    ip = ident
            if not ip:
                return self._json({"ok": False, "message": "session.not.found"}, 400)
            current_ip = ""
            try:
                current_ip = str(admin_panel.client_ip(self) or "").strip()
            except Exception:
                current_ip = ""

            def _revoke(conn):
                if current_ip and ip == current_ip:
                    return {"ok": True, "revoked": "", "skipped_current": True}
                features.revoke_user_session(conn, uid, ip)
                features.audit(conn, "auth.session_revoke", {"user_id": uid, "ip": ip})
                return {"ok": True, "revoked": ip}

            return self._json(db_call(_revoke))
        if path == "/auth/steam-connect":
            self.bind_auth_user()
            uid = int(getattr(REQ, "user_id", 0) or features.request_user_id() or 0)
            if not uid:
                return self._json({"message": "unauthorized", "unauthorized": True}, 401)

            def _unlink(conn):
                conn.execute("UPDATE users SET steam_id = '' WHERE id = ?", (uid,))
                features.audit(conn, "auth.steam_disconnect", {"user_id": uid})
                return {"ok": True}

            return self._json(db_call(_unlink))
        if path == "/auth/discord-connect":
            self.bind_auth_user()
            uid = int(getattr(REQ, "user_id", 0) or features.request_user_id() or 0)
            if not uid:
                return self._json({"message": "unauthorized", "unauthorized": True}, 401)

            def _unlink(conn):
                conn.execute("UPDATE users SET discord_id = '' WHERE id = ?", (uid,))
                conn.execute(
                    "DELETE FROM settings WHERE key IN (?, ?, ?)",
                    (f"client_discord_name_{uid}", f"client_discord_avatar_{uid}", f"oauth_discord_id_{uid}"),
                )
                features.audit(conn, "auth.discord_disconnect", {"user_id": uid})
                return {"ok": True}

            return self._json(db_call(_unlink))
        if path == "/signage":
            payload = body if isinstance(body, dict) else {}
            net_id = str(payload.get("net_id") or payload.get("id") or (params.get("net_id") or [""])[0] or "")
            server_id = int(payload.get("server_id") or (params.get("server_id") or [0])[0] or 0)

            def _del_signage(conn):
                deleted = features.delete_signage_one(conn, net_id, server_id)
                if net_id:
                    enqueue("delete-entity", {"net_id": net_id}, conn=conn)
                    features.audit(conn, "signage.delete", {
                        "net_id": net_id,
                        "steam_id": deleted.get("steam_id") or "",
                        "server_id": int(deleted.get("server_id") or server_id or 1),
                    })
                return deleted

            return self._json(db_call(_del_signage))
        if path == "/plugin/signage":
            ids = (body or {}).get("net_ids") or (body or {}).get("ids") or params.get("net_ids") or []
            db_call(lambda c: features.delete_signage(c, ids))
            # Return net_ids so the SPA/mock can clear cards immediately
            return self._json({"ok": True, "net_ids": [str(x) for x in (ids or []) if str(x).strip()], "destroyed_at": now_ms()})
        if "/comments/" in path or "/notes/" in path:
            cid = path.rstrip("/").split("/")[-1]
            if str(cid).isdigit():
                db_call(lambda c: c.execute("DELETE FROM comments WHERE id = ?", (cid,)))
                return self._json({"ok": True, "id": int(cid), "deleted": True})
        if path.startswith("/project/") and ("/clients" in path) and "clients-settings" not in path:
            parts = [p for p in path.strip("/").split("/") if p]
            pid = int(parts[1]) if len(parts) >= 2 and parts[1].isdigit() else 0
            if not pid and len(parts) >= 2:
                row = get_project_row(parts[1])
                pid = int(row.get("id") or 0) if row else 0
            target = ""
            if len(parts) >= 4 and parts[2].startswith("client") and parts[3].isdigit():
                target = parts[3]
            target = target or (params.get("targetClientId") or params.get("target_client_id") or params.get("client_id") or params.get("clientId") or params.get("id") or [""])[0]
            if not target and isinstance(body, dict):
                nested = body.get("client") if isinstance(body.get("client"), dict) else {}
                target = body.get("targetClientId") or body.get("target_client_id") or body.get("client_id") or body.get("clientId") or body.get("id") or nested.get("id")
            try:
                client_id = int(target or 0)
            except Exception:
                client_id = 0

            def _del_client(conn):
                result = features.staff_remove(conn, pid, client_id)
                if isinstance(result, dict) and result.get("ok") is False:
                    return result
                return features.staff_list_payload(conn, pid, list(PERMISSIONS))

            out = db_call(_del_client)
            if isinstance(out, dict) and out.get("ok") is False:
                return self._json(out, 400)
            return self._json(out)
        # DELETE /server/{id} — remove paired server from project
        if path.startswith("/server/") or path.rstrip("/") in ("/server", "/servers"):
            parts = [p for p in path.strip("/").split("/") if p]
            sid = 0
            if len(parts) >= 2 and parts[1].isdigit():
                sid = int(parts[1])
            if not sid and isinstance(body, dict):
                try:
                    sid = int(body.get("id") or body.get("server_id") or 0)
                except Exception:
                    sid = 0
            if not sid:
                try:
                    sid = int((params.get("id") or params.get("server_id") or [0])[0] or 0)
                except Exception:
                    sid = 0

            def _del_server(conn):
                if not sid:
                    return {"ok": False, "message": "server id required"}
                row = rowd(conn.execute("SELECT * FROM servers WHERE id = ?", (sid,)).fetchone())
                if not row:
                    return {"ok": False, "message": "not found"}
                pid = current_pid() or 0
                row_pid = int(row.get("project_id") or 0)
                if pid and row_pid and row_pid != pid:
                    return {"ok": False, "message": "forbidden"}
                # Drop live presence for this server only
                try:
                    conn.execute("DELETE FROM online_players WHERE COALESCE(server_id, 0) = ?", (sid,))
                except Exception:
                    pass
                conn.execute("DELETE FROM servers WHERE id = ?", (sid,))
                try:
                    features.audit(conn, "server.delete", {
                        "server_id": sid,
                        "name": row.get("name") or row.get("hostname") or "",
                        "project_id": row_pid or pid,
                    })
                except Exception:
                    pass
                return {"ok": True, "id": sid, "deleted": True}

            out = db_call(_del_server)
            if not out.get("ok"):
                status = 404 if out.get("message") == "not found" else 400
                if out.get("message") == "forbidden":
                    status = 403
                return self._json(out, status)
            return self._json(out)

        if path.startswith("/project/") and path.count("/") == 2:
            key = path.split("/")[2]

            def _del(conn):
                row = None
                if key.isdigit():
                    row = rowd(conn.execute("SELECT * FROM project WHERE id = ?", (key,)).fetchone())
                if not row:
                    row = rowd(conn.execute("SELECT * FROM project WHERE domain = ? OR name = ?", (key, key)).fetchone())
                if not row:
                    return {"ok": False, "message": "not found"}
                pid = int(row["id"])
                conn.execute("DELETE FROM servers WHERE project_id = ?", (pid,))
                conn.execute("DELETE FROM pair_codes WHERE project_id = ?", (pid,))
                conn.execute("DELETE FROM online_players WHERE project_id = ?", (pid,))
                for table in (
                    "queue", "chat", "alerts", "checks", "bans", "reports", "mutes",
                    "comments", "kills", "bags", "bag_events", "audit", "player_sessions",
                ):
                    try:
                        conn.execute(f"DELETE FROM {table} WHERE project_id = ?", (pid,))
                    except Exception:
                        pass
                conn.execute("DELETE FROM project WHERE id = ?", (pid,))
                uid = int(row.get("owner_user_id") or 0)
                if uid:
                    features.sync_user_projects_blocked(conn, uid)
                # Do not recreate a shared default project after delete.
                features.audit(conn, "project.delete", {"id": pid, "domain": row.get("domain")})
                uid = int(features.request_user_id() or 0)
                if uid:
                    remaining = [
                        project_obj(rowd(r))
                        for r in conn.execute(
                            "SELECT * FROM project WHERE COALESCE(owner_user_id, 0) = ? ORDER BY id ASC",
                            (uid,),
                        ).fetchall()
                    ]
                else:
                    remaining = []
                return {
                    "ok": True,
                    "id": pid,
                    "deleted": True,
                    "deleted_id": pid,
                    "projects": remaining,
                    "data": remaining,
                    "results": remaining,
                }

            result = db_call(_del)
            if isinstance(result, dict) and result.get("message") == "not found":
                return self._json(result, 404)
            return self._json(result)
        if path.startswith("/player-mute/"):
            mid = path.split("/")[-1]
            if not str(mid).isdigit():
                return self._json({"ok": True, "computed_is_active": False, "deleted_at": now_ms()})

            def _um(conn):
                pid = current_pid() or 0
                row = rowd(conn.execute(
                    "SELECT * FROM mutes WHERE id = ?" + (" AND project_id = ?" if pid else " AND 0=1"),
                    (mid, pid) if pid else (mid,),
                ).fetchone())
                if not row:
                    return {"ok": False, "message": "not found"}
                deleted_at = now_ms()
                conn.execute("UPDATE mutes SET active = 0 WHERE id = ? AND project_id = ?", (mid, pid))
                frozen = features.freeze_actor(conn)
                staff = actor_client(conn, frozen.get("actor_name"), frozen.get("actor_user_id"), frozen)
                if row:
                    sid = str(row.get("steam_id") or "")
                    pname = resolve_player_name(conn, sid, sid)
                    conn.execute(
                        "UPDATE mutes SET active = 0 WHERE steam_id = ? AND project_id = ? AND active = 1",
                        (sid, pid),
                    )
                    announce = f"Игрок {pname} получил размут"
                    enqueue("mute", {
                        "steam_id": sid,
                        "name": pname,
                        "active": False,
                        "reason": "unmute",
                        "announce": True,
                        "initiator_name": frozen.get("actor_name") or "Admin",
                    }, conn=conn)
                    enqueue("chat-message", {
                        "initiator_name": frozen.get("actor_name") or "Admin",
                        "initiator_steam_id": "0",
                        "target_steam_id": None,
                        "message": announce,
                        "mode": "global",
                    }, conn=conn)
                    insert_chat(
                        conn, "project", frozen.get("actor_name") or "Admin", None, False,
                        announce, True,
                        project_id=pid or None,
                        actor_user_id=int(frozen.get("actor_user_id") or 0),
                        actor_name=str(frozen.get("actor_name") or "Admin"),
                        author_type="staff",
                    )
                    enqueue("chat-message", {
                        "initiator_name": frozen.get("actor_name") or "Admin",
                        "initiator_steam_id": "0",
                        "target_steam_id": sid,
                        "message": "Ваш мут был снят администратором.",
                        "mode": "direct",
                    }, conn=conn)
                    features.audit(conn, "mute.delete", {
                        "steam_id": sid,
                        "actor_user_id": frozen.get("actor_user_id"),
                        "actor_name": frozen.get("actor_name"),
                    })
                    try:
                        features.notify_mute(conn, {
                            "steam_id": sid,
                            "name": str(row.get("steam_id") or sid),
                            "admin_name": frozen.get("actor_name") or "",
                            "admin_id": frozen.get("actor_user_id") or 0,
                            "mute_id": int(mid),
                            "project_id": pid,
                        }, str(row.get("reason") or "Mute"), "", False)
                    except Exception as exc:
                        print("unmute notify failed", exc)
                    emit_realtime(pid, "mute.removed", {"playerId": sid, "actorId": frozen.get("actor_user_id")})
                    return {
                        "ok": True,
                        "id": int(mid),
                        "target_steam_id": sid,
                        "steam_id": sid,
                        "reason": row.get("reason") or "Mute",
                        "created_at": int(row.get("created_at") or 0),
                        "expired_at": int(row.get("expired_at") or 0),
                        "computed_is_active": False,
                        "active": False,
                        "deleted_at": deleted_at,
                        "client_id": int(staff.get("id") or 1),
                        "client": staff,
                        "initiator_client": staff,
                        "deleted_client_id": int(staff.get("id") or 1),
                        "target_player": player_view(conn, sid) if sid else None,
                    }
                return {
                    "ok": True,
                    "id": int(mid),
                    "computed_is_active": False,
                    "active": False,
                    "deleted_at": deleted_at,
                }

            return self._json(db_call(_um))
        if path == "/reports":
            rid = (params.get("report_id") or [None])[0]
            sid = (params.get("target_steam_id") or [None])[0]

            def _d(conn):
                clause, args = project_clause()
                if rid:
                    delete_reports(conn,"id = ?" + clause, [rid, *args])
                elif sid:
                    delete_reports(conn,"target_steam_id = ?" + clause, [sid, *args])

            db_call(_d)
            return self._json({"ok": True})
        if path == "/reports/all" or path == "/reports/all":
            db_call(lambda c: delete_reports(c,"1=1" + project_clause()[0], project_clause()[1]))
            return self._json({"ok": True})
        if path.startswith("/ban/"):
            bid = path.split("/")[-1]
            comment = ""
            if isinstance(body, dict):
                comment = str(body.get("comment") or "")
            if not comment:
                comment = str((params.get("comment") or [""])[0] or "")

            def _u(conn):
                return deactivate_ban(conn, bid, comment)

            return self._json(db_call(_u) or {"ok": True})
        if path.startswith("/check/"):
            cid = path.split("/")[2]
            body = body or {}
            status_in = str(body.get("status") or "")
            verdict_in = str(body.get("verdict") or body.get("reason") or body.get("comment") or "")
            is_ban = (
                "ban" in status_in.lower()
                or "ban" in verdict_in.lower()
                or bool(body.get("bans"))
            )
            is_cancel = "cancel" in status_in.lower() or "cancel" in verdict_in.lower()
            verdict_store = "Бан" if is_ban else ("Отмена" if is_cancel else "Чист")
            if verdict_in and verdict_in.lower() not in (
                "finishedclear", "finishedban", "canceled", "cancelled", "clear", "ban", "cancel", "finished"
            ):
                verdict_store = verdict_in
            finish = {"is_ban": is_ban, "is_cancel": is_cancel, "verdict": verdict_store}

            def _f(conn):
                row = rowd(conn.execute("SELECT * FROM checks WHERE id = ?", (cid,)).fetchone())
                if not row:
                    return None
                sid = str(row.get("steam_id") or "")
                existing_status = str(row.get("status") or "")
                if existing_status.lower() in ("ban", "finishedban") and not finish["is_cancel"]:
                    finish["is_ban"] = True
                    if str(finish["verdict"]) in ("Чист", "clear", "FinishedClear", ""):
                        finish["verdict"] = "Бан"
                if not finish["is_ban"] and not finish["is_cancel"] and sid:
                    started = int(row.get("started_at") or row.get("created_at") or 0)
                    try:
                        ban_row = conn.execute(
                            """SELECT created_at FROM bans
                               WHERE steam_id = ? AND active = 1 AND COALESCE(project_id, 0) = ?
                               ORDER BY id DESC LIMIT 1""",
                            (sid, int(row.get("project_id") or current_pid() or 0)),
                        ).fetchone()
                    except Exception:
                        ban_row = None
                    if ban_row:
                        ban_at = int(ban_row["created_at"] or 0)
                        if not started or ban_at >= max(0, started - 120000):
                            finish["is_ban"] = True
                            if str(finish["verdict"]) in ("Чист", "clear", "FinishedClear", ""):
                                finish["verdict"] = "Бан"
                local_ban = bool(finish["is_ban"])
                local_cancel = bool(finish["is_cancel"])
                local_verdict = str(finish["verdict"] or ("Бан" if local_ban else ("Отмена" if local_cancel else "Чист")))
                status = "ban" if local_ban else ("cancel" if local_cancel else "clear")
                conn.execute(
                    "UPDATE checks SET status = ?, finished_at = ?, notice = 0, verdict = ? WHERE id = ?",
                    (status, now_ms(), local_verdict, cid),
                )
                _activity_cache_drop(cid)
                release_check_freeze(conn,cid)
                updated = rowd(conn.execute("SELECT * FROM checks WHERE id = ?", (cid,)).fetchone())
                view = self._check_view(conn, updated)
                player = view.get("player") or {}
                sid = str(row.get("steam_id") or view.get("steam_id") or sid)
                frozen = features.freeze_actor(conn)
                staff = staff_brief(
                    conn,
                    actor_text=str(frozen.get("actor_name") or row.get("checker_name") or ""),
                    actor_id=int(frozen.get("actor_user_id") or row.get("checker_id") or 0),
                    payload=row,
                )
                features.notify_check(
                    conn,
                    {
                        "steam_id": sid,
                        "name": player.get("steam_name") or sid,
                        "avatar": player.get("steam_avatar") or "",
                        "check_id": int(cid) if str(cid).isdigit() else 0,
                        "checker_id": int(staff.get("id") or row.get("checker_id") or 0),
                        "checker_name": str(staff.get("name") or row.get("checker_name") or "Admin"),
                        "project_id": int(row.get("project_id") or 0),
                    },
                    "Проверка завершена",
                    "Бан" if local_ban else ("Отмена" if local_cancel else "Чист"),
                )
                features.audit(conn, "check.finished", {
                    "steam_id": sid,
                    "name": player.get("steam_name") or sid,
                    "status": status,
                    "verdict": local_verdict,
                    "is_ban": bool(local_ban),
                })
                already_ban = existing_status.lower() in ("ban", "finishedban")
                banned = []
                raw_bans = body.get("bans") if isinstance(body, dict) and isinstance(body.get("bans"), list) else []
                if local_ban and not raw_bans and not already_ban:
                    raw_bans = [{"steam_id": sid, "reason": str(body.get("comment") or local_verdict or "Ban")}]
                destroy_now = any_destroy_flag(body) if isinstance(body, dict) else False
                for item in raw_bans:
                    if not isinstance(item, dict):
                        continue
                    bid = str(item.get("steam_id") or item.get("target_steam_id") or sid)
                    reason = str(item.get("reason") or body.get("comment") or local_verdict or "Ban")
                    comment = str(item.get("comment") or body.get("comment") or "")
                    name = apply_player_ban(conn, bid, reason, comment, bool(item.get("ban_ip")), int(item.get("expired_at") or 0))
                    dest = destroy_now or any_destroy_flag(item)
                    banned.append({"steam_id": bid, "name": name, "reason": reason, "destroy_buildings": dest})
                    if dest:
                        enqueue("destroy_buildings", {"steam_id": bid}, conn=conn)
                view["bans"] = banned
                view["status"] = "FinishedBan" if local_ban else ("Canceled" if local_cancel else "FinishedClear")
                view["verdict"] = local_verdict
                try:
                    cleanup_reports_after_check(conn, sid)
                except Exception as exc:
                    print("cleanup reports after check failed", exc)
                try:
                    features.audit(conn, "check.finish_message", {
                        "steam_id": sid,
                        "name": player.get("steam_name") or sid,
                        "check_id": int(cid) if str(cid).isdigit() else cid,
                        "status": status,
                        "verdict": local_verdict,
                    })
                except Exception as exc:
                    print("check finish audit failed", exc)
                return view

            view = db_call(_f)
            is_ban = bool(finish.get("is_ban"))
            is_cancel = bool(finish.get("is_cancel"))
            if view:
                opts = court_options()
                sid = view.get("steam_id")
                enqueue("notice_set", {"steam_id": sid, "value": False})
                enqueue(
                    "check_finish",
                    {
                        "steam_id": sid,
                        "is_canceled": is_cancel,
                        "is_clear": not is_ban and not is_cancel,
                        "is_ban": is_ban,
                        "broadcast": bool(opts.get("check_finished_clear_broadcast")) if not is_ban else bool(opts.get("ban_broadcast")),
                    },
                )
                destroy_now = any_destroy_flag(body) if isinstance(body, dict) else False
                for item in view.get("bans") or []:
                    dest = bool(item.get("destroy_buildings")) or destroy_now
                    enqueue("ban", {
                        "steam_id": item.get("steam_id"),
                        "name": item.get("name"),
                        "reason": item.get("reason"),
                        "broadcast": bool(opts.get("ban_broadcast")),
                        "destroy_buildings": dest,
                    })
                    enqueue("kick", {"steam_id": item.get("steam_id"), "reason": item.get("reason") or "Ban", "announce": False})
                    if dest:
                        enqueue("destroy_buildings", {"steam_id": item.get("steam_id")})
                return self._json(view)
            return self._json({
                "ok": True,
                "status": "FinishedBan" if is_ban else ("Canceled" if is_cancel else "FinishedClear"),
            })
        return self._json({"ok": True})

    def _browse_players(self, params, full=True):
        def _b(conn):
            steam_ids = params.get("steam_ids") or params.get("steam_ids[]") or []
            status_raw = str(qfirst(params, "status", "player_status", "online_status") or "").strip().lower()
            online_flag = qbool(params, "online", "only_online", "online_only", default=None)
            offline_flag = qbool(params, "offline", default=None)
            online_only = False
            if online_flag is True or status_raw in ("online", "online_only", "only_online"):
                online_only = True
            elif online_flag is False and status_raw in ("offline",):
                online_only = False
            elif offline_flag is False:
                online_only = True
            elif status_raw in ("offline", "all"):
                online_only = False
            include_offline = not online_only
            q = str(qfirst(params, "search", "q") or "").lower()
            items = []
            ids = project_server_ids(conn)
            if steam_ids:
                for sid in steam_ids:
                    if not is_real_steam_id(sid):
                        continue
                    items.append(player_view(conn, sid, nest_team=bool(full)))
            elif include_offline:
                pid = current_pid()
                steam_seen = set()
                if ids:
                    marks = ",".join("?" * len(ids))
                    for row in conn.execute(
                        f"SELECT DISTINCT steam_id FROM player_sessions WHERE COALESCE(server_id, 1) IN ({marks}) OR COALESCE(project_id, 0) = ?",
                        [*ids, pid or 0],
                    ).fetchall():
                        steam_seen.add(row["steam_id"])
                if pid:
                    for table, col in (
                        ("chat", "steam_id"),
                        ("bans", "steam_id"),
                        ("checks", "steam_id"),
                        ("reports", "target_steam_id"),
                        ("mutes", "steam_id"),
                        ("online_players", "steam_id"),
                    ):
                        try:
                            for row in conn.execute(
                                f"SELECT DISTINCT {col} FROM {table} WHERE COALESCE(project_id, 0) = ?",
                                (pid,),
                            ).fetchall():
                                if row[0]:
                                    steam_seen.add(row[0])
                        except Exception:
                            pass
                for steam in list(steam_seen)[:400]:
                    if not is_real_steam_id(steam):
                        continue
                    items.append(player_view(conn, steam, nest_team=False))
            else:
                if not ids:
                    return browse([], params)
                marks = ",".join("?" * len(ids))
                for row in conn.execute(
                    f"SELECT steam_id FROM online_players WHERE COALESCE(server_id, 1) IN ({marks})",
                    ids,
                ).fetchall():
                    if not is_real_steam_id(row["steam_id"]):
                        continue
                    items.append(player_view(conn, row["steam_id"], nest_team=bool(full)))
            items = [
                p for p in items
                if is_real_steam_id(p.get("steam_id") or p.get("id"))
                and str(p.get("steam_name") or "").strip().lower() not in ("site", "project", "org")
            ]
            if online_only:
                live = {"online", "active", "afk", "joining", "queued", "unstable"}
                items = [p for p in items if str(p.get("status") or "").lower() in live]
            elif status_raw in ("offline",):
                items = [p for p in items if str(p.get("status") or "offline").lower() in ("offline", "")]
            if q:
                items = [p for p in items if q in (p.get("steam_name") or "").lower() or q in p.get("steam_id", "")]
            return browse(items, params)

        return db_call(_b)

    def _report_player(self, player) -> dict:
        if not isinstance(player, dict):
            player = {}
        sid = str(player.get("steam_id") or player.get("id") or "")
        name = str(player.get("steam_name") or player.get("name") or sid or ".")
        avatar = player.get("steam_avatar") or player.get("avatar") or PLACEHOLDER
        steam_data = player.get("steam_data") if isinstance(player.get("steam_data"), dict) else {}
        steam_data["steamid"] = str(steam_data.get("steamid") or sid)
        steam_data["personaname"] = str(steam_data.get("personaname") or name)
        steam_data["avatarfull"] = str(steam_data.get("avatarfull") or avatar)
        player["id"] = sid
        player["steam_id"] = sid
        player["steam_name"] = name
        player["name"] = name
        player["steam_avatar"] = avatar
        player["avatar"] = avatar
        player["steam_data"] = steam_data
        return player

    def _browse_reports(self, params):
        def _slim_player(conn, steam_id: str) -> dict:
            sid = str(steam_id or "")
            name = sid or "."
            avatar = PLACEHOLDER
            status = "offline"
            try:
                row = conn.execute(
                    "SELECT steam_name FROM players WHERE steam_id = ?",
                    (sid,),
                ).fetchone()
                if row:
                    name = str(row["steam_name"] or sid or ".")
            except Exception:
                pass
            try:
                ids = project_server_ids(conn)
                if sid and ids:
                    marks = ",".join("?" * len(ids))
                    if conn.execute(
                        f"SELECT 1 FROM online_players WHERE steam_id = ? AND COALESCE(server_id, 1) IN ({marks})",
                        [sid, *ids],
                    ).fetchone():
                        status = "online"
                elif sid and conn.execute(
                    "SELECT 1 FROM online_players WHERE steam_id = ?",
                    (sid,),
                ).fetchone():
                    status = "online"
            except Exception:
                pass
            try:
                cached = features.read_cache(conn, "steam_cache", "steam_id", sid)
                if isinstance(cached, dict) and cached.get("avatar"):
                    avatar = str(cached.get("avatar") or avatar)
                if isinstance(cached, dict) and cached.get("personaname") and (not name or name == sid):
                    name = str(cached.get("personaname") or name)
            except Exception:
                pass
            local_av = UPLOADS / f"steam-{sid}.jpg"
            if sid and local_av.exists() and local_av.stat().st_size > 200:
                avatar = f"/uploads/{local_av.name}"
            return {
                "id": sid,
                "steam_id": sid,
                "steam_name": name,
                "name": name,
                "steam_avatar": avatar,
                "avatar": avatar,
                "status": status,
                "online": status == "online",
                "is_online": status == "online",
                "team": [],
                "steam_data": {
                    "steamid": sid,
                    "personaname": name,
                    "avatarfull": avatar,
                    "avatar": avatar,
                },
            }

        def _item(conn, row):
            initiator = _slim_player(conn, row["initiator_steam_id"])
            victim = _slim_player(conn, row["target_steam_id"])
            kills = 0
            deaths = 0
            kd = 0.0
            victim["kd"] = kd
            victim["kdr"] = kd
            victim["kills"] = kills
            victim["deaths"] = deaths
            created = int(row["created_at"] or now_ms())
            try:
                srv = report_server_payload(conn, str(row["target_steam_id"] or ""), int(row["server_id"] or 0) if "server_id" in row.keys() else 0)
                server_id = int(srv.get("id") or 1) or 1
                server_name = str(srv.get("name") or "") or "Rust"
            except Exception:
                srv = {"id": 1, "name": "Rust", "hostname": "Rust"}
                server_id, server_name = 1, "Rust"
            return {
                "id": int(row["id"] or 0),
                "report_id": int(row["id"] or 0),
                "initiator_steam_id": str(row["initiator_steam_id"] or ""),
                "target_steam_id": str(row["target_steam_id"] or ""),
                "reason": str(row["reason"] or ""),
                "type": str(row["reason"] or ""),
                "message": str(row["message"] or ""),
                "comment": str(row["message"] or ""),
                "created_at": created,
                "initiator_player": initiator,
                "target_player": victim,
                "initiator": initiator,
                "target": victim,
                "author": initiator,
                "player": victim,
                "server_id": server_id,
                "server_name": server_name,
                "server": srv if isinstance(srv, dict) else {"id": server_id, "name": server_name, "hostname": server_name, "title": server_name, "label": server_name},
                "total_reports": 1,
                "total_reports_unique": 1,
                "active_check_id": 0,
                "kd": kd,
                "kda": kd,
                "kdr": kd,
                "kills": kills,
                "deaths": deaths,
                "deathes": deaths,
            }

        def _b(conn):
            try:
                prune_old_reports(conn)
            except Exception:
                pass
            items = []
            pclause, pargs = scoped_project_clause(conn, params)
            rows = conn.execute(
                "SELECT * FROM reports WHERE 1=1" + pclause + " ORDER BY id DESC LIMIT 400",
                pargs,
            ).fetchall()
            target = query_sid(params, "target_steam_id", "player_id", "steam_id", "suspect_steam_id")
            ignored = {}
            for row in rows:
                if target and str(row["target_steam_id"] or "") != str(target):
                    continue
                sid = str(row["target_steam_id"] or "")
                try:
                    if sid not in ignored:
                        ignored[sid] = int(features.ignore_reports_get(conn, sid) or 0)
                    if ignored[sid] > now_ms():
                        continue
                except Exception:
                    pass
                try:
                    items.append(_item(conn, row))
                except Exception as exc:
                    print("report row failed", row["id"], exc)

            if target:
                return browse(items, params)

            grouped = []
            by_target = {}
            for item in items:
                sid = str(item.get("target_steam_id") or "")
                if not sid:
                    grouped.append(item)
                    continue
                bucket = by_target.get(sid)
                if bucket is None:
                    reporters = {str(item.get("initiator_steam_id") or "")}
                    reasons = []
                    reason = str(item.get("reason") or "")
                    if reason:
                        reasons.append(reason)
                    item["total_reports"] = 1
                    item["total_reports_unique"] = 1
                    item["_reporters"] = reporters
                    item["_reasons"] = reasons
                    item["reports"] = [{
                        "id": item["id"],
                        "report_id": item["id"],
                        "initiator_steam_id": item["initiator_steam_id"],
                        "target_steam_id": item["target_steam_id"],
                        "reason": item["reason"],
                        "message": item["message"],
                        "created_at": item["created_at"],
                        "initiator_player": item["initiator_player"],
                        "server": item.get("server") or {"id": item.get("server_id") or 1, "name": ""},
                        "server_id": item.get("server_id") or 1,
                    }]
                    by_target[sid] = item
                    grouped.append(item)
                    continue
                bucket["total_reports"] = int(bucket.get("total_reports") or 1) + 1
                reporters = bucket.get("_reporters")
                if not isinstance(reporters, set):
                    reporters = set()
                    bucket["_reporters"] = reporters
                reporters.add(str(item.get("initiator_steam_id") or ""))
                bucket["total_reports_unique"] = max(1, len([x for x in reporters if x]))
                reasons = bucket.get("_reasons")
                if not isinstance(reasons, list):
                    reasons = []
                    bucket["_reasons"] = reasons
                reason = str(item.get("reason") or "")
                if reason and reason not in reasons:
                    reasons.append(reason)
                nested = bucket.get("reports")
                if not isinstance(nested, list):
                    nested = []
                    bucket["reports"] = nested
                nested.append({
                    "id": item["id"],
                    "report_id": item["id"],
                    "initiator_steam_id": item["initiator_steam_id"],
                    "target_steam_id": item["target_steam_id"],
                    "reason": item["reason"],
                    "message": item["message"],
                    "created_at": item["created_at"],
                    "initiator_player": item["initiator_player"],
                    "server": item.get("server") or bucket.get("server") or {"id": 1, "name": ""},
                    "server_id": item.get("server_id") or bucket.get("server_id") or 1,
                })

            for item in grouped:
                item.pop("_reporters", None)
                reasons = item.pop("_reasons", None)
                if isinstance(reasons, list) and reasons:
                    item["reason"] = ", ".join(reasons)
                    item["type"] = item["reason"]

            return browse(grouped, params)

        return db_call(_b)

    def _browse_bans(self, params):
        def _b(conn):
            ban_ids = [int(x) for x in param_values(params, "ban_ids", "id") if str(x).isdigit()]
            steam_ids = param_values(params, "steam_ids", "steam_id", "target_steam_id")
            search = str((params.get("search") or params.get("q") or [""])[0] or "").strip()
            foreign_pid = foreign_project_from_params(params)
            me = int(current_pid() or 0)
            sql = "SELECT * FROM bans"
            clauses = []
            args = []
            want_pids = []
            for raw in param_values(params, "project_ids"):
                try:
                    n = int(raw or 0)
                except Exception:
                    n = 0
                if n and n not in want_pids:
                    want_pids.append(n)
            asked_project_ids = params_have_key(params, "project_ids")
            if asked_project_ids and not want_pids:
                return browse([], params)
            if want_pids:
                allowed_foreign = set(features.subscribed_foreign_project_ids(conn) or [])
                allowed = []
                only_self = len(want_pids) == 1 and want_pids[0] == me
                for pid in want_pids:
                    if only_self and pid == me:
                        allowed.append(pid)
                    elif pid != me and pid in allowed_foreign:
                        allowed.append(pid)
                if not allowed:
                    return browse([], params)
                marks = ",".join("?" * len(allowed))
                clauses.append(f"COALESCE(project_id, 0) IN ({marks})")
                args.extend(allowed)
            elif foreign_pid and foreign_pid != me:
                allowed = set(features.subscribed_foreign_project_ids(conn) or [])
                if foreign_pid not in allowed:
                    return browse([], params)
                clauses.append("COALESCE(project_id, 0) = ?")
                args.append(foreign_pid)
            else:
                pclause, pargs = project_clause()
                clauses.append(pclause.replace(" AND ", "", 1) if pclause.startswith(" AND ") else pclause.strip())
                args.extend(pargs)
            if ban_ids:
                marks = ",".join("?" * len(ban_ids))
                clauses.append(f"id IN ({marks})")
                args.extend(ban_ids)
            if steam_ids:
                marks = ",".join("?" * len(steam_ids))
                clauses.append(f"steam_id IN ({marks})")
                args.extend(steam_ids)
            if search:
                clauses.append("(reason LIKE ? OR comment LIKE ? OR steam_id LIKE ? OR IFNULL(steam_name,'') LIKE ?)")
                needle = f"%{search}%"
                args.extend([needle, needle, needle, needle])
            clauses.append("COALESCE(pending, 0) = 0")
            clauses = [c for c in clauses if c]
            if clauses:
                sql += " WHERE " + " AND ".join(clauses)
            sql += " ORDER BY id DESC LIMIT 80"
            items = []
            for row in conn.execute(sql, args).fetchall():
                try:
                    items.append(ban_view(conn, row))
                except Exception as exc:
                    print("ban row failed", getattr(row, "id", None), type(exc).__name__, exc)
            if ban_ids:
                by_id = {int(item["id"]): item for item in items if item.get("id") is not None}
                items = [by_id[bid] for bid in ban_ids if bid in by_id]
            return browse(items, params)

        try:
            return db_call(_b)
        except Exception as exc:
            print("browse bans failed", type(exc).__name__, exc)
            return browse([], params)

    def _check_view(self, conn, row, brief=False):
        if not row:
            return {}
        raw = row["status"] or "active"
        status_map = {
            "active": "Pending",
            "started": "Pending",
            "Started": "Pending",
            "Pending": "Pending",
            "finished": "FinishedClear",
            "clear": "FinishedClear",
            "FinishedClear": "FinishedClear",
            "ban": "FinishedBan",
            "FinishedBan": "FinishedBan",
            "cancel": "Canceled",
            "canceled": "Canceled",
            "Cancelled": "Canceled",
            "Canceled": "Canceled",
        }
        status = status_map.get(raw, "Pending" if not row["finished_at"] else "FinishedClear")
        if status == "FinishedBan":
            verdict_label = "Бан"
        elif status == "Canceled":
            verdict_label = "Отмена"
        elif status == "Pending":
            verdict_label = "На проверке"
        else:
            verdict_label = "Чист"
        stored_verdict = str(row["verdict"] or "").strip()
        if stored_verdict.lower() in ("", "clear", "finishedclear", "finished", "ban", "finishedban", "cancel", "canceled", "cancelled"):
            display_verdict = "" if status == "Pending" else verdict_label
        else:
            display_verdict = stored_verdict
        sid = str(row["steam_id"] or "")
        stored_name = str((row["steam_name"] if "steam_name" in row.keys() else "") or sid or "")
        player = None
        if brief:
            # The checks table needs only its row identity.  Building a full
            # player card for every one of 60 rows was the main reason all
            # navigation tabs waited on the database.
            player = player_brief_for_ban(conn, sid) if sid else {}
            player["id"] = sid
            player["steam_name"] = player.get("steam_name") or stored_name or sid
            player["name"] = player.get("name") or player["steam_name"]
        elif sid:
            try:
                player = player_view(conn, sid, nest_team=False, allow_refresh=False)
            except Exception:
                player = None
        if not isinstance(player, dict):
            player = player_details_safe(sid, stored_name or sid)["player"]
        player = ensure_player_shape(player, sid, stored_name)
        player["steam_id"] = sid
        player["steam_name"] = player.get("steam_name") or player.get("name") or stored_name or sid
        player["name"] = player.get("name") or player["steam_name"]
        if not isinstance(player.get("team"), list):
            player["team"] = []
        checker_id = 0
        try:
            checker_id = int(row["checker_id"] or 0) if "checker_id" in row.keys() else 0
        except Exception:
            checker_id = 0
        checker_name = row["checker_name"] if "checker_name" in row.keys() else ""
        checker_email = row["checker_email"] if "checker_email" in row.keys() else ""
        checker_id, checker_name, checker_email, checker_role = resolved_staff_snapshot(
            conn, checker_name, checker_id, checker_email, "",
            row["project_id"] if "project_id" in row.keys() else current_pid() or 0,
        )
        checker = mark_staff_moderator(staff_brief(conn, checker_name, checker_id, {
            "actor_name": checker_name, "actor_email": checker_email, "actor_role": checker_role, "actor_user_id": checker_id,
        }))
        if checker_name and not features.is_generic_staff_label(checker_name):
            checker["name"] = checker_name
        live_tag = features.staff_public_tag(features.user_by_id(conn, checker_id) if checker_id else None, checker.get("name") or "", conn)
        if live_tag:
            checker["tag"] = live_tag
        checker["id"] = stable_client_id(checker_id, checker_name or checker.get("name") or "")
        if not checker["id"] and checker.get("name"):
            checker["id"] = stable_client_id(0, str(checker.get("name")))
        checker["status"] = "online"
        checker["online"] = True
        checker["is_online"] = True
        checker["steam_id"] = ""
        checker["steam"] = features.empty_steam_profile(PLACEHOLDER)
        checker["permissions"] = checker.get("permissions") if isinstance(checker.get("permissions"), list) else []
        cid = int(checker.get("id") or checker_id or 0)
        player_team = player.get("team") if isinstance(player.get("team"), list) else []
        if not isinstance(player.get("team"), list):
            player["team"] = []
        suspect_team = []
        for mate in player_team:
            if isinstance(mate, dict):
                mate_sid = str(mate.get("steam_id") or mate.get("id") or "").strip()
            else:
                mate_sid = str(mate or "").strip()
            if mate_sid and mate_sid not in suspect_team:
                suspect_team.append(mate_sid)
        srv = report_server_payload(conn, sid)
        return {
            "id": row["id"],
            "steam_id": sid,
            "status": status,
            "state": status,
            "contact": row["contact"] or "",
            "started_at": row["started_at"],
            "created_at": row["started_at"],
            "finished_at": row["finished_at"],
            "verdict": display_verdict,
            "verdict_label": verdict_label,
            "status_label": verdict_label,
            "result": display_verdict or verdict_label,
            "target_player": player,
            "player": player,
            "suspect": player,
            "checker": checker,
            "moderator": checker,
            "moderator_player": checker,
            "initiator_client": checker,
            "created_by": checker,
            "client": checker,
            "client_id": cid,
            "checker_id": cid,
            "initiator_client_id": cid,
            "server_id": int((srv or {}).get("id") or 1) or 1,
            "server": srv,
            "notice": bool(row["notice"]) if "notice" in row.keys() else False,
            "notice_state": bool(row["notice"]) if "notice" in row.keys() else False,
            "discord": row["contact"] or "",
            "discord_contact": row["contact"] or "",
            "reports": [],
            "activity": [],
            "messages": [],
            "commands": [],
            "team": player_team,
            "suspect_team": suspect_team,
            "team_steam_ids": suspect_team,
        }

    def _bag_player(self, conn, steam_id: str):
        sid = str(steam_id or "").strip()
        if not sid or sid in ("0", "None"):
            return None
        player = player_brief_for_ban(conn, sid)
        name = resolve_player_name(conn, sid, str(player.get("steam_name") or player.get("name") or sid))
        player["id"] = sid
        player["steam_id"] = sid
        player["steam_name"] = name
        player["name"] = name
        player["display_name"] = name
        player["exists"] = True
        player["found"] = True
        player["unknown"] = False
        if not isinstance(player.get("team"), list):
            player["team"] = []
        player["steam_id"] = sid
        return player

    def _check_activity(self, conn, cid) -> list:
        check = None
        if str(cid).isdigit():
            check = rowd(conn.execute("SELECT * FROM checks WHERE id = ?", (cid,)).fetchone())
        if not check:
            check = {}
        try:
            cpid = int(check.get("project_id") or 0)
            if cpid:
                features.set_request_project(cpid)
                REQ.project_id = cpid
        except Exception:
            pass
        pid = int(check.get("project_id") or current_pid() or 0)
        sid = str(check.get("steam_id") or "")
        check_id = int(check.get("id") or 0)
        items = []
        if not check_id:
            return items
        player = activity_player_brief(conn, sid) if sid else {
            "steam_id": sid or "0",
            "steam_name": str(check.get("steam_name") or sid or "Unknown"),
            "name": str(check.get("steam_name") or sid or "Unknown"),
            "team": [],
        }
        if check.get("steam_name") and (not player.get("steam_name") or player.get("steam_name") == sid):
            player["steam_name"] = str(check.get("steam_name"))
            player["name"] = player["steam_name"]
        checker_id = int(check.get("checker_id") or 0)
        checker_name = str(check.get("checker_name") or "")
        checker_email = str(check.get("checker_email") or "")
        checker_id, checker_name, checker_email, checker_role = resolved_staff_snapshot(
            conn, checker_name, checker_id, checker_email, "", check.get("project_id") or current_pid() or 0,
        )
        staff = mark_staff_moderator(staff_brief(conn, checker_name, checker_id, {
            "actor_name": checker_name, "actor_email": checker_email, "actor_role": checker_role, "actor_user_id": checker_id,
        }))
        if checker_name and not features.is_generic_staff_label(checker_name):
            staff["name"] = checker_name
        staff["id"] = stable_client_id(checker_id or staff.get("id"), staff.get("name") or checker_name)
        staff["status"] = "online"
        staff["online"] = True
        staff["is_online"] = True
        started_at = int(check.get("started_at") or 0) or now_ms()
        staff_by_id = {}

        def _staff_row(uid, name):
            key = (int(uid or 0), str(name or ""))
            if key not in staff_by_id:
                staff_by_id[key] = staff_brief(conn, name, uid, {
                    "actor_name": name, "actor_user_id": uid,
                })
            return dict(staff_by_id[key])

        items.append({
            "id": "started-%s" % check_id,
            "M_ID": check_id,
            "check_id": int(check_id),
            "checkId": int(check_id),
            "type": "Started",
            "kind": "Started",
            "created_at": started_at,
            "meta": {"client_id": staff["id"], "steam_id": sid, "actor_name": staff.get("name") or checker_name},
            "player": player,
            "initiator_player": player,
            "target_player": player,
            "initiator_client": staff,
        })
        contact_text = str(check.get("contact") or "").strip()
        contact_logged = False
        notice_rows = conn.execute(
            """SELECT * FROM audit WHERE event IN ('check.notice', 'check.freeze')
               AND created_at >= ? AND (json_extract(payload,'$.check_id') = ? OR (json_extract(payload,'$.check_id') IS NULL AND json_extract(payload,'$.steam_id') = ?)) ORDER BY id ASC LIMIT 1000""",
            (int(started_at or 0) - 5000, int(check_id), sid),
        ).fetchall()
        for row in notice_rows:
            try:
                payload = json.loads(row["payload"] or "{}")
            except Exception:
                payload = {}
            if row["event"] == "check.freeze" and int(payload.get("project_id") or 0) != int(pid or 0):
                continue
            cid_match = str(payload.get("check_id") or "")
            sid_match = str(payload.get("steam_id") or "")
            if cid_match and cid_match != str(check_id):
                continue
            if sid_match and sid_match != sid:
                continue
            if not cid_match and not sid_match:
                continue
            if row["event"] == "check.freeze":
                items.append(check_freeze_chat_item(conn,row,check_id,sid,payload))
                continue
            active = bool(payload.get("active"))
            created = int(row["created_at"] or now_ms())
            if row["event"] == "check.notice" and not active and started_at and abs(created - started_at) < 3000:
                continue
            items.append({
                "id": "notice-%s" % row["id"],
                "M_ID": int(row["id"] or 0),
                "check_id": int(check_id),
                "checkId": int(check_id),
                "type": "FreezeChanged" if row["event"] == "check.freeze" else "NoticeChanged",
                "kind": "FreezeChanged" if row["event"] == "check.freeze" else "NoticeChanged",
                "created_at": created,
                "meta": {
                    "active": active,
                    "action": "freeze" if row["event"] == "check.freeze" else "notice",
                    "client_id": int(payload.get("client_id") or staff["id"]),
                    "steam_id": sid,
                    "error": False,
                },
                "player": player,
                "initiator_player": player,
                "target_player": player,
                "initiator_client": staff,
            })
        if sid:
            rows = []
            seen_chat = set()
            def _add_chat_rows(extra):
                for r in extra or []:
                    try:
                        rid = int(r["id"] or 0)
                    except Exception:
                        rid = 0
                    if rid and rid in seen_chat:
                        continue
                    if rid:
                        seen_chat.add(rid)
                    rows.append(r)
            try:
                _add_chat_rows(conn.execute(
                    """SELECT * FROM chat
                       WHERE COALESCE(check_id, 0) = ? AND COALESCE(project_id,0) = ?
                       ORDER BY id ASC LIMIT 400""",
                    (int(check_id), int(pid or 0)),
                ).fetchall())
            except Exception:
                pass
            # Legacy untagged direct messages only, inside this check's lifetime.
            try:
                _add_chat_rows(conn.execute(
                    """SELECT * FROM chat WHERE COALESCE(check_id,0)=0
                       AND COALESCE(project_id,0)=?
                       AND (steam_id=? OR target_steam_id=?)
                       AND created_at>=? AND created_at<=?
                       ORDER BY id ASC LIMIT 400""",
                    (int(pid or 0), sid, sid, int(started_at or 0), int(check.get("finished_at") or now_ms())),
                ).fetchall())
            except Exception:
                pass
            rows.sort(key=lambda r: int(r["id"] or 0))
        else:
            rows = []
        for row in rows:
            author_sid = str(row["steam_id"] or "")
            from_site = chat_flag(row, "from_site") or author_sid in ("site", "project", "org", "0", "admin")
            target_sid = str(row["target_steam_id"] or "")
            row_check = 0
            try:
                if "check_id" in row.keys():
                    row_check = int(row["check_id"] or 0)
            except Exception:
                row_check = 0
            if row_check and row_check != int(check_id):
                continue
            if from_site:
                if target_sid and target_sid != sid:
                    continue
            elif author_sid not in (sid, "") and target_sid != sid:
                continue
            stored_actor_id = 0
            stored_actor_name = ""
            try:
                if "actor_user_id" in row.keys():
                    stored_actor_id = int(row["actor_user_id"] or 0)
            except Exception:
                stored_actor_id = 0
            try:
                if "actor_name" in row.keys():
                    stored_actor_name = str(row["actor_name"] or "")
            except Exception:
                stored_actor_name = ""
            if from_site:
                if author_sid in ("project", "org"):
                    author = project_chat_client(conn, pid, stored_actor_name and row["steam_name"] or "")
                    author["actor_user_id"] = stored_actor_id
                    author["actor_name"] = stored_actor_name
                    staff_client_id = int(author["id"])
                else:
                    author = mark_staff_moderator(_staff_row(stored_actor_id, stored_actor_name))
                    if stored_actor_name:
                        author["name"] = stored_actor_name
                        author["steam_name"] = stored_actor_name
                    author["steam_name"] = author.get("name") or stored_actor_name or author.get("steam_name") or ""
                typ = "MessageFromModerator"
                channel = "direct" if target_sid else "global"
            else:
                author_name = str(row["steam_name"] or author_sid or sid or "")
                author = {
                    "steam_id": str(author_sid or sid or "0"),
                    "steam_name": author_name,
                    "name": author_name,
                    "team": [],
                }
                typ = "MessageFromPlayer"
                channel = "team" if chat_flag(row, "is_team") else ("direct" if target_sid else "global")
            if not isinstance(author.get("team"), list):
                author["team"] = []
            text = row["text"] or ""
            created = int(row["created_at"] or now_ms())
            if started_at and created < started_at - 5000:
                continue
            finished_at = 0
            try:
                finished_at = int(check.get("finished_at") or 0)
            except Exception:
                finished_at = 0
            if finished_at and created > finished_at + 1500:
                continue
            low = str(text or "").strip().lower()
            # Skip fake finish chat bubbles — system Finished activity already covers this
            if low.startswith("проверка завершена") or low.startswith("check finished") or low.startswith("check completed"):
                continue
            is_contact = False
            related = []
            if not from_site and (low.startswith("/contact") or low.startswith("contact ")):
                is_contact = True
                contact_logged = True
            staff_client_id = 0
            try:
                staff_client_id = int((author or {}).get("id") or stored_actor_id or 0)
            except Exception:
                staff_client_id = int(stored_actor_id or 0)
            if from_site:
                staff_client_id = stable_client_id(staff_client_id, stored_actor_name or author.get("name"))
                author["id"] = staff_client_id
            items.append({
                "id": "chat-%s" % row["id"],
                "M_ID": int(row["id"] or 0),
                "check_id": int(check_id),
                "checkId": int(check_id),
                "type": typ,
                "kind": typ,
                "text": text,
                "message": text,
                "created_at": int(row["created_at"] or now_ms()),
                "meta": {
                    "text": text,
                    "message": text,
                    "is_contact": is_contact,
                    "related_players": related if is_contact else [],
                    "matches": related if is_contact else [],
                    "match": bool(related),
                    "steam_id": str(author.get("steam_id") or author_sid or sid or "0"),
                    "client_id": staff_client_id if from_site else 0,
                    "channel": channel,
                    "author_name": stored_actor_name or author.get("name") or "",
                    "actor_name": stored_actor_name or author.get("name") or "",
                },
                "player": author,
                "initiator_player": author,
                "target_player": player,
                "initiator_client": author if from_site else {
                    "id": 0,
                    "steam_id": str(author.get("steam_id") or author_sid or "0"),
                    "name": author.get("steam_name") or author.get("name") or "",
                    "status": "offline",
                },
                "from_site": from_site,
            })
        if contact_text and not contact_logged:
            items.append(check_contact_activity_item(
                check_id, sid, player.get("steam_name") or sid, contact_text, player, [], started_at + 1,
            ))
        try:
            append_check_game_events(conn, check, sid, check_id, player, staff, items)
        except Exception as exc:
            print("check game events failed", check_id, type(exc).__name__, exc)
        if check.get("finished_at"):
            raw_status = str(check.get("status") or check.get("verdict") or "")
            finish_map = {
                "ban": "FinishedBan",
                "FinishedBan": "FinishedBan",
                "clear": "FinishedClear",
                "finished": "FinishedClear",
                "FinishedClear": "FinishedClear",
                "cancel": "Canceled",
                "canceled": "Canceled",
                "Cancelled": "Canceled",
                "Canceled": "Canceled",
            }
            finish_status = finish_map.get(raw_status, "")
            low = raw_status.lower()
            if "ban" in low or raw_status == "Бан":
                finish_status = "FinishedBan"
            elif "cancel" in low or raw_status == "Отмена":
                finish_status = "Canceled"
            elif not finish_status:
                finish_status = "FinishedClear"
            verdict_text = str(check.get("verdict") or "")
            if finish_status == "FinishedBan":
                verdict_text = verdict_text if verdict_text and verdict_text not in ("FinishedBan", "ban") else "Бан"
            elif finish_status == "Canceled":
                verdict_text = verdict_text if verdict_text and "cancel" not in verdict_text.lower() else "Отмена"
            else:
                verdict_text = verdict_text if verdict_text and "finished" not in verdict_text.lower() and verdict_text != "clear" else "Чист"
            items.append({
                "id": "finished-%s" % check_id,
                "M_ID": check_id,
                "check_id": int(check_id),
                "checkId": int(check_id),
                "type": "Finished",
                "kind": "Finished",
                "created_at": int(check.get("finished_at") or now_ms()),
                "meta": {
                    "status": finish_status,
                    "verdict": verdict_text,
                    "steam_id": sid,
                    "client_id": staff["id"],
                },
                "player": player,
                "initiator_player": player,
                "target_player": player,
                "initiator_client": staff,
            })
        items.sort(key=lambda x: x.get("created_at") or 0)
        return items

    def _post_check_activity(self, path, body) -> list:
        cid = path.split("/")[2]
        payload = body if isinstance(body, dict) else {}
        text = str(payload.get("text") or payload.get("message") or payload.get("content") or "").strip()
        if not text:
            return db_call(lambda c: self._check_activity(c, cid))

        def _save(conn):
            pid = current_pid() or 0
            check = None
            uid = 0
            try:
                uid = int(features.request_user_id() or 0)
            except Exception:
                uid = 0
            if str(cid).isdigit():
                found = rowd(conn.execute("SELECT * FROM checks WHERE id = ?", (cid,)).fetchone())
                if found:
                    cpid = 0
                    try:
                        cpid = int(found.get("project_id") or 0)
                    except Exception:
                        cpid = 0
                    prow = rowd(conn.execute("SELECT * FROM project WHERE id = ?", (cpid,)).fetchone()) if cpid else None
                    if cpid and prow and user_can_access_project(conn, prow, uid):
                        pid = cpid
                        features.set_request_project(pid)
                        try:
                            REQ.project_id = pid
                        except Exception:
                            pass
                        check = found
                    elif pid and cpid == pid:
                        check = found
            if not check and pid and str(cid).isdigit():
                check = rowd(conn.execute(
                    "SELECT * FROM checks WHERE id = ? AND COALESCE(project_id, 0) = ?",
                    (cid, pid),
                ).fetchone())
            if not check:
                check = {}
            sid = str(payload.get("target_steam_id") or payload.get("steam_id") or check.get("steam_id") or "") or None
            staff = features.freeze_actor(conn)
            actor_id = int(staff.get("actor_user_id") or 0)
            actor_name = str(staff.get("actor_name") or "Admin")
            proj_name = project_title(conn)
            mid = insert_chat(conn, "site", actor_name, sid, False, text, True, actor_user_id=actor_id, actor_name=actor_name, check_id=int(check.get("id") or 0) or (int(cid) if str(cid).isdigit() else 0)) or 0
            if sid:
                features.audit(conn, "chat.direct", {
                    "steam_id": sid,
                    "name": sid,
                    "message": text,
                    "channel": "direct",
                    "from_site": True,
                    "source": "site",
                    "author_type": "staff",
                })
                enqueue(
                    "chat-message",
                    {
                        "initiator_name": actor_name or proj_name,
                        "initiator_steam_id": "0",
                        "target_steam_id": sid,
                        "message": text,
                        "mode": "direct",
                    },
                    conn=conn,
                )
            check_id = int(check.get("id") or 0) or (int(cid) if str(cid).isdigit() else 0)
            author = staff_brief(conn, actor_name, actor_id, {
                "actor_name": actor_name, "actor_user_id": actor_id,
            })
            author["name"] = actor_name
            author["id"] = stable_client_id(actor_id or author.get("id"), actor_name)
            author["status"] = "online"
            author = mark_staff_moderator(author)
            player = {
                "steam_id": str(sid or "0"),
                "steam_name": str((check.get("steam_name") if check else "") or sid or ""),
                "name": str((check.get("steam_name") if check else "") or sid or ""),
                "team": [],
            }
            if not isinstance((player or {}).get("team"), list) and isinstance(player, dict):
                player["team"] = []
            item = {
                "id": "chat-%s" % (mid or now_ms()),
                "M_ID": int(mid or 0),
                "check_id": int(check_id),
                "checkId": int(check_id),
                "type": "MessageFromModerator",
                "kind": "MessageFromModerator",
                "text": text,
                "message": text,
                "created_at": now_ms(),
                "meta": {
                    "text": text,
                    "message": text,
                    "client_id": int(author.get("id") or 0),
                    "steam_id": str(sid or "0"),
                    "channel": "direct" if sid else "global",
                    "author_name": actor_name,
                    "actor_name": actor_name,
                },
                "player": author,
                "initiator_player": author,
                "target_player": player,
                "initiator_client": author,
                "from_site": True,
            }
            return [item]

        items = db_call(_save)
        try:
            drop_id = cid
            if isinstance(items, list) and items:
                drop_id = items[0].get("check_id") or cid
            _activity_cache_drop(drop_id)
        except Exception:
            pass
        if isinstance(items, list) and len(items) > 40:
            return items[-40:]
        return items

    def _browse_checks(self, params):
        def _b(conn):
            sid = query_sid(params, "steam_id", "player_id", "target_steam_id", "suspect_steam_id")
            exclude_sid = query_sid(params, "exclude_steam_id", "exclude_steam")
            contact_raw = str(qfirst(params, "contact", "contacts", "discord") or "").strip()
            has_contact = any(
                key in (params or {})
                for key in ("contact", "contacts", "discord", "contact[]", "contacts[]")
            )
            contact_key = features.contact_lookup_key(contact_raw) if contact_raw else ""
            if has_contact and not contact_key:
                return browse([], params)
            items = []
            seen_steam = set()
            pclause, pargs = scoped_project_clause(conn, params)
            for row in conn.execute(
                "SELECT * FROM checks WHERE 1=1" + pclause + " ORDER BY id DESC LIMIT 60",
                pargs,
            ).fetchall():
                row_sid = str(row["steam_id"] or "")
                if sid and row_sid != sid:
                    continue
                if exclude_sid and row_sid == exclude_sid:
                    continue
                if contact_key:
                    other = features.normalize_contact(row["contact"] or "")
                    if other != contact_key:
                        continue
                    if row_sid in seen_steam:
                        continue
                    seen_steam.add(row_sid)
                items.append(self._check_view(conn, row, brief=True))
            return browse(items, params)

        return db_call(_b)

    def _browse_alerts(self, params):
        # Only SPA-safe types. contact/custom_api render as empty skeleton rows.
        allowed = {
            "dug_up_stash", "join_with_ip_ban", "join_with_external_ban", "detect_ra_ban",
            "vpn_detected", "license_changed", "auto_kick",
        }

        def _b(conn):
            items = []
            want = params.get("type") or params.get("type[]") or []
            if isinstance(want, str):
                want = [want]
            want = [str(x) for x in want if str(x).strip()]
            sid = query_sid(params, "steam_id", "player_id", "target_steam_id")
            pclause, pargs = scoped_project_clause(conn, params)
            for row in conn.execute(
                "SELECT * FROM alerts WHERE 1=1" + pclause + " ORDER BY id DESC LIMIT 80",
                pargs,
            ).fetchall():
                try:
                    payload = json.loads(row["payload"] or "{}")
                except Exception:
                    payload = {}
                if not isinstance(payload, dict):
                    payload = {"value": payload}
                typ = str(row["type"] or "")
                # Contact belongs in check chat; custom_api has no reliable SPA template
                if typ in ("contact", "custom", "custom_api"):
                    continue
                if typ not in allowed:
                    continue
                if want and typ not in want and "all" not in want:
                    continue
                steam = str(row["steam_id"] or payload.get("steam_id") or payload.get("target_steam_id") or "")
                if not steam or not steam.isdigit() or len(steam) < 15:
                    continue
                if sid and steam != str(sid):
                    continue
                player = player_brief_for_ban(conn, steam)
                if not player or not player.get("steam_id"):
                    continue
                pretty = resolve_player_name(conn, steam, player.get("steam_name") or "")
                # "." / empty / steamid-as-name → use short id so SPA templates are not blank
                if not pretty or pretty.strip() in (".", "-", "—") or pretty == steam:
                    pretty = "Игрок " + steam[-4:]
                player["steam_name"] = pretty
                player["name"] = pretty
                player["display_name"] = pretty
                if isinstance(player.get("steam_data"), dict):
                    player["steam_data"]["personaname"] = pretty
                if not player.get("steam_avatar"):
                    player["steam_avatar"] = PLACEHOLDER
                # Keep relative /local and /uploads — absolute 127.0.0.1 breaks on domain/HTTPS
                av = str(player.get("steam_avatar") or "")
                if av.startswith("http://127.0.0.1") or av.startswith("https://127.0.0.1"):
                    try:
                        from urllib.parse import urlparse
                        av = urlparse(av).path or PLACEHOLDER
                    except Exception:
                        av = PLACEHOLDER
                    player["steam_avatar"] = av
                player["avatar"] = player.get("steam_avatar")
                player["status"] = player.get("status") or "offline"
                player["online"] = player.get("status") in ("online", "active", "joining", "queued", "afk")
                player["is_online"] = bool(player.get("online"))
                if not isinstance(player.get("steam_data"), dict):
                    player["steam_data"] = {}
                player["steam_data"]["personaname"] = player.get("steam_name")
                player["steam_data"]["avatarfull"] = player.get("steam_avatar")
                player["steam_data"]["avatar"] = player.get("steam_avatar")
                meta = dict(payload)
                meta["steam_id"] = steam
                meta["player"] = player
                meta.setdefault("ip", str(player.get("ip") or payload.get("ip") or ""))
                # Always provide bans array — SPA does meta.bans.some(...) for detect_ra_ban
                if not isinstance(meta.get("bans"), list):
                    meta["bans"] = []
                if typ == "detect_ra_ban":
                    bans = []
                    for brow in conn.execute(
                        "SELECT * FROM bans WHERE steam_id = ? AND active = 1 ORDER BY id DESC LIMIT 5",
                        (steam,),
                    ).fetchall():
                        bans.append(ban_view(conn, brow))
                    if not bans:
                        fake = {
                            "id": int(row["id"] or 0),
                            "steam_id": steam,
                            "steam_name": player.get("steam_name") or steam,
                            "reason": str(payload.get("reason") or meta.get("reason") or "Ban"),
                            "comment": str(payload.get("comment") or payload.get("reason") or "Ban"),
                            "ip": str(meta.get("ip") or ""),
                            "ban_ip": 0,
                            "created_at": int(row["created_at"] or now_ms()),
                            "expired_at": 0,
                            "active": 1,
                        }
                        bans.append(ban_view(conn, fake))
                    meta["bans"] = bans
                    meta["ban"] = bans[0] if bans else None
                    meta["ban_id"] = int((bans[0] or {}).get("id") or row["id"] or 0) if bans else int(row["id"] or 0)
                    ban0 = bans[0] if bans else None
                    if not isinstance(ban0, dict) or not ban0.get("client"):
                        continue
                elif typ == "auto_kick":
                    kind = str(payload.get("type") or payload.get("kind") or "steam_closed")
                    pretty_name = str(player.get("steam_name") or "")
                    if kind == "steam_closed" and pretty_name and pretty_name != steam:
                        kind = "steam_empty_profile"
                    meta["target_steam_id"] = steam
                    meta["type"] = kind
                    meta["meta_value"] = payload.get("meta_value") if isinstance(payload.get("meta_value"), dict) else {
                        "reason": payload.get("reason") or "",
                        "current": payload.get("current") or 0,
                        "current_afk": payload.get("current_afk") or 0,
                        "country": payload.get("country") or "",
                        "provider": payload.get("provider") or "",
                        "real_name": payload.get("real_name") or pretty_name or "",
                        "found": payload.get("found") or "",
                        "signed_at": payload.get("signed_at") or 0,
                        "minimal": payload.get("minimal") or 0,
                        "kick_for_hidden_game_activity": bool(payload.get("kick_for_hidden_game_activity")),
                    }
                elif typ == "vpn_detected":
                    meta["ip_details"] = payload.get("ip_details") if isinstance(payload.get("ip_details"), dict) else local_ip_details(meta.get("ip") or "")
                elif typ in ("join_with_ip_ban", "join_with_external_ban"):
                    meta.setdefault("ban_id", int(payload.get("ban_id") or row["id"] or 0))
                elif typ == "license_changed":
                    meta.setdefault("previous", payload.get("previous") or payload.get("old") or payload.get("from") or "—")
                    meta.setdefault("current", payload.get("current") or payload.get("new") or payload.get("to") or "—")
                    meta.setdefault("old", meta.get("previous"))
                    meta.setdefault("new", meta.get("current"))
                elif typ == "dug_up_stash":
                    meta.setdefault("grid", payload.get("grid") or payload.get("square") or "")
                    meta.setdefault("square", meta.get("grid") or "")
                    meta.setdefault("position", payload.get("position") or meta.get("grid") or "")
                    if not str(meta.get("grid") or meta.get("position") or "").strip():
                        continue
                category = str(meta.get("category") or typ)
                items.append({
                    "id": int(row["id"] or 0),
                    "type": typ,
                    "steam_id": steam,
                    "payload": payload,
                    "meta": meta,
                    "created_at": int(row["created_at"] or 0),
                    "player": player,
                    "server_id": int(player.get("server_id") or 1) or 1,
                    "hide_in_table": False,
                    "resolved": False,
                    "hide_resolved": False,
                    "category": category,
                })
            return browse(items, params)

        return db_call(_b)

    def _browse_chat(self, params):
        def _small_player(conn, steam_id, steam_name=""):
            steam_id = str(steam_id or "")
            name = str(steam_name or steam_id or "")
            return {
                "steam_id": steam_id,
                "steam_name": name,
                "name": name,
                "steam_avatar": PLACEHOLDER,
                "status": "offline",
            }

        def _item(conn, row):
            from_site = chat_flag(row, "from_site", "from_site") or row["steam_id"] in ("site", "project", "0", "", None)
            target = row["target_steam_id"] or None
            initiator_kind = "player"
            stored_actor_id = 0
            if from_site:
                msg_type = "direct" if target else "global"
                from_project = str(row["steam_id"] or "") in ("project", "org")
                initiator_kind = "project" if from_project else "client"
                stored_name = str(row["steam_name"] or "")
                stored_actor = ""
                stored_actor_id = 0
                try:
                    if "actor_name" in row.keys() and row["actor_name"]:
                        stored_actor = str(row["actor_name"] or "")
                    if "actor_user_id" in row.keys() and row["actor_user_id"]:
                        stored_actor_id = int(row["actor_user_id"] or 0)
                except Exception:
                    stored_actor_id = 0
                if from_project:
                    staff_name = stored_name or project_title(conn)
                    row_pid = 0
                    try:
                        row_pid = int(row["project_id"] or 0) if "project_id" in row.keys() else 0
                    except Exception:
                        row_pid = 0
                    pid = row_pid or current_pid() or 0
                    prow = rowd(conn.execute("SELECT * FROM project WHERE id = ?", (pid,)).fetchone()) or {} if pid else {}
                    if str(staff_name or "").strip() in ("RustCheck", "RustApp", "system") or str(stored_actor or "").strip() in ("RustCheck", "RustApp"):
                        initiator_client = rustcheck_system_client()
                        staff_name = "RustApp"
                        staff_avatar = RUSTCHECK_AVATAR
                    else:
                        staff_avatar = prow.get("avatar") or PLACEHOLDER
                        initiator_client = {
                            "id": (1000000 + int(pid or 0)) if pid else 1,
                            "name": staff_name,
                            "tag": staff_name,
                            "avatar": staff_avatar,
                            "status": "online",
                            "is_project": True,
                        }
                else:
                    staff_name = stored_actor or stored_name
                    initiator_client = staff_brief(conn, staff_name, stored_actor_id, {
                        "actor_name": staff_name, "actor_user_id": stored_actor_id,
                    })
                    initiator_client["status"] = "online"
                    staff_avatar = initiator_client.get("avatar") or PLACEHOLDER
                initiator_player = {
                    "steam_id": "0",
                    "steam_name": staff_name,
                    "steam_avatar": staff_avatar,
                    "status": "online",
                    "is_project": from_project,
                }
                initiator_name = staff_name
                initiator_avatar = staff_avatar
                initiator_id = str(int(((initiator_client or {}).get("id") if from_project else stored_actor_id) or (initiator_client or {}).get("id") or 0) or 1)
                if initiator_client and isinstance(initiator_client, dict):
                    cid_num = stable_client_id(int(initiator_id or 0) or initiator_client.get("id"), initiator_name)
                    initiator_client["id"] = cid_num
                    initiator_id = str(cid_num)
                else:
                    initiator_id = str(stable_client_id(int(initiator_id or 0), initiator_name))
            else:
                msg_type = "team" if chat_flag(row, "is_team", "is_team") else ("direct" if target else "global")
                initiator_player = _small_player(conn, row["steam_id"], row["steam_name"])
                initiator_client = None
                initiator_name = (initiator_player or {}).get("steam_name") or str(row["steam_name"] or row["steam_id"] or "")
                initiator_avatar = PLACEHOLDER
                initiator_id = str(row["steam_id"] or "")
            created = int(row["created_at"] or now_ms())
            target_player = _small_player(conn, target, "") if target else None
            if initiator_client and isinstance(initiator_client, dict):
                cid = stable_client_id(
                    initiator_client.get("id") or stored_actor_id or initiator_id,
                    initiator_name,
                )
                initiator_client["id"] = cid
                initiator_id = str(cid)
            else:
                initiator_id = str(initiator_id if initiator_id is not None else "")
            if initiator_player and isinstance(initiator_player, dict):
                initiator_player.setdefault("steam_id", initiator_id or "0")
                initiator_player.setdefault("steam_name", initiator_name or "")
                initiator_player.setdefault("name", initiator_player.get("steam_name") or "")
            return {
                "id": row["id"],
                "unique_id": f"msg-{row['id']}",
                "steam_id": row["steam_id"],
                "initiator_id": initiator_id,
                "initiator": initiator_kind,
                "initiator_name": initiator_name,
                "initiator_avatar": initiator_avatar,
                "target_steam_id": target,
                "target_id": target,
                "text": row["text"] or "",
                "message": row["text"] or "",
                "type": msg_type,
                "is_team": chat_flag(row, "is_team", "is_team"),
                "created_at": created,
                "server_id": int(row["server_id"] or 0),
                "serverId": int(row["server_id"] or 0),
                "from_site": from_site,
                "initiator_player": initiator_player,
                "initiator_client": initiator_client,
                "target_player": target_player,
                "target_name": (target_player or {}).get("steam_name") or "",
            }

        def _b(conn):
            sid = query_sid(params, "steam_id", "target_steam_id", "player_id")
            search_ids = params.get("search_players_ids") or params.get("search_players_ids[]") or []
            if isinstance(search_ids, str):
                search_ids = [search_ids]
            search_ids = [str(x).strip() for x in search_ids if str(x).strip()]
            search_text = str(qfirst(params, "search_text") or "").lower()
            filter_types = params.get("filter_type") or params.get("filter_type[]") or []
            if isinstance(filter_types, str):
                filter_types = [filter_types]
            filter_types = {str(x).strip().lower() for x in filter_types if str(x).strip()}
            direction = str(qfirst(params, "pagination_direction") or "to").lower()
            try:
                cursor = int(qfirst(params, "pagination_timestamp") or 0)
            except Exception:
                cursor = 0
            pclause, pargs = scoped_project_clause(conn, params)
            paired = set(project_server_ids(conn))
            args = list(pargs)
            if cursor and direction in ("from", "newer", "after"):
                sql = "SELECT * FROM chat WHERE 1=1" + pclause + " AND created_at > ? ORDER BY created_at ASC, id ASC LIMIT 50"
                args.append(cursor)
                rows = conn.execute(sql, args).fetchall()
            elif cursor:
                sql = "SELECT * FROM chat WHERE 1=1" + pclause + " AND created_at < ? ORDER BY created_at DESC, id DESC LIMIT 80"
                args.append(cursor)
                rows = list(reversed(conn.execute(sql, args).fetchall()))
            else:
                sql = "SELECT * FROM chat WHERE 1=1" + pclause + " ORDER BY created_at DESC, id DESC LIMIT 80"
                rows = list(reversed(conn.execute(sql, args).fetchall()))
            items = []
            for row in rows:
                created = int(row["created_at"] or 0)
                if cursor:
                    if direction in ("from", "newer", "after") and created <= cursor:
                        continue
                    if direction in ("to", "older", "before") and created >= cursor:
                        continue
                steam_id = str(row["steam_id"] or "")
                target = str(row["target_steam_id"] or "")
                if sid and steam_id != sid and target != sid:
                    continue
                if search_ids and steam_id not in search_ids and target not in search_ids:
                    continue
                if search_text and search_text not in str(row["text"] or "").lower() and search_text not in str(row["steam_name"] or "").lower():
                    continue
                from_site_row = chat_flag(row, "from_site", "from_site") or steam_id in ("site", "project", "0", "", None)
                row_server = 0
                try:
                    if "server_id" in row.keys():
                        row_server = int(row["server_id"] or 0)
                except Exception:
                    row_server = 0
                if not from_site_row:
                    if paired and row_server and row_server not in paired:
                        continue
                item = _item(conn, row)
                if row_server:
                    item["server_id"] = row_server
                    item["serverId"] = row_server
                is_team_msg = bool(item.get("is_team")) or str(item.get("type") or "").lower() == "team"
                if is_team_msg and "team" not in filter_types:
                    continue
                if filter_types and str(item.get("type") or "").lower() not in filter_types:
                    continue
                items.append(item)
            # Contract: oldest first, newest last. Frontend appends new messages to the end.
            return {"data": items, "results": items, "items": items, "total": len(items), "count": len(items), "limit": 400, "page": 1}

        return db_call(_b)

    def _browse_mutes(self, params):
        def _b(conn):
            items = []
            sid_filter = query_sid(params, "steam_id", "player_id", "target_steam_id")
            pclause, pargs = scoped_project_clause(conn, params)
            sql = "SELECT * FROM mutes WHERE 1=1" + pclause
            args = list(pargs)
            if sid_filter:
                sql += " AND steam_id = ?"
                args.append(sid_filter)
            sql += " ORDER BY id DESC LIMIT 200"
            for row in conn.execute(sql, args).fetchall():
                actor_id = 0
                snap_name = ""
                snap_email = ""
                snap_role = ""
                try:
                    actor_id = int(row["actor_user_id"] or 0) if "actor_user_id" in row.keys() else 0
                except Exception:
                    actor_id = 0
                try:
                    if "actor_name" in row.keys():
                        snap_name = str(row["actor_name"] or "")
                    if "actor_email" in row.keys():
                        snap_email = str(row["actor_email"] or "")
                    if "actor_role" in row.keys():
                        snap_role = str(row["actor_role"] or "")
                except Exception:
                    pass
                actor_id, snap_name, snap_email, snap_role = resolved_staff_snapshot(
                    conn, snap_name, actor_id, snap_email, snap_role,
                    row["project_id"] if "project_id" in row.keys() else current_pid() or 0,
                )
                staff = actor_client(conn, snap_name, actor_id, {
                    "actor_name": snap_name, "actor_email": snap_email, "actor_role": snap_role, "actor_user_id": actor_id,
                })
                staff["name"] = snap_name or staff.get("name") or ""
                if features.is_generic_staff_label(staff.get("name")):
                    live = features.staff_public_name(features.user_by_id(conn, actor_id) if actor_id else None, snap_name, snap_email)
                    if live:
                        staff["name"] = live
                live_tag = features.staff_public_tag(features.user_by_id(conn, actor_id) if actor_id else None, staff.get("name") or "", conn)
                if live_tag:
                    staff["tag"] = live_tag
                staff["id"] = stable_client_id(actor_id, snap_name or staff.get("name") or "")
                row_sid = str(row["steam_id"] or "")
                items.append({
                    "id": row["id"],
                    "target_steam_id": row_sid,
                    "steam_id": row_sid,
                    "reason": row["reason"],
                    "created_at": row["created_at"],
                    "expired_at": row["expired_at"] or 0,
                    "computed_is_active": bool(row["active"]),
                    "client_id": int(staff.get("id") or 0),
                    "client": staff,
                    "initiator_client": staff,
                    "actor_id": actor_id,
                    "actor_name": snap_name or staff.get("name") or "",
                    "initiator_name": snap_name or staff.get("name") or "",
                    "system_source": "RustCheck",
                    "project_id": current_pid() or 0,
                    "deleted_at": None if row["active"] else int(row["created_at"] or now_ms()),
                    "target_player": player_view(conn, row_sid),
                })
            return browse(items, params)

        return db_call(_b)

    def _browse_bags(self, params):
        def _row(conn, row, server):
            keys = row.keys() if hasattr(row, "keys") else []
            from_sid = str(row["from_steam_id"] if "from_steam_id" in keys and row["from_steam_id"] else row["steam_id"] if "steam_id" in keys else "")
            to_sid = str(row["to_steam_id"] if "to_steam_id" in keys and row["to_steam_id"] else row["steam_id"] if "steam_id" in keys else from_sid)
            if not from_sid:
                from_sid = to_sid
            giver = self._bag_player(conn, from_sid)
            receiver = self._bag_player(conn, to_sid)
            pos = parse_xyz(row["position"] if "position" in keys else "")
            pos["time"] = int(row["created_at"] or 0)
            server_world = float((server or {}).get("world_size") or (server or {}).get("size") or 3000)
            grid = str(row["grid"] if "grid" in keys else "") or rust_grid(float(pos.get("x") or 0), float(pos.get("z") or 0), server_world)
            coords = as_coords(grid)
            pos_text = f"{float(pos.get('x') or 0):.2f}, {float(pos.get('y') or 0):.2f}, {float(pos.get('z') or 0):.2f}"
            display = grid or pos_text
            giver_name = (giver or {}).get("steam_name") or from_sid
            receiver_name = (receiver or {}).get("steam_name") or to_sid
            return {
                "id": row["id"],
                "M_ID": row["id"],
                "net_id": row["net_id"] if "net_id" in keys else "",
                "name": (row["name"] if "name" in keys else "") or "bag",
                "grid": grid,
                "square": grid,
                "position": display,
                "coords": coords,
                "coordinates": display,
                "coordinate": display,
                "position_text": display,
                "xyz": pos_text,
                "x": pos["x"],
                "y": pos["y"],
                "z": pos["z"],
                "steam_id": to_sid or from_sid,
                "steam_name": receiver_name,
                "initiator_steam_id": from_sid,
                "target_steam_id": to_sid,
                "from_steam_id": from_sid,
                "to_steam_id": to_sid,
                "initiator_name": giver_name,
                "target_name": receiver_name,
                "from_name": giver_name,
                "to_name": receiver_name,
                "created_at": row["created_at"],
                "player": receiver or giver,
                "initiator": giver,
                "target": receiver,
                "initiator_player": giver,
                "target_player": receiver,
                "from_player": giver,
                "to_player": receiver,
                "player_from": giver,
                "player_to": receiver,
                "giver": giver,
                "receiver": receiver,
                "teammates": False,
                "has_teammates": False,
                "team": (receiver or {}).get("team") or [],
                "server": server,
                "server_id": int(server.get("id") or 1),
                "client_id": 1,
            }

        def _b(conn):
            items = []
            server = get_server(conn)
            world = float(server.get("world_size") or server.get("size") or 3000)
            for row in conn.execute(
                "SELECT * FROM bags WHERE steam_id != '' AND steam_id != '0'"
                + project_clause()[0]
                + " ORDER BY id DESC LIMIT 400",
                project_clause()[1],
            ).fetchall():
                item = _row(conn, row, server)
                grid = str(item.get("grid") or "")
                if (not grid or grid in ("A0", "0", "A14")) and (item.get("x") or item.get("z")):
                    grid = rust_grid(float(item.get("x") or 0), float(item.get("z") or 0), world)
                    item["grid"] = grid
                    item["square"] = grid
                    item["coords"] = as_coords(grid)
                items.append(item)
            # Do NOT merge bag_events here — deleted bags would reappear as ghosts
            return browse(items, params)

        return db_call(_b)

    def _browse_audit(self, params):
        type_map = {
            "auth.sign_in": "EditSettings",
            "auth.sign_up": "StaffEdit",
            "check.started": "PlayerCheck",
            "check.finished": "PlayerCheck",
            "check.notice": "PlayerCheck",
            "mute.create": "PlayerMute",
            "mute.delete": "PlayerMute",
            "ban.create": "PlayerBan",
            "ban.created": "PlayerBan",
            "ban.edit": "BanEdit",
            "ban.delete": "BanEdit",
            "webhook.save": "EditSettings",
            "wallet.topup": "EditSubscription",
            "tariff.change": "EditSubscription",
            "project.delete": "StaffDelete",
            "check.contact": "ChatMessage",
            "report.created": "ChatMessage",
            "settings.edit": "EditSettings",
            "chat.direct": "ChatMessage",
            "chat.global": "ChatMessage",
            "player.message": "ChatMessage",
            "custom_action.execute": "CustomAction",
        }

        def _b(conn):
            items = []
            seen = set()

            def _resolve_ban_id(ban_id, sid, audit_id):
                try:
                    ban_id = int(ban_id or 0)
                except (TypeError, ValueError):
                    ban_id = 0
                pclause, pargs = scoped_project_clause(conn, params)
                if ban_id:
                    return ban_id
                if sid:
                    found = conn.execute(
                        "SELECT id FROM bans WHERE steam_id = ?" + pclause + " ORDER BY id DESC LIMIT 1",
                        [sid, *pargs],
                    ).fetchone()
                    if found:
                        return int(found["id"])
                return int(audit_id or 0)

            pclause, pargs = scoped_project_clause(conn, params)
            for row in conn.execute(
                "SELECT * FROM audit WHERE 1=1" + pclause + " ORDER BY id DESC LIMIT 80",
                pargs,
            ).fetchall():
              try:
                try:
                    payload = json.loads(row["payload"] or "{}")
                except Exception:
                    payload = {}
                if not isinstance(payload, dict):
                    payload = {"value": payload}
                if "actor_name" in row.keys() and row["actor_name"]:
                    payload["actor_name"] = row["actor_name"] or payload.get("actor_name")
                if "actor_email" in row.keys() and row["actor_email"]:
                    payload["actor_email"] = row["actor_email"] or payload.get("actor_email")
                if "actor_role" in row.keys() and row["actor_role"]:
                    payload["actor_role"] = row["actor_role"] or payload.get("actor_role")
                event = row["event"] or "info"
                actor_row_id = 0
                try:
                    actor_row_id = int(row["actor_user_id"] or 0) if "actor_user_id" in row.keys() else 0
                except Exception:
                    actor_row_id = 0
                if is_ingame_chat_audit(event, payload, actor_row_id):
                    continue
                typ = type_map.get(event, "EditSettings")
                meta = dict(payload)
                target_sid = str(payload.get("steam_id") or payload.get("target_steam_id") or "")
                target_name = str(payload.get("name") or payload.get("target_name") or "")
                if target_sid and not is_display_name(target_name, target_sid):
                    target_name = resolve_player_name(conn, target_sid, "")
                meta["target_steam_id"] = target_sid
                meta["steam_id"] = target_sid
                meta["target_name"] = target_name
                meta["player_name"] = target_name
                if typ == "PlayerCheck":
                    meta["action_type"] = "finished" if event.endswith("finished") else "created"
                elif typ == "PlayerMute":
                    meta["action_type"] = "deleted" if event.endswith("delete") else "created"
                elif typ == "PlayerBan":
                    meta["action_type"] = "created"
                    meta["reason"] = payload.get("reason") or ""
                    meta["ban_id"] = _resolve_ban_id(payload.get("ban_id"), target_sid, row["id"])
                elif typ == "BanEdit":
                    meta["action"] = payload.get("action") or ("unban" if event.endswith("delete") else "edit")
                    meta["ban_id"] = _resolve_ban_id(payload.get("ban_id"), target_sid, row["id"])
                elif typ == "ChatMessage":
                    meta["channel"] = payload.get("channel") or ("direct" if event == "chat.direct" or target_sid else "global")
                    meta["message"] = payload.get("message") or payload.get("text") or ""
                    if event == "report.created" and not meta["message"]:
                        meta["channel"] = "global"
                        meta["message"] = "Репорт: " + str(payload.get("reason") or "жалоба")
                    meta["text"] = meta["message"]
                    meta["reply_to"] = str(payload.get("reply_to") or payload.get("target_steam_id") or target_sid or "")
                    if meta["channel"] == "global":
                        meta["reply_to"] = ""
                    if meta["channel"] == "direct" and target_sid:
                        if not is_display_name(target_name, target_sid):
                            target_name = resolve_player_name(conn, target_sid, "")
                        meta["target_name"] = target_name
                        meta["player_name"] = target_name
                elif typ == "PlayerMessage":
                    typ = "ChatMessage"
                    meta["channel"] = payload.get("channel") or ("direct" if target_sid else "global")
                    meta["message"] = payload.get("message") or payload.get("text") or ""
                    meta["text"] = meta["message"]
                    meta["reply_to"] = str(payload.get("reply_to") or payload.get("target_steam_id") or target_sid or "")
                    if meta["channel"] == "global":
                        meta["reply_to"] = ""
                elif typ == "CustomAction":
                    cmds = payload.get("commands") or []
                    if isinstance(cmds, str):
                        cmds = [cmds]
                    meta["target"] = payload.get("target") or "command"
                    meta["commands"] = cmds
                    meta["command"] = "; ".join(str(c) for c in cmds)
                    meta["server_id"] = payload.get("server_id") or 0
                    meta["server_name"] = payload.get("server_name") or ""
                    meta["result"] = payload.get("result") or "ok"
                    meta["status"] = payload.get("status") or "ok"
                elif typ == "EditSettings":
                    meta["target"] = payload.get("target") or ("discord" if "webhook" in event else "court")
                elif typ == "EditSubscription":
                    plan = str(payload.get("plan") or payload.get("to") or "pro")
                    meta["from"] = str(payload.get("from") or "plus")
                    meta["to"] = plan
                if event in ("check.notice", "auth.sign_in", "auth.sign_up"):
                    continue
                if typ == "EditSettings" and not str(meta.get("target") or "").strip():
                    continue
                if typ == "CustomAction" and not str(meta.get("command") or meta.get("commands") or "").strip():
                    continue
                if typ == "ChatMessage" and not str(meta.get("message") or "").strip():
                    continue
                if typ == "PlayerCheck" and not target_sid:
                    continue
                if typ in ("PlayerBan", "BanEdit", "PlayerMute") and not target_sid and not meta.get("ban_id"):
                    continue
                if typ == "EditSettings" and meta.get("target") == "court" and event.startswith("ban."):
                    continue
                # Ensure SPA always has a display name for the target SteamID
                if target_sid:
                    if not is_display_name(target_name, target_sid):
                        target_name = resolve_player_name(conn, target_sid, "")
                    meta["target_name"] = target_name
                    meta["player_name"] = target_name
                    meta["name"] = target_name
                    if target_sid in str(meta.get("message") or ""):
                        meta["message"] = str(meta["message"]).replace(target_sid, target_name)
                        meta["text"] = meta["message"]
                dedupe_key = (
                    typ,
                    event,
                    str(meta.get("message") or "")[:120],
                    target_sid,
                    int(int(row["created_at"] or 0) / 5000),
                )
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                actor_id = 0
                try:
                    actor_id = int(row["actor_user_id"] or 0) if "actor_user_id" in row.keys() else 0
                except Exception:
                    actor_id = 0
                actor_id, frozen_name, frozen_email, frozen_role = resolved_staff_snapshot(
                    conn,
                    (row["actor_name"] if "actor_name" in row.keys() else "") or payload.get("actor_name") or str(row["actor"] or ""),
                    actor_id,
                    (row["actor_email"] if "actor_email" in row.keys() else "") or payload.get("actor_email") or "",
                    (row["actor_role"] if "actor_role" in row.keys() else "") or payload.get("actor_role") or "",
                    row["project_id"] if "project_id" in row.keys() else current_pid() or 0,
                )
                staff = staff_brief(conn, frozen_name, actor_id, {
                    **payload, "actor_name": frozen_name, "actor_email": frozen_email,
                    "actor_role": frozen_role, "actor_user_id": actor_id,
                })
                frozen_name = features.staff_public_name(
                    features.user_by_id(conn, actor_id) if actor_id else None,
                    frozen_name, frozen_email,
                ) or frozen_name
                if frozen_name and not features.is_generic_staff_label(frozen_name):
                    staff["name"] = frozen_name
                live_tag = features.staff_public_tag(features.user_by_id(conn, actor_id) if actor_id else None, staff.get("name") or "", conn)
                if live_tag:
                    staff["tag"] = live_tag
                if frozen_role:
                    staff["role"] = frozen_role
                    staff["actor_role"] = frozen_role
                if not staff.get("avatar"):
                    staff["avatar"] = PLACEHOLDER
                # The original RustApp client treats every displayed model as
                # an ORM object and reads M_ID from both the audit row and its
                # author.  Without it Vue crashes while rendering the audit
                # timeline and retries the request indefinitely.
                staff["M_ID"] = int(staff.get("id") or actor_id or 0)
                staff["status"] = "online"
                staff["online"] = True
                staff["is_online"] = True
                meta["actor_name"] = frozen_name
                meta["actor_role"] = frozen_role
                meta["client_name"] = frozen_name
                meta["initiator_name"] = frozen_name
                meta["system_source"] = payload.get("system_source") or "RustCheck"
                items.append({
                    "id": int(row["id"]),
                    "M_ID": int(row["id"]),
                    "type": typ,
                    "event": event,
                    "action": typ,
                    "actor": frozen_name,
                    "actor_name": frozen_name,
                    "actor_role": frozen_role,
                    "payload": payload,
                    "meta": meta,
                    "data": payload,
                    "created_at": int(row["created_at"] or now_ms()),
                    "client": dict(staff),
                    "initiator_client": dict(staff),
                    "client_id": int(staff.get("id") or 0),
                    "initiator_client_id": int(staff.get("id") or 0),
                    "server_id": int(payload.get("server_id") or meta.get("server_id") or 0),
                    "server_name": str(payload.get("server_name") or meta.get("server_name") or ""),
                    "project_id": int(row["project_id"] or 0) if "project_id" in row.keys() else current_pid() or 0,
                    "system_source": "RustCheck",
                })
              except Exception:
                continue
            items = [
                it for it in items
                if it.get("type") and it.get("client") and it.get("id")
            ]
            return browse(items, params)

        try:
            return db_call(_b)
        except Exception as exc:
            print("audit browse failed", exc)
            return browse([], params)

    def _project_stats_payload(self, path, params):
        def _s(conn):
            now = now_ms()
            online_now = 0
            try:
                online_now = int(conn.execute("SELECT COUNT(*) FROM online_players").fetchone()[0] or 0)
            except Exception:
                online_now = 0
            players_total = 0
            try:
                players_total = int(conn.execute("SELECT COUNT(*) FROM players").fetchone()[0] or 0)
            except Exception:
                players_total = 0

            if path.endswith("/ip") or path.rstrip("/").endswith("/ip"):
                return {
                    "created_at": now,
                    "top_cities": [],
                    "top_countries": [],
                    "total_players": players_total,
                    "countries": [],
                }

            is_unique = "unique" in path
            points = []
            # 25 hourly buckets for online charts / daily-ish for unique
            step = 86400000 if is_unique else 3600000
            count = 30 if is_unique else 24
            for i in range(count, -1, -1):
                t = now - i * step
                online = online_now if i == 0 and not is_unique else 0
                total = players_total if i == 0 and is_unique else 0
                points.append({
                    "timestamp": t,
                    "time": t,
                    "online": online,
                    "joining": 0,
                    "queued": 0,
                    "queue": 0,
                    "reserved": 0,
                    "players": online,
                    "total": total,
                    "value": total if is_unique else online,
                    "license": 0,
                    "pirate": 0,
                })
            return {
                "time_points": points,
                "countries": [],
                "total": players_total,
                "stats": {},
                "reasons": {},
                "moders": [],
            }

        return db_call(_s)

    def _stats_payload(self, params, kind="check"):
        def _s(conn):
            staff_id = parse_stats_staff_id(params)
            ts_from = 0
            ts_to = 0
            try:
                ts_from = int(float(qfirst(params, "from", "date_from", "start") or 0))
            except Exception:
                ts_from = 0
            try:
                ts_to = int(float(qfirst(params, "to", "date_to", "end") or 0))
            except Exception:
                ts_to = 0
            if 0 < ts_from < 10**12:
                ts_from *= 1000
            if 0 < ts_to < 10**12:
                ts_to *= 1000
            data = features.stats_kind(conn, kind, client_id=staff_id, ts_from=ts_from, ts_to=ts_to)
            now = now_ms()
            points = []
            buckets = data.get("stats") or {}
            for i in range(7, -1, -1):
                t = features._day_start(now - i * 86400000)
                bucket = buckets.get(str(t)) or {}
                points.append({
                    "time": t, "timestamp": t, "value": int(bucket.get("value") or 0), "online": 0, "players": 0,
                    "license": 0, "pirate": 0, "joining": 0, "queue": 0, "queued": 0, "reserved": 0,
                    "checks": int(bucket.get("clear") or 0) + int(bucket.get("ban") or 0) + int(bucket.get("canceled") or 0),
                    "bans": int(bucket.get("ban") or 0),
                    "mutes": int(bucket.get("mute") or 0),
                    "total": int(bucket.get("value") or 0),
                })
            data["time_points"] = points
            data["countries"] = []
            data["client_id"] = staff_id
            return data

        return db_call(_s)


if __name__ == "__main__":
    import sys

    def _autoreload():
        watched = [ROOT / "server.py", ROOT / "features.py", ROOT / "oauth_auth.py", ROOT / "admin_panel.py", ROOT / "platega_pay.py"]
        stamp = {}
        for path in watched:
            try:
                stamp[str(path)] = path.stat().st_mtime
            except Exception:
                stamp[str(path)] = 0
        while True:
            time.sleep(2)
            for path in watched:
                try:
                    mt = path.stat().st_mtime
                except Exception:
                    continue
                if mt <= stamp.get(str(path), 0):
                    continue
                print("file changed, restarting", path)
                os.execv(sys.executable, [sys.executable, "-u", str(ROOT / "server.py")])

    threading.Thread(target=_autoreload, daemon=True).start()

    def _scheduled_restart():
        delay = int(os.environ.get("CHECKAPP_RESTART_SEC") or (5 * 3600))
        if delay <= 0:
            return
        time.sleep(max(60, delay))
        print("scheduled restart after", delay, "sec")
        os.execv(sys.executable, [sys.executable, "-u", str(ROOT / "server.py")])

    threading.Thread(target=_scheduled_restart, daemon=True).start()
    port = int(os.environ.get("PORT") or os.environ.get("CHECKAPP_PORT") or 8081)
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print("RustApp: http://127.0.0.1:%s/" % port)
    print("Build: %s" % BUILD_ID)
    print("Serving from: %s" % ROOT.resolve())
    print("Register a new account on /client/auth — accounts are isolated.")
    print("Plugin API URL: http://THIS_PC:%s  (set PUBLIC_SITE / your domain in .env)" % port)
    server.serve_forever()
