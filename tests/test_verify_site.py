import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

# scripts 디렉터리를 모듈 탐색 경로에 추가
WORKSPACE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WORKSPACE_DIR / "scripts"))

from verify_site import (
    DRAFT_FORBIDDEN_TERMS,
    TURNSTILE_PUBLIC_SITEKEY,
    TeeLogger,
    is_allowed_external_request,
    validate_privacy_markup,
    validate_redesign_markup,
)


VALID_LANDING = """
<nav><a href="#featured-works">대표 작업</a><a href="#company">회사</a><a href="#contact">문의</a></nav>
<section id="hero">
<h1>작은 불편을 <span>쓰이는 제품으로.</span></h1>
<p>일민형은 일상의 문제를 웹과 앱으로 풀어내는 1인 소프트웨어 회사입니다. 이민형이 직접 만들고 다듬습니다.</p>
<a href="#featured-works">대표 작업 보기</a><a href="#contact">문의하기</a>
<aside><a href="#work-zerolingual">0개국어</a><a href="#work-newbie">신입 이사원<span>출시 준비 중</span></a></aside>
</section>
<section id="featured-works"><article id="work-zerolingual"></article>
<article id="work-newbie">출시 준비 중</article></section>
<section id="other-projects"><article id="work-idigdi"><a href="https://bw-jeju.duckdns.org">서비스 방문하기</a><img src="assets/idigdi-main.webp"></article>
<ol class="contest-list"><li>2026 관광데이터 활용 공모전</li><li>제4회 문화체육관광 인공지능·데이터 활용 공모전</li><li>2026 부산광역시 공공데이터·AI 활용 창업경진대회</li><li>2026 세종특별자치시 데이터·AI 활용 창업경진대회</li><li>2026 보건의료빅데이터·AI 활용 창업경진대회</li><li>2026 고용24 국민참여 AI 고용서비스 발굴 온라인 해커톤</li><li>제11회 농업·농촌 공공데이터+AI 활용 창업경진대회</li></ol></section>
<section id="experience"></section>
<section id="company">
<p>업무의 불편을 쓰이는 웹과 앱으로 만드는 개발자, 이민형.</p>
<ul><li>최적화된 서비스를 만들어내는 개발자</li><li>경험을 통해 성장해 나가는 개발자</li><li>사람들의 불편함 속에서 필요로 하는 것을 고민하는 개발자</li></ul>
<dl><div><dt>상호</dt><dd>일민형 (1min)</dd></div><div><dt>대표자</dt><dd>이민형</dd></div><div><dt>사업자등록번호</dt><dd>114-40-01468</dd></div><div><dt>업종</dt><dd>응용 소프트웨어 개발 및 공급</dd></div><div><dt>소재지</dt><dd>전라남도 나주시</dd></div><div><dt>설립</dt><dd>2026년 10월</dd></div></dl>
</section>
<section id="contact">
<a href="mailto:2min@1min.dev">2min@1min.dev</a><button id="copy-email" type="button">주소 복사</button><p id="copy-status" role="status" aria-live="polite"></p>
<div class="collection-note"><p>이메일 주소, 문의 내용 / 답장 / 보유 기간: 답변 완료 후 1년(이후 지체 없이 삭제) / 국외 이전: Cloudflare</p><a href="privacy.html">홈페이지 개인정보처리방침</a></div>
<div id="contact-fallback" hidden><p>현재 온라인 양식은 준비 중입니다. 이메일로 직접 문의해 주세요.</p></div>
<form id="contact-form" hidden>
<label for="contact-email">이메일</label><input id="contact-email" name="email" type="email" required>
<label for="contact-message">내용</label><textarea id="contact-message" name="message" maxlength="4000" required></textarea>
<output id="character-count">0 / 4000자</output>
<div class="honeypot" aria-hidden="true" hidden><label for="contact-website">웹사이트</label><input id="contact-website" name="website" type="text" tabindex="-1" autocomplete="off"></div>
<input id="contact-started-at" name="startedAt" type="hidden">
<div class="cf-turnstile" data-sitekey="TURNSTILE_SITE_KEY"></div>
<input id="contact-consent" type="checkbox" required><label for="contact-consent">개인정보 수집·이용 및 국외 이전(Cloudflare)에 동의합니다. (필수)</label>
<button id="contact-submit" type="submit">문의 보내기</button>
<p id="form-status" role="status" aria-live="polite"></p>
<p id="form-fallback" hidden><a href="mailto:2min@1min.dev">이메일 문의</a></p>
</form>
</section>
<footer><a href="privacy.html">개인정보처리방침</a><div id="en"></div><a href="#en">English</a></footer>
<a href="https://play.google.com/store/apps/details?id=com.scnulmh.zerolingual">Play</a>
<a href="intoss://zerolanguage">Toss</a>
<a href="https://app.notion.com/p/Newbie-Helper-401266b5e461803ebdeee369e3ef90eb">Newbie</a>
<a href="https://bw-jeju.duckdns.org">Idigdi</a>
<style>.honeypot { display: none !important; } @media (prefers-reduced-motion: reduce) { * { transition-duration: 0.01ms; } }</style>
<script>
const s = 'https://challenges.cloudflare.com/turnstile/v0/api.js';
const opts = { async: true, defer: true, endpoint: 'https://contact.1min.dev/api/contact' };
</script>
"""


