#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_btc_trend_bug.py - رفع باگ در _btc_trend_bearish

مشکل: شرط if not c or len(c.get('c') or ()) همیشه True است وقتی داده موجود است.
این یعنی تابع همیشه False برمی‌گرداند و فیلتر روند هیچ‌وقت فعال نمی‌شود.

علت: شرط اشتباه است - بررسی می‌کند که candleها وجود دارند (True)،
نه اینکه کافی هستند. باید بررسی کند که ≥ 50 کندل وجود دارد.

راه‌حل: تغییر شرط به بررسی کافی بودن داده (≥ 50 کندل).
"""
import os, sys, shutil, time

DEPLOY = '--deploy' in sys.argv

T_OLD = """def _btc_trend_bearish():
    \"\"\"G-trend: True if BTC 4h SMA20 < SMA50 (bearish regime).
    One API call, cached by caller if needed.\"\"\"
    try:
        c = fetch_candles('BTCUSDT', '240', 100)
        if not c or len(c.get('c') or ()):
            return False
        closes = c['c']
        fa = sma(closes, 20)
        sl2 = sma(closes, 50)
        if fa[-1] is not None and sl2[-1] is not None:
            return fa[-1] < sl2[-1]
    except Exception:
        pass
    return False  # fail-open: if we can't check, don't block"""

T_NEW = """def _btc_trend_bearish():
    \"\"\"G-trend: True if BTC 4h SMA20 < SMA50 (bearish regime).
    One API call, cached by caller if needed.\"\"\"
    try:
        c = fetch_candles('BTCUSDT', '240', 100)
        if not c or not c.get('c') or len(c['c']) < 50:
            return False  # داده ناکافی - fail-open
        closes = c['c']
        fa = sma(closes, 20)
        sl2 = sma(closes, 50)
        if fa[-1] is not None and sl2[-1] is not None:
            return fa[-1] < sl2[-1]
    except Exception:
        pass
    return False  # fail-open: if we can't check, don't block"""


def main():
    print('=' * 70)
    print('fix_btc_trend_bug.py - رفع باگ در _btc_trend_bearish')
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
        print('+ trader.py: رفع باگ _btc_trend_bearish')
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
        print('  - قبل: if not c or len(c.get(\'c\') or ())')
        print('    وقتی داده موجود است، len > 0 = True، شرط True، return False')
        print('    یعنی تابع همیشه False برمی‌گرداند!')
        print('  - بعد: if not c or not c.get(\'c\') or len(c[\'c\']) < 50')
        print('    فقط اگر داده ناکافی باشد (< 50 کندل) return False')
        print('    در غیر این صورت، SMA20 و SMA50 محاسبه می‌شود')
    else:
        print('dry-run OK. To deploy:')
        print('  cd ~/nobitex-usdt && venv/bin/python fix_btc_trend_bug.py --deploy')
    print('=' * 70)
    return 0

if __name__ == '__main__':
    sys.exit(main())
