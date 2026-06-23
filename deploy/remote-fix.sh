#!/bin/bash
set -e

echo "=== Fix 1: Remove 443 port from devpanel-client ==="
# Check if 443 is still mapped
if docker port devpanel-client 443 2>/dev/null; then
  sed -i '/"443:443"/d' /opt/devpanel/docker-compose.prod.yml
  cd /opt/devpanel
  docker compose -f docker-compose.prod.yml up -d client 2>&1 | tail -3
  cd /
fi
echo "devpanel-client ports:"
docker ps --filter name=devpanel-client --format '{{.Ports}}'

echo ""
echo "=== Fix 2: Write clean Nginx config ==="
cat > /etc/nginx/sites-available/sensei << 'NGINXEOF'
# Sensei + DevPanel unified Nginx config

server {
    listen 80;
    server_name senseiissei.dev www.senseiissei.dev 82.165.118.241;

    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    location / {
        return 301 https://senseiissei.dev$request_uri;
    }
}

server {
    listen 443 ssl;
    server_name www.senseiissei.dev;

    ssl_certificate     /etc/letsencrypt/live/senseiissei.dev/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/senseiissei.dev/privkey.pem;
    ssl_protocols       TLSv1.2 TLSv1.3;

    return 301 https://senseiissei.dev$request_uri;
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
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Sensei WebSocket
    location /api/chat/ws {
        proxy_pass http://127.0.0.1:7000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 86400;
    }

    # Health
    location /health {
        proxy_pass http://127.0.0.1:7000;
    }

    # DevPanel (secret)
    location /devpanel/ {
        proxy_pass http://127.0.0.1:8080/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        sub_filter 'href="/' 'href="/devpanel/';
        sub_filter 'src="/' 'src="/devpanel/';
        sub_filter_once off;
        sub_filter_types text/html application/javascript text/css;
    }

    location /devpanel/api/ {
        proxy_pass http://127.0.0.1:8080/api/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location /devpanel/uploads/ {
        proxy_pass http://127.0.0.1:8080/uploads/;
        proxy_set_header Host $host;
    }

    # Sensei static assets
    location ~* ^/assets/ {
        try_files $uri =404;
        expires 1y;
        add_header Cache-Control "public, immutable";
        access_log off;
    }

    location = /index.html {
        try_files $uri =404;
        expires -1;
        add_header Cache-Control "no-cache, no-store, must-revalidate";
    }

    location / {
        try_files $uri $uri/ /index.html;
    }

    gzip on;
    gzip_types text/css application/javascript application/json;
    gzip_min_length 1000;
}
NGINXEOF

ln -sf /etc/nginx/sites-available/sensei /etc/nginx/sites-enabled/sensei
rm -f /etc/nginx/sites-enabled/default

echo "Testing Nginx config..."
nginx -t 2>&1
echo "Starting Nginx..."
systemctl start nginx 2>&1 || systemctl restart nginx 2>&1
systemctl enable nginx 2>&1
systemctl reload nginx 2>&1

echo ""
echo "=== Verification ==="
echo "1. Sensei backend (port 7000):"
curl -s http://localhost:7000/health 2>/dev/null
echo ""

echo "2. Sensei frontend (HTTPS):"
curl -sk -o /dev/null -w "HTTP %{http_code}" https://localhost/ 2>/dev/null
echo ""

echo "3. DevPanel (HTTPS /devpanel/):"
curl -sk -o /dev/null -w "HTTP %{http_code}" https://localhost/devpanel/ 2>/dev/null
echo ""

echo "4. Nginx status:"
systemctl is-active nginx
echo ""

echo "5. All containers:"
docker ps --format "table {{.Names}}\t{{.Ports}}\t{{.Status}}" 2>/dev/null
echo ""

echo "=== Done ==="
echo "Public chat:  https://senseiissei.dev"
echo "Dev panel:    https://senseiissei.dev/devpanel/"
