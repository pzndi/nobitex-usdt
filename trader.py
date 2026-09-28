#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
trader.py — ماژول معاملات ربات
- احراز هویت نوبیتکس apiv2: هدرهای Nobitex-Key/Signature/Timestamp (امضای Ed25519)
- تب «کیف پول»: مستقیم از API صرافی
- همگام‌سازی وضعیت سفارش‌های واقعی از API → ستون «وضعیت» تب معاملات
- انتخاب نماد: رأی‌گیری بین تایم‌فریم‌ها (حداقل ۲ تایم‌فریم + اکثریت + بیشتر از فروش)
- سقف‌های ایمنی: MAX_DAILY_TRADES / MAX_OPEN_POSITIONS / MIN_USDT_BALANCE

وضعیت‌های دفتر معاملات:
  شبیه‌سازی شده = سفارش dry-run (بدون ارسال به صرافی — اجرا شده فرض می‌شود)
  ثبت‌شده = سفارش واقعی ثبت شده، در انتظار تأیید وضعیت از API
  باز / پر شد / در انتظار تریگر / لغو شده / بخشی پر و لغو شد = وضعیت واقعی از API
  (مقادیر رسمی apiv2: Active / Done / Inactive / Canceled / Canceled با matchedAmount>0)
  ناموفق = خطای API هنگام ثبت سفارش واقعی
