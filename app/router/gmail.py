"""Module for defining the main routes of the API."""
import os
import threading
import uuid
from google.oauth2.credentials import Credentials
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from services import GmailService
from schema import EmailFilter #, EmailQuery #, task_states
from models.db import MongodbClient
from controllers.utils import upsert_task

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
    service = GmailService(credentials)
    task_id = f"{str(uuid.uuid4())}"
    task = {"id": task_id, "status": "Pending"}
    threading.Thread(target=service.collect, args=[body.model_dump(), email, task]).start()
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
    upsert_task(email, task)
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

# @router.get("/queries")
# def get_queries(email: str = Query(...)) -> JSONResponse:
#     """
#     Retrieves all email queries for a specific user from the MongoDB collection.

#     Args:
#         email (str): The email address, provided as a query parameter.

#     Returns:
#         JSONResponse: A JSON response containing the user's email queries.
#     """
#     result = collection.find_one({"_id": email}, projection={"queries": 1})
#     del result["_id"]
#     return JSONResponse(content=result["queries"] if "queries" in result else {}, status_code=200)

# @router.post("/trigger")
# def trigger(body: EmailQuery, email: str = Query(...)) -> JSONResponse:
#     """
#     Collects Gmail data for a specified user and initiates an asynchronous collection task.

#     Args:
#         body (EmailQuery): The query parameters for the email collection.
#         email (str, optional): The user's email address, provided as a query parameter.

#     Returns:
#         JSONResponse:
#             - If the user is not found, returns a 404 error with an appropriate message.
#             - If the user's credentials are invalid or expired, returns a 401 error.
#             - Otherwise, starts a background thread to collect emails,
#               updates the user's query in the database,
#               and returns a JSON response containing the task ID and its initial status.

#     Raises:
#         None

#     Side Effects:
#         - Starts a background thread for email collection.
#         - Updates or inserts the user's query parameters in the MongoDB collection.
#         - Modifies the global `task_states` dictionary with the new task's status.
#     """
#     record = collection.find_one(
#         {"_id": email}, projection={"token": 1, "refresh_token": 1, "queries": 1})
#     if record is None:
#         return JSONResponse(content={"error": "User not found."}, status_code=404)
#     credentials = Credentials(
#         token=record["token"],
#         refresh_token=record["refresh_token"],
#         token_uri="https://oauth2.googleapis.com/token",
#         client_id=os.environ.get("CLIENT_ID"),
#         client_secret=os.environ.get("CLIENT_SECRET"),
#         scopes=["https://www.googleapis.com/auth/gmail.readonly"],
#     )
#     if not credentials.valid or credentials.expired:
#         return JSONResponse(content={"valid": False,
#                                      "error": "Invalid or expired credentials."}, status_code=401)
#     service = GmailService(credentials)
#     task_id = f"{str(uuid.uuid4())}"
#     body = body.model_dump()
#     del body["filter"]["max_results"]
#     body["filter"] = {k: v for k, v in body["filter"].items() if v is not None}
#     if "queries" not in record:
#         record["queries"] = []
#     for query in record["queries"]:
#         if query["id"] == body["id"]:
#             query.update(body)
#             break
#     else:
#         record["queries"].append(body)
#     data = {
#         "_id": email,
#         "queries": record["queries"],
#     }
#     collection.update_one(
#         { '_id': email },
#         { '$set': data },
#         upsert=True
#     )
#     # task_states[task_id] = "Pending"
#     threading.Thread(target=service.collect, args=[body["filter"], task_id]).start()
#     return JSONResponse(content={"id": task_id, "status": "Pending"})
