#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_oco_health_vwap.py - اصلاح oco_health_check برای استفاده از VWAP و کپ

مشکل: oco_health_check SL/TP را از دفتر می‌خواند (قدیمی) و OCO را با آن
بازسازی می‌کند. اگر قیمت بازار زیر SL قدیمی باشد، PriceConditionFailed رخ می‌دهد.

شاهد: MEW SL دفتر=0.0004884 اما بازار=0.0004883 → PriceConditionFailed

راه‌حل: 
۱. VWAP واقعی ورود از _entry_fill
۲. SL/TP بر اساس VWAP با کپ 0.49%/0.98%
۳. اگر قیمت بازار زیر SL باشد، SL را به‌روزرسانی کن
"""
import os, sys, shutil, time

DEPLOY = '--deploy' in sys.argv

T_OLD = """        sl_o, tp_o = None, None
        for _, rr in reversed(led['rows']):
            if rr[1].strip().upper() == sym and rr[2].strip() == 'خرید' and rr[11].strip() in EXECUTED:
                sl_o = parse_price(rr[8])
                tp_o = parse_price(rr[9])
                break
        
        if not (sl_o and tp_o and sl_o > 0 and tp_o > 0):
            log.error('G-oco-health: %s cannot rebuild OCO. SL/TP not found.', sym)
            continue
            
        vol_o = currency_available(client, sym)
        if vol_o is None or vol_o <= 1e-12:
            vol_o = rv
            log.warning('G-oco-health: %s active=0, using ledger vol %s', sym, rv)
        
        code2, data2 = client.place_oco_sell(sym, vol_o, tp_o, sl_o)"""

T_NEW = """        # G-fix: محاسبه SL/TP بر اساس VWAP واقعی و کپ، نه SL/TP قدیمی دفتر
        _entry_vwap, _ = _entry_fill(client, led, sym)
        sl_o, tp_o = None, None
        for _, rr in reversed(led['rows']):
            if rr[1].strip().upper() == sym and rr[2].strip() == 'خرید' and rr[11].strip() in EXECUTED:
                sl_o = parse_price(rr[8])
                tp_o = parse_price(rr[9])
                break
        
        if not (sl_o and tp_o and sl_o > 0 and tp_o > 0):
            log.error('G-oco-health: %s cannot rebuild OCO. SL/TP not found.', sym)
            continue
        
        # G-fix: بازمحاسبه SL/TP بر اساس VWAP و کپ
        if _entry_vwap and _entry_vwap > 0:
            _slm = getattr(st, 'sl_atr_mult', 0) or 0
            _tpm = getattr(st, 'tp_atr_mult', 0) or 0
            if _slm > 0 and _tpm > 0 and sl_o < _entry_vwap:
                _atr = (_entry_vwap - sl_o) / _slm
                sl_new = _entry_vwap - _slm * _atr
                tp_new = _entry_vwap + _tpm * _atr
                # کپ بر اساس min(VWAP, current_price)
                _current_px = prices.get(sym) if prices else None
                _ref_px = min(_entry_vwap, _current_px) if _current_px else _entry_vwap
                _tp_max = _ref_px * (1 + 0.98 / 100.0)
                _sl_min = _ref_px * (1 - 0.49 / 100.0)
                if tp_new > _tp_max:
                    tp_new = _tp_max
                if sl_new < _sl_min:
                    sl_new = _sl_min
                sl_o = sl_new
                tp_o = tp_new
                log.info('G-oco-health: %s SL/TP recalculated: SL=%s TP=%s (VWAP=%s)',
                         sym, fmt_price(sl_o), fmt_price(tp_o), fmt_price(_entry_vwap))
        
        vol_o = currency_available(client, sym)
        if vol_o is None or vol_o <= 1e-12:
            vol_o = rv
            log.warning('G-oco-health: %s active=0, using ledger vol %s', sym, rv)
        
        code2, data2 = client.place_oco_sell(sym, vol_o, tp_o, sl_o)"""


def main():
    print('=' * 70)
    print('fix_oco_health_vwap.py - اصلاح oco_health_check با VWAP و کپ')
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
            print(f'+ trader.py: oco_health_check با VWAP و کپ')
            print(f'  + backup: {bak}')
        else:
            print('+ trader.py (dry-run): oco_health_check با VWAP')
        return 0
    except SyntaxError as e:
        print(f'  + syntax error: {e}')
        return 1


if __name__ == '__main__':
    sys.exit(main())
