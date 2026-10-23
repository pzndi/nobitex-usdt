#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_report_analysis_summary.py - اضافه کردن خلاصه تب تحلیل به scale_24h_report"""
import os, sys, shutil, time

DEPLOY = '--deploy' in sys.argv

T_OLD = """    # 6. توصیه‌ها
    print('\\n━━━ ۶) توصیه‌های خودکار ━━━')"""

T_NEW = """    # 5.5. خلاصه تب تحلیل معاملات (داده‌های واقعی)
    print('\\n━━━ ۵.۵) خلاصه تحلیل معاملات (از تب تحلیل) ━━━')
    try:
        ws_an = sh.worksheet(trader.ANALYSIS_TAB)
        an_vals = ws_an.get_all_values()
        an_data = an_vals[3:] if len(an_vals) > 3 else []
        if an_data:
            an_wins = 0
            an_losses = 0
            an_total_pnl = 0.0
            for row in an_data:
                if not row or not any(str(c).strip() for c in row):
                    continue
                result = str(row[2]).strip() if len(row) > 2 else ''
                pnl_str = str(row[4]).strip() if len(row) > 4 else '0'
                try:
                    pnl = float(pnl_str)
                except:
                    pnl = 0.0
                if result == 'برد':
                    an_wins += 1
                elif result == 'باخت':
                    an_losses += 1
                an_total_pnl += pnl
            an_total = an_wins + an_losses
            an_winrate = (an_wins / an_total * 100) if an_total > 0 else 0
            print(f'  تعداد معاملات: {an_total}')
            print(f'  برد/باخت: {an_wins}/{an_losses}')
            print(f'  نرخ برد: {an_winrate:.1f}%')
            print(f'  P&L کل (واقعی): {an_total_pnl:+.4f} USDT')
            # میانگین سود و ضرر
            if an_wins > 0:
                win_avg = sum(float(row[4]) for row in an_data if len(row) > 4 and str(row[2]).strip() == 'برد' and _safe_float(row[4]) is not None) / an_wins
                print(f'  میانگین سود: {win_avg:+.4f} USDT')
            if an_losses > 0:
                loss_avg = sum(float(row[4]) for row in an_data if len(row) > 4 and str(row[2]).strip() == 'باخت' and _safe_float(row[4]) is not None) / an_losses
                print(f'  میانگین ضرر: {loss_avg:+.4f} USDT')
        else:
            print('  (هنوز داده‌ای در تب تحلیل نیست)')
    except Exception as e:
        print(f'  ⚠ خطا در خواندن تب تحلیل: {e}')

    # 6. توصیه‌ها
    print('\\n━━━ ۶) توصیه‌های خودکار ━━━')"""


def _safe_float(v):
    try:
        return float(v)
    except:
        return None


def main():
    print('=' * 70)
    print('fix_report_analysis_summary.py - اضافه کردن خلاصه تب تحلیل')
    print(f'mode: {"DEPLOY" if DEPLOY else "DRY-RUN"}')
    print('=' * 70)
    
    with open('scale_24h_report.py', 'r', encoding='utf-8') as f:
        src = f.read()
    
    if T_OLD not in src:
        print('! T_OLD not found - already patched?')
        return 1
    
    if 'ANALYSIS_TAB' in src:
        print('! already patched')
        return 0
    
    new_src = src.replace(T_OLD, T_NEW)
    
    # همچنین اضافه کردن import trader و sh
    T_OLD_2 = "    positions_data = get_open_positions_summary()"
    T_NEW_2 = """    # G-analysis: خواندن تب تحلیل معاملات
    try:
        import trader
        from settings import load_env
        import gspread as _gs
        _e = load_env()
        _gc = _gs.service_account(filename='service_account.json')
        sh = _gc.open_by_key(_e['SHEET_ID'])
    except Exception:
        sh = None
    
    positions_data = get_open_positions_summary()"""
    
    if T_OLD_2 in new_src:
        new_src = new_src.replace(T_OLD_2, T_NEW_2)
    
    try:
        compile(new_src, 'scale_24h_report.py', 'exec')
        if DEPLOY:
            bak = f'scale_24h_report.py.bak.{time.strftime("%Y%m%d_%H%M")}'
            shutil.copy('scale_24h_report.py', bak)
            with open('scale_24h_report.py', 'w', encoding='utf-8') as f:
                f.write(new_src)
            print(f'+ scale_24h_report.py: اضافه شدن خلاصه تب تحلیل')
            print(f'  + backup: {bak}')
        else:
            print('+ scale_24h_report.py (dry-run): اضافه شدن خلاصه تب تحلیل')
        return 0
    except SyntaxError as e:
        print(f'  + syntax error: {e}')
        return 1


if __name__ == '__main__':
    sys.exit(main())
