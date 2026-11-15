"""Auth, billing, webhooks, audit, mutes, bags, stats helpers for Checkapp."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import ssl
import threading
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from pathlib import Path
from typing import Any

UPLOADS = Path(__file__).resolve().parent / "data" / "uploads"
UPLOADS.mkdir(parents=True, exist_ok=True)
TRIAL_MS = 7 * 24 * 60 * 60 * 1000
PAID_UNTIL_FAR = 4102444800000
_REQUEST = threading.local()
# Assigned by server.py after emit_realtime exists. Never a global/cross-project bus.
realtime_emit = None


def load_dotenv(path: Path | None = None) -> None:
    """Load KEY=VALUE from .env without overriding real process environment."""
    candidates = []
    if path is not None:
        candidates.append(Path(path))
    here = Path(__file__).resolve().parent
    candidates.extend([here / ".env", here.parent / ".env"])
    seen = set()
    for env_path in candidates:
        try:
            resolved = env_path.resolve()
        except Exception:
            resolved = env_path
        if resolved in seen or not env_path.is_file():
            continue
        seen.add(resolved)
        try:
            text = env_path.read_text(encoding="utf-8")
        except Exception:
            continue
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip()
            if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
                val = val[1:-1]
            if key and key not in os.environ:
                os.environ[key] = val


load_dotenv()
TOKEN_SECRET = os.environ.get("CHECKAPP_TOKEN_SECRET") or "checkapp-local-token-secret"


def set_request_project(pid: int) -> None:
    try:
        _REQUEST.project_id = int(pid or 0)
    except Exception:
        _REQUEST.project_id = 0


def request_project_id() -> int:
    try:
        return int(getattr(_REQUEST, "project_id", 0) or 0)
    except Exception:
        return 0


def set_request_user(uid: int) -> None:
    try:
        _REQUEST.user_id = int(uid or 0)
    except Exception:
        _REQUEST.user_id = 0


def request_user_id() -> int:
    try:
        return int(getattr(_REQUEST, "user_id", 0) or 0)
    except Exception:
        return 0


def as_epoch_ms(value) -> int:
    """Normalize timestamps: seconds → ms. Never treat 5-minute leftovers as a trial."""
    try:
        ts = int(value or 0)
    except (TypeError, ValueError):
        return 0
    if ts <= 0:
        return 0
    if 1_000_000_000 <= ts < 10_000_000_000:
        return ts * 1000
    return ts


GLOBAL_SETTING_PREFIXES = (
    "client_avatar",
    "client_discord",
    "client_steam",
    "client_google",
    "oauth_discord",
    "pair_token_",
    "platega_",
    "player_exempt_",
)


def is_global_setting_key(key: str) -> bool:
    text = str(key or "")
    return any(text.startswith(prefix) for prefix in GLOBAL_SETTING_PREFIXES)


def scoped_setting_key(key: str, pid: int | None = None) -> str | None:
    """Project settings must never share a global key. pid=0 → no lookup/write."""
    text = str(key or "")
    if is_global_setting_key(text):
        return text
    if text.startswith("p") and ":" in text[:12]:
        return text
    if pid is None:
        pid = request_project_id()
    try:
        pid = int(pid or 0)
    except Exception:
        pid = 0
    if not pid:
        return None
    return f"p{pid}:{text}"


def parse_server_host_port(ip: str, port: int = 0) -> tuple[str, int]:
    """Return (host, port) from stored IP / hostname / host:port."""
    host = str(ip or "").strip()
    try:
        port_n = int(port or 0)
    except Exception:
        port_n = 0
    if not host:
        return "", port_n
    if host.startswith("[") and "]" in host:
        inner = host[1 : host.index("]")]
        rest = host[host.index("]") + 1 :].lstrip(":")
        host = inner
        if rest.isdigit() and not port_n:
            port_n = int(rest)
        return host, port_n
    if host.count(":") == 1 and "." in host:
        left, right = host.rsplit(":", 1)
        if right.isdigit():
            if not port_n:
                port_n = int(right)
            host = left
    return host, port_n


def format_server_endpoint(ip: str, port: int = 0) -> str:
    host, port_n = parse_server_host_port(ip, port)
    if host and port_n:
        if ":" in host and not host.startswith("["):
            return f"[{host}]:{port_n}"
        return f"{host}:{port_n}"
    return host


def project_server_endpoint(conn, project_id: int) -> str:
    """Connected game server as IP:PORT for this project only."""
    try:
        pid = int(project_id or 0)
    except Exception:
        pid = 0
    if not pid:
        return ""
    row = conn.execute(
        """SELECT server_ip, hostname, port FROM servers
           WHERE project_id = ? AND COALESCE(paired, 0) = 1
           ORDER BY last_seen DESC, id DESC LIMIT 1""",
        (pid,),
    ).fetchone()
    ip = ""
    port = 0
    if row:
        ip = str(row["server_ip"] or "").strip()
        if not ip:
            host = str(row["hostname"] or "").strip()
            parsed, extra_port = parse_server_host_port(host, 0)
            if re.match(r"^\d{1,3}(?:\.\d{1,3}){3}$", parsed or ""):
                ip = parsed
                if extra_port and not port:
                    port = extra_port
        try:
            port = int(row["port"] or 0) or port
        except Exception:
            pass
        endpoint = format_server_endpoint(ip, port)
        if endpoint:
            return endpoint
    reg = conn.execute(
        """SELECT server_ip FROM server_ips
           WHERE project_id = ? AND server_ip != ''
           ORDER BY updated_at DESC LIMIT 1""",
        (pid,),
    ).fetchone()
    if reg:
        return format_server_endpoint(str(reg["server_ip"] or ""), port)
    return ""


def init_empty_project(conn, project_id: int) -> None:
    """New project: empty webhooks/settings, never a copy of another project."""
    try:
        pid = int(project_id or 0)
    except Exception:
        pid = 0
    if not pid:
        return
    prev = request_project_id()
    try:
        set_request_project(pid)
        ensure_webhook_catalog(conn)
        for key, empty in (
            ("court_discord", {}),
            ("court_commands", []),
            ("court_api", {}),
            ("autokick_rules", {}),
            ("ban_sync", {"is_public": False, "share": False, "share_details": False, "share_moders": False, "share_reasons": True, "enabled": False}),
        ):
            lookup = scoped_setting_key(key, pid)
            if not lookup:
                continue
            exists = conn.execute("SELECT 1 FROM settings WHERE key = ?", (lookup,)).fetchone()
            if not exists:
                conn.execute(
                    "INSERT INTO settings (key, value) VALUES (?, ?)",
                    (lookup, json.dumps(empty, ensure_ascii=False)),
                )
    except Exception:
        pass
    finally:
        set_request_project(prev)


def actor_role_for(conn, user_id: int, project_id: int = 0) -> str:
    """Snapshot role at write time: owner of this project, otherwise staff."""
    uid = int(user_id or 0)
    pid = int(project_id or request_project_id() or 0)
    if not uid:
        return "system"
    if pid:
        try:
            prow = conn.execute("SELECT owner_user_id FROM project WHERE id = ?", (pid,)).fetchone()
            if prow and int(prow["owner_user_id"] or 0) == uid:
                return "owner"
        except Exception:
            pass
    return "staff"


SYSTEM_ACTOR_NAMES = {
    "", "system", "plugin", "server", "rustcheck", "checkapp", "rustapp",
    "project", "org", "organization", "discord", "webhook", "admin",
    "staff", "moderator", "сотрудник", "user", "rystcheck", "rust check",
}

_FAKE_EMAIL_DOMAINS = {
    "steam.rustcheck.local",
    "discord.rustcheck.local",
    "google.rustcheck.local",
    "rustcheck.local",
    "checkapp.local",
}


_PROJECT_LABELS = {"at": 0.0, "labels": set()}
_PROJECT_LABELS_LOCK = threading.Lock()


def load_project_labels(conn=None) -> set[str]:
    """Project name/domain must never be used as a staff @username."""
    now = time.time()
    with _PROJECT_LABELS_LOCK:
        cached = set(_PROJECT_LABELS["labels"] or set())
        fresh = bool(cached) and (now - float(_PROJECT_LABELS["at"] or 0) < 30)
    if fresh and conn is None:
        return cached
    labels = set(cached)
    if conn is not None:
        try:
            for row in conn.execute("SELECT COALESCE(name,''), COALESCE(domain,'') FROM project"):
                for val in row:
                    text = str(val or "").strip().lower().lstrip("@")
                    if not text:
                        continue
                    labels.add(text)
                    labels.add(text.replace(" ", ""))
                    labels.add(text.replace("-", ""))
                    labels.add(text.replace(" ", "").replace("-", ""))
        except Exception:
            pass
        with _PROJECT_LABELS_LOCK:
            _PROJECT_LABELS["at"] = now
            _PROJECT_LABELS["labels"] = set(labels)
    return labels


def is_generic_staff_label(text: str, conn=None) -> bool:
    t = str(text or "").strip().lower().lstrip("@")
    if not t:
        return True
    compact = t.replace(" ", "").replace("-", "")
    if t in SYSTEM_ACTOR_NAMES or compact in SYSTEM_ACTOR_NAMES:
        return True
    if t in ("удалённый сотрудник", "удаленный сотрудник"):
        return True
    labels = load_project_labels(conn)
    return t in labels or compact in labels


def staff_public_name(user: dict | None = None, snap_name: str = "", snap_email: str = "", conn=None) -> str:
    """Visible staff name: account name first, never staff/admin/project."""
    if conn is not None:
        load_project_labels(conn)
    user = user if isinstance(user, dict) else {}
    email = str(user.get("email") or snap_email or "").strip()
    live = human_actor_name(str(user.get("name") or ""), email, "")
    if live and not is_generic_staff_label(live, conn):
        return live
    snap = human_actor_name(snap_name, snap_email or email, "")
    if snap and not is_generic_staff_label(snap, conn):
        return snap
    tag = str(user.get("tag") or "").strip().lstrip("@")
    if tag and not is_generic_staff_label(tag, conn):
        return tag
    if email and "@" in email:
        local = email.split("@")[0]
        if local and not is_generic_staff_label(local, conn):
            return local
    return live or snap or ""


def _handle_slug(text: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_]+", "_", str(text or "").strip().lstrip("@")).strip("_")
    return slug[:24]


def staff_public_tag(user: dict | None = None, name: str = "", conn=None) -> str:
    """Personal @handle. Never empty, never the project, never the RustApp system label."""
    if conn is not None:
        load_project_labels(conn)
    user = user if isinstance(user, dict) else {}

    def usable(val: str) -> bool:
        text = str(val or "").strip().lstrip("@")
        if not text or is_generic_staff_label(text, conn):
            return False
        if text.isdigit() and len(text) >= 16:
            return False
        return True

    tag = str(user.get("tag") or "").strip().lstrip("@")
    if usable(tag):
        return tag
    email = str(user.get("email") or "").strip()
    local = email.split("@")[0] if "@" in email else ""
    domain = email.split("@")[1].lower() if "@" in email else ""
    if domain not in _FAKE_EMAIL_DOMAINS and usable(local):
        return local
    n = _handle_slug(name or user.get("name") or "")
    if usable(n):
        return n
    try:
        uid = int(user.get("id") or 0)
    except Exception:
        uid = 0
    if uid:
        return f"user{uid}"
    return ""


def human_actor_name(name: str, email: str = "", fallback: str = "") -> str:
    """Never treat the product/plugin/project label as the human who clicked."""
    text = str(name or "").strip()
    if text.lower() in SYSTEM_ACTOR_NAMES or text.lower().replace(" ", "") in SYSTEM_ACTOR_NAMES:
        text = ""
    if text:
        return text
    mail = str(email or "").strip()
    if mail and "@" in mail:
        return mail.split("@")[0]
    alt = str(fallback or "").strip()
    if alt and alt.lower() not in SYSTEM_ACTOR_NAMES:
        return alt
    return ""


def request_actor(conn=None) -> dict:
    """The user who is performing the current request — never last staff / first user / the RustApp system label."""
    uid = request_user_id()
    pid = request_project_id()
    if uid and conn is not None:
        row = user_by_id(conn, uid)
        if row:
            email = str(row.get("email") or "").strip()
            name = human_actor_name(
                row.get("name") or "",
                email,
                email.split("@")[0] if "@" in email else "user",
            ) or (email.split("@")[0] if "@" in email else "user")
            role = actor_role_for(conn, int(row.get("id") or uid), pid)
            return {
                "id": int(row.get("id") or uid),
                "email": email,
                "name": name,
                "tag": staff_public_tag(row, name, conn),
                "role": role or str(row.get("role") or "staff"),
                "system_source": "RustCheck",
            }
    return {
        "id": int(uid or 0),
        "email": "",
        "name": "system",
        "tag": "",
        "role": "system",
        "system_source": "RustCheck",
    }


def freeze_actor(conn=None) -> dict:
    """Immutable snapshot written with every user action. Frontend must display these fields as-is."""
    info = request_actor(conn)
    actor_id = int(info.get("id") or 0)
    email = str(info.get("email") or "").strip()
    name = human_actor_name(info.get("name") or "", email, "user") or (email.split("@")[0] if "@" in email else "user")
    role = str(info.get("role") or "")
    tag = str(info.get("tag") or "").strip().lstrip("@")
    return {
        "actor_id": actor_id,
        "actor_user_id": actor_id,
        "actor_name": name,
        "actor_email": email,
        "actor_role": role,
        "actor_tag": tag,
        "system_source": "RustCheck",
    }


def log_command_execution(conn, commands, *, target_steam_id="", target_name="", server_id=0, server_name="", result="", status="ok") -> dict:
    """Persist a command-history row for THIS project only, with the real site user as actor."""
    pid = int(request_project_id() or 0)
    frozen = freeze_actor(conn)
    if isinstance(commands, str):
        cmds = [commands] if commands.strip() else []
    elif isinstance(commands, list):
        cmds = [str(c) for c in commands if str(c).strip()]
    else:
        cmds = []
    text = "; ".join(cmds)[:2000]
    now = _now_ms()
    try:
        conn.execute(
            """INSERT INTO command_log (
                   project_id, actor_user_id, actor_name, actor_email, actor_role,
                   command, commands, target_steam_id, target_name,
                   server_id, server_name, result, status, system_source, created_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                pid, int(frozen.get("actor_user_id") or 0), frozen.get("actor_name") or "",
                frozen.get("actor_email") or "", frozen.get("actor_role") or "",
                text, json.dumps(cmds, ensure_ascii=False), str(target_steam_id or ""),
                str(target_name or ""), int(server_id or 0), str(server_name or ""),
                str(result or ""), str(status or "ok"), "RustCheck", now,
            ),
        )
        rid = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    except Exception as exc:
        print("command_log insert failed", type(exc).__name__, exc)
        rid = 0
    return {
        "id": rid,
        "project_id": pid,
        "actor_id": int(frozen.get("actor_user_id") or 0),
        "actor_name": frozen.get("actor_name") or "",
        "command": text,
        "commands": cmds,
        "target_steam_id": str(target_steam_id or ""),
        "target_name": str(target_name or ""),
        "server_id": int(server_id or 0),
        "server_name": str(server_name or ""),
        "result": str(result or ""),
        "status": str(status or "ok"),
        "system_source": "RustCheck",
        "created_at": now,
    }


def command_log_items(conn, limit: int = 200, project_id: int = 0) -> list:
    pid = int(project_id or request_project_id() or 0)
    if not pid:
        return []
    items = []
    try:
        rows = conn.execute(
            """SELECT * FROM command_log WHERE project_id = ? ORDER BY id DESC LIMIT ?""",
            (pid, int(limit or 200)),
        ).fetchall()
    except Exception:
        rows = []
    for row in rows:
        cmds = []
        try:
            cmds = json.loads(row["commands"] or "[]")
        except Exception:
            cmds = []
        if not cmds and row["command"]:
            cmds = [str(row["command"])]
        actor_id = int(row["actor_user_id"] or 0)
        actor_user = user_by_id(conn, actor_id) if actor_id else None
        actor_name = human_actor_name(row["actor_name"] or "", row["actor_email"] or "", "") or str(row["actor_name"] or "")
        actor_tag = staff_public_tag(actor_user or {}, actor_name, conn)
        items.append({
            "id": int(row["id"] or 0),
            "project_id": pid,
            "actor_id": actor_id,
            "actor_user_id": actor_id,
            "actor_tag": actor_tag,
            "actor_name": actor_name,
            "actor_email": str(row["actor_email"] or ""),
            "actor_role": str(row["actor_role"] or ""),
            "command": str(row["command"] or ""),
            "commands": cmds,
            "target_steam_id": str(row["target_steam_id"] or ""),
            "target_name": str(row["target_name"] or ""),
            "server_id": int(row["server_id"] or 0),
            "server_name": str(row["server_name"] or ""),
            "result": str(row["result"] or ""),
            "status": str(row["status"] or "ok"),
            "system_source": "RustCheck",
            "created_at": int(row["created_at"] or 0),
            "client": {
                "id": actor_id,
                "name": actor_name,
                "tag": actor_tag,
                "email": str(row["actor_email"] or ""),
                "role": str(row["actor_role"] or "staff"),
            },
            "initiator_client": {
                "id": actor_id,
                "name": actor_name,
                "tag": actor_tag,
                "email": str(row["actor_email"] or ""),
                "role": str(row["actor_role"] or "staff"),
            },
        })
    return items


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_json(obj: dict) -> str:
    return _b64url(json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def _b64url_decode(part: str) -> bytes:
    pad = "=" * (-len(part) % 4)
    return base64.urlsafe_b64decode(part + pad)


def make_access_token(user: dict) -> str:
    uid = int(user.get("id") or 0)
    email = str(user.get("email") or "").lower().strip()
    name = str(user.get("name") or email.split("@")[0] or "user")
    header = _b64url_json({"alg": "HS256", "typ": "JWT"})
    payload = _b64url_json(
        {
            "sub": str(uid),
            "id": uid,
            "email": email,
            "name": name,
            "serial": "checkapp-local",
            "exp": int(time.time()) + 86400 * 365,
        }
    )
    sig = hmac_hex(f"{header}.{payload}")
    return f"{header}.{payload}.{sig}"


def hmac_hex(message: str) -> str:
    return hashlib.sha256((TOKEN_SECRET + ":" + message).encode("utf-8")).hexdigest()


def parse_access_token(token: str) -> dict | None:
    raw = str(token or "").strip()
    if raw.lower().startswith("bearer "):
        raw = raw[7:].strip()
    # Axios+XHR may concatenate headers: "Bearer a, Bearer b"
    if "," in raw:
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        for part in reversed(parts):
            parsed = parse_access_token(part)
            if parsed:
                return parsed
        return None
    # SPA stores access_token as "\"<jwt>\"" (with literal quotes)
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ("'", '"'):
        raw = raw[1:-1].strip()
    raw = raw.strip().strip('"').strip("'")
    if raw.lower().startswith("bearer "):
        raw = raw[7:].strip()
    if not raw or raw.count(".") != 2:
        return None
    header_b64, payload_b64, sig = raw.split(".", 2)
    expected = hmac_hex(f"{header_b64}.{payload_b64}")
    # Accept legacy unsigned ".local" tokens from older mock builds
    if sig not in ("local",) and not secrets.compare_digest(sig, expected):
        return None
    try:
        payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    exp = int(payload.get("exp") or 0)
    if exp and exp < int(time.time()) - 60:
        return None
    return payload

# month_price is in kopecks (SPA divides by 100): 0 -> Free, 30000 -> ₽300
PLANS = {
    "base": {
        "id": 1, "slug": "base", "name": "Base", "tier": "base", "price_month": 0,
        "servers_limit": 5, "players_limit": 500000, "projects_limit": 2, "clients_limit": 999,
        "subtitle": "Тест 7 дней",
        "features": ["Все функции", "Тестовая подписка 7 дней", "После теста — заморозка без оплаты Plus"],
    },
    "plus": {
        "id": 2, "slug": "plus", "name": "Plus", "tier": "plus", "price_month": 30000,
        "servers_limit": 5, "players_limit": 500000, "projects_limit": 3, "clients_limit": 999,
        "subtitle": "30 дней",
        "features": ["Все функции", "5 серверов", "Подписка на 30 дней"],
    },
    "enterprise": {
        "id": 3, "slug": "enterprise", "name": "Enterprise", "tier": "enterprise", "price_month": 1000000,
        "servers_limit": 5, "players_limit": 500000, "projects_limit": 10, "clients_limit": 999,
        "subtitle": "Custom",
        "features": ["Все функции", "От 5 серверов", "Приоритетная поддержка"],
    },
}
PLANS["basic"] = PLANS["base"]
PLANS["starter"] = PLANS["base"]
PLANS["pro"] = PLANS["enterprise"]
PLANS["premium"] = PLANS["enterprise"]
PLANS["custom"] = PLANS["enterprise"]

PLUS_FEATURE_KEYS = ()  # Base has full feature access; Plus is paid duration only

OWNER_EMAIL = "admin@gmail.com"
OWNER_PASSWORD = "admin123"
OWNER_NAME = "Owner"

QUEUE_MAP = {
    "check_start": "check-started",
    "check-start": "check-started",
    "notice_set": "notice-state-set",
    "notice-set": "notice-state-set",
    "execute_command": "execute-command",
    "check_finish": "check-finished",
    "check-finish": "check-finished",
    "chat-message": "chat-message",
    "kick": "kick",
    "ban": "ban",
    "mute": "mute",
    "destroy_buildings": "destroy-buildings",
    "destroy-buildings": "destroy-buildings",
    "delete_entity": "delete-entity",
    "delete-entity": "delete-entity",
}


def queue_name(name: str) -> str:
    return QUEUE_MAP.get(name, name.replace("_", "-"))


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120000).hex()
    return f"{salt}${digest}"


def check_password(password: str, stored: str) -> bool:
    if not stored or "$" not in stored:
        return False
    salt, _ = stored.split("$", 1)
    return secrets.compare_digest(hash_password(password, salt), stored)


def verify_password(password: str, stored: str) -> bool:
    return check_password(password, stored)


def ensure_bootstrap_admin(conn) -> None:
    email = OWNER_EMAIL.lower().strip()
    now = int(time.time() * 1000)
    row = conn.execute("SELECT id, password_hash FROM users WHERE lower(email) = ?", (email,)).fetchone()
    if not row:
        conn.execute(
            """INSERT INTO users (email, name, tag, bio, password_hash, role, is_admin, is_platform_admin, created_at, account_blocked, account_blocked_at, account_blocked_reason)
               VALUES (?, ?, 'owner', '', ?, 'owner', 1, 1, ?, 0, 0, '')""",
            (email, OWNER_NAME, hash_password(OWNER_PASSWORD), now),
        )
        return
    conn.execute(
        """UPDATE users SET name = ?, role = 'owner', is_admin = 1, is_platform_admin = 1
           WHERE id = ?""",
        (OWNER_NAME, int(row["id"])),
    )
    if not str(row["password_hash"] or "").strip():
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (hash_password(OWNER_PASSWORD), int(row["id"])),
        )


def pref_bool(row, *keys, default=False) -> bool:
    """First present key wins. False is not overwritten by a leftover True `enabled`."""
    data = row if isinstance(row, dict) else {}
    for key in keys:
        if key in data and data[key] is not None:
            val = data[key]
            if isinstance(val, str):
                return val.strip().lower() in ("1", "true", "yes", "on")
            return bool(val)
    return bool(default)


def ensure_query_indexes(conn) -> None:
    """Composite indexes matching real filters. Safe to run repeatedly."""
    stmts = (
        "CREATE INDEX IF NOT EXISTS idx_chat_project_created ON chat(project_id, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_chat_project_id ON chat(project_id, id)",
        "CREATE INDEX IF NOT EXISTS idx_bans_project_steam ON bans(project_id, steam_id)",
        "CREATE INDEX IF NOT EXISTS idx_bans_project_ip ON bans(project_id, ip)",
        "CREATE INDEX IF NOT EXISTS idx_bans_project_active ON bans(project_id, active)",
        "CREATE INDEX IF NOT EXISTS idx_mutes_project_steam ON mutes(project_id, steam_id)",
        "CREATE INDEX IF NOT EXISTS idx_mutes_active_expired ON mutes(active, expired_at)",
        "CREATE INDEX IF NOT EXISTS idx_alerts_project_id ON alerts(project_id, id)",
        "CREATE INDEX IF NOT EXISTS idx_audit_project_created ON audit(project_id, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_online_server_steam ON online_players(server_id, steam_id)",
        "CREATE INDEX IF NOT EXISTS idx_team_history_pid_steam ON team_history(project_id, steam_id)",
        "CREATE INDEX IF NOT EXISTS idx_servers_project_paired ON servers(project_id, paired)",
        "CREATE INDEX IF NOT EXISTS idx_servers_token ON servers(token)",
        "CREATE INDEX IF NOT EXISTS idx_queue_project_done ON queue(project_id, done, id)",
        "CREATE INDEX IF NOT EXISTS idx_signage_project ON signage(project_id, id)",
        "CREATE INDEX IF NOT EXISTS idx_player_ips_ip ON player_ips(ip)",
        "CREATE INDEX IF NOT EXISTS idx_player_ips_steam ON player_ips(steam_id)",
        "CREATE INDEX IF NOT EXISTS idx_command_log_project ON command_log(project_id, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_kills_project ON kills(project_id, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_kills_initiator ON kills(project_id, initiator_steam_id, id)",
        "CREATE INDEX IF NOT EXISTS idx_kills_target ON kills(project_id, target_steam_id, id)",
        "CREATE INDEX IF NOT EXISTS idx_chat_steam ON chat(project_id, steam_id, id)",
        "CREATE INDEX IF NOT EXISTS idx_chat_target ON chat(project_id, target_steam_id, id)",
        "CREATE INDEX IF NOT EXISTS idx_audit_project_id ON audit(project_id, id)",
        "CREATE INDEX IF NOT EXISTS idx_bans_project_id ON bans(project_id, id)",
        "CREATE INDEX IF NOT EXISTS idx_webhooks_project ON webhooks(project_id, kind)",
        "CREATE INDEX IF NOT EXISTS idx_staff_project_user ON staff_members(project_id, user_id)",
        "CREATE INDEX IF NOT EXISTS idx_signage_likes_user_draw ON signage_likes(user_id, drawing_id)",
        "CREATE INDEX IF NOT EXISTS idx_player_sessions_pid ON player_sessions(project_id, steam_id)",
        "CREATE INDEX IF NOT EXISTS idx_checks_project ON checks(project_id, id)",
    )
    for sql in stmts:
        try:
            conn.execute(sql)
        except Exception:
            pass


def ensure_schema(conn) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE,
            name TEXT DEFAULT '',
            password_hash TEXT DEFAULT '',
            steam_id TEXT DEFAULT '',
            google_id TEXT DEFAULT '',
            role TEXT DEFAULT 'admin',
            is_admin INTEGER DEFAULT 1,
            created_at INTEGER
        );
        CREATE TABLE IF NOT EXISTS webhooks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT,
            url TEXT,
            enabled INTEGER DEFAULT 1,
            options TEXT DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            actor TEXT DEFAULT '',
            event TEXT DEFAULT '',
            payload TEXT DEFAULT '{}',
            created_at INTEGER
        );
        CREATE TABLE IF NOT EXISTS bags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            steam_id TEXT,
            net_id TEXT,
            name TEXT DEFAULT '',
            grid TEXT DEFAULT '',
            position TEXT DEFAULT '',
            from_steam_id TEXT DEFAULT '',
            to_steam_id TEXT DEFAULT '',
            created_at INTEGER
        );
        CREATE TABLE IF NOT EXISTS bag_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            net_id TEXT,
            from_steam_id TEXT DEFAULT '',
            to_steam_id TEXT DEFAULT '',
            name TEXT DEFAULT '',
            grid TEXT DEFAULT '',
            position TEXT DEFAULT '',
            created_at INTEGER
        );
        CREATE TABLE IF NOT EXISTS wallet (
            id INTEGER PRIMARY KEY,
            balance INTEGER DEFAULT 0,
            plan TEXT DEFAULT 'base'
        );
        CREATE TABLE IF NOT EXISTS lifetime_stats (
            key TEXT PRIMARY KEY,
            value INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS player_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            steam_id TEXT,
            ip TEXT DEFAULT '',
            connected_at INTEGER,
            disconnected_at INTEGER DEFAULT 0,
            disconnected_reason TEXT DEFAULT '',
            is_license INTEGER DEFAULT 1,
            server_id INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS player_ips (
            steam_id TEXT,
            ip TEXT,
            first_seen INTEGER,
            last_seen INTEGER,
            count INTEGER DEFAULT 1,
            PRIMARY KEY (steam_id, ip)
        );
        CREATE TABLE IF NOT EXISTS player_names (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            steam_id TEXT,
            steam_name TEXT,
            created_at INTEGER,
            last_seen INTEGER
        );
        CREATE TABLE IF NOT EXISTS wallet_ops (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            amount INTEGER,
            comment TEXT,
            created_at INTEGER
        );
        CREATE TABLE IF NOT EXISTS autokick (
            type TEXT PRIMARY KEY,
            active INTEGER DEFAULT 0,
            options TEXT DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS steam_cache (
            steam_id TEXT PRIMARY KEY,
            payload TEXT DEFAULT '{}',
            fetched_at INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS ip_cache (
            ip TEXT PRIMARY KEY,
            payload TEXT DEFAULT '{}',
            fetched_at INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS home_cache (
            steam_id TEXT PRIMARY KEY,
            payload TEXT DEFAULT '{}',
            fetched_at INTEGER DEFAULT 0
        );
        """
    )
    for col, default in (
        ("checker_id", "INTEGER DEFAULT 1"),
        ("checker_name", "TEXT DEFAULT ''"),
        ("checker_email", "TEXT DEFAULT ''"),
    ):
        try:
            conn.execute(f"ALTER TABLE checks ADD COLUMN {col} {default}")
        except Exception:
            pass
    for col, default in (
        ("tag", "TEXT DEFAULT 'owner'"),
        ("bio", "TEXT DEFAULT ''"),
    ):
        try:
            conn.execute(f"ALTER TABLE users ADD COLUMN {col} {default}")
        except Exception:
            pass
    for col, default in (
        ("from_steam_id", "TEXT DEFAULT ''"),
        ("to_steam_id", "TEXT DEFAULT ''"),
    ):
        try:
            conn.execute(f"ALTER TABLE bags ADD COLUMN {col} {default}")
        except Exception:
            pass
    conn.execute("DELETE FROM users WHERE email IN ('admin', 'admin@checkapp.local')")
    if conn.execute("SELECT COUNT(*) FROM wallet").fetchone()[0] == 0:
        conn.execute("INSERT INTO wallet (id, balance, plan) VALUES (1, 0, 'base')")
    conn.execute("UPDATE wallet SET plan = 'plus' WHERE plan IN ('pro', 'premium')")
    conn.execute("UPDATE wallet SET plan = 'base' WHERE plan IN ('basic', 'starter')")
    conn.execute("DELETE FROM users WHERE lower(email) IN ('admin', 'admin@checkapp.local')")
    for col, default in (
        ("plan", "TEXT DEFAULT 'base'"),
        ("trial_ends_at", "INTEGER DEFAULT 0"),
        ("paid_until", "INTEGER DEFAULT 0"),
        ("balance", "INTEGER DEFAULT 0"),
        ("owner_user_id", "INTEGER DEFAULT 0"),
    ):
        try:
            conn.execute(f"ALTER TABLE project ADD COLUMN {col} {default}")
        except Exception:
            pass
    try:
        # Drop unowned projects left by old auto-seed / race bugs — never reassign to strangers.
        conn.execute("DELETE FROM project WHERE COALESCE(owner_user_id, 0) = 0")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE wallet_ops ADD COLUMN project_id INTEGER DEFAULT 0")
    except Exception:
        pass
    try:
        wallet_row = conn.execute("SELECT balance FROM wallet WHERE id = 1").fetchone()
        wallet_bal = int(wallet_row["balance"] if wallet_row else 0)
        if wallet_bal > 0:
            proj_sum = int(conn.execute("SELECT COALESCE(SUM(balance), 0) FROM project").fetchone()[0])
            if proj_sum <= 0:
                first = conn.execute("SELECT id FROM project ORDER BY id ASC LIMIT 1").fetchone()
                if first:
                    conn.execute(
                        "UPDATE project SET balance = ? WHERE id = ?",
                        (wallet_bal, int(first["id"])),
                    )
            conn.execute("UPDATE wallet SET balance = 0, plan = 'base' WHERE id = 1")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE servers ADD COLUMN server_ip TEXT DEFAULT ''")
    except Exception:
        pass
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS server_ips (
            project_id INTEGER NOT NULL,
            server_id INTEGER DEFAULT 0,
            server_ip TEXT NOT NULL,
            updated_at INTEGER DEFAULT 0,
            PRIMARY KEY (project_id, server_ip)
        );
        """
    )
    ensure_admin_schema(conn)
    now = _now_ms()
    try:
        conn.execute(
            "UPDATE project SET paid_until = 0 WHERE paid_until >= ?",
            (PAID_UNTIL_FAR - 86400000,),
        )
        conn.execute(
            "UPDATE project SET paid_until = 0 WHERE paid_until > ?",
            (now + 86400000 * 400,),
        )
        # Only clamp absurd far-future trials — never revive ended/discarded trials (≤0 or past).
        conn.execute(
            "UPDATE project SET trial_ends_at = ? WHERE trial_ends_at > ?",
            (now + TRIAL_MS, now + 86400000 * 400),
        )
        billing = setting_json(conn, "billing", {})
        if isinstance(billing, dict):
            pu = int(billing.get("paid_until") or 0)
            if pu >= PAID_UNTIL_FAR - (86400000 * 30) or pu > now + (86400000 * 400):
                billing["paid_until"] = 0
                setting_json_set(conn, "billing", billing)
    except Exception:
        pass
    for col, default in (
        ("project_id", "INTEGER DEFAULT 1"),
    ):
        try:
            conn.execute(f"ALTER TABLE servers ADD COLUMN {col} {default}")
        except Exception:
            pass
        try:
            conn.execute(f"ALTER TABLE pair_codes ADD COLUMN {col} {default}")
        except Exception:
            pass
        try:
            conn.execute(f"ALTER TABLE online_players ADD COLUMN {col} {default}")
        except Exception:
            pass
    try:
        conn.execute("ALTER TABLE pair_codes ADD COLUMN server_name TEXT DEFAULT ''")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE reports ADD COLUMN server_id INTEGER DEFAULT 0")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE online_players ADD COLUMN server_id INTEGER DEFAULT 1")
    except Exception:
        pass
    for table in (
        "queue", "chat", "alerts", "checks", "bans", "reports", "mutes",
        "comments", "kills", "bags", "bag_events", "audit", "player_sessions",
        "webhooks",
    ):
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN project_id INTEGER DEFAULT 0")
        except Exception:
            pass
    try:
        conn.execute("ALTER TABLE chat ADD COLUMN server_id INTEGER DEFAULT 0")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE chat ADD COLUMN check_id INTEGER DEFAULT 0")
    except Exception:
        pass
    try:
        for prow in conn.execute("SELECT id FROM project").fetchall():
            pid = int(prow["id"] or 0)
            if not pid:
                continue
            sids = [
                int(r["id"])
                for r in conn.execute(
                    "SELECT id FROM servers WHERE COALESCE(project_id, 0) = ? AND paired = 1",
                    (pid,),
                ).fetchall()
            ]
            if len(sids) == 1:
                conn.execute(
                    """UPDATE chat SET server_id = ?
                       WHERE COALESCE(project_id, 0) = ?
                         AND COALESCE(server_id, 0) = 0
                         AND COALESCE(from_site, 0) = 0""",
                    (sids[0], pid),
                )
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE player_sessions ADD COLUMN server_id INTEGER DEFAULT 1")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE signage ADD COLUMN destroyed_at INTEGER DEFAULT 0")
    except Exception:
        pass
    first = conn.execute("SELECT id FROM project ORDER BY id ASC LIMIT 1").fetchone()
    first_id = int(first["id"]) if first else 1
    proj_n = 0
    try:
        proj_n = int(conn.execute("SELECT COUNT(*) FROM project").fetchone()[0] or 0)
    except Exception:
        proj_n = 0
    # Only remap orphan rows when a single project exists — otherwise this steals new-project data.
    if proj_n == 1:
        conn.execute("UPDATE servers SET project_id = ? WHERE project_id IS NULL OR project_id = 0", (first_id,))
        for table in (
            "queue", "chat", "alerts", "checks", "bans", "reports", "mutes",
            "comments", "kills", "bags", "bag_events", "audit", "player_sessions",
            "online_players", "pair_codes", "webhooks",
        ):
            try:
                conn.execute(
                    f"UPDATE {table} SET project_id = ? WHERE project_id IS NULL OR project_id = 0",
                    (first_id,),
                )
            except Exception:
                pass
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS signage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            steam_id TEXT DEFAULT '',
            net_id TEXT DEFAULT '',
            type TEXT DEFAULT '',
            position TEXT DEFAULT '',
            square TEXT DEFAULT '',
            image TEXT DEFAULT '',
            created_at INTEGER,
            destroyed_at INTEGER DEFAULT 0,
            project_id INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS team_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            steam_id TEXT DEFAULT '',
            team_key TEXT DEFAULT '',
            members TEXT DEFAULT '[]',
            started_at INTEGER,
            ended_at INTEGER DEFAULT 0,
            project_id INTEGER DEFAULT 1,
            server_id INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS team_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event TEXT DEFAULT '',
            steam_id TEXT DEFAULT '',
            members TEXT DEFAULT '[]',
            created_at INTEGER DEFAULT 0,
            project_id INTEGER DEFAULT 0,
            server_id INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS signage_likes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            drawing_id INTEGER NOT NULL,
            net_id TEXT DEFAULT '',
            project_id INTEGER NOT NULL,
            created_at INTEGER,
            UNIQUE(user_id, drawing_id)
        );
        CREATE TABLE IF NOT EXISTS command_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER DEFAULT 0,
            actor_user_id INTEGER DEFAULT 0,
            actor_name TEXT DEFAULT '',
            actor_email TEXT DEFAULT '',
            actor_role TEXT DEFAULT '',
            command TEXT DEFAULT '',
            commands TEXT DEFAULT '[]',
            target_steam_id TEXT DEFAULT '',
            target_name TEXT DEFAULT '',
            server_id INTEGER DEFAULT 0,
            server_name TEXT DEFAULT '',
            result TEXT DEFAULT '',
            status TEXT DEFAULT 'ok',
            system_source TEXT DEFAULT 'RustCheck',
            created_at INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS staff_members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT DEFAULT '',
            name TEXT DEFAULT '',
            steam_id TEXT DEFAULT '',
            twofactor_active INTEGER DEFAULT 0,
            role TEXT DEFAULT 'staff',
            permissions TEXT DEFAULT '[]',
            project_id INTEGER DEFAULT 1,
            created_at INTEGER
        );
        CREATE TABLE IF NOT EXISTS former_staff_snapshots (
            project_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            name TEXT DEFAULT '',
            tag TEXT DEFAULT '',
            email TEXT DEFAULT '',
            role TEXT DEFAULT 'staff',
            avatar TEXT DEFAULT '',
            removed_at INTEGER DEFAULT 0,
            PRIMARY KEY (project_id, user_id)
        );
        """
    )
    for col, default in (
        ("steam_strict", "INTEGER DEFAULT 0"),
        ("twofa_strict", "INTEGER DEFAULT 0"),
    ):
        try:
            conn.execute(f"ALTER TABLE project ADD COLUMN {col} {default}")
        except Exception:
            pass
    for col, default in (
        ("twofactor_active", "INTEGER DEFAULT 0"),
        ("tag", "TEXT DEFAULT ''"),
        ("bio", "TEXT DEFAULT ''"),
        ("discord_id", "TEXT DEFAULT ''"),
        ("google_id", "TEXT DEFAULT ''"),
    ):
        try:
            conn.execute(f"ALTER TABLE users ADD COLUMN {col} {default}")
        except Exception:
            pass
    try:
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_steam_id ON users(steam_id) WHERE steam_id != ''"
        )
    except Exception:
        pass
    try:
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_discord_id ON users(discord_id) WHERE discord_id != ''"
        )
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE team_history ADD COLUMN server_id INTEGER DEFAULT 0")
    except Exception:
        pass
    try:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS team_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event TEXT DEFAULT '',
                steam_id TEXT DEFAULT '',
                members TEXT DEFAULT '[]',
                created_at INTEGER DEFAULT 0,
                project_id INTEGER DEFAULT 0,
                server_id INTEGER DEFAULT 0
            )"""
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_team_events_pid_steam ON team_events(project_id, steam_id)")
    except Exception:
        pass
    ensure_query_indexes(conn)
    for col, default in (
        ("user_id", "INTEGER DEFAULT 0"),
        ("is_immutable", "INTEGER DEFAULT 0"),
        ("active", "INTEGER DEFAULT 1"),
    ):
        try:
            conn.execute(f"ALTER TABLE staff_members ADD COLUMN {col} {default}")
        except Exception:
            pass
    try:
        conn.execute("ALTER TABLE kills ADD COLUMN bone TEXT DEFAULT ''")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE kills ADD COLUMN initiator_name TEXT DEFAULT ''")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE kills ADD COLUMN target_name TEXT DEFAULT ''")
    except Exception:
        pass
    try:
        import platega_pay
        platega_pay.ensure_schema(conn)
    except Exception:
        pass
    seed_lifetime(conn)
    ensure_trial(conn)
    try:
        for row in conn.execute("SELECT steam_id, steam_name, ip, first_seen, last_seen FROM players").fetchall():
            sid = row["steam_id"]
            name = str(row["steam_name"] or "").strip()
            ip = str(row["ip"] or "").strip()
            first = int(row["first_seen"] or 0)
            last = int(row["last_seen"] or first)
            if name and not conn.execute("SELECT 1 FROM player_names WHERE steam_id = ?", (sid,)).fetchone():
                conn.execute(
                    "INSERT INTO player_names (steam_id, steam_name, created_at, last_seen) VALUES (?, ?, ?, ?)",
                    (sid, name, first or last, last or first),
                )
            if ip and not conn.execute("SELECT 1 FROM player_ips WHERE steam_id = ? AND ip = ?", (sid, ip)).fetchone():
                conn.execute(
                    "INSERT INTO player_ips (steam_id, ip, first_seen, last_seen, count) VALUES (?, ?, ?, ?, 1)",
                    (sid, ip, first or last, last or first),
                )
    except Exception:
        pass


