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
    import datetime as _dt
    import jdatetime
    _TEHRAN = _dt.timedelta(hours=3, minutes=30)

    def _now_tehran():
        return _dt.datetime.now(_dt.timezone.utc) + _TEHRAN

    def jnow():
        g = _now_tehran().replace(tzinfo=None)
        return jdatetime.datetime.fromgregorian(datetime=g).strftime('%Y/%m/%d %H:%M')

    def jtoday():
        return jdatetime.date.fromgregorian(date=_now_tehran().date()).strftime('%Y/%m/%d')
except ImportError:
    import datetime as _dt
    _TEHRAN = _dt.timedelta(hours=3, minutes=30)

    def jnow():
        return (_dt.datetime.now(_dt.timezone.utc) + _TEHRAN).strftime('%Y-%m-%d %H:%M')

    def jtoday():
        return (_dt.datetime.now(_dt.timezone.utc) + _TEHRAN).strftime('%Y-%m-%d')


log = logging.getLogger('nobitex-bot')

BASE = 'https://apiv2.nobitex.ir'
TIMEOUT = 60

ORDERS_TAB = 'سفارشات'        # دفتر سفارش‌ها
CLOSED_TAB = 'اتمام معاملات'   # معاملات بسته‌شده
RANKING_TAB = 'معاملات'        # جدول رتبه‌بندی برای سفارشگزاری
TRADES_TAB = ORDERS_TAB        # سازگاری: دفتر و گزارش از سفارشات خوانده می‌شوند
WALLET_TAB = 'کیف پول'
UNIVERSE_TAB = 'dynamic universe'
REPORT_TAB = 'گزارش'

ST_DRY = 'شبیه‌سازی شده'
ST_PLACED = 'ثبت‌شده'
ST_OPEN = 'باز'
ST_FILLED = 'پر شد'
ST_PARTIAL = 'بخشی پر و لغو شد'
ST_CANCELLED = 'لغو شده'
ST_PENDING_STOP = 'در انتظار تریگر'
EXECUTED = {ST_DRY, ST_FILLED, ST_PARTIAL}
OPENISH = {ST_PLACED, ST_OPEN, ST_PENDING_STOP}

MIN_TFS = 2


def record_closed(ws_t, sym, entry_time, entry_price, exit_price, vol, reason, mode):
    """ثبت معامله بسته‌شده در تب «اتمام معاملات»"""
    try:
        pnl = vol * (exit_price - entry_price)
        pct = (exit_price / entry_price - 1) * 100 if entry_price else 0.0
        dur = '—'
        try:
            import jdatetime
            t0 = jdatetime.datetime.strptime(str(entry_time), '%Y/%m/%d %H:%M')
            dur = round((jdatetime.datetime.fromgregorian(datetime=_now_tehran().replace(tzinfo=None)) - t0).total_seconds() / 3600, 1)
        except Exception:
            pass
        ws_c = ws_t.spreadsheet.worksheet(CLOSED_TAB)
        ws_c.append_row([jnow(), sym, entry_time, fmt_price(entry_price),
                         fmt_price(exit_price), vol, round(pnl, 2), round(pct, 2),
                         reason, dur, mode])
        log.info('معامله %s بسته شد — P&L: %+.2f USDT (%s)', sym, pnl, reason)
    except Exception:
        log.exception('خطا در ثبت معامله بسته‌شده %s', sym)  # حداقل تعداد تایم‌فریم هم‌جهت برای صدور سفارش


# ================= کلاینت API معاملاتی =================
def record_trade(ws_t, action, sym, tf, reason, price, volume, amount, sl, tp, oid, status, msg):
    """ثبت سفارش در دفتر «سفارشات» — هر سفارش یک ردیف"""
    ws_t.append_row([jnow(), sym, action, tf, reason, price, volume, amount,
                     sl, tp, oid, status, msg])
    log.info('سفارش ثبت شد: %s %s | %s @ %s | %s', action, sym, volume, price, status)


