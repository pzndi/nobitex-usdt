#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_pullback_closer.py - کاهش pullback برای نزدیک‌تر شدن به بازار

مشکل: اکثر سفارشات خرید پس از ۳۰ دقیقه لغو می‌شوند (83% لغو).
نرخ پر شدن Scale 1/2: 17.3% - بسیار پایین.

علت: pullback زیاد (0.1% - 1.5%) باعث می‌شود سفارشات خیلی دور از بازار باشند.

راه‌حل: کاهش محدوده pullback به 0.05% - 0.5%
"""
import os, sys, shutil, time

DEPLOY = '--deploy' in sys.argv

T_OLD = """        MIN_VOL = 0.5   # نوسان کم → حداقل پولبک
        MAX_VOL = 5.0   # نوسان زیاد → حداکثر پولبک
        MIN_PB = 0.1    # حداقل پولبک (٪)
        MAX_PB = 1.5    # حداکثر پولبک (٪)"""

T_NEW = """        MIN_VOL = 0.5   # نوسان کم → حداقل پولبک
        MAX_VOL = 5.0   # نوسان زیاد → حداکثر پولبک
        MIN_PB = 0.05   # حداقل پولبک (٪) - نزدیک به بازار برای پر شدن سریع‌تر
        MAX_PB = 0.5    # حداکثر پولبک (٪) - حداکثر فاصله از بازار"""

# همچنین به‌روزرسانی docstring
T_OLD_2 = """    - مپینگ نوسان به pullback در محدوده [0.1%, 1.5%]:
      vol ≤ 0.5% → pullback = 0.1% (کم‌نوسان = ورود نزدیک)
      vol ≥ 5.0% → pullback = 1.5% (پرنوسان = ورود دورتر)"""

T_NEW_2 = """    - مپینگ نوسان به pullback در محدوده [0.05%, 0.5%]:
      vol ≤ 0.5% → pullback = 0.05% (کم‌نوسان = ورود نزدیک)
      vol ≥ 5.0% → pullback = 0.5% (پرنوسان = ورود دورتر)"""


def main():
    print('=' * 70)
    print('fix_pullback_closer.py - کاهش pullback برای نزدیک‌تر شدن به بازار')
    print(f'mode: {"DEPLOY" if DEPLOY else "DRY-RUN"}')
    print('=' * 70)
    
    with open('trader.py', 'r', encoding='utf-8') as f:
        src = f.read()
    
    patches = []
    
    if T_OLD in src:
        src = src.replace(T_OLD, T_NEW)
        patches.append('محدوده pullback: 0.1-1.5% → 0.05-0.5%')
    
    if T_OLD_2 in src:
        src = src.replace(T_OLD_2, T_NEW_2)
        patches.append('docstring به‌روزرسانی شد')
    
    if not patches:
        print('! هیچ پچی پیدا نشد')
        return 1
    
    try:
        compile(src, 'trader.py', 'exec')
        if DEPLOY:
            bak = f'trader.py.bak.{time.strftime("%Y%m%d_%H%M")}'
            shutil.copy('trader.py', bak)
            with open('trader.py', 'w', encoding='utf-8') as f:
                f.write(src)
            print(f'+ trader.py: {len(patches)} patches')
            for p in patches:
                print(f'  + {p}')
            print(f'  + backup: {bak}')
        else:
            print(f'+ trader.py (dry-run): {len(patches)} patches')
            for p in patches:
                print(f'  + {p}')
        return 0
    except SyntaxError as e:
        print(f'  + syntax error: {e}')
        return 1


if __name__ == '__main__':
    sys.exit(main())
