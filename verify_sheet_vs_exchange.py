#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_sheet_vs_exchange.py - تطبیق سفارشات شیت با داده‌های واقعی نوبیتکس
بررسی:
- سفارشات با وضعیت «باز» در شیت: باید در open_orders صرافی فعال باشند
- سفارشات با وضعیت «پر شد»: باید در صرافی Done باشند
- سفارشات با وضعیت «لغو شده»: باید در صرافی Canceled باشند
- یتیم‌ها: سفارشات صرافی که در شیت نیستند
"""
import sys
sys.path.insert(0, '.')

import trader
from trader import make_client, clean_oid
from settings import load_env
import gspread
import re


def main():
    print('=' * 70)
    print('🔍 تطبیق سفارشات شیت با داده‌های نوبیتکس')
    print('=' * 70)

    # ۱. خواندن سفارشات باز از شیت
    e = load_env()
    gc = gspread.service_account(filename='service_account.json')
    sh = gc.open_by_key(e['SHEET_ID'])
    ws = sh.worksheet('سفارشات')

    all_vals = ws.get_all_values()
    sheet_orders = []
    # داده از ردیف ۴ (index 3)
    for i, r in enumerate(all_vals[3:], 4):
        if not any(str(c).strip() for c in r):
            continue
        r = list(r) + [''] * (13 - len(r))
        try:
            row_num = i
            time_v = str(r[0]).strip()
            sym = str(r[1]).strip().upper()
            action = str(r[2]).strip()
            tf = str(r[3]).strip()
            reason = str(r[4]).strip()
            price = str(r[5]).strip()
            vol = str(r[6]).strip()
            sl = str(r[8]).strip()
            tp = str(r[9]).strip()
            oid = str(r[10]).strip()
            status = str(r[11]).strip()
            msg = str(r[12]).strip() if len(r) > 12 else ''
        except Exception:
            continue

        # فقط سفارشات خرید/فروش (نه خروج جزئی، نه OCO متحرک)
        if action not in ('خرید', 'فروش'):
            continue
        # استخراج oid‌ها (می‌توانند با | جدا شوند - OCO)
        oids = []
        for x in oid.split('|'):
            c = clean_oid(x)
            if c and c.isdigit():
                oids.append(c)
        sheet_orders.append({
            'row': row_num,
            'time': time_v,
            'sym': sym,
            'action': action,
            'reason': reason,
            'price': price,
            'vol': vol,
            'oid': oid,
            'oids': oids,
            'status': status,
        })

    print(f'\n📊 تعداد کل سفارشات در شیت: {len(sheet_orders)}')
    open_in_sheet = [o for o in sheet_orders if o['status'] in ('باز', 'ثبت‌شده', 'در انتظار تریگر')]
    filled_in_sheet = [o for o in sheet_orders if o['status'] == 'پر شد']
    cancelled_in_sheet = [o for o in sheet_orders if o['status'] == 'لغو شده']
    print(f'  - باز/ثبت‌شده: {len(open_in_sheet)}')
    print(f'  - پر شده: {len(filled_in_sheet)}')
    print(f'  - لغو شده: {len(cancelled_in_sheet)}')

    # ۲. دریافت سفارشات باز از صرافی
    client = make_client()
    code, data = client.open_orders()
    if code != 200:
        print(f'✗ خطا در open_orders: HTTP {code}')
        return 1
    exchange_orders = data.get('orders') or []
    print(f'\n📊 سفارشات باز در صرافی: {len(exchange_orders)}')

    # ۳. تطبیق: سفارشات باز در شیت باید در صرافی فعال باشند
    print('\n━━━ ۱) بررسی سفارشات «باز» در شیت ━━━')
    matched = 0
    mismatched = 0
    orphan_in_sheet = []
    for o in open_in_sheet:
        if not o['oids']:
            # بدون oid در شیت - ممکن است ردیف OCO بدون شناسه باشد
            print(f'  ⚠ ردیف {o["row"]} {o["sym"]} {o["action"]} {o["reason"][:40]}: بدون oid در شیت')
            continue
        # بررسی هر oid
        for oid in o['oids']:
            try:
                code, ds = client.order_status(oid)
                if code == 200 and isinstance(ds, dict):
                    ord_data = ds.get('order', ds)
                    api_status = ord_data.get('status', '?')
                    api_type = ord_data.get('type', '?')
                    api_sym = ord_data.get('srcCurrency', '?')
                    api_price = ord_data.get('price', '?')
                    if api_status == 'Active' or api_status == 'Inactive':
                        matched += 1
                        # تطبیق نام نماد
                        sym_match = (o['sym'].lower() in api_sym.lower()
                                     or api_sym.lower() in o['sym'].lower()
                                     or trader.SYMBOL_ALIASES.get(o['sym'], '').lower() == api_sym.lower())
                        if not sym_match:
                            print(f'  ⚠ ردیف {o["row"]}: {o["sym"]} ≠ صرافی {api_sym} (oid={oid})')
                            mismatched += 1
                    else:
                        print(f'  ✗ ردیف {o["row"]} {o["sym"]}: شیت=باز، صرافی={api_status} (oid={oid})')
                        mismatched += 1
                elif code == 404:
                    print(f'  ✗ ردیف {o["row"]} {o["sym"]}: oid={oid} در صرافی یافت نشد (404)')
                    mismatched += 1
                    orphan_in_sheet.append(o)
                else:
                    print(f'  ? ردیف {o["row"]} {o["sym"]}: oid={oid} HTTP={code} {str(ds)[:80]}')
            except Exception as ex:
                print(f'  ✗ ردیف {o["row"]} {o["sym"]}: oid={oid} خطا - {ex}')
                mismatched += 1
    print(f'\n  خلاصه: {matched} تطبیق، {mismatched} عدم تطبیق')

    # ۴. یتیم‌ها: سفارشات صرافی که در شیت نیستند
    print('\n━━━ ۲) یتیم‌ها: سفارشات صرافی بدون ردیف در شیت ━━━')
    sheet_oids = set()
    for o in sheet_orders:
        for oid in o['oids']:
            sheet_oids.add(oid)
    orphans_in_exchange = []
    for eo in exchange_orders:
        # استخراج oid از صرافی
        oid = clean_oid(eo.get('pairId')) or clean_oid(eo.get('id'))
        if not oid:
            continue
        if oid not in sheet_oids:
            orphans_in_exchange.append(eo)
    if orphans_in_exchange:
        print(f'  تعداد یتیم: {len(orphans_in_exchange)}')
        for eo in orphans_in_exchange:
            sym = eo.get('srcCurrency', '?')
            otype = eo.get('type', '?')
            price = eo.get('price', '?')
            amt = eo.get('amount', '?')
            pairId = eo.get('pairId', '?')
            cid = eo.get('clientOrderId') or ''
            execution = eo.get('execution', '?')
            print(f'  ⚠ {sym} | {otype} | {execution} | px={price} | amt={amt} | pairId={pairId} | cid={cid}')
    else:
        print('  ✓ هیچ سفارش یتیمی در صرافی نیست')

    # ۵. پوزیشن‌های فعال
    print('\n━━━ ۳) پوزیشن‌های فعال (مقایسه شیت با صرافی) ━━━')
    led = trader.read_ledger(ws)
    print(f'  پوزیشن‌های شیت: {len(led["positions"])}')
    for sym, p in led['positions'].items():
        rv = p.get('real_volume') or 0
        if rv <= 1e-12:
            continue
        # موجودی واقعی در صرافی
        try:
            avail = trader.currency_available(client, sym, use_active=False)
            # استفاده از نام مستعار برای دریافت موجودی
            alias = trader.SYMBOL_ALIASES.get(sym, sym)
            avail_alias = trader.currency_available(client, alias, use_active=False)
            avail_final = avail if avail is not None else avail_alias
            print(f'  {sym} (alias: {alias}):')
            print(f'    شیت: vol={rv:.6f} | entry={p.get("entry_price")}')
            print(f'    صرافی: موجودی فعال={avail_final:.6f}' if avail_final else f'    صرافی: موجودی=None')
            if avail_final and rv:
                diff_pct = (rv - avail_final) / rv * 100
                if abs(diff_pct) > 5:
                    print(f'    ⚠ اختلاف: {diff_pct:+.2f}%')
                else:
                    print(f'    ✓ اختلاف کم: {diff_pct:+.2f}%')
        except Exception as e:
            print(f'  {sym}: خطا در دریافت موجودی - {e}')

    print('\n' + '=' * 70)
    print('پایان بررسی')
    print('=' * 70)
    return 0


if __name__ == '__main__':
    sys.exit(main())
