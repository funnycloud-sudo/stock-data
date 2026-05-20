import csv
import urllib.request
from datetime import datetime, timedelta
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


def stooq_symbol(ticker: str) -> str:
    return f"{ticker.lower()}.us"


def download_stooq_csv(ticker: str) -> list[dict]:
    symbol = stooq_symbol(ticker)
    url = f"https://stooq.com/q/d/l/?s={symbol}&i=d"

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
        },
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        content = response.read().decode("utf-8")

    lines = content.splitlines()

    if len(lines) <= 1:
        print(f"[WARN] Sin datos para {ticker}")
        print(content[:300])
        return []

    reader = csv.DictReader(lines)

    rows = []
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
    tickers = read_tickers()
    all_rows = []

    print(f"Tickers encontrados: {len(tickers)}")
    print(", ".join(tickers))

    for ticker in tickers:
        try:
            rows = download_stooq_csv(ticker)
            all_rows.extend(rows)
        except Exception as e:
            print(f"[ERROR] {ticker}: {e}")

    if not all_rows:
        raise RuntimeError(
            "No se ha descargado ninguna fila. Revisa tickers.txt o Stooq."
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
