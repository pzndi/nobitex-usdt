#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""apply_leg_fifo.py — G-legfifo: ورود اختصاصی هر خروج در «اتمام معاملات» — مبنا: r81/r82

ریشه: در گذار فروش→پرشد (sync_order_statuses)، ورود از _entry_fill = VWAP «کل چرخه»
است؛ در خروج‌های پای‌به‌پای (DASH 08/05: OCO1 پای۱ با ورود واقعی 55.0960 و تور ایمنی
پای۲ با 54.8205) هر دو ردیف 54.9595 ثبت شد → بازدهی٪ فشرده‌شده به سمت صفر
(−0.96/−1.21 واقعی و +0.55/+0.80 واقعی) و نویز ~0.25pp در میانه‌های «ترکیب برنده».

اصلاح (بدون تغییر نویسنده‌های OCO):
  1) helper _leg_fifo_entry: صف FIFO لات‌های خریدِ اجراشده (غیرشبیه‌سازی)؛ هر فروشِ
     اجراشدهٔ قبلی از جلو صف مصرف می‌کند؛ سطر خروج خودش vol_c را مصرف می‌کند و
     خروجی = (VWAP لات‌های مصرف‌شده در همین نوبت، کارمزد خرید prorate از N7).
     قیمت لات از fillهای N7 همان سفارش، در غیابش از قیمت ثبت (limit پرشده ≈ ثبت).
     گاردها: پوشش <۵۰٪ → None؛ خطا → None + log.warning (fail-open به _entry_fill).
  2) سیم‌کشی فقط در گذار 849 (لنگر دوسطری یکتا). کالر دوم _entry_fill در G-scale
     (OCO ترکیبی — به‌حق VWAP کل چرخه) دست نمی‌خورد. مسیر 2374 (خروج کیف پول؛
     سند: چرخه‌های تک‌پای از قبل درست) خارج از محدوده.
  اثر: ستون ورود «اتمام معاملات» + ورودی «تحلیل معاملات/ترکیب برنده» + مهر Fix-B
  (کول‌داون r80) هم‌زمان پای-به-پای می‌شوند. Σ(entry_i−exit_i)×vol_i و P&L کل حفظ می‌شود.

