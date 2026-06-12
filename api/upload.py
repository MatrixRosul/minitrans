# Photo upload (admin only). Priority:
#   1. Vercel Blob (BLOB_READ_WRITE_TOKEN set)
#   2. Postgres `photos` table, served back via /api/img?id=...
import json
import os
import random
import re
import string
import sys
import time
import urllib.request
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "_lib"))
import db  # noqa: E402
import util  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            if not util.is_authed(self):
                util.send_json(self, 401, {"error": "unauthorized"})
                return
            q = util.get_query(self)
            mime = q.get("type") if re.match(r"^image/[\w.+-]+$", q.get("type", "")) else "image/jpeg"
            safe_name = re.sub(r"[^a-z0-9._-]+", "-", (q.get("name") or "photo.jpg").lower())[-60:] or "photo.jpg"

            data = util.read_body(self)
            if not data:
                util.send_json(self, 400, {"error": "порожній файл"})
                return
            if len(data) > 4 * 1024 * 1024:
                util.send_json(self, 413, {"error": "файл завеликий (макс 4МБ)"})
                return

            blob_token = os.environ.get("BLOB_READ_WRITE_TOKEN")
            if blob_token:
                pathname = "sales/%x-%s" % (int(time.time() * 1000), safe_name)
                req = urllib.request.Request(
                    "https://blob.vercel-storage.com/" + pathname,
                    data=data,
                    method="PUT",
                    headers={"authorization": "Bearer " + blob_token, "x-content-type": mime},
                )
                with urllib.request.urlopen(req, timeout=30) as r:
                    util.send_json(self, 200, {"url": json.loads(r.read().decode())["url"]})
                return

            if db.mode() != "none":
                if len(data) > 1536 * 1024:
                    util.send_json(self, 413, {"error": "фото завелике (макс ~1.5МБ)"})
                    return
                photo_id = "%x%s" % (
                    int(time.time() * 1000),
                    "".join(random.choices(string.ascii_lowercase + string.digits, k=6)),
                )
                db.insert_photo(photo_id, mime, data)
                util.send_json(self, 200, {"url": "/api/img?id=" + photo_id})
                return

            util.send_json(self, 503, {"error": "сховище фото не налаштовано"})
        except db.NotConfigured:
            util.send_json(self, 503, {"error": "store-not-configured"})
        except Exception as e:  # noqa: BLE001
            print("[upload error] %s" % e)
            util.send_json(self, 500, {"error": "Внутрішня помилка сервера"})
