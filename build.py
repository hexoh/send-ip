#!/usr/bin/env python3
"""打包脚本：把仓库拆成 server / client 两个可直接上传的文件夹。

用法：
    python3 build.py                 # 生成 dist/send-ip-server 和 dist/send-ip-client
    python3 build.py --tar           # 额外生成两个 .tar.gz
    python3 build.py --out /tmp/pkg  # 指定输出目录
    python3 build.py --clean         # 只清理，不生成

只用标准库，不需要装任何依赖，直接 python3 build.py 即可。
"""

import argparse
import os
import shutil
import sys
import tarfile
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUT = os.path.join(BASE_DIR, "dist")

SERVER_NAME = "send-ip-server"
CLIENT_NAME = "send-ip-client"

# 每端要打包的文件：源文件(相对仓库根) -> 包内目标路径
# 仓库里按 server/ client/ 分目录存放，包内则拍平成部署时的实际布局
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

SERVER_README = """\
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
    parser.add_argument("--clean", action="store_true", help="只清理输出目录")
    args = parser.parse_args()

    server_dir = os.path.join(args.out, SERVER_NAME)
    client_dir = os.path.join(args.out, CLIENT_NAME)

    # 先清理旧的包目录，避免残留过期文件
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

    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"打包完成（{stamp}）→ {args.out}\n")

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
    print("      每个包内都有『README.md』，照着做即可。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
