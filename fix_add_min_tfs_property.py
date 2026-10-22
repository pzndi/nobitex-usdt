#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_add_min_tfs_property.py - اضافه کردن property min_tfs به Settings"""
import os, sys, shutil, time

DEPLOY = '--deploy' in sys.argv

T_OLD = """    @property
    def max_sl_band_pct(self):
        \"\"\"G-bandcap: max SL band width (%). Reject entries with wider SL.\"\"\"
        return max(2.0, self._tnum('MAX_SL_BAND_PCT', 8.0))"""

T_NEW = """    @property
    def max_sl_band_pct(self):
        \"\"\"G-bandcap: max SL band width (%). Reject entries with wider SL.\"\"\"
        return max(2.0, self._tnum('MAX_SL_BAND_PCT', 8.0))

    @property
    def min_tfs(self):
        \"\"\"حداقل تعداد تایم‌فریم هم‌جهت برای صدور سیگنال (قابل تنظیم از شیت)\"\"\"
        return max(1, int(self._tnum('MIN_TFS', 3)))"""


def main():
    print('=' * 70)
    print('fix_add_min_tfs_property.py - اضافه کردن property min_tfs')
    print(f'mode: {"DEPLOY" if DEPLOY else "DRY-RUN"}')
    print('=' * 70)
    
    with open('settings.py', 'r', encoding='utf-8') as f:
        src = f.read()
    
    if T_OLD not in src:
        print('! T_OLD pattern not found')
        if 'def min_tfs' in src:
            print('  اما min_tfs از قبل موجود است')
        return 1
    
    if 'def min_tfs' in src:
        print('- min_tfs از قبل موجود است')
        return 0
    
    new_src = src.replace(T_OLD, T_NEW)
    
    try:
        compile(new_src, 'settings.py', 'exec')
        if DEPLOY:
            bak = f'settings.py.bak.{time.strftime("%Y%m%d_%H%M")}'
            shutil.copy('settings.py', bak)
            with open('settings.py', 'w', encoding='utf-8') as f:
                f.write(new_src)
            print(f'+ settings.py: property min_tfs اضافه شد')
            print(f'  + backup: {bak}')
        else:
            print('+ settings.py (dry-run): property min_tfs اضافه شد')
        return 0
    except SyntaxError as e:
        print(f'  + syntax error: {e}')
        return 1


if __name__ == '__main__':
    sys.exit(main())
