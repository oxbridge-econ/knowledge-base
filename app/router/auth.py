"""Module for defining the main routes of the API."""
import os
import json
import pickle
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

router = APIRouter(tags=["auth"])

CLIENT_ID = os.environ.get("CLIENT_ID")
CLIENT_SECRET = os.environ.get("CLIENT_SECRET")
REDIRECT_URI = os.environ.get("REDIRECT_URI")

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

# Client config for OAuth flow
CLIENT_CONFIG = {
    "web": {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uris": [REDIRECT_URI],
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
}

@router.get("/auth/google/url")
async def get_auth_url():
    """
    Handles the generation of a Google OAuth 2.0 authorization URL.

    This endpoint initializes an OAuth 2.0 flow using the provided client configuration
    and scopes, sets the redirect URI, and generates an authorization URL for the user
    to grant access.

    Returns:
        dict: A dictionary containing the generated authorization URL under the key "url".
    """
    flow = InstalledAppFlow.from_client_config(CLIENT_CONFIG, SCOPES)
    flow.redirect_uri = REDIRECT_URI
    auth_url, _ = flow.authorization_url(access_type="offline", prompt="consent")
    return JSONResponse({"url": auth_url})

@router.get("/auth/google/callback")
async def google_callback(code: str, request: Request):
    flow = InstalledAppFlow.from_client_config(CLIENT_CONFIG, SCOPES)
    flow.redirect_uri = REDIRECT_URI
    flow.fetch_token(code=code)
    credentials = flow.credentials
    request.state.session["credential"] = json.loads(credentials.to_json())
    # cred_dict = (request.state.session.get("credential"))
    # cred = Credentials(
    #     token=cred_dict["token"],
    #     refresh_token=cred_dict["refresh_token"],
    #     token_uri=cred_dict["token_uri"],
    #     client_id=cred_dict["client_id"],
    #     client_secret=cred_dict["client_secret"],
    #     scopes=cred_dict["scopes"],
    # )
    # service = build("gmail", "v1", credentials=Credentials(
    #     token=cred_dict["token"],
    #     refresh_token=cred_dict["refresh_token"],
    #     token_uri=cred_dict["token_uri"],
    #     client_id=cred_dict["client_id"],
    #     client_secret=cred_dict["client_secret"],
    #     scopes=cred_dict["scopes"],
    # ))
    service = build("gmail", "v1", credentials=credentials)
    profile = service.users().getProfile(userId="me").execute()
    print(({"profile": profile}))
    with open(f"{profile['emailAddress']}.pickle", "wb") as token:
        pickle.dump(credentials, token)
    return JSONResponse(profile)
