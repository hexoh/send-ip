# send-ip

获取本机公网 IP，上报到自己的服务器并展示。客户端每小时查一次公网 IP 上报，服务端存库并提供网页查看。

## 目录结构

```
send-ip/
├── server/              # 服务端：只部署到 VPS
│   ├── app.py           # Flask 应用（/receive-ip 接收，/ 展示）
│   ├── templates/       # 页面模板（Jinja2，需经 Flask 渲染）
│   ├── requirements.txt # Flask + gunicorn
│   ├── .env.example     # 服务端环境变量示例（APP_TOKEN 等）
│   ├── sendip.service   # systemd 单元
│   ├── nginx.conf       # Nginx 反向代理配置
│   └── Dockerfile       # 可选：容器化部署
├── client/              # 客户端：只部署到被追踪 IP 的机器
│   ├── index.py         # 定时查询并上报公网 IP
│   ├── requirements.txt # requests（仅此一个依赖）
│   ├── sendip-agent.service      # systemd 单元
│   └── sendip-agent.env.example  # 环境变量示例（域名/令牌/间隔）
├── docs/
│   └── DEPLOY.md        # 完整部署指南（VPS + Nginx + HTTPS + systemd）
├── tools/
│   └── preview.py       # 用示例数据渲染页面快照，方便预览
├── build.py             # 打包脚本：生成 dist/ 下的两个部署包
├── dist/                # 打包输出（已 gitignore）
└── README.md
```

两端代码完全独立，**部署时不需要拷全量**：

| 端 | 最少需要的文件 |
|---|---|
| 服务端（VPS） | `server/app.py`、`server/templates/index.html`、`server/requirements.txt` |
| 客户端（Linux） | `client/index.py`、`client/requirements.txt` |

## 打包部署包

不想手动挑文件，直接跑：

```bash
python3 build.py          # 生成 dist/send-ip-server 和 dist/send-ip-client
python3 build.py --tar    # 顺便压成 tar.gz，方便 scp
```

打包时会把 `server/`、`client/` 的内容**拍平成部署时的实际布局**，并各附一份 `README.md`：

| 包 | 内容 | 部署到 |
|---|---|---|
| `dist/send-ip-server/` | `app.py`、`templates/`、`requirements.txt`、`.env.example`、`Dockerfile`、`deploy/{sendip.service,nginx.conf}` | `/opt/send-ip` |
| `dist/send-ip-client/` | `index.py`、`requirements.txt`、`deploy/{sendip-agent.service,sendip-agent.env.example}` | `/opt/send-ip-agent` |

## 本地快速验证

```bash
python3 -m venv .venv
.venv/bin/pip install -r server/requirements.txt
.venv/bin/pip install -r client/requirements.txt   # 本机同时跑两端时两个都装

# 终端 1：启动服务端
APP_TOKEN=devtoken .venv/bin/python server/app.py

# 终端 2：上报一次
.venv/bin/python client/index.py --domain http://127.0.0.1:8000/receive-ip --token devtoken --once

# 浏览器打开 http://127.0.0.1:8000 查看
```

只想看页面长什么样（不起服务）：`.venv/bin/python tools/preview.py` 会生成 `preview.html`，
加 `--empty` 可预览"尚未接收 IP"的空状态。

生产部署见 [docs/DEPLOY.md](docs/DEPLOY.md)。
