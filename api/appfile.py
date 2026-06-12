# Serves candidate-uploaded application files from the database.
# GET (admin only) ?id=<file_id> — returns the file as an attachment.
import os
import re
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "_lib"))
import db  # noqa: E402
import util  # noqa: E402


def _ascii_filename(name):
    """Strip non-ASCII characters so the filename is safe inside an HTTP header."""
    return "".join(c for c in str(name or "file") if ord(c) < 128 and c not in ('"', "\\", "\n", "\r"))


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            if not util.is_authed(self):
                util.send_json(self, 401, {"error": "unauthorized"})
                return
            file_id = util.get_query(self).get("id", "")
            if not re.match(r"^[a-z0-9]+$", file_id):
                util.send_json(self, 400, {"error": "bad id"})
                return
            result = db.get_application_file(file_id)
            if result is None:
                util.send_json(self, 404, {"error": "not found"})
                return
            name, mime, data = result
            safe_name = _ascii_filename(name) or "file"
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Content-Disposition", 'attachment; filename="%s"' % safe_name)
            self.end_headers()
            self.wfile.write(data)
        except db.NotConfigured:
            util.send_json(self, 503, {"error": "store-not-configured"})
        except Exception as e:  # noqa: BLE001
            print("[appfile error] %s" % e)
            util.send_json(self, 500, {"error": "Внутрішня помилка сервера"})
