"""Module to extract text from PDF files and images using Azure OpenAI's GPT-4o-mini model."""
import base64
import hashlib
import json
import os
from io import BytesIO
import threading
from datetime import datetime, timedelta
from typing import List, Dict, Any
from venv import logger
from PIL import Image
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import Docx2txtLoader
from langchain_core.documents import Document
from pdf2image import convert_from_path
from pydantic import BaseModel
from pypdf import PdfReader
from azure.storage.blob import (
     BlobServiceClient, ContentSettings,
    generate_blob_sas, BlobSasPermissions)
from azure.core.exceptions import AzureError

from models.llm import client
from models.db import vstore, astra_collection
from controllers.utils import upsert
from schema import task_states


text_splitter = RecursiveCharacterTextSplitter()
AZURE_CONNECTION_STRING = os.getenv("AZURE_CONNECTION_STRING")
AZURE_CONTAINER_NAME = os.getenv("AZURE_CONTAINER_NAME")

ALLOWED_FILE_TYPES = {
    "application/pdf": ".pdf",
    "text/plain": ".txt",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "image/png": ".png",
    "image/jpeg": ".jpg"
}

class FileAlreadyExistsError(Exception):
    """Custom exception raised when a file already exists in Azure Blob Storage."""
    def __init__(self, filename: str):
        self.filename = filename
        super().__init__(
            f"A file with the name '{filename}' "
            f"already exists. Please rename the file and try again."
        )

class ExtractionResult(BaseModel):
    """
    ExtractionResult is a data model that represents the result of an extraction process.

    Attributes:
        content (str): The extracted content as a string.
    """
    content: str

def check_image(page):
    """
    Checks if a given PDF page contains any images.

    This function examines the /Resources dictionary of the provided PDF page
    to determine if it contains any XObjects of subtype /Image.

    Args:
        page: A dictionary-like object representing a PDF page.

    Returns:
        bool: True if the page contains at least one image, False otherwise.
    """
    # Get the /Resources dictionary
    resources = page.get("/Resources")
    if resources is None:
        return False
    # Check for /XObject in resources
    xobjects = resources.get("/XObject")
    if xobjects is None:
        return False
    # Iterate through XObjects to find images
    for obj in xobjects.values():
        if obj.get("/Subtype") == "/Image":
            return True
    return False

def extract_text_from_image(image):
    """
    Extracts text content from an image of a document page and returns it as structured JSON.

    Args:
        image (PIL.Image.Image): The image object representing the document page.

    Returns:
        str: The extracted plain text content of the page in JSON format.

    Raises:
        Exception: If the response from the AI model is invalid or cannot be parsed.

    Dependencies:
        - Requires the `BytesIO` module for handling image byte streams.
        - Requires the `base64` module for encoding the image in Base64 format.
        - Requires a client instance capable of interacting with the GPT-4o-mini model.
    """
    image_bytes = BytesIO()
    image.save(image_bytes, format="PNG")
    image_bytes = image_bytes.getvalue()
    base64_image = base64.b64encode(image_bytes).decode("utf-8")
    prompt = """
    You are an AI assistant that extracts data from documents and returns it as structured JSON.
    Analyze the provided image of a document page and extract the following:
    - Content of the page (plain text)
    """
    response = client.beta.chat.completions.parse(
        model="gpt-4.1-mini",
        response_format = ExtractionResult,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{base64_image}"}
                    }
                ]
            }
        ]
    )
    return json.loads(response.choices[0].message.content)["content"]

