# Use the official Python 3.10.9 image
FROM python:3.10.9

# Copy the current directory contents into the container at /app
COPY . .

# Set the working directory to /app
WORKDIR /app

# Create a cache directory and set permissions
RUN mkdir -p /app/cache && chmod -R 777 /app/cache

# Install requirements.txt
RUN pip install --no-cache-dir --upgrade -r requirements.txt

EXPOSE 7860

# Start the FastAPI app on port 7860
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]