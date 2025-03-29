"""Module to search and list emails from Gmail."""
import os
import re
import base64
from datetime import datetime, timedelta
from venv import logger

import pandas as pd
from langchain_core.documents import Document
from langchain_community.document_loaders import PyPDFLoader
from langchain_community.document_loaders.image import UnstructuredImageLoader
from langchain_community.document_loaders.csv_loader import CSVLoader

from models.chroma import vectorstore
from models.mails import build_gmail_service

SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']
EMAIL_PATTERN = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'

ATTACHMENTS_DIR = "attachments"
os.makedirs(ATTACHMENTS_DIR, exist_ok=True)

service = build_gmail_service()

def search_emails(query):
    """Search emails based on a query."""
    result = service.users().messages().list(userId='me', q=query).execute()
    messages = []
    if 'messages' in result:
        messages.extend(result['messages'])
    while 'nextPageToken' in result:
        page_token = result['nextPageToken']
        result = service.users().messages().list(
            userId='me', q=query, pageToken=page_token).execute()
        if 'messages' in result:
            messages.extend(result['messages'])
    return messages

def list_emails(messages):
    """List emails from the search results and download attachments."""
    ids = []
    documents = []
    for message in messages:
        msg = service.users().messages().get(userId='me', id=message['id'], format='full').execute()
        metadata = {}
        for header in msg['payload']['headers']:
            if header['name'] == 'From':
                metadata['from'] = header['value']
            elif header['name'] == 'To':
                metadata['to'] = header['value']
            elif header['name'] == 'Subject':
                metadata['subject'] = header['value']
            elif header['name'] == 'Cc':
                metadata['cc'] = header['value']
        metadata['date'] = datetime.fromtimestamp(
            int(msg['internalDate']) / 1000).strftime("%d/%m/%Y %H:%M:%S")
        print.info(metadata, msg['id'])
        print("-"*100)
        body = ""
        if 'parts' in msg['payload']:
            attachment_documents = []
            for part in msg['payload']['parts']:
                if part['filename']:
                    attachment_id = part['body']['attachmentId']
                    logger.info("Downloading attachment: %s", part['filename'])
                    attachment = service.users().messages().attachments().get(
                        userId='me', messageId=message['id'], id=attachment_id).execute()
                    file_data = base64.urlsafe_b64decode(attachment['data'].encode('UTF-8'))
                    path = os.path.join(".", ATTACHMENTS_DIR, part['filename'])
                    with open(path, 'wb') as f:
                        f.write(file_data)
                    if part['filename'].endswith('.pdf'):
                        attachment_documents = attachment_documents + PyPDFLoader(path).load()
                    if part['filename'].endswith('.png'):
                        attachment_documents = attachment_documents + UnstructuredImageLoader(path).load()
                    if part['filename'].endswith('.csv'):
                        attachment_documents = attachment_documents + CSVLoader(path).load()
            ids = []
            documents = []
            for index, document in enumerate(attachment_documents):
                _id = f"{msg['id']}_{index}"
                if 'source' in document.metadata:
                    document.metadata['source'] = document.metadata['source'].replace(f"./{ATTACHMENTS_DIR}/", "")
                print(document.metadata)
                document.metadata.update(metadata)
                print(document.metadata)
                ids.append(_id)
                print(_id)
                print("*"*100)
                vectorstore.add_documents(documents=documents, ids=ids)
        else:
            ids = []
            documents = []
            body = base64.urlsafe_b64decode(msg['payload']['body']['data']).decode('utf-8')
            body = re.sub(r'<[^>]+>', '', body)  # Remove HTML tags
            documents.append(Document(
                page_content=body,
                metadata=metadata
            ))
            ids.append(msg['id'])
            print(msg['id'])
            print("!"*100)
            vectorstore.add_documents(documents=documents, ids=ids)

def collect(query = (datetime.today() - timedelta(days=21)).strftime('after:%Y/%m/%d')):
    """
    Main function to search and list emails from Gmail.

    This function builds a Gmail service, constructs a query to search for emails
    received in the last 14 days, and lists the found emails. If no emails are found,
    it prints a message indicating so.

    Returns:
        None
    """
    emails = search_emails(query)
    if emails:
        print("Found %d emails:\n", len(emails))
        logger.info("Found %d emails after two_weeks_ago:\n", len(emails))
        return f"{len(emails)} emails added to the collection."
    else:
        logger.info("No emails found after two weeks ago.")

def get_documents():
    """
    Main function to list emails from the database.

    This function lists all emails stored in the database.

    Returns:
        None
    """
    data = vectorstore.get()
    df = pd.DataFrame({
        'ids': data['ids'],
        'documents': data['documents'],
        'metadatas': data['metadatas']
    })
    df.to_excel('collection_data.xlsx', index=False)
    df = pd.concat(
        [df.drop('metadatas', axis=1), df['metadatas'].apply(pd.Series)],
        axis=1).to_excel('collection_data_expand.xlsx', index=False)
