# Serves photos stored in the Postgres `photos` table.
import os
import re
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "_lib"))
import db  # noqa: E402
import util  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            photo_id = util.get_query(self).get("id", "")
            if not re.match(r"^[a-z0-9]+$", photo_id):
                util.send_json(self, 400, {"error": "bad id"})
                return
            row = db.get_photo(photo_id)
            if not row:
                util.send_json(self, 404, {"error": "not found"})
                return
            mime, data = row
            util.send_bytes(self, 200, data, mime, cache=True)
        except db.NotConfigured:
            util.send_json(self, 503, {"error": "store-not-configured"})
        except Exception as e:  # noqa: BLE001
            print("[img error] %s" % e)
            util.send_json(self, 500, {"error": "Внутрішня помилка сервера"})
