import os
import logging
from datetime import datetime
from fastapi import FastAPI, HTTPException, Depends, Request
from pydantic import BaseModel
import jwt
import psycopg2
from psycopg2.extras import RealDictCursor
from kafka import KafkaProducer
import json
import httpx
from dotenv import load_dotenv
import time
from typing import Optional, Tuple

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Environment variables
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL must be set in environment variables")

KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
if not KAFKA_BOOTSTRAP_SERVERS:
    raise ValueError("KAFKA_BOOTSTRAP_SERVERS must be set in environment variables")

JWT_SECRET = os.getenv("JWT_SECRET")
if not JWT_SECRET:
    raise ValueError("JWT_SECRET must be set in environment variables")

JWT_ALGORITHM = "HS256"

logger.info(f"Using DATABASE_URL: {DATABASE_URL}")
logger.info(f"Using KAFKA_BOOTSTRAP_SERVERS: {KAFKA_BOOTSTRAP_SERVERS}")
logger.info(f"Using JWT_SECRET: {JWT_SECRET}")

# FastAPI app
app = FastAPI()

# Kafka producer setup with retry logic
def init_kafka_producer(bootstrap_servers, retries=5, delay=10):
    for attempt in range(retries):
        try:
            producer = KafkaProducer(
                bootstrap_servers=[bootstrap_servers],
                value_serializer=lambda v: json.dumps(v).encode('utf-8')
            )
            logger.info("Successfully connected to Kafka")
            return producer
        except Exception as e:
            logger.error(f"Failed to connect to Kafka (attempt {attempt + 1}/{retries}): {str(e)}")
            if attempt < retries - 1:
                time.sleep(delay)
            else:
                raise Exception(f"Failed to connect to Kafka after {retries} attempts: {str(e)}")

try:
    producer = init_kafka_producer(KAFKA_BOOTSTRAP_SERVERS, retries=5, delay=10)
except Exception as e:
    logger.error(f"Failed to initialize Kafka producer: {str(e)}")
    raise e

# PostgreSQL connection
def get_db_connection():
    conn = psycopg2.connect(
        DATABASE_URL,
        cursor_factory=RealDictCursor
    )
    return conn

# Create the reservations table if it doesn't exist
def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS reservations (
                id SERIAL PRIMARY KEY,
                user_id VARCHAR(255) NOT NULL,
                room_id INTEGER NOT NULL,
                start_time TIMESTAMP NOT NULL,
                end_time TIMESTAMP NOT NULL,
                status VARCHAR(50) DEFAULT 'pending',
                priority INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        logger.info("Reservations table created or already exists")
    except Exception as e:
        logger.error(f"Error creating reservations table: {str(e)}")
        raise
    finally:
        cursor.close()
        conn.close()

# Initialize the database on startup
@app.on_event("startup")
async def startup_event():
    init_db()

# Pydantic model for creating a reservation
class ReservationCreate(BaseModel):
    room_id: int
    start_time: datetime
    end_time: datetime

# Pydantic model for reservation response
class ReservationResponse(BaseModel):
    id: int
    user_id: str
    room_id: int
    start_time: datetime
    end_time: datetime
    status: str
    priority: Optional[int] = None
    created_at: datetime
    room_name: Optional[str] = None

# Pydantic models for updating status and priority
class ReservationStatusUpdate(BaseModel):
    status: str

class ReservationPriorityUpdate(BaseModel):
    priority: int

# Pydantic model for request action payload
class ReservationRequestUpdate(BaseModel):
    status: str
    priority: Optional[int] = None

# Dependency to validate JWT token and return both user payload and token
async def get_current_user(request: Request) -> Tuple[dict, str]:
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not token:
        token = request.cookies.get("jwt_token")
    if not token:
        logger.error("Missing or invalid Authorization header and no jwt_token cookie")
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        logger.info(f"JWT payload: {payload}")
        return payload, token  # Return both the decoded payload and the raw token
    except jwt.ExpiredSignatureError:
        logger.error("Token has expired")
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError as e:
        logger.error(f"Token validation failed: {str(e)}")
        raise HTTPException(status_code=401, detail="Invalid token")

# Fetch room details from salle-service
async def fetch_room_details(room_id: int, token: str):
    retries, delay = 5, 5
    for attempt in range(retries):
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"http://salle-service:8002/rooms/{room_id}",
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=5
                )
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logger.warning(f"Room {room_id} not found in salle-service")
                raise HTTPException(status_code=404, detail="Room not found")
            logger.warning(f"Salle-service request retry {attempt + 1}/{retries}: {str(e)}")
            if attempt == retries - 1:
                logger.error(f"Error querying salle-service: {str(e)}")
                raise HTTPException(status_code=503, detail="Failed to communicate with salle-service")
            time.sleep(delay)
        except Exception as e:
            logger.warning(f"Salle-service request retry {attempt + 1}/{retries}: {str(e)}")
            if attempt == retries - 1:
                logger.error(f"Error querying salle-service: {str(e)}")
                raise HTTPException(status_code=503, detail="Failed to communicate with salle-service")
            time.sleep(delay)
    return None

