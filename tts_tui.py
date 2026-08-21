# -*- coding: utf-8 -*-
"""
TTS STUDIO — bản Terminal (TUI nhẹ, KHÔNG cần mở web hay server)
  python tts_tui.py                          → menu tương tác
  python tts_tui.py --file x.md --out y.mp3  → render nhanh một file
  python tts_tui.py --scan file.txt          → quét từ nước ngoài của file

Dùng CHUNG dữ liệu với bản web: sản phẩm/, kho từ động, scan_draft.json.
"""
import os
import sys
import re
import json
import uuid
import shutil
import subprocess
import tempfile
from pathlib import Path
from datetime import datetime

if os.name == "nt":
    os.system("")  # bật ANSI escape trên Windows 10+
    subprocess.run("chcp 65001 >nul", shell=True, capture_output=True)

BASE = Path(__file__).parent
sys.path.insert(0, r"C:\Users\Khang\Desktop\dịch tryện\Nghiên cứu giọng kênh\piper_ngochuyen")

import tts_ngochuyen as tts  # noqa: E402
import loanwords_dynamic as lw  # noqa: E402
from piper.config import SynthesisConfig  # noqa: E402

FFPROBE = r"C:\Users\Khang\Desktop\ffmpeg\ffmpeg-8.1.2-essentials_build\bin\ffprobe.exe"
FF = tts.FFMPEG
PRODUCT = BASE / "sản phẩm"
DRAFT_FILE = BASE / "scan_draft.json"
STATE_FILE = BASE / "tui_state.json"

# ---------- màu ANSI ----------
def C(s, code):
    return f"\033[{code}m{s}\033[0m"

def title(s):
    print(f"\n\033[1;36m═══ {s} ═══\033[0m")

def ok(s):
    print(C("✓ " + s, "92"))

def err(s):
    print(C("✗ " + s, "91"))

def warn(s):
    print(C("⚠ " + s, "93"))

def ask(prompt, default=""):
    try:
        v = input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        raise SystemExit(0)
    return v or default

# ---------- state (tương tự localStorage của web) ----------
DEFAULT_STATE = {
    "speed": 1.3, "pause": 0.18, "pause_comma": 0.18,
    "noise_scale": 0.667, "noise_w": 0.8,
    "eq": "none", "volume": 1.0, "pitch": 0.0,
    "video": {"quality": "1080p", "fps": 30, "crf": 23, "preset": "fast",
              "text_color": "#FFFFFF", "text_size": 48, "text_y": 85, "brightness": 100},
}

def load_state():
    st = dict(DEFAULT_STATE)
    st["video"] = dict(DEFAULT_STATE["video"])
    try:
        d = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        for k, v in d.items():
            if k == "video":
                st["video"].update(v)
            else:
                st[k] = v
    except Exception:
        pass
    return st

def save_state(st):
    STATE_FILE.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")

# ---------- tiện ích ----------
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

def eq_filter(eq):
    if eq == "strong":
        return "highpass=f=80,equalizer=f=1800:t=q:w=1.2:g=4,equalizer=f=4500:t=q:w=1.5:g=3.5,equalizer=f=9000:t=q:w=1.5:g=2,lowpass=f=11000"
    if eq == "accent":
        return "highpass=f=60,equalizer=f=300:t=q:w=1.2:g=3.5,equalizer=f=1200:t=q:w=1.2:g=3,equalizer=f=2600:t=q:w=1.5:g=2.5,equalizer=f=5000:t=q:w=1.5:g=1.5,lowpass=f=12000"
    if eq == "vbee":
        return ("highpass=f=120,equalizer=f=800:t=q:w=1.5:g=2,equalizer=f=2500:t=q:w=1.2:g=3.5,"
                "equalizer=f=6000:t=q:w=1.8:g=2,lowpass=f=12000,loudnorm=I=-14:TP=-1.5:LRA=9")
    return "loudnorm=I=-16:TP=-1.5:LRA=11"

def filter_chain(st):
    factor = 2.0 ** (st["pitch"] / 12.0)
    chains = []
    if abs(st["pitch"]) > 0.001:
        chains.append(f"asetrate={int(tts.SAMPLE_RATE * factor)},atempo={1.0 / factor},aresample={tts.SAMPLE_RATE}")
    chains.append(eq_filter(st["eq"]))
    if abs(st["volume"] - 1.0) > 0.001:
        chains.append(f"volume={st['volume']:.3f}")
    return ",".join(chains)

