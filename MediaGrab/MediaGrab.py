"""
MediaGrab - a desktop downloader for YouTube, Instagram, TikTok, Facebook,
X/Twitter and 1000+ other sites. Paste a link, pick a video resolution or MP3,
click Download.
"""
import io
import os
import sys
import json
import queue
import threading
import subprocess
import urllib.request

import customtkinter as ctk
from tkinter import filedialog, messagebox
from PIL import Image, ImageDraw

import yt_dlp
import imageio_ffmpeg

APP_NAME = "MediaGrab"
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".mediagrab")
CONFIG_FILE = os.path.join(CONFIG_DIR, "settings.json")
DEFAULT_DIR = os.path.join(os.path.expanduser("~"), "Downloads", "MediaGrab")

# ---------- colors ----------
BG = "#0f1115"
PANEL = "#171a21"
CARD = "#1e222b"
CARD_HOVER = "#262b36"
BORDER = "#2b303c"
ACCENT = "#ff4d6d"
ACCENT_HOVER = "#ff6b85"
TEXT = "#eef0f4"
MUTED = "#8b93a5"
OK = "#3ddc97"

ctk.set_appearance_mode("dark")


def resource(name):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


def human_size(n):
    if not n:
        return "—"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
    return f"{n:.1f} TB"


def human_time(sec):
    if not sec:
        return ""
    sec = int(sec)
    h, m, s = sec // 3600, (sec % 3600) // 60, sec % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def fmt_size(f):
    return f.get("filesize") or f.get("filesize_approx") or 0


def quality_tag(h):
    if h >= 4320: return "8K"
    if h >= 2160: return "4K"
    if h >= 1440: return "2K"
    if h >= 1080: return "Full HD"
    if h >= 720:  return "HD"
    return "SD"


def load_config():
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(cfg):
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        pass


def placeholder_thumb(w=256, h=144):
    img = Image.new("RGB", (w, h), CARD)
    d = ImageDraw.Draw(img)
    cx, cy = w // 2, h // 2
    d.polygon([(cx - 16, cy - 20), (cx - 16, cy + 20), (cx + 20, cy)], fill=BORDER)
    return img


def rounded(img, radius=14):
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, img.size[0], img.size[1]], radius, fill=255)
    out = Image.new("RGBA", img.size)
    out.paste(img.convert("RGB"), (0, 0), mask)
    return out


def open_path(path):
    if sys.platform.startswith("win"):
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


# ======================================================================
class OptionCard(ctk.CTkFrame):
    """One selectable quality option (e.g. 1080p / Full HD / 85 MB)."""

    def __init__(self, master, title, tag, detail, size, on_click):
        super().__init__(master, fg_color=CARD, corner_radius=12, border_width=2,
                         border_color=CARD, cursor="hand2")
        self.on_click = on_click
        self.grid_columnconfigure(1, weight=1)

        self.dot = ctk.CTkLabel(self, text="○", font=ctk.CTkFont(size=18), text_color=MUTED, width=28)
        self.dot.grid(row=0, column=0, rowspan=2, padx=(14, 6), pady=4)
        t = ctk.CTkLabel(self, text=title, font=ctk.CTkFont(size=15, weight="bold"), text_color=TEXT, anchor="w", height=22)
        t.grid(row=0, column=1, sticky="w", pady=(7, 0))
        d = ctk.CTkLabel(self, text=detail, font=ctk.CTkFont(size=12), text_color=MUTED, anchor="w", height=18)
        d.grid(row=1, column=1, sticky="w", pady=(0, 7))
        self.badge = ctk.CTkLabel(self, text=f" {tag} ", font=ctk.CTkFont(size=11, weight="bold"),
                                  fg_color=BORDER, corner_radius=6, text_color=TEXT)
        self.badge.grid(row=0, column=2, rowspan=2, padx=8)
        s = ctk.CTkLabel(self, text=size, font=ctk.CTkFont(size=13), text_color=MUTED, width=80, anchor="e")
        s.grid(row=0, column=3, rowspan=2, padx=(4, 16))

        for w in (self, self.dot, t, d, self.badge, s):
            w.bind("<Button-1>", lambda e: self.on_click(self))
            w.bind("<Double-Button-1>", lambda e: self.on_click(self, download=True))
            w.bind("<Enter>", lambda e: self._hover(True))
            w.bind("<Leave>", lambda e: self._hover(False))
        self.selected = False

    def _hover(self, on):
        if not self.selected:
            self.configure(fg_color=CARD_HOVER if on else CARD)

    def set_selected(self, sel):
        self.selected = sel
        self.configure(border_color=ACCENT if sel else CARD, fg_color=CARD_HOVER if sel else CARD)
        self.dot.configure(text="●" if sel else "○", text_color=ACCENT if sel else MUTED)
        self.badge.configure(fg_color=ACCENT if sel else BORDER)


