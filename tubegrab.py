#!/usr/bin/env python3
"""TubeGrab — a modern GUI for downloading YouTube videos, audio, and playlists.

Wraps yt-dlp with a customtkinter interface: paste a URL, pick video or audio,
choose a quality, and download. Playlists are detected automatically.
"""

import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox

try:
    import customtkinter as ctk
except ImportError:
    raise SystemExit("customtkinter is required:  pip3 install customtkinter")

try:
    import yt_dlp
except ImportError:
    raise SystemExit("yt-dlp is required:  pip3 install yt-dlp")

APP_NAME = "TubeGrab"
DEFAULT_DIR = os.path.expanduser("~/Downloads")

ACCENT = "#e53e3e"          # YouTube-ish red
ACCENT_HOVER = "#c53030"
CARD = ("#f2f2f7", "#232330")
FIELD = ("#e8e8ee", "#2d2d3a")
MUTED = ("#6b7280", "#9ca3af")

VIDEO_QUALITIES = {
    "Best available": "bestvideo+bestaudio/best",
    "Up to 2160p (4K)": "bestvideo[height<=2160]+bestaudio/best[height<=2160]",
    "Up to 1080p": "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
    "Up to 720p": "bestvideo[height<=720]+bestaudio/best[height<=720]",
    "Up to 480p": "bestvideo[height<=480]+bestaudio/best[height<=480]",
}

AUDIO_QUALITIES = {
    "Best (original format)": None,
    "MP3 320 kbps": ("mp3", "320"),
    "MP3 192 kbps": ("mp3", "192"),
    "M4A (AAC)": ("m4a", "0"),
}


class CancelledError(Exception):
    pass


