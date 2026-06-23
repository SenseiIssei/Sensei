#!/bin/bash
set -e

echo "=== Copy SSL certs from container to host ==="
mkdir -p /etc/letsencrypt
docker cp devpanel-client:/etc/letsencrypt/live /etc/letsencrypt/live
docker cp devpanel-client:/etc/letsencrypt/archive /etc/letsencrypt/archive 2>/dev/null || true
echo "Certs copied:"
ls -la /etc/letsencrypt/live/senseiissei.dev/

echo ""
echo "=== Fix Nginx config (remove gzip to avoid MIME warning) ==="
# Remove the gzip section that causes duplicate MIME warning
sed -i '/gzip on;/d' /etc/nginx/sites-available/sensei
sed -i '/gzip_types/d' /etc/nginx/sites-available/sensei
sed -i '/gzip_min_length/d' /etc/nginx/sites-available/sensei

echo "Testing Nginx..."
nginx -t 2>&1

echo "Starting Nginx..."
systemctl restart nginx 2>&1
systemctl enable nginx 2>&1

echo ""
echo "=== Verification ==="
echo "1. Sensei backend:"
curl -s http://localhost:7000/health 2>/dev/null
echo ""

echo "2. Sensei frontend (HTTPS):"
curl -sk -o /dev/null -w "HTTP %{http_code}" https://senseiissei.dev/ 2>/dev/null
echo ""

echo "3. DevPanel (HTTPS /devpanel/):"
curl -sk -o /dev/null -w "HTTP %{http_code}" https://senseiissei.dev/devpanel/ 2>/dev/null
echo ""

echo "4. Sensei API (HTTPS):"
curl -sk -o /dev/null -w "HTTP %{http_code}" https://senseiissei.dev/api/models 2>/dev/null
echo ""

echo "5. Nginx status:"
systemctl is-active nginx
echo ""

echo "6. All containers:"
docker ps --format "table {{.Names}}\t{{.Ports}}\t{{.Status}}" 2>/dev/null
echo ""

echo "=== Deployment Complete ==="
echo "Public chat:  https://senseiissei.dev"
echo "Dev panel:    https://senseiissei.dev/devpanel/"
echo "API docs:     https://senseiissei.dev/docs"
echo "Health:       https://senseiissei.dev/health"