class NobitexClient:
    """پوشش امضاشده روی API معاملاتی — Nobitex-Key/Signature/Timestamp
    (امضای Ed25519 روی timestamp+METHOD+full_path+raw_body طبق مستندات رسمی apiv2)"""

    def __init__(self, public_key, private_key_b64):
        from nobitex_auth import SignedClient
        self._sc = SignedClient(public_key, private_key_b64)

    def wallets(self):
        return self._sc.post('/users/wallets/list', {})

    def wallet_balance(self, currency):
        for key in ('currency', 'wallet'):
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

    def trades_today(self, bot_order_ids=None):
        """تعداد سفارش‌های اجراشده‌ی خودِ ربات امروز (به وقت تهران).
        اگر bot_order_ids بدهد فقط معاملات با orderId عضو آن مجموعه شمرده می‌شود —
        معاملات دستی کاربر سهمیه روزانه ربات را مصرف نمی‌کنند.
        شمارش بر پایه orderId یکتاست (پرشدن بخشی یک بار شمرده می‌شود)."""
        import datetime as dt
        code, data = self._sc.get('/market/trades/list')
        if code != 200 or not isinstance(data, dict):
            return None
        offset = dt.timedelta(hours=3, minutes=30)
        now_shifted = dt.datetime.now(dt.timezone.utc) + offset
        midnight = dt.datetime.combine(now_shifted.date(), dt.time.min,
                                       tzinfo=dt.timezone.utc)
        seen = set()
        for tr in (data.get('trades') or []):
            oid = str(tr.get('orderId') or '')
            if bot_order_ids is not None and oid not in bot_order_ids:
                continue
            ts = tr.get('timestamp')
            if not ts:
                continue
            try:
                t = dt.datetime.fromisoformat(str(ts).replace('Z', '+00:00'))
            except ValueError:
                continue
            if t + offset >= midnight:
                seen.add(oid or f"trade-{tr.get('id')}")
        return len(seen)

    def place_order(self, order_type, symbol, price, volume, is_market,
                    client_order_id=None):
        """ثبت سفارش اسپات apiv2 — طبق مستندات p117 و پروب‌های زنده:
        amount (واحد srcCurrency) + execution (limit/market/stop_market/stop_limit)
        + clientOrderId یکتا در میان سفارش‌های باز"""
        payload = {'type': order_type,
                   'market': f'{symbol}USDT',
                   'srcCurrency': symbol.lower(),
                   'dstCurrency': 'usdt',
                   'price': fmt_amt(price),
                   'amount': fmt_amt(volume),
                   'execution': 'market' if is_market else 'limit'}
        if client_order_id:
            payload['clientOrderId'] = client_order_id
        return self._sc.post('/market/orders/add', payload)

    def cancel_order(self, order_id):
        """لغو سفارش — طبق مستندات رسمی p121:
        - پارامتر: order (یا clientOrderId) — نه orderId
        - مقدار مجاز: status=canceled
        - HTTP 200 لزوماً یعنی لغو؛ updatedStatus یا order.status باید Canceled باشد
        - لغو یک پایه از OCO انجام‌نشده، پایه جفت را نیز لغو می‌کند"""
        code, data = self._sc.post('/market/orders/update-status',
                                   {'order': str(order_id), 'status': 'canceled'})
        if code == 200 and isinstance(data, dict):
            o = data.get('order') or {}
            if (str(data.get('updatedStatus')) == 'Canceled'
                    or str(o.get('status')) == 'Canceled'):
                return code, data
            return code, {'status': 'failed', 'code': 'TransitionNotApplied',
                          'message': 'updatedStatus=%s orderStatus=%s' % (
                              data.get('updatedStatus'), o.get('status')),
                          'order': o}
        return code, data

    def place_oco_sell(self, symbol, volume, take_profit, stop_price, stop_limit=None):
        """OCO فروش — حد سود (limit) + حد ضرر (stop-limit) بومی روی صرافی
        مستندات p117: mode=oco + price + stopPrice + stopLimitPrice
        شرط فروش: stopPrice < قیمت بازار < price"""
        if stop_limit is None:
            stop_limit = (stop_price or 0) * 0.995
        payload = {'type': 'sell',
                   'market': f'{symbol}USDT',
                   'srcCurrency': symbol.lower(),
                   'dstCurrency': 'usdt',
                   'price': fmt_amt(take_profit),
                   'amount': fmt_amt(volume),
                   'execution': 'limit',
                   'mode': 'oco',
                   'stopPrice': fmt_amt(stop_price),
                   'stopLimitPrice': fmt_amt(stop_limit)}
        return self._sc.post('/market/orders/add', payload)


def make_client():
    """کلاینت امضاشده از .env — None یعنی کلیدها ناقص‌اند"""
    e = load_env()
    k = (e.get('NOBITEX_API_KEY') or '').strip()
    s = (e.get('NOBITEX_API_SECRET') or '').strip()
    return NobitexClient(k, s) if k and s else None


# ================= ابزارها =================
def clean_oid(v):
    """شناسه سفارش تمیز: عدد صحیح بدون کاما/اعشار — "6,420,187,613.000" → "6420187613" """
    if v in (None, ''):
        return ''
    try:
        return str(int(round(float(str(v).replace(',', '')))))
    except (TypeError, ValueError):
        return str(v).strip()


def fmt_amt(v):
    """فرمت مقدار/قیمت برای API — بدون نماد علمی، حداکثر ۸ رقم اعشار"""
    s = f'{float(v):.8f}'.rstrip('0').rstrip('.')
    return s if s else '0'


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


def currency_available(client, currency, use_active=True):
    """موجودی یک ارز از API نوبیتکس.
    use_active=True  → موجودی قابل استفاده (activeBalance) — ملاک اعتبارسنجی سفارش
                       در صرافی؛ سفارش‌های باز موجودی را بلوکه می‌کنند (مثل PUMP)
    use_active=False → موجودی کل (balance) — برای تشخیص وجود پوزیشن (reconcile)؛
                       سکه‌های بلوکه‌شده زیر OCO خودِ پوزیشن، وجودش را حفظ می‌کنند
    """
    currency = str(currency).lower()

    def _f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    code, data = client.wallets()
    wl = data.get('wallets') if isinstance(data, dict) else None
    if isinstance(wl, list):
        for w in wl:
            if str(w.get('currency', '')).lower() != currency:
                continue
            tot = _f(w.get('balance'))
            act = _f(w.get('activeBalance'))
            blk = _f(w.get('blockedBalance')) or 0.0
            if act is None and tot is not None:
                act = max(tot - blk, 0.0)
            if use_active:
                return act if act is not None else tot
            return tot
    code, data = client.wallet_balance(currency)
    if code == 200 and isinstance(data, dict):
        v = _f(data.get('balance'))
        if v is not None:
            return v
    return None


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
def read_ledger(ws, dust_usdt=0.5):
    """خواندن دفتر سفارش‌ها:
    - پوزیشن‌های باز با میانگین قیمت ورود، آخرین SL/TP و تفکیک حجم واقعی/شبیه‌سازی
      (شبیه‌سازی = ردیف‌های «شبیه‌سازی شده»؛ واقعی = «پر شد/بخشی پر»)
    - سفارش‌های باز، شمارش امروز (شمسی)، خالص خرج شبیه‌سازی
    """
    vals = ws.get_all_values(value_render_option='UNFORMATTED_VALUE')
    led = {'positions': {}, 'pending': set(), 'pending_sells': set(),
           'daily_count': 0, 'dry_net_spent': 0.0, 'rows': []}
    today = jtoday()
    bought = {}   # sym -> [حجم کل، هزینه کل، حجم شبیه‌سازی]
    sold = {}     # sym -> [حجم کل، حجم شبیه‌سازی]
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
        if (t.startswith(today) and status != 'ناموفق'
                and 'OCO' not in r[4]):
            led['daily_count'] += 1
        if status in OPENISH:
            led['pending'].add(sym)
            if act == 'فروش':
                led['pending_sells'].add(sym)
        if status in EXECUTED:
            is_sim = (status == ST_DRY)
            if act == 'خرید':
                b = bought.setdefault(sym, [0.0, 0.0, 0.0])
                b[0] += vol
                b[1] += amt
                if is_sim:
                    b[2] += vol
                    led['dry_net_spent'] += amt
                sl_p, tp_p = parse_price(r[8]), parse_price(r[9])
                if sl_p and tp_p:
                    sltp[sym] = (sl_p, tp_p)
            else:
                s_ = sold.setdefault(sym, [0.0, 0.0])
                s_[0] += vol
                if is_sim:
                    s_[1] += vol
                    led['dry_net_spent'] -= amt
    for sym in set(list(bought) + list(sold)):
        b = bought.get(sym, [0.0, 0.0, 0.0])
        s_ = sold.get(sym, [0.0, 0.0])
        net = b[0] - s_[0]
        if net > 1e-12:
            sim_net = max(0.0, min(b[2] - s_[1], net))
            entry = (b[1] / b[0]) if b[0] else None
            # dust (fee leftovers) is not a position
            if entry is not None and net * entry < dust_usdt:
                continue
            sl, tp = sltp.get(sym, (None, None))
            led['positions'][sym] = {'volume': net,
                                     'sim_volume': sim_net,
                                     'real_volume': net - sim_net,
                                     'entry_price': entry, 'sl': sl, 'tp': tp}
    return led


