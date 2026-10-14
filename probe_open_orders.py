#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
probe_open_orders.py — تشخیص فقط-خواندن
۱) GET /market/orders/list → چاپ کامل JSON سفارش‌های باز (فیلدهای واقعی apiv2)
۲) قیمت لحظه‌ای عمومی BAT/XRP
۳) ردیف‌های BAT/XRP از تب «سفارشات» (دفتر)
هیچ سفارشی ثبت/لغو نمی‌شود؛ هیچ فایلی نوشته نمی‌شود.
"""
import json
import sys

import net_timeout  # noqa: F401  — تایم‌اوت پیش‌فرض HTTP

import trader
from settings import load_env


def main():
    client = trader.make_client()
    if not client:
        print('ERR: client ساخته نشد (کلیدها در .env نیستند)')
        return 1

    code, data = client.open_orders()
    print(f'=== open_orders: HTTP {code} ===')
    orders = data.get('orders') if isinstance(data, dict) else None
    if not isinstance(orders, list):
        print('پاسخ غیرمنتظره:', json.dumps(data, ensure_ascii=False)[:500])
    else:
        print(f'تعداد سفارش باز: {len(orders)}')
        for i, o in enumerate(orders[:10]):
            print(f'--- order[{i}] ---')
            print(json.dumps(o, ensure_ascii=False, indent=1))

    try:
        for s in ('BAT', 'XRP'):
            print(f'قیمت {s} (عمومی):', trader._public_price(s))
    except Exception as e:
        print('دریافت قیمت ناموفق:', repr(e))

    try:
        import gspread
        sheet_id = load_env().get('SHEET_ID')
        gc = gspread.service_account(filename='service_account.json')
        sh = gc.open_by_key(sheet_id)
        try:
            ws = sh.worksheet('سفارشات')
        except Exception:
            print('tabs:', [w.title for w in sh.worksheets()])
            raise
        rows = ws.get_all_values()
        print(f'=== دفتر «{ws.title}»: {len(rows)} ردیف ===')
        if rows:
            print('HEADER:', json.dumps(rows[0], ensure_ascii=False))
        hits = 0
        for r in rows[1:]:
            if 'BAT' in ' | '.join(r) or 'XRP' in ' | '.join(r):
                print(json.dumps(r, ensure_ascii=False))
                hits += 1
                if hits >= 20:
                    print('... (بیش از ۲۰ ردیف — قطع شد)')
                    break
        if hits == 0:
            print('ردیف BAT/XRP یافت نشد')
    except Exception as e:
        print('خواندن دفتر ناموفق:', repr(e))
    return 0


if __name__ == '__main__':
    sys.exit(main())
