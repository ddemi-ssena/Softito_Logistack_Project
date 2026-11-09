"""Bulk-load the six MVP Olist CSV files into PostgreSQL's bronze schema."""

import csv
import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"

TABLES = {
    "olist_orders_dataset.csv": "orders",
    "olist_customers_dataset.csv": "customers",
    "olist_order_items_dataset.csv": "order_items",
    "olist_products_dataset.csv": "products",
    "olist_order_payments_dataset.csv": "order_payments",
    "olist_order_reviews_dataset.csv": "order_reviews",
}


def connection_settings():
    """Read PostgreSQL connection parameters from the repository .env file."""
    load_dotenv(ROOT / ".env")
    required = ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD")
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise RuntimeError(f"Missing required .env settings: {', '.join(missing)}")
    return {
        "host": os.environ["DB_HOST"],
        "port": int(os.environ["DB_PORT"]),
        "dbname": os.environ["DB_NAME"],
        "user": os.environ["DB_USER"],
        "password": os.environ["DB_PASSWORD"],
    }


def load_csv(connection, csv_path: Path, table_name: str) -> int:
    """COPY one headered CSV into its matching bronze table and return row count."""
    with csv_path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.reader(source)
        columns = next(reader)
        column_sql = ", ".join(f'"{column}"' for column in columns)
        copy_sql = (
            f"COPY bronze.{table_name} ({column_sql}) "
            "FROM STDIN"
        )
        row_count = 0
        with connection.cursor() as cursor:
            with cursor.copy(copy_sql) as copy:
                for row in reader:
                    copy.write_row([value if value != "" else None for value in row])
                    row_count += 1
        return row_count


def main() -> None:
    settings = connection_settings()
    with psycopg.connect(**settings) as connection:
        for filename, table_name in TABLES.items():
            csv_path = RAW_DIR / filename
            if not csv_path.is_file():
                raise FileNotFoundError(f"Required CSV not found: {csv_path}")
            count = load_csv(connection, csv_path, table_name)
            print(f"bronze.{table_name}: {count:,} rows loaded")


if __name__ == "__main__":
    main()
