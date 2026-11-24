# CONTRACT – Các điểm nhóm đã chốt

Tài liệu này quy định những chỗ mà code của người này chạm vào code của người khác: protocol, dữ liệu dùng chung, chữ ký hàm và quy ước. Những gì nằm **bên trong** phần của mỗi người thì người đó tự quyết.
Muốn sửa bất kỳ mục nào ở đây thì **cả nhóm phải đồng ý**.

Phân công (theo `work.md`): **A**: discovery + UI · **B**: chat TCP · **C**: truyền file + kiểm thử.

---

## 1. Môi trường & hằng số

- Python 3.10+. Chỉ dùng thư viện chuẩn (`socket`, `threading`, `os`, `time`, `argparse`) + `prompt_toolkit` (`pip install prompt_toolkit`).
- Chạy chương trình:
  ```
  python lanchat.py --name Quan [--port 5000] [--broadcast <broadcast>]
  ```
  Khi test nhiều instance trên 1 máy không có mạng: `--broadcast 127.255.255.255`, mỗi instance một `--port` khác nhau.

| Hằng số | Giá trị | Ghi chú |
|---|---|---|
| `UDP_PORT` | 9999 | cổng discovery |
| `BROADCAST_INTERVAL` | 3 s | chu kỳ gửi HELLO |
| `PEER_TIMEOUT` | 10 s | quá thời gian này không nghe thấy → offline |
| `DEFAULT_TCP_PORT` | 5000 | |
| `MAX_FIELD` | 255 byte | độ dài tối đa của một trường header |
| `MAX_MSG` | 65536 byte | độ dài tối đa một tin chat |
| `CHUNK` | 65536 byte | kích thước khối khi gửi file |
| `CONNECT_TIMEOUT` | 3 s | |
| `DOWNLOAD_DIR` | `downloads/` | |

- **Tên người dùng:** 1–32 ký tự, **không chứa `|` và xuống dòng**, phải duy nhất trong LAN. Tiếng Việt có dấu được phép.
- **Trạng thái:** `online` hoặc `away`.

---

## 2. Protocol UDP – discovery (A)

```
HELLO|<name>|<tcp_port>|<status>
ví dụ: HELLO|Quan|5000|online
```
Mã hóa UTF-8, gửi trong một datagram.

**Gửi**
- Mỗi 3 giây gửi một lần. Khi người dùng gõ `/status` thì **gửi ngay**, không chờ đến chu kỳ tiếp theo.
- Socket UDP: bật `SO_REUSEADDR` và `SO_BROADCAST`, bind vào `""`.

**Nhận**
- Tách gói bằng `|`. Gói chỉ hợp lệ khi:
  - có đủ 4 trường, trường đầu là `HELLO`;
  - port là số từ 1 đến 65535;
  - status là `online` hoặc `away`.
- Gói sai thì **bỏ qua, không báo gì**.
- IP lấy từ địa chỉ trả về của `recvfrom`, không gửi IP trong gói.
- Gói có cùng name **và** cùng port với mình là gói của chính mình, bỏ qua. Cùng name nhưng khác port thì in `[!] Tên <name> bị trùng`.
- Khi có người mới xuất hiện: `[*] <name> is online`. Khi quá 10 s không nghe thấy họ: xóa khỏi `peers` và in `[*] <name> went offline`.

---

## 3. Protocol TCP – chat & file (B định nghĩa, C dùng)

- Mỗi trường header kết thúc bằng `|`.
- `length` và `size` tính theo **byte**, không tính theo số ký tự. Ví dụ `"chào"` có 4 ký tự nhưng là 5 byte UTF-8.
- **Frame đầu tiên của một kết nối cho biết đó là kết nối chat hay kết nối file.**

### Kết nối chat
Mỗi cặp người dùng chung **một kết nối**, gửi được cả hai chiều.
```
HI|<sender_name>|                   ← bên mở kết nối gửi đầu tiên
MSG|<length>|<length byte UTF-8>    ← lặp lại, cả hai chiều
BYE|                                ← khi /leave hoặc /quit
```

### Kết nối file
Mỗi file đi trên **một kết nối riêng**, không dùng chung với socket chat.
```
FILE|<sender_name>|<filename>|<size>|<size byte thô>
```
Gửi xong thì bên gửi đóng kết nối.

### Kiểm tra dữ liệu
Vi phạm bất kỳ điều nào dưới đây → ném `ProtocolError` → đóng kết nối đó. Chương trình **không được crash**.
- Một trường dài quá `MAX_FIELD` byte.
- `length` hoặc `size` có ký tự không phải chữ số.
- `length` lớn hơn `MAX_MSG`.
- Loại frame lạ, không phải `HI`, `MSG`, `BYE` hoặc `FILE`.
- `filename` phải đi qua `os.path.basename()`. Nếu kết quả rỗng, là `.` hoặc `..` thì từ chối nhận.

