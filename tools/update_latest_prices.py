import csv
import json
import time
import urllib.request
from datetime import datetime, time as datetime_time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

TICKERS_FILE = Path("assets/data/tickers.txt")
DAILY_FILE = Path("assets/data/prices_daily.csv")
LATEST_FILE = Path("assets/data/latest_prices.csv")

REQUEST_DELAY_SECONDS = 0.25
NY_ZONE = ZoneInfo("America/New_York")
MADRID_ZONE = ZoneInfo("Europe/Madrid")

MARKET_CLOSE_CONFIRM_HOUR = 17
MARKET_CLOSE_CONFIRM_MINUTE = 30


def read_tickers() -> list[str]:
    tickers: list[str] = []
    seen: set[str] = set()

    for line in TICKERS_FILE.read_text(encoding="utf-8").splitlines():
        ticker = line.strip().upper()
        if not ticker or ticker.startswith("#") or ticker in seen:
            continue
        seen.add(ticker)
        tickers.append(ticker)

    if not tickers:
        raise ValueError("tickers.txt está vacío")

    return tickers


def confirmed_closes() -> dict[str, tuple[str, float]]:
    result: dict[str, tuple[str, float]] = {}

    with DAILY_FILE.open("r", encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        for row in reader:
            ticker = (row.get("ticker") or "").strip().upper()
            date = (row.get("date") or "").strip()
            close_raw = (row.get("close") or "").strip()
            if not ticker or not date or not close_raw:
                continue
            try:
                result[ticker] = (date, float(close_raw))
            except ValueError:
                continue

    return result


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


def now_utc_string() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def now_madrid_string() -> str:
    return datetime.now(MADRID_ZONE).strftime("%Y-%m-%d %H:%M:%S")


def yahoo_date(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, tz=NY_ZONE).strftime("%Y-%m-%d")


def fetch_latest_daily(ticker: str) -> tuple[str, float]:
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
        "?range=5d&interval=1d&events=history&includeAdjustedClose=true"
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

    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))

    chart = payload.get("chart", {})
    if chart.get("error") is not None:
        raise RuntimeError(f"Yahoo error para {ticker}: {chart['error']}")

    results = chart.get("result") or []
    if not results:
        raise RuntimeError(f"Sin resultados para {ticker}")

    result = results[0]
    timestamps = result.get("timestamp") or []
    quote = result.get("indicators", {}).get("quote", [{}])[0]
    closes = quote.get("close") or []

    candidates: list[tuple[str, float]] = []
    for index, timestamp in enumerate(timestamps):
        if index >= len(closes):
            continue
        close = closes[index]
        if close is None:
            continue
        candidates.append((yahoo_date(timestamp), float(close)))

    if not candidates:
        raise RuntimeError(f"Sin precio reciente válido para {ticker}")

    return candidates[-1]


def main() -> None:
    tickers = read_tickers()
    confirmed = confirmed_closes()
    status = current_market_status()
    updated_at_utc = now_utc_string()
    updated_at_madrid = now_madrid_string()

    rows: list[dict] = []
    failed: list[tuple[str, str]] = []

    print(f"Actualizando latest_prices.csv para {len(tickers)} tickers")
    print(f"Estado mercado: {status}")
    print(f"Actualizado Madrid: {updated_at_madrid}")

    for index, ticker in enumerate(tickers, start=1):
        try:
            price_date, price = fetch_latest_daily(ticker)
            confirmed_data = confirmed.get(ticker)

            confirmed_close = ""
            confirmed_close_date = ""
            change_from_close = ""
            change_from_close_percent = ""

            if confirmed_data is not None:
                confirmed_close_date, confirmed_close_value = confirmed_data
                confirmed_close = round(confirmed_close_value, 6)
                diff = price - confirmed_close_value
                change_from_close = round(diff, 6)
                if confirmed_close_value != 0:
                    change_from_close_percent = round(
                        diff / confirmed_close_value * 100,
                        4,
                    )

            rows.append(
                {
                    "ticker": ticker,
                    "price": round(price, 6),
                    "price_date": price_date,
                    "updated_at_utc": updated_at_utc,
                    "updated_at_madrid": updated_at_madrid,
                    "market_status": status,
                    "confirmed_close": confirmed_close,
                    "confirmed_close_date": confirmed_close_date,
                    "change_from_close": change_from_close,
                    "change_from_close_percent": change_from_close_percent,
                }
            )

            print(f"[{index}/{len(tickers)}] {ticker}: {price}")
        except Exception as error:
            failed.append((ticker, str(error)))
            print(f"[ERROR] {ticker}: {error}")

        time.sleep(REQUEST_DELAY_SECONDS)

    if not rows:
        raise RuntimeError("No se pudo actualizar ningún precio")

    rows.sort(key=lambda row: row["ticker"])

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

    print(f"latest_prices.csv actualizado: {len(rows)} tickers")
    if failed:
        print(f"Fallidos: {len(failed)}")
        for ticker, reason in failed:
            print(f" - {ticker}: {reason}")


if __name__ == "__main__":
    main()
