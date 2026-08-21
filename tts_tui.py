# -*- coding: utf-8 -*-
"""
TTS STUDIO — bản TUI đầy đủ (Textual), y chang layout bản web.
  ngochuyen            → mở app
  python tts_tui.py --file x.md --out y.mp3  → render nhanh, không vào app
Dùng chung dữ liệu với bản web: sản phẩm/, kho từ động, scan_draft.json, tui_state.json.
"""
import os
import sys
import re
import json
import uuid
import subprocess
import tempfile
from pathlib import Path
from datetime import datetime

if os.name == "nt":
    os.system("")
    subprocess.run("chcp 65001 >nul", shell=True, capture_output=True)

BASE = Path(__file__).parent
sys.path.insert(0, r"C:\Users\Khang\Desktop\dịch tryện\Nghiên cứu giọng kênh\piper_ngochuyen")

import tts_ngochuyen as tts  # noqa: E402
import loanwords_dynamic as lw  # noqa: E402

FFPROBE = r"C:\Users\Khang\Desktop\ffmpeg\ffmpeg-8.1.2-essentials_build\bin\ffprobe.exe"
FF = tts.FFMPEG
PRODUCT = BASE / "sản phẩm"
VIDEO_DIR = BASE / "video_output"
DRAFT_FILE = BASE / "scan_draft.json"
STATE_FILE = BASE / "tui_state.json"

from textual import work  # noqa: E402
from textual.app import App, ComposeResult  # noqa: E402
from textual.containers import Horizontal, Vertical, VerticalScroll  # noqa: E402
from textual.screen import ModalScreen  # noqa: E402
from textual.widgets import (  # noqa: E402
    Button, DataTable, Footer, Input, Label, ProgressBar, Select, Static, TextArea,
)

VIEWS = ["home", "products", "words", "video", "settings"]
VIEW_TITLES = {"home": "Chuyển văn bản", "products": "Sản phẩm", "words": "Kho từ đọc",
               "video": "Video", "settings": "Cài đặt"}
NAV_ICONS = {"home": "⌨", "products": "≡", "words": "📖", "video": "🎬", "settings": "⚙"}
QUALITY_MAP = {"480p": (854, 480), "720p": (1280, 720), "1080p": (1920, 1080), "4k": (3840, 2160)}

DEFAULT_STATE = {
    "text": "", "speed": "1.3", "volume": "1.0", "pitch": "0", "eq": "none",
    "pause": 0.18, "pause_comma": 0.18, "noise_scale": 0.667, "noise_w": 0.8,
    "video": {"img": "", "text": "", "color": "#FFFFFF", "size": "48", "y": "85",
              "bright": "100", "quality": "1080p", "fps": "30", "crf": "23",
              "preset": "fast", "out": ""},
}


def save_state(st):
    STATE_FILE.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")


def load_draft():
    try:
        return json.loads(DRAFT_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def load_state():
    st = json.loads(json.dumps(DEFAULT_STATE))
    try:
        d = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        for k, v in d.items():
            if k == "video":
                st["video"].update(v)
            else:
                st[k] = v
    except Exception:
        pass
    # các ô UI (Input/Select) chỉ nhận chuỗi — state cũ có thể lưu số
    for k in ("speed", "volume", "pitch", "eq", "text"):
        st[k] = str(st[k])
    if st["pitch"] not in ("0", "1", "2", "-1", "-2"):
        try:
            st["pitch"] = str(int(float(st["pitch"])))
        except Exception:
            st["pitch"] = "0"
        if st["pitch"] not in ("0", "1", "2", "-1", "-2"):
            st["pitch"] = "0"
    for k in st["video"]:
        st["video"][k] = str(st["video"][k])
    return st


def save_draft(items):
    DRAFT_FILE.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")


def audio_duration(p: Path) -> float:
    try:
        r = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration",
                            "-of", "default=noprint_wrappers=1:nokey=1", str(p)],
                           capture_output=True, text=True, timeout=10)
        return float(r.stdout.strip())
    except Exception:
        return 0.0


def fmt_dur(sec):
    sec = int(sec or 0)
    return f"{sec//60}:{sec%60:02d}"


class InputScreen(ModalScreen[str]):
    """Hộp nhập một dòng (trả về chuỗi hoặc None)."""
    BINDINGS = [("escape", "cancel", "Hủy")]

    def __init__(self, prompt: str, value: str = ""):
        super().__init__()
        self.prompt = prompt
        self.value = value

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-box"):
            yield Label(self.prompt)
            yield Input(value=self.value, id="modal-input")

    def on_input_submitted(self, event: Input.Submitted):
        self.dismiss(event.value)

    def action_cancel(self):
        self.dismiss(None)

