"""Module for defining the main routes of the API."""
import os
import threading
from google.oauth2.credentials import Credentials
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from services import GmailService
from schema import MailReqData
from models.db import MongodbClient

router = APIRouter(prefix="/service", tags=["mail"])

@router.post("/gmail")
def collect(body: MailReqData) -> JSONResponse:
    """
    Handles the chat POST request.

    Args:
        query (ReqData): The request data containing the query parameters.

    Returns:
        str: The generated response from the chat function.
    """
    collection = MongodbClient["user"]["FinFAST"]
    cred_dict = collection.find_one({"_id": body.email})
    if cred_dict is None:
        return JSONResponse(content={"error": "User not found."}, status_code=404)
    credentials = Credentials(
        token=cred_dict["token"],
        refresh_token=cred_dict["refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ.get("CLIENT_ID"),
        client_secret=os.environ.get("CLIENT_SECRET"),
        scopes=["https://www.googleapis.com/auth/gmail.readonly"],
    )
    if not credentials.valid or credentials.expired:
        return JSONResponse(content={"valid": False,
                                     "error": "Invalid or expired credentials."}, status_code=401)
    service = GmailService(body.email)
    if body.query is not None:
        threading.Thread(target=service.collect, args=[body.query]).start()
        return JSONResponse(content={"message": "Mail collection in progress."})
    return JSONResponse(content={"error": "Query is required."}, status_code=400)


@router.get("/gmail")
def get(body: MailReqData) -> JSONResponse:
    """
    Handles the chat POST request.

    Args:
        query (ReqData): The request data containing the query parameters.

    Returns:
        str: The generated response from the chat function.
    """
    collection = MongodbClient["user"]["FinFAST"]
    cred_dict = collection.find_one({"_id": body.email})
    if cred_dict is None:
        return JSONResponse(content={"error": "User not found."}, status_code=404)
    credentials = Credentials(
        token=cred_dict["token"],
        refresh_token=cred_dict["refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ.get("CLIENT_ID"),
        client_secret=os.environ.get("CLIENT_SECRET"),
        scopes=["https://www.googleapis.com/auth/gmail.readonly"],
    )
    if not credentials.valid or credentials.expired:
        return JSONResponse(content={"valid": False}, status_code=401)
    service = GmailService(credentials)
    if body.query is not None:
        print(body.query)
        return JSONResponse(content=service.get(body.query))
    return JSONResponse(content={"valid": True})
