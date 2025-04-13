import os
import logging
from datetime import datetime
from typing import List
from fastapi import FastAPI, HTTPException, Depends, Header
from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship
from kafka import KafkaProducer
import json
import jwt
import requests
from dotenv import load_dotenv
import time

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Environment variables
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

logger.info(f"Using DATABASE_URL: {DATABASE_URL}")
logger.info(f"Using KAFKA_BOOTSTRAP_SERVERS: {KAFKA_BOOTSTRAP_SERVERS}")
logger.info(f"Using JWT_SECRET: {JWT_SECRET}")

# FastAPI app
app = FastAPI()

# Database setup
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

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

# Database models
class Reservation(Base):
    __tablename__ = "reservations"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, index=True)
    room_id = Column(Integer, index=True)
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

# Create the database tables
Base.metadata.create_all(bind=engine)

# Dependency to get DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Dependency to get current user from JWT token
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

# Check room availability by querying salle-service
def check_room_availability(room_id: int, start_time: datetime, end_time: datetime, db: Session):
    # Query salle-service to check if the room exists
    try:
        response = requests.get(f"http://salle-service:8002/rooms/{room_id}")
        if response.status_code != 200:
            raise HTTPException(status_code=404, detail="Room not found")
    except requests.RequestException as e:
        logger.error(f"Error querying salle-service: {str(e)}")
        raise HTTPException(status_code=503, detail="Failed to communicate with salle-service")

    # Check for overlapping reservations
    overlapping_reservations = db.query(Reservation).filter(
        Reservation.room_id == room_id,
        Reservation.start_time < end_time,
        Reservation.end_time > start_time
    ).all()

    if overlapping_reservations:
        raise HTTPException(status_code=400, detail="Room is not available for the selected time slot")

    return True

# Create a reservation
@app.post("/reservations/")
async def create_reservation(
    room_id: int,
    start_time: datetime,
    end_time: datetime,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Validate time range
    if start_time >= end_time:
        raise HTTPException(status_code=400, detail="End time must be after start time")
    if start_time < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Start time cannot be in the past")

    # Check room availability
    check_room_availability(room_id, start_time, end_time, db)

    # Create the reservation
    reservation = Reservation(
        user_id=user["sub"],
        room_id=room_id,
        start_time=start_time,
        end_time=end_time
    )
    db.add(reservation)
    db.commit()
    db.refresh(reservation)

    # Publish reservation_created event to Kafka
    event = {
        "event_type": "reservation_created",
        "reservation_id": reservation.id,
        "user_id": user["sub"],
        "room_id": room_id,
        "start_time": start_time.isoformat(),
        "end_time": end_time.isoformat(),
        "timestamp": datetime.utcnow().isoformat()
    }
    try:
        producer.send("reservation-events", event)
        producer.flush()
        logger.info(f"Published reservation_created event: {event}")
    except Exception as e:
        logger.error(f"Error publishing to Kafka: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to publish event to Kafka")

    return {
        "id": reservation.id,
        "user_id": user["sub"],
        "room_id": room_id,
        "start_time": start_time,
        "end_time": end_time
    }

# Get all reservations for the authenticated user
@app.get("/reservations/")
async def get_reservations(user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    reservations = db.query(Reservation).filter(Reservation.user_id == user["sub"]).all()
    return [
        {
            "id": r.id,
            "user_id": r.user_id,
            "room_id": r.room_id,
            "start_time": r.start_time,
            "end_time": r.end_time,
            "created_at": r.created_at
        }
        for r in reservations
    ]

# Delete a reservation
@app.delete("/reservations/{reservation_id}")
async def delete_reservation(reservation_id: int, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    reservation = db.query(Reservation).filter(Reservation.id == reservation_id, Reservation.user_id == user["sub"]).first()
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservation not found or not authorized")

    # Publish reservation_deleted event to Kafka
    event = {
        "event_type": "reservation_deleted",
        "reservation_id": reservation.id,
        "user_id": user["sub"],
        "room_id": reservation.room_id,
        "start_time": reservation.start_time.isoformat(),
        "end_time": reservation.end_time.isoformat(),
        "timestamp": datetime.utcnow().isoformat()
    }
    try:
        producer.send("reservation-events", event)
        producer.flush()
        logger.info(f"Published reservation_deleted event: {event}")
    except Exception as e:
        logger.error(f"Error publishing to Kafka: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to publish event to Kafka")

    db.delete(reservation)
    db.commit()
    return {"message": "Reservation deleted successfully"}

# Health check endpoint
@app.get("/health")
async def health_check():
    health_status = {"status": "healthy", "details": {}}

    # Check database connectivity
    try:
        db = SessionLocal()
        db.execute("SELECT 1")
        db.close()
        health_status["details"]["database"] = "healthy"
    except Exception as e:
        logger.error(f"Database health check failed: {str(e)}")
        health_status["details"]["database"] = f"unhealthy: {str(e)}"
        health_status["status"] = "unhealthy"

    # Check Kafka connectivity
    try:
        producer.send("health-check-topic", {"test": "message"})
        producer.flush()
        health_status["details"]["kafka"] = "healthy"
    except Exception as e:
        logger.error(f"Kafka health check failed: {str(e)}")
        health_status["details"]["kafka"] = f"unhealthy: {str(e)}"
        health_status["status"] = "unhealthy"

    # Check salle-service connectivity
    try:
        response = requests.get("http://salle-service:8002/health")
        if response.status_code != 200:
            raise Exception("Salle-service health check failed")
        health_status["details"]["salle_service"] = "healthy"
    except Exception as e:
        logger.error(f"Salle-service health check failed: {str(e)}")
        health_status["details"]["salle_service"] = f"unhealthy: {str(e)}"
        health_status["status"] = "unhealthy"

    if health_status["status"] == "unhealthy":
        raise HTTPException(status_code=503, detail=health_status)
    return health_status

@app.get("/")
async def root():
    return {"message": "Reservation Service is running"}