Nội dung của `MSG` được phép chứa `|`, vì bên nhận đọc theo `length` chứ không tìm dấu `|`.

---

## 4. Dữ liệu dùng chung – `state.py`

Toàn bộ dữ liệu dùng chung được bảo vệ bằng **một lock duy nhất: `state.lock`**.

| Biến | Kiểu | Ai được ghi |
|---|---|---|
| `me` | `{"name": str, "port": int, "status": str}` | A |
| `peers` | `name → {"ip": str, "port": int, "status": str, "last_seen": float}` | A |
| `last_list` | `list[str]`: danh sách tên theo đúng thứ tự của lần `/list` gần nhất | A |
| `chats` | `name → socket`: các kết nối chat đang mở | B |
| `history` | `name → list[str]`: các dòng đã định dạng, ví dụ `[Minh] hi` | B |
| `unread` | `name → int` | B |
| `current` | `str` hoặc `None`: người đang chat | B |

**Quy tắc**
1. Đọc hoặc ghi bất kỳ biến nào ở trên đều phải nằm trong `with state.lock:`.
2. **Không** gọi `send`, `recv`, `connect` hay `out()` khi đang giữ lock. Hãy copy dữ liệu cần dùng ra ngoài, thoát khỏi lock rồi mới làm.
3. Chỉ người phụ trách (cột "Ai được ghi") mới ghi vào biến đó. Người khác muốn thay đổi thì gọi hàm của người phụ trách.

---

## 5. Chữ ký hàm giữa các người

### `ui.py` (A)
| Hàm | Mô tả |
|---|---|
| `out(text: str) -> None` | An toàn khi nhiều thread cùng gọi. In một dòng phía trên dòng đang gõ. **Mọi thông báo của cả nhóm đều phải đi qua hàm này**, không ai được tự gọi `print` |
| `read_line() -> str` | Chờ người dùng nhập một dòng, dùng `PromptSession().prompt("> ")`. Nếu gặp `EOFError` hoặc `KeyboardInterrupt` thì xử lý như `/quit` |

Hàm `main` bọc toàn bộ vòng lặp nhập lệnh trong `with patch_stdout():`.

### `discovery.py` (A)
| Hàm | Mô tả |
|---|---|
| `start_discovery() -> None` | Khởi động 3 thread daemon: broadcaster, listener, quét timeout |
| `list_peers() -> list[dict]` | Trả về danh sách người online và cập nhật `last_list` |
| `get_peer(key: str) -> dict \| None` | `key` là tên hoặc số thứ tự (theo `last_list`). Trả về **bản copy** `{"name", "ip", "port", "status"}`, không tìm thấy thì trả `None` |
| `set_status(status: str) -> None` | Đổi trạng thái của mình và broadcast ngay |

### `protocol.py` (B)
| Hàm | Mô tả |
|---|---|
| `class ProtocolError(Exception)` | Báo dữ liệu nhận được sai định dạng |
| `recv_exact(sock, n) -> bytes` | Lặp `recv` cho đến khi đủ `n` byte. Nếu kết nối đóng giữa chừng thì ném `ConnectionError` |
| `read_until_bar(sock) -> str` | Đọc một trường header đến dấu `\|`. Dài quá `MAX_FIELD` thì ném `ProtocolError` |
| `read_size(sock, limit) -> int` | Đọc một trường số, kiểm tra chỉ gồm chữ số và không vượt `limit`. Dùng chung cho `MSG` và `FILE` |
| `send_hi(sock, name)` / `send_msg(sock, text)` / `send_bye(sock)` | Đóng gói frame và gửi bằng `sendall` |
| `read_chat_frame(sock) -> tuple` | Trả về `("MSG", text)` hoặc `("BYE", None)` |

### `chat.py` (B)
| Hàm | Mô tả |
|---|---|
| `start_server(port) -> None` | Chạy thread acceptor. Mỗi lần `accept()` xong thì **giao ngay** socket cho một thread worker. Acceptor **không** tự đọc dữ liệu |
| `open_chat(key) -> None` | Xử lý `/chat <name\|number>` |
| `send_text(text) -> None` | Gửi tin cho người đang chat |
| `leave() -> None` | Xử lý `/leave` |
| `close_all() -> None` | Gửi `BYE` tới mọi kết nối chat rồi đóng, dùng khi `/quit` |
| `get_current() -> dict \| None` | Trả thông tin người đang chat `{"name", "ip", "port"}` |

**Thread worker** đọc trường đầu tiên của kết nối:
- `HI` → chạy vòng nhận tin chat;
- `FILE` → gọi `filetransfer.handle_incoming_file(sock, addr)`;
- giá trị khác → đóng kết nối.

