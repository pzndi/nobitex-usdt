#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_ghost_ladder.py - P1 pending per-row | P2 TTL partial | P3 instant-exit
| P4 G-scale log | P5 mem-sync.  --check = فقط گزارش تطبیق. بدون آرگومان = بکاپ+اعمال."""
import io, os, py_compile, shutil, sys, time

SRC = 'trader.py'
HUNKS = []
def H(pid, desc, old, new):
    HUNKS.append((pid, desc, old, new))

H('P1', 'pending نماد-محور -> per-row در TTL', '''        if ok:
            for row_num, rr in led['rows']:
                if oid in str(rr[10]).replace(',', ''):
                    ws_t.update_cell(row_num, 12, ST_CANCELLED)
                    break
            led['pending'].discard(sym)
            for _ps in list(led.get('pending') or ()):
                if _norm_sym(_ps) == _norm_sym(sym):
                    led['pending'].discard(_ps)
            log.info('سفارش ورود کهنه لغو شد: %s (سن %.0f دقیقه)', sym, age_min)''',
'''        if ok:
            _c_row = None
            for row_num, rr in led['rows']:
                if oid in str(rr[10]).replace(',', ''):
                    _c_row = row_num
                    if matched <= 0:
                        ws_t.update_cell(row_num, 12, ST_CANCELLED)
                    break
            if matched > 0:
                # G-partial (P1b): ردیف نیمه‌پر را «لغو شده» نکن — بخشِ پرشده باید
                # از مسیر همگام‌سازی (Canceled+matched -> «پر شد» + گذار fill + OCO)
                # پوزیشنِ محافظت‌شده شود؛ علامت‌گذاری اینجا مسیر گذار را می‌بُرد.
                log.info('TTL %s: باقیماندهٔ سفارش نیمه‌پر لغو شد (پرشده=%s) — '
                         'ثبت بخشِ پرشده به همگام‌سازی واگذار شد', sym, matched)
            else:
                # G-pending (P1a): pending نماد-محور است؛ لغوی یکی از چند سفارشِ بازِ
                # نماد نباید نماد را از pending بردارد (شبح 05:02: لغوی یک پله
                # دروازهٔ خرید را همان تیک باز کرد -> سه نسل نردبان در کرش 05:34).
                _still = any(_rn != _c_row
                             and str(_rr[2]).strip() == 'خرید'
                             and _norm_sym(_rr[1]) == _norm_sym(sym)
                             and str(_rr[11]).strip() in OPENISH
                             for _rn, _rr in (led.get('rows') or []))
                if not _still:
                    led['pending'].discard(sym)
                    for _ps in list(led.get('pending') or ()):
                        if _norm_sym(_ps) == _norm_sym(sym):
                            led['pending'].discard(_ps)
                log.info('سفارش ورود کهنه لغو شد: %s (سن %.0f دقیقه)%s', sym, age_min,
                         ' — نماد در pending ماند (سفارش باز دیگر)' if _still else '')''')

H('P2a-1', 'حذف skip بی‌صدای نیمه‌پر', '''        if matched > 0:            # پرشدن جزئی — لغو نکن
            continue
        cid = str(o.get('clientOrderId') or '')''',
'''        cid = str(o.get('clientOrderId') or '')''')

H('P2a-2', 'نیمه‌پرِ کهنه: لغو باقیمانده با لاگ', '''        if age_min < st.entry_ttl_min:
            continue''',
'''        if age_min < st.entry_ttl_min:
            continue
        if matched > 0:
            # G-partial (P2a): نیمه‌پرِ کهنه دیگر بی‌صدا رد نمی‌شود (شبح 1472:
            # fill جزئی پیش از 05:02، بی‌حفاظ تا پرشد کامل در کرش 05:34) —
            # باقیمانده لغو می‌شود تا بخشِ پرشده همان تیک محافظت‌شدنی شود.
            log.info('TTL %s: سفارش نیمه‌پر کهنه (سن %.0f دقیقه، پرشده=%s) — لغو باقیمانده',
                     sym, age_min, matched)''')

H('P2b', 'خریدِ نیمه‌پرِ لغوشده -> پر شد + گذار fill', '''            if matched > 0:
                new_st = ST_PARTIAL
                vol_update = matched''',
'''            if matched > 0:
                # G-partial (P2b): خریدِ نیمه‌پرِ لغوشده -> «پر شد» با حجم واقعی؛
                # گذار fill همان تیک روی بخشِ پرشده OCO می‌گذارد. («بخشی پر» =
                # لیمبوی بی‌حفاظ: نه پوزیشن، نه OCO، نه check_sl_tp.)
                # فروش‌ها دست‌نخورده — همان ST_PARTIAL قبلی.
                if str(r[2]).strip() == 'خرید':
                    new_st = ST_FILLED
                else:
                    new_st = ST_PARTIAL
                vol_update = matched''')

H('P5', 'همگام‌سازی حافظهٔ درون‌تیکی sync', '''        if new_st != str(r[11]).strip():
            ws_t.update_cell(row_num, 12, new_st)
            if vol_update is not None:
                ws_t.update_cell(row_num, 7, vol_update)
            log.info('وضعیت سفارش %s → %s', '|'.join(oids), new_st)''',
'''        if new_st != str(r[11]).strip():
            ws_t.update_cell(row_num, 12, new_st)
            # G-mem (P5): حافظهٔ درون‌تیکی همگام شود — وگرنه _entry_fill/VWAPِ
            # همین تیک وضعیت کهنه می‌دید (شاهد 19:38: VWAP=169.42 از چرخهٔ
            # بستهٔ قبلی به‌جای 172.19 -> باند غلط -> defer بی‌مورد).
            r[11] = new_st
            if vol_update is not None:
                ws_t.update_cell(row_num, 7, vol_update)
                r[6] = vol_update
            log.info('وضعیت سفارش %s → %s', '|'.join(oids), new_st)''')

H('P3', 'بیرونِ باند در گذار fill -> فروش فوری', '''                if _px_f7 and _px_f7 > 0:
                    if _px_f7 <= sl_o or _px_f7 >= tp_o:
                        # قیمت روی/زیر SL یا روی/بالای TP — استاپ فروش رد می‌شود؛ خروج با check_sl_tp
                        log.info('OCO گذار fill %s به check_sl_tp واگذار شد — قیمت لحظه‌ای %s خارج از باند SL=%s..TP=%s',
                                 sym_c, fmt_price(_px_f7), fmt_price(sl_o), fmt_price(tp_o))
                        continue''',
'''                if _px_f7 and _px_f7 > 0:
                    if _px_f7 <= sl_o or _px_f7 >= tp_o:
                        # G-instant-exit (P3): قیمت لحظه‌ای بیرونِ باند یعنی TP/SL
                        # همین حالا لمس شده. واگذاری به check_sl_tp پنجرهٔ بی‌حفاظ
                        # می‌سازد (شاهد 05:34: سه fill در 173.52 بالای TP؛ خروج
                        # نهایی 168.45 -> ضرر -0.14 به‌جای سود ~+0.10).
                        _why = 'حد سود' if _px_f7 >= tp_o else 'حد ضرر'
                        log.info('G-instant-exit %s: قیمت لحظه‌ای %s بیرونِ باند SL=%s..TP=%s — فروش فوری (%s)',
                                 sym_c, fmt_price(_px_f7), fmt_price(sl_o), fmt_price(tp_o), _why)
                        _sold = False
                        if st is not None:
                            _sold = sell_one(st, ws_t, client, False, sym_c, _why,
                                             _px_f7, vol_o, led)
                        if _sold:
                            led.setdefault('pending_sells', set()).add(sym_c)
                        else:
                            log.warning('G-instant-exit %s انجام نشد — خروج به check_sl_tp واگذار شد', sym_c)
                        continue''')

H('P4', 'لاگ لغوی موفق OCO در G-scale', '''                    for _rn in _tgt_rows:
                        ws_t.update_cell(_rn, 12, ST_CANCELLED)''',
'''                    for _rn in _tgt_rows:
                        ws_t.update_cell(_rn, 12, ST_CANCELLED)
                    # G-log (P4): لغوی موفق تا حالا بی‌صدا بود (شاهد: ردیف 698
                    # ساعت 20:49). یک خط INFO برای ردگیری.
                    log.info('G-scale %s: لغو %d لگ OCO انجام شد (ردیف‌ها: %s)',
                             sym_c, len(_tgt), _tgt_rows or '—')''')

def main():
    check = '--check' in sys.argv[1:]
    text = io.open(SRC, encoding='utf-8').read()
    fails = [(p, text.count(o)) for p, _, o, _ in HUNKS if text.count(o) != 1]
    if fails:
        print('✗ اعمال نشد — این هانک‌ها تطبیق نگرفتند (تعداد یافته):')
        for p, n in fails:
            print('  ', p, '->', n)
        sys.exit(1)
    print(f'✓ هر {len(HUNKS)} هانک دقیقاً یک‌بار یافت شد:')
    for p, d, _, _ in HUNKS:
        print('  ', p, '—', d)
    if check:
        print('\n(--check: چیزی نوشته نشد)'); return
    for _, _, o, n in HUNKS:
        text = text.replace(o, n, 1)
    bak = SRC + '.bak-' + time.strftime('%Y%m%d-%H%M%S')
    shutil.copy2(SRC, bak)
    tmp = SRC + '.tmp'
    io.open(tmp, 'w', encoding='utf-8').write(text)
    os.replace(tmp, SRC)
    py_compile.compile(SRC, doraise=True)
    print(f'\n✓ اعمال شد | بکاپ: {bak} | py_compile OK')
    print('→ کرون از تیک بعد کد تازه را برمی‌دارد (ری‌استارت لازم نیست).')

if __name__ == '__main__':
    main()
