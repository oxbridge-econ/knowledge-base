#!/bin/bash
set -e

# Create and activate virtual environment (recommended)
python -m venv antenv
source antenv/bin/activate

# Show which Python and pip are being used
echo "Python: $(which python)"
echo "Pip: $(which pip)"

# Install system dependencies
apt-get update && apt-get install -y libtesseract-dev libgl1-mesa-glx tesseract-ocr poppler-utils

# Install Python dependencies
pip install --upgrade pip
pip install -r requirements.txt  # Ensure this includes uvicorn, gunicorn, fastapi etc.
pip install uvicorn gunicorn  # Explicitly install if not in requirements.txt

# Show installed packages for debugging
pip list

# Show which gunicorn and uvicorn will be used
echo "Gunicorn: $(which gunicorn)"
echo "Uvicorn: $(which uvicorn)"

# Start Gunicorn server
exec gunicorn -w 2 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000 main:app
