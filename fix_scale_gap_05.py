#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_scale_gap_05.py - تغییر فاصله Scale 2/2 از Scale 1/2 به 0.5%
قبلاً: price_2 = price_1 * 0.999 (0.1% فاصله)
اکنون: price_2 = price_1 * 0.995 (0.5% فاصله)
"""
import os, sys, shutil, time

DEPLOY = '--deploy' in sys.argv

T_OLD = """        # Scale 2/2: همیشه 0.1% پایین‌تر از Scale 1/2
        price_2 = price_1 * 0.999

        return price_1, price_2"""

T_NEW = """        # Scale 2/2: همیشه 0.5% پایین‌تر از Scale 1/2
        price_2 = price_1 * 0.995

        return price_1, price_2"""


def main():
    print('=' * 70)
    print('fix_scale_gap_05.py - تغییر فاصله Scale 2/2 از Scale 1/2 به 0.5%')
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
        print('+ trader.py: فاصله Scale 2/2 از Scale 1/2 = 0.5%')
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
    else:
        print('dry-run OK. To deploy:')
        print('  cd ~/nobitex-usdt && venv/bin/python fix_scale_gap_05.py --deploy')
    print('=' * 70)
    return 0

if __name__ == '__main__':
    sys.exit(main())
