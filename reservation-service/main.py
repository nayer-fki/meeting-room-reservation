from fastapi import FastAPI, HTTPException, Depends, Request
from pydantic import BaseModel
from datetime import datetime
import os
import logging
import jwt
import requests
import time
from kafka import KafkaProducer
import json
import psycopg2
from psycopg2.extras import RealDictCursor

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI()

# Load environment variables
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL must be set in environment variables")

KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS")
if not KAFKA_BOOTSTRAP_SERVERS:
    raise ValueError("KAFKA_BOOTSTRAP_SERVERS must be set in environment variables")

JWT_SECRET = os.getenv("JWT_SECRET")
if not JWT_SECRET:
    raise ValueError("JWT_SECRET must be set in environment variables")
JWT_ALGORITHM = "HS256"

# Kafka producer setup with retry logic
def init_kafka_producer(bootstrap_servers, retries=20, delay=5):
    for attempt in range(retries):
        try:
            producer = KafkaProducer(
                bootstrap_servers=[bootstrap_servers],
                value_serializer=lambda v: json.dumps(v).encode('utf-8'),
                retries=5,
                request_timeout_ms=10000,
                max_block_ms=10000,
                connections_max_idle_ms=300000
            )
            producer.send('test-topic', {'test': 'connection'}).get(timeout=5)
            logger.info("Successfully connected to Kafka")
            return producer
        except Exception as e:
            logger.warning(f"Failed to connect to Kafka (attempt {attempt + 1}/{retries}): {str(e)}")
            if attempt < retries - 1:
                time.sleep(delay)
            else:
                raise Exception(f"Failed to connect to Kafka after {retries} attempts: {str(e)}")

try:
    producer = init_kafka_producer(KAFKA_BOOTSTRAP_SERVERS)
except Exception as e:
    logger.error(f"Failed to initialize Kafka producer: {str(e)}")
    raise e

# PostgreSQL connection with retry logic
def get_db_connection(retries=20, delay=5):
    for attempt in range(retries):
        try:
            conn = psycopg2.connect(
                DATABASE_URL,
                cursor_factory=RealDictCursor
            )
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.close()
            logger.info("Successfully connected to PostgreSQL")
            return conn
        except psycopg2.OperationalError as e:
            logger.warning(f"Failed to connect to PostgreSQL (attempt {attempt + 1}/{retries}): {str(e)}")
            if attempt < retries - 1:
                time.sleep(delay)
            else:
                raise Exception(f"Failed to connect to PostgreSQL after {retries} attempts: {str(e)}")

# Pydantic models
class ReservationCreate(BaseModel):
    room_id: int
    start_time: datetime
    end_time: datetime
    priority: int = 0

class ReservationUpdate(BaseModel):
    status: str

class Notification(BaseModel):
    id: int
    user_id: str
    reservation_id: int
    message: str
    is_read: bool
    created_at: datetime

