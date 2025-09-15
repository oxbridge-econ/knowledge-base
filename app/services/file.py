"""Module for handling file operations."""
import os
from venv import logger
import hashlib
import threading
from datetime import datetime, timedelta
from typing import List, Dict, Any
from azure.storage.blob import (
    BlobServiceClient, ContentSettings,
    generate_blob_sas, BlobSasPermissions
)
from azure.core.exceptions import AzureError
from controllers.file import FileHandler
from controllers.loader import (
    FileAlreadyExistsError,upload, 
    delete_file,
)
from controllers.utils import upsert


SERVICE = "file"
AZURE_CONNECTION_STRING = os.getenv("AZURE_CONNECTION_STRING")
AZURE_CONTAINER_NAME = os.getenv("AZURE_CONTAINER_NAME")

ALLOWED_FILE_TYPES = {
    "application/pdf": ".pdf",
    "text/plain": ".txt",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "image/png": ".png",
    "image/jpeg": ".jpg"
}

class FileService:
    """
    FileService handles file operations including upload, retrieval, and deletion.
    Delegates document processing to the existing loader functions.
    """

    def __init__(self, user_id: str, task: dict = None):
        """
        Initialize FileService with user_id and optional task.
        
        Args:
            user_id (str): The user ID for file operations
            task (dict, optional): Task dictionary for tracking file processing status
        """
        self.user_id = user_id
        self.task = task
        if task:
            upsert(self.user_id, self.task, SERVICE)

    def process_file(self, content: bytes, filename: str, content_type: str) -> dict:
        """
        Process an uploaded file: validate, upload to Azure, and delegate to loader for processing.
        
        Args:
            content (bytes): File content
            filename (str): Name of the file
            content_type (str): MIME type of the file
            
        Returns:
            dict: Task information with processing status
        """
        try:
            # Validate file type
            if content_type not in ALLOWED_FILE_TYPES:
                raise ValueError(f"Unsupported file type: {content_type}")

            # Upload to Azure first
            self._upload_to_azure(content, filename, content_type)

            # Delegate to appropriate loader function based on content type
            temp_path = os.path.join("/tmp", filename)
            with open(temp_path, "wb") as f:
                f.write(content)

            # Use FileHandler for processing
            threading.Thread(
                target=self._process_with_file_handler,
                args=(temp_path, filename)
            ).start()

            return self.task

        except Exception as e:
            logger.error("Error processing file %s: %s", filename, str(e))
            if self.task:
                self.task["status"] = "failed"
                self.task["error"] = str(e)
                upsert(self.user_id, self.task, SERVICE)
            raise e


    def _process_with_file_handler(self, file_path: str, filename: str):
        """Process file using the standardized FileHandler."""
        try:
            # Update task status
            if self.task:
                self.task["status"] = "in progress"
                upsert(self.user_id, self.task, SERVICE)

            # Use FileHandler for processing
            file_handler = FileHandler(file_path)
            documents = file_handler.process()

            # Add metadata and upload to vector store
            for doc in documents:
                doc.metadata["source"] = filename
                doc.metadata["userId"] = self.user_id
                doc.metadata["service"] = SERVICE
                doc.metadata['lastModified'] = datetime.now().strftime("%Y/%m/%d %H:%M:%S")

            # Upload to vector store (use existing upload function)
            upload(documents, self.user_id, self.task)

        except Exception as e:
            logger.error("Error processing file %s: %s", filename, e)
            if self.task:
                self.task["status"] = "failed"
                self.task["error"] = str(e)
                upsert(self.user_id, self.task, SERVICE)

        finally:
            if os.path.exists(file_path):
                os.remove(file_path)


    def get_files(self) -> List[Dict[str, Any]]:
        """
        Retrieve list of files uploaded by the user from Azure Blob Storage.
        
        Returns:
            List[Dict[str, Any]]: List of file metadata with download URLs
        """
        try:
            blob_service_client = BlobServiceClient.from_connection_string(AZURE_CONNECTION_STRING)
            container_client = blob_service_client.get_container_client(AZURE_CONTAINER_NAME)
            blobs = container_client.list_blobs(name_starts_with=f"{self.user_id}/")

            files = []
            for blob in blobs:
                file_id = hashlib.sha256((self.user_id + blob.name).encode()).hexdigest()
                download_url = self._generate_download_url(blob.name, expiry_hours=8760)

                files.append({
                    "id": file_id,
                    "filename": blob.name.split("/")[-1],
                    "createdAt": blob.last_modified.isoformat(),
                    "downloadUrl": download_url,
                })
            return files

        except AzureError as e:
            logger.error("Error retrieving files for %s: %s", self.user_id, e)
            return []

    def delete_file(self, filename: str) -> Dict[str, Any]:
        """
        Delete a file from Azure Blob Storage and remove associated documents from vector database.
        Uses the existing delete_file function from loader.
        
        Args:
            filename (str): Name of the file to delete
            
        Returns:
            Dict[str, Any]: Result of the deletion operation
        """

        return delete_file(self.user_id, filename)

    def _upload_to_azure(self, file_content: bytes, filename: str, content_type: str):
        """Upload file to Azure Blob Storage."""
        blob_path = f"{self.user_id}/{filename}"

        try:
            blob_service_client = BlobServiceClient.from_connection_string(AZURE_CONNECTION_STRING)
            container_client = blob_service_client.get_container_client(AZURE_CONTAINER_NAME)
            blob_client = container_client.get_blob_client(blob_path)

            if blob_client.exists():
                logger.warning("File already exists at %s", blob_path)
                raise FileAlreadyExistsError(filename)

            content_settings = ContentSettings(content_type=content_type)
            blob_client.upload_blob(
                file_content,
                overwrite=True,
                content_settings=content_settings
            )

            logger.info("File uploaded successfully to %s", blob_path)

        except FileAlreadyExistsError:
            raise
        except AzureError as e:
            logger.error("Azure error uploading file to %s: %s", blob_path, e)
            raise
        except Exception as e:
            logger.error("Unexpected error uploading file to %s: %s", blob_path, e)
            raise

    def _generate_download_url(self, blob_path: str, expiry_hours: int = 1) -> str:
        """Generate a download URL (SAS URL) for a blob in Azure Storage."""
        try:
            blob_service_client = BlobServiceClient.from_connection_string(AZURE_CONNECTION_STRING)

            sas_token = generate_blob_sas(
                account_name=blob_service_client.account_name,
                container_name=AZURE_CONTAINER_NAME,
                blob_name=blob_path,
                account_key=blob_service_client.credential.account_key,
                permission=BlobSasPermissions(read=True),
                expiry=datetime.now() + timedelta(hours=expiry_hours)
            )

            blob_url = (
                f"https://{blob_service_client.account_name}."
                f"blob.core.windows.net/{AZURE_CONTAINER_NAME}/"
                f"{blob_path}?{sas_token}"
            )
            return blob_url

        except Exception as e:
            logger.error("Error generating download URL for %s: %s", blob_path, e)
            raise
