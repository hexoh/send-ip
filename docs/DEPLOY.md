<h1 align="center">Deployment Guide</h1>

<p align="center">
  <b>English</b> | <a href="DEPLOY.zh-CN.md">简体中文</a>
</p>

The server runs on a cloud host, receives the IP and displays it; the client runs on the Linux machine whose IP you want to track and reports on a schedule.

```
┌────────────────────┐   POST /receive-ip    ┌──────────────────────────────┐
│  client index.py   │  {"ip_address":"..."} │  VPS: Nginx(443) → gunicorn  │
│  home Linux host   │ ────────────────────► │  Flask app.py → SQLite       │
│  systemd service   │   X-Auth-Token        │  open the domain in a browser│
└────────────────────┘                       └──────────────────────────────┘
```

## API overview

| Method | Path | Purpose | Auth |
|---|---|---|---|
| GET | `/` | Display page (IP + changed at + last heartbeat) | `APP_PASSWORD` session cookie |
| POST | `/login` | Check the page password, set the session cookie | — |
| POST | `/logout` | Clear the session cookie | — |
| POST | `/receive-ip` | Receive client reports | `X-Auth-Token` |
| GET | `/api/last-ip` | Query the latest record (JSON) | `X-Auth-Token` or page session |
| GET | `/healthz` | Health check | None |
| POST | `/receive_ip` | **Legacy path, kept for compatibility only**, logs a WARNING | `X-Auth-Token` |

> Paths use hyphens (`-`) rather than underscores, following URL conventions. The old `/receive_ip`
> still works; once every client has been upgraded, delete the
> `@app.route("/receive_ip", ...)` line in `server/app.py`.


## What each side needs (you don't copy everything)

The repo serves two purposes in one, but **the two sides run completely separate code**, so you don't need to move the whole repo. The repo is already split by side: `server/` goes only to the VPS, `client/` only to the tracked machine.

| File | Server VPS | Client Linux | Notes |
|---|:---:|:---:|---|
| `server/app.py` | Required | — | Flask server |
| `server/templates/index.html` | Required | — | Page template |
| `server/requirements.txt` | Required | — | Flask + gunicorn |
| `client/index.py` | — | Required | Reporting client |
| `client/requirements.txt` | — | Required | requests |
| `server/sendip.service`, `server/nginx.conf` | Recommended | — | Server systemd / Nginx config |
| `client/sendip-agent.service`, `client/sendip-agent.env.example` | — | Recommended | Client systemd / env vars |
| `docs/`, `README.md`, `LICENSE` | Not needed | Not needed | Documentation |
| `tools/preview.py` | Not needed | Not needed | Local layout preview |
| `server/Dockerfile`, `server/.env.example` | As needed | — | Only for Docker deployment |

**Minimum runnable set**: 3 files for the server, 2 files for the client (the full path has been tested end to end).

### Don't want to pick files by hand? One-command packaging

```bash
python3 build.py          # produces dist/send-ip-server and dist/send-ip-client (each with .service / nginx.conf / bilingual README.md)
python3 build.py --tar    # also compress to tar.gz, handy for scp
```

Then upload each folder as a whole; **no other file from the repo is needed**:

```bash
scp -r dist/send-ip-server/* user@vps:/opt/send-ip/
scp -r dist/send-ip-client/* user@target:/opt/send-ip-agent/
```

Sections 1 and 2 below are still the complete manual steps; packaging just saves you the "pick the files" step.

---

## 1. Server deployment (VPS)

Using Ubuntu 22.04 / 24.04 and the domain `ip.example.com` as an example; Debian works the same way.

### 1. DNS

Add an A record at your domain registrar: `ip.example.com` → your VPS public IP.
Verify it took effect: `ping ip.example.com` should resolve to the VPS IP.

### 2. Open ports

Both the cloud provider's security group and the host firewall must allow 80 and 443 (**do not** open 8000; only Nginx should reach it over the loopback interface).

```bash
sudo ufw allow 80,443/tcp
```

