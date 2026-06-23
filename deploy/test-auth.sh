#!/bin/bash
echo '{"email":"test@sensei.dev","password":"testpassword123","name":"Test User"}' > /tmp/test_reg.json
echo "=== Register test ==="
curl -sk -X POST https://senseiissei.dev/api/auth/register \
  -H 'Content-Type: application/json' \
  -d @/tmp/test_reg.json
echo ""

echo "=== Login test ==="
curl -sk -X POST https://senseiissei.dev/api/auth/login \
  -H 'Content-Type: application/json' \
  -d @/tmp/test_reg.json
echo ""

echo "=== Cleanup test user ==="
rm -f /opt/sensei/.sensei_users.json
echo "Test user cleaned up"
