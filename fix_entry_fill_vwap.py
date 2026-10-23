#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_entry_fill_vwap.py - اصلاح _entry_fill برای محاسبه VWAP همه خریدها

مشکل: _entry_fill فقط آخرین خرید را برمی‌گرداند، نه VWAP همه خریدها.
وقتی Scale 1/2 و Scale 2/2 هر دو پر می‌شوند، فقط آخرین خرید محاسبه می‌شود.

شاهد: NEAR با دو خرید (4.984 و 5.140) ولی _entry_fill فقط 5.140 را برگرداند.

راه‌حل: جمع‌آوری همه oidهای خرید و محاسبه VWAP وزنی.
"""
import os, sys, shutil, time

DEPLOY = '--deploy' in sys.argv

T_OLD = """def _entry_fill(client, led, sym):
    \"\"\"N7: (price, fee_usdt_equiv) of the LAST executed buy of sym from real
    fills; fallback to ledger row price with zero fee. Buy fee is charged in
    the coin itself -> converted at fill price.\"\"\"
    oid = None
    px = None
    for _, rr in (led.get('rows') or []):
        if (rr[1].strip().upper() == sym and rr[2].strip() == 'خرید'
                and rr[11].strip() in EXECUTED):
            v = parse_price(rr[5])
            if v:
                px = v
            fo = clean_oid(str(rr[10]).split('|')[0])
            if fo and fo != '—':
                oid = fo
    if oid and client is not None:
        f = _fills_for_orders(client, [oid]).get(oid)
        if f:
            return f['vwap'], f['fee'] * f['vwap']
    return px, 0.0"""

T_NEW = """def _entry_fill(client, led, sym):
    \"\"\"N7: (vwap, fee_usdt_equiv) of ALL executed buys of sym from real
    fills; fallback to ledger row price with zero fee. Buy fee is charged in
    the coin itself -> converted at fill price.
    G-fix: محاسبه VWAP وزنی همه خریدها (Scale 1/2 + Scale 2/2)، نه فقط آخرین.\"\"\"
    all_oids = []
    last_px = None
    for _, rr in (led.get('rows') or []):
        if (rr[1].strip().upper() == sym and rr[2].strip() == 'خرید'
                and rr[11].strip() in EXECUTED):
            v = parse_price(rr[5])
            if v:
                last_px = v
            fo = clean_oid(str(rr[10]).split('|')[0])
            if fo and fo != '—':
                all_oids.append(fo)
    if all_oids and client is not None:
        fills = _fills_for_orders(client, all_oids)
        if fills:
            total_cost = sum(f['vwap'] * f['amount'] for f in fills.values())
            total_amount = sum(f['amount'] for f in fills.values())
            total_fee_coin = sum(f['fee'] for f in fills.values())
            if total_amount > 0:
                vwap = total_cost / total_amount
                fee_usdt = total_fee_coin * vwap
                return vwap, fee_usdt
    return last_px, 0.0"""


def main():
    print('=' * 70)
    print('fix_entry_fill_vwap.py - اصلاح _entry_fill برای VWAP همه خریدها')
    print(f'mode: {"DEPLOY" if DEPLOY else "DRY-RUN"}')
    print('=' * 70)
    
    with open('trader.py', 'r', encoding='utf-8') as f:
        src = f.read()
    
    if T_OLD not in src:
        print('! T_OLD not found - already patched?')
        return 1
    
    new_src = src.replace(T_OLD, T_NEW)
    
    try:
        compile(new_src, 'trader.py', 'exec')
        if DEPLOY:
            bak = f'trader.py.bak.{time.strftime("%Y%m%d_%H%M")}'
            shutil.copy('trader.py', bak)
            with open('trader.py', 'w', encoding='utf-8') as f:
                f.write(new_src)
            print(f'+ trader.py: اصلاح _entry_fill برای VWAP همه خریدها')
            print(f'  + backup: {bak}')
        else:
            print('+ trader.py (dry-run): اصلاح _entry_fill')
        return 0
    except SyntaxError as e:
        print(f'  + syntax error: {e}')
        return 1


if __name__ == '__main__':
    sys.exit(main())
