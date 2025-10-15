# pylint: disable=duplicate-code
"""Module for defining the main routes of the API."""
import uuid
import threading
from datetime import datetime, timedelta, timezone
from venv import logger
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from pymongo import DESCENDING
from pymongo.errors import PyMongoError
from schema import DriveFilter, DocsReq
from models.db import MongodbClient, cosmos_collection
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

@router.get("/query")
def get_query(email: str = Query(...), user_id: str = Query(None),
              query_id: str = Query(...)) -> JSONResponse:
    """
    Retrieves a specific Drive query for a user from the MongoDB collection.

    Args:
        email (str): The email address, provided as a query parameter.
        user_id (str, optional): The user ID, provided as a query parameter.
        query_id (str): The ID of the query to retrieve.

    Returns:
        JSONResponse: A JSON response containing the requested Drive query.
    """
    if user_id is None:
        user_id = email
    required_fields = [
        "id", "url", "folderId", "folderName", "title"
    ]
    # Check if user exists
    _id = f"{user_id}/{email}"
    user = collection.find_one({"_id": _id})
    if user is None:
        return JSONResponse(content={"error": "User not found."}, status_code=404)

    pipeline = [
        {"$match": {"_id": _id}},
        {"$unwind": "$queries"},
        {"$match": {"queries.id": query_id}},
        {"$project": {
            "_id": 0,
            "query": {
                "$arrayToObject": {
                    "$filter": {
                        "input": {"$objectToArray": "$queries"},
                        "cond": {"$in": ["$$this.k", required_fields]}
                    }
                }
            }
        }}
    ]

    result = list(collection.aggregate(pipeline))
    if not result:
        return JSONResponse(
            content={"error": f"Query with ID '{query_id}' not found for user."},
            status_code=404
        )
    return JSONResponse(content=result[0]["query"], status_code=200)

@router.delete("/query")
def delete_query(email: str = Query(...), user_id: str = Query(None),
                 query_id: str = Query(...)) -> JSONResponse:
    """
    Deletes a specific Drive query for a user from the MongoDB collection.

    Args:
        email (str): The email address, provided as a query parameter.
        user_id (str, optional): The user ID, provided as a query parameter.
        query_id (str): The ID of the query to be deleted, provided as a query parameter.

    Returns:
        JSONResponse: A JSON response indicating whether the deletion was successful or not.
    """
    if user_id is None:
        user_id = email
    _id = f"{user_id}/{email}"
    user_doc = collection.find_one(
        {"_id": _id, "queries.id": query_id},
        projection={"queries.$": 1}
    )
    if not user_doc:
        # Check if user exists at all
        user_exists = collection.find_one({"_id": _id}, projection={"_id": 1})
        if not user_exists:
            return JSONResponse(
                content={"error": "User not found."},
                status_code=404
            )
        return JSONResponse(
            content={"error": f"Query with ID '{query_id}' not found."},
            status_code=404
        )
    result = collection.update_one(
        {"_id": _id},
        {"$pull": {"queries": {"id": query_id}}}
    )
    if result.modified_count > 0:
        return JSONResponse(content={"status": "success"}, status_code=200)
    return JSONResponse(content={"error": "Failed to delete query"}, status_code=500)

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

@router.get("/queries")
def get_queries(email: str = Query(...), user_id: str = Query(None)) -> JSONResponse:
    """
    Retrieves all Drive queries for a specific user from the MongoDB collection.

    Args:
        email (str): The email address, provided as a query parameter.
        user_id (str, optional): The user ID, provided as a query parameter.

    Returns:
        JSONResponse: A JSON response containing the user's Drive queries.
    """
    if user_id is None:
        user_id = email
    _id = f"{user_id}/{email}"
    user = collection.find_one({"_id": _id})
    if user is None:
        return JSONResponse(content={"error": "User not found."}, status_code=404)

    pipeline = [
        {"$match": {"_id": _id}},
        {"$unwind": "$queries"},
        {"$sort": {"queries.createdTime": -1}},
        {"$group": {
            "_id": "$_id",
            "queries": {"$push": "$queries"}
        }},
        {"$project": {"queries": 1}}
    ]
    result = list(collection.aggregate(pipeline))
    if not result or "queries" not in result[0]:
        return JSONResponse(content=[], status_code=200)

    processed_queries = []
    for query in result[0]["queries"]:
        processed_query = {
            "id": query.get("id", "unknown"),
            "status": (query["task"]["status"] if "task" in
                        query else query.get("status", "unknown")),
            "filters": {
                key: value for key, value in query.items()
                if key in ["url", "folderId", "folderName"]
                and value is not None
            },
            "count": query.get("task", {}).get("count", 0),
            "service": query.get("task", {}).get("service", ""),
            "type": (query.get("task", {}).get("type", "")),
            "createdTime": query.get("createdTime", ""),
            "title": query.get("title", ""),
        }
        processed_queries.append(processed_query)
    return JSONResponse(content=processed_queries, status_code=200)

@router.post("/docs")
def retrieve_docs(
    body: DocsReq, email: str = Query(...), user_id: str = Query(None)) -> JSONResponse:
    """
    Retrieves all documents for a specific user from the Drive service.

    Args:
        body (DocsReq): Request parameters for document retrieval.
        email (str): The email address, provided as a query parameter.
        user_id (str, optional): The user ID, provided as a query parameter.

    Returns:
        JSONResponse: A JSON response containing the user's Drive documents with download URLs.
    """
    if user_id is None:
        user_id = email
    credentials = get_user_credentials(service=SERVICE, _id=f"{user_id}/{email}")
    if not credentials.valid or credentials.expired:
        return JSONResponse(content={"valid": False,
                                     "error": "Invalid or expired credentials."}, status_code=401)

    _filter = {
        "metadata.userId": user_id,
        "metadata.email": email,
        "metadata.service": SERVICE,
        "metadata.lastModified": { "$gte": datetime.fromtimestamp(
                int((datetime.now() - timedelta(days=30)).timestamp()), tz=timezone.utc) }
    }

    try:
        results = list(cosmos_collection.find(
            _filter,
            {"metadata.id": 1, "metadata.filename": 1}
            ).sort("metadata.date", DESCENDING)
            .skip(body.skip or 0)
            .limit(body.limit or 10)
        )

        docs = []
        service = DriveService(credentials, user_id, email)
        for doc in results:
            file_id = doc["metadata"]["id"]
            filename = doc["metadata"]["filename"]
            # Generate Google Drive download URL
            download_url = f"https://drive.google.com/file/d/{file_id}/view"
            docs.append({
                "id": file_id,
                "filename": filename,
                "downloadUrl": download_url
            })

        try:
            total = cosmos_collection.count_documents(_filter)
        except PyMongoError as count_error:
            logger.error(count_error)
            total = 0
        result = {
            "docs": docs,
            "skip": body.skip + len(docs),
            "total": total
        }
        return JSONResponse(content=result, status_code=200)
    except PyMongoError as e:
        logger.error(e)
        response = {
            "error": "The read operation timed out"
        }
        return JSONResponse(content=response, status_code=200)
