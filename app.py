#!/usr/bin/env python3
"""
Vimeo Account Video Downloader
Downloads all videos from a Vimeo user account using an API access token.

Strategy:
  1. Fetch the full video list via the Vimeo API (/me/videos with pagination).
  2. For each video, attempt a direct download using the signed URL returned
     by the API (fastest, no extra dependency).
  3. Fall back to yt-dlp (with Bearer-token header) for videos that have no
     API download link (e.g. privacy-restricted or externally hosted).
"""

import json
import os
import re
import subprocess
import sys
import threading
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, scrolledtext, ttk

import requests

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
VIMEO_API_BASE = "https://api.vimeo.com"
CHUNK_SIZE = 1024 * 1024  # 1 MB per streaming chunk

# Quality priority (lower = better)
_QUALITY_RANK = {"source": 1, "hd": 2, "sd": 3, "mobile": 4}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def sanitize_filename(name: str) -> str:
    """Strip characters that are illegal in Windows / macOS / Linux filenames."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    name = name.strip(". ")
    return name[:200] or "untitled"


def format_duration(seconds: int) -> str:
    if not seconds:
        return "--:--"
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def format_size(num_bytes) -> str:
    if not num_bytes:
        return "Unknown"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num_bytes < 1024:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.1f} PB"


# ---------------------------------------------------------------------------
# Vimeo API wrapper
# ---------------------------------------------------------------------------

class VimeoAPI:
    def __init__(self, token: str, client_id: str = "", client_secret: str = ""):
        self.token = token
        self.client_id = client_id
        self.client_secret = client_secret
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"bearer {token}",
                "Accept": "application/vnd.vimeo.*+json;version=3.4",
            }
        )

    @classmethod
    def from_client_credentials(cls, client_id: str, client_secret: str) -> "VimeoAPI":
        """Exchange client credentials for an app-level access token."""
        resp = requests.post(
            f"{VIMEO_API_BASE}/oauth/authorize/client",
            auth=(client_id, client_secret),
            json={"grant_type": "client_credentials", "scope": "public private video_files"},
            headers={"Accept": "application/vnd.vimeo.*+json;version=3.4"},
            timeout=15,
        )
        resp.raise_for_status()
        token = resp.json().get("access_token", "")
        if not token:
            raise ValueError("No access_token returned by Vimeo OAuth endpoint.")
        return cls(token, client_id=client_id, client_secret=client_secret)

    # ------------------------------------------------------------------
    def get_me(self) -> dict:
        r = self.session.get(f"{VIMEO_API_BASE}/me", timeout=15)
        r.raise_for_status()
        return r.json()

    # ------------------------------------------------------------------
    def get_all_videos(self, progress_cb=None, base_path="/me/videos") -> list:
        """Return every video in the authenticated user's library."""
        videos: list = []
        url = f"{VIMEO_API_BASE}{base_path}"
        params = {
            "fields": (
                "uri,name,duration,link,download,pictures,status,privacy,created_time"
            ),
            "per_page": 100,
            "page": 1,
        }

        while url:
            r = self.session.get(url, params=params, timeout=30)
            r.raise_for_status()
            data = r.json()

            videos.extend(data.get("data", []))
            if progress_cb:
                progress_cb(len(videos), data.get("total", 0))

            next_path = data.get("paging", {}).get("next")
            if next_path:
                # next_path is a relative path like /me/videos?page=2&…
                url = (
                    next_path
                    if next_path.startswith("http")
                    else f"{VIMEO_API_BASE}{next_path}"
                )
                params = None  # params are already embedded in the URL
            else:
                url = None

        return videos

    # ------------------------------------------------------------------
    def best_download(self, video: dict, preferred_quality: str):
        """
        Return (url, quality_label, size_bytes) for the best available
        download link, or (None, None, None) if none exist.
        """
        downloads = video.get("download") or []
        if not downloads:
            return None, None, None

        # Prefer actual video MIME types; fall back to everything
        vids = [d for d in downloads if str(d.get("type", "")).startswith("video/")]
        if not vids:
            vids = downloads

        if preferred_quality == "best":
            vids.sort(
                key=lambda d: (
                    _QUALITY_RANK.get(d.get("quality", "mobile"), 99),
                    -(d.get("size") or 0),
                )
            )
        else:
            matched = [d for d in vids if d.get("quality") == preferred_quality]
            vids = matched if matched else vids
            vids.sort(key=lambda d: _QUALITY_RANK.get(d.get("quality", "mobile"), 99))

        best = vids[0]
        return best.get("link"), best.get("quality"), best.get("size")


# ---------------------------------------------------------------------------
# Background download worker
# ---------------------------------------------------------------------------

