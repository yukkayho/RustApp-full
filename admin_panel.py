"""Platform admin API for Checkapp."""
from __future__ import annotations

import ipaddress
import json
import os
import re
import threading
import time
import uuid
from typing import Any

import features

_ADMIN_SEEN: dict[int, int] = {}
_ADMIN_FLUSH: dict[int, int] = {}
_ADMIN_SEEN_LOCK = threading.Lock()
_ADMIN_ONLINE_MS = 90 * 1000


def touch_admin_presence(uid: int, conn=None) -> None:
    try:
        uid = int(uid or 0)
    except Exception:
        return
    if not uid:
        return
    now = int(time.time() * 1000)
    should_flush = False
    with _ADMIN_SEEN_LOCK:
        _ADMIN_SEEN[uid] = now
        last_flush = int(_ADMIN_FLUSH.get(uid) or 0)
        if now - last_flush >= 15000:
            _ADMIN_FLUSH[uid] = now
            should_flush = True
    if not should_flush:
        return
    try:
        if conn is not None:
            conn.execute("UPDATE users SET last_seen_at = ? WHERE id = ?", (now, uid))
            return
        from server import db_call

        db_call(lambda c: c.execute("UPDATE users SET last_seen_at = ? WHERE id = ?", (now, uid)))
    except Exception:
        pass


def admin_is_online(uid: int, last_seen_at: int = 0) -> bool:
    try:
        uid = int(uid or 0)
    except Exception:
        return False
    now = int(time.time() * 1000)
    with _ADMIN_SEEN_LOCK:
        ts = int(_ADMIN_SEEN.get(uid) or 0)
    try:
        ts = max(ts, int(last_seen_at or 0))
    except Exception:
        pass
    return ts > 0 and (now - ts) <= _ADMIN_ONLINE_MS


def _parse_ip(value: str) -> str:
    text = str(value or "").strip().split(",")[0].strip()
    if not text:
        return ""
    # Strip port from IPv4 host:port
    if text.count(":") == 1 and "." in text:
        text = text.split(":", 1)[0].strip()
    # Strip brackets from [IPv6]:port
    if text.startswith("[") and "]" in text:
        text = text[1 : text.index("]")]
    try:
        return str(ipaddress.ip_address(text))
    except Exception:
        return ""


def _is_private_or_local(ip: str) -> bool:
    try:
        obj = ipaddress.ip_address(ip)
        # Do NOT use is_reserved — TEST-NET (203.0.113.x) is reserved but is a valid public-looking client IP for tests,
        # and real CDN edges must never be filtered by "reserved".
        return bool(obj.is_private or obj.is_loopback or obj.is_link_local)
    except Exception:
        return True


def get_client_ip(handler) -> str:
    """Real browser/user IP behind Cloudflare / nginx. Do not invent headers."""
    headers = getattr(handler, "headers", None) or {}

    def hdr(*names: str) -> str:
        for name in names:
            try:
                val = headers.get(name)
            except Exception:
                val = None
            if val:
                parsed = _parse_ip(str(val))
                if parsed:
                    return parsed
        return ""

    # 1) Cloudflare sets CF-Connecting-IP to the visitor (overwrites client spoofing)
    cf = hdr("CF-Connecting-IP", "cf-connecting-ip", "True-Client-IP")
    if cf:
        return cf

    # 2) nginx X-Real-IP (configured from CF-Connecting-IP or $remote_addr)
    real = hdr("X-Real-IP", "x-real-ip")
    if real:
        return real

    try:
        peer = _parse_ip(str(handler.client_address[0] or ""))
    except Exception:
        peer = ""

    # 3) X-Forwarded-For — only trust when the immediate peer is a local/proxy hop
    forwarded = (
        headers.get("X-Forwarded-For")
        or headers.get("x-forwarded-for")
        or headers.get("Forwarded")
        or ""
    )
    parts: list[str] = []
    for chunk in str(forwarded).split(","):
        chunk = chunk.strip()
        if chunk.lower().startswith("for="):
            chunk = chunk[4:].strip().strip('"')
        parsed = _parse_ip(chunk)
        if parsed:
            parts.append(parsed)

    if parts:
        if peer and _is_private_or_local(peer):
            # Backend is behind nginx/CDN — leftmost is the original client
            for cand in parts:
                if not _is_private_or_local(cand):
                    return cand
            return parts[0]
        # Direct public peer: ignore client-supplied XFF (spoof risk)
        if peer:
            return peer
        return parts[0]

    return peer or ""


def client_ip(handler) -> str:
    """Alias used across the codebase."""
    return get_client_ip(handler)


def plugin_remote_ip(handler) -> str:
    """Outbound IP of the Rust game server (plugin → API), not a browser user IP."""
    return get_client_ip(handler)


def require_admin(handler):
    user = handler.bind_auth_user()
    if not features.is_platform_admin(user):
        handler._json({"message": "forbidden", "unauthorized": True}, 403)
        return None
    ip = client_ip(handler)
    if user and ip:
        try:
            from server import db_call

            db_call(lambda c: features.record_user_ip(c, int(user.get("id") or 0), ip))
        except Exception:
            pass
    try:
        touch_admin_presence(int(user.get("id") or 0))
    except Exception:
        pass
    return user


def _rowd(row):
    return dict(row) if row else {}


def _fmt_ts(ms: int) -> str:
    try:
        ms = int(ms or 0)
    except Exception:
        return ""
    if ms <= 0:
        return ""
    import datetime

    return datetime.datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M:%S")


def _query(params: dict) -> str:
    raw = params.get("q") or params.get("search") or [""]
    if isinstance(raw, list):
        raw = raw[0] if raw else ""
    return str(raw or "").strip().lower()


def _match_any(q: str, *values) -> bool:
    if not q:
        return True
    for val in values:
        text = str(val or "").lower()
        if q in text:
            return True
    return False


def _project_status(conn, pid: int) -> dict:
    meta = features.project_billing(conn, int(pid))
    flags = features.project_admin_flags(conn, int(pid))
    blocked = bool(flags.get("blocked"))
    admin_frozen = bool(flags.get("admin_frozen"))
    is_paid = bool(meta.get("is_paid"))
    is_trial = bool(meta.get("is_trial"))
    lifecycle = features.project_lifecycle_status(blocked, is_paid, is_trial, admin_frozen)
    subscription_expired = lifecycle == "frozen" and (not admin_frozen)

    if blocked:
        status = "blocked"
        status_label = "Проект заблокирован"
        status_icon = "lock"
    elif is_paid or is_trial:
        status = "trial" if is_trial else "active"
        status_label = "Пробный период" if is_trial else "Активен"
        status_icon = "trial" if is_trial else "ok"
    else:
        status = "frozen"
        status_label = "Проект заморожен"
        status_icon = "snowflake"

    return {
        "status": status,
        "status_label": status_label,
        "status_icon": status_icon,
        "lifecycle": lifecycle,
        "subscription_expired": subscription_expired,
        "frozen": lifecycle == "frozen",
        "blocked": blocked,
        "admin_frozen": admin_frozen,
        "is_trial": is_trial,
        "is_paid": is_paid,
        "plan": meta.get("slug") or "base",
        "balance": int(meta.get("balance") or 0),
        "balance_rub": round(int(meta.get("balance") or 0) / 100, 2),
        "paid_until": int(meta.get("paid_until") or 0),
        "paid_until_fmt": _fmt_ts(int(meta.get("paid_until") or 0)),
        "trial_ends_at": int(meta.get("trial_ends") or meta.get("trial_ends_at") or 0),
        "trial_ends_fmt": _fmt_ts(int(meta.get("trial_ends") or meta.get("trial_ends_at") or 0)),
    }