class TestRedesignMarkup(unittest.TestCase):
    def test_complete_landing_contract(self):
        self.assertEqual(validate_redesign_markup(VALID_LANDING), [])
        real_index = (WORKSPACE_DIR / "index.html").read_text(encoding="utf-8")
        self.assertEqual(validate_redesign_markup(real_index), [])

    def test_missing_hero_cta_and_extra_capture(self):
        broken = (
            VALID_LANDING.replace('href="#contact">문의하기', 'href="mailto:2min@1min.dev">문의하기')
            .replace('assets/idigdi-main.webp', 'assets/idigdi-main.webp"><img src="assets/idigdi-route.webp')
        )
        errors = validate_redesign_markup(broken)
        self.assertTrue(any("히어로 CTA" in error for error in errors))
        self.assertTrue(any("이디그디 캡처" in error for error in errors))

    def test_wrong_order_and_forbidden_copy(self):
        broken = VALID_LANDING.replace('<section id="experience"></section>', '<section id="skills">롤백 스크립트</section><section id="experience"></section>')
        errors = validate_redesign_markup(broken)
        self.assertTrue(any("섹션 순서" in error for error in errors))
        self.assertTrue(any("금지 문구" in error for error in errors))

    def test_contest_list_missing_or_outside_other_projects(self):
        start = VALID_LANDING.index('<ol class="contest-list">')
        end = VALID_LANDING.index('</ol>', start) + len('</ol>')
        contest_list = VALID_LANDING[start:end]
        for broken in (
            VALID_LANDING.replace(contest_list, ''),
            VALID_LANDING.replace(contest_list, '').replace('<section id="experience">', contest_list + '<section id="experience">'),
            VALID_LANDING.replace('2026 세종특별자치시 데이터·AI 활용 창업경진대회', ''),
        ):
            self.assertTrue(any("공모전 도전 목록" in error for error in validate_redesign_markup(broken)))
        with_result = VALID_LANDING.replace('2026 관광데이터 활용 공모전', '2026 관광데이터 활용 공모전 수상')
        self.assertTrue(any("공모전" in error for error in validate_redesign_markup(with_result)))

    def test_contact_form_labels_and_consent_required(self):
        missing_email_label = VALID_LANDING.replace('for="contact-email"', 'for="wrong-id"')
        self.assertTrue(any("이메일 라벨" in error for error in validate_redesign_markup(missing_email_label)))

        missing_message_limit = VALID_LANDING.replace('maxlength="4000"', '')
        self.assertTrue(any("내용 라벨·4000자" in error for error in validate_redesign_markup(missing_message_limit)))

        missing_consent_required = VALID_LANDING.replace(
            '<input id="contact-consent" type="checkbox" required>',
            '<input id="contact-consent" type="checkbox">',
        )
        self.assertTrue(any("필수 동의" in error for error in validate_redesign_markup(missing_consent_required)))

        note_start = VALID_LANDING.index('<div class="collection-note">')
        note_end = VALID_LANDING.index('</div>', note_start) + len('</div>')
        note_block = VALID_LANDING[note_start:note_end]
        note_after_form = VALID_LANDING.replace(note_block, '').replace('</form>', '</form>' + note_block)
        self.assertTrue(any("수집 안내" in error for error in validate_redesign_markup(note_after_form)))

    def test_honeypot_hidden_and_attributes(self):
        for target, replacement in (
            ('aria-hidden="true"', ''),
            ('tabindex="-1"', 'tabindex="0"'),
            ('autocomplete="off"', ''),
            ('.honeypot { display: none !important; }', '.honeypot { opacity: 0; }'),
        ):
            broken = VALID_LANDING.replace(target, replacement)
            self.assertTrue(any("허니팟" in error for error in validate_redesign_markup(broken)), msg=target)

    def test_privacy_links_and_placeholder_fallback(self):
        missing_footer_privacy = VALID_LANDING.replace('<footer><a href="privacy.html">개인정보처리방침</a>', '<footer>')
        self.assertTrue(any("바닥글 privacy.html" in error for error in validate_redesign_markup(missing_footer_privacy)))

        missing_placeholder = VALID_LANDING.replace('data-sitekey="TURNSTILE_SITE_KEY"', 'data-sitekey=""')
        self.assertTrue(any("Turnstile 위젯" in error for error in validate_redesign_markup(missing_placeholder)))

        missing_fallback = VALID_LANDING.replace('id="contact-fallback"', 'id="missing-fallback"')
        self.assertTrue(any("자리표시 키 대체 안내" in error for error in validate_redesign_markup(missing_fallback)))

        with_inner_html = VALID_LANDING.replace('</script>', 'document.body.innerHTML = "";</script>')
        self.assertTrue(any("innerHTML" in error for error in validate_redesign_markup(with_inner_html)))

    def test_duplicate_fallback_controls_and_consent_transfer_rejected(self):
        dup_mail = VALID_LANDING.replace(
            '<div id="contact-fallback" hidden><p>현재 온라인 양식은 준비 중입니다. 이메일로 직접 문의해 주세요.</p></div>',
            '<div id="contact-fallback" hidden><a href="mailto:2min@1min.dev">2min@1min.dev</a></div>',
        )
        self.assertTrue(any("중복 노출" in error for error in validate_redesign_markup(dup_mail)))

        dup_button = VALID_LANDING.replace(
            '<div id="contact-fallback" hidden><p>현재 온라인 양식은 준비 중입니다. 이메일로 직접 문의해 주세요.</p></div>',
            '<div id="contact-fallback" hidden><button id="fallback-copy" type="button">주소 복사</button></div>',
        )
        self.assertTrue(any("중복 노출" in error for error in validate_redesign_markup(dup_button)))

        missing_transfer_consent = VALID_LANDING.replace(
            "개인정보 수집·이용 및 국외 이전(Cloudflare)에 동의합니다. (필수)",
            "개인정보 수집·이용 안내를 확인하고 동의합니다. (필수)",
        )
        self.assertTrue(any("필수 동의" in error for error in validate_redesign_markup(missing_transfer_consent)))

    def test_draft_phrases_rejected_and_privacy_contract(self):
        real_index = (WORKSPACE_DIR / "index.html").read_text(encoding="utf-8")
        real_privacy = (WORKSPACE_DIR / "privacy.html").read_text(encoding="utf-8")
        self.assertEqual(validate_privacy_markup(real_privacy), [])

        for term in DRAFT_FORBIDDEN_TERMS:
            self.assertNotIn(term, real_index)
            self.assertNotIn(term, real_privacy)

            draft_landing = VALID_LANDING.replace("</section>\n<footer>", f"<p>{term}</p></section>\n<footer>")
            self.assertTrue(any(term in error for error in validate_redesign_markup(draft_landing)), msg=term)

            draft_privacy = real_privacy.replace("</main>", f"<p>{term}</p></main>")
            self.assertTrue(any(term in error for error in validate_privacy_markup(draft_privacy)), msg=term)

        missing_retention = real_privacy.replace("답변 완료 후 1년", "답변 완료 후 30일")
        self.assertTrue(any("답변 완료 후 1년" in error for error in validate_privacy_markup(missing_retention)))

        unofficial_link = real_privacy.replace("</main>", '<a href="https://example.com/policy">외부</a></main>')
        self.assertTrue(any("비공식 외부 링크" in error for error in validate_privacy_markup(unofficial_link)))

    def test_turnstile_sitekey_real_and_placeholder_formats(self):
        self.assertEqual(validate_redesign_markup(VALID_LANDING), [])

        with_real_key = VALID_LANDING.replace(
            'data-sitekey="TURNSTILE_SITE_KEY"',
            f'data-sitekey="{TURNSTILE_PUBLIC_SITEKEY}"',
        )
        self.assertEqual(validate_redesign_markup(with_real_key), [])

        real_index = (WORKSPACE_DIR / "index.html").read_text(encoding="utf-8")
        self.assertIn(f'data-sitekey="{TURNSTILE_PUBLIC_SITEKEY}"', real_index)
        self.assertIn("siteKey==='TURNSTILE_SITE_KEY'", real_index)

        for invalid_key in ("", "invalid", "0x12", "1x4AAAAAAFsvfCbrajidkTlI", "0x4AAAAAAFsvfCbrajidkTlI bad"):
            broken = VALID_LANDING.replace('data-sitekey="TURNSTILE_SITE_KEY"', f'data-sitekey="{invalid_key}"')
            self.assertTrue(
                any("Turnstile 위젯" in error for error in validate_redesign_markup(broken)),
                msg=f"invalid key should be rejected: {invalid_key!r}",
            )

    def test_external_request_allowlist(self):
        base_url = "http://127.0.0.1:8123"
        for allowed in (
            base_url,
            f"{base_url}/index.html",
            f"{base_url}/assets/fonts/Pretendard-Regular.woff2",
            "data:image/svg+xml;utf8,<svg></svg>",
            "https://challenges.cloudflare.com",
            "https://challenges.cloudflare.com/turnstile/v0/api.js",
            "https://challenges.cloudflare.com/cdn-cgi/challenge-platform/h/b/turnstile",
        ):
            self.assertTrue(is_allowed_external_request(allowed, base_url), msg=allowed)

        for rejected in (
            "http://challenges.cloudflare.com/turnstile/v0/api.js",
            "https://challenges.cloudflare.com.attacker.com/turnstile/v0/api.js",
            "https://challenges.cloudflare.com@attacker.com/turnstile/v0/api.js",
            "http://127.0.0.1:81234/index.html",
            "https://contact.1min.dev/api/contact",
            "https://fonts.googleapis.com/css2?family=Noto+Sans+KR",
            "https://cdn.jsdelivr.net/npm/library.js",
        ):
            self.assertFalse(is_allowed_external_request(rejected, base_url), msg=rejected)


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
