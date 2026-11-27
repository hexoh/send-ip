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
        log.warning("Legacy address format detected; corrected to %s (was %s)", fixed, url)
        return fixed
    # Only append automatically when it clearly looks like a "base address", to avoid breaking custom routes
    if path.endswith("/"):
        new_path = path + RECEIVE_PATH
    else:
        log.warning(
            "Reporting URL path does not end with /%s (%s); using it as-is. "
            "If you get 405/404, make sure the URL looks like https://domain/%s",
            RECEIVE_PATH,
            path,
            RECEIVE_PATH,
        )
        return url
    fixed = urlunsplit((parts.scheme, parts.netloc, new_path, parts.query, ""))
    log.warning("Reporting URL auto-completed to %s (was %s)", fixed, url)
    return fixed


def _handle_stop(signum, frame):
    global _running
    _running = False
    log.info("Received signal %s, shutting down", signum)


def get_public_ip():
    for url in IP_LOOKUP_URLS:
        try:
            resp = requests.get(url, timeout=TIMEOUT)
            if resp.status_code == 200:
                ip = resp.text.strip()
                if ip:
                    log.info("Public IP found: %s (source %s)", ip, url)
                    return ip
            log.warning("Lookup %s returned status %s", url, resp.status_code)
        except requests.RequestException as exc:
            log.warning("Lookup %s failed: %s", url, exc)
    log.error("All IP lookup sources failed")
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
                    "Report failed: got 200 but not an API response (likely redirected to the page). URL: %s",
                    domain,
                )
                return False, None, code, "wrong_url"
            return True, bool(payload.get("changed")), code, None

        if code == 405:
            log.error(
                "Report failed: 405 Method Not Allowed - the URL points to the page. "
                "Current %s, expected form %s/%s",
                domain,
                domain.rstrip("/"),
                RECEIVE_PATH,
            )
            return False, None, code, "wrong_url"
        if code == 404:
            log.error(
                "Report failed: 404 Not Found - the server has no such route. Check whether Nginx proxies that path prefix, "
                "or whether the URL is %s/%s",
                domain.rstrip("/"),
                RECEIVE_PATH,
            )
            return False, None, code, "notfound"
        if code == 401:
            log.error("Report failed: 401 - bad token; check that the client --token matches the server APP_TOKEN")
            return False, None, code, "auth"

        log.error("Report failed with status %s, response %s", code, resp.text[:200])
        return False, None, code, "other"
    except requests.RequestException as exc:
        log.error("Report request error: %s", exc)
    return False, None, None, "other"


def parse_args():
    parser = argparse.ArgumentParser(description="Periodically report the public IP to the server")
    parser.add_argument(
        "--domain",
        default=os.environ.get("SENDIP_DOMAIN", ""),
        help="Server receiving URL, e.g. https://ip.example.com/receive-ip "
        "(a base URL ending in / gets receive-ip appended automatically)",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("SENDIP_TOKEN", ""),
        help="Auth token matching the server",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=int(os.environ.get("SENDIP_INTERVAL", "3600")),
        help="Reporting interval in seconds, defaults to 3600 (1 hour). Home broadband can use 3600; lower to 600 for faster change detection",
    )
    parser.add_argument(
        "--once", action="store_true", help="Report once and exit, useful for verifying the configuration"
    )
    args = parser.parse_args()
    if not args.domain:
        parser.error("You must specify the server URL via --domain or the SENDIP_DOMAIN environment variable")
    args.domain = normalize_domain(args.domain)
    if args.interval < 60:
        parser.error("--interval should not be less than 60 seconds to avoid hammering the public IP lookup services")
    return args


def main():
    args = parse_args()
    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)

    log.info(
        "Client started: domain=%s interval=%ss token=%s",
        args.domain,
        args.interval,
        "configured" if args.token else "not configured",
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
                    log.warning("Retrying with corrected URL: %s", candidate)
                    ok, changed, code, reason = send_ip(ip, candidate, args.token)
                    if ok:
                        domain = candidate
                        url_fixed = True
                        log.warning(
                            "URL auto-corrected and verified; update the config to %s to apply it on next start",
                            candidate,
                        )

            if ok:
                log.info(
                    "Report succeeded: %s (%s)",
                    ip,
                    "IP changed" if changed else "heartbeat, IP unchanged",
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
            log.info("%s consecutive failures, retrying in %.0f seconds", failures, sleep_for)

        end_at = time.time() + sleep_for
        while _running and time.time() < end_at:
            time.sleep(min(1, max(0, end_at - time.time())))

    log.info("Client stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
