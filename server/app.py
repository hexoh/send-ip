"""IP 接收与展示服务端。

接收客户端 POST 上来的公网 IP 并持久化（SQLite），首页展示最后一次上报结果。

环境变量：
    APP_TOKEN   鉴权令牌，客户端需在请求头 X-Auth-Token 中携带。留空则不校验（仅本机调试用）
    DB_PATH     SQLite 文件路径，默认 ./data/ips.db
    PORT        监听端口，默认 8000（仅直接运行本文件时生效）
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
# 存储层
# --------------------------------------------------------------------------- #
def get_db():
    """建立连接并确保表存在。SQLite 支持多进程/多线程读，gunicorn 多 worker 下可用。"""
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
    # 兼容早期的单列 updated_at 结构：重建表但保留最后一条 IP，避免升级后页面变空
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
    """记录一次上报。

    IP 变化时换新记录并重置 first_seen；IP 未变只刷新 last_seen（心跳）。
    只保留最新一条，避免表膨胀。
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
# 鉴权
# --------------------------------------------------------------------------- #
def token_ok():
    if not APP_TOKEN:
        return True
    supplied = request.headers.get("X-Auth-Token") or request.args.get("token", "")
    return supplied == APP_TOKEN


# --------------------------------------------------------------------------- #
# 路由
# --------------------------------------------------------------------------- #
@app.route("/")
def index():
    return render_template("index.html", **load_last())


@app.route("/receive-ip", methods=["POST"])
@app.route("/receive_ip", methods=["POST"])  # 兼容旧地址，确认没有旧客户端后删掉这一行
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
    # 0.0.0.0 才能被容器外部或反向代理访问；生产环境建议用 gunicorn 启动
    app.run(host="0.0.0.0", port=port, debug=False)