def plans_payload() -> list:
    out = []
    for slug in ("base", "plus", "enterprise"):
        plan = dict(features.PLANS.get(slug) or {})
        out.append(
            {
                "slug": slug,
                "name": plan.get("name") or slug,
                "price_month": int(plan.get("price_month") or 0),
                "price_rub": round(int(plan.get("price_month") or 0) / 100, 2),
                "subtitle": plan.get("subtitle") or "",
            }
        )
    return out


def _safe_count(conn, sql: str, args: tuple = ()) -> int:
    try:
        row = conn.execute(sql, args).fetchone()
        return int((row[0] if row else 0) or 0)
    except Exception:
        return 0


def stats_payload(conn) -> dict:
    users = int(conn.execute("SELECT COUNT(*) FROM users").fetchone()[0])
    projects = int(conn.execute("SELECT COUNT(*) FROM project").fetchone()[0])
    servers = int(conn.execute("SELECT COUNT(*) FROM servers").fetchone()[0])
    paired = int(conn.execute("SELECT COUNT(*) FROM servers WHERE paired = 1").fetchone()[0] or 0)
    online = _safe_count(conn, "SELECT COUNT(*) FROM servers WHERE connected = 1")
    active = 0
    frozen = 0
    blocked = 0
    for row in conn.execute("SELECT id FROM project").fetchall():
        st = _project_status(conn, int(row["id"]))
        lifecycle = st.get("lifecycle") or st.get("status")
        if lifecycle == "blocked" or st["blocked"]:
            blocked += 1
        elif lifecycle == "frozen" or st.get("frozen"):
            frozen += 1
        else:
            active += 1
    week_ago = int(time.time() * 1000) - 7 * 24 * 60 * 60 * 1000
    return {
        "users": users,
        "projects": projects,
        "servers": servers,
        "paired_servers": paired,
        "online_servers": online,
        "active_projects": active,
        "frozen_projects": frozen,
        "blocked_projects": blocked,
        "checks": _safe_count(conn, "SELECT COUNT(*) FROM checks"),
        "reports": _safe_count(conn, "SELECT COUNT(*) FROM reports"),
        "users_7d": _safe_count(conn, "SELECT COUNT(*) FROM users WHERE COALESCE(created_at, 0) >= ?", (week_ago,)),
        "projects_7d": _safe_count(conn, "SELECT COUNT(*) FROM project WHERE COALESCE(created_at, 0) >= ?", (week_ago,)),
    }


DAY_MS = 24 * 60 * 60 * 1000

_CHAT_MAX = 50 * 1024 * 1024
_CHAT_EXTS = {
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".webp": "image",
    ".gif": "image",
    ".mp4": "video",
    ".webm": "video",
    ".mov": "video",
    ".ogg": "audio",
    ".mp3": "audio",
    ".wav": "audio",
    ".m4a": "audio",
}


