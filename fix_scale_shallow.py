#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_scale_shallow.py - Make G-scale entries shallower for higher fill rate"""
import os, sys, shutil, py_compile, time

DEPLOY = '--deploy' in sys.argv

T_OLD = """def _calc_scaled_entries(sym, price, row, st):
    \"\"\"G-scale: Calculate 2 entry prices for scaling in.
    Returns (price_fib, price_deep) or (None, None) if data unavailable.\"\"\"
    try:
        c = fetch_candles(sym + 'USDT', '60', 100)
        if not c or len(c.get('c', [])) < 25:
            return None, None
        closes, highs, lows = c['c'], c['h'], c['l']

        # Level 1: Fibonacci 0.618 retracement
        lookback = min(50, len(closes))
        swing_high = max(highs[-lookback:])
        swing_low = min(lows[-lookback:])
        fib_618 = swing_high - (swing_high - swing_low) * 0.618

        # Level 2: Bollinger lower band or 2xATR
        bb_lo = _bb_lower_band(closes, 20, 2.0)
        if bb_lo is None or bb_lo <= 0:
            _atr_series = se_prepare_atr(c)
            _atr_val = _atr_series[-1] if _atr_series and _atr_series[-1] else None
            if _atr_val and _atr_val > 0:
                bb_lo = price - 2 * _atr_val

        # Validate and fallback
        _pull = _eff_pullback_pct(row, st) / 100.0
        price_fib = fib_618 if (fib_618 and 0 < fib_618 < price) else price * (1 - _pull)
        price_deep = bb_lo if (bb_lo and 0 < bb_lo < price) else price * (1 - _pull * 2)

        # Ensure deep is below fib
        if price_deep >= price_fib:
            price_deep = price_fib * 0.98

        return price_fib, price_deep
    except Exception:
        return None, None"""

T_NEW = """def _calc_scaled_entries(sym, price, row, st):
    \"\"\"G-scale: Calculate 2 shallow entry prices for scaling in.
    Uses Fib 0.382 and BB 1.5sigma for higher fill rate.\"\"\"
    try:
        c = fetch_candles(sym + 'USDT', '60', 100)
        if not c or len(c.get('c', [])) < 25:
            return None, None
        closes, highs, lows = c['c'], c['h'], c['l']

        # Level 1: Fibonacci 0.382 retracement (shallow)
        lookback = min(50, len(closes))
        swing_high = max(highs[-lookback:])
        swing_low = min(lows[-lookback:])
        fib_382 = swing_high - (swing_high - swing_low) * 0.382

        # Level 2: Bollinger lower band (1.5 sigma) or 1xATR (shallow)
        bb_lo = _bb_lower_band(closes, 20, 1.5)
        if bb_lo is None or bb_lo <= 0:
            _atr_series = se_prepare_atr(c)
            _atr_val = _atr_series[-1] if _atr_series and _atr_series[-1] else None
            if _atr_val and _atr_val > 0:
                bb_lo = price - 1.0 * _atr_val  # shallow fallback

        # Validate and fallback (half and full pullback)
        _pull = _eff_pullback_pct(row, st) / 100.0
        price_fib = fib_382 if (fib_382 and 0 < fib_382 < price) else price * (1 - _pull * 0.5)
        price_deep = bb_lo if (bb_lo and 0 < bb_lo < price) else price * (1 - _pull)

        # Ensure deep is below fib
        if price_deep >= price_fib:
            price_deep = price_fib * 0.99

        return price_fib, price_deep
    except Exception:
        return None, None"""

CHANGES = {
    'trader.py': [(T_OLD, T_NEW, 'Make G-scale entries shallower (Fib 0.382, BB 1.5sigma, ATR 1x)')]
}

def main():
    os.chdir(os.path.expanduser('~/nobitex-usdt'))
    print('=' * 72)
    print('fix_scale_shallow.py - Shallow G-scale entries')
    print('mode: DEPLOY' if DEPLOY else 'mode: DRY-RUN (preview only)')
    print('=' * 72)
    all_ok = True
    applied = []
    fname = 'trader.py'
    if not os.path.exists(fname):
        print('X %s not found' % fname)
        sys.exit(1)
    src = open(fname, encoding='utf-8').read()
    cand = src
    file_ok = True
    for old, new, desc in CHANGES[fname]:
        if old in cand:
            cand = cand.replace(old, new, 1)
            print('+ %s: %s' % (fname, desc))
            applied.append((fname, desc))
        else:
            print('X %s: pattern not found: %s' % (fname, desc))
            file_ok = False
            all_ok = False
    if not file_ok:
        sys.exit(1)
    cand_name = 'trader_candidate.py'
    with open(cand_name, 'w', encoding='utf-8') as f:
        f.write(cand)
    try:
        py_compile.compile(cand_name, doraise=True)
        print('  + py_compile: OK')
    except py_compile.PyCompileError as e:
        print('  X py_compile FAILED: %s' % e)
        sys.exit(1)
    if DEPLOY:
        bak = '%s.bak.%s' % (fname, time.strftime('%Y%m%d_%H%M'))
        shutil.copy2(fname, bak)
        print('  + backup: %s' % bak)
        shutil.move(cand_name, fname)
        print('  + deployed: %s' % fname)
    else:
        print('  (dry-run: candidate saved as %s)' % cand_name)
    print()
    print('=' * 72)
    print('+ %d patches ready' % len(applied))
    if DEPLOY:
        print('Deploy complete. Next buy cycle will use shallower entries.')
    else:
        print('dry-run OK. To deploy:')
        print('  cd ~/nobitex-usdt && venv/bin/python fix_scale_shallow.py --deploy')
    print('=' * 72)

if __name__ == '__main__':
    main()
