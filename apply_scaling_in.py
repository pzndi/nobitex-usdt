#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""apply_scaling_in.py - G-scale: 2-level scaling in (Fib 0.618 + BB/2xATR)"""
import os, sys, shutil, py_compile, time

DEPLOY = '--deploy' in sys.argv

# ─── پچ ۱: افزودن توابع کمکی قبل از buy_one ───
T1_OLD = """def buy_one(st, ws_t, client, dry, sym, a, price, led, coid=None):
    row = a['best'][1]
    tf, sl, tp = row[1], row[9], row[10]
    # گزینهٔ الف (G-volsize): vol-targeted sizing — cap-style
    _size = _eff_order_usdt(row, st)
    vol = math.floor((_size / price) * 1e8) / 1e8
    if vol <= 0:
        return
    amount = round(_size, 2)
    reason = f"رأی خرید {a['buys']}/{a['total']} تایم‌فریم" + _band_tag(st, row)"""

T1_NEW = """def _bb_lower_band(closes, period=20, std=2.0):
    \"\"\"G-scale: Bollinger lower band (pure python).\"\"\"
    n = len(closes)
    if n < period:
        return None
    slice_c = closes[-period:]
    mean = sum(slice_c) / period
    variance = sum((c - mean) ** 2 for c in slice_c) / period
    return mean - std * (variance ** 0.5)


def _calc_scaled_entries(sym, price, row, st):
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
        return None, None


def buy_one(st, ws_t, client, dry, sym, a, price, led, coid=None):
    row = a['best'][1]
    tf, sl, tp = row[1], row[9], row[10]
    # گزینهٔ الف (G-volsize): vol-targeted sizing — cap-style
    _size = _eff_order_usdt(row, st)
    # G-scale: Calculate 2 entry prices for scaling in
    _price1, _price2 = _calc_scaled_entries(sym, price, row, st)
    if _price1 is None:
        _pull = _eff_pullback_pct(row, st) / 100.0
        _price1 = price * (1 - _pull)
        _price2 = None
    # Split volume: 50% each
    _size1 = round(_size * 0.5, 2)
    _size2 = round(_size - _size1, 2) if _price2 else 0
    # Order 1 (Fib 0.618)
    vol = math.floor((_size1 / _price1) * 1e8) / 1e8
    if vol <= 0:
        return
    amount = round(_size1, 2)
    reason = f"رأی خرید {a['buys']}/{a['total']} تایم‌فریم | Scale 1/2 (Fib 0.618)" + _band_tag(st, row)"""

# ─── پچ ۲: اصلاح dry mode ───
T2_OLD = """    if dry:
        record_trade(ws_t, 'خرید', sym, tf, reason, fmt_price(price), vol, amount,
                     sl, tp, '—', ST_DRY, 'شبیه‌سازی — بدون ارسال به صرافی')
        led['dry_net_spent'] += amount
        p = led['positions'].setdefault(sym, {'volume': 0.0, 'sim_volume': 0.0, 'real_volume': 0.0, 'entry_price': None, 'sl': None, 'tp': None})
        p['volume'] += vol
        p['sim_volume'] = p.get('sim_volume', 0.0) + vol
        return"""

T2_NEW = """    if dry:
        record_trade(ws_t, 'خرید', sym, tf, reason, fmt_price(_price1), vol, amount,
                     sl, tp, '—', ST_DRY, 'شبیه‌سازی Scale 1/2 — بدون ارسال به صرافی')
        led['dry_net_spent'] += amount
        p = led['positions'].setdefault(sym, {'volume': 0.0, 'sim_volume': 0.0, 'real_volume': 0.0, 'entry_price': None, 'sl': None, 'tp': None})
        p['volume'] += vol
        p['sim_volume'] = p.get('sim_volume', 0.0) + vol
        if _price2 and _size2 > 0:
            vol2 = math.floor((_size2 / _price2) * 1e8) / 1e8
            if vol2 > 0:
                amount2 = round(_size2, 2)
                reason2 = f"رأی خرید {a['buys']}/{a['total']} تایم‌فریم | Scale 2/2 (BB/2xATR)" + _band_tag(st, row)
                record_trade(ws_t, 'خرید', sym, tf, reason2, fmt_price(_price2), vol2, amount2,
                             sl, tp, '—', ST_DRY, 'شبیه‌سازی Scale 2/2 — بدون ارسال به صرافی')
                led['dry_net_spent'] += amount2
                p['volume'] += vol2
                p['sim_volume'] = p.get('sim_volume', 0.0) + vol2
        return"""