# Check room availability by querying salle-service
async def check_room_availability(room_id: int, start_time: datetime, end_time: datetime, token: str):
    # Fetch room details from salle-service
    room = await fetch_room_details(room_id, token)

    # Check for overlapping reservations
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT id FROM reservations
            WHERE room_id = %s
            AND status = 'approved'
            AND (
                (start_time <= %s AND end_time >= %s) OR
                (start_time <= %s AND end_time >= %s) OR
                (start_time >= %s AND end_time <= %s)
            )
            """,
            (
                room_id,
                start_time, start_time,
                end_time, end_time,
                start_time, end_time
            )
        )
        overlapping_reservations = cursor.fetchall()
        if overlapping_reservations:
            logger.warning(f"Room {room_id} is already reserved for the selected time slot")
            raise HTTPException(status_code=400, detail="Room is not available for the selected time slot")
        return room
    except Exception as e:
        logger.error(f"Error checking overlapping reservations for room {room_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to check room availability")
    finally:
        cursor.close()
        conn.close()

# Create a reservation
@app.post("/reservations/", response_model=ReservationResponse)
async def create_reservation(reservation: ReservationCreate, user_and_token: Tuple[dict, str] = Depends(get_current_user)):
    user, token = user_and_token

    # Validate time range
    if reservation.start_time >= reservation.end_time:
        logger.error(f"Invalid time range: start_time {reservation.start_time} >= end_time {reservation.end_time}")
        raise HTTPException(status_code=400, detail="End time must be after start time")
    if reservation.start_time < datetime.utcnow():
        logger.error(f"Start time {reservation.start_time} is in the past")
        raise HTTPException(status_code=400, detail="Start time cannot be in the past")

    # Check room availability and get room details
    room = await check_room_availability(reservation.room_id, reservation.start_time, reservation.end_time, token)

    # Create the reservation
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO reservations (user_id, room_id, start_time, end_time)
            VALUES (%s, %s, %s, %s)
            RETURNING id, user_id, room_id, start_time, end_time, status, priority, created_at
            """,
            (user["sub"], reservation.room_id, reservation.start_time, reservation.end_time)
        )
        new_reservation = cursor.fetchone()
        conn.commit()

        # Publish reservation_created event to Kafka
        reservation_event = {
            "event_type": "reservation_created",
            "reservation_id": new_reservation["id"],
            "user_id": user["sub"],
            "room_id": reservation.room_id,
            "start_time": reservation.start_time.isoformat(),
            "end_time": reservation.end_time.isoformat(),
            "role": user.get("role", "unknown"),
            "timestamp": datetime.utcnow().isoformat()
        }
        try:
            producer.send("reservation-events", reservation_event)
            producer.flush()
            logger.info(f"Published reservation_created event: {reservation_event}")
        except Exception as e:
            logger.error(f"Error publishing to Kafka: {str(e)}")
            raise HTTPException(status_code=500, detail="Failed to publish event to Kafka")

        return ReservationResponse(
            **new_reservation,
            room_name=room.get("name")
        )
    except Exception as e:
        logger.error(f"Error creating reservation: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to create reservation")
    finally:
        cursor.close()
        conn.close()

