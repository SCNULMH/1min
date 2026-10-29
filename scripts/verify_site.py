#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
1min.dev 사이트 정적 및 브라우저 검증 스크립트.
"""

import argparse
import hashlib
import os
import re
import socket
import subprocess
import sys
import time
from html.parser import HTMLParser
from pathlib import Path
from PIL import Image

WORKSPACE_DIR = Path(__file__).resolve().parent.parent

# Playwright 및 임시 파일용 디렉터리 설정 (권한 문제 방지)
PWTMP_DIR = Path(r"C:\Users\user\build-tmp\pwtmp")
PWTMP_DIR.mkdir(parents=True, exist_ok=True)
os.environ["TEMP"] = str(PWTMP_DIR)
os.environ["TMP"] = str(PWTMP_DIR)

# 실행 로그를 C:\Users\user\build-tmp\pwtmp\verify-log.txt 에 남기기 위한 티(Tee) 로거
VERIFY_LOG_FILE = PWTMP_DIR / "verify-log.txt"


class TeeLogger:
    def __init__(self, filename, stream):
        self.file = open(filename, "w", encoding="utf-8")
        self.stream = stream

    def write(self, message):
        self.stream.write(message)
        self.file.write(message)
        self.file.flush()

    def flush(self):
        self.stream.flush()
        self.file.flush()

    def close(self):
        if not self.file.closed:
            self.file.close()

# 보호 문서 기준 SHA-256 해시
PROTECTED_HASHES = {
    "newbie-helper/privacy.html": "f25896a13cc1c9457d9a54d9cd466f429aa9462a7e44a5937823833bd35f6f58",
    "newbie-helper/account-deletion.html": "6b1e209c552c54c4e2b80862dc052abc6eb709c67c0c3ede78cd8691ca8a14c7",
}

COMPANY_INFO_ITEMS = [
    ("상호", "일민형 (1min)"),
    ("대표자", "이민형"),
    ("사업자등록번호", "114-40-01468"),
    ("업종", "응용 소프트웨어 개발 및 공급"),
    ("소재지", "전라남도 나주시"),
    ("설립", "2026년 10월"),
]

EXPECTED_SECTIONS = [
    "intro",
    "app",
    "projects",
    "experience",
    "skills",
    "company",
    "contact",
]


class SiteHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.nav_links = []
        self.local_links = []
        self.image_srcs = []
        self.in_nav = False

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if "id" in attrs_dict:
            self.ids.append((tag, attrs_dict["id"]))

        if tag == "nav":
            self.in_nav = True

        if tag == "a" and "href" in attrs_dict:
            href = attrs_dict["href"]
            if self.in_nav and href.startswith("#"):
                self.nav_links.append(href[1:])
            elif not href.startswith(("http://", "https://", "mailto:", "#", "intoss:")):
                self.local_links.append(href)

        if tag in ("img", "source") and "src" in attrs_dict:
            self.image_srcs.append(attrs_dict["src"])
        if tag == "source" and "srcset" in attrs_dict:
            self.image_srcs.append(attrs_dict["srcset"])

    def handle_endtag(self, tag):
        if tag == "nav":
            self.in_nav = False


def calculate_sha256(file_path: Path) -> str:
    sha = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(8192):
            sha.update(chunk)
    return sha.hexdigest().lower()


def run_static_checks() -> tuple[int, int]:
    passed = 0
    failed = 0

    print("=== [정적 검증 시작] ===")

    # 1. 보호 문서 해시 검증
    for rel_path, expected_hash in PROTECTED_HASHES.items():
        p = WORKSPACE_DIR / rel_path
        if not p.is_file():
            print(f"❌ [실패] 보호 문서 누락: {rel_path}")
            failed += 1
            continue
        actual_hash = calculate_sha256(p)
        if actual_hash == expected_hash:
            print(f"✅ [통과] 보호 문서 해시 일치: {rel_path}")
            passed += 1
        else:
            print(f"❌ [실패] 보호 문서 해시 불일치: {rel_path} (기대: {expected_hash}, 실제: {actual_hash})")
            failed += 1

    # 2. index.html 읽기
    index_path = WORKSPACE_DIR / "index.html"
    if not index_path.is_file():
        print("❌ [실패] index.html 파일이 존재하지 않습니다.")
        failed += 1
        return passed, failed
    with open(index_path, "r", encoding="utf-8") as f:
        html_content = f.read()

    # 3. HTML 파싱 및 ID, 링크, 목차 검사
    parser = SiteHTMLParser()
    parser.feed(html_content)

    # 섹션 순서 및 ID 중복 검사
    id_list = [id_val for _, id_val in parser.ids]
    id_counts = {id_val: id_list.count(id_val) for id_val in id_list}
    duplicate_ids = [id_val for id_val, count in id_counts.items() if count > 1]
    if duplicate_ids:
        print(f"❌ [실패] 중복된 ID 발견: {duplicate_ids}")
        failed += 1
    else:
        print("✅ [통과] HTML 내 ID 중복 없음")
        passed += 1

    # 기대 섹션 ID 존재 및 순서 확인
    found_section_indices = []
    missing_sections = []
    for sec in EXPECTED_SECTIONS:
        if sec in id_list:
            found_section_indices.append(id_list.index(sec))
        else:
            missing_sections.append(sec)

    if missing_sections:
        print(f"❌ [실패] 필수 섹션 누락: {missing_sections}")
        failed += 1
    elif found_section_indices != sorted(found_section_indices):
        print(f"❌ [실패] 섹션 순서 불일치: 기대순서={EXPECTED_SECTIONS}")
        failed += 1
    else:
        print(f"✅ [통과] 7개 섹션 순서 일치: {EXPECTED_SECTIONS}")
        passed += 1

    # 목차 nav 링크와 섹션 ID 연결 확인
    nav_missing = [n for n in parser.nav_links if n not in id_list]
    if nav_missing:
        print(f"❌ [실패] 네비게이션 목차에 대상 없는 앵커: {nav_missing}")
        failed += 1
    else:
        print(f"✅ [통과] 네비게이션 목차 앵커 연결 완벽: {parser.nav_links}")
        passed += 1

    # 4. 이메일 주소 검사 (전부 2min@1min.dev 여야 함)
    found_emails = set(re.findall(r"[\w\.-]+@[\w\.-]+\.\w+", html_content))
    allowed_emails = {"2min@1min.dev"}
    invalid_emails = found_emails - allowed_emails
    if invalid_emails:
        print(f"❌ [실패] 허용되지 않은 이메일 주소 발견: {invalid_emails}")
        failed += 1
    elif "2min@1min.dev" in found_emails:
        print("✅ [통과] 홈페이지 내 모든 이메일이 2min@1min.dev 로 통일됨")
        passed += 1
    else:
        print("❌ [실패] 2min@1min.dev 이메일 주소가 발견되지 않음")
        failed += 1

    # 5. 회사 정보 6개 항목 보존 검사
    missing_company_info = []
    for term, desc in COMPANY_INFO_ITEMS:
        if term not in html_content or desc not in html_content:
            missing_company_info.append((term, desc))
    if missing_company_info:
        print(f"❌ [실패] 회사 정보 항목 누락: {missing_company_info}")
        failed += 1
    else:
        print("✅ [통과] 회사 정보 6개 항목 완벽 보존")
        passed += 1

    # 6. 금지 정보 검사 (전화번호, 주민번호, 개인 이메일, 내부 캡처 파일명, 고객사 실명, 근거 초과 날짜, 비공개 링크 등)
    forbidden_issues = []
    if re.search(r"010-\d{4}-\d{4}", html_content) or re.search(r"0[2-6]\d?-\d{3,4}-\d{4}", html_content):
        forbidden_issues.append("전화번호 패턴 발견")
    if "hjs8396@" in html_content:
        forbidden_issues.append("개인 이메일(hjs8396@) 발견")
    if re.search(r"\b\d{6}-[1-4]\d{6}\b", html_content):
        forbidden_issues.append("주민번호 패턴 발견")
    if "05_KPS" in html_content:
        forbidden_issues.append("내부 캡처 파일명 노출 발견")
    if "광양바이오매스" in html_content:
        forbidden_issues.append("고객사 실명(광양바이오매스) 발견")
    if "KPS" in html_content:
        forbidden_issues.append("고객사 실명(KPS) 발견")
    if "2025.12" in html_content:
        forbidden_issues.append("근거 초과 날짜(2025.12) 발견")
    if "notion.so" in html_content:
        forbidden_issues.append("비공개 노션 링크(notion.so) 발견")
    if "작업 확인 시점" in html_content:
        forbidden_issues.append("제거 대상 '작업 확인 시점' 표기 발견")
    if forbidden_issues:
        print(f"❌ [실패] 금지 정보 검출: {forbidden_issues}")
        failed += 1
    else:
        print("✅ [통과] 비공개/금지 정보(전화번호, 주민번호, 개인메일, 내부자료 파일명) 미포함 확인")
        passed += 1

    # 7. 참조된 로컬 파일(자산, 상대 링크) 실재 여부 검사
    referenced_files = set(parser.local_links + parser.image_srcs)
    css_urls = re.findall(r"url\(['\"]?([^'\")]+)['\"]?\)", html_content)
    for u in css_urls:
        referenced_files.add(u)

    missing_files = []
    for f in referenced_files:
        f_clean = f.split("?")[0].split("#")[0]
        if f_clean in ("", ".", "./", "/"):
            continue
        file_path = WORKSPACE_DIR / f_clean
        if not file_path.is_file() and not file_path.is_dir():
            missing_files.append(f)
    if missing_files:
        print(f"❌ [실패] 존재하지 않는 로컬 자산 참조: {missing_files}")
        failed += 1
    else:
        print(f"✅ [통과] 참조된 로컬 자산 및 링크 {len(referenced_files)}개 모두 존재 확인")
        passed += 1

    # 8. 새 캡처 WebP 이미지 규격 검사
    newbie_shots = ["assets/newbie-home.webp", "assets/newbie-life.webp"]
    shot_errors = []
    for shot_rel in newbie_shots:
        sp = WORKSPACE_DIR / shot_rel
        if not sp.is_file():
            shot_errors.append(f"{shot_rel} 파일 누락")
            continue
        size_bytes = os.path.getsize(sp)
        if size_bytes > 300000:
            shot_errors.append(f"{shot_rel} 크기 초과 ({size_bytes} > 300,000 bytes)")
        try:
            with Image.open(sp) as img:
                if img.format != "WEBP":
                    shot_errors.append(f"{shot_rel} 포맷 오류 ({img.format})")
                w, h = img.size
                if max(w, h) > 1200:
                    shot_errors.append(f"{shot_rel} 긴 변 초과 (max({w},{h}) > 1200)")
        except Exception as e:
            shot_errors.append(f"{shot_rel} 이미지 로드 실패: {e}")

    if shot_errors:
        print(f"❌ [실패] 새 캡처 규격 위반: {shot_errors}")
        failed += 1
    else:
        print("✅ [통과] 신규 WebP 캡처 규격 만족 (긴 변 <= 1200, 크기 <= 300KB)")
        passed += 1

    # 9. 글꼴 파일 및 문서 보관 검사
    font_files = [
        "assets/fonts/Pretendard-Regular.woff2",
        "assets/fonts/Pretendard-SemiBold.woff2",
        "assets/fonts/OFL-1.1.txt",
        "assets/fonts/README.md",
    ]
    missing_fonts = [f for f in font_files if not (WORKSPACE_DIR / f).is_file()]
    if missing_fonts:
        print(f"❌ [실패] 자체 호스팅 글꼴 파일 누락: {missing_fonts}")
        failed += 1
    else:
        print("✅ [통과] Pretendard 자체 호스팅 파일 및 라이선스·README 존재 확인")
        passed += 1

    # 10. Pretendard 제작자 표기 라이선스 일치 검사 (Kil Hyung-jin)
    readme_font = WORKSPACE_DIR / "assets/fonts/README.md"
    readme_text = readme_font.read_text(encoding="utf-8") if readme_font.is_file() else ""
    if "Kil Hyung-jin" in html_content and "Kil Hyung-jin" in readme_text:
        print("✅ [통과] Pretendard 제작자 표기(Kil Hyung-jin) 동봉 라이선스와 일치 확인")
        passed += 1
    else:
        print("❌ [실패] Pretendard 제작자 표기 오류 (Kil Hyung-jin 누락)")
        failed += 1

    # 11. Polishing 프로젝트 제외 확인
    if "Polishing" in html_content:
        print("❌ [실패] Polishing 프로젝트가 index.html에 남아 있음")
        failed += 1
    else:
        print("✅ [통과] Polishing 프로젝트 제외 확인")
        passed += 1

    # 12. 0개국어 앱인토스 출시 링크 및 배지 검사
    if "intoss://zerolanguage" in html_content and "Google Play · 앱인토스 출시" in html_content:
        print("✅ [통과] 0개국어 앱인토스 출시 링크(intoss://zerolanguage) 및 배지 확인")
        passed += 1
    else:
        print("❌ [실패] 0개국어 앱인토스 출시 링크 또는 배지 누락")
        failed += 1

    # 13. 영어 소개 영역 id="en" 앵커 존재 검사
    if "en" in id_list:
        print("✅ [통과] 영어 소개 영역 앵커(id=\"en\") 존재 확인")
        passed += 1
    else:
        print("❌ [실패] 영어 소개 영역 앵커(id=\"en\") 누락")
        failed += 1

    # 14. 확정 경력 및 교육 항목 검사 (사용자 제공 2026-10-29 기준)
    career_errors = []
    if "(주)아이티맨" not in html_content or "2025.06.16 ~ 재직 중" not in html_content:
        career_errors.append("(주)아이티맨 재직 기간(2025.06.16 ~ 재직 중) 누락")
    if "(주)아이티맨 — " in html_content:
        career_errors.append("아이티맨 직급 표기 발견(비워 두어야 함)")
    if "(주)에이스퀘어 — 현장실습생" not in html_content or "2023.12 ~ 2024.01" not in html_content:
        career_errors.append("(주)에이스퀘어 현장실습생(2023.12 ~ 2024.01) 누락")
    if "스마트인재개발원 — DCX 개발자 과정" not in html_content or "2024.10.07 ~ 2025.04.04" not in html_content:
        career_errors.append("스마트인재개발원 교육 과정(2024.10.07 ~ 2025.04.04) 누락")
    if "교육</h3>" not in html_content:
        career_errors.append("교육 항목 분리 표기 누락")

    if career_errors:
        print(f"❌ [실패] 확정 경력/교육 요건 불일치: {career_errors}")
        failed += 1
    else:
        print("✅ [통과] 확정 경력((주)아이티맨, (주)에이스퀘어) 및 교육(스마트인재개발원) 분리 반영 확인")
        passed += 1
    print(f"=== 정적 검증 완료: 통과 {passed}, 실패 {failed} ===")
    return passed, failed


def run_browser_checks(preview_dir_str: str) -> tuple[int, int]:
    passed = 0
    failed = 0

    print("=== [브라우저 및 반응형/미리보기 검증 시작] ===")
    preview_dir = Path(preview_dir_str)
    preview_dir.mkdir(parents=True, exist_ok=True)

    # 1. 사용 가능한 빈 포트 찾기
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    # 2. python -m http.server 구동
    cmd = [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"]
    print(f"ℹ️ 로컬 HTTP 서버 시작 (PID 대기 중): 127.0.0.1:{port} (경로: {WORKSPACE_DIR})")
    server_proc = subprocess.Popen(cmd, cwd=str(WORKSPACE_DIR), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    server_pid = server_proc.pid
    print(f"ℹ️ 로컬 HTTP 서버 실행됨: PID {server_pid}")

    try:
        # 서버 준비 대기
        base_url = f"http://127.0.0.1:{port}"
        ready = False
        for _ in range(20):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                    ready = True
                    break
            except OSError:
                time.sleep(0.1)

        if not ready:
            print(f"❌ [실패] HTTP 서버 응답 대기 시간 초과 (PID {server_pid})")
            failed += 1
            return passed, failed
        else:
            print("✅ [통과] 로컬 HTTP 서버 정상 구동 확인")
            passed += 1

        # 3. Playwright 실행
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)

            test_cases = [
                {"name": "desktop-1280-light", "width": 1280, "height": 800, "color_scheme": "light", "shot": True},
                {"name": "desktop-1280-dark", "width": 1280, "height": 800, "color_scheme": "dark", "shot": True},
                {"name": "mobile-390-light", "width": 390, "height": 844, "color_scheme": "light", "shot": True},
                {"name": "mobile-390-dark", "width": 390, "height": 844, "color_scheme": "dark", "shot": True},
                {"name": "mobile-360-light", "width": 360, "height": 640, "color_scheme": "light", "shot": False},
                {"name": "mobile-360-dark", "width": 360, "height": 640, "color_scheme": "dark", "shot": False},
            ]

            for tc in test_cases:
                context = browser.new_context(
                    viewport={"width": tc["width"], "height": tc["height"]},
                    color_scheme=tc["color_scheme"],
                )
                page = context.new_page()

                console_errors = []
                asset_404s = []
                external_requests = []

                page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
                page.on("response", lambda res: asset_404s.append(res.url) if res.status >= 400 else None)
                page.on(
                    "request",
                    lambda req: external_requests.append(req.url)
                    if not req.url.startswith(base_url) and not req.url.startswith("data:")
                    else None,
                )

                response = page.goto(base_url + "/index.html", wait_until="networkidle")
                if not response or response.status != 200:
                    print(f"❌ [실패] [{tc['name']}] 페이지 로드 실패 (상태: {response.status if response else 'None'})")
                    failed += 1
                    context.close()
                    continue

                # 가로 스크롤(가로 넘침) 검사
                scroll_w = page.evaluate("document.documentElement.scrollWidth")
                client_w = page.evaluate("document.documentElement.clientWidth")
                if scroll_w > client_w:
                    print(f"❌ [실패] [{tc['name']}] 가로 스크롤 발생! scrollWidth={scroll_w} > clientWidth={client_w}")
                    failed += 1
                else:
                    passed += 1

                # [REWORK 3] 지연 로딩 이미지 모두 eager 전환 및 스크롤로 로드 요청 완료 대기
                page.evaluate("""(() => {
                    document.querySelectorAll('img[loading="lazy"]').forEach(img => {
                        img.loading = 'eager';
                    });
                })()""")
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                try:
                    page.wait_for_function(
                        "() => Array.from(document.querySelectorAll('img')).every(img => img.complete && img.naturalWidth > 0)",
                        timeout=5000,
                    )
                    fonts_ready = page.evaluate("document.fonts.ready.then(() => true)")
                    if fonts_ready:
                        passed += 1
                    else:
                        print(f"❌ [실패] [{tc['name']}] 글꼴 로딩 완료 실패")
                        failed += 1
                except Exception as e:
                    print(f"❌ [실패] [{tc['name']}] 이미지/글꼴 로딩 완료 타임아웃: {e}")
                    failed += 1

                # [REWORK 2] 앵커 이동 완료 대기 및 헤더 가림 / 뷰포트 내 표시 검사
                # 부드러운 스크롤 끄고 즉각적이고 안정적인 이동 보장
                page.evaluate("document.documentElement.style.scrollBehavior = 'auto'")
                nav_anchors = page.evaluate("[...document.querySelectorAll('nav a[href^=\"#\"]')].map(a => a.getAttribute('href'))")
                nav_overflow_errors = []
                for href in nav_anchors:
                    page.click(f"nav a[href='{href}']")
                    page.wait_for_timeout(80)
                    pos = page.evaluate(f"""(() => {{
                        const header = document.querySelector('.top');
                        const header_bottom = header ? header.getBoundingClientRect().bottom : 0;
                        const el = document.getElementById('{href[1:]}');
                        if (!el) return null;
                        const h = el.querySelector('h1, h2, h3') || el;
                        const r = h.getBoundingClientRect();
                        return {{
                            heading_top: r.top,
                            heading_bottom: r.bottom,
                            header_bottom: header_bottom,
                            vh: window.innerHeight
                        }};
                    }})()""")
                    if not pos:
                        nav_overflow_errors.append(f"{href} 대상 요소 없음")
                    else:
                        # 1. 제목 상단이 헤더 아래에 위치하는가
                        if pos["heading_top"] < (pos["header_bottom"] - 1):
                            nav_overflow_errors.append(
                                f"{href} 제목이 고정 헤더에 가려짐 (heading_top={pos['heading_top']:.1f} < header_bottom={pos['header_bottom']:.1f})"
                            )
                        # 2. 제목 전체가 뷰포트 안에 보이는가
                        if pos["heading_bottom"] > (pos["vh"] + 1):
                            nav_overflow_errors.append(
                                f"{href} 제목 하단이 뷰포트 밖으로 벗어남 (heading_bottom={pos['heading_bottom']:.1f} > vh={pos['vh']:.1f})"
                            )

                if nav_overflow_errors:
                    print(f"❌ [실패] [{tc['name']}] 목차 이동 시 가림/넘침 발생: {nav_overflow_errors}")
                    failed += 1
                else:
                    passed += 1

                # 글꼴 로드 및 적용 정밀 검사 (desktop-1280-light에서 1회 정밀 검사)
                if tc["name"] == "desktop-1280-light":
                    pretendard_400 = page.evaluate("document.fonts.check('400 16px Pretendard')")
                    pretendard_600 = page.evaluate("document.fonts.check('600 16px Pretendard')")
                    font_gwangyang_loaded = page.evaluate("document.fonts.check('400 24px \"Gwangyang Touching\"')")

                    if pretendard_400 and pretendard_600:
                        print("✅ [통과] Pretendard 400 및 600 글꼴 브라우저 로드 성공")
                        passed += 1
                    else:
                        print(f"❌ [실패] Pretendard 글꼴 로드 실패 (400={pretendard_400}, 600={pretendard_600})")
                        failed += 1

                    if font_gwangyang_loaded:
                        print("✅ [통과] Gwangyang Touching(광양감동체) 글꼴 브라우저 로드 성공")
                        passed += 1
                    else:
                        print("❌ [실패] Gwangyang Touching 글꼴 브라우저 로드 실패")
                        failed += 1

                    h1_font = page.evaluate("getComputedStyle(document.querySelector('h1')).fontFamily")
                    h2_font = page.evaluate("getComputedStyle(document.querySelector('h2')).fontFamily")
                    body_font = page.evaluate("getComputedStyle(document.body).fontFamily")
                    if "Pretendard" in h1_font and "Pretendard" in h2_font and "Pretendard" in body_font:
                        print("✅ [통과] 본문 및 메인 제목(h1, h2)에 Pretendard 글꼴 적용 확인")
                        passed += 1
                    else:
                        print(f"❌ [실패] 본문/제목 글꼴 불일치: h1={h1_font}, h2={h2_font}, body={body_font}")
                        failed += 1

                    gwangyang_elem_font = page.evaluate(
                        "getComputedStyle(document.querySelector('.font-gwangyang')).fontFamily"
                    )
                    other_gwangyang_elements = page.evaluate("""(() => {
                        const all = document.querySelectorAll('body *:not(.font-gwangyang):not(.font-gwangyang *)');
                        const leaked = [];
                        for (const el of all) {
                            const fam = getComputedStyle(el).fontFamily;
                            if (fam.includes('Gwangyang')) {
                                leaked.push(el.tagName + (el.id ? '#' + el.id : '') + (el.className ? '.' + el.className : ''));
                            }
                        }
                        return leaked;
                    })()""")

                    if "Gwangyang" in gwangyang_elem_font and len(other_gwangyang_elements) == 0:
                        print("✅ [통과] 광양감동체 0개국어 표제 한정 적용 및 타 요소 누출 없음 확인")
                        passed += 1
                    else:
                        print(f"❌ [실패] 광양감동체 적용 대상 오류: 표제={gwangyang_elem_font}, 누출요소={other_gwangyang_elements}")
                        failed += 1

                    keyboard_nav_ok = page.evaluate("""(() => {
                        const links = document.querySelectorAll('a');
                        return links.length > 0;
                    })()""")
                    page.keyboard.press("Tab")
                    first_focus = page.evaluate("document.activeElement.tagName")
                    page.keyboard.press("Tab")
                    second_focus = page.evaluate("document.activeElement.tagName")
                    if keyboard_nav_ok and first_focus == "A" and second_focus == "A":
                        print("✅ [통과] 키보드 Tab 포커스 정상 작동 확인")
                        passed += 1
                    else:
                        print(f"❌ [실패] 키보드 포커스 오류 (focus1={first_focus}, focus2={second_focus})")
                        failed += 1

                # [REWORK 1] 미리보기 캡처 직전 부드러운 스크롤 끄고 맨 위로 복귀 및 위치 안정화
                if tc["shot"]:
                    page.evaluate("document.documentElement.style.scrollBehavior = 'auto'")
                    page.evaluate("window.scrollTo(0, 0)")
                    try:
                        page.wait_for_function("() => window.scrollY === 0", timeout=2000)
                    except Exception:
                        pass
                    page.wait_for_timeout(100)

                    out_path = preview_dir / f"{tc['name']}.png"
                    page.screenshot(path=str(out_path), full_page=True)
                    print(f"📸 미리보기 저장 완료: {out_path}")
                    passed += 1

                # [REWORK 3] 모든 앵커 이동과 이미지 로딩이 완료된 최종 시점에 오류 판정
                if console_errors:
                    print(f"❌ [실패] [{tc['name']}] 콘솔 에러 발생: {console_errors}")
                    failed += 1
                else:
                    passed += 1

                if asset_404s:
                    print(f"❌ [실패] [{tc['name']}] 자산 로드 404 오류: {asset_404s}")
                    failed += 1
                else:
                    passed += 1

                if external_requests:
                    print(f"❌ [실패] [{tc['name']}] 외부 자산(CDN 등) 요청 감지: {external_requests}")
                    failed += 1
                else:
                    passed += 1

                context.close()

            browser.close()

    finally:
        print(f"ℹ️ 로컬 HTTP 서버 종료 중 (PID {server_pid})...")
        server_proc.terminate()
        try:
            server_proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            server_proc.kill()
        print(f"ℹ️ 로컬 HTTP 서버 정상 종료 완료 (PID {server_pid})")

    print(f"=== 브라우저 검증 완료: 통과 {passed}, 실패 {failed} ===")
    return passed, failed


def main():
    orig_stdout = sys.stdout
    orig_stderr = sys.stderr
    tee_out = TeeLogger(VERIFY_LOG_FILE, orig_stdout)
    tee_err = TeeLogger(PWTMP_DIR / "verify-err.txt", orig_stderr)
    sys.stdout = tee_out
    sys.stderr = tee_err

    parser = argparse.ArgumentParser(description="1min.dev 사이트 검증 도구")
    parser.add_argument("--static", action="store_true", help="정적 파일, 앵커, 보호문서, 금지정보 검사 실행")
    parser.add_argument("--browser", action="store_true", help="브라우저 반응형 렌더링, 폰트, 가로스크롤, 캡처 검사 실행")
    parser.add_argument(
        "--preview-dir",
        default=r"C:\Users\user\Desktop\1min_사이트_미리보기",
        help="미리보기 캡처 저장 경로",
    )

    args = parser.parse_args()

    if not args.static and not args.browser:
        args.static = True
        args.browser = True

    total_passed = 0
    total_failed = 0

    try:
        if args.static:
            p, f = run_static_checks()
            total_passed += p
            total_failed += f

        if args.browser:
            p, f = run_browser_checks(args.preview_dir)
            total_passed += p
            total_failed += f

        print(f"\n==========================================")
        print(f"최종 검증 집계: 통과 {total_passed}건, 실패 {total_failed}건")
        print(f"==========================================")
    finally:
        sys.stdout = orig_stdout
        sys.stderr = orig_stderr
        tee_out.flush()
        tee_out.close()
        tee_err.flush()
        tee_err.close()

    if total_failed > 0:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
