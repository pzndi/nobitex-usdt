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
from indicators import sma
from strategy_engine import fetch_candles, fmt_price

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
CLOSED_TAB = 'اتمام معاملات'
ANALYSIS_TAB = 'تحلیل معاملات'   # معاملات بسته‌شده
RANKING_TAB = 'معاملات'        # جدول رتبه‌بندی برای سفارشگزاری
TRADES_TAB = ORDERS_TAB        # سازگاری: دفتر و گزارش از سفارشات خوانده می‌شوند
WALLET_TAB = 'کیف پول'
UNIVERSE_TAB = 'dynamic universe'
REPORT_TAB = 'گزارش'
EFFECTIVE_TAB = 'کانفیگ مؤثر'   # F9-lite: effective config snapshot
GUARDS_TAB = 'گاردها'            # G-guards: live guards status dashboard

ST_DRY = 'شبیه‌سازی شده'
ST_PLACED = 'ثبت‌شده'
ST_OPEN = 'باز'
ST_FILLED = 'پر شد'
ST_PARTIAL = 'بخشی پر و لغو شد'
ST_CANCELLED = 'لغو شده'
ST_PENDING_STOP = 'در انتظار تریگر'
EXECUTED = {ST_DRY, ST_FILLED, ST_PARTIAL}
OPENISH = {ST_PLACED, ST_OPEN, ST_PENDING_STOP}

MIN_TFS = 3       # fallback وقتی st در دسترس نیست — مقدار زنده: st.min_tfs از تب تنظیمات
MIN_TFS_SELL = 3  # fallback فروش — مقدار زنده: st.min_tfs_sell از تب تنظیمات (P1)


def _record_analysis(ws_t, sym, entry_price, exit_price, vol, pnl, pct, dur, reason, led, client, st):
    """ثبت تحلیل معامله بسته‌شده در تب «تحلیل معاملات» با علت‌یابی خودکار"""
    try:
        # ۱. استخراج SL/TP از ledger (آخرین ردیف خرید پر شده)
        sl_set = None
        tp_set = None
        for _, rr in reversed(led.get('rows') or []):
            if (str(rr[1]).strip().upper() == sym.upper()
                    and str(rr[2]).strip() == 'خرید'
                    and str(rr[11]).strip() in EXECUTED):
                sl_set = parse_price(rr[8])
                tp_set = parse_price(rr[9])
                break
        
        # ۲. محاسبه فاصله SL/TP از entry (درصد)
        sl_dist_pct = None
        tp_dist_pct = None
        if entry_price and sl_set:
            sl_dist_pct = (entry_price - sl_set) / entry_price * 100
        if entry_price and tp_set:
            tp_dist_pct = (tp_set - entry_price) / entry_price * 100
        
        # ۳. استخراج ATR و نوسان 4h
        atr = None
        vol_4h = None
        try:
            c = fetch_candles(sym + 'USDT', '60', 100)
            if c and len(c.get('c') or ()) >= 15:
                _atr_series = se_prepare_atr(c)
                atr = _atr_series[-1] if _atr_series and _atr_series[-1] else None
                # نوسان 4h (max high - min low در 4 کندل اخیر)
                highs = c['h']
                lows = c['l']
                lookback = min(4, len(highs))
                max_h = max(highs[-lookback:])
                min_l = min(lows[-lookback:])
                vol_4h = (max_h - min_l) / entry_price * 100 if entry_price else None
        except Exception:
            pass
        
        # ۴. شمارش Scale و تشخیص Scale-in
        scale1_count = 0
        scale2_count = 0
        for _, rr in (led.get('rows') or []):
            if (str(rr[1]).strip().upper() == sym.upper()
                    and str(rr[2]).strip() == 'خرید'
                    and str(rr[11]).strip() in EXECUTED):
                reason_str = str(rr[4]) if len(rr) > 4 else ''
                if 'Scale 1/2' in reason_str:
                    scale1_count += 1
                elif 'Scale 2/2' in reason_str:
                    scale2_count += 1
        scale_in = scale2_count > 0
        
        # ۵. تشخیص Trailing و Partial (از تاریخچه ردیف‌های فروش)
        trailing_active = False
        partial_active = False
        for _, rr in (led.get('rows') or []):
            if str(rr[1]).strip().upper() != sym.upper():
                continue
            reason_str = str(rr[4]) if len(rr) > 4 else ''
            if 'OCO متحرک' in reason_str:
                trailing_active = True
            if 'خروج جزئی' in reason_str:
                partial_active = True
        
        # ۶. تشخیص نوع خروج
        exit_type = 'نامشخص'
        if 'انقضای مدت' in reason:
            exit_type = 'انقضای مدت'
        elif 'خروج جزئی' in reason:
            exit_type = 'خروج جزئی'
        elif 'OCO تور ایمنی' in reason:
            exit_type = 'تور ایمنی'
        elif 'خروج از کیف پول' in reason:
            exit_type = 'فروش دستی/OCO'
        elif 'اجرای سفارش فروش' in reason:
            # تشخیص دقیق SL یا TP
            if sl_set and exit_price and abs(exit_price - sl_set) / sl_set < 0.005:
                exit_type = 'حد ضرر (SL)'
            elif tp_set and exit_price and abs(exit_price - tp_set) / tp_set < 0.005:
                exit_type = 'حد سود (TP)'
            elif pnl > 0:
                exit_type = 'فروش با سود (Trailing)'
            else:
                exit_type = 'فروش با ضرر (SL)'
        
        # ۷. تشخیص نتیجه
        if pnl > 0.01:
            result = 'برد'
        elif pnl < -0.01:
            result = 'باخت'
        else:
            result = 'سربه‌سر'
        
        # ۸. علت‌یابی خودکار
        analysis = 'خروج عادی'
        lesson = '—'
        
        if exit_type == 'حد سود (TP)':
            analysis = 'هدف محقق شد'
            lesson = 'تنظیمات TP مناسب است'
        elif exit_type == 'حد ضرر (SL)':
            if dur and dur < 1:
                analysis = 'ورود در سقف کوتاه‌مدت - SL سریع اجرا شد'
                lesson = 'فیلتر ورود قوی‌تر یا پولبک بیش‌تر'
            elif vol_4h and vol_4h > 3:
                analysis = 'نوسان شدید بازار - SL نزدیک اجرا شد'
                lesson = 'در بازار پرنوسان، SL عریض‌تر یا ATR بیش‌تر'
            else:
                analysis = 'SL اجرا شد - روند نزولی'
                lesson = 'بررسی روند بازار قبل از ورود'
        elif exit_type == 'انقضای مدت':
            if pnl > 0:
                analysis = 'بازار رنج - سود کم در زمان طولانی'
                lesson = 'TP نزدیک‌تر یا timeout کوتاه‌تر'
            else:
                analysis = 'بازار رنج - ضرر در زمان طولانی'
                lesson = 'timeout کوتاه‌تر یا SL نزدیک‌تر'
        elif exit_type == 'خروج جزئی':
            analysis = 'خروج جزئی موفق - قفل سود'
            lesson = 'استراتژی partial مناسب است'
        elif trailing_active:
            if pnl > 0:
                analysis = 'تریلینگ موفق - SL بالا کشیده شد'
                lesson = 'تنظیمات trailing مناسب است'
            else:
                analysis = 'تریلینگ فعال شد ولی ضرر کرد'
                lesson = 'بررسی trail_activation_pct'
        elif scale_in:
            if pnl > 0:
                analysis = 'میانگین‌گیری موفق (Scale-in)'
                lesson = 'G-scale در این نماد خوب کار کرد'
            else:
                analysis = 'میانگین‌گیری ناموفق'
                lesson = 'بررسی فاصله Scale 2/2'
        
        # ۹. ایجاد یا دسترسی به تب تحلیل معاملات
        try:
            ws_a = ws_t.spreadsheet.worksheet(ANALYSIS_TAB)
        except Exception:
            ws_a = ws_t.spreadsheet.add_worksheet(ANALYSIS_TAB, rows=1000, cols=25)
            # هدر ردیف ۱
            ws_a.update(values=[['📊 تحلیل معاملات — علت‌یابی برد/باخت و درس‌آموخته',
                                 'به‌روزرسانی:', jnow()]], range_name='A1:C1')
            # هدر ردیف ۳
            ws_a.update(values=[[
                'زمان خروج', 'نماد', 'نتیجه', 'نوع خروج', 'P&L USDT', 'P&L %',
                'مدت (ساعت)', 'قیمت ورود', 'قیمت خروج', 'SL تنظیم‌شده', 'TP تنظیم‌شده',
                'فاصله SL%', 'فاصله TP%', 'ATR', 'نوسان 4h%', 'تعداد Scale 1/2',
                'تعداد Scale 2/2', 'Scale-in', 'Trailing فعال', 'Partial فعال',
                'علت تحلیل', 'درس‌آموخته'
            ]], range_name='A3:V3')
        
        # به‌روزرسانی زمان
        try:
            ws_a.update(values=[['📊 تحلیل معاملات — علت‌یابی برد/باخت و درس‌آموخته',
                                 'به‌روزرسانی:', jnow()]], range_name='A1:C1')
        except Exception:
            pass
        
        # ۱۰. ثبت ردیف جدید
        ws_a.append_row([
            jnow(), sym, result, exit_type,
            round(pnl, 2), round(pct, 2), dur,
            fmt_price(entry_price) if entry_price else '—',
            fmt_price(exit_price) if exit_price else '—',
            fmt_price(sl_set) if sl_set else '—',
            fmt_price(tp_set) if tp_set else '—',
            round(sl_dist_pct, 2) if sl_dist_pct is not None else '—',
            round(tp_dist_pct, 2) if tp_dist_pct is not None else '—',
            round(atr, 6) if atr else '—',
            round(vol_4h, 2) if vol_4h is not None else '—',
            scale1_count, scale2_count,
            'بله' if scale_in else 'خیر',
            'بله' if trailing_active else 'خیر',
            'بله' if partial_active else 'خیر',
            analysis, lesson
        ])
        
        log.info('تحلیل معامله %s ثبت شد: %s', sym, analysis)
        # G-wincombo: بازمحاسبهٔ تب «ترکیب برنده» پس از هر خروج تازه
        try:
            import win_combo
            win_combo.refresh_after_close(ws_t, st)
        except Exception:
            pass
    except Exception:
        log.exception('خطا در ثبت تحلیل معامله %s', sym)


def record_closed(ws_t, sym, entry_time, entry_price, exit_price, vol, reason, mode, fee_usdt=0.0):
    """ثبت معامله بسته‌شده در تب «اتمام معاملات»"""
    try:
        # G-unit (r17): گارد واحد — درس فساد 07/30 (pct در جای pnl / قیمت نماد دیگر)
        try:
            entry_price = float(entry_price or 0.0)
            exit_price = float(exit_price or 0.0)
            vol = float(vol or 0.0)
        except (TypeError, ValueError):
            entry_price = exit_price = vol = 0.0
        _unit_ok = entry_price > 0 and exit_price > 0 and vol > 0
        if _unit_ok and abs(vol * (exit_price - entry_price)) > 0.30 * vol * entry_price + 0.05:
            _unit_ok = False
        if not _unit_ok:
            log.error('G-unit: ورودی ناسازگار در بستن %s (entry=%s exit=%s vol=%s | %s) — با پرچم ثبت شد',
                      sym, entry_price, exit_price, vol, reason)
            mode = (str(mode) + ' | ⚠️ G-unit')[:120]
        pnl = vol * (exit_price - entry_price) - float(fee_usdt or 0.0)
        pct = (exit_price / entry_price - 1) * 100 if entry_price else 0.0
        dur = '—'
        try:
            import jdatetime
            t0 = jdatetime.datetime.strptime(str(entry_time), '%Y/%m/%d %H:%M')
            dur = round((jdatetime.datetime.fromgregorian(datetime=_now_tehran().replace(tzinfo=None)) - t0).total_seconds() / 3600, 1)
        except Exception:
            pass
        ws_c = ws_t.spreadsheet.worksheet(CLOSED_TAB)
        try:
            ws_c.update(values=[['🏁 معاملات بسته‌شده — خروج، سود/زیان و دلیل',
                                 'به‌روزرسانی:', jnow()]], range_name='A1:C1')
        except Exception:
            pass
        ws_c.append_row([jnow(), sym, entry_time, fmt_price(entry_price),
                         fmt_price(exit_price), vol, round(pnl, 2), round(pct, 2),
                         reason, dur, mode])
        log.info('معامله %s بسته شد — P&L: %+.2f USDT (%s)', sym, pnl, reason)
    except Exception:
        log.exception('خطا در ثبت معامله بسته‌شده %s', sym)


# ================= کلاینت API معاملاتی =================
def record_trade(ws_t, action, sym, tf, reason, price, volume, amount, sl, tp, oid, status, msg):
    """ثبت سفارش در دفتر «سفارشات» — هر سفارش یک ردیف"""
    ws_t.append_row([jnow(), sym, action, tf, reason, price, volume, amount,
                     sl, tp, oid, status, msg])
    try:
        ws_t.update(values=[['📒 دفتر سفارش‌ها — ثبت، وضعیت خودکار و SL/TP داینامیک',
                             'به‌روزرسانی:', jnow()]], range_name='A1:C1')
    except Exception:
        pass
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
                out = dict(data)
                out['status'] = 'ok'
                return code, out
            return code, {'status': 'failed', 'code': 'TransitionNotApplied',
                          'message': 'updatedStatus=%s orderStatus=%s' % (
                              data.get('updatedStatus'), o.get('status')),
                          'order': o}
        return code, data

    def place_oco_sell(self, symbol, volume, take_profit, stop_price, stop_limit=None, ref_price=None):
        """OCO فروش — حد سود (limit) + حد ضرر (stop-limit) بومی روی صرافی
        مستندات p117: mode=oco + price + stopPrice + stopLimitPrice
        شرط فروش: stopPrice < قیمت بازار < price
        G4 (اپراتور 1405/08/02): کلمپ و پایش شرط قیمت داخل خود متد —
        پوشش هر ۷ نقطهٔ فراخوان بدون تغییر امضای فراخوان‌ها:
        ۱) SL به زیر 99.6٪ قیمت مرجع (ref_price یا لحظه‌ای عمومی) کلمپ می‌شود
        ۲) پاسخ PriceConditionFailed → یک تلاش مجدد با قیمت تازه
        ۳) شکست نهایی → همان پاسخ برمی‌گردد (تور ایمنی/F5 چرخهٔ بعد جبران می‌کند)"""
        def _oco_post(tp, sp, slt):
            if slt is None:
                slt = (sp or 0) * 0.995
            payload = {'type': 'sell',
                       'market': f'{symbol}USDT',
                       'srcCurrency': symbol.lower(),
                       'dstCurrency': 'usdt',
                       'price': fmt_amt(tp),
                       'amount': fmt_amt(volume),
                       'execution': 'limit',
                       'mode': 'oco',
                       'stopPrice': fmt_amt(sp),
                       'stopLimitPrice': fmt_amt(slt)}
            return self._sc.post('/market/orders/add', payload)

        tp, sp, slt = take_profit, stop_price, stop_limit

        def _live_px():
            if ref_price:
                return ref_price
            try:
                return _public_price(symbol)
            except Exception:
                return None

        px = _live_px()
        if px and px > 0 and sp and sp > px * (1 - 0.004):
            _cap = px * (1 - 0.004)
            log.info('G4: OCO %s SL %s → کلمپ %s (قیمت %s)',
                     symbol, fmt_price(sp), fmt_price(_cap), fmt_price(px))
            sp = _cap
            if slt is not None and slt > sp * 0.995:
                slt = sp * 0.995
        code, data = _oco_post(tp, sp, slt)
        ok = code == 200 and isinstance(data, dict) and data.get('status') == 'ok'
        if not ok and 'PriceCondition' in str(data):
            px2 = _live_px()
            if px2 and px2 > 0:
                sp2 = min(sp, px2 * (1 - 0.004)) if sp else px2 * (1 - 0.004)
                tp2 = tp
                if tp2 and tp2 <= px2:
                    tp2 = px2 * 1.001
                log.warning('G4: OCO %s رد شد (شرط قیمت) — تلاش مجدد: SL=%s TP=%s (قیمت %s)',
                            symbol, fmt_price(sp2), fmt_price(tp2), fmt_price(px2))
                code, data = _oco_post(tp2, sp2, None)
        return code, data


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


def is_buy_candidate(a, st=None):
    _min_tfs = st.min_tfs if st is not None else MIN_TFS
    return (a['buys'] >= _min_tfs and a['buys'] >= (a['total'] + 1) // 2
            and a['buys'] > a['sells'])


