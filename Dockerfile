# Use the official Python 3.10.9 image
FROM python:3.10.9

# Copy the current directory contents into the container at /app
COPY . .

# Set the working directory to /app
WORKDIR /app

# Create a cache directory and set permissions
RUN mkdir -p /app/cache && chmod -R 777 /app/cache
RUN mkdir -p /app/nltk_data && chmod -R 777 /app/nltk_data

# Install requirements.txt
RUN pip install --no-cache-dir --upgrade -r requirements.txt
# RUN python -c "import nltk; nltk.download('averaged_perceptron_tagger_eng', download_dir='/app/nltk_data'); nltk.download('punkt_tab', download_dir='/app/nltk_data')"

EXPOSE 7860

# Start the FastAPI app on port 7860
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]