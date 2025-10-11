# pylint: disable=duplicate-code
"""This module provides a utility class, `GmailService`, for interacting with the Gmail API."""
import base64
import hashlib
import os

from concurrent.futures import ThreadPoolExecutor
from venv import logger

from datetime import datetime, timezone, timedelta
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from langchain_core.documents import Document
from controllers.file import FileHandler, CalendarLoader
from controllers.utils import upsert, check_relevance
from models.db import vstore, astra_collection, MongodbClient

SERVICE = "gmail"
collection = MongodbClient[SERVICE]["user"]
EMAIL_PATTERN = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"

ATTACHMENTS_DIR = "cache"
os.makedirs(ATTACHMENTS_DIR, exist_ok=True)

MAX_WORKERS = 2
thread_pool = ThreadPoolExecutor(max_workers=MAX_WORKERS)

class GmailService():
    """
    GmailService is a utility class for interacting with the Gmail API. It provides methods to 
    construct query strings, search for emails, and retrieve detailed email information.
    Methods:
        __init__(token):
            Initializes the GmailService instance with an authenticated Gmail API service.
        build_query(params):
            Constructs a query string based on the provided parameters for filtering emails.
        _search(query, max_results=10, check_next_page=False):
            Searches for emails based on a query string and returns a list of message metadata.
        get_emails(query, max_results=10):
            Retrieves a list of emails with detailed information such as subject, sender, 
            recipients, and content.
    Attributes:
        service:
            An authenticated Gmail API service instance used to interact with the Gmail API.
    """
    def __init__(self, credentials, user_id: str = None, email: str = None, task: str = None):
        """
        Initializes the Gmail controller with the provided email address.

        Args:
            email_address (str):
            The email address used to create credentials for accessing the Gmail API.
        """
        self.service = build("gmail", "v1", credentials=credentials)
        self.email = email
        self.task = task
        self.user_id = user_id
        self._id = f"{self.user_id}/{self.email}"
        if email and task:
            self.task = task
            self.email = email

    def _parse_query(self, params) -> str:
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
            query_parts.append(params["has_words"])
        if 'not_has_words' in params and params['not_has_words']:
            query_parts.append(f'-{params["not_has_words"]}')
        if 'has_attachment' in params and params['has_attachment']:
            query_parts.append('has:attachment')
        return ' '.join(query_parts)

    def _search(self, query, max_results=200, check_next_page=False) -> list:
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
        query = self._parse_query(query)
        result = self.service.users().threads().list(  # pylint: disable=no-member
            userId='me', q=query, maxResults=max_results).execute()
        threads = []
        if "threads" in result:
            threads.extend(result["threads"])
        while "nextPageToken" in result and check_next_page:
            page_token = result["nextPageToken"]
            result = (
                self.service.users().threads().list(  # pylint: disable=no-member
                    userId="me", q=query, maxResults=max_results, pageToken=page_token).execute()
            )
            if "threads" in result:
                threads.extend(result["threads"])
        messages = []
        for thread in threads:
            thread_data = self.service.users().threads().get(userId='me', id=thread['id']).execute()   # pylint: disable=no-member
            if thread_data.get('messages'):
                latest_message = thread_data['messages'][-1]
                messages.append(latest_message)
        return messages

    def _create_email_base_structure(self, msg: dict, hkt_dt: datetime) -> dict:
        """Creates the base email structure with default values."""
        return {
            'subject': '',
            'from': '',
            'to': '',
            'cc': '',
            'content': '',
            'snippet': msg['snippet'] if 'snippet' in msg else '',
            "datetime": hkt_dt.strftime("%Y-%m-%d %H:%M:%S"),
        }

    def _extract_headers(self, email: dict, headers: list) -> None:
        """Extracts header information from email headers."""
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

    def _try_extract_text_content(self, email: dict, part: dict) -> bool:
        """Tries to extract text content from a part. Returns True if content was extracted."""
        if part['mimeType'] == 'text/plain':
            content = base64.urlsafe_b64decode(part['body']['data']).decode('utf-8')
            if content:
                email['content'] = content
                email['mimeType'] = part['mimeType']
                return True
        elif part['mimeType'] == 'text/html':
            content = base64.urlsafe_b64decode(part['body']['data']).decode('utf-8')
            if content:
                email['content'] = content
                email['mimeType'] = part['mimeType']
                return True
        return False

    def _extract_content_from_multipart_alternative(self, email: dict, subparts: list) -> None:
        """Extracts content from multipart/alternative subparts."""
        for subpart in subparts:
            if self._try_extract_text_content(email, subpart):
                break

    def _extract_content_from_parts(self, email: dict, parts: list) -> None:
        """Extracts content from email parts."""
        for part in parts:
            if self._try_extract_text_content(email, part):
                break
            if part['mimeType'] == "multipart/alternative":
                self._extract_content_from_multipart_alternative(email, part['parts'])

    def _extract_email_content(self, email: dict, msg: dict) -> None:
        """Extracts content from email message."""
        if 'parts' in msg['payload']:
            self._extract_content_from_parts(email, msg['payload']['parts'])
        elif 'data' in msg['payload']['body']:
            email['mimeType'] = msg['payload']['mimeType']
            content = base64.urlsafe_b64decode(
                msg['payload']['body']['data']).decode('utf-8')
            if content:
                email['content'] = content

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
            logger.info("Processing message: %s", message['id'])
            try:
                msg = self.service.users().messages().get(  # pylint: disable=no-member
                        userId='me', id=message['id'], format='full').execute()
                headers = msg['payload']['headers']
                utc_dt = datetime.fromtimestamp(int(msg["internalDate"]) / 1000, tz=timezone.utc)
                hkt_dt = utc_dt.astimezone(timezone(timedelta(hours=8)))
                email = self._create_email_base_structure(msg, hkt_dt)
                self._extract_headers(email, headers)
                self._extract_email_content(email, msg)
                emails.append(email)
            except HttpError:
                logger.error("Requested entity was not found with ID: %s", message['id'])
                result = astra_collection.delete_many({
                    "$and": [
                        {"metadata.userId": self.user_id},
                        {"metadata.email": self.email},
                        {"metadata.service": "gmail"},
                        {"metadata.msgId": message['id']}
                    ]
                })
                logger.info("Deleted %d documents for message ID: %s",
                           result.deleted_count, message['id'])
        return emails

    def _get_metadata(self, msg: dict) -> dict:
        metadata = {}
        metadata["threadId"] = msg["threadId"]
        metadata["msgId"] = msg["id"]
        metadata["service"] = "gmail"
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
        metadata["userId"] = self.user_id
        metadata["email"] = self.service.users().getProfile(  # pylint: disable=no-member
            userId="me").execute().get("emailAddress")
        return metadata

    def _retrieve_content(self, msg: dict, metadata: dict, message) -> list[Document]: # pylint: disable=too-many-branches,too-many-locals,too-many-statements,too-many-nested-blocks
        msg_id = f"{msg['threadId']}-{msg['id']}"
        documents = []
        mime_types = []
        if msg["payload"]["mimeType"] in [ # pylint: disable=too-many-nested-blocks
            "multipart/alternative",
            "multipart/related",
            "multipart/mixed",
        ]:
            mime_types = []
            attach_docs = []
            for part in msg["payload"]["parts"]:
                mime_types.append(part["mimeType"])
                mime_type = part["mimeType"]
                if mime_type in ["text/plain", "text/html"]:
                    if mime_type not in [doc.metadata["mimeType"] for doc in documents]:
                        body = base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8")
                        documents.append(Document(
                            page_content=body,
                            metadata={**metadata, "mimeType": mime_type, "id": msg_id}
                        ))
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
                        self.service.users()  # pylint: disable=no-member
                        .messages()
                        .attachments()
                        .get(userId="me", messageId=message["id"], id=attachment_id)
                        .execute()
                    )
                    file_data = base64.urlsafe_b64decode(attachment["data"].encode("UTF-8"))
                    path = os.path.join(".", ATTACHMENTS_DIR, f"{msg['id']}_{part['filename']}")
                    with open(path, "wb") as f:
                        f.write(file_data)
                    if part["mimeType"] == "application/ics":
                        calendar = CalendarLoader(file_path=path, part=part,
                         msg_id=msg_id, file_data=file_data)
                        attach_docs = calendar.load()
                    else:
                        try:
                            attach_docs = []
                            for document in FileHandler(path=path).process():
                                attach_docs.append(document)
                        except (OSError, IOError, ValueError, TypeError) as e:
                            logger.error("Error processing attachment %s: %s", part["filename"], e)
                            attach_docs = []
                    if os.path.exists(path):
                        os.remove(path)
                    for index, document in enumerate(attach_docs or []):
                        if "page_label" in document.metadata:
                            document.metadata["page"] = document.metadata["page_label"]
                        document.metadata["attachId"] = part["body"]["attachmentId"]
                        document.metadata["filename"] = part["filename"]
                        document.metadata = {
                            key: value
                            for key, value in document.metadata.items()
                            if key in ["filename", "page", "attachId"] \
                                and value is not None and value != ""
                        }
                        document.metadata.update(metadata)
                        document.metadata["mimeType"] = part["mimeType"]
                        document.metadata["id"] = (f"{msg_id}-"
                        f"{hashlib.sha256(file_data).hexdigest()}-{index}")
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
        return documents

    def _init_task(self, query):
        """Initialize the collection task and update status."""
        self.task['status'] = "in progress"
        upsert(self._id, self.task, "gmail")
        if self.task["type"] == "manual":
            query["task"] = {} if "task" not in query else query["task"]
            query["task"]["status"] = "in progress"
            upsert(self._id, query, "gmail", "user")
        logger.info(" Task %s status updated to 'in progress'", self.task["id"])

    def _update_query_status(self, query, messages_processed):
        """Update the query status in the task."""
        if self.task["type"] == "manual":
            query["task"]["status"] = self.task["status"]
            query["task"]["count"] = messages_processed
            query["task"]["service"] = "gmail"
            query["task"]["type"] = "manual"
            query["updatedTime"] = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
            self.task["query"] = query
            upsert(self._id, query, "gmail", "user")
            logger.info(" Query status updated")

    def collect(self, query):
        """
        Collects Gmail messages matching the specified query,
        processes their content, checks for relevance,
        and uploads relevant documents to a vector store.

        Workflow:
        1. Updates the task status to "in progress".
        2. Searches for Gmail messages matching the query.
        3. For each message:
            - Retrieves the full message and its metadata.
            - Extracts and processes the message content.
            - Checks if the extracted documents are relevant.
            - If relevant documents are found:
                - Deletes historical documents for the same thread to avoid duplication.
                - Uploads the relevant documents to the vector store.
        4. Updates the task status to "completed" upon successful processing.
        5. Handles and logs any exceptions, updating the task status to "failed" if an error occurs.

        Args:
            query (str): The Gmail search query to filter messages.

        Raises:
            Exception: Propagates any exceptions encountered during processing
                after updating the task status and logging the error.
        """
        logger.info("Starting Gmail collection for user with query: %s", query)
        try:
            self._init_task(query)
            messages_processed = 0
            for message in self._search(query, max_results=200, check_next_page=True):
                documents = []
                logger.info("Processing message with ID: %s", message["id"])
                msg = self.service.users().messages().get(  # pylint: disable=no-member
                    userId="me", id=message["id"], format="full").execute()
                metadata = self._get_metadata(msg)
                documents = self._retrieve_content(msg, metadata, message)
                # Increment counter for each message processed
                messages_processed += 1
                if len(query.get("topics", [])) > 0:
                    documents = check_relevance(documents, query.get("topics", []))
                logger.info("Found %d relevant documents for task %s",
                            len(documents), self.task["id"])
                if len(documents) > 0:
                    try:
                        result = astra_collection.delete_many({
                            "$and": [
                                {"metadata.threadId": msg["threadId"]},
                                {"metadata.service": "gmail"},
                                {"metadata.email": self.email},
                                {"metadata.userId": self.user_id}
                            ]
                        })
                        logger.info(
                            "Deleted historical %d documents for thread %s to avoid duplication",
                            result.deleted_count, msg["threadId"])
                        vstore.upload(documents, self.task)
                        logger.info("✅ Vector store upload successful for task %s", self.task["id"])
                    except (ConnectionError, TimeoutError) as upload_error:
                        logger.error(" Vector store upload failed for task %s: %s",
                                self.task["id"], str(upload_error))
                        raise upload_error
                    except (ValueError, TypeError) as upload_error:
                        logger.error(" Data validation error during vector store upload for task"
                        "%s: %s", self.task["id"], str(upload_error))
                        raise upload_error
                    except (OSError, IOError) as upload_error:
                        logger.error(" File system error during vector store upload for task "
                        "%s: %s",self.task["id"], str(upload_error))
                        raise upload_error
            self.task['status'] = "completed"
            self.task['updatedTime'] = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
            self._update_query_status(query, messages_processed)
            upsert(self._id, self.task, "gmail")
            logger.info("✅ Collection completed for task %s", self.task["id"])
        except (ValueError, TypeError, KeyError,
                IndexError, ConnectionError, TimeoutError, OSError, IOError) as e:
            logger.error("💥 Error in collect for task %s: %s",
                         self.task["id"], str(e), exc_info=True)
            # Mark task as failed
            self.task['status'] = "failed"
            # task_states[self.task["id"]] = "Failed"
            self._update_query_status(query, 0)
            upsert(self._id, self.task, "gmail")
            raise

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
                    messages = self._search(query, max_results=10)
            return self._get_email_by_messages(messages)
        except (KeyError, ValueError, TypeError) as e:
            logger.info("An error occurred: %s", e)
            return []
