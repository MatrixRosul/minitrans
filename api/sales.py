import os
import random
import string
import sys
import time
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "_lib"))
import db  # noqa: E402
import util  # noqa: E402

STATUSES = ("available", "reserved", "sold")


def _clean(b):
    images = b.get("images")
    return {
        "title": str(b.get("title") or "").strip(),
        "specs": str(b.get("specs") or "").strip(),
        "desc": str(b.get("desc") or "").strip(),
        "price": str(b.get("price") or "").strip(),
        "status": b.get("status") if b.get("status") in STATUSES else "available",
        "hidden": bool(b.get("hidden")),
        "images": [x for x in images if isinstance(x, str) and len(x) < 500][:12]
        if isinstance(images, list)
        else [],
    }


def _new_id():
    alphabet = string.ascii_lowercase + string.digits
    return "%x%s" % (int(time.time() * 1000), "".join(random.choices(alphabet, k=6)))


def _guard(fn):
    def wrapped(self):
        try:
            fn(self)
        except db.NotConfigured:
            util.send_json(self, 503, {"error": "store-not-configured"})
        except Exception as e:  # noqa: BLE001 — log details, never leak them
            print("[sales error] %s: %s" % (fn.__name__, e))
            util.send_json(self, 500, {"error": "Внутрішня помилка сервера"})

    return wrapped


class handler(BaseHTTPRequestHandler):
    @_guard
    def do_GET(self):
        if db.mode() == "none":
            util.send_json(self, 503, {"error": "store-not-configured"})
            return
        post_id = util.get_query(self).get("id")
        if post_id:
            post = db.get_post(post_id)
            if not post or (post["hidden"] and not util.is_authed(self)):
                util.send_json(self, 404, {"error": "not found"})
                return
            util.send_json(self, 200, {"post": post})
            return
        posts = db.list_posts()
        if not util.is_authed(self):
            posts = [p for p in posts if not p["hidden"]]
        util.send_json(self, 200, {"posts": posts})

    @_guard
    def do_POST(self):
        if not util.is_authed(self):
            util.send_json(self, 401, {"error": "unauthorized"})
            return
        body = _clean(util.read_json(self))
        if not body["title"]:
            util.send_json(self, 400, {"error": "Вкажіть назву"})
            return
        post = dict(body, id=_new_id(), createdAt=db.now_ms())
        db.insert_post(post)
        util.send_json(self, 200, {"post": post})

    @_guard
    def do_PUT(self):
        if not util.is_authed(self):
            util.send_json(self, 401, {"error": "unauthorized"})
            return
        body = util.read_json(self)
        post_id = body.get("id") or util.get_query(self).get("id")
        current = db.get_post(post_id) if post_id else None
        if not current:
            util.send_json(self, 404, {"error": "not found"})
            return
        merged = dict(current)
        merged.update(body)
        nxt = _clean(merged)
        if not nxt["title"]:
            util.send_json(self, 400, {"error": "Вкажіть назву"})
            return
        post = dict(nxt, id=current["id"], createdAt=current["createdAt"])
        db.update_post(post)
        util.send_json(self, 200, {"post": post})

    @_guard
    def do_DELETE(self):
        if not util.is_authed(self):
            util.send_json(self, 401, {"error": "unauthorized"})
            return
        post_id = util.get_query(self).get("id")
        if not post_id or not db.delete_post(post_id):
            util.send_json(self, 404, {"error": "not found"})
            return
        util.send_json(self, 200, {"ok": True})