# Get reservation history for the current user (or all reservations for admin)
@app.get("/reservations/history", response_model=list[ReservationResponse])
async def get_reservation_history(user_and_token: Tuple[dict, str] = Depends(get_current_user)):
    user, token = user_and_token

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        if user.get("role") == "admin":
            # Admins can see all reservations
            cursor.execute(
                """
                SELECT id, user_id, room_id, start_time, end_time, status, priority, created_at
                FROM reservations
                ORDER BY created_at DESC
                """
            )
        else:
            # Regular users see only their reservations
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

        # Fetch room details from salle-service
        enriched_reservations = []
        for reservation in reservations:
            room = await fetch_room_details(reservation["room_id"], token)
            reservation["room_name"] = room.get("name") if room else "Unknown Room"
            enriched_reservations.append(ReservationResponse(**reservation))

        return enriched_reservations
    except Exception as e:
        logger.error(f"Error fetching reservation history for user {user['sub']}: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to fetch reservation history")
    finally:
        cursor.close()
        conn.close()

# Get all reservations for the authenticated user
@app.get("/reservations/", response_model=list[ReservationResponse])
async def get_reservations(user_and_token: Tuple[dict, str] = Depends(get_current_user)):
    user, token = user_and_token

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
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

        # Fetch room details from salle-service
        enriched_reservations = []
        for reservation in reservations:
            room = await fetch_room_details(reservation["room_id"], token)
            reservation["room_name"] = room.get("name") if room else "Unknown Room"
            enriched_reservations.append(ReservationResponse(**reservation))

        return enriched_reservations
    except Exception as e:
        logger.error(f"Error fetching reservations for user {user['sub']}: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to fetch reservations")
    finally:
        cursor.close()
        conn.close()

# Delete a reservation
@app.delete("/reservations/{reservation_id}", response_model=dict)
async def delete_reservation(reservation_id: int, user_and_token: Tuple[dict, str] = Depends(get_current_user)):
    user, _ = user_and_token  # We don't need the token for this endpoint

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Check if the reservation exists and belongs to the user
        cursor.execute(
            "SELECT id, user_id, room_id, start_time, end_time FROM reservations WHERE id = %s",
            (reservation_id,)
        )
        reservation = cursor.fetchone()
        if not reservation:
            logger.warning(f"Reservation {reservation_id} not found")
            raise HTTPException(status_code=404, detail="Reservation not found")
        if reservation["user_id"] != user["sub"] and user.get("role") != "admin":
            logger.error(f"User {user['sub']} attempted to delete reservation {reservation_id} they do not own")
            raise HTTPException(status_code=403, detail="Not authorized to delete this reservation")

        # Delete the reservation
        cursor.execute("DELETE FROM reservations WHERE id = %s", (reservation_id,))
        conn.commit()

        # Publish reservation_deleted event to Kafka
        reservation_event = {
            "event_type": "reservation_deleted",
            "reservation_id": reservation_id,
            "user_id": user["sub"],
            "room_id": reservation["room_id"],
            "start_time": reservation["start_time"].isoformat(),
            "end_time": reservation["end_time"].isoformat(),
            "role": user.get("role", "unknown"),
            "timestamp": datetime.utcnow().isoformat()
        }
        try:
            producer.send("reservation-events", reservation_event)
            producer.flush()
            logger.info(f"Published reservation_deleted event: {reservation_event}")
        except Exception as e:
            logger.error(f"Error publishing to Kafka: {str(e)}")
            raise HTTPException(status_code=500, detail="Failed to publish event to Kafka")

        return {"message": "Reservation deleted successfully"}
    except Exception as e:
        logger.error(f"Error deleting reservation {reservation_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to delete reservation")
    finally:
        cursor.close()
        conn.close()

