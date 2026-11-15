"""Steam OpenID and Discord OAuth helpers for the RustApp auth."""
from __future__ import annotations

import json
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

import features

STEAM_OPENID = "https://steamcommunity.com/openid/login"
DISCORD_TOKEN_URL = "https://discord.com/api/oauth2/token"
DISCORD_USER_URL = "https://discord.com/api/users/@me"
DISCORD_AUTHORIZE_URL = "https://discord.com/api/oauth2/authorize"
PLACEHOLDER_AVATAR = "/local/image-1024.jpg?v=5&https=1"
OAUTH_QUERY_TTL = 600


def discord_avatar_url(discord_id: str, avatar_hash: str = "") -> str:
    did = str(discord_id or "").strip()
    hashed = str(avatar_hash or "").strip()
    if did and hashed and hashed not in ("None", "null") and not hashed.startswith("/"):
        ext = "gif" if hashed.startswith("a_") else "png"
        return f"https://cdn.discordapp.com/avatars/{did}/{hashed}.{ext}?size=128"
    try:
        idx = (int(did) >> 22) % 6
    except Exception:
        idx = 0
    return f"https://cdn.discordapp.com/embed/avatars/{idx}.png"


def discord_client_id() -> str:
    return str(os.environ.get("DISCORD_CLIENT_ID") or "").strip()


def discord_client_secret() -> str:
    return str(os.environ.get("DISCORD_CLIENT_SECRET") or "").strip()


def discord_configured() -> bool:
    return bool(discord_client_id() and discord_client_secret())


def discord_authorize_ready() -> bool:
    return bool(discord_client_id())


def google_client_id() -> str:
    return str(os.environ.get("GOOGLE_CLIENT_ID") or "").strip()


def google_client_secret() -> str:
    return str(os.environ.get("GOOGLE_CLIENT_SECRET") or "").strip()


def google_configured() -> bool:
    return bool(google_client_id() and google_client_secret())


def steam_api_key() -> str:
    return str(os.environ.get("STEAM_WEB_API_KEY") or "").strip()


def public_base(scheme: str, host: str) -> str:
    host = str(host or "127.0.0.1:8081").strip()
    scheme = str(scheme or "http").strip().lower()
    if scheme not in ("http", "https"):
        scheme = "https"
    if "localhost" in host or host.startswith("127.0.0.1"):
        scheme = "http"
    return f"{scheme}://{host}"


def discord_callback_url(scheme: str, host: str) -> str:
    override = str(os.environ.get("DISCORD_REDIRECT_URI") or "").strip()
    host_l = str(host or "").split(":")[0].lower()
    if override and "localhost" not in host_l and not host_l.startswith("127."):
        return override
    return public_base(scheme, host) + "/auth/discord/callback"


def _parse_query(query: str) -> dict[str, str]:
    raw = str(query or "").strip().lstrip("?")
    if not raw:
        return {}
    parsed = urllib.parse.parse_qs(raw, keep_blank_values=True)
    out: dict[str, str] = {}
    for key, vals in parsed.items():
        if vals:
            out[str(key)] = str(vals[0])
    return out


def _encode_query(params: dict[str, str]) -> str:
    return urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})


def sign_oauth_state(payload: dict) -> str:
    body = features._b64url_json(dict(payload))
    sig = features.hmac_hex(f"oauth-state:{body}")
    return f"{body}.{sig}"


