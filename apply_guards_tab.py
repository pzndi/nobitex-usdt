#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""apply_guards_tab.py - create guards status tab"""
import os, sys, shutil, py_compile, time

DEPLOY = '--deploy' in sys.argv

S1_OLD = """                  'INTERVAL_UNIVERSE_MIN', 'INTERVAL_SIGNALS_MIN', 'INTERVAL_BACKTEST_MIN',
                  'INTERVAL_WALLET_MIN', 'BACKTEST_TIMEFRAME', 'SLTP_TIMEFRAME'}"""
S1_NEW = """                  'INTERVAL_UNIVERSE_MIN', 'INTERVAL_SIGNALS_MIN', 'INTERVAL_BACKTEST_MIN',
                  'INTERVAL_WALLET_MIN', 'INTERVAL_GUARDS_MIN', 'BACKTEST_TIMEFRAME', 'SLTP_TIMEFRAME'}"""

S2_OLD = """                  'INTERVAL_BACKTEST_MIN': '30', 'INTERVAL_WALLET_MIN': '30',"""
S2_NEW = """                  'INTERVAL_BACKTEST_MIN': '30', 'INTERVAL_WALLET_MIN': '30',
                  'INTERVAL_GUARDS_MIN': '5',"""

S3_OLD = """    'INTERVAL_WALLET_MIN':     (1, 1440),"""
S3_NEW = """    'INTERVAL_WALLET_MIN':     (1, 1440),
    'INTERVAL_GUARDS_MIN':     (1, 1440),"""

S4_OLD = """    def interval_wallet_min(self):
        return self._interval('INTERVAL_WALLET_MIN', 30)"""
S4_NEW = """    def interval_wallet_min(self):
        return self._interval('INTERVAL_WALLET_MIN', 30)

    @property
    def interval_guards_min(self):
        return self._interval('INTERVAL_GUARDS_MIN', 5)"""

T1_OLD = """EFFECTIVE_TAB = 'کانفیگ مؤثر'   # F9-lite: effective config snapshot"""
T1_NEW = """EFFECTIVE_TAB = 'کانفیگ مؤثر'   # F9-lite: effective config snapshot
GUARDS_TAB = 'گاردها'            # G-guards: live guards status dashboard"""

