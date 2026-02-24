# Draping Tailoring Measurement App

This is a Python Flask web application for managing tailoring measurements, customer details, dress types, and measurement parameters. The app uses SQLite as the database and is designed for deployment as a web app, accessible on mobile and desktop devices.

## Features
- CRUD for Customers, Dress Types, Measurement Parameters
- Auto Job Number for each order
- Multiple dress types per job
- Measurement entry with unit conversion (inches/cm)
- Image and voice upload
- PDF generation for job details (with images)
- Search and history for customers
- Bulk upload/download via Excel templates

## Getting Started

1. Install Python 3.8+
2. Create a virtual environment:
   ```
   python -m venv venv
   ```
3. Activate the virtual environment:
   - Windows:
     ```
     venv\Scripts\activate
     ```
   - Mac/Linux:
     ```
     source venv/bin/activate
     ```
4. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
5. Run the app:
   ```
   python app.py
   ```
6. Access the app at http://localhost:5000

## Folder Structure
- app.py: Main Flask app
- models.py: Database models
- templates/: HTML templates
- static/: CSS, JS, images
- uploads/: Uploaded images and voice files
- requirements.txt: Python dependencies

## Deployment

This app is a standard Flask application. For 2–3 people and low traffic, the simplest reliable deployment is a small VPS (Ubuntu) running:
- **Gunicorn** (Python WSGI server)
- **Nginx** (reverse proxy + HTTPS)
- **SQLite** (OK for low traffic if you run a single Gunicorn worker) OR **PostgreSQL** (more robust)

### Recommended: VPS (Ubuntu) + Nginx + Gunicorn

#### 1) Copy code to the server
On the server:
```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip nginx

sudo mkdir -p /var/www/draping
sudo chown -R $USER:$USER /var/www/draping
```

Upload/copy your project into `/var/www/draping` so it contains `app.py`, `templates/`, `static/`, etc.

#### 2) Create a virtualenv and install dependencies
```bash
cd /var/www/draping
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

#### 3) Configure environment variables
Create a `.env` file in `/var/www/draping`:
```bash
SECRET_KEY="put-a-long-random-string-here"

# Option A (simple): SQLite
SQLALCHEMY_DATABASE_URI="sqlite:///draping.db"

# Option B (recommended for more safety): PostgreSQL
# DATABASE_URL="postgresql://user:pass@host:5432/dbname"

# Uploads path (keep this persistent)
UPLOAD_FOLDER="/var/www/draping/uploads"
```

Notes:
- If you keep **SQLite**, run Gunicorn with **one worker** to reduce DB locking issues.
- If you use **PostgreSQL**, you can safely run multiple workers.

#### 4) Run with Gunicorn
From `/var/www/draping`:
```bash
source .venv/bin/activate
gunicorn -w 1 -b 127.0.0.1:8000 app:app
```

If you are using PostgreSQL, you can use more workers, e.g. `-w 2`.

#### 5) Systemd service (auto start)
Create `/etc/systemd/system/draping.service`:
```ini
[Unit]
Description=Draping Flask App
After=network.target

[Service]
User=www-data
Group=www-data
WorkingDirectory=/var/www/draping
Environment="PATH=/var/www/draping/.venv/bin"
ExecStart=/var/www/draping/.venv/bin/gunicorn -w 1 -b 127.0.0.1:8000 app:app
Restart=always

[Install]
WantedBy=multi-user.target
```

Then:
```bash
sudo chown -R www-data:www-data /var/www/draping
sudo systemctl daemon-reload
sudo systemctl enable --now draping
sudo systemctl status draping
```

#### 6) Nginx reverse proxy + HTTPS
Create `/etc/nginx/sites-available/draping`:
```nginx
server {
   listen 80;
   server_name your-domain.com;

   client_max_body_size 20M;

   location / {
      proxy_pass http://127.0.0.1:8000;
      proxy_set_header Host $host;
      proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
      proxy_set_header X-Forwarded-Proto $scheme;
   }
}
```

Enable it:
```bash
sudo ln -s /etc/nginx/sites-available/draping /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

For HTTPS, install Certbot:
```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com
```

### Alternative: Managed platforms (Render / Railway / Fly.io)
These are easier (no server maintenance) but you must ensure persistence:
- Use **PostgreSQL** (recommended)
- Store uploads in persistent disk volume or S3/R2
- Start command: `gunicorn -w 2 -b 0.0.0.0:$PORT app:app` (platform sets `$PORT`)

### Backups (important)
- If using SQLite: back up the DB file regularly (and the `uploads/` folder).
- If using PostgreSQL: use daily DB dumps + upload backups.

## To Do
- Job management and tailor assignment (future)

---

For any issues or feature requests, contact the developer.