all-or-nothing + pre-flight شکل خروجی _fills_for_orders + کامپایل + نوشتن اتمیک.
تست: ۸ سناریوی مصنوعی + اسموک زندهٔ دفتر (مبنای ستون‌ها، بدون API).
"""
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
FAILED = []


def load(fn):
    with open(os.path.join(BASE, fn), encoding='utf-8') as f:
        return f.read()


def save_atomic(fn, src):
    tmp = os.path.join(BASE, fn + '.tmp_patch')
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(src)
    os.replace(tmp, os.path.join(BASE, fn))


def rep(src, old, new, what):
    n = src.count(old)
    if n != 1:
        FAILED.append('%s: %d مطابقت (انتظار 1)' % (what, n))
        return src
    print('  OK %s' % what)
    return src.replace(old, new)


print('== 1) ویرایش trader.py ==')
t = load('trader.py')
if 'def _leg_fifo_entry' in t:
    FAILED.append('helper _leg_fifo_entry از قبل موجود است — تداخل نام')

# pre-flight: شکل خروجی _fills_for_orders (dict با vwap/amount/fee)
if t.count('def _fills_for_orders') != 1:
    FAILED.append('def _fills_for_orders: %d مورد' % t.count('def _fills_for_orders'))
else:
    seg = t.split('def _fills_for_orders', 1)[1].split('\ndef ', 1)[0]
    ret_lines = [ln.strip() for ln in seg.split('\n') if ln.strip().startswith('return')]
    final = next((ln for ln in ret_lines if 'vwap' in ln and 'amount' in ln), None)
    if final is None:
        FAILED.append('شکل خروجی _fills_for_orders ناشناخته — returnهای دیده‌شده: %r' % (ret_lines[:6],))
    else:
        print('  OK pre-flight fills: %s' % final[:110])

HELPER = '''def _leg_fifo_entry(client, led, sym, exit_row_num, exit_vol):
    """G-legfifo: (vwap, fee_usdt) ورودِ اختصاصی «همین خروج» — نه VWAP کل چرخه.
    لات‌های خرید اجراشده (غیرشبیه‌سازی) به ترتیب دفتر push و هر فروش اجراشدهٔ
    قبلی از جلو صف مصرف می‌کند؛ سطر خروج (exit_row_num) خودش exit_vol را مصرف
    می‌کند و خروجی = VWAP لات‌های مصرف‌شده در همین نوبت. قیمت/کارمزد لات از
    fillهای N7 همان سفارش (یک فراخوانی) و در غیابش از قیمت ثبت دفتر (limit
    پرشده ≈ قیمت ثبت). شاهد ناخالص/خالص: DASH پای۱ 0.045375 → OCO 0.045355
    (−0.044٪) و تور ایمنی 0.045614 در برابر پای۲ 0.045603 (+0.024٪) → تحمل
    مصرف + گارد پوشش ۵۰٪. None → caller به _entry_fill برمی‌گردد (ردیف قدیمی/
    آرشیوشده/ناهمخوان)."""
    try:
        lot_rows = []   # [oid, qty, px]
        consumed = []   # (oid, take, px) — فقط نوبت سطر خروج
        for rn, rr in (led.get('rows') or []):
            if rn > exit_row_num:
                break
            if rr[1].strip().upper() != sym:
                continue
            rstat = rr[11].strip() if len(rr) > 11 else ''
            if rstat not in EXECUTED or rstat == ST_DRY:
                continue
            rtype = rr[2].strip()
            if rtype == 'خرید':
                fo = clean_oid(str(rr[10]).split('|')[0])
                if not fo or fo == chr(8212):
                    fo = ''
                lot_rows.append([fo, parse_price(rr[6]) or 0.0,
                                 parse_price(rr[5]) or 0.0])
            elif rtype == 'فروش':
                if rn == exit_row_num:
                    need = float(exit_vol) if exit_vol else (parse_price(rr[6]) or 0.0)
                else:
                    need = parse_price(rr[6]) or 0.0
                while need > 1e-12 and lot_rows:
                    take = min(need, lot_rows[0][1])
                    if rn == exit_row_num and take > 1e-12:
                        consumed.append((lot_rows[0][0], take, lot_rows[0][2]))
                    lot_rows[0][1] -= take
                    need -= take
                    if lot_rows[0][1] <= 1e-12:
                        lot_rows.pop(0)
                if rn == exit_row_num:
                    break
        if not consumed:
            return None
        amt = sum(t2 for _, t2, _ in consumed)
        if exit_vol and amt < 0.5 * float(exit_vol):
            return None
        fills = {}
        oids = [o for o, _, _ in consumed if o]
        if client is not None and oids:
            try:
                fills = _fills_for_orders(client, oids) or {}
            except Exception:
                fills = {}
        cost = fee = 0.0
        for oid, take, px in consumed:
            f = fills.get(oid) if oid else None
            if f:
                try:
                    _p = float(f['vwap']) or px
                    _a = float(f['amount']) or 0.0
                    _fc = float(f['fee']) or 0.0
                    fee += _fc * _p * (take / _a if _a > 0 else 1.0)
                    px = _p
                except (KeyError, TypeError, ValueError):
                    pass
            cost += px * take
        if amt <= 0:
            return None
        return cost / amt, fee
    except Exception:
        log.warning('G-legfifo %s: خطای ساختاری — بازگشت به VWAP چرخه', sym, exc_info=True)
        return None


'''

t = rep(t, 'def _entry_fill(client, led, sym):',
        HELPER + 'def _entry_fill(client, led, sym):',
        'درج helper _leg_fifo_entry قبل از _entry_fill')

t = rep(t, """            entry_n7, buy_fee_n7 = _entry_fill(client, led, sym_c)
            entry_n7 = entry_n7 or entry_c