def seed_lifetime(conn) -> None:
    mapping = {
        "checks": "SELECT COUNT(*) FROM checks",
        "bans": "SELECT COUNT(*) FROM bans",
        "reports": "SELECT COUNT(*) FROM reports",
        "messages": "SELECT COUNT(*) FROM chat",
        "players": "SELECT COUNT(*) FROM players",
    }
    for key, sql in mapping.items():
        try:
            current = int(conn.execute(sql).fetchone()[0] or 0)
        except Exception:
            current = 0
        row = conn.execute("SELECT value FROM lifetime_stats WHERE key = ?", (key,)).fetchone()
        if not row:
            conn.execute("INSERT INTO lifetime_stats (key, value) VALUES (?, ?)", (key, current))
        elif int(row["value"] or 0) < current:
            conn.execute("UPDATE lifetime_stats SET value = ? WHERE key = ?", (current, key))


def lifetime_bump(conn, key: str, n: int = 1) -> None:
    try:
        conn.execute(
            "INSERT INTO lifetime_stats (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = value + excluded.value",
            (key, int(n)),
        )
    except Exception:
        pass


def lifetime_get(conn, key: str, fallback: int = 0) -> int:
    try:
        row = conn.execute("SELECT value FROM lifetime_stats WHERE key = ?", (key,)).fetchone()
        if row:
            return max(int(row["value"] or 0), int(fallback or 0))
    except Exception:
        pass
    return int(fallback or 0)


def ensure_trial(conn) -> None:
    billing = setting_json(conn, "billing", {})
    if not isinstance(billing, dict):
        billing = {}
    now = _now_ms()
    if not billing.get("trial_started_at"):
        billing["trial_started_at"] = now
        billing["trial_ends_at"] = now + TRIAL_MS
        setting_json_set(conn, "billing", billing)
    try:
        for row in conn.execute("SELECT id, plan, trial_ends_at, paid_until FROM project").fetchall():
            plan = normalize_plan(row["plan"] if "plan" in row.keys() else "")
            trial = int(row["trial_ends_at"] or 0) if "trial_ends_at" in row.keys() else 0
            paid = 0
            try:
                paid = sanitize_paid_until(row["paid_until"] if "paid_until" in row.keys() else 0, now)
            except Exception:
                paid = 0
            if paid > now:
                # Paid projects must not get a trial stamp.
                if trial:
                    conn.execute("UPDATE project SET trial_ends_at = 0 WHERE id = ?", (row["id"],))
                continue
            # Never auto-restart trial here — granted only on project create / discard ends it.
            if plan in ("pro", "premium"):
                conn.execute("UPDATE project SET plan = 'plus' WHERE id = ?", (row["id"],))
    except Exception:
        pass


def normalize_plan(slug: str) -> str:
    slug = str(slug or "base").strip().lower()
    if slug in ("basic", "starter", "free"):
        return "base"
    if slug in ("pro", "premium", "custom"):
        return "enterprise"
    if slug not in ("base", "plus", "enterprise"):
        return "base"
    return slug


def owner_user(conn) -> dict:
    uid = request_user_id()
    if uid:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
        if row:
            return dict(row)
    return {"id": 0, "email": "", "name": "system"}


def user_by_id(conn, uid: int) -> dict | None:
    try:
        uid = int(uid or 0)
    except Exception:
        return None
    if not uid:
        return None
    row = conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    return dict(row) if row else None


def user_from_token_payload(conn, payload: dict | None) -> dict | None:
    if not payload:
        return None
    uid = 0
    try:
        uid = int(payload.get("id") or payload.get("sub") or 0)
    except Exception:
        uid = 0
    if uid:
        row = user_by_id(conn, uid)
        if row:
            return row
    email = str(payload.get("email") or "").lower().strip()
    if email:
        row = conn.execute("SELECT * FROM users WHERE lower(email) = ?", (email,)).fetchone()
        if row:
            return dict(row)
    return None


def client_avatar_for(conn, uid: int = 0) -> str:
    keys = []
    if uid:
        keys.append(f"client_avatar_{int(uid)}")
    keys.append("client_avatar")
    for key in keys:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        if row and row["value"]:
            return str(row["value"])
    return ""


def is_real_steam_id(sid) -> bool:
    text = str(sid or "").strip()
    if text in ("76561198000000000", "76561198000000001"):
        return False
    return text.isdigit() and len(text) == 17 and text.startswith("7656119")


def spa_https_image(url: str) -> str:
    """SPA Urls.Images() keeps a path only if it contains 'https'; otherwise it prefixes dead S3."""
    text = str(url or "/local/image-1024.jpg?v=6").strip() or "/local/image-1024.jpg?v=6"
    if text.startswith("/") and "https" not in text.lower():
        text = text + ("&" if "?" in text else "?") + "https=1"
    return text


def empty_steam_profile(avatar: str = "") -> dict:
    """SPA Settings reads client.steam.avatar with no guard. Never return null/omit steam."""
    av = spa_https_image(avatar or "/local/image-1024.jpg?v=6")
    return {
        "steam_id": "",
        "steamid": "",
        "steam_name": "",
        "name": "",
        "personaname": "",
        "avatar": av,
        "steam_avatar": av,
        "avatarfull": av,
        "connected": False,
        "profileurl": "",
    }


def client_from_user(user: dict, avatar: str, conn=None) -> dict:
    email = str(user.get("email") or "").strip()
    name = staff_public_name(user, str(user.get("name") or ""), email, conn) or str(user.get("name") or (email.split("@")[0] if email else "user") or "user")
    tag = staff_public_tag(user, name, conn)
    bio = str(user.get("bio") or "")
    steam_id = str(user.get("steam_id") or "")
    discord_id = str(user.get("discord_id") or "")
    empty_av = spa_https_image(avatar or "/local/image-1024.jpg?v=6")
    linked_steam = is_real_steam_id(steam_id)
    return {
        "id": int(user.get("id") or 0),
        "name": name,
        "tag": tag,
        "username": tag,
        "nickname": name,
        "bio": bio,
        "about": bio,
        "email": email,
        "avatar": empty_av,
        "steam_id": steam_id if linked_steam else "",
        "discord_id": discord_id,
        "steam": {
            "steam_id": steam_id, "steamid": steam_id, "steam_name": "", "name": "", "personaname": "",
            "avatar": empty_av, "steam_avatar": empty_av, "avatarfull": empty_av,
        } if linked_steam else empty_steam_profile(empty_av),
        "discord": {
            "discord_id": discord_id, "discord_name": "", "name": "",
            "avatar": "", "discord_avatar": "",
        },
        "google": {
            "google_id": "", "google_name": "", "name": "",
            "avatar": empty_av, "google_avatar": empty_av,
        },
        "email_confirmed": True,
        "twofactor_active": bool(user.get("twofactor_active") or user.get("twofa") or False),
        "centrifugo_token": "local",
        "created_at": "2024-01-01T00:00:00.000Z",
        "is_admin": True,
        "permissions": [],
        "status": "online",
        "state": "online",
        "online": True,
        "is_online": True,
        "presence": "online",
        "was_online_at": _now_ms(),
        "last_seen": _now_ms(),
        "last_online": _now_ms(),
        "last_online_at": _now_ms(),
        "last_seen_at": _now_ms(),
        "last_active_at": _now_ms(),
        "online_at": _now_ms(),
    }


def save_client_profile(conn, body: dict, avatar_fallback: str = "") -> dict:
    uid = int(request_user_id() or 0)
    user = user_by_id(conn, uid) if uid else None
    if not user:
        user = owner_user(conn)
        uid = int((user or {}).get("id") or 0)
    if not uid:
        return client_from_user({"id": 0, "email": "", "name": "guest"}, avatar_fallback)
    body = body if isinstance(body, dict) else {}
    name = str(
        body.get("name") or body.get("nickname") or body.get("nick") or body.get("display_name")
        or user.get("name") or "user"
    ).strip() or "user"
    tag = str(
        body.get("tag") or body.get("username") or body.get("user_name") or body.get("login")
        or body.get("handle") or user.get("tag") or ""
    ).strip().lstrip("@")
    if is_generic_staff_label(tag, conn):
        tag = staff_public_tag(user, name, conn)
    bio = body.get("bio")
    if bio is None:
        bio = body.get("about")
    if bio is None:
        bio = user.get("bio") or ""
    bio = str(bio)
    avatar = avatar_fallback
    raw_avatar = body.get("avatar")
    if isinstance(raw_avatar, dict):
        avatar = str(raw_avatar.get("url") or raw_avatar.get("s3_id") or avatar or "")
    elif raw_avatar not in (None, ""):
        avatar = str(raw_avatar)
    elif body.get("url") or body.get("s3_id"):
        avatar = str(body.get("url") or body.get("s3_id") or "")
    conn.execute(
        "UPDATE users SET name = ?, tag = ?, bio = ? WHERE id = ?",
        (name, tag, bio, uid),
    )
    if avatar:
        key = f"client_avatar_{uid}"
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, avatar),
        )
    saved_avatar = client_avatar_for(conn, uid) or avatar or ""
    updated = user_by_id(conn, uid) or user
    # Import locally to avoid circular import at module load
    import oauth_auth
    base = client_from_user(updated, saved_avatar, conn)
    steam = oauth_auth.steam_profile_for_user(conn, updated, allow_network=False)
    if steam and is_real_steam_id(steam.get("steam_id")):
        base["steam"] = steam
        base["steam_id"] = str(steam.get("steam_id") or "")
    else:
        base["steam"] = empty_steam_profile(saved_avatar)
        base["steam_id"] = ""
    disc = oauth_auth.discord_profile_for_user(conn, updated)
    if disc:
        base["discord"] = disc
    goog = oauth_auth.google_profile_for_user(conn, updated) if hasattr(oauth_auth, "google_profile_for_user") else None
    if goog:
        base["google"] = goog
    return base


def audit(conn, event: str, payload: dict | None = None, actor: str = "") -> None:
    frozen = freeze_actor(conn)
    payload = dict(payload or {})
    ev = str(event or "")
    if ev in ("chat.direct", "chat.global", "player.message"):
        from_site = payload.get("from_site") is True or str(payload.get("source") or "").lower() in ("site", "staff")
        author_type = str(payload.get("author_type") or "").lower()
        if author_type == "player" or (not from_site and not int(frozen.get("actor_user_id") or 0)):
            print("audit skip in-game chat", ev)
            return
    actor_id = int(frozen.get("actor_user_id") or 0)
    actor_email = str(frozen.get("actor_email") or "").strip()
    actor_name = human_actor_name(frozen.get("actor_name") or "", actor_email, actor)
    actor_role = str(frozen.get("actor_role") or "").strip()
    actor_tag = str(frozen.get("actor_tag") or "").strip().lstrip("@")
    if not actor:
        actor = actor_email or actor_name or "system"
    if not actor_name:
        actor_name = actor_email.split("@")[0] if "@" in actor_email else (actor or "system")
        actor_name = human_actor_name(actor_name, actor_email, "user") or actor_name
    if not actor_email and "@" in str(actor):
        actor_email = str(actor)
    # Snapshot the performer at write time. Never reuse payload.user_id (that is often the TARGET).
    # system_source is the technical pipeline (plugin/site) and must NEVER replace actor_name.
    payload["actor_id"] = actor_id
    payload["actor_user_id"] = actor_id
    payload["actor_email"] = actor_email or actor
    payload["actor_name"] = actor_name
    payload["actor_role"] = actor_role
    payload["actor_tag"] = actor_tag
    payload["system_source"] = "RustCheck"
    pid = request_project_id()
    if not pid:
        try:
            pid = int(payload.get("project_id") or 0)
        except Exception:
            pid = 0
    if not pid:
        if not str(event or "").startswith("admin."):
            print("audit skip, no project_id for", event)
            return
    created = _now_ms()
    blob = json.dumps(payload, ensure_ascii=False)
    variants = [
        (
            """INSERT INTO audit (actor, event, payload, created_at, project_id, actor_user_id, actor_name, actor_email, actor_role)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (actor, event, blob, created, pid or None, actor_id, actor_name, actor_email, actor_role),
        ),
        (
            """INSERT INTO audit (actor, event, payload, created_at, project_id, actor_user_id, actor_name, actor_email)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (actor, event, blob, created, pid or None, actor_id, actor_name, actor_email),
        ),
        (
            "INSERT INTO audit (actor, event, payload, created_at, project_id, actor_user_id) VALUES (?, ?, ?, ?, ?, ?)",
            (actor, event, blob, created, pid or None, actor_id),
        ),
        (
            "INSERT INTO audit (actor, event, payload, created_at, project_id) VALUES (?, ?, ?, ?, ?)",
            (actor, event, blob, created, pid or None),
        ),
        (
            "INSERT INTO audit (actor, event, payload, created_at) VALUES (?, ?, ?, ?)",
            (actor, event, blob, created),
        ),
    ]
    last_err = None
    for sql, args in variants:
        try:
            conn.execute(sql, args)
            last_err = None
            break
        except Exception as exc:
            last_err = exc
    if last_err:
        print("audit insert failed", type(last_err).__name__, last_err)
        return
    try:
        hook = realtime_emit
        if hook and pid:
            hook(pid, "audit.created", {
                "event": event,
                "actorId": actor_id,
                "actor_id": actor_id,
                "actorName": actor_name,
                "actor_name": actor_name,
                "payload": payload,
                "projectId": pid,
                "project_id": pid,
                "createdAt": created,
            })
    except Exception as exc:
        print("audit realtime emit failed", type(exc).__name__, exc)
    if pid and not str(event).startswith("admin."):
        emit_json_webhook(conn, "audit_event", {"data":payload,"event":event,"created_at":created}, project_id=pid)
        mapped = {"staff_edit":"staff_edit", "staff_delete":"staff_delete", "custom_action.execute":"custom_action_execute", "signage.delete":"signage_delete", "ban.edit":"ban_edit"}.get(event)
        if mapped:
            emit_json_webhook(conn, mapped, {"data":payload,"created_at":created}, project_id=pid)
        if event == "ban.create" and actor_id:
            notify_many_bans(conn, pid, actor_id, actor_name, created)
    try:
        notify_admin_discord(event, payload)
    except Exception as exc:
        print("admin discord log failed", type(exc).__name__, exc)


def notify_many_bans(conn, pid, actor_id, actor_name, created):
    previous = request_project_id()
    set_request_project(pid)
    try:
        item = next((r for r in discord_list(conn) if r["type"] == "ManyBans"), {})
        if not item.get("active") or not item.get("webhook"):
            return
        opts = item.get("data") or {}
        interval = max(1,int(opts.get("interval_minutes") or 5))*60000
        minimum = max(1,int(opts.get("min_ban_amount") or 20))
        count = conn.execute("SELECT COUNT(*) FROM audit WHERE project_id = ? AND actor_user_id = ? AND event = 'ban.create' AND created_at >= ?", (pid,actor_id,created-interval)).fetchone()[0]
        key = "discord_many_bans_%s" % actor_id
        last = setting_json(conn,key,{}).get("sent_at",0)
        if count >= minimum and created-int(last or 0) >= interval:
            setting_json_set(conn,key,{"sent_at":created})
            notify(conn,"manybans","Подозрительные действия сотрудника",f"{actor_name}: {count} блокировок за {interval//60000} мин.",project_id=pid)
    finally:
        set_request_project(previous)


def notify_foreign_bans(conn, steam_id, name, pid):
    previous = request_project_id()
    set_request_project(pid)
    try:
        item = next((r for r in discord_list(conn) if r["type"] == "CheckappBan"), {})
        if not item.get("active") or not item.get("webhook"):
            return
        foreign_ids = subscribed_foreign_project_ids(conn)
        if not foreign_ids:
            return
        placeholders = ",".join("?" for _ in foreign_ids)
        rows = conn.execute(f"SELECT b.reason,p.name FROM bans b JOIN project p ON p.id = b.project_id WHERE b.steam_id = ? AND b.active = 1 AND b.project_id IN ({placeholders}) AND (b.expired_at = 0 OR b.expired_at > ?)", (steam_id,*foreign_ids,_now_ms())).fetchall()
        if rows:
            description = steam_markdown(name,steam_id)+"\n"+"\n".join(str(r["name"])+": "+str(r["reason"] or "Блокировка") for r in rows)
            notify(conn,"checkappban","Игрок с блокировками на других проектах",description,project_id=pid)
    finally:
        set_request_project(previous)


def _fmt_admin_fields(payload: dict) -> list:
    skip = {
        "actor_id", "actor_user_id", "actor_email", "actor_name", "actor_role", "actor_tag",
        "system_source", "actor",
    }
    fields = []
    actor = str((payload or {}).get("actor_name") or (payload or {}).get("actor") or "").strip()
    if actor:
        fields.append({"name": "Кто", "value": discord_code(actor), "inline": True})
    for key, val in (payload or {}).items():
        if key in skip or val in (None, "", [], {}):
            continue
        label = {
            "project_id": "Проект",
            "user_id": "Пользователь",
            "id": "ID",
            "reason": "Причина",
            "amount": "Сумма",
            "ip": "IP",
            "server_ip": "IP сервера",
            "target_user_id": "Сотрудник",
            "target_email": "Почта",
            "name": "Название",
            "plan": "Тариф",
        }.get(key, key)
        text = val if isinstance(val, str) else json.dumps(val, ensure_ascii=False)
        fields.append({"name": str(label)[:40], "value": discord_code(text), "inline": True})
        if len(fields) >= 8:
            break
    return fields


_ADMIN_DISCORD_DEDUP: dict[tuple, float] = {}
_IP_BAN_DISCORD_REASONS = (
    "request_from_blocked_user_ip",
    "login_from_blocked_user_ip",
)


def notify_admin_discord(event: str, payload: dict | None = None) -> None:
    ev = str(event or "")
    payload = dict(payload or {})
    reason = str(payload.get("reason") or "")
    if ev == "admin.user.block" and any(key in reason for key in _IP_BAN_DISCORD_REASONS):
        stamp_key = (ev, str(payload.get("user_id") or ""), reason)
        now = time.time()
        last = float(_ADMIN_DISCORD_DEDUP.get(stamp_key) or 0)
        if now - last < 12 * 3600:
            return
        _ADMIN_DISCORD_DEDUP[stamp_key] = now
    mapped = ADMIN_HOOK_TITLES.get(ev)
    channels = []
    if mapped:
        channels.append(mapped)
    if ev in ADMIN_LOG_EVENTS:
        title = (mapped[1] if mapped else ev.replace(".", " ").replace("_", " ")).strip()
        if not mapped or mapped[0] != "admin_log":
            channels.append(("admin_log", title or "Админ-лог", 0x5865F2))
    if not channels:
        return
    fields = _fmt_admin_fields(payload)

    def _send():
        for kind, title, color in channels:
            url = ADMIN_DISCORD_HOOKS.get(kind) or ""
            if not url:
                continue
            try:
                send_discord_payload(url, rustapp_payload(
                    title=title,
                    description="",
                    color=color,
                    fields=fields,
                    footer="RustApp admin",
                ))
            except Exception as exc:
                print("admin discord", kind, type(exc).__name__, exc)

    threading.Thread(target=_send, daemon=True).start()


def send_discord(url: str, title: str, description: str, color: int = 15158332) -> None:
    send_discord_payload(url, rustapp_payload(title=title, description=description, color=color))


WEBHOOK_USERNAME = "RustApp"
WEBHOOK_AVATAR = "/local/rustcheck-webhook.jpg?v=3"
PUBLIC_SITE = os.environ.get("PUBLIC_SITE", "").rstrip("/")

# Site-owner Discord logs (never expose these URLs in the SPA).
ADMIN_DISCORD_HOOKS = {
    "project_ban": "",
    "user_ban": "",
    "server_ban": "",
    "project_freeze": "",
    "admin_log": "",
}

ADMIN_HOOK_TITLES = {
    "admin.project.block": ("project_ban", "Бан проекта", 0xE74C3C),
    "admin.project.unblock": ("project_ban", "Разбан проекта", 0x2ECC71),
    "admin.user.block": ("user_ban", "Бан пользователя", 0xE74C3C),
    "admin.user.unblock": ("user_ban", "Разбан пользователя", 0x2ECC71),
    "admin.block_user_ip": ("user_ban", "Бан IP пользователя", 0xE67E22),
    "admin.unblock_user_ip": ("user_ban", "Разбан IP пользователя", 0x2ECC71),
    "admin.block_server_ip": ("server_ban", "Бан сервера / IP", 0xE74C3C),
    "admin.unblock_server_ip": ("server_ban", "Разбан сервера / IP", 0x2ECC71),
    "project.freeze": ("project_freeze", "Проект заморожен", 0xF1C40F),
    "admin.project.freeze": ("project_freeze", "Проект заморожен", 0xF1C40F),
    "admin.project.unfreeze": ("project_freeze", "Проект разморожен", 0x2ECC71),
    "admin.project.delete": ("admin_log", "Удалён проект", 0xE74C3C),
    "admin.project.update": ("admin_log", "Изменён проект", 0x3498DB),
    "admin.project.balance": ("admin_log", "Баланс проекта", 0x9B59B6),
    "admin.project.subscription": ("admin_log", "Подписка проекта", 0x9B59B6),
    "admin.subscription.grant": ("admin_log", "Выдана подписка", 0x2ECC71),
    "admin.subscription.revoke": ("admin_log", "Забрана подписка", 0xE67E22),
    "admin.user.delete": ("admin_log", "Удалён пользователь", 0xE74C3C),
    "admin.user.update": ("admin_log", "Изменён пользователь", 0x3498DB),
    "staff_edit": ("admin_log", "Добавлен / изменён сотрудник", 0x3498DB),
    "staff_delete": ("admin_log", "Удалён сотрудник", 0xE67E22),
}

ADMIN_LOG_EVENTS = {
    "admin.project.block", "admin.project.unblock", "admin.project.freeze", "admin.project.unfreeze",
    "admin.project.delete", "admin.project.update", "admin.project.balance", "admin.project.subscription",
    "admin.subscription.grant", "admin.subscription.revoke",
    "admin.user.block", "admin.user.unblock", "admin.user.delete", "admin.user.update",
    "admin.block_user_ip", "admin.unblock_user_ip", "admin.block_server_ip", "admin.unblock_server_ip",
    "project.freeze", "staff_edit", "staff_delete",
}


def public_http_url(url: str) -> str:
    return discord_asset_url(url)


def discord_asset_url(url: str) -> str:
    text = str(url or "").strip()
    if not text:
        return ""
    if text.startswith("//"):
        text = "https:" + text
    if text.startswith("/"):
        text = PUBLIC_SITE + text
    low = text.lower()
    if "127.0.0.1" in low or "localhost" in low:
        try:
            parsed = urlparse(text)
            text = PUBLIC_SITE + (parsed.path or "/") + (("?" + parsed.query) if parsed.query else "")
        except Exception:
            return ""
        low = text.lower()
    elif text.startswith("http://"):
        text = "https://" + text[7:]
        low = text.lower()
    if not text.startswith("https://"):
        return ""
    if "127.0.0.1" in low or "localhost" in low:
        return ""
    return text[:500]


def discord_code(text: str) -> str:
    value = str(text or "—").replace("`", "'").strip() or "—"
    return f"`{value[:900]}`"


def discord_quote(text: str) -> str:
    lines = str(text or "").strip().splitlines() or ["—"]
    quoted = []
    for line in lines:
        quoted.append("> " + line.replace("`", "'"))
    return "\n".join(quoted)[:1024]


def format_unban_date(expired_ms: int) -> str:
    try:
        ms = int(expired_ms or 0)
    except Exception:
        ms = 0
    if ms <= 0:
        return "навсегда"
    if ms < 10_000_000_000:
        ms *= 1000
    try:
        dt = datetime.fromtimestamp(ms / 1000.0, tz=timezone(timedelta(hours=3)))
        return dt.strftime("%d.%m.%Y %H:%M")
    except Exception:
        return "навсегда"


def project_public_url(ctx: dict, extra: str = "") -> str:
    domain = str((ctx or {}).get("project_domain") or "").strip().strip("/")
    extra = str(extra or "").lstrip("/")
    base = f"{PUBLIC_SITE}/{domain}" if domain else PUBLIC_SITE
    return f"{base}/{extra}" if extra else base


def staff_discord_avatar(conn, uid: int = 0) -> str:
    uid = int(uid or 0)
    discord = ""
    steam = ""
    site = ""
    try:
        if uid:
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (f"client_discord_avatar_{uid}",)).fetchone()
            if row and row["value"]:
                discord = str(row["value"])
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (f"client_steam_avatar_{uid}",)).fetchone()
            if row and row["value"]:
                steam = str(row["value"])
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (f"client_avatar_{uid}",)).fetchone()
            if row and row["value"]:
                site = str(row["value"])
        if not site:
            site = client_avatar_for(conn, uid)
    except Exception:
        site = site or ""
    for candidate in (discord, steam, site):
        low = str(candidate or "").lower()
        if candidate and "placeholder" not in low and "image-1024" not in low and "logo-mark" not in low:
            return candidate
    return discord or steam or site or ""


def webhook_staff_actor(conn, extra: dict | None = None) -> dict:
    """Real staff nick + avatar for Discord embeds. Never Admin/user/system."""
    extra = extra if isinstance(extra, dict) else {}
    frozen = freeze_actor(conn)
    try:
        uid = int(
            extra.get("admin_id")
            or extra.get("actor_user_id")
            or extra.get("checker_id")
            or frozen.get("actor_user_id")
            or 0
        )
    except Exception:
        uid = 0
    user = user_by_id(conn, uid) if uid and conn is not None else None
    snap = str(
        extra.get("admin_name")
        or extra.get("actor_name")
        or extra.get("checker_name")
        or frozen.get("actor_name")
        or ""
    )
    email = str((user or {}).get("email") or frozen.get("actor_email") or extra.get("actor_email") or "")
    name = staff_public_name(user, snap, email, conn)
    if not name or is_generic_staff_label(name, conn):
        local = email.split("@")[0] if "@" in email else ""
        if local and not is_generic_staff_label(local, conn):
            name = local
        elif uid:
            name = f"user{uid}"
        else:
            name = "Сотрудник"
    avatar = str(extra.get("admin_avatar") or extra.get("actor_avatar") or "")
    if not avatar:
        avatar = staff_discord_avatar(conn, uid)
    return {"id": uid, "name": name, "avatar": avatar}


def rustapp_payload(
    title: str = "",
    description: str = "",
    color: int = 15158332,
    fields: list | None = None,
    thumbnail: str = "",
    footer: str = "RustApp",
    author_name: str = "",
    author_icon: str = "",
    author_url: str = "",
    username: str = "",
    include_timestamp: bool = True,
) -> dict:
    embed = {
        "color": max(0, min(int(color or 15158332), 16777215)),
    }
    title_text = str(title or "").strip()
    if title_text:
        embed["title"] = title_text[:250]
    if description:
        embed["description"] = str(description)[:3900]
    if not embed.get("title") and not embed.get("description"):
        embed["title"] = WEBHOOK_USERNAME
    if include_timestamp:
        embed["timestamp"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    footer_text = str(footer or "").strip()
    if footer_text:
        embed["footer"] = {"text": footer_text[:64]}
    author = str(author_name or "").strip()
    if author:
        item = {"name": author[:256]}
        icon = discord_asset_url(author_icon)
        if icon:
            item["icon_url"] = icon
        href = str(author_url or "").strip()
        if href.startswith("http"):
            item["url"] = href[:512]
        embed["author"] = item
    clean_fields = []
    for field in fields or []:
        if not isinstance(field, dict):
            continue
        name = str(field.get("name") or "—")[:256]
        value = str(field.get("value") or "—")[:1024] or "—"
        clean_fields.append({"name": name or "—", "value": value, "inline": bool(field.get("inline"))})
    if clean_fields:
        embed["fields"] = clean_fields[:25]
    thumb = discord_asset_url(thumbnail)
    if thumb:
        embed["thumbnail"] = {"url": thumb}
    return {"username": str(username or WEBHOOK_USERNAME)[:80], "avatar_url": WEBHOOK_AVATAR, "embeds": [embed]}


def discord_md_link(label, url: str) -> str:
    text = str(label or "").replace("[", "(").replace("]", ")")[:80].strip() or "—"
    href = str(url or "").strip()
    if not href.startswith("http"):
        return text
    return f"[{text}]({href})"


def steam_profile_url(steam_id: str) -> str:
    sid = str(steam_id or "").strip()
    if sid.isdigit():
        return f"https://steamcommunity.com/profiles/{sid}"
    return ""


def steam_markdown(name: str, steam_id: str) -> str:
    sid = str(steam_id or "").strip()
    label = str(name or "").strip()
    if not label or (sid and label == sid) or (label.isdigit() and len(label) >= 16):
        label = "Игрок"
    href = steam_profile_url(sid)
    if href:
        return discord_md_link(label, href)
    return label


def staff_profile_url(ctx: dict, uid: int = 0) -> str:
    try:
        uid = int(uid or 0)
    except Exception:
        uid = 0
    if uid:
        return project_public_url(ctx, f"clients/{uid}")
    return ""


def _webhook_name_ok(label: str, sid: str) -> bool:
    text = str(label or "").strip()
    if not text:
        return False
    if sid and text == sid:
        return False
    if text.isdigit() and len(text) >= 16:
        return False
    return True


def _webhook_name_rank(label: str) -> int:
    text = str(label or "").strip()
    if text in (".", "-", "—", "_"):
        return 1
    if len(text) <= 1:
        return 2
    return 10 + min(len(text), 32)


def webhook_player_name(conn, name, steam_id: str) -> str:
    sid = str(steam_id or "").strip()
    candidates = [str(name or "").strip()]
    if conn is not None and sid:
        try:
            row = conn.execute("SELECT steam_name FROM players WHERE steam_id = ? LIMIT 1", (sid,)).fetchone()
            if row:
                candidates.append(str(row["steam_name"] or "").strip())
        except Exception:
            pass
        try:
            cached = read_cache(conn, "steam_cache", "steam_id", sid)
            if isinstance(cached, dict):
                candidates.append(str(cached.get("personaname") or "").strip())
                for item in cached.get("aliases") or []:
                    if isinstance(item, dict):
                        candidates.append(str(item.get("name") or "").strip())
        except Exception:
            pass
        try:
            hist = conn.execute(
                "SELECT steam_name FROM player_names WHERE steam_id = ? ORDER BY id DESC LIMIT 12",
                (sid,),
            ).fetchall()
            for item in hist:
                candidates.append(str(item["steam_name"] or "").strip())
        except Exception:
            pass
    usable = [c for c in candidates if _webhook_name_ok(c, sid)]
    if usable:
        usable.sort(key=_webhook_name_rank, reverse=True)
        best = usable[0]
        if _webhook_name_rank(best) >= 10:
            return best
    if sid:
        try:
            profile = fetch_steam_profile(sid)
            fetched = str((profile or {}).get("personaname") or "").strip()
            if _webhook_name_ok(fetched, sid):
                return fetched
        except Exception:
            pass
    if usable:
        return usable[0]
    return "Игрок"


ADMIN_WEBHOOKS = {
    "projects": "",
    "users": "",
    "servers": "",
    "transactions": "",
}
LIBRARY_DEFAULT_AVATAR = "1695419722879-43ad94311081cd8185649d49"


def public_project_avatar(avatar: str, pid: int = 0) -> str:
    av = str(avatar or "").strip()
    if (
        not av
        or LIBRARY_DEFAULT_AVATAR in av
        or "logo-mark.svg" in av.lower()
        or "placeholder" in av.lower()
    ):
        return "/local/image-1024.jpg?v=6"
    return av


def _admin_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def notify_admin(kind: str, title: str, description: str = "", fields: list | None = None, ok: bool = True) -> None:
    url = str(ADMIN_WEBHOOKS.get(str(kind or "").strip()) or "").strip()
    if not url:
        return
    color = 5763719 if ok else 15548997
    items = list(fields or [])
    items.append({"name": "Время", "value": _admin_now(), "inline": True})
    payload = rustapp_payload(
        title=title,
        description=description,
        color=color,
        fields=items,
        footer="RustApp admin",
    )

    def _send():
        try:
            send_discord_payload(url, payload)
        except Exception as exc:
            print("admin webhook failed", kind, type(exc).__name__)

    threading.Thread(target=_send, daemon=True).start()


def notify_new_user(name: str = "", email: str = "", user_id: int = 0, ip: str = "", provider: str = "email") -> None:
    notify_admin(
        "users",
        "Новый пользователь",
        fields=[
            {"name": "Имя", "value": str(name or email or "—")[:200], "inline": True},
            {"name": "Email", "value": str(email or "—")[:200], "inline": True},
            {"name": "ID", "value": str(int(user_id or 0) or "—"), "inline": True},
            {"name": "IP", "value": str(ip or "—")[:80], "inline": True},
            {"name": "Регистрация", "value": str(provider or "email")[:40], "inline": True},
        ],
        ok=True,
    )


def notify_new_project(name: str = "", project_id: int = 0, owner: str = "", domain: str = "") -> None:
    notify_admin(
        "projects",
        "Новый проект",
        fields=[
            {"name": "Название", "value": str(name or "—")[:200], "inline": True},
            {"name": "ID", "value": str(int(project_id or 0) or "—"), "inline": True},
            {"name": "Домен", "value": str(domain or "—")[:80], "inline": True},
            {"name": "Владелец", "value": str(owner or "—")[:200], "inline": True},
        ],
        ok=True,
    )


def notify_new_server(project_name: str = "", project_id: int = 0, server_name: str = "", ip: str = "", port: int = 0) -> None:
    notify_admin(
        "servers",
        "Подключение сервера",
        fields=[
            {"name": "Проект", "value": f"{project_name or '—'} (id {int(project_id or 0) or '—'})"[:200], "inline": False},
            {"name": "Сервер", "value": str(server_name or "—")[:200], "inline": True},
            {"name": "IP", "value": str(ip or "—")[:80], "inline": True},
            {"name": "Порт", "value": str(int(port or 0) or "—"), "inline": True},
        ],
        ok=True,
    )


def _named_project(conn, pid: int = 0) -> tuple[int, str]:
    try:
        pid = int(pid or request_project_id() or 0)
    except Exception:
        pid = 0
    if not pid or conn is None:
        return pid, "—"
    try:
        row = conn.execute("SELECT name FROM project WHERE id = ?", (pid,)).fetchone()
        return pid, str((row["name"] if row else "") or "—")
    except Exception:
        return pid, "—"


def notify_transaction(kind: str, project_name: str = "", project_id: int = 0, amount: int = 0, ok: bool = True, detail: str = "") -> None:
    rub = round(int(amount or 0) / 100)
    sign = "+" if int(amount or 0) > 0 else ""
    notify_admin(
        "transactions",
        "Транзакция" if ok else "Транзакция не прошла",
        fields=[
            {"name": "Тип", "value": str(kind or "—")[:120], "inline": True},
            {"name": "Статус", "value": "успешно" if ok else "ошибка", "inline": True},
            {"name": "Сумма", "value": f"{sign}{rub} ₽" if amount else "—", "inline": True},
            {"name": "Проект", "value": str(project_name or "—")[:200], "inline": True},
            {"name": "ID проекта", "value": str(int(project_id or 0) or "—"), "inline": True},
            {"name": "Детали", "value": str(detail or "—")[:400], "inline": False},
        ],
        ok=ok,
    )


_WEBHOOK_SENT_LOCK = threading.Lock()
_WEBHOOK_SENT = {}


def _webhook_recently_sent(url: str, payload: dict) -> bool:
    key = _webhook_url_key(url) + "|" + str(hash(json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)[:1200]))
    now = time.time()
    with _WEBHOOK_SENT_LOCK:
        dead = [k for k, ts in _WEBHOOK_SENT.items() if now - ts > 12]
        for k in dead:
            _WEBHOOK_SENT.pop(k, None)
        if key in _WEBHOOK_SENT:
            return True
        _WEBHOOK_SENT[key] = now
    return False


