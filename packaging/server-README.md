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

3) Generate a token and the page password, then write the config (save the token; the client needs it)

    python3 -c "import secrets; print(secrets.token_urlsafe(32))"   # client token
    python3 -c "import secrets; print(secrets.token_urlsafe(18))"   # page password (or pick your own)
    sudo cp .env.example /etc/send-ip.env
    sudo nano /etc/send-ip.env        # set APP_TOKEN and APP_PASSWORD, and COOKIE_SECURE=1 on HTTPS
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

Open the domain in a browser to see the IP; the page asks for the access password you set in
`APP_PASSWORD` first, then refreshes automatically every 5 minutes. "Sign out" in the top-left
corner locks it again.
The page follows the browser language (English / 简体中文) and has an EN / 中文 switch in the
top-right corner; add `?lang=zh` or `?lang=en` to the URL to force one.

## Troubleshooting

- systemctl status sendip / journalctl -u sendip -n 50
- Report returns 401: the client token does not match the server APP_TOKEN
- Report returns 502: gunicorn is not running; check journalctl
- Forgot the page password: edit APP_PASSWORD in /etc/send-ip.env, then systemctl restart sendip
- Login says "too many attempts" (429): too many wrong passwords from one IP; wait 10 minutes or restart
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

3) 生成令牌与页面密码，写配置（令牌要记下来，客户端要用）

    python3 -c "import secrets; print(secrets.token_urlsafe(32))"   # 客户端令牌
    python3 -c "import secrets; print(secrets.token_urlsafe(18))"   # 页面密码（也可以自己定）
    sudo cp .env.example /etc/send-ip.env
    sudo nano /etc/send-ip.env        # 填 APP_TOKEN 和 APP_PASSWORD，HTTPS 站点再加 COOKIE_SECURE=1
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

浏览器打开域名即可看到 IP，会先要求输入 `APP_PASSWORD` 里设的访问密码，之后页面每 5 分钟自动刷新，
左上角"退出"可重新上锁。页面跟随浏览器语言（英文 / 简体中文），
右上角有 EN / 中文 切换；也可以在网址后加 `?lang=zh` 或 `?lang=en` 强制指定。

## 排错

- systemctl status sendip / journalctl -u sendip -n 50
- 上报 401：客户端令牌与服务端 APP_TOKEN 不一致
- 上报 502：gunicorn 没起来，看 journalctl
- 忘了页面密码：改 /etc/send-ip.env 里的 APP_PASSWORD，然后 systemctl restart sendip
- 登录提示"尝试次数过多"（429）：同一 IP 密码错太多次，等 10 分钟或重启服务
- 8000 端口只绑 127.0.0.1，不要在外网放行
