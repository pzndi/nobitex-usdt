#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_scale_max_aggressive.py - Maximum aggressive G-scale entries
- Fib 0.236 -> 0.146 (extreme shallow)
- BB 1.0sigma -> 0.7sigma (extreme shallow)
- ATR fallback 0.5x -> 0.3x
- Hard caps: Scale1 max 1.5%, Scale2 max 3.0%
"""
import os, sys, shutil, time

DEPLOY = '--deploy' in sys.argv

T_OLD = """        # Level 1: Fibonacci 0.236 retracement (very shallow - aggressive)
        lookback = min(50, len(closes))
        swing_high = max(highs[-lookback:])
        swing_low = min(lows[-lookback:])
        fib_236 = swing_high - (swing_high - swing_low) * 0.236

        # Level 2: Bollinger lower band (1.0 sigma) or 0.5xATR (very shallow)
        bb_lo = _bb_lower_band(closes, 20, 1.0)
        if bb_lo is None or bb_lo <= 0:
            _atr_series = se_prepare_atr(c)
            _atr_val = _atr_series[-1] if _atr_series and _atr_series[-1] else None
            if _atr_val and _atr_val > 0:
                bb_lo = price - 0.5 * _atr_val  # very shallow fallback

        # Validate and fallback (0.2% and 0.5% pullback)
        _pull = _eff_pullback_pct(row, st) / 100.0
        price_fib = fib_236 if (fib_236 and 0 < fib_236 < price) else price * (1 - 0.002)
        price_deep = bb_lo if (bb_lo and 0 < bb_lo < price) else price * (1 - 0.005)

        # Ensure deep is below fib
        if price_deep >= price_fib:
            price_deep = price_fib * 0.99"""

T_NEW = """        # Level 1: Fibonacci 0.146 retracement (extreme shallow - max aggressive)
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
            price_deep = price_fib * 0.99"""

def main():
    print('=' * 70)
    print('fix_scale_max_aggressive.py - Maximum aggressive G-scale entries')
    print(f'mode: {"DEPLOY" if DEPLOY else "DRY-RUN (preview only)"}')
    print('=' * 70)

    with open('trader.py', 'r', encoding='utf-8') as f:
        trader_src = f.read()

    if T_OLD not in trader_src:
        print('! trader.py: T_OLD pattern not found - already patched?')
        return 1

    new_src = trader_src.replace(T_OLD, T_NEW)

    # Syntax check using builtin compile()
    try:
        compile(new_src, 'trader.py', 'exec')
        print('+ trader.py: Max aggressive G-scale (Fib 0.146, BB 0.7sigma, caps 1.5%/3%)')
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
        print('  (dry-run: candidate saved as trader_candidate.py)')

    print()
    print('=' * 70)
    if DEPLOY:
        print('Deploy complete.')
    else:
        print('dry-run OK. To deploy:')
        print('  cd ~/nobitex-usdt && venv/bin/python fix_scale_max_aggressive.py --deploy')
    print('=' * 70)
    return 0

if __name__ == '__main__':
    sys.exit(main())
