#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_vwap_cap.py - اضافه کردن کپ TP/SL در بخش VWAP (Scale-in) G-fillanchor

مشکل: بخش VWAP (خط 193) کپ TP/SL ندارد، فقط بخش اصلی (خط 95) دارد.
این یعنی وقتی Scale-in رخ می‌دهد (دومین Scale 1/2 پر می‌شود)، TP/SL بدون کپ محاسبه می‌شود.

راه‌حل: اضافه کردن همان کپ به بخش VWAP با تورفتگی صحیح (24 فاصله).
"""
import os, sys, shutil, time

DEPLOY = '--deploy' in sys.argv

# بخش VWAP با تورفتگی 24 فاصله (نه 20)
T_OLD = """                        _sl_new = _fill_px - _slm * _atr
                        _tp_new = _fill_px + _tpm * _atr
                        if 0 < _sl_new < _fill_px < _tp_new:"""

T_NEW = """                        _sl_new = _fill_px - _slm * _atr
                        _tp_new = _fill_px + _tpm * _atr
                        # G-cap: حداکثر سود خالص 0.8% (TP≤1.08% ناخالص، SL≤0.54% ناخالص)
                        _tp_max = _fill_px * (1 + 1.08 / 100.0)
                        _sl_min = _fill_px * (1 - 0.54 / 100.0)
                        if _tp_new > _tp_max:
                            _tp_new = _tp_max
                        if _sl_new < _sl_min:
                            _sl_new = _sl_min
                        if 0 < _sl_new < _fill_px < _tp_new:"""


def main():
    print('=' * 70)
    print('fix_vwap_cap.py - اضافه کردن کپ TP/SL در بخش VWAP (Scale-in)')
    print(f'mode: {"DEPLOY" if DEPLOY else "DRY-RUN"}')
    print('=' * 70)
    
    with open('trader.py', 'r', encoding='utf-8') as f:
        src = f.read()
    
    if T_OLD not in src:
        print('! T_OLD pattern not found - already patched?')
        return 1
    
    # شمارش تعداد occurrence (باید 1 باشد)
    count = src.count(T_OLD)
    print(f'  + تعداد occurrenceهای T_OLD: {count}')
    
    new_src = src.replace(T_OLD, T_NEW)
    
    try:
        compile(new_src, 'trader.py', 'exec')
        print('+ trader.py: اضافه شدن کپ TP/SL در بخش VWAP (Scale-in)')
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
        print()
        print('اکنون هر دو بخش G-fillanchor کپ دارند:')
        print('  - بخش اصلی (fill-anchor): ✓ کپ فعال')
        print('  - بخش VWAP (Scale-in): ✓ کپ فعال')
    else:
        print('dry-run OK. To deploy:')
        print('  cd ~/nobitex-usdt && venv/bin/python fix_vwap_cap.py --deploy')
    print('=' * 70)
    return 0

if __name__ == '__main__':
    sys.exit(main())
