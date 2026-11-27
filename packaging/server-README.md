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
