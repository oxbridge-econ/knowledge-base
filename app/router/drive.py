# pylint: disable=duplicate-code
"""Module for defining the main routes of the API."""
import uuid
import threading
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from schema import DriveFilter
from models.db import MongodbClient
from services import DriveService, get_user_credentials, delete_user
from controllers.utils import upsert

SERVICE = "drive"
router = APIRouter(prefix=f"/service/{SERVICE}", tags=[SERVICE])
collection = MongodbClient[SERVICE]["user"]

@router.get("")
def validate(email: str = Query(...), user_id: str = Query(None)) -> JSONResponse:
    """
    Validates user credentials for the Drive service.

    Args:
        email (str): The user's email address, provided as a query parameter.
        user_id (str, optional): The user's unique identifier, provided as a query parameter.

    Returns:
        JSONResponse: 
            - If credentials are invalid or expired, returns a 401 response with valid=False.
            - Otherwise, returns valid=True.
    """
    if user_id is None:
        user_id = email
    credentials = get_user_credentials(service=SERVICE, _id=f"{user_id}/{email}")
    if not credentials.valid or credentials.expired:
        return JSONResponse(content={"valid": False}, status_code=401)
    return JSONResponse(content={"valid": True})

@router.delete("")
def delete(email: str = Query(...), user_id: str = Query(None)) -> JSONResponse:
    """
    Deletes a user's email entry from the service.

    Args:
        email (str): The email address to delete. Required as a query parameter.
        user_id (str, optional): The user ID associated with the email.
            If not provided, defaults to the email.

    Returns:
        JSONResponse: A JSON response indicating whether the deletion was successful.
            - If the deletion count is not 1, returns {"valid": False} with status code 401.
            - Otherwise, returns {"valid": True}.
    """
    if user_id is None:
        user_id = email
    count = delete_user(service = SERVICE, _id=f"{user_id}/{email}")
    if count != 1:
        return JSONResponse(content={"error": "Failed to delete user"}, status_code=500)
    return JSONResponse(content={"status": "success"}, status_code=200)

# @router.get("/query")
# def get_query(email: str = Query(...), user_id: str = Query(None),
#               query_id: str = Query(...)) -> JSONResponse:


# @router.delete("/query")
# def delete_query(email: str = Query(...), user_id: str = Query(None),
#                  query_id: str = Query(...)) -> JSONResponse:


@router.post("/query")
def update_query(
    body: DriveFilter, user_id: str = Query(None), email: str = Query(...)) -> JSONResponse:
    """
    Handles the POST request to the "/collect" endpoint for collecting data from a drive service.

    Args:
        body (DriveFilter):
            The filter parameters for the drive collection, provided in the request body.
        user_id (str, optional): The user ID, provided as a query parameter. Defaults to None.
        email (str): The user's email address, provided as a required query parameter.

    Returns:
        JSONResponse: 
            - If credentials are invalid or expired,
                returns a JSON response with an error message and a 401 status code.
            - Otherwise, initiates a background collection task,
                updates the database, and returns the task details as a JSON response.

    Side Effects:
        - Starts a new thread to perform the collection task asynchronously.
        - Updates or inserts task and user query information in the database.

    Notes:
        - If user_id is not provided, it defaults to the value of email.
        - The function expects valid user credentials to access the drive service.
    """
    if user_id is None:
        user_id = email
    _id = f"{user_id}/{email}"
    credentials = get_user_credentials(service=SERVICE, _id=_id)
    if not credentials.valid or credentials.expired:
        return JSONResponse(content={"valid": False,
                                     "error": "Invalid or expired credentials."}, status_code=401)
    query = body.model_dump()
    query["id"] = query["url"].split("/")[-1]
    task = {
        "id": f"{str(uuid.uuid4())}",
        "status": "pending",
        "service": SERVICE,
        "type": "manual",
        "query": query
    }
    service = DriveService(credentials, user_id, email, task)
    threading.Thread(target=service.collect, args=[query]).start()
    upsert(_id, task, SERVICE)
    upsert(_id, query, SERVICE, "user")
    return JSONResponse(content=task)

# @router.get("/queries")
# def get_queries(email: str = Query(...), user_id: str = Query(None)) -> JSONResponse:

# @router.post("/docs")
# def retrieve_docs(
#     body: DocsReq, email: str = Query(...), user_id: str = Query(None)) -> JSONResponse:
