"""MongoDB database interaction module."""
import os
from pymongo import MongoClient

MongodbClient = MongoClient(os.getenv('MONGODB_URL'))