def load_pdf(content: bytes, filename: str, email: str, task: dict):
    """
    Loads and processes PDF files from a specified directory.

    This function iterates through all PDF files in the given directory, extracts text
    from each page, and creates a list of Document objects containing the extracted text
    and metadata. If a page contains an image, the text is extracted from the image using
    OCR.

    Args:
        content (bytes): The binary content of the image file.
        filename (str): The name to use when saving the file temporarily.
        email (str): The email address of the user, used for metadata.
        task_id (str): The unique identifier for the task.

    Returns:
        list: A list of Document objects, where each object contains the page content
              and metadata (filename and page number).

    Raises:
        FileNotFoundError: If a specified PDF file is not found.
        Exception: For any other errors encountered during processing.

    Notes:
        - The function assumes the presence of helper functions `check_image`, 
          `convert_from_path`, and `extract_text_from_image`.
        - The `Document` class is used to store the page content and metadata.
    """
    documents = []
    path = os.path.join("/tmp", filename)
    with open(path, "wb") as f:
        f.write(content)
    try:
        task["status"] = "in progress"
        task["updatedTime"] = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
        upsert(email, task)
        task_states[task["id"]] = "In Progress"
        pdf = PdfReader(path)
        for page_num, page in enumerate(pdf.pages):
            contain = check_image(page)
            if contain:
                images = convert_from_path(
                    path, first_page=page_num + 1, last_page=page_num + 1)
                text = extract_text_from_image(images[0])
            else:
                text = page.extract_text()
            doc = Document(
                page_content=text,
                metadata={"source": filename, "page": page_num + 1})
            documents.append(doc)
        os.remove(path)
        threading.Thread(target=upload, args=[documents, email, task]).start()
    except (FileNotFoundError, ValueError, OSError, Exception) as e: # pylint: disable=broad-except
        if os.path.exists(path):
            os.remove(path)
        task["status"] = "failed"
        task["error"] = str(e)
        upsert(email, task)
        task_states[task["id"]] = "Failed"


def load_img(content: bytes, filename: str, email: str, task: dict):
    """
    Loads an image file from bytes content, extracts its contents and upload.

    Args:
        content (bytes): The binary content of the image file.
        filename (str): The name to use when saving the file temporarily.
        email (str): The email address of the user, used for metadata.
        task_id (str): The unique identifier for the task.

    Returns:
        list: A list of dictionaries representing the extracted documents.

    Side Effects:
        - Writes the image file to the /tmp directory.
        - Uploads the extracted documents using the upload function.
    """
    try:
        task["status"] = "in progress"
        upsert(email, task)
        task_states[task["id"]] = "In Progress"
        documents = []
        text = extract_text_from_image(Image.open(BytesIO(content)))
        doc = Document(page_content=text, metadata={"source": filename})
        documents.append(doc)
        threading.Thread(target=upload, args=[documents, email, task]).start()
    except (FileNotFoundError, ValueError, OSError) as e:
        logger.error("Error processing image %s: . Error: %s", filename, e)
        task["status"] = "failed"
        upsert(email, task)
        task_states[task["id"]] = "Failed"


def load_docx(content: bytes, filename: str, email: str, task: dict):
    """
    Loads a DOCX file from bytes content, extracts its contents and upload.

    Args:
        content (bytes): The binary content of the DOCX file.
        filename (str): The name to use when saving the file temporarily.
        email (str): The email address of the user, used for metadata.
        task_id (str): The unique identifier for the task.

    Returns:
        list: A list of dictionaries representing the extracted documents.

    Side Effects:
        - Writes the DOCX file to the /tmp directory.
        - Uploads the extracted documents using the upload function.
    """
    path = os.path.join("/tmp", filename)
    try:
        task["status"] = "in progress"
        upsert(email, task)
        task_states[task["id"]] = "In Progress"
        with open(path, "wb") as f:
            f.write(content)
        documents = Docx2txtLoader(file_path=path).load()
        os.remove(path)
        threading.Thread(target=upload, args=[documents, email, task]).start()
    except (FileNotFoundError, ValueError, OSError):
        if os.path.exists(path):
            os.remove(path)
        task["status"] = "failed"
        upsert(email, task)
        task_states[task["id"]] = "Failed"


