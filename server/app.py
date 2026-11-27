"""IP receiving and display server.

Receives the public IP POSTed by clients and persists it (SQLite); the home page shows the latest report.

Environment variables:
    APP_TOKEN   Auth token; clients must send it in the X-Auth-Token header. Leave empty to disable checks (local debugging only)
    DB_PATH     SQLite file path, defaults to ./data/ips.db
    PORT        Listen port, defaults to 8000 (only used when running this file directly)
"""

import logging
import os
import sqlite3
from datetime import datetime, timedelta, timezone

from flask import Flask, jsonify, render_template, request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("DB_PATH") or os.path.join(BASE_DIR, "data", "ips.db")
APP_TOKEN = os.environ.get("APP_TOKEN", "").strip()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
log = logging.getLogger("sendip")

app = Flask(__name__)

CST = timezone(timedelta(hours=8))


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
        log.info("已升级 ip_record 表结构为心跳模式（保留原 IP: %s）", old[0] if old else "无")
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
        log.exception("读取数据库失败: %s", exc)
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
    return supplied == APP_TOKEN


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #
@app.route("/")
def index():
    return render_template("index.html", **load_last())


@app.route("/receive-ip", methods=["POST"])
@app.route("/receive_ip", methods=["POST"])  # Legacy route kept for compatibility; remove this line once no old clients remain
def receive_ip():
    if request.path.rstrip("/").endswith("receive_ip"):
        log.warning("收到旧地址 /receive_ip 的请求，已自动兼容，请把客户端改为 /receive-ip")
    if not token_ok():
        log.warning("鉴权失败，来源 %s", request.remote_addr)
        return jsonify(success=False, error="unauthorized"), 401

    data = request.get_json(silent=True) or {}
    ip = (data.get("ip_address") or "").strip()
    if not ip:
        return jsonify(success=False, error="ip_address is required"), 400

    result = save_ip(ip)
    log.info(
        "收到 IP %s（%s）来自 %s",
        ip,
        "IP 已变更" if result["changed"] else "心跳，IP 未变",
        request.remote_addr,
    )
    return jsonify(success=True, **result)


@app.route("/api/last-ip")
def api_last_ip():
    if not token_ok():
        return jsonify(success=False, error="unauthorized"), 401
    return jsonify(success=True, **load_last())


@app.route("/healthz")
def healthz():
    return jsonify(status="ok")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    # 0.0.0.0 is required for access from outside the container or through a reverse proxy; gunicorn is recommended in production
    app.run(host="0.0.0.0", port=port, debug=False)
