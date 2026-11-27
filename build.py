#!/usr/bin/env python3
"""Packaging script: split the repository into two ready-to-upload folders, server and client.

Usage:
    python3 build.py                 # produce dist/send-ip-server and dist/send-ip-client
    python3 build.py --tar           # also produce the two .tar.gz archives
    python3 build.py --out /tmp/pkg  # set the output directory
    python3 build.py --version 1.2.0 # set the version (defaults to git describe)
    python3 build.py --clean         # clean only, do not build

Standard library only, no dependencies needed; just run python3 build.py.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tarfile
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUT = os.path.join(BASE_DIR, "dist")

SERVER_NAME = "send-ip-server"
CLIENT_NAME = "send-ip-client"

# Files to package for each side: source (relative to repo root) -> target path inside the bundle
# The repo keeps server/ and client/ separate; bundles are flattened into the real deployment layout
SERVER_FILES = [
    ("server/app.py", "app.py"),
    ("server/templates/index.html", "templates/index.html"),
    ("server/requirements.txt", "requirements.txt"),
    ("server/.env.example", ".env.example"),
    ("server/sendip.service", "deploy/sendip.service"),
    ("server/nginx.conf", "deploy/nginx.conf"),
    ("server/Dockerfile", "Dockerfile"),
]

CLIENT_FILES = [
    ("client/index.py", "index.py"),
    ("client/requirements.txt", "requirements.txt"),
    ("client/sendip-agent.service", "deploy/sendip-agent.service"),
    ("client/sendip-agent.env.example", "deploy/sendip-agent.env.example"),
]

# Each bundle gets a single README.md with both English and Chinese sections.
# Rationale: the bundle is the only documentation a deployer receives, so one entry
# point avoids the "wrong file / missing translation" problem. Repo-level docs stay split.
SERVER_README = """\
<p align="center"><a href="#english">English</a> | <a href="#zh-cn">简体中文</a></p>

<a id="english"></a>

# send-ip server (VPS)

Receives the public IP reported by clients, stores it in SQLite, and displays it on a web page.
This bundle contains only the files required by the server; extract it to /opt/send-ip.

## Deployment steps

1) Install system dependencies (Ubuntu / Debian)

    sudo apt update
    sudo apt install -y python3-venv nginx certbot python3-certbot-nginx

2) Install Python dependencies

    cd /opt/send-ip
    python3 -m venv .venv
    .venv/bin/pip install --upgrade pip
    .venv/bin/pip install -r requirements.txt

3) Generate a token and write the config (save the token; the client needs it)

    python3 -c "import secrets; print(secrets.token_urlsafe(32))"
    sudo cp .env.example /etc/send-ip.env
    sudo nano /etc/send-ip.env        # replace APP_TOKEN with the generated token
    sudo chmod 600 /etc/send-ip.env

    sudo mkdir -p /var/lib/send-ip
    sudo chown -R www-data:www-data /var/lib/send-ip /opt/send-ip

4) Start the systemd service

    sudo cp deploy/sendip.service /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable --now sendip
    curl http://127.0.0.1:8000/healthz     # expect {"status":"ok"}

5) Configure Nginx + HTTPS (replace ip.example.com with your domain)

    sudo cp deploy/nginx.conf /etc/nginx/sites-available/send-ip
    sudo nano /etc/nginx/sites-available/send-ip
    sudo ln -sf /etc/nginx/sites-available/send-ip /etc/nginx/sites-enabled/send-ip
    sudo rm -f /etc/nginx/sites-enabled/default
    sudo nginx -t && sudo systemctl reload nginx
    sudo certbot --nginx -d ip.example.com

6) Verify the reporting endpoint

    curl -X POST https://ip.example.com/receive-ip \\
      -H "Content-Type: application/json" \\
      -H "X-Auth-Token: your-token" \\
      -d '{"ip_address":"1.2.3.4"}'

