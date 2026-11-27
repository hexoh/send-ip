"""IP receiving and display server.

Receives the public IP POSTed by clients and persists it (SQLite); the home page shows the latest report.

Environment variables:
    APP_TOKEN   Auth token; clients must send it in the X-Auth-Token header. Leave empty to disable checks (local debugging only)
    APP_PASSWORD  Password for the web page. Leave empty to keep the page public (not recommended)
    SECRET_KEY  Key used to sign session cookies; auto-generated into <DB dir>/secret.key when empty
    COOKIE_SECURE  Set to 1 when the site is served over HTTPS so the session cookie is Secure-only
    DB_PATH     SQLite file path, defaults to ./data/ips.db
    PORT        Listen port, defaults to 8000 (only used when running this file directly)
"""

import hmac
import ipaddress
import logging
import os
import secrets
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone

from flask import Flask, jsonify, redirect, render_template, request, session

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("DB_PATH") or os.path.join(BASE_DIR, "data", "ips.db")
APP_TOKEN = os.environ.get("APP_TOKEN", "").strip()
# Any string works as the password; only the outermost spaces are trimmed so an accidentally
# padded line in the env file does not lock the owner out.
APP_PASSWORD = os.environ.get("APP_PASSWORD", "").strip()
PAGE_LOCKED = bool(APP_PASSWORD)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
log = logging.getLogger("sendip")


def env_int(name, default):
    """Read a positive integer from the environment, falling back to the default on junk."""
    try:
        value = int(os.environ.get(name, "").strip())
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "").strip().lower() in ("1", "true", "yes", "on")
SESSION_DAYS = env_int("SESSION_DAYS", 7)
LOGIN_MAX_FAILS = env_int("LOGIN_MAX_FAILS", 5)
LOGIN_LOCK_SECONDS = env_int("LOGIN_LOCK_SECONDS", 600)


def load_secret_key():
    """Return the key that signs session cookies.

    Reuse SECRET_KEY when given; otherwise create <DB dir>/secret.key once (mode 600) so that
    session cookies survive a restart and every gunicorn worker signs them the same way.
    """
    given = os.environ.get("SECRET_KEY", "").strip()
    if given:
        return given

    path = os.path.join(os.path.dirname(DB_PATH) or ".", "secret.key")

    def read():
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return fh.read().strip()
        except OSError:
            return ""

    saved = read()
    if saved:
        return saved

    key = secrets.token_hex(32)
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        # O_EXCL: with several workers starting at once, exactly one creates the file and the
        # others read it back. Writing to a shared name with O_TRUNC would let two workers
        # overwrite each other and sign cookies differently.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        for _ in range(20):  # the winner may still be writing; give it a moment
            saved = read()
            if saved:
                return saved
            time.sleep(0.05)
        log.warning("Session key file %s is empty; using a per-process key", path)
        return key
    except OSError as exc:
        log.warning("Could not save the session key (%s); sessions will be lost on restart", exc)
        return key

    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(key + "\n")
    log.info("Created a session key at %s", path)
    return key


app = Flask(__name__)

app.config.update(
    SECRET_KEY=load_secret_key(),
    SESSION_COOKIE_HTTPONLY=True,   # JS must not be able to read the cookie
    SESSION_COOKIE_SAMESITE="Lax",  # keeps the cookie off cross-site POSTs
    SESSION_COOKIE_SECURE=COOKIE_SECURE,
    PERMANENT_SESSION_LIFETIME=timedelta(days=SESSION_DAYS),
)

if not PAGE_LOCKED:
    log.warning("APP_PASSWORD is empty: the page is public and anyone can read the IP. Set it in production")
elif APP_PASSWORD in ("please-change-me-to-a-long-random-password", "changeme", "password"):
    log.warning("APP_PASSWORD is still the example value from .env.example; set your own before exposing the page")

CST = timezone(timedelta(hours=8))

SUPPORTED_LANGS = ("en", "zh")
DEFAULT_LANG = "en"


