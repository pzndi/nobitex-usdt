#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_coid2_underscore.py - رفع باگ ParseError در coid2 برای نمادهای با underscore

مشکل: در buy_one خط 1112، coid2 با sym.lower() ساخته می‌شود که اگر نماد
شامل _ باشد (مثل 1M_PEPE)، نوبیتکس آن را رد می‌کند (ParseError).

در خط 2990 (run)، coid با replace("_", "") ساخته می‌شود اما coid2 نه.

راه‌حل: اضافه کردن replace("_", "") به coid2.
"""
import os, sys, shutil, time

DEPLOY = '--deploy' in sys.argv

T_OLD = """                coid2 = f"nbx-{sym.lower()}-{int(time.time())}\""""

T_NEW = """                coid2 = f"nbx-{sym.lower().replace('_', '')}-{int(time.time())}\""""


def main():
    print('=' * 70)
    print('fix_coid2_underscore.py - رفع باگ ParseError در coid2')
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
            print(f'+ trader.py: coid2 با replace("_", "")')
            print(f'  + backup: {bak}')
        else:
            print('+ trader.py (dry-run): coid2 با replace')
        return 0
    except SyntaxError as e:
        print(f'  + syntax error: {e}')
        return 1


if __name__ == '__main__':
    sys.exit(main())
