#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""apply_bandcap_setting.py - Add MAX_SL_BAND_PCT to settings"""
import os, sys, shutil, py_compile, time

DEPLOY = '--deploy' in sys.argv

# ═══════════════════════════════════════════════════════════════
# پچ ۱: settings.py — افزودن MAX_SL_BAND_PCT
# ═══════════════════════════════════════════════════════════════
S1_OLD = "                   'MAX_SL_MULT': '1.5', 'TREND_FILTER_ENABLED': 'بله', 'TRAIL_ATR_MULT': '0.5', 'PARTIAL_EXIT_PCT': '50', 'PARTIAL_EXIT_TRIGGER': '2.0', 'ENTRY_MODE': 'limit_pullback', 'PULLBACK_PCT': '1.0', 'POSITION_TIMEOUT_H': '48', 'POSITION_TIMEOUT_MIN_PCT': '0'}"
S1_NEW = "                   'MAX_SL_MULT': '1.5', 'TREND_FILTER_ENABLED': 'بله', 'TRAIL_ATR_MULT': '0.5', 'PARTIAL_EXIT_PCT': '50', 'PARTIAL_EXIT_TRIGGER': '2.0', 'ENTRY_MODE': 'limit_pullback', 'PULLBACK_PCT': '1.0', 'POSITION_TIMEOUT_H': '48', 'POSITION_TIMEOUT_MIN_PCT': '0', 'MAX_SL_BAND_PCT': '8.0'}"

S2_OLD = "    'PUMP_GUARD_PCT':       (0.0, 50.0),"
S2_NEW = "    'PUMP_GUARD_PCT':       (0.0, 50.0),\n    'MAX_SL_BAND_PCT':      (2.0, 20.0),"

S3_OLD = """    @property
    def max_sl_mult(self):
        \"\"\"G-maxsl: ceiling on SL multiplier from backtest edges.
        Backtest may suggest x2.5 for high-volatility new symbols;
        this caps it (e.g. 1.5) to limit worst-case loss per trade.
        0 = no cap (backtest wins).\"\"\"
        return max(0.0, self._tnum('MAX_SL_MULT', 1.5))"""
S3_NEW = """    @property
    def max_sl_mult(self):
        \"\"\"G-maxsl: ceiling on SL multiplier from backtest edges.
        Backtest may suggest x2.5 for high-volatility new symbols;
        this caps it (e.g. 1.5) to limit worst-case loss per trade.
        0 = no cap (backtest wins).\"\"\"
        return max(0.0, self._tnum('MAX_SL_MULT', 1.5))

    @property
    def max_sl_band_pct(self):
        \"\"\"G-bandcap: max SL band width (%). Reject entries with wider SL.\"\"\"
        return max(2.0, self._tnum('MAX_SL_BAND_PCT', 8.0))"""

# ═══════════════════════════════════════════════════════════════
# پچ ۲: trader.py — استفاده از مقدار شیت به جای ثابت
# ═══════════════════════════════════════════════════════════════
T1_OLD = """        # گزینهٔ ب (G-bandcap): سقف عرض استاپ — رد دُم پرنوسان (STRK 8.8٪،
        # WAL 11.1٪ → رد؛ BAT 6.3٪ → عبور با سایزِ کاهش‌یافته از گزینهٔ الف)
        _w_pct = _sl_width_pct(row, st)
        if _w_pct is not None and _w_pct > MAX_SL_BAND_PCT:
            log.info('skip buy %s: SL band %.1f%% > %.1f%% (high-volatility tail)',
                     sym, _w_pct, MAX_SL_BAND_PCT)
            continue"""

T1_NEW = """        # گزینهٔ ب (G-bandcap): سقف عرض استاپ — رد دُم پرنوسان (STRK 8.8٪،
        # WAL 11.1٪ → رد؛ BAT 6.3٪ → عبور با سایزِ کاهش‌یافته از گزینهٔ الف)
        _max_band = getattr(st, 'max_sl_band_pct', MAX_SL_BAND_PCT)
        _w_pct = _sl_width_pct(row, st)
        if _w_pct is not None and _w_pct > _max_band:
            log.info('skip buy %s: SL band %.1f%% > %.1f%% (high-volatility tail)',
                     sym, _w_pct, _max_band)
            continue"""

CHANGES = {
    'settings.py': [(S1_OLD, S1_NEW, 'add MAX_SL_BAND_PCT to DEFAULTS'),
                    (S2_OLD, S2_NEW, 'add MAX_SL_BAND_PCT to PARAM_RANGES'),
                    (S3_OLD, S3_NEW, 'add max_sl_band_pct property')],
    'trader.py': [(T1_OLD, T1_NEW, 'use st.max_sl_band_pct instead of constant')]
}


def main():
    os.chdir(os.path.expanduser('~/nobitex-usdt'))
    print('=' * 72)
    print('apply_bandcap_setting.py - Add MAX_SL_BAND_PCT to settings')
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
            shutil.move(cand_name, fname)
            print('  + deployed: %s' % fname)
        else:
            print('  (dry-run: %s)' % cand_name)
    print()
    if not all_ok:
        print('X some patches failed')
        sys.exit(1)
    print('+ %d patches ready' % len(applied))
    if DEPLOY:
        print('Deploy complete. Add MAX_SL_BAND_PCT=8.0 to sheet.')
    else:
        print('dry-run OK. To deploy:')
        print('  cd ~/nobitex-usdt && venv/bin/python apply_bandcap_setting.py --deploy')
    print('=' * 72)

if __name__ == '__main__':
    main()
