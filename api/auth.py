import hmac
import os
import sys
import time
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "_lib"))
import util  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        util.send_json(self, 200, {"authed": util.is_authed(self)})

    def do_POST(self):
        password = util.admin_password()
        if not password:
            util.send_json(self, 503, {"error": "ADMIN_PASSWORD не налаштовано"})
            return
        body = util.read_json(self)
        given = str(body.get("password") or "")
        if not hmac.compare_digest(given, password):
            time.sleep(1.5)  # slow down brute force on the shared password
            util.send_json(self, 401, {"error": "Невірний пароль"})
            return
        util.send_json(self, 200, {"ok": True}, {"Set-Cookie": util.session_cookie()})

    def do_DELETE(self):
        util.send_json(self, 200, {"ok": True}, {"Set-Cookie": util.session_cookie(clear=True)})
