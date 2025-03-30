# Use the official Python 3.10.9 image
FROM python:3.10.9

RUN apt-get update && \
    apt-get install -y sqlite3 libsqlite3-dev && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Verify SQLite3 installation
RUN sqlite3 --version

# Verify SQLite version
RUN sqlite3 --version

# Copy the current directory contents into the container at /app
COPY . .

# Set the working directory to /app
WORKDIR /app

# Install requirements.txt
RUN pip install --no-cache-dir --upgrade -r requirements.txt

EXPOSE 7860

# Start the FastAPI app on port 7860
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]