class DownloadWorker(threading.Thread):
    def __init__(
        self,
        api: VimeoAPI,
        videos: list,
        output_dir: str,
        quality: str,
        add_number_prefix: bool,
        log_cb,
        progress_cb,
        video_done_cb,
        all_done_cb,
    ):
        super().__init__(daemon=True)
        self.api = api
        self.videos = videos
        self.output_dir = output_dir
        self.quality = quality
        self.add_number_prefix = add_number_prefix
        self.log_cb = log_cb
        self.progress_cb = progress_cb
        self.video_done_cb = video_done_cb
        self.all_done_cb = all_done_cb
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    # ------------------------------------------------------------------
    def run(self):
        total = len(self.videos)
        pad = len(str(total))

        for idx, video in enumerate(self.videos):
            if self._stop.is_set():
                self.log_cb("Download cancelled by user.")
                break
            if not self._process_video(idx, total, pad, video):
                break

        if not self._stop.is_set():
            self.all_done_cb()

    def _process_video(self, idx: int, total: int, pad: int, video: dict) -> bool:
        """Handle a single video download. Returns False if the loop should stop."""
        name = video.get("name") or f"video_{idx + 1}"
        uri = video.get("uri", "")
        video_id = uri.rsplit("/", 1)[-1] if uri else str(idx)

        self.log_cb(f"\n[{idx + 1}/{total}] {name}")
        self.progress_cb(idx, total, 0, 0, name)

        filepath = self._resolve_filepath(idx, pad, name, video, video_id)
        if filepath is None:
            # Already downloaded and skipped
            self.video_done_cb(idx, "skipped")
            return True

        ok = self._attempt_download(video, video_id, filepath, idx, total, name)

        if self._stop.is_set():
            return False

        if ok:
            self.log_cb(f"  ✓ Saved: {os.path.basename(filepath)}")
            self.video_done_cb(idx, "done")
        else:
            self.log_cb(f"  ✗ Failed: {name}")
            self.video_done_cb(idx, "failed")
        return True

    def _resolve_filepath(self, idx: int, pad: int, name: str, video: dict, video_id: str):
        """Return the destination filepath, or None if the video should be skipped."""
        safe_name = sanitize_filename(name)
        if self.add_number_prefix:
            safe_name = f"{str(idx + 1).zfill(pad)}_{safe_name}"
        filepath = os.path.join(self.output_dir, f"{safe_name}.mp4")

        if os.path.exists(filepath):
            dl_url, _q, size = self.api.best_download(video, self.quality)
            if size and os.path.getsize(filepath) >= size:
                self.log_cb(f"  Skipping – already downloaded: {os.path.basename(filepath)}")
                return None
            # Unique-ify the path
            base, ext = os.path.splitext(filepath)
            counter = 1
            candidate = f"{base}_{video_id}{ext}"
            while os.path.exists(candidate) and counter < 100:
                candidate = f"{base}_{video_id}_{counter}{ext}"
                counter += 1
            filepath = candidate

        return filepath

    def _attempt_download(self, video: dict, video_id: str, filepath: str,
                          idx: int, total: int, name: str) -> bool:
        """Try API direct download, then fall back to yt-dlp."""
        dl_url, q_label, size = self.api.best_download(video, self.quality)
        if dl_url:
            self.log_cb(f"  Quality: {q_label}  |  Size: {format_size(size)}")
            self.log_cb("  Downloading via Vimeo API …")
            return self._download_direct(dl_url, filepath, idx, total, size, name)

        video_url = video.get("link") or f"https://vimeo.com/{video_id}"
        self.log_cb("  No API download link – falling back to yt-dlp …")
        return self._download_ytdlp(video_url, filepath, name, idx, total)

    # ------------------------------------------------------------------
    def _download_direct(self, url, filepath, v_idx, v_total, expected_size, name):
        try:
            with self.api.session.get(url, stream=True, timeout=60) as resp:
                resp.raise_for_status()
                total = int(resp.headers.get("content-length", 0)) or expected_size or 0
                downloaded = 0
                tmp_path = filepath + ".part"
                with open(tmp_path, "wb") as fh:
                    for chunk in resp.iter_content(chunk_size=CHUNK_SIZE):
                        if self._stop.is_set():
                            fh.close()
                            os.remove(tmp_path)
                            return False
                        if chunk:
                            fh.write(chunk)
                            downloaded += len(chunk)
                            self.progress_cb(v_idx, v_total, downloaded, total, name)
            os.replace(tmp_path, filepath)
            return True
        except Exception as exc:
            self.log_cb(f"  Error: {exc}")
            tmp = filepath + ".part"
            if os.path.exists(tmp):
                os.remove(tmp)
            return False

    # ------------------------------------------------------------------
    def _download_ytdlp(self, url, filepath, name, v_idx, v_total):
        try:
            cmd = [
                "yt-dlp",
                "--add-header", f"Authorization:bearer {self.api.token}",
                "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
                "--merge-output-format", "mp4",
                "-o", filepath,
                "--no-playlist",
                "--no-colors",
                url,
            ]
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            for line in process.stdout:
                if self._stop.is_set():
                    process.terminate()
                    return False
                line = line.rstrip()
                if line:
                    self.log_cb(f"    {line}")
                    m = re.search(r"(\d+\.?\d*)%", line)
                    if m:
                        pct = float(m.group(1)) / 100.0
                        self.progress_cb(v_idx, v_total, pct, 1.0, name)
            process.wait()
            return process.returncode == 0
        except FileNotFoundError:
            self.log_cb("  yt-dlp not found. Run:  pip install yt-dlp")
            return False
        except Exception as exc:
            self.log_cb(f"  yt-dlp error: {exc}")
            return False


