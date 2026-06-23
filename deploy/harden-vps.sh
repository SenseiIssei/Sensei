#!/bin/bash
set -e

echo "=========================================="
echo "  SENSEI VPS SECURITY HARDENING"
echo "=========================================="
echo ""

# ── 1. GET REAL LET'S ENCRYPT CERTIFICATE ──
echo "[1/8] Getting real Let's Encrypt SSL certificate..."
# Stop nginx temporarily so certbot can use standalone mode
systemctl stop nginx 2>/dev/null || true

# Get the certificate
certbot certonly --standalone \
  -d senseiissei.dev \
  -d www.senseiissei.dev \
  --non-interactive \
  --agree-tos \
  --register-unsafely-without-email \
  --keep-until-expiring 2>&1 || {
    echo "Standalone failed, trying webroot method..."
    systemctl start nginx
    sleep 2
    mkdir -p /var/www/certbot
    certbot certonly --webroot \
      -w /var/www/certbot \
      -d senseiissei.dev \
      -d www.senseiissei.dev \
      --non-interactive \
      --agree-tos \
      --register-unsafely-without-email 2>&1
  }

# Verify the new cert
echo "New certificate:"
openssl x509 -in /etc/letsencrypt/live/senseiissei.dev/fullchain.pem -noout -issuer -subject -dates 2>/dev/null

# Set up auto-renewal
echo "Setting up auto-renewal..."
systemctl enable certbot.timer 2>/dev/null || true
systemctl start certbot.timer 2>/dev/null || true

# Create renewal hook to reload nginx
mkdir -p /etc/letsencrypt/renewal-hooks/deploy
cat > /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh << 'HOOK'
#!/bin/bash
systemctl reload nginx
HOOK
chmod +x /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh

echo ""

# ── 2. UPDATE NGINX WITH REAL CERT + SECURITY HEADERS ──
echo "[2/8] Updating Nginx with real cert + security headers..."

