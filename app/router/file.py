"""Module for defining the main routes of the API."""
import uuid
import threading
from typing import List, Dict, Any
from venv import logger
import os
from pathlib import Path
from fastapi import APIRouter, File, UploadFile, HTTPException, Query
from fastapi.responses import JSONResponse
from controllers.utils import upsert
from controllers.loader import load_docx, load_pdf, load_img
from schema import task_states
from azure.storage.blob import BlobServiceClient, ContentSettings
from azure.core.exceptions import AzureError

router = APIRouter(prefix="/file", tags=["file"])

ALLOWED_FILE_TYPES = {
    "application/pdf": ".pdf",
    "text/plain": ".txt",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "image/png": ".png",
    "image/jpeg": ".jpg"
}

AZURE_CONNECTION_STRING = os.getenv("AZURE_CONNECTION_STRING")
AZURE_CONTAINER_NAME = os.getenv("AZURE_CONTAINER_NAME")

def upload_file_to_azure(file_content: bytes, blob_path: str, content_type: str = None) -> Dict[str, Any]:
    """
    Upload a file to Azure Blob Storage.
    
    Args:
        file_content: The file content as bytes
        blob_path: The path in the container where the file will be stored
        content_type: The MIME type of the file
        
    Returns:
        Dict containing upload result status and details
    """
    if not AZURE_CONNECTION_STRING:
        logger.error("Azure Storage connection string not configured")
        return {
            "success": False,
            "error": "Azure Storage not configured",
            "message": "Azure Storage connection string is missing"
        }

    try:
        # Initialize the BlobServiceClient
        blob_service_client = BlobServiceClient.from_connection_string(AZURE_CONNECTION_STRING)

        # Get a reference to the container
        container_client = blob_service_client.get_container_client(AZURE_CONTAINER_NAME)
        # Ensure container exists
        try:
            container_client.create_container()
        except Exception:
            pass

        # Create a blob client for the specific path
        blob_client = container_client.get_blob_client(blob_path)

        # Set content type if provided
        content_settings = None
        if content_type:
            content_settings = ContentSettings(content_type=content_type)

        # Upload the file
        blob_client.upload_blob(
            file_content, 
            overwrite=True,
            content_settings=content_settings
        )

        logger.info("File uploaded successfully to %s", blob_path)

        return {
            "success": True,
            "blob_path": blob_path,
            "message": "File uploaded successfully"
        }

    except AzureError as e:
        logger.error("Azure error uploading file to %s: %s", blob_path, e)
        return {
            "success": False,
            "blob_path": blob_path,
            "error": str(e),
            "message": "Failed to upload file to Azure Blob Storage"
        }
    except Exception as e:
        logger.error("Unexpected error uploading file to %s: %s", blob_path, e)
        return {
            "success": False,
            "blob_path": blob_path,
            "error": str(e),
            "message": "Unexpected error during file upload"
        }

def _validate_file(file: UploadFile) -> Dict[str, Any]:
    """
    Validate a single file against allowed types.
    
    Args:
        file: The uploaded file to validate
        
    Returns:

        Dict containing validation result
    """
    if not file.filename:
        return {
            "valid": False,
            "error": "Filename is required"
        }

    file_extension = Path(file.filename).suffix.lower()

    if file.content_type not in ALLOWED_FILE_TYPES:
        return {
            "valid": False,
            "error": f"Content type '{file.content_type}' is not allowed"
        }

    expected_extension = ALLOWED_FILE_TYPES.get(file.content_type)
    if file_extension != expected_extension:
        return {
            "valid": False,
            "error": f"File extension '{file_extension}' doesn't match content type '{file.content_type}'"
        }

    return {"valid": True}

def _process_file_async(
    file_content: bytes, 
    filename: str, 
    email: str, 
    content_type: str, 
    task: Dict[str, Any]
) -> None:
    """
    Process a single file asynchronously (existing processing logic).
    
    Args:
        file_content: The file content as bytes
        filename: The original filename
        email: The user's email
        content_type: The MIME type of the file
        task: The task dictionary
    """
    try:
        task["status"] = "in progress"
        task_states[task["id"]] = "In Progress"
        upsert(email, task)
        logger.info("Task %s: Status updated to 'in progress'.", task["id"])
        if content_type == "application/pdf":
            load_pdf(file_content, filename, email, task)
        elif content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            load_docx(file_content, filename, email, task)
        elif content_type in ["image/png", "image/jpeg"]:
            load_img(file_content, filename, email, task)
        else:
            logger.warning("Unsupported content type for processing: %s", content_type)
            task["status"] = "completed"
            task_states[task["id"]] = "Completed"
            upsert(email, task)
            logger.info("Task %s: Marked as 'completed' (unsupported file type).", task["id"])
            return

        task["status"] = "completed"
        task_states[task["id"]] = "Completed"
        upsert(email, task)
        logger.info("Task %s: Status updated to 'completed'.", task["id"])
    except Exception as e:
        logger.error("Error processing file %s: %s", filename, e)
        task["status"] = "failed"
        task["error_message"] = str(e)
        task_states[task["id"]] = "Failed"
        upsert(email, task)


@router.post("")
async def load(
    files: List[UploadFile] = File(...), email: str = Query(...)) -> JSONResponse:
    """
    Handles multiple file uploads with Azure Blob Storage support.

    Args:
        files: List of uploaded files
        email: The user's email address

    Returns:
        JSONResponse: Summary of upload results for each file
    """
    if not files:
        raise HTTPException(
            status_code=400,
            detail="No files provided"
        )


    # Validate email
    if not email or "@" not in email:
        raise HTTPException(
            status_code=400,
            detail="Valid email address is required"
        )

    results = []
    task = {
            "id": str(uuid.uuid4()),
            "status": "pending",
            "service": "file",
            "type": "manual",
            }
    for file in files:
        result = {
            "filename": file.filename,
            "content_type": file.content_type,
            "validation": {"valid": False},
            "azure_upload": {"success": False},
        }

        try:
            # Validate file
            validation_result = _validate_file(file)
            result["validation"] = validation_result

            if not validation_result["valid"]:
                result["error"] = validation_result["error"]
                results.append(result)
                continue

            # Read file content
            file_content = await file.read()

            if len(file_content) == 0:
                result["error"] = "File is empty"
                results.append(result)
                continue

            # Upload to Azure Blob Storage
            blob_path = f"{email}/{file.filename}"
            azure_result = upload_file_to_azure(
                file_content=file_content,
                blob_path=blob_path,
                content_type=file.content_type
            )

            result["azure_upload"] = azure_result

            # Update task states
            task_states[task["id"]] = "Pending"
            upsert(email, task)

            # Start asynchronous processing of the file
            if file.content_type in ALLOWED_FILE_TYPES:
                threading.Thread(
                    target=_process_file_async,
                    args=(file_content, file.filename, email, file.content_type, task)
                ).start()
        except Exception as e:
            logger.error("Error processing file %s: %s", file.filename, e)
            result["error"] = str(e)

        results.append(result)

    # Create summary
    total_files = len(files)
    successful_validations = sum(1 for r in results if r["validation"]["valid"])
    successful_uploads = sum(1 for r in results if r["azure_upload"]["success"])

    summary = {
        "total_files": total_files,
        "successful_validations": successful_validations,
        "successful_uploads": successful_uploads,
        "failed_files": total_files - successful_uploads,
        "results": results,
        "task": task
    }

    logger.info(
        "File upload summary for %s: %d/%d files uploaded successfully to Azure",
        email, successful_uploads, total_files
    )

    return JSONResponse(content=task)

