#!/bin/bash
# بازسازی venv در صورت حذف تصادفی — کپی از پروژه‌ی خواهر (آفلاین) یا PyPI
cd "$(dirname "$0")"
if [ ! -x venv/bin/python ]; then
  SIS=$(basename $(dirname $(dirname $(dirname $(readlink -f venv 2>/dev/null || echo .)))))  # noop
  for SIB in ~/nobitex-usdt ~/wallex-trader; do
    [ "$SIB" != "$(pwd)" ] && [ -x "$SIB/venv/bin/python" ] && cp -r "$SIB/venv" ./venv && break
  done
  [ -x venv/bin/python ] || { python3 -m venv venv && venv/bin/pip install --default-timeout=180 -r requirements.txt; }
fi
venv/bin/python -c "import gspread, requests, jdatetime, cryptography" && echo '✓ venv سالم' || echo '✗ بازسازی ناموفق'