def eq_filter(eq):
    if eq == "strong":
        return "highpass=f=80,equalizer=f=1800:t=q:w=1.2:g=4,equalizer=f=4500:t=q:w=1.5:g=3.5,equalizer=f=9000:t=q:w=1.5:g=2,lowpass=f=11000"
    if eq == "accent":
        return "highpass=f=60,equalizer=f=300:t=q:w=1.2:g=3.5,equalizer=f=1200:t=q:w=1.2:g=3,equalizer=f=2600:t=q:w=1.5:g=2.5,equalizer=f=5000:t=q:w=1.5:g=1.5,lowpass=f=12000"
    if eq == "vbee":
        return ("highpass=f=120,equalizer=f=800:t=q:w=1.5:g=2,equalizer=f=2500:t=q:w=1.2:g=3.5,"
                "equalizer=f=6000:t=q:w=1.8:g=2,lowpass=f=12000,loudnorm=I=-14:TP=-1.5:LRA=9")
    return "loudnorm=I=-16:TP=-1.5:LRA=11"


def filter_chain(speed_vol_pitch_eq):
    _, volume, pitch, eq = speed_vol_pitch_eq
    factor = 2.0 ** (float(pitch) / 12.0)
    chains = []
    if abs(float(pitch)) > 0.001:
        chains.append(f"asetrate={int(tts.SAMPLE_RATE * factor)},atempo={1.0 / factor},aresample={tts.SAMPLE_RATE}")
    chains.append(eq_filter(eq))
    if abs(float(volume) - 1.0) > 0.001:
        chains.append(f"volume={float(volume):.3f}")
    return ",".join(chains)


# ═══════════════════════════════ backend sync (chạy trong worker) ═══════════════════════════════

def render_sync(text, out_path, opts, progress_cb):
    """opts: dict speed,pause,pause_comma,noise_scale,noise_w,volume,pitch,eq. Trả (ok, msg)."""
    from piper.config import SynthesisConfig
    text = re.sub(r"#[^\n]*", "", text).strip()
    if not text:
        return False, "Text trống"
    text_proc = tts.vietnamize_text(text)
    sentences = tts.split_into_sentences(text_proc)
    total = len(sentences)
    syn = SynthesisConfig(length_scale=1.0 / float(opts["speed"]),
                          noise_scale=float(opts["noise_scale"]),
                          noise_w_scale=float(opts["noise_w"]))
    from piper.voice import PiperVoice
    voice = PiperVoice.load(str(tts.MODEL))
    tts.patch_anh_phoneme(voice)
    tts.patch_phatam_fix(voice)
    parts, done, skipped = [], 0, 0
    for s in sentences:
        if not re.search(r"[A-Za-zÀ-ỹ0-9]", s):
            continue
        try:
            wav = tts.synth_sentence(voice, syn, s)
        except Exception:
            skipped += 1
            continue
        parts.append(wav)
        last_ch = s[-1] if s else ""
        if last_ch in "，,。.":
            parts.append(tts.silence(float(opts["pause_comma"]) if last_ch in "，," else float(opts["pause"])))
        done += 1
        progress_cb(done, total)
    if not parts:
        return False, "Không có câu nào đọc được"
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    tts.write_wav_pcm(b"".join(parts), tmp.name)
    r = subprocess.run([FF, "-y", "-i", tmp.name, "-codec:a", "libmp3lame", "-qscale:a", "2",
                        "-af", filter_chain((0, opts["volume"], opts["pitch"], opts["eq"])),
                        str(out_path)], capture_output=True, text=True, cwd=str(BASE))
    os.unlink(tmp.name)
    if r.returncode != 0 or not out_path.exists():
        return False, f"ffmpeg lỗi: {(r.stderr or '')[-300:]}"
    msg = f"Xong: {out_path.name} ({fmt_dur(audio_duration(out_path))})"
    if skipped:
        msg += f" — bỏ {skipped} câu đọc lỗi"
    return True, msg