def _ensure_admin_chat(conn) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS admin_chat (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            user_name TEXT DEFAULT '',
            user_email TEXT DEFAULT '',
            kind TEXT DEFAULT 'text',
            text TEXT DEFAULT '',
            file_url TEXT DEFAULT '',
            file_name TEXT DEFAULT '',
            mime TEXT DEFAULT '',
            duration_ms INTEGER DEFAULT 0,
            created_at INTEGER DEFAULT 0,
            reply_to INTEGER DEFAULT 0,
            reply_name TEXT DEFAULT '',
            reply_text TEXT DEFAULT '',
            reply_kind TEXT DEFAULT '',
            mentions TEXT DEFAULT '[]'
        )"""
    )
    for col, default in (
        ("reply_to", "INTEGER DEFAULT 0"),
        ("reply_name", "TEXT DEFAULT ''"),
        ("reply_text", "TEXT DEFAULT ''"),
        ("reply_kind", "TEXT DEFAULT ''"),
        ("mentions", "TEXT DEFAULT '[]'"),
    ):
        try:
            conn.execute("ALTER TABLE admin_chat ADD COLUMN " + col + " " + default)
        except Exception:
            pass


def _parse_multipart(raw: bytes, content_type: str) -> tuple[dict, dict | None]:
    fields: dict[str, str] = {}
    file_part = None
    m = re.search(r"boundary=([^;]+)", content_type or "", re.I)
    if not m or not raw:
        return fields, None
    boundary = m.group(1).strip().strip('"').encode("utf-8")
    marker = b"--" + boundary
    for chunk in raw.split(marker):
        chunk = chunk.strip(b"\r\n")
        if not chunk or chunk == b"--" or chunk.startswith(b"--"):
            continue
        if b"\r\n\r\n" not in chunk:
            continue
        head, data = chunk.split(b"\r\n\r\n", 1)
        if data.endswith(b"\r\n"):
            data = data[:-2]
        header = head.decode("utf-8", "ignore")
        name_m = re.search(r'name="([^"]+)"', header)
        fn_m = re.search(r'filename="([^"]*)"', header)
        mime_m = re.search(r"Content-Type:\s*([^\r\n]+)", header, re.I)
        name = name_m.group(1) if name_m else ""
        if fn_m is not None and fn_m.group(1):
            file_part = {
                "field": name,
                "filename": fn_m.group(1),
                "mime": (mime_m.group(1).strip() if mime_m else ""),
                "data": data,
            }
        elif name:
            fields[name] = data.decode("utf-8", "ignore")
    return fields, file_part


def _chat_ext(name: str, mime: str) -> str:
    low = str(name or "").lower()
    for ext in _CHAT_EXTS:
        if low.endswith(ext):
            return ext
    mime = str(mime or "").lower()
    if "png" in mime:
        return ".png"
    if "jpeg" in mime or "jpg" in mime:
        return ".jpg"
    if "webp" in mime:
        return ".webp"
    if "gif" in mime:
        return ".gif"
    if "mp4" in mime:
        return ".mp4"
    if "webm" in mime:
        return ".webm"
    if "ogg" in mime:
        return ".ogg"
    if "mpeg" in mime or "mp3" in mime:
        return ".mp3"
    if "wav" in mime:
        return ".wav"
    if "quicktime" in mime or "mov" in mime:
        return ".mov"
    return ""


def _chat_kind(ext: str, mime: str, hinted: str) -> str:
    hint = str(hinted or "").lower()
    if hint in ("image", "video", "audio", "file"):
        if hint == "audio" and ext in (".webm", ".ogg", ".mp3", ".wav", ".m4a", ""):
            return "audio"
        if hint != "file":
            return hint
    if ext in _CHAT_EXTS:
        kind = _CHAT_EXTS[ext]
        if kind == "video" and ("audio" in str(mime or "").lower() or hint == "audio"):
            return "audio"
        return kind
    return "file"


def _save_chat_file(data: bytes, filename: str, mime: str, hinted: str) -> tuple[str, str, str]:
    if not data or len(data) > _CHAT_MAX:
        raise ValueError("Файл слишком большой (макс. 50 МБ)")
    ext = _chat_ext(filename, mime)
    if not ext:
        raise ValueError("Такой тип файла нельзя отправить")
    kind = _chat_kind(ext, mime, hinted)
    from server import UPLOADS

    UPLOADS.mkdir(exist_ok=True)
    name = "ac-" + uuid.uuid4().hex + ext
    (UPLOADS / name).write_bytes(data)
    url = "/uploads/" + name + "?https=1"
    safe_name = os.path.basename(str(filename or name))[:120]
    return kind, url, safe_name


def _parse_mentions(raw) -> list:
    if isinstance(raw, list):
        out = []
        for x in raw:
            try:
                n = int(x)
            except Exception:
                continue
            if n:
                out.append(n)
        return out
    if isinstance(raw, (int, float)):
        n = int(raw)
        return [n] if n else []
    s = str(raw or "").strip()
    if not s:
        return []
    if s.startswith("["):
        try:
            data = json.loads(s)
            return _parse_mentions(data if isinstance(data, list) else [])
        except Exception:
            return []
    out = []
    for part in re.split(r"[,\s]+", s):
        try:
            n = int(part)
        except Exception:
            continue
        if n:
            out.append(n)
    return out


def _norm_handle(s: str) -> str:
    return re.sub(r"[^a-z0-9а-яё_]+", "", str(s or "").lower())


def _admin_handles(admin: dict) -> list[str]:
    name = str(admin.get("name") or "").strip()
    email = str(admin.get("email") or "").strip()
    local = email.split("@")[0] if email else ""
    out = []
    if name:
        out.append(name.replace(" ", ""))
        out.append(name)
    if local:
        out.append(local)
    return out


def _resolve_mentions(conn, text: str, payload: dict) -> list:
    ids = set(_parse_mentions(payload.get("mentions")))
    blob = str(text or "")
    tags = [_norm_handle(t) for t in re.findall(r"@([A-Za-zА-Яа-яЁё0-9_.-]{2,40})", blob)]
    tags = [t for t in tags if t]
    if tags:
        try:
            admins = features.list_platform_admins(conn)
        except Exception:
            admins = []
        by_handle = {}
        for a in admins:
            aid = int(a.get("id") or 0)
            if not aid:
                continue
            for h in _admin_handles(a):
                key = _norm_handle(h)
                if key:
                    by_handle[key] = aid
        for tag in tags:
            if tag in by_handle:
                ids.add(by_handle[tag])
    return [i for i in ids if i]


def _chat_item(conn, row) -> dict:
    item = _rowd(row)
    uid = int(item.get("user_id") or 0)
    last_seen = 0
    try:
        seen = conn.execute("SELECT last_seen_at FROM users WHERE id = ?", (uid,)).fetchone()
        last_seen = int((seen["last_seen_at"] if seen else 0) or 0)
    except Exception:
        last_seen = 0
    return {
        "id": int(item.get("id") or 0),
        "user_id": uid,
        "user_name": item.get("user_name") or "",
        "user_email": item.get("user_email") or "",
        "kind": item.get("kind") or "text",
        "text": item.get("text") or "",
        "file_url": item.get("file_url") or "",
        "file_name": item.get("file_name") or "",
        "mime": item.get("mime") or "",
        "duration_ms": int(item.get("duration_ms") or 0),
        "created_at": int(item.get("created_at") or 0),
        "online": admin_is_online(uid, last_seen),
        "reply_to": int(item.get("reply_to") or 0),
        "reply_name": item.get("reply_name") or "",
        "reply_text": item.get("reply_text") or "",
        "reply_kind": item.get("reply_kind") or "",
        "mentions": _parse_mentions(item.get("mentions")),
    }


def list_admin_chat(conn, after_id: int = 0, limit: int = 80) -> list:
    _ensure_admin_chat(conn)
    try:
        after_id = int(after_id or 0)
        limit = max(1, min(int(limit or 80), 200))
    except Exception:
        after_id, limit = 0, 80
    if after_id > 0:
        rows = conn.execute(
            "SELECT * FROM admin_chat WHERE id > ? ORDER BY id ASC LIMIT ?",
            (after_id, limit),
        ).fetchall()
        return [_chat_item(conn, r) for r in rows]
    rows = conn.execute(
        "SELECT * FROM admin_chat ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    items = [_chat_item(conn, r) for r in rows]
    items.reverse()
    return items


def admin_chat_peek(conn) -> dict:
    _ensure_admin_chat(conn)
    row = conn.execute("SELECT MAX(id) AS m FROM admin_chat").fetchone()
    last_id = int((row["m"] if row else 0) or 0)
    total = int(conn.execute("SELECT COUNT(*) FROM admin_chat").fetchone()[0] or 0)
    last_user_id = 0
    mentions = []
    if last_id:
        last = conn.execute(
            "SELECT user_id, mentions FROM admin_chat WHERE id = ?",
            (last_id,),
        ).fetchone()
        if last:
            item = _rowd(last)
            last_user_id = int(item.get("user_id") or 0)
            mentions = _parse_mentions(item.get("mentions"))
    return {
        "last_id": last_id,
        "total": total,
        "last_user_id": last_user_id,
        "mentions": mentions,
    }


def post_admin_chat(conn, user: dict, payload: dict) -> dict:
    _ensure_admin_chat(conn)
    text = str(payload.get("text") or "").strip()[:4000]
    kind = str(payload.get("kind") or "text").strip().lower()
    file_url = str(payload.get("file_url") or "")
    file_name = str(payload.get("file_name") or "")
    mime = str(payload.get("mime") or "")
    try:
        duration = int(payload.get("duration_ms") or 0)
    except Exception:
        duration = 0
    if not text and not file_url:
        return {"ok": False, "message": "Пустое сообщение"}
    if not file_url:
        kind = "text"
    reply_to = 0
    reply_name = ""
    reply_text = ""
    reply_kind = ""
    try:
        reply_to = int(payload.get("reply_to") or 0)
    except Exception:
        reply_to = 0
    if reply_to > 0:
        src = conn.execute("SELECT * FROM admin_chat WHERE id = ?", (reply_to,)).fetchone()
        if src:
            srcd = _rowd(src)
            reply_name = str(srcd.get("user_name") or srcd.get("user_email") or "Админ")[:80]
            snippet = str(srcd.get("text") or "").strip()
            rkind = str(srcd.get("kind") or "text")
            if not snippet:
                snippet = {"image": "Фото", "video": "Видео", "audio": "Голосовое", "file": "Файл"}.get(rkind, "Сообщение")
            reply_text = snippet[:140]
            reply_kind = rkind
        else:
            reply_to = 0
    mentions = _resolve_mentions(conn, text, payload)
    now = int(time.time() * 1000)
    cur = conn.execute(
        """INSERT INTO admin_chat (user_id, user_name, user_email, kind, text, file_url, file_name, mime, duration_ms, created_at, reply_to, reply_name, reply_text, reply_kind, mentions)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            int(user.get("id") or 0),
            str(user.get("name") or user.get("email") or "Админ"),
            str(user.get("email") or ""),
            kind or "text",
            text,
            file_url,
            file_name[:120],
            mime[:120],
            max(0, duration),
            now,
            reply_to,
            reply_name,
            reply_text,
            reply_kind,
            json.dumps(mentions),
        ),
    )
    row = conn.execute("SELECT * FROM admin_chat WHERE id = ?", (cur.lastrowid,)).fetchone()
    return {"ok": True, "message": _chat_item(conn, row)}


def delete_admin_chat(conn, user: dict, mid: int) -> dict:
    _ensure_admin_chat(conn)
    row = conn.execute("SELECT * FROM admin_chat WHERE id = ?", (int(mid),)).fetchone()
    if not row:
        return {"ok": False, "message": "Сообщение не найдено"}
    item = _rowd(row)
    uid = int(user.get("id") or 0)
    is_owner = features.is_platform_owner(user)
    if int(item.get("user_id") or 0) != uid and not is_owner:
        return {"ok": False, "message": "Можно удалить только своё сообщение"}
    url = str(item.get("file_url") or "")
    conn.execute("DELETE FROM admin_chat WHERE id = ?", (int(mid),))
    if "/uploads/ac-" in url:
        try:
            from server import UPLOADS
            from urllib.parse import urlparse

            name = os.path.basename(urlparse(url).path)
            if name.startswith("ac-"):
                fs = UPLOADS / name
                if fs.is_file():
                    fs.unlink()
        except Exception:
            pass
    return {"ok": True}


