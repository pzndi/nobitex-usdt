#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_max_sl_band_and_tp_cap.py - رفع MAX_SL_BAND_PCT و اضافه کردن کپ TP/SL

۱. اضافه کردن MAX_SL_BAND_PCT به TRADING_KEYS در settings.py
۲. اضافه کردن کپ TP/SL در G-fillanchor (دو بخش در trader.py):
   - TP ناخالص ≤ 1.08% (0.8% سود خالص + 0.28% کارمزد)
   - SL ناخالص ≤ 0.54% (نصف TP برای نسبت 2:1)
"""
import os, sys, shutil, time

DEPLOY = '--deploy' in sys.argv


def patch_settings():
    """اضافه کردن MAX_SL_BAND_PCT به TRADING_KEYS در settings.py"""
    with open('settings.py', 'r', encoding='utf-8') as f:
        src = f.read()
    
    # الگوی TRADING_KEYS - اضافه کردن MAX_SL_BAND_PCT
    T_OLD = "'PARTIAL_EXIT_PCT', 'PUMP_GUARD_PCT'}"
    T_NEW = "'PARTIAL_EXIT_PCT', 'PUMP_GUARD_PCT', 'MAX_SL_BAND_PCT'}"
    
    if T_OLD in src and 'MAX_SL_BAND_PCT' not in src.split('TRADING_KEYS')[1].split('}')[0] if 'TRADING_KEYS' in src else False:
        # اگر MAX_SL_BAND_PCT هنوز در TRADING_KEYS نیست
        pass
    
    # روش ساده‌تر: بررسی آیا MAX_SL_BAND_PCT در TRADING_KEYS هست
    # پیدا کردن TRADING_KEYS = {...}
    import re
    m = re.search(r"TRADING_KEYS\s*=\s*\{([^}]+)\}", src)
    if m:
        keys_content = m.group(1)
        if 'MAX_SL_BAND_PCT' not in keys_content:
            # اضافه کردن MAX_SL_BAND_PCT
            new_keys_content = keys_content.rstrip().rstrip(',') + ", 'MAX_SL_BAND_PCT'"
            new_src = src.replace(m.group(0), f"TRADING_KEYS = {{{new_keys_content}}}")
            
            try:
                compile(new_src, 'settings.py', 'exec')
                if DEPLOY:
                    bak = f'settings.py.bak.{time.strftime("%Y%m%d_%H%M")}'
                    shutil.copy('settings.py', bak)
                    with open('settings.py', 'w', encoding='utf-8') as f:
                        f.write(new_src)
                    print('+ settings.py: اضافه شدن MAX_SL_BAND_PCT به TRADING_KEYS')
                    print(f'  + backup: {bak}')
                else:
                    print('+ settings.py: اضافه شدن MAX_SL_BAND_PCT به TRADING_KEYS (dry-run)')
                return True
            except SyntaxError as e:
                print(f'  + syntax error: {e}')
                return False
        else:
            print('- settings.py: MAX_SL_BAND_PCT از قبل در TRADING_KEYS موجود است')
            return False
    else:
        print('! TRADING_KEYS pattern not found in settings.py')
        return False


def patch_trader():
    """اضافه کردن کپ TP/SL در G-fillanchor (دو بخش)"""
    with open('trader.py', 'r', encoding='utf-8') as f:
        src = f.read()
    
    # الگوی مشترک برای هر دو بخش
    # بخش ۱ و ۲ هر دو این الگو را دارند:
    T_OLD = """                    _sl_new = _fill_px - _slm * _atr
                    _tp_new = _fill_px + _tpm * _atr
                    if 0 < _sl_new < _fill_px < _tp_new:"""
    
    T_NEW = """                    _sl_new = _fill_px - _slm * _atr
                    _tp_new = _fill_px + _tpm * _atr
                    # G-cap: حداکثر سود خالص 0.8% (TP≤1.08% ناخالص، SL≤0.54% ناخالص)
                    _tp_max = _fill_px * (1 + 1.08 / 100.0)
                    _sl_min = _fill_px * (1 - 0.54 / 100.0)
                    if _tp_new > _tp_max:
                        _tp_new = _tp_max
                    if _sl_new < _sl_min:
                        _sl_new = _sl_min
                    if 0 < _sl_new < _fill_px < _tp_new:"""
    
    if T_OLD not in src:
        print('! T_OLD pattern not found in trader.py')
        return False
    
    # شمارش تعداد occurrence
    count = src.count(T_OLD)
    print(f'  + تعداد occurrenceهای T_OLD: {count}')
    
    new_src = src.replace(T_OLD, T_NEW)
    
    try:
        compile(new_src, 'trader.py', 'exec')
        if DEPLOY:
            bak = f'trader.py.bak.{time.strftime("%Y%m%d_%H%M")}'
            shutil.copy('trader.py', bak)
            with open('trader.py', 'w', encoding='utf-8') as f:
                f.write(new_src)
            print(f'+ trader.py: اضافه شدن کپ TP/SL در {count} بخش G-fillanchor')
            print(f'  + backup: {bak}')
        else:
            print(f'+ trader.py: اضافه شدن کپ TP/SL در {count} بخش G-fillanchor (dry-run)')
        return True
    except SyntaxError as e:
        print(f'  + syntax error: {e}')
        return False


def update_sheet_descriptions():
    """به‌روزرسانی توضیحات در ستون توضیح شیت"""
    try:
        import sys
        sys.path.insert(0, '.')
        from settings import load_env
        import gspread
        
        e = load_env()
        gc = gspread.service_account(filename='service_account.json')
        sh = gc.open_by_key(e['SHEET_ID'])
        ws = sh.worksheet('تنظیمات')
        
        all_vals = ws.get_all_values()
        
        descriptions = {
            'PARTIAL_EXIT_TRIGGER': 'خروج جزئی در +0.5٪ (زیر TP cap 1.08٪ - هدف سود خالص 0.8٪)',
            'TRAIL_ACTIVATION_PCT': 'فعال‌سازی تریلینگ در +0.5٪ (زیر TP cap - سود خالص حداکثر 0.8٪)',
            'TRAIL_ATR_MULT': 'ضریب ATR تریلینگ = 0.2 (SL متحرک نزدیک به بازار)',
            'MAX_SL_BAND_PCT': 'سقف عرض استاپ = 5٪ (فیلتر نمادهای پرنوسان - هدف سود خالص 0.8٪)',
            'TP_ATR_MULT': 'ضریب TP = 3.0× ATR (با G-fillanchor به cap 1.08٪ محدود می‌شود)',
            'SL_ATR_MULT': 'ضریب SL = 1.5× ATR (با G-fillanchor به cap 0.54٪ محدود می‌شود)',
        }
        
        updated = 0
        for i, row in enumerate(all_vals):
            if not row:
                continue
            key = str(row[0]).strip()
            if key in descriptions:
                # ستون توضیح = ستون 3 (index 2)
                current_desc = str(row[2]).strip() if len(row) > 2 else ''
                new_desc = descriptions[key]
                if current_desc != new_desc:
                    # به‌روزرسانی ستون توضیح
                    ws.update_cell(i+1, 3, new_desc)
                    print(f'  ✓ توضیح {key}: به‌روزرسانی شد')
                    updated += 1
        
        print(f'  + {updated} توضیح به‌روزرسانی شد')
        return True
    except Exception as e:
        print(f'  + خطا در به‌روزرسانی توضیحات: {e}')
        return False


def main():
    print('=' * 70)
    print('fix_max_sl_band_and_tp_cap.py - رفع MAX_SL_BAND_PCT و کپ TP/SL')
    print(f'mode: {"DEPLOY" if DEPLOY else "DRY-RUN"}')
    print('=' * 70)
    
    print()
    print('=== بخش ۱: settings.py ===')
    s1 = patch_settings()
    
    print()
    print('=== بخش ۲: trader.py ===')
    s2 = patch_trader()
    
    if DEPLOY and (s1 or s2):
        print()
        print('=== بخش ۳: به‌روزرسانی توضیحات شیت ===')
        update_sheet_descriptions()
    
    print()
    print('=' * 70)
    if DEPLOY:
        print('Deploy complete.')
        print()
        print('تغییرات اعمال شده:')
        print('  1. MAX_SL_BAND_PCT اکنون از شیت خوانده می‌شود (5.0)')
        print('  2. کپ TP/SL در G-fillanchor اضافه شد:')
        print('     - TP ≤ 1.08% (سود خالص ≤ 0.8%)')
        print('     - SL ≤ 0.54% (ضرر خالص ≤ 0.82%)')
        print('  3. توضیحات در شیت به‌روزرسانی شد')
    else:
        print('dry-run OK. To deploy:')
        print('  cd ~/nobitex-usdt && venv/bin/python fix_max_sl_band_and_tp_cap.py --deploy')
    print('=' * 70)
    return 0


if __name__ == '__main__':
    sys.exit(main())
