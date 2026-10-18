#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""تست اعتبارسنجی فیلد mark به‌عنوان قیمت جهانی"""
import requests, sys

HEADERS = {'User-Agent': 'TraderBot/NobitexSheetBot-2.0'}

# نمادهایی که می‌خواهیم تست کنیم
TEST_SYMS = ['btc', 'eth', 'sol', 'xrp', 'inj', 'strk', 'bat', 's', 'zec',
             'fil', 'near', 'doge', 'ada', 'prom', 'zil', 'sand', 'wal',
             'magic', 'pump', 'moodeng', 'sui', 'copxon', 'slvon']

print('=' * 90)
print(f'{"نماد":<10} {"bestSell":<12} {"bestBuy":<12} {"latest":<12} {"mark":<12} {"پریمیوم٪":<10} {"وضعیت":<15}')
print('=' * 90)

results = []
for sym in TEST_SYMS:
    try:
        r = requests.post('https://apiv2.nobitex.ir/market/stats',
                          json={'stats': f'{sym}-usdt'},
                          headers=HEADERS, timeout=15)
        d = r.json().get('stats', {}).get(f'{sym}-usdt', {})
        if not d or d.get('isClosed'):
            print(f'{sym.upper():<10} {"—":<12} {"—":<12} {"—":<12} {"—":<12} {"—":<10} {"بسته/ناموجود":<15}')
            results.append((sym, False, 'closed'))
            continue
        bs = float(d.get('bestSell') or 0)
        bb = float(d.get('bestBuy') or 0)
        lt = float(d.get('latest') or 0)
        mk = float(d.get('mark') or 0)
        if bs > 0 and mk > 0:
            prem = (bs / mk - 1) * 100
            status = '✓ جهانی دارد' if prem < 15 else '⚠ پریمیوم بالا'
            print(f'{sym.upper():<10} {bs:<12.6g} {bb:<12.6g} {lt:<12.6g} {mk:<12.6g} {prem:+.2f}%     {status:<15}')
            results.append((sym, True, prem))
        elif mk > 0:
            print(f'{sym.upper():<10} {"0":<12} {"0":<12} {"0":<12} {mk:<12.6g} {"—":<10} {"⚠ فقط mark":<15}')
            results.append((sym, False, 'mark_only'))
        else:
            print(f'{sym.upper():<10} {bs:<12.6g} {bb:<12.6g} {lt:<12.6g} {"0":<12} {"—":<10} {"✗ بدون mark":<15}')
            results.append((sym, False, 'no_mark'))
    except Exception as e:
        print(f'{sym.upper():<10} ERROR: {str(e)[:50]}')
        results.append((sym, False, 'error'))

print()
print('=' * 90)
tradeable = [r for r in results if r[1] is True and isinstance(r[2], float) and r[2] < 15]
blocked = [r for r in results if not r[1] or (isinstance(r[2], float) and r[2] >= 15)]
print(f'✓ قابل معامله (mark>0, پریمیوم<15٪): {len(tradeable)} نماد')
print(f'✗ رد شده (بدون mark یا پریمیوم بالا): {len(blocked)} نماد')
print(f'   {", ".join(r[0].upper() for r in blocked)}')
print()
print('تحلیل:')
print('  - اگر mark ≈ bestSell (پریمیوم < 3٪) → mark احتمالاً قیمت جهانی است')
print('  - اگر mark < bestSell (پریمیوم 3-10٪) → توجیه اقتصادی دارد (پریمیوم تومانی)')
print('  - اگر mark >> bestSell یا منفی → mark قیمت جهانی نیست')
