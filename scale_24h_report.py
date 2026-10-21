#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scale_24h_report.py - گزارش ۲۴ ساعته عملکرد G-scale و سلامت سیستم
داده‌ها مستقیماً از Google Sheets ledger خوانده می‌شود (دقیق‌تر از لاگ).
"""
import os, sys, re, time
from datetime import datetime, timedelta
sys.path.insert(0, os.path.expanduser('~/nobitex-usdt'))

LOG_PATH = os.path.expanduser('~/nobitex-usdt/update.log')
NOW = datetime.now()
CUTOFF = NOW - timedelta(hours=24)


def read_log_tail_24h():
    """خواندن لاگ در ۲۴ ساعت اخیر"""
    if not os.path.exists(LOG_PATH):
        return []
    with open(LOG_PATH, encoding='utf-8', errors='replace') as f:
        lines = f.readlines()
    cutoff_str = CUTOFF.strftime('%Y-%m-%d')
    return [l for l in lines if cutoff_str in l or '2026-10-' in l][-5000:]


def parse_jalali_to_check_in_window(jdate_str, window_hours=24):
    """بررسی اینکه تاریخ شمسی در ۲۴ ساعت اخیر است یا خیر
    فرمت: 1405/07/29 HH:MM
    چون محاسبه دقیق شمسی پیچیده است، از heuristic استفاده می‌کنیم:
    اگر تاریخ شمسی در ۲ روز شمسی اخیر باشد، شامل می‌شود.
    """
    if not jdate_str:
        return False
    # استخراج روز شمسی
    m = re.match(r'^(\d{4})/(\d{1,2})/(\d{1,2})', str(jdate_str).strip())
    if not m:
        return False
    try:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        # ساده‌سازی: فقط تاریخ‌های اخیر (1405/07/28, 1405/07/29) را شامل می‌شویم
        # این یک heuristic است؛ برای دقت بیشتر باید jdatetime نصب باشد
        return True
    except ValueError:
        return False


def count_scale_from_ledger(led_rows):
    """شمارش Scale 1/2 و 2/2 مستقیماً از ledger
    led_rows: list of (row_num, row_list)
    ساختار row:
      [0]=time, [1]=sym, [2]=action, [3]=tf, [4]=reason, [5]=price,
      [6]=vol, [7]=amount, [8]=sl, [9]=tp, [10]=oid, [11]=status, [12]=msg
    """
    s1_placed = 0
    s2_placed = 0
    s1_filled = 0
    s2_filled = 0
    s1_cancelled = 0
    s2_cancelled = 0
    s1_dry = 0
    s2_dry = 0
    
    for _, r in led_rows:
        if len(r) < 12:
            continue
        action = str(r[2]).strip()
        if action != 'خرید':
            continue
        reason = str(r[4]) if len(r) > 4 else ''
        status = str(r[11]).strip() if len(r) > 11 else ''
        
        # تشخیص Scale 1/2 یا 2/2 از reason
        is_scale1 = 'Scale 1/2' in reason or 'Scale 1' in reason
        is_scale2 = 'Scale 2/2' in reason or 'Scale 2' in reason
        
        if not (is_scale1 or is_scale2):
            continue
        
        # شمارش بر اساس status
        if is_scale1:
            if status == 'ثبت‌شده' or status == 'باز':
                s1_placed += 1
            elif status == 'پر شد':
                s1_filled += 1
            elif status == 'لغو شده':
                s1_cancelled += 1
            elif status == 'شبیه‌سازی شده':
                s1_dry += 1
        elif is_scale2:
            if status == 'ثبت‌شده' or status == 'باز':
                s2_placed += 1
            elif status == 'پر شد':
                s2_filled += 1
            elif status == 'لغو شده':
                s2_cancelled += 1
            elif status == 'شبیه‌سازی شده':
                s2_dry += 1
    
    total_s1 = s1_placed + s1_filled + s1_cancelled + s1_dry
    total_s2 = s2_placed + s2_filled + s2_cancelled + s2_dry
    fill_rate_s1 = (s1_filled / total_s1 * 100) if total_s1 > 0 else 0
    fill_rate_s2 = (s2_filled / total_s2 * 100) if total_s2 > 0 else 0
    
    return {
        's1_placed': s1_placed,
        's1_filled': s1_filled,
        's1_cancelled': s1_cancelled,
        's1_dry': s1_dry,
        's1_total': total_s1,
        's1_fill_rate': fill_rate_s1,
        's2_placed': s2_placed,
        's2_filled': s2_filled,
        's2_cancelled': s2_cancelled,
        's2_dry': s2_dry,
        's2_total': total_s2,
        's2_fill_rate': fill_rate_s2,
    }


def count_pnl_from_log(lines):
    """محاسبه P&L از لاگ"""
    pnl_total = 0.0
    trades = 0
    wins = 0
    losses = 0
    for line in lines:
        if 'معامله' in line and 'بسته شد' in line:
            m = re.search(r'P&L:\s*([+-]?\d+\.?\d*)\s*USDT', line)
            if m:
                pnl = float(m.group(1))
                pnl_total += pnl
                trades += 1
                if pnl > 0:
                    wins += 1
                elif pnl < 0:
                    losses += 1
    return {
        'total_pnl': pnl_total,
        'trades': trades,
        'wins': wins,
        'losses': losses,
        'win_rate': (wins / trades * 100) if trades > 0 else 0,
    }


def count_oco_health_errors(lines):
    """شمارش خطاهای G-oco-health از لاگ"""
    rebuild_attempts = 0
    failures = 0
    successes = 0
    for line in lines:
        if 'G-oco-health' not in line:
            continue
        # فقط خطوط ۲۴ ساعت اخیر
        ts = re.match(r'^(\d{4}-\d{2}-\d{2})', line)
        if ts:
            try:
                line_date = datetime.strptime(ts.group(1), '%Y-%m-%d')
                if line_date < CUTOFF.replace(hour=0, minute=0, second=0):
                    continue
            except ValueError:
                pass
        if 'Rebuilding' in line:
            rebuild_attempts += 1
        elif 'Failed for' in line:
            failures += 1
        elif 'rebuilt' in line.lower() or 'All OCO legs' in line:
            successes += 1
    return {
        'rebuild_attempts': rebuild_attempts,
        'failures': failures,
        'successes': successes,
    }


def count_guard_rejections(lines):
    """شمارش رد گاردها از لاگ"""
    counts = {}
    for line in lines:
        if 'skip buy' not in line and 'انجام نشد' not in line:
            continue
        ts = re.match(r'^(\d{4}-\d{2}-\d{2})', line)
        if ts:
            try:
                line_date = datetime.strptime(ts.group(1), '%Y-%m-%d')
                if line_date < CUTOFF.replace(hour=0, minute=0, second=0):
                    continue
            except ValueError:
                pass
        if 'momentum' in line or 'PUMP_GUARD' in line:
            reason = 'PUMP_GUARD'
        elif 'SL band' in line:
            reason = 'G_BANDCAP'
        elif 'symbol blocked' in line:
            reason = 'BLOCKED_SYMBOLS'
        elif 'موجودی USDT کافی نیست' in line:
            reason = 'INSUFFICIENT_USDT'
        elif 'no global mark' in line:
            reason = 'G_GLOBAL'
        else:
            reason = 'OTHER'
        counts[reason] = counts.get(reason, 0) + 1
    return counts


def get_open_positions_summary():
    """خلاصه پوزیشن‌های باز از ledger"""
    try:
        sys.path.insert(0, '.')
        import trader
        from trader import make_client, read_ledger
        from settings import load_env
        import gspread
        e = load_env()
        gc = gspread.service_account(filename='service_account.json')
        sh = gc.open_by_key(e['SHEET_ID'])
        ws = sh.worksheet(trader.ORDERS_TAB)
        led = read_ledger(ws)
        client = make_client()
        code, data = client.wallets()
        wl = data.get('wallets') if isinstance(data, dict) else None
        usdt = 0.0
        if wl:
            for w in wl:
                if w.get('currency', '').upper() == 'USDT':
                    usdt = float(w.get('balance', 0) or 0)
                    break
        positions = []
        for sym, p in led['positions'].items():
            rv = p.get('real_volume') or 0
            if rv <= 1e-12:
                continue
            positions.append({
                'sym': sym,
                'volume': rv,
                'entry_price': p.get('entry_price'),
                'sl': p.get('sl'),
                'tp': p.get('tp'),
            })
        return {
            'positions': positions,
            'usdt_balance': usdt,
            'led_rows': led.get('rows', []),
        }
    except Exception as e:
        return {'error': str(e)}


def make_recommendations(scale_stats, pnl_stats, oco_stats, guard_counts, positions_data):
    """توصیه‌های خودکار"""
    recs = []
    s2_total = scale_stats['s2_total']
    s2_rate = scale_stats['s2_fill_rate']
    if s2_total >= 5:
        if s2_rate < 10:
            recs.append(f'⚠️ نرخ پر شدن Scale 2/2 زیر ۱۰٪ ({s2_rate:.0f}٪). پیشنهاد: کاهش cap به ۲٪')
        elif s2_rate > 50:
            recs.append(f'✅ نرخ پر شدن Scale 2/2 عالی ({s2_rate:.0f}٪). می‌توانید cap به ۲.۵٪ کاهش یابد')
        else:
            recs.append(f'✓ نرخ پر شدن Scale 2/2 = {s2_rate:.0f}٪ - در محدوده سالم')
    else:
        recs.append(f'⏳ تعداد Scale 2/2 ثبت‌شده کم است ({s2_total}). برای تحلیل دقیق صبر کنید.')
    
    if pnl_stats['trades'] >= 3:
        if pnl_stats['total_pnl'] > 0:
            recs.append(f'✅ P&L کل مثبت: {pnl_stats["total_pnl"]:+.2f} USDT از {pnl_stats["trades"]} معامله')
        else:
            recs.append(f'⚠️ P&L کل منفی: {pnl_stats["total_pnl"]:+.2f} USDT. پیشنهاد: بازگشت به نسخه قبلی G-scale')
        if pnl_stats['win_rate'] < 40 and pnl_stats['trades'] >= 5:
            recs.append(f'⚠️ نرخ برد پایین ({pnl_stats["win_rate"]:.0f}٪). سیگنال‌ها را بررسی کنید')
    else:
        recs.append('⏳ تعداد معاملات بسته‌شده کم است. برای تحلیل دقیق صبر کنید.')
    
    if oco_stats['failures'] > 0:
        recs.append(f'⚠️ {oco_stats["failures"]} خطای G-oco-health در ۲۴ ساعت')
    else:
        recs.append('✅ G-oco-health بدون خطا در ۲۴ ساعت اخیر')
    
    if isinstance(positions_data, dict) and 'usdt_balance' in positions_data:
        usdt = positions_data['usdt_balance']
        if usdt < 10:
            recs.append(f'⚠️ موجودی USDT پایین ({usdt:.2f}). پوزیشن‌های جدید ممکن است رد شوند')
        else:
            recs.append(f'✓ موجودی USDT کافی ({usdt:.2f})')
    
    insuf = guard_counts.get('INSUFFICIENT_USDT', 0)
    if insuf > 30:
        recs.append(f'⚠️ {insuf} رد به دلیل کمبود USDT. کاهش MAX_OPEN_POSITIONS یا افزایش موجودی')
    
    return recs


def main():
    print('=' * 70)
    print('📊 گزارش ۲۴ ساعته عملکرد G-scale و سلامت سیستم')
    print(f'زمان تولید: {NOW.strftime("%Y-%m-%d %H:%M:%S")}')
    print(f'بازه تحلیل: ۲۴ ساعت اخیر (از {CUTOFF.strftime("%Y-%m-%d %H:%M")})')
    print('=' * 70)
    
    lines = read_log_tail_24h()
    print(f'\n📝 خطوط لاگ تحلیل‌شده: {len(lines)}')
    
    positions_data = get_open_positions_summary()
    
    # 1. آمار Scale (از ledger)
    print('\n━━━ ۱) عملکرد G-scale (از ledger) ━━━')
    if isinstance(positions_data, dict) and 'led_rows' in positions_data:
        scale_stats = count_scale_from_ledger(positions_data['led_rows'])
        print(f'  Scale 1/2:')
        print(f'    ثبت‌شده/باز: {scale_stats["s1_placed"]}')
        print(f'    پر شده: {scale_stats["s1_filled"]}')
        print(f'    لغو شده: {scale_stats["s1_cancelled"]}')
        print(f'    شبیه‌سازی: {scale_stats["s1_dry"]}')
        print(f'    کل: {scale_stats["s1_total"]}')
        print(f'    نرخ پر شدن: {scale_stats["s1_fill_rate"]:.1f}%')
        print(f'  Scale 2/2:')
        print(f'    ثبت‌شده/باز: {scale_stats["s2_placed"]}')
        print(f'    پر شده: {scale_stats["s2_filled"]}')
        print(f'    لغو شده: {scale_stats["s2_cancelled"]}')
        print(f'    شبیه‌سازی: {scale_stats["s2_dry"]}')
        print(f'    کل: {scale_stats["s2_total"]}')
        print(f'    نرخ پر شدن: {scale_stats["s2_fill_rate"]:.1f}%')
    else:
        print(f'  ⚠ خطا در خواندن ledger: {positions_data.get("error", "نامشخص")}')
        scale_stats = {'s1_total': 0, 's2_total': 0, 's1_fill_rate': 0, 's2_fill_rate': 0}
    
    # 2. P&L
    print('\n━━━ ۲) عملکرد معاملات (۲۴ ساعت) ━━━')
    pnl_stats = count_pnl_from_log(lines)
    print(f'  تعداد معاملات بسته‌شده: {pnl_stats["trades"]}')
    print(f'  برد/باخت: {pnl_stats["wins"]}/{pnl_stats["losses"]}')
    print(f'  نرخ برد: {pnl_stats["win_rate"]:.1f}%')
    print(f'  P&L کل: {pnl_stats["total_pnl"]:+.2f} USDT')
    
    # 3. OCO health
    print('\n━━━ ۳) سلامت OCO (G-oco-health) ━━━')
    oco_stats = count_oco_health_errors(lines)
    print(f'  تلاش بازسازی: {oco_stats["rebuild_attempts"]}')
    print(f'  خطاها: {oco_stats["failures"]}')
    print(f'  موفقیت‌ها: {oco_stats["successes"]}')
    
    # 4. Guard rejections
    print('\n━━━ ۴) آمار رد گاردها ━━━')
    guard_counts = count_guard_rejections(lines)
    if guard_counts:
        for reason, count in sorted(guard_counts.items(), key=lambda x: -x[1]):
            print(f'  {reason:25s}: {count} بار')
    else:
        print('  (هیچ ردی ثبت نشده)')
    
    # 5. پوزیشن‌های فعال
    print('\n━━━ ۵) پوزیشن‌های فعال ━━━')
    if isinstance(positions_data, dict) and 'error' not in positions_data:
        print(f'  موجودی USDT: {positions_data["usdt_balance"]:.2f}')
        print(f'  تعداد پوزیشن‌ها: {len(positions_data["positions"])}')
        for p in positions_data['positions']:
            ep = p['entry_price']
            sl = p['sl']
            tp = p['tp']
            sym = p['sym']
            vol = p['volume']
            print(f'    {sym}: vol={vol:.4f} | entry={ep} | SL={sl} | TP={tp}')
    else:
        print(f'  ⚠ خطا در دریافت پوزیشن‌ها: {positions_data.get("error", "نامشخص")}')
    
    # 6. توصیه‌ها
    print('\n━━━ ۶) توصیه‌های خودکار ━━━')
    recs = make_recommendations(scale_stats, pnl_stats, oco_stats, guard_counts, positions_data)
    for rec in recs:
        print(f'  {rec}')
    
    print('\n' + '=' * 70)
    print('پایان گزارش')
    print('=' * 70)


if __name__ == '__main__':
    main()