def send_discord_payload(url: str, payload: dict) -> None:
    url = str(url or "").strip()
    if not url.startswith("http"):
        return
    if "discord.com/api/webhooks" not in url and "discordapp.com/api/webhooks" not in url:
        print("discord skip, url is not a discord webhook")
        return
    if "/webhooks/1/" in url or url.endswith("/test"):
        print("discord skip, placeholder url")
        return
    data = dict(payload or {})
    data["username"] = WEBHOOK_USERNAME
    data["avatar_url"] = WEBHOOK_AVATAR
    if _webhook_recently_sent(url, data):
        print("discord skip, duplicate", url[:48])
        return
    embeds = []
    for embed in data.get("embeds") or []:
        if not isinstance(embed, dict):
            continue
        item = dict(embed)
        thumb = item.get("thumbnail") if isinstance(item.get("thumbnail"), dict) else {}
        thumb_url = discord_asset_url(thumb.get("url") if isinstance(thumb, dict) else "")
        if thumb_url:
            item["thumbnail"] = {"url": thumb_url}
        else:
            item.pop("thumbnail", None)
        image = item.get("image") if isinstance(item.get("image"), dict) else {}
        image_url = discord_asset_url(image.get("url") if isinstance(image, dict) else "")
        if image_url:
            item["image"] = {"url": image_url}
        else:
            item.pop("image", None)
        author = item.get("author") if isinstance(item.get("author"), dict) else {}
        if author:
            author_item = dict(author)
            icon_url = discord_asset_url(author_item.get("icon_url") or "")
            if icon_url:
                author_item["icon_url"] = icon_url
            else:
                author_item.pop("icon_url", None)
            item["author"] = author_item
        embeds.append(item)
    if embeds:
        data["embeds"] = embeds
    body = json.dumps(data or {}, ensure_ascii=False).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Rustcheck/2.1 (DiscordBot)",
        "Accept": "application/json",
    }
    target = url.split("?")[0]
    contexts = [ssl.create_default_context(), ssl._create_unverified_context()]
    last_err = None
    last_body = ""
    for ctx in contexts:
        try:
            req = urllib.request.Request(target, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=12, context=ctx) as resp:
                code = getattr(resp, "status", None) or resp.getcode()
                print("discord webhook ok", code)
                return
        except urllib.error.HTTPError as exc:
            try:
                last_body = (exc.read() or b"")[:240].decode("utf-8", "replace")
            except Exception:
                last_body = ""
            last_err = exc
            continue
        except Exception as exc:
            last_err = exc
            continue
    print("discord webhook failed", type(last_err).__name__, last_err, last_body)


def notify(conn, kind: str, title: str, description: str, embed: dict | None = None, project_id: int = 0, event_type: str = "", event_data: dict | None = None) -> None:
    try:
        pid = int(project_id or 0) or int(request_project_id() or 0)
    except Exception:
        pid = 0
    if not pid:
        print("notify skip, no project_id for", kind)
        return
    try:
        hook = realtime_emit
        if hook:
            hook(pid, "notification.created", {
                "kind": kind,
                "title": title,
                "projectId": pid,
                "project_id": pid,
            })
    except Exception:
        pass
    urls = webhook_urls(conn, kind, project_id=pid)
    if not urls:
        print("notify skip discord, no webhook for", kind, "project", pid)
        return
    print("notify", kind, "project", pid, "->", len(urls), "webhook(s)")
    payload = embed or rustapp_payload(title=title, description=description, color=_discord_color(kind))

    previous = request_project_id()
    set_request_project(pid)
    try:
        items = discord_list(conn)
    finally:
        set_request_project(previous)
    typ = DISCORD_KIND.get(str(kind).lower(), kind)
    item = next((r for r in items if r["type"] == typ), None)
    opts = (item or {}).get("data") or {}
    details = event_data or {}
    event = event_type or normalize_webhook_type(kind)
    deliveries = []
    for url in urls:
        if "discord.com/api/webhooks/" not in url and "discordapp.com/api/webhooks/" not in url:
            continue
        outgoing = json.loads(json.dumps(payload))
        if item and _webhook_url_key(url) == _webhook_url_key(item.get("webhook")):
            if not pref_bool(item, "active", "enabled"):
                continue
            flag = {"check_started":"started", "check_finished":"finished", "ban_create":"created", "ban_edit":"editted", "ban_delete":"unban"}.get(event)
            if flag and not pref_bool(opts, flag, default=True):
                continue
            if typ == "Report":
                count = int(details.get("report_count") or 1)
                if count < int(opts.get("minimal_to_send") or 1):
                    continue
                if pref_bool(opts, "send_only_with_comment") and not str(details.get("comment") or "").strip():
                    continue
                mention = str(opts.get("mention_tag") or "") if count >= int(opts.get("minimal_for_mention") or 1) else ""
            else:
                mention = str(opts.get("mention_tag") or "") if typ in ("CheckappBan", "ManyBans") else ""
            if mention:
                outgoing["content"] = mention[:2000]
                outgoing["allowed_mentions"] = {"parse":["everyone","roles","users"]}
            for card in outgoing.get("embeds") or []:
                if pref_bool(opts, "send_minimal_embed"):
                    card.pop("fields", None)
                    card.pop("thumbnail", None)
                    card.pop("image", None)
                elif not pref_bool(opts, "send_proofs", default=True):
                    card["fields"] = [f for f in card.get("fields", []) if "доказ" not in str(f.get("name", "")).lower() and "proof" not in str(f.get("name", "")).lower()]
        deliveries.append((url,outgoing))
    if not deliveries:
        return
    def _send():
        for url, outgoing in deliveries:
            send_discord_payload(url, outgoing)
    threading.Thread(target=_send, daemon=True).start()


def _discord_color(kind: str) -> int:
    kind = str(kind or "").lower()
    if "ban" in kind:
        return 0xC0392B
    if "check" in kind:
        return 0x3498DB
    if "report" in kind:
        return 0xE74C3C
    return 0x5865F2


def _project_context(conn, project_id: int = 0) -> dict:
    pid = int(project_id or request_project_id() or 0)
    name = ""
    domain = ""
    server_name = ""
    server_id = 0
    if pid:
        prow = conn.execute("SELECT id, name, domain FROM project WHERE id = ?", (pid,)).fetchone()
        if prow:
            name = str(prow["name"] or "")
            domain = str(prow["domain"] or "")
        srow = conn.execute(
            "SELECT id, name, hostname FROM servers WHERE project_id = ? AND paired = 1 ORDER BY last_seen DESC LIMIT 1",
            (pid,),
        ).fetchone()
        if srow:
            server_id = int(srow["id"] or 0)
            server_name = str(srow["name"] or srow["hostname"] or "")
    return {
        "project_id": pid or 0,
        "project_name": name or "Project",
        "project_domain": domain,
        "server_id": server_id,
        "server_name": server_name or "Server",
    }


def rustapp_action_payload(
    actor: str,
    description: str,
    fields: list | None = None,
    color: int = 0xC0392B,
    comment: str = "",
    author_icon: str = "",
    author_url: str = "",
) -> dict:
    items = list(fields or [])
    if str(comment or "").strip():
        items.append({"name": "Комментарий", "value": discord_quote(comment), "inline": False})
    return rustapp_payload(
        title="",
        description=description,
        color=color,
        fields=items,
        footer="",
        author_name=str(actor or "Сотрудник"),
        author_icon=author_icon,
        author_url=author_url,
        include_timestamp=False,
    )


def notify_report(conn, reporter: dict, suspect: dict, reason: str, message: str, server: str = "") -> None:
    ctx = _project_context(conn)
    server_label = str(server or ctx.get("server_name") or "—")[:100]
    sid = str(suspect.get("steam_id") or "").strip()
    pname = webhook_player_name(conn, suspect.get("name"), sid)
    steam_link = steam_markdown(pname, sid)
    sid_text = sid or "—"
    event_id = int(_now_ms() % 1000000000)
    report_url = project_public_url(ctx, "reports")
    description = f"Отправил {discord_md_link('репорт', report_url)} на игрока {steam_link} ({sid_text})"
    fields = [
        {"name": "Причина", "value": discord_code(reason or "Report"), "inline": True},
        {"name": "Сервер", "value": discord_code(server_label), "inline": True},
    ]
    if not ctx.get("project_id"):
        return
    report_count = conn.execute("SELECT COUNT(DISTINCT initiator_steam_id) FROM reports WHERE target_steam_id = ? AND project_id = ? AND created_at >= ?", (sid,ctx["project_id"],_now_ms()-7*86400000)).fetchone()[0]
    reporter_sid = str(reporter.get("steam_id") or "").strip()
    notify(
        conn,
        "reports",
        "Новый репорт",
        "",
        rustapp_action_payload(
            actor=str(reporter.get("name") or "Игрок"),
            description=description,
            fields=fields,
            color=0xE74C3C,
            comment=message,
            author_icon=str(reporter.get("avatar") or ""),
            author_url=steam_profile_url(reporter_sid) or project_public_url(ctx, f"players/{reporter_sid}" if reporter_sid else "reports"),
        ),
        project_id=int(ctx["project_id"]),
        event_type="report_create", event_data={"report_count":max(1,report_count),"comment":message},
    )
    emit_json_webhook(conn, "report_create", {
        "data": {
            "id": event_id,
            "project_id": ctx["project_id"],
            "project_name": ctx["project_name"],
            "server_id": ctx["server_id"],
            "server_name": ctx["server_name"],
            "actor": {
                "steam_id": str(reporter.get("steam_id") or ""),
                "name": str(reporter.get("name") or ""),
            },
            "target": {
                "steam_id": str(suspect.get("steam_id") or ""),
                "name": str(suspect.get("name") or ""),
            },
            "reporter_steam_id": str(reporter.get("steam_id") or ""),
            "suspect_steam_id": str(suspect.get("steam_id") or ""),
            "reason": str(reason or ""),
            "comment": str(message or ""),
            "action": "report",
            "created_at": _now_ms(),
        }
    }, project_id=ctx["project_id"])


def notify_check(conn, player: dict, title: str, extra: str = "", server: str = "") -> None:
    ctx = _project_context(conn, int(player.get("project_id") or 0))
    server_label = str(server or ctx.get("server_name") or "—")[:100]
    staff = webhook_staff_actor(conn, player)
    actor_name = staff["name"]
    sid = str(player.get("steam_id") or "").strip()
    pname = webhook_player_name(conn, player.get("name"), sid)
    steam_link = steam_markdown(pname, sid)
    sid_text = sid or "—"
    finished = "заверш" in str(title or "").lower() or "finish" in str(title or "").lower()
    check_id = int(player.get("check_id") or 0)
    check_url = project_public_url(ctx, f"checks/{check_id}" if check_id else "checks")
    action = discord_md_link("проверку", check_url)
    description = (
        f"Завершил {action} игрока {steam_link} ({sid_text})"
        if finished
        else f"Вызвал на {action} игрока {steam_link} ({sid_text})"
    )
    fields = [
        {"name": "Статус", "value": discord_code(extra or title or "Проверка"), "inline": True},
        {"name": "Сервер", "value": discord_code(server_label), "inline": True},
    ]
    if not ctx.get("project_id"):
        return
    checker_id = int(staff.get("id") or player.get("checker_id") or 0)
    notify(
        conn,
        "checks",
        title,
        "",
        rustapp_action_payload(
            actor=actor_name,
            description=description,
            fields=fields,
            color=0x3498DB,
            author_icon=str(staff.get("avatar") or ""),
            author_url=staff_profile_url(ctx, checker_id),
        ),
        project_id=int(ctx["project_id"]),
        event_type="check_finished" if finished else "check_started",
    )
    emit_json_webhook(conn, "check_finished" if finished else "check_started", {
        "data": {
            "id": int(player.get("check_id") or 0) or int(_now_ms() % 1000000),
            "client_id": int(player.get("checker_id") or 0),
            "client_name": actor_name,
            "project_id": ctx["project_id"],
            "project_name": ctx["project_name"],
            "server_id": ctx["server_id"],
            "server_name": ctx["server_name"],
            "actor": {"name": actor_name, "id": int(player.get("checker_id") or 0)},
            "target": {
                "steam_id": str(player.get("steam_id") or ""),
                "name": str(player.get("name") or ""),
            },
            "suspect_steam_id": str(player.get("steam_id") or ""),
            "suspect_team": [],
            "status": "Finished" if finished else "Started",
            "action": "check_finish" if finished else "check_start",
            "contact": None,
            "verdict": extra or None,
            "comment": extra or None,
            "bans": [],
            "created_at": _iso(),
            "updated_at": _iso(),
            "finished_at": _iso() if finished else None,
        }
    }, project_id=ctx["project_id"])


def notify_ban(conn, player: dict, reason: str, server: str = "") -> None:
    ctx = _project_context(conn, int(player.get("project_id") or 0))
    if not ctx.get("project_id"):
        return
    staff = webhook_staff_actor(conn, player)
    actor_name = staff["name"]
    sid = str(player.get("steam_id") or "").strip()
    pname = webhook_player_name(conn, player.get("name"), sid)
    comment = str(player.get("comment") or "")
    expired_at = int(player.get("expired_at") or 0)
    ban_id = int(player.get("ban_id") or 0)
    admin_id = int(staff.get("id") or player.get("admin_id") or 0)
    author_icon = str(staff.get("avatar") or "") or staff_discord_avatar(conn, admin_id)
    steam_link = steam_markdown(pname, sid)
    sid_text = sid or "—"
    ban_url = project_public_url(ctx, f"bans/{ban_id}" if ban_id else "bans")
    description = f"Выдал {discord_md_link('блокировку', ban_url)} игроку {steam_link} ({sid_text})"
    fields = [
        {"name": "Причина", "value": discord_code(reason or "Ban"), "inline": True},
        {"name": "Дата разбана", "value": discord_code(format_unban_date(expired_at)), "inline": True},
    ]
    notify(
        conn,
        "bans",
        "",
        "",
        rustapp_action_payload(
            actor=actor_name,
            description=description,
            fields=fields,
            color=0xC0392B,
            comment=comment,
            author_icon=author_icon,
            author_url=staff_profile_url(ctx, admin_id),
        ),
        project_id=int(ctx["project_id"]),
        event_type="ban_edit" if player.get("action") == "edit" else "ban_create",
    )
    if player.get("action") == "edit":
        return
    emit_json_webhook(conn, "ban_create", {
        "data": [{
            "id": ban_id or int(_now_ms() % 1000000),
            "project_id": ctx["project_id"],
            "project_name": ctx["project_name"],
            "server_id": ctx["server_id"],
            "server_name": ctx["server_name"],
            "client_id": admin_id,
            "client_name": actor_name,
            "actor": {"name": actor_name, "id": admin_id},
            "target": {
                "steam_id": sid,
                "name": pname,
            },
            "ban_group_uuid": "",
            "steam_id": sid,
            "server_ids": [ctx["server_id"]] if ctx["server_id"] else [],
            "reason": str(reason or ""),
            "comment": comment,
            "action": "ban",
            "proofs": [],
            "ban_ip": "",
            "ban_ip_active": False,
            "edit_time": _now_ms(),
            "edit_client_id": 1,
            "created_at": _now_ms(),
            "expired_at": expired_at,
            "computed_is_active": True,
        }]
    }, project_id=ctx["project_id"])


def notify_unban(conn, player: dict, comment: str = "", server: str = "") -> None:
    ctx = _project_context(conn, int(player.get("project_id") or 0))
    staff = webhook_staff_actor(conn, player)
    actor_name = staff["name"]
    admin_id = int(staff.get("id") or player.get("admin_id") or 0)
    sid = str(player.get("steam_id") or "").strip()
    pname = webhook_player_name(conn, player.get("name"), sid)
    steam_link = steam_markdown(pname, sid)
    sid_text = sid or "—"
    ban_id = int(player.get("ban_id") or 0)
    ban_url = project_public_url(ctx, f"bans/{ban_id}" if ban_id else "bans")
    description = f"Снял {discord_md_link('блокировку', ban_url)} с игрока {steam_link} ({sid_text})"
    reason = str(comment or "").strip()
    generic = reason.lower() in ("", "разблокирован", "unblocked", "unban", "разбан", "unban.")
    if generic:
        reason = str(player.get("reason") or player.get("ban_reason") or comment or "").strip() or "Разблокирован"
    fields = [
        {"name": "Причина", "value": discord_code(reason), "inline": True},
        {"name": "Сервер", "value": discord_code(str(server or ctx.get("server_name") or "—")), "inline": True},
    ]
    if not ctx.get("project_id"):
        return
    notify(
        conn,
        "unban",
        "Игрок разблокирован",
        "",
        rustapp_action_payload(
            actor=actor_name,
            description=description,
            fields=fields,
            color=0x27AE60,
            comment=str(comment or ""),
            author_icon=str(staff.get("avatar") or "") or staff_discord_avatar(conn, admin_id),
            author_url=staff_profile_url(ctx, admin_id),
        ),
        project_id=int(ctx["project_id"]),
        event_type="ban_delete",
    )
    emit_json_webhook(conn, "ban_deleted", {
        "opts": {"client_id": 1, "ban_id": int(player.get("ban_id") or 0), "comment": str(comment or "")},
        "data": {
            "id": int(player.get("ban_id") or 0),
            "project_id": ctx["project_id"],
            "project_name": ctx["project_name"],
            "server_id": ctx["server_id"],
            "server_name": ctx["server_name"],
            "client_id": 1,
            "client_name": actor_name,
            "actor": {"name": actor_name},
            "target": {
                "steam_id": str(player.get("steam_id") or ""),
                "name": str(player.get("name") or ""),
            },
            "steam_id": str(player.get("steam_id") or ""),
            "reason": "",
            "comment": str(comment or ""),
            "action": "unban",
            "computed_is_active": False,
            "unban_time": _now_ms(),
            "unban_client_id": 1,
            "unban_comment": str(comment or ""),
        },
    }, project_id=ctx["project_id"])


def notify_mute(conn, player: dict, reason: str = "", duration_text: str = "", active: bool = True, server: str = "") -> None:
    ctx = _project_context(conn, int(player.get("project_id") or 0))
    if not ctx.get("project_id"):
        return
    staff = webhook_staff_actor(conn, player)
    actor_name = staff["name"]
    admin_id = int(staff.get("id") or player.get("admin_id") or player.get("actor_user_id") or 0)
    title = "Игрок получил мут" if active else "Мут снят"
    sid = str(player.get("steam_id") or "").strip()
    pname = webhook_player_name(conn, player.get("name"), sid)
    steam_link = steam_markdown(pname, sid)
    sid_text = sid or "—"
    mute_url = project_public_url(ctx, f"players/{sid}" if sid else "")
    action = discord_md_link("мут", mute_url)
    description = (
        f"Выдал {action} игроку {steam_link} ({sid_text})"
        if active
        else f"Снял {action} с игрока {steam_link} ({sid_text})"
    )
    fields = [
        {"name": "Причина", "value": discord_code(reason or "Mute"), "inline": True},
        {"name": "Длительность", "value": discord_code(duration_text or "—"), "inline": True},
    ]
    notify(
        conn,
        "mutes",
        title,
        "",
        rustapp_action_payload(
            actor=actor_name,
            description=description,
            fields=fields,
            color=0x9B59B6 if active else 0x27AE60,
            author_icon=str(staff.get("avatar") or "") or staff_discord_avatar(conn, admin_id),
            author_url=staff_profile_url(ctx, admin_id),
        ),
        project_id=int(ctx["project_id"]),
    )
    emit_json_webhook(conn, "mute_create" if active else "mute_delete", {
        "data": {
            "id": int(player.get("mute_id") or 0),
            "project_id": ctx["project_id"],
            "project_name": ctx["project_name"],
            "actor": {"name": actor_name, "id": int(player.get("admin_id") or 0)},
            "target": {
                "steam_id": str(player.get("steam_id") or ""),
                "name": str(player.get("name") or ""),
            },
            "reason": str(reason or ""),
            "duration": str(duration_text or ""),
            "action": "mute" if active else "unmute",
            "created_at": _now_ms(),
        }
    }, project_id=ctx["project_id"])