### 3. Install dependencies

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip nginx certbot python3-certbot-nginx
```

### 4. Upload the code (only 3 files needed)

The server **does not need** `index.py` (client code), `tools/`, `DEPLOY.md`, or `README.md`. All it actually runs is:

```
app.py                    # Flask app
templates/index.html      # Page template
requirements.txt          # Flask + gunicorn
```

Pick one of the three approaches below.

**Option A: rsync from your machine (recommended, fewest files)**

```bash
# Run from your local repo directory
ssh user@vps 'sudo mkdir -p /opt/send-ip/templates /opt/send-ip/deploy && sudo chown -R $USER:$USER /opt/send-ip'
rsync -avz server/app.py server/requirements.txt server/.env.example user@vps:/opt/send-ip/
rsync -avz server/templates/ user@vps:/opt/send-ip/templates/
rsync -avz server/sendip.service server/nginx.conf user@vps:/opt/send-ip/deploy/
```

**Option B: git on the VPS, checking out only the server directory**

```bash
sudo mkdir -p /opt/send-ip && sudo chown -R $USER:$USER /opt/send-ip
git clone --depth 1 --sparse https://github.com/hexoh/send-ip.git /tmp/send-ip-src
cd /tmp/send-ip-src && git sparse-checkout set server
# Flatten server/ into the deployment directory (keep app.py at the root)
cp -r server/. /opt/send-ip/
```

Since the repo is now split by side, `git sparse-checkout set server` is a clean directory-level selection and won't be disturbed by root-level files as before.

> A small reminder: `git sparse-checkout set` only accepts **directory** names; passing a file name fails with
> `fatal: 'app.py' is not a directory`. Root-level files (`README.md`, `build.py`, etc.) are always checked out; they are tiny, just ignore them.

**Option C: the easy way, clone the whole repo**

```bash
git clone --depth 1 https://github.com/hexoh/send-ip.git /opt/send-ip
```

All three approaches produce identical runtime results; the only difference is a few extra files on disk that don't participate in running. The repo contains no `data/` or `preview.html` (both are in `.gitignore`), so you won't accidentally upload local runtime data.

### 5. Install dependencies

```bash
cd /opt/send-ip
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt   # only Flask + gunicorn
```

> The server doesn't need `requests`, and the client doesn't need `Flask`/`gunicorn`; the dependencies are already split:
> the server uses `server/requirements.txt`, the client uses `client/requirements.txt`.

### 6. Generate the token and the page password, then write the config file

```bash
# Generate a random token for the client, write it down
python3 -c "import secrets; print(secrets.token_urlsafe(32))"

# Generate the password for the web page, keep it in your password manager
python3 -c "import secrets; print(secrets.token_urlsafe(18))"
```

Put them into `/etc/send-ip.env`:

```bash
sudo cp /opt/send-ip/.env.example /etc/send-ip.env
sudo nano /etc/send-ip.env     # replace APP_TOKEN and APP_PASSWORD with the values above
sudo chmod 600 /etc/send-ip.env
```

Server environment variables:

| Variable | Default | Meaning |
|---|---|---|
| `APP_TOKEN` | empty | Client token. Empty = reports are not checked (local debugging only) |
| `APP_PASSWORD` | empty | **Page password.** Any string you like (spaces trimmed at both ends). Empty = the page is public; anyone with the domain sees your IP |
| `COOKIE_SECURE` | off | Set to `1` when served over HTTPS so the session cookie is `Secure` |
| `SECRET_KEY` | auto | Session cookie signing key. Empty = generated once into `<DB dir>/secret.key` (mode 600) |
| `SESSION_DAYS` | 7 | How long a login stays valid |
| `LOGIN_MAX_FAILS` | 5 | Wrong passwords allowed from one IP before the lockout, per gunicorn worker |
| `LOGIN_LOCK_SECONDS` | 600 | Lockout length after too many wrong passwords |
| `DB_PATH` | `./data/ips.db` | SQLite file |

> `APP_PASSWORD` protects the page **and** `/api/last-ip`. The client keeps using `APP_TOKEN`, so
> the reporting path is unaffected. With `APP_PASSWORD` empty the app logs a warning at startup.

### 7. Data directory permissions

```bash
sudo mkdir -p /var/lib/send-ip
sudo chown -R www-data:www-data /var/lib/send-ip
sudo chown -R www-data:www-data /opt/send-ip
```

### 8. Register the systemd service

```bash
sudo cp /opt/send-ip/deploy/sendip.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now sendip
sudo systemctl status sendip --no-pager
```

Local self-test (should return `{"status":"ok"}`):

```bash
curl http://127.0.0.1:8000/healthz
```

### 9. Configure Nginx + HTTPS

```bash
sudo cp /opt/send-ip/deploy/nginx.conf /etc/nginx/sites-available/send-ip
# Change server_name to your real domain
sudo nano /etc/nginx/sites-available/send-ip
sudo ln -sf /etc/nginx/sites-available/send-ip /etc/nginx/sites-enabled/send-ip
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
```

Once HTTP works, issue the certificate (certbot rewrites the nginx config and sets up the 80→443 redirect automatically):

```bash
sudo certbot --nginx -d ip.example.com
```

### 10. Verify the server

```bash
# Simulate a client report
curl -X POST https://ip.example.com/receive-ip \
  -H "Content-Type: application/json" \
  -H "X-Auth-Token: your-token" \
  -d '{"ip_address":"1.2.3.4"}'
