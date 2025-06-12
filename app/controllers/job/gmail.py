"""Module to process Gmail collection tasks."""
import os
from datetime import datetime

import threading
import uuid
from google.oauth2.credentials import Credentials
from services import GmailService
from models.db import MongodbClient
from schema import task_states

collection = MongodbClient["service"]["gmail"]


def process():
    """
    Processes all records in the collection by retrieving Gmail credentials
    and starting a collection task for each.

    For each record:
        - Prints the record.
        - Generates a unique task ID.
        - Constructs Gmail API credentials from the record and environment variables.
        - Checks if the credentials are valid and not expired; skips the record if invalid.
        - Initializes a GmailService with the credentials.
        - Starts a new thread to collect Gmail data using the specified query and task ID.

    Note:
        - Assumes `collection`, `Credentials`, `os`, `uuid`, `GmailService`,
        and `threading` are properly imported and configured.
        - Only processes records with valid, non-expired credentials.
    """
    records = list(collection.find({}))
    for record in records:
        task_id = f"{str(uuid.uuid4())}"
        credentials = Credentials(
            token=record["token"],
            refresh_token=record["refresh_token"],
            token_uri="https://oauth2.googleapis.com/token",
            client_id=os.environ.get("CLIENT_ID"),
            client_secret=os.environ.get("CLIENT_SECRET"),
            scopes=["https://www.googleapis.com/auth/gmail.readonly"],
        )
        current_date = datetime.now().strftime("%Y/%m/%d")
        if not credentials.valid or credentials.expired:
            continue
        if "before" in record["query"]:
            if record["query"]["before"] <= current_date:
                continue
            else:
                record["query"]["after"] = current_date
        collection.update_one(
            {"_id": record["_id"]},
            {"$set": {"lastCollectDate": current_date, "task_id": task_id}},
            upsert=True
        )
        task_states[task_id] = "Pending"
        service = GmailService(credentials)
        threading.Thread(target=service.collect, args=[record["query"], task_id]).start()
