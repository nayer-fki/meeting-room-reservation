import os
import logging
from fastapi import FastAPI, HTTPException, Depends, Request
from pydantic import BaseModel
import jwt
from datetime import datetime
from kafka import KafkaProducer
import json
import psycopg2
from psycopg2.extras import RealDictCursor
import time
from typing import Optional  # Add this for Python 3.9 compatibility

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI()

# JWT Secret (read from environment variables)
JWT_SECRET = os.getenv("JWT_SECRET")
if not JWT_SECRET:
    raise ValueError("JWT_SECRET must be set in environment variables")
logger.info(f"Using JWT_SECRET: {JWT_SECRET}")
JWT_ALGORITHM = "HS256"

# Kafka Producer with retry logic
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
if not KAFKA_BOOTSTRAP_SERVERS:
    raise ValueError("KAFKA_BOOTSTRAP_SERVERS must be set in environment variables")

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
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL must be set in environment variables")
    conn = psycopg2.connect(
        database_url,
        cursor_factory=RealDictCursor
    )
    return conn

# Create the rooms table if it doesn't exist
def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS rooms (
                id SERIAL PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                capacity INTEGER NOT NULL,
                location VARCHAR(255),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        logger.info("Rooms table created or already exists")
    except Exception as e:
        logger.error(f"Error creating rooms table: {str(e)}")
        raise
    finally:
        cursor.close()
        conn.close()

# Initialize the database on startup
@app.on_event("startup")
async def startup_event():
    init_db()

# Pydantic model for a meeting room
class Room(BaseModel):
    name: str
    capacity: int
    location: Optional[str] = None  # Updated for Python 3.9 compatibility

# Pydantic model for room response (includes id and created_at)
class RoomResponse(Room):
    id: int
    created_at: datetime

# Pydantic model for availability check
class AvailabilityRequest(BaseModel):
    room_id: int
    start_time: datetime
    end_time: datetime

# Dependency to validate JWT token
async def get_current_user(request: Request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not token:
        token = request.cookies.get("jwt_token")
    if not token:
        logger.error("Missing or invalid Authorization header and no jwt_token cookie")
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        logger.info(f"JWT payload: {payload}")
        return payload
    except jwt.ExpiredSignatureError:
        logger.error("Token has expired")
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError as e:
        logger.error(f"Token validation failed: {str(e)}")
        raise HTTPException(status_code=401, detail="Invalid token")

# Health check endpoint (public, no authentication required)
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

    logger.info(f"Health check result: {health_status}")
    if health_status["status"] == "unhealthy":
        raise HTTPException(status_code=503, detail=health_status)
    return health_status

# Create a room
@app.post("/rooms/", response_model=RoomResponse)
async def create_room(room: Room, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "admin":
        logger.error(f"User {current_user.get('sub')} attempted to create a room without admin privileges")
        raise HTTPException(status_code=403, detail="Admin access required")

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO rooms (name, capacity, location)
            VALUES (%s, %s, %s)
            RETURNING id, name, capacity, location, created_at
            """,
            (room.name, room.capacity, room.location)
        )
        new_room = cursor.fetchone()
        conn.commit()

        # Publish room_created event to Kafka
        room_event = {
            "event_type": "room_created",
            "room_id": new_room["id"],
            "name": new_room["name"],
            "capacity": new_room["capacity"],
            "location": new_room["location"],
            "created_by": current_user.get("sub"),
            "timestamp": datetime.utcnow().isoformat()
        }
        producer.send('room-events', room_event)
        producer.flush()
        logger.info(f"Published room_created event: {room_event}")

        return RoomResponse(**new_room)
    except Exception as e:
        logger.error(f"Error creating room: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to create room: {str(e)}")
    finally:
        cursor.close()
        conn.close()

# Get all rooms (for /rooms/)
@app.get("/rooms/", response_model=list[RoomResponse])
async def get_rooms(current_user: dict = Depends(get_current_user)):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id, name, capacity, location, created_at FROM rooms")
        rooms = cursor.fetchall()
        return [RoomResponse(**room) for room in rooms]
    except Exception as e:
        logger.error(f"Error fetching rooms: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch rooms: {str(e)}")
    finally:
        cursor.close()
        conn.close()

# Get all rooms (for /salles/ to fix the 404 error)
@app.get("/salles/", response_model=list[RoomResponse])
async def get_salles(current_user: dict = Depends(get_current_user)):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id, name, capacity, location, created_at FROM rooms")
        rooms = cursor.fetchall()
        return [RoomResponse(**room) for room in rooms]
    except Exception as e:
        logger.error(f"Error fetching salles: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch salles: {str(e)}")
    finally:
        cursor.close()
        conn.close()

# Get a specific room
@app.get("/rooms/{room_id}", response_model=RoomResponse)
async def get_room(room_id: int, current_user: dict = Depends(get_current_user)):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id, name, capacity, location, created_at FROM rooms WHERE id = %s", (room_id,))
        room = cursor.fetchone()
        if not room:
            logger.warning(f"Room {room_id} not found")
            raise HTTPException(status_code=404, detail="Room not found")
        return RoomResponse(**room)
    except Exception as e:
        logger.error(f"Error fetching room {room_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch room: {str(e)}")
    finally:
        cursor.close()
        conn.close()

# Update a room
@app.put("/rooms/{room_id}", response_model=RoomResponse)
async def update_room(room_id: int, room: Room, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "admin":
        logger.error(f"User {current_user.get('sub')} attempted to update a room without admin privileges")
        raise HTTPException(status_code=403, detail="Admin access required")

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            UPDATE rooms
            SET name = %s, capacity = %s, location = %s
            WHERE id = %s
            RETURNING id, name, capacity, location, created_at
            """,
            (room.name, room.capacity, room.location, room_id)
        )
        updated_room = cursor.fetchone()
        if not updated_room:
            logger.warning(f"Room {room_id} not found for update")
            raise HTTPException(status_code=404, detail="Room not found")
        conn.commit()

        # Publish room_updated event to Kafka
        room_event = {
            "event_type": "room_updated",
            "room_id": updated_room["id"],
            "name": updated_room["name"],
            "capacity": updated_room["capacity"],
            "location": updated_room["location"],
            "updated_by": current_user.get("sub"),
            "timestamp": datetime.utcnow().isoformat()
        }
        producer.send('room-events', room_event)
        producer.flush()
        logger.info(f"Published room_updated event: {room_event}")

        return RoomResponse(**updated_room)
    except Exception as e:
        logger.error(f"Error updating room {room_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to update room: {str(e)}")
    finally:
        cursor.close()
        conn.close()

# Delete a room
@app.delete("/rooms/{room_id}", response_model=dict)
async def delete_room(room_id: int, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "admin":
        logger.error(f"User {current_user.get('sub')} attempted to delete a room without admin privileges")
        raise HTTPException(status_code=403, detail="Admin access required")

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM rooms WHERE id = %s RETURNING id", (room_id,))
        deleted_room = cursor.fetchone()
        if not deleted_room:
            logger.warning(f"Room {room_id} not found for deletion")
            raise HTTPException(status_code=404, detail="Room not found")
        conn.commit()

        # Publish room_deleted event to Kafka
        room_event = {
            "event_type": "room_deleted",
            "room_id": deleted_room["id"],
            "deleted_by": current_user.get("sub"),
            "timestamp": datetime.utcnow().isoformat()
        }
        producer.send('room-events', room_event)
        producer.flush()
        logger.info(f"Published room_deleted event: {room_event}")

        return {"message": f"Room {room_id} deleted"}
    except Exception as e:
        logger.error(f"Error deleting room {room_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to delete room: {str(e)}")
    finally:
        cursor.close()
        conn.close()

# Check room availability
@app.post("/rooms/availability/", response_model=dict)
async def check_room_availability(request: AvailabilityRequest, current_user: dict = Depends(get_current_user)):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Check if the room exists
        cursor.execute("SELECT id FROM rooms WHERE id = %s", (request.room_id,))
        room = cursor.fetchone()
        if not room:
            logger.warning(f"Room {request.room_id} not found for availability check")
            raise HTTPException(status_code=404, detail="Room not found")

        # Check for overlapping reservations
        cursor.execute(
            """
            SELECT id FROM reservations
            WHERE room_id = %s
            AND start_time < %s
            AND end_time > %s
            AND status = 'approved'
            """,
            (request.room_id, request.end_time, request.start_time)
        )
        overlapping_reservations = cursor.fetchall()

        if overlapping_reservations:
            return {"available": False, "message": "Room is not available for the selected time slot"}
        return {"available": True, "message": "Room is available"}
    except Exception as e:
        logger.error(f"Error checking room availability for room {request.room_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to check room availability: {str(e)}")
    finally:
        cursor.close()
        conn.close()

# Root endpoint
@app.get("/")
async def root():
    return {"message": "Salle Service is running"}