# ─── پچ ۳: استفاده از قیمت محاسبه‌شده ───
T3_OLD = """    # G-entry: limit_pullback mode places limit at pullback price
    _is_market = (st.order_type == 'market' and st.entry_mode != 'limit_pullback')
    # بهبود ۳ (G-vpull): عمق پولبک volatility-based (نه ثابت شیت)
    _pull_pct = _eff_pullback_pct(row, st) if (not _is_market and row) else st.pullback_pct
    _limit_price = price
    if not _is_market and st.entry_mode == 'limit_pullback' and _pull_pct > 0:
        _limit_price = price * (1 - _pull_pct / 100.0)"""

T3_NEW = """    # G-entry: limit_pullback mode places limit at pullback price
    _is_market = (st.order_type == 'market' and st.entry_mode != 'limit_pullback')
    # G-scale: Use pre-calculated scaled entry price
    _limit_price = _price1"""

# ─── پچ ۴: افزودن سفارش دوم بعد از ثبت سفارش اول ───
T4_OLD = """        p['volume'] += vol
        p['real_volume'] = p.get('real_volume', 0.0) + vol
        if st.use_exchange_oco and st.order_type == 'market':"""

T4_NEW = """        p['volume'] += vol
        p['real_volume'] = p.get('real_volume', 0.0) + vol
        # G-scale: Place second order at deep pullback level
        if _price2 and _size2 > 0 and not _is_market:
            vol2 = math.floor((_size2 / _price2) * 1e8) / 1e8
            if vol2 > 0:
                amount2 = round(_size2, 2)
                reason2 = f"رأی خرید {a['buys']}/{a['total']} تایم‌فریم | Scale 2/2 (BB/2xATR)" + _band_tag(st, row)
                coid2 = (coid + '_s2') if coid else None
                code2, data2 = client.place_order('buy', sym, _price2, vol2, False, client_order_id=coid2)
                ok2 = code2 == 200 and isinstance(data2, dict) and data2.get('status') == 'ok'
                o2 = (data2.get('order') or {}) if isinstance(data2, dict) else {}
                oid2 = clean_oid(o2.get('id') if isinstance(o2, dict) else None or (data2.get('id') if isinstance(data2, dict) else ''))
                if ok2:
                    record_trade(ws_t, 'خرید', sym, tf, reason2, fmt_price(price), vol2, amount2,
                                 sl, tp, oid2, ST_PLACED, str(data2)[:80])
                    p2 = led['positions'].get(sym) or led['positions'].setdefault(sym, {'volume': 0.0, 'sim_volume': 0.0, 'real_volume': 0.0, 'entry_price': None, 'sl': None, 'tp': None})
                    p2['volume'] += vol2
                    p2['real_volume'] = p2.get('real_volume', 0.0) + vol2
                else:
                    log.error('ثبت سفارش دوم %s ناموفق: HTTP %s | %s', sym, code2, str(data2)[:150])
        if st.use_exchange_oco and st.order_type == 'market':"""

CHANGES = {
    'trader.py': [(T1_OLD, T1_NEW, 'add _calc_scaled_entries + modify buy_one setup'),
                  (T2_OLD, T2_NEW, 'modify dry mode for 2 orders'),
                  (T3_OLD, T3_NEW, 'use pre-calculated entry price'),
                  (T4_OLD, T4_NEW, 'add 2nd order placement after position tracking')]
}


def main():
    os.chdir(os.path.expanduser('~/nobitex-usdt'))
    print('=' * 72)
    print('apply_scaling_in.py - G-scale: 2-level scaling in')
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
            print('  expected: %s...' % old[:80])
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
        print('Deploy complete. Monitor next buy cycle.')
    else:
        print('dry-run OK. To deploy:')
        print('  cd ~/nobitex-usdt && venv/bin/python apply_scaling_in.py --deploy')
    print('=' * 72)


if __name__ == '__main__':
    main()
