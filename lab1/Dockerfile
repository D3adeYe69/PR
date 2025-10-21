FROM python:3.12-slim

WORKDIR /app

# Copy only the lab1 server & client from the parent build context
# When this Dockerfile is built with context `..`, the files are at `lab1/server.py` etc.
COPY lab1/server.py lab1/client.py ./

# Create mount points
RUN mkdir -p /app/site /app/downloads

EXPOSE 8080

CMD ["python", "server.py", "/app/site", "8080"]


