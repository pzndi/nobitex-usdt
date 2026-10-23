#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_analysis_in_reconcile.py - اضافه کردن _record_analysis به reconcile_real_positions

مشکل: معاملاتی که از طریق reconcile_real_positions بسته می‌شوند (خروج از کیف پول،
OCO خارج از ربات، فروش دستی) در تب «تحلیل معاملات» ثبت نمی‌شوند.

علت: _record_analysis فقط در sync_order_statuses فراخوانی می‌شود، نه در reconcile.

شاهد: MEW و WLD با "خروج از کیف پول" بسته شدند اما در تب تحلیل نیستند.

راه‌حل: اضافه کردن _record_analysis بعد از record_closed در reconcile_real_positions.
"""
import os, sys, shutil, time

DEPLOY = '--deploy' in sys.argv

T_OLD = """        record_closed(ws_t, sym, e_time, _entry_n7 or p.get('entry_price') or price, price,
                      sold, 'خروج از کیف پول (OCO یا فروش دستی)', 'واقعی', fee_usdt=_sell_fee_n7 + _buy_fee_n7)
        led['positions'].pop(sym, None)"""

T_NEW = """        record_closed(ws_t, sym, e_time, _entry_n7 or p.get('entry_price') or price, price,
                      sold, 'خروج از کیف پول (OCO یا فروش دستی)', 'واقعی', fee_usdt=_sell_fee_n7 + _buy_fee_n7)
        # G-analysis: ثبت تحلیل معامله در تب «تحلیل معاملات»
        try:
            _entry_an = _entry_n7 or p.get('entry_price') or price
            _exit_an = price
            _vol_an = sold
            _pnl_an = _vol_an * (_exit_an - _entry_an) - _sell_fee_n7 - _buy_fee_n7
            _pct_an = (_exit_an / _entry_an - 1) * 100 if _entry_an else 0.0
            _dur_an = '—'
            try:
                import jdatetime as _jd
                import datetime as _dt
                _t0 = _jd.datetime.strptime(str(e_time).strip(), '%Y/%m/%d %H:%M')
                _now_a = (_dt.datetime.now(_dt.timezone.utc)
                          + _dt.timedelta(hours=3, minutes=30)).replace(tzinfo=None)
                _dur_an = round((_now_a - _t0.togregorian()).total_seconds() / 3600, 1)
            except Exception:
                pass
            _record_analysis(ws_t, sym, _entry_an, _exit_an, _vol_an,
                            _pnl_an, _pct_an, _dur_an,
                            'خروج از کیف پول (OCO یا فروش دستی)',
                            led, client, st)
        except Exception:
            log.exception('خطا در ثبت تحلیل معامله %s (reconcile)', sym)
        led['positions'].pop(sym, None)"""


def main():
    print('=' * 70)
    print('fix_analysis_in_reconcile.py - اضافه کردن _record_analysis به reconcile')
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
        print('+ trader.py: اضافه شدن _record_analysis به reconcile_real_positions')
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
        print('اکنون هر معامله‌ای که از طریق reconcile بسته شود (خروج از کیف پول،')
        print('OCO خارج از ربات، فروش دستی) هم در تب تحلیل معاملات ثبت می‌شود.')
    else:
        print('dry-run OK. To deploy:')
        print('  cd ~/nobitex-usdt && venv/bin/python fix_analysis_in_reconcile.py --deploy')
    print('=' * 70)
    return 0

if __name__ == '__main__':
    sys.exit(main())