def is_sell_candidate(a, st=None):
    _min_tfs = st.min_tfs_sell if st is not None else MIN_TFS_SELL
    return (a['sells'] >= _min_tfs and a['sells'] >= (a['total'] + 1) // 2
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
                # F9 (اپراتور 1405/08/01): مرزگذاری پوزیشنی — با خروج کامل
                # (net <= 0) انباشتگرهای نماد صفر می‌شوند تا entry_price
                # پوزیشن بعدی = VWAP همین دوره باشد نه میانگین بی‌مرز کل
                # دفتر (شاهد: ZEC 1338.50 کاذب در برابر VWAP 1236.15).
                # خروج کامل از هر مسیر (OCO/TTL/گارد خودی/G-timeout) از
                # همین شاخه عبور می‌کند. dust باقی‌مانده عمداً حفظ می‌شود.
                if bought.get(sym, [0.0])[0] - s_[0] <= 1e-12:
                    bought.pop(sym, None)
                    sold.pop(sym, None)
                    sltp.pop(sym, None)
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
    # F10 (اپراتور 1405/08/01): وضعیت OCOهای همین اجرا — ردیف‌های ثبت‌شده
    # بعد از snapshot دفتر در led['rows'] نیستند؛ G-scale باید آنها را هم
    # برای لغو ببیند (شاهد: MEW 15:37 — لغوی بی‌اثر → AmountToLow).
    _oco_placed_run = {}
    _scale_fb_run = {}
    for row_num, r in led['rows']:
        # OCO = two legs; ids joined with | in the ledger
        oids = [clean_oid(x) for x in str(r[10]).split('|')]
        oids = [x for x in oids if x and x != chr(8212)]
        # ردیف OCO بدون شناسه → وضعیت‌خوانی ممنوع (شبهه‌ی قاطی شدن با خرید مرتبط)
        # تور ایمنی در همین چرخه شناسه می‌گذارد؛ تیک بعدی وضعیت را می‌خواند
        if str(r[4]).find('OCO') >= 0 and not oids:
            # لاگ فقط برای ردیف‌های باز — ردیف‌های پایانی (پر/لغو شده) هر تیک اسپم نمی‌شوند
            if str(r[11]).strip() in OPENISH:
                log.info('OCO بدون شناسه (ردیف %s، %s) — منتظر تور ایمنی برای درج شناسه', row_num, r[1])
            continue
        if not oids or str(r[11]).strip() not in OPENISH:
            continue
        legs = {}
        for oid in oids:
            code, data = client.order_status(oid)
            # G-fix: وقتی یک لگ OCO اجرا می‌شود، لگ دیگر حذف می‌شود (404)
            # این لگ را نادیده بگیریم - لگ دیگر Done خواهد بود
            if code == 404 or (isinstance(data, dict) and str(data.get('error')) == 'NotFound'):
                continue
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
                # G-partial (P2b): خریدِ نیمه‌پرِ لغوشده -> «پر شد» با حجم واقعی؛
                # گذار fill همان تیک روی بخشِ پرشده OCO می‌گذارد. («بخشی پر» =
                # لیمبوی بی‌حفاظ: نه پوزیشن، نه OCO، نه check_sl_tp.)
                # فروش‌ها دست‌نخورده — همان ST_PARTIAL قبلی.
                if str(r[2]).strip() == 'خرید':
                    new_st = ST_FILLED
                else:
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
            # G-mem (P5): حافظهٔ درون‌تیکی همگام شود — وگرنه _entry_fill/VWAPِ
            # همین تیک وضعیت کهنه می‌دید (شاهد 19:38: VWAP=169.42 از چرخهٔ
            # بستهٔ قبلی به‌جای 172.19 -> باند غلط -> defer بی‌مورد).
            r[11] = new_st
            if vol_update is not None:
                ws_t.update_cell(row_num, 7, vol_update)
                r[6] = vol_update
            log.info('وضعیت سفارش %s → %s', '|'.join(oids), new_st)

        sym_c = r[1].strip().upper()
        if r[2].strip() == 'خرید' and new_st == ST_FILLED:
            log.info('گذار خرید به پرشد %s | use_oco=%s | در pending_sells=%s',
                     sym_c,
                     (getattr(st, 'use_exchange_oco', None) if st is not None else None),
                     sym_c in led.get('pending_sells', set()))
            # P2-1 (fill-time): مهر زمان fill در ستون پیام — سن پوزیشن timeout و
            # مدت نگهداری از fill محاسبه شوند نه زمان ثبت سفارش (شاهد: BAT با سن
            # کاذب 18.1h در ۵ دقیقه پس از fill). یک‌بار؛ گارد fill@ دارد.
            _msg = str(r[12] or '')
            if 'fill@' not in _msg:
                try:
                    ws_t.update_cell(row_num, 13, (_msg + ' | fill@' + jnow())[:250])
                except Exception:
                    pass
            # بهبود ۲ (G-fillanchor): SL/TP از قیمت واقعی fill بازمحاسبه — ریشهٔ
            # «fill روی استاپ»: SL/TP ردیف لنگر قیمت سیگنال است ولی fill پولبکی
            # ~۱٪ پایین‌تر رخ می‌دهد. ATR از خود ردیف بازیابی می‌شود
            # (ATR = (سیگنال−SL)/ضریب) — سازگار با ریسک لحظهٔ تصمیم. fail-open.
            try:
                _fill_px = parse_price(o.get('averagePrice')) or parse_price(o.get('price'))
                _p_sig = parse_price(r[5])
                _sl_old, _tp_old = parse_price(r[8]), parse_price(r[9])
                _slm = getattr(st, 'sl_atr_mult', 0) or 0
                _tpm = getattr(st, 'tp_atr_mult', 0) or 0
                if (_fill_px and _p_sig and _sl_old and _tp_old and _slm > 0
                        and _tpm > 0 and abs(_fill_px / _p_sig - 1) < 0.20
                        and _p_sig > _sl_old):
                    _atr = (_p_sig - _sl_old) / _slm
                    _sl_new = _fill_px - (_p_sig - _sl_old)
                    _tp_new = _fill_px + (_tp_old - _p_sig)
                    # G-cap2 (اپراتور 1405/08/01): TP≤0.80% ناخالص، SL≤1.00% ناخالص
                    # هدف: افزایش نرخ برد — TP نزدیک‌تر (پرشدن بیشتر)، SL بیرون نویز
                    # کارمزد واقعی نوبیتکس 0.18% (0.09% خرید + 0.09% فروش)
                    # G-wincombo v4 (حاکمیت تب — اجازهٔ اپراتور 1405/08/04): نماد داخل
                    # تب «ترکیب برنده» از کپ G-cap2 عبور می‌کند؛ شیفت لنگر می‌ماند و
                    # باند تب حول fill حفظ می‌شود. خطا/خالی → کپ (fail-open به رفتار فعلی).
                    _wc_skip_cap = False
                    try:
                        import win_combo as _wc_m
                        _wc_p = _wc_m.get_params(ws_t, st)
                        _wc_skip_cap = bool(_wc_p and sym_c in _wc_p)
                    except Exception:
                        _wc_skip_cap = False
                    if _wc_skip_cap:
                        log.info('G-wincombo v4 %s: عبور از کپ — باند تب حول fill حفظ شد (SL=%s | TP=%s)',
                                 sym_c, fmt_price(_sl_new), fmt_price(_tp_new))
                    if not _wc_skip_cap:
                        _tp_max = _fill_px * (1 + 0.80 / 100.0)
                        _sl_min = _fill_px * (1 - 1.00 / 100.0)
                        if _tp_new > _tp_max:
                            _tp_new = _tp_max
                        if _sl_new < _sl_min:
                            _sl_new = _sl_min
                    if 0 < _sl_new < _fill_px < _tp_new:
                        r[8] = fmt_price(_sl_new)
                        r[9] = fmt_price(_tp_new)
                        try:
                            ws_t.update_cell(row_num, 9, r[8])
                            ws_t.update_cell(row_num, 10, r[9])
                        except Exception:
                            pass
                        log.info('G-fillanchor %s: SL %s → %s | TP %s → %s (fill=%.6g)',
                                 sym_c, fmt_price(_sl_old), r[8],
                                 fmt_price(_tp_old), r[9], _fill_px)
            except Exception:
                pass

        # معامله واقعی بسته شد: فروش کامل پر شد → ثبت در «اتمام معاملات»
        if r[2].strip() == 'فروش' and new_st == ST_FILLED:
            pos_c = led['positions'].get(sym_c) or {}
            entry_c = pos_c.get('entry_price') or parse_price(r[5]) or 0.0
            vol_c = exit_vol or (parse_price(r[6]) or 0.0)
            # N7: real fills for exit legs + last-buy entry (fee-aware)
            _xf = _exit_fill(client, oids)
            exit_n7 = ((_xf[0] if _xf and _xf[0] else None)
                       or exit_px or (parse_price(r[5]) or 0.0))
            if _xf and _xf[1]:
                vol_c = _xf[1]
            sell_fee_n7 = (_xf[2] if _xf else 0.0)
            entry_n7, buy_fee_n7 = _entry_fill(client, led, sym_c)
            entry_n7 = entry_n7 or entry_c
            t_in = next((_fill_time_of(rr) for _, rr in reversed(led['rows'])
                         if rr[1].strip().upper() == sym_c and rr[2].strip() == 'خرید'
                         and rr[11].strip() in EXECUTED), '—')
            record_closed(ws_t, sym_c, t_in, entry_n7, exit_n7,
                          vol_c, 'اجرای سفارش فروش', 'واقعی', fee_usdt=sell_fee_n7 + buy_fee_n7)
            # G-analysis: ثبت تحلیل معامله در تب «تحلیل معاملات»
            try:
                _pnl_an = vol_c * (exit_n7 - entry_n7) - sell_fee_n7 - buy_fee_n7
                _pct_an = (exit_n7 / entry_n7 - 1) * 100 if entry_n7 else 0.0
                _dur_an = '—'
                try:
                    import jdatetime as _jd
                    import datetime as _dt
                    _t0 = _jd.datetime.strptime(str(t_in).strip(), '%Y/%m/%d %H:%M')
                    _now_a = (_dt.datetime.now(_dt.timezone.utc)
                              + _dt.timedelta(hours=3, minutes=30)).replace(tzinfo=None)
                    _dur_an = round((_now_a - _t0.togregorian()).total_seconds() / 3600, 1)
                except Exception:
                    pass
                _record_analysis(ws_t, sym_c, entry_n7, exit_n7, vol_c,
                                _pnl_an, _pct_an, _dur_an, 'اجرای سفارش فروش',
                                led, client, st)
            except Exception:
                log.exception('خطا در ثبت تحلیل معامله %s', sym_c)
            # Fix-B: مهر P&L رفت‌وبرگشت (مبنای آخرین خرید) در ردیف فروش —
            # کول‌داون ورود مجدد و P&L محقق گزارش از همین سلول می‌خوانند
            entry_b = entry_n7
            exit_b = exit_n7
            if entry_b and exit_b and vol_c:
                _stamp_pnl(ws_t, row_num, r[12], vol_c * (exit_b - entry_b) - sell_fee_n7 - buy_fee_n7, now_ref=jnow())

        # OCO بومی صرافی — در گذار خرید به «پر شد»
        if (st is not None and getattr(st, 'use_exchange_oco', False)
                and r[2].strip() == 'خرید' and new_st == ST_FILLED):
            
            _is_scale_in = sym_c in led.get('pending_sells', set())
            
            if _is_scale_in:
                # G-scale VWAP: Scale-in detected! Cancel existing OCO and recalculate based on VWAP
                log.info('G-scale: Scale-in detected for %s. Canceling existing OCO...', sym_c)
                # F10 (اپراتور 1405/08/01): لغوی راستی‌آزمایی‌شدهٔ OCO در G-scale.
                # ریشهٔ MEW 15:37: هر دو پلهٔ fill در همان اجرا رسیدند؛ ردیف OCO#1
                # بعد از snapshot ثبت شده بود → اسکن led['rows'] آن را نمی‌دید →
                # «لغو» بی‌اثر + ثبت مجدد با موجودی قفل‌شده در OCO زنده = AmountToLow.
                _tgt = [x for x in (_oco_placed_run.get(sym_c) or []) if x]
                _tgt_rows = []
                for _rn, _rr in led['rows']:
                    if (_rr[1].strip().upper() == sym_c and 'OCO' in str(_rr[4])
                            and _rr[11].strip() in OPENISH):
                        _oids2 = [clean_oid(x) for x in str(_rr[10]).split('|')]
                        _tgt.extend(x for x in _oids2 if x and x != chr(8212))
                        _tgt_rows.append(_rn)
                _tgt = list(dict.fromkeys(_tgt))
                if not _tgt:
                    log.info('G-scale %s: OCO زنده‌ای برای لغو نیست — ثبت مستقیم OCO تازه روی کل موجودی', sym_c)
                else:
                    _cancel_ok = True
                    for _oid in _tgt:
                        _cc, _cd = client.cancel_order(_oid)
                        _ok_c = (_cc == 200 and (not isinstance(_cd, dict)
                                                 or _cd.get('status') != 'failed'))
                        if not _ok_c and isinstance(_cd, dict) and str(_cd.get('error')) == 'NotFound':
                            _ok_c = True
                        if not _ok_c:
                            _cancel_ok = False
                            log.error('G-scale %s: لغو پایه OCO %s ناموفق: HTTP %s | %s',
                                      sym_c, _oid, _cc, str(_cd)[:100])
                    if not _cancel_ok:
                        log.error('G-scale %s: لغو ناقص — OCO صرافی دست‌نخورده ماند؛ انکرهای فعلی حفظ و ثبت مجدد skipped',
                                  sym_c)
                        continue
                    for _rn in _tgt_rows:
                        ws_t.update_cell(_rn, 12, ST_CANCELLED)
                    # G-log (P4): لغوی موفق تا حالا بی‌صدا بود (شاهد: ردیف 698
                    # ساعت 20:49). یک خط INFO برای ردگیری.
                    log.info('G-scale %s: لغو %d لگ OCO انجام شد (ردیف‌ها: %s)',
                             sym_c, len(_tgt), _tgt_rows or '—')
                    # انکرهای این ردیف (fill-anchored، پیش از بازنویسی VWAP) برای fallback
                    _scale_fb_run[sym_c] = (parse_price(r[8]), parse_price(r[9]))
                led.get('pending_sells', set()).discard(sym_c)
                
                # Fetch VWAP from real trades
                _vwap, _ = _entry_fill(client, led, sym_c)
                if _vwap and _vwap > 0:
                    _fill_px = _vwap
                    # G-fix: اگر VWAP بالاتر از قیمت بازار است، از قیمت بازار استفاده کن
                    # این از خطای PriceConditionFailed و اجرای سریع SL جلوگیری می‌کند
                    # F4 (اپراتور 1405/08/01): prices در این تابع تعریف نشده بود و
                    # گذار scale-in را با NameError می‌کشت (حادثهٔ 06:26 MEW).
                    # تکمیل کلمپ نیمه‌کارهٔ G-fix با قیمت لحظه‌ای:
                    _current_px = None
                    try:
                        _current_px = _public_price(sym_c)
                    except Exception:
                        _current_px = None
                    if _current_px and _current_px < _fill_px:
                        _fill_px = _current_px
                    _p_sig = parse_price(r[5])
                    _sl_old, _tp_old = parse_price(r[8]), parse_price(r[9])
                    _slm = getattr(st, 'sl_atr_mult', 0) or 0
                    _tpm = getattr(st, 'tp_atr_mult', 0) or 0
                    if (_p_sig and _sl_old and _tp_old and _slm > 0 and _tpm > 0 and _p_sig > _sl_old):
                        _atr = (_p_sig - _sl_old) / _slm
                        _sl_new = _fill_px - (_p_sig - _sl_old)
                        _tp_new = _fill_px + (_tp_old - _p_sig)
                        # G-cap2 (اپراتور 1405/08/01): TP≤0.88% ناخالص، SL≤1.10% ناخالص
                        # (نسخه VWAP scale-in — همان نسبت +10٪ نسبت به site1)
                        # G-wincombo v4 (حاکمیت تب — اجازهٔ اپراتور 1405/08/04): گارد
                        # عبور از کپ برای نمادهای تب — همان قاعدهٔ سایت ۱ (VWAP scale-in).
                        _wc_skip_cap = False
                        try:
                            import win_combo as _wc_m
                            _wc_p = _wc_m.get_params(ws_t, st)
                            _wc_skip_cap = bool(_wc_p and sym_c in _wc_p)
                        except Exception:
                            _wc_skip_cap = False
                        if _wc_skip_cap:
                            log.info('G-wincombo v4 %s: عبور از کپ (VWAP) — باند تب حفظ شد (SL=%s | TP=%s)',
                                     sym_c, fmt_price(_sl_new), fmt_price(_tp_new))
                        if not _wc_skip_cap:
                            _tp_max = _fill_px * (1 + 0.88 / 100.0)
                            _sl_min = _fill_px * (1 - 1.10 / 100.0)
                            if _tp_new > _tp_max:
                                _tp_new = _tp_max
                            if _sl_new < _sl_min:
                                _sl_new = _sl_min
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
            sl_o, tp_o = parse_price(r[8]), parse_price(r[9])
            if vol_o <= 1e-12 or not sl_o or not tp_o:
                log.warning('OCO در sync برای %s رد شد: vol=%s | sl=%s | tp=%s | matchedAmount=%s',
                            sym_c, vol_o, sl_o, tp_o, o.get('matchedAmount'))
            if vol_o > 1e-12 and sl_o and tp_o:
                # F7a (اپراتور 1405/08/01): قیمت تازه + کلمپ SL + defer — ریشهٔ
                # PriceConditionFailed در گذار fill (MEW 08:53 و 1M_PEPE 10:15×2)
                _px_f7 = None
                try:
                    _px_f7 = _public_price(sym_c)
                except Exception:
                    _px_f7 = None
                if _px_f7 and _px_f7 > 0:
                    if _px_f7 <= sl_o or _px_f7 >= tp_o:
                        # G-instant-exit (P3): قیمت لحظه‌ای بیرونِ باند یعنی TP/SL
                        # همین حالا لمس شده. واگذاری به check_sl_tp پنجرهٔ بی‌حفاظ
                        # می‌سازد (شاهد 05:34: سه fill در 173.52 بالای TP؛ خروج
                        # نهایی 168.45 -> ضرر -0.14 به‌جای سود ~+0.10).
                        _why = 'حد سود' if _px_f7 >= tp_o else 'حد ضرر'
                        log.info('G-instant-exit %s: قیمت لحظه‌ای %s بیرونِ باند SL=%s..TP=%s — فروش فوری (%s)',
                                 sym_c, fmt_price(_px_f7), fmt_price(sl_o), fmt_price(tp_o), _why)
                        _sold = False
                        if st is not None:
                            _sold = sell_one(st, ws_t, client, False, sym_c, _why,
                                             _px_f7, vol_o, led)
                        if _sold:
                            led.setdefault('pending_sells', set()).add(sym_c)
                        else:
                            log.warning('G-instant-exit %s انجام نشد — خروج به check_sl_tp واگذار شد', sym_c)
                        continue
                    _sl_cap_f7 = _px_f7 * (1 - 0.004)
                    if sl_o > _sl_cap_f7:
                        log.info('OCO گذار fill %s: SL %s → کلمپ %s (قیمت لحظه‌ای %s)',
                                 sym_c, fmt_price(sl_o), fmt_price(_sl_cap_f7), fmt_price(_px_f7))
                        sl_o = _sl_cap_f7
                        try:
                            r[8] = fmt_price(sl_o)
                            ws_t.update_cell(row_num, 9, r[8])
                        except Exception:
                            pass
                code2, data2 = client.place_oco_sell(sym_c, vol_o, tp_o, sl_o)
                ok2 = code2 == 200 and isinstance(data2, dict) and data2.get('status') == 'ok'
                # F10d: شکست ثبت با انکر VWAP → بازگشت با انکرهای پیش از اسکیل‌این
                # (الگوی F5 در تریلینگ — کاهش پنجرهٔ بی‌حفاظتی به ثانیه)
                if not ok2 and sym_c in _scale_fb_run:
                    _fb = _scale_fb_run.pop(sym_c)
                    if (_fb and _fb[0] and _fb[1]
                            and (abs(_fb[0] - sl_o) > 1e-12 or abs(_fb[1] - tp_o) > 1e-12)):
                        try:
                            code2, data2 = client.place_oco_sell(sym_c, vol_o, _fb[1], _fb[0])
                        except Exception:
                            code2, data2 = None, None
                        ok2 = code2 == 200 and isinstance(data2, dict) and data2.get('status') == 'ok'
                        if ok2:
                            sl_o, tp_o = _fb[0], _fb[1]
                            r[8], r[9] = fmt_price(sl_o), fmt_price(tp_o)
                            try:
                                ws_t.update_cell(row_num, 9, r[8])
                                ws_t.update_cell(row_num, 10, r[9])
                            except Exception:
                                pass
                            log.warning('G-scale %s: ثبت OCO با انکر VWAP ناموفق — بازگشت به انکرهای پیش از اسکیل‌این (SL=%s | TP=%s)',
                                        sym_c, r[8], r[9])
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
                    _oco_placed_run[sym_c] = [x for x in oid_oco.split('|') if x]
                    log.info('OCO بومی صرافی برای %s ثبت شد (TP=%s | SL=%s)',
                             sym_c, fmt_price(tp_o), fmt_price(sl_o))
                else:
                    log.error('ثبت OCO برای %s ناموفق (HTTP %s): %s — حفاظت SL/TP با خود ربات',
                              sym_c, code2, str(data2)[:120])


def _band_tag(st, row):
    """G-band: display-only label of the SL/TP band source for the buy
    ledger row. Implied ratio = (TP-entry)/(entry-SL) from the signal row;
    equal to sheet ratio -> 'sheet', else -> 'backtest'. No trading logic."""
    try:
        sl_c, tp_c = parse_price(row[9]), parse_price(row[10])
        px = parse_price(row[2]) or 0.0
        if not (sl_c and tp_c and px) or px <= sl_c or tp_c <= px:
            return ''
        d_sl, d_tp = px - sl_c, tp_c - px
        if d_sl <= 0 or d_tp <= 0:
            return ''
        ratio = d_tp / d_sl
        sheet_ratio = (st.tp_atr_mult / st.sl_atr_mult) if st.sl_atr_mult else None
        if sheet_ratio and abs(ratio - sheet_ratio) < 0.01:
            return ' | band: sheet (SLx%.1f/TPx%.1f)' % (st.sl_atr_mult, st.tp_atr_mult)
        return ' | band: backtest (ratio %.2f)' % ratio
    except Exception:
        return ''


def se_prepare_atr(c):
    """G-trail: compute ATR14 series from candle dict (pure python)."""
    h, l, cl = c['h'], c['l'], c['c']
    n = len(cl)
    if n < 15:
        return [None] * n
    trs = [h[0] - l[0]]
    for i in range(1, n):
        trs.append(max(h[i] - l[i], abs(h[i] - cl[i-1]), abs(l[i] - cl[i-1])))
    out = [None] * n
    a = sum(trs[1:15]) / 14
    out[14] = a
    for i in range(15, n):
        a = (a * 13 + trs[i]) / 14
        out[i] = a
    return out


def _btc_trend_bearish():
    """G-trend: True if BTC 4h SMA20 < SMA50 (bearish regime).
    One API call, cached by caller if needed."""
    try:
        c = fetch_candles('BTCUSDT', '240', 100)
        if not c or not c.get('c') or len(c['c']) < 50:
            return False  # داده ناکافی - fail-open
        closes = c['c']
        fa = sma(closes, 20)
        sl2 = sma(closes, 50)
        if fa[-1] is not None and sl2[-1] is not None:
            return fa[-1] < sl2[-1]
    except Exception:
        pass
    return False  # fail-open: if we can't check, don't block


RISK_TARGET_USDT = 0.50  # گزینهٔ الف (G-volsize): سقف ریسک دلاری هر معامله — قابل ارتقا به کلید شیت
MAX_SL_BAND_PCT = 8.0    # گزینهٔ ب (G-bandcap): سقف عرض استاپ ٪ — فیلتر دُم پرنوسان
MAX_LOCAL_PREMIUM_PCT = 10.0   # G-premium: سقف پریمیوم محلی/جهانی
MAX_MARK_DEVIATION_PCT = 2.0   # G-mark-dev: سقف فاصله قیمت محلی از جهانی
_MARK_CACHE = {}               # کش موقت قیمت‌های mark برای هر چرخه


def _public_mark(sym):
    if sym in _MARK_CACHE:
        return _MARK_CACHE[sym]
    try:
        pair = f'{sym.lower()}-usdt'
        r = requests.post('https://apiv2.nobitex.ir/market/stats',
                          json={'stats': pair},
                          headers={'User-Agent': 'TraderBot/NobitexSheetBot-2.0'},
                          timeout=15)
        st_ = (r.json().get('stats') or {}).get(pair) or {}
        mk = float(st_.get('mark') or 0)
        val = mk if mk > 0 else None
        _MARK_CACHE[sym] = val
        return val
    except Exception:
        _MARK_CACHE[sym] = None
        return None


def clear_mark_cache():
    _MARK_CACHE.clear()


def _sl_width_pct(row, st):
    """عرض استاپ تخمینی (٪ از fill): ضریبSL×ATR ÷ fill + اسلیپیج ۰.۵٪.
    ATR از ردیف ((سیگنال−SL)÷ضریب)؛ fill تخمینی با پولبک G-vpull.
    دادهٔ ناقص → None (fail-open)."""
    try:
        p = parse_price(row[2])
        sl = parse_price(row[9])
        slm = getattr(st, 'sl_atr_mult', 0) or 0
        if p and sl and slm > 0 and 0 < sl < p:
            atr = (p - sl) / slm
            pull = _eff_pullback_pct(row, st) / 100.0
            fill_est = p * (1 - pull)
            if fill_est > 0:
                return (slm * atr) / fill_est * 100.0 + 0.5
    except Exception:
        pass
    return None


def _eff_order_usdt(row, st):
    """گزینهٔ الف (cap-style): min(ORDER_SIZE, RISK_TARGET ÷ عرض).
    دادهٔ ناقص → ORDER_SIZE (رفتار فعلی)."""
    w = _sl_width_pct(row, st)
    if w and w > 0.5:
        return min(st.order_size_usdt, RISK_TARGET_USDT / (w / 100.0))
    return st.order_size_usdt


def _bb_lower_band(closes, period=20, std=2.0):
    """G-scale: Bollinger lower band (pure python)."""
    n = len(closes)
    if n < period:
        return None
    slice_c = closes[-period:]
    mean = sum(slice_c) / period
    variance = sum((c - mean) ** 2 for c in slice_c) / period
    return mean - std * (variance ** 0.5)


def _calc_scaled_entries(sym, price, row, st):
    """G-scale v2: نوسان-محور - محاسبه ۲ قیمت ورود بر اساس نوسان ۴ ساعت اخیر
    - نوسان = (max(highs[-4:]) - min(lows[-4:])) / price × 100
    - مپینگ نوسان به pullback در محدوده [0.05%, 0.5%]:
      vol ≤ 0.5% → pullback = 0.05% (کم‌نوسان = ورود نزدیک)
      vol ≥ 5.0% → pullback = 0.5% (پرنوسان = ورود دورتر)
      بین این دو → خطی
    - Scale 1/2 = price * (1 - pullback/100)
    - Scale 2/2 = Scale 1/2 * 0.995 (همیشه 0.5% پایین‌تر از Scale 1/2)
    """
    try:
        c = fetch_candles(sym + 'USDT', '60', 10)
        if not c or len(c.get('c', [])) < 5:
            return None, None
        highs, lows = c['h'], c['l']

        # محاسبه نوسان در ۴ ساعت اخیر (۴ کندل ۱ ساعته)
        lookback = min(4, len(highs))
        max_high_4h = max(highs[-lookback:])
        min_low_4h = min(lows[-lookback:])
        volatility_pct = (max_high_4h - min_low_4h) / price * 100

        # مپینگ نوسان به pullback در محدوده [0.1%, 1.5%]
        MIN_VOL = 0.5   # نوسان کم → حداقل پولبک
        MAX_VOL = 5.0   # نوسان زیاد → حداکثر پولبک
        MIN_PB = 0.05   # حداقل پولبک (٪) - نزدیک به بازار برای پر شدن سریع‌تر
        MAX_PB = 0.5    # حداکثر پولبک (٪) - حداکثر فاصله از بازار
        if volatility_pct <= MIN_VOL:
            pullback_pct = MIN_PB
        elif volatility_pct >= MAX_VOL:
            pullback_pct = MAX_PB
        else:
            ratio = (volatility_pct - MIN_VOL) / (MAX_VOL - MIN_VOL)
            pullback_pct = MIN_PB + ratio * (MAX_PB - MIN_PB)

        # Scale 1/2: قیمت ورود اول
        price_1 = price * (1 - pullback_pct / 100.0)

        # Scale 2/2: همیشه 0.5% پایین‌تر از Scale 1/2
        price_2 = price_1 * 0.995

        return price_1, price_2
    except Exception:
        return None, None


def buy_one(st, ws_t, client, dry, sym, a, price, led, coid=None):
    row = a['best'][1]
    tf, sl, tp = row[1], row[9], row[10]
    # G-wincombo: هندسهٔ per-symbol از تب «ترکیب برنده» — نماد حاضر → override
    # گارد: بافر SL نسبت به fill تخمینی + حداقل RR؛ رد → هندسهٔ ردیف حفظ می‌شود.
    # row[9]/row[10] هم به‌روز می‌شوند تا G-volsize/برچسب باند سازگار بمانند.
    try:
        import win_combo
        _wcp = win_combo.get_params(ws_t, st)
        if sym in _wcp:
            _pull_e = _eff_pullback_pct(row, st) / 100.0
            _buf_e = getattr(st, 'slbuf_min_pct', 0.5) / 100.0
            _slp_e = _wcp[sym]['sl_pct'] / 100.0
            _tpp_e = _wcp[sym]['tp_pct'] / 100.0
            if _slp_e >= _pull_e + _buf_e and _tpp_e >= 1.2 * _slp_e:
                sl = fmt_price(price * (1 - _slp_e))
                tp = fmt_price(price * (1 + _tpp_e))
                row[9], row[10] = sl, tp
                log.info('G-wincombo %s: SL%%=%.2f TP%%=%.2f از تب ترکیب برنده', sym,
                         _wcp[sym]['sl_pct'], _wcp[sym]['tp_pct'])
            else:
                log.info('G-wincombo %s: override رد شد (بافر SL یا RR) — هندسهٔ ردیف', sym)
    except Exception:
        pass
    # گزینهٔ الف (G-volsize): vol-targeted sizing — cap-style
    _size = _eff_order_usdt(row, st)
    # G-market-entry (اپراتور 1405/08/01): در مسیر مارکت، قیمت ورود = قیمت
    # لحظه‌ای بازار و حجم کامل است؛ محاسبه پولبک/نردبان فقط در مسیر limit
    _is_market = (st.order_type == 'market' and st.entry_mode != 'limit_pullback')
    # G-mhalf: پایهٔ اول مارکت (نصف حجم) + پایهٔ دوم limit نیم‌درصد پایین‌تر — کلید LEG1_MARKET
    _leg1_market = (not _is_market) and bool(getattr(st, 'leg1_market', False))
    if _is_market:
        _price1, _price2 = price, None
        _size1 = round(_size, 2)
        _size2 = 0
    elif _leg1_market:
        _price1, _price2 = price, price * 0.995
        _size1 = round(_size * 0.5, 2)
        _size2 = round(_size - _size1, 2)
    else:
        # G-scale: Calculate 2 entry prices for scaling in
        _price1, _price2 = _calc_scaled_entries(sym, price, row, st)
        if _price1 is None:
            _pull = _eff_pullback_pct(row, st) / 100.0
            _price1 = price * (1 - _pull)
            _price2 = None
        # Split volume: 50% each
        _size1 = round(_size * 0.5, 2)
        _size2 = round(_size - _size1, 2) if _price2 else 0
    # Order 1 (Fib 0.618)
    vol = math.floor((_size1 / _price1) * 1e8) / 1e8
    if vol <= 0:
        return
    amount = round(_size1, 2)
    _entry_tag = ('ورود مارکت' if _is_market else 'Scale 1/2 (مارکت)' if _leg1_market else 'Scale 1/2 (Fib 0.618)')
    reason = f"رأی خرید {a['buys']}/{a['total']} تایم‌فریم | {_entry_tag}" + _band_tag(st, row)
    if dry:
        record_trade(ws_t, 'خرید', sym, tf, reason, fmt_price(_price1), vol, amount,
                     sl, tp, '—', ST_DRY, 'شبیه‌سازی Scale 1/2 — بدون ارسال به صرافی')
        led['dry_net_spent'] += amount
        p = led['positions'].setdefault(sym, {'volume': 0.0, 'sim_volume': 0.0, 'real_volume': 0.0, 'entry_price': None, 'sl': None, 'tp': None})
        p['volume'] += vol
        p['sim_volume'] = p.get('sim_volume', 0.0) + vol
        if _price2 and _size2 > 0:
            vol2 = math.floor((_size2 / _price2) * 1e8) / 1e8
            if vol2 > 0:
                amount2 = round(_size2, 2)
                reason2 = f"رأی خرید {a['buys']}/{a['total']} تایم‌فریم | Scale 2/2 (-0.5%)" + _band_tag(st, row)
                record_trade(ws_t, 'خرید', sym, tf, reason2, fmt_price(_price2), vol2, amount2,
                             sl, tp, '—', ST_DRY, 'شبیه‌سازی Scale 2/2 — بدون ارسال به صرافی')
                led['dry_net_spent'] += amount2
                p['volume'] += vol2
                p['sim_volume'] = p.get('sim_volume', 0.0) + vol2
        return
    # G-scale: Use pre-calculated scaled entry price (market mode: قیمت لحظه‌ای)
    _limit_price = _price1
    # G-mhalf: شفافیت — نوع هر پایه در لاگ
    log.info('ورود %s | پایهٔ ۱: %s | پایهٔ ۲: %s', sym,
             'مارکت' if (_is_market or _leg1_market) else 'limit',
             'limit -0.5%' if _price2 else '—')
    code, data = client.place_order('buy', sym, _limit_price, vol, _is_market or _leg1_market, client_order_id=coid)
    ok = code == 200 and isinstance(data, dict) and data.get('status') == 'ok'
    o = (data.get('order') or {}) if isinstance(data, dict) else {}
    oid = clean_oid(o.get('id') if isinstance(o, dict) else None or (data.get('id') if isinstance(data, dict) else ''))
    if ok:
        record_trade(ws_t, 'خرید', sym, tf, reason, fmt_price(_limit_price), vol, amount,
                     sl, tp, oid, ST_PLACED, str(data)[:80])
        p = led['positions'].setdefault(sym, {'volume': 0.0, 'sim_volume': 0.0, 'real_volume': 0.0, 'entry_price': None, 'sl': None, 'tp': None})
        p['volume'] += vol
        p['real_volume'] = p.get('real_volume', 0.0) + vol
        # G-scale: Place second order at deep pullback level
        # G-budget: بررسی موجودی واقعی USDT قبل از Scale 2/2
        if _price2 and _size2 > 0 and not _is_market:
            _usdt_avail = currency_available(client, 'usdt') or 0.0
            if _usdt_avail < _size2:
                log.info('G-budget: %s فقط Scale 1/2 ثبت شد (موجودی USDT=%.2f، لازم=%.2f)',
                         sym, _usdt_avail, _size2)
                _price2 = None  # Scale 2/2 را رد کن
        if _price2 and _size2 > 0 and not _is_market:
            vol2 = math.floor((_size2 / _price2) * 1e8) / 1e8
            if vol2 > 0:
                amount2 = round(_size2, 2)
                reason2 = f"رأی خرید {a['buys']}/{a['total']} تایم‌فریم | Scale 2/2 (-0.5%)" + _band_tag(st, row)
                # G-scale: تولید cid برای Scale 2/2 تا توسط cancel_stale_entries قابل لغو باشد
                # الگو باید ^nbx-{sym}-{epoch9+}$ باشد تا cancel_stale_entries آن را بشناسد
                coid2 = f"nbx-{sym.lower().replace('_', '')}-{int(time.time())}"
                code2, data2 = client.place_order('buy', sym, _price2, vol2, False, client_order_id=coid2)
                ok2 = code2 == 200 and isinstance(data2, dict) and data2.get('status') == 'ok'
                o2 = (data2.get('order') or {}) if isinstance(data2, dict) else {}
                oid2 = clean_oid(o2.get('id') if isinstance(o2, dict) else None or (data2.get('id') if isinstance(data2, dict) else ''))
                if ok2:
                    record_trade(ws_t, 'خرید', sym, tf, reason2, fmt_price(_price2), vol2, amount2,
                                 sl, tp, oid2, ST_PLACED, str(data2)[:80])
                    p2 = led['positions'].get(sym) or led['positions'].setdefault(sym, {'volume': 0.0, 'sim_volume': 0.0, 'real_volume': 0.0, 'entry_price': None, 'sl': None, 'tp': None})
                    p2['volume'] += vol2
                    p2['real_volume'] = p2.get('real_volume', 0.0) + vol2
                else:
                    log.error('ثبت سفارش دوم %s ناموفق: HTTP %s | %s', sym, code2, str(data2)[:150])
        if st.use_exchange_oco and st.order_type == 'market':
            # F5: کارمزد خرید از سکه دریافتی کسر می‌شود → حجم OCO باید به موجودی فعال کپ شود
            # F6: شناسه پایه‌ها از id/pairId/orderId + orders[] + fallback از open_orders؛
            #     SL/TP در سلول‌های ردیف درج می‌شود تا sync/تریلینگ آن را ببینند
            sl_o, tp_o = parse_price(sl), parse_price(tp)
            vol_o = vol
            avail_o = currency_available(client, sym)
            if avail_o is not None and avail_o > 1e-12:
                # G-oco: OCO با کل موجودی active نماد — سکه‌های سرگردان پوشش می‌یابند
                vol_o = avail_o
            if not (vol_o > 1e-12 and sl_o and tp_o):
                log.warning('OCO فوری %s رد شد: موجودی فعال=%s | SL=%s | TP=%s — تور ایمنی چرخه بعد جبران می‌کند',
                            sym, avail_o, sl_o, tp_o)
            else:
                # F7c (اپراتور 1405/08/01): کلمپ SL با قیمت لحظه‌ای — همان الگوی F7a برای مسیر مارکت
                try:
                    _px_f7c = _public_price(sym)
                except Exception:
                    _px_f7c = None
                if _px_f7c and _px_f7c > 0 and sl_o:
                    _sl_cap_f7c = _px_f7c * (1 - 0.004)
                    if sl_o > _sl_cap_f7c:
                        log.info('OCO فوری %s: SL %s → کلمپ %s (قیمت لحظه‌ای %s)',
                                 sym, fmt_price(sl_o), fmt_price(_sl_cap_f7c), fmt_price(_px_f7c))
                        sl_o = _sl_cap_f7c
                code2, data2 = client.place_oco_sell(sym, vol_o, tp_o, sl_o)
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
                if ok2 and not leg_ids:
                    try:
                        _co, _do = client.open_orders()
                        for _lg in (_do.get('orders') or []):
                            if (str(_lg.get('srcCurrency', '')).lower() == sym.lower()
                                    and str(_lg.get('type')) == 'sell'):
                                for _k in ('pairId', 'id'):
                                    if _lg.get(_k):
                                        leg_ids.append(clean_oid(_lg.get(_k)))
                    except Exception:
                        pass
                oid_oco = '|'.join(dict.fromkeys(leg_ids))
                if ok2:
                    record_trade(ws_t, 'فروش', sym, '', 'OCO حد سود/ضرر بومی صرافی',
                                 fmt_price(tp_o), vol_o, round(vol_o * tp_o, 2),
                                 fmt_price(sl_o), fmt_price(tp_o), oid_oco, ST_PLACED,
                                 'OCO: TP=' + fmt_price(tp_o) + ' | SL=' + fmt_price(sl_o))
                    led.setdefault('pending_sells', set()).add(sym)
                    if not oid_oco:
                        log.warning('OCO %s ثبت شد اما شناسه استخراج نشد — sync/تور ایمنی تکمیل می‌کند', sym)
                else:
                    log.error('ثبت OCO برای %s ناموفق (HTTP %s): %s — SL/TP توسط خود ربات',
                              sym, code2, str(data2)[:120])
    else:
        _is_ump = (isinstance(data, dict) and data.get('code') == 'UnexpectedMarketPrice')
        if _is_ump and st.pullback_pct > 0:
            # G-ump: قیمت سیگنال از بازار عقب مانده — retry با قیمت تازه
            _fresh = _public_price(sym)
            if _fresh and _fresh > 0:
                _dev = abs(_fresh - price) / price * 100.0
                if _dev < 2.0:
                    _limit = _fresh * (1 - _pull_pct / 100.0)
                    log.info('G-ump: retrying %s with fresh price %.6g (dev %.2f%%)',
                             sym, _fresh, _dev)
                    code, data = client.place_order('buy', sym, _limit, vol,
                                                    False, client_order_id=coid)
                    if code == 200 and isinstance(data, dict) and data.get('status') == 'ok':
                        record_trade(ws_t, 'خرید', sym, tf, reason + ' (UMP retry)',
                                     fmt_price(_fresh), vol, amount,
                                     sl, tp, clean_oid((data.get('order') or {}).get('id') or ''),
                                     ST_PLACED, str(data)[:80])
                        _p = led['positions'].setdefault(sym, {'volume': 0.0, 'sim_volume': 0.0,
                                                               'real_volume': 0.0,
                                                               'entry_price': None,
                                                               'sl': None, 'tp': None})
                        _p['volume'] += vol
                        _p['real_volume'] = _p.get('real_volume', 0.0) + vol
                        led['daily_count'] = led.get('daily_count', 0) + 1
                        return
                    else:
                        log.warning('G-ump retry also failed for %s: HTTP %s', sym, code)
                else:
                    log.info('G-ump: %s price moved %.1f%% (>2%%) — skipping (rally too fast)',
                             sym, _dev)
        log.error('ثبت سفارش واقعی خرید %s ناموفق: HTTP %s | %s', sym, code, str(data)[:150])
        record_trade(ws_t, 'خرید', sym, tf, reason, fmt_price(_limit_price), vol, amount,
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


def _fill_time_of(rr):
    """P2-1: زمان fill ردیف خرید از مهر «fill@» در ستون پیام؛ fallback: زمان ثبت.
    مبنای سن پوزیشن (timeout) و مدت معاملات بسته — نه زمان ثبت سفارش."""
    msg = str(rr[12]) if len(rr) > 12 else ''
    if 'fill@' in msg:
        return msg.split('fill@', 1)[1][:16]
    return rr[0]


def check_position_timeout(st, ws_t, client, dry, led, prices):
    """G-timeout: sell positions older than POSITION_TIMEOUT_H
    if unrealized P&L% is below POSITION_TIMEOUT_MIN_PCT."""
    if st.position_timeout_h <= 0:
        return
    import jdatetime as _jd
    import datetime as _dt
    now = (_dt.datetime.now(_dt.timezone.utc)
           + _dt.timedelta(hours=3, minutes=30)).replace(tzinfo=None)
    for sym in list(led['positions']):
        p = led['positions'].get(sym)
        if not p:
            continue
        rv = p.get('real_volume') or 0
        if rv <= 1e-12:
            continue
        # پیدا کردن زمان آخرین خرید
        entry_t = None
        for _, rr in reversed(led['rows']):
            if (rr[1].strip().upper() == sym and rr[2].strip() == 'خرید'
                    and rr[11].strip() in EXECUTED):
                entry_t = _fill_time_of(rr)
                break
        if not entry_t:
            continue
        try:
            t0 = _jd.datetime.strptime(str(entry_t).strip(), '%Y/%m/%d %H:%M')
        except (ValueError, TypeError):
            continue
        age_h = (now - t0.togregorian()).total_seconds() / 3600
        if age_h < st.position_timeout_h:
            continue
        px = prices.get(sym)
        if px is None:
            continue
        # F8a (اپراتور 1405/08/01): entry_price در read_ledger میانگین بی‌مرزِ همهٔ
        # خریدهای اجراشدهٔ دفتر است (ZEC: 1338.50 کاذب در برابر VWAP واقعی 1236.15
        # → P&L کاذب −8.4٪ → فروش اجباری G-timeout بر مبنای غلط). مبنای درست:
        # قیمت آخرین خرید همین نماد — هم‌راستا با Fix-C تریلینگ و Fix-B بسته‌شدن.
        entry = _last_buy_price(led, sym) or p.get('entry_price') or 0
        if entry <= 0:
            continue
        pnl_pct = (px / entry - 1) * 100
        if pnl_pct < st.position_timeout_min_pct:
            log.info('G-timeout: %s held %.1fh with P&L %+.1f%% (min %.1f%%) - selling',
                     sym, age_h, pnl_pct, st.position_timeout_min_pct)
            exit_position(st, ws_t, client, sym,
                          'انقضای مدت (%.0fh)' % st.position_timeout_h,
                          px, led)


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
        # G-fix: جلوگیری از فروش اضافی بعد از OCO
        # اگر موجودی فعال صفر یا بسیار کم است، یعنی OCO اجرا شده
        if client and not dry:
            _avail = currency_available(client, sym)
            _rv = led['positions'].get(sym, {}).get('real_volume', 0)
            if _avail is not None and _rv > 0 and _avail < _rv * 0.5:
                log.info('G-fix: خروج %s رد شد - OCO اجرا شده (فعال=%s از دفتر=%s) — جبران با reconcile',
                         sym, fmt_bal(_avail), fmt_bal(_rv))
                continue
        exit_position(st, ws_t, client, sym, why, price, led)


def sell_one(st, ws_t, client, dry, sym, reason, price, vol, led):
    """فروش حجم مشخص — dry=True فقط در دفتر ثبت می‌کند
    (خروج کامل پوزیشن از exit_position انجام می‌شود)"""
    if not vol or vol <= 1e-12:
        log.warning('فروش %s رد شد: حجم صفر است', sym)
        return
    amount = round(vol * price, 2)
    pos = led['positions'].get(sym) or {}
    # F8b: نمایش P&L بر مبنای آخرین خرید (entry_price کهنه — هم‌راستا با Fix-B)
    entry = _last_buy_price(led, sym) or pos.get('entry_price')
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
    code, data = client.place_order('sell', sym, price, vol, st.exit_order_type == 'market')
    ok = code == 200 and isinstance(data, dict) and data.get('status') == 'ok'
    # G-ump-sell: شکست قطعی UnexpectedMarketPrice = قیمت ارسالی از بازار فعلی عقب مانده؛
    # یک تلاش مجدد با قیمت تازه (آینهٔ G-ump خرید — برای خروج فوریت بالاست پس حد sanity
    # نسبت به خرید loosen است). مطابق X2: فقط روی پاسخ صریح failed، نه پاسخ گمشده.
    if (not ok and code == 200 and isinstance(data, dict)
            and data.get('status') == 'failed'
            and data.get('code') == 'UnexpectedMarketPrice'):
        _fresh = _public_price(sym)
        if _fresh and _fresh > 0 and price and abs(_fresh - price) / price < 0.20:
            log.info('G-ump-sell: retrying %s with fresh price %.6g (was %.6g)',
                     sym, _fresh, price)
            price = _fresh
            amount = round(vol * price, 2)
            if entry:
                pnl = round(vol * price - vol * entry, 2)
                pnl_msg = f' | P&L: {pnl:+.2f} USDT'
            code, data = client.place_order('sell', sym, price, vol,
                                            st.exit_order_type == 'market')
            ok = code == 200 and isinstance(data, dict) and data.get('status') == 'ok'
    o = (data.get('order') or {}) if isinstance(data, dict) else {}
    oid = clean_oid(o.get('id') if isinstance(o, dict) else None or (data.get('id') if isinstance(data, dict) else ''))
    if ok:
        record_trade(ws_t, 'فروش', sym, '', reason, fmt_price(price), vol, amount,
                     '—', '—', oid, ST_PLACED, str(data)[:80] + pnl_msg)
        return True
    else:
        log.error('ثبت سفارش واقعی فروش %s ناموفق: HTTP %s | %s', sym, code, str(data)[:150])
        record_trade(ws_t, 'فروش', sym, '', reason, fmt_price(price), vol, amount,
                     '—', '—', '', 'ناموفق', str(data)[:100])
        return False


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
            if avail is not None and avail < real_vol * 0.5:
                # Fix-4: فعال ≪ دفتر ولی کل سکه‌ها هنوز در کیف پول‌اند → زیر
                # سفارش باز صرافی بلوکه‌اند (پایه استاپِ تریگرشده در حال پرشدن).
                # فروش سمت ربات فقط به غبار غیرقابل‌فروش (AmountTooLow) می‌رسد؛
                # خروج روی صرافی انجام می‌شود و بستن دفتر با reconcile
                tot = currency_available(client, sym, use_active=False)
                if tot is not None and tot >= real_vol * 0.5:
                    log.info('خروج %s به سفارش باز صرافی واگذار شد (فعال=%s از دفتر=%s) — جبران با reconcile',
                             sym, fmt_bal(avail), fmt_bal(real_vol))
                    return
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


def _last_buy_price(led, sym):
    """قیمت آخرین خریدِ اجراشدهٔ نماد از دفتر — مبنای P&L رفت‌وبرگشت و
    آستانه فعال‌سازی تریلینگ (به‌جای میانگین وزنی کل تاریخچه)"""
    p_ = None
    for _, rr in led.get('rows') or []:
        if (rr[1].strip().upper() == sym and rr[2].strip() == 'خرید'
                and rr[11].strip() in EXECUTED):
            v = parse_price(rr[5])
            if v:
                p_ = v
    return p_


def _stamp_pnl(ws_t, row_num, msg, pnl, now_ref=None):
    """مهر P&L در پیام ردیف فروش — idempotent (یک‌بار)؛ کول‌داون ورود مجدد
    و P&L محقق گزارش از همین می‌خوانند"""
    if pnl is None or 'P&L:' in str(msg):
        return
    try:
        _t = now_ref or jnow()
        ws_t.update_cell(row_num, 13, (str(msg) + ' | P&L: %+.2f @' % pnl + _t)[:250])
    except Exception:
        pass


def _fills_for_orders(client, order_ids):
    """N7: real fills (vwap/amount/fee) per orderId from /market/trades/list.
    Recent window only; misses fall back gracefully at call sites."""
    ids = {str(o) for o in order_ids if o}
    if not ids or client is None:
        return {}
    try:
        code, data = client._sc.get('/market/trades/list')
    except Exception:
        return {}
    if code != 200 or not isinstance(data, dict):
        return {}
    by = {}
    for t in (data.get('trades') or []):
        oid = str(t.get('orderId') or '')
        if oid not in ids:
            continue
        try:
            px = float(t.get('price') or 0)
            amt = float(t.get('amount') or 0)
            fee = float(t.get('fee') or 0)
        except (TypeError, ValueError):
            continue
        if px <= 0 or amt <= 0:
            continue
        b = by.setdefault(oid, [0.0, 0.0, 0.0])
        b[0] += px * amt
        b[1] += amt
        b[2] += fee
    return {oid: {'vwap': b[0] / b[1], 'amount': b[1], 'fee': b[2]}
            for oid, b in by.items()}


def _exit_fill(client, oids):
    """N7: aggregate real exit fill across order ids (OCO legs)
    -> (vwap, amount, fee_usdt) or None"""
    fills = _fills_for_orders(client, oids)
    if not fills:
        return None
    px_amt = sum(f['vwap'] * f['amount'] for f in fills.values())
    amt = sum(f['amount'] for f in fills.values())
    fee = sum(f['fee'] for f in fills.values())
    return (px_amt / amt if amt > 0 else None, amt, fee)


def _entry_fill(client, led, sym):
    """N7: (vwap, fee_usdt_equiv) of executed buys in the CURRENT cycle.
    Cycle boundary = EXECUTED sell row in ledger (sells mark end of cycle).
    G-fix-cycle: فقط fillهای چرخه جاری برای VWAP استفاده شوند تا با fillهای
    چرخه قبلی مخلوط نشوند. باگ: 1M_PEPE چرخه B با VWAP چرخه A محاسبه می‌شد
    و P&L به جای +0.80% به صورت -1.34% ثبت شد.
    G-fix-closed-cycle: اگر پوزیشن بسته شده (cycle_oids خالی در پایان)،
    از آخرین چرخه بسته‌شده استفاده شود. بدون این، _entry_fill برای معامله
    بسته‌شده مقدار (None, 0.0) برمی‌گرداند."""
    cycle_oids = []
    last_px = None
    last_closed_oids = None
    last_closed_px = None
    for _, rr in (led.get('rows') or []):
        if rr[1].strip().upper() != sym:
            continue
        rtype = rr[2].strip()
        rstat = rr[11].strip() if len(rr) > 11 else ''
        # Executed sell marks end of cycle - save as last_closed before reset
        if rtype == 'فروش' and rstat in EXECUTED:
            if cycle_oids:
                last_closed_oids = list(cycle_oids)
                last_closed_px = last_px
            cycle_oids = []
            last_px = None
            continue
        if rtype == 'خرید' and rstat in EXECUTED:
            v = parse_price(rr[5])
            if v:
                last_px = v
            fo = clean_oid(str(rr[10]).split('|')[0])
            if fo and fo != '—':
                cycle_oids.append(fo)
    # اگر چرخه جاری خالی است (پوزیشن بسته‌شده)، از آخرین چرخه بسته‌شده استفاده کن
    if not cycle_oids and last_closed_oids is not None:
        cycle_oids = last_closed_oids
        last_px = last_closed_px
    if cycle_oids and client is not None:
        fills = _fills_for_orders(client, cycle_oids)
        if fills:
            total_cost = sum(f['vwap'] * f['amount'] for f in fills.values())
            total_amount = sum(f['amount'] for f in fills.values())
            total_fee_coin = sum(f['fee'] for f in fills.values())
            if total_amount > 0:
                vwap = total_cost / total_amount
                fee_usdt = total_fee_coin * vwap
                return vwap, fee_usdt
    return last_px, 0.0


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
        # Fix-C: مرجع فعال‌سازی = قیمت آخرین خرید همین نماد (نه میانگین تاریخچه) —
        # میانگینِ قدیمی تریلینگ را بلافاصله بعد از خرید فعال می‌کرد
        entry_ref = _last_buy_price(led, sym) or entry
        if price < entry_ref * (1 + st.trail_activation_pct / 100.0):
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

        # G-trail: ATR-based trailing distance (per-symbol volatility)
        if st.trail_atr_mult > 0:
            _c = fetch_candles(sym + 'USDT', '60', 100)
            _atr = None
            if _c and len(_c.get('c') or ()):
                _v = se_prepare_atr(_c)
                _atr = _v[-1] if _v and _v[-1] else None
            if _atr:
                # G-wincombo: ضریب تریلینگ per-symbol (نمادِ فاقد تب → ضریب جهانی)
                _tm_eff = st.trail_atr_mult
                try:
                    import win_combo
                    _wct = win_combo.get_params(ws_t, st)
                    _wcv = (_wct.get(sym) or {}).get('trail_mult')
                    if _wcv:
                        _tm_eff = _wcv
                except Exception:
                    pass
                new_sl = price - _tm_eff * _atr
            else:
                new_sl = price * (1 - st.trail_distance_pct / 100.0)
        else:
            new_sl = price * (1 - st.trail_distance_pct / 100.0)
        # G-pexit: partial exit on first activation
        # G-pexit-fix: cancel blocking OCO first, then sell, then re-place OCO
        if (st.partial_exit_pct > 0 and client is not None
                and (p.get('real_volume') or 0) > 1e-12
                and price >= entry_ref * (1 + st.partial_exit_trigger / 100.0)):
            _pe_state_file = 'state.json'
            # G-pexit-fix2: فلگ از دفتر خوانده می‌شود (نه state.json)
            # اگر ردیف «خروج جزئی» یا «OCO post-partial» برای این نماد هست → done
            # G-ump-sell: ردیف «ناموفق» فلگ را set نمی‌کند — شکست خروج جزئی باید
            # در چرخهٔ بعد تلاش مجدد شود؛ ردیف‌های «ثبت‌شده»/«پر شد» (سفارش کارکردی)
            # همچنان race-protection را حفظ می‌کنند
            _pe_done = any(
                (('خروج جزئی' in str(rr[4]) and str(rr[11]).strip() != 'ناموفق')
                 or 'OCO post-partial' in str(rr[12]))
                and str(rr[1]).strip().upper() == sym
                for _, rr in led['rows'])
            if not _pe_done:
                _pe_vol = p['real_volume'] * st.partial_exit_pct / 100.0
                _pe_active = currency_available(client, sym) or 0
                if _pe_active < _pe_vol:
                    # سکه‌ها بلوکه‌اند — OCO را لغو کن تا آزاد شوند
                    _cancelled = False
                    for _rn, _rr in led['rows']:
                        if (str(_rr[1]).strip().upper() == sym
                                and 'OCO' in str(_rr[4])
                                and str(_rr[11]).strip() in OPENISH):
                            _oids = [clean_oid(x) for x in str(_rr[10]).split('|')]
                            _oids = [x for x in _oids if x and x != '—']
                            for _oid in _oids:
                                _c, _d = client.cancel_order(_oid)
                                if _c in (200, 201):
                                    _cancelled = True
                            ws_t.update_cell(_rn, 12, ST_CANCELLED)
                            log.info('G-pexit-fix: cancelled OCO %s for partial exit', sym)
                            break
                    if _cancelled:
                        _pe_active = currency_available(client, sym) or 0
                _pe_vol = min(_pe_vol, _pe_active)
                if _pe_vol > 1e-12:
                    _ok_sell = sell_one(st, ws_t, client, False, sym,
                                        'خروج جزئی (+%.1f%%)' % st.partial_exit_trigger,
                                        price, _pe_vol, led)
                    if not _ok_sell:
                        # G-ump-sell: فروش جزئی ناموفق — حجم‌ها و OCO دست نمی‌خورند؛
                        # ردیف «ناموفق» فلگ را set نمی‌کند → تلاش مجدد چرخهٔ بعد؛
                        # تور ایمنی backfill سکه‌های آزادشده را پوشش می‌دهد
                        log.warning('G-pexit %s: فروش جزئی ناموفق — به چرخهٔ بعد موکول', sym)
                    else:
                        p['real_volume'] = max(0, p['real_volume'] - _pe_vol)
                        p['volume'] = max(0, p.get('volume', 0) - _pe_vol)
                        led['positions'][sym] = p
                        # OCO جدید با حجم باقیمانده
                        _pe_remaining = p['real_volume']
                        _pe_sl = p.get('sl')
                        _pe_tp = p.get('tp')
                        _pe_avail = currency_available(client, sym)
                        if _pe_avail is not None:
                            _pe_remaining = min(_pe_remaining, _pe_avail)
                        if _pe_remaining > 1e-12 and _pe_sl and _pe_tp:
                            # F8c (اپراتور 1405/08/01): کلمپ SL بازثبتِ پس از خروج جزئی — پنجمین سایت
                            # ثبت OCO که بی‌کلمپ ماند (خانوادهٔ PriceConditionFailed صبح)
                            try:
                                _px_f8 = _public_price(sym)
                            except Exception:
                                _px_f8 = None
                            if _px_f8 and _px_f8 > 0 and _pe_sl:
                                _sl_cap_f8 = _px_f8 * (1 - 0.004)
                                if _pe_sl > _sl_cap_f8:
                                    log.info('G-pexit %s: SL بازثبت %s → کلمپ %s (قیمت لحظه‌ای %s)',
                                             sym, fmt_price(_pe_sl), fmt_price(_sl_cap_f8), fmt_price(_px_f8))
                                    _pe_sl = _sl_cap_f8
                            _c2, _d2 = client.place_oco_sell(sym, _pe_remaining, _pe_tp, _pe_sl)
                            _ok2 = _c2 == 200 and isinstance(_d2, dict) and _d2.get('status') == 'ok'
                            if _ok2:
                                _o2 = (_d2.get('order') or {}) if isinstance(_d2, dict) else {}
                                _legs = []
                                if isinstance(_o2, dict):
                                    for _k2 in ('id', 'pairId', 'orderId'):
                                        if _o2.get(_k2):
                                            _legs.append(clean_oid(_o2.get(_k2)))
                                if isinstance(_d2, dict) and isinstance(_d2.get('orders'), list):
                                    for _lg2 in _d2['orders']:
                                        if isinstance(_lg2, dict):
                                            for _k2 in ('id', 'pairId', 'orderId'):
                                                if _lg2.get(_k2):
                                                    _legs.append(clean_oid(_lg2.get(_k2)))
                                record_trade(ws_t, 'فروش', sym, '', 'OCO حد سود/ضرر بومی صرافی',
                                             fmt_price(_pe_tp), _pe_remaining,
                                             round(_pe_remaining * _pe_tp, 2),
                                             fmt_price(_pe_sl), fmt_price(_pe_tp),
                                             '|'.join(dict.fromkeys(_legs)), ST_PLACED,
                                             'OCO post-partial: TP=' + fmt_price(_pe_tp) + ' | SL=' + fmt_price(_pe_sl))
                                led.setdefault('pending_sells', set()).add(sym)
                                log.info('G-pexit-fix: OCO re-placed for %s | vol=%.6f | SL=%s',
                                         sym, _pe_remaining, fmt_price(_pe_sl))
                            else:
                                log.error('G-pexit %s: بازثبت OCO ناموفق (HTTP %s) — تور ایمنی چرخهٔ بعد جبران می‌کند',
                                          sym, _c2)
                        log.info('G-pexit: sold %.1f%% of %s at +%.1f%% (state persisted)',
                                 st.partial_exit_pct, sym, st.partial_exit_trigger)
                else:
                    log.warning('G-pexit %s: no sellable volume after OCO cancel', sym)

        if new_sl <= sl:
            continue

        if has_oco and oco_sl is not None and new_sl <= oco_sl * 1.005:
            p['sl'] = oco_sl
            set_sheet_sl(oco_sl)
            continue
        if has_oco:
            if client is None or (p.get('real_volume') or 0) <= 1e-12:
                continue
            # F5 (اپراتور 1405/08/01): قیمت تازه + کلمپ SL — ریشهٔ PriceConditionFailed (حادثهٔ 13:37 ZEC)
            _px_f5 = None
            try:
                _px_f5 = _public_price(sym)
            except Exception:
                _px_f5 = None
            _tp_f5 = p.get("tp")
            if _px_f5 and _tp_f5 and _px_f5 >= _tp_f5 * (1 - 0.004):
                # قیمت چسبیده به TP یا بالاتر — بازسازی ریسکی/بیهوده است؛ پایهٔ TP خودش پر می‌شود
                continue
            if _px_f5 and _px_f5 > 0:
                _sl_cap_f5 = _px_f5 * (1 - 0.004)
                if new_sl > _sl_cap_f5:
                    log.info('OCO متحرک %s: SL جدید %s بالاتر از کلمپ %s (قیمت لحظه‌ای %s) — کلمپ شد',
                             sym, fmt_price(new_sl), fmt_price(_sl_cap_f5), fmt_price(_px_f5))
                    new_sl = _sl_cap_f5
            if new_sl <= sl:
                # کلمپ SL را به زیر حد فعلی برگرداند — بهبودی نیست
                continue
            if oco_sl is not None and new_sl <= oco_sl * 1.005:
                # بعد از کلمپ بهبودی نسبت به SL صرافی نماند — OCO فعلی سالم است؛ لغو/بازسازی نکن
                p["sl"] = oco_sl
                set_sheet_sl(oco_sl)
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
            if oco_row[0]:
                ws_t.update_cell(oco_row[0], 12, ST_CANCELLED)
            # G-blocked: اگر استاپ صرافی در حال پر شدن است → این چرخه رد شو
            _av = currency_available(client, sym)
            _tot = currency_available(client, sym, use_active=False)
            _rv = p.get('real_volume') or 0
            if (_av is not None and _tot is not None
                    and _rv > 1e-12 and _av < _rv * 0.5 and _tot >= _rv * 0.5):
                log.info('G-blocked: OCO rebuild deferred for %s (exchange stop filling: active=%.6f total=%.6f)',
                         sym, _av, _tot)
                continue
            vol_o = p['real_volume']
            avail = currency_available(client, sym)
            if avail is not None and avail > 1e-12:
                # G-oco: کل موجودی active — پوشش سکه‌های سرگردان
                vol_o = avail
            tp_o = p.get('tp')
            if not (vol_o > 1e-12 and tp_o):
                led['pending_sells'].discard(sym)
                log.error('OCO متحرک %s: حجم/TP نامعتبر — حفاظت با خود ربات', sym)
                continue
            try:
                code2, data2 = client.place_oco_sell(sym, vol_o, tp_o, new_sl)
            except Exception as _exc_f5:
                code2, data2 = None, {'exception': str(_exc_f5)}
            ok2 = code2 == 200 and isinstance(data2, dict) and data2.get('status') == 'ok'
            if not ok2:
                # F5 (اپراتور 1405/08/01): بازگشت فوری با SL/TP قبلی — پنجرهٔ بی‌حفاظتی
                # از ~۳.۵ دقیقه (انتظار برای تور ایمنی تیک بعد) به ثانیه کاهش می‌یابد
                _sl_fb_f5 = oco_sl or sl
                try:
                    code2, data2 = client.place_oco_sell(sym, vol_o, tp_o, _sl_fb_f5)
                except Exception:
                    code2, data2 = None, None
                ok2 = code2 == 200 and isinstance(data2, dict) and data2.get('status') == 'ok'
                if ok2:
                    new_sl = _sl_fb_f5
                    log.warning('OCO متحرک %s: SL جدید رد شد — بازگشت فوری با SL قبلی %s',
                                sym, fmt_price(_sl_fb_f5))
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
            if not leg_ids:
                try:
                    _co, _do = client.open_orders()
                    for _lg in (_do.get('orders') or []):
                        if (str(_lg.get('srcCurrency', '')).lower() == sym.lower()
                                and str(_lg.get('type')) == 'sell'):
                            for _k in ('pairId', 'id'):
                                if _lg.get(_k):
                                    leg_ids.append(clean_oid(_lg.get(_k)))
                except Exception:
                    pass
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


def _buy_reason(sym_rows):
    # بهبود (G-reason): علت دقیق رأی خرید — TFهای خریدخور با قوتشان + یادداشت
    # اندیکاتوری بهترین TF (note = دلایل رأی‌های غیرخنثی همان TF)
    buys = [(str(x[1]).strip(), str(x[5]).strip(),
             str(x[11]).strip() if len(x) > 11 else '')
            for x in sym_rows if str(x[4]).strip() == 'خرید']
    if not buys:
        return '—'

    def _num(s):
        try:
            return int(float(s))
        except (TypeError, ValueError):
            return 0
    tf_list = ' + '.join(f'{tf}({st_}٪)' for tf, st_, _ in buys)
    best_note = max(buys, key=lambda b: _num(b[1]))[2]
    return (f'{len(buys)}/{len(sym_rows)} TF: {tf_list} | '
            + (best_note[:110] if best_note else 'بدون یادداشت'))


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
        sym_rows = [x for x in rows if len(x) > 4 and str(x[0]).strip().upper() == sym
                    and str(x[4]).strip() in ('خرید', 'فروش', 'خنثی')]
        n_buys = sum(1 for x in sym_rows if str(x[4]).strip() == 'خرید')
        n_sells = sum(1 for x in sym_rows if str(x[4]).strip() == 'فروش')
        if sym in led.get('positions', {}):
            status = 'پوزیشن باز'
        elif sym in led.get('pending', set()):
            status = 'سفارش باز'
        elif (n_buys >= st.min_tfs and n_buys >= (len(sym_rows) + 1) // 2
                and n_buys > n_sells):
            status = 'کاندید خرید'  # معیار واقعی — همان st.min_tfs که سفارش با آن ثبت می‌شود
        else:
            status = '—'
        reason = _buy_reason(sym_rows) if status == 'کاندید خرید' else '—'
        tf_agg = f'خرید {n_buys}/{len(sym_rows)} · فروش {n_sells}/{len(sym_rows)}'
        bp = bt_params.get(sym) or {}
        strat = (f"آستانه {bp['thr']}٪ | SL {bp['slm']}xATR | TP {bp['tpm']}xATR"
                 if bp else 'پیش‌فرض شیت تنظیمات')
        data.append([rank, sym, r[4], r[5], r[6], r[7], r[8],
                     r[2], r[2], r[10], r[9], rr, strat, status, reason, tf_agg])
    n = max(20, len(data) + 4)
    data = data + [[''] * 16] * (n - len(data))
    ws.update(values=[['رتبه‌بندی لحظه‌ای برای سفارشگزاری — بازه: INTERVAL_SIGNALS_MIN در تب تنظیمات',
                       'به‌روزرسانی:', jnow()]], range_name='A1:C1')
    ws.update(values=[['علت رأی خرید (TFهای رأی‌داده + دلایل اندیکاتوری)']], range_name='O3')
    ws.update(values=[['رأی TFها (خرید/فروش)']], range_name='P3')
    ws.update(values=data, range_name=f'A4:P{3 + n}')


def cancel_stale_entries(st, ws_t, client, led):
    """لغو سفارش‌های ورود (خرید) کهنه — TTL از شیت. فروش‌ها هرگز لمس نمی‌شوند.
    X1: فیلدهای واقعی open_orders در apiv2: type/pairId/matchedAmount/clientOrderId/
    srcCurrency — فیلدهای side/executedPercent/created_at/symbol/id در پاسخ نیستند
    (نسخه قبلی هرگز match نمی‌شد — با تست ساختگی اثبات شد: صفر فراخوانی لغو).
    پاسخ فهرست timestamp ندارد → سن سفارش از epoch داخل clientOrderId خود ربات
    (nbx-{sym}-{epoch}). فقط سفارش‌های خود ربات لغو می‌شوند؛ سفارش دستی کاربر،
    فروش‌ها و بخشی‌پرها هرگز لمس نمی‌شوند."""
    if not client or st.entry_ttl_min <= 0:
        return
    try:
        code, data = client.open_orders()
        live = data.get('orders') or []
    except Exception:
        return
    import re as _re
    for o in live:
        if str(o.get('type', '')).lower() != 'buy':
            continue
        try:
            matched = float(str(o.get('matchedAmount') or 0).replace(',', ''))
        except (TypeError, ValueError):
            matched = 0.0
        cid = str(o.get('clientOrderId') or '')
        m = _re.match(r'^nbx-([a-z0-9]+)-(\d{9,})$', cid)
        if not m:                  # سفارش خود ربات نیست (دستی/نامشخص) — دست نزن
            continue
        sym, epoch = m.group(1).upper(), int(m.group(2))
        age_min = (time.time() - epoch) / 60.0
        if age_min < st.entry_ttl_min:
            continue
        if matched > 0:
            # G-partial (P2a): نیمه‌پرِ کهنه دیگر بی‌صدا رد نمی‌شود (شبح 1472:
            # fill جزئی پیش از 05:02، بی‌حفاظ تا پرشد کامل در کرش 05:34) —
            # باقیمانده لغو می‌شود تا بخشِ پرشده همان تیک محافظت‌شدنی شود.
            log.info('TTL %s: سفارش نیمه‌پر کهنه (سن %.0f دقیقه، پرشده=%s) — لغو باقیمانده',
                     sym, age_min, matched)
        # G-cancel: apiv2 برای سفارش‌های دارای clientOrderId فیلد pairId در
        # orders/list نمی‌فرستد → شناسه عددی از ردیف خرید باز همان نماد در دفتر
        # (ثبت‌شده هنگام ثبت سفارش از پاسخ orders/add).
        # G-fix: وقتی چندین سفارش باز برای یک نماد وجود دارد (Scale 1/2 + Scale 2/2)،
        # باید oid را بر اساس cid مرتبط پیدا کنیم، نه آخرین ردیف.
        oid = clean_oid(o.get('pairId'))
        if not oid:
            for _rn, _rr in led.get('rows') or []:
                if (len(_rr) > 11 and _norm_sym(_rr[1]) == _norm_sym(sym)
                        and str(_rr[2]).strip() == 'خرید'
                        and str(_rr[11]).strip() in OPENISH):
                    _c = clean_oid(_rr[10])
                    if _c and _c.isdigit():
                        # استعلام وضعیت این oid - آیا cid آن با سفارش فعلی مطابقت دارد؟
                        try:
                            _cs, _ds = client.order_status(_c)
                            _ord_c = _ds.get('order', _ds) if isinstance(_ds, dict) else {}
                            _cid_c = str(_ord_c.get('clientOrderId') or '')
                            if _cid_c == cid:
                                oid = _c  # ← oid درست پیدا شد
                                break
                        except Exception:
                            continue
        if not oid:
            log.warning('لغو سفارش کهنه %s ناموفق: شناسه عددی سفارش یافت نشد '
                        '(pairId غایب و ردیف دفتر بدون oid با cid منطبق)', sym)
            continue
        # تأیید هویت: شناسه دفتر باید به همین سفارش (cid) تعلق داشته و فعال باشد
        try:
            _cs, _ds = client.order_status(oid)
            _ord = _ds.get('order') if isinstance(_ds, dict) else None
            _ord = _ord if isinstance(_ord, dict) else {}
            if str(_ord.get('clientOrderId') or '') != cid:
                log.warning('لغو سفارش کهنه %s ناموفق: شناسه دفتر %s با سفارش زنده '
                            'هم‌خوان نیست — رد شد', sym, oid)
                continue
            if str(_ord.get('status')) != 'Active':
                log.info('سفارش کهنه %s فعال نیست (%s) — به همگام‌سازی واگذار شد',
                         sym, _ord.get('status'))
                continue
        except Exception:
            log.warning('لغو سفارش کهنه %s: استعلام وضعیت ناموفق — این چرخه رد شد', sym)
            continue
        code_c, data_c = client.cancel_order(oid)
        ok = (code_c in (200, 201)
              and not (isinstance(data_c, dict) and data_c.get('status') == 'failed'))
        if ok:
            _c_row = None
            for row_num, rr in led['rows']:
                if oid in str(rr[10]).replace(',', ''):
                    _c_row = row_num
                    if matched <= 0:
                        ws_t.update_cell(row_num, 12, ST_CANCELLED)
                    break
            if matched > 0:
                # G-partial (P1b): ردیف نیمه‌پر را «لغو شده» نکن — بخشِ پرشده باید
                # از مسیر همگام‌سازی (Canceled+matched -> «پر شد» + گذار fill + OCO)
                # پوزیشنِ محافظت‌شده شود؛ علامت‌گذاری اینجا مسیر گذار را می‌بُرد.
                log.info('TTL %s: باقیماندهٔ سفارش نیمه‌پر لغو شد (پرشده=%s) — '
                         'ثبت بخشِ پرشده به همگام‌سازی واگذار شد', sym, matched)
            else:
                # G-pending (P1a): pending نماد-محور است؛ لغوی یکی از چند سفارشِ بازِ
                # نماد نباید نماد را از pending بردارد (شبح 05:02: لغوی یک پله
                # دروازهٔ خرید را همان تیک باز کرد -> سه نسل نردبان در کرش 05:34).
                _still = any(_rn != _c_row
                             and str(_rr[2]).strip() == 'خرید'
                             and _norm_sym(_rr[1]) == _norm_sym(sym)
                             and str(_rr[11]).strip() in OPENISH
                             for _rn, _rr in (led.get('rows') or []))
                if not _still:
                    led['pending'].discard(sym)
                    for _ps in list(led.get('pending') or ()):
                        if _norm_sym(_ps) == _norm_sym(sym):
                            led['pending'].discard(_ps)
                log.info('سفارش ورود کهنه لغو شد: %s (سن %.0f دقیقه)%s', sym, age_min,
                         ' — نماد در pending ماند (سفارش باز دیگر)' if _still else '')
        elif isinstance(data_c, dict) and str(data_c.get('error')) == 'NotFound':
            # سفارش در فاصله fetch→cancel از لیست خارج شده (fill/لغو بیرونی) —
            # وضعیت واقعی را همگام‌سازی چرخه بعد تعیین می‌کند؛ دفتر دست نمی‌خورد
            log.info('سفارش کهنه %s پیش از لغو از لیست خارج شد — به همگام‌سازی واگذار شد', sym)
        else:
            log.warning('لغو سفارش کهنه %s ناموفق: %s', sym, str(data_c)[:120])




def _norm_sym(s):
    """F11a: نرمال‌سازی نماد برای مقایسه — حذف نویسه‌های غیر الفبایی‌عددی.
    شاهد: cid سفارش 'nbx-1mpepe-…' (بدون زیرخط) در برابر نماد دفتر '1M_PEPE'
    → جستجوی oid در لغو TTL هرگز منطبق نمی‌شد و هر تیک WARNING می‌زد."""
    import re as _re_n
    return _re_n.sub(r'[^A-Z0-9]', '', str(s).upper())
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
        marked_row = None
        for row_num, rr in led['rows']:
            if (rr[1].strip().upper() == sym and rr[2].strip() == 'فروش'
                    and rr[11].strip() in OPENISH):
                ws_t.update_cell(row_num, 12, ST_FILLED)
                ws_t.update_cell(row_num, 7, sold)
                ws_t.update_cell(row_num, 6, fmt_price(price))
                marked_row = (row_num, rr)
                break
        # Fix-B: مهر P&L رفت‌وبرگشت (مبنای آخرین خرید) — کول‌داون ورود مجدد
        # و P&L محقق گزارش از پیام ردیف‌های فروش می‌خوانند
        # N7: real exit fill from the marked row's order ids (OCO legs)
        _sell_fee_n7 = 0.0
        if marked_row is not None:
            _oids = [clean_oid(x) for x in str(marked_row[1][10]).split('|')]
            _oids = [x for x in _oids if x and x != '—']
            _xf = _exit_fill(client, _oids)
            if _xf and _xf[0]:
                price = _xf[0]
                if _xf[1]:
                    sold = _xf[1]
                ws_t.update_cell(marked_row[0], 6, fmt_price(price))
                ws_t.update_cell(marked_row[0], 7, sold)
                _sell_fee_n7 = _xf[2]
        _entry_n7, _buy_fee_n7 = _entry_fill(client, led, sym)
        # G-fix: جمع‌آوری oids فروش برای دریافت قیمت واقعی خروج
        _reconcile_oids = []
        for _, _rr in reversed(led.get('rows') or []):
            if (str(_rr[1]).strip().upper() == sym
                    and str(_rr[2]).strip() == 'فروش'
                    and str(_rr[11]).strip() in OPENISH):
                for _x in str(_rr[10]).split('|'):
                    _c = clean_oid(_x)
                    if _c and _c.isdigit():
                        _reconcile_oids.append(_c)
        entry_b = _entry_n7 or p.get('entry_price') or price
        pnl_b = (sold * (price - entry_b) - _sell_fee_n7 - _buy_fee_n7) if (price and entry_b) else None
        if marked_row is not None:
            _stamp_pnl(ws_t, marked_row[0], marked_row[1][12], pnl_b, now_ref=jnow())
        if marked_row is None:
            # N5: هیچ ردیف فروش بازی نبود (خروج از مسیر OCO بی‌شناسه / فروش دستی).
            # بدون ردیف پایانی، دفتر در تیک بعد همان پوزیشن را بازسازی و دوباره
            # می‌بندد — حلقه فانتوم (PUMP: ۱۷۶ ردیف «بسته شد» کاذب در یک روز).
            ws_t.append_row([jnow(), sym, 'فروش', '', 'خروج از کیف پول (جبران دفتر)',
                             fmt_price(price), sold, round(sold * price, 2),
                             '', '', '', ST_FILLED,
                             'ردیف جبران — بستن پوزیشن تخلیه‌شده از کیف پول' + ('' if pnl_b is None else ' | P&L: %+.2f' % pnl_b)])
            log.info('ردیف جبران دفتر درج شد: فروش %s | %s @ %s',
                     sym, sold, fmt_price(price))
        e_time = next((rr[0] for _, rr in reversed(led['rows'])
                       if rr[1].strip().upper() == sym and rr[2].strip() == 'خرید'
                       and rr[11].strip() in EXECUTED), '—')
        # G-fix: استفاده از قیمت واقعی فروش (exit VWAP) به‌جای قیمت لحظه‌ای
        _xf_re = _exit_fill(client, _reconcile_oids) if _reconcile_oids else None
        _real_exit = ((_xf_re[0] if _xf_re and _xf_re[0] else None) or price)
        _real_sell_fee = (_xf_re[2] if _xf_re else _sell_fee_n7)
        record_closed(ws_t, sym, e_time, _entry_n7 or p.get('entry_price') or price, _real_exit,
                      sold, 'خروج از کیف پول (OCO یا فروش دستی)', 'واقعی', fee_usdt=_real_sell_fee + _buy_fee_n7)
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
            _record_analysis(ws_t, sym, _entry_an, _real_exit, _vol_an,
                            _vol_an * (_real_exit - _entry_an) - _real_sell_fee - _buy_fee_n7,
                            (_real_exit / _entry_an - 1) * 100 if _entry_an else 0.0,
                            _dur_an,
                            'خروج از کیف پول (OCO یا فروش دستی)',
                            led, client, st)
        except Exception:
            log.exception('خطا در ثبت تحلیل معامله %s (reconcile)', sym)
        led['positions'].pop(sym, None)
        led['pending_sells'].discard(sym)
        led['pending'].discard(sym)

    # ── G-oco: شناسایی سکه‌های سرگردان (active > غبار بدون پوزیشن دفتری) ──
    try:
        code_w, data_w = client.wallets()
        for w in (data_w.get('wallets') or []):
            _cur = str(w.get('currency') or '').strip().upper()
            if _cur in ('USDT', 'RLS', ''):
                continue
            try:
                _bal = float(w.get('activeBalance') or w.get('balance') or 0)
            except (TypeError, ValueError):
                _bal = 0
            _px = prices.get(_cur) or _public_price(_cur)
            if _bal > 1e-12 and _px and (_bal * _px) >= st.dust_usdt:
                if _cur not in led['positions'] and _cur not in led.get('pending_sells', set()):
                    log.warning('G-oco stray: %s has %.8f (%.2f USDT) active, no ledger position',
                                _cur, _bal, _bal * _px)
    except Exception:
        pass


def _exit_time_of(rr):
    """G-cool-fix: زمان واقعی خروج از ردیف فروش — مهر « @%Y/%m/%d %H:%M» در rr[12]
    (زمان پرشدن OCO/فروش). fallback به rr[0] (ردیف‌های جبران که rr[0]=زمان خروج است،
    یا مهر @ خراب/غیرتاریخ). هیچ‌کدام → None."""
    try:
        import jdatetime as _jd
        msg = str(rr[12]) if len(rr) > 12 else ''
        if ' @' in msg:
            try:
                return _jd.datetime.strptime(
                    msg.split(' @')[-1].strip(), '%Y/%m/%d %H:%M').togregorian()
            except ValueError:
                pass
        return _jd.datetime.strptime(
            str(rr[0]).strip(), '%Y/%m/%d %H:%M').togregorian()
    except Exception:
        return None


def recent_losing_exit(led, sym, minutes):
    """آیا این نماد در N دقیقه اخیر خروج زیان‌ده داشته؟ (کول‌داون ورود مجدد)
    معیار: ردیف فروش «پر شد» با P&L منفی در پیام، یا دلیل «حد ضرر»"""
    if minutes <= 0:
        return False
    import re as _re
    try:
        import jdatetime as _jd
        import datetime as _dt
        now = _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(hours=3, minutes=30)
        now = now.replace(tzinfo=None)
        for _, rr in led['rows']:
            if (rr[1].strip().upper() == sym and rr[2].strip() == 'فروش'
                    and rr[11].strip() in EXECUTED):
                reason = str(rr[4])
                msg = str(rr[12])
                m = _re.search(r'P&L:\s*([+-]?\d+(?:\.\d+)?)', msg)
                pnl = float(m.group(1)) if m else None
                is_loss = (pnl is not None and pnl < 0) or ('حد ضرر' in reason)
                if not is_loss:
                    continue
                # G-cool-fix: شمارش از لحظهٔ خروج واقعی (مهر @ در rr[12])، نه ثبت سفارش فروش
                g = _exit_time_of(rr)
                if g is not None and (now - g).total_seconds() < minutes * 60:
                    return True
    except Exception:
        log.warning('recent_losing_exit(%s): خطای ساختاری — کول‌داون fail-open', sym, exc_info=True)
    return False


def losing_exits_count(led, sym, minutes, now_ref=None):
    """G3.2 anti-knife: count losing exits of sym within last N minutes
    (P&L stamp from Fix-B, or stop-loss reason). A symbol that keeps losing
    (ZEC pattern 1405/07/14: four entries while price fell 1450->1310)
    must not be re-bought."""
    if minutes <= 0:
        return 0
    try:
        import jdatetime as _jd
        import datetime as _dt
        now = now_ref or (_dt.datetime.now(_dt.timezone.utc)
                          + _dt.timedelta(hours=3, minutes=30)).replace(tzinfo=None)
        n = 0
        for _, rr in led['rows']:
            if (rr[1].strip().upper() == sym and rr[2].strip() == 'فروش'
                    and rr[11].strip() in EXECUTED):
                msg = str(rr[12])
                pnl = None
                if 'P&L:' in msg:
                    try:
                        pnl = float(msg.split('P&L:')[1].strip().split()[0])
                    except (ValueError, IndexError):
                        pnl = None
                if not ((pnl is not None and pnl < 0) or 'حد ضرر' in str(rr[4])):
                    continue
                # G-cool-fix: هم‌راستا با recent_losing_exit — helper مشترک + fallback امن برای @ خراب
                g = _exit_time_of(rr)
                if g is not None and (now - g).total_seconds() < minutes * 60:
                    n += 1
        return n
    except Exception:
        log.warning('losing_exits_count(%s): خطای ساختاری — fail-open به 0', sym, exc_info=True)
        return 0


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


# G-oco-health: نمادهای کوتاه ربات به نام‌های کامل صرافی نوبیتکس
# اگر نماد در open_orders با نام کامل (Cardano) بیاید اما ربات نام کوتاه (ADA) را داشته باشد
SYMBOL_ALIASES = {
    'ADA': 'Cardano',
    'S': 'Sonic',
    'NEAR': 'NEARProtocol',
    'DOGE': 'Dogecoin',
    'XRP': 'Ripple',
    'SOL': 'Solana',
    'BTC': 'Bitcoin',
    'ETH': 'Ethereum',
    'WLD': 'Worldcoin',
    'ZEC': 'Zcash',
    'XAUT': 'TetherGold',
    'PEPE': 'Pepe',
    '1MPEPE': '1MPEPE',
    'SHIB': 'ShibaInu',
    'TRX': 'Tron',
    'LTC': 'Litecoin',
    'BNB': 'BNB',
    'AVAX': 'Avalanche',
    'MATIC': 'MaticNetwork',
    'DOT': 'Polkadot',
    'LINK': 'ChainLink',
    'UNI': 'Uniswap',
    'ATOM': 'Cosmos',
    'FTM': 'Fantom',
    'ALGO': 'Algorand',
    'MANA': 'Decentraland',
    'SAND': 'TheSandbox',
    'AXS': 'AxieInfinity',
    'CHZ': 'Chiliz',
    'GALA': 'Gala',
    'CVX': 'ConvexFinance',
    'AAVE': 'Aave',
    'MKR': 'Maker',
    'COMP': 'Compound',
    'SUSHI': 'SushiSwap',
    'CRV': 'CurveDao',
    '1INCH': 'OneInch',
    'BAT': 'BasicAttentionToken',
    'ZIL': 'Zilliqa',
    'KNC': 'KyberNetwork',
    'BUSD': 'BinanceUSD',
    'USDC': 'USDCCoin',
    'TUSD': 'TrueUSD',
    'DAI': 'Dai',
    'PAXG': 'PaxosGold',
    'OCEAN': 'OceanProtocol',
    'FET': 'FetchAI',
    'GRT': 'TheGraph',
    'MEW': 'cat in a dogs world',
    'DOOD': 'DOOD',
    'MASK': 'MASK',
    '1M_PEPE': '1M_PEPE',
    'ENS': 'EthereumNameService',
    'AAVE': 'Aave',
    'MKR': 'Maker',
    'COMP': 'Compound',
    'SUSHI': 'SushiSwap',
    'CRV': 'CurveDao',
    '1INCH': 'OneInch',
    'BAT': 'BasicAttentionToken',
    'ZIL': 'Zilliqa',
    'KNC': 'KyberNetwork',
    'BUSD': 'BinanceUSD',
    'USDC': 'USDCCoin',
    'TUSD': 'TrueUSD',
    'DAI': 'Dai',
    'PAXG': 'PaxosGold',
    'OCEAN': 'OceanProtocol',
    'FET': 'FetchAI',
    'GRT': 'TheGraph',
    'MEW': 'cat in a dogs world',
    'DOOD': 'DOOD',
    'MASK': 'MASK',
    '1M_PEPE': '1M_PEPE',
    '1ART': 'OneArt',
    'AVAX': 'Avalanche',
}


def _match_sym_orders(ex_orders, sym, sym_vol):
    """G-oco-health: Match exchange sell orders by name (in-check) or amount.
    Handles Nobitex full names (Cardano, Sonic, NEARProtocol) via SYMBOL_ALIASES."""
    sym_lower = sym.lower()
    # پیدا کردن نام کامل صرافی از aliases
    alias_full = SYMBOL_ALIASES.get(sym.upper(), sym).lower()
    matched = []
    for o in ex_orders:
        if str(o.get('type')) != 'sell':
            continue
        src = str(o.get('srcCurrency', '')).lower()
        # Match by name: short or full alias
        if (sym_lower in src or src in sym_lower
                or alias_full in src or src in alias_full
                or alias_full == src):
            matched.append(o)
            continue
        # Fallback: match by amount (within 3% tolerance - covers exchange fees)
        try:
            amt = float(o.get('amount', 0) or 0)
            if sym_vol > 0 and abs(amt - sym_vol) / sym_vol < 0.03:
                matched.append(o)
        except (TypeError, ValueError):
            pass
    return matched


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
        if avail is not None and avail < rv * 0.5:
            # خروج روی صرافی در جریان است (پایه OCO اجرا شده / فروش دستی) —
            # دفتر در تیک‌های بعدی توسط reconcile بسته می‌شود؛ ثبت OCO برای
            # باقیماندهٔ غبار فقط خطای AmountTooLow می‌سازد
            log.info('OCO تور ایمنی %s رد شد: کیف پول در حال تخلیه (فعال=%s از %s) — جبران با reconcile',
                     sym, fmt_bal(avail), fmt_bal(rv))
            continue
        if avail is not None and avail > 1e-12:
            # G-oco: کل موجودی active — پوشش سکه‌های سرگردان
            vol_o = avail
        if vol_o <= 1e-12:
            log.warning('OCO تور ایمنی %s: موجودی فعال صرافی صفر است', sym)
            continue
        # F7b (اپراتور 1405/08/01): کلمپ SL — قیمت داخل باند ولی چسبیده به SL؛
        # ریشهٔ PriceConditionFailed تور ایمنی (MEW 08:54 و 1M_PEPE 10:16)
        _sl_cap_f7b = price * (1 - 0.004)
        if sl > _sl_cap_f7b:
            log.info('OCO تور ایمنی %s: SL %s → کلمپ %s (قیمت لحظه‌ای %s)',
                     sym, fmt_price(sl), fmt_price(_sl_cap_f7b), fmt_price(price))
            sl = _sl_cap_f7b
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
        if not leg_ids:
            try:
                _co, _do = client.open_orders()
                for _lg in (_do.get('orders') or []):
                    if (str(_lg.get('srcCurrency', '')).lower() == sym.lower()
                            and str(_lg.get('type')) == 'sell'):
                        for _k in ('pairId', 'id'):
                            if _lg.get(_k):
                                leg_ids.append(clean_oid(_lg.get(_k)))
            except Exception:
                pass
        record_trade(ws_t, 'فروش', sym, '', 'OCO تور ایمنی (جبران)',
                     fmt_price(tp), vol_o, round(vol_o * tp, 2),
                     fmt_price(sl), fmt_price(tp),
                     '|'.join(dict.fromkeys(leg_ids)), ST_PLACED,
                     'SL=' + fmt_price(sl) + ' | TP=' + fmt_price(tp))
        led.setdefault('pending_sells', set()).add(sym)
        try:
            led['rows'].append((len(ws_t.col_values(1)),
                                [jnow(), sym, 'فروش', '', 'OCO تور ایمنی (جبران)',
                                 fmt_price(tp), vol_o, round(vol_o * tp, 2),
                                 fmt_price(sl), fmt_price(tp),
                                 '|'.join(dict.fromkeys(leg_ids)), ST_PLACED, '']))
        except Exception:
            pass
        log.info('OCO تور ایمنی %s ثبت شد (SL=%s | TP=%s)',
                 sym, fmt_price(sl), fmt_price(tp))


# GUARDS_DEFS: (name, log_pattern, active_condition)
GUARDS_DEFS = [
    ('MAX_DAILY_TRADES',     'سقف معاملات روزانه',           True),
    ('OPEN_POSITION_EXISTS', 'پوزیشن یا سفارش باز موجود',     True),
    ('SAME_CYCLE',           'خروج در همین چرخه',            True),
    ('ORDER_FAIL_COOLDOWN_MIN', 'سفارش ناموفق در',            'order_fail_cooldown_min'),
    ('REENTRY_COOLDOWN_MIN', 'خروج زیان‌ده در',              'reentry_cooldown_min'),
    ('MAX_OPEN_POSITIONS',   'سقف پوزیشن باز',               True),
    ('BAND_SL_TP',           'باند SL/TP زیر حداقل',         True),
    ('G_SLBUF',              'SL buffer',                    True),
    ('G_BANDCAP',            'SL band',                       True),
    ('G_GLOBAL',             'no global mark price',          True),
    ('MAX_LOCAL_PREMIUM_PCT','local premium',                True),
    ('MAX_MARK_DEVIATION_PCT','above global mark',            True),
    ('PUMP_GUARD_PCT',       'momentum exhaustion',          'pump_guard_pct'),
    ('LOSS_STREAK_LIMIT',    'losing exits in last',         'loss_streak_limit'),
    ('TREND_FILTER_ENABLED', 'market regime bearish',        'trend_filter_enabled'),
    ('MIN_USDT_BALANCE',     'موجودی USDT کافی نیست',        True),
    ('ENTRY_TTL_MIN',        'سفارش ورود کهنه لغو شد',       True),
    ('RISK_TARGET_USDT',     'G-volsize',                     True),
    ('MAX_SL_MULT',          'G-maxsl',                      'use_bt_params'),
]


GUARDS_DUTY = {
    'MAX_DAILY_TRADES': 'جلوگیری از ثبت بیش از حداکثر تعداد معامله در یک روز',
    'OPEN_POSITION_EXISTS': 'جلوگیری از ورود همزمان به نمادی که پوزیشن باز دارد',
    'SAME_CYCLE': 'جلوگیری از خرید مجدد نمادی که در همان چرخه بسته شده',
    'ORDER_FAIL_COOLDOWN_MIN': 'صبر بعد از سفارش ناموفق (UnexpectedMarketPrice و غیره)',
    'REENTRY_COOLDOWN_MIN': 'صبر بعد از خروج زیان‌ده برای جلوگیری از ورود مجدد سریع',
    'BAND_SL_TP': 'رد ورود اگر باند SL/TP زیر حداقل هزینه باشد (TP<1.5٪ یا SL<1.0٪)',
    'G_SLBUF': 'رد ورود اگر بافر SL نسبت به fill تخمینی کمتر از 0.5٪ باشد',
    'G_BANDCAP': 'رد نمادهای پرنوسان (عرض SL > 8٪) مثل STRK و WAL',
    'G_GLOBAL': 'رد نمادهای بدون داده جهانی (mark=0) مثل COPXON و SLVON',
    'MAX_LOCAL_PREMIUM_PCT': 'رد ورود اگر پریمیوم محلی/جهانی > 10٪ (ریسک نوسان تومانی)',
    'MAX_MARK_DEVIATION_PCT': 'رد ورود اگر قیمت محلی > 2٪ بالاتر از جهانی (پامپ محلی بدون پشتوانه)',
    'PUMP_GUARD_PCT': 'رد ورود اگر قیمت بیش از 5٪ بالاتر از SMA20(1h) باشد (اشباع خرید)',
    'LOSS_STREAK_LIMIT': 'صبر بعد از N خروج زیان‌ده در پنجره زمانی (جلوگیری از سقوط روی چاقو)',
    'TREND_FILTER_ENABLED': 'مسدود کردن همه خریدها وقتی BTC نزولی است (SMA20<SMA50)',
    'MIN_USDT_BALANCE': 'رد ورود اگر موجودی USDT کافی نباشد',
    'ENTRY_TTL_MIN': 'لغو سفارش limit کهنه اگر پس از 60 دقیقه پر نشود',
    'RISK_TARGET_USDT': 'برابرسازی ریسک دلاری هر معامله (cap $0.50)',
    'MAX_SL_MULT': 'محدود کردن ضریب SL از بک‌تست به 1.5× (جلوگیری از زیان شدید)',
}


def _guard_active(st, cond):
    if cond is True:
        return True
    if cond is False:
        return False
    return bool(getattr(st, cond, 0))


def _parse_guard_line(line):
    """P4: استخراج (زمان تهران جلالی، نماد، علت کامل) از یک خط لاگ EDT"""
    import re as _re
    from datetime import datetime as _dt
    out_time = out_sym = out_reason = None
    mt = _re.match(r'(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})', line)
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
    ms = _re.search(r'(?:skip buy|خرید|فروش)\s+(\w+)', line)
    if ms:
        out_sym = ms.group(1)
    mr = _re.search(r'\]\s+(.+)$', line)
    if mr:
        out_reason = mr.group(1).strip()[:80]
    return out_time, out_sym, out_reason


def write_guards_status(sh, st, state=None):
    """G-guards: live status of all guards + last trigger + today count"""
    import os as _os, re as _re
    from datetime import datetime as _dt
    try:
        try:
            ws = sh.worksheet(GUARDS_TAB)
        except Exception:
            ws = sh.add_worksheet(title=GUARDS_TAB, rows=30, cols=8)
            ws.update(values=[['پایش زنده گاردها', 'به‌روزرسانی:', jnow()]],
                      range_name='A1:C1')
            ws.update(values=[['نام گارد', 'وظیفه', 'وضعیت', 'آخرین رد', 'نماد', 'علت', 'تعداد امروز', 'یادداشت']],
                      range_name='A3:H3')
            ws.freeze(rows=3)
        log_path = _os.path.expanduser('~/nobitex-usdt/update.log')
        recent_lines = []
        try:
            with open(log_path, encoding='utf-8') as f:
                lines = f.readlines()
            # آخرین ۵۰۰ خط (حدود ۲۴-۴۸ ساعت)
            recent_lines = [l.strip() for l in lines[-500:] if l.strip()]
        except Exception:
            pass
        rows = []
        _ref_time = None  # G-syms: ref = newest log timestamp
        for _line in reversed(recent_lines):
            _mt = _re.match(r'(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})', _line)
            if _mt:
                try:
                    _ref_time = _dt.strptime(_mt.group(1) + ' ' + _mt.group(2), '%Y-%m-%d %H:%M:%S')
                except Exception:
                    pass
                break
        for name, pattern, cond in GUARDS_DEFS:
            active = _guard_active(st, cond)
            status = 'فعال' if active else 'غیرفعال'
            count = 0
            last_time = '—'
            last_sym = '—'
            last_reason = '—'
            syms = []  # G-syms: distinct symbols rejected in last 60 min
            for line in recent_lines:
                if pattern in line:
                    count += 1
                    _gt, _gs, _gr = _parse_guard_line(line)
                    if _gt:
                        last_time = _gt
                    if _gs:
                        last_sym = _gs
                    if _gs and _gs not in syms:
                        _mt = _re.match(r'(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})', line)
                        if _mt and _ref_time:
                            try:
                                _lt = _dt.strptime(_mt.group(1) + ' ' + _mt.group(2), '%Y-%m-%d %H:%M:%S')
                                if 0 <= (_ref_time - _lt).total_seconds() <= 3600:
                                    syms.append(_gs)
                            except Exception:
                                pass
                    if _gr:
                        last_reason = _gr
            if syms:
                last_sym = '، '.join(syms[-5:]) + (' ...' if len(syms) > 5 else '')
            note = ''
            if cond is not True and cond is not False:
                val = getattr(st, cond, 0)
                note = '%s=%s' % (cond, val)
            duty = GUARDS_DUTY.get(name, '')
            if name == 'PUMP_GUARD_PCT':
                duty = 'رد ورود اگر قیمت بیش از %.0f%% بالای SMA20 ساعتی — زنده از تنظیمات' % st.pump_guard_pct
            elif name == 'G_SLBUF':
                duty = 'رد ورود اگر بافر SL نسبت به fill تخمینی < %.1f%% (SLBUF_MIN_PCT)' % st.slbuf_min_pct
            rows.append([name, duty, status, last_time, last_sym, last_reason, count, note])
        # گسترش ستون‌ها اگر تب قدیمی با 7 ستون ساخته شده بود
        if ws.col_count < 8:
            ws.add_cols(8 - ws.col_count)
        ws.update(values=[['پایش زنده گاردها', 'به‌روزرسانی:', jnow()]],
                  range_name='A1:C1')
        ws.update(values=[['نام گارد', 'وظیفه', 'وضعیت', 'آخرین رد (۲۴س)', 'نمادها (۶۰د)', 'علت', 'تعداد (۲۴س)', 'یادداشت']],
                  range_name='A3:H3')
        data = rows + [[''] * 8] * max(0, 25 - len(rows))
        ws.update(values=data, range_name='A4:H%d' % (4 + len(data) - 1))
    except Exception:
        log.exception('خطا در write_guards_status')


def write_effective_config(sh, st, state=None):
    """F9-lite: tab of effective config - written every signals cycle.
    Makes any sheet edit (indicator on/off, threshold, timeframe) visible
    in the same tick, e.g. 'votes needed: 3 of 5 -> 4 of 6'."""
    import math as _m
    try:
        try:
            ws = sh.worksheet(EFFECTIVE_TAB)
        except Exception:   # WorksheetNotFound (gspread not imported in trader.py)
            ws = sh.add_worksheet(title=EFFECTIVE_TAB, rows=30, cols=4)
            ws.update(values=[['item', 'effective', 'derived'], ], range_name='A3:C3')
            ws.freeze(rows=3)
        voters = st.voting_indicators
        nv = len(voters)
        need = max(1, _m.ceil(nv * st.threshold_pct / 100.0))
        tfs = [l for l, _ in st.active_timeframes]
        maj = (len(tfs) + 1) // 2
        rows = [
            ['voting indicators', ','.join(voters), '%d voters' % nv],
            ['votes needed per TF', '%d of %d' % (need, nv),
             'threshold %.0f%%' % st.threshold_pct],
            ['active timeframes', ','.join(tfs),
             'candidate gate: %d of %d TFs' % (maj, len(tfs))],
            ['SL/TP band', 'x%s / x%s ATR(%s)' % (st.sl_atr_mult, st.tp_atr_mult, st.sltp_timeframe[0]), ''],
            ['trailing', 'act %.2f%% / dist %.2f%%' % (st.trail_activation_pct, st.trail_distance_pct),
             'on' if st.trail_enabled else 'off'],
            ['band guard (entry)', 'TP>=1.5% SL>=1.0%', 'Fix-3'],
            ['knife guard', '%d losses in %.0fh' % (st.loss_streak_limit, st.loss_streak_window_h), 'Fix-3.2b'],
            ['momentum guard', '%.1f%% above SMA20(1h)' % st.pump_guard_pct, 'Fix-3.2'],
            ['G-volsize', 'cap $%.2f' % RISK_TARGET_USDT, 'vol-targeted sizing — برابرسازی ریسک دلاری هر معامله'],
            ['G-bandcap', '≤ %.1f%%' % MAX_SL_BAND_PCT, 'فیلتر دم پرنوسان (STRK/WAL) — رد نمادهای پرنوسان'],
            ['G-global', 'mark > 0', 'رد نمادهای بدون داده جهانی (COPXON, SLVON) — فقط نمادهایی که mark نوبیتکس دارند'],
            ['G-premium', '≤ %.1f%%' % MAX_LOCAL_PREMIUM_PCT, 'رد اگر پریمیوم محلی/جهانی > حد مجاز (ریسک تومانی شدید)'],
            ['G-mark-dev', '≤ %.1f%%' % MAX_MARK_DEVIATION_PCT, 'رد اگر قیمت محلی > حد مجاز بالاتر از جهانی (پامپ محلی بدون پشتوانه)'],
            ['caps', 'pos %d | clip %s | daily %d' % (st.max_open_positions, st.order_size_usdt, st.max_daily_trades), ''],
            ['bt override', 'on' if getattr(st, 'use_bt_params', True) else 'off',
             '%d symbols' % len((state or {}).get('bt_params') or {})],
            ['mode', 'DRY' if st.dry_run else 'LIVE', 'trading %s' % ('on' if st.trading_enabled else 'OFF')],
        ]
        ws.update(values=[['Effective config (per signals tick)', 'updated:', jnow()]],
                  range_name='A1:C1')
        n = max(18, len(rows) + 4)
        data = rows + [[''] * 3] * (n - len(rows))
        ws.update(values=data, range_name='A4:C%d' % (3 + n))
    except Exception:
        log.exception('effective-config tab write failed')


def archive_orders(sh, st, led=None, threshold=300, max_age_days=7):
    """G-arch: archive old terminal rows from the orders ledger to 'آرشیو سفارشات'.
    Only moves rows that are:
      - status = cancelled or failed (no operational effect)
      - older than max_age_days
      - symbol has no open position or pending order
    Never touches OPENISH/EXECUTED rows for active symbols.
    Runs every 24h from scheduler; safe to run manually."""
    import jdatetime as _jd
    import datetime as _dt
    try:
        ws = sh.worksheet(ORDERS_TAB)
        rows = ws.get_all_values()
        if len(rows) <= threshold:
            log.info('G-arch: ledger has %d rows (≤%d) — no archive needed', len(rows), threshold)
            return 0

        # پوزیشن‌های باز و pending — این نمادها هرگز آرشیو نمی‌شوند
        if led is None:
            led = read_ledger(ws, st.dust_usdt)
        protected_syms = set(led.get('positions', {}).keys()) | set(led.get('pending', set()))

        # مرز زمانی
        cutoff = (_dt.datetime.now(_dt.timezone.utc)
                  + _dt.timedelta(hours=3, minutes=30)
                  - _dt.timedelta(days=max_age_days)).replace(tzinfo=None)
        cutoff_j = _jd.datetime.fromgregorian(datetime=cutoff).strftime('%Y/%m/%d %H:%M')

        # شناسایی ردیف‌های آرشیوشدنی
        archivable = []
        for i, r in enumerate(rows, 1):
            if i <= 3:  # header rows
                continue
            if len(r) < 12:
                continue
            t = str(r[0]).strip()
            sym = str(r[1]).strip().upper()
            status = str(r[11]).strip()
            if not t or t >= cutoff_j:
                continue  # too recent
            if sym in protected_syms:
                continue  # active symbol
            if status in (ST_CANCELLED, 'ناموفق'):  # لغو شده, ناموفق
                archivable.append((i, r))

        if not archivable:
            log.info('G-arch: %d rows but 0 archivable (all recent or active)', len(rows))
            return 0

        # تب آرشیو — ساخت اگر نیست
        ARCH_TAB = 'آرشیو سفارشات'
        try:
            arch = sh.worksheet(ARCH_TAB)
        except Exception:
            arch = sh.add_worksheet(title=ARCH_TAB, rows=200, cols=14)
            arch.append_row(['ردیف اصلی'] +
                           ['زمان', 'نماد',
                            'عملیات', 'تایم‌فریم',
                            'دلیل', 'قیمت', 'مقدار',
                            'مبلغ', 'SL', 'TP',
                            'شناسه', 'وضعیت', 'پیام'])
            log.info('G-arch: created archive tab')

        # کپی
        arch.append_rows([[str(i)] + [str(c) for c in r] for i, r in archivable])

        # حذف از دفتر (از پایین به بالا)
        row_nums = [i for i, _ in archivable]
        runs = []
        for n in row_nums:
            if runs and runs[-1][1] == n - 1:
                runs[-1][1] = n
            else:
                runs.append([n, n])
        reqs = [{'deleteDimension': {'range': {'sheetId': ws.id,
                                              'dimension': 'ROWS',
                                              'startIndex': a - 1, 'endIndex': b}}}
                for a, b in sorted(runs, reverse=True)]
        ws.spreadsheet.batch_update({'requests': reqs})

        log.info('G-arch: archived %d rows (%d ranges) — ledger now %d rows',
                 len(archivable), len(runs), len(rows) - len(archivable))
        return len(archivable)
    except Exception:
        log.exception('G-arch: archive failed — ledger untouched')
        return 0


def _sl_buffer_skip(a, st):
    # G-slbuf (بهبود ۱): (skip, buf, fill_est) — آیا ورود به‌خاطر بافر SL ریز رد شود؟
    # بافر = فاصلهٔ SL از قیمت fill تخمینی (limit_pullback: سیگنال×(1−پولبک) —
    # همان فرمول buy_one). شواهد: وقتی 1.5×ATR < پولبک، fill روی استاپ می‌نشیند —
    # XRP 0.07٪، SOL 0.13٪، ADA 0.31٪ → استاپ آنی؛ سطل [0–0.5٪): ۱۰/۱۶ استاپ.
    # دادهٔ ناقص → False (fail-open: گارد کیفیت است، نه ایمنی).
    row = (a.get('best') or (None, None))[1]
    if row is None or len(row) < 10:
        return False, None, None
    p = parse_price(row[2])
    sl = parse_price(row[9])
    if not (p and sl and p > 0 and sl < p):
        return False, None, None
    mkt = (st.order_type == 'market' and st.entry_mode != 'limit_pullback')
    _pp = st.pullback_pct if mkt else _eff_pullback_pct(row, st)
    fill = p if mkt else p * (1 - _pp / 100.0)
    buf = (fill - sl) / fill * 100.0
    return (buf < st.slbuf_min_pct), buf, fill


def _rank_candidates(agg, st=None):
    # بهبود ۴ (G-rank): اولویت خرید = کیفیت سیگنال — اکثریت TF (نزولی)، سپس
    # قوت بهترین TF (نزولی)؛ برابرها → ترتیب universe/نقدشوندگی (sort پایدار).
    # تا پیش از این ترتیب خرید = ترتیب universe بود و «رتبه‌بندی برای سفارشگزاری»
    # صرفاً نمایشی بود (ممیزی ۱۴۰۵/۰۷/۲۲ — cands بدون هیچ sort).
    cands = [s for s, a in agg.items() if is_buy_candidate(a, st)]
    cands.sort(key=lambda s: (-agg[s]['buys'],
                              -(agg[s]['best'][0] if agg[s]['best'] else 0)))
    return cands


def _eff_pullback_pct(row, st):
    # بهبود ۳ (G-vpull): پولبک volatility-based — clamp(0.5×ATR٪, 0.3٪, 2.0٪).
    # ATR از خود ردیف: (سیگنال−SL)/ضریب — سازگار با G-fillanchor. دادهٔ ناقص →
    # st.pullback_pct (رفتار فعلی؛ fail-open).
    try:
        p = parse_price(row[2])
        sl = parse_price(row[9])
        slm = getattr(st, 'sl_atr_mult', 0) or 0
        if p and sl and slm > 0 and 0 < sl < p:
            atr_pct = (p - sl) / slm / p * 100.0
            return min(max(0.5 * atr_pct, 0.3), 2.0)
    except Exception:
        pass
    return st.pullback_pct


def run(sh, st, rows, state=None):
    dry = st.dry_run
    write_effective_config(sh, st, state)
    log.info('ماژول معاملات فعال — حالت: %s', 'شبیه‌سازی (DRY-RUN)' if dry else '⚠️ سفارش واقعی')
    ws_t = sh.worksheet(TRADES_TAB)
    client = make_client()
    if not dry and not client:
        log.error('معامله واقعی فعال است اما کلیدهای API در .env ناقص‌اند — هیچ سفارشی ثبت نشد')
        return

    agg = aggregate_signals(rows)
    # G-trend: one BTC trend check per cycle
    run._btc_bearish = _btc_trend_bearish() if st.trend_filter_enabled else False
    prices = {str(r[0]).upper(): parse_price(r[2]) for r in rows if r and r[0]}
    led = read_ledger(ws_t, st.dust_usdt)
    # N2/Fix-A: snapshot پوزیشن‌ها «قبل از sync» — خروج‌هایی که sync در همین تیک
    # تشخیص می‌دهد (پر شدن OCO روی صرافی) نیز از خرید مجدد همان چرخه بلاک می‌شوند
    positions_at_start = set(led['positions'])

    if client and not dry:
        sync_order_statuses(ws_t, led, client, st)
        led = read_ledger(ws_t, st.dust_usdt)  # خواندن مجدد پس از همگام‌سازی
    if client:
        reconcile_real_positions(st, ws_t, client, led, prices)
    if client:
        cancel_stale_entries(st, ws_t, client, led)
    if client:
        backfill_oco(st, ws_t, client, led, prices)

    # ۰) اجرای خودکار حد ضرر/حد سود — با اولویت بالا، قبل از سیگنال‌ها
    apply_trailing(st, ws_t, led, prices, client)
    check_position_timeout(st, ws_t, client, dry, led, prices)
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

    cands = _rank_candidates(agg, st)
    log.info('کاندیدهای خرید این اجرا: %s', '، '.join(cands) if cands else 'هیچ')

    # ۱) فروش پوزیشن‌هایی که سیگنال فروش اکثریت گرفته‌اند
    for sym in list(led['positions']):
        a = agg.get(sym)
        if not (a and is_sell_candidate(a, st)):
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
    _pump_sma_cache = {}
    for sym in cands:
        a = agg[sym]
        if led['daily_count'] >= st.max_daily_trades:
            log.info('خرید %s انجام نشد: سقف معاملات روزانه (%d)', sym, st.max_daily_trades)
            continue
        if sym in led['positions'] or sym in led['pending']:
            log.info('خرید %s انجام نشد: پوزیشن یا سفارش باز موجود است', sym)
            continue
        if sym in positions_at_start:
            log.info('خرید %s انجام نشد: خروج در همین چرخه — ورود مجدد از تیک بعد', sym)
            continue
        if st.order_fail_cooldown_min > 0 and recent_failed_buy(led, sym, st.order_fail_cooldown_min):
            log.info('خرید %s انجام نشد: سفارش ناموفق در %d دقیقه اخیر — صبر', sym, st.order_fail_cooldown_min)
            continue
        if st.reentry_cooldown_min > 0 and recent_losing_exit(led, sym, st.reentry_cooldown_min):
            log.info('خرید %s انجام نشد: خروج زیان‌ده در %d دقیقه اخیر — کول‌داون ورود مجدد', sym, st.reentry_cooldown_min)
            continue
        if open_pos >= st.max_open_positions:
            log.info('خرید %s انجام نشد: سقف پوزیشن باز (%d)', sym, st.max_open_positions)
            continue
        p = prices.get(sym)
        if not p or p <= 0:
            continue
        # Fix-3: گارد باندِ ورود — در نمادهای کم‌نوسان (مثل ETH/BTC/XAUT) که
        # 3×ATR٪ ≈ هزینه رفت‌وبرگشت است، TP خالص سودی باقی نمی‌گذارد (رخداد
        # ETH 1405/07/12: TP=+0.89٪، خالص ≈ +0.04)؛ ورود باید باندی داشته باشد
        # که سود خالص معنادار بدهد
        row = a['best'][1]
        tp_c, sl_c = parse_price(row[10]), parse_price(row[9])
        if tp_c and sl_c:
            tp_pct = (tp_c - p) / p * 100.0
            sl_pct = (p - sl_c) / p * 100.0
            if tp_pct < 1.5 or sl_pct < 1.0:
                log.info('خرید %s انجام نشد: باند SL/TP زیر حداقل هزینه (TP=%.2f٪، SL=%.2f٪)',
                         sym, tp_pct, sl_pct)
                continue
        # G-slbuf (بهبود ۱): حداقل بافر SL نسبت به fill تخمینی — رد ورود وقتی
        # 1.5×ATR از پولبک کوچک‌تر است (fill روی استاپ). حداقل ۰.۵٪؛ قابل ارتقا
        # به کلید شیت پس از walk-forward
        _skip_buf, _buf, _fill_est = _sl_buffer_skip(a, st)
        if _skip_buf:
            log.info('skip buy %s: SL buffer %.2f%% < %.1f%% at est. fill %.6g',
                 sym, _buf, st.slbuf_min_pct, _fill_est)
            continue
        # گزینهٔ ب (G-bandcap): سقف عرض استاپ — رد دُم پرنوسان (STRK 8.8٪،
        # WAL 11.1٪ → رد؛ BAT 6.3٪ → عبور با سایزِ کاهش‌یافته از گزینهٔ الف)
        _max_band = getattr(st, 'max_sl_band_pct', MAX_SL_BAND_PCT)
        _w_pct = _sl_width_pct(row, st)
        if _w_pct is not None and _w_pct > _max_band:
            log.info('skip buy %s: SL band %.1f%% > %.1f%% (high-volatility tail)',
                     sym, _w_pct, _max_band)
            continue
        # G-global: فقط نمادهایی که داده جهانی دارند (mark > 0)
        _mark_px = _public_mark(sym)
        if not _mark_px or _mark_px <= 0:
            log.info('skip buy %s: no global mark price (no global data)', sym)
            continue
        # G-premium: رد اگر پریمیوم محلی/جهانی > 10٪ (ریسک تومانی)
        _prem = (p / _mark_px - 1) * 100
        if _prem > MAX_LOCAL_PREMIUM_PCT:
            log.info('skip buy %s: local premium %.1f%% > %.1f%% (high toman premium)',
                     sym, _prem, MAX_LOCAL_PREMIUM_PCT)
            continue
        # G-mark-dev: رد اگر قیمت محلی بیش از ۲٪ بالاتر از جهانی (پامپ محلی)
        _dev = (p - _mark_px) / _mark_px * 100
        if _dev > MAX_MARK_DEVIATION_PCT:
            log.info('skip buy %s: local price %.1f%% above global mark (pump without global backing)',
                     sym, _dev)
            continue
        # G3.2 momentum guard (ORCA 1405/07/14: entry near top of +17% rally
        # -> loss): entry price must not be far above SMA20(1h)
        if st.pump_guard_pct > 0:
            sma_r = _pump_sma_cache.get(sym)
            if sma_r is None:
                c_g = fetch_candles(sym + 'USDT', '60', 60)
                s_series = sma(c_g['c'], 20) if c_g and len(c_g.get('c') or ()) >= 20 else []
                sma_r = s_series[-1] if s_series and s_series[-1] is not None else 0.0
                _pump_sma_cache[sym] = sma_r
            if sma_r and p > sma_r * (1 + st.pump_guard_pct / 100.0):
                log.info('skip buy %s: momentum exhaustion - price %+.1f%% above SMA20(1h)',
                         sym, (p / sma_r - 1) * 100.0)
                continue
        # G3.2 anti-knife (ZEC pattern 1405/07/14: repeated entries while
        # price fell 1450->1310): N losing exits in window -> no re-entry
        if st.loss_streak_limit > 0:
            n_loss = losing_exits_count(led, sym, st.loss_streak_window_h * 60)
            if n_loss >= st.loss_streak_limit:
                log.info('skip buy %s: %d losing exits in last %dh - knife cooldown',
                         sym, n_loss, st.loss_streak_window_h)
                continue
        # G-trend: market regime filter - skip all buys when BTC bearish
        if st.trend_filter_enabled and getattr(run, '_btc_bearish', False):
            if sym == list(cands)[0]:  # log once per cycle
                log.info('skip buy %s: market regime bearish (BTC 4h SMA20<SMA50)', sym)
            continue
        if dry:
            bal = st.dry_start_usdt - led['dry_net_spent']
        else:
            bal = currency_available(client, 'usdt')
            if bal is None:
                log.error('خرید %s انجام نشد: موجودی USDT از API قابل دریافت نیست', sym)
                continue
        # G-scale: بررسی فقط Scale 1/2 (نصف کل) به‌جای کل مبلغ؛
        # G-market-entry: در مسیر مارکت حجم کامل لازم است
        _need_size = (st.order_size_usdt if
                      (st.order_type == 'market' and st.entry_mode != 'limit_pullback')
                      else st.order_size_usdt * 0.5)
        if bal < _need_size or bal - _need_size < st.min_usdt_balance:
            log.info('خرید %s انجام نشد: موجودی USDT کافی نیست (%.1f)', sym, bal)
            continue
        buy_one(st, ws_t, client, dry, sym, a, p, led, coid=f'nbx-{sym.lower().replace("_", "")}-{int(time.time())}')
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


def update_report(sh, st, rows, client=None):
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
    _rep_client = client or make_client()
    for sym, p in led['positions'].items():
        px = prices.get(sym)
        if px is None:
            continue
        pos_value += p['volume'] * px
        # G-float: real entry from exchange fills (N7 pattern) with ledger fallback;
        # buy fee (charged in coin) converted at fill price and subtracted
        entry_r, buy_fee_r = _entry_fill(_rep_client, led, sym)
        entry_eff = entry_r or p.get('entry_price')
        if entry_eff:
            unreal += p['volume'] * (px - entry_eff) - (buy_fee_r or 0.0)

    realized = 0.0
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
