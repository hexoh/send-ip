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
