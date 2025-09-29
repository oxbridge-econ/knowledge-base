"""Module for database operations."""
import os
from venv import logger
from google.oauth2.credentials import Credentials
from services.gmail import GmailService
from services.drive import DriveService
from models.db import MongodbClient

__all__ = [
    "GmailService",
    "DriveService"
]

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
    if service == "gmail":
        collection = MongodbClient["gmail"]["user"]
        scopes=["https://www.googleapis.com/auth/gmail.readonly"]
    elif service == "drive":
        collection = MongodbClient["drive"]["user"]
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