# Get pending reservations (employee only)
@app.get("/reservations/pending", response_model=list[ReservationResponse])
async def get_pending_reservations(user_and_token: Tuple[dict, str] = Depends(get_current_user)):
    user, token = user_and_token
    if user.get("role") != "employee":
        raise HTTPException(status_code=403, detail="Employee access required")

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT id, user_id, room_id, start_time, end_time, status, priority, created_at
            FROM reservations
            WHERE status = 'pending'
            ORDER BY created_at DESC
            """
        )
        reservations = cursor.fetchall()

        enriched_reservations = []
        for reservation in reservations:
            room = await fetch_room_details(reservation["room_id"], token)
            reservation["room_name"] = room.get("name") if room else "Unknown Room"
            enriched_reservations.append(ReservationResponse(**reservation))

        return enriched_reservations
    except Exception as e:
        logger.error(f"Error fetching pending reservations: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to fetch pending reservations")
    finally:
        cursor.close()
        conn.close()

# Handle reservation request (accept/refuse) with status and priority (employee only)
@app.post("/reservations/request/{reservation_id}/{action}")
async def handle_reservation_request(
    reservation_id: int,
    action: str,
    update: ReservationRequestUpdate,
    user_and_token: Tuple[dict, str] = Depends(get_current_user)
):
    user, _ = user_and_token
    if user.get("role") != "employee":
        raise HTTPException(status_code=403, detail="Employee access required")
    if action not in ["accept", "refuse"]:
        raise HTTPException(status_code=400, detail="Invalid action")

    new_status = update.status
    priority = update.priority if action == "accept" else None

    if new_status not in ["approved", "denied"]:
        raise HTTPException(status_code=400, detail="Invalid status")
    if priority and (priority < 1 or priority > 3):
        raise HTTPException(status_code=400, detail="Priority must be between 1 and 3")

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            UPDATE reservations
            SET status = %s, priority = %s
            WHERE id = %s AND status = 'pending'
            RETURNING id, user_id, room_id, start_time, end_time
            """,
            (new_status, priority, reservation_id)
        )
        updated_reservation = cursor.fetchone()
        if not updated_reservation:
            raise HTTPException(status_code=404, detail="Reservation not found or not pending")
        conn.commit()

        reservation_event = {
            "event_type": f"reservation_{new_status}",
            "reservation_id": reservation_id,
            "user_id": updated_reservation["user_id"],
            "room_id": updated_reservation["room_id"],
            "start_time": updated_reservation["start_time"].isoformat(),
            "end_time": updated_reservation["end_time"].isoformat(),
            "handled_by": user["sub"],
            "timestamp": datetime.utcnow().isoformat()
        }
        if priority:
            reservation_event["priority"] = priority

        try:
            producer.send("reservation-events", reservation_event)
            producer.flush()
            logger.info(f"Published reservation_{new_status} event: {reservation_event}")
        except Exception as e:
            logger.error(f"Error publishing to Kafka: {str(e)}")
            raise HTTPException(status_code=500, detail="Failed to publish event to Kafka")

        return {"message": f"Reservation {action}ed successfully"}
    except Exception as e:
        conn.rollback()
        logger.error(f"Error handling reservation request: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to handle reservation request")
    finally:
        cursor.close()
        conn.close()

