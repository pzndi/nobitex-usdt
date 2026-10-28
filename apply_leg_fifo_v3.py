# -*- coding: utf-8 -*-
"""G-legfifo v3: مرز صف را «پوششِ مصرف» تعیین می‌کند.
مبنا: r90 — اسموک v2 برای NEAR/ZEC/ENA دقیق بود اما DASH row1052 (خروج
جزئی دوم از یک موقعیت: دو خرید 55.096/54.82 سپس دو فروش) را None→fallback
داد = بازگشت به باگ اصلی ③ (VWAP هر دو پای). ریشه: مرزِ سفتِ v2 (آخرین
فروش اجراشده) خروجِ جزئی را «پایان چرخه» می‌انگارد. v3 مرزهای کاندید
(۰ + هر فروش اجراشدهٔ پیش از خروج) را از نزدیک به دور با حجم قابل‌مصرف
می‌سنجد و اولین مرز پوشش‌دهندهٔ ≥۵۰٪ را برمی‌گزیند. اسموک این‌بار
«ادعایی» است: assert روی ۱۱ ردیف زنده + گارد رگرسیون ویژهٔ row1052."""
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
for marker in ['v2 (r90): صف فقط از مرز چرخه', 'cycle_start = 0']:
    if marker not in seg:
        FAILED.append('pre-flight: %r در تابع فعلی نیست' % marker)
if '_leg_fifo_entry(client, led, sym_c, row_num, vol_c)' not in t:
    FAILED.append('pre-flight: سیم‌کشی 849 یافت نشد')
if FAILED:
    print('\n'.join('  ❌ ' + f for f in FAILED)); sys.exit(1)
print('  OK pre-flight: تابع v2 + سیم‌کندگی موجود')

t = rep(t, """    v2 (r90): صف فقط از مرز چرخه بازسازی می‌شود — آخرین فروش اجراشدهٔ پیش از
    سطر خروج (هم‌مرزِ G-fix-cycle در _entry_fill). ریشهٔ v2: صفِ سراسری حبابِ
    کاغذی بین‌چرخه‌ای می‌ساخت — بقایای ناخالصِ ثبت در برابر خالصِ فروخته +
    پرشدن جزئیِ نامرئی، جلوِ صف می‌ماندند (شاهد NEAR: ~0.035 @ 4.6885 از
    چرخهٔ 09:26 = 6.7٪ وزنِ خروج 07:06 → 4.72158 به‌جای ~4.723). لات‌های خرید
    اجراشده (غیرشبیه‌سازی) پس از مرز به ترتیب دفتر push و سطر خروج
    (exit_row_num) خودش exit_vol را مصرف می‌کند و خروجی = VWAP لات‌های
    مصرف‌شده در همین نوبت. خروجِ دومی پس از خریدِ جدید به لات‌های بعد از
    خروجِ اول منتسب می‌شود (شاهد DASH: 55.096 / 54.82)؛ خروجِ بدون لات پس از
    مرز → None → fallback به _entry_fill. قیمت/کارمزد لات از""",
"""    v3 (r91): مرز صف را «پوششِ مصرف» تعیین می‌کند، نه صرفاً آخرین فروشِ
    اجراشده. مرزهای کاندید = ۰ (ابتدای دفتر) + هر فروش اجراشدهٔ پیش از سطر
    خروج؛ از نزدیک‌ترین مرز با «حجم قابل‌مصرف لات‌های پس از مرز (منهای
    فروش‌های میانی)» آزموده می‌شوند و اولین مرزی که ≥۵۰٪ حجم خروج را
    بپوشاند انتخاب می‌شود؛ بدون پوشش → None → fallback به _entry_fill.
    ریشهٔ v2→v3: فروشِ اجراشده لزوماً پایان چرخه نیست — خروج جزئی (OCO
    پله‌ای + تور ایمنی؛ شاهد DASH 08/05: دو خرید 55.096/54.82 سپس دو
    فروش) مرز نمی‌سازد و مرزِ سفتِ v2 چنین خروجی را به fallback (VWAP هر
    دو پای = باگ اصلی ③) می‌انداخت؛ از سوی دیگر صفِ سراسریِ v1 حبابِ
    کاغذی بین‌چرخه‌ای انباشته می‌کرد (شاهد NEAR: ~0.035 @ 4.6885 از چرخهٔ
    قبل = 6.7٪ وزن خیانی خروج 07:06). v3 هر دو را حل می‌کند: مرزِ نزدیک
    تا وقتی پوشش می‌دهد (حباب کهنه بیرون می‌ماند) و خروج جزئی با
    عقب‌رفتنِ یک پله و بازپخشِ فروش میانی، لات‌های درست را پیدا می‌کند
    (شاهد DASH: 55.096 / 54.82). لات‌های خرید اجراشده (غیرشبیه‌سازی) پس از
    مرز به ترتیب دفتر push و سطر خروج (exit_row_num) خودش exit_vol را مصرف
    می‌کند و خروجی = VWAP لات‌های مصرف‌شده در همین نوبت؛ خروجِ بدون لات پس
    از مرز → None → fallback به _entry_fill. قیمت/کارمزد لات از""",
'docstring v3')

