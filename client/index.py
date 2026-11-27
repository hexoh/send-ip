"""Public IP reporting client.

Run it persistently on the machine whose IP should be tracked: by default it looks up the
local public IP once an hour and reports it to the server. Home broadband IPs usually only
change on PPPoE re-dial or device reboot, so 1 hour is enough; lower it to 600 seconds if
you need to detect changes faster.

Usage:
    python index.py --domain https://ip.example.com/receive-ip --token <TOKEN> --interval 3600

Can also be configured with the SENDIP_DOMAIN / SENDIP_TOKEN / SENDIP_INTERVAL environment variables.
"""

import argparse
import logging
import os
import signal
import sys
import time
from urllib.parse import urlsplit, urlunsplit

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("sendip-agent")

# Multiple IP lookup sources, tried in order as fallbacks so one dead service cannot break reporting
IP_LOOKUP_URLS = (
    "https://ipinfo.io/ip",
    "https://api.ipify.org",
    "https://ifconfig.me/ip",
)

TIMEOUT = 10

# Route on the server that receives reports
RECEIVE_PATH = "receive-ip"

_running = True


def normalize_domain(raw):
    """Normalize the user-provided address into the actual reporting URL.

    The most common mistake is entering the page address (e.g. https://ip.example.com/ip/),
    which returns 405 when POSTed to the page route. Here a "base address ending in /" gets
    receive-ip appended automatically.
    """
    url = (raw or "").strip()
    if not url:
        return url
    parts = urlsplit(url)
    path = parts.path or "/"
    if path.rstrip("/").endswith(RECEIVE_PATH):
        return url
    # Automatically correct the legacy underscore address receive_ip to receive-ip
    if path.rstrip("/").endswith("receive_ip"):
        fixed = urlunsplit(
            (parts.scheme, parts.netloc, path.replace("receive_ip", "receive-ip"), parts.query, "")
        )
        log.warning("检测到旧地址写法，已自动纠正为 %s（原为 %s）", fixed, url)
        return fixed
    # Only append automatically when it clearly looks like a "base address", to avoid breaking custom routes
    if path.endswith("/"):
        new_path = path + RECEIVE_PATH
    else:
        log.warning(
            "上报地址路径不是 /%s 结尾（%s），将按原样使用；"
            "若收到 405/404，请确认地址形如 https://域名/%s",
            RECEIVE_PATH,
            path,
            RECEIVE_PATH,
        )
        return url
    fixed = urlunsplit((parts.scheme, parts.netloc, new_path, parts.query, ""))
    log.warning("上报地址已自动补全为 %s（原为 %s）", fixed, url)
    return fixed


def _handle_stop(signum, frame):
    global _running
    _running = False
    log.info("收到信号 %s，准备退出", signum)


def get_public_ip():
    for url in IP_LOOKUP_URLS:
        try:
            resp = requests.get(url, timeout=TIMEOUT)
            if resp.status_code == 200:
                ip = resp.text.strip()
                if ip:
                    log.info("查询到公网 IP: %s (来源 %s)", ip, url)
                    return ip
            log.warning("查询 %s 返回状态码 %s", url, resp.status_code)
        except requests.RequestException as exc:
            log.warning("查询 %s 失败: %s", url, exc)
    log.error("所有 IP 查询源均失败")
    return None


