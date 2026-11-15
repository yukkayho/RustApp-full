#!/usr/bin/env python3
"""WSGI entry for Spaceship / cPanel (Phusion Passenger).

Do not run server.py on shared hosting. Passenger loads `application`.
"""

from __future__ import annotations

import os
import sys
import traceback
from io import BytesIO

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
os.chdir(HERE)
os.environ["CHECKAPP_WSGI"] = "1"

from server import Handler  # noqa: E402


class _Sock:
    def __init__(self, raw: bytes):
        self._in = BytesIO(raw)
        self._out = BytesIO()

    def makefile(self, mode="rb", *args, **kwargs):
        if "w" in str(mode):
            return self._out
        return self._in

    def sendall(self, data):
        self._out.write(data)

    def close(self):
        pass

    def setsockopt(self, *args, **kwargs):
        pass

    def shutdown(self, *args, **kwargs):
        pass

    def fileno(self):
        return -1


class _Server:
    server_name = "checkapp"
    server_port = 443
    timeout = None


_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}


def _request_bytes(environ) -> bytes:
    headers = []
    seen = set()
    for key, val in environ.items():
        if not key.startswith("HTTP_") or not val:
            continue
        name = key[5:].replace("_", "-")
        headers.append("%s: %s" % (name, val))
        seen.add(name.lower())
    if environ.get("CONTENT_TYPE") and "content-type" not in seen:
        headers.append("Content-Type: %s" % environ["CONTENT_TYPE"])
    clen = str(environ.get("CONTENT_LENGTH") or "0")
    if "content-length" not in seen:
        headers.append("Content-Length: %s" % clen)
    if environ.get("wsgi.url_scheme") == "https" and "x-forwarded-proto" not in seen:
        headers.append("X-Forwarded-Proto: https")
    if "host" not in seen:
        host = environ.get("HTTP_HOST") or environ.get("SERVER_NAME") or "localhost"
        headers.append("Host: %s" % host)
    method = environ.get("REQUEST_METHOD") or "GET"
    path = environ.get("PATH_INFO") or "/"
    if not path.startswith("/"):
        path = "/" + path
    qs = environ.get("QUERY_STRING") or ""
    uri = path + (("?" + qs) if qs else "")
    try:
        length = int(clen or 0)
    except Exception:
        length = 0
    body = b""
    if length > 0:
        body = environ["wsgi.input"].read(length)
    head = "%s %s HTTP/1.1\r\n%s\r\n\r\n" % (method, uri, "\r\n".join(headers))
    return head.encode("latin-1", "replace") + body


def application(environ, start_response):
    try:
        sock = _Sock(_request_bytes(environ))
        addr = (environ.get("REMOTE_ADDR") or "127.0.0.1", 0)
        Handler(sock, addr, _Server())
        raw = sock._out.getvalue()
        sep = raw.find(b"\r\n\r\n")
        if sep < 0:
            start_response("500 Internal Server Error", [("Content-Type", "text/plain")])
            return [b"empty response"]
        head, body = raw[:sep], raw[sep + 4 :]
        lines = head.decode("latin-1", "replace").split("\r\n")
        status = lines[0].split(" ", 1)[1] if lines and " " in lines[0] else "200 OK"
        out = []
        for line in lines[1:]:
            if ":" not in line:
                continue
            name, value = line.split(":", 1)
            if name.strip().lower() in _HOP:
                continue
            out.append((name.strip(), value.strip()))
        start_response(status, out)
        return [body]
    except Exception:
        traceback.print_exc()
        start_response("500 Internal Server Error", [("Content-Type", "text/plain; charset=utf-8")])
        return [b"RustApp failed to handle this request. See the Python app error log."]
