"""Module for database utils operations."""
import os
from venv import logger
from google.oauth2.credentials import Credentials
from models.db import MongodbClient

def get_user_credentials(service: str, user_creds: dict = None, _id: str = None) -> Credentials:
    """
    Retrieves user credentials from the MongoDB collection for the specified user email.

    Args:
        user_creds (dict, optional): The user credentials dictionary retrieved from the database.
        email (str, optional): The email address of the user.

    Returns:
        Credentials: The user's credentials if found, otherwise raises an error.
    
    Raises:
        ValueError: If user credentials are not found.
    """
    collection = MongodbClient[service]["user"]
    if service == "gmail":
        scopes=["https://www.googleapis.com/auth/gmail.readonly"]
    elif service == "drive":
        scopes=["https://www.googleapis.com/auth/drive.readonly"]
    else:
        raise ValueError("Unsupported service")
    if user_creds is None:
        user_creds = collection.find_one(
            {"_id": _id},
            projection={"token": 1, "refresh_token": 1}
        )
        if not user_creds:
            logger.error("User credentials not found for: %s", _id)
            raise ValueError("User credentials not found")
    credentials = Credentials(
        token=user_creds["token"],
        refresh_token=user_creds["refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ.get("CLIENT_ID"),
        client_secret=os.environ.get("CLIENT_SECRET"),
        scopes=scopes,
    )
    return credentials

def delete_user(service: str, _id: str = None):
    """
    Deletes a user document from the specified service's "user" collection in MongoDB.

    Args:
        service (str): The name of the service whose user collection will be accessed.
        _id (str, optional): The unique identifier of the user to delete. Defaults to None.

    Returns:
        int: The number of documents deleted (0 if no document was deleted, 1 if successful).
    """
    collection = MongodbClient[service]["user"]
    result = collection.delete_one({"_id": _id})
    return result.deleted_count