class HistoryItem(ctk.CTkFrame):
    def __init__(self, master, name, kind, path):
        super().__init__(master, fg_color=CARD, corner_radius=10)
        self.path = path
        self.grid_columnconfigure(1, weight=1)
        icon = "🎵" if kind == "audio" else "🎬"
        ctk.CTkLabel(self, text=icon, font=ctk.CTkFont(size=18), width=30).grid(row=0, column=0, rowspan=2, padx=(10, 4), pady=8)
        short = name if len(name) <= 26 else name[:25] + "…"
        ctk.CTkLabel(self, text=short, font=ctk.CTkFont(size=12, weight="bold"), text_color=TEXT,
                     anchor="w").grid(row=0, column=1, sticky="w", pady=(8, 0))
        self.state_lbl = ctk.CTkLabel(self, text="Waiting…", font=ctk.CTkFont(size=11), text_color=MUTED, anchor="w")
        self.state_lbl.grid(row=1, column=1, sticky="w", pady=(0, 2))
        self.bar = ctk.CTkProgressBar(self, height=4, progress_color=ACCENT, fg_color=BORDER)
        self.bar.set(0)
        self.bar.grid(row=2, column=0, columnspan=3, sticky="ew", padx=10, pady=(0, 8))
        self.open_btn = ctk.CTkButton(self, text="Open", width=54, height=26, fg_color=BORDER,
                                      hover_color=CARD_HOVER, command=self.open, state="disabled")
        self.open_btn.grid(row=0, column=2, rowspan=2, padx=8)

    def progress(self, frac, text):
        self.bar.set(frac)
        self.state_lbl.configure(text=text, text_color=MUTED)

    def finished(self, path):
        self.path = path
        self.bar.set(1)
        self.bar.configure(progress_color=OK)
        self.state_lbl.configure(text="✔ Done", text_color=OK)
        self.open_btn.configure(state="normal", fg_color=ACCENT, hover_color=ACCENT_HOVER)

    def failed(self, msg):
        self.bar.configure(progress_color="#e5484d")
        self.state_lbl.configure(text="✖ " + msg[:40], text_color="#e5484d")

    def open(self):
        if self.path and os.path.exists(self.path):
            if sys.platform.startswith("win"):
                subprocess.Popen(["explorer", "/select,", os.path.normpath(self.path)])
            else:
                open_path(os.path.dirname(self.path))


