# -*- coding: utf-8 -*-
"""G-legfifo v2: صف FIFO از مرز چرخه (آخرین فروش اجراشدهٔ پیش از خروج).
مبنا: r89 — دامپ دفتر نشان داد صفِ سراسریِ v1 حباب کاغذی بین‌چرخه‌ای دارد:
باقی‌مانده‌های (ناخالصِ ثبت‌شده در برابر خالصِ فروخته‌شده + پرشدن جزئیِ
نامرئی) از چرخه‌های کهنه جلوِ صف می‌مانند و به ورودیِ خروج‌های تازه
می‌خورند. شاهد زنده: خروج NEAR 07:06 — جلوی صف 0.035461 @ 4.6885 (بقایای
کاغذی لات چرخهٔ 09:26) + 0.493506 @ fill 4.7229 → 4.72158؛ در حالی‌که
اتحاد OCO-net (0.528967 = خالصِ لات 11:38 دقیق) ثابت می‌کند کیف پس از خروج
قبل صفر بود → ورود واقعی ≈ 4.723. ZEC هم همین با 2٪. v2 مرز صف را هم‌مرزِ
G-fix-cycle در _entry_fill می‌گذارد → حباب بین‌چرخه‌ای صفر؛ الگوی DASH
(خروج→خرید→خروج) و چندپایگیِ درون‌چرخه حفظ؛ خروجِ بدون لات پس از مرز →
None → fallback به _entry_fill."""
import os
import sys

BASE = os.path.expanduser('~/nobitex-usdt')
sys.path.insert(0, BASE)
T = os.path.join(BASE, 'trader.py')
FAILED = []


def load(fn):
    with open(fn, encoding='utf-8') as f:
        return f.read()


def save_atomic(fn, src):
    tmp = fn + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(src)
    os.replace(tmp, fn)


def rep(src, old, new, what):
    n = src.count(old)
    if n != 1:
        FAILED.append('%s: انتظار ۱ مطابقت، پیدا شد %d' % (what, n))
        return src
    print('  OK %s' % what)
    return src.replace(old, new)


print('== 1) ویرایش trader.py ==')
t = load(T)
if t.count('def _leg_fifo_entry') != 1:
    print('❌ تابع _leg_fifo_entry یافت نشد/تکراری'); sys.exit(1)
seg = t.split('def _leg_fifo_entry', 1)[1].split('\ndef ', 1)[0]

for marker, name in [
    ('لات‌های خرید اجراشده (غیرشبیه‌سازی) به ترتیب دفتر push و هر فروش اجراشدهٔ',
     'جملهٔ صف سراسری در docstring'),
    ('lot_rows = []   # [oid, qty, px]',
     'آغاز بدنهٔ صف'),
]:
    if seg.count(marker) != 1:
        FAILED.append('pre-flight %s: %d مورد' % (name, seg.count(marker)))
if FAILED:
    print('\n'.join('  ❌ ' + f for f in FAILED)); sys.exit(1)

t = rep(t,
    """    لات‌های خرید اجراشده (غیرشبیه‌سازی) به ترتیب دفتر push و هر فروش اجراشدهٔ
    قبلی از جلو صف مصرف می‌کند؛ سطر خروج (exit_row_num) خودش exit_vol را مصرف
    می‌کند و خروجی = VWAP لات‌های مصرف‌شده در همین نوبت. قیمت/کارمزد لات از""",
    """    v2 (r90): صف فقط از مرز چرخه بازسازی می‌شود — آخرین فروش اجراشدهٔ پیش از
    سطر خروج (هم‌مرزِ G-fix-cycle در _entry_fill). ریشهٔ v2: صفِ سراسری حبابِ
    کاغذی بین‌چرخه‌ای می‌ساخت — بقایای ناخالصِ ثبت در برابر خالصِ فروخته +
    پرشدن جزئیِ نامرئی، جلوِ صف می‌ماندند (شاهد NEAR: ~0.035 @ 4.6885 از
    چرخهٔ 09:26 = 6.7٪ وزنِ خروج 07:06 → 4.72158 به‌جای ~4.723). لات‌های خرید
    اجراشده (غیرشبیه‌سازی) پس از مرز به ترتیب دفتر push و سطر خروج
    (exit_row_num) خودش exit_vol را مصرف می‌کند و خروجی = VWAP لات‌های
    مصرف‌شده در همین نوبت. خروجِ دومی پس از خریدِ جدید به لات‌های بعد از
    خروجِ اول منتسب می‌شود (شاهد DASH: 55.096 / 54.82)؛ خروجِ بدون لات پس از
    مرز → None → fallback به _entry_fill. قیمت/کارمزد لات از""",
    'docstring v2')

