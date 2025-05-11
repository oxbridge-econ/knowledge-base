"""Module to handle the main FastAPI application and its endpoints."""
import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from jose import jwt
from router import content, service, file
from starlette.middleware.base import BaseHTTPMiddleware

SECRET_KEY = "your-secret-key"
ALGORITHM = "HS256"

class SessionMiddleware(BaseHTTPMiddleware):
    """
    Middleware to manage session data using JWT (JSON Web Tokens) stored in cookies.

    This middleware intercepts incoming HTTP requests to extract session data from a 
    "session_token" cookie. If the cookie exists and contains a valid JWT, the session 
    data is decoded and attached to the request's state. If the cookie is missing or 
    invalid, an empty session is initialized.

    After processing the request, the middleware encodes the updated session data into 
    a new JWT and sets it as a "session_token" cookie in the response.

    Attributes:
        SECRET_KEY (str): The secret key used to encode and decode the JWT.
        ALGORITHM (str): The algorithm used for encoding and decoding the JWT.

    Methods:
        dispatch(request: Request, call_next): Intercepts the request to manage session 
        data and modifies the response to include the updated session token.

    Cookie Parameters:
        session_token (str): A JWT containing session data. This cookie is HTTP-only 
        and has a maximum age of 3600 seconds (1 hour).

    Raises:
        jwt.JWTError: If the session token cannot be decoded due to invalid signature 
        or other issues.
    """
    async def dispatch(self, request: Request, call_next):
        session_token = request.cookies.get("session_token")
        if session_token:
            try:
                session_data = jwt.decode(session_token, SECRET_KEY, algorithms=[ALGORITHM])
            except jwt.JWTError:
                session_data = {}
        else:
            session_data = {}
        request.state.session = session_data
        response = await call_next(request)
        session_token = jwt.encode(request.state.session, SECRET_KEY, algorithm=ALGORITHM)
        response.set_cookie(
            key="session_token",
            value=session_token,
            httponly=True,
            max_age=3600
        )
        return response

logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(funcName)s - %(message)s')
logging.getLogger().setLevel(logging.INFO)

app = FastAPI(docs_url="/")

app.include_router(content.router)
app.include_router(service.router)
app.include_router(file.router)

origins = [
    "*"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials = True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(SessionMiddleware)

@app.get("/_health")
def health():
    """
    Returns the health status of the application.

    :return: A string "OK" indicating the health status.
    """
    return "OK"