def list_users_payload(conn, params: dict | None = None) -> list:
    q = _query(params or {})
    out = []
    for row in conn.execute("SELECT * FROM users ORDER BY id ASC").fetchall():
        u = _rowd(row)
        uid = int(u.get("id") or 0)
        ips = [
            r["ip"]
            for r in conn.execute(
                "SELECT ip FROM user_login_ips WHERE user_id = ?",
                (uid,),
            ).fetchall()
        ]
        proj_count = int(
            conn.execute(
                "SELECT COUNT(*) FROM project WHERE COALESCE(owner_user_id, 0) = ?",
                (uid,),
            ).fetchone()[0]
        )
        item = {
            "id": uid,
            "email": u.get("email") or "",
            "name": u.get("name") or "",
            "tag": u.get("tag") or "",
            "role": u.get("role") or "",
            "created_at": int(u.get("created_at") or 0),
            "created_at_fmt": _fmt_ts(u.get("created_at")),
            "projects_count": proj_count,
            "projects_blocked": bool(int(u.get("projects_blocked") or 0)),
            "account_blocked": bool(int(u.get("account_blocked") or 0)),
            "status": "BLOCKED" if int(u.get("account_blocked") or 0) else "ACTIVE",
            "is_platform_admin": features.is_platform_admin(u),
            "ips": ips,
        }
        if q and not (
            _match_any(q, uid, u.get("email"), u.get("name"), u.get("tag"), *ips)
            or (q.isdigit() and str(uid) == q)
        ):
            continue
        out.append(item)
    return out


def user_detail_payload(conn, uid: int) -> dict | None:
    u = features.user_by_id(conn, uid)
    if not u:
        return None
    ips = []
    for r in conn.execute(
        "SELECT ip, first_seen, last_seen, hits FROM user_login_ips WHERE user_id = ? ORDER BY last_seen DESC",
        (uid,),
    ).fetchall():
        row = _rowd(r)
        row["ip_blocked"] = features.is_user_ip_blocked(conn, row.get("ip") or "")
        row["first_seen_fmt"] = _fmt_ts(row.get("first_seen"))
        row["last_seen_fmt"] = _fmt_ts(row.get("last_seen"))
        ips.append(row)
    for ip in ips:
        ip["first_seen_fmt"] = _fmt_ts(ip.get("first_seen"))
        ip["last_seen_fmt"] = _fmt_ts(ip.get("last_seen"))
    projects = []
    for row in conn.execute(
        "SELECT * FROM project WHERE COALESCE(owner_user_id, 0) = ? ORDER BY id ASC",
        (uid,),
    ).fetchall():
        p = _rowd(row)
        pid = int(p.get("id") or 0)
        st = _project_status(conn, pid)
        servers = [
            _rowd(s)
            for s in conn.execute(
                "SELECT id, name, hostname, server_ip, port, paired, connected, last_seen FROM servers WHERE project_id = ?",
                (pid,),
            ).fetchall()
        ]
        projects.append(
            {
                "id": pid,
                "name": p.get("name") or "",
                "domain": p.get("domain") or "",
                "created_at": int(p.get("created_at") or 0),
                "created_at_fmt": _fmt_ts(p.get("created_at")),
                "servers": servers,
                "server_ip": features.project_server_endpoint(conn, pid),
                **st,
            }
        )
    return {
        "id": uid,
        "email": u.get("email") or "",
        "name": u.get("name") or "",
        "tag": u.get("tag") or "",
        "role": u.get("role") or "",
        "steam_id": u.get("steam_id") or "",
        "created_at": int(u.get("created_at") or 0),
        "created_at_fmt": _fmt_ts(u.get("created_at")),
        "projects_blocked": bool(int(u.get("projects_blocked") or 0)),
        "account_blocked": bool(int(u.get("account_blocked") or 0)),
        "account_blocked_reason": str(u.get("account_blocked_reason") or ""),
        "status": "BLOCKED" if int(u.get("account_blocked") or 0) else "ACTIVE",
        "ips": ips,
        "projects": projects,
        "is_platform_admin": features.is_platform_admin(u),
    }


def list_projects_payload(conn, params: dict | None = None) -> list:
    q = _query(params or {})
    out = []
    for row in conn.execute("SELECT * FROM project ORDER BY id ASC").fetchall():
        p = _rowd(row)
        pid = int(p.get("id") or 0)
        owner_id = int(p.get("owner_user_id") or 0)
        owner = features.user_by_id(conn, owner_id) if owner_id else None
        st = _project_status(conn, pid)
        srv = conn.execute(
            "SELECT server_ip, port, hostname FROM servers WHERE project_id = ? ORDER BY last_seen DESC LIMIT 1",
            (pid,),
        ).fetchone()
        server_ip = features.project_server_endpoint(conn, pid)
        if not server_ip and srv:
            server_ip = features.format_server_endpoint(str(srv["server_ip"] or ""), int(srv["port"] or 0))
        item = {
            "id": pid,
            "name": p.get("name") or "",
            "domain": p.get("domain") or "",
            "owner_user_id": owner_id,
            "owner_email": (owner or {}).get("email") or "",
            "owner_name": (owner or {}).get("name") or "",
            "server_ip": server_ip,
            "created_at": int(p.get("created_at") or 0),
            "created_at_fmt": _fmt_ts(p.get("created_at")),
            **st,
        }
        if q and not (
            _match_any(q, pid, p.get("name"), p.get("domain"), server_ip, owner_id, (owner or {}).get("email"))
            or (q.isdigit() and (str(pid) == q or str(owner_id) == q))
        ):
            continue
        out.append(item)
    return out