t = rep(t,
    """        lot_rows = []   # [oid, qty, px]
        consumed = []   # (oid, take, px) — فقط نوبت سطر خروج
        for rn, rr in (led.get('rows') or []):
            if rn > exit_row_num:
                break""",
    """        lot_rows = []   # [oid, qty, px]
        consumed = []   # (oid, take, px) — فقط نوبت سطر خروج
        # G-legfifo v2: مرز صف = آخرین فروش اجراشدهٔ پیش از سطر خروج (هم‌مرزِ
        # G-fix-cycle در _entry_fill) — صفِ سراسری حبابِ بین‌چرخه‌ای می‌ساخت
        # (شاهد NEAR: ~0.035 @ 4.6885 از چرخهٔ 09:26 = 6.7٪ وزنِ خروج 07:06).
        cycle_start = 0
        for _rn, _rr in (led.get('rows') or []):
            if _rn >= exit_row_num:
                break
            if _rr[1].strip().upper() != sym:
                continue
            _rs = _rr[11].strip() if len(_rr) > 11 else ''
            if _rs in EXECUTED and _rs != ST_DRY and _rr[2].strip() == 'فروش':
                cycle_start = _rn
        for rn, rr in (led.get('rows') or []):
            if rn > exit_row_num:
                break
            if rn <= cycle_start:
                continue""",
    'صف از مرز چرخه (cycle_start)')

if FAILED:
    print('\n'.join('  ❌ ' + f for f in FAILED)); sys.exit(1)

print('== 2) کامپایل پیش از نوشتن ==')
try:
    compile(t, T, 'exec')
    print('  OK compile trader.py')
except SyntaxError as e:
    print('  ❌ کامپایل: %s' % e); sys.exit(1)

print('== 3) نوشتن اتمیک ==')
save_atomic(T, t)
print('  OK trader.py')

print('== 4) تست واحد — ۱۱ سناریو ==')
import trader
F = trader.ST_FILLED
C = trader.ST_CANCELLED
DRY = trader.ST_DRY
P = trader.ST_PARTIAL


def R(rn, sym, act, px, vol, oid, stat):
    r = [''] * 13
    r[0] = '1405/08/06 12:00'; r[1] = sym; r[2] = act
    r[5] = str(px); r[6] = str(vol); r[10] = oid; r[11] = stat
    return (rn, r)


ledA = {'rows': [R(10, 'A', 'خرید', 10, 100, 'B1', F), R(11, 'A', 'فروش', 12, 100, 'S1', F)]}
v = trader._leg_fifo_entry(None, ledA, 'A', 11, 100)
assert v and abs(v[0] - 10) < 1e-9
print('  OK س۱ تک‌لات: 10')

ledB = {'rows': [R(10, 'B', 'خرید', 55.096, 0.045375, 'B1', F),
                 R(11, 'B', 'خرید', 54.820, 0.045614, 'B2', F),
                 R(12, 'B', 'فروش', 54.43, 0.045355, 'S1', F)]}
v = trader._leg_fifo_entry(None, ledB, 'B', 12, 0.045355)
assert v and abs(v[0] - 55.096) < 1e-9
print('  OK س۲ دوپای هم‌چرخه: 55.096 (فقط لات اول)')

ledC = {'rows': [R(10, 'C', 'خرید', 55.096, 0.045375, 'B1', F),
                 R(11, 'C', 'فروش', 54.43, 0.045355, 'S1', F),
                 R(12, 'C', 'خرید', 54.820, 0.045614, 'B2', F),
                 R(13, 'C', 'فروش', 55.26, 0.045603, 'S2', F)]}
va = trader._leg_fifo_entry(None, ledC, 'C', 11, 0.045355)
vb = trader._leg_fifo_entry(None, ledC, 'C', 13, 0.045603)
assert va and abs(va[0] - 55.096) < 1e-9 and vb and abs(vb[0] - 54.820) < 1e-9
print('  OK س۳ الگوی DASH دو چرخه: 55.096 / 54.820')

ledD = {'rows': [R(10, 'D', 'خرید', 10, 105, 'B1', F),
                 R(11, 'D', 'فروش', 12, 100, 'S1', F),
                 R(12, 'D', 'خرید', 20, 100, 'B2', F),
                 R(13, 'D', 'فروش', 21, 100, 'S2', F)]}
v = trader._leg_fifo_entry(None, ledD, 'D', 13, 100)
assert v and abs(v[0] - 20) < 1e-9, v
print('  OK س۴ ضدحباب (تیتر v2): 20 — v1 می‌داد 19.5 (5@10 + 95@20)')

ledE = {'rows': [R(10, 'E', 'خرید', 10, 100, 'B1', F),
                 R(11, 'E', 'فروش', 12, 40, 'S1', F),
                 R(12, 'E', 'فروش', 11, 60, 'S2', F)]}
assert trader._leg_fifo_entry(None, ledE, 'E', 12, 60) is None
print('  OK س۵ خروج بقایا: None → fallback به _entry_fill')

