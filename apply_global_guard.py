#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""apply_global_guard.py — گارد G-global + G-premium + G-mark-dev"""
import os, sys, shutil, py_compile, time

DEPLOY = '--deploy' in sys.argv

T1_OLD = """RISK_TARGET_USDT = 0.50  # گزینهٔ الف (G-volsize): سقف ریسک دلاری هر معامله — قابل ارتقا به کلید شیت
MAX_SL_BAND_PCT = 8.0    # گزینهٔ ب (G-bandcap): سقف عرض استاپ ٪ — فیلتر دُم پرنوسان"""

T1_NEW = """RISK_TARGET_USDT = 0.50  # گزینهٔ الف (G-volsize): سقف ریسک دلاری هر معامله — قابل ارتقا به کلید شیت
MAX_SL_BAND_PCT = 8.0    # گزینهٔ ب (G-bandcap): سقف عرض استاپ ٪ — فیلتر دُم پرنوسان
MAX_LOCAL_PREMIUM_PCT = 10.0   # G-premium: سقف پریمیوم محلی/جهانی
MAX_MARK_DEVIATION_PCT = 2.0   # G-mark-dev: سقف فاصله قیمت محلی از جهانی
_MARK_CACHE = {}               # کش موقت قیمت‌های mark برای هر چرخه


def _public_mark(sym):
    if sym in _MARK_CACHE:
        return _MARK_CACHE[sym]
    try:
        pair = f'{sym.lower()}-usdt'
        r = requests.post('https://apiv2.nobitex.ir/market/stats',
                          json={'stats': pair},
                          headers={'User-Agent': 'TraderBot/NobitexSheetBot-2.0'},
                          timeout=15)
        st_ = (r.json().get('stats') or {}).get(pair) or {}
        mk = float(st_.get('mark') or 0)
        val = mk if mk > 0 else None
        _MARK_CACHE[sym] = val
        return val
    except Exception:
        _MARK_CACHE[sym] = None
        return None


def clear_mark_cache():
    _MARK_CACHE.clear()"""

T2_OLD = """        # گزینهٔ ب (G-bandcap): سقف عرض استاپ — رد دُم پرنوسان (STRK 8.8٪،
        # WAL 11.1٪ → رد؛ BAT 6.3٪ → عبور با سایزِ کاهش‌یافته از گزینهٔ الف)
        _w_pct = _sl_width_pct(row, st)
        if _w_pct is not None and _w_pct > MAX_SL_BAND_PCT:
            log.info('skip buy %s: SL band %.1f%% > %.1f%% (high-volatility tail)',
                     sym, _w_pct, MAX_SL_BAND_PCT)
            continue"""

T2_NEW = """        # گزینهٔ ب (G-bandcap): سقف عرض استاپ — رد دُم پرنوسان (STRK 8.8٪،
        # WAL 11.1٪ → رد؛ BAT 6.3٪ → عبور با سایزِ کاهش‌یافته از گزینهٔ الف)
        _w_pct = _sl_width_pct(row, st)
        if _w_pct is not None and _w_pct > MAX_SL_BAND_PCT:
            log.info('skip buy %s: SL band %.1f%% > %.1f%% (high-volatility tail)',
                     sym, _w_pct, MAX_SL_BAND_PCT)
            continue
        # G-global: فقط نمادهایی که داده جهانی دارند (mark > 0)
        _mark_px = _public_mark(sym)
        if not _mark_px or _mark_px <= 0:
            log.info('skip buy %s: no global mark price (no global data)', sym)
            continue
        # G-premium: رد اگر پریمیوم محلی/جهانی > 10٪ (ریسک تومانی)
        _prem = (p / _mark_px - 1) * 100
        if _prem > MAX_LOCAL_PREMIUM_PCT:
            log.info('skip buy %s: local premium %.1f%% > %.1f%% (high toman premium)',
                     sym, _prem, MAX_LOCAL_PREMIUM_PCT)
            continue
        # G-mark-dev: رد اگر قیمت محلی بیش از ۲٪ بالاتر از جهانی (پامپ محلی)
        _dev = (p - _mark_px) / _mark_px * 100
        if _dev > MAX_MARK_DEVIATION_PCT:
            log.info('skip buy %s: local price %.1f%% above global mark (pump without global backing)',
                     sym, _dev)
            continue"""

S_OLD = """def run_signals(sh, st, state):
    symbols = state.get('universe') or []
    if not symbols:
        return False"""

S_NEW = """def run_signals(sh, st, state):
    symbols = state.get('universe') or []
    if not symbols:
        return False
    trader.clear_mark_cache()  # G-global: refresh mark cache each cycle"""

CHANGES = {
    'trader.py': [(T1_OLD, T1_NEW, 'ثوابت و توابع G-global'),
                  (T2_OLD, T2_NEW, 'گاردهای G-global + G-premium + G-mark-dev')],
    'scheduler.py': [(S_OLD, S_NEW, 'clear_mark_cache در run_signals')],
}


def main():
    os.chdir(os.path.expanduser('~/nobitex-usdt'))
    print('=' * 72)
    print('apply_global_guard.py — گارد داده جهانی نوبیتکس')
    print('mode: DEPLOY' if DEPLOY else 'mode: DRY-RUN (preview only)')
    print('=' * 72)

    all_ok = True
    applied = []

    for fname, patches in CHANGES.items():
        if not os.path.exists(fname):
            print('X %s not found' % fname)
            all_ok = False
            continue

        src = open(fname, encoding='utf-8').read()
        cand = src
        file_ok = True

        for old, new, desc in patches:
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
            continue

        cand_name = fname.replace('.py', '_candidate.py')
        with open(cand_name, 'w', encoding='utf-8') as f:
            f.write(cand)

        try:
            py_compile.compile(cand_name, doraise=True)
            print('  + py_compile: OK')
        except py_compile.PyCompileError as e:
            print('  X py_compile FAILED: %s' % e)
            all_ok = False
            continue

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
    if not all_ok:
        print('X some patches failed')
        sys.exit(1)

    print('+ %d patches ready' % len(applied))
    if DEPLOY:
        print('Deploy complete. Monitor:')
        print('  tail -f ~/nobitex-usdt/update.log | grep -E "skip buy|mark|premium"')
    else:
        print('dry-run OK. To deploy:')
        print('  cd ~/nobitex-usdt && venv/bin/python apply_global_guard.py --deploy')
    print('=' * 72)


if __name__ == '__main__':
    main()