DEVCLIENT_IP=$(docker inspect devpanel-client --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' 2>/dev/null || echo "127.0.0.1")
echo "devpanel-client IP: $DEVCLIENT_IP"

cat > /etc/nginx/sites-available/sensei << NGINXEOF
server {
    listen 80;
    server_name senseiissei.dev www.senseiissei.dev 82.165.118.241;

    # ACME challenge
    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    # Redirect everything to HTTPS
    location / {
        return 301 https://senseiissei.dev\$request_uri;
    }
}

# www -> non-www redirect
server {
    listen 443 ssl http2;
    server_name www.senseiissei.dev;

    ssl_certificate     /etc/letsencrypt/live/senseiissei.dev/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/senseiissei.dev/privkey.pem;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers off;

    return 301 https://senseiissei.dev\$request_uri;
}

# Main server
server {
    listen 443 ssl http2;
    server_name senseiissei.dev 82.165.118.241;

    # Real Let's Encrypt certificate
    ssl_certificate         /etc/letsencrypt/live/senseiissei.dev/fullchain.pem;
    ssl_certificate_key     /etc/letsencrypt/live/senseiissei.dev/privkey.pem;
    ssl_protocols           TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers off;
    ssl_session_cache       shared:SSL:10m;
    ssl_session_timeout     1d;
    ssl_session_tickets     off;

    # OCSP stapling
    ssl_stapling            on;
    ssl_stapling_verify     on;
    resolver                1.1.1.1 8.8.8.8 valid=300s;
    resolver_timeout        5s;

    # Hide server version
    server_tokens off;

    # Max upload size
    client_max_body_size 35m;

    # ── SECURITY HEADERS ──
    add_header Strict-Transport-Security "max-age=63072000; includeSubDomains; preload" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    add_header Permissions-Policy "geolocation=(), microphone=(), camera=(), payment=()" always;
    add_header Content-Security-Policy "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; font-src 'self' data:; img-src 'self' data: blob: https:; connect-src 'self' wss: ws:; frame-ancestors 'none'; object-src 'none'; base-uri 'self'" always;

    root /opt/sensei/frontend/dist;
    index index.html;

    # Sensei API
    location /api/ {
        proxy_pass http://127.0.0.1:7000;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        # Rate limiting per IP
        limit_req zone=sensei_api burst=20 nodelay;
    }

    # Sensei WebSocket
    location /api/chat/ws {
        proxy_pass http://127.0.0.1:7000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_read_timeout 86400;
    }

    # Health
    location /health {
        proxy_pass http://127.0.0.1:7000;
        access_log off;
    }

    # DevPanel (secret) - proxy to container HTTPS
    location /devpanel/ {
        proxy_pass https://${DEVCLIENT_IP}:443/;
        proxy_http_version 1.1;
        proxy_set_header Host senseiissei.dev;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_ssl_verify off;
        # Rewrite paths for subfolder
        sub_filter 'href="/' 'href="/devpanel/';
        sub_filter 'src="/' 'src="/devpanel/';
        sub_filter_once off;
        sub_filter_types text/html application/javascript text/css;
    }

    location /devpanel/api/ {
        proxy_pass https://${DEVCLIENT_IP}:443/api/;
        proxy_http_version 1.1;
        proxy_set_header Host senseiissei.dev;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-Proto https;
        proxy_ssl_verify off;
    }

    location /devpanel/uploads/ {
        proxy_pass https://${DEVCLIENT_IP}:443/uploads/;
        proxy_set_header Host senseiissei.dev;
        proxy_ssl_verify off;
    }

    # Sensei static assets - cache aggressively
    location ~* ^/assets/ {
        try_files \$uri =404;
        expires 1y;
        add_header Cache-Control "public, immutable";
        access_log off;
    }

    # index.html - never cache
    location = /index.html {
        try_files \$uri =404;
        expires -1;
        add_header Cache-Control "no-cache, no-store, must-revalidate";
    }

    # SPA fallback
    location / {
        try_files \$uri \$uri/ /index.html;
    }
}
NGINXEOF

# Add rate limiting zone to nginx.conf http block
if ! grep -q 'sensei_api' /etc/nginx/nginx.conf; then
    sed -i '/http {/a\\tlimit_req_zone $binary_remote_addr zone=sensei_api:10m rate=10r/s;' /etc/nginx/nginx.conf
fi

# Create webroot for certbot
mkdir -p /var/www/certbot

ln -sf /etc/nginx/sites-available/sensei /etc/nginx/sites-enabled/sensei
rm -f /etc/nginx/sites-enabled/default

echo "Testing Nginx config..."
nginx -t 2>&1
systemctl start nginx
systemctl reload nginx
echo ""

# ── 3. HARDEN SSH ──
echo "[3/8] Hardening SSH configuration..."

# Backup original sshd_config
cp /etc/ssh/sshd_config /etc/ssh/sshd_config.bak.$(date +%s)

# Apply SSH hardening
cat > /etc/ssh/sshd_config.d/sensei-hardening.conf << 'SSHEOF'
# Sensei SSH Hardening
Port 22
Protocol 2

# Authentication
PermitRootLogin prohibit-password
PasswordAuthentication yes
PubkeyAuthentication yes
MaxAuthTries 3
LoginGraceTime 30

# Session limits
MaxSessions 4
MaxStartups 10:30:60
ClientAliveInterval 300
ClientAliveCountMax 2

# Security
X11Forwarding no
AllowTcpForwarding no
AllowAgentForwarding no
PermitTunnel no
PermitEmptyPasswords no
ChallengeResponseAuthentication no
UsePAM yes

# Logging
LogLevel VERBOSE
SyslogFacility AUTH

# Allow only root and specific users
AllowUsers root

# Banner (optional)
Banner /etc/ssh/sshd_banner
SSHEOF

# Create login banner
cat > /etc/ssh/sshd_banner << 'BANNER'
╔═══════════════════════════════════════════════╗
║  Authorized access only. All activity is     ║
║  monitored and logged. Unauthorized access    ║
║  will be prosecuted to the full extent of law ║
╚═══════════════════════════════════════════════╝
BANNER

# Restart SSH
systemctl restart sshd 2>/dev/null || systemctl restart ssh 2>/dev/null
echo "SSH hardened (root login: key-only, max auth tries: 3, no X11/tunnel forwarding)"
echo ""

# ── 4. CLOSE UNNECESSARY FIREWALL PORTS ──
echo "[4/8] Hardening firewall..."

# Close game server ports (not needed for Sensei)
ufw deny 25565 2>/dev/null || true
ufw delete allow 25565 2>/dev/null || true
ufw delete allow 25565/tcp 2>/dev/null || true
ufw delete allow 25565/udp 2>/dev/null || true
ufw delete allow 2456:2458/udp 2>/dev/null || true

# Only allow essential ports
ufw allow 22/tcp comment 'SSH'
ufw allow 80/tcp comment 'HTTP'
ufw allow 443/tcp comment 'HTTPS'

# Enable rate limiting for SSH
ufw limit 22/tcp

# Reload
ufw reload 2>/dev/null

echo "Firewall rules updated:"
ufw status numbered 2>/dev/null
echo ""

# ── 5. BIND DOCKER PORTS TO LOCALHOST ONLY ──
echo "[5/8] Binding Docker ports to localhost only..."

# Update Sensei docker-compose to bind to 127.0.0.1
sed -i 's/"${SENSEI_PORT:-7000}:7000"/"127.0.0.1:${SENSEI_PORT:-7000}:7000"/' /opt/sensei/docker-compose.yml
sed -i 's/"5173:5173"/"127.0.0.1:5173:5173"/' /opt/sensei/docker-compose.yml 2>/dev/null || true

# Update devpanel docker-compose to bind 8080 to localhost only
sed -i 's/"8080:80"/"127.0.0.1:8080:80"/' /opt/devpanel/docker-compose.prod.yml

# Restart containers with new port bindings
cd /opt/sensei
docker compose up -d 2>&1 | tail -5
cd /opt/devpanel
docker compose -f docker-compose.prod.yml up -d 2>&1 | tail -5
cd /

echo "Docker ports bound to localhost:"
docker ps --format '{{.Names}}: {{.Ports}}' 2>/dev/null
echo ""

# ── 6. FAIL2BAN JAILS ──
echo "[6/8] Configuring fail2ban jails..."

cat > /etc/fail2ban/jail.d/sensei.conf << 'F2BEOF'
[DEFAULT]
bantime = 3600
findtime = 600
maxretry = 3
banaction = ufw

# SSH protection
[sshd]
enabled = true
port = ssh
filter = sshd
logpath = /var/log/auth.log
maxretry = 3
bantime = 7200

# Nginx protection
[nginx-limit-req]
enabled = true
filter = nginx-limit-req
port = http,https
logpath = /var/log/nginx/error.log
maxretry = 5
bantime = 7200

[nginx-botsearch]
enabled = true
port = http,https
logpath = /var/log/nginx/access.log
maxretry = 2
bantime = 7200

[nginx-http-auth]
enabled = true
port = http,https
logpath = /var/log/nginx/error.log
maxretry = 3
bantime = 3600

# Recidive - ban repeat offenders for longer
[recidive]
enabled = true
filter = recidive
logpath = /var/log/fail2ban.log
action = ufw
bantime = 86400
findtime = 86400
maxretry = 3
F2BEOF

systemctl restart fail2ban
systemctl enable fail2ban
echo "Fail2ban jails configured:"
fail2ban-client status 2>/dev/null
echo ""

# ── 7. ADDITIONAL HARDENING ──
echo "[7/8] Additional system hardening..."

# Disable IPv6 if not needed (reduces attack surface)
# (Commented out in case user needs IPv6)
# net.ipv6.conf.all.disable_ipv6 = 1

# Kernel hardening via sysctl
cat > /etc/sysctl.d/99-sensei-hardening.conf << 'SYSCTLEOF'
# Prevent IP spoofing
net.ipv4.conf.all.rp_filter = 1
net.ipv4.conf.default.rp_filter = 1

# Disable IP forwarding
net.ipv4.ip_forward = 0

# Ignore ICMP redirects
net.ipv4.conf.all.accept_redirects = 0
net.ipv4.conf.default.accept_redirects = 0
net.ipv6.conf.all.accept_redirects = 0
net.ipv6.conf.default.accept_redirects = 0

# Ignore ICMP broadcast requests (smurf attacks)
net.ipv4.icmp_echo_ignore_broadcasts = 1

# Reverse path filtering
net.ipv4.conf.all.secure_redirects = 0
net.ipv4.conf.default.secure_redirects = 0

# Log martian packets
net.ipv4.conf.all.log_martians = 1
net.ipv4.conf.default.log_martians = 1

# Disable source routing
net.ipv4.conf.all.accept_source_route = 0
net.ipv4.conf.default.accept_source_route = 0
net.ipv6.conf.all.accept_source_route = 0
net.ipv6.conf.default.accept_source_route = 0

# TCP SYN cookies (prevent SYN flood)
net.ipv4.tcp_syncookies = 1

# Increase system file descriptor limits
fs.file-max = 65535

# Restrict core dumps
fs.suid_dumpable = 0

# Hide kernel pointers
kernel.kptr_restrict = 2

# Restrict kernel profiling
kernel.perf_event_paranoid = 3

# Disable unprivileged BPF
kernel.unprivileged_bpf_disabled = 1

# Protect against time-wait assassination
net.ipv4.tcp_rfc1337 = 1

# Disable unused filesystems
fs.protected_hardlinks = 1
fs.protected_symlinks = 1
fs.protected_fifos = 2
fs.protected_regular = 2
SYSCTLEOF

sysctl --system 2>&1 | tail -3

# Disable unnecessary services
systemctl disable --now apport 2>/dev/null || true
systemctl disable --now motd-news 2>/dev/null || true

# Set secure permissions on key files
chmod 600 /etc/ssh/sshd_config
chmod 600 /opt/sensei/.env
chmod 700 /opt/sensei/.sensei_users.json 2>/dev/null || true

# Secure shared memory
if ! grep -q '/dev/shm' /etc/fstab; then
    echo 'tmpfs /dev/shm tmpfs defaults,noexec,nosuid,nodev 0 0' >> /etc/fstab
    mount -o remount /dev/shm 2>/dev/null || true
fi

echo "System hardened (kernel, sysctl, permissions, shared memory)"
echo ""

# ── 8. UPDATE DEVPANEL IP CRON (in case IP changed) ──
echo "[8/8] Updating DevPanel IP in Nginx..."
DEVCLIENT_IP=$(docker inspect devpanel-client --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' 2>/dev/null)
if [ -n "$DEVCLIENT_IP" ]; then
    sed -i "s|proxy_pass https://[0-9.]*:443/|proxy_pass https://${DEVCLIENT_IP}:443/|g" /etc/nginx/sites-available/sensei
    sed -i "s|proxy_pass https://[0-9.]*:443/api/|proxy_pass https://${DEVCLIENT_IP}:443/api/|g" /etc/nginx/sites-available/sensei
    sed -i "s|proxy_pass https://[0-9.]*:443/uploads/|proxy_pass https://${DEVCLIENT_IP}:443/uploads/|g" /etc/nginx/sites-available/sensei
    nginx -t 2>&1 && systemctl reload nginx
fi

echo ""
echo "=========================================="
echo "  FINAL VERIFICATION"
echo "=========================================="
echo ""

echo "1. SSL Certificate:"
echo | openssl s_client -connect senseiissei.dev:443 -servername senseiissei.dev 2>/dev/null | openssl x509 -noout -issuer -subject -dates 2>/dev/null
echo ""

echo "2. SSL Chain verification:"
echo | openssl s_client -connect senseiissei.dev:443 -servername senseiissei.dev 2>/dev/null | grep 'Verify return code'
echo ""

echo "3. Sensei frontend:"
curl -sk -o /dev/null -w "  HTTP %{http_code}" https://senseiissei.dev/
echo ""

echo "4. DevPanel:"
curl -sk -o /dev/null -w "  HTTP %{http_code}" https://senseiissei.dev/devpanel/
echo ""

echo "5. API:"
curl -sk -o /dev/null -w "  HTTP %{http_code}" https://senseiissei.dev/api/models
echo ""

echo "6. Health:"
curl -sk https://senseiissei.dev/health
echo ""

echo "7. SSH config:"
grep -E 'PermitRootLogin|PasswordAuthentication|MaxAuthTries' /etc/ssh/sshd_config.d/sensei-hardening.conf
echo ""

echo "8. Firewall:"
uff status 2>/dev/null || ufw status
echo ""

echo "9. Fail2ban:"
fail2ban-client status 2>/dev/null
echo ""

echo "10. Exposed ports (should only see 22, 80, 443):"
ss -tlnp | grep LISTEN | grep -v '127.0.0' | grep -v '127.0.0.53' | grep -v '127.0.0.54'
echo ""

echo "11. Docker ports (should be 127.0.0.1 only):"
docker ps --format '{{.Names}}: {{.Ports}}' 2>/dev/null
echo ""

echo "=========================================="
echo "  SECURITY HARDENING COMPLETE"
echo "=========================================="
echo ""
echo "What was done:"
echo "  1. Real Let's Encrypt SSL certificate (no more browser warnings)"
echo "  2. Auto-renewal configured with nginx reload hook"
echo "  3. SSH: root login key-only, max 3 tries, no X11/tunnel forwarding"
echo "  4. Firewall: closed game ports, rate-limited SSH, only 22/80/443 open"
echo "  5. Docker ports bound to 127.0.0.1 (not accessible from internet)"
echo "  6. Fail2ban: SSH + Nginx jails with 1-2hr bans, repeat offender tracking"
echo "  7. Kernel hardening: SYN cookies, anti-spoofing, no source routing"
echo "  8. Nginx: HSTS, CSP, X-Frame-Options, X-Content-Type-Options, rate limiting"
echo "  9. HTTP/2 enabled, OCSP stapling, secure SSL protocols only"
echo "  10. Login banner, secure shared memory, file permissions locked down"
echo ""
echo "IMPORTANT: Set up SSH key authentication and then disable password auth:"
echo "  ssh-keygen -t ed25519  (on your local machine)"
echo "  ssh-copy-id root@82.165.118.241"
echo "  # Then edit /etc/ssh/sshd_config.d/sensei-hardening.conf"
echo "  # Set: PasswordAuthentication no"
echo "  # Restart: systemctl restart sshd"
