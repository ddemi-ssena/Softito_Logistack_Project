"""Consume Kafka order events and write them idempotently to PostgreSQL."""

import argparse
import json
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path

from confluent_kafka import Consumer, KafkaError
from psycopg.types.json import Jsonb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "etl"))
from extract import connection_settings  # noqa: E402
import psycopg  # noqa: E402

TOPIC = "orders.events"
REQUIRED_FIELDS = {
    "event_id", "event_type", "order_id", "customer_id",
    "event_timestamp", "source", "payload",
}


def parse_args():
    parser = argparse.ArgumentParser(description="Persist Kafka order events in PostgreSQL.")
    parser.add_argument("--max-messages", type=int, default=200)
    parser.add_argument("--idle-timeout", type=float, default=30.0)
    parser.add_argument("--continuous", action="store_true", help="Keep consuming until the process is stopped")
    parser.add_argument("--bootstrap-servers", default=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"))
    parser.add_argument("--group-id", default="retailpulse-order-events")
    return parser.parse_args()


def validate_event(value):
    event = json.loads(value)
    if not isinstance(event, dict) or not REQUIRED_FIELDS.issubset(event):
        raise ValueError("event is missing required fields")
    uuid.UUID(event["event_id"])
    if not isinstance(event["order_id"], str) or not event["order_id"]:
        raise ValueError("order_id must be a non-empty string")
    if event["customer_id"] is not None and not isinstance(event["customer_id"], str):
        raise ValueError("customer_id must be a string or null")
    if not isinstance(event["event_type"], str) or not event["event_type"]:
        raise ValueError("event_type must be a non-empty string")
    if not isinstance(event["source"], str) or not event["source"]:
        raise ValueError("source must be a non-empty string")
    if not isinstance(event["payload"], dict):
        raise ValueError("payload must be a JSON object")
    if not isinstance(event["event_timestamp"], str):
        raise ValueError("event_timestamp must be an ISO-8601 string")
    timestamp = datetime.fromisoformat(event["event_timestamp"].replace("Z", "+00:00"))
    if timestamp.tzinfo is not None:
        timestamp = timestamp.replace(tzinfo=None)
    return event, timestamp


def main():
    args = parse_args()
    if args.max_messages < 1 or args.idle_timeout <= 0:
        raise SystemExit("--max-messages and --idle-timeout must be positive")

    consumer = Consumer({
        "bootstrap.servers": args.bootstrap_servers,
        "group.id": args.group_id,
        "auto.offset.reset": "earliest",
        "enable.auto.commit": False,
        "client.id": "retailpulse-consumer",
    })
    consumer.subscribe([TOPIC])
    inserted = duplicates = invalid = consumed = 0
    idle_seconds = 0.0

    try:
        with psycopg.connect(**connection_settings()) as connection:
            while args.continuous or (consumed < args.max_messages and idle_seconds < args.idle_timeout):
                message = consumer.poll(1.0)
                if message is None:
                    idle_seconds += 1.0
                    continue
                idle_seconds = 0.0
                if message.error():
                    if message.error().code() == KafkaError._PARTITION_EOF:
                        continue
                    print(f"Kafka message error: {message.error()}")
                    invalid += 1
                    consumed += 1
                    consumer.commit(message=message, asynchronous=False)
                    continue

                consumed += 1
                try:
                    event, timestamp = validate_event(message.value().decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
                    print(f"Skipped invalid event at offset {message.offset()}: {error}")
                    invalid += 1
                    consumer.commit(message=message, asynchronous=False)
                    continue

                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        
                        INSERT INTO streaming.order_events (
                            event_id, order_id, customer_id, event_type,
                            event_timestamp, payload
                        ) VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (event_id) DO NOTHING
                        """,
                        (
                            event["event_id"], event["order_id"], event["customer_id"],
                            event["event_type"], timestamp, Jsonb(event["payload"]),
                        ),
                    )
                    if cursor.rowcount:
                        inserted += 1
                    else:
                        duplicates += 1
                connection.commit()
                consumer.commit(message=message, asynchronous=False)
                if consumed % 100 == 0:
                    print(f"Consumed {consumed:,}: inserted={inserted:,}, duplicates={duplicates:,}, invalid={invalid:,}")
    finally:
        consumer.close()

    print(
        f"Summary: consumed={consumed:,}, inserted={inserted:,}, "
        f"duplicates_skipped={duplicates:,}, invalid_skipped={invalid:,}"
    )


if __name__ == "__main__":
    main()