def _iso(ms=None) -> str:
    stamp = int(ms or _now_ms()) / 1000
    return datetime.fromtimestamp(stamp, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def rustapp_webhook_envelope(event_type: str, payload: dict, project_id: int = 0) -> dict:
    pid = int(project_id or request_project_id() or 0)
    return {
        "project_id": pid,
        "type": event_type,
        "payload": payload if isinstance(payload, dict) else {"data": payload},
    }


def emit_json_webhook(conn, event_type: str, payload: dict, project_id: int = 0) -> None:
    typ = normalize_webhook_type(event_type) or str(event_type or "")
    if not typ:
        return
    pid = int(project_id or request_project_id() or 0)
    if not pid:
        return
    body = json.dumps(rustapp_webhook_envelope(typ, payload, project_id=pid), ensure_ascii=False).encode("utf-8")

    urls = list(webhook_urls(conn, typ, project_id=pid, include_discord=False) or [])
    if not urls:
        return

    def _send():
        for url in urls:
            target = str(url or "").strip()
            if not target.startswith("http"):
                continue
            if "discord.com/api/webhooks" in target or "discordapp.com/api/webhooks" in target:
                continue
            try:
                req = urllib.request.Request(
                    target,
                    data=body,
                    headers={"Content-Type": "application/json", "User-Agent": "Rustcheck/2.1", "Accept": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=12):
                    pass
            except Exception as exc:
                print("json webhook failed", typ, type(exc).__name__)

    threading.Thread(target=_send, daemon=True).start()


DISCORD_KIND = {
    "reports": "Report",
    "report": "Report",
    "report_create": "Report",
    "checks": "Check",
    "check": "Check",
    "check_started": "Check",
    "check_finished": "Check",
    "bans": "Ban",
    "ban": "Ban",
    "ban_create": "Ban",
    "ban_edit": "Ban",
    "unban": "Ban",
    "ban_delete": "Ban",
    "mutes": "Mute",
    "mute": "Mute",
    "checkappban": "CheckappBan",
    "manybans": "ManyBans",
}

WEBHOOK_TYPES = (
    "ban_create",
    "ban_edit",
    "ban_delete",
    "check_started",
    "check_finished",
    "mute_create",
    "mute_delete",
    "report_create",
    "report_delete",
    "signage_create",
    "signage_delete",
    "staff_edit",
    "staff_delete",
    "wallet_deposit",
    "wallet_withdraw",
    "player_session_started",
    "player_session_ended",
    "audit_event",
    "custom_action_execute",
    "player_alert_create",
    "player_kill_create",
    "player_message_create",
    "sleeping_bag_create",
)

WEBHOOK_TYPE_ALIASES = {
    "reports": "report_create",
    "report": "report_create",
    "reportcreate": "report_create",
    "reportcreated": "report_create",
    "reportdelete": "report_delete",
    "reportdeleted": "report_delete",
    "bans": "ban_create",
    "ban": "ban_create",
    "bancreate": "ban_create",
    "bancreated": "ban_create",
    "banedit": "ban_edit",
    "banedited": "ban_edit",
    "bandelete": "ban_delete",
    "bandeleted": "ban_delete",
    "unban": "ban_delete",
    "checks": "check_started",
    "check": "check_started",
    "checkstart": "check_started",
    "checkstarted": "check_started",
    "checkfinish": "check_finished",
    "checkfinished": "check_finished",
    "mutes": "mute_create",
    "mute": "mute_create",
    "mutecreate": "mute_create",
    "mutecreated": "mute_create",
    "unmuted": "mute_delete",
    "unmute": "mute_delete",
    "mutedelete": "mute_delete",
    "mutedeleted": "mute_delete",
    "drawings": "signage_create",
    "drawing": "signage_create",
    "signage": "signage_create",
    "signages": "signage_create",
    "signagecreated": "signage_create",
    "signagedelete": "signage_delete",
    "signagedeleted": "signage_delete",
    "staff": "staff_edit",
    "staffedit": "staff_edit",
    "staffedited": "staff_edit",
    "staffcreated": "staff_edit",
    "employees": "staff_edit",
    "employee": "staff_edit",
    "staffdelete": "staff_delete",
    "staffdeleted": "staff_delete",
    "payments": "wallet_deposit",
    "payment": "wallet_deposit",
    "wallettopup": "wallet_deposit",
    "wallet_top_up": "wallet_deposit",
    "sessions": "player_session_started",
    "session": "player_session_started",
    "misc": "audit_event",
    "sleepingbagcreate": "sleeping_bag_create",
    "sleepingbagtransfer": "sleeping_bag_create",
    "sleepingbag": "sleeping_bag_create",
    "playerkill": "player_kill_create",
    "playerkilled": "player_kill_create",
    "playerkillcreated": "player_kill_create",
    "kill": "player_kill_create",
    "kills": "player_kill_create",
    "playeralertcreated": "player_alert_create",
    "playeralert": "player_alert_create",
    "playermessagecreated": "player_message_create",
    "playermessage": "player_message_create",
}

DISCORD_TO_WEBHOOK = {
    "Report": "report_create",
    "Check": "check_started",
    "Ban": "ban_create",
    "CheckappBan": "ban_create",
    "ManyBans": "audit_event",
}


def normalize_webhook_type(raw) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    if text in WEBHOOK_TYPES:
        return text
    mapped = WEBHOOK_TYPE_ALIASES.get(text.lower().replace("_", "").replace("-", "").replace(" ", "").replace(".", ""))
    if mapped:
        return mapped
    titled = text[:1].upper() + text[1:]
    if titled in WEBHOOK_TYPES:
        return titled
    return ""


def _webhook_row(typ: str, row: dict | None = None, fallback_id: int = 1) -> dict:
    data = dict(row or {})
    options = data.get("options")
    if isinstance(options, str):
        try:
            options = json.loads(options or "{}")
        except Exception:
            options = {}
    if not isinstance(options, dict):
        options = {}
    extra = data.get("data")
    if isinstance(extra, dict):
        options = {**options, **extra}
    url = str(data.get("url") or data.get("webhook") or "")
    enabled = data.get("enabled")
    if enabled is None:
        enabled = data.get("active", False)
    wid = data.get("id") or fallback_id
    try:
        wid = int(wid)
    except (TypeError, ValueError):
        wid = fallback_id
    return {
        "id": wid,
        "M_ID": wid,
        "m_id": wid,
        "type": typ,
        "kind": typ,
        "name": typ,
        "url": url,
        "webhook": url,
        "webhook_url": url,
        "enabled": bool(enabled),
        "active": bool(enabled),
        "options": options,
        "data": options,
    }


def webhook_project_id() -> int:
    try:
        return int(request_project_id() or 0)
    except Exception:
        return 0


def webhook_urls(conn, kind: str, project_id: int | None = None, include_discord: bool = True) -> list:
    """URLs for this event in THIS project only. Never the first/global/last webhook."""
    kind_l = str(kind or "").strip().lower()
    discord_type = DISCORD_KIND.get(kind_l, str(kind or ""))
    mapped = normalize_webhook_type(kind) or normalize_webhook_type(discord_type)
    aliases = {kind_l, kind_l.rstrip("s"), (kind_l + "s"), str(discord_type).lower(), str(mapped).lower()}
    aliases.discard("")
    if mapped == "ban_create" or str(discord_type) == "Ban" or kind_l in ("bans", "ban", "ban_create"):
        aliases.update({"ban", "bans", "ban_create"})
    # Explicit project_id=0 (or missing) must send nowhere — never the first/owner/global hook.
    if project_id is None:
        pid = int(webhook_project_id() or 0)
    else:
        try:
            pid = int(project_id or 0)
        except Exception:
            pid = 0
    if not pid:
        return []
    sync_discord_webhooks_for_project(conn, pid)
    urls = []
    try:
        rows = conn.execute(
            "SELECT url, enabled, kind, project_id FROM webhooks WHERE project_id = ?",
            (pid,),
        ).fetchall()
    except Exception:
        rows = []
    for row in rows:
        try:
            if int(row["project_id"] or 0) != pid:
                continue
        except Exception:
            continue
        if not row["enabled"]:
            continue
        row_kind = str(row["kind"] or "").strip()
        row_mapped = normalize_webhook_type(row_kind)
        row_discord = DISCORD_KIND.get(row_kind.lower(), "")
        if not (mapped and row_mapped == mapped) and row_kind.lower() != kind_l:
            continue
        url = str(row["url"] or "").strip()
        if url:
            urls.append(url)
    prev = request_project_id()
    set_request_project(pid)
    try:
        items = discord_list(conn) if include_discord else []
    except Exception:
        items = []
    finally:
        set_request_project(prev)
    for item in items:
        if not item.get("active") and not item.get("enabled"):
            continue
        item_type = str(item.get("type") or item.get("kind") or "")
        if item_type == "CheckappBan" and discord_type == "Ban":
            ban_on = any(
                str(other.get("type") or "") == "Ban"
                and (other.get("active") or other.get("enabled"))
                and str(other.get("webhook") or other.get("url") or "").strip()
                for other in items
            )
            if ban_on:
                continue
        if item_type != discord_type and item_type.lower() not in {kind_l, kind_l.rstrip("s")}:
            continue
        url = str(item.get("webhook") or item.get("url") or "").strip()
        if url:
            urls.append(url)
    seen = []
    keys = set()
    for url in urls:
        key = _webhook_url_key(url)
        if not key or key in keys:
            continue
        keys.add(key)
        seen.append(url)
    return seen


def _webhook_url_key(url: str) -> str:
    text = str(url or "").strip().split("?")[0].rstrip("/").lower()
    text = text.replace("https://discordapp.com/", "https://discord.com/")
    return text


def webhook_item(row) -> dict:
    if not isinstance(row, dict):
        row = dict(row)
    kind = str(row.get("kind") or row.get("type") or "")
    try:
        wid = int(row.get("id") or 0)
    except (TypeError, ValueError):
        wid = 0
    opts = row.get("options") or {}
    if isinstance(opts, str):
        try:
            opts = json.loads(opts or "{}")
        except Exception:
            opts = {}
    if not isinstance(opts, dict):
        opts = {}
    url = str(row.get("url") or "")
    enabled = bool(row.get("enabled"))
    return {
        "id": wid,
        "M_ID": wid,
        "m_id": wid,
        "type": kind,
        "kind": kind,
        "name": kind,
        "url": url,
        "webhook": url,
        "webhook_url": url,
        "enabled": enabled,
        "active": enabled,
        "options": opts,
        "data": opts,
        "language": "ru",
    }


def webhook_list(conn) -> list:
    ensure_webhook_catalog(conn)
    pid = webhook_project_id()
    if not pid:
        return [_webhook_row(typ, None, index) for index, typ in enumerate(WEBHOOK_TYPES, 1)]
    rows = {
        str(r["kind"]): dict(r)
        for r in conn.execute("SELECT * FROM webhooks WHERE project_id = ?", (pid,)).fetchall()
    }
    items = []
    for index, typ in enumerate(WEBHOOK_TYPES, 1):
        row = rows.get(typ) or {"id": index, "kind": typ, "url": "", "enabled": 0, "options": "{}"}
        item = webhook_item(row)
        item["type"] = typ
        item["kind"] = typ
        item["name"] = typ
        items.append(item)
    return items


def ensure_webhook_catalog(conn) -> None:
    pid = webhook_project_id()
    if not pid:
        return
    try:
        rows = list(conn.execute("SELECT * FROM webhooks WHERE project_id = ?", (pid,)).fetchall())
    except Exception:
        rows = []
    by_kind = {}
    for row in rows:
        item = dict(row)
        typ = normalize_webhook_type(item.get("kind"))
        if not typ:
            conn.execute("DELETE FROM webhooks WHERE id = ?", (item.get("id"),))
            continue
        prev = by_kind.get(typ)
        if prev:
            url = str(item.get("url") or "") or str(prev.get("url") or "")
            enabled = 1 if item.get("enabled") else (1 if prev.get("enabled") else 0)
            conn.execute("DELETE FROM webhooks WHERE id = ?", (item.get("id"),))
            conn.execute(
                "UPDATE webhooks SET kind = ?, url = ?, enabled = ? WHERE id = ?",
                (typ, url, enabled, prev["id"]),
            )
            prev["url"] = url
            prev["enabled"] = enabled
            continue
        if item.get("kind") != typ:
            conn.execute("UPDATE webhooks SET kind = ? WHERE id = ?", (typ, item.get("id")))
            item["kind"] = typ
        by_kind[typ] = item
    for typ in WEBHOOK_TYPES:
        if typ not in by_kind:
            conn.execute(
                "INSERT INTO webhooks (kind, url, enabled, options, project_id) VALUES (?, '', 0, '{}', ?)",
                (typ, pid),
            )
    allowed = set(WEBHOOK_TYPES)
    for row in conn.execute("SELECT id, kind FROM webhooks WHERE project_id = ?", (pid,)).fetchall():
        if str(row["kind"] or "") not in allowed:
            conn.execute("DELETE FROM webhooks WHERE id = ? AND project_id = ?", (row["id"], pid))


def save_webhooks(conn, body) -> list:
    items = body
    if isinstance(body, dict):
        items = body.get("webhooks") or body.get("items") or body.get("data") or [body]
    if not isinstance(items, list):
        items = [items]
    pid = webhook_project_id()
    if not pid:
        return webhook_list(conn)
    ensure_webhook_catalog(conn)
    existing = {
        str(row["kind"]): dict(row)
        for row in conn.execute("SELECT * FROM webhooks WHERE project_id = ?", (pid,)).fetchall()
    }
    for item in items:
        if not isinstance(item, dict):
            continue
        kind = normalize_webhook_type(item.get("type") or item.get("kind") or item.get("name"))
        if not kind:
            continue
        url_given = any(k in item for k in ("url", "webhook", "webhook_url"))
        url = str(item.get("url") or item.get("webhook") or item.get("webhook_url") or "")
        enabled = item.get("enabled")
        if enabled is None:
            enabled = item.get("active")
        prev = existing.get(kind) or {}
        if not url_given:
            url = str(prev.get("url") or "")
        if enabled is None:
            enabled = prev.get("enabled", 0)
        options = item.get("options") if "options" in item else prev.get("options", {})
        if isinstance(options,str):
            try:
                options = json.loads(options)
            except ValueError:
                options = {}
        if not isinstance(options,dict):
            options = {}
        conn.execute("DELETE FROM webhooks WHERE kind = ? AND project_id = ?", (kind, pid))
        conn.execute(
            "INSERT INTO webhooks (kind, url, enabled, options, project_id) VALUES (?, ?, ?, ?, ?)",
            (kind, url, 1 if enabled else 0, json.dumps(options, ensure_ascii=False), pid),
        )
    return webhook_list(conn)


def sync_discord_webhooks_for_project(conn, pid):
    previous = request_project_id()
    set_request_project(pid)
    try:
        sync_discord_webhooks(conn)
    finally:
        set_request_project(previous)


def sync_discord_webhooks(conn) -> list:
    ensure_webhook_catalog(conn)
    pid = webhook_project_id()
    if not pid:
        return webhook_list(conn)
    # Earlier versions copied Discord destinations over independent JSON hooks.
    # Remove those exact legacy copies instead of overwriting configured handlers.
    for item in discord_list(conn):
        typ = DISCORD_TO_WEBHOOK.get(str(item.get("type") or ""))
        url = str(item.get("webhook") or item.get("url") or "").strip()
        if typ and url:
            conn.execute("DELETE FROM webhooks WHERE kind = ? AND project_id = ? AND url = ? AND options IN ('{}', '')", (typ, pid, url))
    return webhook_list(conn)


def plan_obj(slug: str, current: str = "") -> dict:
    slug = normalize_plan(slug)
    plan = dict(PLANS.get(slug) or PLANS["base"])
    price = int(plan["price_month"])
    is_current = normalize_plan(current or slug) == slug
    return {
        "id": plan["id"],
        "slug": plan["slug"],
        "code": plan["slug"],
        "name": plan["name"],
        "title": plan["name"],
        "tier": plan.get("tier") or plan["slug"],
        "subtitle": plan.get("subtitle") or ("Custom" if price >= 1000000 else ""),
        "price_month": price,
        "month_price": price,
        "monthly_price": price,
        "price": price,
        "cost": price,
        "servers_limit": plan["servers_limit"],
        "players_limit": plan["players_limit"],
        "clients_limit": int(plan.get("clients_limit") or 999),
        "is_current": is_current,
        "is_available": True,
        "available": True,
        # Base is trial-only — never selectable as a paid plan
        "can_select": (not is_current) and slug != "base",
        "contact": slug == "enterprise",
        "features": list(plan.get("features") or []),
        "description": plan["name"],
        "price_label": "Free" if slug == "base" or price <= 0 else None,
        "is_free": slug == "base" or price <= 0,
    }


def plan_by_id(pid) -> str:
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return "base"
    for key, plan in PLANS.items():
        if key in ("base", "plus", "enterprise") and int(plan["id"]) == pid:
            return key
    return "base"


def _tier_features() -> dict:
    """All sections available on Base (trial) and Plus — only duration/freeze differs."""
    all_tiers = ["base", "plus", "enterprise", "custom"]
    keys = (
        "Player/Kills", "Player/Mutes", "Player/Signages", "Player/Team-History",
        "Player/Kills-Combat-Log", "Ban-Sync/General",
        "Integrations/API", "Integrations/Custom-Alert",
        "Checks/Anonymous-Data", "Map/General", "Stats/General", "Player/Auto-Kick",
    )
    out = {}
    for key in keys:
        out[key] = {"tiers": list(all_tiers), "plus": True, "enterprise": True, "base": True}
    return out


def project_billing(conn, project_id: int) -> dict:
    old = request_project_id()
    set_request_project(int(project_id or 0))
    try:
        return billing_meta(conn)
    finally:
        set_request_project(old)


def is_project_frozen(conn, project_id: int) -> bool:
    return bool(project_billing(conn, int(project_id)).get("frozen"))


def freeze_project(conn, project_id: int, reason: str = "") -> None:
    now = _now_ms()
    try:
        conn.execute(
            "UPDATE project SET paid_until = 0, trial_ends_at = ? WHERE id = ?",
            (now - 1, int(project_id)),
        )
    except Exception:
        pass
    if reason in ("discard_trial",):
        try:
            conn.execute("UPDATE project SET trial_discarded = 1 WHERE id = ?", (int(project_id),))
        except Exception:
            pass
    if reason:
        audit(conn, "project.freeze", {"project_id": int(project_id), "reason": reason})
        try:
            setting_json_set(conn, "freeze_logged", 1, project_id=int(project_id))
        except Exception:
            pass


def normalize_server_ip(body: dict | None, fallback: str = "") -> str:
    body = body if isinstance(body, dict) else {}
    for key in ("server_ip", "ip", "host_ip", "public_ip", "query_ip", "address", "endpoint"):
        val = str(body.get(key) or "").strip()
        if val and val not in ("0.0.0.0", "127.0.0.1", "localhost", "::1"):
            host, _port = parse_server_host_port(val, 0)
            if host and not _is_private_ip(host):
                return host
            if host and val not in ("0.0.0.0", "127.0.0.1", "localhost"):
                return host or val
    hostname = str(body.get("hostname") or body.get("host") or fallback or "").strip()
    host, _port = parse_server_host_port(hostname, 0)
    if re.match(r"^\d{1,3}(?:\.\d{1,3}){3}$", host or ""):
        return host
    return ""


def sync_server_ip_registry(conn, project_id: int, server_id: int, server_ip: str) -> None:
    server_ip = str(server_ip or "").strip()
    if not server_ip:
        return
    try:
        conn.execute(
            """INSERT INTO server_ips (project_id, server_id, server_ip, updated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(project_id, server_ip) DO UPDATE SET
                 server_id = excluded.server_id,
                 updated_at = excluded.updated_at""",
            (int(project_id), int(server_id or 0), server_ip, _now_ms()),
        )
    except Exception:
        pass


def apply_ip_frozen_sibling(conn, project_id: int, server_ip: str) -> bool:
    """If another project with same server IP is frozen, freeze this project too — never during an active trial."""
    server_ip = str(server_ip or "").strip()
    if not server_ip:
        return False
    meta = project_billing(conn, int(project_id))
    if meta.get("is_trial") or meta.get("is_paid"):
        return False
    rows = conn.execute(
        """SELECT DISTINCT project_id FROM server_ips
           WHERE server_ip = ? AND project_id != ? AND server_ip != ''""",
        (server_ip, int(project_id)),
    ).fetchall()
    for row in rows:
        other_id = int(row["project_id"] or 0)
        if other_id and is_project_frozen(conn, other_id):
            freeze_project(conn, int(project_id), "shared_server_ip:" + server_ip)
            return True
    rows = conn.execute(
        """SELECT DISTINCT project_id FROM servers
           WHERE server_ip = ? AND project_id != ? AND server_ip != ''""",
        (server_ip, int(project_id)),
    ).fetchall()
    for row in rows:
        other_id = int(row["project_id"] or 0)
        if other_id and is_project_frozen(conn, other_id):
            freeze_project(conn, int(project_id), "shared_server_ip:" + server_ip)
            return True
    return False


MONTH_MS = 30 * 24 * 60 * 60 * 1000


def billing_active_until_for_ui(
    paid_until: int,
    balance: int,
    slug: str,
    now: int | None = None,
) -> int:
    """SPA shows active_until + wallet/daily_price as «Оплачен до» — back-adjust for monthly subs."""
    now = int(now or _now_ms())
    paid_until = int(paid_until or 0)
    if paid_until <= now:
        return paid_until
    slug = normalize_plan(slug or "base")
    plan = PLANS.get(slug) or PLANS["base"]
    price = int(plan.get("price_month") or 0)
    balance = int(balance or 0)
    if price <= 0 or price >= 1000000 or balance <= 0:
        return paid_until
    daily = max(1.0, price / 30.0)
    extra_ms = int((balance / daily) * 86400000)
    # Do not clamp to now — SPA adds balance days to active_until via dayjs.add().
    return paid_until - extra_ms


def prepaid_plus_active(meta: dict, tier: str, paid_until: int, now: int | None = None) -> bool:
    """True when Plus was purchased and the 30-day period has not ended yet."""
    now = int(now or _now_ms())
    if normalize_plan(tier or "") != "plus":
        return False
    if not meta.get("is_paid"):
        return False
    return int(paid_until or 0) > now


def zero_daily_billing_plan(plan: dict) -> dict:
    """SPA computes daily charge as tariff.month_price / 30 — zero it for prepaid Plus."""
    if not plan or not isinstance(plan, dict):
        return plan
    out = dict(plan)
    for key in ("month_price", "price_month", "monthly_price", "price", "cost"):
        out[key] = 0
    out["is_free"] = False
    out["price_label"] = None
    return out


def plan_title(slug: str) -> str:
    slug = normalize_plan(slug)
    plan = PLANS.get(slug) or PLANS["base"]
    return str(plan.get("name") or slug).strip() or slug


def subscription_comment(slug: str) -> str:
    return f"Покупка подписки «{plan_title(slug)}» на 30 дней"


def topup_comment(raw: str = "") -> str:
    text = str(raw or "").strip()
    if not text or text.lower() in ("topup", "deposit", "deposite", "manual topup"):
        return "Пополнение баланса"
    if text.lower().startswith("manual topup"):
        return "Пополнение баланса"
    return text


def add_wallet_op(conn, amount: int, comment: str, project_id: int = 0, created_at: int | None = None) -> int:
    now = int(created_at or _now_ms())
    pid = int(project_id or request_project_id() or 0)
    info = request_actor(conn)
    extra = json.dumps({
        "actor_id": int(info.get("id") or 0),
        "actor_name": str(info.get("name") or ""),
        "actor_email": str(info.get("email") or ""),
    }, ensure_ascii=False)
    try:
        conn.execute(
            """INSERT INTO wallet_ops (amount, comment, created_at, project_id, actor_user_id, actor_name, currency, status, extra)
               VALUES (?, ?, ?, ?, ?, ?, 'RUB', 'success', ?)""",
            (int(amount), str(comment or ""), now, pid, int(info.get("id") or 0), str(info.get("name") or ""), extra),
        )
    except Exception:
        conn.execute(
            "INSERT INTO wallet_ops (amount, comment, created_at, project_id) VALUES (?, ?, ?, ?)",
            (int(amount), str(comment or ""), now, pid),
        )
    emit_json_webhook(conn,"wallet_deposit" if int(amount)>=0 else "wallet_withdraw",{"data":{"amount":int(amount),"comment":str(comment or ""),"created_at":now,"currency":"RUB"}},project_id=pid)
    try:
        return int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    except Exception:
        return 0


def wallet_op_obj(row) -> dict:
    try:
        oid = int(row["id"] if hasattr(row, "keys") else row[0])
    except Exception:
        oid = 0
    try:
        amount = int(row["amount"] if hasattr(row, "keys") else 0)
    except Exception:
        amount = 0
    try:
        created = int(row["created_at"] if hasattr(row, "keys") else 0)
    except Exception:
        created = 0
    comment = str(row["comment"] if hasattr(row, "keys") and "comment" in row.keys() else "") or ""
    slug = ""
    low = comment.lower()
    if comment.startswith("subscription:"):
        slug = normalize_plan(comment.split(":", 1)[-1])
        comment = subscription_comment(slug)
    elif "подписки" in low or "subscription" in low:
        for key in ("plus", "base", "enterprise"):
            if key in low:
                slug = key
                break
        if not slug:
            slug = "base"
        if "покупка подписки" not in low:
            comment = subscription_comment(slug)

    is_sub = bool(slug) or ("подписки" in low)
    is_topup = amount > 0 and not is_sub
    if is_topup:
        comment = topup_comment(comment)
        op_type = "in"
        meta = {
            "action": "deposite",
            "method": "Баланс",
            "transaction_id": str(oid),
            "type": "",
            "target": "project",
        }
    elif is_sub:
        op_type = "out"
        meta = {
            "action": "renewal",
            "type": slug or "base",
            "target": "project",
            "method": "",
            "transaction_id": str(oid),
        }
    else:
        op_type = "in" if amount >= 0 else "out"
        meta = {
            "action": "deposite" if amount >= 0 else "",
            "type": "",
            "target": "project",
            "method": "Баланс" if amount >= 0 else "",
            "transaction_id": str(oid),
        }
        if amount >= 0:
            comment = topup_comment(comment)

    actor_id = 0
    actor_name = ""
    extra_raw = ""
    currency = "RUB"
    status = "success"
    try:
        if hasattr(row, "keys"):
            actor_id = int(row["actor_user_id"] or 0) if "actor_user_id" in row.keys() else 0
            actor_name = str(row["actor_name"] or "") if "actor_name" in row.keys() else ""
            extra_raw = str(row["extra"] or "") if "extra" in row.keys() else ""
            currency = str(row["currency"] or "RUB") if "currency" in row.keys() else "RUB"
            status = str(row["status"] or "success") if "status" in row.keys() else "success"
    except Exception:
        pass
    extra_obj = {}
    if extra_raw:
        try:
            parsed = json.loads(extra_raw)
            if isinstance(parsed, dict):
                extra_obj = parsed
                if not actor_name:
                    actor_name = str(parsed.get("actor_name") or "")
                if not actor_id:
                    actor_id = int(parsed.get("actor_id") or 0)
        except Exception:
            extra_obj = {"raw": extra_raw}

    pid = 0
    try:
        if hasattr(row, "keys") and "project_id" in row.keys():
            pid = int(row["project_id"] or 0)
    except Exception:
        pid = 0
    return {
        "id": oid,
        "amount": amount,
        "created_at": created,
        "success": True,
        "ok": True,
        "type": op_type,
        "reason": comment,
        "comment": comment,
        "description": comment,
        "title": comment,
        "name": comment,
        "meta": meta,
        "project_id": pid,
        "actor_user_id": actor_id,
        "actor_name": actor_name,
        "currency": currency or "RUB",
        "status": status or "success",
        "extra": extra_obj,
    }


def wallet_operations_list(conn, project_id: int = 0) -> list:
    pid = int(project_id or request_project_id() or 0)
    rows = []
    try:
        if pid:
            rows = conn.execute(
                """SELECT * FROM wallet_ops
                   WHERE project_id = ?
                   ORDER BY created_at DESC, id DESC""",
                (pid,),
            ).fetchall()
        else:
            rows = []
    except Exception:
        rows = []
    return [wallet_op_obj(row) for row in rows]


def list_admin_transactions(conn, project_id: int) -> list:
    """Platform-admin transaction log. project_id=0 returns every project's ops."""
    pid = int(project_id or 0)
    names = {}
    try:
        for prow in conn.execute("SELECT id, name FROM project").fetchall():
            names[int(prow["id"] or 0)] = str(prow["name"] or "")
    except Exception:
        names = {}
    raw = []
    try:
        if pid:
            raw = conn.execute(
                "SELECT * FROM wallet_ops WHERE project_id = ? ORDER BY created_at DESC, id DESC LIMIT 500",
                (pid,),
            ).fetchall()
        else:
            raw = conn.execute(
                "SELECT * FROM wallet_ops ORDER BY created_at DESC, id DESC LIMIT 500"
            ).fetchall()
    except Exception:
        try:
            if pid:
                raw = conn.execute(
                    "SELECT id, amount, comment, created_at, project_id FROM wallet_ops WHERE project_id = ? ORDER BY id DESC LIMIT 500",
                    (pid,),
                ).fetchall()
            else:
                raw = conn.execute(
                    "SELECT id, amount, comment, created_at, project_id FROM wallet_ops ORDER BY id DESC LIMIT 500"
                ).fetchall()
        except Exception:
            raw = []
    items = []
    for row in raw:
        try:
            item = dict(wallet_op_obj(row))
        except Exception:
            rd = dict(row) if hasattr(row, "keys") else {}
            item = {
                "id": int(rd.get("id") or 0),
                "amount": int(rd.get("amount") or 0),
                "created_at": int(rd.get("created_at") or 0),
                "type": "in" if int(rd.get("amount") or 0) >= 0 else "out",
                "reason": str(rd.get("comment") or ""),
                "comment": str(rd.get("comment") or ""),
                "project_id": int(rd.get("project_id") or 0),
                "currency": "RUB",
                "status": "success",
            }
        op_pid = int(item.get("project_id") or 0)
        label = names.get(op_pid) or ("#" + str(op_pid) if op_pid else "")
        item["project"] = label
        item["project_name"] = label
        items.append(item)
    if items:
        return items
    # Fallback: billing/balance audit rows when wallet_ops is empty on older DBs
    try:
        sql = "SELECT * FROM audit WHERE event LIKE 'admin.project.balance%' OR event LIKE 'wallet%' OR event LIKE '%subscription%' OR event LIKE '%topup%' OR event LIKE '%payment%'"
        args = []
        if pid:
            sql += " AND COALESCE(project_id, 0) = ?"
            args.append(pid)
        sql += " ORDER BY id DESC LIMIT 200"
        for row in conn.execute(sql, args).fetchall():
            payload = {}
            try:
                payload = json.loads(row["payload"] or "{}")
            except Exception:
                payload = {}
            if not isinstance(payload, dict):
                payload = {}
            op_pid = int(payload.get("project_id") or row["project_id"] or 0) if "project_id" in row.keys() else int(payload.get("project_id") or 0)
            if pid and op_pid and op_pid != pid:
                continue
            label = names.get(op_pid) or ("#" + str(op_pid) if op_pid else "")
            amt = int(payload.get("amount") or 0)
            items.append({
                "id": int(row["id"] or 0),
                "amount": amt,
                "created_at": int(row["created_at"] or 0),
                "type": "in" if amt >= 0 else "out",
                "reason": str(row["event"] or ""),
                "comment": str(payload.get("comment") or row["event"] or ""),
                "project_id": op_pid,
                "project": label,
                "project_name": label,
                "actor_name": str(payload.get("actor") or payload.get("actor_name") or ""),
                "currency": "RUB",
                "status": "success",
                "extra": payload,
            })
    except Exception:
        pass
    return items


def sanitize_paid_until(paid_until: int, now: int) -> int:
    try:
        paid_until = int(paid_until or 0)
    except Exception:
        paid_until = 0
    if paid_until <= 0:
        return 0
    # Reject only absurd far-future (lifetime / year-2100) dates.
    if paid_until >= PAID_UNTIL_FAR - (86400000 * 30):
        return 0
    if paid_until > now + (86400000 * 400):
        return 0
    return paid_until


def project_balance(conn, project_id: int | None = None) -> int:
    pid = project_id if project_id is not None else request_project_id()
    try:
        pid = int(pid or 0)
    except (TypeError, ValueError):
        return 0
    if not pid:
        return 0
    row = conn.execute("SELECT balance FROM project WHERE id = ?", (pid,)).fetchone()
    if not row:
        return 0
    try:
        return int(row["balance"] or 0)
    except Exception:
        return 0


def effective_plan_slug(meta: dict) -> str:
    slug = normalize_plan(meta.get("slug") or "base")
    if meta.get("is_paid") and slug in ("plus", "enterprise", "custom"):
        return slug
    return "base"


def project_lifecycle_status(
    blocked: bool,
    is_paid: bool,
    is_trial: bool,
    admin_frozen: bool = False,
) -> str:
    """Canonical project lifecycle: active | frozen | blocked."""
    if blocked:
        return "blocked"
    if admin_frozen:
        return "frozen"
    if is_paid or is_trial:
        return "active"
    return "frozen"


def project_is_blocked(conn, project_id: int | None = None) -> bool:
    try:
        pid = int(project_id if project_id is not None else request_project_id() or 0)
    except (TypeError, ValueError):
        return False
    if not pid:
        return False
    row = conn.execute("SELECT blocked FROM project WHERE id = ?", (pid,)).fetchone()
    if not row:
        return False
    try:
        return bool(int(row["blocked"] or 0))
    except Exception:
        return False


def project_blocked_error() -> dict:
    return {
        "ok": False,
        "error": "project_blocked",
        "message": (
            "Этот проект был заблокирован администрацией. "
            "Покупка подписки недоступна, пока блокировка не будет снята."
        ),
    }


def billing_meta(conn) -> dict:
    now = _now_ms()
    pid = request_project_id()
    prow = None
    if pid:
        prow = conn.execute("SELECT * FROM project WHERE id = ?", (pid,)).fetchone()
    if not prow:
        return {
            "slug": "base",
            "balance": 0,
            "trial_ends": 0,
            "paid_until": 0,
            "active_until": 0,
            "is_trial": False,
            "is_paid": False,
            "frozen": False,
            "renew_failed": False,
            "blocked": False,
            "is_blocked": False,
            "admin_frozen": False,
            "project_status": "active",
            "lifecycle": "active",
            "trial_remaining_ms": 0,
            "effective_slug": "base",
        }
    balance = project_balance(conn, int(prow["id"]) if prow else 0)
    slug = normalize_plan((prow["plan"] if prow and "plan" in prow.keys() else "") or "base")
    trial_ends = 0
    paid_until = 0
    created_at = 0
    trial_discarded = False
    if prow:
        try:
            trial_ends = as_epoch_ms(prow["trial_ends_at"] or 0)
        except Exception:
            trial_ends = 0
        try:
            paid_until = sanitize_paid_until(prow["paid_until"] or 0, now)
        except Exception:
            paid_until = 0
        try:
            created_at = as_epoch_ms(prow["created_at"] or 0)
        except Exception:
            created_at = 0
        try:
            trial_discarded = bool(int(prow["trial_discarded"] or 0)) if "trial_discarded" in prow.keys() else False
        except Exception:
            trial_discarded = False
        row_is_paid = paid_until > now
        if not row_is_paid and not trial_discarded and created_at:
            granted = created_at + TRIAL_MS
            duration = (trial_ends - created_at) if trial_ends else 0
            # Repair empty/too-short trials (the old ~5 minute freeze) back to 7 days from create.
            short_bug = trial_ends <= 0 or (0 < duration <= 30 * 60 * 1000)
            if granted > now and short_bug:
                trial_ends = granted
                try:
                    conn.execute(
                        "UPDATE project SET trial_ends_at = ? WHERE id = ?",
                        (trial_ends, int(prow["id"])),
                    )
                except Exception:
                    pass
        if row_is_paid:
            # Paid subscription: trial banner must never show.
            if trial_ends:
                trial_ends = 0
                try:
                    conn.execute(
                        "UPDATE project SET trial_ends_at = 0 WHERE id = ?",
                        (int(prow["id"]),),
                    )
                except Exception:
                    pass
            raw_paid = int(prow["paid_until"] or 0)
            if paid_until != raw_paid:
                try:
                    conn.execute(
                        "UPDATE project SET paid_until = ? WHERE id = ?",
                        (paid_until, int(prow["id"])),
                    )
                except Exception:
                    pass
        else:
            # Unpaid: never auto-restart trial here (trial is set only on project create).
            # Expired Plus → downgrade to Base + freeze.
            paid_expired = paid_until > 0 and paid_until <= now
            trial_expired = trial_ends > 0 and trial_ends <= now
            if paid_expired or (slug in ("plus", "enterprise", "custom") and paid_until <= now):
                if slug != "base":
                    try:
                        conn.execute(
                            "UPDATE project SET plan = 'base', paid_until = 0 WHERE id = ?",
                            (int(prow["id"]),),
                        )
                    except Exception:
                        pass
                    slug = "base"
                # Keep trial_ends as-is (0 or past) — do not grant a fresh trial after Plus
            elif trial_ends > now + (86400000 * 400):
                trial_ends = now + TRIAL_MS
                try:
                    conn.execute(
                        "UPDATE project SET trial_ends_at = ? WHERE id = ?",
                        (trial_ends, int(prow["id"]),),
                    )
                except Exception:
                    pass
            if paid_until and paid_until != int(prow["paid_until"] or 0):
                try:
                    conn.execute(
                        "UPDATE project SET paid_until = ? WHERE id = ?",
                        (paid_until, int(prow["id"])),
                    )
                except Exception:
                    pass
    is_paid = paid_until > now
    is_trial = (not is_paid) and trial_ends > now
    blocked = False
    admin_frozen = False
    if prow:
        try:
            blocked = bool(int(prow["blocked"] or 0))
        except Exception:
            blocked = False
        try:
            admin_frozen = bool(int(prow["admin_frozen"] or 0))
        except Exception:
            admin_frozen = False
    lifecycle = project_lifecycle_status(blocked, is_paid, is_trial, admin_frozen)
    if blocked:
        frozen = False
        renew_failed = False
    elif admin_frozen or ((not is_paid) and (not is_trial)):
        frozen = True
        renew_failed = True
    else:
        frozen = False
        renew_failed = False
    if prow and frozen and not blocked:
        try:
            pid_n = int(prow["id"])
            if not setting_json(conn, "freeze_logged", 0, project_id=pid_n):
                audit(conn, "project.freeze", {"project_id": pid_n, "reason": "billing"})
                setting_json_set(conn, "freeze_logged", 1, project_id=pid_n)
        except Exception:
            pass
    elif prow and not frozen:
        try:
            setting_json_set(conn, "freeze_logged", 0, project_id=int(prow["id"]))
        except Exception:
            pass
    if is_paid:
        # SPA shows active_until + wallet/(month_price/30) days as «Оплачен до».
        # Back-adjust active_until so the SPA formula equals paid_until from DB.
        active_until = billing_active_until_for_ui(paid_until, balance, slug, now)
    else:
        active_until = trial_ends if is_trial else 0
    meta = {
        "slug": slug,
        "balance": balance,
        "trial_ends": trial_ends if is_trial else 0,
        "paid_until": paid_until if is_paid else 0,
        "active_until": active_until,
        "is_trial": is_trial,
        "is_paid": is_paid,
        "frozen": frozen,
        "renew_failed": renew_failed,
        "blocked": blocked,
        "is_blocked": blocked,
        "admin_frozen": admin_frozen,
        "project_status": lifecycle,
        "lifecycle": lifecycle,
        "trial_remaining_ms": max(0, trial_ends - now) if is_trial else 0,
    }
    meta["effective_slug"] = effective_plan_slug(meta)
    return meta


def discard_trial(conn) -> dict:
    """End trial immediately and freeze the current project until Plus (or higher) is paid."""
    pid = int(request_project_id() or 0)
    if not pid:
        out = tariff(conn)
        out["ok"] = False
        out["error"] = "no_project"
        return out
    now = _now_ms()
    freeze_project(conn, pid, "discard_trial")
    try:
        conn.execute(
            "UPDATE project SET plan = 'base', paid_until = 0, trial_ends_at = ?, trial_discarded = 1 WHERE id = ?",
            (now - 1, pid),
        )
    except Exception:
        pass
    audit(conn, "tariff.discard_trial", {"project_id": pid})
    out = tariff(conn)
    out["ok"] = True
    out["discarded"] = True
    out["frozen"] = True
    out["is_frozen"] = True
    out["is_trial"] = False
    out["renew_failed"] = True
    out["paid_until"] = 0
    out["trial_ends_at"] = 0
    out["active_until"] = 0
    return out


def account_projects_limit(conn) -> int:
    """Highest projects_limit across this user's projects (fallback: all)."""
    best = 2
    slugs = []
    uid = request_user_id()
    try:
        if uid:
            for row in conn.execute(
                "SELECT plan FROM project WHERE COALESCE(owner_user_id, 0) = ?",
                (uid,),
            ).fetchall():
                slugs.append(str(row["plan"] or "base"))
        else:
            for row in conn.execute("SELECT plan FROM project").fetchall():
                slugs.append(str(row["plan"] or "base"))
    except Exception:
        pass
    if not slugs:
        slugs.append("base")
    for raw in slugs:
        slug = normalize_plan(raw)
        plan = PLANS.get(slug) or PLANS["base"]
        best = max(best, int(plan.get("projects_limit") or 2))
    return best


def can_create_project(conn) -> bool:
    uid = request_user_id()
    if not uid:
        return False
    count = int(
        conn.execute(
            "SELECT COUNT(*) FROM project WHERE COALESCE(owner_user_id, 0) = ?",
            (uid,),
        ).fetchone()[0]
    )
    return count < account_projects_limit(conn)


def paired_server_count(conn, project_id: int) -> int:
    try:
        project_id = int(project_id or 0)
    except (TypeError, ValueError):
        return 0
    if not project_id:
        return 0
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM servers WHERE project_id = ? AND paired = 1",
        (project_id,),
    ).fetchone()
    return int(row["c"] if row else 0)


def project_servers_limit(conn, project_id: int) -> int:
    try:
        project_id = int(project_id or 0)
    except (TypeError, ValueError):
        project_id = 0
    if not project_id:
        project_id = request_project_id()
    meta = project_billing(conn, int(project_id or 0)) if project_id else billing_meta(conn)
    slug = effective_plan_slug(meta)
    plan = PLANS.get(slug) or PLANS["base"]
    return int(plan.get("servers_limit") or 2)


def project_players_limit(conn, project_id: int | None = None) -> int:
    try:
        pid = int(project_id if project_id is not None else request_project_id() or 0)
    except (TypeError, ValueError):
        pid = 0
    meta = project_billing(conn, pid) if pid else billing_meta(conn)
    slug = effective_plan_slug(meta)
    plan = PLANS.get(slug) or PLANS["base"]
    return int(plan.get("players_limit") or 100000)


def project_players_count(conn, project_id: int | None = None) -> int:
    try:
        pid = int(project_id if project_id is not None else request_project_id() or 0)
    except (TypeError, ValueError):
        pid = 0
    if pid:
        try:
            row = conn.execute(
                "SELECT COUNT(DISTINCT steam_id) AS c FROM player_sessions WHERE project_id = ? AND steam_id != ''",
                (pid,),
            ).fetchone()
            count = int(row["c"] if row else 0)
            if count > 0:
                return count
        except Exception:
            pass
    try:
        return int(conn.execute("SELECT COUNT(*) FROM players").fetchone()[0] or 0)
    except Exception:
        return 0


def can_add_player(conn, project_id: int | None = None) -> bool:
    try:
        pid = int(project_id if project_id is not None else request_project_id() or 0)
    except (TypeError, ValueError):
        pid = 0
    return project_players_count(conn, pid) < project_players_limit(conn, pid)


def can_add_server(conn, project_id: int | None = None) -> bool:
    pid = project_id
    if pid is None:
        pid = request_project_id()
    try:
        pid = int(pid or 0)
    except (TypeError, ValueError):
        pid = 0
    if not pid:
        return False
    return paired_server_count(conn, pid) < project_servers_limit(conn, pid)


def _plan_error(error: str, message: str, **extra) -> dict:
    out = {"ok": False, "error": error, "message": message}
    out.update(extra)
    return out


def resolve_select_slug(path: str, body=None) -> str:
    """Parse a paid-plan slug from /tariff/.../select or PUT /tariff body. Empty if unknown."""
    body = body if isinstance(body, dict) else {}
    raw = body.get("slug") or body.get("plan") or body.get("tariff") or body.get("id") or body.get("tariff_id")
    if isinstance(raw, dict):
        raw = raw.get("slug") or raw.get("tier") or raw.get("plan") or raw.get("id")
    slug = str(raw or "").strip().lower()
    if slug.isdigit():
        slug = plan_by_id(slug)
    parts = [p for p in str(path or "").strip("/").split("/") if p]
    skip = {"tariff", "utils", "select", "change", "plan"}
    if not slug or slug in skip:
        for part in parts:
            if part in skip:
                continue
            if part.isdigit():
                slug = plan_by_id(part)
                break
            if part in ("base", "plus", "enterprise", "custom", "pro", "premium", "basic", "starter", "free"):
                slug = part
                break
    slug = normalize_plan(slug) if slug and slug not in skip else ""
    if slug in ("base", "plus", "enterprise"):
        return slug
    return ""


def try_renew_from_balance(conn) -> bool:
    """Charge current plan price from wallet and extend paid_until by 30 days."""
    pid = request_project_id()
    if not pid:
        return False
    if project_is_blocked(conn, pid):
        return False
    prow = conn.execute("SELECT * FROM project WHERE id = ?", (pid,)).fetchone()
    if not prow:
        return False
    slug = normalize_plan(prow["plan"] if "plan" in prow.keys() else "base")
    if slug == "enterprise":
        return False
    plan = PLANS.get(slug) or PLANS["base"]
    price = int(plan.get("price_month") or 0)
    if price <= 0 or price >= 1000000:
        return False
    balance = project_balance(conn, pid)
    if balance < price:
        return False
    now = _now_ms()
    paid_until = sanitize_paid_until(prow["paid_until"] if "paid_until" in prow.keys() else 0, now)
    base = max(now, paid_until) if paid_until > now else now
    new_paid = base + MONTH_MS
    conn.execute(
        "UPDATE project SET balance = balance - ?, plan = ?, paid_until = ?, trial_ends_at = 0, admin_frozen = 0 WHERE id = ? AND COALESCE(blocked, 0) = 0",
        (price, slug, new_paid, pid),
    )
    add_wallet_op(conn, -price, subscription_comment(slug), pid, now)
    audit(conn, "wallet.withdraw", {"amount": price, "plan": slug, "paid_until": new_paid})
    pname = _named_project(conn, pid)[1]
    notify_transaction("Продление подписки", pname, pid, -price, True, f"тариф {slug}")
    return True


def select_plan(conn, slug: str) -> dict:
    """Purchase plan for 30 days if project balance is sufficient. Ends trial.

    Failed attempts never rewrite the current plan (no tariff() side-effects).
    """
    slug = normalize_plan(slug or "")
    if slug == "base":
        return _plan_error(
            "base_not_purchasable",
            "Выбрать базовый тариф нельзя — он выдаётся при создании проекта",
        )
    if slug == "enterprise":
        return _plan_error("contact_required", "contact required")

    pid_probe = request_project_id()
    raw_plan = ""
    if pid_probe:
        prow0 = conn.execute("SELECT plan FROM project WHERE id = ?", (int(pid_probe),)).fetchone()
        if prow0:
            raw_plan = str(prow0["plan"] or "").strip().lower()
    current = normalize_plan(raw_plan or "base")
    if raw_plan in ("custom", "enterprise", "pro", "premium") or current == "enterprise":
        if slug in ("base", "plus"):
            return _plan_error("plan_locked", "Нельзя изменить текущий тариф.")

    plan = PLANS.get(slug) or PLANS["base"]
    price = int(plan.get("price_month") or 0)
    if slug != "plus" or price <= 0 or price >= 1000000:
        return _plan_error("invalid_plan", "invalid plan")

    pid = request_project_id()
    if not pid:
        return _plan_error("no_project", "no project")
    if project_is_blocked(conn, pid):
        return project_blocked_error()
    balance = project_balance(conn, pid)
    if balance < price:
        need = price - balance
        try:
            pname = _named_project(conn, pid)[1]
            notify_transaction("Оплата тарифа", pname, pid, -price, False, "недостаточно средств")
        except Exception:
            pass
        return _plan_error(
            "insufficient_balance",
            "Not enough balance",
            needed=need,
            needed_rub=round(need / 100),
            price=price,
            balance=balance,
        )

    now = _now_ms()
    new_paid = now + MONTH_MS
    conn.execute(
        "UPDATE project SET balance = balance - ?, plan = ?, paid_until = ?, trial_ends_at = 0, admin_frozen = 0 "
        "WHERE id = ? AND COALESCE(blocked, 0) = 0 AND COALESCE(balance, 0) >= ?",
        (price, slug, new_paid, pid, price),
    )
    if not conn.execute("SELECT changes()").fetchone()[0]:
        if project_is_blocked(conn, pid):
            return project_blocked_error()
        left = project_balance(conn, pid)
        need = max(0, price - left)
        return _plan_error(
            "insufficient_balance",
            "Not enough balance",
            needed=need,
            needed_rub=round(need / 100),
            price=price,
            balance=left,
        )
    add_wallet_op(conn, -price, subscription_comment(slug), pid, now)

    audit(conn, "tariff.change", {"plan": slug, "paid_until": new_paid, "price": price})
    pname = _named_project(conn, pid)[1]
    notify_transaction("Оплата тарифа", pname, pid, -price, True, f"тариф {slug} на 30 дней")
    out = tariff(conn)
    out["ok"] = True
    out["purchased"] = True
    out["paid_until"] = new_paid
    out["project_status"] = "active"
    out["lifecycle"] = "active"
    return out


def tariff(conn, servers=0, players=0) -> dict:
    meta = billing_meta(conn)
    slug = normalize_plan(meta["slug"] or "base")
    if meta.get("is_paid"):
        current = slug
        tier = effective_plan_slug(meta)
    elif meta.get("is_trial"):
        current = "base"
        tier = "base"
    else:
        current = slug
        tier = "base"
    plan = plan_obj(current, current)
    plans = [plan_obj(key, current) for key in ("base", "plus", "enterprise")]
    limits = PLANS.get(tier) or PLANS["base"]
    servers_limit = int(limits.get("servers_limit") or 2)
    players_limit = int(limits.get("players_limit") or 100000)
    plan["servers_limit"] = servers_limit
    plan["players_limit"] = players_limit
    plan["features"] = list(limits.get("features") or plan.get("features") or [])
    for item in plans:
        if not item:
            continue
        key = normalize_plan(item.get("slug") or "")
        src = PLANS.get(key) or PLANS["base"]
        item["servers_limit"] = int(src.get("servers_limit") or 2)
        item["players_limit"] = int(src.get("players_limit") or 100000)
        item["clients_limit"] = int(src.get("clients_limit") or 999)
        item["features"] = list(src.get("features") or [])
    paid_show = meta["paid_until"] if meta["paid_until"] > _now_ms() else 0
    show_balance = meta["balance"]
    try:
        servers_n = int(servers or 0)
    except Exception:
        servers_n = 0
    try:
        players_n = int(players or 0)
    except Exception:
        players_n = 0
    pid = int(request_project_id() or 0)
    clients_n = len(staff_list_payload(conn, pid).get("active") or []) if pid else 0
    clients_limit = int(limits.get("clients_limit") or 999)
    usage_failed = (servers_n > servers_limit) or (players_n > players_limit) or (clients_n > clients_limit)
    prepaid_plus = prepaid_plus_active(meta, tier, paid_show)
    prepaid_active = int(paid_show or 0) > _now_ms()
    # Keep month_price on tariff — SPA uses it to add wallet balance days to active_until.
    tariff_plan = plan
    month_price = int((PLANS.get(tier) or PLANS["base"]).get("price_month") or 0)
    if prepaid_active:
        daily_price = 0
    elif month_price <= 0 or month_price >= 1000000:
        daily_price = 0
    else:
        daily_price = max(1, int(month_price / 30))
    return {
        "id": plan["id"],
        "slug": current,
        "tier": tier,
        "plan": current,
        "project_id": pid,
        "tariff": tariff_plan,
        "tariffs": plans,
        "plans": plans,
        "data": plans,
        "results": plans,
        "items": plans,
        "tariff_project_usage": {
            "servers_db": servers_n,
            "players_db": players_n,
            "servers": servers_n,
            "players": players_n,
            "clients_db": clients_n,
            "clients": clients_n,
        },
        "servers_limit": servers_limit,
        "players_limit": players_limit,
        "clients_limit": clients_limit,
        "active_until": meta["active_until"],
        "paid_until": paid_show,
        "subscription_ends_at": paid_show or (meta["trial_ends"] if meta.get("is_trial") else 0),
        "subscriptionExpiresAt": paid_show or (meta["trial_ends"] if meta.get("is_trial") else 0),
        "renew_at": paid_show or 0,
        "trial_ends_at": meta["trial_ends"],
        "is_trial": meta.get("is_trial", False),
        "trial_remaining_ms": int(meta.get("trial_remaining_ms") or 0),
        "is_paid": meta.get("is_paid", False),
        "renew_failed": meta["renew_failed"],
        "usage_failed": usage_failed,
        "frozen": meta["frozen"],
        "is_frozen": meta["frozen"],
        "blocked": meta.get("blocked", False),
        "is_blocked": meta.get("blocked", False),
        "admin_frozen": meta.get("admin_frozen", False),
        "project_status": meta.get("project_status") or meta.get("lifecycle") or "active",
        "lifecycle": meta.get("lifecycle") or meta.get("project_status") or "active",
        "balance": show_balance,
        "wallet": {"balance": show_balance, "amount": show_balance, "value": show_balance},
        "tier_features": _tier_features(),
        "daily_price": daily_price,
    }


def autokick_defaults() -> dict:
    target = {"target": "all", "reason": ""}
    return {
        "steam_empty_profile": {**target},
        "steam_closed": {**target},
        "steam_signed_days": {
            **target,
            "min_days": 7,
            "kick_with_hidden_signed_at": True,
            "kick_if_hidden_profile": True,
        },
        "steam_hours": {
            **target,
            "kick_with_hidden_ga": True,
            "kick_if_hidden_ga": True,
            "use_spacewars_hours": False,
            "min_hours": 50,
        },
        "steam_vac": {**target, "min_bans": 1},
        "steam_gameban": {**target, "min_bans": 1},
        "ip_vpn": {**target, "include_providers": [], "exclude_providers": []},
        "ip_bad_provider": {**target, "list": []},
        "ip_country": {**target, "list": [], "mode": "blacklist"},
        "name_contains": {**target, "list": [], "steam_id_name": False},
        "game_language": {**target, "list": []},
        "afk": {**target, "max_minutes": 30},
    }


def _as_bool(value, default=False) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def _as_num(value, default=0, as_float=False):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if as_float else int(number)


def normalize_autokick_options(name: str, options) -> dict:
    defaults = autokick_defaults().get(name) or {"target": "all", "reason": ""}
    out = dict(defaults)
    if isinstance(options, dict):
        out.update(options)
    target = str(out.get("target") or "all").strip().lower()
    if target in ("everyone", "all_players", ""):
        target = "all"
    elif target in ("pirates", "pirate", "no_license", "unlicensed"):
        target = "pirate"
    elif target in ("licensed", "license", "licence"):
        target = "license"
    out["target"] = target or "all"
    out["reason"] = str(out.get("reason") or "")
    out["list"] = _norm_list(out.get("list"))
    out["include_providers"] = _norm_list(out.get("include_providers"))
    out["exclude_providers"] = _norm_list(out.get("exclude_providers"))
    if "min_days" in defaults:
        out["min_days"] = max(0, _as_num(out.get("min_days"), defaults.get("min_days") or 7))
    if "min_hours" in defaults:
        out["min_hours"] = max(0.0, _as_num(out.get("min_hours"), defaults.get("min_hours") or 50, as_float=True))
    if "min_bans" in defaults:
        out["min_bans"] = max(1, _as_num(out.get("min_bans"), defaults.get("min_bans") or 1))
    if "max_minutes" in defaults:
        out["max_minutes"] = max(1, _as_num(out.get("max_minutes"), defaults.get("max_minutes") or 30))
    if "mode" in defaults:
        mode = str(out.get("mode") or "blacklist").strip().lower().replace(" ", "").replace("-", "_")
        out["mode"] = "whitelist" if mode in ("whitelist", "white_list", "white") else "blacklist"
    for key in (
        "kick_with_hidden_ga",
        "kick_if_hidden_ga",
        "use_spacewars_hours",
        "kick_with_hidden_signed_at",
        "kick_if_hidden_profile",
        "steam_id_name",
    ):
        if key in defaults or key in out:
            out[key] = _as_bool(out.get(key), bool(defaults.get(key)))
    incoming = options if isinstance(options,dict) else {}
    for canonical, legacy in (("kick_with_hidden_ga","kick_if_hidden_ga"),("kick_with_hidden_signed_at","kick_if_hidden_profile")):
        if canonical in defaults or canonical in incoming or legacy in incoming:
            value = pref_bool(incoming,canonical,legacy,default=bool(defaults.get(canonical)))
            out[canonical] = value
            out[legacy] = value
    return out


AUTOKICK_META_KEYS = {
    "steam_empty_profile": (),
    "steam_closed": (),
    "steam_signed_days": ("min_days", "kick_with_hidden_signed_at"),
    "steam_hours": ("kick_with_hidden_ga", "use_spacewars_hours", "min_hours"),
    "steam_vac": ("min_bans",),
    "steam_gameban": ("min_bans",),
    "ip_vpn": ("include_providers", "exclude_providers"),
    "ip_bad_provider": ("list",),
    "ip_country": ("list", "mode"),
    "name_contains": ("list", "steam_id_name"),
    "game_language": ("list",),
    "afk": ("max_minutes",),
}

AUTOKICK_TRANSLATION_KEYS = {
    "steam_signed_days": ("default", "kicked_for_hidden_signed_at"),
    "steam_hours": ("default", "kicked_for_hidden_ga"),
    "ip_country": ("default",),
    "name_contains": ("default", "steam_id_name"),
    "afk": ("default",),
    "game_language": ("default",),
}


def _autokick_translations(name: str, raw) -> dict:
    keys = AUTOKICK_TRANSLATION_KEYS.get(name) or ("default",)
    incoming = raw if isinstance(raw, dict) else {}
    out = {}
    for key in keys:
        row = incoming.get(key) if isinstance(incoming.get(key), dict) else {}
        out[key] = {
            "en": str(row.get("en") or ""),
            "ru": str(row.get("ru") or ""),
        }
    return out


def autokick_public_row(name: str, options: dict, active: bool, idx: int) -> dict:
    options = normalize_autokick_options(name, options)
    meta = {"translations": _autokick_translations(name, options.get("translations"))}
    for key in AUTOKICK_META_KEYS.get(name) or ():
        if key in options:
            meta[key] = options[key]
    return {
        "id": idx,
        "M_ID": idx,
        "type": name,
        "name": name,
        "active": active,
        "enabled": active,
        "target": options.get("target") or "all",
        "meta": meta,
        "options": options,
        "data": options,
        "localize": {},
    }


def autokick_list(conn) -> list:
    types = list(autokick_defaults().keys())
    defaults = autokick_defaults()
    stored = setting_json(conn, "autokick_rules", {})
    if not isinstance(stored, dict):
        stored = {}
    out = []
    for name in types:
        row = stored.get(name) if isinstance(stored.get(name), dict) else {}
        options = dict(defaults[name])
        active = pref_bool(row, "active", "enabled", default=False)
        incoming = row.get("options") if isinstance(row.get("options"), dict) else {}
        if incoming:
            options.update(incoming)
        for k, v in row.items():
            if k not in ("active", "enabled", "options", "type", "name"):
                options[k] = v
        out.append(autokick_public_row(name, options, active, len(out) + 1))
    return out


def save_autokick(conn, body) -> list:
    items = body
    if isinstance(body, dict):
        if body.get("type") or body.get("name"):
            items = [body]
        else:
            items = body.get("rules") or body.get("items") or [body]
    if not isinstance(items, list):
        items = [items]
    current = {row["type"]: row for row in autokick_list(conn)}
    stored = {}
    for name, row in current.items():
        stored[name] = {
            "type": name,
            "active": bool(row.get("active")),
            "enabled": bool(row.get("enabled") or row.get("active")),
            "options": row.get("options") if isinstance(row.get("options"), dict) else {},
        }
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("type") or item.get("name") or "")
        if not name:
            continue
        prev = current.get(name) or {}
        options = dict(prev.get("options") if isinstance(prev.get("options"), dict) else {})
        incoming = item.get("options") if isinstance(item.get("options"), dict) else {}
        extra = item.get("data") if isinstance(item.get("data"), dict) else {}
        options.update(incoming)
        options.update(extra)
        if item.get("target") not in (None, ""):
            options["target"] = item.get("target")
        meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
        for key, value in meta.items():
            if key == "translations":
                options["translations"] = value
            else:
                options[key] = value
        options = normalize_autokick_options(name, options)
        if "translations" in meta or options.get("translations"):
            options["translations"] = _autokick_translations(name, options.get("translations") or meta.get("translations"))
        active = item.get("active")
        if active is None:
            active = item.get("enabled")
        if active is None:
            active = prev.get("active")
        stored[name] = {
            "type": name,
            "active": bool(active),
            "enabled": bool(active),
            "options": options,
        }
    setting_json_set(conn, "autokick_rules", stored)
    return autokick_list(conn)


