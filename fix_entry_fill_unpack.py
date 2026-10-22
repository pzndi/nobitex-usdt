#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_entry_fill_unpack.py - رفع ValueError در sync_order_statuses

مشکل: در خط 157 (بخش G-scale VWAP)، _entry_fill با 3 متغیر unpack شده:
    _vwap, _, _ = _entry_fill(client, led, sym_c)
اما تابع _entry_fill فقط 2 مقدار برمی‌گرداند (price, fee).

راه‌حل: تغییر به 2 متغیر (همانند خط 122 که درست است).
"""
import os, sys, shutil, time

DEPLOY = '--deploy' in sys.argv

T_OLD = """                # Fetch VWAP from real trades
                _vwap, _, _ = _entry_fill(client, led, sym_c)"""

T_NEW = """                # Fetch VWAP from real trades
                _vwap, _ = _entry_fill(client, led, sym_c)"""


def main():
    print('=' * 70)
    print('fix_entry_fill_unpack.py - رفع ValueError در sync_order_statuses')
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
        print('+ trader.py: رفع unpack _entry_fill (3 -> 2 متغیر)')
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
        print('  cd ~/nobitex-usdt && venv/bin/python fix_entry_fill_unpack.py --deploy')
    print('=' * 70)
    return 0

if __name__ == '__main__':
    sys.exit(main())
