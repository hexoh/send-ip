<h1 align="center">部署指南</h1>

<p align="center">
  <b>简体中文</b> | <a href="DEPLOY.md">English</a>
</p>

服务端跑在云服务器上接收 IP 并展示，客户端跑在要被追踪 IP 的 Linux 机器上定时上报。

```
┌────────────────────┐   POST /receive-ip    ┌──────────────────────────────┐
│  客户端 index.py    │  {"ip_address":"..."} │  VPS: Nginx(443) → gunicorn  │
│  家宽 Linux 机器     │ ────────────────────► │  Flask app.py → SQLite       │
│  systemd 常驻        │   X-Auth-Token        │  浏览器打开域名即可看到 IP     │
└────────────────────┘                       └──────────────────────────────┘
```

## 接口一览

| 方法 | 路径 | 用途 | 鉴权 |
|---|---|---|---|
| GET | `/` | 展示页（IP + 变更时间 + 最后心跳） | 无 |
| POST | `/receive-ip` | 接收客户端上报 | `X-Auth-Token` |
| GET | `/api/last-ip` | 查询最新记录（JSON） | `X-Auth-Token` |
| GET | `/healthz` | 健康检查 | 无 |
| POST | `/receive_ip` | **旧地址，仅兼容保留**，会打 WARNING | `X-Auth-Token` |

> 路径统一用连字符（`-`）而不是下划线，符合 URL 惯例。旧的 `/receive_ip` 目前仍可用，
> 确认所有客户端都升级后，把 `server/app.py` 里那行 `@app.route("/receive_ip", ...)` 删掉即可。


## 两端分别需要拷什么（不用拷全部）

仓库是"一仓两用"，但**两边跑的是完全独立的两套代码**，不需要把整个仓库搬过去。
仓库已按端分目录：`server/` 只给 VPS，`client/` 只给被追踪的机器。

| 文件 | 服务端 VPS | 客户端 Linux | 说明 |
|---|:---:|:---:|---|
| `server/app.py` | 必须 | — | Flask 服务端 |
| `server/templates/index.html` | 必须 | — | 页面模板 |
| `server/requirements.txt` | 必须 | — | Flask + gunicorn |
| `client/index.py` | — | 必须 | 上报客户端 |
| `client/requirements.txt` | — | 必须 | requests |
| `server/sendip.service`、`server/nginx.conf` | 建议 | — | 服务端 systemd / Nginx 配置 |
| `client/sendip-agent.service`、`client/sendip-agent.env.example` | — | 建议 | 客户端 systemd / 环境变量 |
| `docs/`、`README.md`、`LICENSE` | 不需要 | 不需要 | 文档 |
| `tools/preview.py` | 不需要 | 不需要 | 本地看版式用 |
| `server/Dockerfile`、`server/.env.example` | 按需 | — | 只用 Docker 部署时才需要 |

**最小可运行集合**：服务端 3 个文件，客户端 2 个文件（已实测跑通完整链路）。

### 不想手动挑文件？一键打包

```bash
python3 build.py          # 生成 dist/send-ip-server 和 dist/send-ip-client（各自带 .service / nginx.conf / 中英文 README.md）
python3 build.py --tar    # 额外压成 tar.gz，方便 scp
```

然后把对应文件夹整个传上去即可，**不需要仓库里的其他任何文件**：

```bash
scp -r dist/send-ip-server/* user@vps:/opt/send-ip/
scp -r dist/send-ip-client/* user@target:/opt/send-ip-agent/
```

后面的一、二节仍是完整的手动步骤说明，打包只是省掉"挑文件"这一步。

---

## 一、服务端部署（VPS）

以 Ubuntu 22.04 / 24.04、域名为 `ip.example.com` 为例，Debian 同理。

### 1. 域名解析

在域名服务商处添加 A 记录：`ip.example.com` → 你的 VPS 公网 IP。
确认生效：`ping ip.example.com` 能解析到 VPS IP。

### 2. 放行端口

云厂商安全组和本机防火墙都要放行 80 和 443（**不要**放行 8000，只让 Nginx 走本机回环）。

```bash
sudo ufw allow 80,443/tcp
```

