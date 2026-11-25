# test_filetransfer.py: test cho filetransfer.py (người C)
# Chạy: python -m unittest test_filetransfer -v
import hashlib
import os
import socket
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

# Thêm _stubs vào CUỐI danh sách tìm module: file thật ở thư mục gốc (nếu có) luôn được dùng trước
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "_stubs"))

import filetransfer
from protocol import ProtocolError
def feed(data):
    """Tạo cặp socket nối sẵn. Một thread gửi `data` vào đầu a rồi đóng; trả về đầu b để đọc."""
    a, b = socket.socketpair()

    def writer():
        with a:
            a.sendall(data)

    threading.Thread(target=writer, daemon=True).start()
    return b


def sha256(data):
    return hashlib.sha256(data).hexdigest()
class TestHandleIncomingFile(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        filetransfer.DOWNLOAD_DIR = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def receive(self, header, body=b""):
        with feed(header.encode("utf-8") + body) as sock:
            filetransfer.handle_incoming_file(sock, ("127.0.0.1", 0))

    def files(self):
        return sorted(os.listdir(self.tmp.name))

    def content(self, name):
        with open(os.path.join(self.tmp.name, name), "rb") as f:
            return f.read()
    def test_1_empty_file(self):
        self.receive("Minh|rong.txt|0|")
        self.assertEqual(self.files(), ["rong.txt"])
        self.assertEqual(self.content("rong.txt"), b"")

    def test_2_big_file_sha256(self):
        body = os.urandom(1_000_000)
        self.receive(f"Minh|big.bin|{len(body)}|", body)
        self.assertEqual(sha256(self.content("big.bin")), sha256(body))

    def test_3_path_traversal(self):
        self.receive("Minh|../x|1|", b"z")
        self.assertEqual(self.files(), ["x"])

    def test_4_duplicate_names(self):
        for _ in range(3):
            self.receive("Minh|a.txt|1|", b"z")
        self.assertEqual(self.files(), ["a (1).txt", "a (2).txt", "a.txt"])

    def test_5_bad_size(self):
        with self.assertRaises(ProtocolError):
            self.receive("Minh|a.txt|12a|")
        self.assertEqual(self.files(), [])

    def test_6_cut_midway(self):
        with self.assertRaises(ConnectionError):
            self.receive("Minh|a.txt|100|", b"0123456789")
        self.assertEqual(self.files(), [])   
    def test_13_same_name_concurrently(self):
        barrier = threading.Barrier(2)
        original_recv_exact = filetransfer.recv_exact
        errors = []

        def read_together(sock, n):
            # Chờ cả hai lượt mở file tạm rồi mới đọc nội dung.
            barrier.wait(timeout=5)
            return original_recv_exact(sock, n)

        def receiver(sender_name, body):
            try:
                self.receive(f"{sender_name}|a.txt|1|", body)
            except Exception as e:
                errors.append(f"{sender_name}: {type(e).__name__}: {e}")

        threads = [
            threading.Thread(
                target=receiver, args=("Minh", b"A"), daemon=True
            ),
            threading.Thread(
                target=receiver, args=("Quan", b"B"), daemon=True
            ),
        ]

        with patch.object(
            filetransfer, "recv_exact", side_effect=read_together
        ):
            for thread in threads:
                thread.start()

            for thread in threads:
                thread.join(timeout=7)

            self.assertTrue(
                all(not thread.is_alive() for thread in threads),
                "Có thread nhận chưa kết thúc",
            )

        self.assertEqual(errors, [], f"Lỗi khi nhận đồng thời: {errors}")
        self.assertEqual(self.files(), ["a (1).txt", "a.txt"])
        self.assertCountEqual(
            [self.content(name) for name in self.files()],
            [b"A", b"B"],
        ) 
class TestSendFile(unittest.TestCase):
    def check_send(self, name, body):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, name)
            with open(path, "wb") as f:
                f.write(body)

            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
                server.bind(("127.0.0.1", 0))
                server.listen(1)
                server.settimeout(5)

                peer = {
                    "ip": "127.0.0.1",
                    "port": server.getsockname()[1],
                }

                with patch.dict(filetransfer.state.me, {"name": "Nam"}):
                    sender = threading.Thread(
                        target=filetransfer._send_worker,
                        args=(peer, path, name),
                        daemon=True,
                    )
                    sender.start()

                    received = bytearray()
                    try:
                        conn, _ = server.accept()
                        with conn:
                            conn.settimeout(5)
                            while True:
                                chunk = conn.recv(65536)
                                if not chunk:
                                    break
                                received.extend(chunk)
                    finally:
                        sender.join(timeout=5)

                    self.assertFalse(
                        sender.is_alive(),
                        "Thread gửi chưa kết thúc",
                    )

            fields = bytes(received).split(b"|", 4)
            self.assertEqual(
                len(fields), 5,
                "Header không đủ các trường",
            )

            frame, sender_name, filename, size, content = fields
            self.assertEqual(frame, b"FILE")
            self.assertEqual(sender_name, b"Nam")
            self.assertEqual(filename, name.encode("utf-8"))
            self.assertEqual(size, str(len(body)).encode("ascii"))
            self.assertEqual(len(content), len(body))
            self.assertEqual(sha256(content), sha256(body))

    def test_7_send_empty_file(self):
        self.check_send("rong.txt", b"")

    def test_8_send_big_file(self):
        self.check_send("du_lieu.bin", os.urandom(1_000_000))   
class TestSendFileValidation(unittest.TestCase):
    def setUp(self):
        self.out_patch = patch.object(filetransfer, "out")
        self.mock_out = self.out_patch.start()
        self.addCleanup(self.out_patch.stop)

        self.thread_patch = patch.object(filetransfer.threading, "Thread")
        self.mock_thread = self.thread_patch.start()
        self.addCleanup(self.thread_patch.stop)

    def assert_rejected(self, expected_message):
        self.mock_out.assert_called_once()
        message = self.mock_out.call_args.args[0]
        self.assertIn(expected_message, message)
        self.mock_thread.assert_not_called()

    def test_9_missing_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "khong_ton_tai.txt")
            filetransfer.send_file(path)

        self.assert_rejected("Không tìm thấy file")

    def test_10_no_current_peer(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "a.txt")
            with open(path, "wb") as f:
                f.write(b"hello")

            with patch.object(
                filetransfer.chat, "get_current", return_value=None
            ):
                filetransfer.send_file(path)

        self.assert_rejected("Chưa chat với ai")

    def test_11_filename_contains_bar(self):
        with patch.object(filetransfer.os.path, "isfile", return_value=True):
            filetransfer.send_file("a|b.txt")

        self.assert_rejected("Tên file không hợp lệ")

    def test_12_filename_too_long(self):
        name = "á" * 128 + ".txt"

        with patch.object(filetransfer.os.path, "isfile", return_value=True):
            filetransfer.send_file(name)

        self.assert_rejected("Tên file không hợp lệ")
if __name__ == "__main__":
    unittest.main()