"""Module for defining the main routes of the API."""
import os
import threading
import uuid
from google.oauth2.credentials import Credentials
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from astrapy.constants import SortMode
from services import GmailService
from schema import EmailFilter, DocsReq, task_states
from models.db import MongodbClient, astra_collection
from controllers.utils import upsert

router = APIRouter(prefix="/service/gmail", tags=["service"])
collection = MongodbClient["service"]["gmail"]

@router.post("/collect")
def collect(body: EmailFilter, email: str = Query(...)) -> JSONResponse:
    """
    Collects Gmail data for a specified user and initiates an asynchronous collection task.

    Args:
        body (EmailQuery): The query parameters for the email collection.
        email (str, optional): The user's email address, provided as a query parameter.

    Returns:
        JSONResponse: 
            - If the user is not found, returns a 404 error with an appropriate message.
            - If the user's credentials are invalid or expired, returns a 401 error.
            - Otherwise, starts a background thread to collect emails,
              updates the user's query in the database,
              and returns a JSON response containing the task ID and its initial status.

    Raises:
        None

    Side Effects:
        - Starts a background thread for email collection.
        - Updates or inserts the user's query parameters in the MongoDB collection.
        - Modifies the global `task_states` dictionary with the new task's status.
    """
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
    task = {
        "id": f"{str(uuid.uuid4())}",
        "status": "Pending",
        "type": "Manual"
    }
    service = GmailService(credentials, email, task)
    body = body.model_dump()
    query = {k: v for k, v in body.items() if v is not None}
    threading.Thread(target=service.collect, args=[query]).start()
    del query["max_results"]
    data = {
        "_id": email,
        "query": query
    }
    collection.update_one(
        { '_id': email },
        { '$set': data },
        upsert=True
    )
    query["id"] = str(uuid.uuid4()) if "id" not in query else query["id"]
    task_states[task["id"]] = task["status"]
    upsert(email, query, collection=collection, size=10, field="queries")
    return JSONResponse(content=task)

@router.post("/preview")
def preview(body: EmailFilter, email: str = Query(...)) -> JSONResponse:
    """
    Handles the chat POST request.

    Args:
        query (ReqData): The request data containing the query parameters.

    Returns:
        str: The generated response from the chat function.
    """
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
    return JSONResponse(content=service.preview(body.model_dump()))

@router.get("/query")
def get_query(email: str = Query(...)) -> JSONResponse:
    """
    Submits an email query and stores or updates it in the MongoDB collection.

    Args:
        body (EmailQuery): The email query data provided in the request body.
        email (str): The email address, provided as a query parameter.

    Returns:
        JSONResponse: A JSON response indicating
        whether the query was successfully updated ("success")
        or if there were no changes ("no changes").
    """
    result = collection.find_one({"_id": email}, projection={"query": 1})
    del result["_id"]
    return JSONResponse(content=result["query"] if "query" in result else {}, status_code=200)

@router.get("")
def valid(email: str = Query(...)) -> JSONResponse:
    """
    Handles the chat POST request.

    Args:
        query (ReqData): The request data containing the query parameters.

    Returns:
        str: The generated response from the chat function.
    """
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

@router.get("/queries")
def get_queries(email: str = Query(...)) -> JSONResponse:
    """
    Retrieves all email queries for a specific user from the MongoDB collection.

    Args:
        email (str): The email address, provided as a query parameter.

    Returns:
        JSONResponse: A JSON response containing the user's email queries.
    """
    queries = collection.find_one({"_id": email}, projection={"queries": 1})
    if queries:
        del queries["_id"]
    else:
        queries = []
    return JSONResponse(content=queries, status_code=200)

@router.get("/docs")
def get_docs(body: DocsReq, email: str = Query(...)) -> JSONResponse:
    """
    Retrieves all documents for a specific user from the MongoDB collection.

    Args:
        email (str): The email address, provided as a query parameter.

    Returns:
        JSONResponse: A JSON response containing the user's documents.
    """
    cred_dict = collection.find_one({"_id": email}, projection={"token": 1, "refresh_token": 1})
    _filter = {
        "metadata.userId": email,
        "metadata.type": "gmail"
    }
    results = list(astra_collection.find(
        filter=_filter,
        projection={"metadata.msgId": 1},
        sort={"metadata.date": SortMode.ASCENDING},
        skip=body.skip or 0,
        limit=body.limit or 10
    ))
    messages = [
        {"id": d["metadata"]["msgId"]}
        for d in results
    ]
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
    service = GmailService(credentials, email)
    return JSONResponse(content=service.preview(messages), status_code=200)

@router.get("/count")
def count(email: str = Query(...)) -> JSONResponse:
    """
    Retrieves the count of documents for a specific user from the MongoDB collection.

    Args:
        email (str): The email address, provided as a query parameter.

    Returns:
        JSONResponse: A JSON response containing the count of the user's documents.
    """
    _filter = {
        "metadata.userId": email,
        "metadata.type": "gmail"
    }
    doc_count = astra_collection.count_documents(
        filter=_filter, upper_bound=1000)
    return JSONResponse(content={"count": doc_count}, status_code=200)
