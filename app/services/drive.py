"""
This module provides a utility class, `DriveService`, for interacting with the Google Drive API.
"""
import os
import io
from concurrent.futures import ThreadPoolExecutor
from venv import logger

from datetime import datetime, timezone
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload
from models.db import vstore, cosmos_collection, MongodbClient
from controllers.utils import upsert
from controllers.file import FileHandler
from langchain_core.documents import Document

SERVICE = "drive"
collection = MongodbClient[SERVICE]["user"]

EXPORT_MIME_TYPES = {
    'application/vnd.google-apps.document': 'application/pdf',
    'application/vnd.google-apps.spreadsheet':\
          'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'application/vnd.google-apps.presentation': 'application/pdf'
}

FILE_DIR = "cache"
os.makedirs(FILE_DIR, exist_ok=True)

MAX_WORKERS = 2
thread_pool = ThreadPoolExecutor(max_workers=MAX_WORKERS)


class DriveService():
    """
    DriveService is a utility class for interacting with Google Drive API.
    It provides methods to construct query strings, search for emails,
    and retrieve detailed email information.
    Methods:
        __init__(token):
            Initializes the DriveService instance with an authenticated Google Drive API service.
        build_query(params):
            Constructs a query string based on the provided parameters for filtering emails.
        _search(query, max_results=10, check_next_page=False):
            Searches for emails based on a query string and returns a list of message metadata.
        get_emails(query, max_results=10):
            Retrieves a list of emails with detailed information such as subject, sender, 
            recipients, and content.
    Attributes:
        service:
            An Google Drive API service instance used to interact with Google Drive API.
    """
    def __init__(self, credentials, user_id: str = None, email: str = None, task: str = None):
        """
        Initializes the Google Drive controller with the provided email address.

        Args:
            email_address (str):
            The email address used to create credentials for accessing the Google Drive API.
        """
        self.service = build(SERVICE, "v3", credentials=credentials)
        self.email = email
        self.task = task
        self.user_id = user_id
        self._id = f"{self.user_id}/{self.email}"
        if email and task:
            self.task = task
            self.email = email
            upsert(self._id, self.task, SERVICE)

    def _get_metadata(self, file_info: dict) -> dict:
        metadata = {}
        metadata["service"] = SERVICE
        metadata["date"] = datetime.fromisoformat(file_info["createdTime"].replace("Z", "+00:00"))
        metadata["lastModified"] = datetime.now(timezone.utc)
        metadata["userId"] = self.user_id
        metadata["email"] = self.email
        metadata["id"] = file_info["id"]
        metadata["folderId"] = file_info["folderId"]
        metadata["filename"] = file_info['path'].split("/")[-1]
        return metadata

    def _init_task(self, query):
        """Initialize the collection task and update status."""
        self.task['status'] = "in progress"
        upsert(self._id, self.task, SERVICE)
        if self.task["type"] == "manual":
            query["task"] = {} if "task" not in query else query["task"]
            query["task"]["status"] = "in progress"
            upsert(self._id, query, SERVICE, "users")
        logger.info(" Task %s status updated to 'in progress'", self.task["id"])

    def _update_query_status(self, query, messages_processed):
        """Update the query status in the task."""
        if self.task["type"] == "manual":
            query["task"]["status"] = self.task["status"]
            query["task"]["count"] = messages_processed
            query["updatedTime"] = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
            self.task["query"] = query
            upsert(self._id, query, SERVICE, "users")
            logger.info(" Query status updated")

    def download_file(self, file_info):
        """Download a file from Google Drive."""
        if file_info['mimeType'] in EXPORT_MIME_TYPES:
            export_mime_type = EXPORT_MIME_TYPES.get(file_info['mimeType'])
            if export_mime_type == 'application/pdf':
                file_info['name'] = os.path.splitext(file_info['name'])[0] + '.pdf'
            elif export_mime_type ==\
                  'application/vnd.openxmlformats-officedocument.wordprocessingml.document':
                file_info['name'] = os.path.splitext(file_info['name'])[0] + '.docx'
            elif export_mime_type ==\
                  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet':
                file_info['name'] = os.path.splitext(file_info['name'])[0] + '.xlsx'
            elif export_mime_type ==\
                  'application/vnd.openxmlformats-officedocument.presentationml.presentation':
                file_info['name'] = os.path.splitext(file_info['name'])[0] + '.pptx'
            request = self.service.files().export_media(    # pylint: disable=no-member
                fileId=file_info['id'], mimeType=export_mime_type)
        else:
            request = self.service.files().get_media(fileId=file_info['id']) # pylint: disable=no-member
        path = os.path.join(".", FILE_DIR, f"{self.user_id}", f"{file_info['name']}")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with io.FileIO(path, 'wb') as fh:
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                try:
                    _, done = downloader.next_chunk()
                except HttpError as error:
                    logger.error("An error occurred: %s", error)
                    break
            if done:
                file_info['path'] = path
                logger.info("Download completed for file: %s", file_info['name'])
        return done, file_info

    def collect(self, query):
        """
        Collects and processes files from a specified Google Drive folder based on given query.

        This method inits a collection task, retrieves files from specified Google Drive folder,
        processes each file (excluding folders and shortcuts), downloads file, extracts metadata,
        and uploads processed documents to a vector store after removing any historical duplicates.
        The task status is updated upon completion or failure.

        Args:
            query (dict): A dict containing query parameters, including the folder ID under.

        Raises:
            ConnectionError: If there is a network-related error during vector store upload.
            TimeoutError: If the vector store upload times out.
            ValueError: If there is a data validation error during vector store upload.
            TypeError: If there is a type error during vector store upload.
            OSError: If there is a file system error during vector store upload.
            IOError: If there is an I/O error during vector store upload.
            KeyError: If required keys are missing in the query or file information.
            IndexError: If an indexing error occurs during processing.

        Side Effects:
            - Updates the task status and metadata.
            - Logs progress and errors.
            - Modifies the vector store by deleting and uploading documents.
        """
        logger.info("Starting Google Drive collection for user with query: %s", query)
        try:
            self._init_task(query)
            file_processed = 0
            files = self.service.files().list(  # pylint: disable=no-member
                    q=f"'{query['id']}' in parents and trashed=false"
            ).execute()
            for item in files.get('files', []):
                documents = []
                if item["kind"] != 'drive#file' or\
                  item["mimeType"] in [
                      "application/vnd.google-apps.folder", "application/vnd.google-apps.shortcut"]:
                    continue
                logger.info("Processing file with ID: %s", item["id"])
                file_info = self.service.files().get(   # pylint: disable=no-member
                    fileId=item["id"],
                    fields="id, name, mimeType, createdTime, modifiedTime, parents").execute()
                done, file_info = self.download_file(file_info)
                if done:
                    file_info["folderId"] = query["id"]
                    metadata = self._get_metadata(file_info)
                    file_processed +=1
                    for document in FileHandler(path=file_info["path"]).process():
                        documents.append(Document(
                            page_content=document.page_content,
                            metadata=metadata,
                        ))
                if len(documents) > 0:
                    try:
                        result = cosmos_collection.delete_many({
                            "$and": [
                                {"metadata.id": file_info["id"]},
                                {"metadata.service": SERVICE},
                                {"metadata.email": self.email},
                                {"metadata.userId": self.user_id}
                            ]
                        })
                        logger.info(
                            "Deleted historical %d documents for file %s to avoid duplication",
                            result.deleted_count, file_info["id"])
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
            self._update_query_status(query, file_processed)
            # pylint: disable=duplicate-code
            upsert(self._id, self.task, SERVICE)
            logger.info("✅ Collection completed for task %s", self.task["id"])
        except (ValueError, TypeError, KeyError,
                IndexError, ConnectionError, TimeoutError, OSError, IOError) as e:
            logger.error("💥 Error in collect for task %s: %s",
                         self.task["id"], str(e), exc_info=True)
            self.task['status'] = "failed"
            raise
