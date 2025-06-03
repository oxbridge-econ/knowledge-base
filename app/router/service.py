"""Module for defining the main routes of the API."""
import os
import threading
import uuid
from google.oauth2.credentials import Credentials
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from services import GmailService
from schema import EmailQuery, task_states
from models.db import MongodbClient

router = APIRouter(prefix="/service", tags=["service"])

@router.post("/gmail/collect")
def collect(body: EmailQuery, email: str = Query(...)) -> JSONResponse:
    """
    Handles the chat POST request.

    Args:
        query (ReqData): The request data containing the query parameters.

    Returns:
        str: The generated response from the chat function.
    """
    collection = MongodbClient["user"]["FinFAST"]
    cred_dict = collection.find_one({"_id": email})
    if cred_dict is None:
        return JSONResponse(content={"error": "User not found."}, status_code=404)
    credentials = Credentials(
        token=cred_dict["gmail"]["token"],
        refresh_token=cred_dict["gmail"]["refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ.get("CLIENT_ID"),
        client_secret=os.environ.get("CLIENT_SECRET"),
        scopes=["https://www.googleapis.com/auth/gmail.readonly"],
    )
    if not credentials.valid or credentials.expired:
        return JSONResponse(content={"valid": False,
                                     "error": "Invalid or expired credentials."}, status_code=401)
    service = GmailService(credentials)
    task_id = f"{str(uuid.uuid4())}"
    task_states[task_id] = "Pending"
    threading.Thread(target=service.collect, args=[body, task_id]).start()
    return JSONResponse(content={"id": task_id, "status": task_states[task_id]})

@router.post("/gmail/preview")
def preview(body: EmailQuery, email: str = Query(...)) -> JSONResponse:
    """
    Handles the chat POST request.

    Args:
        query (ReqData): The request data containing the query parameters.

    Returns:
        str: The generated response from the chat function.
    """
    collection = MongodbClient["user"]["FinFAST"]
    cred_dict = collection.find_one({"_id": email})
    if cred_dict is None:
        return JSONResponse(content={"error": "User not found."}, status_code=404)
    credentials = Credentials(
        token=cred_dict["gmail"]["token"],
        refresh_token=cred_dict["gmail"]["refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ.get("CLIENT_ID"),
        client_secret=os.environ.get("CLIENT_SECRET"),
        scopes=["https://www.googleapis.com/auth/gmail.readonly"],
    )
    if not credentials.valid or credentials.expired:
        return JSONResponse(content={"valid": False}, status_code=401)
    service = GmailService(credentials)
    return JSONResponse(content=service.get(body))

@router.get("/gmail")
def valid(email: str = Query(...)) -> JSONResponse:
    """
    Handles the chat POST request.

    Args:
        query (ReqData): The request data containing the query parameters.

    Returns:
        str: The generated response from the chat function.
    """
    collection = MongodbClient["user"]["FinFAST"]
    cred_dict = collection.find_one({"_id": email})
    if cred_dict is None:
        return JSONResponse(content={"error": "User not found."}, status_code=404)
    credentials = Credentials(
        token=cred_dict["gmail"]["token"],
        refresh_token=cred_dict["gmail"]["refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ.get("CLIENT_ID"),
        client_secret=os.environ.get("CLIENT_SECRET"),
        scopes=["https://www.googleapis.com/auth/gmail.readonly"],
    )
    if not credentials.valid or credentials.expired:
        return JSONResponse(content={"valid": False}, status_code=401)
    return JSONResponse(content={"valid": True})