**Kết nối trùng:** nếu đã có kết nối với X mà lại có thêm một kết nối nữa (ví dụ hai bên cùng gõ `/chat` một lúc) thì **giữ kết nối do người có tên nhỏ hơn mở** (so sánh chuỗi), đóng kết nối còn lại. Hai bên áp dụng cùng một quy tắc nên luôn giữ lại cùng một kết nối.

**Unread:** tin từ người không phải `current` thì lưu vào `history`, tăng `unread` và in `[*] New message from <name> (<n> unread)`. Khi `/chat` chuyển sang người đó thì in lại các tin chưa đọc và đặt `unread` về 0.

### `filetransfer.py` (C)
| Hàm | Mô tả |
|---|---|
| `send_file(path) -> None` | Kiểm tra file tồn tại **ngay lúc gọi**, lỗi thì báo bằng `out`. Lấy người nhận từ `chat.get_current()` **tại thời điểm gõ lệnh**, sau đó chạy thread gửi |
| `handle_incoming_file(sock, addr) -> None` | B gọi hàm này sau khi đã đọc trường `FILE`. Hàm đọc tiếp các trường còn lại rồi nhận nội dung file |

**Quy tắc nhận file**
- Ghi vào `downloads/<tên>.part`, nhận đủ `size` byte rồi mới đổi tên thành tên thật.
- Trùng tên thì lưu thành `tên (1).ext`, `tên (2).ext`, …
- Lỗi giữa chừng thì xóa file `.part` và báo `[!]`.
- File rỗng (`size = 0`) vẫn phải nhận được bình thường.

### `lanchat.py` (A)
Đọc tham số dòng lệnh, khởi động discovery và server, chạy vòng lặp đọc lệnh rồi gọi hàm tương ứng:

| Lệnh | Gọi tới |
|---|---|
| `/list` | `discovery.list_peers()` |
| `/chat <name\|number>` | `chat.open_chat(key)` |
| `<text thường>` | `chat.send_text(text)` |
| `/send <file>` | `filetransfer.send_file(path)` |
| `/leave` | `chat.leave()` |
| `/status <online\|away>` | `discovery.set_status(status)` |
| `/help` | in danh sách lệnh |
| `/quit` | `chat.close_all()` rồi thoát |
| lệnh sai | in hướng dẫn ngắn |

---

## 6. Quy ước lỗi & hiển thị

**Lỗi**
- Các hàm mạng chỉ ném 2 loại exception:
  - `ConnectionError`, bao gồm cả `OSError` và timeout;
  - `ProtocolError`.
- Thread worker bắt cả hai loại, sau đó: báo bằng `out` → dọn dữ liệu trong `state` → đóng socket.
- **Không exception nào được phép làm chết thread chính.**
- Khi kết nối: dùng `socket.create_connection((ip, port), timeout=3)`, kết nối xong thì gọi `settimeout(None)`.

**Hiển thị**
- Tiền tố: `[*]` cho thông tin, `[!]` cho lỗi, `[Tên] nội dung` cho tin chat.
- Mẫu câu (theo đề bài):
  ```
  [*] Listening on TCP port 5000
  [*] Broadcasting presence on UDP port 9999
  [*] Connected to Minh (192.168.1.12:6000)
  [*] New message from Huy (1 unread)
  [*] Switched to Quan — 2 unread:
  [*] Sending slides.pdf (2.4 MB) ... 40%      ← in mỗi 10%
  [*] Sending slides.pdf (2.4 MB) ... 100% Done.
  ```

---

## 7. Thread model (đề mục 5.1)

| Thread | Chờ gì | Người phụ trách |
|---|---|---|
| Main | bàn phím | A |
| UDP broadcaster | hẹn giờ 3 s | A |
| UDP listener | gói UDP | A |
| Quét timeout | hẹn giờ | A |
| TCP acceptor | kết nối mới | B |
| Worker / receiver (mỗi kết nối một thread) | socket của peer | B (chat), C (file) |
| File sender (mỗi lần gửi một thread) | — | C |

---

## 8. Đối chiếu yêu cầu đề → người phụ trách

| Mục trong đề | Người |
|---|---|
| 3.1 Peer discovery, 3.2 Online status | A |
| 4.1 Lệnh, 4.3 Gõ phím khi có tin đến | A |
| 3.3 Chat, 5.2 Framing | B |
| 3.4 File transfer | C |
| 5.3 Xử lý lỗi | mỗi người phần của mình |
| Wireshark, README, checklist kiểm thử | C |
| Báo cáo | mỗi người viết phần của mình, **A ghép** thành bản cuối |

---

## 9. Không làm

GUI, mã hóa, chat nhóm, gửi tiếp file bị đứt, gói `BYE` qua UDP (đã có timeout 10 s).
