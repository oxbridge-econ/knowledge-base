"""Module for defining the main routes of the API."""
import os
import pickle
import threading
from venv import logger
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from controllers import mail
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from schema import MailReqData

router = APIRouter(prefix="/mail", tags=["mail"])

@router.post("")
def collect(query: MailReqData, request: Request):
    """
    Handles the chat POST request.

    Args:
        query (ReqData): The request data containing the query parameters.

    Returns:
        str: The generated response from the chat function.
    """
    try:
        if os.path.exists(f"cache/{query.email}.pickle"):
            with open(f"cache/{query.email}.pickle", "rb") as token:
                credentials = pickle.load(token)
        else:
            cred_dict = request.state.session.get("credential")
            credentials = Credentials(
                token=cred_dict["token"],
                refresh_token=cred_dict["refresh_token"],
                token_uri=cred_dict["token_uri"],
                client_id=cred_dict["client_id"],
                client_secret=cred_dict["client_secret"],
                scopes=cred_dict["scopes"],
            )
        mailservice = build("gmail", "v1", credentials=credentials)
        threading.Thread(target=mail.collect, args=(mailservice, query.query)).start()
        return JSONResponse(content={"message": "Mail collection in progress."})
    except Exception as e:
        logger.error("Error collecting mail: %s", e)
        return JSONResponse(content={"error": str(e)}, status_code=500)

@router.get("")
def get(query: MailReqData, request: Request):
    """
    Handles the chat POST request.

    Args:
        query (ReqData): The request data containing the query parameters.

    Returns:
        str: The generated response from the chat function.
    """
    if os.path.exists(f"cache/{query.email}.pickle"):
            with open(f"cache/{query.email}.pickle", "rb") as token:
                credentials = pickle.load(token)
    else:
        cred_dict = request.state.session.get("credential")
        credentials = Credentials(
            token=cred_dict["token"],
            refresh_token=cred_dict["refresh_token"],
            token_uri=cred_dict["token_uri"],
            client_id=cred_dict["client_id"],
            client_secret=cred_dict["client_secret"],
            scopes=cred_dict["scopes"],
        )
    mailservice = build("gmail", "v1", credentials=credentials)
    result = mail.get_emails(mailservice, query.query)
    return JSONResponse(content= result)
