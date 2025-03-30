# Use the official Python 3.10.9 image
FROM python:3.10.9

# Install SQLite
RUN apt-get update && apt-get install -y sqlite3 libsqlite3-dev && rm -rf /var/lib/apt/lists/*

# Copy the current directory contents into the container at .
COPY . .

# Set the working directory to /
WORKDIR /app

# Install requirements.txt 
RUN pip install --no-cache-dir --upgrade -r requirements.txt

EXPOSE 7860

# Start the FastAPI app on port 7860, the default port expected by Spaces
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]