def list_server_ips_payload(conn, params: dict | None = None) -> list:
    """Every row in servers, plus leftover registry/blocked IPs. Never unique-by-IP-only."""
    q = _query(params or {})
    try:
        rows = conn.execute(
            """SELECT s.id, s.name, s.hostname, s.server_ip, s.port, s.paired, s.connected, s.last_seen,
                      s.project_id,
                      p.name AS project_name, p.domain, p.owner_user_id, p.blocked, p.admin_frozen,
                      u.email AS owner_email, u.name AS owner_name
               FROM servers s
               LEFT JOIN project p ON p.id = s.project_id
               LEFT JOIN users u ON u.id = p.owner_user_id
               ORDER BY s.project_id ASC, s.id ASC"""
        ).fetchall()
    except Exception:
        rows = conn.execute(
            """SELECT s.*, p.name AS project_name, p.domain, p.owner_user_id, p.blocked, p.admin_frozen,
                      u.email AS owner_email, u.name AS owner_name
               FROM servers s
               LEFT JOIN project p ON p.id = s.project_id
               LEFT JOIN users u ON u.id = p.owner_user_id
               ORDER BY s.id ASC"""
        ).fetchall()
    out = []
    seen_keys = set()
    for row in rows:
        try:
            r = _rowd(row)
            pid = int(r.get("project_id") or 0)
            sid = int(r.get("id") or 0)
            raw_ip = str(r.get("server_ip") or "").strip()
            host, port_n = features.parse_server_host_port(raw_ip, int(r.get("port") or 0))
            if not host:
                host, extra = features.parse_server_host_port(str(r.get("hostname") or ""), port_n)
                if extra:
                    port_n = extra
            if host in ("0.0.0.0", "localhost", "::1"):
                host = ""
            endpoint = features.format_server_endpoint(host, port_n)
            key = (sid, pid, host or "", int(port_n or 0))
            if sid and key in seen_keys:
                continue
            if sid:
                seen_keys.add(key)
            if pid and sid and host:
                try:
                    features.sync_server_ip_registry(conn, pid, sid, host)
                except Exception:
                    pass
            st = {"status": "unknown"}
            try:
                st = _project_status(conn, pid) if pid else st
            except Exception:
                pass
            heartbeat = False
            try:
                last = int(r.get("last_seen") or 0)
                if last > 10**12:
                    last = last // 1000
                heartbeat = bool(int(r.get("paired") or 0) and last > 0 and last > int(time.time()) - 90)
            except Exception:
                heartbeat = bool(r.get("connected"))
            blocked_ip = features.is_server_ip_blocked(conn, host) if host else False
            name = str(r.get("name") or r.get("hostname") or "") or (f"Server #{sid}" if sid else "")
            item = {
                "id": sid,
                "server_id": sid,
                "name": name,
                "server_name": name,
                "hostname": str(r.get("hostname") or name),
                "server_ip": host or "",
                "ip": host or "",
                "port": int(port_n or 0),
                "endpoint": endpoint or (f"{host}:{port_n}" if host and port_n else host),
                "address": endpoint or host or "",
                "project_id": pid,
                "project_name": r.get("project_name") or "",
                "owner_user_id": int(r.get("owner_user_id") or 0),
                "owner_email": r.get("owner_email") or "",
                "owner_name": r.get("owner_name") or "",
                "updated_at": int(r.get("last_seen") or 0),
                "updated_at_fmt": _fmt_ts((int(r.get("last_seen") or 0) * 1000) if int(r.get("last_seen") or 0) < 10**12 else r.get("last_seen")),
                "ip_blocked": blocked_ip,
                "paired": bool(r.get("paired")),
                "connected": heartbeat,
                "status": "online" if heartbeat else "offline",
                "project_status": st.get("status"),
                "project_status_label": st.get("status_label"),
            }
            out.append(item)
        except Exception as exc:
            print("server-ip row skipped", type(exc).__name__, exc)
            continue
    # Registry rows that never made it into servers (legacy)
    for row in conn.execute(
        """SELECT si.server_ip, si.project_id, si.server_id, si.updated_at,
                  p.name AS project_name, p.owner_user_id,
                  u.email AS owner_email, u.name AS owner_name
           FROM server_ips si
           LEFT JOIN project p ON p.id = si.project_id
           LEFT JOIN users u ON u.id = p.owner_user_id"""
    ).fetchall():
        r = _rowd(row)
        host, port_n = features.parse_server_host_port(str(r.get("server_ip") or ""), 0)
        pid = int(r.get("project_id") or 0)
        sid = int(r.get("server_id") or 0)
        key = (sid, pid, host, port_n)
        if not host or key in seen_keys:
            continue
        if any(it.get("ip") == host and it.get("project_id") == pid and (not port_n or it.get("port") == port_n) for it in out):
            continue
        seen_keys.add(key)
        st = _project_status(conn, pid) if pid else {"status": "unknown"}
        endpoint = features.format_server_endpoint(host, port_n)
        out.append({
            "id": sid,
            "server_id": sid,
            "name": "",
            "server_name": "",
            "hostname": "",
            "server_ip": host,
            "ip": host,
            "port": int(port_n or 0),
            "endpoint": endpoint or host,
            "address": endpoint or host,
            "project_id": pid,
            "project_name": r.get("project_name") or "",
            "owner_user_id": int(r.get("owner_user_id") or 0),
            "owner_email": r.get("owner_email") or "",
            "owner_name": r.get("owner_name") or "",
            "updated_at": int(r.get("updated_at") or 0),
            "updated_at_fmt": _fmt_ts(r.get("updated_at")),
            "ip_blocked": features.is_server_ip_blocked(conn, host),
            "paired": False,
            "connected": False,
            "status": "offline",
            "project_status": st.get("status"),
            "project_status_label": st.get("status_label"),
        })
    blocked_only = conn.execute("SELECT server_ip, blocked_at, blocked_by, reason FROM blocked_server_ips").fetchall()
    for row in blocked_only:
        ip = str(row["server_ip"] or "")
        if not ip:
            continue
        if any(it.get("ip") == ip or it.get("server_ip") == ip for it in out):
            continue
        out.append(
            {
                "id": 0,
                "server_id": 0,
                "name": "",
                "server_name": "",
                "hostname": "",
                "server_ip": ip,
                "ip": ip,
                "port": 0,
                "endpoint": ip,
                "address": ip,
                "project_id": 0,
                "project_name": "",
                "owner_user_id": 0,
                "owner_email": "",
                "owner_name": "",
                "updated_at": int(row["blocked_at"] or 0),
                "updated_at_fmt": _fmt_ts(row["blocked_at"]),
                "ip_blocked": True,
                "paired": False,
                "connected": False,
                "status": "blocked",
                "project_status": "blocked_ip",
                "project_status_label": "IP заблокирован",
                "blocked_by": row["blocked_by"] or "",
                "reason": row["reason"] or "",
            }
        )
    if not q:
        return out
    filtered = []
    for item in out:
        if _match_any(
            q,
            item.get("server_ip"),
            item.get("endpoint"),
            item.get("name"),
            item.get("project_id"),
            item.get("owner_user_id"),
            item.get("project_name"),
            item.get("owner_email"),
            item.get("port"),
        ) or (q.isdigit() and q in (str(item.get("project_id")), str(item.get("owner_user_id")), str(item.get("server_id")), str(item.get("port")))):
            filtered.append(item)
    return filtered


def delete_project(conn, pid: int, actor: str = "") -> dict:
    row = _rowd(conn.execute("SELECT * FROM project WHERE id = ?", (pid,)).fetchone())
    if not row:
        return {"ok": False, "message": f"project #{pid} not found"}
    conn.execute("DELETE FROM servers WHERE project_id = ?", (pid,))
    conn.execute("DELETE FROM pair_codes WHERE project_id = ?", (pid,))
    conn.execute("DELETE FROM online_players WHERE project_id = ?", (pid,))
    conn.execute("DELETE FROM server_ips WHERE project_id = ?", (pid,))
    for table in (
        "queue", "chat", "alerts", "checks", "bans", "reports", "mutes",
        "comments", "kills", "bags", "bag_events", "audit", "player_sessions", "wallet_ops",
    ):
        try:
            conn.execute(f"DELETE FROM {table} WHERE project_id = ?", (pid,))
        except Exception:
            pass
    conn.execute("DELETE FROM project WHERE id = ?", (pid,))
    features.audit(conn, "admin.project.delete", {"id": pid, "actor": actor})
    return {"ok": True, "id": pid}


def delete_user(conn, uid: int, actor: str = "") -> dict:
    u = features.user_by_id(conn, uid)
    if not u:
        return {"ok": False, "message": "not found"}
    if str(u.get("email") or "").lower() == features.OWNER_EMAIL.lower():
        return {"ok": False, "message": "cannot delete owner"}
    for row in conn.execute("SELECT id FROM project WHERE COALESCE(owner_user_id, 0) = ?", (uid,)).fetchall():
        delete_project(conn, int(row["id"]), actor)
    conn.execute("DELETE FROM user_login_ips WHERE user_id = ?", (uid,))
    conn.execute("DELETE FROM staff_members WHERE user_id = ?", (uid,))
    conn.execute("DELETE FROM users WHERE id = ?", (uid,))
    features.audit(conn, "admin.user.delete", {"id": uid, "actor": actor})
    return {"ok": True, "id": uid}


def update_user(conn, uid: int, body: dict, actor: str = "") -> dict:
    u = features.user_by_id(conn, uid)
    if not u:
        return {"ok": False, "message": "not found"}
    name = body.get("name")
    if name is not None:
        name = str(name).strip()
        if not name:
            return {"ok": False, "message": "name required"}
        if len(name) > 64:
            return {"ok": False, "message": "name too long"}
        conn.execute("UPDATE users SET name = ? WHERE id = ?", (name, uid))
    email = body.get("email")
    if email is not None:
        email = str(email).lower().strip()
        if email and email != str(u.get("email") or "").lower():
            if conn.execute("SELECT id FROM users WHERE lower(email) = ? AND id != ?", (email, uid)).fetchone():
                return {"ok": False, "message": "email exists"}
            conn.execute("UPDATE users SET email = ? WHERE id = ?", (email, uid))
    password = body.get("password")
    if password:
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (features.hash_password(str(password)), uid),
        )
    if "is_platform_admin" in body:
        val = 1 if body.get("is_platform_admin") else 0
        conn.execute("UPDATE users SET is_platform_admin = ? WHERE id = ?", (val, uid))
    features.audit(conn, "admin.user.update", {"id": uid, "actor": actor})
    return {"ok": True, "user": user_detail_payload(conn, uid)}


