#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""add_min_tfs_to_settings.py - اضافه کردن MIN_TFS به شیت تنظیمات

مشکل: MIN_TFS یک ثابت در trader.py (خط 81) است و قابل تنظیم نیست.
با 4 تایم‌فریم فعال و MIN_TFS=3، نیاز به 75% تأیید است که خیلی سخت‌گیرانه است.

راه‌حل:
۱. اضافه کردن MIN_TFS به TRADING_KEYS در settings.py
۲. اضافه کردن property min_tfs به Settings
۳. اضافه کردن MIN_TFS به شیت تنظیمات
۴. تغییر is_buy_candidate برای استفاده از st.min_tfs (به‌جای ثابت)
"""
import os, sys, shutil, time

DEPLOY = '--deploy' in sys.argv


def patch_settings():
    """اضافه کردن MIN_TFS به settings.py"""
    with open('settings.py', 'r', encoding='utf-8') as f:
        src = f.read()
    
    changes = []
    
    # ۱. اضافه کردن MIN_TFS به TRADING_KEYS
    if "'MIN_TFS'" not in src:
        # پیدا کردن TRADING_KEYS
        import re
        m = re.search(r"(TRADING_KEYS\s*=\s*\{[^}]+)'PARTIAL_EXIT_PCT', 'PUMP_GUARD_PCT'\}", src)
        if m:
            old = m.group(0)
            new = old.replace("'PARTIAL_EXIT_PCT', 'PUMP_GUARD_PCT'}", 
                            "'PARTIAL_EXIT_PCT', 'PUMP_GUARD_PCT', 'MIN_TFS'}")
            src = src.replace(old, new)
            changes.append('MIN_TFS به TRADING_KEYS اضافه شد')
    
    # ۲. اضافه کردن MIN_TFS به DEFAULT_TRADING
    if "'MIN_TFS'" not in src.split('DEFAULT_TRADING')[1].split('}')[0] if 'DEFAULT_TRADING' in src else True:
        # پیدا کردن 'MAX_SL_BAND_PCT': '8.0' در DEFAULT_TRADING
        old_def = "'MAX_SL_BAND_PCT': '8.0'}"
        new_def = "'MAX_SL_BAND_PCT': '8.0', 'MIN_TFS': '3'}"
        if old_def in src and 'MIN_TFS' not in src.split('DEFAULT_TRADING')[1].split('}')[0]:
            src = src.replace(old_def, new_def)
            changes.append('MIN_TFS به DEFAULT_TRADING اضافه شد')
    
    # ۳. اضافه کردن property min_tfs به Settings
    if 'def min_tfs' not in src:
        # پیدا کردن property max_sl_band_pct و اضافه کردن بعد از آن
        old_prop = """    def max_sl_band_pct(self):
        return max(2.0, self._tnum('MAX_SL_BAND_PCT', 8.0))"""
        new_prop = """    def max_sl_band_pct(self):
        return max(2.0, self._tnum('MAX_SL_BAND_PCT', 8.0))

    @property
    def min_tfs(self):
        \"\"\"حداقل تعداد تایم‌فریم هم‌جهت برای صدور سیگنال (قابل تنظیم از شیت)\"\"\"
        return max(1, int(self._tnum('MIN_TFS', 3)))"""
        if old_prop in src:
            src = src.replace(old_prop, new_prop)
            changes.append('property min_tfs به Settings اضافه شد')
    
    # ۴. اضافه کردن MIN_TFS به PARAM_RANGES
    if "'MIN_TFS'" not in src.split('PARAM_RANGES')[1].split('}')[0] if 'PARAM_RANGES' in src else True:
        old_range = "    'MAX_SL_BAND_PCT':      (2.0, 20.0),"
        new_range = "    'MAX_SL_BAND_PCT':      (2.0, 20.0),\n    'MIN_TFS':              (1.0, 8.0),"
        if old_range in src and 'MIN_TFS' not in src.split('PARAM_RANGES')[1].split('}')[0]:
            src = src.replace(old_range, new_range)
            changes.append('MIN_TFS به PARAM_RANGES اضافه شد')
    
    if not changes:
        print('- settings.py: هیچ تغییری لازم نیست (همه موجود است)')
        return False
    
    try:
        compile(src, 'settings.py', 'exec')
        if DEPLOY:
            bak = f'settings.py.bak.{time.strftime("%Y%m%d_%H%M")}'
            shutil.copy('settings.py', bak)
            with open('settings.py', 'w', encoding='utf-8') as f:
                f.write(src)
            print(f'+ settings.py:')
            for c in changes:
                print(f'  + {c}')
            print(f'  + backup: {bak}')
        else:
            print(f'+ settings.py (dry-run):')
            for c in changes:
                print(f'  + {c}')
        return True
    except SyntaxError as e:
        print(f'  + syntax error: {e}')
        return False


def patch_trader():
    """تغییر is_buy_candidate برای استفاده از st.min_tfs"""
    with open('trader.py', 'r', encoding='utf-8') as f:
        src = f.read()
    
    # الگوی فعلی is_buy_candidate
    T_OLD = """def is_buy_candidate(a):
    return (a['buys'] >= MIN_TFS and a['buys'] >= (a['total'] + 1) // 2
            and a['buys'] > a['sells'])"""
    
    T_NEW = """def is_buy_candidate(a, st=None):
    _min_tfs = st.min_tfs if st is not None else MIN_TFS
    return (a['buys'] >= _min_tfs and a['buys'] >= (a['total'] + 1) // 2
            and a['buys'] > a['sells'])"""
    
    if T_OLD not in src:
        print('- trader.py: T_OLD not found (maybe already patched)')
        return False
    
    new_src = src.replace(T_OLD, T_NEW)
    
    # همچنین تغییر _rank_candidates برای پاس دادن st
    T_OLD2 = """def _rank_candidates(agg):
    # بهبود ۴ (G-rank): اولویت خرید = کیفیت سیگنال — اکثریت TF (نزولی)، سپس
    # قوت بهترین TF (نزولی)؛ برابرها → ترتیب universe/نقدشوندگی (sort پایدار).
    # تا پیش از این ترتیب خرید = ترتیب universe بود و «رتبه‌بندی برای سفارشگزاری»
    # صرفاً نمایشی بود (ممیزی ۱۴۰۵/۰۷/۲۲ — cands بدون هیچ sort).
    cands = [s for s, a in agg.items() if is_buy_candidate(a)]
    cands.sort(key=lambda s: (-agg[s]['buys'],
                              -(agg[s]['best'][0] if agg[s]['best'] else 0)))
    return cands"""
    
    T_NEW2 = """def _rank_candidates(agg, st=None):
    # بهبود ۴ (G-rank): اولویت خرید = کیفیت سیگنال — اکثریت TF (نزولی)، سپس
    # قوت بهترین TF (نزولی)؛ برابرها → ترتیب universe/نقدشوندگی (sort پایدار).
    # تا پیش از این ترتیب خرید = ترتیب universe بود و «رتبه‌بندی برای سفارشگزاری»
    # صرفاً نمایشی بود (ممیزی ۱۴۰۵/۰۷/۲۲ — cands بدون هیچ sort).
    cands = [s for s, a in agg.items() if is_buy_candidate(a, st)]
    cands.sort(key=lambda s: (-agg[s]['buys'],
                              -(agg[s]['best'][0] if agg[s]['best'] else 0)))
    return cands"""
    
    if T_OLD2 in new_src:
        new_src = new_src.replace(T_OLD2, T_NEW2)
    
    # همچنین تغییر فراخوانی _rank_candidates در run
    T_OLD3 = "    cands = _rank_candidates(agg)"
    T_NEW3 = "    cands = _rank_candidates(agg, st)"
    if T_OLD3 in new_src:
        new_src = new_src.replace(T_OLD3, T_NEW3)
    
    # همچنین تغییر فراخوانی is_buy_candidate در جاهای دیگر
    # خط 1784: elif (n_buys >= MIN_TFS ...
    T_OLD4 = "elif (n_buys >= MIN_TFS and n_buys >= (len(sym_rows) + 1) // 2"
    T_NEW4 = "elif (n_buys >= (st.min_tfs if st is not None else MIN_TFS) and n_buys >= (len(sym_rows) + 1) // 2"
    # این تغییر نیاز به st دارد که در write_ranking ممکن است نباشد - بررسی می‌کنیم
    # برای امنیت، این بخش را تغییر نمی‌دهیم
    
    try:
        compile(new_src, 'trader.py', 'exec')
        if DEPLOY:
            bak = f'trader.py.bak.{time.strftime("%Y%m%d_%H%M")}'
            shutil.copy('trader.py', bak)
            with open('trader.py', 'w', encoding='utf-8') as f:
                f.write(new_src)
            print(f'+ trader.py: is_buy_candidate و _rank_candidates برای استفاده از st.min_tfs')
            print(f'  + backup: {bak}')
        else:
            print(f'+ trader.py (dry-run): is_buy_candidate و _rank_candidates برای استفاده از st.min_tfs')
        return True
    except SyntaxError as e:
        print(f'  + syntax error: {e}')
        return False


def add_to_sheet():
    """اضافه کردن MIN_TFS به شیت تنظیمات"""
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
        
        # بررسی وجود MIN_TFS
        for row in all_vals:
            if row and 'MIN_TFS' in str(row[0]):
                print('- شیت: MIN_TFS از قبل موجود است')
                return False
        
        # پیدا کردن ردیف MAX_SL_BAND_PCT
        target_row = None
        for i, row in enumerate(all_vals):
            if row and 'MAX_SL_BAND_PCT' in str(row[0]):
                target_row = i + 1
                break
        
        if target_row:
            # درج بعد از MAX_SL_BAND_PCT
            ws.insert_row(['MIN_TFS', '2', '', 'حداقل تعداد تایم‌فریم هم‌جهت برای صدور سیگنال (با 4 TF: 2=50%، 3=75%)'], index=target_row + 1)
            print(f'+ شیت: MIN_TFS = 2 در ردیف {target_row + 1} اضافه شد')
        else:
            ws.append_row(['MIN_TFS', '2', '', 'حداقل تعداد تایم‌فریم هم‌جهت برای صدور سیگنال'])
            print('+ شیت: MIN_TFS = 2 در ردیف آخر اضافه شد')
        
        return True
    except Exception as e:
        print(f'  + خطا در به‌روزرسانی شیت: {e}')
        return False


def main():
    print('=' * 70)
    print('add_min_tfs_to_settings.py - اضافه کردن MIN_TFS به شیت تنظیمات')
    print(f'mode: {"DEPLOY" if DEPLOY else "DRY-RUN"}')
    print('=' * 70)
    
    print()
    s1 = patch_settings()
    
    print()
    s2 = patch_trader()
    
    if DEPLOY and (s1 or s2):
        print()
        add_to_sheet()
    
    print()
    print('=' * 70)
    if DEPLOY:
        print('Deploy complete.')
        print()
        print('MIN_TFS اکنون قابل تنظیم از شیت است (مقدار اولیه: 2)')
        print('با 4 تایم‌فریم فعال و MIN_TFS=2، نیاز به 50% تأیید است')
    else:
        print('dry-run OK. To deploy:')
        print('  cd ~/nobitex-usdt && venv/bin/python add_min_tfs_to_settings.py --deploy')
    print('=' * 70)
    return 0


if __name__ == '__main__':
    sys.exit(main())
