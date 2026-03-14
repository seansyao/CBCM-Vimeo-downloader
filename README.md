# Vimeo Account Video Downloader

A Python desktop application (Tkinter GUI) that downloads videos from any Vimeo user profile using a credentials JSON file.

---

## Features

- **Credentials loaded from a JSON file** — browse for a file containing `access_token`, `client_id`, and `client_secret`; all three fields are displayed as masked entries with individual Show/Hide toggles
- **Client-credentials OAuth flow** — if no `access_token` is provided, the app automatically exchanges `client_id` + `client_secret` for a token via Vimeo's OAuth endpoint
- **Configurable profile URL** — download from any public Vimeo profile (`https://vimeo.com/username`), channel (`https://vimeo.com/channels/name`), or leave blank to use the authenticated account (`/me/videos`)
- **Fetch limit** — optionally cap how many videos are fetched (useful for quick testing); leave empty to fetch all
- Fetches the **complete video library** with automatic pagination
- Displays videos in a scrollable, interactive checklist with:
  - **Video Title** — original title from Vimeo
  - **Video File Name** — auto-generated sanitized filename (see [File Naming](#file-naming) below)
  - **Created** — upload date/time converted to local timezone
  - **Duration**
  - **Best available quality**
  - **File size**
  - **Download status**
- **Filter toggle** — hide videos that have no duration, quality, or size information
- **Two-stage download strategy**
  1. Direct signed URL from the Vimeo API (fastest, no extra tool required)
  2. Falls back to **yt-dlp** for videos without an API download link
- Quality selector: Best Available / HD / SD / Mobile
- Per-video **progress bar** with bytes downloaded and percentage
- Overall progress bar across all selected videos
- **Skip already-downloaded** files automatically (checks file size)
- **Pre-marked already-downloaded videos** — when Fetch is clicked, the app scans the output folder for existing `.mp4` files; any video whose generated filename already exists is shown as "Done ✓" (green) with its checkbox disabled and unchecked, so it is excluded from the next download batch
- Optional **number-prefix filenames** (e.g. `001_20240315_143022_Sunday_Service.mp4`)
- Scrollable main window — all controls remain accessible at any window size
- Cancel in-progress downloads cleanly
- Timestamped log panel

---

## Requirements

- Python 3.10 or later
- `PyVimeo` — official Vimeo Python SDK for all API calls
- `requests` — HTTP client (used internally by PyVimeo and for streaming downloads)
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

## File Naming

Downloaded files are named automatically using the following format:

```
YYYYMMDD_HHMMSS_<sanitized_title>.mp4
```

- **`YYYYMMDD_HHMMSS`** — the video's creation timestamp in your local timezone
- The title is sanitized by replacing spaces, periods, and any Windows-invalid characters (`\ / : * ? " < > |`) with `_`
- The first letter after each `_` separator is capitalised

**Examples:**

| Vimeo Title | Generated filename |
|---|---|
| `Sunday Service 03.09.25` | `20250309_103000_Sunday_Service_03_09_25.mp4` |
| `Weekly Update: Team/Dev` | `20260114_090000_Weekly_Update__Team_Dev.mp4` |

The **Video File Name** column in the video list shows the exact filename that will be used before you start a download.

If the **Number-prefix filenames** option is enabled, a zero-padded index is prepended:

```
001_20240315_143022_Sunday_Service.mp4
```

---

## Usage

```bash
python app.py
```

1. Click **Browse…** next to **Credentials File** and select your credentials JSON.
2. The Access Token, Client ID, and Client Secret fields will populate automatically (masked by default — click **Show** to reveal any field).
3. Optionally edit the **Profile URL** to target a specific Vimeo profile or channel (defaults to `https://vimeo.com/cbcmrcf`).
4. Choose an **Output Folder** (defaults to `~/Downloads/Vimeo`).
5. Optionally enter a **Limit** to fetch only the first N videos (leave empty to fetch all).
6. Select a **Quality** preference and click **🔍 Fetch Videos**.
7. Once the list loads, use **Select All / Deselect All** or click individual checkboxes to choose which videos to download. Videos whose generated filename already exists in the output folder are pre-marked as **Done ✓** and cannot be re-selected. Review the **Video File Name** column to confirm the generated filenames.
8. Optionally enable **Hide videos without duration / quality / size** to filter out unavailable videos.
9. Click **⬇ Download Selected** and monitor progress in real time.
10. Click **Open Folder** to open the output directory when done.

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
