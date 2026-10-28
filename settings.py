#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
settings.py — خواندن پیکربندی از تب «تنظیمات» شیت + فایل .env
شیت = منبع حقیقت؛ هر اجرا تنظیمات تازه خوانده می‌شود (تغییر در شیت از اجرای بعد اعمال می‌شود)
"""

TRUE_WORDS = {'بله', 'yes', 'true', '1', 'on', 'فعال'}
FA_DIGITS = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')

INDICATOR_KEYS = {'SMA', 'EMA', 'RSI', 'MACD', 'BB', 'STOCH', 'OBV', 'CCI', 'WPR', 'ATR'}
TIMEFRAME_KEYS = {'1m', '5m', '15m', '30m', '1h', '3h', '4h', '6h', '12h', '1D', '2D', '3D'}
TRADING_KEYS = {'TRADING_ENABLED', 'DRY_RUN', 'MAX_DAILY_TRADES', 'ORDER_TYPE',
                'ORDER_SIZE_USDT', 'MAX_OPEN_POSITIONS', 'MIN_USDT_BALANCE', 'DRY_START_USDT',
                'SL_ATR_MULT', 'TP_ATR_MULT', 'USE_EXCHANGE_OCO',
                'TRAIL_ENABLED', 'TRAIL_ACTIVATION_PCT', 'TRAIL_DISTANCE_PCT', 'DUST_USDT',
                'ORDER_FAIL_COOLDOWN_MIN', 'EXIT_ORDER_TYPE', 'ENTRY_TTL_MIN', 'REENTRY_COOLDOWN_MIN', 'PUMP_GUARD_PCT', 'LOSS_STREAK_LIMIT', 'LOSS_STREAK_WINDOW_H', 'USE_BT_PARAMS', 'MAX_SL_MULT', 'TREND_FILTER_ENABLED', 'TRAIL_ATR_MULT', 'PARTIAL_EXIT_PCT', 'PARTIAL_EXIT_TRIGGER', 'ENTRY_MODE', 'PULLBACK_PCT', 'SLBUF_MIN_PCT', 'POSITION_TIMEOUT_H', 'POSITION_TIMEOUT_MIN_PCT', 'MAX_SL_BAND_PCT', 'MIN_TFS', 'MIN_TFS_SELL', 'LEG1_MARKET', 'WIN_COMBO_ENABLED'}
GENERAL_KEYS = {'TOP_N', 'MIN_VOLUME_USDT', 'SIGNAL_THRESHOLD_PCT', 'CANDLE_LOOKBACK',
                   'INTERVAL_UNIVERSE_MIN', 'INTERVAL_SIGNALS_MIN', 'INTERVAL_BACKTEST_MIN',
                   'INTERVAL_WALLET_MIN', 'INTERVAL_GUARDS_MIN', 'INTERVAL_ARCHIVE_MIN', 'BACKTEST_TIMEFRAME', 'SLTP_TIMEFRAME', 'BT_OPTIMIZE_THRESHOLD', 'BT_THRESHOLD_GRID', 'BT_SL_MULTS', 'BT_TP_MULTS', 'BT_MIN_TRADES', 'BT_MIN_TEST_TRADES', 'BT_HOLDOUT_PCT', 'BT_FEE_RT_PCT', 'BT_SL_SLIP_PCT', 'BT_WARMUP', 'BT_LOOKBACK'}

RES_FALLBACK = {'1m': '1', '5m': '5', '15m': '15', '30m': '30', '1h': '60', '3h': '180',
                '4h': '240', '6h': '360', '12h': '720', '1D': '1D', '2D': '2D', '3D': '3D'}

DEFAULT_INDICATORS = {
    'SMA':   (True,  'fast=20;slow=50'),
    'EMA':   (True,  'fast=9;slow=21'),
    'RSI':   (True,  'period=14;oversold=30;overbought=70'),
    'MACD':  (True,  'fast=12;slow=26;signal=9'),
    'BB':    (True,  'period=20;std=2.0'),
    'STOCH': (False, 'k=14;d=3;smooth=3'),
    'OBV':   (False, 'period=20'),
    'CCI':   (False, 'period=20'),
    'WPR':   (False, 'period=14'),
    'ATR':   (True,  'period=14'),
}
DEFAULT_TIMEFRAMES = [('15m', '15'), ('1h', '60'), ('4h', '240'), ('1D', '1D')]
DEFAULT_TRADING = {'TRADING_ENABLED': 'خیر', 'DRY_RUN': 'بله', 'MAX_DAILY_TRADES': '10',
                   'ORDER_TYPE': 'market', 'ORDER_SIZE_USDT': '50',
                   'MAX_OPEN_POSITIONS': '3', 'MIN_USDT_BALANCE': '20',
                   'DRY_START_USDT': '1000', 'SL_ATR_MULT': '2.0', 'TP_ATR_MULT': '3.0', 'USE_EXCHANGE_OCO': 'خیر',
                   'TRAIL_ENABLED': 'بله', 'TRAIL_ACTIVATION_PCT': '1.0', 'TRAIL_DISTANCE_PCT': '2.0', 'DUST_USDT': '0.5', 'ORDER_FAIL_COOLDOWN_MIN': '30', 'EXIT_ORDER_TYPE': 'market', 'ENTRY_TTL_MIN': '60', 'REENTRY_COOLDOWN_MIN': '30', 'PUMP_GUARD_PCT': '8', 'LOSS_STREAK_LIMIT': '2', 'LOSS_STREAK_WINDOW_H': '12', 'USE_BT_PARAMS': 'بله', 'MAX_SL_MULT': '1.5', 'TREND_FILTER_ENABLED': 'بله', 'TRAIL_ATR_MULT': '0.5', 'PARTIAL_EXIT_PCT': '50', 'PARTIAL_EXIT_TRIGGER': '2.0', 'ENTRY_MODE': 'limit_pullback', 'PULLBACK_PCT': '1.0', 'SLBUF_MIN_PCT': '0.5', 'POSITION_TIMEOUT_H': '48', 'POSITION_TIMEOUT_MIN_PCT': '0', 'MAX_SL_BAND_PCT': '8.0', 'MIN_TFS': '3', 'MIN_TFS_SELL': '3', 'WIN_COMBO_ENABLED': 'بله'}
DEFAULT_GENERAL = {'TOP_N': '10', 'MIN_VOLUME_USDT': '100000',
                   'SIGNAL_THRESHOLD_PCT': '70', 'CANDLE_LOOKBACK': '300',
                   'INTERVAL_UNIVERSE_MIN': '120', 'INTERVAL_SIGNALS_MIN': '5',
                   'INTERVAL_BACKTEST_MIN': '30', 'INTERVAL_WALLET_MIN': '30',
                  'INTERVAL_GUARDS_MIN': '5', 'INTERVAL_ARCHIVE_MIN': '1440',
                   'BACKTEST_TIMEFRAME': '1D', 'SLTP_TIMEFRAME': '1h', 'BT_OPTIMIZE_THRESHOLD': 'خیر', 'BT_THRESHOLD_GRID': '60;70;80', 'BT_SL_MULTS': '1.5;2.0;2.5', 'BT_TP_MULTS': '2.0;3.0;4.0', 'BT_MIN_TRADES': '8', 'BT_MIN_TEST_TRADES': '2', 'BT_HOLDOUT_PCT': '30', 'BT_FEE_RT_PCT': '0.25', 'BT_SL_SLIP_PCT': '0.35', 'BT_WARMUP': '60', 'BT_LOOKBACK': '480'}


def load_env(path='.env'):
    vals = {}
    try:
        with open(path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                k, v = line.split('=', 1)
                vals[k.strip()] = v.strip()
    except FileNotFoundError:
        pass
    return vals


def truthy(v):
    return str(v).strip().lower() in TRUE_WORDS


def parse_params(s):
    """'fast=20;slow=50' → {'fast': 20.0, 'slow': 50.0}"""
    out = {}
    for part in (s or '').split(';'):
        part = part.strip()
        if '=' in part:
            k, v = part.split('=', 1)
            v = v.strip()
            try:
                out[k.strip()] = float(v)
            except ValueError:
                out[k.strip()] = v
    return out


def _num(raw, default):
    try:
        return float(str(raw).strip().translate(FA_DIGITS).replace(',', ''))
    except (TypeError, ValueError):
        return float(default)


# F9: دامنه‌های مجاز پارامترهای عددی — خارج دامنه → clamp + هشدار
PARAM_RANGES = {
    'SL_ATR_MULT':          (0.5, 5.0),
    'TP_ATR_MULT':          (0.5, 10.0),
    'ORDER_SIZE_USDT':      (1.0, 100.0),
    'MAX_OPEN_POSITIONS':   (1, 20),
    'MAX_DAILY_TRADES':     (1, 200),
    'MIN_USDT_BALANCE':     (0.0, 100.0),
    'DRY_START_USDT':       (1.0, 10000.0),
    'TRAIL_ACTIVATION_PCT': (0.1, 10.0),
    'TRAIL_DISTANCE_PCT':   (0.1, 10.0),
    'SIGNAL_THRESHOLD_PCT': (40.0, 90.0),
    'TOP_N':                (5, 30),
    'CANDLE_LOOKBACK':      (50, 480),
    'MIN_VOLUME_USDT':      (1000.0, 10000000.0),
    'PARTIAL_EXIT_PCT':     (0.0, 90.0),
    'PARTIAL_EXIT_TRIGGER': (0.1, 20.0),
    'POSITION_TIMEOUT_H':   (0.0, 720.0),
    'POSITION_TIMEOUT_MIN_PCT': (-50.0, 50.0),
    'PULLBACK_PCT':         (0.0, 10.0),
    'SLBUF_MIN_PCT':         (0.0, 5.0),
    'TRAIL_ATR_MULT':       (0.0, 3.0),
    'MAX_SL_MULT':          (0.0, 5.0),
    'LOSS_STREAK_LIMIT':    (0, 10),
    'LOSS_STREAK_WINDOW_H': (1.0, 168.0),
    'ORDER_FAIL_COOLDOWN_MIN': (0, 1440),
    'ENTRY_TTL_MIN':        (0, 1440),
    'REENTRY_COOLDOWN_MIN': (0, 1440),
    'DUST_USDT':            (0.01, 10.0),
    'PUMP_GUARD_PCT':       (0.0, 50.0),
    'MAX_SL_BAND_PCT':      (2.0, 20.0),
    'MIN_TFS':              (1.0, 8.0),
    'MIN_TFS_SELL':         (1.0, 8.0),
    'INTERVAL_UNIVERSE_MIN':   (5, 1440),
    'INTERVAL_SIGNALS_MIN':    (1, 1440),
    'INTERVAL_BACKTEST_MIN':   (5, 1440),
    'INTERVAL_WALLET_MIN':     (1, 1440),
    'INTERVAL_GUARDS_MIN':     (1, 1440),
    'INTERVAL_ARCHIVE_MIN':    (60, 10080),
    'BT_MIN_TRADES':         (0, 200),
    'BT_MIN_TEST_TRADES':    (0, 100),
    'BT_HOLDOUT_PCT':        (5.0, 50.0),
    'BT_FEE_RT_PCT':         (0.0, 2.0),
    'BT_SL_SLIP_PCT':        (0.0, 2.0),
    'BT_WARMUP':             (20, 200),
    'BT_LOOKBACK':           (60, 1000),
}


def _clamp(key, value, default):
    """F9: clamp value to PARAM_RANGES[key]. Logs once if clamped."""
    rng = PARAM_RANGES.get(key)
    if rng is None:
        return value
    lo, hi = rng
    original = value
    if value < lo:
        value = lo
    elif value > hi:
        value = hi
    if value != original:
        import logging
        logging.getLogger('nobitex-bot').warning(
            'F9 clamp: %s=%s outside [%s,%s] → clamped to %s',
            key, original, lo, hi, value)
    return value


class Settings:
    def __init__(self):
        self.indicators = {k: {'enabled': en, 'params': parse_params(det)}
                           for k, (en, det) in DEFAULT_INDICATORS.items()}
        self.timeframes = [(lbl, True, res) for lbl, res in DEFAULT_TIMEFRAMES]
        self.trading = dict(DEFAULT_TRADING)
        self.general = dict(DEFAULT_GENERAL)

    @classmethod
    def from_sheet(cls, ws):
        s = cls()
        s.timeframes = []
        for row in ws.get_all_values():
            if not row:
                continue
            key = str(row[0]).strip()
            val = str(row[1]).strip() if len(row) > 1 else ''
            det = str(row[2]).strip() if len(row) > 2 else ''
            if key in INDICATOR_KEYS:
                s.indicators[key] = {'enabled': truthy(val), 'params': parse_params(det)}
            elif key in TIMEFRAME_KEYS:
                s.timeframes.append((key, truthy(val), det or RES_FALLBACK.get(key, key)))
            elif key in TRADING_KEYS:
                s.trading[key] = val
            elif key in GENERAL_KEYS:
                s.general[key] = val
        if not s.timeframes:
            s.timeframes = [(lbl, True, res) for lbl, res in DEFAULT_TIMEFRAMES]
        return s

    # ---------- عمومی ----------
    @property
    def top_n(self):
        return _clamp('TOP_N', max(1, int(_num(self.general.get('TOP_N'), 10))), 10)

    @property
    def min_volume(self):
        return _num(self.general.get('MIN_VOLUME_USDT'), 100000)

    @property
    def threshold_pct(self):
        return _clamp('SIGNAL_THRESHOLD_PCT', min(100.0, max(1.0, _num(self.general.get('SIGNAL_THRESHOLD_PCT'), 70))), 70)

    @property
    def lookback(self):
        return _clamp('CANDLE_LOOKBACK', max(50, min(int(_num(self.general.get('CANDLE_LOOKBACK'), 300)), 480)), 300)

    @property
    def active_timeframes(self):
        out = [(lbl, res) for lbl, en, res in self.timeframes if en]
        return out or [('1h', '60')]

    @property
    def voting_indicators(self):
        return [k for k, v in self.indicators.items() if v['enabled'] and k != 'ATR']

    # ---------- معاملات ----------
    def _tnum(self, key, default):
        # F9: clamp applied automatically for all trading params
        return _clamp(key, _num(self.trading.get(key), default), default)

    @property
    def trading_enabled(self):
        return truthy(self.trading.get('TRADING_ENABLED', 'خیر'))

    @property
    def dry_run(self):
        return truthy(self.trading.get('DRY_RUN', 'بله'))

    @property
    def max_daily_trades(self):
        return int(self._tnum('MAX_DAILY_TRADES', 10))

    @property
    def order_type(self):
        return str(self.trading.get('ORDER_TYPE', 'market')).strip().lower()

    @property
    def reentry_cooldown_min(self):
        """پس از خروج زیان‌ده (SL)، خرید همان نماد به این مدت ممنوع. 0 = خاموش"""
        return max(0.0, self._tnum('REENTRY_COOLDOWN_MIN', 30))

    @property
    def use_bt_params(self):
        """G-bt: per-symbol bt_params (slm/tpm/thr) imposed on signals.
        no = sheet params (SL/TP/threshold) rule ALL symbols; backtest tab
        stays informational."""
        return truthy(self.trading.get('USE_BT_PARAMS', 'بله'))

    @property
    def max_sl_mult(self):
        """G-maxsl: ceiling on SL multiplier from backtest edges.
        Backtest may suggest x2.5 for high-volatility new symbols;
        this caps it (e.g. 1.5) to limit worst-case loss per trade.
        0 = no cap (backtest wins)."""
        return max(0.0, self._tnum('MAX_SL_MULT', 1.5))

    @property
    def max_sl_band_pct(self):
        """G-bandcap: max SL band width (%). Reject entries with wider SL."""
        return max(2.0, self._tnum('MAX_SL_BAND_PCT', 8.0))

    @property
    def min_tfs(self):
        """حداقل تعداد تایم‌فریم هم‌جهت برای صدور سیگنال (قابل تنظیم از شیت)"""
        return max(1, int(self._tnum('MIN_TFS', 3)))

    @property
    def min_tfs_sell(self):
        """P1: حداقل TF رأی فروش برای خروج سیگنالی — پیش‌فرض 3 = رفتار فعلی"""
        return max(1, int(self._tnum('MIN_TFS_SELL', 3)))

    @property
    def trend_filter_enabled(self):
        """G-trend: skip all buys when BTC 4h SMA20 < SMA50 (bearish regime)."""
        return truthy(self.trading.get('TREND_FILTER_ENABLED', 'بله'))

    @property
    def trail_atr_mult(self):
        """G-trail: trailing distance as multiple of ATR(1h). 0 = use percentage."""
        return max(0.0, self._tnum('TRAIL_ATR_MULT', 0.5))

    @property
    def partial_exit_pct(self):
        """G-pexit: percentage of position to sell at trigger. 0 = disabled."""
        return min(90.0, max(0.0, self._tnum('PARTIAL_EXIT_PCT', 50)))

    @property
    def partial_exit_trigger(self):
        """G-pexit: profit percentage that triggers partial exit."""
        return max(0.1, self._tnum('PARTIAL_EXIT_TRIGGER', 2.0))

    @property
    def entry_mode(self):
        """G-entry: 'market' or 'limit_pullback'."""
        return str(self.trading.get('ENTRY_MODE', 'limit_pullback')).strip().lower()

    @property
    def leg1_market(self):
        """G-mhalf: پایهٔ اول Scale به‌صورت مارکت (بله/خیر) — پایهٔ دوم limit نیم‌درصد پایین‌تر"""
        return truthy(self.trading.get('LEG1_MARKET', 'خیر'))

    @property
    def win_combo_enabled(self):
        """G-wincombo: هندسهٔ per-symbol از تب «ترکیب برنده» (بله/خیر)"""
        return truthy(self.trading.get('WIN_COMBO_ENABLED', 'بله'))

    @property
    def pullback_pct(self):
        """G-entry: pullback percentage for limit entry."""
        return max(0.0, min(10.0, self._tnum('PULLBACK_PCT', 1.0)))

    @property
    def slbuf_min_pct(self):
        """P4/G-slbuf: حداقل بافر SL نسبت به fill تخمینی (٪). 0 = خاموش"""
        return min(5.0, max(0.0, self._tnum('SLBUF_MIN_PCT', 0.5)))

    @property
    def position_timeout_h(self):
        """G-timeout: max hours to hold a position. 0 = no timeout."""
        return max(0.0, self._tnum('POSITION_TIMEOUT_H', 48))

    @property
    def position_timeout_min_pct(self):
        """G-timeout: sell if unrealized P&L% is below this after timeout."""
        return self._tnum('POSITION_TIMEOUT_MIN_PCT', 0)

    @property
    def pump_guard_pct(self):
        # G3.2: حداکثر فاصله قیمت از SMA20(1h) برای ورود (٪) — ضد تعقیب پامپ. 0 = خاموش
        return min(50.0, max(0.0, self._tnum('PUMP_GUARD_PCT', 8)))

    @property
    def loss_streak_limit(self):
        # G3.2: با این تعداد خروج زیان‌ده در بازه اخیر، خرید همان نماد ممنوع. 0 = خاموش
        return min(10, max(0, int(self._tnum('LOSS_STREAK_LIMIT', 2))))

    @property
    def loss_streak_window_h(self):
        # G3.2: بازه گارد ضد-چاقو (ساعت)
        return min(72.0, max(1.0, self._tnum('LOSS_STREAK_WINDOW_H', 12)))

    @property
    def entry_ttl_min(self):
        return max(0.0, self._tnum('ENTRY_TTL_MIN', 60))

    @property
    def exit_order_type(self):
        return str(self.trading.get('EXIT_ORDER_TYPE', 'market')).strip().lower()

    @property
    def order_size_usdt(self):
        return self._tnum('ORDER_SIZE_USDT', 50)

    @property
    def max_open_positions(self):
        return int(self._tnum('MAX_OPEN_POSITIONS', 3))

    @property
    def min_usdt_balance(self):
        return self._tnum('MIN_USDT_BALANCE', 20)

    @property
    def dry_start_usdt(self):
        return self._tnum('DRY_START_USDT', 1000)

    @property
    def sl_atr_mult(self):
        return self._tnum('SL_ATR_MULT', 2.0)

    @property
    def tp_atr_mult(self):
        return self._tnum('TP_ATR_MULT', 3.0)

    @property
    def dust_usdt(self):
        return self._tnum('DUST_USDT', 0.5)

    @property
    def order_fail_cooldown_min(self):
        return max(0.0, self._tnum('ORDER_FAIL_COOLDOWN_MIN', 30))

    @property
    def use_exchange_oco(self):
        return truthy(self.trading.get('USE_EXCHANGE_OCO', 'خیر'))

    @property
    def trail_enabled(self):
        return truthy(self.trading.get('TRAIL_ENABLED', 'بله'))

    @property
    def trail_activation_pct(self):
        return self._tnum('TRAIL_ACTIVATION_PCT', 1.0)

    @property
    def trail_distance_pct(self):
        return self._tnum('TRAIL_DISTANCE_PCT', 2.0)

    # ---------- بازه چرخه‌ها (دقیقه) — قابل تغییر از شیت ----------
    def _interval(self, key, default):
        return _clamp(key, max(1, int(_num(self.general.get(key), default))), default)

    @property
    def interval_universe_min(self):
        return self._interval('INTERVAL_UNIVERSE_MIN', 120)

    @property
    def interval_signals_min(self):
        return self._interval('INTERVAL_SIGNALS_MIN', 5)

    @property
    def interval_backtest_min(self):
        return self._interval('INTERVAL_BACKTEST_MIN', 30)

    @property
    def interval_wallet_min(self):
        return self._interval('INTERVAL_WALLET_MIN', 30)

    @property
    def interval_guards_min(self):
        return self._interval('INTERVAL_GUARDS_MIN', 5)

    @property
    def interval_archive_min(self):
        """P3: فاصلهٔ چرخهٔ آرشیو سفارشات (دقیقه) — پیش‌فرض 1440 = 24 ساعت"""
        return self._interval('INTERVAL_ARCHIVE_MIN', 1440)

    @property
    def sltp_timeframe(self):
        """تایم‌فریم مرجع محاسبه SL/TP — باید در فهرست فعال باشد؛ در غیر این صورت اولین فعال"""
        label = str(self.general.get('SLTP_TIMEFRAME') or '1h').strip()
        act = dict(self.active_timeframes)
        if label in act:
            return label, act[label]
        first = self.active_timeframes[0]
        return first[0], first[1]

    @property
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
        return max(60, min(1000, int(_num(self.general.get('BT_LOOKBACK'), 480))))
