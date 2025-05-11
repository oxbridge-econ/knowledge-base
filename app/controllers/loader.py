"""Module to extract text from PDF files and images using Azure OpenAI's GPT-4o-mini model."""
import base64
import hashlib
import json
import os
from io import BytesIO

from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import Docx2txtLoader
from langchain_core.documents import Document
from pdf2image import convert_from_path
from pydantic import BaseModel
from pypdf import PdfReader

from models.llm import client
from models.db import vectorstore

text_splitter = RecursiveCharacterTextSplitter()

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
        model="gpt-4o-mini",
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

def load_pdf(content: bytes, filename: str):
    """
    Loads and processes PDF files from a specified directory.

    This function iterates through all PDF files in the given directory, extracts text
    from each page, and creates a list of Document objects containing the extracted text
    and metadata. If a page contains an image, the text is extracted from the image using
    OCR.

    Args:
        directory (str): The path to the directory containing the PDF files.

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
            documents.append(doc.model_dump())
        os.remove(path)
        return documents
    except (FileNotFoundError, ValueError, OSError) as e:
        print(f"Error: {str(e)}")
        return documents

def load_jsonl(directory):
    """
    Reads a JSONL file and converts its content into a list of Document objects.

    Args:
        path (str): Path to the JSONL file.

    Returns:
        list: A list of Document objects.
    """
    for filename in os.listdir(directory):
        if filename.endswith(".pdf"):
            documents = []
            file_path = os.path.join(directory, filename)
            with open(file_path, "r", encoding="utf-8") as file:
                for line in file:
                    # Parse each line as JSON
                    json_obj = json.loads(line.strip())
                    metadata = {
                        "id": json_obj.get("id", ""),
                        "url": json_obj.get("url", ""),
                        "title": json_obj.get("title", ""),
                        "ts": json_obj.get("ts", "")
                    }
                    if json_obj.get("mine") == "text/html":
                        text = base64.urlsafe_b64decode(json_obj.get("text", "")).decode("utf-8")
                    else:
                        text = json_obj.get("text", "")
                    doc = Document(page_content=text, metadata=metadata)
                    documents.append(doc)
            documents = []

def load_docx(directory):
    """
    Loads and processes all .docx files from a specified directory.

    This function iterates through the files in the given directory, identifies
    files with a .docx extension, and uses the Docx2txtLoader to load and extract
    their contents. The extracted contents are aggregated into a single list.

    Args:
        directory (str): The path to the directory containing .docx files.

    Returns:
        list: A list containing the contents of all loaded .docx files.
    """
    documents = []
    for filename in os.listdir(directory):
        if filename.endswith(".docx"):
            documents.extend(Docx2txtLoader(file_path=os.path.join(directory, filename)).load())
    upload(documents)
    return documents

def upload(docs):
    """
    Processes a list of documents, splits them into smaller chunks, updates their metadata,
    generates unique IDs for each chunk, and adds them to a vector store.

    Args:
        docs (list): A list of document objects to be processed.

    Metadata Processing:
        - Extracts and updates the "page" metadata if "page_label" exists.
        - Updates the "attachment" metadata by removing the "{FOLDER}/" prefix from the "source".
        - Filters metadata to retain only "attachment" and "page" keys.
        - Generates a unique "id" for each document based on the "attachment" metadata.
        - Constructs unique IDs for each document chunk, incorporating "id", "page", and chunk index.

    Operations:
        - Splits each document into smaller chunks using `text_splitter.split_documents`.
        - Appends processed document chunks and their IDs to the `documents` and `ids` lists.
        - Adds the processed documents and their IDs to the `vector_store`.

    Raises:
        KeyError: If required metadata keys are missing during processing.
    """
    documents = []
    ids = []
    for doc in docs:
        for index, document in enumerate(text_splitter.split_documents([doc])):
            if "page_label" in document.metadata:
                document.metadata["page"] = int(document.metadata["page_label"])
            document.metadata["attachment"] = document.metadata["source"].replace("{FOLDER}/", "")
            document.metadata = {
                key: value
                for key, value in document.metadata.items()
                if key in ["attachment", "page"]
            }
            document.metadata["id"] = str(
                hashlib.sha256(document.metadata['attachment'].encode()).hexdigest())
            if "page" in document.metadata:
                ids.append(f"{document.metadata["id"]}-{document.metadata["page"]}-{index}")
            else:
                ids.append(f"{document.metadata["id"]}-{index}")
            documents.append(document)
    vectorstore.add_documents(documents=documents, ids=ids)