# ================= همگام‌سازی وضعیت از API =================
def sync_order_statuses(ws_t, led, client, st=None):
    """همگام‌سازی وضعیت سفارش‌های واقعی از API نوبیتکس
    - مقادیر رسمی: Active / Done / Inactive / Canceled (matchedAmount>0 = بخشی پر)
    - در لحظه‌ی گذار سفارش خرید به «پر شد»: ثبت OCO بومی صرافی (اگر فعال باشد)
      این محل اصلی OCO برای سفارش‌های limit است که با تأخیر پر می‌شوند"""
    api_map = {'Active': ST_OPEN, 'Done': ST_FILLED,
               'Inactive': ST_PENDING_STOP, 'Canceled': ST_CANCELLED}
    for row_num, r in led['rows']:
        # OCO = two legs; ids joined with | in the ledger
        oids = [clean_oid(x) for x in str(r[10]).split('|')]
        oids = [x for x in oids if x and x != chr(8212)]
        if not oids or str(r[11]).strip() not in OPENISH:
            continue
        legs = {}
        for oid in oids:
            code, data = client.order_status(oid)
            o = data.get('order') if isinstance(data, dict) else None
            raw = o.get('status') if isinstance(o, dict) else None
            if raw in api_map:
                legs[oid] = (raw, o)
            else:
                log.warning('order %s: unknown status HTTP %s | %s',
                            oid, code, str(data)[:120])
        if not legs:
            continue
        done_leg = next(((rw, o) for rw, o in legs.values() if rw == 'Done'), None)
        if done_leg:
            raw, o = done_leg
        elif all(rw == 'Canceled' for rw, _ in legs.values()):
            raw = 'Canceled'
            o = next(iter(legs.values()))[1]
        else:
            raw, o = next(iter(legs.values()))
        new_st = api_map[raw]
        vol_update = None
        exit_px = None
        exit_vol = None
        if raw == 'Canceled':
            try:
                matched = float(str(o.get('matchedAmount') or 0).replace(',', ''))
            except (TypeError, ValueError):
                matched = 0.0
            if matched > 0:
                new_st = ST_PARTIAL
                vol_update = matched
        if raw == 'Done':
            try:
                exit_px = float(str(o.get('price') or 0).replace(',', '')) or None
                exit_vol = float(str(o.get('matchedAmount') or 0).replace(',', '')) or None
            except (TypeError, ValueError):
                pass
        if new_st != str(r[11]).strip():
            ws_t.update_cell(row_num, 12, new_st)
            if vol_update is not None:
                ws_t.update_cell(row_num, 7, vol_update)
            log.info('وضعیت سفارش %s → %s', '|'.join(oids), new_st)

        sym_c = r[1].strip().upper()
        if r[2].strip() == 'خرید' and new_st == ST_FILLED:
            log.info('گذار خرید به پرشد %s | use_oco=%s | در pending_sells=%s',
                     sym_c,
                     (getattr(st, 'use_exchange_oco', None) if st is not None else None),
                     sym_c in led.get('pending_sells', set()))

        # معامله واقعی بسته شد: فروش کامل پر شد → ثبت در «اتمام معاملات»
        if r[2].strip() == 'فروش' and new_st == ST_FILLED:
            pos_c = led['positions'].get(sym_c) or {}
            entry_c = pos_c.get('entry_price') or parse_price(r[5]) or 0.0
            vol_c = exit_vol or (parse_price(r[6]) or 0.0)
            t_in = next((rr[0] for _, rr in led['rows']
                         if rr[1].strip().upper() == sym_c and rr[2].strip() == 'خرید'
                         and rr[11].strip() in EXECUTED), '—')
            record_closed(ws_t, sym_c, t_in, entry_c, exit_px or (parse_price(r[5]) or 0.0),
                          vol_c, 'اجرای سفارش فروش', 'واقعی')

        # OCO بومی صرافی — فقط در گذار خرید به «پر شد» (یک‌بار؛ در صورت شکست،
        # حفاظت SL/TP با خود ربات ادامه می‌یابد)
        if (st is not None and getattr(st, 'use_exchange_oco', False)
                and r[2].strip() == 'خرید' and new_st == ST_FILLED
                and sym_c not in led.get('pending_sells', set())):
            try:
                vol_o = float(str(o.get('matchedAmount') or r[6]).replace(',', '') or 0)
            except (TypeError, ValueError):
                vol_o = 0.0
            avail_o = currency_available(client, sym_c)
            if avail_o is not None:
                vol_o = min(vol_o, avail_o)
            sl_o, tp_o = parse_price(r[8]), parse_price(r[9])
            if vol_o <= 1e-12 or not sl_o or not tp_o:
                log.warning('OCO در sync برای %s رد شد: vol=%s | sl=%s | tp=%s | matchedAmount=%s',
                            sym_c, vol_o, sl_o, tp_o, o.get('matchedAmount'))
            if vol_o > 1e-12 and sl_o and tp_o:
                code2, data2 = client.place_oco_sell(sym_c, vol_o, tp_o, sl_o)
                ok2 = code2 == 200 and isinstance(data2, dict) and data2.get('status') == 'ok'
                o2 = (data2.get('order') or {}) if isinstance(data2, dict) else {}
                leg_ids = []
                if isinstance(o2, dict):
                    for _k in ('id', 'pairId', 'orderId'):
                        if o2.get(_k):
                            leg_ids.append(clean_oid(o2.get(_k)))
                if isinstance(data2, dict) and isinstance(data2.get('orders'), list):
                    for _lg in data2['orders']:
                        if isinstance(_lg, dict):
                            for _k in ('id', 'pairId', 'orderId'):
                                if _lg.get(_k):
                                    leg_ids.append(clean_oid(_lg.get(_k)))
                oid_oco = '|'.join(dict.fromkeys(leg_ids))
                if ok2 and not oid_oco:
                    log.info('OCO add response without id: %s', str(data2)[:300])
                if ok2:
                    record_trade(ws_t, 'فروش', sym_c, '', 'OCO حد سود/ضرر بومی صرافی',
                                 fmt_price(tp_o), vol_o, round(vol_o * tp_o, 2),
                                 fmt_price(sl_o), fmt_price(tp_o),
                                 oid_oco, ST_PLACED,
                                 'OCO: TP=' + fmt_price(tp_o) + ' | SL=' + fmt_price(sl_o))
                    led.setdefault('pending_sells', set()).add(sym_c)
                    log.info('OCO بومی صرافی برای %s ثبت شد (TP=%s | SL=%s)',
                             sym_c, fmt_price(tp_o), fmt_price(sl_o))
                else:
                    log.error('ثبت OCO برای %s ناموفق (HTTP %s): %s — حفاظت SL/TP با خود ربات',
                              sym_c, code2, str(data2)[:120])


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
        p = led['positions'].setdefault(sym, {'volume': 0.0, 'sim_volume': 0.0, 'real_volume': 0.0, 'entry_price': None, 'sl': None, 'tp': None})
        p['volume'] += vol
        p['sim_volume'] = p.get('sim_volume', 0.0) + vol
        return
    code, data = client.place_order('buy', sym, price, vol, st.order_type == 'market', client_order_id=coid)
    ok = code == 200 and isinstance(data, dict) and data.get('status') == 'ok'
    o = (data.get('order') or {}) if isinstance(data, dict) else {}
    oid = clean_oid(o.get('id') if isinstance(o, dict) else None or (data.get('id') if isinstance(data, dict) else ''))
    if ok:
        record_trade(ws_t, 'خرید', sym, tf, reason, fmt_price(price), vol, amount,
                     sl, tp, oid, ST_PLACED, str(data)[:80])
        p = led['positions'].setdefault(sym, {'volume': 0.0, 'sim_volume': 0.0, 'real_volume': 0.0, 'entry_price': None, 'sl': None, 'tp': None})
        p['volume'] += vol
        p['real_volume'] = p.get('real_volume', 0.0) + vol
        if st.use_exchange_oco and st.order_type == 'market':
            code2, data2 = client.place_oco_sell(sym, vol, parse_price(tp), parse_price(sl))
            ok2 = code2 == 200 and isinstance(data2, dict) and data2.get('status') == 'ok'
            o2 = (data2.get('order') or {}) if isinstance(data2, dict) else {}
            oid2 = clean_oid(o2.get('id')) if ok2 else ''
            if ok2:
                record_trade(ws_t, 'فروش', sym, '', 'OCO حد سود/ضرر بومی صرافی',
                             tp, vol, round(vol * (parse_price(tp) or 0.0), 2),
                             '', '', oid2, ST_PLACED, f'OCO: TP={tp} | SL={sl}')
                led.setdefault('pending_sells', set()).add(sym)
            else:
                log.error('ثبت OCO برای %s ناموفق (HTTP %s): %s — SL/TP توسط خود ربات چک می‌شود',
                          sym, code2, str(data2)[:120])
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
    (خروج‌ها سقف روزانه را دور می‌زنند — مدیریت ریسک‌اند، نه معامله جدید)"""
    for sym in led['positions']:
        if prices.get(sym) is None:
            px = _public_price(sym)
            if px:
                prices[sym] = px
    exits = [(s, w, px) for s, w, px in find_sl_tp_exits(led['positions'], prices)
             if s not in led.get('pending_sells', set())]
    if not exits:
        return
    log.info('خروج‌های فعال: %s', '، '.join(f'{s} ({w})' for s, w, _ in exits))
    for sym, why, price in exits:
        exit_position(st, ws_t, client, sym, why, price, led)


def sell_one(st, ws_t, client, dry, sym, reason, price, vol, led):
    """فروش حجم مشخص — dry=True فقط در دفتر ثبت می‌کند
    (خروج کامل پوزیشن از exit_position انجام می‌شود)"""
    if not vol or vol <= 1e-12:
        log.warning('فروش %s رد شد: حجم صفر است', sym)
        return
    amount = round(vol * price, 2)
    pos = led['positions'].get(sym) or {}
    entry = pos.get('entry_price')
    pnl = round(vol * price - vol * entry, 2) if entry else None
    pnl_msg = f' | P&L: {pnl:+.2f} USDT' if pnl is not None else ''
    e_time = next((rr[0] for _, rr in led['rows']
                   if rr[1].strip().upper() == sym and rr[2].strip() == 'خرید'
                   and rr[11].strip() in EXECUTED), '—')
    if dry:
        record_trade(ws_t, 'فروش', sym, '', reason, fmt_price(price), vol, amount,
                     '—', '—', '—', ST_DRY, 'شبیه‌سازی — بدون ارسال به صرافی' + pnl_msg)
        record_closed(ws_t, sym, e_time, entry or price, price, vol, reason, 'شبیه‌سازی')
        led['dry_net_spent'] -= amount
        return
    code, data = client.place_order('sell', sym, price, vol, st.order_type == 'market')
    ok = code == 200 and isinstance(data, dict) and data.get('status') == 'ok'
    o = (data.get('order') or {}) if isinstance(data, dict) else {}
    oid = clean_oid(o.get('id') if isinstance(o, dict) else None or (data.get('id') if isinstance(data, dict) else ''))
    if ok:
        record_trade(ws_t, 'فروش', sym, '', reason, fmt_price(price), vol, amount,
                     '—', '—', oid, ST_PLACED, str(data)[:80] + pnl_msg)
    else:
        log.error('ثبت سفارش واقعی فروش %s ناموفق: HTTP %s | %s', sym, code, str(data)[:150])
        record_trade(ws_t, 'فروش', sym, '', reason, fmt_price(price), vol, amount,
                     '—', '—', '', 'ناموفق', str(data)[:100])


def exit_position(st, ws_t, client, sym, reason, price, led):
    """خروج کامل از پوزیشن — جداکننده بخش واقعی و شبیه‌سازی:
    بخش واقعی تا سقف موجودی واقعی صرافی فروخته می‌شود؛
    بخش شبیه‌سازی فقط در دفتر بسته می‌شود (مستقل از DRY_RUN)."""
    pos = led['positions'].get(sym)
    if not pos:
        return
    sim_vol = max(pos.get('sim_volume') or 0.0, 0.0)
    real_vol = max(pos.get('real_volume') or 0.0, 0.0)
    if real_vol > 1e-12:
        if client is None:
            log.error('خروج واقعی %s ممکن نیست: کلاینت API ساخته نشده است', sym)
        else:
            v = real_vol
            avail = currency_available(client, sym)
            if avail is not None:
                v = min(real_vol, avail)
            if v > 1e-12:
                sell_one(st, ws_t, client, False, sym, reason, price, v, led)
            else:
                log.warning('بخش واقعی %s فروخته نشد: موجودی صرافی صفر است', sym)
                dup = any(rr[1].strip().upper() == sym and rr[11].strip() == 'ناموفق'
                          and rr[0].startswith(jtoday()) for _, rr in led['rows'])
                if not dup:
                    record_trade(ws_t, 'فروش', sym, '', reason + ' (بخش واقعی)',
                                 fmt_price(price), real_vol, round(real_vol * price, 2),
                                 '—', '—', '', 'ناموفق', 'موجودی صرافی برای فروش کافی نیست')
    if sim_vol > 1e-12:
        sell_one(st, ws_t, client, True, sym, reason, price, sim_vol, led)
    led['positions'].pop(sym, None)


def apply_trailing(st, ws_t, led, prices, client=None):
    """SL/TP داینامیک — با رشد قیمت SL بالا کشیده می‌شود (قفل سود)

    پوزیشن واقعیِ دارای OCO باز روی صرافی:
      - هم‌راستاسازی: SL شیت هرگز بالاتر از SL واقعی صرافی نمی‌ماند
      - SL جدید > SL صرافی × 1.005 → لغو OCO قبلی + ثبت OCO جدید با SL بالاتر
      - شکست جایگزینی → حفاظت به SL/TP خود ربات برمی‌گردد
    """
    if not st.trail_enabled:
        return
    for sym, p in list(led['positions'].items()):
        entry, sl, price = p.get('entry_price'), p.get('sl'), prices.get(sym)
        if not (entry and sl and price):
            continue
        if price < entry * (1 + st.trail_activation_pct / 100.0):
            continue

        oco_row = next(((rn, rr) for rn, rr in led['rows']
                        if 'OCO' in str(rr[4]) and rr[1].strip().upper() == sym
                        and rr[11].strip() in OPENISH), None)
        has_oco = sym in led.get('pending_sells', set()) and oco_row is not None
        oco_sl = parse_price(oco_row[1][8]) if oco_row else None

        def set_sheet_sl(v):
            for row_num, rr in led['rows']:
                if (rr[1].strip().upper() == sym and rr[2].strip() == 'خرید'
                        and rr[11].strip() in EXECUTED):
                    ws_t.update_cell(row_num, 9, fmt_price(v))
                    break

        # هم‌راستاسازی: SL شیت (از تریلینگ قدیمی فقط-شیت) بالاتر از واقعیت صرافی نباشد
        if has_oco and oco_sl is not None and sl > oco_sl:
            p['sl'] = oco_sl
            sl = oco_sl
            set_sheet_sl(oco_sl)
            log.info('SL شیت %s به SL واقعی صرافی هم‌راستا شد: %s', sym, fmt_price(oco_sl))

        new_sl = price * (1 - st.trail_distance_pct / 100.0)
        if new_sl <= sl:
            continue

        if has_oco and oco_sl is not None and new_sl <= oco_sl * 1.005:
            p['sl'] = oco_sl
            set_sheet_sl(oco_sl)
            continue
        if has_oco:
            if client is None or (p.get('real_volume') or 0) <= 1e-12:
                continue
            old_ids = [clean_oid(x) for x in str(oco_row[1][10]).split('|')
                       if clean_oid(x) and clean_oid(x) != chr(8212)]
            cancel_ok = bool(old_ids)
            for oid in old_ids:
                code_c, data_c = client.cancel_order(oid)
                ok_c = (code_c == 200 and (not isinstance(data_c, dict)
                                           or data_c.get('status') != 'failed'))
                if not ok_c and isinstance(data_c, dict) and str(data_c.get('error')) == 'NotFound':
                    ok_c = True  # پایه قبلاً لغو شده — نتیجه مطلوب حاصل است
                if not ok_c:
                    cancel_ok = False
                    log.error('لغو پایه OCO %s ناموفق: HTTP %s | %s',
                              oid, code_c, str(data_c)[:100])
            if not cancel_ok:
                log.error('OCO %s دست‌نخورده ماند — SL صرافی همان %s است',
                          sym, fmt_price(oco_sl))
                p['sl'] = oco_sl or sl
                continue
            ws_t.update_cell(oco_row[0], 12, ST_CANCELLED)
            vol_o = p['real_volume']
            avail = currency_available(client, sym)
            if avail is not None:
                vol_o = min(vol_o, avail)
            tp_o = p.get('tp')
            if not (vol_o > 1e-12 and tp_o):
                led['pending_sells'].discard(sym)
                log.error('OCO متحرک %s: حجم/TP نامعتبر — حفاظت با خود ربات', sym)
                continue
            code2, data2 = client.place_oco_sell(sym, vol_o, tp_o, new_sl)
            ok2 = code2 == 200 and isinstance(data2, dict) and data2.get('status') == 'ok'
            if not ok2:
                led['pending_sells'].discard(sym)
                log.error('ثبت OCO متحرک %s ناموفق: HTTP %s | %s — حفاظت با خود ربات',
                          sym, code2, str(data2)[:120])
                continue
            o2 = (data2.get('order') or {}) if isinstance(data2, dict) else {}
            leg_ids = []
            if isinstance(o2, dict):
                for _k in ('id', 'pairId', 'orderId'):
                    if o2.get(_k):
                        leg_ids.append(clean_oid(o2.get(_k)))
            if isinstance(data2, dict) and isinstance(data2.get('orders'), list):
                for _lg in data2['orders']:
                    if isinstance(_lg, dict):
                        for _k in ('id', 'pairId', 'orderId'):
                            if _lg.get(_k):
                                leg_ids.append(clean_oid(_lg.get(_k)))
            oid_new = '|'.join(dict.fromkeys(leg_ids))
            record_trade(ws_t, 'فروش', sym, '', 'OCO متحرک (SL بالاتر)',
                         fmt_price(tp_o), vol_o, round(vol_o * tp_o, 2),
                         fmt_price(new_sl), fmt_price(tp_o), oid_new, ST_PLACED,
                         'SL: ' + fmt_price(new_sl))
            p['sl'] = new_sl
            set_sheet_sl(new_sl)
            log.info('OCO متحرک %s: SL %s -> %s (بازسازی روی صرافی)',
                     sym, fmt_price(oco_sl or sl), fmt_price(new_sl))
            continue
        p['sl'] = new_sl
        set_sheet_sl(new_sl)
        log.info('SL متحرک %s: %s -> %s', sym, fmt_price(sl), fmt_price(new_sl))


def write_ranking(sh, st, rows, led, bt_params=None):
    """رتبه‌بندی چرخه سیگنال — تب «معاملات»: آماده‌سازی ورود/TP/SL برای سفارشگزاری"""
    ws = sh.worksheet(RANKING_TAB)
    bt_params = bt_params or {}
    best = {}
    for r in rows:
        if len(r) < 11 or not r[0]:
            continue
        sym = str(r[0]).upper()
        try:
            strength = float(r[5] or 0)
        except (TypeError, ValueError):
            strength = 0.0
        if sym not in best or strength > best[sym][0]:
            best[sym] = (strength, list(r))
    ordered = sorted(best.items(),
                     key=lambda kv: (1 if kv[1][1][4] == 'خرید' else 0, kv[1][0]),
                     reverse=True)
    data = []
    for rank, (sym, (strength, r)) in enumerate(ordered, 1):
        price, tp, sl = parse_price(r[2]), parse_price(r[10]), parse_price(r[9])
        rr = round((tp - price) / (price - sl), 2) if (price and tp and sl and price > sl) else '—'
        if sym in led.get('positions', {}):
            status = 'پوزیشن باز'
        elif sym in led.get('pending', set()):
            status = 'سفارش باز'
        else:
            status = 'کاندید خرید' if r[4] == 'خرید' else '—'
        bp = bt_params.get(sym) or {}
        strat = (f"آستانه {bp['thr']}٪ | SL {bp['slm']}xATR | TP {bp['tpm']}xATR"
                 if bp else 'پیش‌فرض شیت تنظیمات')
        data.append([rank, sym, r[4], r[5], r[6], r[7], r[8],
                     r[2], r[2], r[10], r[9], rr, strat, status])
    n = max(20, len(data) + 4)
    data = data + [[''] * 14] * (n - len(data))
    ws.update(values=[['رتبه‌بندی لحظه‌ای برای سفارشگزاری — بازه: INTERVAL_SIGNALS_MIN در تب تنظیمات',
                       'به‌روزرسانی:', jnow()]], range_name='A1:C1')
    ws.update(values=data, range_name=f'A4:N{3 + n}')


def reconcile_real_positions(st, ws_t, client, led, prices):
    """تطبیق پوزیشن‌های واقعی با کیف پول نوبیتکس (منبع حقیقت).
    اگر اکثر سکه‌های یک پوزیشن واقعی از کیف پول رفته باشند (اجرای OCO روی
    صرافی، فروش دستی یا برداشت)، پوزیشن در دفتر بسته می‌شود — مستقل از اینکه
    شناسه سفارش در دفتر موجود باشد یا نه."""
    for sym in list(led['positions']):
        p = led['positions'].get(sym) or {}
        rv = p.get('real_volume') or 0.0
        if rv <= 1e-12:
            continue
        avail = currency_available(client, sym, use_active=False)
        if avail is None or avail >= rv * 0.5:
            continue
        price = prices.get(sym) or _public_price(sym) or p.get('entry_price') or 0.0
        sold = max(rv - avail, 0.0)
        for row_num, rr in led['rows']:
            if (rr[1].strip().upper() == sym and rr[2].strip() == 'فروش'
                    and rr[11].strip() in OPENISH):
                ws_t.update_cell(row_num, 12, ST_FILLED)
                ws_t.update_cell(row_num, 7, sold)
                ws_t.update_cell(row_num, 6, fmt_price(price))
                break
        e_time = next((rr[0] for _, rr in led['rows']
                       if rr[1].strip().upper() == sym and rr[2].strip() == 'خرید'
                       and rr[11].strip() in EXECUTED), '—')
        record_closed(ws_t, sym, e_time, p.get('entry_price') or price, price,
                      sold, 'خروج از کیف پول (OCO یا فروش دستی)', 'واقعی')
        led['positions'].pop(sym, None)
        led['pending_sells'].discard(sym)
        led['pending'].discard(sym)


def recent_failed_buy(led, sym, minutes):
    """آیا خرید این نماد در N دقیقه اخیر ناموفق بوده؟ (جلوگیری از کوبیدن هر چرخه)"""
    if minutes <= 0:
        return False
    try:
        import jdatetime as _jd
        now_j = _jd.datetime.fromgregorian(datetime=_now_tehran().replace(tzinfo=None))
        for _, rr in led['rows']:
            if (rr[1].strip().upper() == sym and rr[2].strip() == 'خرید'
                    and rr[11].strip() == 'ناموفق'):
                t0 = _jd.datetime.strptime(str(rr[0]).strip(), '%Y/%m/%d %H:%M')
                if (now_j - t0).total_seconds() < minutes * 60:
                    return True
    except Exception:
        pass
    return False


def backfill_oco(st, ws_t, client, led, prices):
    """تور ایمنی OCO: هر پوزیشن واقعی (بالای غبار) که سفارش فروش باز ندارد،
    OCO با SL/TP همان پوزیشن می‌گیرد — جبران خودکار هر جاافتادگی، هر چرخه.
    اگر قیمت خارج از بازه SL..TP باشد، OCO معنا ندارد و خروج به check_sl_tp واگذار می‌شود."""
    if not (client and getattr(st, 'use_exchange_oco', False)):
        return
    for sym, p in list(led['positions'].items()):
        rv = p.get('real_volume') or 0.0
        if rv <= 1e-12 or sym in led.get('pending_sells', set()):
            continue
        sl, tp = p.get('sl'), p.get('tp')
        if not (sl and tp):
            continue
        price = prices.get(sym)
        if price is None:
            price = _public_price(sym)
            if price:
                prices[sym] = price
        if price is None:
            log.warning('OCO تور ایمنی %s: قیمت لحظه‌ای در دسترس نیست', sym)
            continue
        if not (sl < price < tp):
            log.info('OCO تور ایمنی %s رد شد: قیمت %s خارج از بازه SL..TP — خروج با check_sl_tp',
                     sym, fmt_price(price))
            continue
        vol_o = rv
        avail = currency_available(client, sym)
        if avail is not None:
            vol_o = min(vol_o, avail)
        if vol_o <= 1e-12:
            log.warning('OCO تور ایمنی %s: موجودی فعال صرافی صفر است', sym)
            continue
        code2, data2 = client.place_oco_sell(sym, vol_o, tp, sl)
        ok2 = code2 == 200 and isinstance(data2, dict) and data2.get('status') == 'ok'
        if not ok2:
            log.error('OCO تور ایمنی %s ناموفق: HTTP %s | %s — حفاظت با خود ربات',
                      sym, code2, str(data2)[:120])
            continue
        o2 = (data2.get('order') or {}) if isinstance(data2, dict) else {}
        leg_ids = []
        if isinstance(o2, dict):
            for _k in ('id', 'pairId', 'orderId'):
                if o2.get(_k):
                    leg_ids.append(clean_oid(o2.get(_k)))
        if isinstance(data2, dict) and isinstance(data2.get('orders'), list):
            for _lg in data2['orders']:
                if isinstance(_lg, dict):
                    for _k in ('id', 'pairId', 'orderId'):
                        if _lg.get(_k):
                            leg_ids.append(clean_oid(_lg.get(_k)))
        record_trade(ws_t, 'فروش', sym, '', 'OCO تور ایمنی (جبران)',
                     fmt_price(tp), vol_o, round(vol_o * tp, 2),
                     fmt_price(sl), fmt_price(tp),
                     '|'.join(dict.fromkeys(leg_ids)), ST_PLACED,
                     'SL=' + fmt_price(sl) + ' | TP=' + fmt_price(tp))
        led.setdefault('pending_sells', set()).add(sym)
        log.info('OCO تور ایمنی %s ثبت شد (SL=%s | TP=%s)',
                 sym, fmt_price(sl), fmt_price(tp))


def run(sh, st, rows, state=None):
    dry = st.dry_run
    log.info('ماژول معاملات فعال — حالت: %s', 'شبیه‌سازی (DRY-RUN)' if dry else '⚠️ سفارش واقعی')
    ws_t = sh.worksheet(TRADES_TAB)
    client = make_client()
    if not dry and not client:
        log.error('معامله واقعی فعال است اما کلیدهای API در .env ناقص‌اند — هیچ سفارشی ثبت نشد')
        return

    agg = aggregate_signals(rows)
    prices = {str(r[0]).upper(): parse_price(r[2]) for r in rows if r and r[0]}
    led = read_ledger(ws_t, st.dust_usdt)

    if client and not dry:
        sync_order_statuses(ws_t, led, client, st)
        led = read_ledger(ws_t, st.dust_usdt)  # خواندن مجدد پس از همگام‌سازی
    if client:
        reconcile_real_positions(st, ws_t, client, led, prices)
    if client:
        backfill_oco(st, ws_t, client, led, prices)

    # ۰) اجرای خودکار حد ضرر/حد سود — با اولویت بالا، قبل از سیگنال‌ها
    apply_trailing(st, ws_t, led, prices, client)
    check_sl_tp(st, ws_t, client, dry, led, prices)

    # شمارش روزانه: فقط معاملات خود ربات (تطبیق orderId با دفتر سفارشات)
    # معاملات دستی کاربر سهمیه ربات را مصرف نمی‌کند
    bot_ids = set()
    for _, r in led['rows']:
        for _x in str(r[10]).split('|'):
            _x = clean_oid(_x)
            if _x not in ('', 'None', chr(8212)):
                bot_ids.add(_x)
    api_count = client.trades_today(bot_order_ids=bot_ids) if (client and not dry) else 0
    led['daily_count'] = max(led['daily_count'], api_count or 0)
    if not dry:
        led['daily_count'] = max(api_count or 0, sum(
            1 for _, rr in led['rows']
            if rr[0].startswith(jtoday()) and rr[2].strip() in ('خرید', 'فروش')
            and rr[11].strip() not in (ST_DRY, 'ناموفق')
            and 'OCO' not in str(rr[4])))
    log.info('معاملات امروز ربات: %d (اجراشده از API: %s)', led['daily_count'], api_count)

    cands = [s for s, a in agg.items() if is_buy_candidate(a)]
    log.info('کاندیدهای خرید این اجرا: %s', '، '.join(cands) if cands else 'هیچ')

    # ۱) فروش پوزیشن‌هایی که سیگنال فروش اکثریت گرفته‌اند
    for sym in list(led['positions']):
        a = agg.get(sym)
        if not (a and is_sell_candidate(a)):
            continue
        if sym in led.get('pending_sells', set()):
            log.info('فروش سیگنالی %s رد شد: OCO بومی باز است — خروج با صرافی', sym)
            continue
        if led['daily_count'] >= st.max_daily_trades:
            log.info('فروش %s انجام نشد: سقف معاملات روزانه', sym)
            continue
        p = prices.get(sym) or _public_price(sym)
        if not p:
            continue
        exit_position(st, ws_t, client, sym,
                      f"سیگنال فروش {a['sells']}/{a['total']} تایم‌فریم", p, led)
        led['daily_count'] += 1

    # ۲) خرید کاندیدها با احترام به همه سقف‌ها
    if dry:
        open_pos = len(led['positions'])
    else:
        open_pos = sum(1 for p in led['positions'].values()
                       if (p.get('real_volume') or 0) > 1e-12)
    for sym in cands:
        a = agg[sym]
        if led['daily_count'] >= st.max_daily_trades:
            log.info('خرید %s انجام نشد: سقف معاملات روزانه (%d)', sym, st.max_daily_trades)
            continue
        if sym in led['positions'] or sym in led['pending']:
            log.info('خرید %s انجام نشد: پوزیشن یا سفارش باز موجود است', sym)
            continue
        if st.order_fail_cooldown_min > 0 and recent_failed_buy(led, sym, st.order_fail_cooldown_min):
            log.info('خرید %s انجام نشد: سفارش ناموفق در %d دقیقه اخیر — صبر', sym, st.order_fail_cooldown_min)
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
    bt = (state or {}).get('bt_params') or {}
    write_ranking(sh, st, rows, led, bt)


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


def update_report(sh, st, rows):
    """گزارش عملکرد — از دفتر معاملات + قیمت لحظه‌ای
    P&L شناور: پوزیشن‌های باز × (قیمت فعلی − میانگین ورود)
    P&L محقق: جمع «P&L: …» ثبت‌شده در ردیف‌های فروش"""
    import re as _re
    led = read_ledger(sh.worksheet(TRADES_TAB), st.dust_usdt)
    prices = {str(r[0]).upper(): parse_price(r[2]) for r in rows if r and r[0]}
    for sym in led['positions']:
        if prices.get(sym) is None:
            px = _public_price(sym)
            if px:
                prices[sym] = px

    unreal = 0.0
    pos_value = 0.0
    for sym, p in led['positions'].items():
        px = prices.get(sym)
        if px is None:
            continue
        pos_value += p['volume'] * px
        if p.get('entry_price'):
            unreal += p['volume'] * (px - p['entry_price'])

    realized = 0.0
    closed = wins = 0
    for _, r in led['rows']:
        if r[2].strip() != 'فروش':
            continue
        m = _re.search(r'P&L:\s*([+-]?\d+(?:\.\d+)?)', str(r[12]))
        if not m:
            continue
        v = float(m.group(1))
        realized += v
        closed += 1
        if v > 0:
            wins += 1

    n_buys = sum(1 for _, r in led['rows']
                 if r[2].strip() == 'خرید' and r[11].strip() in EXECUTED)
    winrate = f'{wins * 100 // closed}٪' if closed else '—'

    if st.dry_run:
        cash = st.dry_start_usdt - led['dry_net_spent']
        total = cash + pos_value - st.dry_start_usdt
        cash_row = ['نقد باقی‌مانده (شبیه‌سازی)', fmt_bal(cash), 'USDT']
        total_row = ['P&L کل شبیه‌سازی', f'{total:+.2f}', 'USDT — نقد + ارزش پوزیشن − اولیه']
    else:
        cash_row = ['نقد باقی‌مانده', '—', 'از تب کیف پول (API)']
        total_row = ['P&L کل ربات', f'{unreal + realized:+.2f}', 'USDT — شناور + محقق']

    data = [
        ['📊 گزارش عملکرد ربات', '', f'به‌روزرسانی: {jnow()}'],
        ['شاخص', 'مقدار', 'توضیح'],
        ['حالت', 'شبیه‌سازی (DRY-RUN)' if st.dry_run else '⚠️ معامله واقعی', ''],
        ['موجودی اولیه شبیه‌سازی', fmt_bal(st.dry_start_usdt), 'USDT — از تب تنظیمات'],
        cash_row,
        ['ارزش پوزیشن‌های باز', fmt_bal(pos_value), 'USDT — با قیمت لحظه‌ای'],
        ['پوزیشن‌های باز', len(led['positions']), '، '.join(sorted(led['positions'])) or '—'],
        ['P&L شناور', f'{unreal:+.2f}', 'USDT'],
        ['P&L محقق', f'{realized:+.2f}', 'USDT'],
        total_row,
        ['خریدهای اجراشده', n_buys, ''],
        ['معاملات بسته‌شده', closed, ''],
        ['نرخ برد', winrate, 'از معاملات بسته‌شده'],
    ]
    try:
        ws = sh.worksheet(REPORT_TAB)
    except Exception:
        ws = sh.add_worksheet(title=REPORT_TAB, rows=30, cols=6)
        log.info('تب «گزارش» ساخته شد')
    ws.update(values=data, range_name=f'A1:C{len(data)}')
    log.info('تب گزارش به‌روزرسانی شد — شناور %+.2f | محقق %+.2f USDT', unreal, realized)


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
