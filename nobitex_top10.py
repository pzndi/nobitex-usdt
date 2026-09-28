#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
nobitex_top10.py
هر بار اجرا:
  ۱) آمار ۲۴ ساعته همه بازارهای نوبیتکس را دریافت می‌کند
  ۲) بازارهای پایه USDT را جدا می‌کند
  ۳) بر اساس حجم معاملات و نقدپذیری (اسپرد) رتبه‌بندی می‌کند
  ۴) ۱۰ نماد برتر را در «ستون دوم» گوگل‌شیت «نمادهای معاملاتی» می‌نویسد

اجرا:
  python3 nobitex_top10.py          (یک‌بار)
  python3 nobitex_top10.py --loop   (مداوم، هر ۲ ساعت)
"""

import argparse
import logging
import os
import time
from datetime import datetime

import requests
import gspread
from google.oauth2.service_account import Credentials

# ----------------- تنظیمات -----------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SERVICE_ACCOUNT_FILE = os.path.join(BASE_DIR, "service_account.json")

SHEET_NAME = "نمادهای معاملاتی"       # نام گوگل‌شیت
USER_EMAIL = "ziaianndi@gmail.com"    # شیت با این ایمیل به اشتراک گذاشته می‌شود
TOP_N = 10                            # تعداد نماد برتر
INTERVAL = 2 * 60 * 60                # ۲ ساعت (فقط در حالت --loop)

NOBITEX_STATS_URL = "https://apiv2.nobitex.ir/market/stats"
HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) nobitex-sheet-updater/1.0",
    "Accept": "application/json",
}

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("nobitex-sheet")


# ----------------- نوبیتکس -----------------
def _request_stats():
    """درخواست آمار همه بازارها (GET و در صورت نیاز POST)."""
    try:
        r = requests.get(NOBITEX_STATS_URL, headers=HTTP_HEADERS, timeout=60)
        if r.ok:
            return r.json()
    except requests.RequestException:
        pass
    r = requests.post(NOBITEX_STATS_URL, json={}, headers=HTTP_HEADERS, timeout=60)
    r.raise_for_status()
    return r.json()


def fetch_usdt_markets(retries=3, wait_sec=30):
    """آمار بازارهای USDT را به صورت لیست برمی‌گرداند."""
    stats = None
    for attempt in range(1, retries + 1):
        try:
            stats = _request_stats().get("stats", {})
            break
        except Exception as exc:
            log.warning("تلاش %d از %d ناموفق بود: %s", attempt, retries, exc)
            if attempt < retries:
                time.sleep(wait_sec)

    if not stats:
        log.error("دریافت داده از نوبیتکس شکست خورد.")
        return []

    markets = []
    for name, s in stats.items():
        if not name.upper().endswith("USDT"):
            continue
        try:
            best_buy = float(s.get("bestBuy") or 0)
            best_sell = float(s.get("bestSell") or 0)
            volume_usdt = float(s.get("volumeDst") or 0)   # حجم ۲۴ ساعته بر حسب USDT
            day_change = float(s.get("dayChange") or 0)    # درصد تغییر ۲۴ ساعته
        except (TypeError, ValueError):
            continue

        if best_sell <= 0 or volume_usdt <= 0:
            continue  # بازار بسته یا بی‌حجم حذف می‌شود

        spread_pct = max(0.0, (best_sell - best_buy) / best_sell * 100.0)
        markets.append({
            "market": name,               # مثل BTCUSDT
            "symbol": name[:-5].upper() if name.lower().endswith("-usdt") else name[:-4].upper(),          # مثل BTC
            "volume_usdt": volume_usdt,
            "spread_pct": spread_pct,
            "day_change": day_change,
        })

    log.info("%d بازار USDT از نوبیتکس دریافت شد.", len(markets))
    return markets


def rank_markets(markets):
    """
    رتبه‌بندی بر اساس نقدپذیری و حجم معاملات:
      - حجم ۲۴ ساعته به USDT: هرچه بیشتر بهتر
      - اسپرد خرید/فروش: هرچه کمتر، بازار نقدشوندتر
      امتیاز = حجم / (۱ + اسپرد)
    """
    def score(m):
        return m["volume_usdt"] / (1.0 + m["spread_pct"])

    return sorted(markets, key=score, reverse=True)


# ----------------- گوگل شیت -----------------
def get_gspread_client():
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    return gspread.authorize(creds)


def open_or_create_spreadsheet(gc):
    try:
        sh = gc.open(SHEET_NAME)
        log.info("شیت موجود «%s» باز شد: %s", SHEET_NAME, sh.url)
    except gspread.SpreadsheetNotFound:
        sh = gc.create(SHEET_NAME)
        log.info("شیت «%s» ساخته شد: %s", SHEET_NAME, sh.url)
        try:
            sh.share(USER_EMAIL, perm_type="user", role="writer")
            log.info("شیت با ایمیل %s به اشتراک گذاشته شد؛ لینک به ایمیل شما ارسال می‌شود.", USER_EMAIL)
        except Exception as exc:
            log.warning("اشتراک‌گذاری خودکار ناموفق بود: %s", exc)
    return sh


def update_sheet(ws, ranked):
    """نوشتن ۱۰ نماد برتر — نمادها در ستون دوم (B) قرار می‌گیرند."""
    rows = [
        ["آخرین به‌روزرسانی", datetime.now().strftime("%Y-%m-%d %H:%M:%S")],
        ["", "", "", "", ""],
        ["رتبه", "نماد", "حجم ۲۴ ساعته (USDT)", "اسپرد (درصد)", "تغییر ۲۴ ساعته (درصد)"],
    ]
    for i, m in enumerate(ranked[:TOP_N], start=1):
        rows.append([
            i,
            m["symbol"],
            round(m["volume_usdt"], 2),
            round(m["spread_pct"], 3),
            round(m["day_change"], 2),
        ])

    ws.clear()
    ws.update(values=rows, range_name="A1")
    try:
        ws.format("A3:E3", {"textFormat": {"bold": True}})
    except Exception:
        pass

    log.info("۱۰ نماد برتر در شیت نوشته شد: %s",
             ", ".join(m["symbol"] for m in ranked[:TOP_N]))


# ----------------- اجرا -----------------
def run_once():
    markets = fetch_usdt_markets()
    if not markets:
        return
    ranked = rank_markets(markets)
    try:
        gc = get_gspread_client()
        sh = open_or_create_spreadsheet(gc)
        update_sheet(sh.sheet1, ranked)
    except Exception as exc:
        log.error("خطا در به‌روزرسانی گوگل شیت: %s", exc)


def main():
    parser = argparse.ArgumentParser(
        description="به‌روزرسانی گوگل‌شیت «نمادهای معاملاتی» با ۱۰ نماد برتر USDT نوبیتکس")
    parser.add_argument("--loop", action="store_true",
                        help="اجرای مستمر هر ۲ ساعت (به‌جای cron)")
    args = parser.parse_args()

    if args.loop:
        while True:
            run_once()
            log.info("اجرای بعدی تا ۲ ساعت دیگر ...")
            time.sleep(INTERVAL)
    else:
        run_once()


if __name__ == "__main__":
    main()
