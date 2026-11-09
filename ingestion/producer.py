"""Publish Silver orders as replayable Kafka events."""

import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path

from confluent_kafka import Producer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "etl"))
from extract import connection_settings  # noqa: E402
import psycopg  # noqa: E402

TOPIC = "orders.events"


def build_event(order_id, customer_id, order_status, purchase_timestamp, order_amount, customer_state):
    timestamp = purchase_timestamp.isoformat()
    return {
        "event_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"retailpulse:order_created:{order_id}")),
        #Normalde uuid4() kullansaydık her çalıştırdığımızda rastgele bambaşka bir kimlik (ID) üretirdi.
        # Ama uuid5 (deterministik) kullandığımız için, aynı order_id geldiğinde her seferinde birebir 
        # aynı event_id'yi üretiyor. Neden? Çünkü aynı siparişi yanlışlıkla 2 kere gönderirsek, veritabanı
        # "Ben bu event_id'yi zaten kaydetmiştim" diyerek ikincisini reddedebilsin!
        "event_type": "order_created",
        "order_id": order_id,
        "customer_id": customer_id,
        "event_timestamp": timestamp,
        "source": "olist_historical_replay",
        "payload": {
            "order_status": order_status,
            "order_purchase_timestamp": timestamp,
            "total_amount": float(order_amount or 0),
            "customer_state": customer_state,
        },
    }


def parse_args():
    parser = argparse.ArgumentParser(description="Replay Silver orders to Kafka.")
    parser.add_argument("--limit", type=int, default=100, help="Maximum orders to publish")
    parser.add_argument("--offset", type=int, default=0, help="Skip this many earliest Silver orders") #offset atlama parametresi, veritabanındaki siparişleri belirli bir sayıda atlayarak başlamak için kullanılır. Örneğin, --offset 10 olarak ayarlanırsa, ilk 10 sipariş atlanır ve 11. siparişten itibaren yayınlanmaya başlanır. 
    parser.add_argument("--interval-ms", type=int, default=50, help="Delay between events")
    parser.add_argument("--bootstrap-servers", default=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"))
    return parser.parse_args()


def main():
    args = parse_args()
    if args.limit < 1 or args.offset < 0 or args.interval_ms < 0:
        raise SystemExit("--limit must be positive; --offset and --interval-ms cannot be negative")

    with psycopg.connect(**connection_settings()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT o.order_id, o.customer_id, o.order_status, o.order_purchase_timestamp,
                       COALESCE(i.total_amount, 0), c.customer_state
                FROM silver.orders AS o
                LEFT JOIN (
                    SELECT order_id, SUM(price + COALESCE(freight_value, 0)) AS total_amount
                    FROM silver.order_items
                    GROUP BY order_id
                ) AS i ON i.order_id = o.order_id
                LEFT JOIN silver.customers AS c ON c.customer_id = o.customer_id
                WHERE o.order_id IS NOT NULL AND o.order_purchase_timestamp IS NOT NULL
                ORDER BY o.order_purchase_timestamp, o.order_id
                LIMIT %s OFFSET %s
                """,
                (args.limit, args.offset),
            )
            orders = cursor.fetchall()

    producer = Producer({"bootstrap.servers": args.bootstrap_servers, "client.id": "retailpulse-producer"})
    delivered = 0
    delivery_errors = []

    def on_delivery(error, message):
        nonlocal delivered
        if error is not None:
            delivery_errors.append(str(error))
        else:
            delivered += 1

    for index, row in enumerate(orders, start=1):
        if args.interval_ms and index > 1:
            time.sleep(args.interval_ms / 1000)
        order_id, customer_id, order_status, purchase_timestamp, order_amount, customer_state = row
        event = build_event(order_id, customer_id, order_status, purchase_timestamp, order_amount, customer_state)
        producer.produce(
            TOPIC,
            key=order_id.encode("utf-8"),
            value=json.dumps(event, separators=(",", ":")).encode("utf-8"),
            on_delivery=on_delivery,
        )
        producer.poll(0)
        if index % 100 == 0 or index == len(orders):
            print(f"Queued {index:,}/{len(orders):,} events")

    remaining = producer.flush(30)
    print(f"Delivered: {delivered:,}; pending after flush: {remaining:,}")
    if delivery_errors:
        raise RuntimeError(f"Kafka delivery failures: {delivery_errors[:3]}")
    if remaining:
        raise TimeoutError(f"{remaining} Kafka messages were not delivered before timeout")


if __name__ == "__main__":
    main()
