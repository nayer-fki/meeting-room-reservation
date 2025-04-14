import os
import logging
import json
from kafka import KafkaConsumer
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Environment variables
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS")

# Kafka consumer setup
consumer = KafkaConsumer(
    'reservation-events',
    bootstrap_servers=[KAFKA_BOOTSTRAP_SERVERS],
    auto_offset_reset='earliest',
    enable_auto_commit=True,
    group_id='notification-service',
    value_deserializer=lambda x: json.loads(x.decode('utf-8')),
    session_timeout_ms=30000,  # Increase session timeout to 30 seconds
    heartbeat_interval_ms=10000  # Send heartbeats every 10 seconds
)

logger.info("Successfully connected to Kafka consumer")
logger.info("Starting to consume reservation events...")

# Consume messages
for message in consumer:
    event = message.value
    logger.info(f"Received event: {event}")
    logger.info(
        f"Notification: Reservation {event['reservation_id']} created for user {event['user_id']} "
        f"in room {event['room_id']} from {event['start_time']} to {event['end_time']}"
    )