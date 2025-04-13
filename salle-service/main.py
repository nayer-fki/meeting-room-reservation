from fastapi import FastAPI, HTTPException, Depends, Request
from pydantic import BaseModel
from datetime import datetime
import os
import logging
import jwt
import time
from kafka import KafkaProducer
import json
import psycopg2
from psycopg2.extras import RealDictCursor
from typing import Optional  # Import Optional for Python 3.9 compatibility

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
class RoomCreate(BaseModel):
    name: str
    capacity: int
    location: str

class RoomUpdate(BaseModel):
    name: Optional[str] = None
    capacity: Optional[int] = None
    location: Optional[str] = None

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

# Create a room (admin only)
@app.post("/rooms/", response_model=dict)
async def create_room(room: RoomCreate, user: dict = Depends(get_current_user)):
    check_admin(user)
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

        event = {
            "event_type": "room_created",
            "room_id": new_room["id"],
            "name": new_room["name"],
            "capacity": new_room["capacity"],
            "location": new_room["location"],
            "timestamp": datetime.utcnow().isoformat()
        }
        logger.info(f"Sending Kafka event: {event}")
        producer.send("room-events", event)
        producer.flush()

        # Convert datetime to string for the response
        response_room = dict(new_room)
        response_room["created_at"] = new_room["created_at"].isoformat()

        return response_room
    except Exception as e:
        logger.error(f"Error creating room: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to create room")
    finally:
        cursor.close()
        conn.close()

# Get all rooms (available to all authenticated users)
@app.get("/rooms/", response_model=list)
async def get_rooms(user: dict = Depends(get_current_user)):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT id, name, capacity, location, created_at
            FROM rooms
            ORDER BY created_at DESC
            """
        )
        rooms = cursor.fetchall()
        # Convert datetime to string for each room
        return [
            {
                **dict(room),
                "created_at": room["created_at"].isoformat()
            }
            for room in rooms
        ]
    except Exception as e:
        logger.error(f"Error fetching rooms: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to fetch rooms")
    finally:
        cursor.close()
        conn.close()

# Get a specific room (available to all authenticated users)
@app.get("/rooms/{room_id}", response_model=dict)
async def get_room(room_id: int, user: dict = Depends(get_current_user)):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT id, name, capacity, location, created_at
            FROM rooms
            WHERE id = %s
            """,
            (room_id,)
        )
        room = cursor.fetchone()
        if not room:
            raise HTTPException(status_code=404, detail="Room not found")
        # Convert datetime to string for the response
        response_room = dict(room)
        response_room["created_at"] = room["created_at"].isoformat()
        return response_room
    except Exception as e:
        logger.error(f"Error fetching room: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to fetch room")
    finally:
        cursor.close()
        conn.close()

# Update a room (admin only)
@app.put("/rooms/{room_id}", response_model=dict)
async def update_room(room_id: int, room_update: RoomUpdate, user: dict = Depends(get_current_user)):
    check_admin(user)
    update_data = room_update.dict(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")

    set_clause = ", ".join([f"{key} = %s" for key in update_data.keys()])
    values = list(update_data.values()) + [room_id]

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            f"""
            UPDATE rooms
            SET {set_clause}
            WHERE id = %s
            RETURNING id, name, capacity, location, created_at
            """,
            values
        )
        updated_room = cursor.fetchone()
        if not updated_room:
            raise HTTPException(status_code=404, detail="Room not found")
        conn.commit()

        event = {
            "event_type": "room_updated",
            "room_id": updated_room["id"],
            "name": updated_room["name"],
            "capacity": updated_room["capacity"],
            "location": updated_room["location"],
            "timestamp": datetime.utcnow().isoformat()
        }
        logger.info(f"Sending Kafka event: {event}")
        producer.send("room-events", event)
        producer.flush()

        # Convert datetime to string for the response
        response_room = dict(updated_room)
        response_room["created_at"] = updated_room["created_at"].isoformat()
        return response_room
    except Exception as e:
        logger.error(f"Error updating room: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to update room")
    finally:
        cursor.close()
        conn.close()

# Delete a room (admin only)
@app.delete("/rooms/{room_id}", response_model=dict)
async def delete_room(room_id: int, user: dict = Depends(get_current_user)):
    check_admin(user)
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            DELETE FROM rooms
            WHERE id = %s
            RETURNING id, name, capacity, location
            """,
            (room_id,)
        )
        deleted_room = cursor.fetchone()
        if not deleted_room:
            raise HTTPException(status_code=404, detail="Room not found")
        conn.commit()

        event = {
            "event_type": "room_deleted",
            "room_id": deleted_room["id"],
            "name": deleted_room["name"],
            "timestamp": datetime.utcnow().isoformat()
        }
        logger.info(f"Sending Kafka event: {event}")
        producer.send("room-events", event)
        producer.flush()

        return {"message": f"Room {room_id} deleted"}
    except Exception as e:
        logger.error(f"Error deleting room: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to delete room")
    finally:
        cursor.close()
        conn.close()

# Health check endpoint
@app.get("/health")
async def health_check():
    health_status = {"status": "healthy", "details": {}}

    # Check database with retry
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

    # Check Kafka with retry
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

@app.get("/")
async def root():
    return {"message": "Salle Service is running"}