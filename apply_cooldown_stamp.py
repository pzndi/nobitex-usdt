#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""apply_cooldown_stamp.py — G-cool-fix: کول‌داون ورود مجدد از لحظهٔ خروج واقعی — مبنا: r78/r79

ریشه: ردیف فروش OCO در rr[0] زمان «ثبت» سفارش فروش دارد (≈ لحظهٔ ورود)؛ زمان خروج
واقعی فقط در مهر «P&L: … @%Y/%m/%d %H:%M» در rr[12] است (Fix-B). سند: ENA —
rr[0]=1405/08/05 20:35 | خروج @21:25 | ورود مجدد 21:29 → سن rr[0]=54دقیقه > 30 → گارد
رد نشد؛ سن خروج=4دقیقه → باید رد می‌شد. آزمون مرزی r79: چرخش پنجره‌ها روی سن rr[0]
(107) نه مهر @ (78). خواهرِ losing_exits_count از قبل @ را ترجیح می‌دهد — باگ = واگرایی.

اصلاح:
  1) helper مشترک _exit_time_of(rr): مهر @ از rr[12]؛ @ خراب/غیرتاریخ → fallback rr[0]
     (ردیف‌های جبران rr[0]=زمان خروج دارند)؛ هیچ‌کدام → None.
  2) recent_losing_exit: پارس زمان از helper (جایگزین rr[0] خام).
  3) losing_exits_count: هم‌راستا با helper (fallback امن برای @ خراب).
  4) هر دو except بی‌صدا → log.warning (fail-open بلند — درس آزمون r78).

all-or-nothing + کامپایل پیش از نوشتن + نوشتن اتمیک.
تست: led مصنوعی (۷ اسیشن سناریو) + اسموک زندهٔ شیت.
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
if 'def _exit_time_of' in t:
    FAILED.append('helper _exit_time_of از قبل موجود است — تداخل نام')
HELPER = '''def _exit_time_of(rr):
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


'''

t = rep(t, 'def recent_losing_exit(led, sym, minutes):',
        HELPER + 'def recent_losing_exit(led, sym, minutes):',
        'درج helper _exit_time_of')

t = rep(t, """                try:
                    t0 = _jd.datetime.strptime(str(rr[0]).strip(), '%Y/%m/%d %H:%M')
                    g = t0.togregorian()
                    if (now - g).total_seconds() < minutes * 60:
                        return True
                except Exception:
                    continue
""",
        """                # G-cool-fix: شمارش از لحظهٔ خروج واقعی (مهر @ در rr[12])، نه ثبت سفارش فروش
                g = _exit_time_of(rr)
                if g is not None and (now - g).total_seconds() < minutes * 60:
                    return True
""",
        'recent_losing_exit: پارس زمان از مهر خروج')

t = rep(t, """                if g is not None and (now - g).total_seconds() < minutes * 60:
                    return True
    except Exception:
        pass
    return False
""",
        """                if g is not None and (now - g).total_seconds() < minutes * 60:
                    return True
    except Exception:
        log.warning('recent_losing_exit(%s): خطای ساختاری — کول‌داون fail-open', sym, exc_info=True)
    return False
""",
        'recent_losing_exit: fail-open بلند')

t = rep(t, """                t_str = None
                if ' @' in msg:
                    t_str = msg.split(' @')[-1].strip()
                try:
                    t0 = _jd.datetime.strptime(t_str or str(rr[0]).strip(), '%Y/%m/%d %H:%M')
                    if (now - t0.togregorian()).total_seconds() < minutes * 60:
                        n += 1
                except Exception:
                    continue
""",
        """                # G-cool-fix: هم‌راستا با recent_losing_exit — helper مشترک + fallback امن برای @ خراب
                g = _exit_time_of(rr)
                if g is not None and (now - g).total_seconds() < minutes * 60:
                    n += 1
""",
        'losing_exits_count: هم‌راستاسازی با helper')

t = rep(t, """                if g is not None and (now - g).total_seconds() < minutes * 60:
                    n += 1
        return n
    except Exception:
        return 0
""",
        """                if g is not None and (now - g).total_seconds() < minutes * 60:
                    n += 1
        return n
    except Exception:
        log.warning('losing_exits_count(%s): خطای ساختاری — fail-open به 0', sym, exc_info=True)
        return 0
""",
        'losing_exits_count: fail-open بلند')

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

print('\n== 4) تست واحد با led مصنوعی (۷ اسیشن) ==')
sys.path.insert(0, BASE)
import datetime as _dt
import jdatetime as _jd
import trader


def _jal(minutes_ago):
    g = ((_dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(hours=3, minutes=30))
         .replace(tzinfo=None) - _dt.timedelta(minutes=minutes_ago))
    return _jd.datetime.fromgregorian(datetime=g).strftime('%Y/%m/%d %H:%M')


