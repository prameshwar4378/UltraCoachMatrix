# UltraCoachMatrix Deployment Handover

This document records the current secure VPS deployment plan for the UltraCoachMatrix Django application.

## Current Server

- Provider: Contabo VPS
- Hostname pattern: `vmi3387652`
- Public IP: `173.249.33.152`
- OS recommendation: Ubuntu 24.04 LTS
- Application Linux user: `ultracoachmatrix`
- Web server user/group: `www-data`
- Django service name: `ultracoachmatrix`
- Database: PostgreSQL
- Reverse proxy: Nginx
- App server: Gunicorn
- Background jobs: Redis + Celery

Do not deploy or run the Django application as `root`. Use `root` or `sudo` only for OS-level tasks such as package installation, PostgreSQL role/database creation, Nginx config, systemd services, firewall, and SSL.

## Final Folder Structure

The project is deployed under the dedicated Linux user:

```text
/home/ultracoachmatrix/ultracoachmatrix/
    UltraCoachMatrix/     -> cloned Git repository and Django project
    media/                -> production uploads, outside Git repo
    backups/              -> optional database/media backups
    logs/                 -> optional app logs
```

Current Django project path:

```text
/home/ultracoachmatrix/ultracoachmatrix/UltraCoachMatrix
```

Important project files:

```text
/home/ultracoachmatrix/ultracoachmatrix/UltraCoachMatrix/manage.py
/home/ultracoachmatrix/ultracoachmatrix/UltraCoachMatrix/requirements.txt
/home/ultracoachmatrix/ultracoachmatrix/UltraCoachMatrix/.env
/home/ultracoachmatrix/ultracoachmatrix/UltraCoachMatrix/UltraCoachMatrix/
/home/ultracoachmatrix/ultracoachmatrix/UltraCoachMatrix/static/
/home/ultracoachmatrix/ultracoachmatrix/UltraCoachMatrix/staticfiles/
/home/ultracoachmatrix/ultracoachmatrix/UltraCoachMatrix/templates/
```

Production media path:

```text
/home/ultracoachmatrix/ultracoachmatrix/media
```

The repository may also contain a local `media/` directory inside the project. Production must use the external media folder above so `git pull` does not affect uploaded files.

## User Model

Main deployment user:

```text
ultracoachmatrix
```

Switch from root:

```bash
su - ultracoachmatrix
```

Recommended daily login:

```bash
ssh ultracoachmatrix@173.249.33.152
```

The `ultracoachmatrix` user can do normal deployment work:

```bash
git pull
source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py collectstatic
python manage.py createsuperuser
```

Use `sudo` only for system tasks:

```bash
sudo systemctl restart ultracoachmatrix
sudo systemctl restart nginx
sudo nano /etc/nginx/sites-available/ultracoachmatrix
```

Never store real Linux passwords, database passwords, SMTP passwords, or Django secret keys in this handover file.

## Root/Sudo Setup Commands

These tasks require `root` or `sudo`.

Install packages:

```bash
apt update && apt upgrade -y
apt install -y git curl unzip nginx redis-server postgresql postgresql-contrib libpq-dev python3 python3-pip python3-venv python3-dev build-essential libjpeg-dev zlib1g-dev ufw certbot python3-certbot-nginx
```

Ensure the app user has sudo if needed:

```bash
usermod -aG sudo ultracoachmatrix
```

Enable base services:

```bash
systemctl enable postgresql
systemctl enable redis-server
systemctl start postgresql
systemctl start redis-server
```

Create folders:

```bash
mkdir -p /home/ultracoachmatrix/ultracoachmatrix/media
mkdir -p /home/ultracoachmatrix/ultracoachmatrix/backups
mkdir -p /home/ultracoachmatrix/ultracoachmatrix/logs
```

Set ownership and permissions:

```bash
chown -R ultracoachmatrix:ultracoachmatrix /home/ultracoachmatrix/ultracoachmatrix
chown -R ultracoachmatrix:www-data /home/ultracoachmatrix/ultracoachmatrix/media
chmod 755 /home
chmod 755 /home/ultracoachmatrix
chmod 755 /home/ultracoachmatrix/ultracoachmatrix
chmod -R 775 /home/ultracoachmatrix/ultracoachmatrix/media
chmod -R 750 /home/ultracoachmatrix/ultracoachmatrix/backups
chmod -R 750 /home/ultracoachmatrix/ultracoachmatrix/logs
```

## PostgreSQL

Database:

```text
ultracoachmatrix
```

Database user:

```text
dbultracoachmatrix
```

Create database and role as root:

```bash
sudo -u postgres psql
```

SQL:

```sql
CREATE DATABASE ultracoachmatrix;
CREATE USER dbultracoachmatrix WITH PASSWORD 'CHANGE_THIS_STRONG_PASSWORD';

ALTER ROLE dbultracoachmatrix SET client_encoding TO 'utf8';
ALTER ROLE dbultracoachmatrix SET default_transaction_isolation TO 'read committed';
ALTER ROLE dbultracoachmatrix SET timezone TO 'Asia/Kolkata';

GRANT ALL PRIVILEGES ON DATABASE ultracoachmatrix TO dbultracoachmatrix;
ALTER DATABASE ultracoachmatrix OWNER TO dbultracoachmatrix;

\c ultracoachmatrix

GRANT USAGE, CREATE ON SCHEMA public TO dbultracoachmatrix;
ALTER SCHEMA public OWNER TO dbultracoachmatrix;

\q
```

Test database login:

```bash
psql -h localhost -U dbultracoachmatrix -d ultracoachmatrix
```

Database password must be stored only in:

```text
/home/ultracoachmatrix/ultracoachmatrix/UltraCoachMatrix/.env
```

## Django Settings Layout

Settings modules:

```text
UltraCoachMatrix/settings.py
UltraCoachMatrix/settings_common.py
UltraCoachMatrix/settings_development.py
UltraCoachMatrix/settings_production.py
```

Behavior:

- `settings.py` automatically selects development or production.
- Local PC defaults to `settings_development.py`.
- VPS defaults to `settings_production.py` when `DJANGO_ENV=production`, when the path is under `/var/www`, or when the hostname starts with `vmi`.
- Shared settings live in `settings_common.py`.
- Local development uses SQLite.
- Production uses PostgreSQL.
- Production media can be moved outside the repo using `DJANGO_MEDIA_ROOT`.

## Production `.env`

Production config lives here:

```text
/home/ultracoachmatrix/ultracoachmatrix/UltraCoachMatrix/.env
```

Expected HTTPS/domain version:

```env
DJANGO_ENV=production
DJANGO_SECRET_KEY=CHANGE_THIS_SECRET_KEY
DJANGO_DEBUG=false

DJANGO_ALLOWED_HOSTS=ultracoachmatrix.in,www.ultracoachmatrix.in,173.249.33.152
DJANGO_CSRF_TRUSTED_ORIGINS=https://ultracoachmatrix.in,https://www.ultracoachmatrix.in
CORS_ALLOWED_ORIGINS=https://ultracoachmatrix.in,https://www.ultracoachmatrix.in

SECURE_SSL_REDIRECT=true
SESSION_COOKIE_SECURE=true
CSRF_COOKIE_SECURE=true
SECURE_HSTS_SECONDS=31536000

DB_NAME=ultracoachmatrix
DB_USER=dbultracoachmatrix
DB_PASSWORD=CHANGE_THIS_STRONG_PASSWORD
DB_HOST=localhost
DB_PORT=5432

DJANGO_MEDIA_URL=/media/
DJANGO_MEDIA_ROOT=/home/ultracoachmatrix/ultracoachmatrix/media

EMAIL_BASE_URL=https://ultracoachmatrix.in

CELERY_BROKER_URL=redis://127.0.0.1:6379/0
CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/1

FIREBASE_CREDENTIALS_FILE=
FIREBASE_PROJECT_ID=
PUSH_NOTIFICATIONS_ENABLED=true
```

Generate a Django secret key:

```bash
cd /home/ultracoachmatrix/ultracoachmatrix/UltraCoachMatrix
source venv/bin/activate
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

Lock `.env`:

```bash
chmod 600 /home/ultracoachmatrix/ultracoachmatrix/UltraCoachMatrix/.env
```

For temporary HTTP/IP testing before SSL, update `.env`:

```env
DJANGO_ALLOWED_HOSTS=173.249.33.152
DJANGO_CSRF_TRUSTED_ORIGINS=http://173.249.33.152
CORS_ALLOWED_ORIGINS=http://173.249.33.152
SECURE_SSL_REDIRECT=false
SESSION_COOKIE_SECURE=false
CSRF_COOKIE_SECURE=false
SECURE_HSTS_SECONDS=0
EMAIL_BASE_URL=http://173.249.33.152
```

## Python Environment

Virtual environment:

```text
/home/ultracoachmatrix/ultracoachmatrix/UltraCoachMatrix/venv
```

Create/install as `ultracoachmatrix`:

```bash
cd /home/ultracoachmatrix/ultracoachmatrix/UltraCoachMatrix
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

If needed:

```bash
pip install gunicorn
```

Django setup:

```bash
python manage.py migrate
python manage.py collectstatic
python manage.py createsuperuser
python manage.py check
```

Do not run `makemigrations` on the server unless model changes were intentionally made there. Migrations should normally be created locally and committed to Git.

Manual Gunicorn test:

