#!/bin/bash
# Run ON the VDS as root. FileZilla upload does not reload Python.
set +e
SITE="/var/www/checkapp/site"
cd "$SITE" || { echo "NO DIR $SITE"; exit 1; }

echo "=== disk ==="
grep BUILD_ID "$SITE/server.py" | head -1
ls -l "$SITE/platega_pay.py" "$SITE/server.py" "$SITE/mock-local.js" 2>&1 | awk '{print $5,$6,$7,$8,$9}'

echo "=== compile ==="
python3 -m py_compile "$SITE/server.py" "$SITE/platega_pay.py" "$SITE/features.py"
if [ $? -ne 0 ]; then
  echo "COMPILE FAILED — new process will not start"
  exit 1
fi
echo "compile ok"

echo "=== stop old python ==="
# systemd restart would bring the OLD process back on 8081
systemctl stop checkapp 2>/dev/null
systemctl stop rustcheck 2>/dev/null
pkill -f "$SITE/server.py" 2>/dev/null
pkill -f "python3 -u $SITE/server.py" 2>/dev/null
fuser -k 8081/tcp 2>/dev/null
sleep 2

rm -f "$SITE/mock-local.js.gz" "$SITE/checkapp-gates.js.gz"

echo "=== start ==="
nohup python3 -u "$SITE/server.py" >> "$SITE/data/server.log" 2>&1 &
sleep 3

echo "=== live ==="
curl -s -m 3 http://127.0.0.1:8081/utils/build
echo
echo "Need: 2026-09-08-platega-v51"
echo "=== last log ==="
tail -n 20 "$SITE/data/server.log" 2>/dev/null