t = rep(t, """        # G-legfifo v2: مرز صف = آخرین فروش اجراشدهٔ پیش از سطر خروج (هم‌مرزِ
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
                cycle_start = _rn""",
"""        # G-legfifo v3 (r91): مرز را «پوششِ مصرف» تعیین می‌کند، نه صرفاً
        # آخرین فروش اجراشده. ریشه: فروشِ اجراشده لزوماً پایان چرخه نیست —
        # خروج جزئی (OCO پله‌ای + تور ایمنی؛ شاهد DASH 08/05: دو خرید
        # 55.096/54.82 سپس دو فروش) مرز نمی‌سازد و مرزِ سفتِ v2 چنین
        # خروجی را به fallback (VWAP هر دو پای = باگ اصلی ③) می‌انداخت؛
        # از سوی دیگر صفِ سراسریِ v1 حبابِ کاغذی بین‌چرخه‌ای انباشته
        # می‌کرد (شاهد NEAR: 0.035 @ 4.6885 = 6.7٪ وزن خیالی). راه v3:
        # مرزهای کاندید (۰ + هر فروش اجراشدهٔ پیش از خروج) از نزدیک به
        # دور با «حجمِ قابل‌مصرف لات‌های پس از مرز، منهای فروش‌های میانی»
        # آزموده می‌شوند؛ اولین مرز با پوشش ≥۵۰٪ انتخاب می‌شود — حباب
        # کهنه بیرون می‌ماند و خروج جزئی با عقب‌رفتنِ یک پله لات‌های
        # درست را پیدا می‌کند.
        _sym_rows = [(rn, rr) for rn, rr in (led.get('rows') or [])
                     if rr[1].strip().upper() == sym]
        _bounds = [0]   # ۰ = از ابتدای دفتر (آخرین پوشش ممکن)
        for _rn, _rr in _sym_rows:
            if _rn >= exit_row_num:
                break
            _rs = _rr[11].strip() if len(_rr) > 11 else ''
            if _rs in EXECUTED and _rs != ST_DRY and _rr[2].strip() == 'فروش':
                _bounds.append(_rn)
        _need = float(exit_vol) if exit_vol else None

        def _cover(_b):
            # حجم قابل‌مصرفِ سطر خروج از لات‌های پس از مرز _b (بازپخش میانی)
            _avail = 0.0
            for _rn2, _rr2 in _sym_rows:
                if _rn2 > exit_row_num:
                    break
                if _rn2 <= _b:
                    continue
                _rs2 = _rr2[11].strip() if len(_rr2) > 11 else ''
                if _rs2 not in EXECUTED or _rs2 == ST_DRY:
                    continue
                _rt = _rr2[2].strip()
                if _rt == 'خرید':
                    _avail += parse_price(_rr2[6]) or 0.0
                elif _rt == 'فروش':
                    if _rn2 == exit_row_num:
                        break
                    _avail = max(0.0, _avail - (parse_price(_rr2[6]) or 0.0))
            return min(_avail, _need) if _need is not None else _avail

        cycle_start = 0
        for _b in reversed(_bounds):
            _c = _cover(_b)
            if _c > 0 and (_need is None or _c >= 0.5 * _need):
                cycle_start = _b
                break""",
'مرز با پوشش مصرف (v3)')

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

print('== 4) تست واحد — ۱۴ سناریو ==')
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
print('  OK س۳ دو چرخهٔ پیاپی: 55.096 / 54.820')

ledD = {'rows': [R(10, 'D', 'خرید', 10, 105, 'B1', F),
                 R(11, 'D', 'فروش', 12, 100, 'S1', F),
                 R(12, 'D', 'خرید', 20, 100, 'B2', F),
                 R(13, 'D', 'فروش', 21, 100, 'S2', F)]}
v = trader._leg_fifo_entry(None, ledD, 'D', 13, 100)
assert v and abs(v[0] - 20) < 1e-9, v
print('  OK س۴ ضدحباب: 20 — حباب 5@10 بیرون می‌ماند')

ledE = {'rows': [R(10, 'E', 'خرید', 10, 100, 'B1', F),
                 R(11, 'E', 'فروش', 12, 40, 'S1', F),
                 R(12, 'E', 'فروش', 11, 60, 'S2', F)]}
v = trader._leg_fifo_entry(None, ledE, 'E', 12, 60)
assert v and abs(v[0] - 10) < 1e-9, v
print('  OK س۵ خروج جزئی دوم (به‌روزشده v3): 10 — v2: None→fallback')

ledF = {'rows': [R(10, 'F', 'خرید', 10, 100, 'B1', F),
                 R(11, 'F', 'خرید', 9, 100, 'B2', C),
                 R(12, 'F', 'فروش', 12, 100, 'S1', F)]}