```bash
cd /home/ultracoachmatrix/ultracoachmatrix/UltraCoachMatrix
source venv/bin/activate
gunicorn --workers 3 --bind 0.0.0.0:8000 UltraCoachMatrix.wsgi:application
```

Test URL:

```text
http://173.249.33.152:8000
```

Stop manual Gunicorn with `CTRL + C`.

## Gunicorn systemd Service

Service file:

```text
/etc/systemd/system/ultracoachmatrix.service
```

Current recommended content:

```ini
[Unit]
Description=UltraCoachMatrix Django Gunicorn Service
After=network.target postgresql.service redis-server.service

[Service]
User=ultracoachmatrix
Group=www-data
WorkingDirectory=/home/ultracoachmatrix/ultracoachmatrix/UltraCoachMatrix
EnvironmentFile=/home/ultracoachmatrix/ultracoachmatrix/UltraCoachMatrix/.env
RuntimeDirectory=ultracoachmatrix
RuntimeDirectoryMode=0755
ExecStart=/home/ultracoachmatrix/ultracoachmatrix/UltraCoachMatrix/venv/bin/gunicorn --workers 3 --bind unix:/run/ultracoachmatrix/gunicorn.sock --umask 007 UltraCoachMatrix.wsgi:application
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Commands:

```bash
sudo systemctl daemon-reload
sudo systemctl restart ultracoachmatrix
sudo systemctl enable ultracoachmatrix
sudo systemctl status ultracoachmatrix
```

Logs:

```bash
sudo journalctl -u ultracoachmatrix -n 100 --no-pager
```

Socket check:

```bash
ls -l /run/ultracoachmatrix/gunicorn.sock
```

## Nginx

Site config:

```text
/etc/nginx/sites-available/ultracoachmatrix
```

Enabled symlink:

```text
/etc/nginx/sites-enabled/ultracoachmatrix
```

Current HTTP/IP config:

```nginx
server {
    listen 80;
    server_name ultracoachmatrix.in www.ultracoachmatrix.in;

    client_max_body_size 50M;

    location /static/ {
        alias /home/ultracoachmatrix/ultracoachmatrix/UltraCoachMatrix/staticfiles/;
    }

    location /media/ {
        alias /home/ultracoachmatrix/ultracoachmatrix/media/;
    }

    location / {
        proxy_pass http://unix:/run/ultracoachmatrix/gunicorn.sock;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Commands:

```bash
sudo ln -sf /etc/nginx/sites-available/ultracoachmatrix /etc/nginx/sites-enabled/ultracoachmatrix
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl restart nginx
sudo systemctl status nginx
```

Logs:

```bash
sudo tail -n 100 /var/log/nginx/error.log
sudo tail -n 100 /var/log/nginx/access.log
```

## Static And Media

Collect static:

```bash
cd /home/ultracoachmatrix/ultracoachmatrix/UltraCoachMatrix
source venv/bin/activate
python manage.py collectstatic
```

Production media folder:

```text
/home/ultracoachmatrix/ultracoachmatrix/media
```

Move old project media once if needed:

```bash
rsync -av /home/ultracoachmatrix/ultracoachmatrix/UltraCoachMatrix/media/ /home/ultracoachmatrix/ultracoachmatrix/media/
```

## Firewall

```bash
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw enable
sudo ufw status
```

## Celery

The project uses Redis/Celery for background jobs. Add these services when background jobs are needed in production.

Worker service:

```text
/etc/systemd/system/ultracoachmatrix-celery.service
```

```ini
[Unit]
Description=UltraCoachMatrix Celery Worker
After=network.target redis-server.service postgresql.service

[Service]
User=ultracoachmatrix
Group=www-data
WorkingDirectory=/home/ultracoachmatrix/ultracoachmatrix/UltraCoachMatrix
EnvironmentFile=/home/ultracoachmatrix/ultracoachmatrix/UltraCoachMatrix/.env
ExecStart=/home/ultracoachmatrix/ultracoachmatrix/UltraCoachMatrix/venv/bin/celery -A UltraCoachMatrix worker -l info
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Beat service:

```text
/etc/systemd/system/ultracoachmatrix-celerybeat.service
```

```ini
[Unit]
Description=UltraCoachMatrix Celery Beat
After=network.target redis-server.service postgresql.service

[Service]
User=ultracoachmatrix
Group=www-data
WorkingDirectory=/home/ultracoachmatrix/ultracoachmatrix/UltraCoachMatrix
EnvironmentFile=/home/ultracoachmatrix/ultracoachmatrix/UltraCoachMatrix/.env
ExecStart=/home/ultracoachmatrix/ultracoachmatrix/UltraCoachMatrix/venv/bin/celery -A UltraCoachMatrix beat -l info
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Commands:

```bash
sudo systemctl daemon-reload
sudo systemctl restart ultracoachmatrix-celery
sudo systemctl enable ultracoachmatrix-celery
sudo systemctl restart ultracoachmatrix-celerybeat
sudo systemctl enable ultracoachmatrix-celerybeat
```

## Deployment Routine

Run as `ultracoachmatrix`:

```bash
cd /home/ultracoachmatrix/ultracoachmatrix/UltraCoachMatrix
source venv/bin/activate
git pull
pip install -r requirements.txt
python manage.py migrate
python manage.py collectstatic
python manage.py check
```

Restart services:

```bash
sudo systemctl restart ultracoachmatrix
sudo systemctl restart nginx
```

If Celery is enabled:

```bash
sudo systemctl restart ultracoachmatrix-celery
sudo systemctl restart ultracoachmatrix-celerybeat
```

## CSRF And HTTP Testing

When using plain HTTP/IP, `.env` must contain:

```env
DJANGO_ALLOWED_HOSTS=173.249.33.152
DJANGO_CSRF_TRUSTED_ORIGINS=http://173.249.33.152
SECURE_SSL_REDIRECT=false
SESSION_COOKIE_SECURE=false
CSRF_COOKIE_SECURE=false
EMAIL_BASE_URL=http://173.249.33.152
```

If login/form submission shows:

```text
Forbidden (403)
CSRF verification failed. CSRF cookie not set.
```

Check settings:

```bash
cd /home/ultracoachmatrix/ultracoachmatrix/UltraCoachMatrix
source venv/bin/activate
python manage.py shell -c "from django.conf import settings; print(settings.CSRF_COOKIE_SECURE, settings.SESSION_COOKIE_SECURE, settings.SECURE_SSL_REDIRECT, settings.CSRF_TRUSTED_ORIGINS)"
```

For HTTP/IP testing expected output:

```text
False False False ['http://173.249.33.152']
```

Also clear browser cookies/site data for `173.249.33.152`.

## 502 Bad Gateway Checklist

`502 Bad Gateway` means Nginx is running but cannot reach Gunicorn.

Check service:

```bash
sudo systemctl status ultracoachmatrix
sudo journalctl -u ultracoachmatrix -n 100 --no-pager
```

Check socket:

```bash
ls -l /run/ultracoachmatrix/gunicorn.sock
```

Check Nginx error log:

```bash
sudo tail -n 100 /var/log/nginx/error.log
```

Ensure Nginx has:

```nginx
proxy_pass http://unix:/run/ultracoachmatrix/gunicorn.sock;
```

Ensure systemd has:

```ini
RuntimeDirectory=ultracoachmatrix
RuntimeDirectoryMode=0755
ExecStart=/home/ultracoachmatrix/ultracoachmatrix/UltraCoachMatrix/venv/bin/gunicorn --workers 3 --bind unix:/run/ultracoachmatrix/gunicorn.sock --umask 007 UltraCoachMatrix.wsgi:application
```

Restart:

```bash
sudo systemctl daemon-reload
sudo systemctl restart ultracoachmatrix
sudo nginx -t
sudo systemctl restart nginx
```

## SSL

Free SSL can be added after a domain points to `173.249.33.152`.

Install:

```bash
sudo apt install -y certbot python3-certbot-nginx
```

Generate certificate:

```bash
sudo certbot --nginx -d ultracoachmatrix.in -d www.ultracoachmatrix.in
```

Check renewal:

```bash
sudo certbot renew --dry-run
```

After SSL, update `.env` as shown in the production `.env` section and restart:

```bash
sudo systemctl restart ultracoachmatrix
sudo systemctl restart nginx
```

## Services To Check After Reboot

```bash
sudo systemctl status nginx
sudo systemctl status postgresql
sudo systemctl status redis-server
sudo systemctl status ultracoachmatrix
```

Restart only the website:

```bash
sudo systemctl restart ultracoachmatrix
sudo systemctl restart nginx
```

Restart full VPS:

```bash
sudo reboot
```

## Institute Isolation

The current architecture uses one shared PostgreSQL database with institute-level application isolation.

Important models:

- `super_admin.Institute`
- `super_admin.UserProfile`
- institute-scoped records with `institute` foreign keys

Expected rules:

- Every institute has one `Institute` row.
- Institute users have `UserProfile.institute`.
- Views must filter data by the logged-in user's institute.
- Detail/update/delete views must validate that the target object's institute matches the logged-in user's institute.
- Super admins may access global data.

Do not move to separate databases per institute unless the architecture is intentionally redesigned. Separate databases increase migration, backup, reporting, and operations complexity.

## Secrets Notice

Do not commit real secrets to Git or docs:

- Linux user passwords
- `DJANGO_SECRET_KEY`
- `DB_PASSWORD`
- email SMTP password
- Firebase service account JSON

If any password was shared in chat, screenshots, or committed files, rotate it before final production use.
