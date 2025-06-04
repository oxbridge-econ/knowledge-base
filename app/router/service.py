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
    collection = MongodbClient["service"]["gmail"]
    cred_dict = collection.find_one({"_id": email}, projection={"token": 1, "refresh_token": 1})
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
    service = GmailService(credentials)
    task_id = f"{str(uuid.uuid4())}"
    task_states[task_id] = "Pending"
    threading.Thread(target=service.collect, args=[body, task_id]).start()
    body = body.model_dump()
    del body["max_results"]
    data = {
        "_id": email,
        "query": {k: v for k, v in body.items() if v is not None}
    }
    collection.update_one(
        { '_id': email },
        { '$set': data },
        upsert=True
    )
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
    collection = MongodbClient["service"]["gmail"]
    cred_dict = collection.find_one({"_id": email}, projection={"token": 1, "refresh_token": 1})
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
    return JSONResponse(content=service.preview(body))

@router.get("/gmail/query")
def get_query(email: str = Query(...)) -> JSONResponse:
    """
    Submits an email query and stores or updates it in the MongoDB collection.

    Args:
        body (EmailQuery): The email query data provided in the request body.
        email (str): The email address, provided as a query parameter.

    Returns:
        JSONResponse: A JSON response indicating whether the query was successfully updated ("success")
        or if there were no changes ("no changes").
    """
    collection = MongodbClient["service"]["gmail"]
    result = collection.find_one({"_id": email}, projection={"query": 1})
    del result["_id"]
    return JSONResponse(content=result["query"] if "query" in result else {}, status_code=200)

@router.post("/gmail/query")
def save_query(body: EmailQuery, email: str = Query(...)) -> JSONResponse:
    """
    save an email query and stores or updates it in the MongoDB collection.

    Args:
        body (EmailQuery): The email query data provided in the request body.
        email (str): The email address, provided as a query parameter.

    Returns:
        JSONResponse: A JSON response indicating whether the query was successfully updated ("success")
        or if there were no changes ("no changes").
    """
    collection = MongodbClient["service"]["gmail"]
    body = body.model_dump()
    del body["max_results"]
    data = {
        "_id": email,
        "query": {k: v for k, v in body.items() if v is not None}
    }
    result = collection.update_one(
        { '_id': email },
        { '$set': data },
        upsert=True
    )
    if result.modified_count > 0:
        return JSONResponse(content={"status": "success"}, status_code=200)
    return JSONResponse(content={"status": "no changes"}, status_code=200)

@router.get("/gmail")
def valid(email: str = Query(...)) -> JSONResponse:
    """
    Handles the chat POST request.

    Args:
        query (ReqData): The request data containing the query parameters.

    Returns:
        str: The generated response from the chat function.
    """
    collection = MongodbClient["service"]["gmail"]
    cred_dict = collection.find_one({"_id": email}, projection={"token": 1, "refresh_token": 1})
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
    return JSONResponse(content={"valid": True})
