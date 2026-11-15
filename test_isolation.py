"""Isolation, trial, actor and admin tests for RustCheck backend."""
from __future__ import annotations

import json
import sqlite3
import time
import unittest

import features


def mem():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE,
            name TEXT DEFAULT '',
            password_hash TEXT DEFAULT '',
            role TEXT DEFAULT 'user',
            is_platform_admin INTEGER DEFAULT 0,
            created_at INTEGER DEFAULT 0
        );
        CREATE TABLE project (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT DEFAULT '',
            domain TEXT DEFAULT '',
            plan TEXT DEFAULT 'base',
            trial_ends_at INTEGER DEFAULT 0,
            paid_until INTEGER DEFAULT 0,
            owner_user_id INTEGER DEFAULT 0,
            created_at INTEGER DEFAULT 0,
            blocked INTEGER DEFAULT 0,
            admin_frozen INTEGER DEFAULT 0,
            trial_discarded INTEGER DEFAULT 0,
            balance INTEGER DEFAULT 0
        );
        CREATE TABLE webhooks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT,
            url TEXT,
            enabled INTEGER DEFAULT 1,
            options TEXT DEFAULT '{}',
            project_id INTEGER DEFAULT 0
        );
        CREATE TABLE settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        CREATE TABLE audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            actor TEXT DEFAULT '',
            event TEXT DEFAULT '',
            payload TEXT DEFAULT '{}',
            created_at INTEGER,
            project_id INTEGER,
            actor_user_id INTEGER DEFAULT 0
        );
        CREATE TABLE mutes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            steam_id TEXT,
            reason TEXT DEFAULT '',
            created_at INTEGER,
            expired_at INTEGER DEFAULT 0,
            active INTEGER DEFAULT 1,
            project_id INTEGER DEFAULT 0,
            actor_user_id INTEGER DEFAULT 0
        );
        CREATE TABLE wallet (id INTEGER PRIMARY KEY, balance INTEGER DEFAULT 0, plan TEXT DEFAULT 'base');
        """
    )
    features.ensure_schema(conn)
    features.ensure_admin_schema(conn)
    return conn


class IsolationTests(unittest.TestCase):
    def setUp(self):
        self.conn = mem()
        now = int(time.time() * 1000)
        self.conn.execute(
            "INSERT INTO users (email, name, is_platform_admin, role) VALUES (?, ?, 1, 'owner')",
            (features.OWNER_EMAIL, "owner"),
        )
        self.owner_id = int(self.conn.execute("SELECT id FROM users").fetchone()[0])
        self.conn.execute(
            "INSERT INTO users (email, name) VALUES ('staff@test.local', 'Staff')"
        )
        self.staff_id = int(self.conn.execute("SELECT id FROM users WHERE email='staff@test.local'").fetchone()[0])
        trial = now + features.TRIAL_MS
        self.conn.execute(
            "INSERT INTO project (name, domain, plan, trial_ends_at, paid_until, owner_user_id, created_at) VALUES (?,?,?,?,?,?,?)",
            ("A", "proj-a", "base", trial, 0, self.owner_id, now),
        )
        self.pid_a = int(self.conn.execute("SELECT id FROM project WHERE domain='proj-a'").fetchone()[0])
        self.conn.execute(
            "INSERT INTO project (name, domain, plan, trial_ends_at, paid_until, owner_user_id, created_at) VALUES (?,?,?,?,?,?,?)",
            ("B", "proj-b", "base", trial, 0, self.staff_id, now),
        )
        self.pid_b = int(self.conn.execute("SELECT id FROM project WHERE domain='proj-b'").fetchone()[0])

    def tearDown(self):
        features.set_request_project(0)
        features.set_request_user(0)
        self.conn.close()

    def test_webhooks_isolated(self):
        features.set_request_project(self.pid_a)
        features.save_webhooks(self.conn, [{"kind": "ban_create", "url": "https://a.example/hook", "enabled": True}])
        features.set_request_project(self.pid_b)
        items = features.webhook_list(self.conn)
        urls = [i.get("url") for i in items if i.get("url")]
        self.assertNotIn("https://a.example/hook", urls)
        features.save_webhooks(self.conn, [{"kind": "ban_create", "url": "https://b.example/hook", "enabled": True}])
        features.set_request_project(self.pid_a)
        items_a = features.webhook_list(self.conn)
        urls_a = [i.get("url") for i in items_a]
        self.assertIn("https://a.example/hook", urls_a)
        self.assertNotIn("https://b.example/hook", urls_a)

    def test_court_commands_isolated(self):
        features.set_request_project(self.pid_a)
        features.court_commands_save(self.conn, [{"id": 1, "name": "Action A", "commands": ["say a"]}])
        features.set_request_project(self.pid_b)
        cmds = features.court_commands_list(self.conn)
        names = [c.get("name") for c in cmds]
        self.assertNotIn("Action A", names)
        features.court_commands_save(self.conn, [{"id": 2, "name": "Action B", "commands": ["say b"]}])
        features.set_request_project(self.pid_a)
        names_a = [c.get("name") for c in features.court_commands_list(self.conn)]
        self.assertIn("Action A", names_a)
        self.assertNotIn("Action B", names_a)

    def test_trial_is_seven_days(self):
        features.set_request_project(self.pid_a)
        meta = features.billing_meta(self.conn)
        self.assertTrue(meta["is_trial"])
        self.assertFalse(meta["frozen"])
        self.assertGreaterEqual(meta["trial_remaining_ms"], 6 * 86400000)
        self.assertLessEqual(meta["trial_remaining_ms"], features.TRIAL_MS)

    def test_short_trial_is_repaired(self):
        now = int(time.time() * 1000)
        created = now - 10 * 60 * 1000
        self.conn.execute(
            "UPDATE project SET created_at = ?, trial_ends_at = ?, trial_discarded = 0, paid_until = 0 WHERE id = ?",
            (created, created + 5 * 60 * 1000, self.pid_a),
        )
        features.set_request_project(self.pid_a)
        meta = features.billing_meta(self.conn)
        self.assertTrue(meta["is_trial"], meta)
        self.assertFalse(meta["frozen"])
        self.assertGreater(meta["trial_remaining_ms"], 6 * 86400000)

    def test_actor_is_current_user_not_last_staff(self):
        features.set_request_project(self.pid_a)
        features.set_request_user(self.owner_id)
        features.audit(self.conn, "settings.edit", {"target": "court"})
        features.set_request_user(self.staff_id)
        features.audit(self.conn, "mute.create", {"steam_id": "76561199358366053"})
        features.set_request_user(self.owner_id)
        features.audit(self.conn, "settings.edit", {"target": "discord"})
        rows = list(self.conn.execute("SELECT actor, event, actor_user_id, payload FROM audit ORDER BY id"))
        self.assertEqual(int(rows[0]["actor_user_id"]), self.owner_id)
        self.assertEqual(int(rows[1]["actor_user_id"]), self.staff_id)
        self.assertEqual(int(rows[2]["actor_user_id"]), self.owner_id)
        self.assertIn(features.OWNER_EMAIL.lower(), str(rows[0]["actor"]).lower())
        self.assertIn("staff@test.local", str(rows[1]["actor"]).lower())
        self.assertIn(features.OWNER_EMAIL.lower(), str(rows[2]["actor"]).lower())

    def test_platform_admin_owner_only_add(self):
        features.set_request_user(self.owner_id)
        out = features.add_platform_admin(self.conn, "staff@test.local", features.OWNER_EMAIL)
        self.assertTrue(out["ok"], out)
        admins = features.list_platform_admins(self.conn)
        emails = [a["email"].lower() for a in admins]
        self.assertIn("staff@test.local", emails)
        blocked = features.remove_platform_admin(self.conn, self.owner_id, features.OWNER_EMAIL)
        self.assertFalse(blocked["ok"])

    def test_mute_rows_are_per_project_and_player(self):
        self.conn.execute(
            "INSERT INTO mutes (steam_id, reason, created_at, active, project_id) VALUES (?,?,?,1,?)",
            ("76561199358366053", "Mute A", int(time.time() * 1000), self.pid_a),
        )
        self.conn.execute(
            "INSERT INTO mutes (steam_id, reason, created_at, active, project_id) VALUES (?,?,?,1,?)",
            ("76561198000000002", "Mute B", int(time.time() * 1000), self.pid_b),
        )
        a_rows = self.conn.execute(
            "SELECT * FROM mutes WHERE project_id = ? AND steam_id = ?",
            (self.pid_a, "76561199358366053"),
        ).fetchall()
        b_rows = self.conn.execute(
            "SELECT * FROM mutes WHERE project_id = ? AND steam_id = ?",
            (self.pid_b, "76561198000000002"),
        ).fetchall()
        leak = self.conn.execute(
            "SELECT * FROM mutes WHERE project_id = ? AND steam_id = ?",
            (self.pid_b, "76561199358366053"),
        ).fetchall()
        self.assertEqual(len(a_rows), 1)
        self.assertEqual(len(b_rows), 1)
        self.assertEqual(len(leak), 0)
        self.assertEqual(a_rows[0]["reason"], "Mute A")

    def test_audit_not_attached_to_first_project(self):
        features.set_request_project(self.pid_b)
        features.set_request_user(self.staff_id)
        features.audit(self.conn, "webhook.save", {"count": 1, "project_id": self.pid_b})
        row = self.conn.execute("SELECT project_id FROM audit ORDER BY id DESC LIMIT 1").fetchone()
        self.assertEqual(int(row["project_id"]), self.pid_b)

    def test_pid_zero_does_not_read_other_project_settings(self):
        features.set_request_project(self.pid_a)
        features.setting_json_set(self.conn, "court_discord", {"Ban": {"url": "https://a.example/hook"}})
        features.set_request_project(0)
        leaked = features.setting_json(self.conn, "court_discord", {})
        self.assertEqual(leaked, {})
        features.set_request_project(self.pid_b)
        leaked_b = features.setting_json(self.conn, "court_discord", {})
        self.assertNotIn("Ban", leaked_b if isinstance(leaked_b, dict) else {})

    def test_new_project_gets_empty_webhooks(self):
        features.set_request_project(self.pid_a)
        features.save_webhooks(self.conn, [{"kind": "ban_create", "url": "https://a.example/hook", "enabled": True}])
        features.init_empty_project(self.conn, self.pid_b)
        features.set_request_project(self.pid_b)
        urls = [i.get("url") for i in features.webhook_list(self.conn) if i.get("url")]
        self.assertNotIn("https://a.example/hook", urls)

    def test_actor_ignores_target_user_id(self):
        features.set_request_project(self.pid_a)
        features.set_request_user(self.owner_id)
        features.audit(self.conn, "ban.create", {"steam_id": "76561198000000001", "user_id": self.staff_id})
        row = self.conn.execute("SELECT actor_user_id, payload FROM audit ORDER BY id DESC LIMIT 1").fetchone()
        self.assertEqual(int(row["actor_user_id"]), self.owner_id)
        payload = json.loads(row["payload"])
        self.assertEqual(int(payload.get("actor_id") or 0), self.owner_id)
        self.assertNotEqual(int(payload.get("actor_id") or 0), self.staff_id)

    def test_adding_staff_does_not_rewrite_old_audit(self):
        features.set_request_project(self.pid_a)
        features.set_request_user(self.owner_id)
        features.audit(self.conn, "mute.create", {"steam_id": "76561198000000001"})
        old_id = int(self.conn.execute("SELECT id FROM audit ORDER BY id DESC LIMIT 1").fetchone()[0])
        features.set_request_user(self.staff_id)
        features.audit(self.conn, "staff_edit", {"project_id": self.pid_a, "target_user_id": self.staff_id, "user_id": self.staff_id})
        old = self.conn.execute("SELECT actor_user_id FROM audit WHERE id = ?", (old_id,)).fetchone()
        self.assertEqual(int(old["actor_user_id"]), self.owner_id)

    def test_autokick_isolated(self):
        features.set_request_project(self.pid_a)
        features.save_autokick(self.conn, [{"type": "ip_vpn", "active": True}])
        features.set_request_project(self.pid_b)
        rows = features.autokick_list(self.conn)
        vpn = next((r for r in rows if r.get("type") == "ip_vpn"), None)
        self.assertFalse(bool(vpn and vpn.get("active")))

    def test_server_endpoint_format(self):
        self.assertEqual(features.format_server_endpoint("217.60.245.104", 10017), "217.60.245.104:10017")
        self.assertEqual(features.format_server_endpoint("217.60.245.104:10017", 0), "217.60.245.104:10017")

    def test_webhook_urls_never_cross_projects(self):
        features.set_request_project(self.pid_a)
        self.conn.execute(
            "INSERT INTO webhooks (kind, url, enabled, project_id) VALUES (?,?,1,?)",
            ("ban_create", "https://hooks.example/a", self.pid_a),
        )
        features.set_request_project(self.pid_b)
        self.conn.execute(
            "INSERT INTO webhooks (kind, url, enabled, project_id) VALUES (?,?,1,?)",
            ("ban_create", "https://hooks.example/b", self.pid_b),
        )
        a_urls = features.webhook_urls(self.conn, "ban_create", project_id=self.pid_a)
        b_urls = features.webhook_urls(self.conn, "ban_create", project_id=self.pid_b)
        none_urls = features.webhook_urls(self.conn, "ban_create", project_id=0)
        self.assertEqual(a_urls, ["https://hooks.example/a"])
        self.assertEqual(b_urls, ["https://hooks.example/b"])
        self.assertEqual(none_urls, [])

    def test_audit_actor_name_is_frozen(self):
        features.set_request_project(self.pid_a)
        features.set_request_user(self.staff_id)
        features.audit(self.conn, "mute.create", {"steam_id": "76561198000000001", "name": "Player"})
        row = self.conn.execute(
            "SELECT actor_user_id, actor_name, actor_role FROM audit ORDER BY id DESC LIMIT 1"
        ).fetchone()
        self.assertEqual(int(row["actor_user_id"]), self.staff_id)
        self.assertEqual(str(row["actor_name"]), "Staff")
        self.assertEqual(str(row["actor_role"]), "staff")
        features.set_request_user(self.owner_id)
        again = self.conn.execute(
            "SELECT actor_user_id, actor_name FROM audit ORDER BY id DESC LIMIT 1"
        ).fetchone()
        self.assertEqual(int(again["actor_user_id"]), self.staff_id)
        self.assertEqual(str(again["actor_name"]), "Staff")

    def test_transactions_filtered_by_project(self):
        features.set_request_user(self.owner_id)
        features.set_request_project(self.pid_a)
        features.add_wallet_op(self.conn, 10000, "Пополнение A", project_id=self.pid_a)
        features.set_request_project(self.pid_b)
        features.add_wallet_op(self.conn, 20000, "Пополнение B", project_id=self.pid_b)
        a_items = features.list_admin_transactions(self.conn, self.pid_a)
        b_items = features.list_admin_transactions(self.conn, self.pid_b)
        empty = features.list_admin_transactions(self.conn, 0)
        self.assertEqual(len(a_items), 1)
        self.assertEqual(len(b_items), 1)
        self.assertEqual(len(empty), 2)
        self.assertEqual(a_items[0]["amount"], 10000)
        self.assertNotEqual(a_items[0]["id"], b_items[0]["id"])

    def test_empty_project_gets_no_webhooks(self):
        features.set_request_project(self.pid_a)
        self.conn.execute(
            "INSERT INTO webhooks (kind, url, enabled, project_id) VALUES (?,?,1,?)",
            ("mute_create", "https://hooks.example/a-mute", self.pid_a),
        )
        self.assertEqual(features.webhook_urls(self.conn, "mutes", project_id=self.pid_b), [])
        self.assertEqual(features.webhook_urls(self.conn, "mutes", project_id=0), [])
        self.assertEqual(features.webhook_urls(self.conn, "mutes", project_id=self.pid_a), ["https://hooks.example/a-mute"])

    def test_ban_sync_public_does_not_toggle_off_with_enabled(self):
        features.set_request_project(self.pid_a)
        features.set_request_user(self.owner_id)
        saved = features.ban_sync_save(self.conn, {"is_public": True, "enabled": False})
        self.assertTrue(saved["is_public"])
        self.assertFalse(saved["enabled"])
        again = features.ban_sync_settings(self.conn)
        self.assertTrue(again["is_public"])
        self.assertFalse(again["enabled"])
        features.set_request_project(self.pid_b)
        other = features.ban_sync_settings(self.conn)
        self.assertFalse(other["is_public"])
        avail = {item["id"] for item in features.ban_sync_available(self.conn)}
        self.assertIn(self.pid_a, avail)
        self.assertNotIn(self.pid_b, avail)
        row = next(item for item in features.ban_sync_available(self.conn) if item["id"] == self.pid_a)
        self.assertIn("project_original", row)
        self.assertEqual(row["project_id_original"], self.pid_a)
        self.assertEqual(row["project_original"]["id"], self.pid_a)
        self.assertIn("total_bans", row)
        features.set_request_project(self.pid_b)
        added = features.ban_sync_subscribe(self.conn, {"project_id_original": self.pid_a})
        ids = [int(item["id"]) for item in added]
        self.assertIn(self.pid_a, ids)
        again = features.ban_sync_subscribe(self.conn, self.pid_a)
        self.assertEqual(len(again), len(added))
        listed = features.ban_sync_subscribe(self.conn, [self.pid_a])
        self.assertIn(self.pid_a, [int(item["id"]) for item in listed])

    def test_product_name_is_not_human_actor(self):
        self.assertEqual(features.human_actor_name("RustCheck", "admin@x.com"), "admin")
        self.assertEqual(features.human_actor_name("Checkapp", "staff@test.local"), "staff")
        self.assertEqual(features.human_actor_name("AdminName", ""), "AdminName")

    def test_command_log_isolated_and_has_actor(self):
        features.set_request_project(self.pid_a)
        features.set_request_user(self.owner_id)
        features.log_command_execution(self.conn, ["mute 76561198000000001"], target_name="Player", server_name="A1")
        features.set_request_project(self.pid_b)
        features.set_request_user(self.staff_id)
        self.assertEqual(features.command_log_items(self.conn), [])
        features.set_request_project(self.pid_a)
        items = features.command_log_items(self.conn)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["actor_name"], "owner")
        self.assertEqual(int(items[0]["actor_id"]), self.owner_id)
        self.assertEqual(items[0]["server_name"], "A1")
        self.assertEqual(items[0]["system_source"], "RustCheck")

    def test_staff_add_is_per_project(self):
        features.set_request_project(self.pid_a)
        features.set_request_user(self.owner_id)
        found = features.user_by_tag(self.conn, "Staff")
        self.assertIsNotNone(found)
        self.assertEqual(int(found["id"]), self.staff_id)
        out = features.staff_upsert(self.conn, self.pid_a, self.staff_id, ["Court_ChatReadPublic"])
        self.assertTrue(out["ok"], out)
        self.assertEqual(int(out["row"]["client"]["id"]), self.staff_id)
        again = features.staff_upsert(self.conn, self.pid_a, self.staff_id, ["Court_ChatReadPublic", "Court_CheckProcess"])
        self.assertTrue(again["ok"], again)
        self.assertIn("Court_CheckProcess", again["row"]["permissions"])
        flagged = features.staff_upsert(
            self.conn, self.pid_a, self.staff_id, {"Court_CheckProcess": True, "Court_PlayerBan": False}
        )
        self.assertTrue(flagged["ok"], flagged)
        self.assertEqual(flagged["row"]["permissions"], ["Court_CheckProcess"])
        listed_a = features.staff_list_payload(self.conn, self.pid_a)
        ids_a = [int(r["client"]["id"]) for r in listed_a["active"]]
        self.assertIn(self.staff_id, ids_a)
        features.set_request_project(self.pid_b)
        listed_b = features.staff_list_payload(self.conn, self.pid_b)
        ids_b = [int(r["client"]["id"]) for r in listed_b["active"]]
        # Staff is owner of B, but was added as member only on A
        self.assertIn(self.staff_id, ids_b)
        extra = [r for r in listed_b["active"] if int(r["client"]["id"]) == self.staff_id]
        self.assertTrue(extra[0].get("is_owner"))

    def test_cannot_add_project_owner_as_staff(self):
        features.set_request_project(self.pid_a)
        features.set_request_user(self.owner_id)
        out = features.staff_upsert(self.conn, self.pid_a, self.owner_id, [])
        self.assertFalse(out["ok"])
        self.assertEqual(out["error"], "cannot_add_self")

    def test_freeze_actor_never_rustcheck(self):
        features.set_request_project(self.pid_a)
        features.set_request_user(self.owner_id)
        frozen = features.freeze_actor(self.conn)
        self.assertEqual(int(frozen["actor_user_id"]), self.owner_id)
        self.assertEqual(frozen["actor_name"], "owner")
        self.assertNotEqual(str(frozen["actor_name"]).lower(), "rustcheck")
        self.assertEqual(frozen["system_source"], "RustCheck")
        features.set_request_user(self.staff_id)
        frozen_s = features.freeze_actor(self.conn)
        self.assertEqual(int(frozen_s["actor_user_id"]), self.staff_id)
        self.assertEqual(frozen_s["actor_name"], "Staff")
        self.assertNotEqual(str(frozen_s["actor_name"]).lower(), "rustcheck")

    def test_alerts_require_project_id(self):
        self.conn.execute(
            """CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT,
                steam_id TEXT,
                payload TEXT,
                created_at INTEGER,
                project_id INTEGER DEFAULT 0
            )"""
        )
        features.set_request_project(self.pid_a)
        self.conn.execute(
            "INSERT INTO alerts (type, steam_id, payload, created_at, project_id) VALUES (?,?,?,?,?)",
            ("auto_kick", "76561199358366053", "{}", int(time.time() * 1000), self.pid_a),
        )
        features.set_request_project(self.pid_b)
        leaked = self.conn.execute(
            "SELECT * FROM alerts WHERE COALESCE(project_id, 0) = ?",
            (self.pid_b,),
        ).fetchall()
        self.assertEqual(len(leaked), 0)
        owned = self.conn.execute(
            "SELECT * FROM alerts WHERE COALESCE(project_id, 0) = ?",
            (self.pid_a,),
        ).fetchall()
        self.assertEqual(len(owned), 1)

    def test_pref_bool_keeps_explicit_false(self):
        self.assertFalse(features.pref_bool({"active": False, "enabled": True}, "active", "enabled"))
        self.assertTrue(features.pref_bool({"enabled": True}, "active", "enabled"))
        self.assertFalse(features.pref_bool({}, "active", "enabled"))

    def test_discord_toggle_persists_and_stays_in_project(self):
        features.set_request_project(self.pid_a)
        features.discord_toggle(self.conn, "Check", True)
        on = {r["type"]: r for r in features.discord_list(self.conn)}
        self.assertTrue(on["Check"]["active"])
        features.discord_toggle(self.conn, "Check", False)
        off = {r["type"]: r for r in features.discord_list(self.conn)}
        self.assertFalse(off["Check"]["active"])
        self.assertFalse(off["Check"]["enabled"])
        features.set_request_project(self.pid_b)
        other = {r["type"]: r for r in features.discord_list(self.conn)}
        self.assertFalse(other["Check"]["active"])

    def test_signage_likes_isolated(self):
        self.conn.executescript(
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
            CREATE TABLE IF NOT EXISTS signage_likes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                drawing_id INTEGER NOT NULL,
                net_id TEXT DEFAULT '',
                project_id INTEGER NOT NULL,
                created_at INTEGER,
                UNIQUE(user_id, drawing_id)
            );
            """
        )
        self.conn.execute(
            "INSERT INTO signage (steam_id, net_id, created_at, project_id) VALUES (?,?,?,?)",
            ("76561198000000001", "n1", int(time.time() * 1000), self.pid_a),
        )
        did = int(self.conn.execute("SELECT last_insert_rowid()").fetchone()[0])
        features.set_request_project(self.pid_a)
        features.set_request_user(self.owner_id)
        liked = features.signage_toggle_like(self.conn, did, "n1", True)
        self.assertTrue(liked["likedByCurrentUser"])
        again = features.signage_toggle_like(self.conn, did, "n1", None)
        self.assertFalse(again["likedByCurrentUser"])
        features.signage_toggle_like(self.conn, did, "n1", True)
        features.set_request_project(self.pid_b)
        leaked = self.conn.execute(
            "SELECT * FROM signage_likes WHERE project_id = ?",
            (self.pid_b,),
        ).fetchall()
        self.assertEqual(len(leaked), 0)

    def test_realtime_never_crosses_projects(self):
        import server as srv
        a = srv.emit_realtime(self.pid_a, "notification.created", {"title": "A"})
        b = srv.emit_realtime(self.pid_b, "notification.created", {"title": "B"})
        self.assertIsNotNone(a)
        self.assertIsNotNone(b)
        ev_a = srv.realtime_since(self.pid_a, 0)
        ev_b = srv.realtime_since(self.pid_b, 0)
        types_a = [e.get("payload", {}).get("title") for e in ev_a]
        types_b = [e.get("payload", {}).get("title") for e in ev_b]
        self.assertIn("A", types_a)
        self.assertNotIn("B", types_a)
        self.assertIn("B", types_b)
        self.assertNotIn("A", types_b)
        self.assertEqual(srv.realtime_since(0, 0), [])

    def test_team_event_stays_in_project(self):
        features.set_request_project(self.pid_a)
        features.save_team_snapshot(self.conn, "76561198000000001", ["76561198000000002"], self.pid_a, 1)
        features.record_team_event(self.conn, "team.created", "76561198000000001", ["76561198000000001", "76561198000000002"], self.pid_a, 1)
        features.set_request_project(self.pid_a)
        items_a = features.team_history_items(self.conn, "76561198000000001")
        features.set_request_project(self.pid_b)
        items_b = features.team_history_items(self.conn, "76561198000000001")
        self.assertTrue(len(items_a) >= 1)
        self.assertEqual(len(items_b), 0)

    def test_ip_geo_private_is_unknown_ok(self):
        geo = features.fetch_ip_geo("127.0.0.1")
        self.assertTrue(features._is_private_ip("127.0.0.1"))
        self.assertIn(geo.get("country_name"), ("Local network", "Локальная сеть", "Unknown"))
        self.assertNotEqual(str(geo.get("country_code") or "").lower(), "un")
        self.assertFalse(features._geo_is_placeholder({"country": "Local network", "city": "", "isp": ""}))
        self.assertFalse(features._geo_is_placeholder({"country": "Локальная сеть", "city": "", "isp": ""}))

    def test_staff_flag_map_keeps_enabled_keys(self):
        out = features.normalize_staff_permissions({
            "Court_ChatReadPublic": True,
            "Court_CheckProcess": False,
            "Court_PlayerBan": 1,
        })
        self.assertIn("Court_ChatReadPublic", out)
        self.assertIn("Court_PlayerBan", out)
        self.assertNotIn("Court_CheckProcess", out)

    def test_steam_profile_defaults_are_not_fake_hours(self):
        out = features.fetch_steam_profile("not-a-steam-id")
        self.assertIsNone(out.get("rust_hours_total"))
        self.assertNotEqual(out.get("rust_hours_total"), 1234)
        self.assertFalse(out.get("profile_filled"))

    def test_check_chat_emits_to_same_project_only(self):
        import server as srv
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS checks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                steam_id TEXT, steam_name TEXT DEFAULT '', status TEXT DEFAULT 'active',
                contact TEXT DEFAULT '', started_at INTEGER, finished_at INTEGER DEFAULT 0,
                notice INTEGER DEFAULT 0, checker_id INTEGER DEFAULT 0,
                checker_name TEXT DEFAULT '', checker_email TEXT DEFAULT '', project_id INTEGER
            );
            CREATE TABLE IF NOT EXISTS chat (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                steam_id TEXT, steam_name TEXT DEFAULT '', target_steam_id TEXT,
                is_team INTEGER DEFAULT 0, text TEXT, from_site INTEGER DEFAULT 0,
                created_at INTEGER, project_id INTEGER, actor_user_id INTEGER DEFAULT 0,
                actor_name TEXT DEFAULT '', actor_email TEXT DEFAULT '', actor_role TEXT DEFAULT ''
            );
            """
        )
        self.conn.execute(
            "INSERT INTO checks (steam_id, steam_name, status, started_at, finished_at, project_id) VALUES (?,?,?,?,0,?)",
            ("76561198000000001", "PlayerA", "active", int(time.time() * 1000), self.pid_a),
        )
        features.set_request_project(self.pid_a)
        features.set_request_user(self.owner_id)
        srv.insert_chat(
            self.conn, "project", "AdminOne", "76561198000000001", False, "hello from A", True,
            project_id=self.pid_a, actor_user_id=self.owner_id, actor_name="AdminOne", author_type="staff",
        )
        ev_a = [e for e in srv.realtime_since(self.pid_a, 0) if e.get("type") == "check.message.created"]
        ev_b = [e for e in srv.realtime_since(self.pid_b, 0) if e.get("type") == "check.message.created"]
        self.assertTrue(ev_a)
        msg = (ev_a[-1].get("payload") or {}).get("message") or {}
        self.assertEqual(msg.get("authorName"), "AdminOne")
        self.assertEqual(int((ev_a[-1].get("payload") or {}).get("projectId") or 0), self.pid_a)
        self.assertFalse(ev_b)

    def test_contact_lookup_rejects_junk_and_bare_slash_contact(self):
        self.assertEqual(features.contact_lookup_key("/contact"), "")
        self.assertEqual(features.contact_lookup_key("contact"), "")
        self.assertEqual(features.contact_lookup_key("/contact discorduser"), "discorduser")
        self.assertEqual(features.contact_lookup_key("ab"), "")

    def test_discord_list_reads_lowercase_saved_type(self):
        features.set_request_project(self.pid_a)
        features.setting_json_set(self.conn, "court_discord", {
            "check": {"type": "check", "active": True, "webhook": "https://discord.com/api/webhooks/x"},
        })
        rows = {r["type"]: r for r in features.discord_list(self.conn)}
        self.assertTrue(rows["Check"]["active"])
        self.assertEqual(rows["Check"]["webhook"], "https://discord.com/api/webhooks/x")

    def test_foreign_project_param_reads_nested_filter(self):
        import server as srv
        features.set_request_project(self.pid_a)
        self.assertEqual(
            srv.foreign_project_from_params({
                "filter[project_id_original]": [str(self.pid_b)],
                "steam_id": ["76561198000000001"],
            }),
            self.pid_b,
        )
        self.assertEqual(
            srv.foreign_project_from_params({"project_id_original": [str(self.pid_a)]}),
            0,
        )
        clause, _args = srv.scoped_project_clause(
            self.conn, {"project_id_original": [str(self.pid_b)]}
        )
        self.assertIn("0=1", clause)

    def test_parse_ms_cursor_stops_unusable_second_page(self):
        import server as srv
        ms, sent = srv.parse_ms_cursor("")
        self.assertFalse(sent)
        self.assertEqual(ms, 0)
        ms, sent = srv.parse_ms_cursor("not-a-time")
        self.assertTrue(sent)
        self.assertEqual(ms, 0)
        ms, sent = srv.parse_ms_cursor("1710000000000")
        self.assertTrue(sent)
        self.assertEqual(ms, 1710000000000)

    def test_record_user_ip_keeps_loopback(self):
        features.record_user_ip(self.conn, self.owner_id, "127.0.0.1")
        row = self.conn.execute(
            "SELECT ip FROM user_login_ips WHERE user_id = ?",
            (self.owner_id,),
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(str(row["ip"]), "127.0.0.1")

    def test_geo_display_maps_iso_code(self):
        import server as srv
        country, _city, _prov, code = srv.geo_display(
            {"country": "RU", "country_code": "ru"}, "8.8.8.8"
        )
        self.assertEqual(country, "Россия")
        self.assertEqual(code, "ru")
        hc, hcode = srv.header_country(type("H", (), {"headers": {"CF-IPCountry": "RU"}})())
        self.assertEqual(hc, "Россия")
        self.assertEqual(hcode, "ru")

    def test_param_values_indexed_project_ids(self):
        import server as srv
        vals = srv.param_values({"project_ids[0]": ["12"], "project_ids[1]": ["34"]}, "project_ids")
        self.assertEqual(vals, ["12", "34"])
        self.assertTrue(srv.params_have_key({"project_ids[]": []}, "project_ids"))
        self.assertFalse(srv.params_have_key({"steam_id": ["1"]}, "project_ids"))

    def test_team_history_fills_server_id(self):
        self.conn.execute(
            """CREATE TABLE IF NOT EXISTS servers (
                id INTEGER PRIMARY KEY,
                name TEXT DEFAULT '',
                project_id INTEGER DEFAULT 0,
                paired INTEGER DEFAULT 0
            )"""
        )
        self.conn.execute(
            "INSERT INTO servers (id, name, project_id, paired) VALUES (7, 'main', ?, 1)",
            (self.pid_a,),
        )
        features.set_request_project(self.pid_a)
        features.save_team_snapshot(self.conn, "76561198000000001", ["76561198000000002"], self.pid_a, 0)
        items = features.team_history_items(self.conn, "76561198000000001")
        self.assertTrue(items)
        self.assertEqual(int(items[0].get("server_id") or 0), 7)


if __name__ == "__main__":
    unittest.main()
