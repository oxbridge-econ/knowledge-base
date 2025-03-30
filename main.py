"""Module to handle the main FastAPI application and its endpoints."""
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from router import content, mail


app = FastAPI(docs_url="/")

app.include_router(content.router, tags=["content"])
app.include_router(mail.router, tags=["mail"])

origins = [
    "*"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials = True,
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(funcName)s - %(message)s')
logging.getLogger().setLevel(logging.ERROR)


@app.get("/_health")
def health():
    """
    Returns the health status of the application.

    :return: A string "OK" indicating the health status.
    """
    return "OK"
