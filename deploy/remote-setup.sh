#!/bin/bash
set -e

cd /opt/sensei

# Generate JWT secret and update .env
JWT_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
sed -i "s/^SENSEI_JWT_SECRET=.*/SENSEI_JWT_SECRET=${JWT_SECRET}/" .env
echo "JWT secret set: ${JWT_SECRET:0:8}..."

# Remove duplicate CORS lines, keep last
sed -i '/^SENSEI_CORS_ORIGINS=/d' .env
echo "SENSEI_CORS_ORIGINS=https://senseiissei.dev,http://senseiissei.dev,http://localhost,http://82.165.118.241" >> .env

# Build frontend
echo "Building frontend..."
cd frontend
npm install --silent 2>&1 | tail -3
npm run build 2>&1 | tail -5
cd ..

# Start backend with Docker Compose
echo "Starting backend..."
docker compose up -d --build 2>&1 | tail -10

# Wait for backend
echo "Waiting for backend..."
sleep 8
curl -s http://localhost:7000/health || echo "Backend not ready yet"

# Configure Nginx
echo "Configuring Nginx..."
cp deploy/nginx.conf /etc/nginx/sites-available/sensei
ln -sf /etc/nginx/sites-available/sensei /etc/nginx/sites-enabled/sensei
rm -f /etc/nginx/sites-enabled/default

# Update nginx config for IP access too
sed -i 's/server_name senseiissei.dev www.senseiissei.dev;/server_name senseiissei.dev www.senseiissei.dev 82.165.118.241;/' /etc/nginx/sites-available/sensei

nginx -t 2>&1
systemctl reload nginx
systemctl enable nginx

echo ""
echo "=== Deployment Status ==="
echo "Backend health:"
curl -s http://localhost:7000/health 2>/dev/null || echo "Not responding"
echo ""
echo "Nginx status:"
systemctl is-active nginx
echo ""
echo "Frontend files:"
ls -la /opt/sensei/frontend/dist/index.html 2>/dev/null && echo "OK" || echo "Missing"
echo ""
echo "=== Done ==="
