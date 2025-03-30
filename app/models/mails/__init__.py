"""Module to build and return a Gmail API service instance."""
import os.path
import pickle

from google.auth.transport.requests import Request
# from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build


SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def build_gmail_service():
    """
    Builds and returns a Gmail API service instance.

    This function performs the following steps:
    1. Checks if the token.pickle file exists, which contains the user's credentials.
    2. If the token.pickle file exists, loads the credentials from the file.
    3. If the credentials are invalid or do not exist,
    initiates the OAuth2 flow to obtain new credentials.
    4. Saves the new credentials to the token.pickle file for future use.
    5. Builds and returns the Gmail API service instance using the credentials.

    Returns:
        googleapiclient.discovery.Resource: An authorized Gmail API service instance.
    """
    creds = None
    if os.path.exists("token.pickle"):
        with open("token.pickle", "rb") as token:
            creds = pickle.load(token)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            client_config = {
                "installed": {
                    "client_id": "44087493702-4sa7lp3gpt36bir2vaqopp0gtaq8760j.apps.googleusercontent.com",
                    "project_id": "login-system-447114",
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                    "client_secret": os.getenv("CLIENT_SECRET"),
                    "redirect_uris": ["http://localhost"],
                }
            }
            flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
            # flow = InstalledAppFlow.from_client_secrets_file("./credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)

        with open("token.pickle", "wb") as token:
            pickle.dump(creds, token)
        # with open("token.json", "wb") as token:
        #     token.write(creds.to_json().encode())
        # creds = Credentials.from_authorized_user_file("token.json")
    service = build("gmail", "v1", credentials=creds)
    return service
