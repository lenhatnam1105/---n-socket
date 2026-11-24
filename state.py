# state.py: dữ liệu dùng chung. Chỉ đọc/ghi trong `with lock:`.
# Không gọi send/recv/out() khi đang giữ lock.
# Cột "người ghi" theo CONTRACT §4: me, peers, last_list = A; chats, history, unread, current = B.
import threading

lock = threading.Lock()

me = {"name": "", "port": 0, "status": "online"}
peers = {}        # name -> {"ip", "port", "status", "last_seen"}
last_list = []    # tên theo thứ tự /list gần nhất
chats = {}        # name -> socket
history = {}      # name -> list[str]
unread = {}       # name -> int
current = None    # tên người đang chat, hoặc None