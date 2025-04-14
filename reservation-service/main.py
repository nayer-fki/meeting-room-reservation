import os
import logging
from datetime import datetime
from typing import List, Optional
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
from pydantic import BaseModel

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

SALLE_SERVICE_URL = os.getenv("SALLE_SERVICE_URL")
if not SALLE_SERVICE_URL:
    raise ValueError("SALLE_SERVICE_URL must be set in environment variables")

logger.info(f"Using DATABASE_URL: {DATABASE_URL}")
logger.info(f"Using KAFKA_BOOTSTRAP_SERVERS: {KAFKA_BOOTSTRAP_SERVERS}")
logger.info(f"Using JWT_SECRET: {JWT_SECRET}")
logger.info(f"Using SALLE_SERVICE_URL: {SALLE_SERVICE_URL}")

# FastAPI app
app = FastAPI()

# Database setup
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

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

# Database models
class Reservation(Base):
    __tablename__ = "reservations"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, index=True)
    room_id = Column(Integer, index=True)
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=False)
    purpose = Column(String, nullable=False)
    status = Column(String, nullable=False, default="confirmed")
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

# Pydantic models for request validation
class ReservationCreate(BaseModel):
    room_id: int
    start_time: datetime
    end_time: datetime
    purpose: str

class ReservationUpdate(BaseModel):
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    purpose: Optional[str] = None

# Function to fetch room with retries
def fetch_room_with_retries(room_id: int, token: str, retries=10, delay=5):
    for attempt in range(retries):
        try:
            response = requests.get(
                f"{SALLE_SERVICE_URL}/{room_id}",
                headers={"Authorization": f"Bearer {token}"},
                timeout=5
            )
            if response.status_code == 200:
                return response.json()
            else:
                raise Exception(f"Unexpected status code: {response.status_code}")
        except requests.RequestException as e:
            logger.warning(f"Attempt {attempt + 1}/{retries} to contact salle-service failed: {str(e)}")
            if attempt < retries - 1:
                time.sleep(delay)
            else:
                logger.error(f"Failed to contact salle-service after {retries} attempts: {str(e)}")
                raise HTTPException(status_code=503, detail="Service unavailable: Failed to verify room")

# Check room availability
def check_room_availability(room_id: int, start_time: datetime, end_time: datetime, db: Session, exclude_reservation_id: Optional[int] = None):
    # Validate time range
    if start_time >= end_time:
        raise HTTPException(status_code=400, detail="End time must be after start time")
    if start_time < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Start time cannot be in the past")

    # Check for overlapping reservations
    query = db.query(Reservation).filter(
        Reservation.room_id == room_id,
        Reservation.start_time < end_time,
        Reservation.end_time > start_time
    )
    if exclude_reservation_id:
        query = query.filter(Reservation.id != exclude_reservation_id)
    
    overlapping_reservations = query.all()
    if overlapping_reservations:
        raise HTTPException(status_code=400, detail="Room is not available for the selected time slot")

    return True

