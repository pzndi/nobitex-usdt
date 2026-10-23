#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_real_fee_and_exit_price.py - اصلاح کپ کارمزد و باگ قیمت خروج

۱. اصلاح کپ TP/SL بر اساس کارمزد واقعی 0.18% (به‌جای 0.28%):
   - TP ناخالص: 1.08% → 0.98% (0.8% سود + 0.18% کارمزد)
   - SL ناخالص: 0.54% → 0.49% (نصف TP)

۲. رفع باگ قیمت خروج در reconcile_real_positions:
   - قبلاً: قیمت لحظه‌ای (price) به‌عنوان قیمت خروج ثبت می‌شد
   - اکنون: قیمت واقعی فروش از _exit_fill (VWAP واقعی) استفاده می‌شود
"""
import os, sys, shutil, time

DEPLOY = '--deploy' in sys.argv


def patch_caps():
    """اصلاح کپ TP/SL در دو بخش G-fillanchor"""
    with open('trader.py', 'r', encoding='utf-8') as f:
        src = f.read()
    
    T_OLD = """                    # G-cap: حداکثر سود خالص 0.8% (TP≤1.08% ناخالص، SL≤0.54% ناخالص)
                    _tp_max = _fill_px * (1 + 1.08 / 100.0)
                    _sl_min = _fill_px * (1 - 0.54 / 100.0)"""
    
    T_NEW = """                    # G-cap: حداکثر سود خالص 0.8% (TP≤0.98% ناخالص، SL≤0.49% ناخالص)
                    # کارمزد واقعی نوبیتکس 0.18% (0.09% خرید + 0.09% فروش)
                    _tp_max = _fill_px * (1 + 0.98 / 100.0)
                    _sl_min = _fill_px * (1 - 0.49 / 100.0)"""
    
    if T_OLD not in src:
        print('! T_OLD (caps) not found - already patched?')
        return False
    
    count = src.count(T_OLD)
    new_src = src.replace(T_OLD, T_NEW)
    
    try:
        compile(new_src, 'trader.py', 'exec')
        if DEPLOY:
            bak = f'trader.py.bak.{time.strftime("%Y%m%d_%H%M")}'
            shutil.copy('trader.py', bak)
            with open('trader.py', 'w', encoding='utf-8') as f:
                f.write(new_src)
            print(f'+ trader.py: اصلاح کپ TP/SL در {count} بخش (کارمزد واقعی 0.18%)')
            print(f'  + backup: {bak}')
        else:
            print(f'+ trader.py (dry-run): اصلاح کپ TP/SL در {count} بخش')
        return True
    except SyntaxError as e:
        print(f'  + syntax error: {e}')
        return False


def patch_exit_price():
    """رفع باگ قیمت خروج در reconcile_real_positions"""
    with open('trader.py', 'r', encoding='utf-8') as f:
        src = f.read()
    
    T_OLD = """        record_closed(ws_t, sym, e_time, _entry_n7 or p.get('entry_price') or price, price,
                      sold, 'خروج از کیف پول (OCO یا فروش دستی)', 'واقعی', fee_usdt=_sell_fee_n7 + _buy_fee_n7)"""
    
    T_NEW = """        # G-fix: استفاده از قیمت واقعی فروش (exit VWAP) به‌جای قیمت لحظه‌ای
        _xf_re = _exit_fill(client, _reconcile_oids) if _reconcile_oids else None
        _real_exit = ((_xf_re[0] if _xf_re and _xf_re[0] else None) or price)
        _real_sell_fee = (_xf_re[2] if _xf_re else _sell_fee_n7)
        record_closed(ws_t, sym, e_time, _entry_n7 or p.get('entry_price') or price, _real_exit,
                      sold, 'خروج از کیف پول (OCO یا فروش دستی)', 'واقعی', fee_usdt=_real_sell_fee + _buy_fee_n7)"""
    
    if T_OLD not in src:
        print('! T_OLD (exit price) not found - already patched?')
        return False
    
    new_src = src.replace(T_OLD, T_NEW)
    
    # همچنین باید _reconcile_oids را تعریف کنیم - پیدا کردن ردیف‌های فروش این نماد
    # در بخش reconcile، oids از ردیف‌های فروش باز همان نماد گرفته می‌شود
    # اما در کد فعلی، oids تعریف نشده. باید اضافه کنیم.
    # پیدا کردن جایی که _entry_n7 محاسبه می‌شود و اضافه کردن _reconcile_oids
    
    T_OLD_2 = """        _entry_n7, _buy_fee_n7 = _entry_fill(client, led, sym)"""
    T_NEW_2 = """        _entry_n7, _buy_fee_n7 = _entry_fill(client, led, sym)
        # G-fix: جمع‌آوری oids فروش برای دریافت قیمت واقعی خروج
        _reconcile_oids = []
        for _, _rr in reversed(led.get('rows') or []):
            if (str(_rr[1]).strip().upper() == sym
                    and str(_rr[2]).strip() == 'فروش'
                    and str(_rr[11]).strip() in OPENISH):
                for _x in str(_rr[10]).split('|'):
                    _c = clean_oid(_x)
                    if _c and _c.isdigit():
                        _reconcile_oids.append(_c)"""
    
    if T_OLD_2 in new_src:
        new_src = new_src.replace(T_OLD_2, T_NEW_2)
    
    try:
        compile(new_src, 'trader.py', 'exec')
        if DEPLOY:
            with open('trader.py', 'w', encoding='utf-8') as f:
                f.write(new_src)
            print('+ trader.py: رفع باگ قیمت خروج در reconcile')
        else:
            print('+ trader.py (dry-run): رفع باگ قیمت خروج در reconcile')
        return True
    except SyntaxError as e:
        print(f'  + syntax error: {e}')
        return False


def main():
    print('=' * 70)
    print('fix_real_fee_and_exit_price.py - اصلاح کپ کارمزد و باگ قیمت خروج')
    print(f'mode: {"DEPLOY" if DEPLOY else "DRY-RUN"}')
    print('=' * 70)
    
    print()
    print('=== بخش ۱: اصلاح کپ TP/SL ===')
    s1 = patch_caps()
    
    print()
    print('=== بخش ۲: رفع باگ قیمت خروج ===')
    s2 = patch_exit_price()
    
    print()
    print('=' * 70)
    if DEPLOY:
        print('Deploy complete.')
        print()
        print('تغییرات:')
        print('  ۱. کپ TP/SL بر اساس کارمزد واقعی 0.18%:')
        print('     - TP: 1.08% → 0.98%')
        print('     - SL: 0.54% → 0.49%')
        print('     - سود خالص max: 0.80% (بدون تغییر)')
        print('     - ضرر خالص max: 0.67% (بهبود از 0.82%)')
        print()
        print('  ۲. رفع باگ قیمت خروج در reconcile:')
        print('     - قبلاً: قیمت لحظه‌ای به‌عنوان خروج ثبت می‌شد')
        print('     - اکنون: قیمت واقعی فروش (VWAP) از API استفاده می‌شود')
    else:
        print('dry-run OK. To deploy:')
        print('  cd ~/nobitex-usdt && venv/bin/python fix_real_fee_and_exit_price.py --deploy')
    print('=' * 70)
    return 0 if (s1 or s2) else 1


if __name__ == '__main__':
    sys.exit(main())
