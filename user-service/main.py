from fastapi import FastAPI, Request, HTTPException, responses
from authlib.integrations.starlette_client import OAuth
from starlette.middleware.sessions import SessionMiddleware  # Add this import
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

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI()

# Add SessionMiddleware with a secret key
app.add_middleware(SessionMiddleware, secret_key=secrets.token_hex(32))

# Load environment variables
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
    raise ValueError("GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET must be set in environment variables")

# JWT Secret (read from environment variables)
JWT_SECRET = os.getenv("JWT_SECRET")
if not JWT_SECRET:
    raise ValueError("JWT_SECRET must be set in environment variables")
logger.info(f"Using JWT_SECRET: {JWT_SECRET}")
JWT_ALGORITHM = "HS256"

# Kafka Producer
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
producer = KafkaProducer(
    bootstrap_servers=[KAFKA_BOOTSTRAP_SERVERS],
    value_serializer=lambda v: json.dumps(v).encode('utf-8')
)

# PostgreSQL connection
def get_db_connection():
    conn = psycopg2.connect(
        os.getenv("DATABASE_URL"),
        cursor_factory=RealDictCursor
    )
    return conn

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
        # Get state from cookie
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

        # Fetch the token
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

        # Store user in PostgreSQL
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO users (sub, email, name, picture)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (sub) DO UPDATE
                SET email = EXCLUDED.email,
                    name = EXCLUDED.name,
                    picture = EXCLUDED.picture
                RETURNING id
                """,
                (user["sub"], user["email"], user["name"], user.get("picture"))
            )
            user_id = cursor.fetchone()['id']
            conn.commit()
        except Exception as e:
            logger.error(f"Error storing user in database: {str(e)}")
            raise HTTPException(status_code=500, detail="Failed to store user")
        finally:
            cursor.close()
            conn.close()

        # Generate JWT
        payload = {
            "sub": user["sub"],
            "email": user["email"],
            "name": user["name"],
            "exp": datetime.utcnow() + timedelta(hours=24)
        }
        jwt_token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
        user["token"] = jwt_token

        # Publish user_authenticated event to Kafka
        user_event = {
            "event_type": "user_authenticated",
            "user_id": user["sub"],
            "email": user["email"],
            "timestamp": datetime.utcnow().isoformat()
        }
        producer.send('user-events', user_event)
        producer.flush()
        logger.info(f"Published user_authenticated event: {user_event}")

        # Set JWT in a cookie
        response = responses.RedirectResponse(url='/users/me')
        response.set_cookie(key="jwt_token", value=jwt_token, httponly=True, samesite="lax", max_age=86400)
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
        cursor.execute("SELECT sub, email, name, picture FROM users WHERE sub = %s", (payload["sub"],))
        user = cursor.fetchone()
        if not user:
            return {"message": "User not found"}
        # Convert RealDictRow to a regular dict and add the token
        user_dict = dict(user)
        user_dict["token"] = jwt_token
        return {"user": user_dict}
    except Exception as e:
        logger.error(f"Error fetching user: {str(e)}")
        return {"message": "Invalid token"}
    finally:
        cursor.close()
        conn.close()
        


@app.get("/favicon.ico")
async def favicon():
    return {"message": "No favicon"}

@app.get("/")
async def root():
    return {"message": "User Service is running"}