#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""list_tabs.py — استخراج نام همه تب‌های گوگل شیت"""
import gspread, os, re

def load_env(path='.env'):
    """خواندن .env به‌صورت دستی (بدون dotenv)"""
    env = {}
    if not os.path.exists(path):
        return env
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            k, v = line.split('=', 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env

def main():
    e = load_env()
    sid = e.get('SHEET_ID') or e.get('GOOGLE_SHEET_ID')
    gc = gspread.service_account(filename='service_account.json')
    sh = gc.open_by_key(sid) if sid else gc.open('نمادهای معاملاتی')
    sheets = sh.worksheets()
    print('=' * 60)
    print('فهرست تب‌های گوگل شیت: %s' % (sid or 'نمادهای معاملاتی'))
    print('=' * 60)
    for i, ws in enumerate(sheets, 1):
        print('%2d. %s  (%dx%d)' % (i, ws.title, ws.row_count, ws.col_count))
    print('=' * 60)
    print('مجموع: %d تب' % len(sheets))

if __name__ == '__main__':
    main()