# ======================================================================
class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.cfg = load_config()
        self.title(APP_NAME)
        self.geometry("1100x780")
        self.minsize(900, 600)
        self.configure(fg_color=BG)
        try:
            if sys.platform.startswith("win"):
                self.iconbitmap(resource("icon.ico"))
        except Exception:
            pass

        self.q = queue.Queue()
        self.info = None
        self.cards = []
        self.selected = None
        self.mode = "Video"
        self.video_opts, self.audio_opts = [], []

        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=0)
        self.grid_rowconfigure(0, weight=1)

        self._build_main()
        self._build_side()
        self.after(80, self._poll)
        self.bind("<Control-v>", lambda e: self.after(10, self._autofetch_if_link))

    # ------------------------------------------------------------ UI
    def _build_main(self):
        main = ctk.CTkFrame(self, fg_color=BG)
        main.grid(row=0, column=0, sticky="nsew", padx=(24, 12), pady=20)
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(3, weight=1)

        # header
        head = ctk.CTkFrame(main, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew")
        logo = ctk.CTkLabel(head, text="▼", font=ctk.CTkFont(size=20, weight="bold"), text_color="white",
                            fg_color=ACCENT, corner_radius=10, width=40, height=40)
        logo.pack(side="left")
        ctk.CTkLabel(head, text=APP_NAME, font=ctk.CTkFont(size=24, weight="bold"),
                     text_color=TEXT).pack(side="left", padx=12)
        ctk.CTkLabel(head, text="YouTube · Instagram · TikTok · Facebook · X · 1000+ sites",
                     font=ctk.CTkFont(size=12), text_color=MUTED).pack(side="left", padx=4, pady=(6, 0))

        # link bar
        bar = ctk.CTkFrame(main, fg_color=PANEL, corner_radius=16, border_width=1, border_color=BORDER)
        bar.grid(row=1, column=0, sticky="ew", pady=(18, 14))
        bar.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(bar, text="🔗", font=ctk.CTkFont(size=18)).grid(row=0, column=0, padx=(16, 4))
        self.url = ctk.CTkEntry(bar, placeholder_text="Paste a video link here…", height=48, border_width=0,
                                fg_color=PANEL, font=ctk.CTkFont(size=15), text_color=TEXT)
        self.url.grid(row=0, column=1, sticky="ew", padx=4, pady=6)
        self.url.bind("<Return>", lambda e: self.fetch())
        ctk.CTkButton(bar, text="Paste", width=80, height=38, fg_color=CARD, hover_color=CARD_HOVER,
                      command=self.paste).grid(row=0, column=2, padx=4)
        self.fetch_btn = ctk.CTkButton(bar, text="Search", width=110, height=38, fg_color=ACCENT,
                                       hover_color=ACCENT_HOVER, font=ctk.CTkFont(size=14, weight="bold"),
                                       command=self.fetch)
        self.fetch_btn.grid(row=0, column=3, padx=(4, 8))

        # video info card
        info = ctk.CTkFrame(main, fg_color=PANEL, corner_radius=16)
        info.grid(row=2, column=0, sticky="ew")
        info.grid_columnconfigure(1, weight=1)
        self.thumb_img = ctk.CTkImage(rounded(placeholder_thumb()), size=(208, 117))
        self.thumb = ctk.CTkLabel(info, text="", image=self.thumb_img)
        self.thumb.grid(row=0, column=0, rowspan=4, padx=14, pady=14)
        self.title_lbl = ctk.CTkLabel(info, text="No video yet", font=ctk.CTkFont(size=18, weight="bold"),
                                      text_color=TEXT, anchor="w", justify="left", wraplength=480)
        self.title_lbl.grid(row=0, column=1, sticky="sw", padx=(4, 16), pady=(12, 2))
        self.meta_lbl = ctk.CTkLabel(info, text="Paste a link and press Search to see all the qualities.",
                                     font=ctk.CTkFont(size=13), text_color=MUTED, anchor="w", justify="left")
        self.meta_lbl.grid(row=1, column=1, sticky="nw", padx=(4, 16))
        self.site_lbl = ctk.CTkLabel(info, text="", font=ctk.CTkFont(size=11, weight="bold"),
                                     fg_color=PANEL, corner_radius=6, text_color=TEXT)
        self.site_lbl.grid(row=2, column=1, sticky="nw", padx=(4, 16), pady=(8, 0))

        # options area
        opt = ctk.CTkFrame(main, fg_color=PANEL, corner_radius=16)
        opt.grid(row=3, column=0, sticky="nsew", pady=14)
        opt.grid_columnconfigure(0, weight=1)
        opt.grid_rowconfigure(1, weight=1)
        top = ctk.CTkFrame(opt, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=14, pady=(14, 6))
        self.tabs = ctk.CTkSegmentedButton(top, values=["Video", "Audio (MP3)"], command=self._switch_tab,
                                           selected_color=ACCENT, selected_hover_color=ACCENT_HOVER,
                                           unselected_color=CARD, unselected_hover_color=CARD_HOVER,
                                           fg_color=CARD, font=ctk.CTkFont(size=13, weight="bold"), height=34)
        self.tabs.set("Video")
        self.tabs.pack(side="left")
        self.count_lbl = ctk.CTkLabel(top, text="", text_color=MUTED, font=ctk.CTkFont(size=12))
        self.count_lbl.pack(side="right")
        self.list = ctk.CTkScrollableFrame(opt, fg_color="transparent", scrollbar_button_color=BORDER)
        self.list.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
        self.list.grid_columnconfigure(0, weight=1)
        self.empty_lbl = ctk.CTkLabel(self.list, text="Your download options will appear here",
                                      text_color=MUTED, font=ctk.CTkFont(size=13))
        self.empty_lbl.grid(row=0, column=0, pady=40)

        # bottom bar
        bottom = ctk.CTkFrame(main, fg_color="transparent")
        bottom.grid(row=4, column=0, sticky="ew")
        bottom.grid_columnconfigure(0, weight=1)
        self.dl_btn = ctk.CTkButton(bottom, text="⬇   Download", height=52, corner_radius=14,
                                    fg_color=ACCENT, hover_color=ACCENT_HOVER,
                                    font=ctk.CTkFont(size=17, weight="bold"), command=self.download)
        self.dl_btn.grid(row=0, column=0, sticky="ew")
        self.status = ctk.CTkLabel(bottom, text="Ready", text_color=MUTED, font=ctk.CTkFont(size=12), anchor="w")
        self.status.grid(row=1, column=0, sticky="w", pady=(6, 0))

    def _build_side(self):
        side = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=0, width=310)
        side.grid(row=0, column=1, sticky="nsew")
        side.grid_propagate(False)
        side.grid_columnconfigure(0, weight=1)
        side.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(side, text="Downloads", font=ctk.CTkFont(size=18, weight="bold"),
                     text_color=TEXT, anchor="w").grid(row=0, column=0, sticky="w", padx=18, pady=(24, 10))
        self.hist = ctk.CTkScrollableFrame(side, fg_color="transparent", scrollbar_button_color=BORDER)
        self.hist.grid(row=1, column=0, sticky="nsew", padx=8)
        self.hist.grid_columnconfigure(0, weight=1)
        self.hist_empty = ctk.CTkLabel(self.hist, text="Nothing downloaded yet", text_color=MUTED)
        self.hist_empty.grid(row=0, column=0, pady=30)
        self.hist_items = []

        sett = ctk.CTkFrame(side, fg_color=CARD, corner_radius=12)
        sett.grid(row=2, column=0, sticky="ew", padx=14, pady=14)
        sett.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(sett, text="Save to", text_color=MUTED, font=ctk.CTkFont(size=12)).grid(
            row=0, column=0, sticky="w", padx=12, pady=(10, 0))
        self.folder = self.cfg.get("folder", DEFAULT_DIR)
        self.folder_lbl = ctk.CTkLabel(sett, text=self._short(self.folder), text_color=TEXT,
                                       font=ctk.CTkFont(size=12), anchor="w")
        self.folder_lbl.grid(row=1, column=0, sticky="w", padx=12)
        row = ctk.CTkFrame(sett, fg_color="transparent")
        row.grid(row=2, column=0, sticky="ew", padx=10, pady=(6, 8))
        ctk.CTkButton(row, text="Change", width=80, height=28, fg_color=BORDER, hover_color=CARD_HOVER,
                      command=self.browse).pack(side="left")
        ctk.CTkButton(row, text="Open folder", width=100, height=28, fg_color=BORDER, hover_color=CARD_HOVER,
                      command=self.open_folder).pack(side="left", padx=6)

        ctk.CTkLabel(sett, text="Private posts: use login from", text_color=MUTED,
                     font=ctk.CTkFont(size=12)).grid(row=3, column=0, sticky="w", padx=12)
        self.cookies = ctk.CTkOptionMenu(sett, values=["none", "chrome", "edge", "firefox", "brave", "opera"],
                                         fg_color=BORDER, button_color=BORDER, button_hover_color=CARD_HOVER,
                                         height=28, command=self._save_cookie)
        self.cookies.set(self.cfg.get("cookies", "none"))
        self.cookies.grid(row=4, column=0, sticky="ew", padx=12, pady=(4, 12))

    # ------------------------------------------------------------ small helpers
    @staticmethod
    def _short(p):
        return p if len(p) <= 36 else "…" + p[-35:]

    def _save_cookie(self, v):
        self.cfg["cookies"] = v
        save_config(self.cfg)

    def paste(self):
        try:
            text = self.clipboard_get().strip()
        except Exception:
            return
        self.url.delete(0, "end")
        self.url.insert(0, text)
        self.fetch()

    def _autofetch_if_link(self):
        if self.url.get().strip().startswith("http") and self.focus_get() == self.url._entry:
            self.fetch()

    def browse(self):
        d = filedialog.askdirectory(initialdir=self.folder)
        if d:
            self.folder = d
            self.folder_lbl.configure(text=self._short(d))
            self.cfg["folder"] = d
            save_config(self.cfg)

    def open_folder(self):
        os.makedirs(self.folder, exist_ok=True)
        open_path(self.folder)

    def base_opts(self):
        o = {"quiet": True, "no_warnings": True, "ffmpeg_location": FFMPEG, "noplaylist": True}
        if self.cookies.get() != "none":
            o["cookiesfrombrowser"] = (self.cookies.get(),)
        return o

    def _poll(self):
        try:
            while True:
                fn, args = self.q.get_nowait()
                fn(*args)
        except queue.Empty:
            pass
        self.after(80, self._poll)

    def ui(self, fn, *args):
        """Run fn on the GUI thread."""
        self.q.put((fn, args))

    # ------------------------------------------------------------ step 1: read link
    def fetch(self):
        link = self.url.get().strip()
        if not link:
            self.status.configure(text="Paste a link first")
            return
        self.fetch_btn.configure(state="disabled", text="Searching…")
        self.status.configure(text="Reading link…")
        threading.Thread(target=self._fetch, args=(link,), daemon=True).start()

    def _fetch(self, link):
        try:
            with yt_dlp.YoutubeDL(self.base_opts()) as ydl:
                info = ydl.extract_info(link, download=False)
            if info.get("_type") == "playlist" and info.get("entries"):
                info = next(e for e in info["entries"] if e)
            thumb = None
            url = info.get("thumbnail")
            if url:
                try:
                    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                    data = urllib.request.urlopen(req, timeout=10).read()
                    thumb = Image.open(io.BytesIO(data)).convert("RGB")
                except Exception:
                    thumb = None
            self.ui(self._show, info, thumb)
        except Exception as e:
            self.ui(self._fetch_failed, str(e))

    def _fetch_failed(self, msg):
        self.fetch_btn.configure(state="normal", text="Search")
        self.status.configure(text="Could not read this link")
        messagebox.showerror(APP_NAME, "Could not read this link.\n\n" + msg[:600])

    def _show(self, info, thumb):
        self.fetch_btn.configure(state="normal", text="Search")
        self.info = info

        img = thumb or placeholder_thumb()
        img = img.copy()
        img.thumbnail((512, 288))
        canvas = Image.new("RGB", (512, 288), "#000000")
        canvas.paste(img, ((512 - img.width) // 2, (288 - img.height) // 2))
        self.thumb_img = ctk.CTkImage(rounded(canvas, 28), size=(208, 117))
        self.thumb.configure(image=self.thumb_img)

        self.title_lbl.configure(text=(info.get("title") or "Untitled")[:120])
        who = info.get("uploader") or info.get("channel") or ""
        dur = human_time(info.get("duration"))
        views = info.get("view_count")
        parts = [p for p in (who, dur, f"{views:,} views" if views else "") if p]
        self.meta_lbl.configure(text="  •  ".join(parts))
        site = info.get("extractor_key") or ""
        self.site_lbl.configure(text=f"  {site}  ", fg_color=BORDER if site else PANEL)

        formats = info.get("formats") or []
        audios = [f for f in formats if f.get("acodec") not in (None, "none") and f.get("vcodec") in (None, "none")]
        best_audio = max((fmt_size(f) for f in audios), default=0)

        heights = {}
        fps_map = {}
        for f in formats:
            h = f.get("height")
            if h and f.get("vcodec") not in (None, "none"):
                size = fmt_size(f)
                if f.get("acodec") in (None, "none") and size:
                    size += best_audio
                heights[h] = max(heights.get(h, 0), size)
                if f.get("fps"):
                    fps_map[h] = max(fps_map.get(h, 0), int(f["fps"]))
        if not heights and info.get("height"):
            heights[info["height"]] = 0

        self.video_opts = []
        for h in sorted(heights, reverse=True):
            fps = f" · {fps_map[h]} fps" if fps_map.get(h) else ""
            self.video_opts.append({"kind": "video", "height": h, "title": f"{h}p",
                                    "tag": quality_tag(h), "detail": f"MP4 video with sound{fps}",
                                    "size": human_size(heights[h])})
        if not self.video_opts:
            self.video_opts.append({"kind": "video", "height": None, "title": "Best quality",
                                    "tag": "AUTO", "detail": "MP4 video with sound", "size": "—"})

        dur_s = info.get("duration") or 0
        self.audio_opts = []
        for kbps, tag in (("320", "BEST"), ("192", "HIGH"), ("128", "NORMAL")):
            self.audio_opts.append({"kind": "audio", "kbps": kbps, "title": f"MP3 · {kbps} kbps",
                                    "tag": tag, "detail": "Audio only",
                                    "size": human_size(dur_s * int(kbps) * 125) if dur_s else "—"})

        self.tabs.set("Video")
        self._switch_tab("Video")
        self.status.configure(text="Pick a quality, then press Download (or double-click it)")

    def _switch_tab(self, value):
        self.mode = "Video" if value == "Video" else "Audio"
        for c in self.cards:
            c.destroy()
        self.cards, self.selected = [], None
        opts = self.video_opts if self.mode == "Video" else self.audio_opts
        if not self.info:
            return
        self.empty_lbl.grid_remove()
        for i, o in enumerate(opts):
            card = OptionCard(self.list, o["title"], o["tag"], o["detail"], o["size"], self._select)
            card.opt = o
            card.grid(row=i, column=0, sticky="ew", padx=6, pady=3)
            self.cards.append(card)
        if self.cards:
            self._select(self.cards[0])
        word = "resolutions" if self.mode == "Video" else "audio qualities"
        self.count_lbl.configure(text=f"{len(opts)} {word} available")

    def _select(self, card, download=False):
        for c in self.cards:
            c.set_selected(c is card)
        self.selected = card
        if download:
            self.download()

    # ------------------------------------------------------------ step 2: download
    def download(self):
        if not self.info:
            self.fetch()
            return
        if not self.selected:
            self.status.configure(text="Pick a quality first")
            return
        opt = self.selected.opt
        os.makedirs(self.folder, exist_ok=True)
        title = self.info.get("title") or "video"
        label = f"{title}  [{opt['title']}]"

        if not self.hist_items:
            self.hist_empty.grid_remove()
        item = HistoryItem(self.hist, label, opt["kind"], None)
        for i, it in enumerate(self.hist_items):      # newest on top
            it.grid(row=i + 1, column=0, sticky="ew", padx=4, pady=4)
        item.grid(row=0, column=0, sticky="ew", padx=4, pady=4)
        self.hist_items.insert(0, item)

        link = self.info.get("webpage_url") or self.url.get().strip()
        self.status.configure(text=f"Started: {opt['title']}")
        threading.Thread(target=self._download, args=(link, opt, self.folder, item), daemon=True).start()

    def _download(self, link, opt, folder, item):
        def hook(d):
            if d["status"] == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                done = d.get("downloaded_bytes", 0)
                frac = done / total if total else 0
                speed = f"{human_size(d.get('speed'))}/s" if d.get("speed") else ""
                eta = f" · {human_time(d.get('eta'))} left" if d.get("eta") else ""
                self.ui(item.progress, frac, f"{int(frac * 100)}%  ·  {speed}{eta}")
            elif d["status"] == "finished":
                self.ui(item.progress, 1, "Finishing (merging / converting)…")

        o = self.base_opts()
        o.update({"outtmpl": os.path.join(folder, "%(title).150B [%(id)s].%(ext)s"),
                  "progress_hooks": [hook], "windowsfilenames": True})
        if opt["kind"] == "audio":
            o.update({"format": "bestaudio/best",
                      "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3",
                                          "preferredquality": opt["kbps"]},
                                         {"key": "FFmpegMetadata"}]})
        else:
            h = opt["height"]
            o["format"] = (f"bestvideo[height={h}][ext=mp4]+bestaudio[ext=m4a]/"
                           f"bestvideo[height={h}]+bestaudio/best[height={h}]/best[height<={h}]/best"
                           if h else "bestvideo+bestaudio/best")
            o["merge_output_format"] = "mp4"
        try:
            with yt_dlp.YoutubeDL(o) as ydl:
                info = ydl.extract_info(link, download=True)
                path = ydl.prepare_filename(info)
            base = os.path.splitext(path)[0]
            if opt["kind"] == "audio":
                path = base + ".mp3"
            elif os.path.exists(base + ".mp4"):
                path = base + ".mp4"
            self.ui(item.finished, path)
            self.ui(self.status.configure, text="✔ Saved to " + self._short(folder))
        except Exception as e:
            msg = str(e).replace("ERROR: ", "")
            self.ui(item.failed, msg)
            self.ui(self.status.configure, text="Download failed: " + msg[:90])


if __name__ == "__main__":
    App().mainloop()
