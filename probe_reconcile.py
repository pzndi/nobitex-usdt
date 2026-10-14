#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
probe_reconcile.py — تطبیق فقط-خواندن (بند ۱۱)
- wallets/list: موجودی‌های غیرصفر
- orders/list: سفارش‌های باز + پرچم دارایی بدون سفارش فروش (حفاظت)
- orders/status: وضعیت دو خرید باز دفتر (BAT 6630240648، XRP 6639137191)
- trades/list: ۱۰ معامله آخر
- شیت: ردیف‌های باز BAT/XRP/FIL/S
هیچ سفارشی ثبت/لغو نمی‌شود؛ هیچ فایلی نوشته نمی‌شود.
"""
import json
import sys

import net_timeout  # noqa: F401

import trader
from settings import load_env


def _f(v):
    try:
        return float(str(v or 0).replace(',', ''))
    except (TypeError, ValueError):
        return 0.0


def main():
    client = trader.make_client()
    if not client:
        print('ERR: client ساخته نشد')
        return 1

    code, data = client.wallets()
    print(f'=== wallets: HTTP {code} ===')
    held = {}
    wl = data.get('wallets') if isinstance(data, dict) else None
    if isinstance(wl, list):
        for w in wl:
            cur = str(w.get('currency') or w.get('wallet') or '?').lower()
            bal, act, blk = _f(w.get('balance')), _f(w.get('activeBalance')), _f(w.get('blockedBalance'))
            if bal > 0 or act > 0 or blk > 0:
                held[cur] = (bal, act, blk)
                print(f'{cur}: balance={bal} active={act} blocked={blk}')
    else:
        print('پاسخ غیرمنتظره:', json.dumps(data, ensure_ascii=False)[:300])

    code, data = client.open_orders()
    orders = (data.get('orders') or []) if isinstance(data, dict) else []
    print(f'=== open orders: HTTP {code} | count={len(orders)} ===')
    protected = set()
    for o in orders:
        cur = str(o.get('srcCurrency') or '').lower()
        typ = str(o.get('type') or '').lower()
        print(json.dumps({k: o.get(k) for k in ('type', 'execution', 'srcCurrency',
                                                 'price', 'amount', 'matchedAmount',
                                                 'unmatchedAmount', 'clientOrderId', 'pairId')},
                         ensure_ascii=False))
        if typ == 'sell':
            protected.add(cur)

    print('=== دارایی بدون سفارش فروش باز ===')
    skip = {'usdt', 'irt', 'rls'}
    flagged = False
    for cur in sorted(held):
        if cur in skip or cur in protected:
            continue
        bal, act, blk = held[cur]
        print(f'⚠ {cur}: balance={bal} active={act} blocked={blk} — بدون سفارش فروش/OCO باز')
        flagged = True
    if not flagged:
        print('— هیچ دارایی بدون حفاظتی یافت نشد')

    for sym, oid in (('BAT', '6630240648'), ('XRP', '6639137191')):
        try:
            code, data = client.order_status(oid)
            print(f'=== order_status {sym} {oid}: HTTP {code} ===')
            if isinstance(data, dict):
                data = dict(data)
                data.pop('user', None)
                o = data.get('order')
                if isinstance(o, dict):
                    o = dict(o)
                    o.pop('user', None)
                    data['order'] = o
            print(json.dumps(data, ensure_ascii=False)[:600])
        except Exception as e:
            print(f'order_status {sym} ناموفق:', repr(e))

    try:
        code, data = client._sc.get('/market/trades/list')
        trs = (data.get('trades') or []) if isinstance(data, dict) else []
        print(f'=== trades/list: HTTP {code} | count={len(trs)} — ۱۰ مورد آخر ===')
        for t in trs[-10:]:
            print(json.dumps(t, ensure_ascii=False)[:300])
    except Exception as e:
        print('trades/list ناموفق:', repr(e))

    try:
        import gspread
        sheet_id = load_env().get('SHEET_ID')
        gc = gspread.service_account(filename='service_account.json')
        sh = gc.open_by_key(sheet_id)
        ws = sh.worksheet('سفارشات')
        rows = ws.get_all_values()
        print(f'=== دفتر: {len(rows)} ردیف — ردیف‌های بازِ BAT/XRP/FIL/S ===')
        for r in rows[1:]:
            if len(r) > 11 and str(r[1]).strip() in ('BAT', 'XRP', 'FIL', 'S'):
                if str(r[11]).strip() in ('پر شد', 'لغو شده', 'ناموفق', 'شبیه‌سازی'):
                    continue
                print(json.dumps(r, ensure_ascii=False))
    except Exception as e:
        print('خواندن دفتر ناموفق:', repr(e))
    return 0


if __name__ == '__main__':
    sys.exit(main())