Open the domain in a browser to see the IP; the page refreshes automatically every 5 minutes.

## Troubleshooting

- systemctl status sendip / journalctl -u sendip -n 50
- Report returns 401: the client token does not match the server APP_TOKEN
- Report returns 502: gunicorn is not running; check journalctl
- Port 8000 only binds 127.0.0.1; do not expose it to the public internet

---

<a id="zh-cn"></a>

# send-ip 服务端（VPS）

接收客户端上报的公网 IP，存 SQLite，并在网页上展示。
本包只含服务端必需文件，解压到 /opt/send-ip 即可。

## 部署步骤

1) 安装系统依赖（Ubuntu / Debian）

    sudo apt update
    sudo apt install -y python3-venv nginx certbot python3-certbot-nginx

2) 装 Python 依赖

    cd /opt/send-ip
    python3 -m venv .venv
    .venv/bin/pip install --upgrade pip
    .venv/bin/pip install -r requirements.txt

3) 生成令牌并写配置（令牌要记下来，客户端要用）

    python3 -c "import secrets; print(secrets.token_urlsafe(32))"
    sudo cp .env.example /etc/send-ip.env
    sudo nano /etc/send-ip.env        # 把 APP_TOKEN 换成刚生成的令牌
    sudo chmod 600 /etc/send-ip.env

    sudo mkdir -p /var/lib/send-ip
    sudo chown -R www-data:www-data /var/lib/send-ip /opt/send-ip

4) 启动 systemd 服务

    sudo cp deploy/sendip.service /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable --now sendip
    curl http://127.0.0.1:8000/healthz     # 期望 {"status":"ok"}

5) 配 Nginx + HTTPS（把 ip.example.com 换成你的域名）

    sudo cp deploy/nginx.conf /etc/nginx/sites-available/send-ip
    sudo nano /etc/nginx/sites-available/send-ip
    sudo ln -sf /etc/nginx/sites-available/send-ip /etc/nginx/sites-enabled/send-ip
    sudo rm -f /etc/nginx/sites-enabled/default
    sudo nginx -t && sudo systemctl reload nginx
    sudo certbot --nginx -d ip.example.com

6) 验证上报接口

    curl -X POST https://ip.example.com/receive-ip \\
      -H "Content-Type: application/json" \\
      -H "X-Auth-Token: 你的令牌" \\
      -d '{"ip_address":"1.2.3.4"}'

浏览器打开域名即可看到 IP，页面每 5 分钟自动刷新。

## 排错

- systemctl status sendip / journalctl -u sendip -n 50
- 上报 401：客户端令牌与服务端 APP_TOKEN 不一致
- 上报 502：gunicorn 没起来，看 journalctl
- 8000 端口只绑 127.0.0.1，不要在外网放行
"""

CLIENT_README = """\
<p align="center"><a href="#english">English</a> | <a href="#zh-cn">简体中文</a></p>

<a id="english"></a>

# send-ip client (the machine whose IP is tracked)

Periodically looks up the local public IP and reports it to the server. Once an hour by default.
No public IP or open port is required; it only needs outbound internet access.

## Deployment steps

1) Put it in /opt/send-ip-agent and install dependencies (only requests is needed)

    sudo mkdir -p /opt/send-ip-agent
    sudo chown -R $USER:$USER /opt/send-ip-agent
    # After copying this directory's contents:
    cd /opt/send-ip-agent
    python3 -m venv .venv
    .venv/bin/pip install -r requirements.txt

2) Run it once manually to confirm connectivity

    .venv/bin/python index.py \\
      --domain https://ip.example.com/receive-ip \\
      --token your-token \\
      --once

    Seeing the success log (上报成功) means it works.

3) Configure and start the systemd service

    sudo cp deploy/sendip-agent.env.example /etc/send-ip-agent.env
    sudo nano /etc/send-ip-agent.env      # fill in the domain, token, and interval
    sudo chmod 600 /etc/send-ip-agent.env

    sudo cp deploy/sendip-agent.service /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable --now sendip-agent
    sudo journalctl -u sendip-agent -f

