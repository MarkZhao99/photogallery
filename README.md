# Photo Shelf

A simple photo archive website that can store files locally, in your iCloud Drive folder, or on a WebDAV endpoint.

## What this project does

- Uploads one or more images from the admin page, including batch importing multiple photos to the same country
- Saves the shooting country for each photo
- Groups the archive by country
- Stores files in your iCloud Drive folder by default
- Can still switch to local storage or WebDAV if needed

## Quick start

1. Create a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Create your environment file:

```bash
cp .env.example .env
```

4. Run the app:

```bash
python3 app.py
```

5. Open the public gallery at `http://127.0.0.1:5001`
6. Open the private admin login at `http://127.0.0.1:5001/admin/login`

## Local iCloud storage + public sharing

This repository now includes a local dual-instance setup for the iCloud storage mode:

- Admin instance: `127.0.0.1:5001`
- Public gallery instance: `127.0.0.1:5002`

Useful commands:

```bash
./scripts/start_local_gallery_stack.sh
./scripts/status_local_gallery_stack.sh
./scripts/stop_local_gallery_stack.sh
```

For the simplest one-click temporary public share on macOS, double-click:

- [start_public_gallery_share.command](/Users/mark/vscode/vscode1/start_public_gallery_share.command)

To stop it, double-click:

- [stop_public_gallery_share.command](/Users/mark/vscode/vscode1/stop_public_gallery_share.command)

To share the public gallery temporarily over the internet manually:

```bash
./scripts/install_cloudflared_local.sh
./scripts/share_public_quick_tunnel.sh
```

For the full Chinese step-by-step guide, see:

- [LOCAL_PUBLIC_SHARE_ICLOUD.md](/Users/mark/vscode/vscode1/LOCAL_PUBLIC_SHARE_ICLOUD.md)

## Default: use iCloud Drive

Keep this in `.env`:

```bash
PHOTO_STORAGE=icloud
ICLOUD_PHOTO_DIR=~/Library/Mobile Documents/com~apple~CloudDocs/web图库
ADMIN_USERNAME=zxxk
ADMIN_PASSWORD=change-this-admin-password
ADMIN_SESSION_SECRET=change-this-session-secret
```

Uploaded files and the `photo-metadata.json` file will be saved into that iCloud-synced folder.

## Use local storage instead

```bash
PHOTO_STORAGE=local
```

Uploaded files will be saved into the local `uploads/` folder.

## Use WebDAV storage instead

Update `.env`:

```bash
PHOTO_STORAGE=webdav
WEBDAV_BASE_URL=https://your-webdav-host/dav/
WEBDAV_USERNAME=your-username
WEBDAV_PASSWORD=your-password
WEBDAV_REMOTE_DIR=photo-wall
```

## Notes

- Supported image formats: `jpg`, `jpeg`, `png`, `gif`, `webp`
- Public visitors can only browse `/` or `/gallery`; uploads and edits require logging into `/admin/login` with `ADMIN_USERNAME` and `ADMIN_PASSWORD`
- Each upload batch must include a shooting country, and the page groups photos by country
- The app proxies image reads through `/photos/<filename>` so storage credentials stay on the server side
- If your WebDAV service uses a self-signed certificate, you may need extra `requests` SSL configuration before production use