# Helper to get current user from JWT
async def get_current_user(request: Request):
    jwt_token = request.cookies.get("jwt_token")
    if not jwt_token:
        raise HTTPException(status_code=401, detail="Not logged in")
    try:
        payload = jwt.decode(jwt_token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except Exception as e:
        logger.error(f"Invalid token: {str(e)}")
        raise HTTPException(status_code=401, detail="Invalid token")

# Helper to check if user is admin
def check_admin(user):
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

# Check room availability with enhanced retry logic and logging
def check_room_availability(room_id: int, start_time: datetime, end_time: datetime, request: Request, retries=5, delay=1):
    jwt_token = request.cookies.get("jwt_token")
    if not jwt_token:
        raise HTTPException(status_code=401, detail="Not logged in")

    salle_service_url = "http://salle-service:8002"
    for attempt in range(retries):
        try:
            logger.info(f"Checking room availability for room_id: {room_id} (attempt {attempt + 1}/{retries})")
            response = requests.get(
                f"{salle_service_url}/rooms/{room_id}",
                headers={"Cookie": f"jwt_token={jwt_token}"},
                timeout=5
            )
            logger.info(f"Response from salle-service: {response.status_code} - {response.text}")
            if response.status_code != 200:
                raise HTTPException(status_code=404, detail="Room not found")
            room = response.json()
            logger.info(f"Room found: {room}")
            break
        except requests.RequestException as e:
            logger.warning(f"Error querying salle-service (attempt {attempt + 1}/{retries}): {str(e)}")
            if attempt < retries - 1:
                time.sleep(delay)
            else:
                raise HTTPException(status_code=503, detail=f"Failed to communicate with salle-service after {retries} attempts: {str(e)}")

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        logger.info(f"Checking for overlapping reservations for room_id: {room_id}")
        cursor.execute(
            """
            SELECT id FROM reservations
            WHERE room_id = %s
            AND start_time < %s
            AND end_time > %s
            AND status = 'accepted'
            """,
            (room_id, end_time.isoformat(), start_time.isoformat())
        )
        overlapping_reservations = cursor.fetchall()
        logger.info(f"Overlapping reservations: {overlapping_reservations}")
        if overlapping_reservations:
            raise HTTPException(status_code=400, detail="Room is not available for the selected time slot")
        return True
    finally:
        cursor.close()
        conn.close()

# Create a notification
def create_notification(user_id: str, reservation_id: int, message: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        logger.info(f"Creating notification for user_id: {user_id}, reservation_id: {reservation_id}")
        cursor.execute(
            """
            INSERT INTO notifications (user_id, reservation_id, message)
            VALUES (%s, %s, %s)
            RETURNING id
            """,
            (user_id, reservation_id, message)
        )
        notification_id = cursor.fetchone()["id"]
        conn.commit()
        logger.info(f"Created notification with id: {notification_id}")

        event = {
            "event_type": "notification_created",
            "notification_id": notification_id,
            "user_id": user_id,
            "reservation_id": reservation_id,
            "message": message,
            "timestamp": datetime.utcnow().isoformat()
        }
        logger.info(f"Sending Kafka event: {event}")
        producer.send("notification-events", event)
        producer.flush()
    finally:
        cursor.close()
        conn.close()

# Create a reservation
@app.post("/reservations/", response_model=dict)
async def create_reservation(reservation: ReservationCreate, request: Request, user: dict = Depends(get_current_user)):
    if reservation.start_time >= reservation.end_time:
        raise HTTPException(status_code=400, detail="End time must be after start time")
    if reservation.start_time < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Start time cannot be in the past")

    check_room_availability(reservation.room_id, reservation.start_time, reservation.end_time, request)

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        logger.info(f"Creating reservation for user_id: {user['sub']}, room_id: {reservation.room_id}")
        cursor.execute(
            """
            INSERT INTO reservations (user_id, room_id, start_time, end_time, priority)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id, user_id, room_id, start_time, end_time, status, priority, created_at
            """,
            (user["sub"], reservation.room_id, reservation.start_time.isoformat(), reservation.end_time.isoformat(), reservation.priority)
        )
        new_reservation = cursor.fetchone()
        conn.commit()
        logger.info(f"Created reservation: {new_reservation}")

        event = {
            "event_type": "reservation_created",
            "reservation_id": new_reservation["id"],
            "user_id": user["sub"],
            "room_id": new_reservation["room_id"],
            "start_time": new_reservation["start_time"].isoformat(),
            "end_time": new_reservation["end_time"].isoformat(),
            "timestamp": datetime.utcnow().isoformat()
        }
        logger.info(f"Sending Kafka event: {event}")
        producer.send("reservation-events", event)
        producer.flush()

        create_notification(user["sub"], new_reservation["id"], "Your reservation request has been submitted and is pending approval.")

        # Convert datetime objects to strings for the response
        response_reservation = dict(new_reservation)
        response_reservation["start_time"] = new_reservation["start_time"].isoformat()
        response_reservation["end_time"] = new_reservation["end_time"].isoformat()
        response_reservation["created_at"] = new_reservation["created_at"].isoformat()

        return response_reservation
    except Exception as e:
        logger.error(f"Error creating reservation: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to create reservation")
    finally:
        cursor.close()
        conn.close()

# Get all reservations for the authenticated user
@app.get("/reservations/", response_model=list)
async def get_reservations(user: dict = Depends(get_current_user)):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        logger.info(f"Fetching reservations for user_id: {user['sub']}")
        cursor.execute(
            """
            SELECT id, user_id, room_id, start_time, end_time, status, priority, created_at
            FROM reservations
            WHERE user_id = %s
            ORDER BY created_at DESC
            """,
            (user["sub"],)
        )
        reservations = cursor.fetchall()
        logger.info(f"Found reservations: {reservations}")
        # Convert datetime objects to strings
        return [
            {
                **dict(reservation),
                "start_time": reservation["start_time"].isoformat(),
                "end_time": reservation["end_time"].isoformat(),
                "created_at": reservation["created_at"].isoformat()
            }
            for reservation in reservations
        ]
    except Exception as e:
        logger.error(f"Error fetching reservations: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to fetch reservations")
    finally:
        cursor.close()
        conn.close()

# Admin endpoint to get all reservations
@app.get("/admin/reservations/", response_model=list)
async def get_all_reservations(user: dict = Depends(get_current_user)):
    check_admin(user)
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        logger.info("Fetching all reservations (admin)")
        cursor.execute(
            """
            SELECT id, user_id, room_id, start_time, end_time, status, priority, created_at
            FROM reservations
            ORDER BY created_at DESC
            """,
        )
        reservations = cursor.fetchall()
        logger.info(f"Found reservations: {reservations}")
        # Convert datetime objects to strings
        return [
            {
                **dict(reservation),
                "start_time": reservation["start_time"].isoformat(),
                "end_time": reservation["end_time"].isoformat(),
                "created_at": reservation["created_at"].isoformat()
            }
            for reservation in reservations
        ]
    except Exception as e:
        logger.error(f"Error fetching all reservations: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to fetch all reservations")
    finally:
        cursor.close()
        conn.close()

# Update reservation status (accept/refuse)
@app.put("/reservations/{reservation_id}/status", response_model=dict)
async def update_reservation_status(reservation_id: int, update: ReservationUpdate, user: dict = Depends(get_current_user)):
    check_admin(user)
    if update.status not in ["accepted", "refused"]:
        raise HTTPException(status_code=400, detail="Invalid status")
    
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        logger.info(f"Updating reservation status for reservation_id: {reservation_id} to {update.status}")
        cursor.execute(
            """
            UPDATE reservations
            SET status = %s
            WHERE id = %s
            RETURNING id, user_id, room_id, start_time, end_time, status, priority, created_at
            """,
            (update.status, reservation_id)
        )
        updated_reservation = cursor.fetchone()
        if not updated_reservation:
            raise HTTPException(status_code=404, detail="Reservation not found")
        conn.commit()
        logger.info(f"Updated reservation: {updated_reservation}")

        event = {
            "event_type": f"reservation_{update.status}",
            "reservation_id": updated_reservation["id"],
            "user_id": updated_reservation["user_id"],
            "room_id": updated_reservation["room_id"],
            "start_time": updated_reservation["start_time"].isoformat(),
            "end_time": updated_reservation["end_time"].isoformat(),
            "timestamp": datetime.utcnow().isoformat()
        }
        logger.info(f"Sending Kafka event: {event}")
        producer.send("reservation-events", event)
        producer.flush()

        message = f"Your reservation has been {update.status}."
        create_notification(updated_reservation["user_id"], updated_reservation["id"], message)

        # Convert datetime objects to strings for the response
        response_reservation = dict(updated_reservation)
        response_reservation["start_time"] = updated_reservation["start_time"].isoformat()
        response_reservation["end_time"] = updated_reservation["end_time"].isoformat()
        response_reservation["created_at"] = updated_reservation["created_at"].isoformat()

        return response_reservation
    except Exception as e:
        logger.error(f"Error updating reservation status: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to update reservation status")
    finally:
        cursor.close()
        conn.close()

# Delete a reservation
@app.delete("/reservations/{reservation_id}", response_model=dict)
async def delete_reservation(reservation_id: int, user: dict = Depends(get_current_user)):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        logger.info(f"Deleting reservation_id: {reservation_id} for user_id: {user['sub']}")
        cursor.execute(
            """
            SELECT id, user_id, room_id, start_time, end_time
            FROM reservations
            WHERE id = %s AND user_id = %s
            """,
            (reservation_id, user["sub"])
        )
        reservation = cursor.fetchone()
        if not reservation:
            raise HTTPException(status_code=404, detail="Reservation not found or not authorized")

        cursor.execute("DELETE FROM reservations WHERE id = %s", (reservation_id,))
        conn.commit()
        logger.info(f"Deleted reservation_id: {reservation_id}")

        event = {
            "event_type": "reservation_deleted",
            "reservation_id": reservation["id"],
            "user_id": user["sub"],
            "room_id": reservation["room_id"],
            "start_time": reservation["start_time"].isoformat(),
            "end_time": reservation["end_time"].isoformat(),
            "timestamp": datetime.utcnow().isoformat()
        }
        logger.info(f"Sending Kafka event: {event}")
        producer.send("reservation-events", event)
        producer.flush()

        return {"message": "Reservation deleted successfully"}
    except Exception as e:
        logger.error(f"Error deleting reservation: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to delete reservation")
    finally:
        cursor.close()
        conn.close()

# Get notifications for the user
@app.get("/notifications/", response_model=list)
async def get_notifications(user: dict = Depends(get_current_user)):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        logger.info(f"Fetching notifications for user_id: {user['sub']}")
        cursor.execute(
            """
            SELECT id, user_id, reservation_id, message, is_read, created_at
            FROM notifications
            WHERE user_id = %s
            ORDER BY created_at DESC
            """,
            (user["sub"],)
        )
        notifications = cursor.fetchall()
        logger.info(f"Found notifications: {notifications}")
        # Convert datetime objects to strings
        return [
            {
                **dict(notification),
                "created_at": notification["created_at"].isoformat()
            }
            for notification in notifications
        ]
    except Exception as e:
        logger.error(f"Error fetching notifications: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to fetch notifications")
    finally:
        cursor.close()
        conn.close()

# Mark a notification as read
@app.put("/notifications/{notification_id}/read", response_model=dict)
async def mark_notification_read(notification_id: int, user: dict = Depends(get_current_user)):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        logger.info(f"Marking notification_id: {notification_id} as read for user_id: {user['sub']}")
        cursor.execute(
            """
            UPDATE notifications
            SET is_read = TRUE
            WHERE id = %s AND user_id = %s
            RETURNING id, user_id, reservation_id, message, is_read, created_at
            """,
            (notification_id, user["sub"])
        )
        updated_notification = cursor.fetchone()
        if not updated_notification:
            raise HTTPException(status_code=404, detail="Notification not found or not authorized")
        conn.commit()
        logger.info(f"Updated notification: {updated_notification}")

        # Convert datetime objects to strings for the response
        response_notification = dict(updated_notification)
        response_notification["created_at"] = updated_notification["created_at"].isoformat()

        return response_notification
    except Exception as e:
        logger.error(f"Error marking notification as read: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to mark notification as read")
    finally:
        cursor.close()
        conn.close()

@app.get("/health")
async def health_check():
    health_status = {"status": "healthy", "details": {}}

    # Check database connectivity
    retries, delay = 5, 5
    for attempt in range(retries):
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            health_status["details"]["database"] = "healthy"
            cursor.close()
            conn.close()
            break
        except Exception as e:
            logger.warning(f"Database health check retry {attempt + 1}/{retries}: {str(e)}")
            if attempt == retries - 1:
                logger.error(f"Database health check failed: {str(e)}")
                health_status["details"]["database"] = f"unhealthy: {str(e)}"
                health_status["status"] = "unhealthy"
            time.sleep(delay)

    # Check Kafka connectivity
    for attempt in range(retries):
        try:
            producer.bootstrap_connected()
            health_status["details"]["kafka"] = "healthy"
            break
        except Exception as e:
            logger.warning(f"Kafka health check retry {attempt + 1}/{retries}: {str(e)}")
            if attempt == retries - 1:
                logger.error(f"Kafka health check failed: {str(e)}")
                health_status["details"]["kafka"] = f"unhealthy: {str(e)}"
                health_status["status"] = "unhealthy"
            time.sleep(delay)

    logger.info(f"Health check result: {health_status}")
    if health_status["status"] == "unhealthy":
        raise HTTPException(status_code=503, detail=health_status)
    return health_status

@app.get("/")
async def root():
    return {"message": "Reservation Service is running"}