v = trader._leg_fifo_entry(None, ledF, 'F', 12, 100)
assert v and abs(v[0] - 10) < 1e-9
print('  OK س۶ پایهٔ لغوشده: 10')

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
print('  OK س۱۱ تجمیع بدون مرز: 11')

ledL = {'rows': [R(10, 'L', 'خرید', 55.096, 0.045375, 'B1', F),
                 R(11, 'L', 'خرید', 54.8206, 0.045603, 'B2', F),
                 R(12, 'L', 'فروش', 54.43, 0.045355, 'S1', F),
                 R(13, 'L', 'فروش', 55.26, 0.045614, 'S2', F)]}
v = trader._leg_fifo_entry(None, ledL, 'L', 13, 0.045614)
exp = (0.000020 * 55.096 + 0.045594 * 54.8206) / 0.045614
assert v and abs(v[0] - exp) < 1e-9, (v, exp)
print('  OK س۱۲ الگوی واقعی DASH (دو خرید سپس دو فروش): %.4f — رگرسیون v2 رفع شد' % exp)

ledM = {'rows': [R(10, 'M', 'خرید', 10, 105, 'B1', F),
                 R(11, 'M', 'فروش', 12, 100, 'S1', F),
                 R(12, 'M', 'خرید', 20, 100, 'B2', F),
                 R(13, 'M', 'خرید', 21, 100, 'B3', F),
                 R(14, 'M', 'فروش', 22, 150, 'S2', F)]}
v = trader._leg_fifo_entry(None, ledM, 'M', 14, 150)
exp = (100 * 20 + 50 * 21) / 150.0
assert v and abs(v[0] - exp) < 1e-9, (v, exp)
print('  OK س۱۳ توقف در اولین مرز پوشش‌دهنده: %.4f — v1 می‌داد 19.967' % exp)

ledN = {'rows': [R(10, 'N', 'فروش', 10, 50, 'S1', F)]}
assert trader._leg_fifo_entry(None, ledN, 'N', 10, 50) is None
print('  OK س۱۴ بدون لات: None → fallback')

print('== 5) اسموک زندهٔ ادعایی (assert) — مبنای ستون‌ها، بدون API ==')
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
sells = {}
for rn, rr in led['rows']:
    if rr[2].strip() == 'فروش' and (rr[11].strip() if len(rr) > 11 else '') in trader.EXECUTED:
        sells[(rr[1].strip().upper(), rn)] = rr
EXPECT = [
    ('NEAR', 1093, 4.64813, 0.002),
    ('NEAR', 1098, 4.6885, 0.002),
    ('NEAR', 1102, 4.7241, 0.002),
    ('ZEC', 1053, 1296.87, 0.05),
    ('ZEC', 1083, 1295.87, 0.05),
    ('ZEC', 1091, 1314.93, 0.05),
    ('DASH', 1048, 55.096, 0.002),
    ('DASH', 1099, 54.924, 0.002),
    ('ENA', 1033, 0.212731, 0.0005),
    ('ENA', 1067, 0.211206, 0.0005),
    ('ENA', 1106, 0.210143, 0.0005),
]
SMOKE_FAIL = []
for sym, rn, exp, tol in EXPECT:
    rr = sells.get((sym, rn))
    if rr is None:
        SMOKE_FAIL.append('%s row%d در دفتر نیست' % (sym, rn))
        continue
    vol = trader.parse_price(rr[6]) or 0.0
    v = trader._leg_fifo_entry(None, led, sym, rn, vol)
    if v is None:
        SMOKE_FAIL.append('%s row%d: None (انتظار %.6g)' % (sym, rn, exp))
    elif abs(v[0] - exp) > tol:
        SMOKE_FAIL.append('%s row%d: %.6g خارج از %.6g±%g' % (sym, rn, v[0], exp, tol))
    else:
        print('  OK %s row%d → %.6g (انتظار %.6g)' % (sym, rn, v[0], exp))
rr = sells.get(('DASH', 1052))
if rr is None:
    SMOKE_FAIL.append('DASH row1052 در دفتر نیست')
else:
    vol = trader.parse_price(rr[6]) or 0.0
    v = trader._leg_fifo_entry(None, led, 'DASH', 1052, vol)
    if v is None:
        SMOKE_FAIL.append('DASH row1052: None — رگرسیون v2 هنوز هست (انتظار ~54.82)')
    elif not (54.78 < v[0] < 54.86):
        SMOKE_FAIL.append('DASH row1052: %.6g خارج از باند 54.78-54.86 (انتظار ~54.82)' % v[0])
    else:
        print('  OK DASH row1052 → %.6g (خروج جزئی: لات پای۲، نه VWAP دو پای)' % v[0])
if SMOKE_FAIL:
    print('\n'.join('  ❌ ' + f for f in SMOKE_FAIL))
    sys.exit(1)

print('\n✅ پچ v3 کامل شد — تیک بعدی cron کد جدید را برمی‌دارد.')
print('   دیده‌بان: خط «G-legfifo …» در بستن‌های بعدی؛ تک‌لات باید ≈ VWAP چرخه باشد.')