def video_sync(cfg, progress_cb):
    """cfg: img,audio,text,color,size,y,bright,quality,fps,crf,preset,out. Trả (ok, msg)."""
    img_path, audio_path = Path(cfg["img"]), Path(cfg["audio"])
    if not img_path.exists():
        return False, "Ảnh không tồn tại"
    if not audio_path.exists():
        return False, "Audio không tồn tại"
    dur = audio_duration(audio_path)
    if dur <= 0:
        return False, "Audio rỗng hoặc không đọc được"
    vw, vh = QUALITY_MAP.get(cfg["quality"], (1920, 1080))
    txt_file = None
    filters = []
    if int(cfg["bright"]) != 100:
        filters.append(f"eq=brightness={(int(cfg['bright']) - 100) / 100}")
    if cfg["text"]:
        txt_file = BASE / f"_overlay_{uuid.uuid4().hex[:8]}.txt"
        txt_file.write_text(cfg["text"], encoding="utf-8")
        filters.append(f"drawtext=textfile={txt_file.name}:fontcolor={cfg['color']}:fontsize={cfg['size']}"
                       f":x=(w-text_w)/2:y=h*{cfg['y']}/100-text_h/2:expansion=none")
    vf = [f"format=rgba,scale={vw}:{vh}:force_original_aspect_ratio=decrease,pad={vw}:{vh}:(ow-iw)/2:(oh-ih)/2,fps={cfg['fps']}"]
    vf.extend(filters)
    out_path = VIDEO_DIR / cfg["out"]
    cmd = [FF, "-y", "-nostats", "-loglevel", "error",
           "-loop", "1", "-i", str(img_path), "-i", str(audio_path),
           "-vf", ",".join(vf),
           "-c:v", "libx264", "-preset", cfg["preset"], "-crf", str(cfg["crf"]),
           "-c:a", "aac", "-b:a", "128k", "-shortest", "-t", str(dur),
           "-pix_fmt", "yuv420p", "-progress", "pipe:1", str(out_path)]
    proc = subprocess.Popen(cmd, cwd=str(BASE), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, bufsize=1, universal_newlines=True)
    for line in proc.stdout:
        line = line.strip()
        if line.startswith("out_time_ms="):
            try:
                pct = min(99, int((int(line.split("=")[1]) / 1_000_000) / dur * 100))
                progress_cb(pct)
            except Exception:
                pass
        elif line.startswith("progress=end"):
            progress_cb(100)
    proc.wait()
    if txt_file:
        txt_file.unlink(missing_ok=True)
    if proc.returncode != 0:
        return False, f"ffmpeg lỗi: {(proc.stderr.read() if proc.stderr else '')[-300:]}"
    return True, f"Xong: video_output/{cfg['out']} ({fmt_dur(dur)})"


# ═══════════════════════════════ UI ═══════════════════════════════

class Confirm(ModalScreen[bool]):
    """Hộp xác nhận Yes/No."""
    BINDINGS = [("escape", "cancel", "Hủy")]

    def __init__(self, question: str):
        super().__init__()
        self.question = question

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-box"):
            yield Label(self.question, id="confirm-q")
            with Horizontal(id="confirm-btns"):
                yield Button("Xóa", variant="error", id="yes")
                yield Button("Hủy", variant="default", id="no")

    def on_button_pressed(self, event: Button.Pressed):
        self.dismiss(event.button.id == "yes")

    def action_cancel(self):
        self.dismiss(False)


