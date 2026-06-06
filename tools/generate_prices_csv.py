import csv
import json
import time
import urllib.request
from datetime import datetime, time as datetime_time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

TICKERS_FILE = Path("assets/data/tickers.txt")
OUTPUT_FILE = Path("assets/data/prices_daily.csv")
LATEST_FILE = Path("assets/data/latest_prices.csv")
FAILED_FILE = Path("assets/data/failed_tickers.txt")

YEARS_BACK = 10
REQUEST_DELAY_SECONDS = 0.4

NY_ZONE = ZoneInfo("America/New_York")
MADRID_ZONE = ZoneInfo("Europe/Madrid")

MARKET_CLOSE_CONFIRM_HOUR = 17
MARKET_CLOSE_CONFIRM_MINUTE = 30


def read_tickers() -> list[str]:
    if not TICKERS_FILE.exists():
        raise FileNotFoundError(f"No existe {TICKERS_FILE}")

    tickers = []
    seen = set()

    for line in TICKERS_FILE.read_text(encoding="utf-8").splitlines():
        ticker = line.strip().upper()

        if not ticker:
            continue

        if ticker.startswith("#"):
            continue

        if ticker in seen:
            continue

        seen.add(ticker)
        tickers.append(ticker)

    if not tickers:
        raise ValueError("tickers.txt está vacío")

    return tickers


def market_close_confirmed() -> bool:
    ny_now = datetime.now(NY_ZONE)

    if ny_now.weekday() >= 5:
        return True

    confirm_time = datetime_time(
        MARKET_CLOSE_CONFIRM_HOUR,
        MARKET_CLOSE_CONFIRM_MINUTE,
    )

    return ny_now.time() >= confirm_time


def current_market_status() -> str:
    ny_now = datetime.now(NY_ZONE)

    if ny_now.weekday() >= 5:
        return "closed_weekend"

    regular_open = datetime_time(9, 30)
    regular_close = datetime_time(16, 0)
    confirm_time = datetime_time(
        MARKET_CLOSE_CONFIRM_HOUR,
        MARKET_CLOSE_CONFIRM_MINUTE,
    )

    if ny_now.time() < regular_open:
        return "pre_market"

    if regular_open <= ny_now.time() < regular_close:
        return "open"

    if regular_close <= ny_now.time() < confirm_time:
        return "closed_not_confirmed"

    return "closed_confirmed"


def today_ny_string() -> str:
    return datetime.now(NY_ZONE).strftime("%Y-%m-%d")


def now_utc_string() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def now_madrid_string() -> str:
    return datetime.now(MADRID_ZONE).strftime("%Y-%m-%d %H:%M:%S")


def yahoo_date_from_timestamp(timestamp: int) -> str:
    return datetime.fromtimestamp(
        timestamp,
        tz=NY_ZONE,
    ).strftime("%Y-%m-%d")


def download_yahoo_chart(ticker: str) -> list[dict]:
    period_seconds = YEARS_BACK * 365 * 24 * 60 * 60
    period1 = int(time.time()) - period_seconds
    period2 = int(time.time())

    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
        f"?period1={period1}&period2={period2}&interval=1d"
        f"&events=history&includeAdjustedClose=true"
    )

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        },
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        content = response.read().decode("utf-8")

    data = json.loads(content)

    chart = data.get("chart", {})
    error = chart.get("error")

    if error is not None:
        raise RuntimeError(f"Yahoo error para {ticker}: {error}")

    results = chart.get("result", [])

    if not results:
        raise RuntimeError(f"Sin resultados para {ticker}")

    result = results[0]

    timestamps = result.get("timestamp", [])
    quote = result.get("indicators", {}).get("quote", [{}])[0]

    opens = quote.get("open", [])
    highs = quote.get("high", [])
    lows = quote.get("low", [])
    closes = quote.get("close", [])
    volumes = quote.get("volume", [])

    rows = []

    for i, timestamp in enumerate(timestamps):
        try:
            open_price = opens[i]
            high_price = highs[i]
            low_price = lows[i]
            close_price = closes[i]
            volume = volumes[i]

            if (
                open_price is None
                or high_price is None
                or low_price is None
                or close_price is None
            ):
                continue

            date = yahoo_date_from_timestamp(timestamp)

            rows.append(
                {
                    "ticker": ticker,
                    "date": date,
                    "open": round(float(open_price), 6),
                    "high": round(float(high_price), 6),
                    "low": round(float(low_price), 6),
                    "close": round(float(close_price), 6),
                    "volume": int(volume or 0),
                }
            )
        except Exception as e:
            print(f"[WARN] Fila ignorada en {ticker}: {e}")

    if not rows:
        raise RuntimeError(f"Sin filas válidas para {ticker}")

    print(f"[OK] {ticker}: {len(rows)} filas")
    return rows


def remove_unconfirmed_today_rows(rows: list[dict]) -> list[dict]:
    today = today_ny_string()

    if market_close_confirmed():
        print("[INFO] Mercado cerrado confirmado. Se permite la vela de hoy.")
        return rows

    print(
        "[INFO] Mercado no cerrado/confirmado. "
        "Se elimina la vela provisional de hoy del CSV técnico."
    )

    filtered_rows = [
        row for row in rows
        if row["date"] < today
    ]

    removed_count = len(rows) - len(filtered_rows)

    print(f"[INFO] Filas provisionales eliminadas: {removed_count}")

    return filtered_rows


