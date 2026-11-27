<h1 align="center">Send IP</h1>

<p align="center">
  <b>简体中文</b> | <a href="README.md">English</a>
</p>

获取本地公网 IP，上报到自己的服务器并展示。客户端每小时查一次公网 IP 上报，服务端存库并提供需要密码才能查看的网页。
> 适用范围: 家庭宽带公网IP或者动态IP的服务器

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
│   ├── DEPLOY.md        # 完整部署指南（英文）
│   └── DEPLOY.zh-CN.md  # 完整部署指南（简体中文）
├── tools/
│   ├── preview.py       # 用示例数据渲染页面快照，方便预览
│   └── release.py       # 发版脚本：打 tag → 推送 → 由 CI 打包发布
├── ui/                  # 静态页面快照（由 tools/preview.py 生成）
│   ├── preview.html     # IP 展示页
│   └── preview-login.html  # 密码输入页
├── packaging/           # 中英文 README 模板，打包时复制进对应部署包
│   ├── server-README.md
│   └── client-README.md
├── .github/
│   └── workflows/
│       └── release.yml  # tag 触发：打包 + 建 GitHub Release
├── build.py             # 打包脚本：生成 dist/ 下的两个部署包
├── dist/                # 打包输出（已 gitignore）
├── README.md            # 英文说明
└── README.zh-CN.md      # 简体中文（本文件）
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
python3 build.py --version 1.2.3   # 指定版本号，写进包内 VERSION（默认取 git tag）
```

打包时会把 `server/`、`client/` 的内容**拍平成部署时的实际布局**，并各附一份中英文 `README.md`：

| 包 | 内容 | 部署到 |
|---|---|---|
| `dist/send-ip-server/` | `app.py`、`templates/`、`requirements.txt`、`.env.example`、`Dockerfile`、`VERSION`、`deploy/{sendip.service,nginx.conf}` | `/opt/send-ip` |
| `dist/send-ip-client/` | `index.py`、`requirements.txt`、`VERSION`、`deploy/{sendip-agent.service,sendip-agent.env.example}` | `/opt/send-ip-agent` |

## 发布新版本

发版靠 **git tag 触发 GitHub Actions**：推一个 `v1.2.3` 的 tag，CI 自动打包两个部署包、算校验和、建 GitHub Release 并挂上附件。不用手动 `scp`。

一条命令发版（推荐）：

```bash
python3 tools/release.py 1.2.3           # 校验 + 试打包 + 打 tag + 推送
python3 tools/release.py 1.2.3-rc1       # 预发布，Release 会标 prerelease
python3 tools/release.py 1.2.3 --dry-run # 只体检，不动 git
```

脚本会拦下这些坑：版本号格式不对、工作区有未提交改动（tag 内容会和本地代码不一致）、tag 本地或远端已存在、本地试打包失败。走完就能在 Actions 里看进度，跑完 Release 页面自动出现。

手动等价操作（不用脚本时）：

```bash
git tag -a v1.2.3 -m "release v1.2.3"
git push origin v1.2.3
```

Release 附件：

| 附件 | 说明 |
|---|---|
| `send-ip-server-1.2.3.tar.gz` | 服务端，解压到 `/opt/send-ip` |
| `send-ip-client-1.2.3.tar.gz` | 客户端，解压到 `/opt/send-ip-agent` |
| `SHA256SUMS.txt` | 校验和，`sha256sum -c SHA256SUMS.txt` 验完整性 |

版本号规则：`vMAJOR.MINOR.PATCH`，带 `-rc1` / `-beta.2` 这类后缀会自动标成预发布。CI 会校验 tag 与包内 `VERSION` 一致、两个包的关键文件齐全，任何一步不对就失败，不会发出半个包。

打包逻辑改坏了想重发同一个版本：Actions 页面选 `Release` → `Run workflow`，填已存在的 tag，会重新打包并覆盖同名 Release 的附件（不会新建 tag）。

## 本地快速验证

```bash
python3 -m venv .venv
.venv/bin/pip install -r server/requirements.txt
.venv/bin/pip install -r client/requirements.txt   # 本机同时跑两端时两个都装

# 终端 1：启动服务端（APP_PASSWORD 保护页面，去掉则页面公开）
APP_TOKEN=devtoken APP_PASSWORD=devpass .venv/bin/python server/app.py

# 终端 2：上报一次
.venv/bin/python client/index.py --domain http://127.0.0.1:8000/receive-ip --token devtoken --once

# 浏览器打开 http://127.0.0.1:8000，输入 devpass 查看
```

页面由 `APP_PASSWORD` 把守：没登录时浏览器只会拿到一张密码卡片，看不到 IP；`/api/last-ip` 同样受保护
（客户端仍用 `APP_TOKEN` 上报）。同一 IP 连续输错 5 次会锁 10 分钟。`APP_PASSWORD` 为空则页面公开，
只适合本地调试——这种状态下启动日志会打一条警告。

页面右上角有**语言切换**（EN / 中文）。首次访问跟随浏览器的 `Accept-Language`，
也可以用 `?lang=zh` / `?lang=en` 强制指定（方便直接分享链接）。选择会记在 `localStorage` 里，
页面每 5 分钟自动刷新后仍是同一语言。

只想看页面长什么样（不起服务）：`.venv/bin/python tools/preview.py` 会生成 `ui/preview.html`，
加 `--empty` 可预览"尚未接收 IP"的空状态，加 `--lang zh` 可渲染中文版，
加 `--login`（可再叠加 `--error`）会生成 `ui/preview-login.html`，即密码输入页。

生产部署见 [DEPLOY.zh-CN.md](docs/DEPLOY.zh-CN.md)。
