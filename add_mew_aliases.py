#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""add_mew_aliases.py - اضافه کردن MEW, DOOD, MASK, 1M_PEPE به SYMBOL_ALIASES

مشکل: این نمادها در SYMBOL_ALIASES نیستند، که باعث می‌شود G-oco-health و
cancel_stale_entries نتوانند OCOهای آن‌ها را پیدا کنند.

شاهد: MEW با AmountTooLow fail شد چون G-oco-health couldn't find its OCO.

نام‌های کامل:
- MEW → cat in a dogs world
- DOOD → DOOD (همان نام کوتاه با حروف بزرگ)
- MASK → MASK
- 1M_PEPE → 1M_PEPE
"""
import os, sys, shutil, time

DEPLOY = '--deploy' in sys.argv

T_OLD = "    'GRT': 'TheGraph',"

T_NEW = """    'GRT': 'TheGraph',
    'MEW': 'cat in a dogs world',
    'DOOD': 'DOOD',
    'MASK': 'MASK',
    '1M_PEPE': '1M_PEPE',"""


def main():
    print('=' * 70)
    print('add_mew_aliases.py - اضافه کردن MEW, DOOD, MASK, 1M_PEPE به aliases')
    print(f'mode: {"DEPLOY" if DEPLOY else "DRY-RUN"}')
    print('=' * 70)
    
    with open('trader.py', 'r', encoding='utf-8') as f:
        src = f.read()
    
    if T_OLD not in src:
        print('! T_OLD not found')
        return 1
    
    if "'MEW'" in src.split('SYMBOL_ALIASES')[1].split('}')[0]:
        print('- MEW از قبل موجود است')
        return 0
    
    new_src = src.replace(T_OLD, T_NEW)
    
    try:
        compile(new_src, 'trader.py', 'exec')
        if DEPLOY:
            bak = f'trader.py.bak.{time.strftime("%Y%m%d_%H%M")}'
            shutil.copy('trader.py', bak)
            with open('trader.py', 'w', encoding='utf-8') as f:
                f.write(new_src)
            print(f'+ trader.py: اضافه شدن 4 نماد به SYMBOL_ALIASES')
            print(f'  + MEW → cat in a dogs world')
            print(f'  + DOOD → DOOD')
            print(f'  + MASK → MASK')
            print(f'  + 1M_PEPE → 1M_PEPE')
            print(f'  + backup: {bak}')
        else:
            print('+ trader.py (dry-run): اضافه شدن 4 نماد')
        return 0
    except SyntaxError as e:
        print(f'  + syntax error: {e}')
        return 1


if __name__ == '__main__':
    sys.exit(main())
