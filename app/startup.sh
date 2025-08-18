#!/bin/bash


# Create and activate virtual environment (recommended)
python -m venv antenv
source antenv/bin/activate

# Install Python dependencies
# pip install --upgrade pip
# pip install -r requirements.txt  # Ensure this includes uvicorn, gunicorn, fastapi etc.
# pip install uvicorn gunicorn  # Explicitly install if not in requirements.txt

# Install system dependencies (if needed)
# apt-get update && apt-get install -y \
#     tesseract-ocr \
#     libtesseract-dev \
#     poppler-utils

# Install system dependencies
apt-get update && apt-get install -y libtesseract-dev libgl1-mesa-glx tesseract-ocr poppler-utils

# Install Python dependencies
pip install --upgrade pip
pip install -r requirements.txt  # Ensure this includes uvicorn, gunicorn, fastapi etc.
pip install uvicorn gunicorn  # Explicitly install if not in requirements.txt

# Start Gunicorn server
exec gunicorn -w 2 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000 main:app