def update_project(conn, pid: int, body: dict, actor: str = "") -> dict:
    row = _rowd(conn.execute("SELECT * FROM project WHERE id = ?", (pid,)).fetchone())
    if not row:
        return {"ok": False, "message": f"project #{pid} not found"}
    name = body.get("name")
    if name is not None:
        name = str(name).strip()
        if not name:
            return {"ok": False, "message": "name required"}
        if len(name) > 128:
            return {"ok": False, "message": "name too long"}
        conn.execute("UPDATE project SET name = ? WHERE id = ?", (name, pid))
    features.audit(conn, "admin.project.update", {"project_id": pid, "actor": actor})
    return {"ok": True, "project": project_detail_payload(conn, pid)}


def adjust_project_balance(conn, pid: int, body: dict, actor: str = "") -> dict:
    row = _rowd(conn.execute("SELECT * FROM project WHERE id = ?", (pid,)).fetchone())
    if not row:
        return {"ok": False, "message": f"project #{pid} not found"}
    try:
        amount = int(body.get("amount") or body.get("amount_kopecks") or 0)
    except Exception:
        amount = 0
    if not amount:
        return {"ok": False, "message": "amount required"}
    cur = features.project_balance(conn, pid)
    new_bal = max(0, cur + amount)
    conn.execute("UPDATE project SET balance = ? WHERE id = ?", (new_bal, pid))
    comment = str(body.get("comment") or body.get("reason") or f"admin:{actor}")
    features.add_wallet_op(conn, amount, comment, pid)
    features.audit(conn, "admin.project.balance", {"project_id": pid, "amount": amount, "actor": actor})
    st = _project_status(conn, pid)
    return {
        "ok": True,
        "project_id": pid,
        "balance_kopecks": new_bal,
        "balance_rub": round(new_bal / 100, 2),
        "project": {**_rowd(row), **st, "id": pid},
    }


def adjust_balance(conn, uid: int, body: dict, actor: str = "") -> dict:
    """Legacy user balance route — redirects to project balance."""
    try:
        pid = int(body.get("project_id") or 0)
    except Exception:
        pid = 0
    if not pid:
        row = conn.execute(
            "SELECT id FROM project WHERE COALESCE(owner_user_id, 0) = ? ORDER BY id ASC LIMIT 1",
            (uid,),
        ).fetchone()
        pid = int(row["id"]) if row else 0
    if not pid:
        return {"ok": False, "message": "project_id required"}
    return adjust_project_balance(conn, pid, body, actor)


def grant_subscription(conn, pid: int, body: dict, actor: str = "") -> dict:
    row = _rowd(conn.execute("SELECT * FROM project WHERE id = ?", (pid,)).fetchone())
    if not row:
        return {"ok": False, "message": f"project #{pid} not found"}

    action = str((body or {}).get("action") or "").strip().lower()
    if (body or {}).get("revoke") or action in ("revoke", "remove", "take"):
        conn.execute("UPDATE project SET paid_until = 0 WHERE id = ?", (pid,))
        features.audit(conn, "admin.subscription.revoke", {"project_id": pid, "actor": actor})
        try:
            features.add_wallet_op(conn, 0, "Подписка снята администратором", pid)
        except Exception as exc:
            print("revoke subscription wallet log failed", exc)
        return {
            "ok": True,
            "revoked": True,
            "plan": str(row.get("plan") or ""),
            "paid_until": 0,
            "project": next((p for p in list_projects_payload(conn) if p["id"] == pid), None),
        }

    slug = features.normalize_plan(str((body or {}).get("plan") or (body or {}).get("slug") or "plus"))
    try:
        days = int((body or {}).get("days") or (body or {}).get("duration_days") or 0)
    except Exception:
        days = 0
    if days <= 0:
        try:
            days = int((body or {}).get("months") or 0) * 30
        except Exception:
            days = 0
    if days <= 0:
        days = 30 if slug != "base" else 7
    days = max(1, min(days, 3650))

    now = features._now_ms()
    extend_ms = days * DAY_MS
    is_blocked = bool(int(row.get("blocked") or 0))
    # Always store subscription end in paid_until (ms since epoch) — single source of truth.
    current_paid = int(row.get("paid_until") or 0)
    if current_paid > now:
        new_paid = current_paid + extend_ms
    else:
        new_paid = now + extend_ms
    admin_frozen_val = 1 if is_blocked else 0
    conn.execute(
        "UPDATE project SET plan = ?, paid_until = ?, trial_ends_at = 0, admin_frozen = ? WHERE id = ?",
        (slug, new_paid, admin_frozen_val, pid),
    )
    if not is_blocked:
        conn.execute("UPDATE project SET admin_frozen = 0 WHERE id = ?", (pid,))
    features.audit(
        conn,
        "admin.subscription.grant",
        {"project_id": pid, "plan": slug, "days": days, "paid_until": new_paid, "actor": actor},
    )
    try:
        features.add_wallet_op(
            conn,
            0,
            f"Выдана подписка «{features.plan_title(slug)}» на {days} дн.",
            pid,
        )
    except Exception as exc:
        print("grant subscription wallet log failed", exc)
    return {
        "ok": True,
        "plan": slug,
        "days": days,
        "paid_until": new_paid,
        "paid_until_fmt": _fmt_ts(new_paid),
        "project": next((p for p in list_projects_payload(conn) if p["id"] == pid), None),
    }


def project_action(conn, pid: int, action: str, actor: str = "") -> dict:
    row = _rowd(conn.execute("SELECT * FROM project WHERE id = ?", (pid,)).fetchone())
    if not row:
        return {"ok": False, "message": f"project #{pid} not found"}
    now = features._now_ms()
    is_blocked = bool(int(row.get("blocked") or 0))
    if action == "freeze":
        if is_blocked:
            return {"ok": False, "message": "project is blocked — use unblock first"}
        conn.execute("UPDATE project SET admin_frozen = 1 WHERE id = ?", (pid,))
        features.freeze_project(conn, pid, "admin_freeze")
    elif action == "unfreeze":
        if is_blocked:
            return {"ok": False, "message": "project is blocked — use unblock, not unfreeze"}
        conn.execute("UPDATE project SET admin_frozen = 0 WHERE id = ?", (pid,))
        paid = int(row.get("paid_until") or 0)
        if paid <= now:
            conn.execute(
                "UPDATE project SET trial_ends_at = ? WHERE id = ? AND COALESCE(paid_until, 0) <= ?",
                (now + features.TRIAL_MS, pid, now),
            )
    elif action == "block":
        conn.execute("UPDATE project SET blocked = 1, admin_frozen = 1 WHERE id = ?", (pid,))
        features.freeze_project(conn, pid, "admin_block")
        features.on_admin_project_blocked(conn, pid)
    elif action == "unblock":
        conn.execute("UPDATE project SET blocked = 0, admin_frozen = 0 WHERE id = ?", (pid,))
        features.on_admin_project_unblocked(conn, pid)
    else:
        return {"ok": False, "message": "unknown action"}
    features.audit(conn, "admin.project." + action, {"project_id": pid, "actor": actor})
    # Avoid rebuilding full projects list (was freezing admin UI on unblock)
    detail = project_detail_payload(conn, pid)
    return {"ok": True, "project": detail}


