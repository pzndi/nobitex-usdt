#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_global_chart.py — تست پشتیبانی نوبیتکس از نمودار جهانی (_GLOBAL)"""
import requests, time, sys

UDF_URL = 'https://apiv2.nobitex.ir/market/udf/history'
HEADERS = {'User-Agent': 'TraderBot/NobitexSheetBot-2.0'}

TEST_SYMBOLS = [
    ('BTC', 'BTCUSDT', 'BTCUSDT_GLOBAL'),
    ('ETH', 'ETHUSDT', 'ETHUSDT_GLOBAL'),
    ('SOL', 'SOLUSDT', 'SOLUSDT_GLOBAL'),
    ('XRP', 'XRPUSDT', 'XRPUSDT_GLOBAL'),
    ('INJ', 'INJUSDT', 'INJUSDT_GLOBAL'),
    ('STRK', 'STRKUSDT', 'STRKUSDT_GLOBAL'),
    ('BAT', 'BATUSDT', 'BATUSDT_GLOBAL'),
    ('S', 'SUSDT', 'SUSDT_GLOBAL'),
    ('ZEC', 'ZECUSDT', 'ZECUSDT_GLOBAL'),
    ('FIL', 'FILUSDT', 'FILUSDT_GLOBAL'),
    ('NEAR', 'NEARUSDT', 'NEARUSDT_GLOBAL'),
    ('DOGE', 'DOGEUSDT', 'DOGEUSDT_GLOBAL'),
]

def fetch(symbol, resolution='60', lookback=50):
    to = int(time.time())
    frm = to - (lookback + 10) * 60 * 60
    try:
        r = requests.get(UDF_URL, params={'symbol': symbol, 'resolution': resolution,
                                          'from': frm, 'to': to}, headers=HEADERS, timeout=30)
        d = r.json()
        if d.get('s') == 'ok' and d.get('t'):
            return {'ok': True, 'n': len(d['t']), 'px': float(d['c'][-1]), 'vol': float(d['v'][-1])}
        return {'ok': False, 'err': d.get('errmsg', 'unknown')[:60]}
    except Exception as e:
        return {'ok': False, 'err': str(e)[:60]}

print('=' * 78)
print('تست پشتیبانی نوبیتکس از نمودار جهانی (_GLOBAL suffix)')
print('=' * 78)
print(f'{"نماد":<8} {"محلی":<30} {"جهانی":<30} {"پریمیوم٪":<10}')
print('-' * 78)

all_ok = True
for name, loc, glb in TEST_SYMBOLS:
    rl = fetch(loc)
    rg = fetch(glb)
    ls = f'{"✓" if rl["ok"] else "✗"} n={rl.get("n","?")} px={rl.get("px","?")}'[:29]
    gs = f'{"✓" if rg["ok"] else "✗"} n={rg.get("n","?")} px={rg.get("px","?")}'[:29]
    if rl['ok'] and rg['ok']:
        prem = (rl['px'] / rg['px'] - 1) * 100
        ds = f'{prem:+.2f}%'
    elif not rg['ok']:
        ds = f'ERR: {rg.get("err","")[:20]}'
        all_ok = False
    else:
        ds = '—'
    print(f'{name:<8} {ls:<30} {gs:<30} {ds:<10}')

print()
if all_ok:
    print('✓ همه نمادها نمودار جهانی پشتیبانی می‌کنند. آماده پیاده‌سازی هیبریدی.')
    sys.exit(0)
else:
    print('✗ برخی نمادها مشکل داشتند. fallback به محلی فعال خواهد شد.')
    sys.exit(1)
