FROM python:3.12-slim

WORKDIR /app

COPY server.py client.py ./

# Create mount points
RUN mkdir -p /app/site /app/downloads

EXPOSE 8080

CMD ["python", "server.py", "/app/site", "8080"]