def project_detail_payload(conn, pid: int) -> dict | None:
    pid = int(pid or 0)
    if not pid:
        return None
    row = conn.execute("SELECT * FROM project WHERE id = ?", (pid,)).fetchone()
    if not row:
        return None
    p = _rowd(row)
    st = _project_status(conn, pid)
    owner_id = int(p.get("owner_user_id") or 0)
    owner = features.user_by_id(conn, owner_id) if owner_id else None
    servers = [
        _rowd(s)
        for s in conn.execute(
            "SELECT id, name, hostname, server_ip, port, paired, connected, last_seen FROM servers WHERE project_id = ?",
            (pid,),
        ).fetchall()
    ]
    server_ip = features.project_server_endpoint(conn, pid)
    if not server_ip:
        for s in servers:
            ep = features.format_server_endpoint(str(s.get("server_ip") or ""), int(s.get("port") or 0))
            if ep:
                server_ip = ep
                break
    return {
        "id": pid,
        "name": p.get("name") or "",
        "domain": p.get("domain") or "",
        "avatar": p.get("avatar") or "",
        "created_at": int(p.get("created_at") or 0),
        "created_at_fmt": _fmt_ts(p.get("created_at")),
        "owner_user_id": owner_id,
        "owner_email": (owner or {}).get("email") or "",
        "owner_name": (owner or {}).get("name") or "",
        "servers": servers,
        "server_ip": server_ip,
        **st,
    }