# Create a reservation
@app.post("/reservations/", response_model=dict)
async def create_reservation(
    reservation: ReservationCreate,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Verify the room exists by calling salle-service with retry logic
    token = jwt.encode(user, JWT_SECRET, algorithm=JWT_ALGORITHM)
    fetch_room_with_retries(reservation.room_id, token)

    # Check room availability
    check_room_availability(reservation.room_id, reservation.start_time, reservation.end_time, db)

    # Create the reservation
    db_reservation = Reservation(
        user_id=user["sub"],
        room_id=reservation.room_id,
        start_time=reservation.start_time,
        end_time=reservation.end_time,
        purpose=reservation.purpose,
        status="confirmed"
    )
    db.add(db_reservation)
    db.commit()
    db.refresh(db_reservation)

    # Publish reservation_created event to Kafka
    event = {
        "event_type": "reservation_created",
        "reservation_id": db_reservation.id,
        "room_id": db_reservation.room_id,
        "user_id": user["sub"],
        "start_time": db_reservation.start_time.isoformat(),
        "end_time": db_reservation.end_time.isoformat(),
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
        "id": db_reservation.id,
        "user_id": db_reservation.user_id,
        "room_id": db_reservation.room_id,
        "start_time": db_reservation.start_time.isoformat(),
        "end_time": db_reservation.end_time.isoformat(),
        "purpose": db_reservation.purpose,
        "status": db_reservation.status,
        "created_at": db_reservation.created_at.isoformat()
    }

# Get all reservations for the authenticated user
@app.get("/reservations/", response_model=List[dict])
async def get_reservations(user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    reservations = db.query(Reservation).filter(Reservation.user_id == user["sub"]).order_by(Reservation.start_time.desc()).all()
    return [
        {
            "id": r.id,
            "user_id": r.user_id,
            "room_id": r.room_id,
            "start_time": r.start_time.isoformat(),
            "end_time": r.end_time.isoformat(),
            "purpose": r.purpose,
            "status": r.status,
            "created_at": r.created_at.isoformat()
        }
        for r in reservations
    ]

# Get a specific reservation
@app.get("/reservations/{reservation_id}", response_model=dict)
async def get_reservation(reservation_id: int, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    reservation = db.query(Reservation).filter(
        Reservation.id == reservation_id,
        Reservation.user_id == user["sub"]
    ).first()
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservation not found or not authorized")
    
    return {
        "id": reservation.id,
        "user_id": reservation.user_id,
        "room_id": reservation.room_id,
        "start_time": reservation.start_time.isoformat(),
        "end_time": reservation.end_time.isoformat(),
        "purpose": reservation.purpose,
        "status": reservation.status,
        "created_at": reservation.created_at.isoformat()
    }

# Update a reservation
@app.put("/reservations/{reservation_id}", response_model=dict)
async def update_reservation(
    reservation_id: int,
    reservation_update: ReservationUpdate,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Fetch the existing reservation
    reservation = db.query(Reservation).filter(
        Reservation.id == reservation_id,
        Reservation.user_id == user["sub"]
    ).first()
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservation not found or not authorized")

    # Prepare updated values
    update_data = reservation_update.dict(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")

    # Check availability if time fields are updated
    new_start_time = update_data.get("start_time", reservation.start_time)
    new_end_time = update_data.get("end_time", reservation.end_time)
    if "start_time" in update_data or "end_time" in update_data:
        check_room_availability(reservation.room_id, new_start_time, new_end_time, db, exclude_reservation_id=reservation_id)

    # Update the reservation
    for key, value in update_data.items():
        setattr(reservation, key, value)
    
    db.commit()
    db.refresh(reservation)

    # Publish reservation_updated event to Kafka
    event = {
        "event_type": "reservation_updated",
        "reservation_id": reservation.id,
        "room_id": reservation.room_id,
        "user_id": user["sub"],
        "start_time": reservation.start_time.isoformat(),
        "end_time": reservation.end_time.isoformat(),
        "timestamp": datetime.utcnow().isoformat()
    }
    try:
        producer.send("reservation-events", event)
        producer.flush()
        logger.info(f"Published reservation_updated event: {event}")
    except Exception as e:
        logger.error(f"Error publishing to Kafka: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to publish event to Kafka")

    return {
        "id": reservation.id,
        "user_id": reservation.user_id,
        "room_id": reservation.room_id,
        "start_time": reservation.start_time.isoformat(),
        "end_time": reservation.end_time.isoformat(),
        "purpose": reservation.purpose,
        "status": reservation.status,
        "created_at": reservation.created_at.isoformat()
    }

# Delete a reservation
@app.delete("/reservations/{reservation_id}", response_model=dict)
async def delete_reservation(reservation_id: int, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    reservation = db.query(Reservation).filter(
        Reservation.id == reservation_id,
        Reservation.user_id == user["sub"]
    ).first()
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservation not found or not authorized")

    # Update status to 'cancelled' instead of deleting
    reservation.status = "cancelled"
    db.commit()
    db.refresh(reservation)

    # Publish reservation_cancelled event to Kafka
    event = {
        "event_type": "reservation_cancelled",
        "reservation_id": reservation.id,
        "room_id": reservation.room_id,
        "user_id": user["sub"],
        "timestamp": datetime.utcnow().isoformat()
    }
    try:
        producer.send("reservation-events", event)
        producer.flush()
        logger.info(f"Published reservation_cancelled event: {event}")
    except Exception as e:
        logger.error(f"Error publishing to Kafka: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to publish event to Kafka")

    return {"message": f"Reservation {reservation_id} cancelled"}

# Health check endpoint
@app.get("/health")
async def health_check():
    health_status = {"status": "healthy", "details": {}}

    retries, delay = 5, 5

    # Check database connectivity
    for attempt in range(retries):
        try:
            db = SessionLocal()
            db.execute("SELECT 1")
            health_status["details"]["database"] = "healthy"
            db.close()
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

    # Check salle-service connectivity via API Gateway
    for attempt in range(retries):
        try:
            response = requests.get(SALLE_SERVICE_URL, timeout=5)
            if response.status_code == 200:
                health_status["details"]["salle_service"] = "healthy"
                break
            else:
                raise Exception(f"Unexpected status code: {response.status_code}")
        except Exception as e:
            logger.warning(f"Salle service health check retry {attempt + 1}/{retries}: {str(e)}")
            if attempt == retries - 1:
                logger.error(f"Salle service health check failed: {str(e)}")
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