def _row(reg_ago, exit_ago, pnl='-1.00'):
    msg = 'OCO: TP=1 | SL=1'
    if pnl is not None:
        msg += ' | P&L: %s' % pnl
    if exit_ago is not None:
        msg += ' @' + _jal(exit_ago)
    return [_jal(reg_ago), 'TEST', 'فروش', '', 'OCO حد سود/ضرر بومی صرافی',
            '1', '1', '1', '1', '1', '—', 'پر شد', msg]


led1 = {'rows': [(1, _row(60, 5))]}
assert trader.recent_losing_exit(led1, 'TEST', 30), 'س۱: خروج ۵ دقیقه پیش باید بلاک کند'
led2 = {'rows': [(1, _row(60, 45))]}
assert not trader.recent_losing_exit(led2, 'TEST', 30), 'س۲: خروج ۴۵ دقیقه پیش — خارج پنجره'
led3 = {'rows': [(1, _row(10, None))]}
assert trader.recent_losing_exit(led3, 'TEST', 30), 'س۳: بدون @ → fallback rr[0]=۱۰ دقیقه'
led4 = {'rows': [(1, [_jal(40), 'TEST', 'فروش', '', 'OCO حد سود/ضرر بومی صرافی',
                      '1', '1', '1', '1', '1', '—', 'پر شد', 'P&L: -1.00 @خراب'])]}
assert not trader.recent_losing_exit(led4, 'TEST', 30), 'س۴: @ خراب → fallback rr[0]=۴۰'
assert trader.recent_losing_exit(led4, 'TEST', 60), 'س۴ب: پنجره ۶۰ → داخل'
led5 = {'rows': [(1, _row(60, 5)), (2, _row(60, 45)), (3, _row(10, None))]}
n = trader.losing_exits_count(led5, 'TEST', 30)
assert n == 2, 'losing_exits_count باید ۲ باشد (خروج‌های ۵ و ۱۰ دقیقه پیش)، شد %s' % n
assert trader.recent_losing_exit(led1, 'TEST', 0) is False, 'س۶: minutes=0 → False'
print('  OK هر ۷ اسیشن پاس شد (کد قدیمی در س۱ False می‌داد — رفع باگ تأیید شد)')

print('\n== 5) اسموک زنده: آخرین خروج زیان‌ده هر نماد + پنجره تمایز ==')
env = {}
for line in open(os.path.join(BASE, '.env'), encoding='utf-8'):
    line = line.strip()
    if '=' in line and not line.startswith('#'):
        k, _, v = line.partition('=')
        env[k] = v
import gspread
import re as _re
sh = gspread.service_account(filename=os.path.join(BASE, 'service_account.json')).open_by_key(env['SHEET_ID'])
rows = sh.worksheet('سفارشات').get_all_values()
led = {'rows': [(i, r) for i, r in enumerate(rows) if len(r) > 12]}
now_ir = ((_dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(hours=3, minutes=30))
          .replace(tzinfo=None))
for sym in ('ENA', 'DASH', 'ZEC'):
    last = None
    for _, rr in led['rows']:
        if (rr[1].strip().upper() == sym and rr[2].strip() == 'فروش'
                and rr[11].strip() in trader.EXECUTED):
            m = _re.search(r'P&L:\s*([+-]?\d+(?:\.\d+)?)', str(rr[12]))
            if m and float(m.group(1)) < 0:
                last = rr
    if not last:
        print('  %s: خروج زیان‌ده اجراشده نیست' % sym)
        continue
    g0 = _jd.datetime.strptime(str(last[0]).strip(), '%Y/%m/%d %H:%M').togregorian()
    ex = trader._exit_time_of(last)
    a0 = (now_ir - g0).total_seconds() / 60
    ax = (now_ir - ex).total_seconds() / 60 if ex else None
    print('  %s | rr[0] سن=%.0f | مهر@ سن=%s' % (sym, a0, ('%.0f' % ax) if ex else '—'))
    if ex and a0 - ax > 2:
        w = ax + (a0 - ax) / 2
        print('    پنجره تمایز %.0f دقیقه → %s (انتظار: True = شمارش از خروج ✓)'
              % (w, trader.recent_losing_exit(led, sym, w)))
    else:
        print('    اختلاف سن < ۲ دقیقه یا بدون مهر — رفتار fallback معتبر')

print('\n✅ پچ کامل شد — تیک بعدی cron کد جدید را برمی‌دارد.')
print('   دیده‌بان: بلاک «خروج زیان‌ده در …» پس از اولین خروج زیان‌ده کندحالتی بعدی.')
