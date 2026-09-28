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
                'ORDER_FAIL_COOLDOWN_MIN'}
GENERAL_KEYS = {'TOP_N', 'MIN_VOLUME_USDT', 'SIGNAL_THRESHOLD_PCT', 'CANDLE_LOOKBACK',
                   'INTERVAL_UNIVERSE_MIN', 'INTERVAL_SIGNALS_MIN', 'INTERVAL_BACKTEST_MIN',
                   'INTERVAL_WALLET_MIN', 'BACKTEST_TIMEFRAME'}

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
                   'TRAIL_ENABLED': 'بله', 'TRAIL_ACTIVATION_PCT': '1.0', 'TRAIL_DISTANCE_PCT': '2.0', 'DUST_USDT': '0.5', 'ORDER_FAIL_COOLDOWN_MIN': '30'}
DEFAULT_GENERAL = {'TOP_N': '10', 'MIN_VOLUME_USDT': '100000',
                   'SIGNAL_THRESHOLD_PCT': '70', 'CANDLE_LOOKBACK': '300',
                   'INTERVAL_UNIVERSE_MIN': '120', 'INTERVAL_SIGNALS_MIN': '5',
                   'INTERVAL_BACKTEST_MIN': '30', 'INTERVAL_WALLET_MIN': '30',
                   'BACKTEST_TIMEFRAME': '1D'}


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
        return max(1, int(_num(self.general.get('TOP_N'), 10)))

    @property
    def min_volume(self):
        return _num(self.general.get('MIN_VOLUME_USDT'), 100000)

    @property
    def threshold_pct(self):
        return min(100.0, max(1.0, _num(self.general.get('SIGNAL_THRESHOLD_PCT'), 70)))

    @property
    def lookback(self):
        return max(50, min(int(_num(self.general.get('CANDLE_LOOKBACK'), 300)), 480))

    @property
    def active_timeframes(self):
        out = [(lbl, res) for lbl, en, res in self.timeframes if en]
        return out or [('1h', '60')]

    @property
    def voting_indicators(self):
        return [k for k, v in self.indicators.items() if v['enabled'] and k != 'ATR']

    # ---------- معاملات ----------
    def _tnum(self, key, default):
        return _num(self.trading.get(key), default)

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
        return max(1, int(_num(self.general.get(key), default)))

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
    def backtest_timeframe(self):
        return str(self.general.get('BACKSET_TIMEFRAME') or
                   self.general.get('BACKTEST_TIMEFRAME') or '1D').strip()
