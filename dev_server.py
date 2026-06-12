#!/usr/bin/env python3
"""Local dev server: static files + /api/* (the same handler classes Vercel runs).

Run:   .venv/bin/python3 dev_server.py        (port 8080)
Admin: http://localhost:8080/admin.html, dev password: minitrans
DB:    postgres://<you>@127.0.0.1:5432/minitrans (browse it with pgAdmin)
"""
import importlib.util
import os
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, unquote

ROOT = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("PORT", "8080"))

MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".xml": "application/xml",
    ".txt": "text/plain; charset=utf-8",
    ".pdf": "application/pdf",
}

_api_cache = {}


def load_api(name):
    if name not in _api_cache:
        path = os.path.join(ROOT, "api", name + ".py")
        if not os.path.isfile(path):
            _api_cache[name] = None
        else:
            spec = importlib.util.spec_from_file_location("api_" + name, path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            _api_cache[name] = mod.handler
    return _api_cache[name]


class DevHandler(BaseHTTPRequestHandler):
    def _route(self):
        path = unquote(urlsplit(self.path).path)

        if path.startswith("/api/"):
            name = re.sub(r"[^a-zA-Z0-9_-]", "", path[5:])
            cls = load_api(name)
            if cls is None:
                return self._plain(404, "no such api")
            method = getattr(cls, "do_" + self.command, None)
            if method is None:
                return self._plain(405, "method not allowed")
            return method(self)  # api handlers share the BaseHTTPRequestHandler interface

        if self.command != "GET":
            return self._plain(405, "method not allowed")
        if path == "/":
            path = "/index.html"
        file = os.path.normpath(os.path.join(ROOT, path.lstrip("/")))
        if not file.startswith(ROOT) or not os.path.isfile(file):
            return self._plain(404, "not found")
        with open(file, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", MIME.get(os.path.splitext(file)[1].lower(), "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _plain(self, status, text):
        body = text.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _safe(self):
        try:
            self._route()
        except Exception as e:  # noqa: BLE001
            try:
                self._plain(500, "dev-server error: %s" % e)
            except Exception:
                pass

    do_GET = _safe
    do_POST = _safe
    do_PUT = _safe
    do_DELETE = _safe

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (self.command, self.path))


if __name__ == "__main__":
    print("minitrans dev server: http://localhost:%d  (admin: /admin.html, пароль: minitrans)" % PORT)
    ThreadingHTTPServer(("0.0.0.0", PORT), DevHandler).serve_forever()