class TTSStudio(App):
    TITLE = "TTS Studio — giọng Ngọc Huyền"
    SUB_TITLE = "bản Terminal"
    CSS = """
    #main { height: 1fr; }
    #sidebar { width: 28; background: $surface; border-right: solid $primary; padding: 1; }
    #sidebar .nav-btn { width: 100%; margin-bottom: 1; }
    #sidebar .nav-btn.active { background: $primary; color: $text; text-style: bold; }
    #content { width: 1fr; padding: 1 2; }
    .view { display: none; height: 1fr; }
    .view.active { display: block; }
    .view-title { text-style: bold; color: $accent; margin-bottom: 1; }
    #text-input { height: 10; border: round $primary; }
    #char-count { color: $text-muted; margin-bottom: 1; }
    .row { height: auto; margin-bottom: 1; }
    .row Input { width: 1fr; }
    .row Select { width: 1fr; }
    .btns { height: auto; margin-bottom: 1; }
    .btns Button { margin-right: 1; }
    #render-progress { display: none; margin-bottom: 1; }
    #render-progress.visible { display: block; }
    #status { color: $warning; margin-bottom: 1; }
    #scan-box { display: none; height: 1fr; }
    #scan-box.visible { display: block; }
    #scan-table { height: 1fr; }
    DataTable { height: 1fr; }
    #confirm-box { width: 60; height: auto; background: $surface; border: round $error; padding: 1 2; }
    #confirm-btns { height: auto; align-horizontal: right; }
    #confirm-btns Button { margin-left: 1; }
    """

    BINDINGS = [
        ("q", "quit", "Thoát"),
        ("f1", "view('home')", "Văn bản"),
        ("f2", "view('products')", "Sản phẩm"),
        ("f3", "view('words')", "Kho từ"),
        ("f4", "view('video')", "Video"),
        ("f5", "view('settings')", "Cài đặt"),
    ]

    def __init__(self, cli_text=None, cli_out=None):
        super().__init__()
        self.state = load_state()
        self.cli_text, self.cli_out = cli_text, cli_out
        self._products_cache = []
        self._scan_rows = []
        self._merge_sel = set()
        self._last_render_file = None

    # ---------- compose ----------
    def compose(self) -> ComposeResult:
        with Horizontal(id="main"):
            with Vertical(id="sidebar"):
                for v in VIEWS:
                    yield Button(f"{NAV_ICONS[v]} {VIEW_TITLES[v]}", id=f"nav-{v}", classes="nav-btn active" if v == "home" else "nav-btn")
            with VerticalScroll(id="content"):
                # ===== HOME =====
                with Vertical(id="view-home", classes="view active"):
                    yield Label("⌨ CHUYỂN VĂN BẢN THÀNH GIỌNG ĐỌC", classes="view-title")
                    yield TextArea(self.state["text"], id="text-input")
                    yield Label(f"{len(self.state['text'])} ký tự", id="char-count")
                    with Horizontal(classes="row"):
                        yield Input(value=str(self.state["speed"]), id="in-speed", placeholder="Tốc độ (1.3)")
                        yield Input(value=str(self.state["volume"]), id="in-vol", placeholder="Âm lượng (1.0)")
                        yield Select([("Pitch 0", "0"), ("Pitch +1", "1"), ("Pitch +2", "2"), ("Pitch -1", "-1"), ("Pitch -2", "-2")],
                                     value=self.state["pitch"], id="in-pitch", allow_blank=False)
                        yield Select([("EQ chuẩn (loudnorm)", "none"), ("EQ rõ chữ (strong)", "strong"),
                                      ("EQ nhấn thanh (accent)", "accent"), ("EQ Vbee", "vbee")],
                                     value=self.state["eq"], id="in-eq", allow_blank=False)
                    with Horizontal(classes="btns"):
                        yield Button("▶ Tạo giọng đọc", variant="primary", id="btn-gen")
                        yield Button("🔍 Quét từ nước ngoài", id="btn-scan")
                        yield Button("📂 Nạp từ file...", id="btn-loadfile")
                    yield ProgressBar(id="render-progress", show_eta=False)
                    yield Label("", id="status")
                    with Vertical(id="scan-box"):
                        yield Label("🔍 TỪ NƯỚC NGOÀI / KHÔNG DẤU PHÁT HIỆN ĐƯỢC", classes="view-title")
                        yield DataTable(id="scan-table")
                        with Horizontal(classes="btns"):
                            yield Button("✓ Thêm từ đang chọn", id="btn-scan-add")
                            yield Button("✓✓ Thêm tất cả", id="btn-scan-addall")
                            yield Button("✕ Xóa kết quả quét", id="btn-scan-clear")
                # ===== PRODUCTS =====
                with Vertical(id="view-products", classes="view"):
                    yield Label("≡ SẢN PHẨM MP3  (Enter = chọn/bỏ chọn để gộp)", classes="view-title")
                    yield DataTable(id="prod-table")
                    with Horizontal(classes="btns"):
                        yield Button("▶ Nghe", id="btn-play")
                        yield Button("✎ Đổi tên", id="btn-rename")
                        yield Button("🗑 Xóa", variant="error", id="btn-del")
                        yield Button("⧉ Ghép các file đã chọn", id="btn-merge")
                    yield Input(placeholder="Tên mới (dùng cho Đổi tên)", id="in-rename")
                # ===== WORDS =====
                with Vertical(id="view-words", classes="view"):
                    yield Label("📖 KHO TỪ ĐỌC (tự học)", classes="view-title")
                    yield Input(placeholder="Tìm kiếm...", id="in-word-search")
                    yield DataTable(id="word-table")
                    with Horizontal(classes="row"):
                        yield Input(placeholder="Từ mới", id="in-new-word")
                        yield Input(placeholder="Cách đọc", id="in-new-reading")
                        yield Button("✓ Lưu", id="btn-word-save")
                    with Horizontal(classes="btns"):
                        yield Button("✎ Sửa từ đang chọn (điền xuống ô trên)", id="btn-word-edit")
                        yield Button("🗑 Xóa từ đang chọn", variant="error", id="btn-word-del")
                # ===== VIDEO =====
                with Vertical(id="view-video", classes="view"):
                    yield Label("🎬 TẠO VIDEO (ảnh nền + audio + chữ)", classes="view-title")
                    yield Input(value=self.state["video"]["img"], placeholder="Đường dẫn ảnh nền (jpg/png/webp)", id="vid-img")
                    yield Select([], prompt="Chọn audio từ Sản phẩm...", id="vid-audio", allow_blank=True)
                    yield Input(value=self.state["video"]["text"], placeholder="Chữ đè trên video (để trống = không chữ)", id="vid-text")
                    with Horizontal(classes="row"):
                        yield Input(value=self.state["video"]["color"], placeholder="Màu (#FFFFFF)", id="vid-color")
                        yield Input(value=str(self.state["video"]["size"]), placeholder="Cỡ chữ (48)", id="vid-size")
                        yield Input(value=str(self.state["video"]["y"]), placeholder="Vị trí dọc % (85)", id="vid-y")
                        yield Input(value=str(self.state["video"]["bright"]), placeholder="Độ sáng % (100)", id="vid-bright")
                    with Horizontal(classes="row"):
                        yield Select([("480p", "480p"), ("720p", "720p"), ("1080p", "1080p"), ("4k", "4k")],
                                     value=self.state["video"]["quality"], id="vid-quality", allow_blank=False)
                        yield Select([("24 fps", "24"), ("30 fps", "30"), ("60 fps", "60")],
                                     value=self.state["video"]["fps"], id="vid-fps", allow_blank=False)
                        yield Input(value=str(self.state["video"]["crf"]), placeholder="CRF (23)", id="vid-crf")
                        yield Select([("ultrafast", "ultrafast"), ("veryfast", "veryfast"), ("fast", "fast"),
                                      ("medium", "medium"), ("slow", "slow")],
                                     value=self.state["video"]["preset"], id="vid-preset", allow_blank=False)
                    yield Input(value=self.state["video"]["out"], placeholder="Tên video (để trống = tự đặt)", id="vid-out")
                    with Horizontal(classes="btns"):
                        yield Button("🎬 Tạo video", variant="primary", id="btn-video")
                    yield ProgressBar(id="video-progress", show_eta=False)
                    yield Label("", id="video-status")
                # ===== SETTINGS =====
                with Vertical(id="view-settings", classes="view"):
                    yield Label("⚙ CÀI ĐẶT RENDER", classes="view-title")
                    with Horizontal(classes="row"):
                        yield Input(value=str(self.state["pause"]), placeholder="Pause chấm (0.18)", id="set-pause")
                        yield Input(value=str(self.state["pause_comma"]), placeholder="Pause phẩy (0.18)", id="set-pause-comma")
                    with Horizontal(classes="row"):
                        yield Input(value=str(self.state["noise_scale"]), placeholder="Noise scale (0.667)", id="set-noise")
                        yield Input(value=str(self.state["noise_w"]), placeholder="Noise w (0.8)", id="set-noise-w")
                    with Horizontal(classes="btns"):
                        yield Button("💾 Lưu cài đặt", id="btn-save-settings")
        yield Footer()

    # ---------- lifecycle ----------
    def on_mount(self):
        st = self.query_one("#scan-table", DataTable)
        st.add_columns("Từ", "Cách đọc đề xuất", "Trạng thái")
        pt = self.query_one("#prod-table", DataTable)
        pt.add_columns("Tên", "Dung lượng", "Thời lượng", "Ngày tạo")
        pt.cursor_type = "row"
        wt = self.query_one("#word-table", DataTable)
        wt.add_columns("Từ", "Cách đọc")
        wt.cursor_type = "row"
        self.refresh_products()
        self.refresh_words()
        self.refresh_scan_draft()
        self.refresh_video_audio()
        # auto-save mỗi 2s (chống mất khi thoát đột ngột — bản TUI của "F5")
        self.set_interval(2.0, self.autosave)

    def refresh_products(self):
        table = self.query_one("#prod-table", DataTable)
        table.clear()
        self._products_cache = sorted(PRODUCT.glob("*.mp3"), key=lambda p: p.stat().st_mtime, reverse=True)
        for f in self._products_cache:
            table.add_row(f.name, f"{f.stat().st_size / 1048576:.1f}MB",
                          fmt_dur(audio_duration(f)), datetime.fromtimestamp(f.stat().st_mtime).strftime("%d/%m %H:%M"))
        self.refresh_video_audio()

    def refresh_video_audio(self):
        sel = self.query_one("#vid-audio", Select)
        cur = sel.value
        opts = [(f.name, f.name) for f in self._products_cache]
        sel.set_options(opts)
        if cur and any(v == cur for _, v in opts):
            sel.value = cur

    def refresh_words(self, flt=""):
        table = self.query_one("#word-table", DataTable)
        table.clear()
        for w, r in sorted(lw.get_all().items()):
            if not flt or flt.lower() in w.lower() or flt.lower() in r.lower():
                table.add_row(w, r)

    def refresh_scan_draft(self):
        self._scan_rows = load_draft()
        self.render_scan_table()

    def render_scan_table(self):
        table = self.query_one("#scan-table", DataTable)
        table.clear()
        for it in self._scan_rows:
            table.add_row(it["word"], it.get("reading", ""), "chưa có trong kho")
        self.query_one("#scan-box").set_class(bool(self._scan_rows), "visible")

    def switch_view(self, name: str):
        for v in VIEWS:
            self.query_one(f"#view-{v}").set_class(v == name, "active")
            self.query_one(f"#nav-{v}").set_class(v == name, "active")

    def action_view(self, name: str):
        self.switch_view(name)

    def on_button_pressed(self, event: Button.Pressed):
        bid = event.button.id
        if bid and bid.startswith("nav-"):
            self.switch_view(bid[4:])
        handlers = {
            "btn-gen": self.do_generate, "btn-scan": self.do_scan,
            "btn-loadfile": self.do_loadfile, "btn-scan-add": self.do_scan_add,
            "btn-scan-addall": self.do_scan_addall, "btn-scan-clear": self.do_scan_clear,
            "btn-play": self.do_play, "btn-rename": self.do_rename, "btn-del": self.do_delete,
            "btn-merge": self.do_merge, "btn-word-save": self.do_word_save,
            "btn-word-edit": self.do_word_edit, "btn-word-del": self.do_word_del,
            "btn-video": self.do_video, "btn-save-settings": self.do_save_settings,
        }
        if bid in handlers:
            handlers[bid]()

    # ---------- auto-save ----------
    def autosave(self):
        """Tự lưu toàn bộ state (bản TUI của 'chống F5'). Chạy 2s/lần + trước khi render."""
        try:
            self.state["text"] = self.query_one("#text-input", TextArea).text
            self.state["speed"] = self.query_one("#in-speed", Input).value
            self.state["volume"] = self.query_one("#in-vol", Input).value
            self.state["pitch"] = self.query_one("#in-pitch", Select).value or "0"
            self.state["eq"] = self.query_one("#in-eq", Select).value or "none"
            v = self.state["video"]
            v["img"] = self.query_one("#vid-img", Input).value
            v["text"] = self.query_one("#vid-text", Input).value
            v["color"] = self.query_one("#vid-color", Input).value
            v["size"] = self.query_one("#vid-size", Input).value
            v["y"] = self.query_one("#vid-y", Input).value
            v["bright"] = self.query_one("#vid-bright", Input).value
            v["quality"] = self.query_one("#vid-quality", Select).value or "1080p"
            v["fps"] = self.query_one("#vid-fps", Select).value or "30"
            v["crf"] = self.query_one("#vid-crf", Input).value
            v["preset"] = self.query_one("#vid-preset", Select).value or "fast"
            v["out"] = self.query_one("#vid-out", Input).value
            save_state(self.state)
        except Exception:
            pass
    # ---------- HOME: render ----------
    def do_generate(self):
        """Handler chính (thread UI): đọc input → giao việc cho worker."""
        text = self.query_one("#text-input", TextArea).text
        if not text.strip():
            self.notify("Chưa có văn bản", severity="warning")
            return
        self.autosave()
        opts = {"speed": self.query_one("#in-speed", Input).value or "1.3",
                "volume": self.query_one("#in-vol", Input).value or "1.0",
                "pitch": self.query_one("#in-pitch", Select).value or "0",
                "eq": self.query_one("#in-eq", Select).value or "none",
                "pause": self.state.get("pause", 0.18),
                "pause_comma": self.state.get("pause_comma", 0.18),
                "noise_scale": self.state.get("noise_scale", 0.667),
                "noise_w": self.state.get("noise_w", 0.8)}
        out_name = f"{datetime.now():%Y%m%d_%H%M%S}.mp3"
        self._render_worker(text, opts, out_name)

    @work(thread=True, group="tts", exclusive=True)
    def _render_worker(self, text, opts, out_name):
        self.call_from_thread(self._gen_ui_start)
        okk, msg = render_sync(text, PRODUCT / out_name, opts,
                               lambda d, t: self.call_from_thread(self._gen_progress, d, t))
        self.call_from_thread(self._gen_ui_done, okk, msg, out_name)
    def _gen_ui_start(self):
        self.query_one("#render-progress", ProgressBar).add_class("visible")
        self.query_one("#status", Label).update("Đang đọc...")

    def _gen_progress(self, done, total):
        p = self.query_one("#render-progress", ProgressBar)
        p.total = total
        p.update(progress=done)
        self.query_one("#status", Label).update(f"Đang đọc câu {done}/{total}...")

    def _gen_ui_done(self, okk, msg, out_name):
        self.query_one("#status", Label).update(("✓ " if okk else "✗ ") + msg)
        if okk:
            self.notify(f"Hoàn tất: {out_name}", severity="information", title="TTS")
            self.refresh_products()

    def do_loadfile(self):
        """Nạp nội dung file (txt/md/docx/pdf/srt...) vào ô văn bản."""
        self.push_screen(InputScreen("Đường dẫn file (.txt/.md/.docx/.pdf...):"), self._loadfile_done)

    def _loadfile_done(self, path):
        if not path:
            return
        p = Path(path.strip().strip('"'))
        if not p.exists():
            self.notify("File không tồn tại", severity="error")
            return
        from app import extract_text_from_file
        text = extract_text_from_file(p.name, p.read_bytes())
        ta = self.query_one("#text-input", TextArea)
        ta.text = (ta.text + ("\n" if ta.text else "") + text) if ta.text else text
        self.notify(f"Đã nạp {p.name} ({len(text)} ký tự)")

    # ---------- HOME: scan ----------
    def do_scan(self):
        text = self.query_one("#text-input", TextArea).text
        if not text.strip():
            self.notify("Chưa có văn bản để quét", severity="warning")
            return
        items = lw.scan_new_words(text)
        draft = load_draft()
        keys = {d["key"] for d in draft}
        merged = list(draft)
        for it in items:
            if it["key"] not in keys:
                merged.append(it)
                keys.add(it["key"])
        self._scan_rows = merged
        save_draft(self._scan_rows)
        self.render_scan_table()
        self.notify(f"Phát hiện {len(items)} từ (bảng có {len(merged)} từ chờ duyệt)", severity="information")

    def _scan_selected(self):
        table = self.query_one("#scan-table", DataTable)
        if table.row_count == 0 or self._scan_rows == []:
            return None
        idx = table.cursor_row
        if 0 <= idx < len(self._scan_rows):
            return self._scan_rows[idx]
        return None

    def do_scan_add(self):
        it = self._scan_selected()
        if not it:
            self.notify("Chưa chọn từ", severity="warning")
            return
        lw.add_words([(it["word"], it.get("reading", ""))])
        self._scan_rows = [r for r in self._scan_rows if r["key"] != it["key"]]
        save_draft(self._scan_rows)
        self.render_scan_table()
        self.refresh_words()
        self.notify(f"Đã thêm: {it['word']} → {it.get('reading','')}", severity="information")

    def do_scan_addall(self):
        if not self._scan_rows:
            self.notify("Không có từ nào", severity="warning")
            return
        lw.add_words([(r["word"], r.get("reading", "")) for r in self._scan_rows])
        n = len(self._scan_rows)
        self._scan_rows = []
        save_draft([])
        self.render_scan_table()
        self.refresh_words()
        self.notify(f"Đã thêm {n} từ vào kho (tổng {lw.count()})", severity="information")

    def do_scan_clear(self):
        self._scan_rows = []
        save_draft([])
        self.render_scan_table()

    # ---------- PRODUCTS ----------
    def _prod_selected(self):
        table = self.query_one("#prod-table", DataTable)
        if table.row_count == 0:
            return None
        idx = table.cursor_row
        if 0 <= idx < len(self._products_cache):
            return self._products_cache[idx]
        return None

    def do_play(self):
        f = self._prod_selected()
        if f:
            os.startfile(f)
            self.notify(f"Đang mở: {f.name}")

    def do_rename(self):
        f = self._prod_selected()
        new = self.query_one("#in-rename", Input).value.strip()
        if not f or not new:
            self.notify("Chọn file + nhập tên mới vào ô dưới bảng", severity="warning")
            return
        new = re.sub(r'[\\/*?:"<>|]', "", new)
        if not new.endswith(".mp3"):
            new += ".mp3"
        f.rename(PRODUCT / new)
        self.query_one("#in-rename", Input).value = ""
        self.refresh_products()
        self.notify(f"Đã đổi tên → {new}")

    def do_delete(self):
        f = self._prod_selected()
        if not f:
            return

        def _confirm(ok: bool):
            if ok:
                f.unlink()
                self.refresh_products()
                self.notify(f"Đã xóa {f.name}")

        self.push_screen(Confirm(f'Xóa file "{f.name}"?'), _confirm)

    def do_merge(self):
        if len(self._merge_sel) < 2:
            self.notify("Chọn ít nhất 2 file bằng phím Space", severity="warning")
            return
        paths = sorted((PRODUCT / n for n in self._merge_sel), key=lambda p: p.stat().st_mtime)
        out_name = f"Ghep_{datetime.now():%Y%m%d_%H%M%S}.mp3"
        lst = PRODUCT / f"_concat_{uuid.uuid4().hex[:8]}.txt"
        lst.write_text("\n".join(f"file '{p}'" for p in paths), encoding="utf-8")
        r = subprocess.run([FF, "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                            "-c", "copy", str(PRODUCT / out_name)], capture_output=True, timeout=600)
        lst.unlink(missing_ok=True)
        if r.returncode == 0:
            self._merge_sel.clear()
            self.refresh_products()
            self.notify(f"Đã gộp {len(paths)} file → {out_name}")
        else:
            self.notify(f"ffmpeg lỗi: {r.stderr.decode('utf-8', 'ignore')[-200:]}", severity="error")

    def on_data_table_row_selected(self, event: DataTable.RowSelected):
        """Space trên bảng sản phẩm = chọn/bỏ chọn để gộp."""
        if event.data_table.id == "prod-table":
            idx = event.data_table.cursor_row
            if 0 <= idx < len(self._products_cache):
                name = self._products_cache[idx].name
                if name in self._merge_sel:
                    self._merge_sel.discard(name)
                    self.notify(f"Bỏ chọn: {name}")
                else:
                    self._merge_sel.add(name)
                    self.notify(f"Đã chọn {len(self._merge_sel)} file để gộp")

    # ---------- WORDS ----------
    def do_word_save(self):
        w = self.query_one("#in-new-word", Input).value.strip()
        r = self.query_one("#in-new-reading", Input).value.strip()
        if not w or not r:
            self.notify("Nhập đủ từ + cách đọc", severity="warning")
            return
        lw.add_words([(w, r)])
        self.query_one("#in-new-word", Input).value = ""
        self.query_one("#in-new-reading", Input).value = ""
        self.refresh_words()
        self.notify(f"Đã lưu: {w} → {r}")

    def do_word_edit(self):
        table = self.query_one("#word-table", DataTable)
        if table.row_count == 0:
            return
        idx = table.cursor_row
        rows = [(w, r) for w, r in sorted(lw.get_all().items())
                if not self.query_one("#in-word-search", Input).value
                or self.query_one("#in-word-search", Input).value.lower() in w.lower()
                or self.query_one("#in-word-search", Input).value.lower() in r.lower()]
        if 0 <= idx < len(rows):
            w, r = rows[idx]
            self.query_one("#in-new-word", Input).value = w
            self.query_one("#in-new-reading", Input).value = r
            self.notify(f"Sửa '{w}' ở ô trên rồi bấm Lưu")

    def do_word_del(self):
        table = self.query_one("#word-table", DataTable)
        if table.row_count == 0:
            return
        idx = table.cursor_row
        rows = [(w, r) for w, r in sorted(lw.get_all().items())
                if not self.query_one("#in-word-search", Input).value
                or self.query_one("#in-word-search", Input).value.lower() in w.lower()
                or self.query_one("#in-word-search", Input).value.lower() in r.lower()]
        if 0 <= idx < len(rows):
            w = rows[idx][0]
            lw.remove_word(w)
            self.refresh_words()
            self.notify(f"Đã xóa: {w}")

    def do_video(self):
        """Handler chính (thread UI): đọc input → giao việc cho worker."""
        img = self.query_one("#vid-img", Input).value.strip().strip('"')
        audio_name = self.query_one("#vid-audio", Select).value
        if not img or not audio_name:
            self.notify("Cần ảnh nền + audio", severity="warning")
            return
        self.autosave()
        v = self.state["video"]
        cfg = {"img": img, "audio": str(PRODUCT / audio_name),
               "text": v["text"], "color": v["color"] or "#FFFFFF",
               "size": v["size"] or "48", "y": v["y"] or "85",
               "bright": v["bright"] or "100", "quality": v["quality"],
               "fps": v["fps"] or "30", "crf": v["crf"] or "23", "preset": v["preset"] or "fast",
               "out": (v["out"] or f"video_{datetime.now():%Y%m%d_%H%M%S}.mp4")}
        if not cfg["out"].endswith(".mp4"):
            cfg["out"] += ".mp4"
        cfg["out"] = re.sub(r'[\\/*?:"<>|]', "", cfg["out"])
        self._video_worker(cfg)

    @work(thread=True, group="video", exclusive=True)
    def _video_worker(self, cfg):
        self.call_from_thread(self._video_ui_start)
        okk, msg = video_sync(cfg, lambda pct: self.call_from_thread(self._video_progress, pct))
        self.call_from_thread(self._video_ui_done, okk, msg)

    def _video_ui_start(self):
        self.query_one("#video-progress", ProgressBar).add_class("visible")
        self.query_one("#video-status", Label).update("Đang render...")

    def _video_progress(self, pct):
        self.query_one("#video-progress", ProgressBar).update(progress=pct)
        self.query_one("#video-status", Label).update(f"Đang render: {pct}%")

    def _video_ui_done(self, okk, msg):
        self.query_one("#video-status", Label).update(("✓ " if okk else "✗ ") + msg)
        if okk:
            self.notify(f"Video xong: {msg.split(':')[-1].strip()}", severity="information")

    # ---------- SETTINGS ----------
    def do_save_settings(self):
        try:
            self.state["pause"] = float(self.query_one("#set-pause", Input).value or 0.18)
            self.state["pause_comma"] = float(self.query_one("#set-pause-comma", Input).value or 0.18)
            self.state["noise_scale"] = float(self.query_one("#set-noise", Input).value or 0.667)
            self.state["noise_w"] = float(self.query_one("#set-noise-w", Input).value or 0.8)
            save_state(self.state)
            self.notify("Đã lưu cài đặt")
        except ValueError:
            self.notify("Số không hợp lệ", severity="error")


def run_cli(argv):
    """python tts_tui.py --file x.md --out y.mp3 — render nhanh không vào app."""
    if "--file" not in argv:
        return False
    f = Path(argv[argv.index("--file") + 1])
    if "--out" in argv:
        out = Path(argv[argv.index("--out") + 1])
        if not out.is_absolute() and len(out.parts) == 1:
            out = PRODUCT / out
    else:
        out = PRODUCT / f"{f.stem}.mp3"
    from app import extract_text_from_file
    text = f.read_text(encoding="utf-8") if f.suffix.lower() in (".txt", ".md") else extract_text_from_file(f.name, f.read_bytes())
    st = load_state()
    opts = {"speed": st["speed"], "volume": st["volume"], "pitch": st["pitch"], "eq": st["eq"],
            "pause": st.get("pause", 0.18), "pause_comma": st.get("pause_comma", 0.18),
            "noise_scale": st.get("noise_scale", 0.667), "noise_w": st.get("noise_w", 0.8)}
    okk, msg = render_sync(text, out, opts, lambda d, t: print(f"\rĐang đọc câu {d}/{t}...", end="", flush=True))
    print("\n✓ " + msg if okk else "\n✗ " + msg)
    return True


if __name__ == "__main__":
    if run_cli(sys.argv[1:]):
        sys.exit(0)
    TTSStudio().run()
