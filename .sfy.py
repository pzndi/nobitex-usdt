#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apply_sheetify.py — P1..P4: خواندن همهٔ کانفیگ‌های زنده از تب «تنظیمات»
P1: MIN_TFS_SELL قابل تنظیم + هم‌ارزی نمایش/اقدام MIN_TFS (باگ ماژولی 3)
P2: پارامترهای بک‌تست BT_* از شیت (پیش‌فرض = مقادیر قبلی کد)
P3: فواصل auto_block/archive از شیت
P4: SLBUF_MIN_PCT از شیت + متن زندهٔ گاردها + زمان تهران/علت سالم در تب گاردها
پروتکل: انکر یکتا، py_compile، تست واحد، --deploy جدا از build، بکاپ .bak، کامیت گیت.
پیش‌فرض‌ها = رفتار فعلی → صفر تغییر رفتاری (جز نمایش=اقدام در P1 و متن گاردها در P4).
اجرا:  venv/bin/python apply_sheetify.py all            (build/بررسی انکرها)
       venv/bin/python apply_sheetify.py all --deploy   (اعمال + تست + کامیت + ردیف شیت)
       venv/bin/python apply_sheetify.py all --sheet-only  (فقط افزودن ردیف‌های شیت)
"""
import os
import py_compile
import re
import shutil
import subprocess
import sys

FILES = {'settings': 'settings.py', 'trader': 'trader.py',
         'scheduler': 'scheduler.py', 'backtest': 'backtest.py'}
HERE = os.path.dirname(os.path.abspath(__file__))


def read(fid):
    with open(FILES[fid], encoding='utf-8') as f:
        return f.read()


def write(fid, s):
    with open(FILES[fid], 'w', encoding='utf-8') as f:
        f.write(s)


def rdump(fid):
    return FILES[fid] + '.bak'


# ───────────────────────── موتور پچ ─────────────────────────
def hx(fid, old, new, desc):
    """انکر دقیق — count باید 1 باشد؛ new برای تشخیص «از قبل اعمال‌شده»."""
    return {'kind': 'exact', 'fid': fid, 'old': old, 'new': new, 'desc': desc}


def hr(fid, pat, repl, desc, sig, flags=0, optional=False):
    """انکر regex — sig: امضای متنی حالت اعمال‌شده."""
    return {'kind': 'regex', 'fid': fid, 'pat': pat, 'repl': repl, 'desc': desc,
            'sig': sig, 'flags': flags, 'optional': optional}


def hunk_state(h, src):
    # اولین بررسی: آیا از قبل اعمال شده؟ (متن جدید/امضا در فایل هست)
    # این بررسی باید قبل از تطبیق انکر باشد وگرنه انکرهایی که متن قدیمی‌شان
    # زیرمجموعهٔ متن جدید می‌ماند، در اجرای دوم دوباره اعمال می‌شوند.
    if h['kind'] == 'exact':
        if h['new'] in src:
            return 'applied'
        n = src.count(h['old'])
        if n == 1:
            return 'apply'
        return ('fail', 'count=%d' % n)
    if h['sig'] and h['sig'] in src:
        return 'applied'
    rx = re.compile(h['pat'], h['flags'])
    ms = list(rx.finditer(src))
    if len(ms) == 1:
        return 'apply'
    if not ms:
        return ('skip-optional' if h['optional'] else 'fail', 'no-match')
    return ('skip-optional' if h['optional'] else 'fail', 'matches=%d' % len(ms))


def apply_hunk(h, src):
    if h['kind'] == 'exact':
        return src.replace(h['old'], h['new'], 1)
    return re.compile(h['pat'], h['flags']).sub(h['repl'], src, count=1)


# ───────────────────────── تست‌های واحد ─────────────────────────
class FakeSt:
    def __init__(self, **kw):
        self.min_tfs = 2
        self.min_tfs_sell = 3
        self.order_type = 'limit'
        self.entry_mode = 'limit_pullback'
        self.pullback_pct = 1.0
        self.sl_atr_mult = 1.5
        self.slbuf_min_pct = 0.5
        for k, v in kw.items():
            setattr(self, k, v)


def test_p1():
    import settings, trader
    st = FakeSt()
    b = {'buys': 2, 'sells': 1, 'total': 4}
    s3 = {'sells': 3, 'buys': 0, 'total': 4}
    s2 = {'sells': 2, 'buys': 1, 'total': 4}
    assert trader.is_buy_candidate(b, st) is True
    assert trader.is_sell_candidate(s3, st) is True
    assert trader.is_sell_candidate(s2, st) is False
    assert trader.is_sell_candidate(s2, FakeSt(min_tfs_sell=2)) is True
    assert 'is_sell_candidate(a, st)' in read('trader')
    assert 'n_buys >= st.min_tfs' in read('trader')
    s = settings.Settings()
    assert s.min_tfs_sell == 3
    s.trading['MIN_TFS_SELL'] = '2'
    assert s.min_tfs_sell == 2
    print('  ✓ تست P1 سبز (خرید 2/4 ✓، فروش 3 پیش‌فرض ✓، قابل تغییر به 2 ✓، نمایش=اقدام ✓)')


def test_p2():
    import settings, backtest
    s = settings.Settings()
    assert s.bt_optimize_threshold is False
    assert s.bt_threshold_grid == [60.0, 70.0, 80.0]
    assert s.bt_sl_mults == [1.5, 2.0, 2.5]
    assert s.bt_tp_mults == [2.0, 3.0, 4.0]
    assert s.bt_min_trades == 8 and s.bt_min_test_trades == 2
    assert abs(s.bt_holdout - 0.30) < 1e-9
    assert s.bt_fee_rt_pct == 0.25 and s.bt_sl_slip_pct == 0.35
    assert s.bt_warmup == 60 and s.bt_lookback == 480
    s.general['BT_THRESHOLD_GRID'] = '70;80'
    assert s.bt_threshold_grid == [70.0, 80.0]
    s.general['BT_HOLDOUT_PCT'] = '50'
    assert abs(s.bt_holdout - 0.5) < 1e-9
    n = 70
    v = {'buy': [0] * n, 'sell': [0] * n, 'neutral': [2] * n, 'atr': [None] * n}
    v['buy'][60] = 2
    v['neutral'][60] = 0
    v['atr'][60] = 1.0
    c = {'c': [100.0] * n, 'h': [100.0] * n, 'l': [98.5] * n}
    tr = backtest.simulate(v, c, 50, 1.0, 2.0, 60, 62)
    exp = (99.0 * (1 - 0.0035) - 100.0) / 100.0 - 0.0025
    assert len(tr) == 1 and abs(tr[0] - exp) < 1e-12
    tr0 = backtest.simulate(v, c, 50, 1.0, 2.0, 60, 62, fee_pct=0.0, slip_pct=0.0)
    assert abs(tr0[0] - (-0.01)) < 1e-12
    src = read('backtest')
    assert 'st.bt_sl_mults' in src and 'st.bt_fee_rt_pct' in src
    print('  ✓ تست P2 سبز (پیش‌فرض‌ها = کد قبلی؛ کارمزد/اسلپیج قابل تحمیل؛ گرید شیت ✓)')


def test_p3():
    import settings
    s = settings.Settings()
    assert s.interval_auto_block_min == 2880
    assert s.interval_archive_min == 1440
    s.general['INTERVAL_ARCHIVE_MIN'] = '120'
    assert s.interval_archive_min == 120
    s.general['INTERVAL_AUTO_BLOCK_MIN'] = '10'
    assert s.interval_auto_block_min == 60  # clamp به کف دامنه
    src = read('scheduler')
    assert 'st.interval_auto_block_min' in src and 'st.interval_archive_min' in src
    print('  ✓ تست P3 سبز (2880/1440 = رفتار فعلی؛ قابل تغییر از شیت؛ clamp فعال)')


def test_p4():
    import settings, trader
    st = FakeSt()
    row = ['', '', '100', '', '', '', '', '', '', '99.4', '']
    a = {'best': (75, row)}
    skip, buf, fill = trader._sl_buffer_skip(a, st)
    assert skip is True and abs(buf - 0.3009) < 0.01
    skip2, _, _ = trader._sl_buffer_skip(a, FakeSt(slbuf_min_pct=0.2))
    assert skip2 is False
    line = '2026-10-24 13:38:34,318 [INFO] skip buy USOON: market regime bearish (BTC 4h SMA20<SMA50)'
    t, sym, reason = trader._parse_guard_line(line)
    assert sym == 'USOON'
    assert reason.startswith('skip buy USOON')
    assert t is not None and t.endswith('21:08'), t
    s = settings.Settings()
    assert s.slbuf_min_pct == 0.5
    assert 'st.slbuf_min_pct), buf, fill' in read('trader')
    print('  ✓ تست P4 سبز (SLBUF زنده؛ زمان لاگ EDT→تهران جلالی؛ علت کامل بدون بریدگی)')


# ───────────────────────── تعریف پچ‌ها ─────────────────────────
S = 'settings'
T = 'trader'
SC = 'scheduler'
B = 'backtest'

PATCHES = []


def patch(pid, name, files, hunks, test, commit, sheet):
    PATCHES.append({'id': pid, 'name': name, 'files': files, 'hunks': hunks,
                    'test': test, 'commit': commit, 'sheet': sheet})


# ---------- P1 ----------
patch('p1', 'MIN_TFS_SELL از شیت + هم‌ارزی نمایش/اقدام', ['settings.py', 'trader.py'], [
    hr(T, r'^MIN_TFS = 3 .*$',
       'MIN_TFS = 3       # fallback وقتی st در دسترس نیست — مقدار زنده: st.min_tfs از تب تنظیمات\n'
       'MIN_TFS_SELL = 3  # fallback فروش — مقدار زنده: st.min_tfs_sell از تب تنظیمات (P1)',
       'ثابت MIN_TFS → fallback + افزودن MIN_TFS_SELL', 'MIN_TFS_SELL = 3', re.M),
    hx(T,
       "def is_sell_candidate(a):\n"
       "    return (a['sells'] >= MIN_TFS and a['sells'] >= (a['total'] + 1) // 2\n"
       "            and a['sells'] > a['buys'])",
       "def is_sell_candidate(a, st=None):\n"
       "    _min_tfs = st.min_tfs_sell if st is not None else MIN_TFS_SELL\n"
       "    return (a['sells'] >= _min_tfs and a['sells'] >= (a['total'] + 1) // 2\n"
       "            and a['sells'] > a['buys'])",
       'is_sell_candidate از st بخواند'),
    hx(T, '        if not (a and is_sell_candidate(a)):',
       '        if not (a and is_sell_candidate(a, st)):',
       'فراخوانی مسیر فروش: پاس‌دادن st'),
    hx(T,
       "        elif (n_buys >= MIN_TFS and n_buys >= (len(sym_rows) + 1) // 2\n"
       "                and n_buys > n_sells):\n"
       "            status = 'کاندید خرید'  # معیار واقعی (سازگار با MIN_TFS/G-rank)",
       "        elif (n_buys >= st.min_tfs and n_buys >= (len(sym_rows) + 1) // 2\n"
       "                and n_buys > n_sells):\n"
       "            status = 'کاندید خرید'  # معیار واقعی — همان st.min_tfs که سفارش با آن ثبت می‌شود",
       'برچسب «کاندید خرید» با st.min_tfs زنده'),
    hr(S, r"('MAX_SL_BAND_PCT', 'MIN_TFS'\})",
       "'MAX_SL_BAND_PCT', 'MIN_TFS', 'MIN_TFS_SELL'}",
       "TRADING_KEYS += MIN_TFS_SELL", "'MIN_TFS_SELL'}"),
    hr(S, r"('MIN_TFS': '3'\})", "'MIN_TFS': '3', 'MIN_TFS_SELL': '3'}",
       "DEFAULT_TRADING += MIN_TFS_SELL=3", "'MIN_TFS_SELL': '3'}"),
    hr(S, r"('MIN_TFS':\s+\(1\.0, 8\.0\),)",
       "\\1\n    'MIN_TFS_SELL':         (1.0, 8.0),",
       "PARAM_RANGES += MIN_TFS_SELL", "'MIN_TFS_SELL':         (1.0, 8.0),"),
    hx(S,
       "    @property\n"
       "    def min_tfs(self):\n"
       "        \"\"\"حداقل تعداد تایم‌فریم هم‌جهت برای صدور سیگنال (قابل تنظیم از شیت)\"\"\"\n"
       "        return max(1, int(self._tnum('MIN_TFS', 3)))",
       "    @property\n"
       "    def min_tfs(self):\n"
       "        \"\"\"حداقل تعداد تایم‌فریم هم‌جهت برای صدور سیگنال (قابل تنظیم از شیت)\"\"\"\n"
       "        return max(1, int(self._tnum('MIN_TFS', 3)))\n"
       "\n"
       "    @property\n"
       "    def min_tfs_sell(self):\n"
       "        \"\"\"P1: حداقل TF رأی فروش برای خروج سیگنالی — پیش‌فرض 3 = رفتار فعلی\"\"\"\n"
       "        return max(1, int(self._tnum('MIN_TFS_SELL', 3)))",
       'اکسسور min_tfs_sell'),
], test_p1, 'P1 sheetify: MIN_TFS_SELL قابل تنظیم از شیت + هم‌ارزی آستانهٔ فروش و نمایش کاندید با st (نمایش = اقدام)',
   [('MIN_TFS_SELL', '3', 'حداقل تایم‌فریم رأی فروش برای خروج سیگنالی — ۳ = رفتار فعلی؛ برای تقارن با خرید (MIN_TFS=2) به ۲ تغییر دهید')])

# ---------- P2 ----------
_BT_KEYS = ("'BACKTEST_TIMEFRAME', 'SLTP_TIMEFRAME', 'BT_OPTIMIZE_THRESHOLD', "
            "'BT_THRESHOLD_GRID', 'BT_SL_MULTS', 'BT_TP_MULTS', 'BT_MIN_TRADES', "
            "'BT_MIN_TEST_TRADES', 'BT_HOLDOUT_PCT', 'BT_FEE_RT_PCT', "
            "'BT_SL_SLIP_PCT', 'BT_WARMUP', 'BT_LOOKBACK'}")
_BT_DEFAULTS = ("'SLTP_TIMEFRAME': '1h', 'BT_OPTIMIZE_THRESHOLD': 'خیر', "
                "'BT_THRESHOLD_GRID': '60;70;80', 'BT_SL_MULTS': '1.5;2.0;2.5', "
                "'BT_TP_MULTS': '2.0;3.0;4.0', 'BT_MIN_TRADES': '8', "
                "'BT_MIN_TEST_TRADES': '2', 'BT_HOLDOUT_PCT': '30', "
                "'BT_FEE_RT_PCT': '0.25', 'BT_SL_SLIP_PCT': '0.35', "
                "'BT_WARMUP': '60', 'BT_LOOKBACK': '480'}")
_BT_RANGES = ("\\1\n    'BT_MIN_TRADES':         (0, 200),\n"
              "    'BT_MIN_TEST_TRADES':    (0, 100),\n"
              "    'BT_HOLDOUT_PCT':        (5.0, 50.0),\n"
              "    'BT_FEE_RT_PCT':         (0.0, 2.0),\n"
              "    'BT_SL_SLIP_PCT':        (0.0, 2.0),\n"
              "    'BT_WARMUP':             (20, 200),\n"
              "    'BT_LOOKBACK':           (60, 1000),")
_BT_ACCESSORS = '''    @property
    def backtest_timeframe(self):
        return str(self.general.get('BACKTEST_TIMEFRAME') or '1D').strip()

    # ---------- P2: پارامترهای بک‌تست (BT_*) — قابل تغییر از شیت ----------
    @property
    def bt_optimize_threshold(self):
        return truthy(self.general.get('BT_OPTIMIZE_THRESHOLD', 'خیر'))

    def _grid(self, key, default):
        raw = str(self.general.get(key) or default)
        out = []
        for part in raw.replace('،', ';').replace(',', ';').split(';'):
            try:
                out.append(float(part.strip()))
            except ValueError:
                continue
        return out or [float(x) for x in default.split(';')]

    @property
    def bt_threshold_grid(self):
        return sorted({min(90.0, max(1.0, v)) for v in self._grid('BT_THRESHOLD_GRID', '60;70;80')})

    @property
    def bt_sl_mults(self):
        return sorted({min(10.0, max(0.1, v)) for v in self._grid('BT_SL_MULTS', '1.5;2.0;2.5')})

    @property
    def bt_tp_mults(self):
        return sorted({min(20.0, max(0.1, v)) for v in self._grid('BT_TP_MULTS', '2.0;3.0;4.0')})

    @property
    def bt_min_trades(self):
        return max(0, int(_num(self.general.get('BT_MIN_TRADES'), 8)))

    @property
    def bt_min_test_trades(self):
        return max(0, int(_num(self.general.get('BT_MIN_TEST_TRADES'), 2)))

    @property
    def bt_holdout(self):
        return min(0.5, max(0.05, _num(self.general.get('BT_HOLDOUT_PCT'), 30) / 100.0))

    @property
    def bt_fee_rt_pct(self):
        return min(2.0, max(0.0, _num(self.general.get('BT_FEE_RT_PCT'), 0.25)))

    @property
    def bt_sl_slip_pct(self):
        return min(2.0, max(0.0, _num(self.general.get('BT_SL_SLIP_PCT'), 0.35)))

    @property
    def bt_warmup(self):
        return max(20, min(200, int(_num(self.general.get('BT_WARMUP'), 60))))

    @property
    def bt_lookback(self):
        return max(60, min(1000, int(_num(self.general.get('BT_LOOKBACK'), 480))))'''

patch('p2', 'پارامترهای بک‌تست BT_* از شیت', ['settings.py', 'backtest.py'], [
    hr(S, r"('BACKTEST_TIMEFRAME', 'SLTP_TIMEFRAME'\})", _BT_KEYS,
       'GENERAL_KEYS += کلیدهای BT_*', "'BT_LOOKBACK'}"),
    hr(S, r"('SLTP_TIMEFRAME': '1h'\})", _BT_DEFAULTS,
       'DEFAULT_GENERAL += پیش‌فرض‌های BT_* (= مقادیر قبلی کد)', "'BT_LOOKBACK': '480'}"),
    hr(S, r"('INTERVAL_GUARDS_MIN':\s+\(1, 1440\),)", _BT_RANGES,
       'PARAM_RANGES += دامنه‌های BT_*', "'BT_LOOKBACK':           (60, 1000),"),
    hx(S,
       "    @property\n"
       "    def backtest_timeframe(self):\n"
       "        return str(self.general.get('BACKSET_TIMEFRAME') or\n"
       "                   self.general.get('BACKTEST_TIMEFRAME') or '1D').strip()",
       _BT_ACCESSORS,
       'اکسسورهای BT_* + حذف تایپوی BACKSET (بی‌اثر)'),
    hx(B,
       "BT_TAB = 'بک تست'\n"
       "OPTIMIZE_THRESHOLD = False   # فاز ۳ T1: آستانه از شیت — نه از گرید\n"
       "THRESHOLDS = [60, 70, 80]    # فقط وقتی OPTIMIZE_THRESHOLD=True\n"
       "SL_MULTS = [1.5, 2.0, 2.5]\n"
       "TP_MULTS = [2.0, 3.0, 4.0]\n"
       "MIN_TRADES = 8               # حداقل معامله روی داده آموزش\n"
       "MIN_TEST_TRADES = 2          # حداقل معامله روی holdout برای قضاوت\n"
       "WARMUP = 60\n"
       "LOOKBACK = 480\n"
       "HOLDOUT = 0.30               # ۳۰٪ آخر = داده اعتبارسنجی\n"
       "FEE_RT_PCT = 0.25            # کارمزد رفت‌وبرگشت (٪) — اندازه‌گیری‌شده\n"
       "SL_SLIP_PCT = 0.35           # اسلپیج StopLimit (٪) — فقط خروج استاپ",
       "BT_TAB = 'بک تست'\n"
       "# P2: پارامترهای بک‌تست از تب تنظیمات (BT_*) — پیش‌فرض‌ها = مقادیر قبلی کد\n"
       "FEE_RT_PCT_DEFAULT = 0.25    # فقط پیش‌فرضِ امضای simulate برای فراخوانی مستقیم\n"
       "SL_SLIP_PCT_DEFAULT = 0.35",
       'ثابت‌های ماژول → کلیدهای شیت'),
    hx(B,
       "def simulate(v, c, thr, slm, tpm, i0, i1):\n"
       "    \"\"\"شبیه‌سازی روی کندل‌های [i0, i1) با مدل هزینه — خروجی: PnL خالص هر معامله\"\"\"",
       "def simulate(v, c, thr, slm, tpm, i0, i1,\n"
       "             fee_pct=FEE_RT_PCT_DEFAULT, slip_pct=SL_SLIP_PCT_DEFAULT):\n"
       "    \"\"\"شبیه‌سازی روی کندل‌های [i0, i1) با مدل هزینه — خروجی: PnL خالص هر معامله\"\"\"",
       'امضای simulate: کارمزد/اسلپیج پارامتری'),
    hx(B,
       "    fee = FEE_RT_PCT / 100.0\n"
       "    slip = SL_SLIP_PCT / 100.0",
       "    fee = fee_pct / 100.0\n"
       "    slip = slip_pct / 100.0",
       'بدنهٔ simulate از پارامتر بخواند'),
    hx(B,
       "    c = se.fetch_candles(sym + 'USDT', st.backtest_timeframe, LOOKBACK)\n"
       "    if not c or len(c['c']) < WARMUP + 60:\n"
       "        return None\n"
       "    v = se.prepare_votes(c, st)\n"
       "    n = len(c['c'])\n"
       "    split = int(n * (1 - HOLDOUT))\n"
       "    thr_grid = THRESHOLDS if OPTIMIZE_THRESHOLD else [st.threshold_pct]",
       "    lookback, warmup = st.bt_lookback, st.bt_warmup\n"
       "    c = se.fetch_candles(sym + 'USDT', st.backtest_timeframe, lookback)\n"
       "    if not c or len(c['c']) < warmup + 60:\n"
       "        return None\n"
       "    v = se.prepare_votes(c, st)\n"
       "    n = len(c['c'])\n"
       "    split = int(n * (1 - st.bt_holdout))\n"
       "    thr_grid = st.bt_threshold_grid if st.bt_optimize_threshold else [st.threshold_pct]",
       'backtest_symbol از st بخواند (نمای کلی)'),
    hx(B,
       "        for slm in SL_MULTS:\n"
       "            for tpm in TP_MULTS:",
       "        for slm in st.bt_sl_mults:\n"
       "            for tpm in st.bt_tp_mults:",
       'گرید SL/TP از شیت'),
    hx(B,
       "                tr_train = simulate(v, c, thr, slm, tpm, WARMUP, split)\n"
       "                if len(tr_train) < MIN_TRADES:",
       "                tr_train = simulate(v, c, thr, slm, tpm, warmup, split,\n"
       "                                    fee_pct=st.bt_fee_rt_pct, slip_pct=st.bt_sl_slip_pct)\n"
       "                if len(tr_train) < st.bt_min_trades:",
       'شبیه‌سازی آموزش: کارمزد/اسلپیج شیت + حداقل معامله شیت'),
    hx(B,
       "    tr_test = simulate(v, c, best['thr'], best['slm'], best['tpm'], split, n)",
       "    tr_test = simulate(v, c, best['thr'], best['slm'], best['tpm'], split, n,\n"
       "                       fee_pct=st.bt_fee_rt_pct, slip_pct=st.bt_sl_slip_pct)",
       'شبیه‌سازی holdout: کارمزد/اسلپیج شیت'),
    hx(B,
       "    if len(tr_test) < MIN_TEST_TRADES or best['pnl_test'] <= 0:",
       "    if len(tr_test) < st.bt_min_test_trades or best['pnl_test'] <= 0:",
       'حداقل معامله holdout از شیت'),
], test_p2, 'P2 sheetify: پارامترهای بک‌تست (BT_*) از تب تنظیمات — پیش‌فرض = مقادیر قبلی، صفر تغییر رفتاری',
   [('BT_OPTIMIZE_THRESHOLD', 'خیر', 'بهینه‌سازی آستانه per-symbol از گرید (بله/خیر)'),
    ('BT_THRESHOLD_GRID', '60;70;80', 'گرید آستانه برای بهینه‌سازی — جداکننده ؛'),
    ('BT_SL_MULTS', '1.5;2.0;2.5', 'گرید ضریب SL×ATR'),
    ('BT_TP_MULTS', '2.0;3.0;4.0', 'گرید ضریب TP×ATR'),
    ('BT_MIN_TRADES', '8', 'حداقل معامله روی دادهٔ آموزش'),
    ('BT_MIN_TEST_TRADES', '2', 'حداقل معامله روی holdout'),
    ('BT_HOLDOUT_PCT', '30', 'درصد دادهٔ اعتبارسنجی (آخر)'),
    ('BT_FEE_RT_PCT', '0.25', 'کارمزد رفت‌وبرگشت (٪) — اندازه‌گیری‌شده از fillها'),
    ('BT_SL_SLIP_PCT', '0.35', 'اسلپیج خروج استاپ‌لیمیتی (٪)'),
    ('BT_WARMUP', '60', 'کندل‌های warmup حذف‌شده از ابتدای داده'),
    ('BT_LOOKBACK', '480', 'تعداد کندل تاریخچهٔ بک‌تست')])

# ---------- P3 ----------
patch('p3', 'فواصل auto_block/archive از شیت', ['settings.py', 'scheduler.py'], [
    hr(S, r"('INTERVAL_WALLET_MIN', 'INTERVAL_GUARDS_MIN', 'BACKTEST_TIMEFRAME')",
       "'INTERVAL_WALLET_MIN', 'INTERVAL_GUARDS_MIN', 'INTERVAL_AUTO_BLOCK_MIN', "
       "'INTERVAL_ARCHIVE_MIN', 'BACKTEST_TIMEFRAME'",
       'GENERAL_KEYS += INTERVAL_AUTO_BLOCK/ARCHIVE', "'INTERVAL_ARCHIVE_MIN', 'BACKTEST_TIMEFRAME'"),
    hr(S, r"('INTERVAL_GUARDS_MIN': '5',)",
       "'INTERVAL_GUARDS_MIN': '5', 'INTERVAL_AUTO_BLOCK_MIN': '2880', "
       "'INTERVAL_ARCHIVE_MIN': '1440',",
       'DEFAULT_GENERAL += 2880/1440 (= 48س/24س فعلی)', "'INTERVAL_ARCHIVE_MIN': '1440',"),
    hr(S, r"('INTERVAL_GUARDS_MIN':\s+\(1, 1440\),)",
       "\\1\n    'INTERVAL_AUTO_BLOCK_MIN': (60, 10080),\n"
       "    'INTERVAL_ARCHIVE_MIN':    (60, 10080),",
       'PARAM_RANGES += دامنهٔ فواصل جدید', "'INTERVAL_ARCHIVE_MIN':    (60, 10080),"),
    hx(S,
       "    @property\n"
       "    def interval_guards_min(self):\n"
       "        return self._interval('INTERVAL_GUARDS_MIN', 5)",
       "    @property\n"
       "    def interval_guards_min(self):\n"
       "        return self._interval('INTERVAL_GUARDS_MIN', 5)\n"
       "\n"
       "    @property\n"
       "    def interval_auto_block_min(self):\n"
       "        \"\"\"P3: فاصلهٔ چرخهٔ بلاک خودکار نمادها (دقیقه) — پیش‌فرض 2880 = 48 ساعت\"\"\"\n"
       "        return self._interval('INTERVAL_AUTO_BLOCK_MIN', 2880)\n"
       "\n"
       "    @property\n"
       "    def interval_archive_min(self):\n"
       "        \"\"\"P3: فاصلهٔ چرخهٔ آرشیو سفارشات (دقیقه) — پیش‌فرض 1440 = 24 ساعت\"\"\"\n"
       "        return self._interval('INTERVAL_ARCHIVE_MIN', 1440)",
       'اکسسورهای فواصل جدید'),
    hx(SC,
       "        ('auto_block', 48 * 60, lambda: trader.auto_block_update(sh, st)),\n"
       "        ('archive', 24 * 60, lambda: trader.archive_orders(sh, st)),",
       "        ('auto_block', st.interval_auto_block_min, lambda: trader.auto_block_update(sh, st)),\n"
       "        ('archive', st.interval_archive_min, lambda: trader.archive_orders(sh, st)),",
       'زمان‌بند: فواصل از st'),
], test_p3, 'P3 sheetify: فواصل auto_block/archive قابل تنظیم از شیت (پیش‌فرض 48س/24س = رفتار فعلی)',
   [('INTERVAL_AUTO_BLOCK_MIN', '2880', 'فاصلهٔ چرخهٔ بلاک خودکار نمادهای زیان‌ده (دقیقه) — 2880 = 48 ساعت'),
    ('INTERVAL_ARCHIVE_MIN', '1440', 'فاصلهٔ چرخهٔ آرشیو سفارشات (دقیقه) — 1440 = 24 ساعت')])

# ---------- P4 ----------
_PARSE_HELPER = '''def _parse_guard_line(line):
    """P4: استخراج (زمان تهران جلالی، نماد، علت کامل) از یک خط لاگ EDT"""
    import re as _re
    from datetime import datetime as _dt
    out_time = out_sym = out_reason = None
    mt = _re.match(r'(\\d{4}-\\d{2}-\\d{2}) (\\d{2}:\\d{2}:\\d{2})', line)
    if mt:
        try:
            naive = _dt.strptime(mt.group(1) + ' ' + mt.group(2), '%Y-%m-%d %H:%M:%S')
            try:
                from zoneinfo import ZoneInfo
                teh = naive.replace(tzinfo=ZoneInfo('America/New_York')
                                    ).astimezone(ZoneInfo('Asia/Tehran'))
            except Exception:
                teh = naive
            try:
                import jdatetime
                out_time = jdatetime.datetime.fromgregorian(
                    datetime=teh.replace(tzinfo=None)).strftime('%Y/%m/%d %H:%M')
            except Exception:
                out_time = teh.strftime('%Y/%m/%d %H:%M')
        except Exception:
            out_time = mt.group(2)
    ms = _re.search(r'(?:skip buy|خرید|فروش)\\s+(\\w+)', line)
    if ms:
        out_sym = ms.group(1)
    mr = _re.search(r'\\]\\s+(.+)$', line)
    if mr:
        out_reason = mr.group(1).strip()[:80]
    return out_time, out_sym, out_reason


def write_guards_status(sh, st, state=None):'''

patch('p4', 'SLBUF_MIN_PCT از شیت + گاردهای زنده + زمان/علت سالم', ['settings.py', 'trader.py'], [
    hr(S, r"('ENTRY_MODE', 'PULLBACK_PCT', 'POSITION_TIMEOUT_H')",
       "'ENTRY_MODE', 'PULLBACK_PCT', 'SLBUF_MIN_PCT', 'POSITION_TIMEOUT_H'",
       'TRADING_KEYS += SLBUF_MIN_PCT', "'SLBUF_MIN_PCT', 'POSITION_TIMEOUT_H'"),
    hr(S, r"('PULLBACK_PCT': '1\.0',)", "'PULLBACK_PCT': '1.0', 'SLBUF_MIN_PCT': '0.5',",
       'DEFAULT_TRADING += SLBUF_MIN_PCT=0.5', "'SLBUF_MIN_PCT': '0.5',"),
    hr(S, r"('PULLBACK_PCT':\s+\(0\.0, 10\.0\),)",
       "\\1\n    'SLBUF_MIN_PCT':         (0.0, 5.0),",
       'PARAM_RANGES += SLBUF_MIN_PCT', "'SLBUF_MIN_PCT':         (0.0, 5.0),"),
    hx(S,
       "    @property\n"
       "    def pullback_pct(self):\n"
       "        \"\"\"G-entry: pullback percentage for limit entry.\"\"\"\n"
       "        return max(0.0, min(10.0, self._tnum('PULLBACK_PCT', 1.0)))",
       "    @property\n"
       "    def pullback_pct(self):\n"
       "        \"\"\"G-entry: pullback percentage for limit entry.\"\"\"\n"
       "        return max(0.0, min(10.0, self._tnum('PULLBACK_PCT', 1.0)))\n"
       "\n"
       "    @property\n"
       "    def slbuf_min_pct(self):\n"
       "        \"\"\"P4/G-slbuf: حداقل بافر SL نسبت به fill تخمینی (٪). 0 = خاموش\"\"\"\n"
       "        return min(5.0, max(0.0, self._tnum('SLBUF_MIN_PCT', 0.5)))",
       'اکسسور slbuf_min_pct'),
    hx(T, "    return (buf < 0.5), buf, fill",
       "    return (buf < st.slbuf_min_pct), buf, fill",
       'آستانهٔ G-slbuf از st (پیش‌فرض 0.5 = فعلی)'),
    hr(T, r"SL buffer %\.2f%% < 0\.5%% at est\. fill %\.6g',\s*\n\s*sym, _buf, _fill_est\)",
       "SL buffer %.2f%% < %.1f%% at est. fill %.6g',\\n"
       "                 sym, _buf, st.slbuf_min_pct, _fill_est)",
       'متن لاگ SL buffer با مقدار زنده', 'st.slbuf_min_pct, _fill_est)', 0, True),
    hx(T,
       "            duty = GUARDS_DUTY.get(name, '')",
       "            duty = GUARDS_DUTY.get(name, '')\n"
       "            if name == 'PUMP_GUARD_PCT':\n"
       "                duty = 'رد ورود اگر قیمت بیش از %.0f%% بالای SMA20 ساعتی — زنده از تنظیمات' % st.pump_guard_pct\n"
       "            elif name == 'G_SLBUF':\n"
       "                duty = 'رد ورود اگر بافر SL نسبت به fill تخمینی < %.1f%% (SLBUF_MIN_PCT)' % st.slbuf_min_pct",
       'متن وظیفهٔ PUMP/G_SLBUF با مقدار زنده'),
    hx(T, "def write_guards_status(sh, st, state=None):",
       _PARSE_HELPER,
       'هلپر _parse_guard_line (زمان تهران + علت کامل)'),
    hx(T,
       "            for line in recent_lines:\n"
       "                if pattern in line:\n"
       "                    count += 1\n"
       "                    last_time = line[:19].split(' ')[1] if ' ' in line else line[:19]\n"
       "                    m = _re.search(r'(?:skip buy|خرید)\\s+(\\w+)', line)\n"
       "                    if m:\n"
       "                        last_sym = m.group(1)\n"
       "                    if ':' in line:\n"
       "                        parts = line.split(':', 2)\n"
       "                        if len(parts) >= 3:\n"
       "                            last_reason = parts[2].strip()[:60]",
       "            for line in recent_lines:\n"
       "                if pattern in line:\n"
       "                    count += 1\n"
       "                    _gt, _gs, _gr = _parse_guard_line(line)\n"
       "                    if _gt:\n"
       "                        last_time = _gt\n"
       "                    if _gs:\n"
       "                        last_sym = _gs\n"
       "                    if _gr:\n"
       "                        last_reason = _gr",
       'حلقهٔ پارس لاگ: EDT→تهران + علت بدون بریدگی'),
], test_p4, 'P4 sheetify: SLBUF_MIN_PCT از شیت + متن زندهٔ گاردها + زمان تهران/علت سالم در تب گاردها',
   [('SLBUF_MIN_PCT', '0.5', 'حداقل بافر SL نسبت به fill تخمینی (٪) — 0 = خاموش (پیش‌فرض 0.5 = رفتار فعلی)')])


# ───────────────────────── اجرا ─────────────────────────
def p2_preflight():
    """هشدار: ارجاع بیرونی به ثابت‌های حذف‌شدهٔ backtest؟"""
    consts = ['OPTIMIZE_THRESHOLD', 'THRESHOLDS', 'SL_MULTS', 'TP_MULTS',
              'MIN_TRADES', 'MIN_TEST_TRADES', 'HOLDOUT', 'FEE_RT_PCT',
              'SL_SLIP_PCT', 'WARMUP', 'LOOKBACK']
    hard, soft = [], []
    for fn in os.listdir('.'):
        if not fn.endswith('.py') or fn in ('backtest.py', 'apply_sheetify.py') \
                or fn.startswith('apply_') or fn.startswith('fix_'):
            continue
        try:
            with open(fn, encoding='utf-8') as f:
                src = f.read()
        except Exception:
            continue
        for cst in consts:
            if re.search(r'from backtest import[^\n]*\b' + cst + r'\b', src) or \
               re.search(r'backtest\.' + cst + r'\b', src):
                hard.append('%s:%s' % (fn, cst))
            elif re.search(r'\b' + cst + r'\b', src):
                soft.append('%s:%s' % (fn, cst))
    return hard, soft


def run_sheet(rows):
    import gspread
    from settings import load_env
    sh = gspread.service_account(filename='service_account.json').open_by_key(
        load_env().get('SHEET_ID'))
    ws = sh.worksheet('تنظیمات')
    vals = ws.get_values(value_render_option='UNFORMATTED_VALUE')
    have = {str(r[0]).strip() for r in vals if r}
    last = max([i for i, r in enumerate(vals, 1) if any(str(c).strip() for c in r)] or [0])
    add = [r for r in rows if r[0] not in have]
    if not add:
        print('  = شیت: همهٔ ردیف‌ها از قبل موجودند')
        return
    if last + len(add) > ws.row_count:
        ws.add_rows(last + len(add) - ws.row_count + 2)
    ws.update(values=[list(r) for r in add],
              range_name='A%d:C%d' % (last + 1, last + len(add)))
    for r in add:
        print('  ✓ شیت +ردیف %d: %s = %s' % (last + 1 + add.index(r), r[0], r[1]))


def do_patch(p, deploy, skip_git, skip_sheet):
    print('══ %s — %s ══' % (p['id'].upper(), p['name']))
    states = {}
    for h in p['hunks']:
        src = read(h['fid'])
        st = hunk_state(h, src)
        states[id(h)] = st
        if isinstance(st, tuple):
            mark = '⊘ اختیاری رد شد' if st[0] == 'skip-optional' else '✗ شکست'
            print('  %s [%s] %s (%s)' % (mark, h['fid'], h['desc'], st[1]))
            if st[0] == 'fail':
                return False
        else:
            print('  %s [%s] %s' % ('→ اعمال' if st == 'apply' else '= از قبل', h['fid'], h['desc']))
    if not deploy:
        return True
    touched = set()
    for h in p['hunks']:
        if states[id(h)] != 'apply':
            continue
        fid = h['fid']
        if fid not in touched:
            shutil.copy2(FILES[fid], rdump(fid))
            touched.add(fid)
        write(fid, apply_hunk(h, read(fid)))
    for fid in touched:
        py_compile.compile(FILES[fid], doraise=True)
        print('  ✓ py_compile %s' % FILES[fid])
    r = subprocess.run([sys.executable, os.path.abspath(__file__), '--selftest', p['id']],
                       capture_output=True, text=True)
    print(r.stdout.rstrip())
    if r.returncode != 0:
        print(r.stderr.rstrip()[-1500:])
        print('  ✗ تست شکست خورد — بازگردانی از .bak:')
        for fid in touched:
            shutil.copy2(rdump(fid), FILES[fid])
        return False
    if not skip_git:
        files = sorted(touched | ({os.path.relpath(__file__, '.')} if p['id'] == 'p1' else set()))
        subprocess.run(['git', 'add'] + files, check=False)
        c = subprocess.run(['git', 'commit', '-m', p['commit']], capture_output=True, text=True)
        line = (c.stdout or c.stderr).strip().splitlines()
        print('  ✓ git:', line[0] if line else 'بدون تغییر')
    if not skip_sheet:
        try:
            run_sheet(p['sheet'])
        except Exception as e:
            print('  ⚠ شیت ناموفق (کد سبز است؛ بعداً با --sheet-only تلاش کنید): %s' % e)
    return True


def main():
    args = sys.argv[1:]
    if '--selftest' in args:
        ids = [a for a in args if not a.startswith('--')] or ['all']
        ok = True
        for p in PATCHES:
            if 'all' in ids or p['id'] in ids:
                try:
                    p['test']()
                except Exception as e:
                    print('  ✗ تست %s: %r' % (p['id'], e))
                    ok = False
        sys.exit(0 if ok else 1)
    if not (os.path.exists('trader.py') and os.path.exists('settings.py')):
        sys.exit('این اسکریپت باید از ریشهٔ پروژه (~/nobitex-usdt) اجرا شود.')
    deploy = '--deploy' in args
    sheet_only = '--sheet-only' in args
    skip_git = '--skip-git' in args
    skip_sheet = '--skip-sheet' in args
    ids = [a for a in args if not a.startswith('--')] or ['all']
    sel = [p for p in PATCHES if 'all' in ids or p['id'] in ids]
    if not sel:
        sys.exit('پچ نامعلوم. گزینه‌ها: p1 p2 p3 p4 all')
    if sheet_only:
        for p in sel:
            try:
                print('══ %s — ردیف‌های شیت ══' % p['id'].upper())
                run_sheet(p['sheet'])
            except Exception as e:
                print('  ⚠ %s: %s' % (p['id'], e))
        return
    if any(p['id'] == 'p2' for p in sel) and not sheet_only:
        hard, soft = p2_preflight()
        if hard:
            print('✗ ارجاع بیرونی به ثابت‌های backtest — P2 متوقف شد:')
            for x in hard:
                print('   ', x)
            sel = [p for p in sel if p['id'] != 'p2']
        elif soft:
            print('⚠ اشاره‌های واژه‌ای (غیرمستقیم) به نام ثابت‌ها (بررسی شد، مانع نیست):')
            for x in sorted(set(soft))[:8]:
                print('   ', x)
    print('════════ حالت: %s | پچ‌ها: %s ════════' % ('DEPLOY' if deploy else 'BUILD (بررسی انکرها)',
                                                     ' '.join(p['id'] for p in sel)))
    for p in sel:
        if not do_patch(p, deploy, skip_git, skip_sheet):
            print('✗ %s متوقف شد — پچ‌های بعدی اجرا نشدند.' % p['id'].upper())
            sys.exit(1)
    print('════════ %s کامل شد ════════' % ('اعمال' if deploy else 'بررسی (برای اعمال: --deploy)'))


if __name__ == '__main__':
    main()
