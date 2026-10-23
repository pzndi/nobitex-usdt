#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cancel_buy_orders.py - لغو سفارشات خرید باز برای اعمال شرایط جدید G-scale
لغو فقط سفارشات خرید بدون پرشدن جزئی (matchedAmount == 0).
سفارشات فروش، OCO و سفارشات دستی کاربر لمس نمی‌شوند."""
import sys, time, re
sys.path.insert(0, '.')

import trader
from trader import make_client, clean_oid

def main():
    print('=' * 70)
    print('cancel_buy_orders.py - لغو سفارشات خرید باز')
    print('=' * 70)

    # ساخت کلاینت
    client = make_client()
    if not client:
        print('✗ کلیدهای NOBITEX_API_KEY/SECRET در .env یافت نشد')
        return 1
    print('✓ کلاینت نوبیتکس ساخته شد')

    # دریافت سفارشات باز
    try:
        code, data = client.open_orders()
        if code != 200:
            print(f'✗ خطا در دریافت سفارشات: HTTP {code}')
            print(f'  response: {str(data)[:200]}')
            return 1
        orders = data.get('orders') or []
        print(f'✓ تعداد سفارشات باز: {len(orders)}')
    except Exception as e:
        import traceback
        print(f'✗ خطا در دریافت سفارشات: {e}')
        traceback.print_exc()
        return 1

    if not orders:
        print('✓ هیچ سفارش باز وجود ندارد')
        return 0

    # فیلتر فقط سفارشات خرید بدون پر شدگی
    buy_orders = []
    for o in orders:
        otype = str(o.get('type', '')).lower()
        if otype != 'buy':
            continue
        try:
            matched = float(str(o.get('matchedAmount') or 0).replace(',', ''))
        except (TypeError, ValueError):
            matched = 0.0
        if matched > 0:
            print(f'  ⚠ سفارش {o.get("clientOrderId", "?")} پرشدن جزئی دارد ({matched}) - رد شد')
            continue
        buy_orders.append(o)

    if not buy_orders:
        print('✓ سفارش خرید قابل لغو وجود ندارد (همه پر شده‌اند یا فقط فروش هستند)')
        return 0

    print()
    print(f'=== لیست {len(buy_orders)} سفارش خرید قابل لغو ===')
    for o in buy_orders:
        cid = o.get('clientOrderId', '')
        oid = clean_oid(o.get('pairId')) or '?'
        # استخراج نماد از clientOrderId (nbx-NEAR-1234567890)
        m = re.match(r'^nbx-([a-z0-9]+)-\d+$', str(cid))
        sym = m.group(1).upper() if m else '?'
        # پیدا کردن قیمت و حجم
        price = o.get('price', '?')
        vol = o.get('amount', o.get('quantity', '?'))
        print(f'  cid: {cid}')
        print(f'    symbol: {sym} | oid: {oid} | price: {price} | vol: {vol}')
    print()

    # تأیید کاربر
    print('⚠ توقف ۳ ثانیه برای لغو... (Ctrl+C برای انصراف)')
    try:
        time.sleep(3)
    except KeyboardInterrupt:
        print('انصراف')
        return 1

    # لغو سفارشات
    print()
    print('=== لغو سفارشات ===')
    cancelled = 0
    failed = 0
    skipped = 0
    for o in buy_orders:
        cid = str(o.get('clientOrderId') or '')
        oid = clean_oid(o.get('pairId'))
        m = re.match(r'^nbx-([a-z0-9]+)-\d+$', cid)
        sym = m.group(1).upper() if m else '?'

        if not oid or not oid.isdigit():
            print(f'  ⚠ {cid}: شناسه عددی ندارد (pairId غایب) - رد شد')
            skipped += 1
            continue

        try:
            code_c, data_c = client.cancel_order(oid)
            ok = (code_c in (200, 201)
                  and not (isinstance(data_c, dict) and data_c.get('status') == 'failed'))
            if ok:
                print(f'  ✓ لغو شد: {sym} oid={oid} ({cid})')
                cancelled += 1
            elif isinstance(data_c, dict) and str(data_c.get('error')) == 'NotFound':
                print(f'  ~ {sym} oid={oid}: سفارش از قبل حذف شده')
                skipped += 1
            else:
                print(f'  ✗ {sym} oid={oid}: HTTP {code_c} | {str(data_c)[:100]}')
                failed += 1
            time.sleep(0.5)
        except Exception as e:
            print(f'  ✗ {sym} oid={oid}: خطا - {e}')
            failed += 1

    print()
    print('=' * 70)
    print(f'خلاصه: {cancelled} لغو موفق، {failed} خطا، {skipped} رد شده')
    print('=' * 70)
    return 0 if failed == 0 else 1

if __name__ == '__main__':
    sys.exit(main())
