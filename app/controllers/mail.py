"""Module to search and list emails from Gmail."""
import os
import re
import base64
from datetime import datetime, timedelta
from venv import logger
from ics import Calendar

from langchain_core.documents import Document
from langchain_community.document_loaders import (
    PyPDFLoader,
    UnstructuredExcelLoader,
    CSVLoader,
    UnstructuredImageLoader,
)

from models.db import vectorstore

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
EMAIL_PATTERN = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"

ATTACHMENTS_DIR = "cache"
os.makedirs(ATTACHMENTS_DIR, exist_ok=True)

# service = build_gmail_service()
def search_emails(service, query):
    """Search emails based on a query."""
    result = service.users().messages().list(userId="me", q=query).execute()
    messages = []
    if "messages" in result:
        messages.extend(result["messages"])
    while "nextPageToken" in result:
        page_token = result["nextPageToken"]
        result = (
            service.users().messages().list(userId="me", q=query, pageToken=page_token).execute()
        )
        if "messages" in result:
            messages.extend(result["messages"])
    return messages


def list_emails(service, messages):
    """
    Processes a list of email messages, extracts metadata, decodes content, and handles attachments.

    Args:
        messages (list): A list of email message dictionaries, where each dictionary contains
                        at least an 'id' key representing the email's unique identifier.

    Returns:
        None: The function processes the emails and adds the extracted documents to a vector store.

    Functionality:
        - Retrieves email details using the Gmail API.
        - Extracts metadata such as sender, recipient, subject, CC, and date.
        - Decodes email content in plain text or HTML format.
        - Handles multipart emails, including attachments.
        - Processes attachments based on their MIME type:
            - PDF files are loaded using PyPDFLoader.
            - Images (PNG, JPEG) are loaded using UnstructuredImageLoader.
            - CSV files are loaded using CSVLoader.
            - Excel files are loaded using UnstructuredExcelLoader.
            - Calendar files (ICS) are parsed to extract event details.
        - Removes HTML tags from email content.
        - Stores processed documents and metadata in a vector store.
        - Deletes temporary files created during attachment processing.

    Notes:
        - The function assumes the existence of a global `service` object for Gmail API.
        - The `vectorstore.add_documents` method is used to store the processed documents.
        - Attachments are temporarily saved in `ATTACHMENTS_DIR` and deleted after processing.
        - The function logs information about attachments being downloaded.
    """
    ids = []
    documents = []
    for message in messages:
        msg = service.users().messages().get(userId="me", id=message["id"], format="full").execute()
        metadata = {}
        logger.info("vectorstore.index_to_docstore_id: %s", vectorstore.index_to_docstore_id)
        logger.info("type: %s", type(vectorstore.index_to_docstore_id))
        if msg["id"] in vectorstore.index_to_docstore_id:
            logger.info("Email already exists in the database.")
            continue
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
        metadata["date"] = datetime.fromtimestamp(int(msg["internalDate"]) / 1000).strftime(
            "%d/%m/%Y %H:%M:%S"
        )
        metadata["user_id"] = service.users().getProfile(userId="me").execute().get("emailAddress")
        metadata["msg_id"] = msg["id"]
        # print(metadata, msg["payload"]["mimeType"])
        ids = []
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
                print("mimeType: ", part["mimeType"])
                mime_types.append(part["mimeType"])
                if part["mimeType"] == "text/plain" and "text/html" not in mime_types:
                    body = base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8")
                    body = re.sub(r"<[^>]+>", "", body)  # Remove HTML tags
                    metadata["mimeType"] = part["mimeType"]
                    documents.append(Document(page_content=body, metadata=metadata))
                    ids.append(msg["id"])
                elif part["mimeType"] == "text/html" and "text/plain" not in mime_types:
                    body = base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8")
                    body = re.sub(r"<[^>]+>", "", body)
                    metadata["mimeType"] = part["mimeType"]
                    documents.append(Document(page_content=body, metadata=metadata))
                    ids.append(msg["id"])
                if part["filename"]:
                    attachment_id = part["body"]["attachmentId"]
                    logger.info("Downloading attachment: %s", part["filename"])
                    attachment = (
                        service.users()
                        .messages()
                        .attachments()
                        .get(userId="me", messageId=message["id"], id=attachment_id)
                        .execute()
                    )
                    file_data = base64.urlsafe_b64decode(attachment["data"].encode("UTF-8"))
                    path = os.path.join(".", ATTACHMENTS_DIR, part["filename"])
                    with open(path, "wb") as f:
                        f.write(file_data)
                    if part["mimeType"] == "application/pdf":
                        attach_docs = PyPDFLoader(path).load()
                    elif part["mimeType"] == "image/png" or part["mimeType"] == "image/jpeg":
                        attach_docs = UnstructuredImageLoader(path).load()
                    elif part["filename"].endswith(".csv"):
                        attach_docs = CSVLoader(path).load()
                    elif (
                        part["mimeType"]
                        == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    ):
                        attach_docs = UnstructuredExcelLoader(path).load()
                    elif part["mimeType"] == "application/ics":
                        with open(path, "r", encoding="utf-8") as f:
                            calendar = Calendar(f.read())
                        for event in calendar.events:
                            documents.append(
                                Document(
                                    page_content=f"Event: {event.name}\n\Description: {event.description}\nStart: {event.begin}\nEnd: {event.end}",
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
                                    },
                                )
                            )
                            ids.append(f"{msg['id']}_{attachment_id}")
                    if os.path.exists(path):
                        os.remove(path)
                    for index, document in enumerate(attach_docs or []):
                        document.metadata["mimeType"] = part["mimeType"]
                        if "page_label" in document.metadata:
                            document.metadata["page"] = document.metadata["page_label"]
                        document.metadata["attachment"] = part["filename"]
                        document.metadata = {
                            key: value
                            for key, value in document.metadata.items()
                            if key in ["attachment", "page"]
                        }
                        document.metadata.update(metadata)
                        documents.append(document)
                        ids.append(f"{msg['id']}_{attachment_id}_{index}")
        elif msg["payload"]["mimeType"] == "text/plain" and "data" in msg["payload"]["body"]:
            body = base64.urlsafe_b64decode(msg["payload"]["body"]["data"]).decode("utf-8")
            body = re.sub(r"<[^>]+>", "", body)
            metadata["mimeType"] = msg["payload"]["mimeType"]
            documents.append(Document(page_content=body, metadata=metadata))
            ids.append(msg["id"])
        elif msg["payload"]["mimeType"] == "text/html" and "data" in msg["payload"]["body"]:
            body = base64.urlsafe_b64decode(msg["payload"]["body"]["data"]).decode("utf-8")
            body = re.sub(r"<[^>]+>", "", body)
            metadata["mimeType"] = msg["payload"]["mimeType"]
            documents.append(Document(page_content=body, metadata=metadata))
            ids.append(msg["id"])
        if "multipart/alternative" in mime_types and len(mime_types) == 1:
            print("Only multipart/alternative found in the email.")
        else:
            vectorstore.add_documents(documents=documents, ids=ids)


def collect(service, query=(datetime.today() - timedelta(days=10)).strftime("after:%Y/%m/%d")):
    """
    Main function to search and list emails from Gmail.

    This function builds a Gmail service, constructs a query to search for emails
    received in the last 14 days, and lists the found emails. If no emails are found,
    it prints a message indicating so.

    Returns:
        None
    """
    # query = "subject:Re: Smartcareers algorithm debug and improvement'"
    emails = search_emails(service, query)
    if emails:
        logger.info("Found %d emails:\n", len(emails))
        logger.info("Found %d emails after two_weeks_ago:\n", len(emails))
        list_emails(service, emails)
        logger.info("Listing emails...")
        return f"{len(emails)} emails added to the collection."
    else:
        logger.info("No emails found after two weeks ago.")