# Expected: {"ip":"1.2.3.4","success":true,"updated_at":"..."}

# Without the token it should be rejected
curl -o /dev/null -w "%{http_code}\n" -X POST https://ip.example.com/receive-ip \
  -H "Content-Type: application/json" -d '{"ip_address":"1.2.3.4"}'
# Expected: 401
```

Open `https://ip.example.com` in a browser and you'll see the IP; the page refreshes every 60 seconds.

---

## 2. Client deployment (the Linux machine whose IP is tracked)

This machine is the **reporting side**: it needs no public IP, no open ports, just outbound internet access.

### 1. Put the code in place (only 2 files needed)

```bash
sudo mkdir -p /opt/send-ip-agent
sudo chown -R $USER:$USER /opt/send-ip-agent
# The client only needs these two files from client/
scp client/index.py client/requirements.txt user@target:/opt/send-ip-agent/
# Optionally bring along the systemd unit and env template
scp -r client/sendip-agent.service client/sendip-agent.env.example user@target:/opt/send-ip-agent/
```

### 2. Install dependencies

```bash
cd /opt/send-ip-agent
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt   # only requests
```

> The client doesn't need Flask or gunicorn; don't install `server/requirements.txt`, it would waste tens of MB. The tested minimum client is just `index.py` + `requirements.txt`, with `requests` as the only dependency.

### 3. Run it once by hand to confirm connectivity

```bash
/opt/send-ip-agent/.venv/bin/python index.py \
  --domain https://ip.example.com/receive-ip \
  --token your-token \
  --once
```

Seeing `上报成功` (report succeeded) means the path is OK.

### 4. Register the systemd service

```bash
sudo tee /etc/send-ip-agent.env > /dev/null <<'EOF'
SENDIP_DOMAIN=https://ip.example.com/receive-ip
SENDIP_TOKEN=your-token
SENDIP_INTERVAL=3600
EOF
sudo chmod 600 /etc/send-ip-agent.env

# The client bundle is already in /opt/send-ip-agent from the previous step, use it directly
sudo cp /opt/send-ip-agent/sendip-agent.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now sendip-agent
sudo journalctl -u sendip-agent -f
```

> `client/sendip-agent.service` defaults to `User=nobody`. If the venv directory permissions cause problems, change it to the actual user, e.g. `User=pi`.

### 5. Client options and reporting cadence

| Option | Env var | Description |
|---|---|---|
| `--domain` | `SENDIP_DOMAIN` | Server receive URL, required |
| `--token` | `SENDIP_TOKEN` | Must match the server's `APP_TOKEN` |
| `--interval` | `SENDIP_INTERVAL` | Reporting interval in seconds, default 3600 (1 hour), minimum 60 |
| `--once` | — | Run once and exit, for troubleshooting |

**Choosing an interval**: a home broadband public IP only changes on PPPoE re-dial, router/ONT restart, or when the ISP reclaims the lease, so it is very stable day to day; the default 1 hour is enough. The cost is that in the worst case it takes nearly an hour to notice an IP change.

| Scenario | Suggested interval | Notes |
|---|---|---|
| Just want to know the current home IP | 3600 (default) | About 720 lookups per month, well under ipinfo's free quota |
| Running DDNS / remote work is a hard requirement | 600 ~ 900 | Change detection latency drops to 10–15 minutes |
| Serving traffic publicly, need switchover in seconds | 120 ~ 300 | Only meaningful together with server-side change notifications |