def send_ip(ip, domain, token):
    """Report once.

    Returns (success, ip_changed, http_status, failure_reason).
    failure_reason values: wrong_url / notfound / auth / other / None.
    """
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-Auth-Token"] = token
    try:
        resp = requests.post(
            domain, json={"ip_address": ip}, headers=headers, timeout=TIMEOUT
        )
        code = resp.status_code

        if code == 200:
            try:
                payload = resp.json()
            except ValueError:
                payload = None
            # Some misconfigurations 301-redirect to the page and then return 200 HTML; do not treat that as success
            if not isinstance(payload, dict) or payload.get("success") is not True:
                log.error(
                    "上报失败：返回 200 但不是接口响应（很可能被重定向到了页面）。地址：%s",
                    domain,
                )
                return False, None, code, "wrong_url"
            return True, bool(payload.get("changed")), code, None

        if code == 405:
            log.error(
                "上报失败：405 Method Not Allowed —— 地址填成了页面地址。"
                "当前 %s，正确形式应为 %s/%s",
                domain,
                domain.rstrip("/"),
                RECEIVE_PATH,
            )
            return False, None, code, "wrong_url"
        if code == 404:
            log.error(
                "上报失败：404 Not Found —— 服务端没有该路由。检查 Nginx 是否代理了该路径前缀，"
                "或地址是否为 %s/%s",
                domain.rstrip("/"),
                RECEIVE_PATH,
            )
            return False, None, code, "notfound"
        if code == 401:
            log.error("上报失败：401 —— 令牌不对，核对客户端的 --token 与服务端 APP_TOKEN")
            return False, None, code, "auth"

        log.error("上报失败，状态码 %s，响应 %s", code, resp.text[:200])
        return False, None, code, "other"
    except requests.RequestException as exc:
        log.error("上报请求异常: %s", exc)
    return False, None, None, "other"


def parse_args():
    parser = argparse.ArgumentParser(description="定时上报公网 IP 到服务端")
    parser.add_argument(
        "--domain",
        default=os.environ.get("SENDIP_DOMAIN", ""),
        help="服务端接收地址，如 https://ip.example.com/receive-ip"
        "（若填成以 / 结尾的基础地址，会自动补上 receive-ip）",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("SENDIP_TOKEN", ""),
        help="与服务端一致的鉴权令牌",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=int(os.environ.get("SENDIP_INTERVAL", "3600")),
        help="上报间隔秒数，默认 3600（1 小时）。家宽可 3600，需要更快发现变更可降到 600",
    )
    parser.add_argument(
        "--once", action="store_true", help="只上报一次后退出，便于验证配置"
    )
    args = parser.parse_args()
    if not args.domain:
        parser.error("必须通过 --domain 或环境变量 SENDIP_DOMAIN 指定服务端地址")
    args.domain = normalize_domain(args.domain)
    if args.interval < 60:
        parser.error("--interval 不建议小于 60 秒，避免频繁请求公网 IP 查询服务")
    return args


def main():
    args = parse_args()
    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)

    log.info(
        "客户端启动: domain=%s interval=%ss token=%s",
        args.domain,
        args.interval,
        "已配置" if args.token else "未配置",
    )

    failures = 0
    domain = args.domain
    url_fixed = False

    while _running:
        ip = get_public_ip()
        if ip:
            # Report every hour (heartbeat) so the server can tell whether the client is alive;
            # when the IP is unchanged the server only refreshes last_seen and does not bump the IP change time.
            ok, changed, code, reason = send_ip(ip, domain, args.token)

            # The address pointed at the page (405 or redirected to 200 HTML); append receive-ip and retry once
            if not ok and reason == "wrong_url" and not url_fixed:
                candidate = domain.rstrip("/") + "/" + RECEIVE_PATH
                if candidate != domain:
                    log.warning("尝试用纠正后的地址重试: %s", candidate)
                    ok, changed, code, reason = send_ip(ip, candidate, args.token)
                    if ok:
                        domain = candidate
                        url_fixed = True
                        log.warning(
                            "地址已自动纠正并通过验证，请把配置改成 %s，下次启动即生效",
                            candidate,
                        )

            if ok:
                log.info(
                    "上报成功: %s（%s）",
                    ip,
                    "IP 已变更" if changed else "心跳，IP 未变",
                )
                failures = 0
            else:
                failures += 1
        else:
            failures += 1

        if args.once:
            break

        # On consecutive failures, back off progressively up to 30 minutes to avoid hammering the server/lookup sources
        sleep_for = args.interval
        if failures:
            sleep_for = min(args.interval * (2 ** min(failures, 4)), 1800)
            log.info("连续失败 %s 次，%.0f 秒后重试", failures, sleep_for)

        end_at = time.time() + sleep_for
        while _running and time.time() < end_at:
            time.sleep(min(1, max(0, end_at - time.time())))

    log.info("客户端已退出")
    return 0


if __name__ == "__main__":
    sys.exit(main())
