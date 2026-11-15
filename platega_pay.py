"""Platega.io payouts for project wallet top-up. Credentials stay server-side."""
from __future__ import annotations

import hmac
import http.client
import json
import os
import re
import socket
import ssl
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import features

BASE = "https://app.platega.io"
DATA_FILE = Path(__file__).resolve().parent / "data" / "platega.json"
ALLOWED_METHODS = {2, 13}  # SBP QR, crypto
METHOD_LABELS = {
    2: "СБП",
    3: "ЕРИП",
    11: "Карта",
    12: "Международная карта",
    13: "Crypto",
    14: "SberPay",
}
UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
# Seeded from partnership. Prefer env / data/platega.json / settings.
_FALLBACK_SECRET = "TrDvF3mGySvDgdD8gYGG6VcBLda8rbYHBsaOroF7yxAkewAhCioO8XsFxUrwX1ZVYUVHJBQkwQ3iuh4cdzpTySUkS5yEHpFsBJ8m"
_FALLBACK_MERCHANT = "88aca5fc-3d3d-4e6e-a967-1527e244df10"
MIN_RUB = 1
MAX_RUB = 300000


def ensure_schema(conn) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS platega_payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id TEXT UNIQUE,
            transaction_id TEXT DEFAULT '',
            project_id INTEGER DEFAULT 0,
            user_id INTEGER DEFAULT 0,
            amount_kopecks INTEGER DEFAULT 0,
            amount_rub REAL DEFAULT 0,
            method INTEGER DEFAULT 0,
            status TEXT DEFAULT 'PENDING',
            credited INTEGER DEFAULT 0,
            redirect TEXT DEFAULT '',
            payload TEXT DEFAULT '',
            created_at INTEGER DEFAULT 0,
            confirmed_at INTEGER DEFAULT 0
        )"""
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_platega_tx ON platega_payments(transaction_id)"
    )
    _seed_file()
    _seed_settings(conn)


def _seed_file() -> dict:
    data = _read_file()
    changed = False
    if not str(data.get("secret") or "").strip():
        data["secret"] = os.environ.get("PLATEGA_SECRET") or _FALLBACK_SECRET
        changed = True
    if "merchant_id" not in data:
        data["merchant_id"] = str(os.environ.get("PLATEGA_MERCHANT_ID") or _FALLBACK_MERCHANT).strip()
        changed = True
    if changed:
        _write_file(data)
    return data


def _read_file() -> dict:
    try:
        raw = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _write_file(data: dict) -> None:
    try:
        DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        print("platega write creds failed", type(exc).__name__)


def _seed_settings(conn) -> None:
    data = _read_file()
    secret = str(data.get("secret") or "").strip()
    merchant = str(data.get("merchant_id") or "").strip()
    if secret and not _setting(conn, "platega_secret"):
        _set_setting(conn, "platega_secret", secret)
    if merchant and not _setting(conn, "platega_merchant_id"):
        _set_setting(conn, "platega_merchant_id", merchant)


def _setting(conn, key: str) -> str:
    try:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        if not row:
            return ""
        val = row["value"] if isinstance(row, dict) or hasattr(row, "keys") else row[0]
        text = str(val or "").strip()
        if text.startswith("{") or text.startswith('"'):
            try:
                parsed = json.loads(text)
                if isinstance(parsed, str):
                    return parsed.strip()
            except Exception:
                pass
        return text
    except Exception:
        return ""


def _set_setting(conn, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(value or "")),
    )


def _creds(conn=None) -> tuple[str, str]:
    env_m = str(os.environ.get("PLATEGA_MERCHANT_ID") or "").strip()
    env_s = str(os.environ.get("PLATEGA_SECRET") or "").strip()
    file_data = _read_file()
    file_m = str(file_data.get("merchant_id") or "").strip()
    file_s = str(file_data.get("secret") or "").strip()
    db_m = db_s = ""
    if conn is not None:
        db_m = _setting(conn, "platega_merchant_id")
        db_s = _setting(conn, "platega_secret")
    merchant = env_m or file_m or db_m or _FALLBACK_MERCHANT
    secret = env_s or file_s or db_s or _FALLBACK_SECRET
    return merchant, secret


def configured(conn=None) -> dict:
    merchant, secret = _creds(conn)
    return {
        "ok": True,
        "configured": bool(merchant and secret),
        "has_secret": bool(secret),
        "has_merchant": bool(merchant),
        "methods": [
            {"id": 2, "key": "sbp", "label": "СБП", "enabled": True, "hint": "Оплата по QR"},
            {"id": 13, "key": "crypto", "label": "Crypto", "enabled": True, "hint": "USDT и другие монеты"},
            {"id": 11, "key": "card", "label": "Банковская карта", "enabled": False, "hint": "Скоро"},
            {"id": 14, "key": "sberpay", "label": "SberPay", "enabled": False, "hint": "Скоро"},
            {"id": 12, "key": "intl", "label": "Международная карта", "enabled": False, "hint": "Скоро"},
            {"id": 3, "key": "erip", "label": "ЕРИП", "enabled": False, "hint": "Скоро"},
        ],
        "min_rub": MIN_RUB,
        "max_rub": MAX_RUB,
        "callback": "/billing/platega/callback",
    }


def _header(handler, name: str) -> str:
    headers = getattr(handler, "headers", None)
    if not headers:
        return ""
    return str(headers.get(name) or headers.get(name.lower()) or "").strip()


def public_base(handler) -> str:
    try:
        return str(handler._auth_public_base() or "").rstrip("/")
    except Exception:
        return "http://127.0.0.1:8081"


def _project_slug(conn, pid: int) -> str:
    row = conn.execute(
        "SELECT domain, name FROM project WHERE id = ?",
        (int(pid),),
    ).fetchone()
    if not row:
        return str(pid)
    return str(row["domain"] or row["name"] or pid).strip() or str(pid)


def parse_amount(body: dict) -> tuple[int, float]:
    """Return (kopecks, rub). Site wallet is kopecks."""
    if not isinstance(body, dict):
        return 0, 0.0
    if body.get("amount_rub") not in (None, ""):
        try:
            rub = float(body.get("amount_rub"))
        except (TypeError, ValueError):
            rub = 0.0
        rub = round(rub, 2)
        return int(round(rub * 100)), rub
    try:
        raw = float(body.get("amount") or body.get("value") or 0)
    except (TypeError, ValueError):
        raw = 0.0
    if raw <= 0:
        return 0, 0.0
    if raw >= 10000:
        kopecks = int(round(raw))
        return kopecks, round(kopecks / 100.0, 2)
    rub = round(raw, 2)
    return int(round(rub * 100)), rub


def parse_method(body: dict) -> int:
    raw = body.get("payment_method") if isinstance(body, dict) else None
    if raw in (None, ""):
        raw = (body or {}).get("method") or (body or {}).get("paymentMethod")
    text = str(raw or "").strip().lower()
    aliases = {
        "sbp": 2, "sbpqr": 2, "qr": 2, "tinkoff-sbp": 2, "tinkoff_sbp": 2,
        "crypto": 13, "cryptocurrency": 13, "usdt": 13,
    }
    if text in aliases:
        return aliases[text]
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return 0


class _IPv4HTTPSConnection(http.client.HTTPSConnection):
    def connect(self):
        timeout = self.timeout if self.timeout is not None else 12
        last = None
        infos = socket.getaddrinfo(self.host, self.port, socket.AF_INET, socket.SOCK_STREAM)
        for family, socktype, proto, _canon, sockaddr in infos:
            sock = None
            try:
                sock = socket.socket(family, socktype, proto)
                sock.settimeout(timeout)
                sock.connect(sockaddr)
                self.sock = sock
                if self._tunnel_host:
                    self._tunnel()
                self.sock = self._context.wrap_socket(self.sock, server_hostname=self.host)
                return
            except OSError as exc:
                last = exc
                if sock is not None:
                    try:
                        sock.close()
                    except Exception:
                        pass
        if last:
            raise last
        raise OSError("platega ipv4 connect failed")


class _IPv4HTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_IPv4HTTPSConnection, req, context=self._context)


def _platega_request(conn, method: str, path: str, payload=None):
    merchant, secret = _creds(conn)
    if not merchant or not secret:
        raise RuntimeError("need_merchant")
    url = BASE.rstrip("/") + "/" + str(path).lstrip("/")
    data = None
    headers = {
        "X-MerchantId": merchant,
        "X-Secret": secret,
        "Accept": "application/json",
        "User-Agent": "rustcheck-platega/1",
    }
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
    ctx = ssl.create_default_context()
    opener = urllib.request.build_opener(_IPv4HTTPSHandler(context=ctx))
    try:
        with opener.open(req, timeout=12) as resp:
            raw = resp.read().decode("utf-8", "replace")
            try:
                return json.loads(raw) if raw else {}
            except Exception:
                return {"raw": raw}
    except urllib.error.HTTPError as exc:
        err_body = ""
        try:
            err_body = exc.read().decode("utf-8", "replace")[:800]
        except Exception:
            pass
        raise RuntimeError("platega_http_%s %s" % (exc.code, err_body[:240])) from exc
    except (urllib.error.URLError, socket.timeout, TimeoutError, OSError) as exc:
        raise RuntimeError("platega_timeout %s" % str(exc)[:120]) from exc


def _remote_pay_url(remote) -> str:
    if not isinstance(remote, dict):
        return ""
    for key in ("redirect", "url", "paymentLink", "paymentUrl", "link"):
        val = str(remote.get(key) or "").strip()
        if val.startswith("http"):
            return val
    nested = remote.get("data")
    if isinstance(nested, dict):
        return _remote_pay_url(nested)
    return ""


def _platega_create(conn, payload_v1, payload_v2):
    last = None
    for path, payload in (
        ("transaction/process", payload_v1),
        ("v2/transaction/process", payload_v2),
    ):
        try:
            remote = _platega_request(conn, "POST", path, payload)
            if _remote_pay_url(remote):
                return remote
            last = RuntimeError("platega empty url via %s" % path)
        except RuntimeError as exc:
            last = exc
            continue
    if last:
        raise last
    return {}


def fetch_transaction(conn, tx_id: str) -> dict:
    tx_id = str(tx_id or "").strip()
    if not tx_id:
        return {}
    try:
        data = _platega_request(conn, "GET", "transaction/" + tx_id)
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        print("platega fetch tx failed", type(exc).__name__, str(exc)[:180])
        return {}


def _resolve_pid(conn, body: dict) -> int:
    pid = int(features.request_project_id() or 0)
    key = str((body or {}).get("project") or (body or {}).get("project_id") or "").strip()
    if not key:
        return pid
    if key.isdigit():
        return int(key)
    row = conn.execute(
        "SELECT id FROM project WHERE lower(domain) = ? OR lower(name) = ? OR id = ?",
        (key.lower(), key.lower(), int(key) if key.isdigit() else -1),
    ).fetchone()
    return int(row["id"]) if row else pid


def create_payment(conn, handler, body: dict) -> tuple[dict, int]:
    body = body if isinstance(body, dict) else {}
    method = parse_method(body)
    if method not in ALLOWED_METHODS:
        return {"ok": False, "error": "method_disabled", "message": "Сейчас можно оплатить только СБП или Crypto."}, 400
    kopecks, rub = parse_amount(body)
    if rub < MIN_RUB:
        return {"ok": False, "error": "amount", "message": "Минимальная сумма — %s ₽." % MIN_RUB}, 400
    if rub > MAX_RUB:
        return {"ok": False, "error": "amount", "message": "Максимальная сумма — %s ₽." % MAX_RUB}, 400
    ensure_schema(conn)
    pid = _resolve_pid(conn, body)
    uid = int(features.request_user_id() or 0)
    if not pid:
        return {"ok": False, "error": "project", "message": "Не выбран проект для пополнения."}, 400
    merchant, secret = _creds(conn)
    if not secret:
        return {"ok": False, "error": "not_configured", "message": "Ключ Platega не задан."}, 503
    if not merchant:
        return {
            "ok": False,
            "error": "need_merchant",
            "message": "В кабинете Platega (Настройки) скопируй Merchant ID — это UUID. Без него платеж не создаётся.",
        }, 400
    features.set_request_project(pid)
    slug = _project_slug(conn, pid)
    order_id = str(uuid.uuid4())
    base = public_base(handler)
    return_url = "%s/%s/settings/billing?platega=%s" % (base, slug, order_id)
    fail_url = "%s/%s/settings/billing?platega_fail=%s" % (base, slug, order_id)
    actor = {}
    try:
        actor = features.request_actor(conn) or {}
    except Exception:
        actor = {}
    user_name = str(actor.get("name") or actor.get("email") or "user-%s" % uid)
    ip = ""
    try:
        import admin_panel
        ip = admin_panel.client_ip(handler) or ""
    except Exception:
        ip = ""
    payload = {
        "paymentMethod": int(method),
        "paymentDetails": {
            "amount": int(rub) if float(rub) == int(rub) else round(float(rub), 2),
            "currency": "RUB",
        },
        "description": "Пополнение RustApp #%s на %s ₽" % (pid, int(rub) if float(rub) == int(rub) else rub),
        "return": return_url,
        "failedUrl": fail_url,
        "payload": order_id,
        "orderId": order_id,
        "metadata": {
            "userId": str(uid or pid),
            "userName": user_name[:80] or ("user-%s" % (uid or pid)),
        },
    }
    payload_v1 = {
        "paymentMethod": int(method),
        "paymentDetails": payload["paymentDetails"],
        "description": payload["description"],
        "return": return_url,
        "failedUrl": fail_url,
        "payload": order_id,
    }
    try:
        remote = _platega_create(conn, payload_v1, payload)
    except RuntimeError as exc:
        msg = str(exc)
        if "timeout" in msg.lower() or "timed out" in msg.lower():
            return {"ok": False, "error": "timeout", "message": "Платёжная система не ответила. Попробуй ещё раз."}, 504
        if "401" in msg:
            return {"ok": False, "error": "auth", "message": "Platega отклонила ключ или Merchant ID. Проверь Настройки в кабинете."}, 401
        short = msg.replace("platega_http_", "Ошибка Platega ").strip()
        if len(short) > 180:
            short = short[:180]
        return {"ok": False, "error": "platega", "message": short or "Platega не создала платёж."}, 502
    if not isinstance(remote, dict):
        remote = {}
    tx_id = str(remote.get("transactionId") or remote.get("id") or "").strip()
    redirect = _remote_pay_url(remote)
    if not redirect:
        return {"ok": False, "error": "platega", "message": "Platega не вернула ссылку на оплату."}, 502
    now = int(time.time() * 1000)
    conn.execute(
        """INSERT INTO platega_payments
           (order_id, transaction_id, project_id, user_id, amount_kopecks, amount_rub, method, status, credited, redirect, payload, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)""",
        (
            order_id,
            tx_id,
            pid,
            uid,
            kopecks,
            rub,
            method,
            str(remote.get("status") or "PENDING"),
            redirect,
            json.dumps({"remote": {"transactionId": tx_id}, "method": method}, ensure_ascii=False),
            now,
        ),
    )
    features.audit(conn, "wallet.platega.create", {"order_id": order_id, "method": method, "amount_rub": rub, "project_id": pid})
    return {
        "ok": True,
        "order_id": order_id,
        "transaction_id": tx_id,
        "redirect": redirect,
        "method": method,
        "amount_rub": rub,
        "status": remote.get("status") or "PENDING",
    }, 200


def save_merchant(conn, handler, body: dict) -> tuple[dict, int]:
    body = body if isinstance(body, dict) else {}
    mid = str(body.get("merchant_id") or body.get("merchantId") or "").strip()
    if not UUID_RE.match(mid):
        return {"ok": False, "error": "merchant", "message": "Merchant ID должен быть UUID из кабинета Platega → Настройки."}, 400
    uid = int(features.request_user_id() or 0)
    if not uid:
        return {"ok": False, "error": "auth", "message": "Войди в аккаунт."}, 401
    row = conn.execute("SELECT is_admin, email FROM users WHERE id = ?", (uid,)).fetchone()
    email = str((row["email"] if row else "") or "").lower()
    admin = bool(row and int(row["is_admin"] or 0))
    if not admin and email != "pcigru@gmail.com":
        return {"ok": False, "error": "forbidden", "message": "Merchant ID может сохранить владелец."}, 403
    ensure_schema(conn)
    data = _read_file()
    data["merchant_id"] = mid
    if not data.get("secret"):
        data["secret"] = _FALLBACK_SECRET
    _write_file(data)
    _set_setting(conn, "platega_merchant_id", mid)
    return {"ok": True, "has_merchant": True}, 200


def _credit_row(conn, row) -> bool:
    if not row:
        return False
    if int(row["credited"] or 0):
        return True
    pid = int(row["project_id"] or 0)
    kopecks = int(row["amount_kopecks"] or 0)
    if not pid or kopecks <= 0:
        return False
    features.set_request_project(pid)
    conn.execute(
        "UPDATE project SET balance = COALESCE(balance, 0) + ? WHERE id = ?",
        (kopecks, pid),
    )
    now = int(time.time() * 1000)
    label = METHOD_LABELS.get(int(row["method"] or 0), "Platega")
    features.add_wallet_op(
        conn,
        kopecks,
        "Пополнение через %s" % label,
        pid,
        now,
    )
    conn.execute(
        "UPDATE platega_payments SET credited = 1, status = 'CONFIRMED', confirmed_at = ? WHERE id = ?",
        (now, int(row["id"])),
    )
    try:
        pname = features._named_project(conn, pid)[1]
        features.notify_transaction("Пополнение баланса", pname, pid, kopecks, True, "platega")
        features.audit(conn, "wallet.platega.confirmed", {"order_id": row["order_id"], "project_id": pid, "amount": kopecks})
        features.try_renew_from_balance(conn)
    except Exception:
        pass
    return True


def apply_confirmed(conn, order_id: str = "", tx_id: str = "") -> dict:
    ensure_schema(conn)
    row = None
    if order_id:
        row = conn.execute("SELECT * FROM platega_payments WHERE order_id = ?", (str(order_id),)).fetchone()
    if row is None and tx_id:
        row = conn.execute("SELECT * FROM platega_payments WHERE transaction_id = ?", (str(tx_id),)).fetchone()
    if row is None:
        return {"ok": False, "error": "not_found"}
    remote = fetch_transaction(conn, str(row["transaction_id"] or tx_id or ""))
    status = str((remote or {}).get("status") or row["status"] or "").upper()
    if status == "CONFIRMED":
        _credit_row(conn, row)
        return {"ok": True, "status": "CONFIRMED", "credited": True, "amount_rub": row["amount_rub"]}
    if status == "CANCELED":
        conn.execute(
            "UPDATE platega_payments SET status = 'CANCELED' WHERE id = ?",
            (int(row["id"]),),
        )
        return {"ok": True, "status": "CANCELED", "credited": False}
    return {"ok": True, "status": status or "PENDING", "credited": bool(int(row["credited"] or 0)), "amount_rub": row["amount_rub"]}


def handle_callback(conn, handler, body: dict) -> tuple[dict, int]:
    body = body if isinstance(body, dict) else {}
    ensure_schema(conn)
    merchant, secret = _creds(conn)
    got_m = _header(handler, "X-MerchantId")
    got_s = _header(handler, "X-Secret")

    def _same(left, right):
        left = str(left or "")
        right = str(right or "")
        if not left or not right or len(left) != len(right):
            return False
        try:
            return hmac.compare_digest(left, right)
        except Exception:
            return False

    if not (_same(got_m, merchant) and _same(got_s, secret)):
        return {"ok": False, "error": "unauthorized"}, 401
    tx_id = str(body.get("id") or body.get("transactionId") or "").strip()
    order_id = str(body.get("payload") or body.get("orderId") or body.get("externalId") or "").strip()
    status = str(body.get("status") or "").upper()
    row = None
    if order_id:
        row = conn.execute("SELECT * FROM platega_payments WHERE order_id = ?", (order_id,)).fetchone()
    if row is None and tx_id:
        row = conn.execute("SELECT * FROM platega_payments WHERE transaction_id = ?", (tx_id,)).fetchone()
    if row is None:
        print("platega callback unknown", tx_id[:40], status)
        return {"ok": True, "ignored": True}, 200
    if tx_id and not str(row["transaction_id"] or ""):
        conn.execute(
            "UPDATE platega_payments SET transaction_id = ? WHERE id = ?",
            (tx_id, int(row["id"])),
        )
    remote = fetch_transaction(conn, tx_id or str(row["transaction_id"] or ""))
    remote_status = str((remote or {}).get("status") or status or "").upper()
    if remote_status == "CONFIRMED" or status == "CONFIRMED":
        _credit_row(conn, row)
        return {"ok": True, "status": "CONFIRMED"}, 200
    if remote_status == "CANCELED" or status == "CANCELED":
        conn.execute(
            "UPDATE platega_payments SET status = 'CANCELED' WHERE id = ?",
            (int(row["id"]),),
        )
        return {"ok": True, "status": "CANCELED"}, 200
    conn.execute(
        "UPDATE platega_payments SET status = ? WHERE id = ?",
        (remote_status or status or "PENDING", int(row["id"])),
    )
    return {"ok": True, "status": remote_status or status or "PENDING"}, 200


def payment_status(conn, params) -> tuple[dict, int]:
    order = ""
    try:
        order = str((params.get("order") or params.get("platega") or [""])[0] or "")
    except Exception:
        order = str((params or {}).get("order") or "")
    order = order.strip()
    if not order:
        return {"ok": False, "error": "order"}, 400
    return apply_confirmed(conn, order_id=order), 200


def return_redirect(params) -> str:
    order = ""
    fail = ""
    try:
        order = str((params.get("platega") or params.get("order") or [""])[0] or "")
        fail = str((params.get("platega_fail") or [""])[0] or "")
    except Exception:
        pass
    q = order or fail
    loc = "/settings/billing"
    if q:
        loc += ("?platega_fail=" if fail and not order else "?platega=") + q
    return loc
