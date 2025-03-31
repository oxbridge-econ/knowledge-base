"""Module for defining the main routes of the API."""
import os
import pickle
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from controllers import mail
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

router = APIRouter(prefix="/mail", tags=["mail"])

@router.post("")
def collect(email: str, request: Request):
    """
    Handles the chat POST request.

    Args:
        query (ReqData): The request data containing the query parameters.

    Returns:
        str: The generated response from the chat function.
    """
    if os.path.exists(f"{email}.pickle"):
        with open(f"{email}.pickle", "rb") as token:
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
    mail.collect(mailservice)
    return JSONResponse(content={"message": "Mail collected successfully."})

# @router.get("")
# def get():
#     """
#     Handles the chat POST request.

#     Args:
#         query (ReqData): The request data containing the query parameters.

#     Returns:
#         str: The generated response from the chat function.
#     """
#     # result = mail.get()
#     return JSONResponse(content= result)