# Update reservation status (admin only)
@app.put("/reservations/{reservation_id}/status")
async def update_reservation_status(
    reservation_id: int,
    update: ReservationStatusUpdate,
    user_and_token: Tuple[dict, str] = Depends(get_current_user)
):
    user, _ = user_and_token  # We don't need the token for this endpoint

    if user.get("role") != "admin":
        logger.error(f"User {user['sub']} attempted to update reservation status without admin privileges")
        raise HTTPException(status_code=403, detail="Admin access required")

    if update.status not in ["pending", "approved", "denied"]:
        raise HTTPException(status_code=400, detail="Invalid status")

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            UPDATE reservations
            SET status = %s
            WHERE id = %s
            RETURNING id, user_id, room_id, start_time, end_time
            """,
            (update.status, reservation_id)
        )
        updated_reservation = cursor.fetchone()
        if not updated_reservation:
            raise HTTPException(status_code=404, detail="Reservation not found")
        conn.commit()

        # Publish reservation_status_updated event to Kafka
        reservation_event = {
            "event_type": "reservation_status_updated",
            "reservation_id": reservation_id,
            "user_id": updated_reservation["user_id"],
            "room_id": updated_reservation["room_id"],
            "start_time": updated_reservation["start_time"].isoformat(),
            "end_time": updated_reservation["end_time"].isoformat(),
            "status": update.status,
            "updated_by": user["sub"],
            "timestamp": datetime.utcnow().isoformat()
        }
        try:
            producer.send("reservation-events", reservation_event)
            producer.flush()
            logger.info(f"Published reservation_status_updated event: {reservation_event}")
        except Exception as e:
            logger.error(f"Error publishing to Kafka: {str(e)}")
            raise HTTPException(status_code=500, detail="Failed to publish event to Kafka")

        return {"message": "Reservation status updated"}
    except Exception as e:
        conn.rollback()
        logger.error(f"Error updating reservation status: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to update reservation status")
    finally:
        cursor.close()
        conn.close()

# Update reservation priority (admin only)
@app.put("/reservations/{reservation_id}/priority")
async def update_reservation_priority(
    reservation_id: int,
    update: ReservationPriorityUpdate,
    user_and_token: Tuple[dict, str] = Depends(get_current_user)
):
    user, _ = user_and_token  # We don't need the token for this endpoint

    if user.get("role") != "admin":
        logger.error(f"User {user['sub']} attempted to update reservation priority without admin privileges")
        raise HTTPException(status_code=403, detail="Admin access required")

    if update.priority < 1 or update.priority > 3:
        raise HTTPException(status_code=400, detail="Priority must be between 1 and 3")

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            UPDATE reservations
            SET priority = %s
            WHERE id = %s
            RETURNING id, user_id, room_id, start_time, end_time
            """,
            (update.priority, reservation_id)
        )
        updated_reservation = cursor.fetchone()
        if not updated_reservation:
            raise HTTPException(status_code=404, detail="Reservation not found")
        conn.commit()

        # Publish reservation_priority_updated event to Kafka
        reservation_event = {
            "event_type": "reservation_priority_updated",
            "reservation_id": reservation_id,
            "user_id": updated_reservation["user_id"],
            "room_id": updated_reservation["room_id"],
            "start_time": updated_reservation["start_time"].isoformat(),
            "end_time": updated_reservation["end_time"].isoformat(),
            "priority": update.priority,
            "updated_by": user["sub"],
            "timestamp": datetime.utcnow().isoformat()
        }
        try:
            producer.send("reservation-events", reservation_event)
            producer.flush()
            logger.info(f"Published reservation_priority_updated event: {reservation_event}")
        except Exception as e:
            logger.error(f"Error publishing to Kafka: {str(e)}")
            raise HTTPException(status_code=500, detail="Failed to publish event to Kafka")

        return {"message": "Reservation priority updated"}
    except Exception as e:
        conn.rollback()
        logger.error(f"Error updating reservation priority: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to update reservation priority")
    finally:
        cursor.close()
        conn.close()

# Health check endpoint
@app.get("/health")
async def health_check():
    health_status = {"status": "healthy", "details": {}}

    retries, delay = 5, 5

    # Check database connectivity
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
            producer.send("health-check-topic", {"test": "message"})
            producer.flush()
            health_status["details"]["kafka"] = "healthy"
            break
        except Exception as e:
            logger.warning(f"Kafka health check retry {attempt + 1}/{retries}: {str(e)}")
            if attempt == retries - 1:
                logger.error(f"Kafka health check failed: {str(e)}")
                health_status["details"]["kafka"] = f"unhealthy: {str(e)}"
                health_status["status"] = "unhealthy"
            time.sleep(delay)

    # Check salle-service connectivity
    for attempt in range(retries):
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get("http://salle-service:8002/health", timeout=5)
                response.raise_for_status()
                health_status["details"]["salle_service"] = "healthy"
                break
        except Exception as e:
            logger.warning(f"Salle-service health check retry {attempt + 1}/{retries}: {str(e)}")
            if attempt == retries - 1:
                logger.error(f"Salle-service health check failed: {str(e)}")
                health_status["details"]["salle_service"] = f"unhealthy: {str(e)}"
                health_status["status"] = "unhealthy"
            time.sleep(delay)

    logger.info(f"Health check result: {health_status}")
    if health_status["status"] == "unhealthy":
        raise HTTPException(status_code=503, detail=health_status)
    return health_status

@app.get("/")
async def root():
    return {"message": "Reservation Service is running"}