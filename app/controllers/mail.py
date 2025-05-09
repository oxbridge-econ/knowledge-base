"""Module to search and list emails from Gmail."""
import base64
import hashlib
import os
import re
from datetime import datetime, timedelta
from venv import logger

from ics import Calendar
from langchain_community.document_loaders import (
    CSVLoader,
    PyPDFLoader,
    UnstructuredExcelLoader,
    UnstructuredImageLoader,
)
from langchain_core.documents import Document
from models.db import vectorstore

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
EMAIL_PATTERN = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"

ATTACHMENTS_DIR = "cache"
os.makedirs(ATTACHMENTS_DIR, exist_ok=True)

def build_query(params):
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
        query_parts.append(f'subject:"{params["subject"]}"')
    if 'from' in params and params['from']:
        query_parts.append(f'from:{params["from"]}')
    if 'to' in params and params['to']:
        query_parts.append(f'to:{params["to"]}')
    if 'cc' in params and params['cc']:
        query_parts.append(f'cc:{params["cc"]}')
    if 'after' in params and params['after']:
        query_parts.append(f'after:{params["after"]}')
    if 'before' in params and params['before']:
        query_parts.append(f'before:{params["before"]}')
    return ' '.join(query_parts)

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
        metadata["threadId"] = msg["threadId"]
        metadata["msgId"] = msg["id"]
        msgId = f"{msg['threadId']}-{msg['id']}"
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
        metadata["userId"] = service.users().getProfile(userId="me").execute().get("emailAddress")
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
                        try:
                            attach_docs = UnstructuredImageLoader(path).load()
                        except Exception as e:
                            logger.error("Error loading image: %s", e)
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
                            ids.append(f"{msgId}-{part['filename']}-{hashlib.sha256(file_data).hexdigest()}")
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
                        ids.append(f"{msgId}-{hashlib.sha256(file_data).hexdigest()}-{index}")
        elif msg["payload"]["mimeType"] == "text/plain" and "data" in msg["payload"]["body"]:
            body = base64.urlsafe_b64decode(msg["payload"]["body"]["data"]).decode("utf-8")
            body = re.sub(r"<[^>]+>", "", body)
            metadata["mimeType"] = msg["payload"]["mimeType"]
            documents.append(Document(page_content=body, metadata=metadata))
            ids.append(msgId)
        elif msg["payload"]["mimeType"] == "text/html" and "data" in msg["payload"]["body"]:
            body = base64.urlsafe_b64decode(msg["payload"]["body"]["data"]).decode("utf-8")
            body = re.sub(r"<[^>]+>", "", body)
            metadata["mimeType"] = msg["payload"]["mimeType"]
            documents.append(Document(page_content=body, metadata=metadata))
            ids.append(msgId)
        if "multipart/alternative" in mime_types and len(mime_types) == 1:
            print("Only multipart/alternative found in the email.")
        else:
            try:
                vectorstore.add_documents(documents=documents, ids=ids)
            except Exception as e:
                logger.error("Error adding documents to vectorstore: %s", e)


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


def get_emails(service, query, max_results=10):
    """
    Retrieve a list of emails with subject, to, from, cc, and content.
    
    Args:
        mailservice: Authenticated Gmail API service instance
        max_results: Maximum number of emails to retrieve
    
    Returns:
        List of dictionaries containing email details
    """
    try:
        # List messages
        query = build_query(query.dict())
        response = service.users().messages().list(
            userId='me', q=query, maxResults=max_results).execute()
        messages = response.get('messages', [])
        email_list = []
        if not messages:
            return email_list
        for message in messages:
            msg = service.users().messages().get(userId='me', id=message['id'], format='full').execute()
            headers = msg['payload']['headers']
            email_data = {
                'subject': '',
                'from': '',
                'to': '',
                'cc': '',
                'content': '',
                'snippet': msg['snippet'] if 'snippet' in msg else '',
            }
            for header in headers:
                name = header['name'].lower()
                if name == 'subject':
                    email_data['subject'] = header['value']
                elif name == 'from':
                    email_data['from'] = header['value']
                elif name == 'to':
                    email_data['to'] = header['value']
                elif name == 'cc':
                    email_data['cc'] = header['value']
            if 'parts' in msg['payload']:
                for part in msg['payload']['parts']:
                    if part['mimeType'] == 'text/plain':
                        email_data['content'] = base64.urlsafe_b64decode(part['body']['data']).decode('utf-8')
                        break
                    elif part['mimeType'] == 'text/html':
                        email_data['content'] = base64.urlsafe_b64decode(part['body']['data']).decode('utf-8')
                        break
            elif 'data' in msg['payload']['body']:
                email_data['content'] = base64.urlsafe_b64decode(msg['payload']['body']['data']).decode('utf-8')
            email_list.append(email_data)
        return email_list

    except Exception as e:
        print(f"An error occurred: {e}")
        return []