**Reporting is a heartbeat**: every run reports to the server (not only when the IP changes), which lets the server distinguish two timestamps:

- **IP changed at**: when this IP was first seen; it is not refreshed while the IP stays the same
- **Last heartbeat**: the time of the last successful report; if it hasn't updated for more than 2 intervals, the client is offline

That way, even if the IP stays unchanged for a month, the timestamps on the page don't look like "the service is down".

Other behavior: consecutive failures use exponential backoff (capped at 30 minutes, so the server and lookup providers aren't hammered); IP lookup has three fallback sources (ipinfo.io → ipify → ifconfig.me).

---

## 3. Deploying the server with Docker (optional)

If you'd rather not deal with venv and systemd:

```bash
cd /opt/send-ip
docker build -t send-ip .
docker run -d --name send-ip --restart unless-stopped \
  -p 127.0.0.1:8000:8000 \
  -e APP_TOKEN=your-token \
  -v sendip-data:/data \
  send-ip
```

Nginx and HTTPS are unchanged (still proxying to `127.0.0.1:8000`).

---

## 4. Troubleshooting

| Symptom | What to check |
|---|---|
| Browser can't open the home page | `systemctl status sendip`, `journalctl -u sendip -n 50`; `curl 127.0.0.1:8000/healthz` tells you whether it's the app or Nginx |
| **Report returns 405** | **`--domain` points to the page URL**; it must end with `/receive-ip`. E.g. `https://hexoo.me/ip/` should be `https://hexoo.me/ip/receive-ip`. Newer clients auto-complete and retry, logging a WARNING |
| Report returns 401 | The client's `--token` doesn't match `APP_TOKEN` in the server's `/etc/send-ip.env` (watch out for quotes and spaces) |
| Report returns 404 | Nginx isn't proxying that path prefix, or `--domain` is missing a sub-path. First confirm the route exists with `curl -i -X POST domain/path/receive-ip` (should return 401, not 404) |
| Report returns 502 | gunicorn isn't running, check `journalctl -u sendip` |
| Log says "200 but not an API response" | The URL was 301-redirected to the page; again the `/receive-ip` suffix is missing |
| Home page always shows "not received yet" | The client isn't running or hasn't reported successfully; `journalctl -u sendip-agent -f` |
| Forgot the page password | Edit `APP_PASSWORD` in `/etc/send-ip.env`, then `sudo systemctl restart sendip` |
| Login returns 429 / "Too many attempts" | `LOGIN_MAX_FAILS` wrong passwords from one IP trigger a `LOGIN_LOCK_SECONDS` lockout (default 5 / 10 min). Wait it out, or restart the service to clear the counters |
| Everyone is logged out after every restart | `secret.key` couldn't be written. Check that `/var/lib/send-ip/` is owned by `www-data`, or set `SECRET_KEY` explicitly |
| Password accepted but the page asks again | The session cookie doesn't come back: use HTTPS (and set `COOKIE_SECURE=1`); make sure Nginx passes cookies untouched |
| Port 8000 works locally but not from outside | Check ufw / the security group, and whether Nginx loaded the site |
| Certificate issuance fails | Make sure port 80 is reachable and DNS has propagated; verify renewal with `sudo certbot renew --dry-run` |

---

## 5. Security notes

- **Always set `APP_TOKEN`**; otherwise anyone on the internet can write fake IPs to your page.
- **Always set `APP_PASSWORD`**; otherwise anyone who finds the domain can read your IP. The
  password is compared in constant time, the browser only receives a signed cookie (HttpOnly,
  SameSite=Lax, 7 days), and `/api/last-ip` is gated the same way. It is sent once per login, so
  serve the site over HTTPS.
- Any string works as `APP_PASSWORD` (Chinese and symbols are fine); a long random one is just
  harder to guess. The lockout is a speed bump, not a substitute for entropy.
- Quote the value in the env file when it contains spaces, `#` or quotes: `APP_PASSWORD='my pass#1'`.
  Leading and trailing spaces are trimmed, so don't rely on them.
- The password sits in plain text in `/etc/send-ip.env` (mode 600) — anyone who can read that file
  already controls the server.
- Use HTTPS end to end; never send the token over plain HTTP on the public internet.
- Bind port 8000 to `127.0.0.1` only; never expose it publicly.
