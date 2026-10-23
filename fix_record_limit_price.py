#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_record_limit_price.py - ثبت قیمت لیمیت به‌جای قیمت سیگنال در دفتر

مشکل: در buy_one، record_trade با fmt_price(price) (قیمت سیگنال) فراخوانی می‌شود،
نه با قیمت لیمیت واقعی (_limit_price / _price2).

این باعث می‌شود دفتر قیمت سیگنال را نشان دهد، نه قیمت لیمیت. اگر API داده fill
نداشته باشد، _entry_fill به قیمت اشتباه (سیگنال) برمی‌گردد.

شاهد: MEW با Scale 1/2 @ 0.00049079 اما دفتر 0.00049280 ثبت کرده.

راه‌حل: استفاده از fmt_price(_limit_price) و fmt_price(_price2) در record_trade.
"""
import os, sys, shutil, time

DEPLOY = '--deploy' in sys.argv

# باگ ۱: Scale 1/2 موفق
T_OLD_1 = """    if ok:
        record_trade(ws_t, 'خرید', sym, tf, reason, fmt_price(price), vol, amount,
                     sl, tp, oid, ST_PLACED, str(data)[:80])"""

T_NEW_1 = """    if ok:
        record_trade(ws_t, 'خرید', sym, tf, reason, fmt_price(_limit_price), vol, amount,
                     sl, tp, oid, ST_PLACED, str(data)[:80])"""

# باگ ۲: Scale 2/2 موفق
T_OLD_2 = """                if ok2:
                    record_trade(ws_t, 'خرید', sym, tf, reason2, fmt_price(price), vol2, amount2,
                                 sl, tp, oid2, ST_PLACED, str(data2)[:80])"""

T_NEW_2 = """                if ok2:
                    record_trade(ws_t, 'خرید', sym, tf, reason2, fmt_price(_price2), vol2, amount2,
                                 sl, tp, oid2, ST_PLACED, str(data2)[:80])"""

# باگ ۳: سفارش ناموفق
T_OLD_3 = """        record_trade(ws_t, 'خرید', sym, tf, reason, fmt_price(price), vol, amount,
                     sl, tp, '', 'ناموفق', str(data)[:100])"""

T_NEW_3 = """        record_trade(ws_t, 'خرید', sym, tf, reason, fmt_price(_limit_price), vol, amount,
                     sl, tp, '', 'ناموفق', str(data)[:100])"""


def main():
    print('=' * 70)
    print('fix_record_limit_price.py - ثبت قیمت لیمیت به‌جای قیمت سیگنال')
    print(f'mode: {"DEPLOY" if DEPLOY else "DRY-RUN"}')
    print('=' * 70)
    
    with open('trader.py', 'r', encoding='utf-8') as f:
        src = f.read()
    
    patches = []
    
    if T_OLD_1 in src:
        src = src.replace(T_OLD_1, T_NEW_1)
        patches.append('Scale 1/2: fmt_price(price) → fmt_price(_limit_price)')
    else:
        print('! T_OLD_1 (Scale 1/2) not found')
    
    if T_OLD_2 in src:
        src = src.replace(T_OLD_2, T_NEW_2)
        patches.append('Scale 2/2: fmt_price(price) → fmt_price(_price2)')
    else:
        print('! T_OLD_2 (Scale 2/2) not found')
    
    if T_OLD_3 in src:
        src = src.replace(T_OLD_3, T_NEW_3)
        patches.append('ناموفق: fmt_price(price) → fmt_price(_limit_price)')
    else:
        print('! T_OLD_3 (ناموفق) not found')
    
    if not patches:
        return 1
    
    try:
        compile(src, 'trader.py', 'exec')
        if DEPLOY:
            bak = f'trader.py.bak.{time.strftime("%Y%m%d_%H%M")}'
            shutil.copy('trader.py', bak)
            with open('trader.py', 'w', encoding='utf-8') as f:
                f.write(src)
            print(f'+ trader.py: {len(patches)} patches:')
            for p in patches:
                print(f'  + {p}')
            print(f'  + backup: {bak}')
        else:
            print(f'+ trader.py (dry-run): {len(patches)} patches:')
            for p in patches:
                print(f'  + {p}')
        return 0
    except SyntaxError as e:
        print(f'  + syntax error: {e}')
        return 1


if __name__ == '__main__':
    sys.exit(main())
