#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_analysis_exit_price.py - رفع باگ قیمت خروج در _record_analysis داخل reconcile

مشکل: در reconcile_real_positions، record_closed از _real_exit (VWAP واقعی)
استفاده می‌کند، اما _record_analysis از price (قیمت لحظه‌ای) استفاده می‌کند.

این باعث می‌شود P&L در تب اتمام معاملات درست باشد، اما P&L در تب تحلیل
معاملات اشتباه باشد.

راه‌حل: استفاده از _real_exit در _record_analysis به‌جای price.
"""
import os, sys, shutil, time

DEPLOY = '--deploy' in sys.argv

T_OLD = """        _record_analysis(ws_t, sym, _entry_an, _exit_an, _vol_an,
                            _pnl_an, _pct_an, _dur_an,
                            'خروج از کیف پول (OCO یا فروش دستی)',
                            led, client, st)"""

T_NEW = """        _record_analysis(ws_t, sym, _entry_an, _real_exit, _vol_an,
                            _vol_an * (_real_exit - _entry_an) - _real_sell_fee - _buy_fee_n7,
                            (_real_exit / _entry_an - 1) * 100 if _entry_an else 0.0,
                            _dur_an,
                            'خروج از کیف پول (OCO یا فروش دستی)',
                            led, client, st)"""


def main():
    print('=' * 70)
    print('fix_analysis_exit_price.py - رفع باگ قیمت خروج در تحلیل reconcile')
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
            print(f'+ trader.py: رفع باگ _exit_an در _record_analysis (reconcile)')
            print(f'  + backup: {bak}')
        else:
            print('+ trader.py (dry-run): رفع باگ _exit_an')
        return 0
    except SyntaxError as e:
        print(f'  + syntax error: {e}')
        return 1


if __name__ == '__main__':
    sys.exit(main())