""",
        """            entry_n7, buy_fee_n7 = _entry_fill(client, led, sym_c)
            # G-legfifo: ورود اختصاصی همین خروج — لات‌های خریدِ مصرف‌شده تا این
            # سطر (FIFO) به‌جای VWAP کل چرخه؛ شکست/ناهمخوانی → همان _entry_fill
            try:
                _lf = _leg_fifo_entry(client, led, sym_c, row_num, vol_c)
                if _lf is not None:
                    log.info('G-legfifo %s: ورود اختصاصی این خروج %.6g (VWAP چرخه: %s)',
                             sym_c, _lf[0], ('%.6g' % entry_n7) if entry_n7 else chr(8212))
                    entry_n7, buy_fee_n7 = _lf
            except Exception:
                log.warning('G-legfifo %s: خطا — بازگشت به VWAP چرخه', sym_c, exc_info=True)
            entry_n7 = entry_n7 or entry_c
""",
        'سیم‌کشی در گذار بستن (849)')

if FAILED:
    print('\n✗ لنگرهای گم‌شده — هیچ فایلی نوشته نشد:')
    for f in FAILED:
        print('  -', f)
    sys.exit(1)

print('\n== 2) کامپایل پیش از نوشتن ==')
compile(t, 'trader.py', 'exec')
print('  OK compile trader.py')

print('\n== 3) نوشتن اتمیک ==')
save_atomic('trader.py', t)
print('  OK trader.py')

print('\n== 4) تست واحد — ۸ سناریو (client=None، مبنای ستون‌های دفتر) ==')
sys.path.insert(0, BASE)
import trader


def R(rn, sym, act, px, vol, oid, stat, tstr='1405/08/05 21:00'):
    return (rn, [tstr, sym, act, '', 'r', str(px), str(vol), '', '', '', oid, stat, ''])


F, D, DR = trader.ST_FILLED, trader.ST_DRY, 'پر شد'
# س۱: دو پای DASH — خروج اول = پای۱، خروج دوم = پای۲ (غبار پای۱ به دومی می‌رود)
ledA = {'rows': [R(10, 'DASH', 'خرید', 55.0960, 0.045375, 'B1', F),
                 R(11, 'DASH', 'خرید', 54.8205, 0.045603, 'B2', F),
                 R(12, 'DASH', 'فروش', 55.5408, 0.045355, 'S1', F),
                 R(13, 'DASH', 'فروش', 55.2586, 0.045614, 'S2', F)]}
v1 = trader._leg_fifo_entry(None, ledA, 'DASH', 12, 0.045355)
assert v1 and abs(v1[0] - 55.0960) < 0.01, v1
v2 = trader._leg_fifo_entry(None, ledA, 'DASH', 13, 0.045614)
assert v2 and abs(v2[0] - 54.8205) < 0.02, v2
print('  OK س۱ دوپای: %.4f / %.4f (کد فعلی برای هر دو 54.9579 می‌داد)' % (v1[0], v2[0]))
# س۲: OCO ترکیبی — VWAP دو پای (رفتار صحیح فعلی حفظ می‌شود)
ledB = {'rows': [R(10, 'DASH', 'خرید', 55.0960, 0.045375, 'B1', F),
                 R(11, 'DASH', 'خرید', 54.8205, 0.045603, 'B2', F),
                 R(12, 'DASH', 'فروش', 55.0, 0.090978, 'S9', F)]}
v3 = trader._leg_fifo_entry(None, ledB, 'DASH', 12, 0.090978)
exp = (55.0960 * 0.045375 + 54.8205 * 0.045603) / 0.090978
assert v3 and abs(v3[0] - exp) < 0.01, (v3, exp)
print('  OK س۲ ترکیبی: %.4f ≈ %.4f' % (v3[0], exp))
# س۳: بازگشایی پس از بستن کامل — فقط پای جدید
ledC = {'rows': [R(10, 'X', 'خرید', 100, 5, 'B1', F), R(11, 'X', 'فروش', 105, 5, 'S1', F),
                 R(12, 'X', 'خرید', 110, 5, 'B2', F), R(13, 'X', 'فروش', 115, 5, 'S2', F)]}
v4 = trader._leg_fifo_entry(None, ledC, 'X', 13, 5)
assert v4 and abs(v4[0] - 110) < 1e-9
# س۴: خروج جزئی + خرید اضافه + خروج کل
ledD = {'rows': [R(10, 'Y', 'خرید', 100, 10, 'B1', F), R(11, 'Y', 'فروش', 104, 4, 'S1', F),
                 R(12, 'Y', 'خرید', 110, 6, 'B2', F), R(13, 'Y', 'فروش', 112, 12, 'S2', F)]}
v5 = trader._leg_fifo_entry(None, ledD, 'Y', 13, 12)
assert v5 and abs(v5[0] - 105) < 1e-9
# س۵: ردیف شبیه‌سازی نادیده گرفته می‌شود
ledE = {'rows': [R(10, 'Z', 'خرید', 100, 5, 'B1', F), R(11, 'Z', 'خرید', 90, 5, chr(8212), D),
                 R(12, 'Z', 'فروش', 105, 5, 'S1', F)]}
v6 = trader._leg_fifo_entry(None, ledE, 'Z', 12, 5)
assert v6 and abs(v6[0] - 100) < 1e-9
# س۶: بدون لات (آرشیو/قدیمی) → None → fallback
ledF = {'rows': [R(10, 'W', 'فروش', 105, 5, 'S1', F)]}
assert trader._leg_fifo_entry(None, ledF, 'W', 10, 5) is None
# س۷: گارد پوشش — لات ۱ در برابر خروج ۱۰ → None
ledG = {'rows': [R(10, 'V', 'خرید', 100, 1, 'B1', F), R(11, 'V', 'فروش', 105, 10, 'S1', F)]}
assert trader._leg_fifo_entry(None, ledG, 'V', 11, 10) is None
# س۸: exit_vol=None → مصرف از r[6] سطر خروج
ledH = {'rows': [R(10, 'T', 'خرید', 100, 5, 'B1', F), R(11, 'T', 'فروش', 105, 5, 'S1', F)]}
v8 = trader._leg_fifo_entry(None, ledH, 'T', 11, None)
assert v8 and abs(v8[0] - 100) < 1e-9
print('  OK س۳-س۸: بازگشایی / جزئی+اضافه / شبیه‌سازی / بدون لات / گارد پوشش / fallback حجم')

print('\n== 5) اسموک زنده روی دفتر واقعی (مبنای ستون‌ها، بدون API) ==')
env = {}
for line in open(os.path.join(BASE, '.env'), encoding='utf-8'):
    line = line.strip()
    if '=' in line and not line.startswith('#'):
        k, _, v = line.partition('=')
        env[k] = v
import gspread
sh = gspread.service_account(filename=os.path.join(BASE, 'service_account.json')).open_by_key(env['SHEET_ID'])
so = sh.worksheet('سفارشات').get_all_values()
led = {'rows': [(i + 4, list(r) + [''] * (13 - len(r)))
                for i, r in enumerate(so[3:]) if any(str(c).strip() for c in r)]}
cl = sh.worksheet('اتمام معاملات').get_all_values()
closed = {}
for r in cl:
    if len(r) > 8 and str(r[1]).strip():
        closed.setdefault(str(r[1]).strip(), []).append(r)
for sym in ('DASH', 'ENA'):
    print('== %s:' % sym)
    xs = [(rn, rr) for rn, rr in led['rows']
          if rr[1].strip().upper() == sym and rr[2].strip() == 'فروش'
          and (rr[11].strip() if len(rr) > 11 else '') in trader.EXECUTED]
    for rn, rr in xs[-4:]:
        vol = trader.parse_price(rr[6]) or 0.0
        v = trader._leg_fifo_entry(None, led, sym, rn, vol)
        print('  row%-4d %s | vol=%s | ورود FIFO: %s' % (
            rn, str(rr[0]).strip(), str(rr[6]).strip()[:10],
            ('%.6g' % v[0]) if v else 'None → fallback'))
    for r in closed.get(sym, [])[-3:]:
        print('  ثبت‌شده فعلی: %s | ورود %s | خروج %s | %s%% | %s' % (
            str(r[0]).strip()[:16], str(r[3]).strip()[:10], str(r[4]).strip()[:10],
            str(r[7]).strip(), str(r[8]).strip()[:24]))

print('\n✅ پچ کامل شد — تیک بعدی cron کد جدید را برمی‌دارد.')
print('   دیده‌بان: خط «G-legfifo …» در اولین بستن واقعی بعدی (تأخیر/فرق با VWAP چرخه).')
