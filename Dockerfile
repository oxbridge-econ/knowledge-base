# Use the official Python 3.10.9 image
FROM python:3.10.9

# Install dependencies for building SQLite
RUN apt-get update && apt-get install -y \
    build-essential \
    wget \
    libsqlite3-dev \
    && rm -rf /var/lib/apt/lists/*

# Install SQLite 3.35.0 or higher from source
RUN wget https://www.sqlite.org/2025/sqlite-autoconf-3410000.tar.gz && \
    tar -xzf sqlite-autoconf-3410000.tar.gz && \
    cd sqlite-autoconf-3410000 && \
    ./configure && \
    make && \
    make install && \
    cd .. && \
    rm -rf sqlite-autoconf-3410000 sqlite-autoconf-3410000.tar.gz

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