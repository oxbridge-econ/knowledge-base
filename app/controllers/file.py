"""Module for loading documents from sources including local files, URLs, and SharePoint."""
import os
import base64
import hashlib
import json
from venv import logger
from io import BytesIO
from ics import Calendar
import requests
from pydantic import BaseModel
from pdf2image import convert_from_path
from pypdf import PdfReader
from langchain_core.documents import Document
from langchain_community.document_loaders import (
    CSVLoader,
    UnstructuredExcelLoader,
    Docx2txtLoader,
    UnstructuredWordDocumentLoader,
    UnstructuredPowerPointLoader,
    UnstructuredMarkdownLoader,
    TextLoader,
    OutlookMessageLoader,
    UnstructuredEmailLoader,
    BSHTMLLoader
)

from models.llm import client

class ExtractionResult(BaseModel):
    """
    ExtractionResult is a data model that represents the result of an extraction process.

    Attributes:
        content (str): The extracted content as a string.
    """
    content: str

def _extract_text_from_image(base64_image: str) -> str:
    """
    Extracts plain text content from a document image provided as a base64-encoded string.

    This function sends the image to LLM for extraction of the page's textual content.
    The image is expected to be in PNG format and encoded as a base64 string.

    Args:
        base64_image (str): A base64-encoded string representing the PNG image of the document page.

    Returns:
        str: The extracted plain text content from the image.
    """
    prompt = """
    You are an AI assistant that extracts data from documents and returns it as structured JSON.
    Analyze the provided image of a document page and extract the following:
    - Content of the page (plain text)
    """
    response = client.chat.completions.parse(
        model="gpt-4.1-mini",
        response_format=ExtractionResult,
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

class PDFLoader:    # pylint: disable=too-few-public-methods
    """
    PDFLoader is a class that handles loading and processing of PDF files.

    It extracts text from each page of the PDF and returns a list of Document objects
    containing the extracted text and metadata.
    """
    def __init__(self, path: str):
        self.path = path

    def _check_image(self, page, page_area=None, area_threshold=0.7):
        resources = page.get("/Resources")
        if resources is None:
            return False
        if "/XObject" in resources:
            xobjects = resources["/XObject"].get_object()
            for obj in xobjects:
                xobject = xobjects[obj]
                if xobject.get("/Subtype") == "/Image":
                    img_width = float(xobject["/Width"])
                    img_height = float(xobject["/Height"])
                    img_area = img_width * img_height
                    if page_area:
                        area_ratio = img_area / page_area
                        if area_ratio >= area_threshold:
                            logger.info("Image found with area ratio %.2f.", area_ratio)
                            return True
                    else:
                        return True
        return False

    def load(self):
        """
        Loads and processes PDF files from the provided content.

        Returns:
            list: A list of Document objects, where each object contains the page content
                  and metadata (filename and page number).
        """
        documents = []
        try:
            pdf = PdfReader(self.path)
            for page_num, page in enumerate(pdf.pages):
                contain = self._check_image(
                    page, page_area=float(page.mediabox.width * page.mediabox.height))
                if contain:
                    images = convert_from_path(
                        self.path, first_page=page_num + 1, last_page=page_num + 1)
                    image_bytes = BytesIO()
                    images[0].save(image_bytes, format="PNG")
                    image_bytes = image_bytes.getvalue()
                    base64_image = base64.b64encode(image_bytes).decode("utf-8")
                    text = _extract_text_from_image(base64_image)
                else:
                    text = page.extract_text()
                doc = Document(
                    page_content=text,
                    metadata={"page": page_num + 1})
                documents.append(doc)
            os.remove(self.path)
        except (FileNotFoundError, ValueError, OSError, Exception) as e:  # pylint: disable=broad-except
            if os.path.exists(self.path):
                os.remove(self.path)
            logger.error("Error: %s", str(e))
        return documents

class ImageLoader:  # pylint: disable=too-few-public-methods
    """
    ImageLoader is a class that handles loading and processing of image files.

    It extracts text from images using OCR and returns a list of Document objects
    containing the extracted text and metadata.
    """
    def __init__(self, file_path: str):
        self.file_path = file_path

    def load(self):
        """
        Loads and processes image files from a specified path.

        This function reads an image file, extracts text from it using OCR,
        and creates a Document object containing the extracted text and metadata.

        Returns:
            list: A list containing a single Document object with the extracted text.
        """
        documents = []
        try:
            with open(self.file_path, "rb") as image_file:
                image_bytes = image_file.read()
                base64_image = base64.b64encode(image_bytes).decode("utf-8")
                doc = Document(
                    page_content=_extract_text_from_image(base64_image)
                )
                documents.append(doc)
        except (FileNotFoundError, OSError, ValueError) as e:
            logger.error("Error loading image: %s", str(e))
        return documents

class CalendarLoader:  # pylint: disable=too-few-public-methods
    """
    CalendarLoader is a class that handles loading and processing of calendar files.
    """
    def __init__(self, file_path: str, part: dict, msg_id: str, file_data: bytes):
        self.file_path = file_path
        self.part = part or {}
        self.msg_id = msg_id or ""
        self.file_data = file_data or b""

    def load(self):
        """
        Loads and processes calendar files from a specified path.
        """
        documents = []
        try:
            calendar = None
            if self.file_data:
                calendar = Calendar(self.file_data.decode("utf-8"))
            else:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    calendar = Calendar(f.read())

            for event in calendar.events:
                documents.append(
                    Document(
                        page_content=(f"Event: {event.name}\n"
                        f"Description: {event.description}\n"
                        f"Start: {event.begin}\n"
                        f"End: {event.end}"),
                        metadata={
                            "attachment": self.part["filename"],
                            "mimeType": self.part["mimeType"],
                            "location": event.location,
                            "created": event.created.strftime("%d/%m/%Y %H:%M:%S"),
                            "last_modified": event.last_modified.strftime(
                                "%d/%m/%Y %H:%M:%S"
                            ),
                            "start": event.begin.strftime("%d/%m/%Y %H:%M:%S"),
                            "end": event.end.strftime("%d/%m/%Y %H:%M:%S"),
                            "id": (f"{self.msg_id}-{self.part['filename']}-"
                            f"{hashlib.sha256(self.file_data).hexdigest()}")
                        }
                    )
                )
        except (FileNotFoundError, OSError, ValueError) as e:
            logger.error("Error loading calendar: %s", str(e))
        return documents


LOADER_MAP = {
    '.csv': CSVLoader,
    '.xlsx': UnstructuredExcelLoader,
    '.jpg': ImageLoader,
    '.png': ImageLoader,
    '.doc': Docx2txtLoader,
    '.docx': UnstructuredWordDocumentLoader,
    '.ppt': UnstructuredPowerPointLoader,
    '.pptx': UnstructuredPowerPointLoader,
    '.md': UnstructuredMarkdownLoader,
    '.txt': TextLoader,
    '.pdf': PDFLoader,
    '.msg': OutlookMessageLoader,
    '.eml': UnstructuredEmailLoader,
    '.html': BSHTMLLoader,
    '.ics': CalendarLoader,
}

class FileHandler:  # pylint: disable=too-few-public-methods
    """
    FileHandler is responsible for managing file operations within a session-specific directory.

    Attributes:
        session_id (str): Unique identifier for the session.
        folder_path (str): Path to the session-specific folder.

    Methods:
        __init__(session_id: str):
            Initializes the FileHandler with a session ID and ensures the session folder exists.

        process(file_path):
            Processes the given file by determining its extension,
            validating its existence and support,
            and loading it using the appropriate loader class from LOADER_MAP.
            Logs relevant information and errors.
            Returns the loaded data or an empty list if an error occurs.
    """
    def __init__(self, path: str = None):
        """
        Initializes a new instance with the given session directory.

        Args:
            session_dir (str): The path to the session-specific directory.
            path (str, optional): The path to the file to be processed.

        Creates a folder for the session if it does not already exist.
        """
        self.path = path

    def process(self):
        """
        Processes the given file by determining its extension, validating its existence and support,
        and loading its contents using the appropriate loader.

        Args:
            file_path (str): The path to the file to be processed.

        Returns:
            list: The loaded contents of the file, or an empty list if an error occurs.

        Raises:
            FileNotFoundError: If the file does not exist or is not accessible.
            ValueError: If the file extension is not supported.
            requests.RequestException: If a request-related error occurs during loading.

        Logs:
            Logs information about the loading process and any errors encountered.
        """
        try:
            file_extension = os.path.splitext(self.path)[1].lower() \
                if os.path.exists(self.path) else None

            if not file_extension or not os.path.exists(self.path):
                raise FileNotFoundError(f"File {self.path} does not exist or is not accessible")

            if file_extension not in LOADER_MAP:
                raise ValueError(f"Unsupported file extension: {file_extension}")

            loader_class = LOADER_MAP[file_extension]
            loader = loader_class(self.path)
            documents = loader.load()
            return documents

        except (FileNotFoundError, ValueError, requests.RequestException) as e:
            logger.error("Error loading file %s: %s", self.path, str(e))
            return []
