#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_log_tick2.py — هدفمند: scheduler.py، خط «سررسید نبود»، افزودن guards=%d."""
import py_compile, shutil, sys, time
F = 'scheduler.py'
BAD  = "wallet=%d دقیقه)'"
GOOD = "wallet=%d دقیقه | guards=%d)'"
lines = open(F, encoding='utf-8').read().splitlines(keepends=True)
hits = [i for i, ln in enumerate(lines) if 'سررسید نبود' in ln and '%d' in ln]
if len(hits) != 1:
    sys.exit(f'✗ {len(hits)} تطبیق (انتظار ۱) — خط‌ها: {[h+1 for h in hits]}')
i = hits[0]
if BAD not in lines[i]:
    sys.exit(f'✗ الگو در scheduler.py:{i+1} نیست — خط را بفرستید: {lines[i].strip()[:160]}')
if '--check' in sys.argv:
    print(f'✓ scheduler.py:{i+1} آمادهٔ اصلاح (--check: چیزی نوشته نشد)'); sys.exit()
shutil.copy(F, f'{F}.bak-{time.strftime("%Y%m%d-%H%M%S")}')
lines[i] = lines[i].replace(BAD, GOOD, 1)
open(F, 'w', encoding='utf-8').write(''.join(lines))
py_compile.compile(F, doraise=True)
print(f'✓ scheduler.py:{i+1} اصلاح شد:'); print('  جدید:', lines[i].strip()[:170])