def build_latest_rows(
    raw_rows_by_ticker: dict[str, list[dict]],
    confirmed_rows_by_ticker: dict[str, list[dict]],
) -> list[dict]:
    latest_rows = []
    status = current_market_status()
    updated_at_utc = now_utc_string()
    updated_at_madrid = now_madrid_string()

    for ticker, raw_rows in raw_rows_by_ticker.items():
        if not raw_rows:
            continue

        latest = raw_rows[-1]
        confirmed_rows = confirmed_rows_by_ticker.get(ticker, [])

        confirmed_close = ""
        confirmed_close_date = ""
        change_from_close = ""
        change_from_close_percent = ""

        if confirmed_rows:
            confirmed = confirmed_rows[-1]
            confirmed_close = confirmed["close"]
            confirmed_close_date = confirmed["date"]

            if confirmed_close:
                diff = latest["close"] - float(confirmed_close)

                change_from_close = round(diff, 6)

                if float(confirmed_close) != 0:
                    change_from_close_percent = round(
                        diff / float(confirmed_close) * 100,
                        4,
                    )

        latest_rows.append(
            {
                "ticker": ticker,
                "price": latest["close"],
                "price_date": latest["date"],
                "updated_at_utc": updated_at_utc,
                "updated_at_madrid": updated_at_madrid,
                "market_status": status,
                "confirmed_close": confirmed_close,
                "confirmed_close_date": confirmed_close_date,
                "change_from_close": change_from_close,
                "change_from_close_percent": change_from_close_percent,
            }
        )

    latest_rows.sort(
        key=lambda row: row["ticker"]
    )

    return latest_rows


def group_rows_by_ticker(rows: list[dict]) -> dict[str, list[dict]]:
    grouped = {}

    for row in rows:
        ticker = row["ticker"]

        grouped.setdefault(ticker, [])
        grouped[ticker].append(row)

    for ticker_rows in grouped.values():
        ticker_rows.sort(
            key=lambda row: row["date"]
        )

    return grouped


def write_prices_daily(rows: list[dict]) -> None:
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    rows.sort(
        key=lambda row: (row["ticker"], row["date"])
    )

    with OUTPUT_FILE.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "ticker",
                "date",
                "open",
                "high",
                "low",
                "close",
                "volume",
            ],
        )

        writer.writeheader()
        writer.writerows(rows)


def write_latest_prices(rows: list[dict]) -> None:
    LATEST_FILE.parent.mkdir(parents=True, exist_ok=True)

    with LATEST_FILE.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "ticker",
                "price",
                "price_date",
                "updated_at_utc",
                "updated_at_madrid",
                "market_status",
                "confirmed_close",
                "confirmed_close_date",
                "change_from_close",
                "change_from_close_percent",
            ],
        )

        writer.writeheader()
        writer.writerows(rows)


def write_failed_tickers(failed: list[tuple[str, str]]) -> None:
    FAILED_FILE.parent.mkdir(parents=True, exist_ok=True)

    with FAILED_FILE.open("w", encoding="utf-8") as file:
        if not failed:
            file.write("Sin fallidos\n")
            return

        for ticker, reason in failed:
            file.write(f"{ticker} | {reason}\n")


def main() -> None:
    tickers = read_tickers()
    raw_all_rows = []
    failed = []

    print(f"Tickers encontrados: {len(tickers)}")
    print(", ".join(tickers))
    print(f"Estado mercado: {current_market_status()}")
    print(f"Actualizado UTC: {now_utc_string()}")
    print(f"Actualizado Madrid: {now_madrid_string()}")

    for index, ticker in enumerate(tickers, start=1):
        print(f"\n[{index}/{len(tickers)}] Descargando {ticker}...")

        try:
            rows = download_yahoo_chart(ticker)
            raw_all_rows.extend(rows)
        except Exception as e:
            reason = str(e)
            failed.append((ticker, reason))
            print(f"[ERROR] {ticker}: {reason}")

        time.sleep(REQUEST_DELAY_SECONDS)

    write_failed_tickers(failed)

    if not raw_all_rows:
        raise RuntimeError(
            "No se ha descargado ninguna fila."
        )

    raw_all_rows.sort(
        key=lambda row: (row["ticker"], row["date"])
    )

    confirmed_rows = remove_unconfirmed_today_rows(raw_all_rows)

    if not confirmed_rows:
        raise RuntimeError(
            "No hay filas confirmadas para generar prices_daily.csv."
        )

    raw_rows_by_ticker = group_rows_by_ticker(raw_all_rows)
    confirmed_rows_by_ticker = group_rows_by_ticker(confirmed_rows)

    latest_rows = build_latest_rows(
        raw_rows_by_ticker=raw_rows_by_ticker,
        confirmed_rows_by_ticker=confirmed_rows_by_ticker,
    )

    write_prices_daily(confirmed_rows)
    write_latest_prices(latest_rows)

    print(f"\nArchivo generado: {OUTPUT_FILE}")
    print(f"Total filas confirmadas: {len(confirmed_rows)}")

    print(f"\nArchivo generado: {LATEST_FILE}")
    print(f"Total precios actualizados: {len(latest_rows)}")

    print("\nComprobación rápida:")

    for symbol in ["SPY", "QQQ", "IWM", "XLK", "XLB"]:
        count = sum(
            1 for row in confirmed_rows
            if row["ticker"] == symbol
        )

        latest = next(
            (
                row for row in latest_rows
                if row["ticker"] == symbol
            ),
            None,
        )

        print(f"{symbol}: {count} filas confirmadas")

        if latest:
            print(
                f"  Precio actualizado: {latest['price']} "
                f"({latest['price_date']})"
            )
            print(
                f"  Cierre confirmado: {latest['confirmed_close']} "
                f"({latest['confirmed_close_date']})"
            )

    if failed:
        print(f"\nTickers fallidos: {len(failed)}")
        for ticker, reason in failed:
            print(f" - {ticker}: {reason}")
    else:
        print("\nTickers fallidos: 0")


if __name__ == "__main__":
    main()