ledF = {'rows': [R(10, 'F', 'خرید', 10, 100, 'B1', F),
                 R(11, 'F', 'خرید', 9, 100, 'B2', C),
                 R(12, 'F', 'فروش', 12, 100, 'S1', F)]}
v = trader._leg_fifo_entry(None, ledF, 'F', 12, 100)
assert v and abs(v[0] - 10) < 1e-9
print('  OK س۶ پایهٔ لغوشده (الگوی row1101): 10')

ledG = {'rows': [R(10, 'G', 'خرید', 10, 100, 'B1', DRY),
                 R(11, 'G', 'خرید', 20, 100, 'B2', F),
                 R(12, 'G', 'فروش', 22, 100, 'S1', F)]}
v = trader._leg_fifo_entry(None, ledG, 'G', 12, 100)
assert v and abs(v[0] - 20) < 1e-9
print('  OK س۷ ردیف شبیه‌سازی: 20')

ledH = {'rows': [R(10, 'H', 'خرید', 100, 1, 'B1', F), R(11, 'H', 'فروش', 105, 10, 'S1', F)]}
assert trader._leg_fifo_entry(None, ledH, 'H', 11, 10) is None
print('  OK س۸ گارد پوشش ۵۰٪: None')

ledI = {'rows': [R(10, 'I', 'خرید', 100, 5, 'B1', F), R(11, 'I', 'فروش', 105, 5, 'S1', F)]}
v = trader._leg_fifo_entry(None, ledI, 'I', 11, None)
assert v and abs(v[0] - 100) < 1e-9
print('  OK س۹ بدون exit_vol: 100')

ledJ = {'rows': [R(10, 'J', 'خرید', 10, 100, 'B1', F),
                 R(11, 'J', 'فروش', 12, 30, 'S1', P),
                 R(12, 'J', 'خرید', 20, 30, 'B2', F),
                 R(13, 'J', 'فروش', 21, 30, 'S2', F)]}
v = trader._leg_fifo_entry(None, ledJ, 'J', 13, 30)
assert v and abs(v[0] - 20) < 1e-9, v
print('  OK س۱۰ مرزِ فروشِ ST_PARTIAL: 20')

ledK = {'rows': [R(10, 'K', 'خرید', 10, 50, 'B1', F),
                 R(11, 'K', 'خرید', 12, 50, 'B2', F),
                 R(12, 'K', 'فروش', 13, 100, 'S1', F)]}
v = trader._leg_fifo_entry(None, ledK, 'K', 12, 100)
assert v and abs(v[0] - 11) < 1e-9
print('  OK س۱۱ تجمیع بدون مرز (اولین خروج نماد): 11')

print('== 5) اسموک زنده (مبنای ستون‌ها، بدون API) ==')
env = {}
for line in open(os.path.join(BASE, '.env'), encoding='utf-8'):
    line = line.strip()
    if '=' in line and not line.startswith('#'):
        k, _, val = line.partition('=')
        env[k] = val
import gspread
sh = gspread.service_account(filename=os.path.join(BASE, 'service_account.json')).open_by_key(env['SHEET_ID'])
so = sh.worksheet('سفارشات').get_all_values()
led = {'rows': [(i + 4, list(r) + [''] * (13 - len(r)))
                for i, r in enumerate(so[3:]) if any(str(c).strip() for c in r)]}
for sym, note in [('NEAR', 'انتظار: row1098→4.6885 و row1102→4.7241 (v1: 4.6601/4.72171 — حباب حذف شد)'),
                  ('ZEC', 'انتظار: row1083→1295.87 و row1091→~1314.9 (v1: 1314.62)'),
                  ('DASH', 'انتظار: بدون تغییر نسبت به r84 (55.096 / 54.82) — رگرسیون'),
                  ('ENA', 'مشاهده: اگر فرق کرد، حباب ENA هم کشف شد')]:
    print('== %s | %s' % (sym, note))
    xs = [(rn, rr) for rn, rr in led['rows']
          if rr[1].strip().upper() == sym and rr[2].strip() == 'فروش'
          and (rr[11].strip() if len(rr) > 11 else '') in trader.EXECUTED]
    for rn, rr in xs[-3:]:
        vol = trader.parse_price(rr[6]) or 0.0
        v = trader._leg_fifo_entry(None, led, sym, rn, vol)
        print('  row%-5d %s | vol=%-10s | ورود FIFO v2: %s' % (
            rn, str(rr[0]).strip()[:16], str(rr[6]).strip()[:10],
            ('%.6g' % v[0]) if v else 'None → fallback'))

print('\n✅ پچ v2 کامل شد — تیک بعدی cron کد جدید را برمی‌دارد.')
print('   دیده‌بان: اولین خط «G-legfifo …» پس از این پچ باید برای چرخهٔ تک‌لات ≈ VWAP چرخه باشد.')