def upload(docs: list[Document], email: str, task: dict):
    """
    Processes a list of documents, splits them into smaller chunks, updates their metadata,
    generates unique IDs for each chunk, and adds them to a vector store.

    Args:
        docs (list): A list of document objects to be processed.
        email (str): The email address of the user, used for metadata.
        task (dict): The task dictionary containing task information.

    Metadata Processing:
        - Extracts and updates the "page" metadata if "page_label" exists.
        - Updates the "attachment" metadata by removing the "{FOLDER}/" prefix from the "source".
        - Filters metadata to retain only "attachment" and "page" keys.
        - Generates a unique "id" for each document based on the "attachment" metadata.
        - Constructs unique IDs for each document chunk, incorporating "id", "page", and index.

    Operations:
        - Splits each document into smaller chunks using `text_splitter.split_documents`.
        - Appends processed document chunks and their IDs to the `documents` and `ids` lists.
        - Adds the processed documents and their IDs to the `vector_store`.

    Raises:
        KeyError: If required metadata keys are missing during processing.
    """
    documents = []
    ids = []
    try:
        for doc in docs:
            for index, document in enumerate(text_splitter.split_documents([doc])):
                if "page_label" in document.metadata:
                    document.metadata["page"] = int(document.metadata["page_label"])
                attachment = document.metadata["source"].replace("{FOLDER}/", "")
                document.metadata["title"] = attachment.split(".")[0]
                document.metadata["ext"] = attachment.split(".")[-1]
                document.metadata = {
                    key: value
                    for key, value in document.metadata.items()
                    if key in ["page", "title", "ext"]
                }
                document.metadata["id"] = str(
                    hashlib.sha256((email + attachment).encode()).hexdigest())
                document.metadata["userId"] = email
                document.metadata["type"] = "file"
                if "page" in document.metadata:
                    ids.append(f"{document.metadata['id']}-{document.metadata['page']}-{index}")
                else:
                    ids.append(f"{document.metadata['id']}-{index}")
                documents.append(document)
        vstore.add_documents_with_retry(documents, ids, task)
        task["status"] = "completed"
        upsert(email, task)
        task_states[task["id"]] = "Completed"
    except (ConnectionError, TimeoutError, KeyError, ValueError, TypeError, AttributeError) as e:
        logger.error("Error processing documents: %s", e)
        task["status"] = "failed"
        upsert(email, task)
        task_states[task["id"]] = "Failed"


def upload_file_to_azure(
        file_content: bytes, filename: str,
        email: str, content_type: str = None
    ) -> Dict[str, Any]:
    """
    Upload a file to Azure Blob Storage.
    
    Args:
        file_content: The file content as bytes
        blob_path: The path in the container where the file will be stored
        content_type: The MIME type of the file
        
    Returns:
        Dict containing upload result status and details
    """

    blob_path = f"{email}/{filename}"

    try:
        # Initialize the BlobServiceClient
        blob_service_client = BlobServiceClient.from_connection_string(AZURE_CONNECTION_STRING)

        # Get a reference to the container
        container_client = blob_service_client.get_container_client(AZURE_CONTAINER_NAME)

        # Create a blob client for the specific path
        blob_client = container_client.get_blob_client(blob_path)

        if blob_client.exists():
            logger.warning("File already exists at %s", blob_path)
            raise FileAlreadyExistsError(filename)

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
    except FileAlreadyExistsError as e:
        logger.error("File already exists at %s: %s" , blob_path, e)
        raise e
    except AzureError as e:
        logger.error("Azure error uploading file to %s: %s", blob_path, e)
        raise e
    except Exception as e:
        logger.error("Unexpected error uploading file to %s: %s", blob_path, e)
        raise e


