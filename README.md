# Vimeo Account Video Downloader

A Python desktop application (Tkinter GUI) that downloads videos from any Vimeo user profile using a credentials JSON file.

---

## Features

- **Credentials loaded from a JSON file** — browse for a file containing `access_token`, `client_id`, and `client_secret`; all three fields are displayed as masked entries with individual Show/Hide toggles
- **Client-credentials OAuth flow** — if no `access_token` is provided, the app automatically exchanges `client_id` + `client_secret` for a token via Vimeo's OAuth endpoint
- **Configurable profile URL** — download from any public Vimeo profile (`https://vimeo.com/username`), channel (`https://vimeo.com/channels/name`), or leave blank to use the authenticated account (`/me/videos`)
- Fetches the **complete video library** with automatic pagination
- Displays videos in a scrollable, interactive checklist with:
  - Video name
  - Created date/time (converted to local timezone)
  - Duration
  - Best available quality
  - File size
  - Download status
- **Filter toggle** — hide videos that have no duration, quality or size information
- **Two-stage download strategy**
  1. Direct signed URL from the Vimeo API (fastest, no extra tool required)
  2. Falls back to **yt-dlp** for videos without an API download link
- Quality selector: Best Available / HD / SD / Mobile
- Per-video **progress bar** with bytes downloaded and percentage
- Overall progress bar across all selected videos
- **Skip already-downloaded** files automatically (checks file size)
- Optional **number-prefix filenames** (e.g. `001_MyVideo.mp4`)
- Scrollable main window — all controls remain accessible at any window size
- Cancel in-progress downloads cleanly
- Timestamped log panel

---

## Requirements

- Python 3.10 or later
- `requests` — HTTP client for Vimeo API calls
- `yt-dlp` — fallback downloader for videos without a direct API link

Install all dependencies:

```bash
pip install -r requirements.txt
```

---

## Credentials JSON File

Create a JSON file with the following structure:

```json
{
  "access_token": "your_personal_access_token",
  "client_id": "your_client_id",
  "client_secret": "your_client_secret"
}
```

All three keys are required. You can omit the token value (leave it as an empty string `""`) to have the app obtain one automatically using the client credentials.

### Where to get these values

1. Sign in at <https://developer.vimeo.com/> with the account that owns the videos.
2. Go to **My Apps** → **Create an app** (or open an existing app).
3. Copy the **Client Identifier** and **Client Secret** from the app page.
4. Under **Authentication**, generate a **Personal Access Token** with the scopes: `public`, `private`, `video_files`.
5. Save all three values into your credentials JSON file.

> **Tip:** The `video_files` scope is required for direct download links. Without it the app will fall back to yt-dlp for every video.

---

## Usage

```bash
python app.py
```

1. Click **Browse…** next to **Credentials File** and select your credentials JSON.
2. The Access Token, Client ID, and Client Secret fields will populate automatically (masked by default — click **Show** to reveal any field).
3. Optionally edit the **Profile URL** to target a specific Vimeo profile or channel (defaults to `https://vimeo.com/cbcmrcf`).
4. Choose an **Output Folder** (defaults to `~/Downloads/Vimeo`).
5. Select a **Quality** preference and click **🔍 Fetch Videos**.
6. Once the list loads, use **Select All / Deselect All** or click individual checkboxes to choose which videos to download.
7. Optionally enable **Hide videos without duration / quality / size** to filter out unavailable videos.
8. Click **⬇ Download Selected** and monitor progress in real time.
9. Click **Open Folder** to open the output directory when done.

---

## Project Structure

```
├── app.py            # Main GUI application
├── requirements.txt  # Python dependencies
└── README.md
```

---

## Security Notes

- All credential fields are masked in the UI by default; each has an individual **Show** toggle.
- Credentials are never written to disk by this application — they are loaded read-only from the file you provide.
- All API communication is over HTTPS to `api.vimeo.com` only.
- The Bearer token is sent only in the `Authorization` header of API and download requests.