### 3. 安装依赖

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip nginx certbot python3-certbot-nginx
```

### 4. 上传代码（只需 3 个文件）

服务端**不需要** `index.py`（客户端代码）、`tools/`、`DEPLOY.md`、`README.md`。真正要跑的只有：

```
app.py                    # Flask 应用
templates/index.html      # 页面模板
requirements.txt          # Flask + gunicorn
```

下面三种方式挑一种。

**方式 A：本地 rsync（推荐，文件最少）**

```bash
# 在本地仓库目录执行
ssh user@vps 'sudo mkdir -p /opt/send-ip/templates /opt/send-ip/deploy && sudo chown -R $USER:$USER /opt/send-ip'
rsync -avz server/app.py server/requirements.txt server/.env.example user@vps:/opt/send-ip/
rsync -avz server/templates/ user@vps:/opt/send-ip/templates/
rsync -avz server/sendip.service server/nginx.conf user@vps:/opt/send-ip/deploy/
```

**方式 B：在 VPS 上用 git，只检出 server 目录**

```bash
sudo mkdir -p /opt/send-ip && sudo chown -R $USER:$USER /opt/send-ip
git clone --depth 1 --sparse https://github.com/hexoh/send-ip.git /tmp/send-ip-src
cd /tmp/send-ip-src && git sparse-checkout set server
# 把 server/ 的内容摊到部署目录（保持 app.py 在根）
cp -r server/. /opt/send-ip/
```

因为仓库现在按端分了目录，`git sparse-checkout set server` 是干净的目录级裁剪，不会像之前那样被根目录文件干扰。

> 小提醒：`git sparse-checkout set` 只接受**目录**名，传文件名会报
> `fatal: 'app.py' is not a directory`；根目录下的文件（`README.md`、`build.py` 等）无论如何都会检出，体积都很小，忽略即可。

**方式 C：图省事，整仓库 clone**

```bash
git clone --depth 1 https://github.com/hexoh/send-ip.git /opt/send-ip
```

三种方式产出的运行结果完全一样，区别只是磁盘上多几个不参与运行的文件。仓库里没有 `data/` 和 `preview.html`（已在 `.gitignore` 中），不用担心把本地运行数据带上去。

### 5. 装依赖

```bash
cd /opt/send-ip
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt   # 只装 Flask + gunicorn
```

> 服务端不需要 `requests`，客户端不需要 `Flask`/`gunicorn`，两边依赖已拆开：
> 服务端用 `server/requirements.txt`，客户端用 `client/requirements.txt`。

### 6. 生成令牌、写配置文件

```bash
# 生成一个随机令牌，记下来，客户端要用
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

把它填进 `/etc/send-ip.env`：

```bash
sudo cp /opt/send-ip/.env.example /etc/send-ip.env
sudo nano /etc/send-ip.env     # 把 APP_TOKEN 换成刚生成的令牌
sudo chmod 600 /etc/send-ip.env
```

### 7. 数据目录权限

```bash
sudo mkdir -p /var/lib/send-ip
sudo chown -R www-data:www-data /var/lib/send-ip
sudo chown -R www-data:www-data /opt/send-ip
```

### 8. 注册 systemd 服务

```bash
sudo cp /opt/send-ip/deploy/sendip.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now sendip
sudo systemctl status sendip --no-pager
```

本机自测（应该返回 `{"status":"ok"}`）：

```bash
curl http://127.0.0.1:8000/healthz
```

### 9. 配 Nginx + HTTPS

```bash
sudo cp /opt/send-ip/deploy/nginx.conf /etc/nginx/sites-available/send-ip
# 修改 server_name 为你的真实域名
sudo nano /etc/nginx/sites-available/send-ip
sudo ln -sf /etc/nginx/sites-available/send-ip /etc/nginx/sites-enabled/send-ip
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
```

确认 HTTP 能通后签证书（certbot 会自动改写 nginx 配置并配置 80→443 跳转）：

```bash
sudo certbot --nginx -d ip.example.com
```

### 10. 验证服务端

```bash
# 模拟客户端上报
curl -X POST https://ip.example.com/receive-ip \
  -H "Content-Type: application/json" \
  -H "X-Auth-Token: 你的令牌" \
  -d '{"ip_address":"1.2.3.4"}'
# 期望: {"ip":"1.2.3.4","success":true,"updated_at":"..."}

# 不带令牌应该被拒
curl -o /dev/null -w "%{http_code}\n" -X POST https://ip.example.com/receive-ip \
  -H "Content-Type: application/json" -d '{"ip_address":"1.2.3.4"}'
# 期望: 401
```

浏览器打开 `https://ip.example.com` 就能看到 IP，页面每 60 秒自动刷新。

---

## 二、客户端部署（要被追踪 IP 的 Linux 机器）

这台机器是**主动上报方**，不需要公网 IP、不需要开放端口，只要能访问外网即可。

### 1. 放代码（只需 2 个文件）

```bash
sudo mkdir -p /opt/send-ip-agent
sudo chown -R $USER:$USER /opt/send-ip-agent
# 客户端只需要 client/ 下的这两个文件
scp client/index.py client/requirements.txt user@target:/opt/send-ip-agent/
# 想顺便带上 systemd 与环境变量模板
scp -r client/sendip-agent.service client/sendip-agent.env.example user@target:/opt/send-ip-agent/
```

### 2. 装依赖

```bash
cd /opt/send-ip-agent
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt   # 只装 requests
```

> 客户端不需要 Flask 和 gunicorn，别装 `server/requirements.txt`，会白装几十 MB。实测最小客户端只有 `index.py` + `requirements.txt` 两个文件、依赖仅 `requests`。

### 3. 先手工跑一次确认能通

```bash
/opt/send-ip-agent/.venv/bin/python index.py \
  --domain https://ip.example.com/receive-ip \
  --token 你的令牌 \
  --once
```

