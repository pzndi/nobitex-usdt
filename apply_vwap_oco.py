#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""apply_vwap_oco.py - G-scale VWAP: Replace OCO with VWAP-based SL/TP on scale-in"""
import os, sys, shutil, py_compile, time

DEPLOY = '--deploy' in sys.argv

# پچ: جایگزینی منطق ثبت OCO در sync_order_statuses
T_OLD = """        # OCO بومی صرافی — فقط در گذار خرید به «پر شد» (یک‌بار؛ در صورت شکست،
        # حفاظت SL/TP با خود ربات ادامه می‌یابد)
        if (st is not None and getattr(st, 'use_exchange_oco', False)
                and r[2].strip() == 'خرید' and new_st == ST_FILLED
                and sym_c not in led.get('pending_sells', set())):
            try:
                vol_o = float(str(o.get('matchedAmount') or r[6]).replace(',', '') or 0)
            except (TypeError, ValueError):
                vol_o = 0.0
            avail_o = currency_available(client, sym_c)
            if avail_o is not None and avail_o > 1e-12:
                # G-oco: کل موجودی active — پوشش سکه‌های سرگردان
                vol_o = avail_o
            sl_o, tp_o = parse_price(r[8]), parse_price(r[9])"""

T_NEW = """        # OCO بومی صرافی — در گذار خرید به «پر شد»
        if (st is not None and getattr(st, 'use_exchange_oco', False)
                and r[2].strip() == 'خرید' and new_st == ST_FILLED):
            
            _is_scale_in = sym_c in led.get('pending_sells', set())
            
            if _is_scale_in:
                # G-scale VWAP: Scale-in detected! Cancel existing OCO and recalculate based on VWAP
                log.info('G-scale: Scale-in detected for %s. Canceling existing OCO...', sym_c)
                for _rn, _rr in led['rows']:
                    if (_rr[1].strip().upper() == sym_c and 'OCO' in str(_rr[4]) 
                            and _rr[11].strip() in OPENISH):
                        _oids = [clean_oid(x) for x in str(_rr[10]).split('|')]
                        _oids = [x for x in _oids if x and x != chr(8212)]
                        for _oid in _oids:
                            client.cancel_order(_oid)
                        ws_t.update_cell(_rn, 12, 'لغو شده')
                        break
                led.get('pending_sells', set()).discard(sym_c)
                
                # Fetch VWAP from real trades
                _vwap, _, _ = _entry_fill(client, led, sym_c)
                if _vwap and _vwap > 0:
                    _fill_px = _vwap
                    _p_sig = parse_price(r[5])
                    _sl_old, _tp_old = parse_price(r[8]), parse_price(r[9])
                    _slm = getattr(st, 'sl_atr_mult', 0) or 0
                    _tpm = getattr(st, 'tp_atr_mult', 0) or 0
                    if (_p_sig and _sl_old and _tp_old and _slm > 0 and _tpm > 0 and _p_sig > _sl_old):
                        _atr = (_p_sig - _sl_old) / _slm
                        _sl_new = _fill_px - _slm * _atr
                        _tp_new = _fill_px + _tpm * _atr
                        if 0 < _sl_new < _fill_px < _tp_new:
                            r[8] = fmt_price(_sl_new)
                            r[9] = fmt_price(_tp_new)
                            try:
                                ws_t.update_cell(row_num, 9, r[8])
                                ws_t.update_cell(row_num, 10, r[9])
                                log.info('G-fillanchor VWAP %s: SL %s → %s | TP %s → %s (VWAP=%.6g)',
                                         sym_c, fmt_price(_sl_old), r[8], fmt_price(_tp_old), r[9], _fill_px)
                            except Exception:
                                pass

            try:
                vol_o = float(str(o.get('matchedAmount') or r[6]).replace(',', '') or 0)
            except (TypeError, ValueError):
                vol_o = 0.0
            avail_o = currency_available(client, sym_c)
            if avail_o is not None and avail_o > 1e-12:
                # G-oco: کل موجودی active — پوشش سکه‌های سرگردان
                vol_o = avail_o
            sl_o, tp_o = parse_price(r[8]), parse_price(r[9])"""

CHANGES = {
    'trader.py': [(T_OLD, T_NEW, 'G-scale VWAP: recalculate SL/TP and replace OCO on scale-in')]
}


def main():
    os.chdir(os.path.expanduser('~/nobitex-usdt'))
    print('=' * 72)
    print('apply_vwap_oco.py - G-scale VWAP OCO replacement')
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
        print('Deploy complete. Monitor next scale-in fill.')
    else:
        print('dry-run OK. To deploy:')
        print('  cd ~/nobitex-usdt && venv/bin/python apply_vwap_oco.py --deploy')
    print('=' * 72)


if __name__ == '__main__':
    main()