# ---------------------------------------------------------------------------
# Main GUI Application
# ---------------------------------------------------------------------------

class VimeoDownloaderApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Vimeo Account Video Downloader")
        self.root.geometry("980x780")
        self.root.minsize(820, 640)

        self.videos: list = []
        self.video_check_vars: list[tk.BooleanVar] = []
        self.api: VimeoAPI | None = None
        self.worker: DownloadWorker | None = None
        self.is_downloading = False

        self._setup_styles()
        self._build_ui()

    # ------------------------------------------------------------------
    # Styles
    # ------------------------------------------------------------------
    def _setup_styles(self):
        s = ttk.Style()
        try:
            s.theme_use("clam")
        except Exception:
            pass
        s.configure("Title.TLabel", font=("Segoe UI", 14, "bold"))
        s.configure("Download.TButton", font=("Segoe UI", 10, "bold"), padding=6)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self):
        main = self._build_scroll_container()
        ttk.Label(main, text="Vimeo Account Video Downloader", style="Title.TLabel").pack(
            pady=(0, 10)
        )
        self._build_config_panel(main)
        self._build_video_list(main)
        self._build_progress_panel(main)
        self._build_log_panel(main)
        self._build_action_buttons(main)

    def _build_scroll_container(self) -> ttk.Frame:
        """Create the outer canvas+scrollbar wrapper and return the inner content frame."""
        container = ttk.Frame(self.root)
        container.pack(fill=tk.BOTH, expand=True)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(0, weight=1)

        canvas = tk.Canvas(container, highlightthickness=0)
        canvas.grid(row=0, column=0, sticky=tk.NSEW)

        vsb = ttk.Scrollbar(container, orient=tk.VERTICAL, command=canvas.yview)
        vsb.grid(row=0, column=1, sticky=tk.NS)
        canvas.configure(yscrollcommand=vsb.set)

        main = ttk.Frame(canvas, padding=10)
        win_id = canvas.create_window((0, 0), window=main, anchor=tk.NW)

        main.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(win_id, width=e.width))
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))

        return main

    def _build_config_panel(self, parent: ttk.Frame):
        """Build the Configuration label-frame with all credential/path/quality rows."""
        cfg = ttk.LabelFrame(parent, text="Configuration", padding=10)
        cfg.pack(fill=tk.X, pady=(0, 8))
        cfg.columnconfigure(1, weight=1)

        self._build_credentials_row(cfg)
        self._build_masked_row(cfg, row=1, label="Access Token:")
        self._build_masked_row(cfg, row=2, label="Client ID:")
        self._build_masked_row(cfg, row=3, label="Client Secret:")
        self._build_profile_url_row(cfg)
        self._build_output_dir_row(cfg)
        self._build_quality_row(cfg)
        self._build_fetch_row(cfg)

    def _build_credentials_row(self, cfg: ttk.Frame):
        """Row 0: JSON credential file picker."""
        ttk.Label(cfg, text="Credentials File:").grid(row=0, column=0, sticky=tk.W, padx=(0, 8), pady=4)
        frame = ttk.Frame(cfg)
        frame.grid(row=0, column=1, sticky=tk.EW, pady=4)
        frame.columnconfigure(0, weight=1)

        self.cred_file_var = tk.StringVar(value="No file loaded")
        ttk.Label(frame, textvariable=self.cred_file_var, foreground="gray", anchor=tk.W).grid(
            row=0, column=0, sticky=tk.EW
        )
        ttk.Button(frame, text="Browse…", command=self._browse_credentials).grid(
            row=0, column=1, padx=(6, 0)
        )

    def _build_masked_row(self, cfg: ttk.Frame, row: int, label: str):
        """Build a read-only masked entry row with a Show/Hide toggle.

        Stores references as:
          row 1 → self.token_var / self.token_entry / self._show_token
          row 2 → self.client_id_var / self.client_id_entry / self._show_cid
          row 3 → self.client_secret_var / self.client_secret_entry / self._show_cs
        """
        ttk.Label(cfg, text=label).grid(row=row, column=0, sticky=tk.W, padx=(0, 8), pady=4)
        frame = ttk.Frame(cfg)
        frame.grid(row=row, column=1, sticky=tk.EW, pady=4)
        frame.columnconfigure(0, weight=1)

        var = tk.StringVar()
        show_var = tk.BooleanVar()
        entry = ttk.Entry(frame, textvariable=var, show="*", state="readonly")
        entry.grid(row=0, column=0, sticky=tk.EW)
        ttk.Checkbutton(
            frame, text="Show", variable=show_var,
            command=lambda e=entry, sv=show_var: e.config(show="" if sv.get() else "*"),
        ).grid(row=0, column=1, padx=(6, 0))

        if row == 1:
            self.token_var, self.token_entry, self._show_token = var, entry, show_var
        elif row == 2:
            self.client_id_var, self.client_id_entry, self._show_cid = var, entry, show_var
        elif row == 3:
            self.client_secret_var, self.client_secret_entry, self._show_cs = var, entry, show_var

    def _build_profile_url_row(self, cfg: ttk.Frame):
        """Row 4: Vimeo profile URL input."""
        ttk.Label(cfg, text="Profile URL:").grid(row=4, column=0, sticky=tk.W, padx=(0, 8), pady=4)
        self.profile_url_var = tk.StringVar(value="https://vimeo.com/cbcmrcf")
        ttk.Entry(cfg, textvariable=self.profile_url_var).grid(row=4, column=1, sticky=tk.EW, pady=4)

    def _build_output_dir_row(self, cfg: ttk.Frame):
        """Row 5: Output folder picker."""
        ttk.Label(cfg, text="Output Folder:").grid(row=5, column=0, sticky=tk.W, padx=(0, 8), pady=4)
        frame = ttk.Frame(cfg)
        frame.grid(row=5, column=1, sticky=tk.EW, pady=4)
        frame.columnconfigure(0, weight=1)

        self.out_dir_var = tk.StringVar(
            value=os.path.join(os.path.expanduser("~"), "Downloads", "Vimeo")
        )
        ttk.Entry(frame, textvariable=self.out_dir_var).grid(row=0, column=0, sticky=tk.EW)
        ttk.Button(frame, text="Browse…", command=self._browse_dir).grid(row=0, column=1, padx=(6, 0))

    def _build_quality_row(self, cfg: ttk.Frame):
        """Row 6: Quality radio buttons and number-prefix toggle."""
        ttk.Label(cfg, text="Quality:").grid(row=6, column=0, sticky=tk.W, padx=(0, 8), pady=4)
        frame = ttk.Frame(cfg)
        frame.grid(row=6, column=1, sticky=tk.W, pady=4)

        self.quality_var = tk.StringVar(value="best")
        for label, val in (("Best Available", "best"), ("HD", "hd"), ("SD", "sd"), ("Mobile", "mobile")):
            ttk.Radiobutton(frame, text=label, variable=self.quality_var, value=val).pack(
                side=tk.LEFT, padx=(0, 12)
            )

        ttk.Separator(frame, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)
        self.num_prefix_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(frame, text="Number-prefix filenames", variable=self.num_prefix_var).pack(
            side=tk.LEFT
        )

    def _build_fetch_row(self, cfg: ttk.Frame):
        """Row 7: Fetch Videos button and logged-in user label."""
        frame = ttk.Frame(cfg)
        frame.grid(row=7, column=0, columnspan=2, sticky=tk.W, pady=(10, 2))

        self.fetch_btn = ttk.Button(frame, text="🔍  Fetch Videos", command=self._fetch_videos)
        self.fetch_btn.pack(side=tk.LEFT)
        self.user_lbl = ttk.Label(frame, text="")
        self.user_lbl.pack(side=tk.LEFT, padx=(12, 0))

    def _build_video_list(self, parent: ttk.Frame):
        """Build the Videos label-frame with toolbar, treeview, and scrollbar."""
        list_frame = ttk.LabelFrame(parent, text="Videos", padding=5)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 8))

        self._build_video_toolbar(list_frame)
        self._build_video_tree(list_frame)

    def _build_video_toolbar(self, list_frame: ttk.Frame):
        """Select/deselect buttons, selection count label, and filter toggle."""
        toolbar = ttk.Frame(list_frame)
        toolbar.pack(fill=tk.X, pady=(0, 4))

        ttk.Button(toolbar, text="Select All",   command=self._select_all).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(toolbar, text="Deselect All", command=self._deselect_all).pack(side=tk.LEFT, padx=(0, 4))
        self.sel_lbl = ttk.Label(toolbar, text="No videos loaded")
        self.sel_lbl.pack(side=tk.LEFT, padx=(8, 0))

        self.hide_incomplete_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            toolbar, text="Hide videos without duration / quality / size",
            variable=self.hide_incomplete_var, command=self._apply_filter,
        ).pack(side=tk.RIGHT, padx=(8, 0))

    def _build_video_tree(self, list_frame: ttk.Frame):
        """Treeview with columns and row-status colour tags."""
        tree_frame = ttk.Frame(list_frame)
        tree_frame.pack(fill=tk.BOTH, expand=True)

        cols = ("check", "name", "created", "duration", "quality", "size", "status")
        self.tree = ttk.Treeview(tree_frame, columns=cols, show="headings", selectmode="browse")

        headings = {
            "check": "✓", "name": "Video Name", "created": "Created",
            "duration": "Duration", "quality": "Quality", "size": "Size", "status": "Status",
        }
        for col, text in headings.items():
            self.tree.heading(col, text=text)

        col_cfg = {
            "check":    dict(width=32,  minwidth=32,  stretch=False, anchor=tk.CENTER),
            "name":     dict(width=280, minwidth=160),
            "created":  dict(width=130, minwidth=110, anchor=tk.CENTER),
            "duration": dict(width=80,  minwidth=60,  anchor=tk.CENTER),
            "quality":  dict(width=80,  minwidth=60,  anchor=tk.CENTER),
            "size":     dict(width=100, minwidth=80,  anchor=tk.E),
            "status":   dict(width=110, minwidth=80,  anchor=tk.CENTER),
        }
        for col, kwargs in col_cfg.items():
            self.tree.column(col, **kwargs)

        vsb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree.bind("<ButtonRelease-1>", self._on_tree_click)
        self.tree.tag_configure("done",        background="#d4edda", foreground="#155724")
        self.tree.tag_configure("failed",      background="#f8d7da", foreground="#721c24")
        self.tree.tag_configure("skipped",     background="#fff3cd", foreground="#856404")
        self.tree.tag_configure("downloading", background="#cce5ff", foreground="#004085")

    def _build_progress_panel(self, parent: ttk.Frame):
        """Build the Progress label-frame with per-video and overall bars."""
        prog_frame = ttk.LabelFrame(parent, text="Progress", padding=6)
        prog_frame.pack(fill=tk.X, pady=(0, 8))

        self.cur_lbl = ttk.Label(prog_frame, text="Ready")
        self.cur_lbl.pack(anchor=tk.W)

        self.vid_bar = ttk.Progressbar(prog_frame, mode="determinate")
        self.vid_bar.pack(fill=tk.X, pady=(2, 2))

        self.vid_pct_lbl = ttk.Label(prog_frame, text="")
        self.vid_pct_lbl.pack(anchor=tk.W)

        ttk.Separator(prog_frame).pack(fill=tk.X, pady=4)

        self.overall_lbl = ttk.Label(prog_frame, text="Overall: 0 / 0")
        self.overall_lbl.pack(anchor=tk.W)

        self.overall_bar = ttk.Progressbar(prog_frame, mode="determinate")
        self.overall_bar.pack(fill=tk.X, pady=(2, 0))

    def _build_log_panel(self, parent: ttk.Frame):
        """Build the Log label-frame with a dark scrolled text widget."""
        log_frame = ttk.LabelFrame(parent, text="Log", padding=5)
        log_frame.pack(fill=tk.BOTH, pady=(0, 8))

        self.log_box = scrolledtext.ScrolledText(
            log_frame, height=8, state=tk.DISABLED,
            font=("Consolas", 9), wrap=tk.WORD, background="#1e1e1e", foreground="#d4d4d4",
        )
        self.log_box.pack(fill=tk.BOTH, expand=True)

    def _build_action_buttons(self, parent: ttk.Frame):
        """Build the bottom row: Download, Cancel, Open Folder, Clear Log."""
        btn_row = ttk.Frame(parent)
        btn_row.pack(fill=tk.X)

        self.dl_btn = ttk.Button(
            btn_row, text="⬇  Download Selected",
            command=self._start_download, style="Download.TButton", state=tk.DISABLED,
        )
        self.dl_btn.pack(side=tk.LEFT, padx=(0, 6))

        self.cancel_btn = ttk.Button(btn_row, text="Cancel", command=self._cancel, state=tk.DISABLED)
        self.cancel_btn.pack(side=tk.LEFT, padx=(0, 6))

        ttk.Button(btn_row, text="Open Folder", command=self._open_folder).pack(side=tk.LEFT)
        ttk.Button(btn_row, text="Clear Log",   command=self._clear_log).pack(side=tk.RIGHT)

    # ------------------------------------------------------------------
    # Credentials file browser
    # ------------------------------------------------------------------
    def _browse_credentials(self):
        path = filedialog.askopenfilename(
            title="Select Vimeo credentials JSON file",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception as exc:
            messagebox.showerror("Load Error", f"Could not read credentials file:\n{exc}")
            return

        missing = [k for k in ("access_token", "client_id", "client_secret") if k not in data]
        if missing:
            messagebox.showerror(
                "Invalid File",
                f"The JSON file is missing required key(s): {', '.join(missing)}",
            )
            return

        # Populate the read-only entries
        for entry, var, key in (
            (self.token_entry,         self.token_var,         "access_token"),
            (self.client_id_entry,     self.client_id_var,     "client_id"),
            (self.client_secret_entry, self.client_secret_var, "client_secret"),
        ):
            entry.config(state="normal")
            var.set(data[key])
            entry.config(state="readonly")

        import os as _os
        self.cred_file_var.set(_os.path.basename(path))

    # ------------------------------------------------------------------
    # Parse Vimeo profile URL → API path
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_profile_url(profile_url: str) -> str:
        """Return the Vimeo API videos path for a given profile URL.

        Accepts:
          - empty / blank → /me/videos
          - https://vimeo.com/username  → /users/username/videos
          - https://vimeo.com/channels/channelname → /channels/channelname/videos
          - bare username → /users/username/videos
        """
        url = profile_url.strip().rstrip("/")
        if not url or url == "https://vimeo.com":
            return "/me/videos"
        m = re.match(
            r'^(?:https?://)?(?:www\.)?vimeo\.com/(channels/[^/?#]+|[^/?#]+)',
            url,
        )
        if m:
            segment = m.group(1)
            if segment.startswith("channels/"):
                return f"/{segment}/videos"
            return f"/users/{segment}/videos"
        # Treat bare input as a username
        if "/" not in url:
            return f"/users/{url}/videos"
        return "/me/videos"

    # ------------------------------------------------------------------
    # Logging (thread-safe)
    # ------------------------------------------------------------------
    def _log(self, msg: str):
        def _do():
            self.log_box.config(state=tk.NORMAL)
            ts = datetime.now().strftime("%H:%M:%S")
            self.log_box.insert(tk.END, f"[{ts}]  {msg}\n")
            self.log_box.see(tk.END)
            self.log_box.config(state=tk.DISABLED)
        self.root.after(0, _do)

    def _clear_log(self):
        self.log_box.config(state=tk.NORMAL)
        self.log_box.delete("1.0", tk.END)
        self.log_box.config(state=tk.DISABLED)

    # ------------------------------------------------------------------
    # Directory browser
    # ------------------------------------------------------------------
    def _browse_dir(self):
        d = filedialog.askdirectory(initialdir=self.out_dir_var.get())
        if d:
            self.out_dir_var.set(d)

    # ------------------------------------------------------------------
    # Fetch videos
    # ------------------------------------------------------------------
    def _fetch_videos(self):
        token = self.token_var.get().strip()
        client_id = self.client_id_var.get().strip()
        client_secret = self.client_secret_var.get().strip()

        if not token and not (client_id and client_secret):
            messagebox.showerror(
                "Missing Credentials",
                "Please enter either an Access Token or both a Client ID and Client Secret.",
            )
            return

        self.fetch_btn.config(state=tk.DISABLED, text="Fetching…")
        self.tree.delete(*self.tree.get_children())
        self.videos = []
        self.video_check_vars = []
        self.dl_btn.config(state=tk.DISABLED)
        self._log("Connecting to Vimeo API…")

        base_path = self._parse_profile_url(self.profile_url_var.get().strip())
        threading.Thread(
            target=self._run_fetch_worker,
            args=(token, client_id, client_secret, base_path),
            daemon=True,
        ).start()

    def _build_api(self, token: str, client_id: str, client_secret: str) -> "VimeoAPI":
        """Return an authenticated VimeoAPI, obtaining a token via client credentials if needed."""
        if token:
            return VimeoAPI(token, client_id=client_id, client_secret=client_secret)
        self._log("No access token – using client credentials to obtain a token…")
        return VimeoAPI.from_client_credentials(client_id, client_secret)

    def _run_fetch_worker(self, token: str, client_id: str, client_secret: str, base_path: str):
        """Background thread: authenticate, fetch video list, and update the UI."""
        try:
            api = self._build_api(token, client_id, client_secret)
            me = api.get_me()
            username = me.get("name", "Unknown")
            self.api = api
            self.root.after(0, lambda: self.user_lbl.config(
                text=f"Logged in as: {username}", foreground="green"
            ))
            self._log(f"Authenticated as: {username}")
            if base_path != "/me/videos":
                self._log(f"Fetching videos from: {VIMEO_API_BASE}{base_path}")
            self._log("Fetching video list (this may take a moment for large libraries)…")

            videos = api.get_all_videos(
                lambda fetched, total: self._log(f"  … {fetched} / {total} videos fetched"),
                base_path=base_path,
            )
            self.videos = videos
            self.root.after(0, lambda: self._populate_list(videos))
            self._log(f"Found {len(videos)} video(s).")
        except requests.HTTPError as exc:
            code = exc.response.status_code if exc.response is not None else "?"
            if code == 401:
                self._log("ERROR 401 – Authentication failed.")
                self.root.after(
                    0, lambda: messagebox.showerror(
                        "Auth Error",
                        "Authentication failed (401).\n\nPlease check your Access Token, Client ID, and Client Secret.",
                    )
                )
            else:
                self._log(f"HTTP Error {code}: {exc}")
                self.root.after(0, lambda e=exc: messagebox.showerror("API Error", str(e)))
        except Exception as exc:
            self._log(f"Error: {exc}")
            self.root.after(0, lambda e=exc: messagebox.showerror("Error", str(e)))
        finally:
            self.root.after(0, lambda: self.fetch_btn.config(state=tk.NORMAL, text="🔍  Fetch Videos"))

    # ------------------------------------------------------------------
    # Populate the video list treeview
    # ------------------------------------------------------------------
    @staticmethod
    def _format_created(raw: str) -> str:
        """Convert an ISO 8601 timestamp to a local-timezone display string."""
        if not raw:
            return "—"
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return dt.astimezone().strftime("%Y-%m-%d %H:%M")
        except Exception:
            return raw[:16]

    @staticmethod
    def _best_display_quality(video: dict) -> tuple:
        """Return (quality_label, formatted_size) for the best available download."""
        downloads = video.get("download") or []
        if not downloads:
            return "yt-dlp", "—"
        best = sorted(
            downloads,
            key=lambda d: (
                _QUALITY_RANK.get(d.get("quality", "mobile"), 99),
                -(d.get("size") or 0),
            ),
        )[0]
        return best.get("quality", "—"), format_size(best.get("size") or 0)

    def _populate_list(self, videos: list):
        self.tree.delete(*self.tree.get_children())
        self.video_check_vars = []

        for i, v in enumerate(videos):
            name     = v.get("name") or f"Video {i + 1}"
            duration = format_duration(v.get("duration") or 0)
            created  = self._format_created(v.get("created_time", ""))
            quality, size = self._best_display_quality(v)

            var = tk.BooleanVar(value=True)
            self.video_check_vars.append(var)
            self.tree.insert(
                "", tk.END, iid=str(i),
                values=("☑", name, created, duration, quality, size, "Pending"),
            )

        self._update_sel_label()
        self._apply_filter()
        if videos:
            self.dl_btn.config(state=tk.NORMAL)

    # ------------------------------------------------------------------
    # Tree interactions
    # ------------------------------------------------------------------
    def _on_tree_click(self, event):
        region = self.tree.identify("region", event.x, event.y)
        if region != "cell":
            return
        col = self.tree.identify_column(event.x)
        iid = self.tree.identify_row(event.y)
        if iid and col == "#1":
            idx = int(iid)
            self.video_check_vars[idx].set(not self.video_check_vars[idx].get())
            self._refresh_check(iid, idx)
            self._update_sel_label()

    # ------------------------------------------------------------------
    # Filter incomplete videos
    # ------------------------------------------------------------------
    def _apply_filter(self):
        hide = self.hide_incomplete_var.get()
        for i in range(len(self.video_check_vars)):
            iid = str(i)
            if not self.tree.exists(iid):
                continue
            vals = self.tree.item(iid, "values")
            # cols: check(0) name(1) created(2) duration(3) quality(4) size(5) status(6)
            duration = vals[3] if len(vals) > 3 else ""
            quality  = vals[4] if len(vals) > 4 else ""
            size     = vals[5] if len(vals) > 5 else ""
            incomplete = (
                duration in ("", "--:--", "—")
                or quality in ("", "—", "yt-dlp")
                or size in ("", "—", "Unknown")
            )
            if hide and incomplete:
                self.tree.detach(iid)
            else:
                # Re-attach in original order if not already present
                if iid not in self.tree.get_children():
                    # Find the right position (first visible sibling after i)
                    children = list(self.tree.get_children())
                    insert_after = ""
                    for j in range(i - 1, -1, -1):
                        if str(j) in children:
                            insert_after = str(j)
                            break
                    self.tree.reattach(iid, "", self.tree.index(insert_after) + 1 if insert_after else 0)
        self._update_sel_label()

    def _refresh_check(self, iid, idx):
        vals = list(self.tree.item(iid, "values"))
        vals[0] = "☑" if self.video_check_vars[idx].get() else "☐"
        self.tree.item(iid, values=vals)

    def _select_all(self):
        for i, var in enumerate(self.video_check_vars):
            var.set(True)
            self._refresh_check(str(i), i)
        self._update_sel_label()

    def _deselect_all(self):
        for i, var in enumerate(self.video_check_vars):
            var.set(False)
            self._refresh_check(str(i), i)
        self._update_sel_label()

    def _update_sel_label(self):
        sel = sum(v.get() for v in self.video_check_vars)
        total = len(self.video_check_vars)
        self.sel_lbl.config(text=f"{sel} of {total} video(s) selected")

    # ------------------------------------------------------------------
    # Start download
    # ------------------------------------------------------------------
    def _start_download(self):
        selected_idx, out_dir = self._validate_download_inputs()
        if selected_idx is None:
            return
        selected_videos = [self.videos[i] for i in selected_idx]
        self._prepare_download_ui(selected_idx, out_dir, selected_videos)
        self._launch_download_worker(selected_idx, selected_videos, out_dir)

    def _validate_download_inputs(self):
        """Validate selection and output folder. Returns (selected_idx, out_dir) or (None, None)."""
        if not self.videos:
            messagebox.showinfo("No Videos", "Fetch videos first.")
            return None, None

        selected_idx = [i for i, v in enumerate(self.video_check_vars) if v.get()]
        if not selected_idx:
            messagebox.showinfo("Nothing Selected", "Select at least one video before downloading.")
            return None, None

        out_dir = self.out_dir_var.get().strip()
        if not out_dir:
            messagebox.showerror("No Output Folder", "Please select an output folder.")
            return None, None

        try:
            os.makedirs(out_dir, exist_ok=True)
        except OSError as exc:
            messagebox.showerror("Folder Error", str(exc))
            return None, None

        return selected_idx, out_dir

    def _prepare_download_ui(self, selected_idx: list, out_dir: str, selected_videos: list):
        """Reset row statuses and update button states before starting a download."""
        for i in selected_idx:
            vals = list(self.tree.item(str(i), "values"))
            vals[6] = "Queued"
            self.tree.item(str(i), values=vals, tags=())

        self.is_downloading = True
        self.dl_btn.config(state=tk.DISABLED)
        self.fetch_btn.config(state=tk.DISABLED)
        self.cancel_btn.config(state=tk.NORMAL)

        n = len(selected_videos)
        self._log(f"{'─'*52}")
        self._log(f"Starting: {n} video(s) → {out_dir}")
        self._log(f"Quality preference: {self.quality_var.get()}")
        self._log(f"{'─'*52}")

    def _launch_download_worker(self, selected_idx: list, selected_videos: list, out_dir: str):
        """Create and start the DownloadWorker thread."""
        self.worker = DownloadWorker(
            api=self.api,
            videos=selected_videos,
            output_dir=out_dir,
            quality=self.quality_var.get(),
            add_number_prefix=self.num_prefix_var.get(),
            log_cb=self._log,
            progress_cb=lambda *a: self._update_progress(selected_idx, *a),
            video_done_cb=lambda i, s: self._on_video_done(selected_idx[i], s),
            all_done_cb=self._on_all_done,
        )
        self.worker.start()

    # ------------------------------------------------------------------
    # Progress updates (thread-safe via root.after)
    # ------------------------------------------------------------------
    def _update_progress(self, selected_idx, v_idx, v_total, done, total, name):
        def _do():
            if total > 0:
                pct = (done / total) * 100
                self.vid_bar["value"] = pct
                self.vid_pct_lbl.config(
                    text=f"{format_size(done)} / {format_size(total)}  ({pct:.1f}%)"
                )
            else:
                self.vid_bar["value"] = 0
                self.vid_pct_lbl.config(text="Downloading…")

            self.cur_lbl.config(text=f"[{v_idx + 1}/{v_total}]  {name}")

            progress_fraction = (done / total) if total > 0 else 0
            overall_pct = ((v_idx + progress_fraction) / v_total) * 100 if v_total else 0
            self.overall_bar["value"] = overall_pct
            self.overall_lbl.config(
                text=f"Overall: {v_idx + 1} / {v_total}  ({overall_pct:.1f}%)"
            )

            # Highlight current row
            iid = str(selected_idx[v_idx])
            vals = list(self.tree.item(iid, "values"))
            if vals[6] not in ("Done ✓", "Skipped", "Failed ✗"):
                vals[6] = "Downloading…"
                self.tree.item(iid, values=vals, tags=("downloading",))

        self.root.after(0, _do)

    def _on_video_done(self, tree_row_idx, status):
        label_map = {"done": "Done ✓", "failed": "Failed ✗", "skipped": "Skipped"}

        def _do():
            iid = str(tree_row_idx)
            vals = list(self.tree.item(iid, "values"))
            vals[6] = label_map.get(status, status)
            self.tree.item(iid, values=vals, tags=(status,))

        self.root.after(0, _do)

    def _on_all_done(self):
        def _do():
            self.is_downloading = False
            self.dl_btn.config(state=tk.NORMAL)
            self.fetch_btn.config(state=tk.NORMAL)
            self.cancel_btn.config(state=tk.DISABLED)
            self.cur_lbl.config(text="All downloads complete!")
            self.overall_bar["value"] = 100
            self._log("─" * 52)
            self._log("All downloads complete!")

        self.root.after(0, _do)

    # ------------------------------------------------------------------
    # Cancel
    # ------------------------------------------------------------------
    def _cancel(self):
        if self.worker and self.worker.is_alive():
            self.worker.stop()
            self._log("Cancellation requested…")
        self.cancel_btn.config(state=tk.DISABLED)

    # ------------------------------------------------------------------
    # Open output folder
    # ------------------------------------------------------------------
    def _open_folder(self):
        d = self.out_dir_var.get().strip()
        if d and os.path.isdir(d):
            if sys.platform == "win32":
                os.startfile(d)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", d])
            else:
                subprocess.Popen(["xdg-open", d])
        else:
            messagebox.showinfo("Folder Not Found", "Output folder does not exist yet.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    root = tk.Tk()
    app = VimeoDownloaderApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
