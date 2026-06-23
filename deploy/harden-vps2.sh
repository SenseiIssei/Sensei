#!/bin/bash
set -e

echo "=== Step 1: Start devpanel-client ==="
cd /opt/devpanel
docker compose -f docker-compose.prod.yml up -d 2>&1 | tail -5
sleep 5
DEVCLIENT_IP=$(docker inspect devpanel-client --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' 2>/dev/null)
echo "devpanel-client IP: $DEVCLIENT_IP"

echo ""
echo "=== Step 2: Use the correct Let's Encrypt cert path ==="
# The new real cert is at senseiissei.dev-0001
REAL_CERT=/etc/letsencrypt/live/senseiissei.dev-0001/fullchain.pem
REAL_KEY=/etc/letsencrypt/live/senseiissei.dev-0001/privkey.pem
echo "Real cert: $REAL_CERT"
openssl x509 -in $REAL_CERT -noout -issuer -dates 2>/dev/null

echo ""
echo "=== Step 3: Write hardened Nginx config ==="

cat > /etc/nginx/sites-available/sensei << NGINXEOF
# Rate limiting
limit_req_zone \$binary_remote_addr zone=sensei_api:10m rate=10r/s;

server {
    listen 80;
    server_name senseiissei.dev www.senseiissei.dev 82.165.118.241;

    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    location / {
        return 301 https://senseiissei.dev\$request_uri;
    }
}

server {
    listen 443 ssl http2;
    server_name www.senseiissei.dev;

    ssl_certificate     ${REAL_CERT};
    ssl_certificate_key ${REAL_KEY};
    ssl_protocols       TLSv1.2 TLSv1.3;

    return 301 https://senseiissei.dev\$request_uri;
}

server {
    listen 443 ssl http2;
    server_name senseiissei.dev 82.165.118.241;

    # Real Let's Encrypt certificate
    ssl_certificate         ${REAL_CERT};
    ssl_certificate_key     ${REAL_KEY};
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

    server_tokens off;
    client_max_body_size 35m;

    # SECURITY HEADERS
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
        limit_req zone=sensei_api burst=20 nodelay;
        proxy_pass http://127.0.0.1:7000;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
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

    # DevPanel (secret)
    location /devpanel/ {
        proxy_pass https://${DEVCLIENT_IP}:443/;
        proxy_http_version 1.1;
        proxy_set_header Host senseiissei.dev;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_ssl_verify off;
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

    # Static assets
    location ~* ^/assets/ {
        try_files \$uri =404;
        expires 1y;
        add_header Cache-Control "public, immutable";
        access_log off;
    }

    location = /index.html {
        try_files \$uri =404;
        expires -1;
        add_header Cache-Control "no-cache, no-store, must-revalidate";
    }

    location / {
        try_files \$uri \$uri/ /index.html;
    }
}
NGINXEOF

ln -sf /etc/nginx/sites-available/sensei /etc/nginx/sites-enabled/sensei
rm -f /etc/nginx/sites-enabled/default

echo "Testing Nginx..."
nginx -t 2>&1
systemctl restart nginx
echo ""

echo "=== Step 4: SSH Hardening ==="
cat > /etc/ssh/sshd_config.d/sensei-hardening.conf << 'SSHEOF'
Port 22
Protocol 2
PermitRootLogin prohibit-password
PasswordAuthentication yes
PubkeyAuthentication yes
MaxAuthTries 3
LoginGraceTime 30
MaxSessions 4
MaxStartups 10:30:60
ClientAliveInterval 300
ClientAliveCountMax 2
X11Forwarding no
AllowTcpForwarding no
AllowAgentForwarding no
PermitTunnel no
PermitEmptyPasswords no
ChallengeResponseAuthentication no
UsePAM yes
LogLevel VERBOSE
SyslogFacility AUTH
AllowUsers root
SSHEOF

cat > /etc/ssh/sshd_banner << 'BANNER'
Authorized access only. All activity is monitored and logged.
BANNER

systemctl restart sshd 2>/dev/null || systemctl restart ssh 2>/dev/null
echo "SSH hardened"
echo ""

echo "=== Step 5: Firewall hardening ==="
ufw deny 25565 2>/dev/null || true
ufw delete allow 25565 2>/dev/null || true
ufw delete allow 25565/tcp 2>/dev/null || true
ufw delete allow 25565/udp 2>/dev/null || true
ufw delete allow 2456:2458/udp 2>/dev/null || true
ufw limit 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw reload 2>/dev/null
echo "Firewall updated"
echo ""

echo "=== Step 6: Bind Docker ports to localhost ==="
cd /opt/sensei
sed -i 's/"${SENSEI_PORT:-7000}:7000"/"127.0.0.1:${SENSEI_PORT:-7000}:7000"/' docker-compose.yml
# Also bind frontend to localhost
if grep -q '"5173:5173"' docker-compose.yml; then
  sed -i 's/"5173:5173"/"127.0.0.1:5173:5173"/' docker-compose.yml
elif grep -q '"\${.*:-5173}:5173"' docker-compose.yml; then
  sed -i 's/"\${.*:-5173}:5173"/"127.0.0.1:${SENSEI_FRONTEND_PORT:-5173}:5173"/' docker-compose.yml
fi
docker compose up -d 2>&1 | tail -5

cd /opt/devpanel
sed -i 's/"8080:80"/"127.0.0.1:8080:80"/' docker-compose.prod.yml
docker compose -f docker-compose.prod.yml up -d 2>&1 | tail -5
cd /
echo "Docker ports bound to localhost"
echo ""

echo "=== Step 7: Fail2ban ==="
cat > /etc/fail2ban/jail.d/sensei.conf << 'F2BEOF'
[DEFAULT]
bantime = 3600
findtime = 600
maxretry = 3
banaction = ufw

[sshd]
enabled = true
port = ssh
filter = sshd
logpath = /var/log/auth.log
maxretry = 3
bantime = 7200

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
echo "Fail2ban configured"
echo ""

echo "=== Step 8: Kernel hardening ==="
cat > /etc/sysctl.d/99-sensei-hardening.conf << 'SYSCTLEOF'
net.ipv4.conf.all.rp_filter = 1
net.ipv4.conf.default.rp_filter = 1
net.ipv4.ip_forward = 0
net.ipv4.conf.all.accept_redirects = 0
net.ipv4.conf.default.accept_redirects = 0
net.ipv6.conf.all.accept_redirects = 0
net.ipv6.conf.default.accept_redirects = 0
net.ipv4.icmp_echo_ignore_broadcasts = 1
net.ipv4.conf.all.secure_redirects = 0
net.ipv4.conf.default.secure_redirects = 0
net.ipv4.conf.all.log_martians = 1
net.ipv4.conf.default.log_martians = 1
net.ipv4.conf.all.accept_source_route = 0
net.ipv4.conf.default.accept_source_route = 0
net.ipv6.conf.all.accept_source_route = 0
net.ipv6.conf.default.accept_source_route = 0
net.ipv4.tcp_syncookies = 1
fs.file-max = 65535
fs.suid_dumpable = 0
kernel.kptr_restrict = 2
kernel.perf_event_paranoid = 3
kernel.unprivileged_bpf_disabled = 1
net.ipv4.tcp_rfc1337 = 1
fs.protected_hardlinks = 1
fs.protected_symlinks = 1
fs.protected_fifos = 2
fs.protected_regular = 2
SYSCTLEOF

sysctl --system 2>&1 | tail -3

# Secure permissions
chmod 600 /opt/sensei/.env
chmod 700 /opt/sensei/.sensei_users.json 2>/dev/null || true

# Secure shared memory
if ! grep -q '/dev/shm' /etc/fstab; then
    echo 'tmpfs /dev/shm tmpfs defaults,noexec,nosuid,nodev 0 0' >> /etc/fstab
    mount -o remount /dev/shm 2>/dev/null || true
fi

# Disable unnecessary services
systemctl disable --now apport 2>/dev/null || true
systemctl disable --now motd-news 2>/dev/null || true

echo ""

echo "=== Step 9: Update devpanel IP cron ==="
cat > /usr/local/bin/update-devpanel-ip.sh << SCRIPTEOF
#!/bin/bash
DEVCLIENT_IP=\$(docker inspect devpanel-client --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' 2>/dev/null)
if [ -z "\$DEVCLIENT_IP" ]; then
    exit 0
fi
CURRENT_IP=\$(grep -oP 'proxy_pass https://\K[0-9.]+' /etc/nginx/sites-available/sensei | head -1)
if [ "\$DEVCLIENT_IP" != "\$CURRENT_IP" ]; then
    sed -i "s|proxy_pass https://[0-9.]*:443/|proxy_pass https://\${DEVCLIENT_IP}:443/|g" /etc/nginx/sites-available/sensei
    sed -i "s|proxy_pass https://[0-9.]*:443/api/|proxy_pass https://\${DEVCLIENT_IP}:443/api/|g" /etc/nginx/sites-available/sensei
    sed -i "s|proxy_pass https://[0-9.]*:443/uploads/|proxy_pass https://\${DEVCLIENT_IP}:443/uploads/|g" /etc/nginx/sites-available/sensei
    nginx -t 2>&1 && systemctl reload nginx
    echo "Updated devpanel IP to \$DEVCLIENT_IP"
fi
SCRIPTEOF
chmod +x /usr/local/bin/update-devpanel-ip.sh
(crontab -l 2>/dev/null | grep -v update-devpanel-ip; echo "* * * * * /usr/local/bin/update-devpanel-ip.sh > /dev/null 2>&1") | crontab -

# Run it once now
/usr/local/bin/update-devpanel-ip.sh

echo ""
echo "=========================================="
echo "  FINAL VERIFICATION"
echo "=========================================="
echo ""

echo "1. SSL Certificate (should be Let's Encrypt):"
echo | openssl s_client -connect senseiissei.dev:443 -servername senseiissei.dev 2>/dev/null | openssl x509 -noout -issuer -subject -dates 2>/dev/null
echo ""

echo "2. SSL Chain verification (should be code 0):"
echo | openssl s_client -connect senseiissei.dev:443 -servername senseiissei.dev 2>/dev/null | grep 'Verify return code'
echo ""

echo "3. Sensei frontend:"
curl -s -o /dev/null -w "  HTTP %{http_code}" https://senseiissei.dev/
echo ""

echo "4. DevPanel:"
curl -s -o /dev/null -w "  HTTP %{http_code}" https://senseiissei.dev/devpanel/
echo ""

echo "5. API:"
curl -s -o /dev/null -w "  HTTP %{http_code}" https://senseiissei.dev/api/models
echo ""

echo "6. Health:"
curl -s https://senseiissei.dev/health
echo ""

echo "7. SSH config:"
grep -E 'PermitRootLogin|PasswordAuth|MaxAuthTries|X11Forward|AllowTcp' /etc/ssh/sshd_config.d/sensei-hardening.conf
echo ""

echo "8. Firewall (should only have 22, 80, 443):"
ufw status | grep -v '^$'
echo ""

echo "9. Fail2ban:"
fail2ban-client status 2>/dev/null
echo ""

echo "10. Exposed ports (should only be 22, 80, 443):"
ss -tlnp | grep LISTEN | grep -v '127.0.0' | grep -v '127.0.0.5'
echo ""

echo "11. Docker ports (should all be 127.0.0.1):"
docker ps --format '{{.Names}}: {{.Ports}}' 2>/dev/null
echo ""

echo "12. Security headers:"
curl -sI https://senseiissei.dev/ 2>/dev/null | grep -iE 'strict-transport|x-frame|x-content|x-xss|referrer|permissions|content-security'
echo ""

echo "=========================================="
echo "  HARDENING COMPLETE"
echo "=========================================="
