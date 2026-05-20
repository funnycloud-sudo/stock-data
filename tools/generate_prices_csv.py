import csv
import json
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

TICKERS_FILE = Path("assets/data/tickers.txt")
OUTPUT_FILE = Path("assets/data/prices_daily.csv")

YEARS_BACK = 5


def read_tickers() -> list[str]:
    if not TICKERS_FILE.exists():
        raise FileNotFoundError(f"No existe {TICKERS_FILE}")

    tickers = []

    for line in TICKERS_FILE.read_text(encoding="utf-8").splitlines():
        ticker = line.strip().upper()

        if ticker and not ticker.startswith("#"):
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
            "User-Agent": "Mozilla/5.0",
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
        print(f"[WARN] Sin datos para {ticker}")
        return []

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

    print(f"[OK] {ticker}: {len(rows)} filas")
    return rows


def main() -> None:
    tickers = read_tickers()
    all_rows = []

    print(f"Tickers encontrados: {len(tickers)}")
    print(", ".join(tickers))

    for ticker in tickers:
        try:
            rows = download_yahoo_chart(ticker)
            all_rows.extend(rows)
        except Exception as e:
            print(f"[ERROR] {ticker}: {e}")

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

    print(f"Archivo generado: {OUTPUT_FILE}")
    print(f"Total filas: {len(all_rows)}")


if __name__ == "__main__":
    main()
