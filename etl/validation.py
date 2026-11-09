"""Report basic row-count, null-key, negative-value, and date checks."""

from extract import connection_settings
import psycopg


ROW_COUNT_QUERIES = {
    "orders": "SELECT COUNT(*) FROM silver.orders",
    "customers": "SELECT COUNT(*) FROM silver.customers",
    "order_items": "SELECT COUNT(*) FROM silver.order_items",
    "products": "SELECT COUNT(*) FROM silver.products",
    "order_payments": "SELECT COUNT(*) FROM silver.order_payments",
    "order_reviews": "SELECT COUNT(*) FROM silver.order_reviews",
}

NULL_KEY_QUERIES = {
    "orders": "SELECT COUNT(*) FROM silver.orders WHERE order_id IS NULL",
    "customers": "SELECT COUNT(*) FROM silver.customers WHERE customer_id IS NULL OR customer_unique_id IS NULL",
    "order_items": "SELECT COUNT(*) FROM silver.order_items WHERE order_id IS NULL OR order_item_id IS NULL",
    "products": "SELECT COUNT(*) FROM silver.products WHERE product_id IS NULL",
    "order_payments": "SELECT COUNT(*) FROM silver.order_payments WHERE order_id IS NULL OR payment_sequential IS NULL",
    "order_reviews": "SELECT COUNT(*) FROM silver.order_reviews WHERE review_id IS NULL",
}

CHECK_QUERIES = {
    "negative order item price": "SELECT COUNT(*) FROM silver.order_items WHERE price < 0",
    "negative freight value": "SELECT COUNT(*) FROM silver.order_items WHERE freight_value < 0",
    "negative payment value": "SELECT COUNT(*) FROM silver.order_payments WHERE payment_value < 0",
    "purchase after delivery": """
        SELECT COUNT(*) FROM silver.orders
        WHERE order_delivered_customer_date < order_purchase_timestamp
    """,
    "carrier date before purchase": """
        SELECT COUNT(*) FROM silver.orders
        WHERE order_delivered_carrier_date < order_purchase_timestamp
    """,
    "shipping limit before purchase": """
        SELECT COUNT(*) FROM silver.order_items i
        JOIN silver.orders o USING (order_id)
        WHERE i.shipping_limit_date < o.order_purchase_timestamp
    """,
    "review answer before creation": """
        SELECT COUNT(*) FROM silver.order_reviews
        WHERE review_answer_timestamp < review_creation_date
    """,
}


def main() -> None:
    with psycopg.connect(**connection_settings()) as connection:
        with connection.cursor() as cursor:
            print("Silver row counts:")
            for table, query in ROW_COUNT_QUERIES.items():
                cursor.execute(query)
                print(f"  silver.{table}: {cursor.fetchone()[0]:,}")

            print("NULL key checks (expected 0):")
            for table, query in NULL_KEY_QUERIES.items():
                cursor.execute(query)
                print(f"  silver.{table}: {cursor.fetchone()[0]:,}")

            print("Negative value and invalid date checks (expected 0):")
            for name, query in CHECK_QUERIES.items():
                cursor.execute(query)
                print(f"  {name}: {cursor.fetchone()[0]:,}")


if __name__ == "__main__":
    main()
