#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scale_24h_report.py - گزارش ۲۴ ساعته عملکرد G-scale و سلامت سیستم
- نرخ پر شدن Scale 1/2 و 2/2
- P&L پر شده‌ها
- خطاهای G-oco-health
- وضعیت پوزیشن‌های فعال
- توصیه‌های خودکار
"""
import os, sys, re, time, subprocess
from datetime import datetime, timedelta
sys.path.insert(0, os.path.expanduser('~/nobitex-usdt'))

LOG_PATH = os.path.expanduser('~/nobitex-usdt/update.log')
NOW = datetime.now()
CUTOFF = NOW - timedelta(hours=24)

def read_log_tail(hours=24):
    """خواندن لاگ در ۲۴ ساعت اخیر"""
    if not os.path.exists(LOG_PATH):
        return []
    # خواندن فایل فعلی
    with open(LOG_PATH, encoding='utf-8', errors='replace') as f:
        lines = f.readlines()
    
    # فیلتر بر اساس timestamp
    cutoff_str = CUTOFF.strftime('%Y-%m-%d')
    return [l for l in lines if cutoff_str in l or '2026-10-' in l][-3000:]


def parse_log_time(line):
    """استخراج timestamp از خط لاگ"""
    m = re.match(r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', line)
    if m:
        try:
            return datetime.strptime(m.group(1), '%Y-%m-%d %H:%M:%S')
        except ValueError:
            return None
    return None


def count_scale_fills(lines):
    """شمارش پر شدن Scale 1/2 و 2/2"""
    s1_placed = 0
    s2_placed = 0
    s1_filled = 0
    s2_filled = 0
    
    for line in lines:
        # ثبت سفارش
        if 'ثبت شد' in line or 'ثبت‌شده' in line:
            if 'Scale 1/2' in line:
                s1_placed += 1
            elif 'Scale 2/2' in line:
                s2_placed += 1
        # پر شدن
        elif 'پر شد' in line or 'گذار خرید' in line:
            # بررسی msg برای دیدن کدام Scale پر شده
            if 'Scale 1/2' in line:
                s1_filled += 1
            elif 'Scale 2/2' in line:
                s2_filled += 1
            # fallback: خطوط گذار خرید معمولاً Scale 1/2 هستند
            elif 'گذار خرید به پرشد' in line:
                s1_filled += 1
    
    return {
        's1_placed': s1_placed,
        's2_placed': s2_placed,
        's1_filled': s1_filled,
        's2_filled': s2_filled,
        's1_fill_rate': (s1_filled / s1_placed * 100) if s1_placed > 0 else 0,
        's2_fill_rate': (s2_filled / s2_placed * 100) if s2_placed > 0 else 0,
    }


def count_pnl(lines):
    """محاسبه P&L پر شده‌ها"""
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
    """شمارش خطاهای G-oco-health"""
    rebuild_attempts = 0
    failures = 0
    successes = 0
    
    for line in lines:
        if 'G-oco-health' not in line:
            continue
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
    """شمارش رد گاردها"""
    counts = {}
    for line in lines:
        if 'skip buy' not in line and 'انجام نشد' not in line:
            continue
        # استخراج دلیل
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
    """خلاصه پوزیشن‌های باز"""
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
        }
    except Exception as e:
        return {'error': str(e)}


def make_recommendations(scale_stats, pnl_stats, oco_stats, guard_counts, positions_data):
    """توصیه‌های خودکار"""
    recs = []
    
    # نرخ پر شدن Scale 2/2
    s2_rate = scale_stats['s2_fill_rate']
    if scale_stats['s2_placed'] >= 5:
        if s2_rate < 10:
            recs.append('⚠️ نرخ پر شدن Scale 2/2 زیر ۱۰٪ است. پیشنهاد: کاهش cap به ۲٪')
        elif s2_rate > 50:
            recs.append('✅ نرخ پر شدن Scale 2/2 عالی است. می‌توانید cap به ۲.۵٪ کاهش یابد برای میانگین بهتر')
        else:
            recs.append(f'✓ نرخ پر شدن Scale 2/2 = {s2_rate:.0f}٪ - در محدوده سالم')
    else:
        recs.append(f'⏳ تعداد Scale 2/2 ثبت‌شده کم است ({scale_stats["s2_placed"]}). برای تحلیل دقیق صبر کنید.')
    
    # P&L
    if pnl_stats['trades'] >= 3:
        if pnl_stats['total_pnl'] > 0:
            recs.append(f'✅ P&L کل مثبت است: {pnl_stats["total_pnl"]:+.2f} USDT از {pnl_stats["trades"]} معامله')
        else:
            recs.append(f'⚠️ P&L کل منفی است: {pnl_stats["total_pnl"]:+.2f} USDT. پیشنهاد: بازگشت به نسخه قبلی G-scale')
        
        if pnl_stats['win_rate'] < 40 and pnl_stats['trades'] >= 5:
            recs.append(f'⚠️ نرخ برد پایین است ({pnl_stats["win_rate"]:.0f}٪). سیگنال‌ها را بررسی کنید')
    else:
        recs.append('⏳ تعداد معاملات بسته‌شده کم است. برای تحلیل دقیق صبر کنید.')
    
    # OCO health
    if oco_stats['failures'] > 0:
        recs.append(f'⚠️ {oco_stats["failures"]} خطای G-oco-health در ۲۴ ساعت. اگر با پچ جدید ادامه دارد، نماد جدیدی به SYMBOL_ALIASES اضافه کنید')
    else:
        recs.append('✅ G-oco-health بدون خطا در ۲۴ ساعت اخیر')
    
    # USDT
    if isinstance(positions_data, dict) and 'usdt_balance' in positions_data:
        usdt = positions_data['usdt_balance']
        if usdt < 10:
            recs.append(f'⚠️ موجودی USDT پایین است ({usdt:.2f}). پوزیشن‌های جدید ممکن است رد شوند')
        else:
            recs.append(f'✓ موجودی USDT کافی است ({usdt:.2f})')
    
    # Insufficient USDT rejects
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
    
    lines = read_log_tail(24)
    print(f'\n📝 خطوط لاگ تحلیل‌شده: {len(lines)}')
    
    # 1. آمار Scale
    print('\n━━━ ۱) عملکرد G-scale ━━━')
    scale_stats = count_scale_fills(lines)
    print(f'  Scale 1/2:')
    print(f'    ثبت‌شده: {scale_stats["s1_placed"]}')
    print(f'    پر شده: {scale_stats["s1_filled"]}')
    print(f'    نرخ پر شدن: {scale_stats["s1_fill_rate"]:.1f}%')
    print(f'  Scale 2/2:')
    print(f'    ثبت‌شده: {scale_stats["s2_placed"]}')
    print(f'    پر شده: {scale_stats["s2_filled"]}')
    print(f'    نرخ پر شدن: {scale_stats["s2_fill_rate"]:.1f}%')
    
    # 2. P&L
    print('\n━━━ ۲) عملکرد معاملات (۲۴ ساعت) ━━━')
    pnl_stats = count_pnl(lines)
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
    positions_data = get_open_positions_summary()
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
