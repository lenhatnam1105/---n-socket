# filetransfer.py (C)
import tempfile
import os
import socket
import threading

from protocol import ProtocolError, recv_exact, read_until_bar, read_size
import chat, state
from ui import out

# shortcut: hằng số (CONTRACT §1) đặt tạm ở đây vì nhóm chưa chốt chỗ chung, chuyển đi khi đã chốt
CHUNK = 65536
DOWNLOAD_DIR = "downloads"
MAX_FIELD = 255
_finalize_lock = threading.Lock()


def human_size(n):
    if n < 1024:
        return f"{n} B"
    for unit in ("KB", "MB", "GB", "TB"):
        n /= 1024
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}"

def unique_path(folder, name):
    base, ext = os.path.splitext(name)
    path, i = os.path.join(folder, name), 1
    while os.path.exists(path):
        path = os.path.join(folder, f"{base} ({i}){ext}")
        i += 1
    return path

def _progress(label, done, total, last_mark):
    # in mỗi 10%, trả về mốc đã in; mốc 100% để dòng "Done." in
    if total == 0:
        return last_mark
    pct = done * 100 // total
    mark = pct // 10 * 10
    if last_mark < mark < 100:
        out(f"[*] {label} ... {mark}%")
        return mark
    return last_mark

def send_file(path):
    if not os.path.isfile(path):
        out(f"[!] Không tìm thấy file: {path}")
        return
    name = os.path.basename(path)
    if "|" in name or len(name.encode("utf-8")) > MAX_FIELD:
        out(f"[!] Tên file không hợp lệ (chứa '|' hoặc dài quá {MAX_FIELD} byte): {name}")
        return
    peer = chat.get_current()          # lấy người nhận lúc gõ lệnh
    if peer is None:
        out("[!] Chưa chat với ai")
        return
    threading.Thread(target=_send_worker, args=(peer, path, name), daemon=True).start()

def _send_worker(peer, path, name):
    with state.lock:
        sender = state.me["name"]
    try:
        size = os.path.getsize(path)
        label = f"Sending {name} ({human_size(size)})"
        with socket.create_connection((peer["ip"], peer["port"]), timeout=3) as sock:
            sock.settimeout(None)
            sock.sendall(f"FILE|{sender}|{name}|{size}|".encode("utf-8"))
            with open(path, "rb") as f:
                sent, mark = 0, 0
                while sent < size:      # gửi đúng `size` byte dù file bị sửa trong lúc gửi
                    chunk = f.read(min(CHUNK, size - sent))
                    if not chunk:
                        raise OSError("file bị thay đổi trong lúc gửi")
                    sock.sendall(chunk)
                    sent += len(chunk)
                    mark = _progress(label, sent, size, mark)
        out(f"[*] {label} ... 100% Done.")
    except OSError as e:               # gồm cả ConnectionError và timeout
        out(f"[!] Gửi {name} thất bại: {e}")

def handle_incoming_file(sock, addr):
    sender = read_until_bar(sock)
    name = read_until_bar(sock)
    size = read_size(sock, limit=1 << 40)

    base = os.path.basename(name)
    if base in ("", ".", ".."):
        raise ProtocolError("tên file không hợp lệ")

    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    part = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=DOWNLOAD_DIR,
            prefix="recv-",
            suffix=".part",
            delete=False,
        ) as f:
            part = f.name
            left, done, mark = size, 0, 0

            while left > 0:
                data = recv_exact(sock, min(CHUNK, left))
                f.write(data)
                left -= len(data)
                done += len(data)
                mark = _progress(
                    f"Receiving {base}", done, size, mark
                )

        with _finalize_lock:
            target = unique_path(DOWNLOAD_DIR, base)
            os.replace(part, target)

        saved_name = os.path.basename(target)
        out(f"[*] Received {saved_name} from {sender} ... 100% Done.")

    except (OSError, ProtocolError) as e:
        if part is not None and os.path.exists(part):
            os.remove(part)
        out(f"[!] Nhận {base} thất bại: {e}")
        raise
