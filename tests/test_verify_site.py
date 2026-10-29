import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

# scripts 디렉터리를 모듈 탐색 경로에 추가
WORKSPACE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WORKSPACE_DIR / "scripts"))

from verify_site import TeeLogger


class TestTeeLogger(unittest.TestCase):
    def test_open_failure_raises_exception(self):
        """존재하지 않는 디렉터리 경로 등으로 파일 오픈 실패 시 예외 발생 검증"""
        stream = io.StringIO()
        invalid_path = Path("/non_existent_dir_12345/sub/log.txt")
        with self.assertRaises(OSError):
            TeeLogger(invalid_path, stream)

    def test_write_success(self):
        """정상적으로 stream과 파일에 메시지가 쓰이는지 검증"""
        stream = io.StringIO()
        with tempfile.NamedTemporaryFile("w+", encoding="utf-8", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        try:
            logger = TeeLogger(tmp_path, stream)
            logger.write("Hello, World!\n")
            logger.close()

            self.assertEqual(stream.getvalue(), "Hello, World!\n")
            self.assertEqual(tmp_path.read_text(encoding="utf-8"), "Hello, World!\n")
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_write_failure_raises_exception(self):
        """파일 쓰기 과정에서 에러 발생 시 예외가 전파되는지 검증"""
        stream = io.StringIO()
        with tempfile.NamedTemporaryFile("w+", encoding="utf-8", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        try:
            logger = TeeLogger(tmp_path, stream)
            logger.file.close()
            mock_file = MagicMock()
            mock_file.closed = False
            mock_file.write.side_effect = IOError("Disk full simulation")
            logger.file = mock_file

            with self.assertRaises(IOError) as ctx:
                logger.write("Test message")
            self.assertIn("Disk full simulation", str(ctx.exception))
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_flush_failure_raises_exception(self):
        """파일 flush 과정에서 에러 발생 시 예외가 전파되는지 검증"""
        stream = io.StringIO()
        with tempfile.NamedTemporaryFile("w+", encoding="utf-8", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        try:
            logger = TeeLogger(tmp_path, stream)
            logger.file.close()
            mock_file = MagicMock()
            mock_file.closed = False
            mock_file.flush.side_effect = IOError("Flush failure simulation")
            logger.file = mock_file

            with self.assertRaises(IOError) as ctx:
                logger.flush()
            self.assertIn("Flush failure simulation", str(ctx.exception))
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_close_failure_raises_exception(self):
        """파일 close 과정에서 에러 발생 시 예외가 전파되는지 검증"""
        stream = io.StringIO()
        with tempfile.NamedTemporaryFile("w+", encoding="utf-8", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        try:
            logger = TeeLogger(tmp_path, stream)
            logger.file.close()
            mock_file = MagicMock()
            mock_file.closed = False
            mock_file.close.side_effect = IOError("Close failure simulation")
            logger.file = mock_file

            with self.assertRaises(IOError) as ctx:
                logger.close()
            self.assertIn("Close failure simulation", str(ctx.exception))
        finally:
            tmp_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
