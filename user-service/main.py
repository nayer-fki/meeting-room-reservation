from fastapi import FastAPI, Request, HTTPException, responses
from authlib.integrations.starlette_client import OAuth
from starlette.config import Config
from starlette.middleware.sessions import SessionMiddleware
import os
import logging
import secrets
import httpx

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI()

# Load environment variables from .env
config = Config('.env')
oauth = OAuth(config)

# Register Google OAuth (still needed for authorize_redirect)
oauth.register(
    name='google',
    client_id=config('GOOGLE_CLIENT_ID'),
    client_secret=config('GOOGLE_CLIENT_SECRET'),
    authorize_url='https://accounts.google.com/o/oauth2/auth',
    access_token_url='https://accounts.google.com/o/oauth2/token',
    userinfo_endpoint='https://www.googleapis.com/oauth2/v3/userinfo',
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'},
    redirect_uri='http://localhost:8001/auth'
)

# Add session middleware with a strong secret key, lax same-site policy, and secure settings
app.add_middleware(
    SessionMiddleware,
    secret_key=secrets.token_hex(32),
    same_site='lax',
    https_only=False,  # Set to True in production with HTTPS
    max_age=86400  # 24 hours
)

@app.get("/login")
async def login(request: Request):
    # Check if user is already logged in
    if request.session.get('user'):
        return responses.RedirectResponse(url='/users/me')
    
    redirect_uri = "http://localhost:8001/auth"
    # Generate a state and store it in the session
    state = secrets.token_hex(16)
    request.session['oauth_state'] = state
    logger.info(f"Generated state for login: {state}")
    logger.info(f"Session after setting state: {request.session}")
    return await oauth.google.authorize_redirect(request, redirect_uri, state=state)

@app.get("/auth")
async def auth(request: Request):
    try:
        # Log request headers to debug duplicate requests
        logger.info(f"Request headers: {dict(request.headers)}")

        # Log the state from the request and session
        state_from_request = request.query_params.get('state')
        state_from_session = request.session.get('oauth_state')
        logger.info(f"State from request: {state_from_request}")
        logger.info(f"State from session: {state_from_session}")
        logger.info(f"Session in auth: {request.session}")
        logger.info(f"Full query params: {request.query_params}")

        # Validate state
        if not state_from_request or not state_from_session:
            raise HTTPException(status_code=400, detail="State missing: CSRF warning")
        if state_from_request != state_from_session:
            raise HTTPException(status_code=400, detail="State mismatch: CSRF warning")

        # Manually fetch the token
        code = request.query_params.get('code')
        if not code:
            raise HTTPException(status_code=400, detail="No code provided in callback")

        token_url = "https://accounts.google.com/o/oauth2/token"
        client_id = config('GOOGLE_CLIENT_ID')
        client_secret = config('GOOGLE_CLIENT_SECRET')
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

        # Manually fetch user info using the access token
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

        # Store user info in session
        request.session['user'] = dict(user)
        # Clear the state from session after successful auth
        request.session.pop('oauth_state', None)
        return responses.RedirectResponse(url='/users/me')
    except Exception as e:
        logger.error(f"Authentication error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Authentication error: {str(e)}")

@app.get("/users/me")
async def get_current_user(request: Request):
    user = request.session.get('user')
    if not user:
        return {"message": "Not logged in"}
    return {"user": user}

@app.get("/test-session")
async def test_session(request: Request):
    # Test session persistence
    request.session['test'] = 'session-working'
    logger.info(f"Set test session: {request.session}")
    return {"message": "Session test set", "session": dict(request.session)}

@app.get("/check-session")
async def check_session(request: Request):
    logger.info(f"Check session: {request.session}")
    return {"message": "Session check", "session": dict(request.session)}

@app.get("/favicon.ico")
async def favicon():
    return {"message": "No favicon"}

@app.get("/")
async def root():
    return {"message": "User Service is running"}