# --------------------------------------------------------------------------- #
# Storage layer
# --------------------------------------------------------------------------- #
def get_db():
    """Open a connection and ensure the table exists. SQLite supports multi-process/threaded reads, so it works with multiple gunicorn workers."""
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ip_record (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            ip         TEXT NOT NULL,
            first_seen TEXT NOT NULL,
            last_seen  TEXT NOT NULL
        )
        """
    )
    # Compatible with the early single-column updated_at schema: rebuild the table but keep the last IP so the page does not go blank after upgrade
    cols = {row[1] for row in conn.execute("PRAGMA table_info(ip_record)")}
    if "last_seen" not in cols:
        old = None
        if "updated_at" in cols:
            old = conn.execute(
                "SELECT ip, updated_at FROM ip_record ORDER BY id DESC LIMIT 1"
            ).fetchone()
        conn.execute("DROP TABLE ip_record")
        conn.execute(
            """
            CREATE TABLE ip_record (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                ip         TEXT NOT NULL,
                first_seen TEXT NOT NULL,
                last_seen  TEXT NOT NULL
            )
            """
        )
        if old and old[0]:
            conn.execute(
                "INSERT INTO ip_record (ip, first_seen, last_seen) VALUES (?, ?, ?)",
                (old[0], old[1], old[1]),
            )
        conn.commit()
        log.info("Upgraded ip_record schema to heartbeat mode (kept IP: %s)", old[0] if old else "none")
    return conn


def save_ip(ip):
    """Record one report.

    When the IP changes, insert a new record and reset first_seen; when unchanged, only refresh
    last_seen (heartbeat). Keep only the latest row to prevent table growth.
    """
    now = datetime.now(CST).isoformat(timespec="seconds")
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT ip, first_seen FROM ip_record ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row and row[0] == ip:
            with conn:
                conn.execute("UPDATE ip_record SET last_seen = ?", (now,))
            return {
                "ip": ip,
                "first_seen": row[1],
                "last_seen": now,
                "changed": False,
            }

        with conn:
            conn.execute("DELETE FROM ip_record")
            conn.execute(
                "INSERT INTO ip_record (ip, first_seen, last_seen) VALUES (?, ?, ?)",
                (ip, now, now),
            )
        return {"ip": ip, "first_seen": now, "last_seen": now, "changed": True}
    finally:
        conn.close()
    return now


def load_last():
    try:
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT ip, first_seen, last_seen FROM ip_record ORDER BY id DESC LIMIT 1"
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        log.exception("Failed to read database: %s", exc)
        return {"ip": None, "first_seen": None, "last_seen": None}
    if not row:
        return {"ip": None, "first_seen": None, "last_seen": None}
    return {"ip": row[0], "first_seen": row[1], "last_seen": row[2]}


# --------------------------------------------------------------------------- #
# Authentication
# --------------------------------------------------------------------------- #
def token_ok():
    if not APP_TOKEN:
        return True
    supplied = request.headers.get("X-Auth-Token") or request.args.get("token", "")
    return hmac.compare_digest(supplied.encode("utf-8"), APP_TOKEN.encode("utf-8"))


# --------------------------------------------------------------------------- #
# Page password
# --------------------------------------------------------------------------- #
# Wrong-password counter, per client IP. In memory on purpose: no extra dependency and no
# write on the hot path. Each gunicorn worker keeps its own table, so the effective limit is
# LOGIN_MAX_FAILS per worker; that is plenty for a long password (see DEPLOY.md).
_attempts = {}
_attempts_lock = threading.Lock()


def client_ip():
    """Real visitor address, used as the key for the login limiter.

    Directly exposed (public peer): the peer address is the truth and no header is trusted.
    Behind a local proxy: Nginx appends the address it saw with $proxy_add_x_forwarded_for, so the
    LAST entry is trustworthy — anything the client sent itself only ends up in front of it.
    """
    peer = request.remote_addr or "-"
    try:
        addr = ipaddress.ip_address(peer)
        local_proxy = addr.is_private or addr.is_loopback
    except ValueError:
        local_proxy = False
    if not local_proxy:
        return peer
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return peer


def page_unlocked():
    return not PAGE_LOCKED or bool(session.get("authed"))


def lock_seconds_left(ip):
    """Seconds the caller still has to wait, or 0 when it may try again."""
    now = time.monotonic()
    with _attempts_lock:
        state = _attempts.get(ip)
        if not state:
            return 0
        if state["until"] > now:
            return int(state["until"] - now) + 1
        if state["until"]:  # a previous lock has expired: start counting from zero
            _attempts.pop(ip, None)
        return 0


def note_failure(ip):
    """Record one wrong password and return the lockout length it just triggered (0 if none)."""
    now = time.monotonic()
    with _attempts_lock:
        if len(_attempts) > 4096:  # keep a flood of spoofed addresses from growing the dict
            for key in [k for k, v in _attempts.items() if v["until"] <= now]:
                _attempts.pop(key, None)
        state = _attempts.setdefault(ip, {"fails": 0, "until": 0.0})
        state["fails"] += 1
        if state["fails"] >= LOGIN_MAX_FAILS:
            state["fails"] = 0
            state["until"] = now + LOGIN_LOCK_SECONDS
            return LOGIN_LOCK_SECONDS
        return 0


def note_success(ip):
    with _attempts_lock:
        _attempts.pop(ip, None)


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #
def detect_lang():
    """Pick the page language: ?lang= / the posted form wins, then Accept-Language, then English."""
    requested = (request.values.get("lang") or "").strip().lower()
    if requested.startswith("zh"):
        return "zh"
    if requested.startswith("en"):
        return "en"
    return request.accept_languages.best_match(SUPPORTED_LANGS) or DEFAULT_LANG


def render_page(unlocked, error=None, status=200):
    """Render the card. The IP is only read from the database when the visitor is allowed to see it."""
    data = load_last() if unlocked else {"ip": None, "first_seen": None, "last_seen": None}
    body = render_template(
        "index.html", lang=detect_lang(), authed=unlocked, error=error, **data
    )
    return body, status


@app.route("/")
def index():
    return render_page(unlocked=page_unlocked())


@app.route("/login", methods=["POST"])
def login():
    if not PAGE_LOCKED:
        return redirect("./", code=303)

    ip = client_ip()
    left = lock_seconds_left(ip)
    if left:
        log.warning("Password entry blocked for %s, %ss left on the lockout", ip, left)
        body, status = render_page(unlocked=False, error="tooManyAttempts", status=429)
        return body, status, {"Retry-After": str(left)}

    # Compare bytes so non-ASCII passwords work; compare_digest keeps the check time-constant.
    supplied = request.form.get("password", "")
    if hmac.compare_digest(supplied.encode("utf-8"), APP_PASSWORD.encode("utf-8")):
        note_success(ip)
        session.permanent = True
        session["authed"] = True
        log.info("Page unlocked from %s", ip)
        # 303 + relative Location: works both at the site root and under a sub-path such as /ip/
        return redirect(f"./?lang={detect_lang()}", code=303)

    locked_for = note_failure(ip)
    if locked_for:
        log.warning("Wrong page password from %s; locked for %ss", ip, locked_for)
    else:
        log.warning("Wrong page password from %s", ip)
    return render_page(unlocked=False, error="wrongPassword", status=401)


@app.route("/logout", methods=["POST"])
def logout():
    if session.get("authed"):
        log.info("Page locked again (logout from %s)", client_ip())
    session.clear()
    return redirect("./", code=303)


@app.after_request
def no_shared_cache(response):
    """The page body depends on Accept-Language / ?lang=, and the data is live.

    Without Vary, a CDN or reverse proxy could serve the English page to Chinese visitors
    (or a stale IP for hours), so keep it out of shared caches entirely.
    """
    if request.endpoint in ("index", "login"):
        response.headers["Vary"] = "Accept-Language"
        response.headers["Cache-Control"] = "no-store"
    return response


@app.route("/receive-ip", methods=["POST"])
def receive_report():
    if not token_ok():
        log.warning("Authentication failed from %s", request.remote_addr)
        return jsonify(success=False, error="unauthorized"), 401

    data = request.get_json(silent=True) or {}
    ip = (data.get("ip_address") or "").strip()
    if not ip:
        return jsonify(success=False, error="ip_address is required"), 400

    result = save_ip(ip)
    log.info(
        "Received IP %s (%s) from %s",
        ip,
        "IP changed" if result["changed"] else "heartbeat, IP unchanged",
        request.remote_addr,
    )
    return jsonify(success=True, **result)


@app.route("/api/last-ip")
def api_last_ip():
    # The JSON carries the same IP as the page, so it needs the same gate: a browser session
    # or a configured APP_TOKEN. With no APP_TOKEN at all, a page password alone still locks it.
    if not (page_unlocked() or (APP_TOKEN and token_ok())):
        return jsonify(success=False, error="unauthorized"), 401
    return jsonify(success=True, **load_last())


@app.route("/healthz")
def healthz():
    return jsonify(status="ok")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    # 0.0.0.0 is required for access from outside the container or through a reverse proxy; gunicorn is recommended in production
    app.run(host="0.0.0.0", port=port, debug=False)
