#!/bin/bash
set -e

echo "=== Update Nginx to proxy DevPanel via HTTPS ==="

# Get devpanel-client container IP
DEVCLIENT_IP=$(docker inspect devpanel-client --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}')
echo "devpanel-client IP: $DEVCLIENT_IP"

# Write updated nginx config
cat > /etc/nginx/sites-available/sensei << NGINXEOF
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
    listen 443 ssl;
    server_name www.senseiissei.dev;

    ssl_certificate     /etc/letsencrypt/live/senseiissei.dev/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/senseiissei.dev/privkey.pem;
    ssl_protocols       TLSv1.2 TLSv1.3;

    return 301 https://senseiissei.dev\$request_uri;
}

server {
    listen 443 ssl;
    server_name senseiissei.dev 82.165.118.241;

    ssl_certificate     /etc/letsencrypt/live/senseiissei.dev/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/senseiissei.dev/privkey.pem;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers off;
    ssl_session_cache   shared:SSL:10m;
    ssl_session_timeout 1d;

    server_tokens off;
    client_max_body_size 35m;

    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;

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
    }

    # Sensei WebSocket
    location /api/chat/ws {
        proxy_pass http://127.0.0.1:7000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_read_timeout 86400;
    }

    # Health
    location /health {
        proxy_pass http://127.0.0.1:7000;
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

    # Sensei static assets
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

echo "Reloading Nginx..."
systemctl reload nginx

echo ""
echo "=== Final Verification ==="
echo "1. Sensei frontend:"
curl -sk -o /dev/null -w "HTTP %{http_code}" https://senseiissei.dev/ 2>/dev/null
echo ""

echo "2. Sensei API:"
curl -sk -o /dev/null -w "HTTP %{http_code}" https://senseiissei.dev/api/models 2>/dev/null
echo ""

echo "3. Sensei health:"
curl -sk https://senseiissei.dev/health 2>/dev/null
echo ""

echo "4. DevPanel:"
curl -sk -o /dev/null -w "HTTP %{http_code}" https://senseiissei.dev/devpanel/ 2>/dev/null
echo ""

echo "5. Nginx:"
systemctl is-active nginx
echo ""

echo "=== All containers ==="
docker ps --format "table {{.Names}}\t{{.Ports}}\t{{.Status}}" 2>/dev/null
echo ""
echo "=== Done ==="
