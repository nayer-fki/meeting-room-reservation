from fastapi import FastAPI, Request, HTTPException, responses
from fastapi.middleware.cors import CORSMiddleware  # Add CORS middleware import
from authlib.integrations.starlette_client import OAuth
from starlette.middleware.sessions import SessionMiddleware
import os
import logging
import secrets
import httpx
import jwt
from datetime import datetime, timedelta
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

# Add SessionMiddleware with a secret key
app.add_middleware(SessionMiddleware, secret_key=secrets.token_hex(32))

# Add CORS middleware to allow requests from the frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Load environment variables
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
    raise ValueError("GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET must be set in environment variables")

# JWT Secret
JWT_SECRET = os.getenv("JWT_SECRET")
if not JWT_SECRET:
    raise ValueError("JWT_SECRET must be set in environment variables")
logger.info(f"Using JWT_SECRET: {JWT_SECRET}")
JWT_ALGORITHM = "HS256"

# Kafka Producer with retry logic
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
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
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL must be set in environment variables")
    
    for attempt in range(retries):
        try:
            conn = psycopg2.connect(
                database_url,
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

# Helper to check if user is admin
def check_admin(user):
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

# Register Google OAuth
oauth = OAuth()
oauth.register(
    name='google',
    client_id=GOOGLE_CLIENT_ID,
    client_secret=GOOGLE_CLIENT_SECRET,
    authorize_url='https://accounts.google.com/o/oauth2/auth',
    access_token_url='https://accounts.google.com/o/oauth2/token',
    userinfo_endpoint='https://www.googleapis.com/oauth2/v3/userinfo',
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'},
    redirect_uri='http://localhost:8001/auth'
)

@app.get("/login")
async def login(request: Request):
    redirect_uri = "http://localhost:8001/auth"
    state = secrets.token_hex(16)
    logger.info(f"Generated state: {state}")
    response = await oauth.google.authorize_redirect(request, redirect_uri, state=state)
    response.set_cookie(key="oauth_state", value=state, httponly=True, samesite="lax", max_age=3600)
    logger.info(f"Set oauth_state cookie with value: {state}")
    return response

@app.get("/auth")
async def auth(request: Request):
    try:
        state_from_request = request.query_params.get('state')
        state_from_cookie = request.cookies.get('oauth_state')
        logger.info(f"State from request: {state_from_request}")
        logger.info(f"State from cookie: {state_from_cookie}")
        logger.info(f"Full query params: {request.query_params}")
        logger.info(f"All cookies: {request.cookies}")

        if not state_from_request or not state_from_cookie:
            raise HTTPException(status_code=400, detail="State missing: CSRF warning")
        if state_from_request != state_from_cookie:
            raise HTTPException(status_code=400, detail="State mismatch: CSRF warning")

        code = request.query_params.get('code')
        if not code:
            raise HTTPException(status_code=400, detail="No code provided in callback")

        token_url = "https://accounts.google.com/o/oauth2/token"
        client_id = GOOGLE_CLIENT_ID
        client_secret = GOOGLE_CLIENT_SECRET
        redirect_uri = "http://localhost:8001/auth"

        logger.info("Manually fetching access token...")
        async with httpx.AsyncClient() as client:
            response = await client.post(
                token_url,
                data={
                    "code": code,
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code"
                }
            )
            response.raise_for_status()
            token = response.json()
        logger.info(f"Received token: {token}")

        userinfo_endpoint = "https://www.googleapis.com/oauth2/v3/userinfo"
        logger.info("Manually fetching user info...")
        async with httpx.AsyncClient() as client:
            response = await client.get(
                userinfo_endpoint,
                headers={"Authorization": f"Bearer {token['access_token']}"}
            )
            response.raise_for_status()
            user = response.json()
        logger.info(f"Received user info: {user}")

        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            # Insert or update user, but preserve the existing role
            cursor.execute(
                """
                INSERT INTO users (sub, email, name, picture, role)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (sub) DO UPDATE
                SET email = EXCLUDED.email,
                    name = EXCLUDED.name,
                    picture = EXCLUDED.picture
                RETURNING id, sub, email, name, picture, role
                """,
                (user["sub"], user["email"], user["name"], user.get("picture"), "employee")
            )
            db_user = cursor.fetchone()
            conn.commit()

            # Fetch the user again to ensure we have the latest role
            cursor.execute(
                "SELECT id, sub, email, name, picture, role FROM users WHERE sub = %s",
                (user["sub"],)
            )
            db_user = cursor.fetchone()
        except Exception as e:
            logger.error(f"Error storing user in database: {str(e)}")
            raise HTTPException(status_code=500, detail="Failed to store user")
        finally:
            cursor.close()
            conn.close()

        payload = {
            "sub": db_user["sub"],
            "email": db_user["email"],
            "name": db_user["name"],
            "role": db_user["role"],
            "exp": datetime.utcnow() + timedelta(hours=24)
        }
        jwt_token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

        user_event = {
            "event_type": "user_authenticated",
            "user_id": db_user["sub"],
            "email": db_user["email"],
            "timestamp": datetime.utcnow().isoformat()
        }
        producer.send('user-events', user_event)
        producer.flush()
        logger.info(f"Published user_authenticated event: {user_event}")

        # Redirect to the frontend with the token as a query parameter
        redirect_url = f'http://localhost:3000/auth-callback?token={jwt_token}'
        response = responses.RedirectResponse(url=redirect_url)
        response.delete_cookie("oauth_state")
        return response
    except Exception as e:
        logger.error(f"Authentication error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Authentication error: {str(e)}")
    

@app.get("/users/me")
async def get_current_user(request: Request):
    jwt_token = request.cookies.get("jwt_token")
    if not jwt_token:
        return {"message": "Not logged in"}
    try:
        payload = jwt.decode(jwt_token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT sub, email, name, picture, role FROM users WHERE sub = %s", (payload["sub"],))
            user = cursor.fetchone()
            if not user:
                return {"message": "User not found"}
            user_dict = dict(user)
            user_dict["token"] = jwt_token
            return {"user": user_dict}
        finally:
            cursor.close()
            conn.close()
    except Exception as e:
        logger.error(f"Error fetching user: {str(e)}")
        return {"message": "Invalid token"}

# Admin endpoints to manage users
@app.get("/users/", response_model=list)
async def get_all_users(request: Request):
    jwt_token = request.cookies.get("jwt_token")
    if not jwt_token:
        raise HTTPException(status_code=401, detail="Not logged in")
    try:
        payload = jwt.decode(jwt_token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        check_admin(payload)
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT id, sub, email, name, picture, role FROM users")
            users = cursor.fetchall()
            return [dict(user) for user in users]
        finally:
            cursor.close()
            conn.close()
    except Exception as e:
        logger.error(f"Error fetching users: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to fetch users")

@app.put("/users/{user_id}/role")
async def update_user_role(user_id: int, role: str, request: Request):
    if role not in ["employee", "admin"]:
        raise HTTPException(status_code=400, detail="Invalid role")
    jwt_token = request.cookies.get("jwt_token")
    if not jwt_token:
        raise HTTPException(status_code=401, detail="Not logged in")
    try:
        payload = jwt.decode(jwt_token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        check_admin(payload)
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "UPDATE users SET role = %s WHERE id = %s RETURNING id, sub, email, name, picture, role",
                (role, user_id)
            )
            updated_user = cursor.fetchone()
            if not updated_user:
                raise HTTPException(status_code=404, detail="User not found")
            conn.commit()
            return dict(updated_user)
        finally:
            cursor.close()
            conn.close()
    except Exception as e:
        logger.error(f"Error updating user role: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to update user role")

@app.delete("/users/{user_id}")
async def delete_user(user_id: int, request: Request):
    jwt_token = request.cookies.get("jwt_token")
    if not jwt_token:
        raise HTTPException(status_code=401, detail="Not logged in")
    try:
        payload = jwt.decode(jwt_token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        check_admin(payload)
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("DELETE FROM users WHERE id = %s RETURNING id", (user_id,))
            deleted_user = cursor.fetchone()
            if not deleted_user:
                raise HTTPException(status_code=404, detail="User not found")
            conn.commit()
            return {"message": f"User {user_id} deleted"}
        finally:
            cursor.close()
            conn.close()
    except Exception as e:
        logger.error(f"Error deleting user: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to delete user")

@app.get("/health")
async def health_check():
    health_status = {"status": "healthy", "details": {}}

    # Check database connectivity
    retries, delay = 5, 5
    for attempt in range(retries):
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT 1")  # Simple connectivity check
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
            # Check if Kafka broker is reachable without sending a message
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

@app.get("/favicon.ico")
async def favicon():
    return {"message": "No favicon"}

@app.get("/")
async def root():
    return {"message": "User Service is running"}