# ---------- TTS render ----------
_voice = None

def get_voice():
    global _voice
    if _voice is None:
        from piper.voice import PiperVoice
        v = PiperVoice.load(str(tts.MODEL))
        tts.patch_anh_phoneme(v)
        tts.patch_phatam_fix(v)
        _voice = v
    return _voice

def render_text(text: str, out_path: Path, st: dict):
    text = re.sub(r"#[^\n]*", "", text).strip()
    if not text:
        err("Text trống")
        return False
    print("Đang xử lý văn bản...")
    text_proc = tts.vietnamize_text(text)
    sentences = tts.split_into_sentences(text_proc)
    total = len(sentences)
    syn = SynthesisConfig(length_scale=1.0 / st["speed"],
                          noise_scale=st["noise_scale"], noise_w_scale=st["noise_w"])
    voice = get_voice()
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
            parts.append(tts.silence(st["pause_comma"] if last_ch in "，," else st["pause"]))
        done += 1
        print(f"\r\033[KĐang đọc câu {done}/{total}...", end="", flush=True)
    print()
    if not parts:
        err("Không có câu nào đọc được")
        return False
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    tts.write_wav_pcm(b"".join(parts), tmp.name)
    r = subprocess.run([FF, "-y", "-i", tmp.name, "-codec:a", "libmp3lame", "-qscale:a", "2",
                        "-af", filter_chain(st), str(out_path)], capture_output=True, text=True)
    os.unlink(tmp.name)
    if r.returncode != 0 or not out_path.exists():
        err(f"ffmpeg lỗi: {(r.stderr or '')[-300:]}")
        return False
    d = audio_duration(out_path)
    ok(f"Xong: {out_path.name} ({fmt_dur(d)}, bỏ {skipped} câu lỗi)" if skipped
       else f"Xong: {out_path.name} ({fmt_dur(d)})")
    return True

def read_multiline(hint="Dán text (kết thúc bằng dòng riêng chứa dấu chấm '.')"):
    print(C(hint, "90"))
    lines = []
    while True:
        try:
            ln = input()
        except (EOFError, KeyboardInterrupt):
            raise SystemExit(0)
        if ln.strip() == ".":
            break
        lines.append(ln)
    return "\n".join(lines)

def maybe_file_or_text(prompt):
    """Nhập đường dẫn file HOẶC dán text trực tiếp."""
    v = ask(f"{prompt} (Enter = dán text): ")
    if v and Path(v).exists() and Path(v).is_file():
        from app import extract_text_from_file  # tái dùng bộ đọc file của web
        return extract_text_from_file(v, Path(v).read_bytes())
    if v:
        return None  # người dùng nhập gì đó nhưng không phải file → coi như hủy
    return read_multiline()

# ---------- 1. Render TTS ----------
def menu_render(st):
    title("ĐỌC VĂN BẢN THÀNH MP3")
    text = maybe_file_or_text("Nhập đường dẫn file (.txt/.md/.docx/.pdf...)")
    if text is None:
        err("Không đọc được nội dung")
        return
    if not text.strip():
        err("Text trống")
        return
    print(C(f"Độ dài: {len(text)} ký tự | speed {st['speed']} | eq {st['eq']} | vol {st['volume']} | pitch {st['pitch']}", "90"))
    out_name = ask("Tên file out (Enter = tự đặt): ")
    if not out_name:
        out_name = f"{datetime.now():%Y%m%d_%H%M%S}.mp3"
    if not out_name.lower().endswith(".mp3"):
        out_name += ".mp3"
    render_text(text, PRODUCT / re.sub(r'[\\/*?:"<>|]', "", out_name), st)

