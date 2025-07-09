"""
This module provides a utility class, `GmailService`, for interacting with the Gmail API.
"""
import base64
import hashlib
import os
import uuid
import threading
import logging

from datetime import datetime, timezone, timedelta
import time
from openai import RateLimitError
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from ics import Calendar
from langchain_community.document_loaders import (
    CSVLoader,
    PyPDFLoader,
    UnstructuredExcelLoader,
    UnstructuredImageLoader,
)
from langchain_core.documents import Document
from schema import task_states
from models.db import vstore, astra_collection, MongodbClient
from controllers.utils import upsert
from controllers.topic import detector

collection = MongodbClient["service"]["gmail"]
logger = logging.getLogger(__name__)
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
EMAIL_PATTERN = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"

ATTACHMENTS_DIR = "cache"
os.makedirs(ATTACHMENTS_DIR, exist_ok=True)

class GmailService():
    """
    GmailService is a utility class for interacting with the Gmail API. It provides methods to 
    construct query strings, search for emails, and retrieve detailed email information.
    Methods:
        __init__(token):
            Initializes the GmailService instance with an authenticated Gmail API service.
        build_query(params):
            Constructs a query string based on the provided parameters for filtering emails.
        search(query, max_results=10, check_next_page=False):
            Searches for emails based on a query string and returns a list of message metadata.
        get_emails(query, max_results=10):
            Retrieves a list of emails with detailed information such as subject, sender, 
            recipients, and content.
    Attributes:
        service:
            An authenticated Gmail API service instance used to interact with the Gmail API.
    """
    def __init__(self, credentials, email: str = None, task: str = None):
        """
        Initializes the Gmail controller with the provided email address.

        Args:
            email_address (str):
            The email address used to create credentials for accessing the Gmail API.
        """
        self.service = build("gmail", "v1", credentials=credentials)
        if email and task:
            self.task = task
            self.email = email
            upsert(self.email, self.task)

    def parse_query(self, params) -> str:
        """
        Constructs a query string based on the provided parameters.

        Args:
            params (dict): A dictionary containing optional query parameters. 
                Supported keys include:
                    - 'subject' (str): The subject of the email.
                    - 'from' (str): The sender's email address.
                    - 'to' (str): The recipient's email address.
                    - 'cc' (str): The CC recipient's email address.
                    - 'after' (str): A date string to filter emails sent after this date.
                    - 'before' (str): A date string to filter emails sent before this date.

        Returns:
            str: A query string constructed from the provided parameters. Each parameter
            is formatted as a key-value pair and joined by spaces. If a parameter is not
            provided or is empty, it is excluded from the query string.
        """
        query_parts = []
        if 'subject' in params and params['subject']:
            query_parts.append(f'subject:({params["subject"]})')
        if 'from_email' in params and params['from_email']:
            query_parts.append(f'from:({params["from_email"]})')
        if 'to_email' in params and params['to_email']:
            query_parts.append(f'to:({params["to_email"]})')
        if 'cc_email' in params and params['cc_email']:
            query_parts.append(f'cc:({params["cc_email"]})')
        if 'after' in params and params['after']:
            query_parts.append(f'after:{params["after"]}')
        if 'before' in params and params['before']:
            query_parts.append(f'before:{params["before"]}')
        if 'has_words' in params and params['has_words']:
            query_parts.append(f'"{params["has_words"]}"')
        if 'not_has_words' in params and params['not_has_words']:
            query_parts.append(f'-"{params["not_has_words"]}"')
        return ' '.join(query_parts)

    def collect(self, query):
        """
        Main function to search and list emails from Gmail.

        This function builds a Gmail service, constructs a query to search for emails
        received in the last 14 days, and lists the found emails. If no emails are found,
        it prints a message indicating so.

        Returns:
            None
        """
        logger.info("Starting Gmail collection for user with query: %s", query)
        try:
            # Update task status to "in progress"
            self.task['status'] = "in progress"
            upsert(self.email, self.task)
            logger.info("✅ Task %s status updated to 'in progress'", self.task["id"])

            documents = []
            for message in self.search(query, max_results=200, check_next_page=True):
                logger.info("Processing message with ID: %s", message["id"])
                msg = self.service.users().messages().get(
                    userId="me", id=message["id"], format="full").execute()
                metadata = {}
                metadata["threadId"] = msg["threadId"]
                metadata["msgId"] = msg["id"]
                metadata["type"] = "gmail"
                result = astra_collection.delete_many({
                    "$and": [
                        {"metadata.threadId": msg["threadId"]},
                        {"metadata.type": "gmail"},
                        {"metadata.userId": self.email}
                    ]
                })
                logger.info("Deleted %d documents from AstraDB for threadId: %s",
                            result.deleted_count, msg["threadId"])
                msg_id = f"{msg['threadId']}-{msg['id']}"
                for header in msg["payload"]["headers"]:
                    if header["name"] == "From":
                        metadata["from"] = header["value"]
                    elif header["name"] == "To":
                        metadata["to"] = header["value"]
                    elif header["name"] == "Subject":
                        metadata["subject"] = header["value"]
                        logger.info("subject: %s", metadata["subject"])
                    elif header["name"] == "Cc":
                        metadata["cc"] = header["value"]
                metadata["date"] = datetime.fromtimestamp(
                    int(msg["internalDate"]) / 1000, tz=timezone.utc)
                metadata["lastModified"] = datetime.now(timezone.utc)
                metadata["userId"] = self.service.users().getProfile(
                    userId="me").execute().get("emailAddress")
                documents = []
                mime_types = []
                if msg["payload"]["mimeType"] in [
                    "multipart/alternative",
                    "multipart/related",
                    "multipart/mixed",
                ]:
                    mime_types = []
                    attach_docs = []
                    for part in msg["payload"]["parts"]:
                        mime_types.append(part["mimeType"])
                        if part["mimeType"] == "text/plain" and "text/html" not in mime_types:
                            body = base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8")
                            metadata["mimeType"] = part["mimeType"]
                            metadata["id"] = msg_id
                            documents.append(Document(page_content=body, metadata=metadata))
                        elif part["mimeType"] == "text/html" and "text/plain" not in mime_types:
                            body = base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8")
                            metadata["mimeType"] = part["mimeType"]
                            metadata["id"] = msg_id
                            documents.append(Document(page_content=body, metadata=metadata))
                        elif part['mimeType'] == "multipart/alternative":
                            for subpart in part['parts']:
                                if subpart['mimeType'] == 'text/plain':
                                    body = base64.urlsafe_b64decode(subpart['body']['data']).decode('utf-8')
                                    metadata["mimeType"] = msg["payload"]["mimeType"]
                                    metadata["id"] = msg_id
                                    documents.append(Document(page_content=body, metadata=metadata))
                                elif subpart['mimeType'] == 'text/html':
                                    body = base64.urlsafe_b64decode(subpart['body']['data']).decode('utf-8')
                                    metadata["mimeType"] = subpart['mimeType']
                                    metadata["id"] = msg_id
                                    documents.append(Document(page_content=body, metadata=metadata))
                        if part["filename"]:
                            attachment_id = part["body"]["attachmentId"]
                            logger.info("Downloading attachment: %s", part["filename"])
                            attachment = (
                                self.service.users()
                                .messages()
                                .attachments()
                                .get(userId="me", messageId=message["id"], id=attachment_id)
                                .execute()
                            )
                            file_data = base64.urlsafe_b64decode(attachment["data"].encode("UTF-8"))
                            path = os.path.join(".", ATTACHMENTS_DIR, f"{msg['id']}_{part['filename']}")
                            with open(path, "wb") as f:
                                f.write(file_data)
                            if part["mimeType"] == "application/pdf":
                                attach_docs = PyPDFLoader(path).load()
                            elif part["mimeType"] == "image/png" or part["mimeType"] == "image/jpeg":
                                try:
                                    attach_docs = UnstructuredImageLoader(path).load()
                                except (ValueError, TypeError) as e:
                                    logger.error("Error loading image: %s", e)
                            elif part["filename"].endswith(".csv"):
                                attach_docs = CSVLoader(path).load()
                            elif (
                                part["mimeType"]
                                == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                            ):
                                try:
                                    attach_docs = UnstructuredExcelLoader(path).load()
                                except ImportError as e:
                                    logger.warning("Skipping Excel file - missing openpyxl dependency %s", e)
                                    logger.warning("Fix: pip install openpyxl")
                                    attach_docs = []
                                except Exception as e:
                                    logger.error("Error processing Excel file: %s", e)
                                    attach_docs = []
                            elif part["mimeType"] == "application/ics":
                                with open(path, "r", encoding="utf-8") as f:
                                    calendar = Calendar(f.read())
                                for event in calendar.events:
                                    documents.append(
                                        Document(
                                            page_content=f"Event: {event.name}\nDescription: {event.description}\nStart: {event.begin}\nEnd: {event.end}",
                                            metadata={
                                                "attachment": part["filename"],
                                                "mimeType": part["mimeType"],
                                                "location": event.location,
                                                "created": event.created.strftime("%d/%m/%Y %H:%M:%S"),
                                                "last_modified": event.last_modified.strftime(
                                                    "%d/%m/%Y %H:%M:%S"
                                                ),
                                                "start": event.begin.strftime("%d/%m/%Y %H:%M:%S"),
                                                "end": event.end.strftime("%d/%m/%Y %H:%M:%S"),
                                                "id": f"{msg_id}-{part['filename']}-{hashlib.sha256(file_data).hexdigest()}"
                                            }
                                        )
                                    )
                            if os.path.exists(path):
                                os.remove(path)
                            for index, document in enumerate(attach_docs or []):
                                if "page_label" in document.metadata:
                                    document.metadata["page"] = document.metadata["page_label"]
                                document.metadata["attachId"] = part["body"]["attachmentId"]
                                attachment = part["filename"]
                                document.metadata["title"] = attachment.split(".")[0]
                                document.metadata["ext"] = attachment.split(".")[-1]
                                document.metadata = {
                                    key: value
                                    for key, value in document.metadata.items()
                                    if key in ["ext", "page", "title", "attachId"] \
                                        and value is not None and value != ""
                                }
                                document.metadata.update(metadata)
                                document.metadata["mimeType"] = part["mimeType"]
                                document.metadata["id"] = f"{msg_id}-{hashlib.sha256(file_data).hexdigest()}-{index}"

                                max_retries = 3
                                for retry in range(max_retries):
                                    try:
                                        is_relevant = detector.invoke({"document": document}).model_dump()['verdict']
                                        if is_relevant:
                                            documents.append(document)
                                        else:
                                            logger.info("Document %s is not related to the topic.",
                                                        document.metadata["id"])
                                        break  # Success, exit retry loop
                                    except RateLimitError as e:
                                        wait_time = 60
                                        logger.warning("Rate limit hit. Waiting %ds before retry %d/%d", wait_time, retry+1, max_retries)
                                        if retry < max_retries - 1:
                                            time.sleep(wait_time)
                                        else:
                                            logger.error("Max retries reached for OpenAI API. Skipping document.")
                                            # Just add the document without checking relevance as fallback
                                            documents.append(document)
                                    except Exception as e:
                                        logger.error("Error checking document relevance: %s", str(e))
                                        # Add document anyway as fallback
                                        documents.append(document)
                                        break
                elif msg["payload"]["mimeType"] == "text/plain" and "data" in msg["payload"]["body"]:
                    body = base64.urlsafe_b64decode(msg["payload"]["body"]["data"]).decode("utf-8")
                    metadata["mimeType"] = msg["payload"]["mimeType"]
                    metadata["id"] = msg_id
                    documents.append(Document(page_content=body, metadata=metadata))
                elif msg["payload"]["mimeType"] == "text/html" and "data" in msg["payload"]["body"]:
                    body = base64.urlsafe_b64decode(msg["payload"]["body"]["data"]).decode("utf-8")
                    metadata["mimeType"] = msg["payload"]["mimeType"]
                    metadata["id"] = msg_id
                    documents.append(Document(page_content=body, metadata=metadata, id=msg_id))
                # if "multipart/alternative" in mime_types and len(mime_types) == 1:
                #     logger.info("Only multipart/alternative found in the email.")
                #     self.task['status'] = "failed"
                #     task_states[self.task["id"]] = "Failed"
                #     upsert(self.email, self.task)
                # else:
            if documents:
                logger.info("Uploading %d documents for task %s", len(documents), self.task["id"])
                try:
                    vstore.upload(self.email, documents, self.task)
                    logger.info("✅ Vector store upload successful for task %s", self.task["id"])
                    
                except Exception as upload_error:
                    logger.error("💥 Vector store upload failed for task %s: %s", 
                            self.task["id"], str(upload_error))
                    raise upload_error
            # Mark task as completed
            self.task['status'] = "completed"
            self.task['updatedTime'] = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
            task_states[self.task["id"]] = "Completed"
            upsert(self.email, self.task)
            
            logger.info("✅ Collection completed for task %s", 
                    self.task["id"])

        except Exception as e:
            logger.error("💥 Error in collect for task %s: %s", self.task["id"], str(e), exc_info=True)
            # Mark task as failed
            self.task['status'] = "failed"
            task_states[self.task["id"]] = "Failed"
            upsert(self.email, self.task)
            raise

    def search(self, query, max_results=200, check_next_page=False) -> list:
        """
        Searches for Gmail threads based on a query string
        and returns the latest message from each thread.

        Args:
            query (str): The search query string to filter threads.
            max_results (int, optional): The maximum number of threads to retrieve per page.
            check_next_page (bool, optional):
                Whether to fetch additional pages of results if available.

        Returns:
            list: A list of message metadata dicts,
            each representing the latest message in a thread.

        Notes:
            - The `query` parameter supports Gmail's advanced search operators.
            - If `check_next_page` is True, will continue fetching threads until all are retrieved.
            - Only the most recent message from each thread is included in the results.
        """
        query = self.parse_query(query)
        result = self.service.users().threads().list(
            userId='me', q=query, maxResults=max_results).execute()
        threads = []
        if "threads" in result:
            threads.extend(result["threads"])
        while "nextPageToken" in result and check_next_page:
            page_token = result["nextPageToken"]
            result = (
                self.service.users().threads().list(
                    userId="me", q=query, maxResults=max_results, pageToken=page_token).execute()
            )
            if "threads" in result:
                threads.extend(result["threads"])
        messages = []
        for thread in threads:
            thread_data = self.service.users().threads().get(userId='me', id=thread['id']).execute()
            if thread_data.get('messages'):
                latest_message = thread_data['messages'][-1]
                messages.append(latest_message)
        return messages

    def preview(self, query = None, messages: list[dict] = None) -> list:
        """
        Retrieves a preview list of emails matching the given query.

        Args:
            query (str): The search query to filter emails.

        Returns:
            list: A list of email previews matching the query.
            Returns an empty list if no messages are found or if an error occurs.

        Raises:
            Logs exceptions of type KeyError, ValueError, or TypeError and returns an empty list.
        """
        try:
            if messages is None or len(messages) == 0:
                if query is not None:
                    messages = self.search(query, max_results=10)
            return self._get_email_by_messages(messages)
        except (KeyError, ValueError, TypeError) as e:
            logger.info("An error occurred: %s", e)
            return []

    def _get_email_by_messages(self, messages: list[dict]) -> dict:
        """
        Fetches and parses email messages from the Gmail API,
        extracting key fields and decoding content.

        Args:
            messages (list[dict]): A list of message metadata dictionaries,
            each containing at least an 'id' key.

        Returns:
            dict: A list of dictionaries, each representing an email with the following fields:
                - subject (str): The subject of the email.
                - from (str): The sender's email address.
                - to (str): The recipient's email address.
                - cc (str): The CC'd email addresses, if any.
                - content (str): The decoded email body, either plain text or HTML.
                - snippet (str): A short snippet of the email content.
                - datetime (str):
                    The email's sent date and time in "YYYY-MM-DD HH:MM:SS" format (HKT timezone).
                - mimeType (str, optional): The MIME type of the email content.

        Notes:
            - The function converts the email's internal date to Hong Kong Time (UTC+8).
            - If both plain text and HTML parts are present, plain text is preferred.
            - Assumes the Gmail API service is available as self.service.
        """
        emails = []
        for message in messages:
            msg = self.service.users().messages().get(
                    userId='me', id=message['id'], format='full').execute()
            headers = msg['payload']['headers']
            utc_dt = datetime.fromtimestamp(int(msg["internalDate"]) / 1000, tz=timezone.utc)
            hkt_dt = utc_dt.astimezone(timezone(timedelta(hours=8)))
            email = {
                'subject': '',
                'from': '',
                'to': '',
                'cc': '',
                'content': '',
                'snippet': msg['snippet'] if 'snippet' in msg else '',
                "datetime": hkt_dt.strftime("%Y-%m-%d %H:%M:%S"),
            }
            for header in headers:
                name = header['name'].lower()
                if name == 'subject':
                    email['subject'] = header['value']
                elif name == 'from':
                    email['from'] = header['value']
                elif name == 'to':
                    email['to'] = header['value']
                elif name == 'cc':
                    email['cc'] = header['value']
            if 'parts' in msg['payload']:
                for part in msg['payload']['parts']:
                    if part['mimeType'] == 'text/plain':
                        content = base64.urlsafe_b64decode(
                            part['body']['data']).decode('utf-8')
                        if content == "":
                            continue
                        email['content'] = content
                        email['mimeType'] = part['mimeType']
                        break
                    elif part['mimeType'] == 'text/html':
                        content = base64.urlsafe_b64decode(
                            part['body']['data']).decode('utf-8')
                        if content == "":
                            continue
                        email['content'] = content
                        email['mimeType'] = part['mimeType']
                        break
                    elif part['mimeType'] == "multipart/alternative":
                        for subpart in part['parts']:
                            if subpart['mimeType'] == 'text/plain':
                                content = base64.urlsafe_b64decode(
                                    subpart['body']['data']).decode('utf-8')
                                if content == "":
                                    continue
                                email['content'] = content
                                email['mimeType'] = subpart['mimeType']
                                break
                            elif subpart['mimeType'] == 'text/html':
                                content = base64.urlsafe_b64decode(
                                    subpart['body']['data']).decode('utf-8')
                                if content == "":
                                    continue
                                email['content'] = content
                                email['mimeType'] = subpart['mimeType']
                                break
            elif 'data' in msg['payload']['body']:
                email['mimeType'] = msg['payload']['mimeType']
                content = base64.urlsafe_b64decode(
                    msg['payload']['body']['data']).decode('utf-8')
                if content == "":
                    continue
                email['content'] = content
            emails.append(email)
        return emails

def trigger():
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
    records = collection.find(projection={"token": 1, "refresh_token": 1, "queries": 1})
    if not records:
        logger.error("User not found.")
    for record in records:
        credentials = Credentials(
            token=record["token"],
            refresh_token=record["refresh_token"],
            token_uri="https://oauth2.googleapis.com/token",
            client_id=os.environ.get("CLIENT_ID"),
            client_secret=os.environ.get("CLIENT_SECRET"),
            scopes=["https://www.googleapis.com/auth/gmail.readonly"],
        )
        if not credentials.valid or credentials.expired:
            logger.error("Invalid or expired credentials for user: %s", record["_id"])
        service = GmailService(credentials, email=record["_id"])
        if "queries" in record:
            for query in record["queries"]:
                task_id = f"{str(uuid.uuid4())}"
                service.email = record["_id"]
                service.task = {
                    "id": task_id,
                    "status": "pending",
                    "type": "cronjob"
                }
                threading.Thread(target=service.collect, args=[query]).start()
