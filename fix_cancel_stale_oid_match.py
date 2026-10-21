#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_cancel_stale_oid_match.py - رفع تداخل oid در cancel_stale_entries

مشکل: وقتی چندین سفارش خرید باز برای یک نماد وجود دارد (Scale 1/2 + Scale 2/2)،
fallback به ledger فقط آخرین ردیف را برمی‌گرداند که ممکن است به سفارش دیگری تعلق داشته باشد.

راه‌حل: برای هر oid کاندید در ledger، استعلام order_status بگیریم و cid را با
cid سفارش فعلی مقایسه کنیم. اولین تطبیق، oid درست است.
"""
import os, sys, shutil, time

DEPLOY = '--deploy' in sys.argv

T_OLD = """        # G-cancel: apiv2 برای سفارش‌های دارای clientOrderId فیلد pairId در
        # orders/list نمی‌فرستد → شناسه عددی از ردیف خرید باز همان نماد در دفتر
        # (ثبت‌شده هنگام ثبت سفارش از پاسخ orders/add). آخرین ردیف منطبق برنده است.
        oid = clean_oid(o.get('pairId'))
        if not oid:
            for _rn, _rr in led.get('rows') or []:
                if (len(_rr) > 11 and str(_rr[1]).strip().upper() == sym
                        and str(_rr[2]).strip() == 'خرید'
                        and str(_rr[11]).strip() in OPENISH):
                    _c = clean_oid(_rr[10])
                    if _c.isdigit():
                        oid = _c
        if not oid:
            log.warning('لغو سفارش کهنه %s ناموفق: شناسه عددی سفارش یافت نشد '
                        '(pairId غایب و ردیف دفتر بدون oid)', sym)
            continue"""

T_NEW = """        # G-cancel: apiv2 برای سفارش‌های دارای clientOrderId فیلد pairId در
        # orders/list نمی‌فرستد → شناسه عددی از ردیف خرید باز همان نماد در دفتر
        # (ثبت‌شده هنگام ثبت سفارش از پاسخ orders/add).
        # G-fix: وقتی چندین سفارش باز برای یک نماد وجود دارد (Scale 1/2 + Scale 2/2)،
        # باید oid را بر اساس cid مرتبط پیدا کنیم، نه آخرین ردیف.
        oid = clean_oid(o.get('pairId'))
        if not oid:
            for _rn, _rr in led.get('rows') or []:
                if (len(_rr) > 11 and str(_rr[1]).strip().upper() == sym
                        and str(_rr[2]).strip() == 'خرید'
                        and str(_rr[11]).strip() in OPENISH):
                    _c = clean_oid(_rr[10])
                    if _c and _c.isdigit():
                        # استعلام وضعیت این oid - آیا cid آن با سفارش فعلی مطابقت دارد؟
                        try:
                            _cs, _ds = client.order_status(_c)
                            _ord_c = _ds.get('order', _ds) if isinstance(_ds, dict) else {}
                            _cid_c = str(_ord_c.get('clientOrderId') or '')
                            if _cid_c == cid:
                                oid = _c  # ← oid درست پیدا شد
                                break
                        except Exception:
                            continue
        if not oid:
            log.warning('لغو سفارش کهنه %s ناموفق: شناسه عددی سفارش یافت نشد '
                        '(pairId غایب و ردیف دفتر بدون oid با cid منطبق)', sym)
            continue"""


def main():
    print('=' * 70)
    print('fix_cancel_stale_oid_match.py - رفع تداخل oid در cancel_stale_entries')
    print(f'mode: {"DEPLOY" if DEPLOY else "DRY-RUN"}')
    print('=' * 70)
    
    with open('trader.py', 'r', encoding='utf-8') as f:
        trader_src = f.read()
    
    if T_OLD not in trader_src:
        print('! T_OLD pattern not found - already patched?')
        return 1
    
    new_src = trader_src.replace(T_OLD, T_NEW)
    
    try:
        compile(new_src, 'trader.py', 'exec')
        print('+ trader.py: تطبیق oid بر اساس cid (نه آخرین ردیف)')
        print('  + syntax check: OK')
    except SyntaxError as e:
        print(f'  + syntax check FAILED: {e}')
        return 1
    
    if DEPLOY:
        bak = f'trader.py.bak.{time.strftime("%Y%m%d_%H%M")}'
        shutil.copy('trader.py', bak)
        print(f'  + backup: {bak}')
        with open('trader.py', 'w', encoding='utf-8') as f:
            f.write(new_src)
        print('  + deployed: trader.py')
    else:
        with open('trader_candidate.py', 'w', encoding='utf-8') as f:
            f.write(new_src)
        print('  (dry-run: candidate saved)')
    
    print()
    print('=' * 70)
    if DEPLOY:
        print('Deploy complete.')
        print()
        print('⚠ توجه: این پچ چندین order_status اضافی برای هر نماد می‌گیرد.')
        print('اگر rate limit مشکل ایجاد کند، باید بهینه‌سازی شود.')
    else:
        print('dry-run OK. To deploy:')
        print('  cd ~/nobitex-usdt && venv/bin/python fix_cancel_stale_oid_match.py --deploy')
    print('=' * 70)
    return 0

if __name__ == '__main__':
    sys.exit(main())