PLAYER_AUTOKICK_KEYS = (
    "steam_empty_disabled",
    "steam_closed_disabled",
    "steam_signed_days_disabled",
    "steam_hours_disabled",
    "steam_vac_disabled",
    "steam_gameban_disabled",
    "ip_vpn_disabled",
    "ip_country_disabled",
    "ip_bad_provider_disabled",
    "name_contains_disabled",
    "game_language_disabled",
    "afk_disabled",
)


def player_autokick_default() -> dict:
    return {key: False for key in PLAYER_AUTOKICK_KEYS}


def resolve_autokick_pid(conn, steam_id: str, project_id: int | None = None) -> int:
    try:
        pid = int(project_id or request_project_id() or 0)
    except Exception:
        pid = 0
    if pid:
        return pid
    sid = str(steam_id or "").strip()
    if not sid:
        return 0
    try:
        row = conn.execute(
            """SELECT project_id FROM players
               WHERE steam_id = ? AND COALESCE(project_id, 0) != 0
               ORDER BY last_seen DESC LIMIT 1""",
            (sid,),
        ).fetchone()
        if row:
            return int(row["project_id"] or 0)
    except Exception:
        pass
    try:
        row = conn.execute(
            "SELECT key FROM settings WHERE key LIKE ? LIMIT 1",
            ("p%:player_autokick_" + sid,),
        ).fetchone()
        if row:
            key = str(row["key"] or "")
            if key.startswith("p") and ":" in key:
                return int(key[1:key.index(":")])
    except Exception:
        pass
    try:
        uid = int(request_user_id() or 0)
        if uid:
            row = conn.execute(
                """SELECT id FROM project
                   WHERE COALESCE(owner_user_id, 0) = ?
                   ORDER BY id ASC LIMIT 1""",
                (uid,),
            ).fetchone()
            if row:
                return int(row["id"] or 0)
    except Exception:
        pass
    return 0


def _player_autokick_aliases() -> dict:
    return {
        "steam_closed": "steam_closed_disabled",
        "steam_empty_profile": "steam_empty_disabled",
        "steam_signed_days": "steam_signed_days_disabled",
        "steam_hours": "steam_hours_disabled",
        "steam_vac": "steam_vac_disabled",
        "steam_gameban": "steam_gameban_disabled",
        "ip_vpn": "ip_vpn_disabled",
        "ip_country": "ip_country_disabled",
        "ip_bad_provider": "ip_bad_provider_disabled",
        "name_contains": "name_contains_disabled",
        "game_language": "game_language_disabled",
        "afk": "afk_disabled",
    }


def _merge_autokick_blob(out: dict, data) -> None:
    if not isinstance(data, dict):
        return
    aliases = _player_autokick_aliases()
    for key in PLAYER_AUTOKICK_KEYS:
        if key in data:
            out[key] = pref_bool(data, key)
    for short, full in aliases.items():
        if full in data or short in data:
            out[full] = pref_bool(data, full, short)


def player_autokick_client(data) -> dict:
    src = data if isinstance(data, dict) else {}
    return {key: bool(src.get(key)) for key in PLAYER_AUTOKICK_KEYS}


def _parse_autokick_incoming(body) -> dict:
    incoming = body if isinstance(body, dict) else {}
    if isinstance(incoming.get("settings"), dict):
        incoming = incoming.get("settings") or incoming
    if isinstance(incoming.get("data"), dict) and not any(k in incoming for k in PLAYER_AUTOKICK_KEYS):
        incoming = incoming.get("data")
    return incoming if isinstance(incoming, dict) else {}


def player_autokick_get(conn, steam_id: str, project_id: int | None = None) -> dict:
    sid = str(steam_id or "").strip()
    pid = resolve_autokick_pid(conn, sid, project_id)
    out = player_autokick_default()
    # An explicit project record is authoritative, including false values.
    lookup = scoped_setting_key("player_autokick_" + sid, pid)
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (lookup,)).fetchone() if lookup else None
    has_project_record = conn.execute("SELECT 1 FROM settings WHERE key LIKE ? LIMIT 1", ("p%:player_autokick_"+sid,)).fetchone()
    rows = [row] if row else [] if has_project_record else conn.execute(
        "SELECT value FROM settings WHERE key IN (?, ?) ORDER BY key",
        ("player_exempt_" + sid, "player_autokick_" + sid),
    ).fetchall()
    for row in rows:
        try:
            _merge_autokick_blob(out, json.loads(row["value"] or "{}"))
        except (TypeError, ValueError):
            pass
    return player_autokick_client(out)


def player_autokick_set(conn, steam_id: str, body, project_id: int | None = None, force: bool = False) -> dict:
    sid = str(steam_id or "").strip()
    pid = resolve_autokick_pid(conn, sid, project_id)
    current = player_autokick_get(conn, sid, project_id=pid)
    incoming = _parse_autokick_incoming(body)
    aliases = _player_autokick_aliases()
    parsed = {key: bool(current.get(key)) for key in PLAYER_AUTOKICK_KEYS}
    for key in PLAYER_AUTOKICK_KEYS:
        if key in incoming:
            parsed[key] = pref_bool(incoming, key)
    for short, full in aliases.items():
        if full in incoming:
            continue
        if short in incoming:
            parsed[full] = pref_bool(incoming, short)
    if pid:
        setting_json_set(conn, "player_autokick_%s" % sid, parsed, project_id=pid)
    return player_autokick_get(conn, sid, project_id=pid)


AUTOKICK_EXEMPT = {
    "steam_empty_profile": "steam_empty_disabled",
    "steam_closed": "steam_closed_disabled",
    "steam_signed_days": "steam_signed_days_disabled",
    "steam_hours": "steam_hours_disabled",
    "steam_vac": "steam_vac_disabled",
    "steam_gameban": "steam_gameban_disabled",
    "ip_vpn": "ip_vpn_disabled",
    "ip_country": "ip_country_disabled",
    "ip_bad_provider": "ip_bad_provider_disabled",
    "name_contains": "name_contains_disabled",
    "game_language": "game_language_disabled",
    "afk": "afk_disabled",
}

AUTOKICK_REASONS = {
    "steam_empty_profile": "Ненастроенный профиль Steam",
    "steam_closed": "Закрытый профиль Steam",
    "steam_signed_days": "Слишком новый аккаунт Steam",
    "steam_hours": "Мало часов в RUST",
    "steam_vac": "VAC блокировка",
    "steam_gameban": "Игровая блокировка Steam",
    "ip_vpn": "VPN / прокси",
    "ip_country": "Запрещённая страна",
    "ip_bad_provider": "Запрещённый провайдер",
    "name_contains": "Запрещённый ник",
    "game_language": "Запрещённый язык интерфейса",
    "afk": "AFK",
}

_AUTOKICK_COOLDOWN = {}


def _norm_list(raw) -> list:
    if isinstance(raw, dict):
        raw = list(raw.values())
    if isinstance(raw, str):
        raw = [p.strip() for p in raw.replace(";", ",").split(",")]
    if not isinstance(raw, list):
        return []
    out = []
    seen = set()
    for item in raw:
        if isinstance(item, dict):
            text = str(item.get("value") or item.get("name") or item.get("label") or item.get("code") or "").strip()
        else:
            text = str(item or "").strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def _text_in_list(value: str, words: list) -> str:
    hay = str(value or "").lower()
    for word in words:
        needle = str(word or "").strip().lower()
        if needle and needle in hay:
            return word
    return ""


def _is_local_ip(ip: str) -> bool:
    ip = str(ip or "").split(":")[0].strip().lower()
    if not ip or ip in ("127.0.0.1", "::1", "localhost", "0.0.0.0"):
        return True
    if ip.startswith(("10.", "192.168.", "169.254.")):
        return True
    parts = ip.split(".")
    if len(parts) >= 2 and parts[0] == "172" and parts[1].isdigit() and 16 <= int(parts[1]) <= 31:
        return True
    return False


def _lang_norm(code: str) -> str:
    return str(code or "").strip().lower().replace("_", "-")


def _lang_match(player_lang: str, listed: list) -> str:
    pl = _lang_norm(player_lang)
    if not pl:
        return ""
    for item in listed:
        it = _lang_norm(item)
        if not it:
            continue
        if pl == it or pl.startswith(it + "-") or it.startswith(pl + "-"):
            return item
    return ""


def _target_applies(opts: dict, no_license: bool) -> bool:
    target = str((opts or {}).get("target") or "all").strip().lower()
    if target in ("pirate", "pirates", "no_license", "unlicensed"):
        return bool(no_license)
    if target in ("license", "licensed", "licence"):
        return not bool(no_license)
    return True


def autokick_reason(conn, steam_id: str, payload: dict | None = None, project_id: int | None = None) -> dict | None:
    sid = str(steam_id or "").strip()
    if not sid:
        return None
    pid = 0
    try:
        pid = int(project_id or (payload or {}).get("project_id") or request_project_id() or 0)
    except Exception:
        pid = 0
    prev = request_project_id()
    if pid:
        set_request_project(pid)
    try:
        return _autokick_reason_inner(conn, sid, payload)
    finally:
        set_request_project(prev)


def _autokick_reason_inner(conn, sid: str, payload: dict | None = None) -> dict | None:
    if not conn.execute("SELECT 1 FROM online_players WHERE steam_id = ? AND project_id = ?", (sid, int(request_project_id() or 0))).fetchone():
        return None
    rules = {row["type"]: row for row in autokick_list(conn)}
    if not any(row.get("active") for row in rules.values()):
        return None
    exempt = player_autokick_get(conn, sid, project_id=request_project_id())
    payload = payload if isinstance(payload, dict) else {}
    steam = read_cache(conn, "steam_cache", "steam_id", sid)
    if not isinstance(steam, dict):
        steam = {}
    ip = str(payload.get("ip") or "").split(":")[0].strip()
    player_row = conn.execute("SELECT ip, steam_name, last_language, last_no_license FROM players WHERE steam_id = ?", (sid,)).fetchone()
    if not ip and player_row:
        ip = str(player_row["ip"] or "").split(":")[0].strip()
    geo = read_cache(conn, "ip_cache", "ip", ip) if ip else None
    if not isinstance(geo, dict):
        geo = {}
    name = str(payload.get("steam_name") or payload.get("name") or steam.get("personaname") or (player_row["steam_name"] if player_row else "") or "").strip()
    language = str(
        payload.get("language")
        or (payload.get("entity") or {}).get("language")
        or (player_row["last_language"] if player_row else "")
        or ""
    ).strip()
    no_license = bool(payload.get("no_license"))
    if player_row and player_row["last_no_license"] and not no_license:
        no_license = True
    moved = int(payload.get("last_moved_seconds") or payload.get("last_moved") or 0)
    if moved >= 10**12:
        moved = max(0, _now_ms() - moved)
    elif moved >= 10**9:
        moved = max(0, _now_ms() - moved * 1000)
    elif 0 < moved < 100000:
        moved = moved * 1000

    def hit(kind: str, extra: str = "") -> dict:
        opts = (rules.get(kind) or {}).get("options") or {}
        reason = str(opts.get("reason") or "").strip() or AUTOKICK_REASONS.get(kind) or kind
        if extra and extra not in reason:
            reason = "%s: %s" % (reason, extra)
        return {"kind": kind, "reason": reason, "steam_id": sid, "project_id": int(request_project_id() or 0)}

    def allowed(kind: str) -> bool:
        rule = rules.get(kind) or {}
        if not rule.get("active"):
            return False
        key = AUTOKICK_EXEMPT.get(kind)
        if key and exempt.get(key):
            return False
        if not _target_applies(rule.get("options") or {}, no_license):
            return False
        return True

    if allowed("afk"):
        minutes = int((rules["afk"].get("options") or {}).get("max_minutes") or 30)
        if moved >= max(1, minutes) * 60000:
            return hit("afk")

    if allowed("name_contains"):
        opts = rules["name_contains"].get("options") or {}
        words = _norm_list(opts.get("list"))
        matched = _text_in_list(name, words)
        if not matched and opts.get("steam_id_name") and sid:
            compact = re.sub(r"\s+", "", name)
            if sid in compact or (len(sid) >= 10 and sid[-10:] in compact):
                matched = sid
        if matched:
            return hit("name_contains", matched)

    if allowed("game_language"):
        langs = _norm_list((rules["game_language"].get("options") or {}).get("list"))
        matched = _lang_match(language, langs)
        if matched:
            return hit("game_language", matched)

    if steam.get("updated_at") or "visible" in steam or steam.get("personaname") is not None:
        visible = bool(steam.get("visible", True))
        filled = bool(steam.get("profile_filled", True))
        if allowed("steam_closed") and not visible:
            return hit("steam_closed")
        if allowed("steam_empty_profile") and visible and not filled:
            return hit("steam_empty_profile")
        if allowed("steam_signed_days"):
            opts = rules["steam_signed_days"].get("options") or {}
            signed = int(steam.get("signed_at") or 0)
            min_days = int(opts.get("min_days", 7))
            if signed <= 0:
                if opts.get("kick_with_hidden_signed_at") or opts.get("kick_if_hidden_profile"):
                    return hit("steam_signed_days")
            else:
                age_days = max(0, (_now_ms() - signed) / 86400000.0)
                if age_days < min_days:
                    return hit("steam_signed_days")
        if allowed("steam_hours"):
            opts = rules["steam_hours"].get("options") or {}
            complete = bool(steam.get("complete"))
            hidden = bool(steam.get("hours_closed_at")) and not complete
            if hidden and (opts.get("kick_with_hidden_ga") or opts.get("kick_if_hidden_ga")):
                return hit("steam_hours")
            if complete:
                hours = float(steam.get("rust_hours_total") or 0)
                if opts.get("use_spacewars_hours"):
                    hours += float(steam.get("spacewar_hours_total") or 0)
                min_hours = float(opts.get("min_hours", 50))
                if hours < min_hours:
                    return hit("steam_hours")
        bans = steam.get("ban_data") if isinstance(steam.get("ban_data"), dict) else {}
        if allowed("steam_vac"):
            min_bans = int((rules["steam_vac"].get("options") or {}).get("min_bans") or 1)
            vac = int(((bans.get("vac_ban") or {}).get("count") if isinstance(bans.get("vac_ban"), dict) else 0) or 0)
            if vac >= min_bans:
                return hit("steam_vac")
        if allowed("steam_gameban"):
            min_bans = int((rules["steam_gameban"].get("options") or {}).get("min_bans") or 1)
            gb = int(((bans.get("game_ban") or {}).get("count") if isinstance(bans.get("game_ban"), dict) else 0) or 0)
            if gb >= min_bans:
                return hit("steam_gameban")

    if not _is_local_ip(ip):
        provider = str(geo.get("provider") or geo.get("isp") or "").strip()
        country = str(geo.get("country_code") or geo.get("country") or geo.get("country_name") or "").strip()
        if allowed("ip_vpn"):
            opts = rules["ip_vpn"].get("options") or {}
            include = [x.lower() for x in _norm_list(opts.get("include_providers"))]
            exclude = [x.lower() for x in _norm_list(opts.get("exclude_providers"))]
            prov_l = provider.lower()
            if prov_l and any(item and item in prov_l for item in exclude):
                pass
            elif geo.get("proxy") or geo.get("hosting") or (prov_l and any(item and item in prov_l for item in include)):
                return hit("ip_vpn", provider)
        if allowed("ip_bad_provider"):
            words = _norm_list((rules["ip_bad_provider"].get("options") or {}).get("list"))
            matched = _text_in_list(provider, words)
            if matched:
                return hit("ip_bad_provider", matched)
        if allowed("ip_country"):
            opts = rules["ip_country"].get("options") or {}
            listed = [x.lower() for x in _norm_list(opts.get("list"))]
            mode = str(opts.get("mode") or "blacklist").lower().replace("-", "_").replace(" ", "")
            code = country.lower()
            if listed and code:
                in_list = any(item == code or item in code or code in item for item in listed)
                if mode in ("whitelist", "white_list"):
                    if not in_list:
                        return hit("ip_country", country)
                elif in_list:
                    return hit("ip_country", country)
    return None


def apply_autokick(conn, steam_id: str, payload: dict | None = None, project_id: int | None = None) -> dict | None:
    hit = autokick_reason(conn, steam_id, payload, project_id=project_id)
    if not hit:
        return None
    sid = hit["steam_id"]
    now = _now_ms()
    cooldown_key = (int(project_id or hit.get("project_id") or request_project_id() or 0), sid)
    last = int(_AUTOKICK_COOLDOWN.get(cooldown_key) or 0)
    if now - last < 15000:
        return None
    _AUTOKICK_COOLDOWN[cooldown_key] = now
    try:
        pid = int(project_id or hit.get("project_id") or request_project_id() or 0)
        if not pid:
            return hit
        conn.execute(
            "INSERT INTO alerts (type, steam_id, payload, created_at, project_id) VALUES (?, ?, ?, ?, ?)",
            (
                "auto_kick",
                sid,
                json.dumps({
                    "steam_id": sid,
                    "target_steam_id": sid,
                    "kind": hit["kind"],
                    "type": hit["kind"],
                    "reason": hit["reason"],
                    "meta_value": {"reason": hit["reason"]},
                    "project_id": pid,
                }, ensure_ascii=False),
                now,
                pid,
            ),
        )
    except Exception as exc:
        print("autokick alert failed", sid, type(exc).__name__)
    return hit


def _day_start(ms: int) -> int:
    dt = datetime.fromtimestamp(max(0, int(ms or 0)) / 1000.0, tz=timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return int(dt.timestamp() * 1000)


def _empty_bucket() -> dict:
    return {
        "ban": 0, "clear": 0, "canceled": 0, "unban": 0, "mute": 0, "unmute": 0,
        "value": 0, "count": 0, "total": 0, "count_day_interval": 0, "count_night_interval": 0,
        "with_proof": 0,
    }


def _bucket_map(days: int = 30) -> dict:
    now = _now_ms()
    out = {}
    for i in range(days, -1, -1):
        key = str(_day_start(now - i * 86400000))
        out[key] = _empty_bucket()
    return out


def _inc_bucket(buckets: dict, ts, field: str, n: int = 1) -> None:
    ts = int(ts or _now_ms())
    key = str(_day_start(ts))
    if key not in buckets:
        buckets[key] = _empty_bucket()
    buckets[key][field] = int(buckets[key].get(field) or 0) + n
    buckets[key]["value"] = int(buckets[key].get("value") or 0) + n
    buckets[key]["count"] = int(buckets[key].get("count") or 0) + n
    buckets[key]["total"] = int(buckets[key].get("value") or 0)
    try:
        hour = datetime.fromtimestamp(max(0, ts) / 1000.0, tz=timezone.utc).hour
    except Exception:
        hour = 12
    if 8 <= hour < 23:
        buckets[key]["count_day_interval"] = int(buckets[key].get("count_day_interval") or 0) + n
    else:
        buckets[key]["count_night_interval"] = int(buckets[key].get("count_night_interval") or 0) + n


def stats_kind(conn, kind: str = "check", client_id: int = 0, ts_from: int = 0, ts_to: int = 0) -> dict:
    kind = str(kind or "check").lower()
    buckets = _bucket_map(30)
    checks_n = bans_n = mutes_n = clear_n = ban_n = canceled_n = 0
    reasons = {}
    pid = request_project_id() or 0
    try:
        client_id = int(client_id or 0)
    except Exception:
        client_id = 0
    try:
        ts_from = int(ts_from or 0)
        ts_to = int(ts_to or 0)
    except Exception:
        ts_from = ts_to = 0

    def _in_range(ts) -> bool:
        n = int(ts or 0)
        if ts_from and n and n < ts_from:
            return False
        if ts_to and n and n > ts_to:
            return False
        return True

    check_where = " WHERE project_id = ?" if pid else " WHERE 0=1"
    check_args = [pid] if pid else []
    staff_name = ""
    if client_id:
        try:
            user = user_by_id(conn, client_id)
            staff_name = str(staff_public_name(user, "", "", conn) or (user or {}).get("name") or "").strip().lower()
        except Exception:
            staff_name = ""
        check_where += " AND (COALESCE(checker_id, 0) = ?"
        check_args.append(client_id)
        if staff_name:
            check_where += " OR LOWER(TRIM(COALESCE(checker_name, ''))) = ?"
            check_args.append(staff_name)
        check_where += ")"
    ban_where = " WHERE project_id = ?" if pid else " WHERE 0=1"
    ban_args = [pid] if pid else []
    if client_id:
        ban_where += " AND (COALESCE(actor_user_id, 0) = ?"
        ban_args.append(client_id)
        if staff_name:
            ban_where += " OR LOWER(TRIM(COALESCE(actor_name, ''))) = ?"
            ban_args.append(staff_name)
        ban_where += ")"
    mute_where = " WHERE project_id = ?" if pid else " WHERE 0=1"
    mute_args = [pid] if pid else []
    if client_id:
        mute_where += " AND (COALESCE(actor_user_id, 0) = ?"
        mute_args.append(client_id)
        if staff_name:
            mute_where += " OR LOWER(TRIM(COALESCE(actor_name, ''))) = ?"
            mute_args.append(staff_name)
        mute_where += ")"
    moders_map = {}
    try:
        checks_n = 0
        bans_n = 0
        mutes_n = 0
        if kind in ("check", "checks", "all", "project"):
            for row in conn.execute(
                "SELECT status, verdict, started_at, finished_at, checker_id, checker_name, checker_email FROM checks" + check_where,
                check_args,
            ).fetchall():
                ts = int(row["finished_at"] or row["started_at"] or 0)
                if not _in_range(ts):
                    continue
                status = str(row["status"] or "").lower()
                if not row["finished_at"]:
                    continue
                cid = int(row["checker_id"] or 0)
                if client_id:
                    cid = client_id
                elif not cid:
                    continue
                if cid not in moders_map:
                    moders_map[cid] = {
                        "id": cid,
                        "client_id": cid,
                        "name": row["checker_name"] or OWNER_NAME,
                        "email": row["checker_email"] or OWNER_EMAIL,
                        "checks": 0,
                        "bans": 0,
                        "mutes": 0,
                        "mute": 0,
                        "clear": 0,
                        "ban": 0,
                        "canceled": 0,
                        "total": 0,
                    }
                checks_n += 1
                moders_map[cid]["checks"] += 1
                if "ban" in status:
                    ban_n += 1
                    moders_map[cid]["ban"] += 1
                    moders_map[cid]["bans"] += 1
                    _inc_bucket(buckets, ts, "ban")
                    label = "Бан"
                elif "cancel" in status:
                    canceled_n += 1
                    moders_map[cid]["canceled"] += 1
                    _inc_bucket(buckets, ts, "canceled")
                    label = "Отмена"
                else:
                    clear_n += 1
                    moders_map[cid]["clear"] += 1
                    _inc_bucket(buckets, ts, "clear")
                    label = str(row["verdict"] or "Чист") or "Чист"
                    if label.lower() in ("finishedclear", "clear", "finished"):
                        label = "Чист"
                reasons[label] = int(reasons.get(label) or 0) + 1
        if kind in ("ban", "bans"):
            buckets = _bucket_map(30)
            reasons = {}
            for row in conn.execute(
                "SELECT created_at, active, reason, actor_user_id, actor_name FROM bans" + ban_where,
                ban_args,
            ).fetchall():
                ts = int(row["created_at"] or 0)
                if not _in_range(ts):
                    continue
                bans_n += 1
                _inc_bucket(buckets, ts, "ban")
                if not row["active"]:
                    _inc_bucket(buckets, ts, "unban")
                label = str(row["reason"] or "Ban")
                reasons[label] = int(reasons.get(label) or 0) + 1
                try:
                    mid = int(row["actor_user_id"] or 0)
                except Exception:
                    mid = 0
                if mid:
                    if mid not in moders_map:
                        name = ""
                        try:
                            name = str(row["actor_name"] or "")
                        except Exception:
                            name = ""
                        moders_map[mid] = {
                            "id": mid, "client_id": mid, "name": name or OWNER_NAME, "email": "",
                            "checks": 0, "bans": 0, "mutes": 0, "mute": 0, "clear": 0, "ban": 0, "canceled": 0, "total": 0,
                        }
                    moders_map[mid]["bans"] += 1
                    moders_map[mid]["ban"] += 1
        if kind in ("mute", "mutes", "player-mute"):
            buckets = _bucket_map(30)
            reasons = {}
            for row in conn.execute(
                "SELECT created_at, active, reason, actor_user_id, actor_name FROM mutes" + mute_where,
                mute_args,
            ).fetchall():
                ts = int(row["created_at"] or 0)
                if not _in_range(ts):
                    continue
                mutes_n += 1
                _inc_bucket(buckets, ts, "mute")
                if not row["active"]:
                    _inc_bucket(buckets, ts, "unmute")
                label = str(row["reason"] or "Mute")
                reasons[label] = int(reasons.get(label) or 0) + 1
                try:
                    mid = int(row["actor_user_id"] or 0)
                except Exception:
                    mid = 0
                if mid:
                    if mid not in moders_map:
                        name = ""
                        try:
                            name = str(row["actor_name"] or "")
                        except Exception:
                            name = ""
                        moders_map[mid] = {
                            "id": mid, "client_id": mid, "name": name or OWNER_NAME, "email": "",
                            "checks": 0, "bans": 0, "mutes": 0, "mute": 0, "clear": 0, "ban": 0, "canceled": 0, "total": 0,
                        }
                    moders_map[mid]["mutes"] += 1
                    moders_map[mid]["mute"] += 1
            for bucket in buckets.values():
                bucket["total"] = int(bucket.get("mute") or 0)
        if kind in ("all", "project") and kind not in ("check", "checks", "ban", "bans", "mute", "mutes", "player-mute"):
            pass
    except Exception as exc:
        print("stats_kind failed", kind, "pid", pid, exc)
    user = owner_user(conn)
    uid = int(user.get("id") or 1)
    if kind in ("mute", "mutes", "player-mute"):
        total = mutes_n
    elif kind in ("ban", "bans"):
        total = bans_n
    else:
        total = checks_n
    moders = []
    if moders_map:
        for mid, m in moders_map.items():
            if kind in ("ban", "bans"):
                m["total"] = int(m.get("bans") or m.get("ban") or 0)
            elif kind in ("mute", "mutes", "player-mute"):
                m["total"] = int(m.get("mutes") or m.get("mute") or 0)
            else:
                m["total"] = int(m.get("checks") or 0)
            m["mutes"] = int(m.get("mutes") or 0)
            m["mute"] = m["mutes"]
            m["bans"] = int(m.get("bans") or 0)
            moders.append(m)
        # percent shares among project staff only
        sum_total = sum(int(m.get("total") or 0) for m in moders) or 1
        for m in moders:
            share = round(100.0 * int(m.get("total") or 0) / sum_total, 1)
            m["percent"] = share
            m["share"] = share
    elif total > 0 or kind in ("ban", "bans", "mute", "mutes", "player-mute"):
        # bans/mutes have no per-staff actor column; attribute project totals to owner only when this project has data
        if total > 0:
            moders = [{
                "id": uid,
                "client_id": uid,
                "name": user.get("name") or OWNER_NAME,
                "email": user.get("email") or OWNER_EMAIL,
                "checks": checks_n if kind in ("check", "checks", "all", "project") else 0,
                "bans": bans_n,
                "mutes": mutes_n,
                "mute": mutes_n,
                "clear": clear_n,
                "ban": ban_n,
                "canceled": canceled_n,
                "total": int(total or 0),
                "percent": 100,
                "share": 100,
            }]
    if client_id:
        kept = []
        for m in moders:
            try:
                mid = int(m.get("id") or m.get("client_id") or 0)
            except Exception:
                mid = 0
            if mid == int(client_id):
                kept.append(m)
        if not kept:
            kept = [{
                "id": client_id,
                "client_id": client_id,
                "name": staff_name or OWNER_NAME,
                "email": "",
                "checks": checks_n if kind in ("check", "checks", "all", "project") else 0,
                "bans": bans_n,
                "mutes": mutes_n,
                "mute": mutes_n,
                "clear": clear_n,
                "ban": ban_n,
                "canceled": canceled_n,
                "total": int(total or 0),
                "percent": 100 if total else 0,
                "share": 100 if total else 0,
            }]
        else:
            for m in kept:
                m["percent"] = 100 if int(m.get("total") or 0) else 0
                m["share"] = m["percent"]
        moders = kept
    # empty project => empty staff list / zero totals
    return {
        "stats": buckets,
        "reasons": reasons,
        "moders": moders,
        "total": int(total or 0),
        "checks": checks_n,
        "bans": bans_n,
        "mutes": mutes_n,
        "mute": mutes_n,
        "time_points": [],
        "project_id": pid,
    }


def stats_moders(conn) -> dict:
    return stats_kind(conn, "all")


DISCORD_TYPES = ("Report", "Check", "Ban", "CheckappBan", "ManyBans")
DISCORD_IDS = {"Report": 1, "Check": 2, "Ban": 3, "CheckappBan": 4, "ManyBans": 5}
DISCORD_IDS_REV = {str(v): k for k, v in DISCORD_IDS.items()}


def normalize_discord_type(typ: str) -> str:
    text = str(typ or "").strip()
    if not text:
        return ""
    if text in DISCORD_IDS_REV:
        return DISCORD_IDS_REV[text]
    for name in DISCORD_TYPES:
        if name.lower() == text.lower():
            return name
    return text if text in DISCORD_TYPES else ""


def parse_bool_flag(value, default=None):
    if value is None:
        return default
    if isinstance(value, list):
        value = value[0] if value else None
        if value is None:
            return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "on"):
        return True
    if text in ("0", "false", "no", "off", ""):
        return False
    return default
CACHE_TTL_MS = 6 * 60 * 60 * 1000
IP_GEO_TTL_MS = 24 * 60 * 60 * 1000
STEAM_CACHE_TTL_MS = 6 * 60 * 60 * 1000


def _now_ms() -> int:
    return int(time.time() * 1000)


def setting_json(conn, key: str, default=None, project_id: int | None = None):
    lookup = scoped_setting_key(key, project_id)
    if not lookup:
        return default if default is not None else {}
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (lookup,)).fetchone()
    if not row:
        return default if default is not None else {}
    try:
        data = json.loads(row["value"] or "{}")
        return data
    except Exception:
        return default if default is not None else {}


def setting_json_set(conn, key: str, value, project_id: int | None = None) -> None:
    lookup = scoped_setting_key(key, project_id)
    if not lookup:
        return
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (lookup, json.dumps(value, ensure_ascii=False)),
    )


def _discord_item(typ: str, saved: dict | None = None) -> dict:
    row = dict(saved or {})
    data = row.get("data")
    if not isinstance(data, dict):
        data = row.get("options") if isinstance(row.get("options"), dict) else {}
    if not isinstance(data, dict):
        data = {}
    try:
        ban_amount = int(data.get("ban_amount") or data.get("min_amount") or 10)
    except (TypeError, ValueError):
        ban_amount = 10
    try:
        min_amount = int(data.get("min_amount") or data.get("ban_amount") or 5)
    except (TypeError, ValueError):
        min_amount = 5
    merged = {
        "mention": str(data.get("mention") or data.get("mention_tag") or ""),
        "mention_tag": str(data.get("mention_tag") or data.get("mention") or data.get("tag") or ""),
        "tag": str(data.get("tag") or data.get("role") or data.get("mention_tag") or ""),
        "role": str(data.get("role") or data.get("tag") or ""),
        "ban_amount": ban_amount,
        "min_amount": min_amount,
        "min_ban_amount": ban_amount,
        "interval_minutes": min_amount,
    }
    for key, value in data.items():
        if key not in merged:
            merged[key] = value
    # NumericInput expects every numeric option to exist, even before setup.
    def number(key, default):
        try:
            return max(0, int(data.get(key) if data.get(key) is not None else default))
        except (TypeError, ValueError):
            return default
    merged.update({
        "minimal_for_mention": number("minimal_for_mention", ban_amount if typ == "CheckappBan" else 5),
        "minimal_to_send": number("minimal_to_send", min_amount if "min_amount" in data else 5),
        "min_ban_amount": number("min_ban_amount", ban_amount),
        "interval_minutes": number("interval_minutes", min_amount),
        "send_only_with_comment": pref_bool(data, "send_only_with_comment"),
        "send_minimal_embed": pref_bool(data, "send_minimal_embed", "minimalist", "minimal"),
        "created": pref_bool(data, "created", default=True),
        "editted": pref_bool(data, "editted", default=True),
        "unban": pref_bool(data, "unban", default=True),
        "send_proofs": pref_bool(data, "send_proofs", default=True),
    })
    # Discord Check wizard toggles
    if typ == "Check":
        if "check_started" not in merged and "started" not in merged:
            merged["check_started"] = True
            merged["started"] = True
        else:
            merged["check_started"] = bool(merged.get("check_started") if merged.get("check_started") is not None else merged.get("started"))
            merged["started"] = bool(merged.get("started") if merged.get("started") is not None else merged.get("check_started"))
        if "check_finished" not in merged and "finished" not in merged:
            merged["check_finished"] = True
            merged["finished"] = True
        else:
            merged["check_finished"] = bool(merged.get("check_finished") if merged.get("check_finished") is not None else merged.get("finished"))
            merged["finished"] = bool(merged.get("finished") if merged.get("finished") is not None else merged.get("check_finished"))
        if "minimalist" not in merged and "minimal" not in merged:
            merged["minimalist"] = False
            merged["minimal"] = False
        else:
            merged["minimalist"] = bool(merged.get("minimalist") or merged.get("minimal"))
            merged["minimal"] = merged["minimalist"]
    wid = DISCORD_IDS.get(typ, 1)
    raw_id = row.get("id")
    try:
        if raw_id not in (None, "", typ) and int(raw_id) > 0:
            wid = int(raw_id)
    except (TypeError, ValueError):
        pass
    url = str(row.get("webhook") or row.get("url") or "")
    active = pref_bool(row, "active", "enabled", default=False)
    return {
        "id": wid,
        "M_ID": wid,
        "m_id": wid,
        "type": typ,
        "kind": typ,
        "active": active,
        "enabled": active,
        "webhook": url,
        "url": url,
        "language": str(row.get("language") or "ru"),
        "data": merged,
        "options": merged,
    }


def discord_list(conn) -> list:
    stored = setting_json(conn, "court_discord", {})
    if isinstance(stored, list):
        mapped = {}
        for item in stored:
            if isinstance(item, dict) and item.get("type"):
                mapped[str(item["type"])] = item
        stored = mapped
    if not isinstance(stored, dict):
        stored = {}
    lower = {str(k).lower(): v for k, v in stored.items() if isinstance(v, dict)}
    out = []
    for typ in DISCORD_TYPES:
        row = stored.get(typ)
        if not isinstance(row, dict):
            row = lower.get(typ.lower())
        out.append(_discord_item(typ, row if isinstance(row, dict) else None))
    return out


def discord_save_map(conn, items: list) -> list:
    sync_discord_webhooks(conn)
    stored = {}
    current = {row["type"]: row for row in discord_list(conn)}
    for item in items:
        if not isinstance(item, dict):
            continue
        typ = normalize_discord_type(item.get("type") or item.get("kind") or "")
        if typ not in DISCORD_TYPES:
            continue
        base = dict(current.get(typ) or _discord_item(typ))
        base.update({k: item[k] for k in item if k in ("active", "enabled", "webhook", "url", "language", "data", "options")})
        if "enabled" in item and "active" not in item:
            base["active"] = bool(item.get("enabled"))
        # Merge wizard toggles from either data or options
        incoming_data = {}
        if isinstance(item.get("data"), dict):
            incoming_data.update(item.get("data"))
        if isinstance(item.get("options"), dict):
            incoming_data.update(item.get("options"))
        # Also accept flat keys on the item itself
        for key in ("check_started", "check_finished", "started", "finished", "minimalist", "minimal", "mention", "tag", "role", "ban_amount", "min_amount"):
            if key in item:
                incoming_data[key] = item[key]
        if incoming_data:
            prev = base.get("data") if isinstance(base.get("data"), dict) else {}
            merged_data = dict(prev)
            merged_data.update(incoming_data)
            base["data"] = merged_data
            base["options"] = merged_data
        stored[typ] = _discord_item(typ, base)
    for typ in DISCORD_TYPES:
        if typ not in stored:
            stored[typ] = current.get(typ) or _discord_item(typ)
    setting_json_set(conn, "court_discord", stored)
    return discord_list(conn)


def discord_upsert(conn, body) -> list:
    items = body
    if isinstance(body, dict):
        if body.get("type") or body.get("kind"):
            items = [body]
        else:
            items = body.get("items") or body.get("data") or body.get("webhooks") or list(body.values())
    if not isinstance(items, list):
        items = [items]
    return discord_save_map(conn, [item for item in items if isinstance(item, dict)])


