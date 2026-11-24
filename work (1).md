# Phân công – LAN Chat & File Sharing

Nhóm chia việc như sau: **A làm tìm người và giao diện, B làm chat TCP, C làm truyền file và kiểm thử**. Mỗi người có một phần chạy thử được riêng, khối lượng tương đối đều.

> Chi tiết protocol, chữ ký hàm, lock và quy ước lỗi: xem **[CONTRACT.md](CONTRACT.md)**. File này chỉ ghi ai làm gì và khi nào thì coi là xong.

| Người | File phụ trách |
| --- | --- |
| A | `discovery.py`, `ui.py`, `lanchat.py` |
| B | `protocol.py`, `chat.py` |
| C | `filetransfer.py`, README, checklist kiểm thử |
| Cả nhóm | `state.py` (chỉ sửa khi cả nhóm đồng ý) |

---

## Người A: Tìm người + giao diện

| **Việc phải làm** | **Cụ thể phải viết gì?** | **Khi nào coi là xong?** |
| --- | --- | --- |
| Gửi thông báo hiện diện | Cứ 3 giây gửi UDP `HELLO\|name\|tcp_port\|status` đến cổng 9999. Khi `/status` đổi thì gửi ngay. | Cửa sổ nghe UDP nhận được thông báo đều đặn. Đổi trạng thái thì máy khác thấy ngay. |
| Nhận thông báo từ người khác | Kiểm tra gói: đủ 4 trường, port hợp lệ, status hợp lệ; gói sai thì bỏ qua. Lấy IP từ `recvfrom`, lưu vào `peers` và cập nhật `last_seen`. Bỏ qua gói của chính mình. Nếu cùng tên khác port thì báo tên trùng. | Mở hai chương trình thì thấy tên nhau. Gửi gói rác bằng `nc -u` thì chương trình không crash. |
| Phát hiện offline | Thread kiểm tra người nào quá 10 giây không gửi thông báo thì xóa khỏi `peers` và báo offline. | Tắt một chương trình, bên còn lại tự phát hiện. |
| `/list`, `/status` | `list_peers()` in danh sách và cập nhật `last_list`. `get_peer(key)` nhận tên hoặc số thứ tự. `set_status()` đổi trạng thái của mình. | `/chat 2` kết nối đúng người số 2 trong lần `/list` gần nhất. |
| Giao diện console | Dùng `prompt_toolkit`: `read_line()` gọi `PromptSession().prompt("> ")`, vòng lặp chính bọc trong `patch_stdout()`, `out(text)` có lock để nhiều thread in không vỡ dòng. | Đang gõ dở vẫn nhận tin và gõ tiếp được. Gõ tiếng Việt bằng Unikey không bị loạn chữ. |
| Nhận diện lệnh | Đọc dòng người dùng nhập, chuyển lệnh tới hàm theo bảng lệnh ở CONTRACT §5. Làm `/help`. `/quit` gọi `chat.close_all()` rồi thoát. Ctrl+C hoặc EOF xử lý như `/quit`. | Các lệnh gọi đúng chức năng. Lệnh sai thì hiện hướng dẫn ngắn. |
| Báo cáo | Viết phần discovery, UI và thread model. Ghép phần của B và C thành báo cáo cuối (5–10 trang). | Có bản báo cáo hoàn chỉnh. |

**Sản phẩm A bàn giao:** `out`, `read_line`, `list_peers`, `get_peer`, `set_status`, vòng lặp lệnh và báo cáo đã ghép.

---

## Người B: Kết nối TCP + nhắn tin

| **Việc phải làm** | **Cụ thể phải viết gì?** | **Khi nào coi là xong?** |
| --- | --- | --- |
| Hàm đọc TCP dùng chung (`protocol.py`) | Viết `recv_exact`, `read_until_bar`, `read_size`, `ProtocolError`, `send_hi`, `send_msg`, `send_bye`, `read_chat_frame`. Kiểm tra giới hạn `MAX_FIELD` và `MAX_MSG`. **Bàn giao trong 1–2 ngày đầu** vì C cần dùng. | Dữ liệu gửi thành nhiều đợt nhỏ vẫn đọc đúng. Header sai thì ném `ProtocolError`, không crash. |
| Đón kết nối đến | Acceptor `accept()` xong giao socket **ngay** cho một thread worker. Worker đọc trường đầu: `HI\|<name>\|` thì vào chat, `FILE` thì gọi `filetransfer.handle_incoming_file(sock, addr)`, giá trị khác thì đóng kết nối. | Nhận được nhiều kết nối mà không bị đứng chờ một người. Một kết nối im lặng (mở bằng `nc`) không làm treo server. |
| `/chat <name\|number>` | Lấy IP và port qua `discovery.get_peer(key)`. Kết nối bằng `create_connection(timeout=3)`, gửi `HI`, cập nhật `current`. | Chọn bằng tên hoặc số đều kết nối đúng người. Người đã offline thì báo `[!]`, không crash. |
| Gửi và nhận tin | Đóng gói `MSG\|length\|text`, trong đó length tính theo byte UTF-8. Phía nhận đọc đủ nội dung rồi gọi `out()`. | Hai máy nhắn qua lại được, kể cả tiếng Việt và tin có chứa ký tự `\|`. |
| Lịch sử và unread | Tin từ người không phải `current` thì lưu vào `history` và tăng `unread`. Khi chuyển sang người đó thì hiện lại tin chưa đọc. Mọi truy cập dữ liệu đều trong `state.lock`, không gọi `send` hay `out` khi đang giữ lock. | Ba instance chat chéo, không mất tin và đếm đúng unread. |
| Ngắt và lỗi kết nối | Làm `/leave` (gửi `BYE`) và `close_all()` cho `/quit`. Xử lý peer crash. Nếu có kết nối trùng thì **giữ kết nối do người có tên nhỏ hơn mở**. | App không crash. Hai bên `/chat` nhau cùng lúc thì chỉ còn đúng 1 kết nối và vẫn chat được. |