class TubeGrab(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        self.title(APP_NAME)
        self.geometry("920x720")
        self.minsize(820, 640)

        self.events = queue.Queue()
        self.cancel_flag = threading.Event()
        self.info = None  # last fetched metadata
        self.progress_pct = 0.0

        self._build_ui()
        self.after(100, self._poll_events)

    # ------------------------------------------------------------------ UI

    def _build_ui(self):
        root = ctk.CTkFrame(self, fg_color="transparent")
        root.pack(fill="both", expand=True, padx=24, pady=(18, 20))

        # Header
        head = ctk.CTkFrame(root, fg_color="transparent")
        head.pack(fill="x")
        ctk.CTkLabel(head, text="▶", text_color=ACCENT,
                     font=ctk.CTkFont(size=30, weight="bold")).pack(side="left")
        ctk.CTkLabel(head, text=" TubeGrab",
                     font=ctk.CTkFont(size=28, weight="bold")).pack(side="left")
        ctk.CTkLabel(head, text="YouTube video · audio · playlist downloader",
                     text_color=MUTED, font=ctk.CTkFont(size=14)).pack(
                         side="left", padx=14, pady=(8, 0))

        # URL card
        url_card = ctk.CTkFrame(root, fg_color=CARD, corner_radius=14)
        url_card.pack(fill="x", pady=(14, 0))
        row = ctk.CTkFrame(url_card, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(14, 6))
        self.url_var = tk.StringVar()
        self.url_entry = ctk.CTkEntry(
            row, textvariable=self.url_var, height=40, corner_radius=10,
            fg_color=FIELD, border_width=0, font=ctk.CTkFont(size=14),
            placeholder_text="Paste a YouTube video or playlist URL…")
        self.url_entry.pack(side="left", fill="x", expand=True)
        self.fetch_btn = ctk.CTkButton(
            row, text="Fetch Info", width=110, height=40, corner_radius=10,
            fg_color=FIELD, hover_color=("#d8d8e0", "#3a3a4a"),
            text_color=("#111", "#eee"), command=self.fetch_info)
        self.fetch_btn.pack(side="left", padx=(10, 0))

        self.info_var = tk.StringVar(value="Ready when you are — paste a link above.")
        ctk.CTkLabel(url_card, textvariable=self.info_var, text_color=MUTED,
                     anchor="w", justify="left", font=ctk.CTkFont(size=13),
                     wraplength=800).pack(fill="x", padx=18, pady=(0, 12))

        # Options card
        opts = ctk.CTkFrame(root, fg_color=CARD, corner_radius=14)
        opts.pack(fill="x", pady=(12, 0))
        orow = ctk.CTkFrame(opts, fg_color="transparent")
        orow.pack(fill="x", padx=16, pady=14)

        self.mode_var = tk.StringVar(value="Video")
        self.mode_seg = ctk.CTkSegmentedButton(
            orow, values=["Video", "Audio only"], variable=self.mode_var,
            height=36, corner_radius=10, selected_color=ACCENT,
            selected_hover_color=ACCENT_HOVER, command=lambda _: self._refresh_quality())
        self.mode_seg.pack(side="left")

        ctk.CTkLabel(orow, text="Quality", text_color=MUTED,
                     font=ctk.CTkFont(size=13)).pack(side="left", padx=(24, 8))
        self.quality_var = tk.StringVar()
        self.quality_menu = ctk.CTkOptionMenu(
            orow, variable=self.quality_var, width=200, height=36,
            corner_radius=10, fg_color=FIELD, button_color=FIELD,
            button_hover_color=("#d8d8e0", "#3a3a4a"), text_color=("#111", "#eee"))
        self.quality_menu.pack(side="left")

        self.playlist_var = tk.BooleanVar(value=False)
        self.playlist_sw = ctk.CTkSwitch(
            orow, text="Download entire playlist", variable=self.playlist_var,
            progress_color=ACCENT, font=ctk.CTkFont(size=13), state="disabled")
        self.playlist_sw.pack(side="right")

        # Save-to row
        drow = ctk.CTkFrame(opts, fg_color="transparent")
        drow.pack(fill="x", padx=16, pady=(0, 14))
        ctk.CTkLabel(drow, text="Save to", text_color=MUTED,
                     font=ctk.CTkFont(size=13)).pack(side="left", padx=(0, 8))
        self.dir_var = tk.StringVar(value=DEFAULT_DIR)
        ctk.CTkEntry(drow, textvariable=self.dir_var, height=36, corner_radius=10,
                     fg_color=FIELD, border_width=0,
                     font=ctk.CTkFont(size=13)).pack(side="left", fill="x",
                                                     expand=True)
        ctk.CTkButton(drow, text="Browse…", width=100, height=36, corner_radius=10,
                      fg_color=FIELD, hover_color=("#d8d8e0", "#3a3a4a"),
                      text_color=("#111", "#eee"),
                      command=self.choose_dir).pack(side="left", padx=(10, 0))

        # Subtitles row
        srow = ctk.CTkFrame(opts, fg_color="transparent")
        srow.pack(fill="x", padx=16, pady=(0, 14))
        self.subs_var = tk.BooleanVar(value=False)
        self.subs_sw = ctk.CTkSwitch(
            srow, text="Subtitles (.srt)", variable=self.subs_var,
            progress_color=ACCENT, font=ctk.CTkFont(size=13),
            command=self._refresh_subs)
        self.subs_sw.pack(side="left")
        ctk.CTkLabel(srow, text="Languages", text_color=MUTED,
                     font=ctk.CTkFont(size=13)).pack(side="left", padx=(24, 8))
        self.sublang_var = tk.StringVar(value="en")
        self.sublang_entry = ctk.CTkEntry(
            srow, textvariable=self.sublang_var, width=140, height=36,
            corner_radius=10, fg_color=FIELD, border_width=0,
            font=ctk.CTkFont(size=13), state="disabled")
        self.sublang_entry.pack(side="left")
        ctk.CTkLabel(srow, text="comma-separated codes, e.g. en,hi,fr",
                     text_color=MUTED, font=ctk.CTkFont(size=12)).pack(
                         side="left", padx=(8, 0))
        self.autocc_var = tk.BooleanVar(value=True)
        self.autocc_chk = ctk.CTkCheckBox(
            srow, text="Include auto-generated (CC)", variable=self.autocc_var,
            fg_color=ACCENT, hover_color=ACCENT_HOVER,
            font=ctk.CTkFont(size=13), state="disabled")
        self.autocc_chk.pack(side="right")

        # Action row
        act = ctk.CTkFrame(root, fg_color="transparent")
        act.pack(fill="x", pady=(16, 0))
        self.dl_btn = ctk.CTkButton(
            act, text="⬇   Download", width=170, height=44, corner_radius=12,
            fg_color=ACCENT, hover_color=ACCENT_HOVER,
            font=ctk.CTkFont(size=16, weight="bold"), command=self.start_download)
        self.dl_btn.pack(side="left")
        self.cancel_btn = ctk.CTkButton(
            act, text="Cancel", width=100, height=44, corner_radius=12,
            fg_color="transparent", border_width=1, border_color=MUTED,
            text_color=MUTED, hover_color=("#eee", "#333"), state="disabled",
            command=self.cancel_download)
        self.cancel_btn.pack(side="left", padx=10)
        self.status_var = tk.StringVar(value="Ready.")
        ctk.CTkLabel(act, textvariable=self.status_var,
                     font=ctk.CTkFont(size=14)).pack(side="left", padx=12)

        # Progress
        self.progress = ctk.CTkProgressBar(root, height=10, corner_radius=6,
                                           progress_color=ACCENT)
        self.progress.set(0)
        self.progress.pack(fill="x", pady=(14, 0))

        # Log card
        log_card = ctk.CTkFrame(root, fg_color=CARD, corner_radius=14)
        log_card.pack(fill="both", expand=True, pady=(14, 0))
        ctk.CTkLabel(log_card, text="Activity", text_color=MUTED,
                     font=ctk.CTkFont(size=12, weight="bold")).pack(
                         anchor="w", padx=18, pady=(10, 0))
        self.log = ctk.CTkTextbox(log_card, fg_color="transparent",
                                  font=ctk.CTkFont(family="Menlo", size=12),
                                  wrap="word", activate_scrollbars=True)
        self.log.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.log.configure(state="disabled")

        self._refresh_quality()

    def _refresh_quality(self):
        table = VIDEO_QUALITIES if self.mode_var.get() == "Video" else AUDIO_QUALITIES
        self.quality_menu.configure(values=list(table))
        self.quality_var.set(next(iter(table)))

    def _refresh_subs(self):
        state = "normal" if self.subs_var.get() else "disabled"
        self.sublang_entry.configure(state=state)
        self.autocc_chk.configure(state=state)

    def _log(self, msg):
        self.log.configure(state="normal")
        self.log.insert("end", msg + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def choose_dir(self):
        chosen = filedialog.askdirectory(initialdir=self.dir_var.get() or DEFAULT_DIR)
        if chosen:
            self.dir_var.set(chosen)

    # ----------------------------------------------------------- Fetch info

    def fetch_info(self):
        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning(APP_NAME, "Please paste a YouTube URL first.")
            return
        self.fetch_btn.configure(state="disabled")
        self.info_var.set("Fetching info…")
        threading.Thread(target=self._fetch_worker, args=(url,), daemon=True).start()

    def _fetch_worker(self, url):
        opts = {"quiet": True, "extract_flat": "in_playlist", "skip_download": True,
                "socket_timeout": 20}
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
            self.events.put(("info", info))
        except Exception as exc:
            self.events.put(("info_error", str(exc)))

    # ------------------------------------------------------------ Download

    def start_download(self):
        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning(APP_NAME, "Please paste a YouTube URL first.")
            return
        outdir = self.dir_var.get().strip() or DEFAULT_DIR
        os.makedirs(outdir, exist_ok=True)

        self.cancel_flag.clear()
        self.dl_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self.progress.set(0)
        self.status_var.set("Starting…")
        self._log(f"Downloading: {url}")

        ydl_opts = {
            "outtmpl": os.path.join(outdir, "%(title)s.%(ext)s"),
            "progress_hooks": [self._hook],
            "noplaylist": not self.playlist_var.get(),
            "quiet": True,
            "no_warnings": True,
            "retries": 10,
            "fragment_retries": 10,
            "socket_timeout": 30,
            "continuedl": True,
        }
        if self.playlist_var.get():
            ydl_opts["outtmpl"] = os.path.join(
                outdir, "%(playlist_title)s", "%(playlist_index)02d - %(title)s.%(ext)s")

        if self.mode_var.get() == "Video":
            ydl_opts["format"] = VIDEO_QUALITIES[self.quality_var.get()]
            ydl_opts["merge_output_format"] = "mp4"
        else:
            ydl_opts["format"] = "bestaudio/best"
            choice = AUDIO_QUALITIES[self.quality_var.get()]
            if choice:
                codec, bitrate = choice
                ydl_opts["postprocessors"] = [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": codec,
                    "preferredquality": bitrate,
                }]

        if self.subs_var.get():
            langs = [l.strip() for l in self.sublang_var.get().split(",") if l.strip()]
            ydl_opts["writesubtitles"] = True
            ydl_opts["writeautomaticsub"] = self.autocc_var.get()
            ydl_opts["subtitleslangs"] = langs or ["en"]
            ydl_opts["subtitlesformat"] = "best"
            ydl_opts.setdefault("postprocessors", []).append(
                {"key": "FFmpegSubtitlesConvertor", "format": "srt"})
            self._log(f"Subtitles enabled: {', '.join(langs or ['en'])}"
                      + (" (incl. auto-CC)" if self.autocc_var.get() else ""))

        threading.Thread(target=self._download_worker, args=(url, ydl_opts),
                         daemon=True).start()

    def _download_worker(self, url, ydl_opts):
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            self.events.put(("done", None))
        except CancelledError:
            self.events.put(("cancelled", None))
        except Exception as exc:
            self.events.put(("error", str(exc)))

    def _hook(self, d):
        if self.cancel_flag.is_set():
            raise CancelledError()
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes", 0)
            pct = done / total * 100 if total else 0
            speed = d.get("speed")
            speed_s = f"{speed / 1_048_576:.1f} MB/s" if speed else "…"
            name = os.path.basename(d.get("filename", ""))
            self.events.put(("progress", (pct, f"{name}  —  {pct:.0f}%  @ {speed_s}")))
        elif d["status"] == "finished":
            self.events.put(("progress", (100, "Processing (merge/convert)…")))
            self.events.put(("log", f"Finished: {os.path.basename(d.get('filename', ''))}"))

    def cancel_download(self):
        self.cancel_flag.set()
        self.status_var.set("Cancelling…")

    # ------------------------------------------------------- Event polling

    def _poll_events(self):
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "progress":
                    pct, text = payload
                    self.progress_pct = pct
                    self.progress.set(pct / 100)
                    self.status_var.set(text)
                elif kind == "log":
                    self._log(payload)
                elif kind == "done":
                    self.progress.set(1)
                    self.status_var.set("Done ✔")
                    self._log("All downloads complete.")
                    self._reset_buttons()
                elif kind == "cancelled":
                    self.status_var.set("Cancelled.")
                    self._log("Download cancelled.")
                    self._reset_buttons()
                elif kind == "error":
                    self.status_var.set("Error — see activity log.")
                    self._log(f"ERROR: {payload}")
                    self._reset_buttons()
                elif kind == "info":
                    self._show_info(payload)
                elif kind == "info_error":
                    self.info_var.set(f"Could not fetch info: {payload}")
                    self.fetch_btn.configure(state="normal")
        except queue.Empty:
            pass
        self.after(100, self._poll_events)

    def _show_info(self, info):
        self.info = info
        self.fetch_btn.configure(state="normal")
        if info.get("_type") == "playlist" or "entries" in info:
            count = len(list(info.get("entries") or []))
            self.info_var.set(f"Playlist:  {info.get('title', '?')}   ·   {count} videos")
            self.playlist_sw.configure(state="normal")
            self.playlist_var.set(True)
            self._log(f"Detected playlist: {info.get('title')} with {count} videos")
        else:
            dur = info.get("duration") or 0
            mins, secs = divmod(int(dur), 60)
            up = info.get("uploader") or info.get("channel") or "?"
            self.info_var.set(
                f"Video:  {info.get('title', '?')}   ·   {up}   ·   {mins}:{secs:02d}")
            self.playlist_var.set(False)
            self.playlist_sw.configure(state="disabled")
            self._log(f"Detected video: {info.get('title')}")

    def _reset_buttons(self):
        self.dl_btn.configure(state="normal")
        self.cancel_btn.configure(state="disabled")


if __name__ == "__main__":
    TubeGrab().mainloop()
