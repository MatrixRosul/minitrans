# Shared helpers for api/ functions (Vercel Python runtime + dev_server.py).
import hashlib
import hmac
import json
import os
import time
from http.cookies import SimpleCookie
from urllib.parse import urlsplit, parse_qsl

MAX_BODY = 6 * 1024 * 1024


def on_vercel():
    return bool(os.environ.get("VERCEL"))


def admin_password():
    return os.environ.get("ADMIN_PASSWORD") or ("" if on_vercel() else "minitrans")


_derived_secret = None


def _secret():
    """Signing key. Best: dedicated high-entropy ADMIN_SECRET. If only
    ADMIN_PASSWORD is set, stretch it with PBKDF2 so cancel tokens can't be
    used as a cheap offline oracle for the password. On Vercel with neither
    env set returns None — no token can be minted or validated."""
    global _derived_secret
    if _derived_secret is not None:
        return _derived_secret
    explicit = os.environ.get("ADMIN_SECRET")
    if explicit:
        _derived_secret = explicit.encode()
        return _derived_secret
    password = os.environ.get("ADMIN_PASSWORD")
    if password:
        _derived_secret = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), b"minitrans-signing-v1", 200_000
        )
        return _derived_secret
    if on_vercel():
        return None  # unconfigured — auth impossible by design
    _derived_secret = b"minitrans-dev-secret"
    return _derived_secret


def _sign(s):
    secret = _secret()
    if secret is None:
        return None
    return hmac.new(secret, s.encode(), hashlib.sha256).hexdigest()


def make_token():
    exp = int(time.time() * 1000) + 7 * 24 * 3600 * 1000
    sig = _sign("admin:%d" % exp)
    return "%d.%s" % (exp, sig) if sig else ""


def check_token(token):
    if not token or "." not in token:
        return False
    exp, sig = token.split(".", 1)
    if not exp.isdigit() or int(exp) < time.time() * 1000:
        return False
    want = _sign("admin:" + exp)
    return bool(want) and hmac.compare_digest(sig, want)


def get_cookies(h):
    c = SimpleCookie()
    c.load(h.headers.get("Cookie", "") or "")
    return {k: v.value for k, v in c.items()}


def is_authed(h):
    return check_token(get_cookies(h).get("admin_session"))


def cancel_token(booking_id):
    sig = _sign("cancel:" + booking_id)
    return sig[:32] if sig else ""


def check_cancel_token(booking_id, token):
    want = cancel_token(booking_id)
    return bool(token) and bool(want) and len(token) == len(want) and hmac.compare_digest(token, want)


def base_url(h):
    host = h.headers.get("Host") or "minitrans.uz.ua"
    scheme = "https" if on_vercel() else "http"
    return "%s://%s" % (scheme, host)


def session_cookie(clear=False):
    if clear:
        return "admin_session=; Path=/; HttpOnly; Max-Age=0"
    parts = [
        "admin_session=" + make_token(),
        "Path=/",
        "HttpOnly",
        "SameSite=Lax",
        "Max-Age=%d" % (7 * 24 * 3600),
    ]
    if on_vercel():
        parts.append("Secure")
    return "; ".join(parts)


def get_query(h):
    return dict(parse_qsl(urlsplit(h.path).query))


def read_body(h):
    try:
        length = int(h.headers.get("Content-Length") or 0)
    except ValueError:
        length = 0
    if length <= 0:
        return b""
    if length > MAX_BODY:
        raise ValueError("body too large")
    return h.rfile.read(length)


def read_json(h):
    try:
        return json.loads(read_body(h).decode("utf-8") or "{}")
    except Exception:
        return {}


def send_json(h, status, obj, extra_headers=None):
    body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    h.send_response(status)
    h.send_header("Content-Type", "application/json; charset=utf-8")
    h.send_header("Content-Length", str(len(body)))
    for k, v in (extra_headers or {}).items():
        h.send_header(k, v)
    h.end_headers()
    h.wfile.write(body)


def send_bytes(h, status, data, content_type, cache=False):
    h.send_response(status)
    h.send_header("Content-Type", content_type)
    h.send_header("Content-Length", str(len(data)))
    if cache:
        h.send_header("Cache-Control", "public, max-age=31536000, immutable")
    h.end_headers()
    h.wfile.write(data)
