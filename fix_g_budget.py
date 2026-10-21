#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_g_budget.py - تطبیق حجم Scale با موجودی USDT
اگر USDT فقط برای Scale 1/2 کافی باشد، فقط Scale 1/2 ثبت می‌شود و Scale 2/2 رد می‌شود.
"""
import os, sys, shutil, time

DEPLOY = '--deploy' in sys.argv

# لایه ۱: بررسی اولیه در run
T_OLD_1 = """        if bal < st.order_size_usdt or bal - st.order_size_usdt < st.min_usdt_balance:
            log.info('خرید %s انجام نشد: موجودی USDT کافی نیست (%.1f)', sym, bal)
            continue"""

T_NEW_1 = """        # G-scale: بررسی فقط Scale 1/2 (نصف کل) به‌جای کل مبلغ
        _half_size = st.order_size_usdt * 0.5
        if bal < _half_size or bal - _half_size < st.min_usdt_balance:
            log.info('خرید %s انجام نشد: موجودی USDT کافی نیست (%.1f)', sym, bal)
            continue"""

# لایه ۲: داخل buy_one قبل از Scale 2/2
T_OLD_2 = """        # G-scale: Place second order at deep pullback level
        if _price2 and _size2 > 0 and not _is_market:
            vol2 = math.floor((_size2 / _price2) * 1e8) / 1e8
            if vol2 > 0:"""

T_NEW_2 = """        # G-scale: Place second order at deep pullback level
        # G-budget: بررسی موجودی واقعی USDT قبل از Scale 2/2
        if _price2 and _size2 > 0 and not _is_market:
            _usdt_avail = currency_available(client, 'usdt') or 0.0
            if _usdt_avail < _size2:
                log.info('G-budget: %s فقط Scale 1/2 ثبت شد (موجودی USDT=%.2f، لازم=%.2f)',
                         sym, _usdt_avail, _size2)
                _price2 = None  # Scale 2/2 را رد کن
        if _price2 and _size2 > 0 and not _is_market:
            vol2 = math.floor((_size2 / _price2) * 1e8) / 1e8
            if vol2 > 0:"""


def main():
    print('=' * 70)
    print('fix_g_budget.py - تطبیق حجم Scale با موجودی USDT')
    print(f'mode: {"DEPLOY" if DEPLOY else "DRY-RUN"}')
    print('=' * 70)
    
    with open('trader.py', 'r', encoding='utf-8') as f:
        trader_src = f.read()
    
    patches = []
    
    # لایه ۱
    if T_OLD_1 in trader_src:
        trader_src = trader_src.replace(T_OLD_1, T_NEW_1)
        patches.append('Layer 1: بررسی اولیه (run) با نصف مبلغ')
    else:
        print('! T_OLD_1 (Layer 1) not found')
    
    # لایه ۲
    if T_OLD_2 in trader_src:
        trader_src = trader_src.replace(T_OLD_2, T_NEW_2)
        patches.append('Layer 2: بررسی داخل buy_one قبل از Scale 2/2')
    else:
        print('! T_OLD_2 (Layer 2) not found')
    
    if not patches:
        print('! هیچ پچی قابل اعمال نیست')
        return 1
    
    try:
        compile(trader_src, 'trader.py', 'exec')
        print(f'+ {len(patches)} patches:')
        for p in patches:
            print(f'  + {p}')
        print('  + syntax check: OK')
    except SyntaxError as e:
        print(f'  + syntax check FAILED: {e}')
        return 1
    
    if DEPLOY:
        bak = f'trader.py.bak.{time.strftime("%Y%m%d_%H%M")}'
        shutil.copy('trader.py', bak)
        print(f'  + backup: {bak}')
        with open('trader.py', 'w', encoding='utf-8') as f:
            f.write(trader_src)
        print('  + deployed: trader.py')
    else:
        with open('trader_candidate.py', 'w', encoding='utf-8') as f:
            f.write(trader_src)
        print('  (dry-run: candidate saved)')
    
    print()
    print('=' * 70)
    if DEPLOY:
        print('Deploy complete.')
    else:
        print('dry-run OK. To deploy:')
        print('  cd ~/nobitex-usdt && venv/bin/python fix_g_budget.py --deploy')
    print('=' * 70)
    return 0

if __name__ == '__main__':
    sys.exit(main())
