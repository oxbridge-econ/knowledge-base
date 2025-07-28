#!/bin/bash

# Install system dependencies
apt-get update && apt-get install -y libgl1-mesa-glx tesseract-ocr poppler-utils

# Start Gunicorn server
exec gunicorn -w 2 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000 main:app
