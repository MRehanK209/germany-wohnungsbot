sqlite3 -header -column data/listings.db "select date(telegram_sent_at,'unixepoch','localtime') day, count(*) ads from listings where telegram_sent_at is not null group by day order by day;"

sqlite3 -header -column data/listings.db "select platform, count(*) ads from listings where date(telegram_sent_at,'unixepoch','localtime')='2026-11-11' group by platform;"

sqlite3 -header -column data/listings.db "select time(telegram_sent_at,'unixepoch','localtime') time, price, size, url from listings where date(telegram_sent_at,'unixepoch','localtime')='2026-11-12' order by telegram_sent_at;"