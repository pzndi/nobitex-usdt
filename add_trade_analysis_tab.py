#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""add_trade_analysis_tab.py - ایجاد تب «تحلیل معاملات» با علت‌یابی خودکار

اضافه کردن:
1. ثابت ANALYSIS_TAB = 'تحلیل معاملات'
2. تابع _record_analysis() که پس از هر معامله بسته‌شده فراخوانی می‌شود
3. فراخوانی در sync_order_statuses بعد از record_closed

ستون‌ها:
- زمان خروج، نماد، نتیجه (برد/باخت/سربه‌سر)، نوع خروج
- P&L USDT، P&L %، مدت (ساعت)
- قیمت ورود، قیمت خروج
- SL/TP تنظیم‌شده، فاصله SL% و TP%
- ATR، نوسان 4h%
- تعداد Scale 1/2 و 2/2، Scale-in
- Trailing فعال، Partial فعال
- علت تحلیل، درس‌آموخته
"""
import os, sys, shutil, time

DEPLOY = '--deploy' in sys.argv

# بخش ۱: اضافه کردن ثابت ANALYSIS_TAB
T_OLD_1 = """CLOSED_TAB = 'اتمام معاملات'"""

T_NEW_1 = """CLOSED_TAB = 'اتمام معاملات'
ANALYSIS_TAB = 'تحلیل معاملات'"""

# بخش ۲: اضافه کردن تابع _record_analysis قبل از record_closed
T_OLD_2 = """def record_closed(ws_t, sym, entry_time, entry_price, exit_price, vol, reason, mode, fee_usdt=0.0):"""

T_NEW_2 = """def _record_analysis(ws_t, sym, entry_price, exit_price, vol, pnl, pct, dur, reason, led, client, st):
    \"\"\"ثبت تحلیل معامله بسته‌شده در تب «تحلیل معاملات» با علت‌یابی خودکار\"\"\"
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
    except Exception:
        log.exception('خطا در ثبت تحلیل معامله %s', sym)


def record_closed(ws_t, sym, entry_time, entry_price, exit_price, vol, reason, mode, fee_usdt=0.0):"""

# بخش ۳: فراخوانی _record_analysis در sync_order_statuses
T_OLD_3 = """            record_closed(ws_t, sym_c, t_in, entry_n7, exit_n7,
                          vol_c, 'اجرای سفارش فروش', 'واقعی', fee_usdt=sell_fee_n7 + buy_fee_n7)"""

T_NEW_3 = """            record_closed(ws_t, sym_c, t_in, entry_n7, exit_n7,
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
                log.exception('خطا در ثبت تحلیل معامله %s', sym_c)"""


def main():
    print('=' * 70)
    print('add_trade_analysis_tab.py - ایجاد تب «تحلیل معاملات» با علت‌یابی خودکار')
    print(f'mode: {"DEPLOY" if DEPLOY else "DRY-RUN"}')
    print('=' * 70)
    
    with open('trader.py', 'r', encoding='utf-8') as f:
        trader_src = f.read()
    
    patches_applied = []
    
    # بخش ۱
    if T_OLD_1 in trader_src and 'ANALYSIS_TAB' not in trader_src:
        trader_src = trader_src.replace(T_OLD_1, T_NEW_1)
        patches_applied.append('ثابت ANALYSIS_TAB')
    else:
        print('! بخش ۱: قبلاً اعمال شده یا الگو یافت نشد')
    
    # بخش ۲
    if T_OLD_2 in trader_src and '_record_analysis' not in trader_src:
        trader_src = trader_src.replace(T_OLD_2, T_NEW_2)
        patches_applied.append('تابع _record_analysis')
    else:
        print('! بخش ۲: قبلاً اعمال شده یا الگو یافت نشد')
    
    # بخش ۳
    if T_OLD_3 in trader_src:
        trader_src = trader_src.replace(T_OLD_3, T_NEW_3)
        patches_applied.append('فراخوانی _record_analysis در sync_order_statuses')
    else:
        print('! بخش ۳: الگو یافت نشد')
    
    if not patches_applied:
        print('! هیچ پچی قابل اعمال نیست')
        return 1
    
    try:
        compile(trader_src, 'trader.py', 'exec')
        print(f'+ {len(patches_applied)} patches:')
        for p in patches_applied:
            print(f'  + {p}')
        print('  + syntax check: OK')
    except SyntaxError as e:
        print(f'  + syntax check FAILED: {e}')
        return 1
    
    if DEPLOY:
        bak = f'trader.py.bak.{time.strftime("%Y%m%d_%H%M")}'
        shutil.copy('trader.py', bak)
        print(f'  + backup: {bak}')
        with open('trader.py', 'w', encoding='utf-8') as f:
            f.write(trader_src)
        print('  + deployed: trader.py')
    else:
        with open('trader_candidate.py', 'w', encoding='utf-8') as f:
            f.write(trader_src)
        print('  (dry-run: candidate saved)')
    
    print()
    print('=' * 70)
    if DEPLOY:
        print('Deploy complete.')
        print()
        print('تب «تحلیل معاملات» به‌صورت خودکار در اولین معامله بسته‌شده ایجاد می‌شود.')
    else:
        print('dry-run OK. To deploy:')
        print('  cd ~/nobitex-usdt && venv/bin/python add_trade_analysis_tab.py --deploy')
    print('=' * 70)
    return 0

if __name__ == '__main__':
    sys.exit(main())
