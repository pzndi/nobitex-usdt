#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""apply_guards_24h.py - change guards log scan to last 24h (500 lines)"""
import os, sys, shutil, py_compile, time

DEPLOY = '--deploy' in sys.argv

# پچ ۱: حذف وابستگی به تاریخ امروز، استفاده از آخرین ۵۰۰ خط لاگ
T_OLD = """        today_str = _dt.now().strftime('%Y-%m-%d')
        log_path = _os.path.expanduser('~/nobitex-usdt/update.log')
        today_lines = []
        try:
            with open(log_path, encoding='utf-8') as f:
                for line in f:
                    if today_str in line:
                        today_lines.append(line.strip())
        except Exception:
            pass"""

T_NEW = """        log_path = _os.path.expanduser('~/nobitex-usdt/update.log')
        recent_lines = []
        try:
            with open(log_path, encoding='utf-8') as f:
                lines = f.readlines()
            # آخرین ۵۰۰ خط (حدود ۲۴-۴۸ ساعت)
            recent_lines = [l.strip() for l in lines[-500:] if l.strip()]
        except Exception:
            pass"""

# پچ ۲: تغییر متغیر مرجع در حلقه از today_lines به recent_lines
T2_OLD = """            for line in today_lines:
                if pattern in line:"""
T2_NEW = """            for line in recent_lines:
                if pattern in line:"""

# پچ ۳: به‌روزرسانی هدر ستون‌ها برای شفافیت بیشتر
T3_OLD = """        ws.update(values=[['نام گارد', 'وظیفه', 'وضعیت', 'آخرین رد', 'نماد', 'علت', 'تعداد امروز', 'یادداشت']],
                  range_name='A3:H3')"""
T3_NEW = """        ws.update(values=[['نام گارد', 'وظیفه', 'وضعیت', 'آخرین رد (۲۴س)', 'نماد', 'علت', 'تعداد (۲۴س)', 'یادداشت']],
                  range_name='A3:H3')"""

CHANGES = {
    'trader.py': [(T_OLD, T_NEW, 'scan last 500 lines instead of today_str'),
                  (T2_OLD, T2_NEW, 'use recent_lines variable'),
                  (T3_OLD, T3_NEW, 'update header to 24h')]
}


def main():
    os.chdir(os.path.expanduser('~/nobitex-usdt'))
    print('=' * 72)
    print('apply_guards_24h.py - change guards log scan to last 24h (500 lines)')
    print('mode: DEPLOY' if DEPLOY else 'mode: DRY-RUN (preview only)')
    print('=' * 72)
    all_ok = True
    applied = []
    fname = 'trader.py'
    if not os.path.exists(fname):
        print('X %s not found' % fname)
        sys.exit(1)
    src = open(fname, encoding='utf-8').read()
    cand = src
    file_ok = True
    for old, new, desc in CHANGES[fname]:
        if old in cand:
            cand = cand.replace(old, new, 1)
            print('+ %s: %s' % (fname, desc))
            applied.append((fname, desc))
        else:
            print('X %s: pattern not found: %s' % (fname, desc))
            print('  expected: %s...' % old[:80])
            file_ok = False
            all_ok = False
    if not file_ok:
        sys.exit(1)
    cand_name = 'trader_candidate.py'
    with open(cand_name, 'w', encoding='utf-8') as f:
        f.write(cand)
    try:
        py_compile.compile(cand_name, doraise=True)
        print('  + py_compile: OK')
    except py_compile.PyCompileError as e:
        print('  X py_compile FAILED: %s' % e)
        sys.exit(1)
    if DEPLOY:
        bak = '%s.bak.%s' % (fname, time.strftime('%Y%m%d_%H%M'))
        shutil.copy2(fname, bak)
        print('  + backup: %s' % bak)
        shutil.move(cand_name, fname)
        print('  + deployed: %s' % fname)
    else:
        print('  (dry-run: candidate saved as %s)' % cand_name)
    print()
    print('=' * 72)
    print('+ %d patches ready' % len(applied))
    if DEPLOY:
        print('Deploy complete. Wait 5 min, then check tab.')
    else:
        print('dry-run OK. To deploy:')
        print('  cd ~/nobitex-usdt && venv/bin/python apply_guards_24h.py --deploy')
    print('=' * 72)


if __name__ == '__main__':
    main()