**Sản phẩm B bàn giao:** `protocol.py` (bàn giao sớm) và `chat.py` gồm `start_server`, `open_chat`, `send_text`, `leave`, `close_all`, `get_current`.

---

## Người C: Gửi/nhận file + kiểm thử tích hợp

| **Việc phải làm** | **Cụ thể phải viết gì?** | **Khi nào coi là xong?** |
| --- | --- | --- |
| `/send <file>` | Kiểm tra đường dẫn ngay khi gõ lệnh. Lấy người nhận bằng `chat.get_current()` **tại lúc gõ lệnh**, sau đó khởi chạy thread gửi file. | File không tồn tại thì báo lỗi. File hợp lệ thì bắt đầu gửi. Đổi người chat giữa chừng thì file vẫn đến đúng người ban đầu. |
| Gửi file | Mở kết nối TCP riêng, gửi header `FILE\|sender\|filename\|size\|`, rồi gửi nội dung theo từng khối 64 KB. | Gửi file lớn mà chat vẫn hoạt động bình thường. |
| Nhận file | Viết `handle_incoming_file(sock, addr)` để B gọi. Dùng `read_size` đọc kích thước. Tên file đi qua `basename`. Ghi vào `downloads/<tên>.part`, nhận đủ thì đổi tên. Trùng tên thì lưu thành `tên (1).ext`. | File nhận có cùng SHA-256 với file gốc. Header có tên file `../x` không ghi được ra ngoài `downloads/`. |
| Hiển thị tiến độ | Tính phần trăm từ số byte đã gửi hoặc đã nhận, cứ mỗi 10% in một dòng qua `out()` theo mẫu `[*] Sending ... 40%`. | Cả hai phía thấy tiến độ và thông báo hoàn thành. |
| Xử lý lỗi file | Hỗ trợ file rỗng. Mất kết nối giữa chừng thì xóa file `.part` và báo `[!]`. | Thử từng trường hợp đều xử lý đúng. |
| Test tích hợp và Wireshark | Viết checklist test chéo, có các ca: header sai (dùng `nc` gửi rác), tên file `../x`, hai bên `/chat` cùng lúc, tắt đột ngột khi đang chat hoặc đang gửi file. Bắt gói UDP broadcast và TCP three-way handshake bằng Wireshark. Viết README. Viết phần protocol và file cho báo cáo. | Có kết quả test, ảnh Wireshark kèm giải thích, và README hướng dẫn chạy. |

**Sản phẩm C bàn giao:** `filetransfer.py`, checklist kiểm thử, ảnh Wireshark, README và phần báo cáo về protocol và file.

---

## Các điểm đã chốt

Các điểm dưới đây đã chốt trong **[CONTRACT.md](CONTRACT.md)**. Muốn sửa thì cả nhóm phải đồng ý.

| Nội dung | Mục |
| --- | --- |
| Hằng số, quy tắc đặt tên, trạng thái | §1 |
| Protocol UDP (`HELLO`) | §2 |
| Protocol TCP (`HI`, `MSG`, `BYE`, `FILE`) và quy tắc kiểm tra header | §3 |
| Dữ liệu dùng chung trong `state.py` và lock | §4 |
| Chữ ký hàm của từng người, bảng lệnh → hàm | §5 |
| Quy ước lỗi và mẫu câu hiển thị | §6 |

---

## Thứ tự làm

1. Cả nhóm đọc CONTRACT.md và cùng tạo `state.py`.
2. Ba người làm song song:
   - A đưa ngay bản `out()` đơn giản để B và C dùng được;
   - B làm xong `protocol.py` trước;
   - C viết phần gửi/nhận file theo chữ ký hàm đã chốt.
3. **Ghép code ngay khi gửi được 1 tin chat**, sau đó mới hoàn thiện unread, tiến độ và các tình huống lỗi.
4. Test chéo (A test phần B, B test phần C, C test phần A), chụp Wireshark, hoàn thiện báo cáo và tập demo trên 2 máy.
