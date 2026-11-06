#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""week_meter.py — متر هفتهٔ مشاهدهٔ «گزینهٔ ب» (فقط خواندن؛ هر زمان قابل اجرا)
پنجره: معاملاتی که «زمان ورود» ≥ 1405/08/02 19:50 (تهران) = بعد از فرود اهرم‌ها.
معیارهای ازپیش‌ثبت‌شده (درصدی — با هر ORDER_SIZE یکسان):
    payoff ≥ 1.0 | avgW ≥ +1.8٪ | EV ≥ −0.6٪ | معاملهٔ میم = 0
    (معادل دلاری در سایز 5$: avgW ≥ +0.09$ | EV ≥ −0.03$)
اجرا:  venv/bin/python week_meter.py
"""
import os, re, subprocess, sys
from collections import defaultdict

os.chdir(os.path.expanduser('~/nobitex-usdt')); sys.path.insert(0, os.getcwd())
import gspread
from settings import load_env

LANDING_ENTRY = '1405/08/02 19:50'
D0, T0 = '2026-10-24', '12:25'          # لحظهٔ فرود در لاگ (EDT)
MEMES = {'USOON', '1M_PEPE', 'MEW'}
FA = str.maketrans('۰۱۲۳۴۵۶۷۸۹٫', '0123456789.')
DATE_RE = re.compile(r'^14\d{2}/\d{2}/\d{2}')

def norm(x): return str(x or '').strip().translate(FA)
def fnum(x):
    try: return float(str(x).replace(',', '').translate(FA))
    except Exception: return None

sh = gspread.service_account(filename='service_account.json').open_by_key(load_env().get('SHEET_ID'))

# ---------- ۱) معاملات بسته (طبقه‌بندی بر مبنای زمانِ ورود) ----------
post, border = [], []
for r in sh.worksheet('اتمام معاملات').get_values(value_render_option='UNFORMATTED_VALUE'):
    if len(r) < 8: continue
    ex_dt, sym, en_dt = norm(r[0]), norm(r[1]).upper(), norm(r[2])
    if not DATE_RE.match(ex_dt): continue
    if DATE_RE.match(en_dt) and en_dt >= LANDING_ENTRY:
        post.append((ex_dt, sym, r))
    elif ex_dt >= '1405/08/02':
        g = fnum(r[6]); border.append((ex_dt, sym, g if g is not None else 0.0))

trades = []
for ex_dt, sym, r in post:
    g = fnum(r[6]) or 0.0
    d, v = fnum(r[3]), fnum(r[5])
    notional = d * v if (d and v) else None
    pct_net = (g / notional * 100.0) if notional else None
    trades.append({'sym': sym, 'g': g, 'pct': pct_net, 'day': ex_dt[:10]})

n      = len(trades)
wins   = [t for t in trades if t['g'] > 0]
losses = [t for t in trades if t['g'] < 0]
tot    = sum(t['g'] for t in trades)
avgW = sum(t['g'] for t in wins)   / len(wins)   if wins   else 0.0
avgL = sum(t['g'] for t in losses) / len(losses) if losses else 0.0
payoff = (avgW / abs(avgL)) if avgL < 0 else (float('inf') if avgW > 0 else 0.0)
_w = [t['pct'] for t in wins   if t['pct'] is not None] or [0.0]
_l = [t['pct'] for t in losses if t['pct'] is not None] or [0.0]
avgWp, avgLp = sum(_w)/len(_w), sum(_l)/len(_l)
_p = [t['pct'] for t in trades if t['pct'] is not None]
evp = sum(_p)/len(_p) if _p else 0.0
meme_n = sum(1 for t in trades if t['sym'] in MEMES)

print('۱) پنجرهٔ گزینهٔ ب (ورود ≥ %s) — تا این لحظه' % LANDING_ENTRY)
print('   n=%d | برد=%d | باخت=%d | WR=%s' %
      (n, len(wins), len(losses), ('%.0f٪' % (100.0*len(wins)/n)) if n else '—'))
if n:
    print('   جمع=%+.2f$ | EV=%+.3f$/معامله (%+.2f٪) | avgW=%+.3f$ (%+.2f٪) | avgL=%+.3f$ (%+.2f٪) | payoff=%.2f'
          % (tot, tot/n, evp, avgW, avgWp, avgL, avgLp, payoff))
    dd = defaultdict(lambda: [0, 0.0])
    for t in trades:
        dd[t['day']][0] += 1; dd[t['day']][1] += t['g']
    for d in sorted(dd):
        print('     %s: n=%d  Σ=%+.2f$' % (d, dd[d][0], dd[d][1]))
print('   معاملهٔ میم در پنجره: %d %s' % (meme_n, '✓ (باید 0 بماند)' if meme_n == 0 else '🚨'))
if border:
    print('   • مرزی (ورود قبل از فرود، خروج بعد از 08/02): %d ردیف، Σ=%+.2f$ — خارج از آمارِ حکم'
          % (len(border), sum(b[2] for b in border)))

print('\n۲) معیارهای ازپیش‌ثبت‌شده (حکمِ نهایی فقط با n≥20):')
if n:
    for name, ok, val in [
        ('payoff ≥ 1.0',  payoff >= 1.0, 'payoff=%.2f' % payoff),
        ('avgW ≥ +1.8٪',  avgWp  >= 1.8, 'avgW=%+.2f٪' % avgWp),
        ('EV ≥ −0.6٪',    evp    >= -0.6,'EV=%+.2f٪'   % evp),
        ('میم = 0',       meme_n == 0,   'میم=%d'      % meme_n)]:
        print('   %s %s (%s)' % ('✓' if ok else '…', name, val))
if n < 20:
    print('   ⏳ n=%d < 20 — پنجره تا n≥20 تمدید می‌شود (رژیم خرسی ممکن است ورودها را کم کند).' % n)

print('\n۳) رفتار ربات از لحظهٔ فرود (%s %s EDT) — از update.log:' % (D0, T0))
def since(pat):
    g = subprocess.run(['grep', '-a', pat, 'update.log'], capture_output=True, text=True)
    a = subprocess.run(['awk', '-v', 'd0=' + D0, '-v', 't0=' + T0,
                        '($1 > d0) || ($1 == d0 && substr($2,1,5) >= t0)'],
                       input=g.stdout, capture_output=True, text=True)
    return [l for l in a.stdout.splitlines() if l.strip()]
for label, pat in [('تریلینگ فعال→ضرر (بیماری)', 'تریلینگ فعال شد ولی ضرر کرد'),
                   ('تریلینگ موفق',             'تریلینگ موفق'),
                   ('کلمپ G4',                  'کلمپ شد'),
                   ('نماد مسدود (BLOCKED)',     'symbol blocked'),
                   ('ردِ ورود — رژیم خرسی',      'market regime bearish'),
                   ('PriceConditionFailed',     'PriceConditionFailed')]:
    ls = since(pat)
    print('   %-26s: %d' % (label, len(ls)))
    for l in ls[-2:]:
        print('        ' + l[:120])
print('   (اگر لاگ بچرخد، شمارش‌ها کفِ پایین‌اند)')

print('\n۴) پابرجایی سلول‌ها (آشکارسازِ بازنویسیِ G-ablock):')
ws = sh.worksheet('تنظیمات')
row_of = {}
for i, k in enumerate(ws.col_values(1), 1):
    ks = str(k).strip()
    if ks and ks not in row_of: row_of[ks] = i
for k in ['TRAIL_ACTIVATION_PCT', 'TRAIL_ATR_MULT', 'TRAIL_DISTANCE_PCT', 'MIN_TFS', 'ORDER_SIZE_USDT']:
    r = row_of.get(k)
    print('   %-22s = %s' % (k, str(ws.cell(r, 2).value) if r else '؟'))
r = row_of.get('BLOCKED_SYMBOLS')
blk = str(ws.cell(r, 2).value).upper() if r else ''
missing = [m for m in MEMES if m not in blk]
print('   BLOCKED_SYMBOLS        = %s' % blk)
print('   ✓ میم‌ها روی بلوک ماندند' if not missing else
      '   🚨 میم‌ها از بلوک خارج شدند: %s → چرخهٔ ۴۸ساعتهٔ G-ablock بازنویسی کرده؛ خبر بده تا کدش را کاویم.' % missing)

print('\n۵) حکم: %s' % ('هنوز زود (n<20) — متر را روزانه اجرا کن.'
                        if n < 20 else 'n≥20 — معیارها را ببین؛ هر سه سبز = گزینهٔ ب کار کرد.'))