T2_OLD = """def write_effective_config(sh, st, state=None):"""
T2_NEW = '''# GUARDS_DEFS: (name, log_pattern, active_condition)
GUARDS_DEFS = [
    ('سقف روزانه معاملات',   'سقف معاملات روزانه',           True),
    ('پوزیشن/سفارش باز',     'پوزیشن یا سفارش باز موجود',     True),
    ('same-cycle',           'خروج در همین چرخه',            True),
    ('کول‌داون ناموفق',       'سفارش ناموفق در',              'order_fail_cooldown_min'),
    ('کول‌داون زیان‌ده',       'خروج زیان‌ده در',              'reentry_cooldown_min'),
    ('سقف پوزیشن باز',       'سقف پوزیشن باز',               True),
    ('باند SL/TP',           'باند SL/TP زیر حداقل',         True),
    ('G-slbuf',              'SL buffer',                    True),
    ('G-bandcap',            'SL band',                       True),
    ('G-global',             'no global mark price',          True),
    ('G-premium',            'local premium',                True),
    ('G-mark-dev',           'above global mark',            True),
    ('مومنتوم 5٪',           'momentum exhaustion',          'pump_guard_pct'),
    ('چاقو (knife)',         'losing exits in last',         'loss_streak_limit'),
    ('روند BTC 4h',          'market regime bearish',        'trend_filter_enabled'),
    ('AUTO_BLOCK',           'symbol blocked',               True),
    ('موجودی USDT',          'موجودی USDT کافی نیست',        True),
    ('limit TTL',            'سفارش ورود کهنه لغو شد',       True),
    ('G-volsize',            'G-volsize',                     True),
    ('G-maxsl (بک‌تست)',      'G-maxsl',                      'use_bt_params'),
]


def _guard_active(st, cond):
    if cond is True:
        return True
    if cond is False:
        return False
    return bool(getattr(st, cond, 0))


def write_guards_status(sh, st, state=None):
    """G-guards: live status of all guards + last trigger + today count"""
    import re as _re
    from datetime import datetime as _dt
    try:
        try:
            ws = sh.worksheet(GUARDS_TAB)
        except Exception:
            ws = sh.add_worksheet(title=GUARDS_TAB, rows=30, cols=7)
            ws.update(values=[['پایش زنده گاردها', 'به‌روزرسانی:', jnow()]],
                      range_name='A1:C1')
            ws.update(values=[['نام گارد', 'وضعیت', 'آخرین رد', 'نماد', 'علت', 'تعداد امروز', 'یادداشت']],
                      range_name='A3:G3')
            ws.freeze(rows=3)
        today_str = _dt.now().strftime('%Y-%m-%d')
        log_path = os.path.expanduser('~/nobitex-usdt/update.log')
        today_lines = []
        try:
            with open(log_path, encoding='utf-8') as f:
                for line in f:
                    if today_str in line:
                        today_lines.append(line.strip())
        except Exception:
            pass
        rows = []
        for name, pattern, cond in GUARDS_DEFS:
            active = _guard_active(st, cond)
            status = 'فعال' if active else 'غیرفعال'
            count = 0
            last_time = '—'
            last_sym = '—'
            last_reason = '—'
            for line in today_lines:
                if pattern in line:
                    count += 1
                    last_time = line[:19].split(' ')[1] if ' ' in line else line[:19]
                    m = _re.search(r'(?:skip buy|خرید)\\s+(\\w+)', line)
                    if m:
                        last_sym = m.group(1)
                    if ':' in line:
                        parts = line.split(':', 2)
                        if len(parts) >= 3:
                            last_reason = parts[2].strip()[:60]
            note = ''
            if cond is not True and cond is not False:
                val = getattr(st, cond, 0)
                note = '%s=%s' % (cond, val)
            rows.append([name, status, last_time, last_sym, last_reason, count, note])
        ws.update(values=[['پایش زنده گاردها', 'به‌روزرسانی:', jnow()]],
                  range_name='A1:C1')
        ws.update(values=[['نام گارد', 'وضعیت', 'آخرین رد', 'نماد', 'علت', 'تعداد امروز', 'یادداشت']],
                  range_name='A3:G3')
        data = rows + [[''] * 7] * max(0, 25 - len(rows))
        ws.update(values=data, range_name='A4:G%d' % (4 + len(data) - 1))
    except Exception:
        log.exception('خطا در write_guards_status')


def write_effective_config(sh, st, state=None):'''

SC_OLD = """        ('signals', st.interval_signals_min, lambda: run_signals(sh, st, state)),
        ('wallet', st.interval_wallet_min, lambda: run_wallet(sh, st, state)),
    ]"""
SC_NEW = """        ('signals', st.interval_signals_min, lambda: run_signals(sh, st, state)),
        ('wallet', st.interval_wallet_min, lambda: run_wallet(sh, st, state)),
        ('guards', st.interval_guards_min, lambda: trader.write_guards_status(sh, st, state)),
    ]"""

SC2_OLD = """                 st.interval_signals_min, st.interval_wallet_min)"""
SC2_NEW = """                 st.interval_signals_min, st.interval_wallet_min,
                 st.interval_guards_min)"""

CHANGES = {
    'settings.py': [(S1_OLD, S1_NEW, 'add INTERVAL_GUARDS_MIN to ALLOWED_KEYS'),
                   (S2_OLD, S2_NEW, 'default INTERVAL_GUARDS_MIN=5'),
                   (S3_OLD, S3_NEW, 'range INTERVAL_GUARDS_MIN (1-1440)'),
                   (S4_OLD, S4_NEW, 'property interval_guards_min')],
    'trader.py': [(T1_OLD, T1_NEW, 'const GUARDS_TAB'),
                  (T2_OLD, T2_NEW, 'func write_guards_status + GUARDS_DEFS')],
    'scheduler.py': [(SC_OLD, SC_NEW, 'guards cycle in tasks'),
                     (SC2_OLD, SC2_NEW, 'log guards cycle')],
}


def main():
    os.chdir(os.path.expanduser('~/nobitex-usdt'))
    print('=' * 72)
    print('apply_guards_tab.py - create live guards status tab')
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
        print('Deploy complete. Next steps:')
        print('  1. Add INTERVAL_GUARDS_MIN row to sheet')
        print('  2. Wait 5 min for first guards cycle')
        print('  3. Check tab "گاردها" in sheet')
    else:
        print('dry-run OK. To deploy:')
        print('  cd ~/nobitex-usdt && venv/bin/python apply_guards_tab.py --deploy')
    print('=' * 72)


if __name__ == '__main__':
    main()
