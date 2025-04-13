from fastapi import FastAPI, HTTPException, Depends, Header
from pydantic import BaseModel
import os
import logging
import jwt
from datetime import datetime
from kafka import KafkaProducer
import json
import psycopg2
from psycopg2.extras import RealDictCursor
import time

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

# Pydantic model for a meeting room
class Room(BaseModel):
    name: str
    capacity: int
    location: str

# Pydantic model for availability check
class AvailabilityRequest(BaseModel):
    room_id: int
    start_time: datetime
    end_time: datetime

# Dependency to validate JWT token
async def get_current_user(authorization: str = Header(...)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header missing")
    
    try:
        token = authorization.replace("Bearer ", "")
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except Exception as e:
        logger.error(f"Invalid token: {str(e)}")
        raise HTTPException(status_code=401, detail="Invalid token")

@app.post("/rooms/", response_model=dict)
async def create_room(room: Room, current_user: dict = Depends(get_current_user)):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO rooms (name, capacity, location)
            VALUES (%s, %s, %s)
            RETURNING id, name, capacity, location
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
            "timestamp": datetime.utcnow().isoformat()
        }
        producer.send('room-events', room_event)
        producer.flush()
        logger.info(f"Published room_created event: {room_event}")

        return dict(new_room)
    except Exception as e:
        logger.error(f"Error creating room: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to create room")
    finally:
        cursor.close()
        conn.close()

@app.get("/rooms/", response_model=list)
async def get_rooms(current_user: dict = Depends(get_current_user)):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id, name, capacity, location FROM rooms")
        rooms = cursor.fetchall()
        return [dict(room) for room in rooms]
    except Exception as e:
        logger.error(f"Error fetching rooms: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to fetch rooms")
    finally:
        cursor.close()
        conn.close()

@app.get("/rooms/{room_id}", response_model=dict)
async def get_room(room_id: int, current_user: dict = Depends(get_current_user)):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id, name, capacity, location FROM rooms WHERE id = %s", (room_id,))
        room = cursor.fetchone()
        if not room:
            raise HTTPException(status_code=404, detail="Room not found")
        return dict(room)
    except Exception as e:
        logger.error(f"Error fetching room: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to fetch room")
    finally:
        cursor.close()
        conn.close()

@app.put("/rooms/{room_id}", response_model=dict)
async def update_room(room_id: int, room: Room, current_user: dict = Depends(get_current_user)):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            UPDATE rooms
            SET name = %s, capacity = %s, location = %s
            WHERE id = %s
            RETURNING id, name, capacity, location
            """,
            (room.name, room.capacity, room.location, room_id)
        )
        updated_room = cursor.fetchone()
        if not updated_room:
            raise HTTPException(status_code=404, detail="Room not found")
        conn.commit()

        # Publish room_updated event to Kafka
        room_event = {
            "event_type": "room_updated",
            "room_id": updated_room["id"],
            "name": updated_room["name"],
            "capacity": updated_room["capacity"],
            "location": updated_room["location"],
            "timestamp": datetime.utcnow().isoformat()
        }
        producer.send('room-events', room_event)
        producer.flush()
        logger.info(f"Published room_updated event: {room_event}")

        return dict(updated_room)
    except Exception as e:
        logger.error(f"Error updating room: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to update room")
    finally:
        cursor.close()
        conn.close()

@app.delete("/rooms/{room_id}", response_model=dict)
async def delete_room(room_id: int, current_user: dict = Depends(get_current_user)):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM rooms WHERE id = %s RETURNING id", (room_id,))
        deleted_room = cursor.fetchone()
        if not deleted_room:
            raise HTTPException(status_code=404, detail="Room not found")
        conn.commit()

        # Publish room_deleted event to Kafka
        room_event = {
            "event_type": "room_deleted",
            "room_id": deleted_room["id"],
            "timestamp": datetime.utcnow().isoformat()
        }
        producer.send('room-events', room_event)
        producer.flush()
        logger.info(f"Published room_deleted event: {room_event}")

        return {"message": f"Room {room_id} deleted"}
    except Exception as e:
        logger.error(f"Error deleting room: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to delete room")
    finally:
        cursor.close()
        conn.close()

@app.post("/rooms/availability/", response_model=dict)
async def check_room_availability(request: AvailabilityRequest, current_user: dict = Depends(get_current_user)):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Check if the room exists
        cursor.execute("SELECT id FROM rooms WHERE id = %s", (request.room_id,))
        room = cursor.fetchone()
        if not room:
            raise HTTPException(status_code=404, detail="Room not found")

        # Check for overlapping reservations
        cursor.execute(
            """
            SELECT id FROM reservations
            WHERE room_id = %s
            AND start_time < %s
            AND end_time > %s
            """,
            (request.room_id, request.end_time, request.start_time)
        )
        overlapping_reservations = cursor.fetchall()

        if overlapping_reservations:
            return {"available": False, "message": "Room is not available for the selected time slot"}
        return {"available": True, "message": "Room is available"}
    except Exception as e:
        logger.error(f"Error checking room availability: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to check room availability")
    finally:
        cursor.close()
        conn.close()

@app.get("/")
async def root():
    return {"message": "Salle Service is running"}