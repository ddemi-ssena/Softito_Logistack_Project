"""Build Gold dimensions, facts, and analytical marts from Silver data."""

import psycopg

from extract import connection_settings


TRUNCATE_SQL = """
TRUNCATE TABLE
    gold.mart_sales_daily,
    gold.mart_category_performance,
    gold.mart_delivery_performance,
    gold.mart_customer_rfm,
    gold.fact_order_items,
    gold.fact_orders,
    gold.dim_customers,
    gold.dim_products
"""

LOADS = (
    ("dim_customers", """
        INSERT INTO gold.dim_customers (
            customer_unique_id, customer_city, customer_state, customer_zip_code_prefix
        )
        SELECT DISTINCT ON (customer_unique_id)
               customer_unique_id, customer_city, customer_state, customer_zip_code_prefix
        FROM silver.customers
        WHERE customer_unique_id IS NOT NULL
        ORDER BY customer_unique_id, customer_id
    """),
    ("dim_products", """
        INSERT INTO gold.dim_products (
            product_id, product_category_name, product_weight_g,
            product_length_cm, product_height_cm, product_width_cm, product_photos_qty
        )
        SELECT product_id, product_category_name, product_weight_g,
               product_length_cm, product_height_cm, product_width_cm, product_photos_qty
        FROM silver.products
        WHERE product_id IS NOT NULL
    """),
    ("fact_orders", """
        WITH item_totals AS (
            SELECT order_id, SUM(price) AS total_product_amount,
                   SUM(freight_value) AS total_freight
            FROM silver.order_items
            GROUP BY order_id
        ),
        payment_totals AS (
            SELECT order_id, SUM(payment_value) AS total_payment
            FROM silver.order_payments
            GROUP BY order_id
        ),
        customer_map AS (
            SELECT DISTINCT ON (customer_id) customer_id, customer_unique_id
            FROM silver.customers
            WHERE customer_id IS NOT NULL
            ORDER BY customer_id, customer_unique_id
        )
        INSERT INTO gold.fact_orders (
            order_id, customer_id, customer_unique_id,
            order_purchase_timestamp, order_approved_at,
            order_delivered_customer_date, order_estimated_delivery_date,
            order_status, total_product_amount, total_freight, total_payment,
            delivery_days, delivery_delay_days
        )
        SELECT o.order_id, o.customer_id, cm.customer_unique_id,
               o.order_purchase_timestamp, o.order_approved_at,
               o.order_delivered_customer_date, o.order_estimated_delivery_date,
               o.order_status, COALESCE(i.total_product_amount, 0),
               COALESCE(i.total_freight, 0), COALESCE(p.total_payment, 0),
               CASE WHEN o.order_delivered_customer_date IS NOT NULL
                    THEN EXTRACT(EPOCH FROM (o.order_delivered_customer_date - o.order_purchase_timestamp)) / 86400.0
               END,
               CASE WHEN o.order_delivered_customer_date IS NOT NULL
                      AND o.order_estimated_delivery_date IS NOT NULL
                    THEN EXTRACT(EPOCH FROM (o.order_delivered_customer_date - o.order_estimated_delivery_date)) / 86400.0
               END
        FROM silver.orders AS o
        LEFT JOIN item_totals AS i ON i.order_id = o.order_id
        LEFT JOIN payment_totals AS p ON p.order_id = o.order_id
        LEFT JOIN customer_map AS cm ON cm.customer_id = o.customer_id
    """),
    ("fact_order_items", """
        INSERT INTO gold.fact_order_items (
            order_id, order_item_id, product_id, seller_id,
            shipping_limit_date, price, freight_value
        )
        SELECT i.order_id, i.order_item_id, i.product_id, i.seller_id,
               i.shipping_limit_date, i.price, i.freight_value
        FROM silver.order_items AS i
        INNER JOIN silver.orders AS o ON o.order_id = i.order_id
    """),
    ("mart_sales_daily", """
        INSERT INTO gold.mart_sales_daily (
            sales_date, approved_revenue, order_count, average_order_value
        )
        SELECT order_purchase_timestamp::date,
               SUM(total_product_amount), COUNT(*), AVG(total_product_amount)
        FROM gold.fact_orders
        WHERE order_status IN ('approved', 'delivered')
        GROUP BY order_purchase_timestamp::date
    """),
    ("mart_category_performance", """
        INSERT INTO gold.mart_category_performance (
            product_category_name, total_revenue, units_sold, average_product_price
        )
        SELECT COALESCE(NULLIF(BTRIM(p.product_category_name), ''), '(unknown)'),
               SUM(i.price), COUNT(*), AVG(i.price)
        FROM gold.fact_order_items AS i
        INNER JOIN gold.fact_orders AS o ON o.order_id = i.order_id
        LEFT JOIN gold.dim_products AS p ON p.product_id = i.product_id
        WHERE o.order_status IN ('approved', 'delivered')
        GROUP BY COALESCE(NULLIF(BTRIM(p.product_category_name), ''), '(unknown)')
    """),
    ("mart_delivery_performance", """
        INSERT INTO gold.mart_delivery_performance (
            customer_state, order_month, average_delivery_days,
            average_actual_vs_estimated_days, late_delivery_rate, orders_with_delivery
        )
        SELECT COALESCE(c.customer_state, '(unknown)'),
               DATE_TRUNC('month', o.order_purchase_timestamp)::date,
               AVG(o.delivery_days), AVG(o.delivery_delay_days),
               COUNT(*) FILTER (
                   WHERE o.order_delivered_customer_date > o.order_estimated_delivery_date
               )::numeric / NULLIF(COUNT(o.order_delivered_customer_date), 0),
               COUNT(o.order_delivered_customer_date)
        FROM gold.fact_orders AS o
        LEFT JOIN gold.dim_customers AS c ON c.customer_unique_id = o.customer_unique_id
        GROUP BY COALESCE(c.customer_state, '(unknown)'),
                 DATE_TRUNC('month', o.order_purchase_timestamp)::date
    """),
    ("mart_customer_rfm", """
        WITH reference AS (
            SELECT MAX(order_purchase_timestamp)::date + 1 AS reference_date
            FROM gold.fact_orders
        ),
        customer_activity AS (
            SELECT customer_unique_id,
                   MAX(order_purchase_timestamp)::date AS last_order_date,
                   COUNT(*) AS frequency,
                   SUM(total_product_amount) AS monetary
            FROM gold.fact_orders
            WHERE customer_unique_id IS NOT NULL
              AND order_status IN ('approved', 'delivered')
            GROUP BY customer_unique_id
        )
        INSERT INTO gold.mart_customer_rfm (
            customer_unique_id, recency_days, frequency, monetary, reference_date
        )
        SELECT a.customer_unique_id,
               (r.reference_date - a.last_order_date)::integer,
               a.frequency, a.monetary, r.reference_date
        FROM customer_activity AS a
        CROSS JOIN reference AS r
    """),
)


def main() -> None:
    with psycopg.connect(**connection_settings()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(TRUNCATE_SQL)
            for table_name, statement in LOADS:
                cursor.execute(statement)
                print(f"gold.{table_name}: {cursor.rowcount:,} rows loaded")


if __name__ == "__main__":
    main()