def handle_api(handler, method: str, path: str, params: dict, body: dict | None):
    user = require_admin(handler)
    if not user:
        return True
    actor = str(user.get("email") or "")
    from server import db_call

    parts = [p for p in path.strip("/").split("/") if p]

    if method == "GET" and path == "/admin/api/stats":
        handler._json(db_call(stats_payload))
        return True
    if method == "GET" and path == "/admin/api/users":
        handler._json({"users": db_call(lambda c: list_users_payload(c, params))})
        return True
    if method == "GET" and path == "/admin/api/projects":
        handler._json({"projects": db_call(lambda c: list_projects_payload(c, params))})
        return True
    if method == "GET" and path == "/admin/api/server-ips":
        rows = db_call(lambda c: list_server_ips_payload(c, params))
        handler._json({
            "items": rows,
            "data": rows,
            "results": rows,
            "total": len(rows),
        })
        return True
    if method == "GET" and path == "/admin/api/plans":
        handler._json({"plans": plans_payload()})
        return True
    if method == "GET" and len(parts) == 4 and parts[0] == "admin" and parts[1] == "api" and parts[2] == "users":
        uid = int(parts[3])
        detail = db_call(lambda c: user_detail_payload(c, uid))
        if not detail:
            handler._json({"message": "not found"}, 404)
        else:
            handler._json(detail)
        return True

    if method == "GET" and len(parts) == 4 and parts[0] == "admin" and parts[1] == "api" and parts[2] == "projects":
        try:
            pid = int(parts[3])
        except Exception:
            handler._json({"message": "invalid project id"}, 400)
            return True
        detail = db_call(lambda c: project_detail_payload(c, pid))
        if not detail:
            handler._json({"message": "project not found", "id": pid}, 404)
        else:
            handler._json(detail)
        return True

    if method == "POST" and path in ("/admin/api/project-balance", "/admin/api/project-balance/"):
        try:
            pid = int((body or {}).get("project_id") or (body or {}).get("projectId") or 0)
        except Exception:
            pid = 0
        if not pid:
            handler._json({"ok": False, "message": "project_id required"}, 400)
            return True
        out = db_call(lambda c: adjust_project_balance(c, pid, body or {}, actor))
        handler._json(out, 400 if not out.get("ok") else 200)
        return True

    if method == "POST" and len(parts) == 5 and parts[0] == "admin" and parts[1] == "api" and parts[2] == "projects" and parts[4] == "balance":
        try:
            pid = int(parts[3])
        except Exception:
            handler._json({"ok": False, "message": "invalid project id"}, 400)
            return True
        out = db_call(lambda c: adjust_project_balance(c, pid, body or {}, actor))
        handler._json(out, 400 if not out.get("ok") else 200)
        return True

    if method == "PUT" and len(parts) == 4 and parts[0] == "admin" and parts[1] == "api" and parts[2] == "projects":
        try:
            pid = int(parts[3])
        except Exception:
            handler._json({"ok": False, "message": "invalid project id"}, 400)
            return True
        out = db_call(lambda c: update_project(c, pid, body or {}, actor))
        handler._json(out, 400 if not out.get("ok") else 200)
        return True

    if method == "POST" and len(parts) == 5 and parts[2] == "users":
        uid = int(parts[3])
        action = parts[4]
        reason = str((body or {}).get("reason") or "")

        def _user_act(conn):
            if action == "block":
                if features.is_protected_owner(conn, uid):
                    return {"ok": False, "message": "Нельзя заблокировать владельца pcigru@gmail.com"}
                features.set_user_account_blocked(conn, uid, True, reason or "admin panel")
                return {"ok": True, "user": user_detail_payload(conn, uid)}
            if action == "unblock":
                features.set_user_account_blocked(conn, uid, False, "")
                features.set_user_projects_blocked(conn, uid, False)
                return {"ok": True, "user": user_detail_payload(conn, uid)}
            return {"ok": False, "message": "unknown action"}

        out = db_call(_user_act)
        handler._json(out, 400 if not out.get("ok") else 200)
        return True

    if method == "POST" and len(parts) == 5 and parts[2] == "user-ips":
        ip = parts[3]
        action = parts[4]
        reason = str((body or {}).get("reason") or "")

        def _uip(conn):
            if action == "block":
                owner = conn.execute("SELECT id FROM users WHERE lower(email) = ?", (features.OWNER_EMAIL.lower(),)).fetchone()
                if owner:
                    used = conn.execute(
                        "SELECT 1 FROM user_login_ips WHERE user_id = ? AND ip = ? LIMIT 1",
                        (int(owner["id"] or 0), ip),
                    ).fetchone()
                    if used:
                        return {"ok": False, "message": "Нельзя заблокировать IP владельца"}
                features.block_user_ip(conn, ip, actor, reason or "admin panel")
                return {"ok": True, "ip": ip, "blocked": True}
            if action == "unblock":
                features.unblock_user_ip(conn, ip, actor)
                return {"ok": True, "ip": ip, "blocked": False}
            return {"ok": False, "message": "unknown action"}

        out = db_call(_uip)
        handler._json(out, 400 if not out.get("ok") else 200)
        return True

    if method == "PUT" and len(parts) == 4 and parts[2] == "users":
        uid = int(parts[3])
        out = db_call(lambda c: update_user(c, uid, body or {}, actor))
        handler._json(out, 400 if not out.get("ok") else 200)
        return True

    if method == "POST" and len(parts) == 5 and parts[2] == "users" and parts[4] == "balance":
        uid = int(parts[3])
        out = db_call(lambda c: adjust_balance(c, uid, body or {}, actor))
        handler._json(out, 400 if not out.get("ok") else 200)
        return True

    if method == "DELETE" and len(parts) == 4 and parts[2] == "users":
        uid = int(parts[3])
        out = db_call(lambda c: delete_user(c, uid, actor))
        handler._json(out, 400 if not out.get("ok") else 200)
        return True

    if method == "DELETE" and len(parts) == 4 and parts[2] == "projects":
        pid = int(parts[3])
        out = db_call(lambda c: delete_project(c, pid, actor))
        handler._json(out, 404 if out.get("message") == "not found" else 200)
        return True

    if method == "POST" and path == "/admin/api/subscription":
        try:
            pid = int((body or {}).get("project_id") or (body or {}).get("projectId") or 0)
        except Exception:
            pid = 0
        if not pid:
            handler._json({"ok": False, "message": "project_id required"}, 400)
            return True
        out = db_call(lambda c: grant_subscription(c, pid, body or {}, actor))
        handler._json(out, 400 if not out.get("ok") else 200)
        return True

    if method == "POST" and len(parts) == 5 and parts[2] == "projects":
        pid = int(parts[3])
        action = parts[4]
        if action == "balance":
            out = db_call(lambda c: adjust_project_balance(c, pid, body or {}, actor))
            handler._json(out, 400 if not out.get("ok") else 200)
            return True
        if action == "subscription":
            out = db_call(lambda c: grant_subscription(c, pid, body or {}, actor))
            handler._json(out, 400 if not out.get("ok") else 200)
            return True
        if action in ("freeze", "unfreeze", "block", "unblock"):
            out = db_call(lambda c: project_action(c, pid, action, actor))
            handler._json(out, 400 if not out.get("ok") else 200)
            return True
        handler._json({"ok": False, "message": "unknown action", "action": action}, 400)
        return True

    if method == "POST" and len(parts) == 5 and parts[2] == "server-ips":
        ip = parts[3]
        action = parts[4]
        reason = str((body or {}).get("reason") or "")

        def _ip(conn):
            if action == "block":
                features.block_server_ip(conn, ip, actor, reason)
                for row in conn.execute(
                    "SELECT DISTINCT project_id FROM server_ips WHERE server_ip = ?",
                    (ip,),
                ).fetchall():
                    features.enforce_blocked_server_ip(conn, int(row["project_id"]), ip)
                return {"ok": True}
            if action == "unblock":
                features.unblock_server_ip(conn, ip, actor)
                return {"ok": True}
            return {"ok": False, "message": "unknown action"}

        out = db_call(_ip)
        handler._json(out, 400 if not out.get("ok") else 200)
        return True

    if method == "GET" and path == "/admin/api/me":
        handler._json({
            "id": int(user.get("id") or 0),
            "email": user.get("email") or "",
            "name": user.get("name") or "",
            "role": features.platform_admin_role(user),
            "is_owner": features.is_platform_owner(user),
        })
        return True

    if method == "GET" and path == "/admin/api/admins":
        try:
            admins = db_call(features.list_platform_admins)
        except Exception as exc:
            print("admin list failed", exc)
            admins = []
        for row in admins or []:
            try:
                row["online"] = admin_is_online(int(row.get("id") or 0), int(row.get("last_seen_at") or 0))
            except Exception:
                row["online"] = False
        handler._json({"admins": admins or [], "is_owner": features.is_platform_owner(user)})
        return True

    if method == "POST" and path == "/admin/api/admins":
        if not features.is_platform_owner(user):
            handler._json({"ok": False, "message": "Только главный администратор может добавлять администраторов"}, 403)
            return True
        email = str((body or {}).get("email") or "")
        out = db_call(lambda c: features.add_platform_admin(c, email, actor))
        handler._json(out, 400 if not out.get("ok") else 200)
        return True

    if method == "DELETE" and len(parts) == 4 and parts[0] == "admin" and parts[1] == "api" and parts[2] == "admins":
        if not features.is_platform_owner(user):
            handler._json({"ok": False, "message": "Только главный администратор может удалять администраторов"}, 403)
            return True
        try:
            uid = int(parts[3])
        except Exception:
            handler._json({"ok": False, "message": "invalid id"}, 400)
            return True
        out = db_call(lambda c: features.remove_platform_admin(c, uid, actor))
        handler._json(out, 400 if not out.get("ok") else 200)
        return True

    if method == "GET" and path == "/admin/api/audit":
        raw_cat = params.get("category") or params.get("tab") or ""
        if isinstance(raw_cat, list):
            raw_cat = raw_cat[0] if raw_cat else ""
        raw_pid = params.get("project_id") or params.get("project") or 0
        if isinstance(raw_pid, list):
            raw_pid = raw_pid[0] if raw_pid else 0
        try:
            pid = int(raw_pid or 0)
        except Exception:
            pid = 0
        try:
            items = db_call(lambda c: features.list_admin_audit(c, str(raw_cat or ""), pid))
        except Exception as exc:
            print("admin audit failed", exc)
            items = []
        try:
            projects = db_call(lambda c: [
                {"id": int(r["id"]), "name": r["name"] or ("#" + str(r["id"]))}
                for r in c.execute("SELECT id, name FROM project ORDER BY id DESC").fetchall()
            ])
        except Exception:
            projects = []
        handler._json({"items": items or [], "projects": projects or []})
        return True

    if method == "GET" and path == "/admin/api/transactions":
        raw_pid = params.get("project_id") or params.get("project") or 0
        if isinstance(raw_pid, list):
            raw_pid = raw_pid[0] if raw_pid else 0
        try:
            pid = int(raw_pid or 0)
        except Exception:
            pid = 0
        try:
            items = db_call(lambda c: features.list_admin_transactions(c, pid))
        except Exception as exc:
            print("admin transactions failed", exc)
            items = []
        handler._json({"items": items or [], "data": items or [], "results": items or [], "total": len(items or []), "project_id": pid})
        return True

    if method == "GET" and path in ("/admin/api/chat", "/admin/api/chat/"):
        raw_after = params.get("after") or params.get("after_id") or 0
        if isinstance(raw_after, list):
            raw_after = raw_after[0] if raw_after else 0
        raw_limit = params.get("limit") or 80
        if isinstance(raw_limit, list):
            raw_limit = raw_limit[0] if raw_limit else 80
        try:
            after_id = int(raw_after or 0)
            limit = int(raw_limit or 80)
        except Exception:
            after_id, limit = 0, 80
        handler._json({"messages": db_call(lambda c: list_admin_chat(c, after_id, limit))})
        return True

    if method == "GET" and path == "/admin/api/chat/peek":
        handler._json(db_call(admin_chat_peek))
        return True

    if method == "POST" and path in ("/admin/api/chat", "/admin/api/chat/"):
        payload = dict(body or {})
        raw = payload.pop("_multipart_raw", None)
        ctype = payload.pop("_content_type", "")
        if raw:
            fields, file_part = _parse_multipart(raw, ctype)
            payload.update(fields)
            if file_part and file_part.get("data"):
                try:
                    kind, url, fname = _save_chat_file(
                        file_part["data"],
                        file_part.get("filename") or "",
                        file_part.get("mime") or "",
                        fields.get("kind") or payload.get("kind") or "",
                    )
                except ValueError as exc:
                    handler._json({"ok": False, "message": str(exc)}, 400)
                    return True
                payload["kind"] = kind
                payload["file_url"] = url
                payload["file_name"] = fname
                payload["mime"] = file_part.get("mime") or ""
        elif payload.get("data"):
            try:
                raw_b = __import__("base64").b64decode(str(payload.get("data") or ""), validate=False)
                kind, url, fname = _save_chat_file(
                    raw_b,
                    str(payload.get("filename") or payload.get("file_name") or "file"),
                    str(payload.get("mime") or ""),
                    str(payload.get("kind") or ""),
                )
            except Exception as exc:
                handler._json({"ok": False, "message": str(exc) or "Не удалось сохранить файл"}, 400)
                return True
            payload["kind"] = kind
            payload["file_url"] = url
            payload["file_name"] = fname
        out = db_call(lambda c: post_admin_chat(c, user, payload))
        handler._json(out, 400 if not out.get("ok") else 200)
        return True

    if method == "DELETE" and len(parts) == 4 and parts[0] == "admin" and parts[1] == "api" and parts[2] == "chat":
        try:
            mid = int(parts[3])
        except Exception:
            handler._json({"ok": False, "message": "invalid id"}, 400)
            return True
        out = db_call(lambda c: delete_admin_chat(c, user, mid))
        handler._json(out, 400 if not out.get("ok") else 200)
        return True

    handler._json({"message": "not found"}, 404)
    return True
