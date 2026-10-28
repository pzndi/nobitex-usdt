#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""apply_reconguard.py — پچ r110 (پرونده ⑦)
P1: reconcile_real_positions تا وقتی سفارش فروش زنده‌ای برای نماد روی صرافی
    هست چرخه را نمی‌بندد (خروج جزئی در جریان — ریشه: BLUR 11:33 SL نیمه‌پر).
P2: G-scale پس از لغوی موفق، ردیف‌های OCOی ثبت‌شدهٔ پس از snapshot را هم
    با اسکن هدفمند ستون شناسه «لغو شده» مهر می‌زند (F10b).
P3: reconcile برای marked_row از جدیدترین ردیف شروع می‌کند.
هر سه لنگر باید دقیقاً یک‌بار یافت شوند؛ وگرنه بدون نوشتن abort."""
import py_compile, shutil, sys, time

SRC = 'trader.py'
src = open(SRC, encoding='utf-8').read()
if 'G-recon-guard (r110)' in src:
    print('قبلاً پچ شده — کاری انجام نشد')
    sys.exit(0)

edits = []

a1 = ("        avail = currency_available(client, sym, use_active=False)\n"
      "        if avail is None or avail >= rv * 0.5:\n"
      "            continue\n")
r1 = a1 + (
    "        # G-recon-guard (r110): اگر سفارش فروش زنده‌ای برای نماد روی صرافی\n"
    "        # هست، خروج جزئی در جریان است (ریشهٔ ⑦: BLUR 11:33 — SL نیمه‌پر\n"
    "        # 537.107/594.94؛ reconcile بست و sync دوباره بست). بستنِ چرخه تا\n"
    "        # لغو/اجرای کامل سفارش‌های فروش به همگام‌سازی وضعیت واگذار می‌شود.\n"
    "        try:\n"
    "            _oo_code, _oo_data = client.open_orders()\n"
    "            _oo_live = [o for o in ((_oo_data or {}).get('orders') or [])\n"
    "                        if str(o.get('type')) == 'sell'\n"
    "                        and _norm_sym(o.get('srcCurrency', '')) == _norm_sym(sym)]\n"
    "        except Exception as _oo_e:\n"
    "            log.warning('reconcile %s: استعلام سفارش‌های باز ناموفق (%r) — بستن به تیک بعد واگذار شد', sym, _oo_e)\n"
    "            continue\n"
    "        if _oo_live:\n"
    "            log.info('reconcile %s: کیف کمتر از نصف دفتر اما %d سفارش فروش زنده روی صرافی هست — خروج جزئی در جریان، بستن به همگام‌سازی واگذار شد',\n"
    "                     sym, len(_oo_live))\n"
    "            continue\n")
edits.append(('P1', a1, r1))

a2 = ("                    for _rn in _tgt_rows:\n"
      "                        ws_t.update_cell(_rn, 12, ST_CANCELLED)\n")
r2 = a2 + (
    "                    # F10b (r110): ردیف‌های OCOی ثبت‌شده پس از snapshot تیک در\n"
    "                    # led['rows'] نیستند («ردیف‌ها: —»؛ شاهد BLUR 11:33) — اسکن\n"
    "                    # هدفمند ستون شناسه و مهر لغو روی هر ردیف OPENISH حاوی oid لغوشده.\n"
    "                    if not _tgt_rows:\n"
    "                        try:\n"
    "                            _col_oid = ws_t.col_values(11)\n"
    "                            _col_st = ws_t.col_values(12)\n"
    "                            _stamped = 0\n"
    "                            for _i in range(3, len(_col_oid)):\n"
    "                                _oval = str(_col_oid[_i] or '')\n"
    "                                if not any(_x in _oval for _x in _tgt):\n"
    "                                    continue\n"
    "                                _st_old = str(_col_st[_i]) if _i < len(_col_st) else ''\n"
    "                                if _st_old.strip() in OPENISH:\n"
    "                                    ws_t.update_cell(_i + 1, 12, ST_CANCELLED)\n"
    "                                    _stamped += 1\n"
    "                            if _stamped:\n"
    "                                log.info('G-scale %s: %d ردیف OCOی لغوشده (ثبت‌شده پس از snapshot) مهر لغو خورد', sym_c, _stamped)\n"
    "                        except Exception:\n"
    "                            log.exception('G-scale %s: مهر لغوی ردیف‌های پس از snapshot ناموفق', sym_c)\n")
edits.append(('P2', a2, r2))

a3 = ("        marked_row = None\n"
      "        for row_num, rr in led['rows']:\n")
r3 = ("        marked_row = None\n"
      "        for row_num, rr in reversed(led['rows'] or []):\n")
edits.append(('P3', a3, r3))

for name, a, r in edits:
    n = src.count(a)
    if n != 1:
        print(f'لنگر {name} {n} بار یافت شد (انتظار ۱) — abort بدون نوشتن')
        sys.exit(1)
for name, a, r in edits:
    src = src.replace(a, r)
try:
    compile(src, SRC, 'exec')
except SyntaxError as e:
    print('نحو پچ‌شده خراب است — abort بدون نوشتن:', e)
    sys.exit(1)
shutil.copy2(SRC, 'trader.py.bak-' + time.strftime('%Y%m%d-%H%M%S'))
open(SRC, 'w', encoding='utf-8').write(src)
py_compile.compile(SRC, doraise=True)
print('پچ اعمال شد، نحو سالم، بکاپ گرفته شد ✓')