def get_files(email: str) -> List[Dict[str, Any]]:
    """
    Retrieves the list of files uploaded by the user from Azure Blob Storage.

    Args:
        email (str): The email of the user.

    Returns:
        List[Dict[str, Any]]: A list of dictionaries containing file metadata.
    """

    try:
        blob_service_client = BlobServiceClient.from_connection_string(AZURE_CONNECTION_STRING)
        container_client = blob_service_client.get_container_client(AZURE_CONTAINER_NAME)
        blobs = container_client.list_blobs(name_starts_with=f"{email}/")

        files = []
        for blob in blobs:
            # Generate a unique ID for the file
            file_id = hashlib.sha256((email + blob.name).encode()).hexdigest()

            # Generate download URL (SAS URL)
            download_url = generate_download_url(blob.name, expiry_hours=8760)

            files.append({
                "id": file_id,
                "filename": blob.name.split("/")[-1],
                "createdAt": blob.last_modified.isoformat(),
                "downloadUrl": download_url,
            })
        return files
    except AzureError as e:
        logger.error("Error retrieving files for %s: %s", email, e)
        return []

def generate_download_url(blob_path: str, expiry_hours: int = 1) -> str:
    """
    Generate a download URL (SAS URL) for a blob in Azure Storage.
    
    Args:
        blob_path: The path to the blob in the container
        expiry_hours: Number of hours the URL should be valid (default: 1)
        
    Returns:
        str: The download URL with SAS token
    """
    try:
        blob_service_client = BlobServiceClient.from_connection_string(AZURE_CONNECTION_STRING)

        # Generate SAS token
        sas_token = generate_blob_sas(
            account_name=blob_service_client.account_name,
            container_name=AZURE_CONTAINER_NAME,
            blob_name=blob_path,
            account_key=blob_service_client.credential.account_key,
            permission=BlobSasPermissions(read=True),
            expiry=datetime.now() + timedelta(hours=expiry_hours)
        )

        # Construct the full URL
        blob_url = (
            f"https://{blob_service_client.account_name}."
            f"blob.core.windows.net/{AZURE_CONTAINER_NAME}/"
            f"{blob_path}?{sas_token}"
        )
        return blob_url

    except Exception as e:
        logger.error("Error generating download URL for %s: %s", blob_path, e)
        raise e

def delete_file(email: str, file_name: str) -> Dict[str, Any]:
    """
    Deletes a file from Azure Blob Storage 
    and removes associated documents from the vector database.
    Args:
        email (str): The email of the user.
        file_name (str): The name of the file to delete.

    Returns:
        Dict[str, Any]: A dictionary containing the result of the deletion operation.
    """
    try:
        blob_service_client = BlobServiceClient.from_connection_string(AZURE_CONNECTION_STRING)
        container_client = blob_service_client.get_container_client(AZURE_CONTAINER_NAME)
        blob_path = f"{email}/{file_name}"

        blob_client = container_client.get_blob_client(blob_path)
        if not blob_client.exists():
            return {"success": False, "error": f"File '{file_name}' not found."}

        # Delete the blob from Azure Storage
        blob_client.delete_blob()

        # Generate the same document ID used during upload
        document_id = str(hashlib.sha256((email + file_name).encode()).hexdigest())

        # Extract title and extension from filename
        title = file_name.split(".")[0]
        ext = file_name.split(".")[-1]

        # Delete from vector database using the same approach as Gmail service
        try:
            result = astra_collection.delete_many({
                "$and": [
                    {"metadata.userId": email},
                    {"metadata.id": document_id},
                    {"metadata.type": "file"},
                    {"metadata.title": title},
                    {"metadata.ext": ext}
                ]
            })

            logger.info("Deleted %d document chunks from vector DB for file %s, user %s",
                       result.deleted_count, file_name, email)

        except (ConnectionError, TimeoutError, ValueError) as vdb_error:
            logger.error("Error deleting from vector DB for file %s: %s", file_name, vdb_error)

        return {
            "success": True, 
            "message": (f"File '{file_name}' deleted successfully"
                        f" from Azure Storage and vector database."
                    )
        }
    except AzureError as e:
        logger.error("Error deleting file %s: %s", file_name, e)
        return {"success": False, "error": str(e)}
    except (ConnectionError, TimeoutError, ValueError) as e:
        logger.error("Unexpected error deleting file %s: %s", file_name, e)
        return {"success": False, "error": str(e)}
