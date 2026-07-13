# Use the official Python image from the Docker Hub
FROM python:3.12-slim

# Set the working directory
WORKDIR /

# Copy the www directory into the image (optional, since you're mounting it)
COPY www-default /www

# Expose the port the server will run on
EXPOSE 8000

# Command to run the Python HTTP server
# CMD ["python", "-m", "http.server", "8000", "--directory", "/www"]
# Auto refresh new content
CMD ["sh", "-c", "while true; do inotifywait -e modify,create,delete,move /www; python -m http.server 8000 --directory /www; done"]
