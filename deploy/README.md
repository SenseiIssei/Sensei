# Deploying Sensei behind a reverse proxy

Run the Sensei backend bound to localhost and let a reverse proxy terminate TLS,
add a real domain, and (optionally) front-line auth. Templates here:

| File | Use |
|------|-----|
| [`sensei.service`](sensei.service) | systemd unit to run the backend as a service |
| [`nginx.conf`](nginx.conf) | Nginx reverse proxy (TLS + SSE-safe streaming) |
| [`Caddyfile`](Caddyfile) | Caddy reverse proxy (automatic HTTPS) |
| [`traefik-dynamic.yml`](traefik-dynamic.yml) | Traefik dynamic config |

## The one gotcha: streaming

Sensei streams in several places — the SSE chat (`/api/chat/stream`), the
compression **gateway** (`/v1/...`), and the chat WebSocket (`/api/chat/ws`).
**Disable proxy buffering** for those paths or tokens arrive in one lump:

- Nginx: `proxy_buffering off;` (already scoped to those routes in `nginx.conf`)
- Caddy: `flush_interval -1`
- Traefik: streaming works by default

## Security when exposing publicly

The backend has no TLS and minimal auth by default — that's fine *behind* the
proxy on localhost. When the proxy is internet-facing, also:

- `SENSEI_AUTH_ENABLED=true` + `SENSEI_AUTH_TOKEN=<random>` (bearer auth on the API)
- `SENSEI_RATE_LIMIT_ENABLED=true` (on by default)
- consider `SENSEI_REDACTION_ENABLED=true` (DLP) and `SENSEI_BLOCKED_MODELS` / `SENSEI_BLOCKED_PATTERNS` (policy)
- put real keys in the encrypted vault (set them via the Key UI / `PUT /api/settings`), not plaintext `.env`

## Quick start (Linux)

```bash
sudo useradd -r -s /usr/sbin/nologin sensei
sudo git clone https://github.com/SenseiIssei/Sensei.git /opt/sensei
cd /opt/sensei && sudo ./install.sh           # builds venv + web UI
sudo cp deploy/sensei.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now sensei
sudo cp deploy/nginx.conf /etc/nginx/sites-available/sensei   # edit server_name + certs
sudo ln -s /etc/nginx/sites-available/sensei /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```
