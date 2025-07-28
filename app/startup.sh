#!/bin/bash

# Install system dependencies
apt-get update
apt-get install -y poppler-utils libgl1

# Start your Gunicorn server
gunicorn -w 2 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000 main:app