# ---------- 2. Quét từ nước ngoài ----------
def load_draft():
    try:
        return json.loads(DRAFT_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []

def save_draft(items):
    DRAFT_FILE.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")

def menu_scan():
    title("QUÉT TỪ NƯỚC NGOÀI / KHÔNG DẤU")
    text = maybe_file_or_text("Nhập đường dẫn file cần quét")
    if text is None:
        err("Không đọc được nội dung")
        return
    items = lw.scan_new_words(text)
    if not items:
        ok("Sạch — không có từ nào cần đọc riêng")
        return
    draft = load_draft()
    keys = {d["key"] for d in draft}
    added = 0
    print(C(f"Phát hiện {len(items)} từ. Enter = nhận cách đọc đề xuất | gõ cách khác = sửa | s = bỏ qua", "90"))
    for it in items:
        r = ask(f"  {C(it['word'], '96')}  →  {C(it['reading'], '93')}  ")
        if r.lower() == "s":
            continue
        reading = r if r else it["reading"]
        lw.add_words([(it["word"], reading)])
        added += 1
        keys.discard(it["key"])
    draft = [d for d in draft if d["key"] in keys]
    save_draft(draft)
    ok(f"Đã thêm {added} từ vào kho (tổng {lw.count()} từ)")

# ---------- 3. Kho từ ----------
def menu_words():
    title("KHO TỪ ĐỌC (tự học)")
    while True:
        print(f"  1. Xem tất cả ({lw.count()} từ)   2. Tìm   3. Thêm/sửa   4. Xóa   0. Về menu chính")
        c = ask("Chọn: ")
        if c == "1":
            items = lw.get_all()
            for i, (w, r) in enumerate(sorted(items.items(), key=lambda kv: kv[0]), 1):
                print(f"  {i:>4}. {w:<20} → {r}")
        elif c == "2":
            q = ask("Từ cần tìm: ").lower()
            if q:
                for w, r in sorted(lw.get_all().items()):
                    if q in w.lower() or q in r.lower():
                        print(f"  {w:<20} → {r}")
        elif c == "3":
            w = ask("Từ: ")
            if w:
                r = ask("Cách đọc: ")
                if r:
                    lw.add_words([(w, r)])
                    ok(f"Đã lưu: {w} → {r}")
        elif c == "4":
            w = ask("Từ cần xóa: ")
            if w and lw.remove_word(w):
                ok(f"Đã xóa {w}")
            else:
                err("Không tìm thấy trong kho")
        elif c == "0":
            return

# ---------- 4. Sản phẩm ----------
def list_products():
    files = sorted(PRODUCT.glob("*.mp3"), key=lambda p: p.stat().st_mtime, reverse=True)
    for i, f in enumerate(files, 1):
        print(f"  {i:>3}. {f.name:<48} {f.stat().st_size/1048576:6.1f}MB  {fmt_dur(audio_duration(f))}")
    return files

def menu_products():
    title("SẢN PHẨM MP3")
    while True:
        print("  1. Danh sách   2. Mở bằng player   3. Đổi tên   4. Xóa   5. Gộp file   0. Về menu chính")
        c = ask("Chọn: ")
        files = list(PRODUCT.glob("*.mp3"))
        if c == "1":
            list_products()
        elif c == "2":
            fs = sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)
            list_products()
            n = ask("Số thứ tự file cần mở: ")
            if n.isdigit() and 1 <= int(n) <= len(fs):
                os.startfile(fs[int(n) - 1])
                ok("Đã mở")
        elif c == "3":
            fs = sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)
            list_products()
            n = ask("Số thứ tự file cần đổi tên: ")
            if n.isdigit() and 1 <= int(n) <= len(fs):
                old = fs[int(n) - 1]
                new = ask(f"Tên mới (không cần .mp3): ")
                if new:
                    new = re.sub(r'[\\/*?:"<>|]', "", new)
                    if not new.endswith(".mp3"):
                        new += ".mp3"
                    old.rename(PRODUCT / new)
                    ok(f"→ {new}")
        elif c == "4":
            fs = sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)
            list_products()
            n = ask("Số thứ tự file cần XÓA: ")
            if n.isdigit() and 1 <= int(n) <= len(fs):
                f = fs[int(n) - 1]
                if ask(f"Xóa thật không? (gõ 'co' để xác nhận): ").lower() == "co":
                    f.unlink()
                    ok(f"Đã xóa {f.name}")
        elif c == "5":
            fs = sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)
            list_products()
            ns = ask("Các số thứ tự cần gộp (vd: 3,5,7): ")
            idx = [int(x) for x in re.split(r"[,\s]+", ns.strip()) if x.isdigit()]
            if len(idx) < 2 or any(i < 1 or i > len(fs) for i in idx):
                err("Cần ít nhất 2 số hợp lệ")
                continue
            paths = [fs[i - 1] for i in idx]
            out_name = ask("Tên file gộp (Enter = tự đặt): ") or f"Ghep_{datetime.now():%Y%m%d_%H%M%S}.mp3"
            out_name = re.sub(r'[\\/*?:"<>|]', "", out_name if out_name.endswith(".mp3") else out_name + ".mp3")
            lst = PRODUCT / f"_concat_{uuid.uuid4().hex[:8]}.txt"
            lst.write_text("\n".join(f"file '{p}'" for p in paths), encoding="utf-8")
            r = subprocess.run([FF, "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                                "-c", "copy", str(PRODUCT / out_name)], capture_output=True, timeout=600)
            lst.unlink(missing_ok=True)
            if r.returncode == 0:
                ok(f"Đã gộp {len(paths)} file → {out_name} ({(PRODUCT/out_name).stat().st_size/1048576:.1f}MB)")
            else:
                err(f"ffmpeg lỗi: {r.stderr.decode('utf-8', 'ignore')[-200:]}")
        elif c == "0":
            return

# ---------- 5. Tạo video ----------
QUALITY_MAP = {"480p": (854, 480), "720p": (1280, 720), "1080p": (1920, 1080), "4k": (3840, 2160)}

def menu_video(st):
    title("TẠO VIDEO (ảnh nền + audio + chữ)")
    img = ask("Đường dẫn ảnh nền (jpg/png/webp): ")
    img_path = Path(img.strip('"')) if img else None
    if not img_path or not img_path.exists():
        err("Ảnh không tồn tại")
        return
    print(C("Chọn audio từ sản phẩm, hoặc dán đường dẫn khác:", "90"))
    fs = sorted(PRODUCT.glob("*.mp3"), key=lambda p: p.stat().st_mtime, reverse=True)
    for i, f in enumerate(fs[:15], 1):
        print(f"  {i:>3}. {f.name} ({fmt_dur(audio_duration(f))})")
    a = ask("Số thứ tự / đường dẫn: ").strip('"')
    if a.isdigit() and 1 <= int(a) <= len(fs):
        audio_path = fs[int(a) - 1]
    else:
        audio_path = Path(a)
    if not audio_path.exists():
        err("Audio không tồn tại")
        return
    dur = audio_duration(audio_path)
    if dur <= 0:
        err("Audio rỗng hoặc không đọc được")
        return
    v = st["video"]
    print(C(f"Quality {v['quality']} | fps {v['fps']} | crf {v['crf']} | preset {v['preset']} (Enter giữ nguyên)", "90"))
    q = ask(f"Quality [{'/'.join(QUALITY_MAP)}]: ") or v["quality"]
    vw, vh = QUALITY_MAP.get(q, (1920, 1080))
    fps = int(ask(f"FPS [{v['fps']}]: ") or v["fps"])
    crf = int(ask(f"CRF [{v['crf']}]: ") or v["crf"])
    preset = ask(f"Preset [{v['preset']}]: ") or v["preset"]
    text = ask("Chữ đè trên video (Enter = không chữ): ")
    text_color = v["text_color"]
    text_size = v["text_size"]
    text_y = v["text_y"]
    if text:
        text_color = ask(f"Màu chữ [{text_color}]: ") or text_color
        text_size = int(ask(f"Cỡ chữ [{text_size}]: ") or text_size)
        text_y = int(ask(f"Vị trí dọc % [{text_y}]: ") or text_y)
    bright = int(ask(f"Độ sáng % [{v['brightness']}]: ") or v["brightness"])
    out_name = ask("Tên video (Enter = tự đặt): ") or f"video_{datetime.now():%Y%m%d_%H%M%S}.mp4"
    if not out_name.endswith(".mp4"):
        out_name += ".mp4"
    out_name = re.sub(r'[\\/*?:"<>|]', "", out_name)

    # lưu lại settings
    st["video"].update({"quality": q if q in QUALITY_MAP else v["quality"], "fps": fps, "crf": crf,
                        "preset": preset, "text_color": text_color, "text_size": text_size,
                        "text_y": text_y, "brightness": bright})
    save_state(st)

    txt_file = None
    filters = []
    if bright != 100:
        filters.append(f"eq=brightness={(bright - 100) / 100}")
    if text:
        txt_file = BASE / f"_overlay_{uuid.uuid4().hex[:8]}.txt"
        txt_file.write_text(text, encoding="utf-8")
        filters.append(f"drawtext=textfile={txt_file.name}:fontcolor={text_color}:fontsize={text_size}"
                       f":x=(w-text_w)/2:y=h*{text_y}/100-text_h/2:expansion=none")
    vf = [f"format=rgba,scale={vw}:{vh}:force_original_aspect_ratio=decrease,pad={vw}:{vh}:(ow-iw)/2:(oh-ih)/2,fps={fps}"]
    vf.extend(filters)
    cmd = [FF, "-y", "-nostats", "-loglevel", "error",
           "-loop", "1", "-i", str(img_path), "-i", str(audio_path),
           "-vf", ",".join(vf),
           "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
           "-c:a", "aac", "-b:a", "128k", "-shortest", "-t", str(dur),
           "-pix_fmt", "yuv420p", "-progress", "pipe:1",
           str(BASE / "video_output" / out_name)]
    print(C(f"Render {out_name} ({fmt_dur(dur)})...", "90"))
    proc = subprocess.Popen(cmd, cwd=str(BASE), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, bufsize=1, universal_newlines=True)
    for line in proc.stdout:
        line = line.strip()
        if line.startswith("out_time_ms="):
            try:
                pct = min(99, int((int(line.split("=")[1]) / 1_000_000) / dur * 100))
                print(f"\r\033[KĐang render: {pct}%", end="", flush=True)
            except Exception:
                pass
        elif line.startswith("progress=end"):
            print(f"\r\033[KĐang render: 100%", end="", flush=True)
    proc.wait()
    print()
    if txt_file:
        txt_file.unlink(missing_ok=True)
    if proc.returncode != 0:
        err(f"ffmpeg lỗi: {(proc.stderr.read() if proc.stderr else '')[-300:]}")
    else:
        ok(f"Xong: video_output/{out_name}")

# ---------- Cài đặt ----------
def menu_settings(st):
    title("CÀI ĐẶT RENDER (Enter = giữ nguyên)")
    st["speed"] = float(ask(f"Speed [{st['speed']}]: ") or st["speed"])
    st["pause"] = float(ask(f"Pause chấm [{st['pause']}]: ") or st["pause"])
    st["pause_comma"] = float(ask(f"Pause phẩy [{st['pause_comma']}]: ") or st["pause_comma"])
    st["eq"] = ask(f"EQ [none/strong/accent/vbee, hiện {st['eq']}]: ") or st["eq"]
    st["volume"] = float(ask(f"Volume [{st['volume']}]: ") or st["volume"])
    st["pitch"] = float(ask(f"Pitch bán âm [{st['pitch']}]: ") or st["pitch"])
    save_state(st)
    ok("Đã lưu")

# ---------- main ----------
def main():
    st = load_state()
    args = sys.argv[1:]
    if "--file" in args:
        f = Path(args[args.index("--file") + 1])
        if "--out" in args:
            out = Path(args[args.index("--out") + 1])
            if not out.is_absolute() and len(out.parts) == 1:
                out = PRODUCT / out  # chỉ tên file → để vào sản phẩm/
        else:
            out = PRODUCT / f"{f.stem}.mp3"
        from app import extract_text_from_file
        text = f.read_text(encoding="utf-8") if f.suffix.lower() in (".txt", ".md") else extract_text_from_file(f.name, f.read_bytes())
        render_text(text, out, st)
        return
    while True:
        print(f"""
\033[1;35m╔══════════════════════════════════════════╗
║   TTS STUDIO — TERMINAL (giọng Ngọc Huyền)   ║
╚══════════════════════════════════════════╝\033[0m
  1. Đọc văn bản thành MP3
  2. Quét từ nước ngoài + duyệt cách đọc
  3. Kho từ đọc ({lw.count()} từ)
  4. Sản phẩm MP3 (nghe / đổi tên / xóa / gộp)
  5. Tạo video (ảnh + audio + chữ)
  6. Cài đặt render
  0. Thoát""")
        c = ask("Chọn: ")
        try:
            if c == "1":
                menu_render(st)
            elif c == "2":
                menu_scan()
            elif c == "3":
                menu_words()
            elif c == "4":
                menu_products()
            elif c == "5":
                menu_video(st)
            elif c == "6":
                menu_settings(st)
            elif c == "0":
                print("Bye!")
                return
        except SystemExit:
            raise
        except Exception as e:
            err(f"Lỗi: {e}")

if __name__ == "__main__":
    main()