def discord_toggle(conn, typ: str, value) -> list:
    sync_discord_webhooks(conn)
    typ = normalize_discord_type(typ)
    stored = {row["type"]: row for row in discord_list(conn)}
    if not typ:
        return discord_list(conn)
    row = stored.get(typ) or _discord_item(typ)
    parsed = parse_bool_flag(value, default=None)
    if parsed is None:
        # SPA always sends ?value=true|false. Missing value = do not invert (that desynced the switch).
        return discord_list(conn)
    on = parsed
    row["active"] = on
    row["enabled"] = on
    stored[typ] = _discord_item(typ, row)
    setting_json_set(conn, "court_discord", stored)
    print("discord toggle", typ, "active", on)
    return discord_list(conn)


def court_api_state(conn) -> dict:
    routes = ["/public/checks", "/public/bans", "/public/servers"]
    saved = setting_json(conn, "court_api", {})
    if not isinstance(saved, dict):
        saved = {}
    token = str(saved.get("token") or saved.get("api_key") or saved.get("public_api_key") or "checkapp-local-api")
    enabled = pref_bool(saved, "enabled", "api_enabled")
    public_routes = saved.get("public_api_routes") if isinstance(saved.get("public_api_routes"), dict) else {route: False for route in routes}
    return {
        "enabled": enabled,
        "api_enabled": enabled,
        "token": token,
        "api_key": token,
        "public_api_key": token,
        "routes": [route for route, on in public_routes.items() if on],
        "api_consumers": saved.get("api_consumers") if isinstance(saved.get("api_consumers"), list) else [],
        "public_api_routes": public_routes,
        "public_api_routes_available": routes,
    }


def court_api_save(conn, patch: dict) -> dict:
    state = court_api_state(conn)
    if isinstance(patch, dict):
        if "enabled" in patch or "api_enabled" in patch or "value" in patch:
            flag = patch.get("enabled")
            if flag is None:
                flag = patch.get("api_enabled")
            if flag is None:
                flag = patch.get("value")
            if isinstance(flag, str):
                flag = flag.lower() in ("1", "true", "yes", "on")
            state["enabled"] = bool(flag)
            state["api_enabled"] = bool(flag)
        if patch.get("token") or patch.get("api_key") or patch.get("public_api_key"):
            token = str(patch.get("token") or patch.get("api_key") or patch.get("public_api_key"))
            state["token"] = token
            state["api_key"] = token
            state["public_api_key"] = token
        if isinstance(patch.get("public_api_routes"), dict):
            state["public_api_routes"].update(patch["public_api_routes"])
        if isinstance(patch.get("api_consumers"), list):
            state["api_consumers"] = patch["api_consumers"]
    setting_json_set(conn, "court_api", state)
    return court_api_state(conn)


def court_commands_list(conn) -> list:
    saved = setting_json(conn, "court_commands", [])
    items = saved if isinstance(saved, list) else []
    out = []
    for item in items:
        if not isinstance(item, dict):
            continue
        row = dict(item)
        name = str(row.get("name") or row.get("title") or row.get("command") or "").lower()
        cmds = row.get("commands") or row.get("command") or []
        if isinstance(cmds, str):
            cmds = [cmds]
        if not isinstance(cmds, list):
            cmds = []
        row["commands"] = cmds
        dangerous = any(
            token in " ".join([name] + [str(c).lower() for c in cmds])
            for token in ("kill", "ban", "kick", "unban", "mute")
        )
        if row.get("accept") is None:
            row["accept"] = True if dangerous else bool(row.get("confirmation") or row.get("confirm"))
        row["confirmation"] = bool(row.get("accept") or row.get("confirmation") or row.get("confirm") or row.get("force_confirmation"))
        row["confirm"] = row["confirmation"]
        row["force_confirmation"] = row["confirmation"]
        row["accept"] = row["confirmation"] if dangerous else bool(row.get("accept") or row["confirmation"])
        if dangerous:
            row["accept"] = True
            row["confirmation"] = True
            row["confirm"] = True
            row["force_confirmation"] = True
        out.append(row)
    return out


def court_commands_preset() -> list:
    """SPA CommandPresetModal keeps a spinner while `GET /court-commands/preset` is empty."""
    rows = [
        {"id": 1, "name": "Kick", "group": "Vanilla", "category": "moderation", "access": "yellow",
         "commands": ["kick {steamid} {reason}"]},
        {"id": 2, "name": "Kill", "group": "Vanilla", "category": "moderation", "access": "red",
         "commands": ["kill {steamid}"]},
        {"id": 3, "name": "Mute", "group": "Vanilla", "category": "moderation", "access": "yellow",
         "commands": ["mute {steamid} 60m {reason}"]},
        {"id": 4, "name": "Unmute", "group": "Vanilla", "category": "moderation", "access": "green",
         "commands": ["unmute {steamid}"]},
        {"id": 5, "name": "Teleport to player", "group": "Vanilla", "category": "player", "access": "green",
         "commands": ["teleport {steamid}"]},
        {"id": 6, "name": "Bring player", "group": "Vanilla", "category": "player", "access": "yellow",
         "commands": ["teleport {steamid} {me}"]},
        {"id": 7, "name": "Heal", "group": "Vanilla", "category": "player", "access": "green",
         "commands": ["heal {steamid}"]},
        {"id": 8, "name": "Spectate", "group": "Vanilla", "category": "player", "access": "green",
         "commands": ["spectate {steamid}"]},
        {"id": 9, "name": "Freeze", "group": "Admin", "category": "moderation", "access": "yellow",
         "commands": ["freeze {steamid}"]},
        {"id": 10, "name": "Unfreeze", "group": "Admin", "category": "moderation", "access": "green",
         "commands": ["unfreeze {steamid}"]},
        {"id": 11, "name": "Give item", "group": "Admin", "category": "player", "access": "yellow",
         "commands": ["inventory.giveto {steamid} rifle.ak 1"]},
        {"id": 12, "name": "Reset metabolism", "group": "Admin", "category": "player", "access": "green",
         "commands": ["resetmetabolis {steamid}"]},
    ]
    for row in rows:
        row.setdefault("requirements", None)
        row.setdefault("title", row["name"])
        row.setdefault("command", row["commands"][0] if row.get("commands") else "")
    return rows


def court_commands_save(conn, items) -> list:
    if isinstance(items, dict):
        current = court_commands_list(conn)
        item = dict(items)
        if item.get("id"):
            replaced = False
            for i, row in enumerate(current):
                if str(row.get("id")) == str(item.get("id")):
                    current[i] = {**row, **item}
                    replaced = True
                    break
            if not replaced:
                current.append(item)
        else:
            item["id"] = int(time.time() * 1000) % 100000
            current.append(item)
        items = current
    if not isinstance(items, list):
        items = []
    setting_json_set(conn, "court_commands", items)
    return court_commands_list(conn)


def court_command_toggle(conn, cid, active) -> list:
    items = court_commands_list(conn)
    if isinstance(active, str):
        active = active.lower() in ("1", "true", "yes", "on")
    for item in items:
        if str(item.get("id")) == str(cid):
            item["active"] = bool(active)
            item["enabled"] = bool(active)
    setting_json_set(conn, "court_commands", items)
    return items


def cache_steam_avatar(steam_id: str, url: str) -> str:
    sid = str(steam_id or "").strip()
    url = str(url or "").strip()
    if not sid or not url:
        return url
    # Never re-cache an already-local broken path
    if url.startswith("/uploads/steam-"):
        dest_existing = UPLOADS / f"steam-{sid}.jpg"
        if dest_existing.exists() and dest_existing.stat().st_size > 200:
            return f"/uploads/{dest_existing.name}"
        return url if url.startswith("http") else ""
    dest = UPLOADS / f"steam-{sid}.jpg"
    try:
        UPLOADS.mkdir(parents=True, exist_ok=True)
        if dest.exists() and dest.stat().st_size > 200:
            return f"/uploads/{dest.name}"
        data = _http_get(url, timeout=6)
        if data and len(data) > 200:
            dest.write_bytes(data)
            return f"/uploads/{dest.name}"
    except Exception as exc:
        print("steam avatar cache failed", sid, type(exc).__name__)
    return url


def _http_get(url: str, timeout: int = 6) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
        },
    )
    ctx = ssl._create_unverified_context()
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        return resp.read()


def _redact_url(url: str) -> str:
    return re.sub(r"(key=)[^&]+", r"\1REDACTED", str(url or ""), flags=re.I)


def _steam_request(url: str, steam_id: str, endpoint: str, timeout: int = 8) -> tuple[bytes | None, int, str]:
    """GET Steam API. Logs status without the API key. Returns (body, http_status, error)."""
    sid = str(steam_id or "")
    safe = _redact_url(url)
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "RustApp/1.0", "Accept": "application/json"},
        )
        ctx = ssl._create_unverified_context()
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            raw = resp.read()
            status = int(getattr(resp, "status", 200) or 200)
            print(
                "steam api request",
                "endpoint", endpoint,
                "steamid", sid,
                "http", status,
                "ts", _now_ms(),
            )
            return raw, status, ""
    except urllib.error.HTTPError as exc:
        body = b""
        try:
            body = exc.read() or b""
        except Exception:
            body = b""
        err = str(exc.reason or exc)[:200]
        print(
            "steam api error",
            "endpoint", endpoint,
            "steamid", sid,
            "http", int(exc.code or 0),
            "error", err,
            "ts", _now_ms(),
            "url", safe,
        )
        return body or None, int(exc.code or 0), err
    except Exception as exc:
        print(
            "steam api error",
            "endpoint", endpoint,
            "steamid", sid,
            "http", 0,
            "error", type(exc).__name__,
            "ts", _now_ms(),
            "url", safe,
        )
        return None, 0, type(exc).__name__


def _xml_text(root, *tags) -> str:
    for tag in tags:
        node = root.find(tag)
        if node is not None and (node.text or "").strip():
            return node.text.strip()
    return ""


def _parse_member_since(text: str) -> int:
    text = (text or "").strip()
    if not text:
        return 0
    # Steam may return "Sep 11, 2015" or localized forms
    months_ru = {
        "января": "January", "февраля": "February", "марта": "March", "апреля": "April",
        "мая": "May", "июня": "June", "июля": "July", "августа": "August",
        "сентября": "September", "октября": "October", "ноября": "November", "декабря": "December",
    }
    low = text.lower()
    for ru, en in months_ru.items():
        if ru in low:
            text = re.sub(ru, en, text, flags=re.I)
            break
    for fmt in ("%B %d, %Y", "%d %B %Y", "%b %d, %Y", "%d %b %Y", "%Y-%m-%d", "%d.%m.%Y"):
        try:
            return int(datetime.strptime(text, fmt).timestamp() * 1000)
        except Exception:
            continue
    m = re.search(r"(\d{1,2})\s+([A-Za-zА-Яа-я]+)\s+(\d{4})", text)
    if m:
        try:
            return int(datetime.strptime(f"{m.group(2)} {m.group(1)}, {m.group(3)}", "%B %d, %Y").timestamp() * 1000)
        except Exception:
            try:
                return int(datetime.strptime(f"{m.group(2)} {m.group(1)}, {m.group(3)}", "%b %d, %Y").timestamp() * 1000)
            except Exception:
                pass
    return 0


def _parse_alias_time(text: str) -> int:
    raw = re.sub(r"\s+", " ", str(text or "").replace("@", "").replace(",", "")).strip()
    if not raw:
        return 0
    year = str(datetime.now().year)
    candidates = [raw, raw + " " + year]
    for item in candidates:
        for fmt in (
            "%d %b %Y %I:%M%p",
            "%b %d %Y %I:%M%p",
            "%B %d %Y %I:%M%p",
            "%d %B %Y %I:%M%p",
            "%d %b %Y",
            "%b %d %Y",
            "%B %d %Y",
        ):
            try:
                return int(datetime.strptime(item, fmt).timestamp() * 1000)
            except Exception:
                continue
    return _parse_member_since(raw)


def _hours_num(raw) -> float:
    s = str(raw or "0").strip().replace(" ", "").replace("\u00a0", "")
    if not s:
        return 0.0
    # Steam community may use "1,234.5" (thousands) or "1.234,5" (EU decimal)
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        parts = s.split(",")
        if len(parts) == 2 and len(parts[1]) <= 2 and parts[0].replace(".", "").isdigit():
            s = parts[0].replace(".", "") + "." + parts[1]
        else:
            s = s.replace(",", "")
    try:
        return float(s)
    except Exception:
        return 0.0


def fetch_steam_profile(steam_id: str) -> dict:
    sid = str(steam_id or "").strip()
    now = _now_ms()
    out = {
        "visible": None,
        "profile_filled": False,
        "personaname": "",
        "avatar": "",
        "signed_at": 0,
        "updated_at": now,
        "hours_closed_at": None,
        "rust_hours_total": None,
        "rust_hours_2week": None,
        "spacewar_hours_total": None,
        "spacewar_hours_2week": None,
        "ban_data": {
            "days_since_last_ban": None,
            "game_ban": {"count": None},
            "vac_ban": {"count": None},
        },
        "complete": False,
        "privacy": "",
    }
    if not sid.isdigit():
        return out
    local_av = UPLOADS / f"steam-{sid}.jpg"
    if local_av.exists() and local_av.stat().st_size > 200:
        out["avatar"] = f"/uploads/{local_av.name}"

    def grab(text: str, *pats) -> str:
        for pat in pats:
            match = re.search(pat, text, re.I | re.S)
            if match:
                return re.sub(r"<!\[CDATA\[|\]\]>", "", match.group(1)).strip()
        return ""

    try:
        raw = _http_get(f"https://steamcommunity.com/profiles/{sid}/?xml=1", timeout=6)
        text = raw.decode("utf-8", "replace")
        name = grab(text, r"<steamID>(.*?)</steamID>")
        if name:
            out["personaname"] = name
        avatar = grab(text, r"<avatarFull>(.*?)</avatarFull>", r"<avatarMedium>(.*?)</avatarMedium>")
        if avatar:
            out["avatar"] = cache_steam_avatar(sid, avatar) or avatar
        privacy = (grab(text, r"<privacyState>(.*?)</privacyState>") or "public").lower()
        out["visible"] = privacy in ("public", "open", "")
        custom = grab(text, r"<customURL>(.*?)</customURL>")
        avatar_url = str(out.get("avatar") or "")
        default_av = "fef49e7fa7e1997310d705b2a6158ff8dc1cdfeb" in avatar_url.lower()
        setup_missing = "not yet set up their steam community profile" in text.lower() or "hasn't set up their steam community" in text.lower()
        vac = grab(text, r"<vacBanned>(.*?)</vacBanned>")
        if vac in ("1", "true", "yes"):
            out["ban_data"]["vac_ban"]["count"] = 1
        signed = _parse_member_since(grab(text, r"<memberSince>(.*?)</memberSince>"))
        if signed:
            out["signed_at"] = signed
            out["signed_from_steam"] = True
        limited = grab(text, r"<isLimitedAccount>(.*?)</isLimitedAccount>")
        is_limited = limited in ("1", "true", "yes")
        out["profile_filled"] = not (setup_missing or is_limited or (not custom and default_av))
        out["custom_url"] = custom
        gamebans = grab(text, r"<gameBanned>(.*?)</gameBanned>", r"<NumberOfGameBans>(.*?)</NumberOfGameBans>")
        if gamebans.isdigit():
            out["ban_data"]["game_ban"]["count"] = int(gamebans)
        name = str(out.get("personaname") or "").strip()
        if not name or name == sid:
            try:
                html = _http_get(f"https://steamcommunity.com/profiles/{sid}/", timeout=8).decode("utf-8", "replace")
                html_name = grab(
                    html,
                    r'class="actual_persona_name">([^<]+)',
                    r'property="og:title" content="([^"]+)"',
                    r"<title>([^<]+)</title>",
                )
                html_name = re.sub(r"^Steam Community\s*::\s*", "", html_name).strip()
                html_name = re.sub(r"^Steam Community\s*::\s*", "", html_name).strip()
                if html_name and html_name.lower() not in ("steam community", "error", sid.lower()):
                    out["personaname"] = html_name
            except Exception:
                pass
    except Exception as exc:
        print("steam profile fetch failed", sid, type(exc).__name__)
        try:
            html = _http_get(f"https://steamcommunity.com/profiles/{sid}/", timeout=8).decode("utf-8", "replace")
            html_name = grab(
                html,
                r'class="actual_persona_name">([^<]+)',
                r'property="og:title" content="([^"]+)"',
                r"<title>([^<]+)</title>",
            )
            html_name = re.sub(r"^Steam Community\s*::\s*", "", html_name or "").strip()
            if html_name and html_name.lower() not in ("steam community", "error", sid.lower()):
                out["personaname"] = html_name
        except Exception:
            pass

    # Steam Web API (optional key) — SteamID64 only. Never invent hours/VAC.
    api_key = str(os.environ.get("STEAM_WEB_API_KEY") or os.environ.get("STEAM_API_KEY") or "").strip()
    if api_key and sid.isdigit():
        raw, http_status, err = _steam_request(
            f"https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/?key={api_key}&steamids={sid}",
            sid, "GetPlayerSummaries",
        )
        if raw:
            try:
                data = json.loads(raw.decode("utf-8", "replace") or "{}")
            except Exception:
                data = {}
            players = (((data.get("response") or {}).get("players")) or [])
            if players:
                p0 = players[0] if isinstance(players[0], dict) else {}
                if p0.get("personaname"):
                    out["personaname"] = str(p0.get("personaname"))
                if p0.get("avatarfull") or p0.get("avatarmedium"):
                    av = str(p0.get("avatarfull") or p0.get("avatarmedium"))
                    out["avatar"] = cache_steam_avatar(sid, av) or av
                vis = int(p0.get("communityvisibilitystate") or 0)
                out["visible"] = vis == 3
                out["privacy"] = "Public" if vis == 3 else "Private"
                if p0.get("timecreated"):
                    out["signed_at"] = int(p0.get("timecreated")) * 1000
                    out["signed_from_steam"] = True
                out["profile_filled"] = bool(p0.get("profilestate"))
            elif http_status == 200:
                out["privacy"] = out.get("privacy") or "Unavailable"
        raw, http_status, err = _steam_request(
            f"https://api.steampowered.com/ISteamUser/GetPlayerBans/v1/?key={api_key}&steamids={sid}",
            sid, "GetPlayerBans",
        )
        if raw:
            try:
                data = json.loads(raw.decode("utf-8", "replace") or "{}")
            except Exception:
                data = {}
            bans = (data.get("players") or [])
            if bans and isinstance(bans[0], dict):
                b0 = bans[0]
                vac = b0.get("NumberOfVACBans")
                if b0.get("VACBanned") is True and vac in (None, ""):
                    vac = 1
                out["ban_data"]["vac_ban"]["count"] = int(vac or 0)
                out["ban_data"]["game_ban"]["count"] = int(b0.get("NumberOfGameBans") or 0)
                if b0.get("DaysSinceLastBan") is not None:
                    out["ban_data"]["days_since_last_ban"] = int(b0.get("DaysSinceLastBan") or 0)
        raw, http_status, err = _steam_request(
            f"https://api.steampowered.com/IPlayerService/GetOwnedGames/v1/?key={api_key}&steamid={sid}"
            f"&include_appinfo=0&include_played_free_games=1&appids_filter[0]=252490&appids_filter[1]=480",
            sid, "GetOwnedGames",
        )
        if raw:
            try:
                data = json.loads(raw.decode("utf-8", "replace") or "{}")
            except Exception:
                data = {}
            games = ((data.get("response") or {}).get("games")) or []
            game_count = ((data.get("response") or {}).get("game_count"))
            owned_apps = set()
            if isinstance(games, list) and games:
                for game in games:
                    if not isinstance(game, dict):
                        continue
                    app = str(game.get("appid") or "")
                    total_min = float(game.get("playtime_forever") or 0)
                    week_min = float(game.get("playtime_2weeks") or 0)
                    total = round(total_min / 60.0, 1)
                    week = round(week_min / 60.0, 1)
                    if app == "252490":
                        owned_apps.add("252490")
                        out["owns_rust"] = True
                        out["rust_hours_total"] = total
                        out["rust_hours_2week"] = week
                        out["hours_closed_at"] = None
                        out["complete"] = True
                        out["hours_from_api"] = True
                        out["hours_status"] = "ok"
                    elif app == "480":
                        owned_apps.add("480")
                        out["spacewar_hours_total"] = total
                        out["spacewar_hours_2week"] = week
                if out.get("owns_rust") is not True:
                    if "480" in owned_apps and "252490" not in owned_apps:
                        out["owns_rust"] = False
                    elif out.get("visible") is True or game_count is not None:
                        out["owns_rust"] = False
            elif out.get("visible") is False:
                out["hours_status"] = "Private"
            else:
                out["hours_status"] = "Unavailable"
                if out.get("visible") is True:
                    out["owns_rust"] = False
            if not out.get("hours_from_api"):
                raw2, http_status2, err2 = _steam_request(
                    f"https://api.steampowered.com/IPlayerService/GetRecentlyPlayedGames/v1/?key={api_key}&steamid={sid}",
                    sid, "GetRecentlyPlayedGames",
                )
                if raw2:
                    try:
                        data2 = json.loads(raw2.decode("utf-8", "replace") or "{}")
                    except Exception:
                        data2 = {}
                    recent = ((data2.get("response") or {}).get("games")) or []
                    if isinstance(recent, list):
                        for game in recent:
                            if not isinstance(game, dict):
                                continue
                            if str(game.get("appid") or "") != "252490":
                                continue
                            total_min = float(game.get("playtime_forever") or 0)
                            week_min = float(game.get("playtime_2weeks") or 0)
                            out["rust_hours_total"] = round(total_min / 60.0, 1)
                            out["rust_hours_2week"] = round(week_min / 60.0, 1)
                            out["hours_from_api"] = True
                            out["hours_status"] = "ok"
                            out["complete"] = True
                            out["owns_rust"] = True
                            break
        elif out.get("visible") is False:
            out["hours_status"] = "Private"
        else:
            out["hours_status"] = out.get("hours_status") or "Unavailable"
    else:
        if not api_key:
            print("steam api skipped, no STEAM_WEB_API_KEY, steamid", sid, "ts", _now_ms())
            out["hours_status"] = out.get("hours_status") or "Unavailable"

    if not out.get("hours_from_api"):
      try:
        raw = _http_get(f"https://steamcommunity.com/profiles/{sid}/games?tab=all&xml=1", timeout=8)
        text = raw.decode("utf-8", "replace")
        rust_total = rust_2w = None
        space_total = space_2w = None
        blocks = re.findall(r"<game>(.*?)</game>", text, re.I | re.S)
        if not blocks:
            blocks = [text]
        for block in blocks:
            app = grab(block, r"<appID>(.*?)</appID>", r"<appId>(.*?)</appId>")
            total = _hours_num(grab(block, r"<hoursOnRecord>(.*?)</hoursOnRecord>", r"<hoursForever>(.*?)</hoursForever>"))
            week = _hours_num(grab(block, r"<hoursLast2Weeks>(.*?)</hoursLast2Weeks>", r"<hoursLast2Week>(.*?)</hoursLast2Week>"))
            if app == "252490":
                rust_total, rust_2w = total, week
            elif app == "480":
                space_total, space_2w = total, week
        if rust_total is not None:
            out["rust_hours_total"] = rust_total
            out["rust_hours_2week"] = rust_2w or 0
            out["hours_closed_at"] = None
            out["complete"] = True
            out["owns_rust"] = True
        elif not out.get("complete"):
            # Don't invent "closed" if XML simply empty — keep unknown unless already set by API
            if out.get("hours_closed_at") is None and "this profile is private" in text.lower():
                out["hours_closed_at"] = _now_ms()
                out["complete"] = False
            elif blocks and "this profile is private" not in text.lower() and out.get("owns_rust") is None:
                out["owns_rust"] = False
        if space_total is not None:
            out["spacewar_hours_total"] = space_total
            out["spacewar_hours_2week"] = space_2w or 0
            if rust_total is None and out.get("owns_rust") is not True:
                out["owns_rust"] = False
        if rust_total is None:
            html = _http_get(f"https://steamcommunity.com/profiles/{sid}/games/?tab=all", timeout=8).decode("utf-8", "replace")
            match = re.search(r"rgGames\s*=\s*(\[.*?\]);", html, re.S)
            if match:
                try:
                    games = json.loads(match.group(1))
                except Exception:
                    games = []
                for game in games:
                    if not isinstance(game, dict):
                        continue
                    app = str(game.get("appid") or game.get("appID") or "")
                    total = _hours_num(str(game.get("hours_forever") or game.get("hoursOnRecord") or "0"))
                    week = _hours_num(str(game.get("hours") or game.get("hours_2weeks") or "0"))
                    if app == "252490":
                        out["rust_hours_total"] = total
                        out["rust_hours_2week"] = week
                        out["complete"] = True
                        out["owns_rust"] = True
                    elif app == "480":
                        out["spacewar_hours_total"] = total
                        out["spacewar_hours_2week"] = week
                        if out.get("owns_rust") is not True:
                            out["owns_rust"] = False
      except Exception as exc:
        print("steam games fetch failed", sid, type(exc).__name__)
    try:
        aliases = []
        raw = _http_get(f"https://steamcommunity.com/profiles/{sid}/ajaxaliases", timeout=6)
        parsed = json.loads(raw.decode("utf-8", "replace") or "[]")
        if isinstance(parsed, list):
            for item in parsed:
                if not isinstance(item, dict):
                    continue
                alias_name = str(item.get("newname") or item.get("name") or "").strip()
                if not alias_name:
                    continue
                aliases.append({
                    "name": alias_name,
                    "timechanged": str(item.get("timechanged") or ""),
                    "created_at": _parse_alias_time(str(item.get("timechanged") or "")),
                })
        if aliases:
            out["aliases"] = aliases
            current = str(out.get("personaname") or "").strip()
            if not current and aliases[0]["name"] and aliases[0]["name"] != sid:
                out["personaname"] = aliases[0]["name"]
    except Exception as exc:
        print("steam aliases fetch failed", sid, type(exc).__name__)
    out["updated_at"] = _now_ms()
    return out


def read_cache(conn, table: str, key_name: str, key: str, ttl: int = CACHE_TTL_MS):
    try:
        row = conn.execute(f"SELECT payload, fetched_at FROM {table} WHERE {key_name} = ?", (key,)).fetchone()
    except Exception:
        return None
    if not row:
        return None
    try:
        data = json.loads(row["payload"] or "{}")
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    data = dict(data)
    fetched = 0
    try:
        fetched = int(row["fetched_at"] or 0)
    except Exception:
        fetched = 0
    data["_fetched_at"] = fetched
    if ttl and fetched and (_now_ms() - fetched) > int(ttl):
        data["_stale"] = True
    return data


def write_cache(conn, table: str, key_name: str, key: str, payload: dict) -> None:
    try:
        conn.execute(
            f"INSERT INTO {table} ({key_name}, payload, fetched_at) VALUES (?, ?, ?) ON CONFLICT({key_name}) DO UPDATE SET payload=excluded.payload, fetched_at=excluded.fetched_at",
            (key, json.dumps(payload, ensure_ascii=False), _now_ms()),
        )
    except Exception as exc:
        print("write_cache failed", table, type(exc).__name__, exc)


_HOST_PUBLIC_IP = {"ip": "", "at": 0.0}


def host_public_ip() -> str:
    """Public IPv4 of this machine. Never blocks the request thread."""
    now = time.time()
    cached = str(_HOST_PUBLIC_IP.get("ip") or "")
    if cached and (now - float(_HOST_PUBLIC_IP.get("at") or 0)) < 3600:
        return cached
    fetching = bool(_HOST_PUBLIC_IP.get("fetching"))
    if fetching:
        return cached

    def _run():
        try:
            import urllib.request
            with urllib.request.urlopen("https://api.ipify.org", timeout=3) as resp:
                ip = str(resp.read().decode("utf-8", "ignore") or "").strip()
            if re.match(r"^\d{1,3}(?:\.\d{1,3}){3}$", ip) and not _is_private_ip(ip):
                _HOST_PUBLIC_IP["ip"] = ip
                _HOST_PUBLIC_IP["at"] = time.time()
        except Exception:
            pass
        finally:
            _HOST_PUBLIC_IP["fetching"] = False

    _HOST_PUBLIC_IP["fetching"] = True
    try:
        threading.Thread(target=_run, daemon=True).start()
    except Exception:
        _HOST_PUBLIC_IP["fetching"] = False
        try:
            import urllib.request
            with urllib.request.urlopen("https://api.ipify.org", timeout=1) as resp:
                ip = str(resp.read().decode("utf-8", "ignore") or "").strip()
            if re.match(r"^\d{1,3}(?:\.\d{1,3}){3}$", ip) and not _is_private_ip(ip):
                _HOST_PUBLIC_IP["ip"] = ip
                _HOST_PUBLIC_IP["at"] = now
                return ip
        except Exception:
            pass
    return cached


def pick_public_server_ip(*candidates) -> str:
    """First public IPv4 from plugin body / TCP peer / this host. Never keep 0.0.0.0."""
    private = ""
    for raw in candidates:
        text = str(raw or "").strip().split(",")[0].strip()
        if not text:
            continue
        host, _port = parse_server_host_port(text, 0)
        ip = host or text
        if not ip or ip in ("0.0.0.0", "localhost", "::1"):
            continue
        if _is_private_ip(ip):
            if not private:
                private = ip
            continue
        return ip
    if private and private not in ("127.0.0.1", "::1"):
        return private
    return host_public_ip() or private


def _is_private_ip(ip: str) -> bool:
    ip = str(ip or "").strip()
    if not ip or ip in ("127.0.0.1", "::1", "localhost", "0.0.0.0"):
        return True
    if ip.startswith(("10.", "192.168.", "169.254.")):
        return True
    if ip.startswith("172."):
        try:
            second = int(ip.split(".")[1])
            if 16 <= second <= 31:
                return True
        except Exception:
            pass
    return False


def fetch_ip_geo(ip: str) -> dict:
    """Lookup geo via ip-api.com (existing provider). Always preserve the input IP."""
    ip = str(ip or "").split(":")[0].strip()
    local = {
        "ip": ip or "127.0.0.1",
        "country": "Локальная сеть",
        "country_name": "Локальная сеть",
        "city": "LAN",
        "isp": "Private network",
        "provider": "Private network",
        "org": "LAN",
        "proxy": False,
        "country_code": "",
        "updated_at": _now_ms(),
    }
    if _is_private_ip(ip):
        local["provider"] = "Loopback" if ip in ("127.0.0.1", "::1", "localhost", "") else "Private network"
        local["isp"] = local["provider"]
        return local
    empty = {
        "ip": ip,
        "country": "",
        "country_name": "",
        "city": "",
        "isp": "",
        "provider": "",
        "org": "",
        "proxy": False,
        "country_code": "",
        "updated_at": _now_ms(),
        "lookup_failed": True,
    }

    def _ok(country, city, isp, provider="", code="", query="", org="", proxy=False, lat=None, lon=None):
        country = str(country or "").strip()
        city = str(city or "").strip()
        isp = str(isp or provider or org or "").strip()
        provider = str(provider or isp or org or "").strip()
        code = str(code or "").strip().lower()
        names = {
            "ru": "Россия", "ua": "Украина", "by": "Беларусь", "kz": "Казахстан",
            "us": "United States", "de": "Germany", "tr": "Turkey", "cn": "China",
            "gb": "United Kingdom", "pl": "Poland", "nl": "Netherlands", "fi": "Finland",
            "ee": "Estonia", "lv": "Latvia", "lt": "Lithuania", "ge": "Georgia",
            "uz": "Uzbekistan", "md": "Moldova", "cz": "Czechia", "fr": "France",
            "it": "Italy", "es": "Spain", "br": "Brazil", "in": "India", "jp": "Japan",
        }
        if code in ("un", "xx", "t1", "unknown"):
            code = ""
        if len(country) == 2 and country.isalpha() and (not code or code == country.lower()):
            code = country.lower()
            country = names.get(code) or country.upper()
        elif not country and len(code) == 2:
            country = names.get(code) or code.upper()
        if not country and not city and not isp and not provider:
            return None
        out = {
            "ip": str(query or ip).strip() or ip,
            "country": country,
            "country_name": country,
            "city": city,
            "isp": isp or provider,
            "provider": provider or isp,
            "org": str(org or isp or "").strip(),
            "proxy": bool(proxy),
            "country_code": code,
            "latitude": lat,
            "longitude": lon,
            "updated_at": _now_ms(),
            "lookup_failed": False,
        }
        return out

    sources = (
        f"http://ip-api.com/json/{ip}?fields=status,message,country,countryCode,city,isp,org,as,proxy,hosting,query,lat,lon",
        f"https://ipwho.is/{ip}",
        f"https://get.geojs.io/v1/ip/geo/{ip}.json",
        f"https://api.country.is/{ip}",
    )
    last_exc = None
    for url in sources:
        try:
            raw = _http_get(url, timeout=5)
            data = json.loads(raw.decode("utf-8", "replace"))
            if not isinstance(data, dict):
                continue
            if "ip-api.com" in url:
                if data.get("status") != "success":
                    print("ip geo status", ip, data.get("message") or data.get("status"))
                    continue
                parsed = _ok(
                    data.get("country"), data.get("city"),
                    data.get("isp") or data.get("org") or data.get("as"),
                    data.get("isp") or data.get("org"),
                    data.get("countryCode"), data.get("query"),
                    data.get("org"),
                    data.get("proxy") or data.get("hosting"),
                    data.get("lat"), data.get("lon"),
                )
            elif "ipwho.is" in url:
                if data.get("success") is False:
                    continue
                parsed = _ok(
                    data.get("country"), data.get("city"),
                    (data.get("connection") or {}).get("isp") or (data.get("connection") or {}).get("org"),
                    (data.get("connection") or {}).get("isp") or (data.get("connection") or {}).get("org"),
                    data.get("country_code"), data.get("ip"),
                    (data.get("connection") or {}).get("org"),
                    False,
                )
            elif "ipapi.co" in url:
                if data.get("error"):
                    continue
                parsed = _ok(
                    data.get("country_name") or data.get("country"),
                    data.get("city"),
                    data.get("org") or data.get("org_name"),
                    data.get("org") or data.get("org_name"),
                    data.get("country_code") or data.get("country"),
                    data.get("ip"),
                    data.get("org"),
                    False,
                )
            elif "ipinfo.io" in url:
                if data.get("error") or data.get("bogon"):
                    continue
                parsed = _ok(
                    data.get("country_name") or data.get("country"),
                    data.get("city") or data.get("region"),
                    data.get("org") or data.get("isp"),
                    data.get("org") or data.get("isp"),
                    data.get("country"),
                    data.get("ip"),
                    data.get("org"),
                    False,
                )
            elif "geojs.io" in url:
                parsed = _ok(
                    data.get("country") or data.get("country_3"),
                    data.get("city") or data.get("region"),
                    data.get("organization") or data.get("org") or data.get("asn_org"),
                    data.get("organization") or data.get("org"),
                    data.get("country_code") or data.get("country"),
                    data.get("ip"),
                    data.get("organization"),
                    False,
                )
            elif "country.is" in url:
                parsed = _ok(
                    data.get("country"),
                    "",
                    "",
                    "",
                    data.get("country"),
                    data.get("ip"),
                    "",
                    False,
                )
            else:
                if data.get("error"):
                    continue
                parsed = _ok(
                    data.get("country_name") or data.get("country"),
                    data.get("city"),
                    data.get("org") or data.get("org_name"),
                    data.get("org") or data.get("org_name"),
                    data.get("country_code") or data.get("country"),
                    data.get("ip"),
                    data.get("org"),
                    False,
                )
            if parsed:
                return parsed
        except Exception as exc:
            last_exc = exc
            print("ip geo fetch failed", ip, url, exc)
    if last_exc:
        print("ip geo all sources failed", ip, last_exc)
    return empty


def _geo_is_placeholder(cached: dict) -> bool:
    cn = str(cached.get("country_name") or cached.get("country") or "").strip()
    city = str(cached.get("city") or "").strip()
    isp = str(cached.get("isp") or cached.get("provider") or "").strip()
    bad = {"", "unknown", "unavailable", "неизвестно", "pending"}
    if cn.lower() in ("local network", "lan", "локальная сеть"):
        return False
    if cn.lower() in bad:
        return True
    return cn.lower() in bad and city.lower() in bad and isp.lower() in bad


def _strip_cache_meta(data: dict) -> dict:
    out = dict(data or {})
    out.pop("_stale", None)
    out.pop("_fetched_at", None)
    return out


def ensure_ip_geo(conn, ip: str, blocking: bool = True) -> dict:
    """Read ip_cache (TTL 24h) or fetch+store. Never invent geo for public IPs.

    Never returns a `pending` stub — the SPA treats empty/pending as «Неизвестно»
    forever and does not refetch. blocking=False uses cache (including stale)
    and otherwise returns an empty lookup without a pending flag.
    """
    ip = str(ip or "").split(":")[0].strip()
    if not ip:
        return fetch_ip_geo("")
    if _is_private_ip(ip):
        return fetch_ip_geo(ip)
    cached = read_cache(conn, "ip_cache", "ip", ip, ttl=IP_GEO_TTL_MS)
    if isinstance(cached, dict) and not cached.get("lookup_failed") and not _geo_is_placeholder(cached):
        out = _strip_cache_meta(cached)
        out.pop("pending", None)
        out["ip"] = out.get("ip") or ip
        if cached.get("_stale") and blocking:
            data = fetch_ip_geo(ip)
            if isinstance(data, dict) and not data.get("lookup_failed") and not _geo_is_placeholder(data):
                try:
                    write_cache(conn, "ip_cache", "ip", ip, data)
                except Exception:
                    pass
                data = _strip_cache_meta(data)
                data.pop("pending", None)
                return data
        return out
    if not blocking:
        empty = {
            "ip": ip,
            "country": "",
            "country_name": "",
            "city": "",
            "isp": "",
            "provider": "",
            "org": "",
            "proxy": False,
            "country_code": "",
            "updated_at": 0,
            "lookup_failed": True,
        }
        return empty
    data = fetch_ip_geo(ip)
    if isinstance(data, dict) and ip:
        data.pop("pending", None)
        if not data.get("lookup_failed") and not _geo_is_placeholder(data):
            try:
                write_cache(conn, "ip_cache", "ip", ip, data)
            except Exception:
                pass
    if isinstance(data, dict):
        data.pop("pending", None)
        return data
    return {"ip": ip}


def ban_sync_defaults() -> dict:
    return {
        "is_public": False,
        "share": False,
        "share_details": False,
        "share_moders": False,
        "share_reasons": True,
        "enabled": False,
    }


def _ban_sync_key() -> str:
    return "ban_sync"


def ban_sync_settings(conn) -> dict:
    """Per-project ban-list sharing. `is_public` is independent from `enabled` (auto-kick)."""
    pid = request_project_id()
    if not pid:
        out = ban_sync_defaults()
        out["project_id"] = 0
        return out
    saved = setting_json(conn, "ban_sync", None)
    if not isinstance(saved, dict):
        saved = {}
    out = ban_sync_defaults()
    if "is_public" in saved or "share" in saved or "public" in saved:
        public = bool(saved.get("is_public") if "is_public" in saved else (saved.get("share") or saved.get("public")))
    else:
        public = False
    out["is_public"] = public
    out["share"] = public
    out["public"] = public
    out["enabled"] = bool(saved.get("enabled")) if "enabled" in saved else public
    out["share_details"] = bool(saved.get("share_details"))
    out["share_moders"] = bool(saved.get("share_moders"))
    out["share_reasons"] = bool(saved.get("share_reasons", True))
    out["project_id"] = pid
    return out


