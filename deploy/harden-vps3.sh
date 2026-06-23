#!/bin/bash
set -e

echo "=== Restart Nginx ==="
systemctl restart nginx
sleep 2

echo "=== SSH Hardening ==="
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

echo "Authorized access only. All activity is monitored and logged." > /etc/ssh/sshd_banner
systemctl restart sshd 2>/dev/null || systemctl restart ssh 2>/dev/null
echo "SSH hardened"

echo ""
echo "=== Firewall ==="
ufw deny 25565 2>/dev/null || true
ufw delete allow 25565 2>/dev/null || true
ufw delete allow 25565/tcp 2>/dev/null || true
ufw delete allow 25565/udp 2>/dev/null || true
ufw delete allow 2456:2458/udp 2>/dev/null || true
ufw limit 22/tcp 2>/dev/null || true
ufw allow 80/tcp 2>/dev/null || true
ufw allow 443/tcp 2>/dev/null || true
ufw reload 2>/dev/null
echo "Firewall updated"

echo ""
echo "=== Bind Docker ports to localhost ==="
cd /opt/sensei
sed -i 's/"${SENSEI_PORT:-7000}:7000"/"127.0.0.1:${SENSEI_PORT:-7000}:7000"/' docker-compose.yml
if grep -q '"5173:5173"' docker-compose.yml; then
  sed -i 's/"5173:5173"/"127.0.0.1:5173:5173"/' docker-compose.yml
fi
docker compose up -d 2>&1 | tail -3

cd /opt/devpanel
sed -i 's/"8080:80"/"127.0.0.1:8080:80"/' docker-compose.prod.yml
docker compose -f docker-compose.prod.yml up -d 2>&1 | tail -3
cd /
echo "Docker ports bound to localhost"

echo ""
echo "=== Fail2ban ==="
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
echo "=== Kernel hardening ==="
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

chmod 600 /opt/sensei/.env
chmod 700 /opt/sensei/.sensei_users.json 2>/dev/null || true

if ! grep -q '/dev/shm' /etc/fstab; then
    echo 'tmpfs /dev/shm tmpfs defaults,noexec,nosuid,nodev 0 0' >> /etc/fstab
    mount -o remount /dev/shm 2>/dev/null || true
fi

systemctl disable --now apport 2>/dev/null || true
systemctl disable --now motd-news 2>/dev/null || true
echo "Kernel hardened"

echo ""
echo "=== Update devpanel IP ==="
sleep 5
DEVCLIENT_IP=$(docker inspect devpanel-client --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' 2>/dev/null)
if [ -n "$DEVCLIENT_IP" ]; then
    sed -i "s|proxy_pass https://[0-9.]*:443/|proxy_pass https://${DEVCLIENT_IP}:443/|g" /etc/nginx/sites-available/sensei
    sed -i "s|proxy_pass https://[0-9.]*:443/api/|proxy_pass https://${DEVCLIENT_IP}:443/api/|g" /etc/nginx/sites-available/sensei
    sed -i "s|proxy_pass https://[0-9.]*:443/uploads/|proxy_pass https://${DEVCLIENT_IP}:443/uploads/|g" /etc/nginx/sites-available/sensei
    nginx -t 2>&1 && systemctl reload nginx
fi

cat > /usr/local/bin/update-devpanel-ip.sh << 'SCRIPTEOF'
#!/bin/bash
DEVCLIENT_IP=$(docker inspect devpanel-client --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' 2>/dev/null)
if [ -z "$DEVCLIENT_IP" ]; then exit 0; fi
CURRENT_IP=$(grep -oP 'proxy_pass https://\K[0-9.]+' /etc/nginx/sites-available/sensei | head -1)
if [ "$DEVCLIENT_IP" != "$CURRENT_IP" ]; then
    sed -i "s|proxy_pass https://[0-9.]*:443/|proxy_pass https://${DEVCLIENT_IP}:443/|g" /etc/nginx/sites-available/sensei
    sed -i "s|proxy_pass https://[0-9.]*:443/api/|proxy_pass https://${DEVCLIENT_IP}:443/api/|g" /etc/nginx/sites-available/sensei
    sed -i "s|proxy_pass https://[0-9.]*:443/uploads/|proxy_pass https://${DEVCLIENT_IP}:443/uploads/|g" /etc/nginx/sites-available/sensei
    nginx -t 2>&1 && systemctl reload nginx
fi
SCRIPTEOF
chmod +x /usr/local/bin/update-devpanel-ip.sh
(crontab -l 2>/dev/null | grep -v update-devpanel-ip; echo "* * * * * /usr/local/bin/update-devpanel-ip.sh > /dev/null 2>&1") | crontab -

echo ""
echo "=========================================="
echo "  FINAL VERIFICATION"
echo "=========================================="
echo ""

echo "1. SSL Certificate:"
echo | openssl s_client -connect senseiissei.dev:443 -servername senseiissei.dev 2>/dev/null | openssl x509 -noout -issuer -subject -dates 2>/dev/null
echo ""

echo "2. SSL Verification:"
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

echo "7. SSH:"
grep -E 'PermitRootLogin|PasswordAuth|MaxAuthTries|X11Forward|AllowTcp' /etc/ssh/sshd_config.d/sensei-hardening.conf
echo ""

echo "8. Firewall:"
ufw status | grep -v '^$'
echo ""

echo "9. Fail2ban:"
fail2ban-client status 2>/dev/null
echo ""

echo "10. Exposed ports (should only be 22, 80, 443):"
ss -tlnp | grep LISTEN | grep -v '127.0.0' | grep -v '127.0.0.5'
echo ""

echo "11. Docker ports:"
docker ps --format '{{.Names}}: {{.Ports}}' 2>/dev/null
echo ""

echo "12. Security headers:"
curl -sI https://senseiissei.dev/ 2>/dev/null | grep -iE 'strict-transport|x-frame|x-content|x-xss|referrer|permissions|content-security'
echo ""

echo "=========================================="
echo "  HARDENING COMPLETE"
echo "=========================================="
