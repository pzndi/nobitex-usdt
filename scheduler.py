#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scheduler.py — زمان‌بند چرخه‌های ربات (شبانه‌روزی)
کرون هر ۱ دقیقه این فایل را صدا می‌زند؛ فواصل چرخه‌ها هر بار از تب «تنظیمات»
خوانده می‌شود — تغییر INTERVAL_* در شیت از تیک بعدی اعمال می‌شود:
  universe ← INTERVAL_UNIVERSE_MIN (پیش‌فرض ۱۲۰) → تب dynamic universe
  backtest ← INTERVAL_BACKTEST_MIN (۳۰)          → تب بک تست + پارامتر هر نماد
  signals  ← INTERVAL_SIGNALS_MIN  (۵)           → تب استراتژی + رتبه‌بندی معاملات
                                                   + سفارشگزاری + سفارشات + SL متحرک
  wallet   ← INTERVAL_WALLET_MIN   (۳۰)          → تب کیف پول + گزارش
اجرا دستی همه چرخه‌ها: venv/bin/python scheduler.py --force
"""
import json
import logging
import os
import sys
import time

import net_timeout  # noqa: F401 — تایم‌اوت پیش‌فرض HTTP (F1)

import gspread

from settings import Settings, load_env
import main as m
import strategy_engine as se
import trader
import backtest

log = logging.getLogger('nobitex-bot')
STATE_FILE = 'state.json'


def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {'last': {}, 'universe': [], 'bt_params': {}, 'last_rows': []}


def save_state(s):
    tmp = STATE_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(s, f, ensure_ascii=False)
    os.replace(tmp, STATE_FILE)


def due(state, task, interval_min):
    return (time.time() - state['last'].get(task, 0)) >= interval_min * 60


def run_universe(sh, st, state):
    stats = m.fetch_stats()
    if not stats:
        log.error('چرخه universe: آمار بازار دریافت نشد')
        return False
    ranked = m.rank_markets(stats, st)
    if not ranked:
        log.error('چرخه universe: بازار واجد شرایطی نیست')
        return False
    m.update_universe(sh.worksheet('dynamic universe'), ranked, stats, st)
    state['universe'] = [x['symbol'] for x in ranked[:st.top_n]]
    log.info('چرخه universe: %s', '، '.join(state['universe']))
    return True


def run_backtest(sh, st, state):
    symbols = state.get('universe') or []
    if not symbols:
        return False
    state['bt_params'] = backtest.run(sh, st, symbols) or {}
    return True


def _ref_atr(st, sym, cache):
    """ATR تایم‌فریم مرجع برای SL/TP یکنواخت (کش به‌ازای چرخه)"""
    label, res = st.sltp_timeframe
    key = (sym, res)
    if key in cache:
        return cache[key]
    c = se.fetch_candles(sym + 'USDT', res, 120)
    val = None
    if c and len(c['c']) > 50:
        v = se.prepare_votes(c, st)
        val = v['atr'][-1]
    cache[key] = val
    return val


def run_signals(sh, st, state):
    symbols = state.get('universe') or []
    if not symbols:
        return False
    bt = state.get('bt_params') or {}
    ref_cache = {}
    rows = []
    for sym in symbols:
        bp = bt.get(sym) or {}
        for label, res in st.active_timeframes:
            c = se.fetch_candles(sym + 'USDT', res, st.lookback)
            if not c:
                rows.append([sym, label, '', '', '—', '', '', '', '', '', '', 'خطا در دریافت کندل'])
                continue
            r = se.analyze(c, st, thr=bp.get('thr'), slm=bp.get('slm'), tpm=bp.get('tpm'),
                           atr_ref=_ref_atr(st, sym, ref_cache))
            rows.append([sym, label, r['price'], r['trend'], r['signal'],
                         r['strength'], r['buy'], r['sell'], r['neutral'],
                         r['sl'], r['tp'], r['note']])
            time.sleep(0.15)
    m.update_strategy(sh.worksheet('استراتژی'), rows)
    state['last_rows'] = rows
    trader.run(sh, st, rows, state)
    return True


def run_wallet(sh, st, state):
    rows = state.get('last_rows') or []
    trader.refresh_wallet(sh, st, rows)
    trader.update_report(sh, st, rows)


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
    force = '--force' in sys.argv
    sheet_id = load_env().get('SHEET_ID')
    if not sheet_id:
        log.error('SHEET_ID در .env تعریف نشده')
        return 1
    gc = gspread.service_account(filename='service_account.json')
    sh = gc.open_by_key(sheet_id)
    st = Settings.from_sheet(sh.worksheet('تنظیمات'))
    state = load_state()
    now = time.time()

    tasks = [
        ('universe', st.interval_universe_min, lambda: run_universe(sh, st, state)),
        ('backtest', st.interval_backtest_min, lambda: run_backtest(sh, st, state)),
        ('signals', st.interval_signals_min, lambda: run_signals(sh, st, state)),
        ('wallet', st.interval_wallet_min, lambda: run_wallet(sh, st, state)),
    ]
    ran = []
    for name, interval, fn in tasks:
        if force or due(state, name, interval):
            try:
                fn()
                state['last'][name] = now
                ran.append(name)
            except Exception:
                state['last'][name] = now  # جلوگیری از کوبیدن API در خطای پایدار
                log.exception('خطا در چرخه %s', name)
    save_state(state)
    if ran:
        log.info('چرخه‌های این تیک: %s', '، '.join(ran))
    else:
        log.info('تیک: چیزی سررسید نبود (universe=%d | backtest=%d | signals=%d | wallet=%d دقیقه)',
                 st.interval_universe_min, st.interval_backtest_min,
                 st.interval_signals_min, st.interval_wallet_min)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
