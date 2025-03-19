"""Module to search and list emails from Gmail."""
import base64
from datetime import datetime, timedelta
import pandas as pd
from langchain_core.documents import Document

from venv import logger
from models.mails import build_gmail_service
from models.chroma import vectorstore

SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']
EMAIL_PATTERN = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'

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
    """List emails from the search results."""
    ids = []
    documents = []
    for message in messages[:50]:
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
        if 'parts' in msg['payload']:
            body = ''.join(
                part['body']['data'] for part in msg['payload']['parts'] if 'data' in part['body']
            )
            body = base64.urlsafe_b64decode(body).decode('utf-8')
        else:
            body = base64.urlsafe_b64decode(msg['payload']['body']['data']).decode('utf-8')
        ids.append(msg['id'])
        documents.append(Document(
            page_content=body,
            metadata=metadata
        ))
    return vectorstore.add_documents(documents= documents, ids = ids)

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
        logger.info("Found %d emails after two_weeks_ago:\n", len(emails))
        return f"{len(list_emails(emails))} emails added to the collection."
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
    df = pd.concat(
        [df.drop('metadatas', axis=1), df['metadatas'].apply(pd.Series)],
        axis=1).to_csv('collection_data.csv', index=False)