## Options

    --domain / SENDIP_DOMAIN      Server receiving address (required; must end with receive-ip)
    --token  / SENDIP_TOKEN       Must match the server APP_TOKEN
    --interval / SENDIP_INTERVAL  Reporting interval in seconds, defaults to 3600, minimum 60
    --once                        Report once and exit, for troubleshooting

## Common errors

- 405 Method Not Allowed: the address is the page address.
  Wrong: https://hexoo.me/ip/
  Right: https://hexoo.me/ip/receive-ip
  Newer clients append the path and retry automatically, with a WARNING in the log; please fix the config.
- 401: the token does not match the server APP_TOKEN.
- 404: Nginx is not proxying that path prefix.

## Notes

- It reports once an hour (heartbeat), so the server can distinguish "IP change time" from "last heartbeat time"
- When the IP is unchanged, the server only refreshes the heartbeat and does not bump the IP change time
- Consecutive failures back off exponentially, retrying at most every 30 minutes
- Three fallback IP lookup sources: ipinfo.io -> ipify -> ifconfig.me

---

<a id="zh-cn"></a>

# send-ip 客户端（要被追踪 IP 的机器）

定时查询本机公网 IP 并上报给服务端。默认每小时一次。
不需要公网 IP，不需要开放端口，只要能访问外网。

## 部署步骤

1) 放到 /opt/send-ip-agent 并装依赖（只需要 requests）

    sudo mkdir -p /opt/send-ip-agent
    sudo chown -R $USER:$USER /opt/send-ip-agent
    # 把本目录内容拷进去后：
    cd /opt/send-ip-agent
    python3 -m venv .venv
    .venv/bin/pip install -r requirements.txt

2) 先手工跑一次，确认链路通

    .venv/bin/python index.py \\
      --domain https://ip.example.com/receive-ip \\
      --token 你的令牌 \\
      --once

    看到「上报成功」即可。

3) 配置并启动 systemd 常驻

    sudo cp deploy/sendip-agent.env.example /etc/send-ip-agent.env
    sudo nano /etc/send-ip-agent.env      # 填域名、令牌、间隔
    sudo chmod 600 /etc/send-ip-agent.env

    sudo cp deploy/sendip-agent.service /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable --now sendip-agent
    sudo journalctl -u sendip-agent -f

## 参数

    --domain / SENDIP_DOMAIN      服务端接收地址（必填，结尾必须是 receive-ip）
    --token  / SENDIP_TOKEN       与服务端 APP_TOKEN 一致
    --interval / SENDIP_INTERVAL  上报间隔秒数，默认 3600，最小 60
    --once                        只报一次后退出，用于排错

## 常见错误

- 405 Method Not Allowed：地址填成了页面地址。
  错：https://hexoo.me/ip/
  对：https://hexoo.me/ip/receive-ip
  新版客户端会自动补全并重试，日志里会有 WARNING 提示，请顺手把配置改掉。
- 401：令牌与服务端 APP_TOKEN 不一致。
- 404：Nginx 没代理该路径前缀。

## 说明

