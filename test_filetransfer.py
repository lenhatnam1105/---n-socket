# test_filetransfer.py: test cho filetransfer.py (người C)
# Chạy: python -m unittest test_filetransfer -v
import hashlib
import os
import socket
import sys
import tempfile
import threading
import unittest

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
if __name__ == "__main__":
    unittest.main()