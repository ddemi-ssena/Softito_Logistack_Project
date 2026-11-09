"""Clean and standardize Bronze tables into the date-scoped Silver layer."""

from extract import connection_settings
import psycopg


START_DATE = "2017-01-01 00:00:00"
END_DATE_EXCLUSIVE = "2018-09-01 00:00:00"

TRUNCATE_SQL = """
TRUNCATE TABLE
    silver.order_reviews,
    silver.order_payments,
    silver.order_items,
    silver.orders,
    silver.customers,
    silver.products
"""

TRANSFORMS = (
    ("orders", """
        INSERT INTO silver.orders (
            order_id, customer_id, order_status, order_purchase_timestamp,
            order_approved_at, order_delivered_carrier_date,
            order_delivered_customer_date, order_estimated_delivery_date
        )
        SELECT NULLIF(BTRIM(order_id), ''), NULLIF(BTRIM(customer_id), ''),
               LOWER(NULLIF(BTRIM(order_status), '')), order_purchase_timestamp,
               order_approved_at, order_delivered_carrier_date,
               order_delivered_customer_date, order_estimated_delivery_date
        FROM bronze.orders
        WHERE order_purchase_timestamp >= %s::timestamp
          AND order_purchase_timestamp < %s::timestamp
    """),
    ("customers", """
        INSERT INTO silver.customers (
            customer_id, customer_unique_id, customer_zip_code_prefix,
            customer_city, customer_state
        )
        SELECT NULLIF(BTRIM(customer_id), ''),
               NULLIF(BTRIM(customer_unique_id), ''),
               CASE WHEN customer_zip_code_prefix IS NULL THEN NULL
                    ELSE LPAD(customer_zip_code_prefix::text, 5, '0') END,
               LOWER(NULLIF(BTRIM(customer_city), '')),
               UPPER(NULLIF(BTRIM(customer_state), ''))
        FROM bronze.customers
    """),
    ("order_items", """
        INSERT INTO silver.order_items (
            order_id, order_item_id, product_id, seller_id,
            shipping_limit_date, price, freight_value
        )
        SELECT NULLIF(BTRIM(i.order_id), ''), i.order_item_id,
               NULLIF(BTRIM(i.product_id), ''), NULLIF(BTRIM(i.seller_id), ''),
               i.shipping_limit_date, i.price, i.freight_value
        FROM bronze.order_items AS i
        INNER JOIN silver.orders AS o ON o.order_id = NULLIF(BTRIM(i.order_id), '')
    """),
    ("products", """
        INSERT INTO silver.products (
            product_id, product_category_name, product_name_length,
            product_description_length, product_photos_qty, product_weight_g,
            product_length_cm, product_height_cm, product_width_cm
        )
        SELECT NULLIF(BTRIM(product_id), ''),
               LOWER(NULLIF(BTRIM(product_category_name), '')),
               product_name_lenght, product_description_lenght,
               product_photos_qty, product_weight_g, product_length_cm,
               product_height_cm, product_width_cm
        FROM bronze.products
    """),
    ("order_payments", """
        INSERT INTO silver.order_payments (
            order_id, payment_sequential, payment_type,
            payment_installments, payment_value
        )
        SELECT NULLIF(BTRIM(p.order_id), ''), p.payment_sequential,
               LOWER(NULLIF(BTRIM(p.payment_type), '')),
               p.payment_installments, p.payment_value
        FROM bronze.order_payments AS p
        INNER JOIN silver.orders AS o ON o.order_id = NULLIF(BTRIM(p.order_id), '')
    """),
    ("order_reviews", """
        INSERT INTO silver.order_reviews (
            review_id, order_id, review_score, review_comment_title,
            review_comment_message, review_creation_date, review_answer_timestamp
        )
        SELECT NULLIF(BTRIM(r.review_id), ''), NULLIF(BTRIM(r.order_id), ''),
               r.review_score, NULLIF(BTRIM(r.review_comment_title), ''),
               NULLIF(BTRIM(r.review_comment_message), ''),
               r.review_creation_date, r.review_answer_timestamp
        FROM bronze.order_reviews AS r
        INNER JOIN silver.orders AS o ON o.order_id = NULLIF(BTRIM(r.order_id), '')
    """),
)


def main() -> None:
    with psycopg.connect(**connection_settings()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*) FILTER (
                           WHERE order_purchase_timestamp >= %s::timestamp
                             AND order_purchase_timestamp < %s::timestamp
                       ),
                       COUNT(*) FILTER (
                           WHERE order_purchase_timestamp < %s::timestamp
                              OR order_purchase_timestamp >= %s::timestamp
                              OR order_purchase_timestamp IS NULL
                       )
                FROM bronze.orders
                """,
                (START_DATE, END_DATE_EXCLUSIVE, START_DATE, END_DATE_EXCLUSIVE),
            )
            in_range, out_of_range = cursor.fetchone()
            cursor.execute(TRUNCATE_SQL)
            for table_name, statement in TRANSFORMS:
                if table_name == "orders":
                    cursor.execute(statement, (START_DATE, END_DATE_EXCLUSIVE))
                else:
                    cursor.execute(statement)
                print(f"silver.{table_name}: {cursor.rowcount:,} rows transformed")
        print(f"Orders in analytic range: {in_range:,}")
        print(f"Orders outside analytic range: {out_of_range:,}")


if __name__ == "__main__":
    main()
