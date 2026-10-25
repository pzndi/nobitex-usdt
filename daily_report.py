#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
daily_report.py — گزارش روزانهٔ سلامت/عملکرد (فقط-خواندن)
بخش‌ها: سلامت | عملکرد امروز | پوزیشن‌ها+حفاظت | اثبات‌های fixها |
خطاهای امروز (طبقه‌بندی) | انحراف تنظیمات از baseline عصر جدید | دیسک/بکاپ | ریسک لحظه‌ای پوزیشن‌های باز
"""
import os
import re
import subprocess
import sys
from datetime import datetime

import net_timeout  # noqa

LOG = 'update.log'

ERA_BASELINE = {
    'SMA': 'بله', 'EMA': 'بله', 'RSI': 'خیر', 'MACD': 'بله', 'BB': 'بله', 'ATR': 'بله',
    '5m': 'خیر', '15m': 'بله', '1h': 'بله', '4h': 'بله', '1D': 'بله',
    'TRADING_ENABLED': 'بله', 'DRY_RUN': 'خیر',
    'ORDER_TYPE': 'limit', 'EXIT_ORDER_TYPE': 'market',
    'ORDER_SIZE_USDT': '10', 'MAX_OPEN_POSITIONS': '3',
    'SL_ATR_MULT': '1.5', 'TP_ATR_MULT': '3', 'USE_EXCHANGE_OCO': 'بله',
    'TRAIL_ENABLED': 'بله', 'TRAIL_ACTIVATION_PCT': '2', 'TRAIL_ATR_MULT': '0.5',
    'ENTRY_TTL_MIN': '60', 'REENTRY_COOLDOWN_MIN': '30',
    'SIGNAL_THRESHOLD_PCT': '60', 'ENTRY_MODE': 'limit_pullback', 'PULLBACK_PCT': '1.0',
    'POSITION_TIMEOUT_H': '8', 'PUMP_GUARD_PCT': '5', 'MAX_SL_MULT': '1.5',
    'TREND_FILTER_ENABLED': 'بله', 'USE_BT_PARAMS': 'خیر',
    'INTERVAL_SIGNALS_MIN': '3', 'MAX_DAILY_TRADES': '100', 'MIN_USDT_BALANCE': '1',
}


def _today():
    return datetime.now().strftime('%Y-%m-%d')


def _log_lines():
    try:
        with open(LOG, encoding='utf-8', errors='replace') as f:
            return f.read().splitlines()
    except OSError:
        return []


def sec_health(lines):
    print('=== ۱) سلامت ===')
    for l in lines[-5:]:
        print(' ', l[:150])
    errs = [l for l in lines if 'خطا در چرخه' in l]
    errs_today = [l for l in errs if l.startswith(_today())]
    print(f'خطاهای چرخه: کل={len(errs)} | امروز={len(errs_today)}')
    ticks = [l for l in lines if 'چرخه‌های این تیک' in l or 'تیک:' in l]
    if ticks:
        print('  آخرین تیک:', ticks[-1][:110])
    try:
        out = subprocess.run(['pgrep', '-af', 'nobitex-usdt.*scheduler.py'],
                             capture_output=True, text=True).stdout.strip()
        print('  scheduler:', (out.splitlines()[0][:90] if out else 'بین تیک‌ها (طبیعی)'))
    except Exception:
        pass


def sec_perf(lines):
    print('=== ۲) عملکرد امروز ===')
    rep = [l for l in lines if 'تب گزارش به‌روزرسانی' in l]
    trd = [l for l in lines if 'معاملات امروز ربات' in l]
    if rep:
        print(' ', rep[-1][:130])
    if trd:
        print(' ', trd[-1][:130])


def sec_positions():
    print('=== ۳) پوزیشن‌ها + حفاظت ===')
    import trader as tr
    client = tr.make_client()
    if not client:
        print('  کلاینت API در دسترس نیست')
        return
    code, data = client.open_orders()
    orders = (data.get('orders') or []) if isinstance(data, dict) else []
    print(f'  سفارش‌های باز صرافی: {len(orders)}')
    prot = set()
    sells = []
    for o in orders:
        sym = str(o.get('srcCurrency') or '')
        typ = str(o.get('type') or '').lower()
        print(f"    {typ:9} | {sym[:20]:20} | px={o.get('price')} | amt={o.get('amount')}")
        if typ == 'sell':
            prot.add(sym.lower())
            sells.append(o)
    code, wd = client.wallets()
    wl = wd.get('wallets') if isinstance(wd, dict) else None
    held = {}
    if isinstance(wl, list):
        for w in wl:
            try:
                bal = float(str(w.get('balance') or 0).replace(',', ''))
            except (TypeError, ValueError):
                continue
            if bal > 0:
                held[str(w.get('currency') or '').lower()] = bal
    print(f"  USDT: {held.get('usdt', 0.0):.2f}")
    flagged = False
    for cur, bal in sorted(held.items()):
        if cur in ('usdt', 'irt', 'rls') or cur in prot:
            continue
        # نام ارز کیف پول با srcCurrency سفارش متفاوت است (s↔Sonic،
        # bat↔BasicAttentionToken) → تطبیق با مقدار سفارش فروش (تلورانس ۲٪)
        amt_cov = False
        for so in sells:
            try:
                a = float(str(so.get('amount') or 0).replace(',', ''))
            except (TypeError, ValueError):
                continue
            if a > 0 and abs(a - bal) / max(bal, 1e-12) < 0.02:
                amt_cov = True
                break
        if amt_cov:
            continue
        try:
            px = tr._public_price(cur.upper())
        except Exception:
            px = None
        val = bal * px if px else None
        if val is None or val >= 1.0:
            print(f'  ⚠ {cur}: {bal} (~{val or "?"} USDT) — بدون سفارش فروش باز')
            flagged = True
    if not flagged:
        print('  ✓ همهٔ دارایی‌های غیرغبار پوشش فروش دارند (تطبیق نام یا مقدار)')


def sec_fixes(lines):
    print('=== ۴) اثبات‌های امروز ===')
    pats = [
        ('لغو TTL', r'سفارش ورود کهنه لغو شد'),
        ('G-fillanchor', r'G-fillanchor'),
        ('G-slbuf رد', r'SL buffer'),
        ('G-ump-sell', r'G-ump-sell'),
        ('OCO متحرک', r'OCO متحرک'),
        ('گذار fill', r'گذار خرید به پرشد'),
        ('ثبت خرید', r'سفارش ثبت شد: خرید'),
        ('بسته‌شدن', r'معامله \S+ بسته شد'),
    ]
    today = _today()
    any_row = False
    for name, pat in pats:
        rx = re.compile(pat)
        allm = [l for l in lines if rx.search(l)]
        tm = [l for l in allm if l.startswith(today)]
        if allm:
            any_row = True
            print(f'  {name}: امروز={len(tm)} | کل={len(allm)}')
            if tm:
                print(f'    آخرین: {tm[-1][:120]}')
    if not any_row:
        print('  — هیچ رخدادی در لاگ')


def sec_errors(lines):
    print('=== ۵) خطاهای امروز ===')
    today = _today()
    idxs = [i for i, l in enumerate(lines)
            if 'خطا در چرخه' in l and l.startswith(today)]
    if not idxs:
        print('  ✓ بدون خطا')
        return
    for i in idxs:
        # پنجرهٔ داینامیک: تا ورودی بعدی لاگ (حداکثر ۶۰ خط) — tracebackهای
        # دومرحله‌ای (ReadTimeout و...) کامل در می‌آیند
        j = i + 1
        while j < len(lines) and j < i + 60 and not lines[j][:5].isdigit():
            j += 1
        window = '\n'.join(lines[i:j])
        if 'Read timed out' in window or 'ReadTimeout' in window:
            kind = 'timeout خواندن (گوگل)'
        elif 'SSL' in window or 'ssl_wrap' in window:
            kind = 'SSL/برقراری اتصال'
        elif 'NameResolutionError' in window:
            kind = 'DNS'
        elif 'exceeds grid' in window:
            kind = 'grid شیت!'
        elif 'ConnectionReset' in window or 'RemoteDisconnected' in window:
            kind = 'قطع/ریست اتصال'
        else:
            kind = 'نامشخص (traceback را ببینید)'
        print(f'  {lines[i][:95]}  → {kind}')


def sec_settings():
    print('=== ۶) انحراف تنظیمات از baseline عصر جدید ===')
    import gspread
    from settings import load_env
    gc = gspread.service_account(filename='service_account.json')
    ws = gc.open_by_key(load_env().get('SHEET_ID')).worksheet('تنظیمات')
    live = {}
    for r in ws.get_all_values():
        c = [str(x).strip() for x in (list(r) + ['', ''])[:2]]
        if c[0] in ERA_BASELINE and c[1]:
            live[c[0]] = c[1]
    drift = []
    for k, v in ERA_BASELINE.items():
        lv = live.get(k)
        if lv is None:
            drift.append(f'{k}: در شیت یافت نشد')
        elif str(lv) != str(v):
            drift.append(f'{k}: شیت={lv} | baseline={v}')
    if drift:
        print('  ⚠ انحراف:')
        for d in drift:
            print('   ', d)
    else:
        print('  ✓ همهٔ کلیدهای baseline منطبق')


def sec_disk():
    print('=== ۷) دیسک/لاگ/بکاپ ===')
    sz = os.path.getsize(LOG) / 1e6
    print(f'  {LOG}: {sz:.1f} MB')
    rots = sorted(f for f in os.listdir('.') if f.startswith('update.log.'))
    if rots:
        print('  چرخش:', ', '.join(rots))
    baks = sorted(f for f in os.listdir('.') if re.match(r'trader\.py\.bak-\d{8}-\d{6}', f))
    if baks:
        print(f'  ⚠ بکاپ‌های باقی‌مانده ({len(baks)}): {", ".join(baks)}')
    else:
        print('  بکاپ: ندارد ✓')


def sec_risk():
    print('=== ۸) ریسک لحظه‌ای پوزیشن‌های باز ===')
    import trader as tr
    fills = {}
    try:
        with open(LOG, encoding='utf-8', errors='replace') as f:
            for line in f:
                m = re.search(r'G-fillanchor (\S+):.*\(fill=([\d.]+)\)', line)
                if m:
                    fills[m.group(1).upper()] = float(m.group(2))
    except OSError:
        pass
    client = tr.make_client()
    if not client:
        print('  کلاینت API در دسترس نیست')
        return
    code, data = client.open_orders()
    orders = (data.get('orders') or []) if isinstance(data, dict) else []
    ocos = {}
    for o in orders:
        if str(o.get('type', '')).lower() != 'sell':
            continue
        sym = str(o.get('srcCurrency') or '').upper()
        d = ocos.setdefault(sym, {})
        if str(o.get('execution')) == 'Limit':
            d['tp'] = float(o.get('price'))
        else:
            d['sl_trig'] = float(o.get('param1'))
            d['sl_exec'] = float(o.get('price'))
            d['vol'] = float(o.get('amount'))
    code, wd = client.wallets()
    held = {}
    for w in (wd.get('wallets') or []):
        try:
            bal = float(str(w.get('balance') or 0).replace(',', ''))
        except (TypeError, ValueError):
            continue
        if bal > 0:
            held[str(w.get('currency') or '').lower()] = bal
    if not ocos:
        print('  — پوزیشن بازی نیست')
        return
    print(f'  {"نماد":5} | {"fill":>9} | {"قیمت":>9} | {"SLاجرا":>9} | {"بافر٪":>5} | '
          f'{"تاSL٪":>5} | {"تاTP٪":>5} | {"ضرر استاپ":>9} | {"شناور":>8}')
    tot_risk, tot_flt = 0.0, 0.0
    for sym, d in sorted(ocos.items()):
        short = sym
        for cur, bal in held.items():
            v = d.get('vol') or 0
            if v > 0 and abs(v - bal) / max(bal, 1e-12) < 0.02:
                short = cur.upper()
                break
        fill = fills.get(short)
        try:
            px = tr._public_price(short)
        except Exception:
            px = None
        vol = d.get('vol') or 0
        if not (fill and px and vol):
            print(f'  {sym:5} | دادهٔ ناقص (fill={fill}, px={px})')
            continue
        buf = (fill - d['sl_trig']) / fill * 100
        dsl = (px - d['sl_trig']) / px * 100
        dtp = (d['tp'] - px) / px * 100
        stop_loss = vol * (fill - d['sl_exec'])
        flt = vol * (px - fill)
        tot_risk += stop_loss
        tot_flt += flt
        print(f'  {short:5} | {fill:9.5f} | {px:9.5f} | {d["sl_exec"]:9.5f} | {buf:5.1f} | '
              f'{dsl:5.1f} | {dtp:5.1f} | {stop_loss:+9.2f} | {flt:+8.2f}')
    print(f'  — مجموع: ضرر در صورت استاپ = {tot_risk:.2f} | شناور = {tot_flt:+.2f} | '
          f'USDT آزاد = {held.get("usdt", 0):.2f}')


def main():
    lines = _log_lines()
    print(f'###### گزارش روزانه — {datetime.now().strftime("%Y-%m-%d %H:%M")} ######')
    for fn, arg in ((sec_health, lines), (sec_perf, lines), (sec_positions, None),
                    (sec_fixes, lines), (sec_errors, lines),
                    (sec_settings, None), (sec_disk, None), (sec_risk, None)):
        try:
            fn(arg) if arg is not None else fn()
        except Exception as e:
            print(f'  ⚠ خطای بخش {fn.__name__}: {e!r}')
    print('###### پایان گزارش ######')
    return 0


if __name__ == '__main__':
    sys.exit(main())
