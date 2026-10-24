#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_log_tick.py — «چیزی سررسید نبود»: ۴ جاینشان %d در برابر ۵ آرگومان
→ TypeError در قالب‌بندی → گم شدن لاگ آن تیک. --check = فقط گزارش."""
import glob, py_compile, shutil, sys, time
BAD = 'سررسید نبود'
hits = []
for f in sorted(glob.glob('*.py')):
    try:
        lines = open(f, encoding='utf-8').read().splitlines()
    except Exception:
        continue
    for i, ln in enumerate(lines, 1):
        if BAD in ln and '%d' in ln:
            hits.append((f, i, ln.count('%d'), ln))
for f, i, n, ln in hits:
    print(f'{f}:{i} | جاینشان‌ها={n} | {ln.strip()[:160]}')
if not hits:  sys.exit('✗ یافت نشد — خروجی grep را بفرستید')
if len(hits) > 1: sys.exit('✗ بیش از یک تطبیق — خط‌های بالا را بفرستید')
f, i, n, ln = hits[0]
if n != 4: sys.exit(f'✗ انتظار ۴ جاینشان، {n} پیدا شد — خط بالا را بفرستید')
if ' دقیقه)' not in ln: sys.exit('✗ الگوی «دقیقه)» نیست — خط بالا را بفرستید')
if '--check' in sys.argv:
    print('✓ آمادهٔ اصلاح (--check: چیزی نوشته نشد)'); sys.exit()
new_ln = ln.replace(' دقیقه)', ' | guards=%d دقیقه)', 1)
src = open(f, encoding='utf-8').read()
assert src.count(ln) == 1
shutil.copy(f, f'.bak-{time.strftime("%Y%m%d-%H%M%S")}')
open(f, 'w', encoding='utf-8').write(src.replace(ln, new_ln, 1))
py_compile.compile(f, doraise=True)
print('✓ اصلاح شد:'); print('  قدیم:', ln.strip()[:160]); print('  جدید:', new_ln.strip()[:160])