看到 `上报成功` 就说明链路 OK。

### 4. 注册 systemd 常驻

```bash
sudo tee /etc/send-ip-agent.env > /dev/null <<'EOF'
SENDIP_DOMAIN=https://ip.example.com/receive-ip
SENDIP_TOKEN=你的令牌
SENDIP_INTERVAL=3600
EOF
sudo chmod 600 /etc/send-ip-agent.env

# 上一步已把客户端包放到 /opt/send-ip-agent，直接用
sudo cp /opt/send-ip-agent/sendip-agent.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now sendip-agent
sudo journalctl -u sendip-agent -f
```

> `client/sendip-agent.service` 里默认 `User=nobody`，如果 venv 目录权限有问题就改成实际用户，比如 `User=pi`。

### 5. 客户端参数与上报节奏

| 参数 | 环境变量 | 说明 |
|---|---|---|
| `--domain` | `SENDIP_DOMAIN` | 服务端接收地址，必填 |
| `--token` | `SENDIP_TOKEN` | 与服务端 `APP_TOKEN` 一致 |
| `--interval` | `SENDIP_INTERVAL` | 上报间隔秒数，默认 3600（1 小时），最小 60 |
| `--once` | — | 只跑一次，用于排错 |

**间隔怎么选**：家宽的公网 IP 只在 PPPoE 重拨、光猫/路由重启、运营商回收租约时变化，日常非常稳定，所以默认 1 小时足够。代价是最坏情况下 IP 变了要等近 1 小时才发现。

| 场景 | 建议间隔 | 说明 |
|---|---|---|
| 只是想知道家里现在什么 IP | 3600（默认） | 每月约 720 次查询，远低于 ipinfo 免费额度 |
| 要跑 DDNS / 有远程办公刚需 | 600 ~ 900 | 变更发现延迟降到 10~15 分钟 |
| 对外提供服务，要求秒级切换 | 120 ~ 300 | 配合服务端做变更通知才有意义 |

**上报语义是心跳**：每次都会向服务端上报（不是"IP 变了才报"），服务端据此区分两个时间——

- **IP 变更于**：这个 IP 第一次被看到的时间，IP 没变就不会刷新
- **最后心跳**：最后一次成功上报的时间，超过 2 个间隔没更新就说明客户端掉线了

这样即使 IP 一个月不变，页面上的时间也不会显得像"服务挂了"。

其他行为：连续失败会指数退避（从 30 分钟封顶，避免把服务端/查询源打爆）；查 IP 有三个源兜底（ipinfo.io → ipify → ifconfig.me）。

---

## 三、Docker 方式部署服务端（可选）

不想折腾 venv 和 systemd 的话：

```bash
cd /opt/send-ip
docker build -t send-ip .
docker run -d --name send-ip --restart unless-stopped \
  -p 127.0.0.1:8000:8000 \
  -e APP_TOKEN=你的令牌 \
  -v sendip-data:/data \
  send-ip
```

Nginx 和 HTTPS 部分不变（仍然反代到 `127.0.0.1:8000`）。

---

## 四、排错

| 现象 | 排查方向 |
|---|---|
| 浏览器打不开首页 | `systemctl status sendip`、`journalctl -u sendip -n 50`；`curl 127.0.0.1:8000/healthz` 区分是应用还是 Nginx 问题 |
| **上报返回 405** | **`--domain` 填成了页面地址**，必须带 `/receive-ip` 后缀。例：`https://hexoo.me/ip/` 应写作 `https://hexoo.me/ip/receive-ip`。新版客户端会自动补全并重试，日志里会有 WARNING 提示 |
| 上报返回 401 | 客户端 `--token` 与服务端 `/etc/send-ip.env` 的 `APP_TOKEN` 不一致（注意别带引号和空格） |
| 上报返回 404 | Nginx 没代理该路径前缀，或 `--domain` 少了子路径。先用 `curl -i -X POST 域名/路径/receive-ip` 确认路由存在（应返回 401 而非 404） |
| 上报返回 502 | gunicorn 没起来，看 `journalctl -u sendip` |
| 日志报"200 但不是接口响应" | 地址被 301 跳转到了页面，同样缺 `/receive-ip` 后缀 |
| 首页一直是"尚未接收到" | 客户端没跑起来或没上报成功，`journalctl -u sendip-agent -f` |
| 端口 8000 通但外网不通 | 检查 ufw / 安全组，以及 Nginx 是否加载了该站点 |
| 证书签发失败 | 确认 80 端口可达、DNS 已生效；`sudo certbot renew --dry-run` 验证续期 |

---

## 五、安全提醒

- **务必设置 `APP_TOKEN`**，否则公网任何人都能往你的页面写假 IP。
- 全链路走 HTTPS，不要在公网用明文 HTTP 传令牌。
- 8000 端口只绑 `127.0.0.1`，不要暴露到公网。
- 域名和端口不对外公开时，这个页面等于公开了你家宽出口 IP，介意的话可以考虑加一层 Basic Auth 或用随机路径。
