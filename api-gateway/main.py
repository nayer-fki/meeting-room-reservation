import os
import logging
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
import httpx
import jwt
from dotenv import load_dotenv
import time

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Environment variables
USER_SERVICE_URL = os.getenv("USER_SERVICE_URL", "http://user-service:8001")
SALLE_SERVICE_URL = os.getenv("SALLE_SERVICE_URL", "http://salle-service:8002")
RESERVATION_SERVICE_URL = os.getenv("RESERVATION_SERVICE_URL", "http://reservation-service:8003")
JWT_SECRET = os.getenv("JWT_SECRET")
HEALTH_CHECK_TIMEOUT = int(os.getenv("HEALTH_CHECK_TIMEOUT", 5))
CORS_ALLOWED_ORIGINS = os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:3000").split(",")

# Check required environment variables
required_env_vars = ["USER_SERVICE_URL", "SALLE_SERVICE_URL", "RESERVATION_SERVICE_URL", "JWT_SECRET"]
for var in required_env_vars:
    if not os.getenv(var):
        raise ValueError(f"{var} must be set in environment variables")

JWT_ALGORITHM = "HS256"

# Initialize FastAPI app
app = FastAPI()

# Add CORS middleware for React frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Dependency to extract and validate JWT token
async def get_current_user(request: Request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not token:
        token = request.cookies.get("jwt_token")
        if not token:
            logger.error("Missing or invalid Authorization header and no jwt_token cookie")
            raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        logger.error("Token has expired")
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError as e:
        logger.error(f"Token validation failed: {str(e)}")
        raise HTTPException(status_code=401, detail="Invalid token")

# Helper function for proxying requests with retry logic
async def proxy_request(service_url: str, endpoint: str, method: str, headers: dict, json_data: dict = None, params: dict = None, retries: int = 3, delay: int = 5):
    async with httpx.AsyncClient(follow_redirects=False) as client:
        for attempt in range(retries):
            try:
                url = f"{service_url}{endpoint}"
                if method == "GET":
                    response = await client.get(url, headers=headers, params=params, timeout=HEALTH_CHECK_TIMEOUT)
                elif method == "POST":
                    response = await client.post(url, headers=headers, json=json_data, timeout=HEALTH_CHECK_TIMEOUT)
                elif method == "PUT":
                    response = await client.put(url, headers=headers, json=json_data, timeout=HEALTH_CHECK_TIMEOUT)
                elif method == "DELETE":
                    response = await client.delete(url, headers=headers, timeout=HEALTH_CHECK_TIMEOUT)
                else:
                    raise ValueError(f"Unsupported HTTP method: {method}")
                if response.status_code not in {301, 302, 307}:
                    response.raise_for_status()
                return response
            except httpx.HTTPStatusError as e:
                logger.error(f"Downstream service error: {e.response.status_code}, {e.response.text}")
                raise HTTPException(status_code=e.response.status_code, detail=e.response.text)
            except Exception as e:
                logger.warning(f"Request to {service_url}{endpoint} failed (attempt {attempt + 1}/{retries}): {str(e)}")
                if attempt == retries - 1:
                    logger.error(f"Request to downstream service failed after {retries} attempts: {str(e)}")
                    raise HTTPException(status_code=503, detail="Service unavailable")
                time.sleep(delay)

# Proxy route for user-service: Login
@app.get("/api/login")
async def proxy_login(request: Request):
    headers = dict(request.headers)
    response = await proxy_request(USER_SERVICE_URL, "/login", "GET", headers)
    if response.status_code in (301, 302, 307):
        redirect_url = response.headers.get("location")
        if redirect_url:
            redirect_response = Response(
                status_code=response.status_code,
                headers={"location": redirect_url},
                content=""
            )
            set_cookie = response.headers.get("set-cookie")
            if set_cookie:
                redirect_response.headers["set-cookie"] = set_cookie
            return redirect_response
        else:
            raise HTTPException(status_code=500, detail="Redirect URL not found in response")
    raise HTTPException(status_code=response.status_code, detail=response.text)

# Proxy route for user-service: Auth callback
@app.get("/api/auth")
async def proxy_auth(request: Request):
    headers = dict(request.headers)
    response = await proxy_request(USER_SERVICE_URL, "/auth", "GET", headers, params=request.query_params)
    if response.status_code in (301, 302, 307):
        redirect_url = response.headers.get("location")
        if redirect_url:
            redirect_response = Response(
                status_code=response.status_code,
                headers={"location": redirect_url},
                content=""
            )
            set_cookie = response.headers.get("set-cookie")
            if set_cookie:
                redirect_response.headers["set-cookie"] = set_cookie
            return redirect_response
        else:
            raise HTTPException(status_code=500, detail="Redirect URL not found in response")
    raise HTTPException(status_code=response.status_code, detail=response.text)

# Proxy route for user-service: Get current user
@app.get("/api/users/me")
async def proxy_user_me(request: Request, user: dict = Depends(get_current_user)):
    token = request.headers.get("Authorization", "").replace("Bearer ", "") or request.cookies.get("jwt_token")
    headers = {"Authorization": f"Bearer {token}"}
    response = await proxy_request(USER_SERVICE_URL, "/users/me", "GET", headers)
    return response.json()

# Proxy route for user-service: Get all users (admin only)
@app.get("/api/users/")
async def proxy_get_users(request: Request, user: dict = Depends(get_current_user)):
    if user.get("role") != "admin":
        logger.error(f"User {user['sub']} attempted to access all users without admin privileges")
        raise HTTPException(status_code=403, detail="Admin access required")
    token = request.headers.get("Authorization", "").replace("Bearer ", "") or request.cookies.get("jwt_token")
    headers = {"Authorization": f"Bearer {token}"}
    response = await proxy_request(USER_SERVICE_URL, "/users/", "GET", headers)
    return response.json()

# Proxy route for salle-service: Create room
@app.post("/api/rooms/")
async def proxy_create_room(request: Request, user: dict = Depends(get_current_user)):
    token = request.headers.get("Authorization", "").replace("Bearer ", "") or request.cookies.get("jwt_token")
    headers = {"Authorization": f"Bearer {token}"}
    json_data = await request.json()
    response = await proxy_request(SALLE_SERVICE_URL, "/rooms/", "POST", headers, json_data=json_data)
    return response.json()

# Proxy route for salle-service: Get all rooms
@app.get("/api/salles/")
async def proxy_get_rooms(request: Request, user: dict = Depends(get_current_user)):
    token = request.headers.get("Authorization", "").replace("Bearer ", "") or request.cookies.get("jwt_token")
    headers = {"Authorization": f"Bearer {token}"}
    response = await proxy_request(SALLE_SERVICE_URL, "/salles/", "GET", headers)
    return response.json()

# Proxy route for salle-service: Get a specific room
@app.get("/api/rooms/{room_id}")
async def proxy_get_room(room_id: int, request: Request, user: dict = Depends(get_current_user)):
    token = request.headers.get("Authorization", "").replace("Bearer ", "") or request.cookies.get("jwt_token")
    headers = {"Authorization": f"Bearer {token}"}
    response = await proxy_request(SALLE_SERVICE_URL, f"/rooms/{room_id}", "GET", headers)
    return response.json()

# Proxy route for reservation-service: Create reservation
@app.post("/api/reservations/")
async def proxy_create_reservation(request: Request, user: dict = Depends(get_current_user)):
    token = request.headers.get("Authorization", "").replace("Bearer ", "") or request.cookies.get("jwt_token")
    headers = {"Authorization": f"Bearer {token}"}
    json_data = await request.json()
    response = await proxy_request(RESERVATION_SERVICE_URL, "/reservations/", "POST", headers, json_data=json_data)
    return response.json()

# Proxy route for reservation-service: Get reservation history
@app.get("/api/reservations/history")
async def proxy_get_reservation_history(request: Request, user: dict = Depends(get_current_user)):
    token = request.headers.get("Authorization", "").replace("Bearer ", "") or request.cookies.get("jwt_token")
    headers = {"Authorization": f"Bearer {token}"}
    response = await proxy_request(RESERVATION_SERVICE_URL, "/reservations/history", "GET", headers)
    return response.json()

# Proxy route for reservation-service: Get all reservations
@app.get("/api/reservations/")
async def proxy_get_reservations(request: Request, user: dict = Depends(get_current_user)):
    token = request.headers.get("Authorization", "").replace("Bearer ", "") or request.cookies.get("jwt_token")
    headers = {"Authorization": f"Bearer {token}"}
    response = await proxy_request(RESERVATION_SERVICE_URL, "/reservations/", "GET", headers)
    return response.json()

# Proxy route for reservation-service: Get pending reservations (employee only)
@app.get("/api/reservations/pending")
async def proxy_get_pending_reservations(request: Request, user: dict = Depends(get_current_user)):
    token = request.headers.get("Authorization", "").replace("Bearer ", "") or request.cookies.get("jwt_token")
    headers = {"Authorization": f"Bearer {token}"}
    response = await proxy_request(RESERVATION_SERVICE_URL, "/reservations/pending", "GET", headers)
    return response.json()

# Proxy route for reservation-service: Handle reservation request (accept/refuse)
@app.post("/api/reservations/request/{reservation_id}/{action}")
async def proxy_handle_reservation_request(
    reservation_id: int,
    action: str,
    request: Request,
    user: dict = Depends(get_current_user)
):
    token = request.headers.get("Authorization", "").replace("Bearer ", "") or request.cookies.get("jwt_token")
    headers = {"Authorization": f"Bearer {token}"}
    json_data = await request.json()
    response = await proxy_request(
        RESERVATION_SERVICE_URL,
        f"/reservations/request/{reservation_id}/{action}",
        "POST",
        headers,
        json_data=json_data
    )
    return response.json()

# Proxy route for reservation-service: Delete reservation
@app.delete("/api/reservations/{reservation_id}")
async def proxy_delete_reservation(reservation_id: int, request: Request, user: dict = Depends(get_current_user)):
    token = request.headers.get("Authorization", "").replace("Bearer ", "") or request.cookies.get("jwt_token")
    headers = {"Authorization": f"Bearer {token}"}
    response = await proxy_request(RESERVATION_SERVICE_URL, f"/reservations/{reservation_id}", "DELETE", headers)
    return response.json()

# Proxy route for reservation-service: Update reservation status (admin only)
@app.put("/api/reservations/{reservation_id}/status")
async def proxy_update_reservation_status(
    reservation_id: int,
    request: Request,
    user: dict = Depends(get_current_user)
):
    token = request.headers.get("Authorization", "").replace("Bearer ", "") or request.cookies.get("jwt_token")
    headers = {"Authorization": f"Bearer {token}"}
    json_data = await request.json()
    response = await proxy_request(
        RESERVATION_SERVICE_URL,
        f"/reservations/{reservation_id}/status",
        "PUT",
        headers,
        json_data=json_data
    )
    return response.json()

# Proxy route for reservation-service: Update reservation priority (admin only)
@app.put("/api/reservations/{reservation_id}/priority")
async def proxy_update_reservation_priority(
    reservation_id: int,
    request: Request,
    user: dict = Depends(get_current_user)
):
    token = request.headers.get("Authorization", "").replace("Bearer ", "") or request.cookies.get("jwt_token")
    headers = {"Authorization": f"Bearer {token}"}
    json_data = await request.json()
    response = await proxy_request(
        RESERVATION_SERVICE_URL,
        f"/reservations/{reservation_id}/priority",
        "PUT",
        headers,
        json_data=json_data
    )
    return response.json()

# Health check endpoint with retry logic
@app.get("/api/health")
async def health_check():
    health_status = {"status": "healthy", "details": {}}

    retries, delay = 3, 5
    async with httpx.AsyncClient() as client:
        for service_name, service_url in [
            ("user_service", USER_SERVICE_URL),
            ("salle_service", SALLE_SERVICE_URL),
            ("reservation_service", RESERVATION_SERVICE_URL),
        ]:
            for attempt in range(retries):
                try:
                    response = await client.get(f"{service_url}/health", timeout=HEALTH_CHECK_TIMEOUT)
                    response.raise_for_status()
                    health_status["details"][service_name] = response.json()
                    break
                except Exception as e:
                    logger.warning(f"{service_name} health check retry {attempt + 1}/{retries}: {str(e)}")
                    if attempt == retries - 1:
                        logger.error(f"{service_name} health check failed: {str(e)}")
                        health_status["details"][service_name] = f"unhealthy: {str(e)}"
                        health_status["status"] = "unhealthy"
                    time.sleep(delay)

    if health_status["status"] == "unhealthy":
        raise HTTPException(status_code=503, detail=health_status)
    return health_status

# Root endpoint
@app.get("/")
async def root():
    return {"message": "API Gateway is running"}