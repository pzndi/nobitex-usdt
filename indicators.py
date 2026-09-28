#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
indicators.py — اندیکاتورهای تحلیل تکنیکال (پایتون خالص، بدون وابستگی خارجی)
ورودی: لیست float به ترتیب زمانی (قدیمی → جدید)
خروجی: لیستی هم‌طول ورودی؛ خانه‌های ابتدای دوره None هستند
"""


def sma(values, period):
    n = len(values)
    out = [None] * n
    if period <= 0 or n < period:
        return out
    s = sum(values[:period])
    out[period - 1] = s / period
    for i in range(period, n):
        s += values[i] - values[i - period]
        out[i] = s / period
    return out


def ema(values, period):
    n = len(values)
    out = [None] * n
    if period <= 0 or n < period:
        return out
    m = sum(values[:period]) / period
    out[period - 1] = m
    k = 2.0 / (period + 1)
    for i in range(period, n):
        m = values[i] * k + m * (1 - k)
        out[i] = m
    return out


def _rs_val(avg_gain, avg_loss):
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    return 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)


def rsi(closes, period=14):
    n = len(closes)
    out = [None] * n
    if period <= 0 or n <= period:
        return out
    gains = losses = 0.0
    for i in range(1, period + 1):
        d = closes[i] - closes[i - 1]
        if d >= 0:
            gains += d
        else:
            losses -= d
    ag, al = gains / period, losses / period
    out[period] = _rs_val(ag, al)
    for i in range(period + 1, n):
        d = closes[i] - closes[i - 1]
        g = d if d > 0 else 0.0
        l = -d if d < 0 else 0.0
        ag = (ag * (period - 1) + g) / period
        al = (al * (period - 1) + l) / period
        out[i] = _rs_val(ag, al)
    return out


def macd(closes, fast=12, slow=26, signal=9):
    ef, es = ema(closes, fast), ema(closes, slow)
    line = [(f - s) if (f is not None and s is not None) else None
            for f, s in zip(ef, es)]
    n = len(closes)
    sig = [None] * n
    first = next((i for i, v in enumerate(line) if v is not None), None)
    if first is not None and n - first >= signal:
        seg = line[first:]
        m = sum(seg[:signal]) / signal
        sig[first + signal - 1] = m
        k = 2.0 / (signal + 1)
        for i in range(first + signal, n):
            m = line[i] * k + m * (1 - k)
            sig[i] = m
    hist = [(l - s) if (l is not None and s is not None) else None
            for l, s in zip(line, sig)]
    return line, sig, hist


def bollinger(closes, period=20, std=2.0):
    n = len(closes)
    mid, up, lo = [None] * n, [None] * n, [None] * n
    for i in range(period - 1, n):
        w = closes[i - period + 1:i + 1]
        m = sum(w) / period
        sd = (sum((x - m) ** 2 for x in w) / period) ** 0.5
        mid[i], up[i], lo[i] = m, m + std * sd, m - std * sd
    return mid, up, lo


def stoch(highs, lows, closes, k_period=14, d_period=3, smooth=3):
    n = len(closes)
    raw = [None] * n
    for i in range(k_period - 1, n):
        hh = max(highs[i - k_period + 1:i + 1])
        ll = min(lows[i - k_period + 1:i + 1])
        raw[i] = 50.0 if hh == ll else (closes[i] - ll) / (hh - ll) * 100.0
    k = [None] * n
    for i in range(smooth - 1, n):
        w = raw[i - smooth + 1:i + 1]
        if all(v is not None for v in w):
            k[i] = sum(w) / smooth
    d = [None] * n
    for i in range(d_period - 1, n):
        w = k[i - d_period + 1:i + 1]
        if all(v is not None for v in w):
            d[i] = sum(w) / d_period
    return k, d


def obv(closes, volumes):
    out = [0.0] * len(closes)
    for i in range(1, len(closes)):
        if closes[i] > closes[i - 1]:
            out[i] = out[i - 1] + volumes[i]
        elif closes[i] < closes[i - 1]:
            out[i] = out[i - 1] - volumes[i]
        else:
            out[i] = out[i - 1]
    return out


def cci(highs, lows, closes, period=20):
    n = len(closes)
    out = [None] * n
    tp = [(h + l + c) / 3 for h, l, c in zip(highs, lows, closes)]
    for i in range(period - 1, n):
        w = tp[i - period + 1:i + 1]
        m = sum(w) / period
        md = sum(abs(x - m) for x in w) / period
        out[i] = (tp[i] - m) / (0.015 * md) if md else 0.0
    return out


def wpr(highs, lows, closes, period=14):
    n = len(closes)
    out = [None] * n
    for i in range(period - 1, n):
        hh = max(highs[i - period + 1:i + 1])
        ll = min(lows[i - period + 1:i + 1])
        out[i] = -100.0 if hh == ll else (hh - closes[i]) / (hh - ll) * -100.0
    return out


def atr(highs, lows, closes, period=14):
    n = len(closes)
    out = [None] * n
    if period <= 0 or n <= period:
        return out
    trs = [highs[0] - lows[0]]
    for i in range(1, n):
        trs.append(max(highs[i] - lows[i],
                       abs(highs[i] - closes[i - 1]),
                       abs(lows[i] - closes[i - 1])))
    a = sum(trs[1:period + 1]) / period
    out[period] = a
    for i in range(period + 1, n):
        a = (a * (period - 1) + trs[i]) / period
        out[i] = a
    return out
