#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_vwap_cap_current_price.py - رفع کپ VWAP با استفاده از قیمت فعلی بازار

مشکل: وقتی Scale-in رخ می‌دهد و VWAP > قیمت بازار، SL محاسبه‌شده (بر اساس VWAP)
می‌تواند به قیمت بازار نزدیک شود یا حتی بالاتر باشد، که باعث:
۱. خطای PriceConditionFailed در ثبت OCO
۲. اجرای سریع SL (در عرض چند ثانیه)

راه‌حل: کپ بر اساس min(VWAP, current_price) اعمال شود.
اگر VWAP > قیمت بازار، از قیمت بازار استفاده می‌کنیم.
"""
import os, sys, shutil, time

DEPLOY = '--deploy' in sys.argv

T_OLD = """                _vwap, _ = _entry_fill(client, led, sym_c)
                if _vwap and _vwap > 0:
                    _fill_px = _vwap
                    _p_sig = parse_price(r[5])
                    _sl_old, _tp_old = parse_price(r[8]), parse_price(r[9])
                    _slm = getattr(st, 'sl_atr_mult', 0) or 0
                    _tpm = getattr(st, 'tp_atr_mult', 0) or 0
                    if (_p_sig and _sl_old and _tp_old and _slm > 0 and _tpm > 0 and _p_sig > _sl_old):
                        _atr = (_p_sig - _sl_old) / _slm
                        _sl_new = _fill_px - _slm * _atr
                        _tp_new = _fill_px + _tpm * _atr
                        # G-cap: حداکثر سود خالص 0.8% (TP≤1.08% ناخالص، SL≤0.54% ناخالص)
                        _tp_max = _fill_px * (1 + 1.08 / 100.0)
                        _sl_min = _fill_px * (1 - 0.54 / 100.0)
                        if _tp_new > _tp_max:
                            _tp_new = _tp_max
                        if _sl_new < _sl_min:
                            _sl_new = _sl_min
                        if 0 < _sl_new < _fill_px < _tp_new:"""

T_NEW = """                _vwap, _ = _entry_fill(client, led, sym_c)
                if _vwap and _vwap > 0:
                    _fill_px = _vwap
                    # G-fix: اگر VWAP بالاتر از قیمت بازار است، از قیمت بازار استفاده کن
                    # این از خطای PriceConditionFailed و اجرای سریع SL جلوگیری می‌کند
                    _current_px = prices.get(sym_c)
                    if _current_px and _current_px < _fill_px:
                        _fill_px = _current_px
                    _p_sig = parse_price(r[5])
                    _sl_old, _tp_old = parse_price(r[8]), parse_price(r[9])
                    _slm = getattr(st, 'sl_atr_mult', 0) or 0
                    _tpm = getattr(st, 'tp_atr_mult', 0) or 0
                    if (_p_sig and _sl_old and _tp_old and _slm > 0 and _tpm > 0 and _p_sig > _sl_old):
                        _atr = (_p_sig - _sl_old) / _slm
                        _sl_new = _fill_px - _slm * _atr
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
    print('fix_vwap_cap_current_price.py - رفع کپ VWAP با قیمت فعلی بازار')
    print(f'mode: {"DEPLOY" if DEPLOY else "DRY-RUN"}')
    print('=' * 70)
    
    with open('trader.py', 'r', encoding='utf-8') as f:
        src = f.read()
    
    if T_OLD not in src:
        print('! T_OLD pattern not found - already patched?')
        return 1
    
    new_src = src.replace(T_OLD, T_NEW)
    
    try:
        compile(new_src, 'trader.py', 'exec')
        print('+ trader.py: رفع کپ VWAP با min(VWAP, current_price)')
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
        print('رفع مشکل:')
        print('  - قبل: SL بر اساس VWAP محاسبه می‌شد')
        print('    اگر VWAP > قیمت بازار → SL نزدیک به بازار → PriceConditionFailed')
        print('  - بعد: SL بر اساس min(VWAP, current_price) محاسبه می‌شود')
        print('    همیشه SL ≥ 0.54% زیر قیمت مرجع (کمترین)')
    else:
        print('dry-run OK. To deploy:')
        print('  cd ~/nobitex-usdt && venv/bin/python fix_vwap_cap_current_price.py --deploy')
    print('=' * 70)
    return 0

if __name__ == '__main__':
    sys.exit(main())
