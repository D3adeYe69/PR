## Chirtoaca Liviu — Lab 1 Report: HTTP File Server 

This report documents a simple HTTP file server and client implemented with raw TCP sockets in Python. The project is containerized with Docker Compose so it can be run consistently anywhere.

### Project Structure
```
project/
├── server.py              # Main HTTP server
├── client.py              # HTTP client
├── Dockerfile             # Docker image definition
├── docker-compose.yml     # Docker Compose configuration
└── site/                  # Directory to be served (mount from host)
    ├── index.html         # Main page (optional; if missing, a listing is shown)
    ├── image.png          # Image file (optional)
    ├── books/             # Nested directory with PDFs/PNGs
    │   └── sample.pdf
    │    └── Lab1.pdf
    │    └── Lab2_CS.pdf
   
```

### What the Project Does
- Serves files from a chosen directory (`site/`) over HTTP on port 8080
- Correctly handles and serves HTML, PNG, and PDF files
- If a directory path is requested and it has no `index.html`, the server generates an HTML directory listing with hyperlinks
- Handles one HTTP request per connection (intentionally simple)
- Includes a client that:
  - Prints HTML responses (pages or directory listings)
  - Saves PNG/PDF files to a specified directory

### How to Set Up
- Prerequisite: Install and start Docker Desktop
- Put your content (HTML, PNG, PDFs, and optional subdirectories like `books/`) into the `site/` folder

### Start the Server
```bash
docker compose up --build server
```
Open in browser: `http://localhost:8080/`

Notes:
- If you request a directory without an `index.html`, you’ll see an auto-generated listing.
- If you update files but see old content, hard refresh (Ctrl+F5).

### Use the Client
Client command format:
```bash
python client.py <server_host> <server_port> <url_path> <save_directory>
```
Run via Docker Compose (entrypoint already runs `python client.py`):
```bash
docker compose run --rm client server 8080 / ./downloads
```
Behavior:
- HTML (page or directory listing): printed to stdout
- PNG/PDF: saved to the host folder you pass as the last argument

Examples:
```bash
# Print the root page (HTML)
docker compose run --rm client server 8080 / ./downloads

# Save a PNG
docker compose run --rm client server 8080 /image.png ./downloads


# Save a PDF from a nested folder
docker compose run --rm client server 8080 /books/sample.pdf ./downloads
```
Where downloads appear:
- The final argument (e.g., `./downloads`) is a host path relative to this project; files will show up in that folder on your machine.

### Requirements
- HTTP server with raw TCP sockets: implemented in `server.py`
- Supports HTML, PNG, PDF; unknown types → 404: implemented
- Nested directories and directory listing with links: implemented for any folder without `index.html`
- HTTP client with specified args, prints HTML or saves PNG/PDF: implemented in `client.py`
- Docker Compose usage: implemented (`server` and `client` services)


### Troubleshooting
- Seeing old content: hard refresh (Ctrl+F5) or add `?t=1` to the URL
- 404 for a file: check exact filename and that it’s inside `site/`
- Want a directory listing: ensure that folder does not contain an `index.html`
- Clean rebuild:
```bash
docker compose down
docker compose build --no-cache --pull server
docker compose up server
```

### Stop and Clean Up
```bash
docker compose down -v
```

### Conclusion
This project fulfills the lab requirements:
- A raw TCP HTTP server serving HTML/PNG/PDF and generating directory listings
- A client that prints HTML and saves PNG/PDF based on content type
- Support for nested directories and safe path resolution
- Fully Dockerized with a Compose workflow for reproducible runs
