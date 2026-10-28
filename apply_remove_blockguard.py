#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""apply_remove_blockguard.py — حذف کامل گارد BLOCKED_SYMBOLS (G-ablock) — مبنا: r75

گارد سه‌عضوی است؛ حذف فقط ردیف شیت کافی نیست (else-branch نویسنده آن را بازمی‌سازد):
  trader.py:        گیت ورود (3317) + ردیف GUARDS_DEFS (2735) + ردیف GUARDS_DUTY (2758) + تابع auto_block_update (3027)
  scheduler.py:     تسک auto_block (148)
  settings.py:      BLOCKED_SYMBOLS / FREE_SYMBOLS / INTERVAL_AUTO_BLOCK_MIN — کلید + پیش‌فرض + clamp + سه property
  write_tab_docs.py: دو اشاره‌ی متنی AUTO_BLOCK (شمارنده ۱۹ پس از حذف درست می‌شود: 20→19)
  شیت:              ردیف‌های سه کلید در «تنظیمات» (نزولی) + ردیف BLOCKED_SYMBOLS در «گاردها»

all-or-nothing: اگر هر لنگری نباشد هیچ فایلی نوشته نمی‌شود.
نوشتن اتمیک (tmp+os.replace) — بدون توقف ربات؛ تیک بعدی کد جدید را برمی‌دارد.
"""
import os
import re
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
FAILED = []


def load(fn):
    with open(os.path.join(BASE, fn), encoding='utf-8') as f:
        return f.read()


def save_atomic(fn, src):
    tmp = os.path.join(BASE, fn + '.tmp_patch')
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(src)
    os.replace(tmp, os.path.join(BASE, fn))


def cut(src, old, what):
    n = src.count(old)
    if n != 1:
        FAILED.append('%s: %d مطابقت (انتظار 1) — %r' % (what, n, old[:70]))
        return src
    print('  OK %s' % what)
    return src.replace(old, '')


def rexcut(src, pattern, what):
    n = len(re.findall(pattern, src))
    if n != 1:
        FAILED.append('%s: %d مطابقت (انتظار 1) — الگو: %s' % (what, n, pattern))
        return src
    print('  OK %s' % what)
    return re.sub(pattern, '', src)


def remove_block(src, start_sig, what, top_level=True):
    """حذف بلوک def تا مرز بعدی (متد کلاس: دکوراتورهای @ قبلی هم می‌روند)."""
    lines = src.split('\n')
    def_idx = None
    for i, ln in enumerate(lines):
        if ln.startswith(start_sig):
            def_idx = i
            break
    if def_idx is None:
        FAILED.append('%s: امضای شروع پیدا نشد — %r' % (what, start_sig))
        return src
    start = def_idx
    if not top_level:
        while start > 0 and lines[start - 1].strip().startswith('@'):
            start -= 1
    end = len(lines)
    for j in range(def_idx + 1, len(lines)):
        s = lines[j]
        if not s.strip():
            continue
        ind = len(s) - len(s.lstrip())
        hit = (ind == 0) if top_level else (ind <= 4)
        if hit:
            end = j
            break
    n = end - start
    del lines[start:end]
    k = start - 1
    while k >= 0 and lines[k].strip() == '':
        del lines[k]
        k -= 1
    for _ in range(2 if top_level else 1):
        lines.insert(k + 1, '')
    print('  OK %s (%d خط)' % (what, n))
    return '\n'.join(lines)


print('== 1) ویرایش کد ==')

print('trader.py:')
t = load('trader.py')
t = rexcut(t, r"[ \t]*# G-ablock: operator/auto blocked symbols - no new entries\n"
               r"[ \t]*if sym in st\.blocked_symbols:\n"
               r"[ \t]*log\.info\('skip buy %s: symbol blocked \(BLOCKED_SYMBOLS\)', sym\)\n"
               r"[ \t]*continue\n", 'گیت ورود G-ablock (trader.py:3317)')
t = rexcut(t, r"[ \t]*\('BLOCKED_SYMBOLS',[^\n]*\n", 'ردیف GUARDS_DEFS (2735)')
t = rexcut(t, r"(?m)^[ \t]*'BLOCKED_SYMBOLS':[ \t][^\n]*\n", 'ردیف GUARDS_DUTY (2758)')
t = remove_block(t, 'def auto_block_update(sh, st):', 'تابع auto_block_update (3027)', top_level=True)

print('scheduler.py:')
s = load('scheduler.py')
s = rexcut(s, r"[ \t]*\('auto_block',[^\n]*\n", 'تسک auto_block (scheduler.py:148)')

print('settings.py:')
e = load('settings.py')
e = cut(e, "'BLOCKED_SYMBOLS', 'FREE_SYMBOLS', ", 'TRADING_KEYS (settings.py:17)')
e = cut(e, "'BLOCKED_SYMBOLS': '', 'FREE_SYMBOLS': '', ", 'پیش‌فرض TRADING (settings.py:42)')
e = remove_block(e, '    def blocked_symbols(self):', 'property blocked_symbols (251)', top_level=False)
e = remove_block(e, '    def free_symbols(self):', 'property free_symbols (258)', top_level=False)
e = remove_block(e, '    def interval_auto_block_min(self):', 'property interval_auto_block_min (438)', top_level=False)
e = cut(e, "'INTERVAL_AUTO_BLOCK_MIN', ", 'GENERAL_KEYS (20)')
e = cut(e, "'INTERVAL_AUTO_BLOCK_MIN': '2880', ", 'پیش‌فرض GENERAL (47)')
e = rexcut(e, r"\n[ \t]*'INTERVAL_AUTO_BLOCK_MIN':\s*\(\s*60,\s*10080\s*\),", 'clamp (130)')

print('write_tab_docs.py:')
w = load('write_tab_docs.py')
w = cut(w, 'AUTO_BLOCK, ', 'متن گاردها (90)')
w = cut(w, '، AUTO_BLOCK', 'متن پارامترها (36)')

if FAILED:
    print('\n✗ لنگرهای گم‌شده — هیچ فایلی نوشته نشد:')
    for f in FAILED:
        print('  -', f)
    sys.exit(1)

print('\n== 2) کامپایل پیش از نوشتن ==')
edited = (('trader.py', t), ('scheduler.py', s), ('settings.py', e), ('write_tab_docs.py', w))
for fn, src in edited:
    compile(src, fn, 'exec')
    print('  OK compile %s' % fn)

print('\n== 3) نوشتن اتمیک ==')
for fn, src in edited:
    save_atomic(fn, src)
    print('  OK %s' % fn)

print('\n== 4) راستی‌آزمایی import ==')
import_err = None
sys.path.insert(0, BASE)
try:
    import settings as _s
    for _attr in ('blocked_symbols', 'free_symbols', 'interval_auto_block_min'):
        assert not hasattr(_s.Settings, _attr), _attr + ' هنوز هست!'
    print('  OK settings: هر سه property حذف شدند')
    import trader as _t
    assert not hasattr(_t, 'auto_block_update'), 'auto_block_update هنوز هست!'
    assert all(n != 'BLOCKED_SYMBOLS' for n, _, _ in _t.GUARDS_DEFS)
    print('  OK trader: auto_block_update حذف | تعداد گاردها: %d' % len(_t.GUARDS_DEFS))
except Exception:
    import traceback
    import_err = traceback.format_exc()
    print('  ✗ خطای import (ادامه می‌دهیم تا شیت هم پاک شود):')
    print(import_err)

print('\n== 5) پاک‌سازی شیت ==')
env = {}
for line in open(os.path.join(BASE, '.env'), encoding='utf-8'):
    line = line.strip()
    if '=' in line and not line.startswith('#'):
        k, _, v = line.partition('=')
        env[k] = v
import gspread
sh = gspread.service_account(filename=os.path.join(BASE, 'service_account.json')).open_by_key(env['SHEET_ID'])


def _del_row(ws, i):
    try:
        ws.delete_row(i)
    except AttributeError:
        ws.delete_rows(i)


ws_set = sh.worksheet('تنظیمات')
targets = [(i, str(r[0]).strip()) for i, r in enumerate(ws_set.get_all_values(), 1)
           if r and str(r[0]).strip() in
           ('BLOCKED_SYMBOLS', 'INTERVAL_AUTO_BLOCK_MIN', 'FREE_SYMBOLS')]
if not targets:
    print('  تنظیمات: ردیف هدف یافت نشد (قبلاً حذف شده؟)')
for i, key in sorted(targets, reverse=True):
    _del_row(ws_set, i)
    print('  OK تنظیمات: ردیف %d حذف شد (%s)' % (i, key))

ws_g = sh.worksheet('گاردها')
for i, r in enumerate(ws_g.get_all_values(), 1):
    if r and str(r[0]).strip() == 'BLOCKED_SYMBOLS':
        _del_row(ws_g, i)
        print('  OK گاردها: ردیف %d حذف شد' % i)
        break
else:
    print('  گاردها: ردیف BLOCKED_SYMBOLS نیست')

_left = [str(r[0]).strip() for r in ws_set.get_all_values()
         if r and str(r[0]).strip() in
         ('BLOCKED_SYMBOLS', 'INTERVAL_AUTO_BLOCK_MIN', 'FREE_SYMBOLS')]
print('  کلیدهای باقی‌مانده در تنظیمات: %s' % (_left if _left else 'هیچ ✓'))

if import_err:
    print('\n✗ کد پچ شد اما import خطا داد — خروجی را بفرست.')
    sys.exit(3)
print('\n✅ پچ کامل شد — تیک بعدی cron (~60 ثانیه) کد جدید را برمی‌دارد؛')
print('   تب گاردها در تیک guards بعدی (~5 دقیقه) بازنویسی می‌شود (19 گارد).')
print('   پس از تأیید خروجی، کامیت کن تا بازگشت با git revert ممکن باشد.')
