import csv
import json
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

TICKERS_FILE = Path("assets/data/tickers.txt")
OUTPUT_FILE = Path("assets/data/prices_daily.csv")
FAILED_FILE = Path("assets/data/failed_tickers.txt")

YEARS_BACK = 10
REQUEST_DELAY_SECONDS = 0.4


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

            date = datetime.fromtimestamp(
                timestamp,
                tz=timezone.utc,
            ).strftime("%Y-%m-%d")

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
    all_rows = []
    failed = []

    print(f"Tickers encontrados: {len(tickers)}")
    print(", ".join(tickers))

    for index, ticker in enumerate(tickers, start=1):
        print(f"\n[{index}/{len(tickers)}] Descargando {ticker}...")

        try:
            rows = download_yahoo_chart(ticker)
            all_rows.extend(rows)
        except Exception as e:
            reason = str(e)
            failed.append((ticker, reason))
            print(f"[ERROR] {ticker}: {reason}")

        time.sleep(REQUEST_DELAY_SECONDS)

    write_failed_tickers(failed)

    if not all_rows:
        raise RuntimeError(
            "No se ha descargado ninguna fila."
        )

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    all_rows.sort(
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
        writer.writerows(all_rows)

    print(f"\nArchivo generado: {OUTPUT_FILE}")
    print(f"Total filas: {len(all_rows)}")

    print("\nComprobación rápida:")

    for symbol in ["SPY", "QQQ", "IWM", "XLK", "XLB"]:
        count = sum(1 for row in all_rows if row["ticker"] == symbol)
        print(f"{symbol}: {count} filas")

    if failed:
        print(f"\nTickers fallidos: {len(failed)}")
        for ticker, reason in failed:
            print(f" - {ticker}: {reason}")
    else:
        print("\nTickers fallidos: 0")


if __name__ == "__main__":
    main()
