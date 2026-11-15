#!/usr/bin/env python3
"""Idempotent demo data for CRYSAL RUST so the panel can be configured."""
from __future__ import annotations

import json
import struct
import time
import uuid
import zlib
from pathlib import Path

import features
import server

PID = 1
STAFF_EMAIL = "staff@test.local"
STAFF_PASS = "Test1234"
STAFF_NAME = "TestStaff"
TOKEN_MARK = "testdemoseed"

PLAYERS = [
    ("76561198200100001", "TestPlayer", "185.12.34.10"),
    ("76561198200100002", "TestReporter", "185.12.34.11"),
    ("76561198200100003", "TestChecked", "185.12.34.12"),
    ("76561198200100004", "TestArtist", "185.12.34.13"),
    ("76561198200100005", "TestAlert", "185.12.34.14"),
    ("76561198200100006", "TestBag", "185.12.34.15"),
    ("76561198200100007", "TestMuted", "185.12.34.16"),
    ("76561198200100008", "TestBanned", "185.12.34.17"),
]
STEAMS = [p[0] for p in PLAYERS]


def png_bytes(w=64, h=64, rgb=(40, 140, 220)) -> bytes:
    r, g, b = rgb
    raw = b""
    for _y in range(h):
        raw += b"\x00" + bytes([r, g, b, 255]) * w

    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def wipe_old(conn) -> None:
    marks = ",".join("?" * len(STEAMS))
    for sql in (
        f"DELETE FROM online_players WHERE steam_id IN ({marks})",
        f"DELETE FROM player_sessions WHERE steam_id IN ({marks})",
        f"DELETE FROM player_ips WHERE steam_id IN ({marks})",
        f"DELETE FROM player_names WHERE steam_id IN ({marks})",
        f"DELETE FROM reports WHERE initiator_steam_id IN ({marks}) OR target_steam_id IN ({marks})",
        f"DELETE FROM checks WHERE steam_id IN ({marks})",
        f"DELETE FROM alerts WHERE steam_id IN ({marks})",
        f"DELETE FROM bans WHERE steam_id IN ({marks})",
        f"DELETE FROM mutes WHERE steam_id IN ({marks})",
        f"DELETE FROM bags WHERE steam_id IN ({marks}) OR from_steam_id IN ({marks}) OR to_steam_id IN ({marks})",
        f"DELETE FROM bag_events WHERE from_steam_id IN ({marks}) OR to_steam_id IN ({marks})",
        f"DELETE FROM signage WHERE steam_id IN ({marks})",
        f"DELETE FROM kills WHERE initiator_steam_id IN ({marks}) OR target_steam_id IN ({marks})",
        f"DELETE FROM comments WHERE steam_id IN ({marks})",
        f"DELETE FROM chat WHERE steam_id IN ({marks})",
        f"DELETE FROM players WHERE steam_id IN ({marks})",
        f"DELETE FROM steam_cache WHERE steam_id IN ({marks})",
    ):
        try:
            conn.execute(sql, STEAMS)
        except Exception:
            pass
    conn.execute("DELETE FROM servers WHERE token LIKE ? OR name = ?", (TOKEN_MARK + "%", "Test Server"))
    row = conn.execute("SELECT id FROM users WHERE lower(email) = ?", (STAFF_EMAIL,)).fetchone()
    if row:
        uid = int(row["id"])
        conn.execute("DELETE FROM staff_members WHERE user_id = ? AND project_id = ?", (uid, PID))
        conn.execute("DELETE FROM users WHERE id = ?", (uid,))