def ban_sync_save(conn, body) -> dict:
    pid = request_project_id()
    if not pid:
        return ban_sync_settings(conn)
    current = ban_sync_settings(conn)
    incoming = body if isinstance(body, dict) else {}
    if any(k in incoming for k in ("is_public", "share", "public")):
        public = bool(
            incoming["is_public"] if "is_public" in incoming
            else incoming["share"] if "share" in incoming
            else incoming.get("public")
        )
        current["is_public"] = public
        current["share"] = public
        current["public"] = public
    if "enabled" in incoming:
        current["enabled"] = bool(incoming.get("enabled"))
    for key in ("share_details", "share_moders", "share_reasons"):
        if key in incoming:
            current[key] = bool(incoming.get(key))
    current["project_id"] = pid
    setting_json_set(conn, "ban_sync", current)
    return ban_sync_settings(conn)


def _ban_sync_project_row(conn, row) -> dict:
    data = dict(row) if row is not None and not isinstance(row, dict) else (row or {})
    pid = int(data.get("id") or 0)
    name = str(data.get("name") or data.get("domain") or "Project")
    avatar = public_project_avatar(str(data.get("avatar") or "").strip(), pid)
    domain = str(data.get("domain") or "")
    bans = 0
    try:
        bans = conn.execute(
            "SELECT COUNT(*) FROM bans WHERE active = 1 AND project_id = ?",
            (pid,),
        ).fetchone()[0]
    except Exception:
        bans = 0
    saved = _ban_sync_saved_for(conn, pid) if pid else {}
    share_details = bool((saved or {}).get("share_details", True))
    share_moders = bool((saved or {}).get("share_moders", False))
    project_original = {
        "id": pid,
        "name": name,
        "title": name,
        "tag": domain or name,
        "domain": domain,
        "avatar": avatar,
        "image": avatar,
        "verified": False,
    }
    return {
        "id": pid,
        "project_id": pid,
        "project_id_original": pid,
        "name": name,
        "title": name,
        "tag": domain or name,
        "domain": domain,
        "avatar": avatar,
        "image": avatar,
        "bans": int(bans or 0),
        "bans_count": int(bans or 0),
        "count": int(bans or 0),
        "total": int(bans or 0),
        "total_bans": int(bans or 0),
        "followers": 0,
        "no_license_percent": 0,
        "is_public": True,
        "you_are_public": True,
        "public": True,
        "share_details": share_details,
        "share_moders": share_moders,
        "created_at": pid,
        "project_original": project_original,
        "project": project_original,
    }


def _ban_sync_saved_for(conn, pid: int) -> dict:
    lookup = scoped_setting_key("ban_sync", pid)
    if not lookup:
        return {}
    prow = conn.execute("SELECT value FROM settings WHERE key = ?", (lookup,)).fetchone()
    if not prow:
        return {}
    try:
        data = json.loads(prow["value"] or "{}")
    except Exception:
        data = {}
    return data if isinstance(data, dict) else {}


def ban_sync_available(conn) -> list:
    items = []
    for row in conn.execute("SELECT * FROM project ORDER BY id ASC").fetchall():
        pid = int(row["id"] or 0)
        if not pid:
            continue
        data = _ban_sync_saved_for(conn, pid)
        public = bool((data or {}).get("is_public") or (data or {}).get("share") or (data or {}).get("public"))
        if public:
            items.append(_ban_sync_project_row(conn, row))
    return items


def ban_sync_subscriptions(conn) -> list:
    saved = setting_json(conn, "ban_sync_subs", [])
    if not isinstance(saved, list):
        saved = []
    available = {str(item.get("id")): item for item in ban_sync_available(conn)}
    out = []
    for item in saved:
        pid = str(item.get("id") or item.get("project_id") or "")
        if pid in available:
            row = dict(available[pid])
            row["subscribed"] = True
            row["active"] = True
            out.append(row)
    return out


def subscribed_foreign_project_ids(conn) -> list:
    me = int(request_project_id() or 0)
    ids = []
    seen = set()
    for item in ban_sync_subscriptions(conn):
        if not isinstance(item, dict):
            continue
        try:
            pid = int(item.get("project_id_original") or item.get("id") or item.get("project_id") or 0)
        except Exception:
            pid = 0
        if not pid or pid == me or pid in seen:
            continue
        seen.add(pid)
        ids.append(pid)
    return ids


def _ban_sync_pid_from_body(body, params=None):
    if isinstance(body, list):
        return [_ban_sync_pid_from_body(item, params) for item in body]
    if isinstance(body, (int, float)):
        return body
    if isinstance(body, str) and str(body).strip().lstrip("-").isdigit():
        return body.strip()
    incoming = body if isinstance(body, dict) else {}
    if not isinstance(incoming, dict):
        incoming = {}
    nested_data = incoming.get("data")
    if isinstance(nested_data, (dict, int, float, str, list)) and not incoming.get("project_id_original") and not incoming.get("id"):
        if isinstance(nested_data, list) or not isinstance(nested_data, dict):
            return _ban_sync_pid_from_body(nested_data, params)
        incoming = dict(incoming)
        incoming.update(nested_data)
    nested = incoming.get("project_original") if isinstance(incoming.get("project_original"), dict) else {}
    nested_p = incoming.get("project") if isinstance(incoming.get("project"), dict) else {}
    param_map = params if isinstance(params, dict) else {}

    def _param(key):
        raw = param_map.get(key)
        if isinstance(raw, list):
            return raw[0] if raw else None
        return raw

    for raw in (
        incoming.get("project_id_original"),
        incoming.get("id"),
        incoming.get("project_id"),
        incoming.get("subscription_id"),
        incoming.get("target_project_id"),
        nested.get("id"),
        nested_p.get("id"),
        _param("project_id_original"),
        _param("project_id"),
        _param("id"),
        _param("subscription_id"),
    ):
        if raw is None or raw == "" or raw == 0 or raw == "0":
            continue
        return raw
    return None


def ban_sync_subscribe(conn, body, params=None) -> list:
    pids = _ban_sync_pid_from_body(body, params)
    if not isinstance(pids, list):
        pids = [pids]
    current = setting_json(conn, "ban_sync_subs", [])
    if not isinstance(current, list):
        current = []
    ids = {str(item.get("id") or item.get("project_id")) for item in current if isinstance(item, dict)}
    for pid in pids:
        pid_s = str(pid).strip() if pid is not None else ""
        if not pid_s or pid_s in ("0", "None") or pid_s in ids:
            continue
        try:
            pid_store = int(pid_s)
        except Exception:
            pid_store = pid_s
        current.append({"id": pid_store, "project_id": pid_store, "project_id_original": pid_store})
        ids.add(pid_s)
    setting_json_set(conn, "ban_sync_subs", current)
    return ban_sync_subscriptions(conn)


def ignore_reports_get(conn, steam_id: str) -> int:
    data = setting_json(conn, "ignore_reports_%s" % steam_id, {})
    if isinstance(data, dict):
        try:
            return int(data.get("until") or 0)
        except Exception:
            return 0
    try:
        return int(data or 0)
    except Exception:
        return 0


def ignore_reports_set(conn, steam_id: str, body, params=None) -> dict:
    incoming = body if isinstance(body, dict) else {}
    now = _now_ms()
    until = incoming.get("ignore_reports_until") or incoming.get("until") or incoming.get("expired_at")
    days = incoming.get("days")
    if days is None and isinstance(params, dict):
        raw_days = params.get("days")
        if isinstance(raw_days, list):
            days = raw_days[0] if raw_days else None
        else:
            days = raw_days
    if until in (None, "", False):
        if incoming.get("ignore") in (False, 0, "0", "false"):
            until = 0
        elif days in (None, ""):
            until = 0
        elif str(days).strip().lower() in ("0", "false", "off", "disable", "disabled"):
            until = 0
        else:
            try:
                day_n = float(days)
                until = now + int(day_n * 86400000) if day_n > 0 else 0
            except Exception:
                until = now + 7 * 86400000
    try:
        until = int(until or 0)
    except Exception:
        until = 0
    setting_json_set(conn, "ignore_reports_%s" % steam_id, {"until": until})
    return {"ok": True, "ignore_reports_until": until or None, "until": until or None}


STAFF_LIMIT = 999


def normalize_staff_permissions(raw) -> list:
    out: list[str] = []

    def add(token):
        name = str(token or "").strip()
        if not name or name in ("False", "false", "0", "None"):
            return
        if name not in out:
            out.append(name)

    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                if item.get("enabled") in (False, 0, "0", "false", "False"):
                    continue
                name = item.get("name") or item.get("key") or item.get("permission") or item.get("id")
                if name:
                    add(name)
                    continue
                for key, val in item.items():
                    if val in (False, 0, "0", "false", "False", None, ""):
                        continue
                    if str(key).startswith("Court_") or str(key).lower() in _STAFF_ADMIN_ALIASES:
                        add(key)
            elif item not in (None, "", False, 0):
                add(item)
        return out
    if isinstance(raw, dict):
        for key, val in raw.items():
            if val in (False, 0, "0", "false", "False", None, ""):
                continue
            add(key)
        return out
    if raw not in (None, "", False):
        add(raw)
    return out


_STAFF_ADMIN_ALIASES = {
    "admin", "owner", "*", "administrator", "court_admin",
    "permissions-admin", "permissions_admin", "is_admin", "full",
    "full_control", "full-control", "administrator-rights",
}


def _staff_perm_alias(token: str) -> str:
    return str(token or "").strip().lower().replace(" ", "-").replace("_", "-")


def staff_payload_is_admin(permissions=None, is_immutable: bool = False, payload: dict | None = None) -> bool:
    """SPA 'Права администратора (полный доступ)' must grant every Court_* right."""
    data = payload if isinstance(payload, dict) else {}
    nested = data.get("client") if isinstance(data.get("client"), dict) else {}
    for src in (data, nested):
        for key in ("is_immutable", "is_admin", "admin"):
            val = src.get(key)
            if val in (True, 1, "1", "true", "True"):
                return True
    if is_immutable:
        return True
    have = normalize_staff_permissions(permissions)
    for item in have:
        key = _staff_perm_alias(item)
        if key in _STAFF_ADMIN_ALIASES or key.startswith("permissions-admin"):
            return True
    if isinstance(permissions, dict):
        for key, val in permissions.items():
            if val in (False, 0, "0", "false", "False", None, ""):
                continue
            alias = _staff_perm_alias(key)
            if alias in _STAFF_ADMIN_ALIASES or alias.startswith("permissions-admin"):
                return True
    return False


def user_by_tag(conn, tag: str) -> dict | None:
    tag = str(tag or "").strip().lstrip("@").lower()
    if not tag:
        return None
    try:
        row = conn.execute(
            "SELECT * FROM users WHERE lower(COALESCE(tag, '')) = ? OR lower(COALESCE(name, '')) = ? OR lower(COALESCE(email, '')) = ?",
            (tag, tag, tag),
        ).fetchone()
    except Exception:
        row = conn.execute(
            "SELECT * FROM users WHERE lower(COALESCE(name, '')) = ? OR lower(COALESCE(email, '')) = ?",
            (tag, tag),
        ).fetchone()
    if row:
        return dict(row)
    try:
        row = conn.execute(
            "SELECT * FROM users WHERE lower(email) LIKE ?",
            (tag + "@%",),
        ).fetchone()
    except Exception:
        row = None
    return dict(row) if row else None


def staff_resolve_user(conn, payload: dict | None) -> dict | None:
    """Find an account by client_id, nested client, tag, name or email — never the first user in the table."""
    data = payload if isinstance(payload, dict) else {}
    nested = data.get("client") if isinstance(data.get("client"), dict) else {}
    uid = 0
    for raw in (
        data.get("client_id"), data.get("user_id"), data.get("id"),
        nested.get("id"), nested.get("client_id"), nested.get("user_id"),
    ):
        try:
            uid = int(raw or 0)
        except Exception:
            uid = 0
        if uid > 0:
            user = user_by_id(conn, uid)
            if user:
                return user
    tag = str(
        data.get("tag") or data.get("nick") or data.get("nickname") or data.get("username")
        or data.get("name") or data.get("email")
        or nested.get("tag") or nested.get("name") or nested.get("email") or ""
    ).strip()
    if tag:
        return user_by_tag(conn, tag)
    return None


def project_owner_user_id(conn, project_id: int) -> int:
    try:
        pid = int(project_id or request_project_id() or 0)
    except Exception:
        pid = 0
    if not pid:
        return 0
    row = conn.execute("SELECT owner_user_id FROM project WHERE id = ?", (pid,)).fetchone()
    if not row:
        return 0
    try:
        return int(row["owner_user_id"] or 0)
    except Exception:
        return 0


def staff_row_obj(conn, member_row: dict | None, user_row: dict, owner_uid: int, owner_permissions: list | None = None) -> dict:
    uid = int(user_row.get("id") or 0)
    avatar = spa_https_image(client_avatar_for(conn, uid) or "/local/image-1024.jpg?v=6")
    client = client_from_user(user_row, avatar, conn)
    if not isinstance(client, dict):
        client = {"id": uid, "name": str(user_row.get("name") or ""), "avatar": avatar, "tag": "staff", "bio": ""}
    client["avatar"] = spa_https_image(client.get("avatar") or avatar)
    if client.get("bio") is None:
        client["bio"] = ""
    steam_sid = str(client.get("steam_id") or "")
    if isinstance(client.get("steam"), dict):
        steam_sid = steam_sid or str(client["steam"].get("steam_id") or "")
    try:
        import oauth_auth
        steam = oauth_auth.steam_profile_for_user(conn, user_row, allow_network=False)
        if steam and is_real_steam_id(steam.get("steam_id")):
            client["steam"] = steam
            steam_sid = str(steam.get("steam_id") or steam_sid)
            client["steam_id"] = steam_sid
            client["steam_name"] = steam.get("steam_name") or steam.get("personaname") or steam.get("name") or ""
            sav = spa_https_image(steam.get("steam_avatar") or steam.get("avatar") or steam.get("avatarfull") or avatar)
            client["steam_avatar"] = sav
            client["steam"]["steam_avatar"] = sav
            client["steam"]["avatar"] = sav
            client["steam"]["avatarfull"] = sav
        disc = oauth_auth.discord_profile_for_user(conn, user_row)
        if disc:
            client["discord"] = disc
            client["discord_id"] = disc.get("discord_id") or ""
            client["discord_name"] = disc.get("discord_name") or disc.get("name") or disc.get("username") or ""
            client["discord_avatar"] = disc.get("discord_avatar") or disc.get("avatar") or ""
    except Exception as exc:
        print("staff integrations", type(exc).__name__, exc)
    if not is_real_steam_id(steam_sid):
        client["steam"] = empty_steam_profile(avatar)
        client["steam_id"] = ""
    elif isinstance(client.get("steam"), dict):
        sav = spa_https_image(client["steam"].get("steam_avatar") or client["steam"].get("avatar") or avatar)
        client["steam"]["steam_avatar"] = sav
        client["steam"]["avatar"] = sav
        client["steam"]["avatarfull"] = sav
        if not str(client["steam"].get("steam_name") or "").strip():
            client["steam"]["steam_name"] = client.get("steam_name") or client.get("name") or "Steam"
            client["steam"]["personaname"] = client["steam"]["steam_name"]
            client["steam"]["name"] = client["steam"]["steam_name"]
    is_owner = uid == int(owner_uid or 0)
    perms: list = []
    is_immutable = False
    created = _now_ms()
    if member_row:
        try:
            raw = member_row.get("permissions") if hasattr(member_row, "get") else member_row["permissions"]
            perms = normalize_staff_permissions(json.loads(raw) if isinstance(raw, str) else raw)
        except Exception:
            perms = []
        try:
            is_immutable = bool(int(member_row.get("is_immutable") or 0))
        except Exception:
            is_immutable = bool(member_row.get("is_immutable"))
        try:
            created = int(member_row.get("created_at") or created)
        except Exception:
            created = _now_ms()
    if is_owner:
        perms = list(owner_permissions or [])
        is_immutable = False
    elif is_immutable and owner_permissions:
        perms = list(owner_permissions)
    elif not isinstance(perms, list):
        perms = []
    if (is_owner or is_immutable) and "Core_ClientsEdit" not in perms:
        perms = list(perms) + ["Core_ClientsEdit"]
    return {
        "id": uid,
        "client_id": uid,
        "client": client,
        "permissions": perms,
        "is_immutable": is_immutable,
        "is_owner": is_owner,
        "role": "owner" if is_owner else "staff",
        "created_at": created,
    }


def staff_list_payload(conn, project_id: int = 0, owner_permissions: list | None = None) -> dict:
    pid = int(project_id or request_project_id() or 0)
    owner_uid = project_owner_user_id(conn, pid)
    rows: list[dict] = []
    seen: set[int] = set()
    if owner_uid:
        owner = user_by_id(conn, owner_uid)
        if owner:
            rows.append(staff_row_obj(conn, None, owner, owner_uid, owner_permissions))
            seen.add(owner_uid)
    if pid:
        for member in conn.execute(
            """SELECT * FROM staff_members
               WHERE project_id = ? AND COALESCE(active, 1) = 1
               ORDER BY created_at ASC, id ASC""",
            (pid,),
        ).fetchall():
            mem = dict(member)
            uid = int(mem.get("user_id") or 0)
            if not uid:
                email = str(mem.get("email") or "").strip().lower()
                if email:
                    urow = conn.execute("SELECT * FROM users WHERE lower(email) = ?", (email,)).fetchone()
                    if urow:
                        uid = int(urow["id"])
            if not uid or uid in seen:
                continue
            user = user_by_id(conn, uid)
            if not user:
                continue
            rows.append(staff_row_obj(conn, mem, user, owner_uid, owner_permissions))
            seen.add(uid)
    return {"active": rows, "all": rows}


def staff_non_owner_count(conn, project_id: int) -> int:
    pid = int(project_id or 0)
    owner_uid = project_owner_user_id(conn, pid)
    row = conn.execute(
        """SELECT COUNT(*) FROM staff_members
           WHERE project_id = ? AND COALESCE(active, 1) = 1 AND COALESCE(user_id, 0) != ?""",
        (pid, owner_uid),
    ).fetchone()
    try:
        return int(row[0] if row else 0)
    except Exception:
        return 0


def staff_member_payload(conn, project_id: int, user_id: int, owner_permissions: list | None = None) -> dict | None:
    pid = int(project_id or 0)
    uid = int(user_id or 0)
    user = user_by_id(conn, uid)
    if not user:
        return None
    owner_uid = project_owner_user_id(conn, pid)
    member = None
    if pid:
        row = conn.execute(
            "SELECT * FROM staff_members WHERE project_id = ? AND user_id = ?",
            (pid, uid),
        ).fetchone()
        if row:
            member = dict(row)
    return staff_row_obj(conn, member, user, owner_uid, owner_permissions)


def staff_upsert(conn, project_id: int, client_id: int, permissions: list, is_immutable: bool = False) -> dict:
    pid = int(project_id or request_project_id() or 0)
    uid = int(client_id or 0)
    owner_uid = project_owner_user_id(conn, pid)
    actor_id = int(request_user_id() or 0)
    if not pid:
        return {"ok": False, "error": "invalid", "message": "Проект не выбран"}
    if not uid:
        return {"ok": False, "error": "user_not_found", "message": "Пользователь не найден"}
    user = user_by_id(conn, uid)
    if not user:
        return {"ok": False, "error": "user_not_found", "message": "Пользователь не найден"}
    if uid == owner_uid:
        return {
            "ok": False,
            "error": "cannot_add_self",
            "message": "Владелец проекта уже есть в списке сотрудников",
            "row": staff_member_payload(conn, pid, uid, permissions),
        }
    existing = conn.execute(
        "SELECT id, active FROM staff_members WHERE project_id = ? AND user_id = ?",
        (pid, uid),
    ).fetchone()
    if not existing and staff_non_owner_count(conn, pid) >= STAFF_LIMIT:
        return {
            "ok": False,
            "error": "staff-limit-exceeded",
            "message": "Staff limit exceeded",
            "limit": STAFF_LIMIT,
        }
    if is_immutable or staff_payload_is_admin(permissions, is_immutable):
        is_immutable = True
        try:
            from server import PERMISSIONS as _ALL_PERMS
            permissions = list(_ALL_PERMS)
        except Exception:
            permissions = normalize_staff_permissions(permissions)
    else:
        permissions = normalize_staff_permissions(permissions)
    perms_json = json.dumps(list(permissions), ensure_ascii=False)
    now = _now_ms()
    if existing:
        conn.execute(
            """UPDATE staff_members
               SET permissions = ?, is_immutable = ?, active = 1, name = ?, email = ?, role = 'staff'
               WHERE id = ?""",
            (perms_json, 1 if is_immutable else 0, user.get("name") or "", user.get("email") or "", existing["id"]),
        )
    else:
        conn.execute(
            """INSERT INTO staff_members
               (user_id, email, name, permissions, is_immutable, project_id, created_at, active, role)
               VALUES (?, ?, ?, ?, ?, ?, ?, 1, 'staff')""",
            (uid, user.get("email") or "", user.get("name") or "", perms_json, 1 if is_immutable else 0, pid, now),
        )
    audit(conn, "staff_edit", {
        "project_id": pid,
        "target_user_id": uid,
        "target_email": user.get("email") or "",
        "actor_user_id": actor_id,
    })
    return {"ok": True, "row": staff_member_payload(conn, pid, uid, permissions)}


def staff_remove(conn, project_id: int, client_id: int) -> dict:
    pid = int(project_id or request_project_id() or 0)
    uid = int(client_id or 0)
    owner_uid = project_owner_user_id(conn, pid)
    if not pid or not uid:
        return {"ok": False, "error": "invalid"}
    if uid == owner_uid:
        return {"ok": False, "error": "owner_protected", "message": "cannot remove owner"}
    # SPA sends client.id (users.id). Older rows may only match staff_members.id.
    try:
        row = conn.execute(
            """SELECT user_id, id FROM staff_members
               WHERE project_id = ? AND COALESCE(active, 1) = 1
                 AND (COALESCE(user_id, 0) = ? OR id = ?)
               ORDER BY id DESC LIMIT 1""",
            (pid, uid, uid),
        ).fetchone()
        if row:
            mapped = int(row["user_id"] or 0)
            if mapped:
                uid = mapped
    except Exception:
        pass
    if uid == owner_uid:
        return {"ok": False, "error": "owner_protected", "message": "cannot remove owner"}
    # Keep a permanent presentation snapshot.  Moderation history must not
    # turn into blank rows just because the account later leaves the project.
    user = user_by_id(conn, uid) or {}
    avatar = client_avatar_for(conn, uid) or ""
    display_name = staff_public_name(user, str(user.get("name") or ""), str(user.get("email") or ""))
    tag = staff_public_tag(user, display_name, conn)
    try:
        conn.execute(
            """INSERT INTO former_staff_snapshots
               (project_id, user_id, name, tag, email, role, avatar, removed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(project_id, user_id) DO UPDATE SET
                 name=excluded.name, tag=excluded.tag, email=excluded.email,
                 role=excluded.role, avatar=excluded.avatar, removed_at=excluded.removed_at""",
            (pid, uid, display_name, tag, str(user.get("email") or ""),
             str(user.get("role") or "staff"), avatar, _now_ms()),
        )
    except Exception as exc:
        print("former staff snapshot failed", type(exc).__name__, exc)
    conn.execute(
        "UPDATE staff_members SET active = 0 WHERE project_id = ? AND (COALESCE(user_id, 0) = ? OR id = ?)",
        (pid, uid, int(client_id or 0)),
    )
    audit(conn, "staff_delete", {"project_id": pid, "target_user_id": uid})
    return {"ok": True}


def former_staff_snapshot(conn, project_id: int, user_id: int) -> dict | None:
    """Historical staff identity for moderation rows after the account leaves."""
    pid = int(project_id or 0)
    uid = int(user_id or 0)
    if not pid or not uid:
        return None
    try:
        row = conn.execute(
            "SELECT * FROM former_staff_snapshots WHERE project_id = ? AND user_id = ?",
            (pid, uid),
        ).fetchone()
        if row:
            return dict(row)
    except Exception:
        pass
    # Rows created before snapshots existed can still be restored from the
    # inactive membership record.
    try:
        row = conn.execute(
            "SELECT name, email, role FROM staff_members WHERE project_id = ? AND user_id = ? ORDER BY id DESC LIMIT 1",
            (pid, uid),
        ).fetchone()
        if row:
            old = dict(row)
            name = staff_public_name(None, old.get("name") or "", old.get("email") or "")
            return {
                "project_id": pid, "user_id": uid, "name": name,
                "tag": staff_public_tag({"email": old.get("email") or "", "name": name}, name, conn),
                "email": old.get("email") or "", "role": old.get("role") or "staff", "avatar": "",
            }
    except Exception:
        pass
    return None


def staff_guard(conn, user: dict) -> dict | None:
    if not user:
        return {"message": "password.missmatch"}
    email = str(user.get("email") or "").lower()
    if email == OWNER_EMAIL.lower() or str(user.get("role") or "") == "owner" or int(user.get("is_admin") or 0):
        return None
    pid = request_project_id()
    prow = None
    if pid:
        prow = conn.execute("SELECT * FROM project WHERE id = ?", (pid,)).fetchone()
    if not prow:
        prow = conn.execute("SELECT * FROM project ORDER BY id ASC LIMIT 1").fetchone()
    if not prow:
        return None
    twofa = bool(prow["twofa_strict"] if "twofa_strict" in prow.keys() else 0)
    steam = bool(prow["steam_strict"] if "steam_strict" in prow.keys() else 0)
    if twofa and not (user.get("twofactor_active") or user.get("twofa")):
        return {"message": "twofactor.required", "code": "twofactor.required", "need_2fa": True}
    if steam and not str(user.get("steam_id") or "").strip():
        return {"message": "steam.required", "code": "steam.required", "need_steam": True}
    return None


def save_team_snapshot(conn, steam_id: str, members: list, project_id: int = 0, server_id: int = 0) -> None:
    sid = str(steam_id or "")
    if not sid:
        return
    ids = sorted({str(x) for x in members if str(x).strip() and str(x) != sid})
    key = ",".join(ids)
    pid = int(project_id or request_project_id() or 0)
    sid_srv = int(server_id or 0)
    now = _now_ms()
    if pid:
        open_row = conn.execute(
            """SELECT * FROM team_history
               WHERE steam_id = ? AND ended_at = 0 AND COALESCE(project_id, 0) = ?
               ORDER BY id DESC LIMIT 1""",
            (sid, pid),
        ).fetchone()
    else:
        open_row = None
    if open_row and str(open_row["team_key"] or "") == key:
        return
    if open_row:
        conn.execute("UPDATE team_history SET ended_at = ? WHERE id = ?", (now, open_row["id"]))
    if not ids:
        # Leaving team — close any open mate snapshots that still list this player
        try:
            mate_sql = """SELECT id, members FROM team_history
                   WHERE ended_at = 0 AND steam_id != ?"""
            mate_args = [sid]
            if pid:
                mate_sql += " AND COALESCE(project_id, 0) = ?"
                mate_args.append(pid)
            for mate_row in conn.execute(mate_sql, mate_args).fetchall():
                try:
                    mate_members = json.loads(mate_row["members"] or "[]")
                except Exception:
                    mate_members = []
                if sid in {str(x) for x in mate_members}:
                    conn.execute("UPDATE team_history SET ended_at = ? WHERE id = ?", (now, mate_row["id"]))
        except Exception:
            pass
        return
    if pid:
        try:
            last = conn.execute(
                """SELECT id, ended_at FROM team_history
                   WHERE steam_id = ? AND COALESCE(project_id, 0) = ? AND team_key = ?
                   ORDER BY id DESC LIMIT 1""",
                (sid, pid, key),
            ).fetchone()
            if last and int(last["ended_at"] or 0) and (now - int(last["ended_at"] or 0)) < 10 * 60 * 1000:
                conn.execute("UPDATE team_history SET ended_at = 0 WHERE id = ?", (last["id"],))
                return
        except Exception:
            pass
    conn.execute(
        """INSERT INTO team_history (steam_id, team_key, members, started_at, ended_at, project_id, server_id)
           VALUES (?, ?, ?, ?, 0, ?, ?)""",
        (sid, key, json.dumps(ids, ensure_ascii=False), now, pid, sid_srv),
    )
    # Mirror snapshot for teammates so history shows for every member
    for mid in ids:
        try:
            if pid:
                mate_open = conn.execute(
                    """SELECT * FROM team_history
                       WHERE steam_id = ? AND ended_at = 0 AND COALESCE(project_id, 0) = ?
                       ORDER BY id DESC LIMIT 1""",
                    (mid, pid),
                ).fetchone()
            else:
                mate_open = None
            mate_ids = sorted({sid, *[x for x in ids if x != mid]})
            mate_key = ",".join(mate_ids)
            if mate_open and str(mate_open["team_key"] or "") == mate_key:
                continue
            if mate_open:
                conn.execute("UPDATE team_history SET ended_at = ? WHERE id = ?", (now, mate_open["id"]))
            conn.execute(
                """INSERT INTO team_history (steam_id, team_key, members, started_at, ended_at, project_id, server_id)
                   VALUES (?, ?, ?, ?, 0, ?, ?)""",
                (mid, mate_key, json.dumps(mate_ids, ensure_ascii=False), now, pid, sid_srv),
            )
        except Exception:
            pass


CONTACT_JUNK = {
    "", "нет", "no", "none", "n/a", "na", "нетвк", ".", "-", "—", "немає", "нету",
    "null", "undefined", "discord", "ds", "контакт", "contact", "хз", "idk",
}


def normalize_contact(text: str) -> str:
    raw = str(text or "").strip().lower()
    raw = re.sub(r"^/+", "", raw)
    if raw.startswith("contact"):
        raw = raw[7:].strip()
        raw = re.sub(r"^/+", "", raw)
    raw = raw.replace("https://", "").replace("http://", "")
    raw = raw.replace("www.", "").replace("discord.gg/", "").replace("discord.com/invite/", "")
    raw = re.sub(r"#\d{4}$", "", raw)
    raw = re.sub(r"\s+", "", raw)
    return raw


def contact_lookup_key(text: str) -> str:
    """Normalized Discord/contact used for match search. Empty = do not search."""
    key = normalize_contact(text)
    if len(key) < 3 or key in CONTACT_JUNK:
        return ""
    return key


def find_contact_matches(conn, contact: str, steam_id: str, project_id: int) -> list:
    """Other players in THIS project who sent the same Discord/contact. Never dump the whole server."""
    key = contact_lookup_key(contact)
    sid = str(steam_id or "").strip()
    pid = int(project_id or request_project_id() or 0)
    if not pid or not key:
        return []
    out = []
    seen = set()
    try:
        rows = conn.execute(
            """SELECT steam_id, steam_name, contact FROM checks
               WHERE COALESCE(project_id, 0) = ?
                 AND steam_id != ?
                 AND TRIM(COALESCE(contact, '')) != ''
               ORDER BY id DESC LIMIT 300""",
            (pid, sid),
        ).fetchall()
    except Exception:
        rows = []
    for row in rows:
        other = str(row["steam_id"] or "").strip()
        if not other or other in seen or other == sid:
            continue
        if normalize_contact(row["contact"] or "") != key:
            continue
        seen.add(other)
        name = str(row["steam_name"] or other)
        out.append({
            "steam_id": other,
            "steam_name": name,
            "name": name,
            "contact": str(row["contact"] or ""),
        })
        if len(out) >= 20:
            break
    return out


