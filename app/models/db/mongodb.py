"""MongoDB database interaction module."""
import os
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

MongodbClient = MongoClient(os.getenv('MONGODB_URL'))
