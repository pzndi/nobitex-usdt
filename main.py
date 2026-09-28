#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
main.py — چرخه کامل ربات:
  ۱) خواندن تنظیمات از تب «تنظیمات» (شیت = پنل کنترل)
  ۲) آمار بازارها از API نوبیتکس → رتبه‌بندی نقدشوندگی → تب dynamic universe
  ۳) کندل‌ها از API → اندیکاتورها → رأی‌گیری ensemble → تب «استراتژی»
  ۴) هوک معاملات (ماژول trader در گام ۴ اضافه می‌شود)
"""
import logging
import time

import gspread
import requests

from settings import Settings, load_env
import strategy_engine as se

log = logging.getLogger('nobitex-bot')

STATS_URL = 'https://apiv2.nobitex.ir/market/stats'
HEADERS = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) nobitex-sheet-updater/2.0'}

try:
    import jdatetime

    def jnow():
        return jdatetime.datetime.now().strftime('%Y/%m/%d %H:%M')
except ImportError:
    def jnow():
        return time.strftime('%Y-%m-%d %H:%M')


def fetch_stats(retries=3):
    last_err = None
    for attempt in range(1, retries + 1):
        for method in ('get', 'post'):
            try:
                if method == 'get':
                    r = requests.get(STATS_URL, headers=HEADERS, timeout=60)
                else:
                    r = requests.post(STATS_URL, json={}, headers=HEADERS, timeout=60)
                if r.ok:
                    d = r.json()
                    if d.get('status') == 'ok':
                        return d.get('stats', {})
                    last_err = f"status={d.get('status')}"
            except (requests.RequestException, ValueError) as e:
                last_err = str(e)
        if attempt < retries:
            time.sleep(10 * attempt)
    log.error('دریافت آمار بازارها ناموفق: %s', last_err)
    return None


def _num_field(s, keys):
    """اولین فیلد غیرصفر از فهرست نام‌های ممکن (مقادیر رشته‌ای API هم تبدیل می‌شوند)"""
    for k in keys:
        try:
            v = float(s.get(k) or 0)
        except (TypeError, ValueError):
            v = 0.0
        if v != 0:
            return v
    return 0.0


def rank_markets(stats, st):
    """فیلتر و رتبه‌بندی بازارهای USDT بر اساس نقدشوندگی (حجم USDT / اسپرد)

    نام فیلدها در apiv2 نوبیتکس: حجم USDT → volumeDst ، تغییر روزانه → dayChange
    (نام‌های جایگزین هم برای مقاومت بررسی می‌شوند)
    """
    out = []
    for name, s in stats.items():
        lname = str(name).lower()
        if not lname.endswith('-usdt'):
            continue
        if s.get('isClosed'):
            continue
        try:
            best_sell = float(s.get('bestSell') or 0)
            best_buy = float(s.get('bestBuy') or 0)
        except (TypeError, ValueError):
            continue
        if best_sell <= 0 or best_buy <= 0:
            continue
        vol = _num_field(s, ('volumeDst', 'volumeQuote', 'volume'))
        if vol < st.min_volume:
            continue
        change = _num_field(s, ('dayChange', 'change', 'volumeChange'))
        spread = (best_sell - best_buy) / best_sell * 100.0
        out.append({'symbol': lname[:-5].upper(), 'name': name, 'volume': vol,
                    'spread': spread, 'change': change,
                    'score': vol / (1.0 + spread)})
    out.sort(key=lambda m: m['score'], reverse=True)
    return out


def update_universe(ws, ranked, stats, st):
    usdt_rls = stats.get('usdt-rls') or {}
    try:
        rate = float(usdt_rls.get('bestSell') or 0)
    except (TypeError, ValueError):
        rate = 0
    ws.update(values=[['آخرین به‌روزرسانی', jnow(), 'نرخ تتر (ریال)', rate or '—']],
              range_name='A1:D1')
    ws.update(values=[['وضعیت', f'✓ API نوبیتکس سالم', 'بازارهای واجد شرایط', len(ranked)]],
              range_name='A2:D2')
    ws.update(values=[['رتبه', 'نماد', 'حجم ۲۴ ساعته (USDT)', 'اسپرد (٪)',
                       'تغییر ۲۴ ساعته (٪)', 'امتیاز نقدشوندگی']],
              range_name='A3:F3')
    n_rows = max(10, st.top_n)
    data = []
    for i in range(n_rows):
        if i < len(ranked):
            m = ranked[i]
            data.append([i + 1, m['symbol'], round(m['volume']), round(m['spread'], 2),
                         round(m['change'], 2), round(m['score'])])
        else:
            data.append([''] * 6)
    ws.update(values=data, range_name=f'A4:F{3 + n_rows}')
    log.info('تب dynamic universe به‌روزرسانی شد — %d نماد برتر',
             min(len(ranked), st.top_n))


def update_strategy(ws, rows):
    n = max(40, len(rows))
    data = [r + [''] * (12 - len(r)) for r in rows]
    while len(data) < n:
        data.append([''] * 12)
    ws.update(values=[['🎯 سیگنال‌ها برای نمادهای dynamic universe',
                       'آخرین به‌روزرسانی:', jnow()]],
              range_name='A1:C1')
    ws.update(values=data, range_name=f'A4:L{3 + n}')
    log.info('تب «استراتژی» نوشته شد — %d ردیف', len(rows))


def main():
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s [%(levelname)s] %(message)s')
    env = load_env()
    sheet_id = env.get('SHEET_ID')
    if not sheet_id:
        log.error('SHEET_ID در فایل .env تعریف نشده است')
        return 1

    gc = gspread.service_account(filename='service_account.json')
    sh = gc.open_by_key(sheet_id)

    # ۱) تنظیمات — از شیت، تازه در هر اجرا
    try:
        settings = Settings.from_sheet(sh.worksheet('تنظیمات'))
    except gspread.WorksheetNotFound:
        log.error('تب «تنظیمات» پیدا نشد — ابتدا setup_sheets.py را اجرا کنید')
        return 1
    log.info('تنظیمات: اندیکاتورهای فعال %s | تایم‌فریم‌ها: %s | آستانه: %.0f٪',
             ','.join(settings.voting_indicators),
             ','.join(l for l, _ in settings.active_timeframes),
             settings.threshold_pct)

    # ۲) آمار بازار + تب universe
    stats = fetch_stats()
    if not stats:
        log.error('اجرا متوقف شد — آمار بازارها دریافت نشد')
        return 1
    ranked = rank_markets(stats, settings)
    if not ranked:
        log.error('هیچ بازار واجد شرایطی یافت نشد')
        return 1
    log.info('%d بازار واجد شرایط — برترین‌ها: %s', len(ranked),
             ', '.join(m['symbol'] for m in ranked[:settings.top_n]))
    update_universe(sh.worksheet('dynamic universe'), ranked, stats, settings)

    # ۳) تحلیل و سیگنال‌ها
    rows = []
    for m in ranked[:settings.top_n]:
        udf = m['symbol'] + 'USDT'
        for label, res in settings.active_timeframes:
            c = se.fetch_candles(udf, res, settings.lookback)
            if not c:
                rows.append([m['symbol'], label, '', '', '—', '', '', '', '',
                             '', '', 'خطا در دریافت کندل'])
                continue
            r = se.analyze(c, settings)
            rows.append([m['symbol'], label, r['price'], r['trend'], r['signal'],
                         r['strength'], r['buy'], r['sell'], r['neutral'],
                         r['sl'], r['tp'], r['note']])
            time.sleep(0.2)
    update_strategy(sh.worksheet('استراتژی'), rows)

    # ۴) هوک معاملات — گام ۴
    if settings.trading_enabled:
        try:
            import trader
            trader.run(sh, settings, rows)
        except ImportError:
            log.warning('TRADING_ENABLED فعال است اما ماژول trader هنوز اضافه نشده (گام ۴)')
    else:
        log.info('معاملات غیرفعال (TRADING_ENABLED=خیر) — فقط تولید سیگنال')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
