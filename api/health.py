# Setup status for the admin panel (booleans/labels only, no secrets).
import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "_lib"))
import db  # noqa: E402
import mail  # noqa: E402
import util  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        util.send_json(
            self,
            200,
            {
                "dev": not util.on_vercel(),
                "store": db.mode(),  # "postgres" | "none"
                "blob": bool(os.environ.get("BLOB_READ_WRITE_TOKEN")),
                "password": bool(util.admin_password()),
                "mail": mail.enabled(),
            },
        )