"""
import logging
import math
import sys
import time
from datetime import datetime

import requests

from settings import load_env
from strategy_engine import fmt_price

try:
    import jdatetime

    def jnow():
        return jdatetime.datetime.now().strftime('%Y/%m/%d %H:%M')

    def jtoday():
        return jdatetime.date.today().strftime('%Y/%m/%d')
except ImportError:
    def jnow():
        return datetime.now().strftime('%Y-%m-%d %H:%M')

    def jtoday():
        return datetime.now().strftime('%Y-%m-%d')

log = logging.getLogger('nobitex-bot')

BASE = 'https://apiv2.nobitex.ir'
TIMEOUT = 60

TRADES_TAB = 'معاملات'
WALLET_TAB = 'کیف پول'
UNIVERSE_TAB = 'dynamic universe'

ST_DRY = 'شبیه‌سازی شده'
ST_PLACED = 'ثبت‌شده'
ST_OPEN = 'باز'
ST_FILLED = 'پر شد'
ST_PARTIAL = 'بخشی پر و لغو شد'
ST_CANCELLED = 'لغو شده'
ST_PENDING_STOP = 'در انتظار تریگر'
EXECUTED = {ST_DRY, ST_FILLED, ST_PARTIAL}
OPENISH = {ST_PLACED, ST_OPEN, ST_PENDING_STOP}

MIN_TFS = 2  # حداقل تعداد تایم‌فریم هم‌جهت برای صدور سفارش


# ================= کلاینت API معاملاتی =================
class NobitexClient:
    """پوشش امضاشده روی API معاملاتی — Nobitex-Key/Signature/Timestamp
    (امضای Ed25519 روی timestamp+METHOD+full_path+raw_body طبق مستندات رسمی apiv2)"""

    def __init__(self, public_key, private_key_b64):
        from nobitex_auth import SignedClient
        self._sc = SignedClient(public_key, private_key_b64)

    def wallets(self):
        return self._sc.post('/users/wallets/list', {})

    def wallet_balance(self, currency):
        for key in ('wallet', 'currency'):
            code, data = self._sc.post('/users/wallets/balance', {key: currency.lower()})
            if code == 200:
                return code, data
        return code, data

    def open_orders(self):
        # مستندات apiv2: GET /market/orders/list
        code, data = self._sc.get('/market/orders/list')
        if code not in (200, 201):
            code, data = self._sc.post('/market/orders/list', {})
        return code, data

    def order_status(self, order_id):
        return self._sc.post('/market/orders/status', {'id': str(order_id)})

    def trades_today(self):
        """تعداد معاملات امروز (به وقت تهران) از API نوبیتکس — منبع حقیقت.
        timestamp ها ISO8601 UTC هستند؛ مرز نیمه‌شب تهران (UTC+3:30) محاسبه می‌شود.
        صفحه اول پاسخ (۳۰ معامله اخیر) پیمایش می‌شود — برای سقف روزانه کافی است."""
        import datetime as dt
        code, data = self._sc.get('/market/trades/list')
        if code != 200 or not isinstance(data, dict):
            return None
        offset = dt.timedelta(hours=3, minutes=30)
        now_shifted = dt.datetime.now(dt.timezone.utc) + offset
        midnight = dt.datetime.combine(now_shifted.date(), dt.time.min,
                                       tzinfo=dt.timezone.utc)
        n = 0
        for tr in (data.get('trades') or []):
            ts = tr.get('timestamp')
            if not ts:
                continue
            try:
                t = dt.datetime.fromisoformat(str(ts).replace('Z', '+00:00'))
            except ValueError:
                continue
            if t + offset >= midnight:
                n += 1
        return n

    def place_order(self, order_type, symbol, price, volume, is_market,
                    client_order_id=None):
        """ثبت سفارش اسپات apiv2 — طبق مستندات p117 و پروب‌های زنده:
        amount (واحد srcCurrency) + execution (limit/market/stop_market/stop_limit)
        + clientOrderId یکتا در میان سفارش‌های باز"""
        payload = {'type': order_type,
                   'market': f'{symbol}USDT',
                   'srcCurrency': symbol.lower(),
                   'dstCurrency': 'usdt',
                   'price': str(price),
                   'amount': str(volume),
                   'execution': 'market' if is_market else 'limit'}
        if client_order_id:
            payload['clientOrderId'] = client_order_id
        return self._sc.post('/market/orders/add', payload)


def make_client():
    """کلاینت امضاشده از .env — None یعنی کلیدها ناقص‌اند"""
    e = load_env()
    k = (e.get('NOBITEX_API_KEY') or '').strip()
    s = (e.get('NOBITEX_API_SECRET') or '').strip()
    return NobitexClient(k, s) if k and s else None


# ================= ابزارها =================
def parse_price(s):
    try:
        return float(str(s).replace(',', ''))
    except (TypeError, ValueError):
        return None


def fmt_bal(v):
    if v == 0:
        return '0'
    if v >= 1000:
        return f'{v:,.2f}'
    if v >= 1:
        return f'{v:.4f}'
    return f'{v:.8f}'


def currency_available(client, currency):
    """موجودی قابل استفاده یک ارز از API (با تحمل تفاوت فرمت پاسخ)"""
    currency = currency.lower()
    code, data = client.wallet_balance(currency)
    if code == 200 and isinstance(data, dict):
        for k in ('activeBalance', 'balance'):
            if data.get(k) not in (None, ''):
                try:
                    return float(data[k])
                except (TypeError, ValueError):
                    pass
    code, data = client.wallets()
    wl = data.get('wallets') if isinstance(data, dict) else (data if isinstance(data, list) else None)
    if isinstance(wl, list):
        for w in wl:
            if str(w.get('currency', '')).lower() == currency:
                for k in ('activeBalance', 'active_balance', 'balance'):
                    if w.get(k) not in (None, ''):
                        try:
                            return float(w[k])
                        except (TypeError, ValueError):
                            pass
    return None


# ================= تجمیع سیگنال‌ها =================
def aggregate_signals(rows):
    """رأی‌گیری بین تایم‌فریم‌ها برای هر نماد — rows همان ردیف‌های تب استراتژی"""
    agg = {}
    for r in rows:
        if len(r) < 11 or not r[0]:
            continue
        sym = str(r[0]).upper()
        a = agg.setdefault(sym, {'buys': 0, 'sells': 0, 'total': 0, 'best': None})
        a['total'] += 1
        sig = str(r[4]).strip()
        if sig == 'خرید':
            a['buys'] += 1
            try:
                strength = int(float(r[5]))
            except (TypeError, ValueError):
                strength = 0
            if not a['best'] or strength > a['best'][0]:
                a['best'] = (strength, list(r))
        elif sig == 'فروش':
            a['sells'] += 1
    return agg


def is_buy_candidate(a):
    return (a['buys'] >= MIN_TFS and a['buys'] >= (a['total'] + 1) // 2
            and a['buys'] > a['sells'])


def is_sell_candidate(a):
    return (a['sells'] >= MIN_TFS and a['sells'] >= (a['total'] + 1) // 2
            and a['sells'] > a['buys'])


# ================= دفتر معاملات (حافظه ربات) =================
def read_ledger(ws):
    """خواندن دفتر معاملات:
    - پوزیشن‌های باز با میانگین قیمت ورود (حسابداری به روش میانگین هزینه) و آخرین حد ضرر/سود
    - سفارش‌های باز، شمارش معاملات امروز (شمسی)، خالص خرج شبیه‌سازی
    """
    vals = ws.get_all_values()
    led = {'positions': {}, 'pending': set(), 'daily_count': 0,
           'dry_net_spent': 0.0, 'rows': []}
    today = jtoday()
    bought_vol, bought_cost, sold_vol = {}, {}, {}
    sltp = {}
    for i, r in enumerate(vals[3:]):  # داده از ردیف ۴
        if not any(str(c).strip() for c in r):
            continue
        r = list(r) + [''] * (13 - len(r))
        led['rows'].append((i + 4, r))
        t, sym, act = r[0].strip(), r[1].strip().upper(), r[2].strip()
        status = r[11].strip()
        try:
            vol = float(str(r[6]).replace(',', '') or 0)
        except ValueError:
            vol = 0.0
        try:
            amt = float(str(r[7]).replace(',', '') or 0)
        except ValueError:
            amt = 0.0
        if act not in ('خرید', 'فروش'):
            continue
        if t.startswith(today):
            led['daily_count'] += 1
        if status in OPENISH:
            led['pending'].add(sym)
        if status in EXECUTED:
            if act == 'خرید':
                bought_vol[sym] = bought_vol.get(sym, 0.0) + vol
                bought_cost[sym] = bought_cost.get(sym, 0.0) + amt
                if status == ST_DRY:
                    led['dry_net_spent'] += amt
                sl_p, tp_p = parse_price(r[8]), parse_price(r[9])
                if sl_p and tp_p:
                    sltp[sym] = (sl_p, tp_p)
            else:
                sold_vol[sym] = sold_vol.get(sym, 0.0) + vol
                if status == ST_DRY:
                    led['dry_net_spent'] -= amt
    for sym in set(list(bought_vol) + list(sold_vol)):
        net = bought_vol.get(sym, 0.0) - sold_vol.get(sym, 0.0)
        if net > 1e-12:
            entry = (bought_cost[sym] / bought_vol[sym]) if bought_vol.get(sym) else None
            sl, tp = sltp.get(sym, (None, None))
            led['positions'][sym] = {'volume': net, 'entry_price': entry,
                                     'sl': sl, 'tp': tp}
    return led


# ================= همگام‌سازی وضعیت از API =================
def sync_order_statuses(ws_t, led, client):
    """همگام‌سازی وضعیت سفارش‌های واقعی از API
    مقادیر رسمی (مستندات apiv2):
      Active = فعال در بازار | Done = کامل پر شده
      Inactive = سفارش حد ضرر هنوز به قیمت توقف نرسیده
      Canceled = لغو شده — اگر matchedAmount > 0 باشد یعنی بخشی پر شده و لغو شده"""
    api_map = {'Active': ST_OPEN, 'Done': ST_FILLED,
               'Inactive': ST_PENDING_STOP, 'Canceled': ST_CANCELLED}
    for row_num, r in led['rows']:
        oid = str(r[10]).strip()
        if not oid or oid == '—' or str(r[11]).strip() not in OPENISH:
            continue
        code, data = client.order_status(oid)
        o = data.get('order') if isinstance(data, dict) else None
        raw = o.get('status') if isinstance(o, dict) else None
        if raw not in api_map:
            log.warning('وضعیت سفارش %s قابل تشخیص نبود: HTTP %s | %s', oid, code, str(data)[:120])
            continue
        new_st = api_map[raw]
        vol_update = None
        if raw == 'Canceled':
            try:
                matched = float(o.get('matchedAmount') or 0)
            except (TypeError, ValueError):
                matched = 0.0
            if matched > 0:
                new_st = ST_PARTIAL
                vol_update = matched
        if new_st != str(r[11]).strip():
            ws_t.update_cell(row_num, 12, new_st)
            if vol_update is not None:
                ws_t.update_cell(row_num, 7, vol_update)
            log.info('وضعیت سفارش %s → %s', oid, new_st)


# ================= اجرای سفارش =================
def buy_one(st, ws_t, client, dry, sym, a, price, led, coid=None):
    row = a['best'][1]
    tf, sl, tp = row[1], row[9], row[10]
    vol = math.floor((st.order_size_usdt / price) * 1e8) / 1e8
    if vol <= 0:
        return
    amount = round(st.order_size_usdt, 2)
    reason = f"رأی خرید {a['buys']}/{a['total']} تایم‌فریم"
    if dry:
        record_trade(ws_t, 'خرید', sym, tf, reason, fmt_price(price), vol, amount,
                     sl, tp, '—', ST_DRY, 'شبیه‌سازی — بدون ارسال به صرافی')
        led['dry_net_spent'] += amount
        p = led['positions'].setdefault(sym, {'volume': 0.0, 'entry_price': None, 'sl': None, 'tp': None})
        p['volume'] += vol
        return
    code, data = client.place_order('buy', sym, price, vol, st.order_type == 'market', client_order_id=coid)
    ok = code == 200 and isinstance(data, dict) and data.get('status') == 'ok'
    o = (data.get('order') or {}) if isinstance(data, dict) else {}
    oid = str(o.get('id') or (data.get('id') if isinstance(data, dict) else '') or '')
    if ok:
        record_trade(ws_t, 'خرید', sym, tf, reason, fmt_price(price), vol, amount,
                     sl, tp, oid, ST_PLACED, str(data)[:80])
        p = led['positions'].setdefault(sym, {'volume': 0.0, 'entry_price': None, 'sl': None, 'tp': None})
        p['volume'] += vol
    else:
        log.error('ثبت سفارش واقعی خرید %s ناموفق: HTTP %s | %s', sym, code, str(data)[:150])
        record_trade(ws_t, 'خرید', sym, tf, reason, fmt_price(price), vol, amount,
                     sl, tp, '', 'ناموفق', str(data)[:100])


def _public_price(sym):
    """قیمت لحظه‌ای نماد — برای پوزیشن‌هایی که از تاپ ۱۰ خارج شده‌اند (API عمومی، بدون احراز هویت)"""
    pair = f'{sym.lower()}-usdt'
    try:
        r = requests.post('https://apiv2.nobitex.ir/market/stats', json={'stats': pair},
                          headers={'User-Agent': 'TraderBot/NobitexSheetBot-2.0'}, timeout=30)
        st_ = (r.json().get('stats') or {}).get(pair) or {}
        v = float(st_.get('bestSell') or 0)
        return v if v > 0 else None
    except Exception:
        return None


def find_sl_tp_exits(positions, prices):
    """تعیین خروج‌های فعال — تابع خالص و قابل تست: [(نماد, دلیل, قیمت), ...]"""
    exits = []
    for sym, p in positions.items():
        sl, tp = p.get('sl'), p.get('tp')
        if not sl or not tp:
            continue
        price = prices.get(sym)
        if price is None:
            continue
        if price <= sl:
            exits.append((sym, 'حد ضرر', price))
        elif price >= tp:
            exits.append((sym, 'حد سود', price))
    return exits


def check_sl_tp(st, ws_t, client, dry, led, prices):
    """اجرای خودکار حد ضرر/حد سود — اولویت بالاتر از سیگنال‌ها
    نکته: خروج‌ها سقف MAX_DAILY_TRADES را دور می‌زنند (مدیریت ریسک‌اند، نه معامله جدید)"""
    for sym in led['positions']:          # قیمت نمادهای خارج‌شده از تاپ ۱۰
        if prices.get(sym) is None:
            px = _public_price(sym)
            if px:
                prices[sym] = px
    exits = find_sl_tp_exits(led['positions'], prices)
    if not exits:
        return
    log.info('خروج‌های فعال: %s', '، '.join(f'{s} ({w})' for s, w, _ in exits))
    for sym, why, price in exits:
        vol = led['positions'][sym]['volume']
        if not dry:
            avail = currency_available(client, sym)
            if avail is None:
                log.warning('خروج %s انجام نشد: موجودی از API قابل دریافت نیست', sym)
                continue
            vol = min(vol, avail)
        sell_one(st, ws_t, client, dry, sym, why, price, vol, led)


def sell_one(st, ws_t, client, dry, sym, reason, price, vol, led):
    """فروش/خروج — با محاسبه سود و زیان بر اساس میانگین قیمت ورود"""
    amount = round(vol * price, 2)
    pos = led['positions'].get(sym) or {}
    entry = pos.get('entry_price')
    pnl = round(vol * price - vol * entry, 2) if entry else None
    pnl_msg = f' | P&L: {pnl:+.2f} USDT' if pnl is not None else ''
    if dry:
        record_trade(ws_t, 'فروش', sym, '', reason, fmt_price(price), vol, amount,
                     '—', '—', '—', ST_DRY, 'شبیه‌سازی — بدون ارسال به صرافی' + pnl_msg)
        led['dry_net_spent'] -= amount
        led['positions'].pop(sym, None)
        return
    code, data = client.place_order('sell', sym, price, vol, st.order_type == 'market')
    ok = code == 200 and isinstance(data, dict) and data.get('status') == 'ok'
    o = (data.get('order') or {}) if isinstance(data, dict) else {}
    oid = str(o.get('id') or (data.get('id') if isinstance(data, dict) else '') or '')
    if ok:
        record_trade(ws_t, 'فروش', sym, '', reason, fmt_price(price), vol, amount,
                     '—', '—', oid, ST_PLACED, str(data)[:80] + pnl_msg)
        led['positions'].pop(sym, None)
    else:
        log.error('ثبت سفارش واقعی فروش %s ناموفق: HTTP %s | %s', sym, code, str(data)[:150])
        record_trade(ws_t, 'فروش', sym, '', reason, fmt_price(price), vol, amount,
                     '—', '—', '', 'ناموفق', str(data)[:100])


# ================= نقطه ورود اصلی =================
def run(sh, st, rows):
    dry = st.dry_run
    log.info('ماژول معاملات فعال — حالت: %s', 'شبیه‌سازی (DRY-RUN)' if dry else '⚠️ سفارش واقعی')
    ws_t = sh.worksheet(TRADES_TAB)
    client = make_client()
    if not dry and not client:
        log.error('معامله واقعی فعال است اما کلیدهای API در .env ناقص‌اند — هیچ سفارشی ثبت نشد')
        return

    agg = aggregate_signals(rows)
    prices = {str(r[0]).upper(): parse_price(r[2]) for r in rows if r and r[0]}
    led = read_ledger(ws_t)

    if client and not dry:
        sync_order_statuses(ws_t, led, client)
        led = read_ledger(ws_t)  # خواندن مجدد پس از همگام‌سازی

    # ۰) اجرای خودکار حد ضرر/حد سود — با اولویت بالا، قبل از سیگنال‌ها
    check_sl_tp(st, ws_t, client, dry, led, prices)

    # شمارش روزانه از API (منبع حقیقت) + ردیف‌های شبیه‌سازی امروز
    api_count = client.trades_today() if client else 0
    led['daily_count'] = max(led['daily_count'], api_count or 0)
    log.info('معاملات امروز: %d (شمارش از API نوبیتکس: %s)', led['daily_count'], api_count)

    cands = [s for s, a in agg.items() if is_buy_candidate(a)]
    log.info('کاندیدهای خرید این اجرا: %s', '، '.join(cands) if cands else 'هیچ')

    # ۱) فروش پوزیشن‌هایی که سیگنال فروش اکثریت گرفته‌اند
    for sym in list(led['positions']):
        a = agg.get(sym)
        if not (a and is_sell_candidate(a)):
            continue
        if led['daily_count'] >= st.max_daily_trades:
            log.info('فروش %s انجام نشد: سقف معاملات روزانه', sym)
            continue
        p = prices.get(sym) or _public_price(sym)
        if not p:
            continue
        vol = led['positions'][sym]['volume']
        if not dry:
            avail = currency_available(client, sym)
            if avail is None:
                log.warning('فروش %s انجام نشد: موجودی کیف پول از API قابل دریافت نیست', sym)
                continue
            vol = min(vol, avail)
        sell_one(st, ws_t, client, dry, sym,
                 f"سیگنال فروش {a['sells']}/{a['total']} تایم‌فریم", p, vol, led)
        led['daily_count'] += 1

    # ۲) خرید کاندیدها با احترام به همه سقف‌ها
    open_pos = len(led['positions'])
    for sym in cands:
        a = agg[sym]
        if led['daily_count'] >= st.max_daily_trades:
            log.info('خرید %s انجام نشد: سقف معاملات روزانه (%d)', sym, st.max_daily_trades)
            continue
        if sym in led['positions'] or sym in led['pending']:
            log.info('خرید %s انجام نشد: پوزیشن یا سفارش باز موجود است', sym)
            continue
        if open_pos >= st.max_open_positions:
            log.info('خرید %s انجام نشد: سقف پوزیشن باز (%d)', sym, st.max_open_positions)
            continue
        p = prices.get(sym)
        if not p or p <= 0:
            continue
        if dry:
            bal = st.dry_start_usdt - led['dry_net_spent']
        else:
            bal = currency_available(client, 'usdt')
            if bal is None:
                log.error('خرید %s انجام نشد: موجودی USDT از API قابل دریافت نیست', sym)
                continue
        if bal < st.order_size_usdt or bal - st.order_size_usdt < st.min_usdt_balance:
            log.info('خرید %s انجام نشد: موجودی USDT کافی نیست (%.1f)', sym, bal)
            continue
        buy_one(st, ws_t, client, dry, sym, a, p, led, coid=f'nbx-{sym.lower()}-{int(time.time())}')
        led['daily_count'] += 1
        open_pos += 1
    log.info('پایان ماژول معاملات — مجموع سفارش‌های امروز: %d', led['daily_count'])


# ================= تب کیف پول =================
def refresh_wallet(sh, st, rows):
    """موجودی‌ها مستقیم از API نوبیتکس — فرمت تأییدشده:
    currency / balance / blockedBalance / activeBalance"""
    ws = sh.worksheet(WALLET_TAB)
    prices = {str(r[0]).upper(): parse_price(r[2]) for r in rows if r and r[0]}
    usdt_rls = None
    try:
        usdt_rls = parse_price(sh.worksheet(UNIVERSE_TAB).acell('D1').value)
    except Exception:
        pass

    client = make_client()
    if not client:
        ws.update(values=[['کلید API تنظیم نشده — پس از پر کردن .env روی سرور، موجودی‌ها اینجا نمایش داده می‌شوند',
                           '', '', '', '', jnow()]], range_name='A4:F4')
        return

    code, data = client.wallets()
    wl = data.get('wallets') if isinstance(data, dict) else None
    if not isinstance(wl, list):
        msg = f'خطا در دریافت کیف پول از API (HTTP {code})'
        ws.update(values=[[msg, '', '', '', '', jnow()]], range_name='A4:F4')
        log.error('%s — %s', msg, str(data)[:150])
        return

    out = []
    for w in wl:
        cur = str(w.get('currency') or w.get('name') or '').lower()
        if not cur:
            continue
        try:
            bal = float(w.get('balance') or 0)
        except (TypeError, ValueError):
            bal = 0.0
        try:
            blk = float(w.get('blockedBalance') or w.get('blocked') or 0)
        except (TypeError, ValueError):
            blk = 0.0
        act = None
        for k in ('activeBalance', 'active_balance'):
            if w.get(k) not in (None, ''):
                try:
                    act = float(w[k])
                    break
                except (TypeError, ValueError):
                    pass
        if act is None:
            act = max(bal - blk, 0.0)
        if bal == 0 and cur not in ('usdt', 'rls', 'irr'):
            continue
        if cur == 'usdt':
            val = bal
        elif cur in ('rls', 'irr') and usdt_rls:
            val = bal / usdt_rls
        elif prices.get(cur.upper()):
            val = bal * prices[cur.upper()]
        else:
            val = None
        out.append([cur.upper(), fmt_bal(bal), fmt_bal(blk), fmt_bal(act),
                    round(val, 4) if val is not None else '—', ''])
    out.sort(key=lambda x: -(x[4] if isinstance(x[4], (int, float)) else -1))
    if len(out) > 40:
        out = out[:40] + [['…', f'+{len(out) - 40} دارایی دیگر', '', '', '', '']]
    body = out or [['(کیف پولی یافت نشد)', '', '', '', '', '']]
    padded = body + [[''] * 6] * (41 - len(body))
    ws.update(values=[['💼 کیف پول‌های نوبیتکس — مستقیم از API صرافی', 'آخرین به‌روزرسانی:', jnow()]],
              range_name='A1:C1')
    ws.update(values=padded, range_name='A4:F44')
    log.info('تب کیف پول از API به‌روزرسانی شد (%d دارایی)', len(out))


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
    if '--test-auth' in sys.argv:
        key = load_env().get('NOBITEX_API_KEY', '').strip()
        if not key:
            print('✗ NOBITEX_API_KEY در .env تنظیم نشده است')
            sys.exit(1)
        import json
        e = load_env()
        sec = (e.get('NOBITEX_API_SECRET') or '').strip()
        if not sec:
            print('✗ NOBITEX_API_SECRET در .env تنظیم نشده است')
            sys.exit(1)
        c = NobitexClient(key, sec)
        for name, fn in (('کیف پول‌ها', c.wallets), ('سفارش‌های باز', c.open_orders)):
            code, data = fn()
            print(f'--- {name} → HTTP {code} ---')
            print(json.dumps(data, ensure_ascii=False)[:1500])
        print('\n✓ هیچ سفارشی ثبت نشد — این حالت فقط تست اتصال است')
    elif '--test-signals' in sys.argv:
        sample = [
            ['BTC', '15m', '83,000', 'نزولی', 'خرید', '40', 2, 1, 2, '81,000', '85,000', 'تست'],
            ['BTC', '1h', '83,000', 'نزولی', 'خنثی', '60', 0, 3, 2, '', '', ''],
            ['BTC', '4h', '83,000', 'نزولی', 'خنثی', '60', 0, 3, 2, '', '', ''],
            ['BTC', '1D', '83,000', 'صعودی', 'خرید', '60', 3, 0, 2, '80,000', '87,000', ''],
            ['ETH', '15m', '2,680', 'صعودی', 'خنثی', '60', 3, 0, 2, '', '', ''],
            ['ETH', '1h', '2,680', 'نزولی', 'خنثی', '40', 1, 2, 2, '', '', ''],
        ]
        agg = aggregate_signals(sample)
        for sym, a in agg.items():
            d = 'کاندید خرید ✓' if is_buy_candidate(a) else '—'
            print(f'{sym}: خرید={a["buys"]} فروش={a["sells"]} از {a["total"]} تایم‌فریم → {d}')
    else:
        print('استفاده: trader.py --test-auth | --test-signals')
