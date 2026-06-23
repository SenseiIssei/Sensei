#!/bin/bash
set -e

echo "=== Step 1: Move devpanel-client to port 8080 ==="

# Backup the original docker-compose
cp /opt/devpanel/docker-compose.prod.yml /opt/devpanel/docker-compose.prod.yml.bak

# Change port mapping from 80:80 to 8080:80
sed -i 's/"80:80"/"8080:80"/' /opt/devpanel/docker-compose.prod.yml

# Also remove the 443 port mapping if it exists
sed -i '/"443:443"/d' /opt/devpanel/docker-compose.prod.yml

# Restart devpanel-client with new port
cd /opt/devpanel
docker compose -f docker-compose.prod.yml up -d client 2>&1 | tail -5
cd /

echo "=== Step 2: Verify devpanel-client is on 8080 ==="
docker ps --filter name=devpanel-client --format '{{.Ports}}'
sleep 3
curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/ || echo " (connection failed)"

echo ""
echo "=== Step 3: Get devpanel-server IP ==="
DEVSERVER_IP=$(docker inspect devpanel-server --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}')
echo "devpanel-server IP: $DEVSERVER_IP"

echo ""
echo "=== Step 4: Configure host Nginx ==="

cat > /etc/nginx/sites-available/sensei << 'NGINXEOF'
# Sensei + DevPanel unified Nginx config
# - senseiissei.dev/         -> Sensei public chat
# - senseiissei.dev/devpanel/ -> DevPanel (secret)
# - senseiissei.dev/api/      -> Sensei backend

# Rate limiting
limit_req_zone $binary_remote_addr zone=sensei_api:10m rate=60r/s;

# HTTP: ACME challenge + redirect to HTTPS
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

# HTTPS: www redirect
server {
    listen 443 ssl;
    server_name www.senseiissei.dev;

    ssl_certificate     /etc/letsencrypt/live/senseiissei.dev/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/senseiissei.dev/privkey.pem;
    ssl_protocols       TLSv1.2 TLSv1.3;

    return 301 https://senseiissei.dev$request_uri;
}

# HTTPS: main server
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

    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;

    # ---- Sensei public chat (main site) ----
    root /opt/sensei/frontend/dist;
    index index.html;

    # Sensei API proxy
    location /api/ {
        limit_req zone=sensei_api burst=10 nodelay;
        proxy_pass http://127.0.0.1:7000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Sensei WebSocket for chat streaming
    location /api/chat/ws {
        proxy_pass http://127.0.0.1:7000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 86400;
    }

    # Sensei health check
    location /health {
        proxy_pass http://127.0.0.1:7000;
    }

    # ---- DevPanel (secret, at /devpanel/) ----
    location /devpanel/ {
        proxy_pass http://127.0.0.1:8080/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        # Rewrite absolute paths in HTML to include /devpanel/ prefix
        sub_filter 'href="/' 'href="/devpanel/';
        sub_filter 'src="/' 'src="/devpanel/';
        sub_filter 'action="/' 'action="/devpanel/';
        sub_filter_once off;
        sub_filter_types text/html text/css application/javascript;
    }

    # DevPanel API (if needed separately)
    location /devpanel/api/ {
        proxy_pass http://127.0.0.1:8080/api/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # DevPanel uploads
    location /devpanel/uploads/ {
        proxy_pass http://127.0.0.1:8080/uploads/;
        proxy_set_header Host $host;
    }

    # ---- Sensei SPA fallback ----
    # Hashed assets - cache 1 year
    location ~* ^/assets/ {
        try_files $uri =404;
        expires 1y;
        add_header Cache-Control "public, immutable";
        access_log off;
    }

    # index.html - never cache
    location = /index.html {
        try_files $uri =404;
        expires -1;
        add_header Cache-Control "no-cache, no-store, must-revalidate";
    }

    # SPA fallback
    location / {
        try_files $uri $uri/ /index.html;
        add_header Cache-Control "no-cache, no-store, must-revalidate";
    }

    # Gzip
    gzip on;
    gzip_types text/css application/javascript application/json text/html;
    gzip_min_length 1000;
}
NGINXEOF

# Enable the site
ln -sf /etc/nginx/sites-available/sensei /etc/nginx/sites-enabled/sensei
rm -f /etc/nginx/sites-enabled/default

# Test and reload
nginx -t 2>&1
systemctl start nginx
systemctl enable nginx
systemctl reload nginx

echo ""
echo "=== Step 5: Verify everything ==="
echo "Sensei backend:"
curl -s http://localhost:7000/health 2>/dev/null
echo ""
echo "Sensei frontend (via HTTPS):"
curl -sk -o /dev/null -w "%{http_code}" https://localhost/ 2>/dev/null
echo ""
echo "DevPanel (via HTTPS /devpanel/):"
curl -sk -o /dev/null -w "%{http_code}" https://localhost/devpanel/ 2>/dev/null
echo ""
echo "Nginx status:"
systemctl is-active nginx
echo ""
echo "=== Deployment Complete ==="
echo "Public chat:  https://senseiissei.dev"
echo "Dev panel:    https://senseiissei.dev/devpanel/"
echo "API docs:     https://senseiissei.dev/docs"
echo "Health:       https://senseiissei.dev/health"