def record_team_event(conn, event: str, steam_id: str, members: list, project_id: int = 0, server_id: int = 0) -> None:
    """Persist an explicit team lifecycle event for GET /players/{id}/team-history."""
    sid = str(steam_id or "")
    pid = int(project_id or request_project_id() or 0)
    if not sid or not pid:
        return
    ids = [str(x) for x in (members or []) if str(x).strip()]
    try:
        conn.execute(
            """INSERT INTO team_events (event, steam_id, members, created_at, project_id, server_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (str(event or "team.updated"), sid, json.dumps(ids, ensure_ascii=False), _now_ms(), pid, int(server_id or 0)),
        )
    except Exception as exc:
        print("record_team_event failed", type(exc).__name__, exc)


def team_history_items(conn, steam_id: str) -> list:
    sid = str(steam_id)
    items = []
    placeholder = "/local/logo-avatar.png"

    def _member(mid: str) -> dict:
        mid = str(mid or "").strip()
        name = mid
        avatar = placeholder
        try:
            name_row = conn.execute("SELECT steam_name FROM players WHERE steam_id = ?", (mid,)).fetchone()
            if name_row and name_row["steam_name"]:
                name = str(name_row["steam_name"])
        except Exception:
            pass
        try:
            cached = read_cache(conn, "steam_cache", "steam_id", mid)
            if isinstance(cached, dict):
                if cached.get("avatar"):
                    avatar = str(cached.get("avatar") or avatar)
                if cached.get("personaname") and (not name or name == mid):
                    name = str(cached.get("personaname") or name)
        except Exception:
            pass
        return {
            "steam_id": mid,
            "steam_name": name,
            "name": name,
            "id": mid,
            "steam_avatar": avatar,
            "avatar": avatar,
            "status": "offline",
            "steam_data": {"steamid": mid, "personaname": name, "avatarfull": avatar},
        }

    self_player = _member(sid)
    pid = int(request_project_id() or 0)
    if not pid:
        return []
    default_sid = 0
    valid_ids: set[int] = set()
    try:
        for srow in conn.execute(
            "SELECT id FROM servers WHERE project_id = ? AND COALESCE(paired, 0) = 1 ORDER BY id ASC",
            (pid,),
        ).fetchall():
            sidn = int(srow["id"] or 0)
            if sidn:
                valid_ids.add(sidn)
                if not default_sid:
                    default_sid = sidn
        if not default_sid:
            srow = conn.execute(
                "SELECT id FROM servers WHERE project_id = ? ORDER BY id ASC LIMIT 1",
                (pid,),
            ).fetchone()
            if srow:
                default_sid = int(srow["id"] or 0)
                if default_sid:
                    valid_ids.add(default_sid)
    except Exception:
        default_sid = 0

    def _court_server_id(raw) -> int:
        try:
            n = int(raw or 0)
        except Exception:
            n = 0
        if n and n in valid_ids:
            return n
        return default_sid
    seen_keys = set()
    for row in conn.execute(
        """SELECT * FROM team_history
           WHERE steam_id = ? AND COALESCE(project_id, 0) = ?
           ORDER BY id DESC LIMIT 200""",
        (sid, pid),
    ).fetchall():
        team_key = str(row["team_key"] or "")
        if team_key and team_key in seen_keys:
            continue
        if team_key:
            seen_keys.add(team_key)
        try:
            members = json.loads(row["members"] or "[]")
        except Exception:
            members = str(row["team_key"] or "").split(",") if row["team_key"] else []
        players = []
        for mid in members:
            mid = str(mid or "").strip()
            if not mid or mid == sid:
                continue
            players.append(_member(mid))
        if not players:
            continue
        started = int(row["started_at"] or 0)
        ended = int(row["ended_at"] or 0) or None
        size = max(1, len(players) + 1)
        team_all = [self_player] + players
        items.append({
            "id": int(row["id"] or 0),
            "steam_id": sid,
            "player_id": sid,
            "project_id": pid,
            "server_id": _court_server_id(row["server_id"] if "server_id" in row.keys() else 0),
            "started_at": started,
            "ended_at": ended,
            "created_at": started,
            "finished_at": ended,
            "ended": bool(ended),
            "active": not ended,
            "status": "active" if not ended else "ended",
            "size": size,
            "team_size": size,
            "members": players,
            "players": players,
            "team": players,
            "teammates": players,
            "team_players": team_all,
            "player": self_player,
            "friends": players,
            "last_seen_at": ended or started,
        })
    if items:
        return items
    try:
        ev_rows = conn.execute(
            """SELECT * FROM team_events
               WHERE (steam_id = ? OR members LIKE ?) AND COALESCE(project_id, 0) = ?
               ORDER BY id DESC LIMIT 80""",
            (sid, "%" + sid + "%", pid),
        ).fetchall()
    except Exception:
        ev_rows = []
    for row in ev_rows:
        try:
            members = json.loads(row["members"] or "[]")
        except Exception:
            members = []
        members = [str(m) for m in members if str(m).strip()]
        if sid not in members:
            members = [sid] + members
        players = [_member(m) for m in members if m != sid]
        if not players:
            continue
        started = int(row["created_at"] or 0)
        team_all = [self_player] + players
        items.append({
            "id": "ev-%s" % (row["id"] or started),
            "steam_id": sid,
            "player_id": sid,
            "project_id": pid,
            "server_id": _court_server_id(row["server_id"] if "server_id" in row.keys() else 0),
            "started_at": started,
            "ended_at": None,
            "created_at": started,
            "finished_at": None,
            "ended": False,
            "active": True,
            "status": "active",
            "size": max(1, len(players) + 1),
            "team_size": max(1, len(players) + 1),
            "members": players,
            "players": players,
            "team": players,
            "teammates": players,
            "team_players": team_all,
            "player": self_player,
            "friends": players,
            "last_seen_at": started,
        })
    return items


def signage_image_file(net_id: str) -> Path:
    safe = re.sub(r"[^\w.-]", "", str(net_id or ""))
    return UPLOADS / f"signage-{safe or 'unknown'}.png"


def persist_signage_image(net_id: str, image: str) -> str:
    net_id = str(net_id or "").strip()
    if not net_id:
        return ""
    raw = str(image or "").strip()
    if not raw:
        path = signage_image_file(net_id)
        if path.exists() and path.stat().st_size > 32:
            return f"/uploads/{path.name}"
        return ""
    if raw.startswith("/uploads/"):
        return raw
    if raw.startswith("/"):
        return raw
    payload = raw.split(",", 1)[-1] if raw.startswith("data:") else raw
    try:
        data = base64.b64decode(payload, validate=False)
    except Exception:
        return raw if raw.startswith("data:") else ""
    if len(data) < 32:
        return ""
    path = signage_image_file(net_id)
    path.write_bytes(data)
    return f"/uploads/{path.name}"


def normalize_signage_image(net_id: str, image: str) -> str:
    image = str(image or "").strip()
    if image.startswith("/uploads/"):
        fs = UPLOADS / image.split("/")[-1]
        if fs.exists() and fs.stat().st_size > 32:
            return image
    if image.startswith("/") and not image.startswith("/uploads/"):
        return image
    if image.startswith("data:") or (image and not image.startswith("/") and len(image) > 80):
        saved = persist_signage_image(net_id, image)
        if saved:
            return saved
    path = signage_image_file(net_id)
    if path.exists() and path.stat().st_size > 32:
        return f"/uploads/{path.name}"
    return ""


def save_signage(conn, body) -> dict:
    item = body if isinstance(body, dict) else {}
    steam_id = str(item.get("steam_id") or item.get("owner_steam_id") or "")
    net_id = str(item.get("net_id") or item.get("id") or "").strip()
    image = str(item.get("base64_image") or item.get("image") or item.get("url") or "")
    if net_id and image:
        persist_signage_image(net_id, image)
    if image and not image.startswith("data:") and not image.startswith("/") and len(image) > 80:
        image = "data:image/png;base64," + image
    pos = item.get("position")
    if isinstance(pos, dict):
        pos = json.dumps(pos, ensure_ascii=False)
    pos = str(pos or "")
    square = str(item.get("square") or item.get("grid") or "")
    typ = str(item.get("type") or item.get("prefab") or "sign")
    pid = request_project_id() or 0
    now = _now_ms()
    if net_id:
        # One entity id = one drawing card (wipe any prior rows / races / project mismatches)
        conn.execute("DELETE FROM signage WHERE net_id = ?", (net_id,))
    conn.execute(
        """INSERT INTO signage (steam_id, net_id, type, position, square, image, created_at, destroyed_at, project_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)""",
        (steam_id, net_id, typ, pos, square, image, now, pid),
    )
    emit_json_webhook(conn,"signage_create",{"data":{"steam_id":steam_id,"net_id":net_id,"type":typ,"square":square,"created_at":now}},project_id=pid)
    return {"ok": True, "net_id": net_id}


def delete_signage(conn, net_ids) -> dict:
    if isinstance(net_ids, dict):
        net_ids = net_ids.get("net_ids") or net_ids.get("ids") or []
    if not isinstance(net_ids, list):
        net_ids = [net_ids]
    now = _now_ms()
    for nid in net_ids:
        net_id = str(nid or "").strip()
        if not net_id:
            continue
        rows = conn.execute("SELECT net_id,steam_id,project_id FROM signage WHERE net_id = ? AND COALESCE(destroyed_at,0) = 0", (net_id,)).fetchall()
        for row in rows:
            emit_json_webhook(conn,"signage_delete",{"data":dict(row)},project_id=int(row["project_id"] or 0))
        # Soft-delete by net_id across projects so in-game destroy always clears the site
        conn.execute(
            """UPDATE signage SET destroyed_at = ?
               WHERE net_id = ? AND COALESCE(destroyed_at, 0) = 0""",
            (now, net_id),
        )
    return {"ok": True}


def delete_signage_one(conn, net_id: str, server_id: int = 0) -> dict:
    net_id = str(net_id or "").strip()
    if not net_id:
        return {}
    pid = request_project_id() or 0
    row = conn.execute(
        "SELECT * FROM signage WHERE net_id = ? ORDER BY id DESC LIMIT 1",
        (net_id,),
    ).fetchone()
    server_row = conn.execute(
        "SELECT id FROM servers WHERE project_id = ? AND paired = 1 ORDER BY last_seen DESC, id DESC LIMIT 1",
        (pid,),
    ).fetchone()
    sid = int(server_id or (server_row["id"] if server_row else 1))
    destroyed_at = _now_ms()
    if row:
        steam_id = str(row["steam_id"] or "")
        name_row = conn.execute("SELECT steam_name FROM players WHERE steam_id = ?", (steam_id,)).fetchone() if steam_id else None
        player_name = name_row["steam_name"] if name_row else steam_id
        image = normalize_signage_image(net_id, row["image"] or "")
        variant = {
            "id": row["id"],
            "net_id": net_id,
            "steam_id": steam_id,
            "type": row["type"] or "sign",
            "image": image,
            "url": image,
            "src": image,
            "base64_image": image,
            "position": row["position"] or "",
            "square": row["square"] or "",
            "grid": row["square"] or "",
            "created_at": int(row["created_at"] or destroyed_at),
            "player": {
                "steam_id": steam_id,
                "steam_name": player_name or steam_id,
                "name": player_name or steam_id,
            },
        }
        conn.execute(
            """UPDATE signage SET destroyed_at = ?
               WHERE net_id = ?""",
            (destroyed_at, net_id),
        )
        return {
            "id": row["id"],
            "net_id": net_id,
            "steam_id": steam_id,
            "server_id": sid,
            "project_id": pid or 0,
            "type": row["type"] or "sign",
            "position": row["position"] or "",
            "square": row["square"] or "",
            "grid": row["square"] or "",
            "image": image,
            "url": image,
            "created_at": int(row["created_at"] or destroyed_at),
            "destroyed_at": destroyed_at,
            "variants": [variant],
        }
    return {
        "net_id": net_id,
        "server_id": sid,
        "project_id": pid or 0,
        "destroyed_at": destroyed_at,
        "variants": [],
    }


def signage_items(conn, steam_id: str = "", include_destroyed: bool = True) -> list:
    pid = request_project_id() or 0
    if pid:
        sql = "SELECT * FROM signage WHERE project_id = ?"
        args = [pid]
    else:
        sql = "SELECT * FROM signage WHERE 0=1"
        args = []
    if steam_id:
        sql += " AND steam_id = ?"
        args.append(str(steam_id))
    if not include_destroyed:
        sql += " AND COALESCE(destroyed_at, 0) = 0"
    sql += " ORDER BY id DESC LIMIT 500"
    items = []
    for row in conn.execute(sql, args).fetchall():
        net_id = str(row["net_id"] or "")
        image = normalize_signage_image(net_id, row["image"] or "")
        destroyed = int(row["destroyed_at"] if "destroyed_at" in row.keys() else 0) or 0
        items.append({
            "id": row["id"],
            "net_id": net_id,
            "steam_id": row["steam_id"],
            "type": row["type"] or "sign",
            "position": row["position"] or "",
            "square": row["square"] or "",
            "grid": row["square"] or "",
            "image": image,
            "url": image,
            "src": image,
            "base64_image": image,
            "created_at": row["created_at"],
            "destroyed_at": destroyed or None,
        })
    return items


def _truthy_param(val) -> bool:
    if val in (True, 1, "1", "true", "True", "yes", "on"):
        return True
    return False


def signage_browse(conn, steam_id: str = "", hide_destroyed: bool = True, hide_actual: bool = False, only_liked: bool = False) -> list:
    pid = request_project_id() or 0
    server_row = conn.execute(
        "SELECT id FROM servers WHERE project_id = ? AND paired = 1 ORDER BY last_seen DESC, id DESC LIMIT 1",
        (pid,),
    ).fetchone()
    server_id = int(server_row["id"]) if server_row else 1
    # Drop accidental duplicate active rows for the same entity (keep newest)
    try:
        conn.execute(
            """DELETE FROM signage
               WHERE net_id IS NOT NULL AND net_id != ''
                 AND COALESCE(destroyed_at, 0) = 0
                 AND id NOT IN (
                   SELECT mid FROM (
                     SELECT MAX(id) AS mid FROM signage
                     WHERE net_id IS NOT NULL AND net_id != ''
                       AND COALESCE(destroyed_at, 0) = 0
                     GROUP BY net_id
                   )
                 )"""
        )
    except Exception as exc:
        print("signage dedupe failed", exc)
    include_destroyed = True
    if hide_destroyed and not hide_actual:
        include_destroyed = False
    grouped = {}
    for row in signage_items(conn, steam_id, include_destroyed=True):
        net_id = str(row.get("net_id") or "").strip()
        if not net_id:
            continue
        destroyed_at = int(row.get("destroyed_at") or 0) or None
        if hide_destroyed and destroyed_at:
            continue
        if hide_actual and not destroyed_at:
            continue
        sid = str(row.get("steam_id") or "")
        name_row = conn.execute("SELECT steam_name FROM players WHERE steam_id = ?", (sid,)).fetchone() if sid else None
        player_name = str(name_row["steam_name"] if name_row else "").strip() or sid
        variant = {
            "id": row.get("id"),
            "net_id": net_id,
            "steam_id": sid,
            "type": row.get("type") or "sign",
            "image": row.get("image") or "",
            "url": row.get("url") or row.get("image") or "",
            "src": row.get("src") or row.get("image") or "",
            "s3_id": row.get("url") or row.get("image") or "",
            "base64_image": row.get("base64_image") or row.get("image") or "",
            "position": row.get("position") or "",
            "square": row.get("square") or "",
            "grid": row.get("grid") or row.get("square") or "",
            "created_at": int(row.get("created_at") or _now_ms()),
            "player": {
                "steam_id": sid,
                "steam_name": player_name or sid,
                "name": player_name or sid,
            },
        }
        if net_id in grouped:
            if int(row.get("created_at") or 0) >= int(grouped[net_id].get("created_at") or 0):
                grouped[net_id]["id"] = row.get("id")
                grouped[net_id]["created_at"] = int(row.get("created_at") or _now_ms())
                grouped[net_id]["image"] = row.get("image") or grouped[net_id].get("image") or ""
                grouped[net_id]["url"] = grouped[net_id]["image"]
                grouped[net_id]["destroyed_at"] = destroyed_at
                grouped[net_id]["variants"] = [variant]
            continue
        grouped[net_id] = {
            "id": row.get("id"),
            "net_id": net_id,
            "steam_id": sid,
            "server_id": server_id,
            "project_id": pid or 0,
            "type": row.get("type") or "sign",
            "position": row.get("position") or "",
            "square": row.get("square") or "",
            "grid": row.get("grid") or row.get("square") or "",
            "image": row.get("image") or "",
            "url": row.get("url") or row.get("image") or "",
            "s3_id": row.get("url") or row.get("image") or "",
            "created_at": int(row.get("created_at") or _now_ms()),
            "destroyed_at": destroyed_at,
            "variants": [variant],
        }
    out = list(grouped.values())
    out.sort(key=lambda item: int(item.get("created_at") or 0), reverse=True)
    uid = int(request_user_id() or 0)
    liked_ids = set()
    liked_nets = set()
    if uid and pid:
        try:
            for lr in conn.execute(
                "SELECT drawing_id, net_id FROM signage_likes WHERE user_id = ? AND project_id = ?",
                (uid, pid),
            ).fetchall():
                liked_ids.add(int(lr["drawing_id"] or 0))
                if lr["net_id"]:
                    liked_nets.add(str(lr["net_id"]))
        except Exception:
            liked_ids = set()
            liked_nets = set()
    for item in out:
        did = int(item.get("id") or 0)
        nid = str(item.get("net_id") or "")
        liked = (did and did in liked_ids) or (nid and nid in liked_nets)
        item["liked"] = liked
        item["is_liked"] = liked
        item["likedByCurrentUser"] = liked
        item["liked_by_current_user"] = liked
        item["liked_by_me"] = liked
    if only_liked:
        out = [item for item in out if item.get("liked")]
    return out


def signage_toggle_like(conn, drawing_id: int = 0, net_id: str = "", liked=None) -> dict:
    """Persist like for current user + current project. Toggle if liked is None."""
    uid = int(request_user_id() or 0)
    pid = int(request_project_id() or 0)
    did = int(drawing_id or 0)
    nid = str(net_id or "").strip()
    if not uid or not pid:
        return {"ok": False, "liked": False, "likedByCurrentUser": False, "message": "unauthorized"}
    if not did and nid:
        row = conn.execute(
            "SELECT id FROM signage WHERE net_id = ? AND COALESCE(project_id, 0) = ? ORDER BY id DESC LIMIT 1",
            (nid, pid),
        ).fetchone()
        if row:
            did = int(row["id"] or 0)
    if not did:
        return {"ok": False, "liked": False, "likedByCurrentUser": False, "message": "drawing not found"}
    if not nid:
        nrow = conn.execute("SELECT net_id FROM signage WHERE id = ?", (did,)).fetchone()
        nid = str((nrow["net_id"] if nrow else "") or "")
    existing = conn.execute(
        "SELECT id FROM signage_likes WHERE user_id = ? AND drawing_id = ?",
        (uid, did),
    ).fetchone()
    want = liked
    if want is None:
        want = existing is None
    else:
        want = bool(want)
    if want and not existing:
        conn.execute(
            """INSERT INTO signage_likes (user_id, drawing_id, net_id, project_id, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (uid, did, nid, pid, _now_ms()),
        )
    elif (not want) and existing:
        conn.execute("DELETE FROM signage_likes WHERE user_id = ? AND drawing_id = ?", (uid, did))
    return {
        "ok": True,
        "id": did,
        "drawing_id": did,
        "net_id": nid,
        "project_id": pid,
        "liked": bool(want),
        "is_liked": bool(want),
        "likedByCurrentUser": bool(want),
        "liked_by_current_user": bool(want),
    }


def ensure_admin_schema(conn) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS user_login_ips (
            user_id INTEGER NOT NULL,
            ip TEXT NOT NULL,
            first_seen INTEGER DEFAULT 0,
            last_seen INTEGER DEFAULT 0,
            hits INTEGER DEFAULT 1,
            revoked INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, ip)
        );
        CREATE TABLE IF NOT EXISTS blocked_server_ips (
            server_ip TEXT PRIMARY KEY,
            blocked_at INTEGER DEFAULT 0,
            blocked_by TEXT DEFAULT '',
            reason TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS blocked_user_ips (
            ip TEXT PRIMARY KEY,
            blocked_at INTEGER DEFAULT 0,
            blocked_by TEXT DEFAULT '',
            reason TEXT DEFAULT ''
        );
        """
    )
    for col, default in (
        ("is_platform_admin", "INTEGER DEFAULT 0"),
        ("created_at", "INTEGER DEFAULT 0"),
        ("projects_blocked", "INTEGER DEFAULT 0"),
        ("projects_blocked_at", "INTEGER DEFAULT 0"),
        ("account_blocked", "INTEGER DEFAULT 0"),
        ("account_blocked_at", "INTEGER DEFAULT 0"),
        ("account_blocked_reason", "TEXT DEFAULT ''"),
        ("last_seen_at", "INTEGER DEFAULT 0"),
    ):
        try:
            conn.execute(f"ALTER TABLE users ADD COLUMN {col} {default}")
        except Exception:
            pass
    try:
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
    except Exception:
        pass
    for col, default in (
        ("reply_to", "INTEGER DEFAULT 0"),
        ("reply_name", "TEXT DEFAULT ''"),
        ("reply_text", "TEXT DEFAULT ''"),
        ("reply_kind", "TEXT DEFAULT ''"),
        ("mentions", "TEXT DEFAULT '[]'"),
    ):
        try:
            conn.execute(f"ALTER TABLE admin_chat ADD COLUMN {col} {default}")
        except Exception:
            pass
    try:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS blocked_user_ips (
                ip TEXT PRIMARY KEY,
                blocked_at INTEGER DEFAULT 0,
                blocked_by TEXT DEFAULT '',
                reason TEXT DEFAULT ''
            )"""
        )
    except Exception:
        pass
    for col, default in (
        ("blocked", "INTEGER DEFAULT 0"),
        ("admin_frozen", "INTEGER DEFAULT 0"),
        ("created_at", "INTEGER DEFAULT 0"),
        ("trial_discarded", "INTEGER DEFAULT 0"),
    ):
        try:
            conn.execute(f"ALTER TABLE project ADD COLUMN {col} {default}")
        except Exception:
            pass
    for col, default in (
        ("actor_user_id", "INTEGER DEFAULT 0"),
        ("actor_name", "TEXT DEFAULT ''"),
        ("actor_email", "TEXT DEFAULT ''"),
        ("actor_role", "TEXT DEFAULT ''"),
    ):
        try:
            conn.execute(f"ALTER TABLE audit ADD COLUMN {col} {default}")
        except Exception:
            pass
        if col in ("actor_user_id", "actor_name", "actor_email", "actor_role"):
            for table in ("mutes", "bans", "checks", "chat"):
                try:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {default}")
                except Exception:
                    pass
    for col, default in (
        ("pending", "INTEGER DEFAULT 0"),
        ("pending_meta", "TEXT DEFAULT ''"),
    ):
        try:
            conn.execute(f"ALTER TABLE bans ADD COLUMN {col} {default}")
        except Exception:
            pass
    for col, default in (
        ("actor_user_id", "INTEGER DEFAULT 0"),
        ("actor_name", "TEXT DEFAULT ''"),
        ("currency", "TEXT DEFAULT 'RUB'"),
        ("status", "TEXT DEFAULT 'success'"),
        ("op_type", "TEXT DEFAULT ''"),
        ("extra", "TEXT DEFAULT ''"),
    ):
        try:
            conn.execute(f"ALTER TABLE wallet_ops ADD COLUMN {col} {default}")
        except Exception:
            pass
    try:
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_google_id ON users(google_id) WHERE google_id != ''"
        )
    except Exception:
        pass
    try:
        _backfill_audit_actors(conn)
    except Exception:
        pass
    try:
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS webhooks_project_kind ON webhooks(project_id, kind)"
        )
    except Exception:
        pass
    try:
        conn.execute(
            "UPDATE users SET is_platform_admin = 1, role = 'owner' WHERE lower(email) = ?",
            (OWNER_EMAIL.lower(),),
        )
    except Exception:
        pass
    try:
        now = _now_ms()
        conn.execute("UPDATE project SET created_at = ? WHERE COALESCE(created_at, 0) = 0", (now,))
        conn.execute("UPDATE users SET created_at = ? WHERE COALESCE(created_at, 0) = 0", (now,))
    except Exception:
        pass
    # Clear stale user block flags left after blocked projects were deleted/unblocked.
    try:
        conn.execute(
            """UPDATE users SET projects_blocked = 0, projects_blocked_at = 0
               WHERE COALESCE(projects_blocked, 0) = 1
                 AND id NOT IN (
                   SELECT DISTINCT COALESCE(owner_user_id, 0) FROM project
                   WHERE COALESCE(blocked, 0) = 1 AND COALESCE(owner_user_id, 0) > 0
                 )"""
        )
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE user_login_ips ADD COLUMN revoked INTEGER DEFAULT 0")
    except Exception:
        pass
    protect_owner_account(conn)
    try:
        ensure_bootstrap_admin(conn)
    except Exception:
        pass


def admin_emails() -> set[str]:
    raw = str(os.environ.get("CHECKAPP_ADMIN_EMAILS") or "").strip()
    emails = {OWNER_EMAIL.lower()}
    if raw:
        emails.update(e.strip().lower() for e in raw.split(",") if e.strip())
    return emails


def is_platform_admin(user: dict | None) -> bool:
    if not user:
        return False
    email = str(user.get("email") or "").lower().strip()
    if email in admin_emails():
        return True
    try:
        if int(user.get("is_platform_admin") or 0):
            return True
    except Exception:
        pass
    return False


def is_platform_owner(user: dict | None) -> bool:
    if not user:
        return False
    email = str(user.get("email") or "").lower().strip()
    if email == OWNER_EMAIL.lower():
        return True
    return str(user.get("role") or "").lower() == "owner" and email == OWNER_EMAIL.lower()


def platform_admin_role(user: dict | None) -> str:
    if is_platform_owner(user):
        return "owner"
    if is_platform_admin(user):
        return "admin"
    return ""


def list_platform_admins(conn) -> list:
    try:
        rows = conn.execute(
            "SELECT * FROM users ORDER BY id ASC"
        ).fetchall()
    except Exception:
        return []
    out = []
    for row in rows:
        try:
            item = dict(row)
        except Exception:
            continue
        email = str(item.get("email") or "").lower()
        try:
            flagged = int(item.get("is_platform_admin") or 0)
        except Exception:
            flagged = 0
        if not flagged and email != OWNER_EMAIL.lower():
            continue
        role = "owner" if email == OWNER_EMAIL.lower() else "admin"
        out.append({
            "id": int(item.get("id") or 0),
            "email": item.get("email") or "",
            "name": item.get("name") or "",
            "role": role,
            "role_label": "Главный администратор" if role == "owner" else "Администратор",
            "is_owner": role == "owner",
            "created_at": int(item.get("created_at") or 0),
            "last_seen_at": int(item.get("last_seen_at") or 0),
            "online": False,
        })
    out.sort(key=lambda a: (0 if a.get("is_owner") else 1, a.get("id") or 0))
    return out


def add_platform_admin(conn, email: str, actor: str = "") -> dict:
    email = str(email or "").strip().lower()
    if not email or "@" not in email:
        return {"ok": False, "message": "Укажите email пользователя"}
    if email == OWNER_EMAIL.lower():
        return {"ok": False, "message": "Этот пользователь уже главный администратор"}
    row = conn.execute("SELECT * FROM users WHERE lower(email) = ?", (email,)).fetchone()
    if not row:
        return {"ok": False, "message": "Пользователь с такой почтой не найден. Сначала он должен зарегистрироваться."}
    uid = int(row["id"])
    conn.execute(
        "UPDATE users SET is_platform_admin = 1, role = 'admin' WHERE id = ?",
        (uid,),
    )
    audit(conn, "admin.platform.add", {"user_id": uid, "email": email, "role": "admin", "actor": actor})
    return {"ok": True, "admins": list_platform_admins(conn)}


def remove_platform_admin(conn, uid: int, actor: str = "") -> dict:
    try:
        uid = int(uid or 0)
    except Exception:
        uid = 0
    if not uid:
        return {"ok": False, "message": "user_id required"}
    row = conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    if not row:
        return {"ok": False, "message": "not found"}
    email = str(row["email"] or "").lower()
    if email == OWNER_EMAIL.lower():
        return {"ok": False, "message": "Нельзя удалить главного администратора"}
    conn.execute(
        "UPDATE users SET is_platform_admin = 0, role = CASE WHEN role = 'admin' THEN 'user' ELSE role END WHERE id = ?",
        (uid,),
    )
    audit(conn, "admin.platform.remove", {"user_id": uid, "email": email, "actor": actor})
    return {"ok": True, "admins": list_platform_admins(conn)}


def set_platform_admin_role(conn, uid: int, role: str, actor: str = "") -> dict:
    role = str(role or "admin").strip().lower()
    if role not in ("admin",):
        return {"ok": False, "message": "Доступна только роль «Администратор»"}
    row = conn.execute("SELECT * FROM users WHERE id = ?", (int(uid),)).fetchone()
    if not row:
        return {"ok": False, "message": "not found"}
    email = str(row["email"] or "").lower()
    if email == OWNER_EMAIL.lower():
        return {"ok": False, "message": "Роль главного администратора нельзя изменить"}
    conn.execute("UPDATE users SET is_platform_admin = 1, role = 'admin' WHERE id = ?", (int(uid),))
    audit(conn, "admin.platform.role", {"user_id": int(uid), "email": email, "role": "admin", "actor": actor})
    return {"ok": True, "admins": list_platform_admins(conn)}


def audit_category(event: str) -> str:
    ev = str(event or "")
    if ev.startswith("admin.platform") or ev.startswith("admin.user") or ev.startswith("admin.block") or ev.startswith("admin.unblock"):
        return "admin"
    if ev.startswith("admin."):
        return "panel"
    if ev.startswith("auth.") or ev.startswith("project.freeze") or ev.startswith("plugin"):
        return "system"
    return "projects"


def _backfill_audit_actors(conn) -> None:
    """Fill missing actor_user_id from the stored actor email/name. Never use current staff list."""
    try:
        rows = conn.execute(
            """SELECT id, actor, payload, actor_user_id FROM audit
               WHERE COALESCE(actor_user_id, 0) = 0
               ORDER BY id DESC LIMIT 2000"""
        ).fetchall()
    except Exception:
        return
    cache = {}
    for row in rows:
        data = dict(row)
        try:
            payload = json.loads(data.get("payload") or "{}")
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        uid = 0
        try:
            uid = int(payload.get("actor_id") or payload.get("actor_user_id") or 0)
        except Exception:
            uid = 0
        email = str(payload.get("actor_email") or data.get("actor") or "").strip().lower()
        name = str(payload.get("actor_name") or "").strip()
        if not uid and email and "@" in email:
            if email not in cache:
                found = conn.execute("SELECT id, name, email FROM users WHERE lower(email) = ?", (email,)).fetchone()
                cache[email] = dict(found) if found else None
            user = cache.get(email)
            if user:
                uid = int(user.get("id") or 0)
                if not name:
                    name = str(user.get("name") or "")
        if not name:
            name = str(data.get("actor") or payload.get("actor_name") or "")
        try:
            conn.execute(
                "UPDATE audit SET actor_user_id = ?, actor_name = ?, actor_email = ? WHERE id = ?",
                (uid, name, email, int(data.get("id") or 0)),
            )
        except Exception:
            try:
                conn.execute(
                    "UPDATE audit SET actor_user_id = ? WHERE id = ?",
                    (uid, int(data.get("id") or 0)),
                )
            except Exception:
                pass


def list_admin_audit(conn, category: str = "", project_id: int = 0, limit: int = 300) -> list:
    category = str(category or "").strip().lower()
    try:
        limit = min(max(int(limit or 300), 1), 1000)
    except Exception:
        limit = 300
    try:
        rows = conn.execute(
            "SELECT * FROM audit ORDER BY id DESC LIMIT 2000"
        ).fetchall()
    except Exception:
        return []
    items = []
    for row in rows:
        data = dict(row)
        try:
            payload = json.loads(data.get("payload") or "{}")
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {"value": payload}
        event = str(data.get("event") or "")
        cat = audit_category(event)
        pid = 0
        try:
            pid = int(data.get("project_id") or payload.get("project_id") or 0)
        except Exception:
            pid = 0
        if category and cat != category:
            continue
        if project_id and pid != int(project_id):
            continue
        actor_id = 0
        try:
            actor_id = int(data.get("actor_user_id") or payload.get("actor_id") or payload.get("actor_user_id") or 0)
        except Exception:
            actor_id = 0
        actor_name = str(data.get("actor_name") or payload.get("actor_name") or "")
        actor_email = str(data.get("actor_email") or payload.get("actor_email") or data.get("actor") or "")
        if not actor_name:
            actor_name = actor_email.split("@")[0] if "@" in actor_email else str(data.get("actor") or "")
        items.append({
            "id": int(data.get("id") or 0),
            "category": cat,
            "event": event,
            "actor": actor_name or actor_email or data.get("actor") or "",
            "actor_id": actor_id,
            "actor_email": actor_email,
            "actor_name": actor_name,
            "project_id": pid,
            "object": payload.get("steam_id") or payload.get("email") or payload.get("target") or payload.get("target_user_id") or payload.get("reason") or "",
            "payload": payload,
            "created_at": int(data.get("created_at") or 0),
        })
        if len(items) >= limit:
            break
    return items


def has_blocked_owned_project(conn, uid: int) -> bool:
    """True when the user currently owns at least one blocked project."""
    try:
        uid = int(uid or 0)
    except Exception:
        return False
    if not uid:
        return False
    row = conn.execute(
        "SELECT 1 FROM project WHERE COALESCE(owner_user_id, 0) = ? AND COALESCE(blocked, 0) = 1 LIMIT 1",
        (uid,),
    ).fetchone()
    return bool(row)


def user_new_projects_blocked_flag(conn, uid: int) -> bool:
    """Explicit admin flag: block all new projects for this user (persists after project delete)."""
    try:
        uid = int(uid or 0)
    except Exception:
        return False
    if not uid:
        return False
    row = conn.execute("SELECT projects_blocked FROM users WHERE id = ?", (uid,)).fetchone()
    return bool(row and int(row["projects_blocked"] or 0))


def user_projects_blocked(conn, uid: int) -> bool:
    """Block new projects only when admin explicitly flagged the user OR a blocked project exists."""
    return user_new_projects_blocked_flag(conn, uid) or has_blocked_owned_project(conn, uid)


def set_user_projects_blocked(conn, uid: int, blocked: bool = True) -> None:
    try:
        uid = int(uid or 0)
    except Exception:
        return
    if not uid:
        return
    now = _now_ms()
    conn.execute(
        "UPDATE users SET projects_blocked = ?, projects_blocked_at = ? WHERE id = ?",
        (1 if blocked else 0, now if blocked else 0, uid),
    )


def sync_user_projects_blocked(conn, uid: int) -> None:
    """Clear stale user block flag when no blocked projects remain (e.g. after delete/unblock)."""
    try:
        uid = int(uid or 0)
    except Exception:
        return
    if not uid:
        return
    if has_blocked_owned_project(conn, uid):
        return
    set_user_projects_blocked(conn, uid, False)


def apply_owner_block_to_project(conn, project_id: int, owner_user_id: int) -> bool:
    """Auto-block new project when owner is flagged or has blocked projects."""
    try:
        pid = int(project_id or 0)
        uid = int(owner_user_id or 0)
    except Exception:
        return False
    if not pid or not uid:
        return False
    if not user_projects_blocked(conn, uid):
        return False
    conn.execute("UPDATE project SET blocked = 1, admin_frozen = 1 WHERE id = ?", (pid,))
    freeze_project(conn, pid, "owner_projects_blocked")
    return True


def on_admin_project_blocked(conn, project_id: int) -> None:
    """Project-level block only — new projects are blocked via has_blocked_owned_project()."""
    return


def on_admin_project_unblocked(conn, project_id: int) -> None:
    row = conn.execute("SELECT owner_user_id FROM project WHERE id = ?", (int(project_id),)).fetchone()
    if not row:
        return
    uid = int(row["owner_user_id"] or 0)
    if not uid:
        return
    other = conn.execute(
        "SELECT 1 FROM project WHERE COALESCE(owner_user_id, 0) = ? AND COALESCE(blocked, 0) = 1 AND id != ? LIMIT 1",
        (uid, int(project_id)),
    ).fetchone()
    if not other:
        set_user_projects_blocked(conn, uid, False)


def is_protected_owner(conn, uid: int = 0, email: str = "") -> bool:
    mail = str(email or "").strip().lower()
    if mail and mail == OWNER_EMAIL.lower():
        return True
    uid = int(uid or 0)
    if not uid:
        return False
    try:
        row = conn.execute("SELECT email, role FROM users WHERE id = ?", (uid,)).fetchone()
    except Exception:
        row = None
    if not row:
        return False
    return str(row["email"] or "").strip().lower() == OWNER_EMAIL.lower()


def protect_owner_account(conn) -> None:
    try:
        conn.execute(
            """UPDATE users SET account_blocked = 0, account_blocked_at = 0, account_blocked_reason = '',
                   projects_blocked = 0, projects_blocked_at = 0
               WHERE lower(email) = ?""",
            (OWNER_EMAIL.lower(),),
        )
        owner = conn.execute("SELECT id FROM users WHERE lower(email) = ?", (OWNER_EMAIL.lower(),)).fetchone()
        if owner:
            uid = int(owner["id"] or 0)
            ips = [str(r["ip"] or "") for r in conn.execute("SELECT ip FROM user_login_ips WHERE user_id = ?", (uid,)).fetchall()]
            for ip in ips:
                if ip:
                    conn.execute("DELETE FROM blocked_user_ips WHERE ip = ?", (ip,))
    except Exception as exc:
        print("protect_owner_account", type(exc).__name__, exc)


def set_user_account_blocked(conn, uid: int, blocked: bool = True, reason: str = "") -> None:
    uid = int(uid or 0)
    if not uid:
        return
    if blocked and is_protected_owner(conn, uid):
        print("refuse block protected owner", uid)
        return
    prev = conn.execute(
        "SELECT account_blocked, account_blocked_reason FROM users WHERE id = ?",
        (uid,),
    ).fetchone()
    already = bool(prev and int(prev["account_blocked"] or 0))
    if blocked and already:
        return
    if (not blocked) and (not already):
        return
    conn.execute(
        """UPDATE users SET account_blocked = ?, account_blocked_at = ?, account_blocked_reason = ?
           WHERE id = ?""",
        (1 if blocked else 0, _now_ms() if blocked else 0, str(reason or "") if blocked else "", uid),
    )
    if blocked:
        set_user_projects_blocked(conn, uid, True)
    audit(conn, "admin.user.block" if blocked else "admin.user.unblock", {"user_id": uid, "reason": reason})


def user_account_blocked(conn, uid: int) -> bool:
    uid = int(uid or 0)
    if not uid:
        return False
    row = conn.execute("SELECT account_blocked FROM users WHERE id = ?", (uid,)).fetchone()
    return bool(row and int(row["account_blocked"] or 0))


def is_user_ip_blocked(conn, ip: str) -> bool:
    ip = str(ip or "").strip()
    if not ip or ip in ("127.0.0.1", "::1", "0.0.0.0"):
        return False
    row = conn.execute("SELECT ip FROM blocked_user_ips WHERE ip = ?", (ip,)).fetchone()
    return bool(row)


def block_user_ip(conn, ip: str, actor: str = "", reason: str = "") -> None:
    ip = str(ip or "").strip()
    if not ip:
        return
    owner = conn.execute("SELECT id FROM users WHERE lower(email) = ?", (OWNER_EMAIL.lower(),)).fetchone()
    if owner:
        uid = int(owner["id"] or 0)
        used = conn.execute(
            "SELECT 1 FROM user_login_ips WHERE user_id = ? AND ip = ? LIMIT 1",
            (uid, ip),
        ).fetchone()
        if used:
            print("refuse block owner IP", ip)
            return
    conn.execute(
        """INSERT INTO blocked_user_ips (ip, blocked_at, blocked_by, reason)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(ip) DO UPDATE SET
             blocked_at = excluded.blocked_at,
             blocked_by = excluded.blocked_by,
             reason = excluded.reason""",
        (ip, _now_ms(), str(actor or ""), str(reason or "")),
    )
    # Auto-block existing accounts that used this IP
    for row in conn.execute("SELECT DISTINCT user_id FROM user_login_ips WHERE ip = ?", (ip,)).fetchall():
        set_user_account_blocked(conn, int(row["user_id"]), True, reason or "user_ip_blocked:" + ip)
    audit(conn, "admin.block_user_ip", {"ip": ip, "reason": reason, "actor": actor})


def unblock_user_ip(conn, ip: str, actor: str = "") -> None:
    ip = str(ip or "").strip()
    if not ip:
        return
    conn.execute("DELETE FROM blocked_user_ips WHERE ip = ?", (ip,))
    audit(conn, "admin.unblock_user_ip", {"ip": ip, "actor": actor})


def record_user_ip(conn, user_id: int, ip: str, revive: bool = False) -> None:
    try:
        uid = int(user_id or 0)
    except Exception:
        return
    ip = str(ip or "").strip().split(",")[0].strip()
    if not uid or not ip or ip in ("0.0.0.0",):
        return
    now = _now_ms()
    try:
        conn.execute("ALTER TABLE user_login_ips ADD COLUMN revoked INTEGER DEFAULT 0")
    except Exception:
        pass
    if not revive:
        try:
            row = conn.execute(
                "SELECT COALESCE(revoked, 0) FROM user_login_ips WHERE user_id = ? AND ip = ?",
                (uid, ip),
            ).fetchone()
            if row and int((row[0] if not hasattr(row, "keys") else row[0]) or 0):
                return
        except Exception:
            pass
    try:
        conn.execute(
            """INSERT INTO user_login_ips (user_id, ip, first_seen, last_seen, hits, revoked)
               VALUES (?, ?, ?, ?, 1, 0)
               ON CONFLICT(user_id, ip) DO UPDATE SET
                 last_seen = excluded.last_seen,
                 hits = COALESCE(user_login_ips.hits, 0) + 1""",
            (uid, ip, now, now),
        )
    except Exception:
        conn.execute(
            """INSERT INTO user_login_ips (user_id, ip, first_seen, last_seen, hits)
               VALUES (?, ?, ?, ?, 1)
               ON CONFLICT(user_id, ip) DO UPDATE SET
                 last_seen = excluded.last_seen,
                 hits = COALESCE(user_login_ips.hits, 0) + 1""",
            (uid, ip, now, now),
        )
    if revive:
        try:
            conn.execute(
                "UPDATE user_login_ips SET revoked = 0, last_seen = ? WHERE user_id = ? AND ip = ?",
                (now, uid, ip),
            )
        except Exception:
            pass
    # Warm GeoIP cache for activity log / sessions (same provider)
    try:
        ensure_ip_geo(conn, ip)
    except Exception as exc:
        print("record_user_ip geo", ip, type(exc).__name__, exc)


def user_session_revoked(conn, user_id: int, ip: str) -> bool:
    try:
        uid = int(user_id or 0)
    except Exception:
        return False
    ip = str(ip or "").strip().split(",")[0].strip()
    if not uid or not ip:
        return False
    try:
        row = conn.execute(
            "SELECT COALESCE(revoked, 0) FROM user_login_ips WHERE user_id = ? AND ip = ?",
            (uid, ip),
        ).fetchone()
        return bool(row and int(row[0] or 0))
    except Exception:
        return False


def revoke_user_session(conn, user_id: int, ip: str) -> bool:
    try:
        uid = int(user_id or 0)
    except Exception:
        return False
    ip = str(ip or "").strip().split(",")[0].strip()
    if not uid or not ip:
        return False
    try:
        conn.execute("ALTER TABLE user_login_ips ADD COLUMN revoked INTEGER DEFAULT 0")
    except Exception:
        pass
    try:
        cur = conn.execute(
            "UPDATE user_login_ips SET revoked = 1 WHERE user_id = ? AND ip = ?",
            (uid, ip),
        )
        if int(cur.rowcount or 0) <= 0:
            now = _now_ms()
            conn.execute(
                """INSERT INTO user_login_ips (user_id, ip, first_seen, last_seen, hits, revoked)
                   VALUES (?, ?, ?, ?, 0, 1)
                   ON CONFLICT(user_id, ip) DO UPDATE SET revoked = 1""",
                (uid, ip, now, now),
            )
        return True
    except Exception as exc:
        print("revoke_user_session failed", type(exc).__name__, exc)
        return False


def is_server_ip_blocked(conn, server_ip: str) -> bool:
    server_ip = str(server_ip or "").strip()
    if not server_ip:
        return False
    row = conn.execute(
        "SELECT server_ip FROM blocked_server_ips WHERE server_ip = ?",
        (server_ip,),
    ).fetchone()
    return bool(row)


def block_server_ip(conn, server_ip: str, actor: str = "", reason: str = "") -> None:
    server_ip = str(server_ip or "").strip()
    if not server_ip:
        return
    conn.execute(
        """INSERT INTO blocked_server_ips (server_ip, blocked_at, blocked_by, reason)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(server_ip) DO UPDATE SET
             blocked_at = excluded.blocked_at,
             blocked_by = excluded.blocked_by,
             reason = excluded.reason""",
        (server_ip, _now_ms(), str(actor or ""), str(reason or "")),
    )
    audit(conn, "admin.block_server_ip", {"server_ip": server_ip, "reason": reason})


def unblock_server_ip(conn, server_ip: str, actor: str = "") -> None:
    server_ip = str(server_ip or "").strip()
    if not server_ip:
        return
    conn.execute("DELETE FROM blocked_server_ips WHERE server_ip = ?", (server_ip,))
    audit(conn, "admin.unblock_server_ip", {"server_ip": server_ip, "actor": actor})


def enforce_blocked_server_ip(conn, project_id: int, server_ip: str) -> bool:
    """If IP is globally blocked, block the project. Returns True when blocked."""
    server_ip = str(server_ip or "").strip()
    if not server_ip or not is_server_ip_blocked(conn, server_ip):
        return False
    pid = int(project_id or 0)
    if pid:
        try:
            conn.execute(
                "UPDATE project SET blocked = 1, admin_frozen = 1 WHERE id = ?",
                (pid,),
            )
            freeze_project(conn, pid, "blocked_server_ip:" + server_ip)
        except Exception:
            pass
        audit(conn, "admin.auto_block_project", {"project_id": pid, "server_ip": server_ip})
    return True


def project_admin_flags(conn, project_id: int) -> dict:
    row = conn.execute("SELECT blocked, admin_frozen FROM project WHERE id = ?", (int(project_id),)).fetchone()
    if not row:
        return {"blocked": False, "admin_frozen": False}
    return {
        "blocked": bool(int(row["blocked"] or 0)),
        "admin_frozen": bool(int(row["admin_frozen"] or 0)),
    }