- 每小时都上报一次（心跳），服务端据此区分「IP 变更时间」和「最后心跳时间」
- IP 未变化时服务端只刷新心跳，不会翻新 IP 变更时间
- 连续失败会指数退避，最长 30 分钟重试一次
- 查 IP 有三个源兜底：ipinfo.io → ipify → ifconfig.me
"""


def detect_version():
    """Fall back to the current tag when no version is given; otherwise mark it as dev.

    git describe returns v1.2.0 on a tagged commit, and v1.2.0-3-gabc1234 afterwards.
    """
    try:
        out = subprocess.run(
            ["git", "describe", "--tags", "--always", "--dirty"],
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return "dev"
    if out.returncode != 0:
        return "dev"
    return out.stdout.strip() or "dev"


def normalize_version(raw):
    """v1.2.0 -> 1.2.0, ensuring the VERSION file has no leading v."""
    v = (raw or "").strip()
    if v.startswith("v"):
        v = v[1:]
    return v or "dev"


def write_version(bundle_dir, version):
    path = os.path.join(bundle_dir, "VERSION")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(version + "\n")
    return path


def copy_files(bundle_dir, files):
    missing = []
    for src_rel, dst_rel in files:
        src = os.path.join(BASE_DIR, src_rel)
        if not os.path.isfile(src):
            missing.append(src_rel)
            continue
        dst = os.path.join(bundle_dir, dst_rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
    return missing


def write_readme(bundle_dir, content):
    path = os.path.join(bundle_dir, "README.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)
    return path


def make_tar(bundle_dir, out_dir):
    name = os.path.basename(bundle_dir)
    tar_path = os.path.join(out_dir, f"{name}.tar.gz")
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(bundle_dir, arcname=name)
    return tar_path


def tree(bundle_dir):
    lines = []
    for root, dirs, files in os.walk(bundle_dir):
        dirs.sort()
        rel = os.path.relpath(root, bundle_dir)
        depth = 0 if rel == "." else rel.count(os.sep) + 1
        if rel != ".":
            lines.append("  " * (depth - 1) + os.path.basename(root) + "/")
        for f in sorted(files):
            size = os.path.getsize(os.path.join(root, f))
            lines.append("  " * depth + f"{f}  ({size:,} B)")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="打包 server / client 两个部署包")
    parser.add_argument("--out", default=DEFAULT_OUT, help="输出目录，默认 ./dist")
    parser.add_argument("--tar", action="store_true", help="额外生成 .tar.gz 压缩包")
    parser.add_argument(
        "--version",
        default=None,
        help="版本号，写入包内 VERSION 文件；默认取 git describe 结果",
    )
    parser.add_argument("--clean", action="store_true", help="只清理输出目录")
    args = parser.parse_args()

    version = normalize_version(args.version or detect_version())

    server_dir = os.path.join(args.out, SERVER_NAME)
    client_dir = os.path.join(args.out, CLIENT_NAME)

    # Clean the old bundle directories first so no stale files are left behind
    for d in (server_dir, client_dir):
        if os.path.isdir(d):
            shutil.rmtree(d)
    for name in (SERVER_NAME, CLIENT_NAME):
        old_tar = os.path.join(args.out, name + ".tar.gz")
        if os.path.isfile(old_tar):
            os.remove(old_tar)

    if args.clean:
        print(f"已清理 {args.out}")
        return 0

    os.makedirs(server_dir, exist_ok=True)
    os.makedirs(client_dir, exist_ok=True)

    missing = []
    missing += copy_files(server_dir, SERVER_FILES)
    missing += copy_files(client_dir, CLIENT_FILES)

    if missing:
        print("以下文件缺失，打包中止：", file=sys.stderr)
        for m in missing:
            print(f"  - {m}", file=sys.stderr)
        return 1

    write_readme(server_dir, SERVER_README)
    write_readme(client_dir, CLIENT_README)
    write_version(server_dir, version)
    write_version(client_dir, version)

    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"打包完成（{stamp}）  版本 {version} → {args.out}\n")

    for d in (server_dir, client_dir):
        print(f"[{os.path.basename(d)}]")
        print(tree(d))
        print()

    if args.tar:
        print("压缩包：")
        for d in (server_dir, client_dir):
            p = make_tar(d, args.out)
            print(f"  {p}  ({os.path.getsize(p):,} B)")
        print()

    print("用法：把对应文件夹整个上传到目标机器即可，")
    print("      服务端 → /opt/send-ip，客户端 → /opt/send-ip-agent。")
    print("      每个包内都有中英文 README.md，照着做即可。")

    return 0


if __name__ == "__main__":
    sys.exit(main())
