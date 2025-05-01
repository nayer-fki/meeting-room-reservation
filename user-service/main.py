import httpx
from fastapi import FastAPI, Request, HTTPException, responses
from authlib.integrations.starlette_client import OAuth
from starlette.middleware.sessions import SessionMiddleware
import os
import logging
import secrets
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

# Add SessionMiddleware with a fixed secret key
SESSION_SECRET_KEY = os.getenv("SESSION_SECRET_KEY", "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6")
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET_KEY,
    same_site="lax",  # Use "lax" for local testing; switch to "strict" in production
    https_only=False,  # Set to True in production with HTTPS
    max_age=1209600  # 14 days
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

# OAuth Redirect URI (configurable via environment variable)
OAUTH_REDIRECT_URI = os.getenv("OAUTH_REDIRECT_URI", "http://localhost:8080/api/auth")

# Frontend Redirect URL
FRONTEND_REDIRECT_URL = os.getenv("FRONTEND_REDIRECT_URL", "http://localhost:3000/dashboard")
if not FRONTEND_REDIRECT_URL:
    raise ValueError("FRONTEND_REDIRECT_URL must be set in environment variables")

# Kafka Producer with retry logic
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
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

# Create the users table with role column
def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                sub VARCHAR(255) UNIQUE NOT NULL,
                email VARCHAR(255) NOT NULL,
                name VARCHAR(255) NOT NULL,
                picture TEXT,
                role VARCHAR(50) DEFAULT 'visitor'  -- Added role column
            )
        """)
        conn.commit()
        logger.info("Users table created or already exists")
    except Exception as e:
        logger.error(f"Error creating users table: {str(e)}")
        raise
    finally:
        cursor.close()
        conn.close()

# Initialize the database on startup
@app.on_event("startup")
async def startup_event():
    init_db()

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
    redirect_uri=OAUTH_REDIRECT_URI
)

@app.get("/login")
async def login(request: Request):
    redirect_uri = OAUTH_REDIRECT_URI
    state = secrets.token_hex(16)
    logger.info(f"Generated state: {state}")
    
    # Store the state in the session
    request.session['oauth_state'] = state
    logger.info(f"Stored oauth_state in session: {state}")
    
    # Authorize redirect to Google
    response = await oauth.google.authorize_redirect(request, redirect_uri, state=state)
    return response

@app.get("/auth")
async def auth(request: Request):
    try:
        # Get state from query params and session
        state_from_request = request.query_params.get('state')
        state_from_session = request.session.get('oauth_state')
        logger.info(f"State from request: {state_from_request}")
        logger.info(f"State from session: {state_from_session}")
        logger.info(f"Full query params: {request.query_params}")
        logger.info(f"All cookies: {request.cookies}")

        if not state_from_request or not state_from_session:
            logger.warning("State missing: CSRF warning")
            raise HTTPException(status_code=400, detail="State missing: CSRF warning")
        if state_from_request != state_from_session:
            logger.warning("State mismatch: CSRF warning")
            raise HTTPException(status_code=400, detail="State mismatch: CSRF warning")

        # Clear the state from the session
        request.session.pop('oauth_state', None)

        # Fetch the token
        code = request.query_params.get('code')
        if not code:
            logger.warning("No code provided in callback")
            raise HTTPException(status_code=400, detail="No code provided in callback")

        token_url = "https://accounts.google.com/o/oauth2/token"
        client_id = GOOGLE_CLIENT_ID
        client_secret = GOOGLE_CLIENT_SECRET
        redirect_uri = OAUTH_REDIRECT_URI

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

        # Fetch user info
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

        # Validate user info fields
        required_fields = ["sub", "email", "name"]
        for field in required_fields:
            if field not in user or not user[field]:
                logger.warning(f"Missing or empty required field: {field}")
                raise HTTPException(status_code=400, detail="Invalid user info")

        # Sanitize user name
        if not isinstance(user["name"], str) or any(ord(char) < 32 or ord(char) > 126 for char in user["name"]):
            logger.warning(f"Invalid characters in name: {user['name']}. Sanitizing...")
            user["name"] = "".join(char for char in user["name"] if 32 <= ord(char) <= 126)

        # Store user in PostgreSQL with role
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            # Assign role based on email domain (configurable via environment variables)
            ADMIN_EMAIL_DOMAIN = os.getenv("ADMIN_EMAIL_DOMAIN", "admin.com")
            EMPLOYEE_EMAIL_DOMAIN = os.getenv("EMPLOYEE_EMAIL_DOMAIN", "company.com")
            role = (
                "admin" if user["email"].endswith(f"@{ADMIN_EMAIL_DOMAIN}") else
                "employee" if user["email"].endswith(f"@{EMPLOYEE_EMAIL_DOMAIN}") else
                "visitor"
            )
            cursor.execute(
                """
                INSERT INTO users (sub, email, name, picture, role)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (sub) DO UPDATE
                SET email = EXCLUDED.email,
                    name = EXCLUDED.name,
                    picture = EXCLUDED.picture,
                    role = EXCLUDED.role
                RETURNING id
                """,
                (user["sub"], user["email"], user["name"], user.get("picture"), role)
            )
            user_id = cursor.fetchone()['id']
            conn.commit()
            logger.info(f"Stored user {user['sub']} with role {role} in database")
        except Exception as e:
            logger.error(f"Error storing user in database: {str(e)}")
            raise HTTPException(status_code=500, detail="Failed to store user")
        finally:
            cursor.close()
            conn.close()

        # Generate JWT with role
        payload = {
            "sub": user["sub"],
            "email": user["email"],
            "name": user["name"],
            "role": role,
            "exp": datetime.utcnow() + timedelta(days=14)
        }
        logger.info(f"Generating JWT with payload: {payload}")
        jwt_token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
        logger.info(f"Generated JWT token: {jwt_token}")
        user["token"] = jwt_token

        # Publish user_authenticated event to Kafka
        user_event = {
            "event_type": "user_authenticated",
            "user_id": user["sub"],
            "email": user["email"],
            "role": role,
            "timestamp": datetime.utcnow().isoformat()
        }
        producer.send('user-events', user_event)
        producer.flush()
        logger.info(f"Published user_authenticated event: {user_event}")

        # Set JWT in a cookie
        response = responses.RedirectResponse(url=FRONTEND_REDIRECT_URL)
        response.set_cookie(
            key="jwt_token",
            value=jwt_token,
            httponly=True,
            samesite="lax",  # Use "lax" for local testing; switch to "strict" in production
            secure=False,  # Set to True in production with HTTPS
            max_age=1209600  # 14 days
        )
        return response
    except Exception as e:
        logger.error(f"Authentication error: {str(e)}")
        raise HTTPException(status_code=500, detail="Authentication failed")

@app.get("/users/me")
async def get_current_user(request: Request):
    # Try to get the token from the Authorization header first
    jwt_token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not jwt_token:
        # If not in header, fall back to cookie
        jwt_token = request.cookies.get("jwt_token")
    if not jwt_token:
        logger.warning("No JWT token provided")
        raise HTTPException(status_code=401, detail="Not logged in")
    
    conn = None
    cursor = None
    try:
        logger.info(f"Verifying JWT token")
        payload = jwt.decode(jwt_token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        logger.info(f"JWT payload: {payload}")

        # Validate payload fields
        required_fields = ["sub", "email", "name", "role", "exp"]
        for field in required_fields:
            if field not in payload or not payload[field]:
                logger.warning(f"Invalid token: Missing or empty field: {field}")
                raise HTTPException(status_code=401, detail="Invalid token")

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT sub, email, name, picture, role FROM users WHERE sub = %s", (payload["sub"],))
        user = cursor.fetchone()
        if not user:
            logger.warning(f"User {payload['sub']} not found in database")
            raise HTTPException(status_code=404, detail="User not found")
        # Convert RealDictRow to a regular dict and add the token
        user_dict = dict(user)
        user_dict["token"] = jwt_token
        return {"user": user_dict}
    except jwt.ExpiredSignatureError as e:
        logger.error(f"JWT token expired: {str(e)}")
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError as e:
        logger.error(f"Invalid JWT token: {str(e)}")
        raise HTTPException(status_code=401, detail="Invalid token")
    except Exception as e:
        logger.error(f"Error fetching user: {str(e)}")
        raise HTTPException(status_code=500, detail="Error fetching user")
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

@app.get("/health")
async def health_check():
    health_status = {"status": "healthy", "details": {}}

    # Check database connectivity
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        health_status["details"]["database"] = "healthy"
        cursor.close()
        conn.close()
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

    if health_status["status"] == "unhealthy":
        raise HTTPException(status_code=503, detail=health_status)
    return health_status

@app.get("/favicon.ico")
async def favicon():
    return {"message": "No favicon"}

@app.get("/")
async def root():
    return {"message": "User Service is running"}