def verify_oauth_state(state: str) -> dict | None:
    raw = str(state or "").strip()
    if not raw or raw.count(".") < 1:
        return None
    body, sig = raw.rsplit(".", 1)
    expected = features.hmac_hex(f"oauth-state:{body}")
    if not secrets.compare_digest(sig, expected):
        return None
    try:
        payload = json.loads(features._b64url_decode(body).decode("utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    exp = int(payload.get("exp") or 0)
    if exp and exp < int(time.time()) - 30:
        return None
    return payload


def pack_provider_query(provider: str, data: dict) -> str:
    payload = {
        "provider": str(provider or ""),
        "exp": int(time.time()) + OAUTH_QUERY_TTL,
        **{k: v for k, v in data.items() if v is not None},
    }
    body = features._b64url_json(payload)
    sig = features.hmac_hex(f"oauth-query:{body}")
    return _encode_query({"oauth": body, "sig": sig})


def unpack_provider_query(query: str, provider: str) -> dict | None:
    params = _parse_query(query)
    body = params.get("oauth") or ""
    sig = params.get("sig") or ""
    if not body or not sig:
        return None
    expected = features.hmac_hex(f"oauth-query:{body}")
    if not secrets.compare_digest(sig, expected):
        return None
    try:
        payload = json.loads(features._b64url_decode(body).decode("utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    if str(payload.get("provider") or "") != str(provider):
        return None
    exp = int(payload.get("exp") or 0)
    if exp and exp < int(time.time()) - 30:
        return None
    return payload


def steam_openid_link(return_url: str, realm: str) -> str:
    params = {
        "openid.ns": "http://specs.openid.net/auth/2.0",
        "openid.mode": "checkid_setup",
        "openid.return_to": return_url,
        "openid.realm": realm,
        "openid.identity": "http://specs.openid.net/auth/2.0/identifier_select",
        "openid.claimed_id": "http://specs.openid.net/auth/2.0/identifier_select",
    }
    return STEAM_OPENID + "?" + _encode_query(params)


def verify_steam_openid(query: str) -> dict | None:
    params = _parse_query(query)
    if not params:
        return None
    if params.get("openid.mode") != "id_res":
        return None
    claimed = str(params.get("openid.claimed_id") or "")
    if "steamcommunity.com/openid/id/" not in claimed:
        return None
    steam_id = claimed.rstrip("/").split("/")[-1]
    if not steam_id.isdigit() or len(steam_id) != 17:
        return None
    verify = dict(params)
    verify["openid.mode"] = "check_authentication"
    data = _encode_query(verify).encode("utf-8")
    req = urllib.request.Request(
        STEAM_OPENID,
        data=data,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "RustApp/2.1"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
    except Exception as exc:
        print("steam openid verify failed", type(exc).__name__, exc)
        return None
    if "is_valid:true" not in body.replace(" ", "").lower():
        print("steam openid invalid response", body[:200])
        return None
    profile = steam_profile(steam_id)
    return {
        "steam_id": steam_id,
        "steam_name": profile.get("steam_name") or steam_id,
        "steam_avatar": profile.get("steam_avatar") or PLACEHOLDER_AVATAR,
    }


def steam_profile(steam_id: str) -> dict:
    sid = str(steam_id or "").strip()
    if not sid:
        return {}
    api_key = str(os.environ.get("STEAM_WEB_API_KEY") or "").strip()
    if not api_key:
        return {
            "steam_id": sid,
            "steam_name": sid,
            "steam_avatar": PLACEHOLDER_AVATAR,
            "personaname": sid,
            "profileurl": f"https://steamcommunity.com/profiles/{sid}",
            "avatarfull": PLACEHOLDER_AVATAR,
        }
    url = (
        "https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v0002/?"
        + urllib.parse.urlencode({"key": api_key, "steamids": sid})
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "RustApp/2.1"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8") or "{}")
        players = ((data.get("response") or {}).get("players") or [])
        if players:
            p = players[0]
            # personaname = Steam display name (not RustCheck username, not Rust nick)
            persona = str(p.get("personaname") or "").strip() or sid
            avatar = str(p.get("avatarfull") or p.get("avatarmedium") or p.get("avatar") or "")
            profile_url = str(p.get("profileurl") or "").strip() or f"https://steamcommunity.com/profiles/{sid}"
            return {
                "steam_id": sid,
                "steam_name": persona,
                "steam_avatar": avatar or PLACEHOLDER_AVATAR,
                "personaname": persona,
                "profileurl": profile_url,
                "avatarfull": avatar or PLACEHOLDER_AVATAR,
                "avatarmedium": str(p.get("avatarmedium") or avatar or PLACEHOLDER_AVATAR),
            }
    except Exception as exc:
        print("steam profile fetch failed", type(exc).__name__, exc)
    return {
        "steam_id": sid,
        "steam_name": sid,
        "steam_avatar": PLACEHOLDER_AVATAR,
        "personaname": sid,
        "profileurl": f"https://steamcommunity.com/profiles/{sid}",
        "avatarfull": PLACEHOLDER_AVATAR,
    }


def discord_authorize_link(return_url: str, callback_url: str, uid: int = 0) -> str:
    try:
        uid_n = int(uid or 0)
    except Exception:
        uid_n = 0
    state = sign_oauth_state(
        {
            "return_url": return_url,
            "uid": uid_n,
            "nonce": secrets.token_hex(8),
            "exp": int(time.time()) + OAUTH_QUERY_TTL,
        }
    )
    params = {
        "client_id": discord_client_id(),
        "redirect_uri": callback_url,
        "response_type": "code",
        "scope": "identify",
        "state": state,
        "prompt": "consent",
    }
    return DISCORD_AUTHORIZE_URL + "?" + _encode_query(params)


def discord_exchange_code(code: str, callback_url: str) -> dict | None:
    if not discord_configured():
        return None
    payload = urllib.parse.urlencode(
        {
            "client_id": discord_client_id(),
            "client_secret": discord_client_secret(),
            "grant_type": "authorization_code",
            "code": str(code or ""),
            "redirect_uri": callback_url,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        DISCORD_TOKEN_URL,
        data=payload,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "RustApp/2.1"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            token_data = json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        print("discord token exchange failed", exc.code, exc.read()[:200])
        return None
    except Exception as exc:
        print("discord token exchange failed", type(exc).__name__, exc)
        return None
    access = str(token_data.get("access_token") or "")
    if not access:
        return None
    user_req = urllib.request.Request(
        DISCORD_USER_URL,
        headers={"Authorization": f"Bearer {access}", "User-Agent": "RustApp/2.1"},
    )
    try:
        with urllib.request.urlopen(user_req, timeout=15) as resp:
            user = json.loads(resp.read().decode("utf-8") or "{}")
    except Exception as exc:
        print("discord user fetch failed", type(exc).__name__, exc)
        return None
    if not isinstance(user, dict) or not user.get("id"):
        return None
    discord_id = str(user.get("id"))
    handle = str(user.get("username") or "").strip()
    global_name = str(user.get("global_name") or "").strip()
    username = global_name or handle or discord_id
    avatar = discord_avatar_url(discord_id, user.get("avatar"))
    return {
        "discord_id": discord_id,
        "discord_name": username,
        "discord_avatar": avatar,
        "discord_username": handle,
        "discord_global_name": global_name,
    }


def verify_discord_query(query: str) -> dict | None:
    packed = unpack_provider_query(query, "discord")
    if not packed:
        return None
    discord_id = str(packed.get("discord_id") or "")
    if not discord_id:
        return None
    did = str(packed.get("discord_id") or "")
    return {
        "discord_id": did,
        "discord_name": str(packed.get("discord_name") or packed.get("discord_global_name") or packed.get("discord_username") or did),
        "discord_avatar": str(packed.get("discord_avatar") or discord_avatar_url(did, "")),
        "discord_username": str(packed.get("discord_username") or ""),
        "discord_global_name": str(packed.get("discord_global_name") or packed.get("discord_name") or ""),
    }


def discord_callback_html(query: str, return_url: str = "") -> bytes:
    safe = json.dumps(query)
    dest = json.dumps(str(return_url or "/"))
    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>RustApp</title></head><body>
<script>
var dest = {dest};
try {{
  if (window.opener) {{
    window.opener.postMessage(JSON.stringify({{query: {safe}}}), "*");
    window.close();
  }} else if (dest) {{
    location.replace(dest);
  }} else {{
    window.close();
  }}
}} catch (e) {{
  try {{ if (dest) location.replace(dest); }} catch (e2) {{}}
}}
</script></body></html>"""
    return html.encode("utf-8")


def auth_login_denied(conn, user: dict | None, client_ip: str = "") -> dict | None:
    if not user:
        return {"message": "password.missmatch", "code": "password.missmatch"}
    uid = int(user.get("id") or 0)
    if features.user_account_blocked(conn, uid):
        return {"message": "account.blocked", "code": "account.blocked", "title": "Аккаунт заблокирован"}
    ip = str(client_ip or "").strip()
    if ip and features.is_user_ip_blocked(conn, ip):
        if not features.user_account_blocked(conn, uid):
            features.set_user_account_blocked(conn, uid, True, "login_from_blocked_user_ip")
        return {"message": "account.blocked", "code": "account.blocked", "title": "Аккаунт заблокирован"}
    if features.has_blocked_owned_project(conn, uid):
        return {"message": "account.blocked", "code": "account.blocked"}
    if ip and features.is_server_ip_blocked(conn, ip):
        return {"message": "ip.blocked", "code": "ip.blocked"}
    return features.staff_guard(conn, user)


def find_user_by_steam(conn, steam_id: str) -> dict | None:
    sid = str(steam_id or "").strip()
    if not sid:
        return None
    row = conn.execute(
        "SELECT * FROM users WHERE steam_id = ? AND steam_id != '' LIMIT 1",
        (sid,),
    ).fetchone()
    return dict(row) if row else None


def find_user_by_discord(conn, discord_id: str) -> dict | None:
    did = str(discord_id or "").strip()
    if not did:
        return None
    row = conn.execute(
        "SELECT * FROM users WHERE discord_id = ? AND discord_id != '' LIMIT 1",
        (did,),
    ).fetchone()
    return dict(row) if row else None


def _sanitize_tag(base: str) -> str:
    tag = str(base or "user").strip().lower().replace(" ", "_")
    tag = "".join(ch for ch in tag if ch.isalnum() or ch == "_").strip("_")
    return (tag or "user")[:24]


def unique_tag(conn, base: str) -> str:
    tag = _sanitize_tag(base)
    if not conn.execute("SELECT 1 FROM users WHERE lower(tag) = lower(?) AND tag != ''", (tag,)).fetchone():
        return tag
    for i in range(2, 1000):
        candidate = f"{tag}_{i}"[:24]
        if not conn.execute("SELECT 1 FROM users WHERE lower(tag) = lower(?)", (candidate,)).fetchone():
            return candidate
    return f"user_{secrets.token_hex(3)}"


def create_oauth_user(
    conn,
    *,
    email: str,
    name: str,
    tag: str,
    steam_id: str = "",
    discord_id: str = "",
    google_id: str = "",
    avatar: str = "",
) -> dict | None:
    email = str(email or "").lower().strip()
    name = str(name or "user").strip() or "user"
    tag = _sanitize_tag(tag or name)
    tag = unique_tag(conn, tag)
    if steam_id and find_user_by_steam(conn, steam_id):
        return None
    if discord_id and find_user_by_discord(conn, discord_id):
        return None
    if google_id and find_user_by_google(conn, google_id):
        return None
    if email and conn.execute("SELECT id FROM users WHERE lower(email) = ?", (email,)).fetchone():
        return None
    try:
        conn.execute(
            """INSERT INTO users (email, name, tag, bio, password_hash, steam_id, discord_id, google_id, role, is_admin, created_at)
               VALUES (?, ?, ?, '', '', ?, ?, ?, 'owner', 1, ?)""",
            (email, name, tag, str(steam_id or ""), str(discord_id or ""), str(google_id or ""), features._now_ms()),
        )
    except Exception:
        conn.execute(
            """INSERT INTO users (email, name, tag, bio, password_hash, steam_id, discord_id, role, is_admin, created_at)
               VALUES (?, ?, ?, '', '', ?, ?, 'owner', 1, ?)""",
            (email, name, tag, str(steam_id or ""), str(discord_id or ""), features._now_ms()),
        )
        if google_id:
            conn.execute("UPDATE users SET google_id = ? WHERE id = last_insert_rowid()", (str(google_id),))
    row = conn.execute("SELECT * FROM users WHERE id = last_insert_rowid()").fetchone()
    if not row:
        return None
    user = dict(row)
    uid = int(user.get("id") or 0)
    if avatar and uid:
        key = f"client_avatar_{uid}"
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(avatar)),
        )
    features.audit(conn, "auth.sign_up", {
        "email": email, "steam_id": steam_id, "discord_id": discord_id, "google_id": google_id,
    })
    return user


def link_discord_to_user(conn, user: dict, discord_id: str, discord_name: str = "", avatar: str = "", username: str = "") -> dict | None:
    did = str(discord_id or "").strip()
    if not did:
        return None
    other = find_user_by_discord(conn, did)
    if other and int(other.get("id") or 0) != int(user.get("id") or 0):
        return None
    uid = int(user.get("id") or 0)
    try:
        conn.execute("ALTER TABLE users ADD COLUMN discord_id TEXT DEFAULT ''")
    except Exception:
        pass
    conn.execute("UPDATE users SET discord_id = ? WHERE id = ?", (did, uid))
    if uid:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (f"client_discord_name_{uid}", str(discord_name or username or did)),
        )
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (f"oauth_discord_id_{uid}", did),
        )
        handle = str(username or "").strip()
        if handle:
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (f"client_discord_username_{uid}", handle),
            )
        av = str(avatar or "").strip()
        if "cdn.discordapp.com" not in av:
            av = discord_avatar_url(did, "")
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (f"client_discord_avatar_{uid}", av),
        )
    updated = features.user_by_id(conn, uid)
    return updated


def discord_client_payload(discord_id: str, discord_name: str = "", avatar: str = "", username: str = "") -> dict:
    did = str(discord_id or "")
    handle = str(username or "").strip()
    name = str(discord_name or handle or did)
    av = str(avatar or "").strip()
    if not av or av == PLACEHOLDER_AVATAR or "/local/image-" in av:
        av = discord_avatar_url(did, "")
    return {
        "id": did,
        "user_id": did,
        "account_id": did,
        "discord_id": did,
        "discord_name": name,
        "username": handle or name,
        "global_name": name,
        "display_name": name,
        "name": name,
        "avatar": av,
        "discord_avatar": av,
        "avatarfull": av,
        "avatarmedium": av,
        "personaname": name,
        "connected": True,
        "is_connected": True,
        "available": True,
        "status": "connected",
    }


def discord_profile_for_user(conn, user: dict) -> dict | None:
    did = str((user or {}).get("discord_id") or "").strip()
    uid = int((user or {}).get("id") or 0)
    if uid and not did:
        try:
            brow = conn.execute("SELECT value FROM settings WHERE key = ?", (f"oauth_discord_id_{uid}",)).fetchone()
            if brow and brow["value"]:
                did = str(brow["value"]).strip()
                if did:
                    try:
                        conn.execute(
                            "UPDATE users SET discord_id = ? WHERE id = ? AND (discord_id IS NULL OR discord_id = '')",
                            (did, uid),
                        )
                    except Exception:
                        pass
        except Exception:
            pass
    if not did:
        return None
    name = ""
    handle = ""
    avatar = ""
    if uid:
        nrow = conn.execute("SELECT value FROM settings WHERE key = ?", (f"client_discord_name_{uid}",)).fetchone()
        if nrow and nrow["value"]:
            name = str(nrow["value"])
        hrow = conn.execute("SELECT value FROM settings WHERE key = ?", (f"client_discord_username_{uid}",)).fetchone()
        if hrow and hrow["value"]:
            handle = str(hrow["value"])
        arow = conn.execute("SELECT value FROM settings WHERE key = ?", (f"client_discord_avatar_{uid}",)).fetchone()
        if arow and arow["value"]:
            avatar = str(arow["value"])
    if not name:
        name = handle or did
    if not avatar or avatar == PLACEHOLDER_AVATAR or "/local/image-" in avatar:
        avatar = discord_avatar_url(did, "")
    return discord_client_payload(did, name, avatar, handle)


def link_steam_to_user(conn, user: dict, steam_id: str, steam_name: str = "", avatar: str = "") -> dict | None:
    sid = str(steam_id or "").strip()
    if not sid:
        return None
    other = find_user_by_steam(conn, sid)
    if other and int(other.get("id") or 0) != int(user.get("id") or 0):
        return None
    conn.execute("UPDATE users SET steam_id = ? WHERE id = ?", (sid, int(user.get("id") or 0)))
    uid = int(user.get("id") or 0)
    if uid:
        # Store Steam profile separately — do NOT overwrite RustCheck username/avatar
        if steam_name:
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (f"client_steam_name_{uid}", str(steam_name)),
            )
        if avatar:
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (f"client_steam_avatar_{uid}", str(avatar)),
            )
    updated = features.user_by_id(conn, uid)
    return updated


def steam_https_avatar(url: str) -> str:
    text = str(url or "").strip()
    if not text:
        return PLACEHOLDER_AVATAR
    text = text.replace("http://", "https://")
    text = text.replace("https://cdn.akamai.steamstatic.com", "https://avatars.steamstatic.com")
    text = text.replace("https://steamcdn-a.akamaihd.net", "https://avatars.steamstatic.com")
    return text


def _usable_steam_name(name: str, steam_id: str = "") -> str:
    text = str(name or "").strip()
    sid = str(steam_id or "").strip()
    if not text or text in (".", "-", "—"):
        return ""
    if sid and text == sid:
        return ""
    if text.isdigit() and len(text) >= 16:
        return ""
    return text


def steam_profile_for_user(conn, user: dict, allow_network: bool = True) -> dict | None:
    sid = str((user or {}).get("steam_id") or "").strip()
    if not sid:
        return None
    uid = int((user or {}).get("id") or 0)
    name = ""
    avatar = PLACEHOLDER_AVATAR
    fetched_at = 0
    if uid:
        nrow = conn.execute("SELECT value FROM settings WHERE key = ?", (f"client_steam_name_{uid}",)).fetchone()
        if nrow and nrow["value"]:
            name = _usable_steam_name(nrow["value"], sid)
        arow = conn.execute("SELECT value FROM settings WHERE key = ?", (f"client_steam_avatar_{uid}",)).fetchone()
        if arow and arow["value"]:
            avatar = steam_https_avatar(arow["value"])
        trow = conn.execute("SELECT value FROM settings WHERE key = ?", (f"client_steam_fetched_{uid}",)).fetchone()
        if trow and trow["value"]:
            try:
                fetched_at = int(trow["value"])
            except Exception:
                fetched_at = 0
    if (not name) or avatar == PLACEHOLDER_AVATAR or "image-1024" in avatar:
        try:
            cached = features.read_cache(conn, "steam_cache", "steam_id", sid)
        except Exception:
            cached = None
        if isinstance(cached, dict):
            persona = _usable_steam_name(cached.get("personaname") or cached.get("steam_name") or "", sid)
            if persona:
                name = persona
            av = steam_https_avatar(cached.get("avatarfull") or cached.get("avatar") or cached.get("steam_avatar") or "")
            if av and av != PLACEHOLDER_AVATAR and "image-1024" not in av:
                avatar = av
    if avatar == PLACEHOLDER_AVATAR or "image-1024" in str(avatar):
        try:
            local = features.UPLOADS / f"steam-{sid}.jpg"
            if local.exists() and local.stat().st_size > 200:
                avatar = f"/uploads/{local.name}?v={int(local.stat().st_mtime)}"
        except Exception:
            pass
    stale = (int(time.time()) - fetched_at) > 3600
    need_fetch = allow_network and (stale or not name or avatar == PLACEHOLDER_AVATAR or "image-1024" in avatar)
    fresh = steam_profile(sid) if need_fetch else {}
    if not isinstance(fresh, dict):
        fresh = {}
    fresh_name = _usable_steam_name(fresh.get("steam_name") or fresh.get("personaname") or "", sid)
    if fresh_name:
        name = fresh_name
        if uid:
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (f"client_steam_name_{uid}", name),
            )
    if fresh.get("steam_avatar") and fresh["steam_avatar"] != PLACEHOLDER_AVATAR:
        avatar = steam_https_avatar(fresh["steam_avatar"])
        if uid:
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (f"client_steam_avatar_{uid}", avatar),
            )
    if need_fetch and uid and fresh:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (f"client_steam_fetched_{uid}", str(int(time.time()))),
        )
    display = name or "Steam"
    return steam_client_payload(
        sid,
        display,
        avatar,
        profile_url=str(fresh.get("profileurl") or "") or f"https://steamcommunity.com/profiles/{sid}",
        personaname=display,
    )


def steam_client_payload(
    steam_id: str,
    steam_name: str = "",
    avatar: str = "",
    profile_url: str = "",
    personaname: str = "",
) -> dict:
    sid = str(steam_id or "")
    display = _usable_steam_name(personaname or steam_name, sid) or str(steam_name or "Steam").strip() or "Steam"
    av = steam_https_avatar(avatar or PLACEHOLDER_AVATAR)
    url = str(profile_url or "").strip() or (f"https://steamcommunity.com/profiles/{sid}" if sid else "")
    return {
        "steam_id": sid,
        "steamid": sid,
        "steam_name": display,
        "name": display,
        "personaname": display,
        "avatar": av,
        "steam_avatar": av,
        "avatarfull": av,
        "avatarmedium": av,
        "profileurl": url,
        "profile_url": url,
        "url": url,
        "connected": True,
    }


def issue_login_token(user: dict) -> str:
    return features.make_access_token(user)


GOOGLE_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
GOOGLE_TOKENINFO_URL = "https://oauth2.googleapis.com/tokeninfo"


def google_callback_url(scheme: str, host: str) -> str:
    override = str(os.environ.get("GOOGLE_REDIRECT_URI") or "").strip()
    if override:
        return override
    return public_base(scheme, host) + "/auth/google/callback"


def google_authorize_link(return_url: str, callback_url: str) -> str:
    state = sign_oauth_state(
        {
            "return_url": return_url,
            "nonce": secrets.token_hex(8),
            "exp": int(time.time()) + OAUTH_QUERY_TTL,
        }
    )
    params = {
        "client_id": google_client_id(),
        "redirect_uri": callback_url,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
        "include_granted_scopes": "true",
    }
    return GOOGLE_AUTHORIZE_URL + "?" + _encode_query(params)


def _google_profile_from_userinfo(user: dict) -> dict | None:
    if not isinstance(user, dict):
        return None
    gid = str(user.get("sub") or user.get("id") or "").strip()
    if not gid:
        return None
    email = str(user.get("email") or "").strip().lower()
    name = str(user.get("name") or user.get("given_name") or email.split("@")[0] or gid).strip()
    avatar = str(user.get("picture") or PLACEHOLDER_AVATAR)
    return {
        "google_id": gid,
        "google_email": email,
        "google_name": name,
        "google_avatar": avatar,
        "email": email,
        "name": name,
        "avatar": avatar,
        "email_verified": bool(user.get("email_verified") or user.get("verified_email")),
    }


def google_exchange_code(code: str, callback_url: str) -> dict | None:
    if not google_configured():
        return None
    payload = urllib.parse.urlencode(
        {
            "client_id": google_client_id(),
            "client_secret": google_client_secret(),
            "grant_type": "authorization_code",
            "code": str(code or ""),
            "redirect_uri": callback_url,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        GOOGLE_TOKEN_URL,
        data=payload,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "RustApp/2.1"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            token_data = json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        print("google token exchange failed", exc.code, exc.read()[:200])
        return None
    except Exception as exc:
        print("google token exchange failed", type(exc).__name__, exc)
        return None
    access = str(token_data.get("access_token") or "")
    id_token = str(token_data.get("id_token") or "")
    profile = None
    if access:
        user_req = urllib.request.Request(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access}", "User-Agent": "RustApp/2.1"},
        )
        try:
            with urllib.request.urlopen(user_req, timeout=15) as resp:
                profile = _google_profile_from_userinfo(json.loads(resp.read().decode("utf-8") or "{}"))
        except Exception as exc:
            print("google userinfo failed", type(exc).__name__, exc)
    if not profile and id_token:
        profile = google_verify_id_token(id_token)
    return profile


def google_verify_id_token(credential: str) -> dict | None:
    raw = str(credential or "").strip()
    if not raw or raw.count(".") != 2:
        return None
    cid = google_client_id()
    url = GOOGLE_TOKENINFO_URL + "?" + urllib.parse.urlencode({"id_token": raw})
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "RustApp/2.1"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8") or "{}")
    except Exception as exc:
        print("google id_token verify failed", type(exc).__name__, exc)
        return None
    aud = str(data.get("aud") or "")
    if cid and aud != cid:
        print("google id_token aud mismatch")
        return None
    return _google_profile_from_userinfo(data)


def google_callback_html(query: str) -> bytes:
    return discord_callback_html(query)


def verify_google_query(query: str) -> dict | None:
    packed = unpack_provider_query(query, "google")
    if packed:
        gid = str(packed.get("google_id") or "")
        if gid:
            return {
                "google_id": gid,
                "google_email": str(packed.get("google_email") or packed.get("email") or ""),
                "google_name": str(packed.get("google_name") or packed.get("name") or gid),
                "google_avatar": str(packed.get("google_avatar") or packed.get("avatar") or PLACEHOLDER_AVATAR),
                "email": str(packed.get("email") or packed.get("google_email") or ""),
                "name": str(packed.get("name") or packed.get("google_name") or gid),
                "avatar": str(packed.get("avatar") or packed.get("google_avatar") or PLACEHOLDER_AVATAR),
            }
    # GIS / vue3-google-login posts a raw credential JWT
    cred = ""
    params = _parse_query(query)
    cred = str(params.get("credential") or params.get("id_token") or "").strip()
    if not cred and query and query.count(".") == 2 and " " not in query and "oauth=" not in query:
        cred = query.strip()
    if cred:
        return google_verify_id_token(cred)
    return None


def find_user_by_google(conn, google_id: str) -> dict | None:
    gid = str(google_id or "").strip()
    if not gid:
        return None
    row = conn.execute(
        "SELECT * FROM users WHERE google_id = ? AND google_id != '' LIMIT 1",
        (gid,),
    ).fetchone()
    return dict(row) if row else None


def find_user_by_google_email(conn, email: str) -> dict | None:
    mail = str(email or "").strip().lower()
    if not mail or "@" not in mail:
        return None
    row = conn.execute("SELECT * FROM users WHERE lower(email) = ?", (mail,)).fetchone()
    return dict(row) if row else None


def link_google_to_user(conn, user: dict, google_id: str, google_name: str = "", avatar: str = "", email: str = "") -> dict | None:
    gid = str(google_id or "").strip()
    if not gid:
        return None
    other = find_user_by_google(conn, gid)
    if other and int(other.get("id") or 0) != int(user.get("id") or 0):
        return None
    conn.execute("UPDATE users SET google_id = ? WHERE id = ?", (gid, int(user.get("id") or 0)))
    uid = int(user.get("id") or 0)
    if uid:
        if google_name:
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (f"client_google_name_{uid}", str(google_name)),
            )
        if avatar:
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (f"client_google_avatar_{uid}", str(avatar)),
            )
    updated = features.user_by_id(conn, uid)
    return updated


def google_profile_for_user(conn, user: dict) -> dict | None:
    gid = str((user or {}).get("google_id") or "").strip()
    if not gid:
        return None
    uid = int((user or {}).get("id") or 0)
    name = str((user or {}).get("name") or gid)
    avatar = PLACEHOLDER_AVATAR
    if uid:
        nrow = conn.execute("SELECT value FROM settings WHERE key = ?", (f"client_google_name_{uid}",)).fetchone()
        if nrow and nrow["value"]:
            name = str(nrow["value"])
        arow = conn.execute("SELECT value FROM settings WHERE key = ?", (f"client_google_avatar_{uid}",)).fetchone()
        if arow and arow["value"]:
            avatar = str(arow["value"])
    return {
        "google_id": gid,
        "google_name": name,
        "name": name,
        "avatar": avatar,
        "google_avatar": avatar,
    }


def google_public_config() -> dict:
    cid = google_client_id()
    return {
        "enabled": google_configured(),
        "client_id": cid,
        "configured": google_configured(),
    }
