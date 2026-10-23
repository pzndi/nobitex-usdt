#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_scale_v2_volatility.py - بازنویسی G-scale بر اساس نوسان ۴ ساعت اخیر

تغییرات:
- محاسبه نوسان: max(highs) - min(lows) در ۴ کندل ۱ ساعته اخیر
- مپینگ نوسان به pullback در محدوده [0.1%, 1.5%]
  vol ≤ 0.5% → 0.1% pullback (کم‌نوسان = ورود نزدیک)
  vol ≥ 5.0% → 1.5% pullback (پرنوسان = ورود دورتر)
  بین این دو → خطی
- Scale 1/2 = price * (1 - pullback/100)
- Scale 2/2 = Scale 1/2 * 0.999 (همیشه 0.1% پایین‌تر از Scale 1/2)
"""
import os, sys, shutil, time

DEPLOY = '--deploy' in sys.argv

T_OLD = """def _calc_scaled_entries(sym, price, row, st):
    \"\"\"G-scale: Calculate 2 shallow entry prices for scaling in.
    Uses Fib 0.382 and BB 1.5sigma for higher fill rate.\"\"\"
    try:
        c = fetch_candles(sym + 'USDT', '60', 100)
        if not c or len(c.get('c', [])) < 25:
            return None, None
        closes, highs, lows = c['c'], c['h'], c['l']

        # Level 1: Fibonacci 0.146 retracement (extreme shallow - max aggressive)
        lookback = min(50, len(closes))
        swing_high = max(highs[-lookback:])
        swing_low = min(lows[-lookback:])
        fib_146 = swing_high - (swing_high - swing_low) * 0.146

        # Level 2: Bollinger lower band (0.7 sigma) or 0.3xATR (extreme shallow)
        bb_lo = _bb_lower_band(closes, 20, 0.7)
        if bb_lo is None or bb_lo <= 0:
            _atr_series = se_prepare_atr(c)
            _atr_val = _atr_series[-1] if _atr_series and _atr_series[-1] else None
            if _atr_val and _atr_val > 0:
                bb_lo = price - 0.3 * _atr_val  # extreme shallow fallback

        # Validate and fallback (0.2% and 0.5% pullback)
        _pull = _eff_pullback_pct(row, st) / 100.0
        price_fib = fib_146 if (fib_146 and 0 < fib_146 < price) else price * (1 - 0.002)
        price_deep = bb_lo if (bb_lo and 0 < bb_lo < price) else price * (1 - 0.005)

        # Hard caps - maximum aggressiveness
        # Scale 1/2: max 1.5% from price (otherwise too aggressive)
        # Scale 2/2: max 3.0% from price (otherwise too aggressive)
        MAX_SCALE1_PCT = 0.015
        MAX_SCALE2_PCT = 0.030
        min_scale1 = price * (1 - MAX_SCALE1_PCT)
        min_scale2 = price * (1 - MAX_SCALE2_PCT)
        if price_fib < min_scale1:
            price_fib = min_scale1
        if price_deep < min_scale2:
            price_deep = min_scale2

        # Ensure deep is below fib
        if price_deep >= price_fib:
            price_deep = price_fib * 0.99

        return price_fib, price_deep
    except Exception:
        return None, None"""

T_NEW = """def _calc_scaled_entries(sym, price, row, st):
    \"\"\"G-scale v2: نوسان-محور - محاسبه ۲ قیمت ورود بر اساس نوسان ۴ ساعت اخیر
    - نوسان = (max(highs[-4:]) - min(lows[-4:])) / price × 100
    - مپینگ نوسان به pullback در محدوده [0.1%, 1.5%]:
      vol ≤ 0.5% → pullback = 0.1% (کم‌نوسان = ورود نزدیک)
      vol ≥ 5.0% → pullback = 1.5% (پرنوسان = ورود دورتر)
      بین این دو → خطی
    - Scale 1/2 = price * (1 - pullback/100)
    - Scale 2/2 = Scale 1/2 * 0.999 (همیشه 0.1% پایین‌تر از Scale 1/2)
    \"\"\"
    try:
        c = fetch_candles(sym + 'USDT', '60', 10)
        if not c or len(c.get('c', [])) < 5:
            return None, None
        highs, lows = c['h'], c['l']

        # محاسبه نوسان در ۴ ساعت اخیر (۴ کندل ۱ ساعته)
        lookback = min(4, len(highs))
        max_high_4h = max(highs[-lookback:])
        min_low_4h = min(lows[-lookback:])
        volatility_pct = (max_high_4h - min_low_4h) / price * 100

        # مپینگ نوسان به pullback در محدوده [0.1%, 1.5%]
        MIN_VOL = 0.5   # نوسان کم → حداقل پولبک
        MAX_VOL = 5.0   # نوسان زیاد → حداکثر پولبک
        MIN_PB = 0.1    # حداقل پولبک (٪)
        MAX_PB = 1.5    # حداکثر پولبک (٪)
        if volatility_pct <= MIN_VOL:
            pullback_pct = MIN_PB
        elif volatility_pct >= MAX_VOL:
            pullback_pct = MAX_PB
        else:
            ratio = (volatility_pct - MIN_VOL) / (MAX_VOL - MIN_VOL)
            pullback_pct = MIN_PB + ratio * (MAX_PB - MIN_PB)

        # Scale 1/2: قیمت ورود اول
        price_1 = price * (1 - pullback_pct / 100.0)

        # Scale 2/2: همیشه 0.1% پایین‌تر از Scale 1/2
        price_2 = price_1 * 0.999

        return price_1, price_2
    except Exception:
        return None, None"""


def main():
    print('=' * 70)
    print('fix_scale_v2_volatility.py - بازنویسی G-scale بر اساس نوسان ۴ ساعت')
    print(f'mode: {"DEPLOY" if DEPLOY else "DRY-RUN"}')
    print('=' * 70)
    
    with open('trader.py', 'r', encoding='utf-8') as f:
        trader_src = f.read()
    
    if T_OLD not in trader_src:
        print('! T_OLD pattern not found - already patched?')
        return 1
    
    new_src = trader_src.replace(T_OLD, T_NEW)
    
    try:
        compile(new_src, 'trader.py', 'exec')
        print('+ trader.py: G-scale v2 نوسان-محور')
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
    else:
        print('dry-run OK. To deploy:')
        print('  cd ~/nobitex-usdt && venv/bin/python fix_scale_v2_volatility.py --deploy')
    print('=' * 70)
    return 0

if __name__ == '__main__':
    sys.exit(main())
