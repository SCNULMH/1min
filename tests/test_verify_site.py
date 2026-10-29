import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

# scripts 디렉터리를 모듈 탐색 경로에 추가
WORKSPACE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WORKSPACE_DIR / "scripts"))

from verify_site import TeeLogger, validate_redesign_markup


VALID_LANDING = """
<section id="hero"><h1>업무의 불편을 쓰이는 웹과 앱으로 만드는 개발자, 이민형.</h1>
<p>0개국어 Google Play 출시</p><p>이디그디 공개 서비스 운영</p><p>일민형 설립</p>
<a href="#featured-works">대표 작업 보기</a><a href="mailto:2min@1min.dev">문의하기</a></section>
<section id="featured-works"><article id="work-zerolingual"></article>
<article id="work-newbie">출시 준비 중</article><article id="work-idigdi">
<img src="assets/idigdi-main.webp"><img src="assets/idigdi-results.webp">
<img src="assets/idigdi-route.webp"><img src="assets/idigdi-mobile.webp"></article></section>
<section id="other-projects">클덱스</section><section id="experience"></section>
<section id="skills"></section><section id="company"></section><section id="contact"></section>
<footer><div id="en"></div><a href="#en">English</a></footer>
<a href="https://play.google.com/store/apps/details?id=com.scnulmh.zerolingual">Play</a>
<a href="intoss://zerolanguage">Toss</a>
<a href="https://app.notion.com/p/Newbie-Helper-401266b5e461803ebdeee369e3ef90eb">Newbie</a>
<a href="https://bw-jeju.duckdns.org">Idigdi</a>
<style>@media (prefers-reduced-motion: reduce) { * { transition-duration: 0.01ms; } }</style>
"""


class TestRedesignMarkup(unittest.TestCase):
    def test_complete_landing_contract(self):
        self.assertEqual(validate_redesign_markup(VALID_LANDING), [])

    def test_missing_hero_cta_and_capture(self):
        broken = VALID_LANDING.replace('href="#featured-works"', 'href="#skills"').replace('assets/idigdi-route.webp', 'assets/missing.webp')
        errors = validate_redesign_markup(broken)
        self.assertTrue(any("히어로 CTA" in error for error in errors))
        self.assertTrue(any("이디그디 캡처" in error for error in errors))

    def test_wrong_order_and_forbidden_copy(self):
        broken = VALID_LANDING.replace('<section id="other-projects">클덱스</section><section id="experience"></section>', '<section id="experience"></section><section id="other-projects">클덱스 롤백 스크립트</section>')
        errors = validate_redesign_markup(broken)
        self.assertTrue(any("섹션 순서" in error for error in errors))
        self.assertTrue(any("금지 문구" in error for error in errors))


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
