# بازیابی در قطعی سرور/شبکه
1. pgrep -af scheduler.py  → پروسه‌ی hang را kill -9 کنید
2. sudo rm -f /tmp/nobitex.lock /tmp/wallex.lock
3. هر دو را --force اجرا کنید (با flock)
4. پوزیشن‌های والکس را در برابر SL بسنجید
5. گزارش هر دو شیت را چک کنید