def seed() -> dict:
    now = server.now_ms()
    now_s = server.now_s()
    day = 86400000
    avatar = server.PLACEHOLDER
    features.set_request_project(PID)

    with server.LOCK:
        conn = server.connect()
        try:
            wipe_old(conn)
            owner = conn.execute("SELECT * FROM users WHERE id = 1").fetchone()
            owner_name = str((owner["name"] if owner else "") or "skvirt")
            owner_email = str((owner["email"] if owner else "") or "")

            token = TOKEN_MARK + uuid.uuid4().hex
            conn.execute(
                """INSERT INTO servers (name, hostname, level, description, avatar_url, banner_url,
                    online, slots, port, version, protocol, token, paired, connected, last_seen,
                    project_id, world_size, seed, map_image, server_ip)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 1, ?, ?, ?, ?, ?, ?)""",
                (
                    "Test Server", "Test Server", "Procedural Map", "Тестовый сервер для настройки панели",
                    avatar, "", 3, 150, 28015, "2600", "2600", token, now_s, PID, 3000, 12345,
                    "/local/landing/map-preview.png?https=1", "185.12.34.1",
                ),
            )
            sid = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])

            for steam, name, ip in PLAYERS:
                conn.execute(
                    """INSERT INTO players (steam_id, steam_name, ip, first_seen, last_seen, comment, last_language, last_no_license)
                       VALUES (?, ?, ?, ?, ?, ?, 'ru', 0)""",
                    (steam, name, ip, now - 3 * day, now, "Тестовый игрок для настройки"),
                )
                conn.execute(
                    "INSERT INTO player_names (steam_id, steam_name, created_at, last_seen) VALUES (?, ?, ?, ?)",
                    (steam, name, now - 3 * day, now),
                )
                conn.execute(
                    "INSERT INTO player_ips (steam_id, ip, first_seen, last_seen, count) VALUES (?, ?, ?, ?, 4)",
                    (steam, ip, now - 3 * day, now),
                )
                conn.execute(
                    """INSERT INTO player_sessions (steam_id, ip, connected_at, disconnected_at, disconnected_reason, is_license, server_id, project_id)
                       VALUES (?, ?, ?, 0, '', 1, ?, ?)""",
                    (steam, ip, now - 3600000, sid, PID),
                )
                conn.execute(
                    "INSERT INTO steam_cache (steam_id, payload, fetched_at) VALUES (?, ?, ?)",
                    (steam, json.dumps({
                        "steamid": steam, "personaname": name, "avatar": avatar, "avatarfull": avatar,
                        "profileurl": f"https://steamcommunity.com/profiles/{steam}",
                    }, ensure_ascii=False), now),
                )

            p_player, p_reporter, p_checked, p_artist, p_alert, p_bag, p_muted, p_banned = STEAMS

            live = {
                "steam_id": p_player, "steam_name": "TestPlayer", "ip": "185.12.34.10",
                "status": "online", "ping": 28, "seconds_connected": 1800, "language": "ru",
                "position": "(180.0, 14.0, -90.0)", "x": 180, "y": 14, "z": -90, "coords": "H8",
                "is_alive": True, "can_build": True, "no_license": False, "team": [p_reporter],
            }
            conn.execute(
                "INSERT INTO online_players (steam_id, payload, project_id, server_id) VALUES (?, ?, ?, ?)",
                (p_player, json.dumps(live, ensure_ascii=False), PID, sid),
            )
            conn.execute(
                "INSERT INTO online_players (steam_id, payload, project_id, server_id) VALUES (?, ?, ?, ?)",
                (p_reporter, json.dumps({
                    **live, "steam_id": p_reporter, "steam_name": "TestReporter", "ip": "185.12.34.11",
                    "position": "(190.0, 14.0, -70.0)", "x": 190, "z": -70, "coords": "H9", "team": [p_player],
                }, ensure_ascii=False), PID, sid),
            )

            conn.execute(
                """INSERT INTO reports (initiator_steam_id, target_steam_id, reason, message, created_at, project_id, server_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (p_reporter, p_player, "Чит", "Тестовый репорт: подозрительный прицел", now - 120000, PID, sid),
            )
            conn.execute(
                """INSERT INTO reports (initiator_steam_id, target_steam_id, reason, message, created_at, project_id, server_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (p_reporter, p_checked, "Макрос", "Тестовый репорт на проверку", now - 300000, PID, sid),
            )

            conn.execute(
                """INSERT INTO checks (steam_id, steam_name, status, contact, started_at, finished_at, notice, verdict,
                    checker_id, checker_name, checker_email, project_id, actor_user_id, actor_name, actor_email, actor_role)
                   VALUES (?, ?, 'active', 'discord: testdiscord', ?, 0, 1, '', ?, ?, ?, ?, ?, ?, ?, 'owner')""",
                (p_checked, "TestChecked", now - 600000, 1, owner_name, owner_email, PID, 1, owner_name, owner_email),
            )
            conn.execute(
                """INSERT INTO checks (steam_id, steam_name, status, contact, started_at, finished_at, notice, verdict,
                    checker_id, checker_name, checker_email, project_id, actor_user_id, actor_name, actor_email, actor_role)
                   VALUES (?, ?, 'finished', '', ?, ?, 0, 'Чист', ?, ?, ?, ?, ?, ?, ?, 'owner')""",
                (p_player, "TestPlayer", now - 2 * day, now - 2 * day + 900000, 1, owner_name, owner_email, PID, 1, owner_name, owner_email),
            )
            conn.execute(
                """INSERT INTO checks (steam_id, steam_name, status, contact, started_at, finished_at, notice, verdict,
                    checker_id, checker_name, checker_email, project_id, actor_user_id, actor_name, actor_email, actor_role)
                   VALUES (?, ?, 'ban', '', ?, ?, 0, 'Чит', ?, ?, ?, ?, ?, ?, ?, 'owner')""",
                (p_banned, "TestBanned", now - day, now - day + 600000, 1, owner_name, owner_email, PID, 1, owner_name, owner_email),
            )

            img_name = "sign-test-1.png"
            img_path = server.UPLOADS / img_name
            img_path.write_bytes(png_bytes())
            img_url = f"/uploads/{img_name}?https=1"
            conn.execute(
                """INSERT INTO signage (steam_id, net_id, type, position, square, image, created_at, destroyed_at, project_id)
                   VALUES (?, ?, 'sign.post.town', ?, 'H8', ?, ?, 0, ?)""",
                (p_artist, "900001", json.dumps({"x": 180, "y": 14, "z": -90}), img_url, now - 80000, PID),
            )

            alerts = [
                ("vpn_detected", p_alert, {"steam_id": p_alert, "ip": "185.12.34.14", "reason": "VPN / hosting", "provider": "TestVPN"}),
                ("dug_up_stash", p_alert, {"steam_id": p_alert, "grid": "H8", "square": "H8"}),
                ("auto_kick", p_alert, {"steam_id": p_alert, "kind": "ip_vpn", "reason": "VPN", "meta_value": {"reason": "VPN"}}),
                ("detect_ra_ban", p_banned, {
                    "steam_id": p_banned,
                    "bans": [{"reason": "Чит", "project": "RCC", "created_at": now - day}],
                }),
                ("license_changed", p_player, {"steam_id": p_player, "from": "license", "to": "license"}),
            ]
            for typ, steam, payload in alerts:
                conn.execute(
                    "INSERT INTO alerts (type, steam_id, payload, created_at, project_id) VALUES (?, ?, ?, ?, ?)",
                    (typ, steam, json.dumps(payload, ensure_ascii=False), now - 90000, PID),
                )

            conn.execute(
                """INSERT INTO bags (steam_id, net_id, name, grid, position, from_steam_id, to_steam_id, created_at, project_id)
                   VALUES (?, '800001', 'Test Bag', 'H8', ?, ?, ?, ?, ?)""",
                (p_bag, json.dumps({"x": 210.5, "y": 12.0, "z": -40.2}), p_bag, p_bag, now - 50000, PID),
            )
            conn.execute(
                """INSERT INTO bag_events (net_id, from_steam_id, to_steam_id, name, grid, position, created_at, project_id)
                   VALUES ('800001', ?, ?, 'Test Bag', 'H8', ?, ?, ?)""",
                (p_bag, p_bag, json.dumps({"x": 210.5, "y": 12.0, "z": -40.2}), now - 50000, PID),
            )

            conn.execute(
                """INSERT INTO mutes (steam_id, reason, created_at, expired_at, active, project_id, actor_user_id, actor_name, actor_email, actor_role)
                   VALUES (?, 'Оскорбления в чате', ?, ?, 1, ?, 1, ?, ?, 'owner')""",
                (p_muted, now - 60000, now + 4 * 3600000, PID, owner_name, owner_email),
            )
            conn.execute(
                """INSERT INTO mutes (steam_id, reason, created_at, expired_at, active, project_id, actor_user_id, actor_name, actor_email, actor_role)
                   VALUES (?, 'Спам', ?, ?, 0, ?, 1, ?, ?, 'owner')""",
                (p_player, now - 2 * day, now - day, PID, owner_name, owner_email),
            )

            conn.execute(
                """INSERT INTO bans (steam_id, steam_name, ip, reason, comment, ban_ip, created_at, expired_at, active,
                    project_id, actor_user_id, actor_name, actor_email, actor_role, pending, pending_meta)
                   VALUES (?, 'TestBanned', '185.12.34.17', 'Чит', 'Тестовый бан для настройки', 1, ?, 0, 1, ?, 1, ?, ?, 'owner', 0, '')""",
                (p_banned, now - 40000, PID, owner_name, owner_email),
            )
            conn.execute(
                """INSERT INTO bans (steam_id, steam_name, ip, reason, comment, ban_ip, created_at, expired_at, active,
                    project_id, actor_user_id, actor_name, actor_email, actor_role, pending, pending_meta)
                   VALUES (?, 'TestPlayer', '185.12.34.10', 'Нарушение правил', 'Истёкший тестовый бан', 0, ?, ?, 0, ?, 1, ?, ?, 'owner', 0, '')""",
                (p_player, now - 5 * day, now - 4 * day, PID, owner_name, owner_email),
            )

            for i in range(6):
                ts = now - i * day
                conn.execute(
                    """INSERT INTO checks (steam_id, steam_name, status, contact, started_at, finished_at, notice, verdict,
                        checker_id, checker_name, checker_email, project_id, actor_user_id, actor_name, actor_email, actor_role)
                       VALUES (?, 'TestPlayer', 'finished', '', ?, ?, 0, 'Чист', 1, ?, ?, ?, 1, ?, ?, 'owner')""",
                    (p_player, ts - 800000, ts - 100000, owner_name, owner_email, PID, owner_name, owner_email),
                )
                if i % 2 == 0:
                    conn.execute(
                        """INSERT INTO bans (steam_id, steam_name, ip, reason, comment, ban_ip, created_at, expired_at, active,
                            project_id, actor_user_id, actor_name, actor_email, actor_role, pending, pending_meta)
                           VALUES (?, 'TestBanned', '185.12.34.17', 'Макрос', 'Статистика', 0, ?, ?, 0, ?, 1, ?, ?, 'owner', 0, '')""",
                        (p_banned, ts, ts + day, PID, owner_name, owner_email),
                    )
                conn.execute(
                    """INSERT INTO mutes (steam_id, reason, created_at, expired_at, active, project_id, actor_user_id, actor_name, actor_email, actor_role)
                       VALUES (?, 'Флуд', ?, ?, 0, ?, 1, ?, ?, 'owner')""",
                    (p_muted, ts, ts + 3600000, PID, owner_name, owner_email),
                )

            conn.execute(
                """INSERT INTO kills (initiator_steam_id, target_steam_id, weapon, distance, is_headshot, created_at, project_id, bone, initiator_name, target_name)
                   VALUES (?, ?, 'ak47.entity', 42.5, 1, ?, ?, 'head', 'TestPlayer', 'TestReporter')""",
                (p_player, p_reporter, now - 20000, PID),
            )
            try:
                conn.execute(
                    "INSERT INTO comments (steam_id, text, created_at) VALUES (?, ?, ?)",
                    (p_player, "Тестовый комментарий модератора", now - 10000),
                )
            except Exception:
                pass

            staff_uid = 0
            existing = conn.execute("SELECT id FROM users WHERE lower(email) = ?", (STAFF_EMAIL,)).fetchone()
            if existing:
                staff_uid = int(existing["id"])
            else:
                conn.execute(
                    """INSERT INTO users (email, name, password_hash, steam_id, google_id, role, is_admin, created_at,
                        tag, bio, twofactor_active, is_platform_admin, projects_blocked, projects_blocked_at,
                        account_blocked, account_blocked_at, account_blocked_reason, discord_id, last_seen_at)
                       VALUES (?, ?, ?, '', '', 'staff', 0, ?, ?, 'Тестовый сотрудник', 0, 0, 0, 0, 0, 0, '', '', ?)""",
                    (STAFF_EMAIL, STAFF_NAME, features.hash_password(STAFF_PASS), now, "teststaff", now),
                )
                staff_uid = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
            perms = [
                "Court_ReportRead", "Court_CheckRead", "Court_CheckProcess", "Court_PlayerBanRead",
                "Court_PlayerMuteRead", "Court_ChatReadPublic", "Court_ServerRead", "Court_MapRead",
                "Court_SleepingBagRead", "Court_AlertRead", "Court_AuditRead", "Court_PlayerHistoryRead",
            ]
            conn.execute(
                """INSERT INTO staff_members (email, name, steam_id, twofactor_active, role, permissions, project_id, created_at, user_id, is_immutable, active)
                   VALUES (?, ?, '', 0, 'staff', ?, ?, ?, ?, 0, 1)""",
                (STAFF_EMAIL, STAFF_NAME, json.dumps(perms, ensure_ascii=False), PID, now, staff_uid),
            )

            features.audit(conn, "seed.demo", {"project_id": PID, "server_id": sid})
            features.lifetime_bump(conn, "players", 8)
            conn.commit()
            return {"ok": True, "project_id": PID, "server_id": sid, "staff_email": STAFF_EMAIL, "staff_pass": STAFF_PASS}
        finally:
            conn.close()


if __name__ == "__main__":
    print(json.dumps(seed(), ensure_ascii=False, indent=2))
