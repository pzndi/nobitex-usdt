#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_double_sell.py - جلوگیری از فروش اضافی بعد از OCO

مشکل: وقتی OCO اجرا می‌شود (SL یا TP)، ربات هنوز پوزیشن را باز می‌بیند
و سفارش فروش اضافی (Market) ثبت می‌کند.

شاهد: MEW OCO SL اجرا شد (5089 فروخته)، سپس ربات 5114 MEW هم فروخت.

راه‌حل: در check_sl_tp، قبل از فروش، بررسی کن که آیا سکه‌ها در کیف پول هستند.
اگر موجودی فعال < 50% حجم پوزیشن، یعنی OCO اجرا شده و نباید فروش اضافی کرد.
"""
import os, sys, shutil, time

DEPLOY = '--deploy' in sys.argv

T_OLD = """def check_sl_tp(st, ws_t, client, dry, led, prices):
    \"\"\"اجرای خودکار حد ضرر/حد سود — اولویت بالاتر از سیگنال‌ها
    (خروج‌ها سقف روزانه را دور می‌زنند — مدیریت ریسک‌اند، نه معامله جدید)\"\"\"
    for sym in led['positions']:
        if prices.get(sym) is None:
            px = _public_price(sym)
            if px:
                prices[sym] = px
    exits = [(s, w, px) for s, w, px in find_sl_tp_exits(led['positions'], prices)
             if s not in led.get('pending_sells', set())]
    if not exits:
        return
    log.info('خروج‌های فعال: %s', '، '.join(f'{s} ({w})' for s, w, _ in exits))
    for sym, why, price in exits:
        exit_position(st, ws_t, client, sym, why, price, led)"""

T_NEW = """def check_sl_tp(st, ws_t, client, dry, led, prices):
    \"\"\"اجرای خودکار حد ضرر/حد سود — اولویت بالاتر از سیگنال‌ها
    (خروج‌ها سقف روزانه را دور می‌زنند — مدیریت ریسک‌اند، نه معامله جدید)\"\"\"
    for sym in led['positions']:
        if prices.get(sym) is None:
            px = _public_price(sym)
            if px:
                prices[sym] = px
    exits = [(s, w, px) for s, w, px in find_sl_tp_exits(led['positions'], prices)
             if s not in led.get('pending_sells', set())]
    if not exits:
        return
    log.info('خروج‌های فعال: %s', '، '.join(f'{s} ({w})' for s, w, _ in exits))
    for sym, why, price in exits:
        # G-fix: جلوگیری از فروش اضافی بعد از OCO
        # اگر موجودی فعال صفر یا بسیار کم است، یعنی OCO اجرا شده
        if client and not dry:
            _avail = currency_available(client, sym)
            _rv = led['positions'].get(sym, {}).get('real_volume', 0)
            if _avail is not None and _rv > 0 and _avail < _rv * 0.5:
                log.info('G-fix: خروج %s رد شد - OCO اجرا شده (فعال=%s از دفتر=%s) — جبران با reconcile',
                         sym, fmt_bal(_avail), fmt_bal(_rv))
                continue
        exit_position(st, ws_t, client, sym, why, price, led)"""


def main():
    print('=' * 70)
    print('fix_double_sell.py - جلوگیری از فروش اضافی بعد از OCO')
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
            print(f'+ trader.py: جلوگیری از فروش اضافی بعد از OCO')
            print(f'  + backup: {bak}')
        else:
            print('+ trader.py (dry-run): جلوگیری از فروش اضافی')
        return 0
    except SyntaxError as e:
        print(f'  + syntax error: {e}')
        return 1


if __name__ == '__main__':
    sys.exit(main())
