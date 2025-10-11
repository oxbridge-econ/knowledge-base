"""Module to extract text from PDF files and images using Azure OpenAI's GPT-4o-mini model."""
import base64
import hashlib
import json
import os
from io import BytesIO

from venv import logger

from langchain.text_splitter import RecursiveCharacterTextSplitter

from langchain_core.documents import Document

from pydantic import BaseModel

from azure.storage.blob import (
     BlobServiceClient)
from azure.core.exceptions import AzureError

from models.llm import client
from models.db import vstore, cosmos_collection
from controllers.utils import upsert


text_splitter = RecursiveCharacterTextSplitter()
AZURE_CONNECTION_STRING = os.getenv("AZURE_CONNECTION_STRING")
AZURE_CONTAINER_NAME = os.getenv("AZURE_CONTAINER_NAME")


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


def upload(docs: list[Document], user_id: str, task: dict):
    """
    Processes a list of documents, splits them into smaller chunks, updates their metadata,
    generates unique IDs for each chunk, and adds them to a vector store.

    Args:
        docs (list): A list of document objects to be processed.
        user_id (str): The user_id address of the user, used for metadata.
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
                document.metadata["filename"] = attachment
                document.metadata = {
                    key: value
                    for key, value in document.metadata.items()
                    if key in ["page", "filename"]
                }
                document.metadata["id"] = str(
                    hashlib.sha256((user_id + attachment).encode()).hexdigest())
                document.metadata["userId"] = user_id
                document.metadata["service"] = "file"
                if "page" in document.metadata:
                    ids.append(f"{document.metadata['id']}-{document.metadata['page']}-{index}")
                else:
                    ids.append(f"{document.metadata['id']}-{index}")
                documents.append(document)
        vstore.add_documents_with_retry(documents, ids, task)
        task["status"] = "completed"
        upsert(user_id, task, "file")
    except (ConnectionError, TimeoutError, KeyError, ValueError, TypeError, AttributeError) as e:
        logger.error("Error processing documents: %s", e)
        task["status"] = "failed"
        upsert(user_id, task, "file")

def delete_file(user_id: str, file_name: str):
    """
    Deletes a file from Azure Blob Storage 
    and removes associated documents from the vector database.
    Args:
        user_id (str): The id of the user.
        file_name (str): The name of the file to delete.

    Returns:
        Dict[str, Any]: A dictionary containing the result of the deletion operation.
    """
    try:
        blob_service_client = BlobServiceClient.from_connection_string(AZURE_CONNECTION_STRING)
        container_client = blob_service_client.get_container_client(AZURE_CONTAINER_NAME)
        blob_path = f"{user_id}/{file_name}"

        blob_client = container_client.get_blob_client(blob_path)
        if not blob_client.exists():
            return {"success": False, "error": f"File '{file_name}' not found."}

        # Delete the blob from Azure Storage
        blob_client.delete_blob()

        # Generate the same document ID used during upload
        document_id = str(hashlib.sha256((user_id + file_name).encode()).hexdigest())

        # Extract title and extension from filename
        title = file_name.split(".")[0]
        ext = file_name.split(".")[-1]

        # Delete from vector database using the same approach as Gmail service
        try:
            result = cosmos_collection.delete_many({
                "$and": [
                    {"metadata.userId": user_id},
                    {"metadata.id": document_id},
                    {"metadata.service": "file"},
                    {"metadata.title": title},
                    {"metadata.ext": ext}
                ]
            })

            logger.info("Deleted %d document chunks from vector DB for file %s, user %s",
                       result.deleted_count, file_name, user_id)

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
