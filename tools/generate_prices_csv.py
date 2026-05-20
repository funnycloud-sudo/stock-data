import csv
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

TICKERS = [
    "NVDA",
    "AAPL",
    "MSFT",
    "GOOGL",
    "WMT",
]

YEARS_BACK = 5

OUTPUT_FILE = Path("assets/data/prices_daily.csv")


def stooq_symbol(ticker: str) -> str:
    return f"{ticker.lower()}.us"


def download_stooq_csv(ticker: str) -> list[dict]:
    symbol = stooq_symbol(ticker)

    # Usamos http porque algunos entornos fallan con https en urllib
    url = f"http://stooq.com/q/d/l/?s={symbol}&i=d"

    with urllib.request.urlopen(url, timeout=20) as response:
        content = response.read().decode("utf-8")

    lines = content.splitlines()

    if len(lines) <= 1:
        print(f"[WARN] Sin datos para {ticker}")
        return []

    rows = []
    reader = csv.DictReader(lines)

    min_date = datetime.now() - timedelta(days=365 * YEARS_BACK)

    for row in reader:
        try:
            date = datetime.strptime(row["Date"], "%Y-%m-%d")

            if date < min_date:
                continue

            rows.append(
                {
                    "ticker": ticker,
                    "date": row["Date"],
                    "open": row["Open"],
                    "high": row["High"],
                    "low": row["Low"],
                    "close": row["Close"],
                    "volume": row["Volume"],
                }
            )
        except Exception as e:
            print(f"[WARN] Fila ignorada en {ticker}: {e}")

    print(f"[OK] {ticker}: {len(rows)} filas")
    return rows


def main() -> None:
    all_rows = []

    for ticker in TICKERS:
        try:
            all_rows.extend(download_stooq_csv(ticker))
        except Exception as e:
            print(f"[ERROR] {ticker}: {e}")

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

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


if __name__ == "__main__":
    main()
