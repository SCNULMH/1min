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
def _resolve_temp_dir() -> Path:
    candidates = [
        Path(r"C:\Users\user\build-tmp\pwtmp"),
        WORKSPACE_DIR / ".pwtmp",
        Path(os.environ.get("TEMP", ".")) / "pwtmp",
    ]
    for d in candidates:
        try:
            d.mkdir(parents=True, exist_ok=True)
            test_file = d / ".write_test"
            test_file.write_text("ok", encoding="utf-8")
            test_file.unlink(missing_ok=True)
            return d
        except Exception:
            continue
    return WORKSPACE_DIR

PWTMP_DIR = _resolve_temp_dir()
os.environ["TEMP"] = str(PWTMP_DIR)
os.environ["TMP"] = str(PWTMP_DIR)

# 실행 로그를 C:\Users\user\build-tmp\pwtmp\verify-log.txt 에 남기기 위한 티(Tee) 로거
VERIFY_LOG_FILE = PWTMP_DIR / "verify-log.txt"


class TeeLogger:
    def __init__(self, filename, stream):
        self.stream = stream
        self.file = open(filename, "w", encoding="utf-8")

    def write(self, message):
        self.stream.write(message)
        if self.file and not self.file.closed:
            self.file.write(message)
            self.file.flush()

    def flush(self):
        self.stream.flush()
        if self.file and not self.file.closed:
            self.file.flush()

    def close(self):
        if self.file and not self.file.closed:
            self.file.close()

# 보호 문서 기준 SHA-256 해시
PROTECTED_HASHES = {
    "newbie-helper/privacy.html": "1cee5da5b2160a818a063d5f4cdf18d657f69ffe4c42d2330fa4db4da3aece61",
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
    "hero",
    "featured-works",
    "other-projects",
    "experience",
    "company",
    "contact",
]

DRAFT_FORBIDDEN_TERMS = (
    "사용자 확인 필요",
    "검토안",
    "검토 중",
    "확정 전",
)

EXPECTED_CONTEST_SERVICE_ITEMS = (
    "이디그디 — 여행 이미지와 닮은 제주 관광지·코스를 제안하는 웹앱",
    "검진AI 리셋코치 — 검진 수치와 생활패턴을 바탕으로 위험도를 살피고 개선 행동을 제안하는 웹앱",
    "내일이음 — 경험을 직업·훈련·채용 기회와 다음 행동으로 잇는 AI 고용서비스 웹앱",
    "들마루 — 지원사업과 재배 일정, 병해충 정보를 연결하는 청년농 웹 서비스",
)

CONTEST_LIST_FORBIDDEN_TERMS = (
    "공모전",
    "경진대회",
    "해커톤",
    "대회",
    "2026",
    "제4회",
    "제11회",
    "제12회",
    "contest-year",
    "contest-name",
)

CONTEST_RESULT_FORBIDDEN_TERMS = (
    "수상",
    "입상",
    "대상",
    "최우수상",
    "우수상",
    "장려상",
    "입선",
    "탈락",
)

EXPECTED_EXPERIENCE_CONTEST_ENTRY = (
    "2026",
    "공공데이터·AI 활용 공모전 출품",
    "이디그디(관광데이터 활용 공모전), 내일이음(고용24 AI 고용서비스 해커톤), 들마루(농업·농촌 공공데이터+AI 활용 창업경진대회) 외 서비스 개발",
)

TURNSTILE_PUBLIC_SITEKEY = "0x4AAAAAAFsvfCbrajidkTlI"
TURNSTILE_SITEKEY_PATTERN = r"(?:TURNSTILE_SITE_KEY|0x[0-9A-Za-z_-]{10,})"
TURNSTILE_SCRIPT_URL = "https://challenges.cloudflare.com/turnstile/v0/api.js"
ALLOWED_EXTERNAL_ORIGIN = "https://challenges.cloudflare.com"


def is_allowed_external_request(url: str, base_url: str) -> bool:
    """Allow local test server, data: URIs, and HTTPS challenges.cloudflare.com requests only."""
    normalized_base = base_url.rstrip("/")
    if normalized_base and (url == normalized_base or url.startswith(normalized_base + "/")):
        return True
    if url.startswith("data:"):
        return True
    if url == ALLOWED_EXTERNAL_ORIGIN or url.startswith(ALLOWED_EXTERNAL_ORIGIN + "/"):
        return True
    return False


class SiteHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.nav_links = []
        self.local_links = []
        self.image_srcs = []
        self.anchors = []
        self.sections = []
        self.in_nav = False

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if "id" in attrs_dict:
            self.ids.append((tag, attrs_dict["id"]))
            if tag == "section":
                self.sections.append(attrs_dict["id"])

        if tag == "nav":
            self.in_nav = True

        if tag == "a" and "href" in attrs_dict:
            href = attrs_dict["href"]
            self.anchors.append((href, attrs_dict))
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


def validate_redesign_markup(html_content: str) -> list[str]:
    """Check the public-content contract independently of visual styling."""
    parser = SiteHTMLParser()
    parser.feed(html_content)
    errors = []
    if parser.sections != EXPECTED_SECTIONS:
        errors.append(f"섹션 순서: {parser.sections}")

    ids = [value for _, value in parser.ids]
    for required in ("work-zerolingual", "work-newbie", "work-idigdi", "work-naeil", "work-deulmaru", "en"):
        if required not in ids:
            errors.append(f"앵커 누락: {required}")

    expected_nav = ["featured-works", "company", "contact"]
    if parser.nav_links != expected_nav:
        errors.append(f"메뉴 앵커 순서 오류: {parser.nav_links}")
    for anchor in expected_nav:
        if anchor not in parser.nav_links or anchor not in ids:
            errors.append(f"메뉴 앵커 누락: {anchor}")

    featured = re.search(r'<section\b[^>]*\bid=["\']featured-works["\'][^>]*>(.*?)</section>', html_content, re.S | re.I)
    other = re.search(r'<section\b[^>]*\bid=["\']other-projects["\'][^>]*>(.*?)</section>', html_content, re.S | re.I)
    experience = re.search(r'<section\b[^>]*\bid=["\']experience["\'][^>]*>(.*?)</section>', html_content, re.S | re.I)
    company = re.search(r'<section\b[^>]*\bid=["\']company["\'][^>]*>(.*?)</section>', html_content, re.S | re.I)
    contact = re.search(r'<section\b[^>]*\bid=["\']contact["\'][^>]*>(.*?)</section>', html_content, re.S | re.I)
    footer = re.search(r'<footer\b[^>]*>(.*?)</footer>', html_content, re.S | re.I)

    featured_html = featured.group(1) if featured else ""
    other_html = other.group(1) if other else ""
    experience_html = experience.group(1) if experience else ""
    company_html = company.group(1) if company else ""
    contact_html = contact.group(1) if contact else ""
    footer_html = footer.group(1) if footer else ""

    if not (
        "work-zerolingual" in featured_html
        and "work-newbie" in featured_html
        and featured_html.index("work-zerolingual") < featured_html.index("work-newbie")
        and len(re.findall(r"<article\b", featured_html, re.I)) == 2
    ):
        errors.append("대표 작업 순서 또는 개수 오류")
    if "work-idigdi" in featured_html or "work-idigdi" not in other_html:
        errors.append("이디그디 섹션 위치")

    if re.search(r"\bcontest-heading\b", html_content, re.I):
        errors.append("공모전 도전 소제목(contest-heading) 잔존")
    if re.search(r"\bcontest-(?:year|name)\b", html_content, re.I):
        errors.append("서비스 목록 내 대회명 또는 연도 표기 금지 위반")

    all_contest_lists = re.findall(
        r'<ol\b[^>]*\bclass=["\'][^"\']*\bcontest-list\b[^"\']*["\'][^>]*>',
        html_content,
        re.I,
    )
    idigdi_in_other = re.search(
        r'<article\b[^>]*\bid=["\']work-idigdi["\'][^>]*>.*?</article>',
        other_html,
        re.S | re.I,
    )
    naeil_in_other = re.search(
        r'<article\b[^>]*\bid=["\']work-naeil["\'][^>]*>.*?</article>',
        other_html,
        re.S | re.I,
    )
    deulmaru_in_other = re.search(
        r'<article\b[^>]*\bid=["\']work-deulmaru["\'][^>]*>.*?</article>',
        other_html,
        re.S | re.I,
    )
    contest_list = re.search(
        r'(<ol\b[^>]*\bclass=["\'][^"\']*\bcontest-list\b[^"\']*["\'][^>]*>)(.*?)</ol>',
        other_html,
        re.S | re.I,
    )
    if (
        "work-idigdi" in featured_html
        or not idigdi_in_other
        or (naeil_in_other and idigdi_in_other.end() > naeil_in_other.start())
        or (contest_list and idigdi_in_other.end() > contest_list.start())
    ):
        errors.append("이디그디 블록 누락 또는 배치 오류")
    if (
        "work-naeil" in featured_html
        or not naeil_in_other
        or not idigdi_in_other
        or idigdi_in_other.end() > naeil_in_other.start()
        or (contest_list and naeil_in_other.end() > contest_list.start())
    ):
        errors.append("내일이음 블록 누락 또는 배치 오류")
    if (
        "work-deulmaru" in featured_html
        or not deulmaru_in_other
        or not naeil_in_other
        or naeil_in_other.end() > deulmaru_in_other.start()
        or (contest_list and deulmaru_in_other.end() > contest_list.start())
    ):
        errors.append("들마루 블록 누락 또는 배치 오류")
    if (
        not contest_list
        or len(all_contest_lists) != 1
        or not idigdi_in_other
        or idigdi_in_other.end() > contest_list.start()
    ):
        errors.append("그 밖의 개발 서비스 목록 누락 또는 배치 오류")
    else:
        ol_open_tag = contest_list.group(1)
        contest_list_inner = contest_list.group(2)
        contest_list_full = contest_list.group(0)

        aria_label_match = re.search(r'\baria-label=["\']([^"\']*)["\']', ol_open_tag, re.I)
        if (
            not aria_label_match
            or not aria_label_match.group(1).strip()
            or re.search(r'\baria-hidden=["\']true["\']', ol_open_tag, re.I)
        ):
            errors.append("그 밖의 개발 서비스 목록 aria-label 누락")

        if any(term in contest_list_full for term in CONTEST_LIST_FORBIDDEN_TERMS) or re.search(
            r"20\d{2}", contest_list_full
        ):
            errors.append("서비스 목록 내 대회명 또는 연도 표기 금지 위반")

        li_matches = re.findall(r"<li\b[^>]*>(.*?)</li>", contest_list_inner, re.S | re.I)
        li_texts = tuple(
            re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", item)).strip()
            for item in li_matches
        )
        if li_texts != EXPECTED_CONTEST_SERVICE_ITEMS:
            errors.append("그 밖의 개발 서비스 목록 문구 불일치")

        if any(word in contest_list_full for word in CONTEST_RESULT_FORBIDDEN_TERMS):
            errors.append("공모전 결과 표기 금지 위반")

    exp_articles = re.findall(r"<article\b[^>]*>(.*?)</article>", experience_html, re.S | re.I)
    exp_period, exp_title, exp_desc = EXPECTED_EXPERIENCE_CONTEST_ENTRY
    matching_contest_articles = []
    contest_keyword_articles = []
    for article_inner in exp_articles:
        if any(k in article_inner for k in ("공모전", "경진대회", "해커톤", "출품")):
            contest_keyword_articles.append(article_inner)
        period_m = re.search(
            r'<span\b[^>]*\bclass=["\'][^"\']*\bperiod\b[^"\']*["\'][^>]*>(.*?)</span>',
            article_inner,
            re.S | re.I,
        )
        title_m = re.search(r"<h3\b[^>]*>(.*?)</h3>", article_inner, re.S | re.I)
        desc_matches = re.findall(r"<p\b[^>]*>(.*?)</p>", article_inner, re.S | re.I)
        if (
            period_m
            and title_m
            and len(desc_matches) == 1
            and "<br" not in desc_matches[0].lower()
            and re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", period_m.group(1))).strip() == exp_period
            and re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", title_m.group(1))).strip() == exp_title
            and re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", desc_matches[0])).strip() == exp_desc
        ):
            matching_contest_articles.append(article_inner)

    if len(matching_contest_articles) != 1 or len(contest_keyword_articles) != 1:
        errors.append("경력 섹션 공모전 출품 한 줄 누락 또는 형식 오류")

    if any(word in experience_html for word in CONTEST_RESULT_FORBIDDEN_TERMS):
        errors.append("공모전 결과 표기 금지 위반")

    if "skills" in parser.sections or re.search(r'href=["\']#skills["\']', html_content):
        errors.append("기술 섹션/메뉴 잔존")
    if "클덱스" in html_content or "Cldex" in html_content:
        errors.append("클덱스 잔존")

    hero = re.search(r'<section\b[^>]*\bid=["\']hero["\'][^>]*>(.*?)</section>', html_content, re.S | re.I)
    hero_html = hero.group(1) if hero else ""
    hero_text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", hero_html)).strip()
    for phrase in (
        "작은 불편을",
        "쓰이는 제품으로.",
        "일민형은 일상의 문제를 웹과 앱으로 풀어내는 1인 소프트웨어 회사입니다. 이민형이 직접 만들고 다듬습니다.",
    ):
        if phrase not in hero_text:
            errors.append(f"히어로 문구 누락: {phrase}")
    for label, href in (("대표 작업 보기", "#featured-works"), ("문의하기", "#contact")):
        if not re.search(r'<a\b(?=[^>]*\bhref=["\']' + re.escape(href) + r'["\'])[^>]*>\s*' + label + r'\s*</a>', hero_html, re.S):
            errors.append(f"히어로 CTA 누락: {label}")
    if not (
        re.search(r'href=["\']#work-zerolingual["\']', hero_html)
        and re.search(r'href=["\']#work-newbie["\']', hero_html)
        and hero_html.index("#work-zerolingual") < hero_html.index("#work-newbie")
        and "0개국어" in hero_html
        and "신입 이사원" in hero_html
        and "출시 준비 중" in hero_html
        and "work-idigdi" not in hero_html
        and "work-naeil" not in hero_html
    ):
        errors.append("히어로 우측 미리보기 구성 오류")

    company_text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", company_html)).strip()
    for phrase in (
        "업무의 불편을 쓰이는 웹과 앱으로 만드는 개발자, 이민형.",
        "최적화된 서비스를 만들어내는 개발자",
        "경험을 통해 성장해 나가는 개발자",
        "사람들의 불편함 속에서 필요로 하는 것을 고민하는 개발자",
    ):
        if phrase not in company_text:
            errors.append(f"회사 소개 문구 누락: {phrase}")
    for term, desc in COMPANY_INFO_ITEMS:
        if not re.search(r"<dt>\s*" + re.escape(term) + r"\s*</dt>\s*<dd>\s*" + re.escape(desc) + r"\s*</dd>", company_html):
            errors.append(f"사업자 정보 누락: {term}")

    hrefs = {href for href, _ in parser.anchors}
    for href in (
        "https://play.google.com/store/apps/details?id=com.scnulmh.zerolingual",
        "intoss://zerolanguage",
        "https://app.notion.com/p/Newbie-Helper-401266b5e461803ebdeee369e3ef90eb",
        "https://bw-jeju.1min.dev",
        "https://bw-tomorrow.1min.dev",
        "mailto:2min@1min.dev",
        "#en",
        "privacy.html",
    ):
        if href not in hrefs:
            errors.append(f"필수 링크 누락: {href}")
    if "출시 준비 중" not in featured_html:
        errors.append("신입 이사원 상태 누락")

    idigdi_html = idigdi_in_other.group(0) if idigdi_in_other else ""
    idigdi_text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", idigdi_html)).strip()
    if not (
        re.search(r'<h3\b[^>]*\bid=["\']idigdi-title["\'][^>]*>\s*이디그디\s*</h3>', idigdi_html)
        and "사진과 닮은 제주 명소를 추천하고 일정과 지도를 연결하는 웹 서비스. 공개 서비스로 운영하고 있습니다." in idigdi_text
        and "2026 관광데이터 활용 공모전 기능설명서에 이디그디로 기록했습니다." in idigdi_text
    ):
        errors.append("이디그디 제목 또는 설명 누락")
    idigdi_links = re.findall(r"<a\b[^>]*>.*?</a>", idigdi_html, re.S | re.I)
    idigdi_link = re.search(
        r'<a\b(?=[^>]*\bhref=["\']https://bw-jeju\.1min\.dev["\'])(?=[^>]*\btarget=["\']_blank["\'])([^>]*)>\s*서비스 방문하기\s*</a>',
        idigdi_html,
        re.I,
    )
    idigdi_rel = re.search(r'\brel=["\']([^"\']*)["\']', idigdi_link.group(1), re.I) if idigdi_link else None
    if len(idigdi_links) != 1 or not idigdi_link or not idigdi_rel or not {"noopener", "noreferrer"}.issubset(set(idigdi_rel.group(1).lower().split())):
        errors.append("이디그디 서비스 링크 또는 새 탭 보안 속성 누락")

    idigdi_galleries = re.findall(
        r'<div\b[^>]*\bclass=["\'][^"\']*\bgallery\b[^"\']*["\'][^>]*>(.*?)</div>',
        idigdi_html,
        re.S | re.I,
    )
    expected_idigdi = (
        ("main", "이디그디 첫 화면", 1200, 750, "첫 화면"),
        ("results", "이디그디 CLIP 분석 결과·닮은 여행지 화면", 1200, 750, "CLIP 분석 결과·닮은 여행지"),
        ("route", "이디그디 맞춤 여행 코스 화면", 1200, 750, "맞춤 여행 코스"),
        ("mobile", "이디그디 모바일 첫 화면", 555, 1200, "모바일 첫 화면"),
    )
    idigdi_figures = re.findall(r"<figure\b[^>]*>(.*?)</figure>", idigdi_galleries[0], re.S | re.I) if len(idigdi_galleries) == 1 else []
    if len(idigdi_galleries) != 1 or len(idigdi_figures) != 4 or len(re.findall(r"<img\b", idigdi_html, re.I)) != 4:
        errors.append("이디그디 갤러리 4장 구조 오류")
    else:
        for figure, (name, alt, width, height, caption) in zip(idigdi_figures, expected_idigdi):
            match = re.fullmatch(
                r'\s*<button\b(?=[^>]*\bclass=["\'][^"\']*\bgallery-item\b[^"\']*["\'])(?=[^>]*\btype=["\']button["\'])(?=[^>]*\baria-label=["\']' + re.escape(alt + " 크게 보기") + r'["\'])[^>]*>\s*(<img\b[^>]*>)\s*</button>\s*<figcaption>\s*' + re.escape(caption) + r'\s*</figcaption>\s*',
                figure,
                re.S | re.I,
            )
            img = match.group(1) if match else ""
            attrs = (
                (r'\bsrc=["\']assets/idigdi-' + name + r'\.webp["\']', img),
                (r'\balt=["\']' + re.escape(alt) + r'["\']', img),
                (rf'\bwidth=["\']{width}["\']', img),
                (rf'\bheight=["\']{height}["\']', img),
                (r'\bloading=["\']lazy["\']', img),
            )
            if not match or not all(re.search(pattern, value, re.I) for pattern, value in attrs):
                errors.append(f"이디그디 갤러리 이미지 속성 또는 구조 오류: {name}")

    naeil_article = re.search(r'<article\b[^>]*\bid=["\']work-naeil["\'][^>]*>(.*?)</article>', html_content, re.S | re.I)
    naeil_html = naeil_article.group(1) if naeil_article else ""
    naeil_text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", naeil_html)).strip()
    if not (
        re.search(r"<h3\b[^>]*>\s*내일이음\s*</h3>", naeil_html)
        and "경험을 직업·훈련·채용 기회와 다음 행동으로 잇는 AI 고용서비스 웹앱" in naeil_text
    ):
        errors.append("내일이음 제목 또는 설명 누락")
    naeil_link = re.search(
        r'<a\b(?=[^>]*\bhref=["\']https://bw-tomorrow\.1min\.dev["\'])(?=[^>]*\btarget=["\']_blank["\'])([^>]*)>\s*서비스 방문하기\s*</a>',
        naeil_html,
        re.I,
    )
    naeil_rel = re.search(r'\brel=["\']([^"\']*)["\']', naeil_link.group(1), re.I) if naeil_link else None
    naeil_rel_tokens = set(naeil_rel.group(1).lower().split()) if naeil_rel else set()
    if not naeil_link or not {"noopener", "noreferrer"}.issubset(naeil_rel_tokens):
        errors.append("내일이음 서비스 링크 또는 새 탭 보안 속성 누락")
    naeil_imgs = re.findall(r"<img\b[^>]*>", naeil_html, re.I)
    if len(naeil_imgs) == 0:
        errors.append("내일이음 캡처 누락")
    elif len(naeil_imgs) > 1:
        errors.append("내일이음 캡처 1장 초과")
    else:
        naeil_img = naeil_imgs[0]
        if not (
            re.search(r'\bsrc=["\']assets/naeil-home\.webp["\']', naeil_img)
            and re.search(r'\balt=["\']내일이음 첫 화면["\']', naeil_img)
            and re.search(r'\bwidth=["\']1280["\']', naeil_img)
            and re.search(r'\bheight=["\']800["\']', naeil_img)
            and re.search(r'\bloading=["\']lazy["\']', naeil_img)
        ):
            errors.append("내일이음 캡처 속성(src·alt·width·height·loading) 오류")

    deulmaru_html = deulmaru_in_other.group(0) if deulmaru_in_other else ""
    deulmaru_text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", deulmaru_html)).strip()
    if not (
        re.search(r'<h3\b[^>]*\bid=["\']deulmaru-title["\'][^>]*>\s*들마루\s*</h3>', deulmaru_html)
        and "청년 귀농인의 정착을 돕는 농업 정보 플랫폼. 지원사업 정보, 병해충 사전·상담, 사진으로 병해충을 판별하는 AI 기능을 한곳에 모았습니다." in deulmaru_text
        and "서버는 지금 내려 두었고, 화면 기록과 코드를 공개합니다." in deulmaru_text
    ):
        errors.append("들마루 제목 또는 설명 누락")
    deulmaru_links = re.findall(r"<a\b[^>]*>.*?</a>", deulmaru_html, re.S | re.I)
    github_link = re.search(
        r'<a\b(?=[^>]*\bhref=["\']https://github\.com/SCNULMH/farmer-deulmaru["\'])(?=[^>]*\btarget=["\']_blank["\'])([^>]*)>\s*GitHub 저장소\s*</a>',
        deulmaru_html,
        re.I,
    )
    github_rel = re.search(r'\brel=["\']([^"\']*)["\']', github_link.group(1), re.I) if github_link else None
    if len(deulmaru_links) != 1 or not github_link or not github_rel or not {"noopener", "noreferrer"}.issubset(set(github_rel.group(1).lower().split())):
        errors.append("들마루 GitHub 링크 또는 새 탭 보안 속성 오류")

    deulmaru_galleries = re.findall(
        r'<div\b[^>]*\bclass=["\'][^"\']*\bgallery\b[^"\']*["\'][^>]*>(.*?)</div>',
        deulmaru_html,
        re.S | re.I,
    )
    expected_deulmaru = (
        ("main", "첫", 1280, 786, "첫 화면"),
        ("support", "지원사업 정보", 1024, 617, "지원사업 정보"),
        ("pest", "병해충 사전", 1024, 626, "병해충 사전"),
        ("consulting", "병해충 상담", 1024, 614, "병해충 상담"),
        ("ai", "AI 병해충 판별", 1024, 675, "AI 병해충 판별"),
    )
    figures = re.findall(r"<figure\b[^>]*>(.*?)</figure>", deulmaru_galleries[0], re.S | re.I) if len(deulmaru_galleries) == 1 else []
    if len(deulmaru_galleries) != 1 or len(figures) != 5 or len(re.findall(r"<img\b", deulmaru_html, re.I)) != 5:
        errors.append("들마루 갤러리 5장 구조 오류")
    else:
        for figure, (name, label, width, height, caption) in zip(figures, expected_deulmaru):
            alt = "들마루 첫 화면" if name == "main" else f"들마루 {label} 화면"
            match = re.fullmatch(
                r'\s*<button\b(?=[^>]*\bclass=["\'][^"\']*\bgallery-item\b[^"\']*["\'])(?=[^>]*\btype=["\']button["\'])(?=[^>]*\baria-label=["\']' + re.escape(alt + " 크게 보기") + r'["\'])[^>]*>\s*(<img\b[^>]*>)\s*</button>\s*<figcaption>\s*' + re.escape(caption) + r'\s*</figcaption>\s*',
                figure,
                re.S | re.I,
            )
            img = match.group(1) if match else ""
            attrs = (
                (r'\bsrc=["\']assets/deulmaru-' + name + r'\.webp["\']', img),
                (r'\balt=["\']' + re.escape(alt) + r'["\']', img),
                (rf'\bwidth=["\']{width}["\']', img),
                (rf'\bheight=["\']{height}["\']', img),
                (r'\bloading=["\']lazy["\']', img),
            )
            if not match or not all(re.search(pattern, value, re.I) for pattern, value in attrs):
                errors.append(f"들마루 갤러리 이미지 속성 또는 구조 오류: {name}")

    galleries = re.findall(
        r'<div\b[^>]*\bclass=["\'][^"\']*\bgallery\b[^"\']*["\'][^>]*>(.*?)</div>',
        html_content,
        re.S | re.I,
    )
    total_gallery_imgs = sum(len(re.findall(r"<img\b", g, re.I)) for g in galleries)
    wrapped_gallery_imgs = sum(
        len(
            re.findall(
                r'<button\b(?=[^>]*\btype=["\']button["\'])(?=[^>]*\baria-label=["\'][^"\']*크게 보기["\'])[^>]*>\s*<img\b[^>]*>\s*</button>',
                g,
                re.S | re.I,
            )
        )
        for g in galleries
    )
    work_capture_imgs = [
        tag
        for tag in re.findall(r"<img\b[^>]*>", featured_html + other_html, re.I)
        if not re.search(r'\bclass=["\'][^"\']*\bwork-icon\b', tag, re.I)
    ]
    if (
        not galleries
        or total_gallery_imgs == 0
        or wrapped_gallery_imgs != total_gallery_imgs
        or len(work_capture_imgs) != total_gallery_imgs
    ):
        errors.append("갤러리 이미지 키보드 열기 버튼(type=button, aria-label) 누락")

    lightbox_match = re.search(
        r'<dialog\b[^>]*\bid=["\']lightbox["\'][^>]*>(.*?)</dialog>',
        html_content,
        re.S | re.I,
    )
    lightbox_inner = lightbox_match.group(1) if lightbox_match else ""
    if not (
        lightbox_match
        and re.search(r'<button\b(?=[^>]*\bid=["\']lightbox-close["\'])(?=[^>]*\btype=["\']button["\'])[^>]*>', lightbox_inner, re.I)
        and re.search(r'<button\b(?=[^>]*\bid=["\']lightbox-prev["\'])(?=[^>]*\btype=["\']button["\'])[^>]*>', lightbox_inner, re.I)
        and re.search(r'<button\b(?=[^>]*\bid=["\']lightbox-next["\'])(?=[^>]*\btype=["\']button["\'])[^>]*>', lightbox_inner, re.I)
        and re.search(r'<img\b[^>]*\bid=["\']lightbox-image["\'][^>]*>', lightbox_inner, re.I)
        and re.search(r'\bid=["\']lightbox-count["\']', lightbox_inner, re.I)
        and re.search(r'\bid=["\']lightbox-caption["\']', lightbox_inner, re.I)
    ):
        errors.append("라이트박스 dialog 또는 내부 제어 요소 누락")

    if "AWS EC2" in html_content or "HTTPS" in html_content:
        errors.append("운영 세부 표현 잔존")

    # 문의 섹션·양식·허니팟·수집 안내·처리방침 링크 검사
    if not re.search(r'<button\b[^>]*id=["\']copy-email["\']', contact_html) or not re.search(
        r'<[^>]*id=["\']copy-status["\'](?=[^>]*role=["\']status["\'])[^>]*aria-live=["\']polite["\']|<[^>]*id=["\']copy-status["\'](?=[^>]*aria-live=["\']polite["\'])[^>]*role=["\']status["\']',
        contact_html,
    ):
        errors.append("주소 복사/알림 누락")

    if not re.search(r'<a\b[^>]*\bhref=["\']privacy\.html["\']', contact_html):
        errors.append("문의 섹션 privacy.html 링크 누락")
    if not re.search(r'<a\b[^>]*\bhref=["\']privacy\.html["\']', footer_html):
        errors.append("바닥글 privacy.html 링크 누락")

    note_match = re.search(r'<div\b[^>]*\bclass=["\'][^"\']*\bcollection-note\b[^"\']*["\'][^>]*>(.*?)</div>', contact_html, re.S | re.I)
    form_match = re.search(r'<form\b[^>]*\bid=["\']contact-form["\'][^>]*>(.*?)</form>', contact_html, re.S | re.I)
    if not note_match or not form_match or note_match.start() > form_match.start():
        errors.append("수집 안내 누락 또는 양식 위 배치 위반")
    else:
        note_html = note_match.group(1)
        if not all(
            token in note_html
            for token in (
                "이메일 주소",
                "문의 내용",
                "답장",
                "답변 완료 후 1년",
                "지체 없이 삭제",
                "국외 이전",
                "Cloudflare",
                'href="privacy.html"',
            )
        ):
            errors.append("수집 안내 필수 항목(항목·목적·보유 1년·국외 이전·처리방침 링크) 누락")

    fallback_match = re.search(r'<div\b[^>]*\bid=["\']contact-fallback["\'][^>]*>(.*?)</div>\s*<form\b', contact_html, re.S | re.I)
    if not fallback_match:
        fallback_match = re.search(r'<div\b[^>]*\bid=["\']contact-fallback["\'][^>]*>(.*?)</div>', contact_html, re.S | re.I)
    if not fallback_match or 'href="mailto:2min@1min.dev"' not in contact_html:
        errors.append("자리표시 키 대체 안내 영역 누락")
    else:
        fallback_inner = fallback_match.group(1)
        if (
            "mailto:2min@1min.dev" in fallback_inner
            or re.search(r"<button\b", fallback_inner, re.I)
            or "fallback-copy" in html_content
        ):
            errors.append("자리표시 키 대체 안내 이메일·복사 버튼 중복 노출")

    form_html = form_match.group(1) if form_match else ""
    if not (
        re.search(r'<label\b[^>]*\bfor=["\']contact-email["\'][^>]*>', form_html)
        and re.search(
            r'<input\b(?=[^>]*\bid=["\']contact-email["\'])(?=[^>]*\bname=["\']email["\'])(?=[^>]*\btype=["\']email["\'])(?=[^>]*\brequired\b)[^>]*>',
            form_html,
        )
    ):
        errors.append("양식 이메일 라벨 연결 또는 필수 속성 누락")

    if not (
        re.search(r'<label\b[^>]*\bfor=["\']contact-message["\'][^>]*>', form_html)
        and re.search(
            r'<textarea\b(?=[^>]*\bid=["\']contact-message["\'])(?=[^>]*\bname=["\']message["\'])(?=[^>]*\bmaxlength=["\']4000["\'])(?=[^>]*\brequired\b)[^>]*>',
            form_html,
        )
        and re.search(r'id=["\']character-count["\'][^>]*>\s*0\s*/\s*4000자\s*</', form_html)
    ):
        errors.append("양식 내용 라벨·4000자 제한·글자 수 표시 누락")

    honeypot_box = re.search(
        r'<div\b(?=[^>]*\bclass=["\'][^"\']*\bhoneypot\b[^"\']*["\'])(?=[^>]*\baria-hidden=["\']true["\'])(?=[^>]*\bhidden\b)[^>]*>(.*?)</div>',
        form_html,
        re.S | re.I,
    )
    if (
        not honeypot_box
        or not re.search(r'<label\b[^>]*\bfor=["\']contact-website["\']', honeypot_box.group(1))
        or not re.search(
            r'<input\b(?=[^>]*\bid=["\']contact-website["\'])(?=[^>]*\bname=["\']website["\'])(?=[^>]*\btabindex=["\']-1["\'])(?=[^>]*\bautocomplete=["\']off["\'])[^>]*>',
            honeypot_box.group(1),
        )
        or not re.search(r"\.honeypot\s*\{[^}]*display\s*:\s*none\s*!important", html_content)
    ):
        errors.append("허니팟 숨김 또는 속성(aria-hidden·hidden·tabindex·autocomplete) 누락")

    if not re.search(r'<input\b(?=[^>]*\bname=["\']startedAt["\'])(?=[^>]*\btype=["\']hidden["\'])[^>]*>', form_html):
        errors.append("startedAt 필드 누락")

    if not re.search(
        rf'<div\b(?=[^>]*\bclass=["\'][^"\']*\bcf-turnstile\b[^"\']*["\'])(?=[^>]*\bdata-sitekey=["\']{TURNSTILE_SITEKEY_PATTERN}["\'])[^>]*>',
        form_html,
    ):
        errors.append("Turnstile 위젯 또는 유효한 data-sitekey 누락")

    if (
        "https://challenges.cloudflare.com/turnstile/v0/api.js" not in html_content
        or "async" not in html_content
        or "defer" not in html_content
        or "https://contact.1min.dev/api/contact" not in html_content
    ):
        errors.append("Turnstile 스크립트(async/defer) 또는 Worker 요청 주소 누락")

    consent_label_match = re.search(r'<label\b[^>]*\bfor=["\']contact-consent["\'][^>]*>(.*?)</label>', form_html, re.S | re.I)
    consent_label_text = (
        re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", consent_label_match.group(1))).strip()
        if consent_label_match
        else ""
    )
    if not (
        consent_label_match
        and all(token in consent_label_text for token in ("개인정보 수집·이용", "국외 이전", "Cloudflare"))
        and re.search(
            r'<input\b(?=[^>]*\bid=["\']contact-consent["\'])(?=[^>]*\btype=["\']checkbox["\'])(?=[^>]*\brequired\b)[^>]*>',
            form_html,
        )
    ):
        errors.append("필수 동의 체크박스·국외 이전(Cloudflare) 문구 또는 라벨 연결 누락")

    if not re.search(r'<[^>]*\bid=["\']form-status["\'][^>]*\baria-live=["\']polite["\']', form_html) or not re.search(
        r'<[^>]*\bid=["\']form-fallback["\'][^>]*>.*?mailto:2min@1min\.dev',
        form_html,
        re.S,
    ):
        errors.append("양식 aria-live 상태 안내 또는 실패 시 메일 대체 안내 누락")

    if "innerHTML" in html_content:
        errors.append("innerHTML 사용 금지 위반")

    if not re.search(r"@media\s*\(prefers-reduced-motion:\s*reduce\)", html_content):
        errors.append("모션 감소 CSS 누락")
    for term in (
        "Polishing",
        "발전실적",
        "연료관리",
        "일일집계",
        "작업허가서",
        "실결재자",
        "MOOC",
        "롤백 스크립트",
        "테스트 포트",
        "발전소",
        "고객사",
        *DRAFT_FORBIDDEN_TERMS,
    ):
        if term in html_content:
            errors.append(f"금지 문구: {term}")
    return errors


def validate_privacy_markup(privacy_html: str) -> list[str]:
    """Check privacy.html finalized retention, overseas transfer, official Cloudflare links, and absence of draft markers."""
    errors = []
    for token in (
        "홈페이지 개인정보처리방침",
        "2026-10-30",
        "일민형 (1min)",
        "2min@1min.dev",
        "답변 완료 후 1년",
        "지체 없이",
        "삭제",
        "Cloudflare, Inc.(미국)",
        "미국 등 Cloudflare 데이터센터 소재국",
        "이메일 주소, 문의 내용, 접속 IP, 보안 확인 토큰",
        "양식 제출 때 네트워크로 전송",
        "봇 확인(Turnstile)과 메일 전달(Workers·Email)",
        "전달 처리 후 Cloudflare 정책에 따름",
        "동의하지 않으면 양식 대신 이메일로 직접 문의할 수 있음",
        "https://www.cloudflare.com/privacypolicy/",
        "https://developers.cloudflare.com/turnstile/",
        "https://www.cloudflare.com/cloudflare-customer-dpa/",
        'href="index.html"',
    ):
        if token not in privacy_html:
            errors.append(f"필수 문구/링크 누락: {token}")
    for term in DRAFT_FORBIDDEN_TERMS:
        if term in privacy_html:
            errors.append(f"초안 문구 잔존: {term}")
    if re.search(r"https?://(?:fonts\.googleapis|fonts\.gstatic|cdn\.jsdelivr|unpkg\.com)", privacy_html, re.I):
        errors.append("외부 CDN 글꼴 참조 발견")
    privacy_parser = SiteHTMLParser()
    privacy_parser.feed(privacy_html)
    for href, _ in privacy_parser.anchors:
        if href.startswith(("http://", "https://")) and not href.startswith(
            ("https://www.cloudflare.com/", "https://developers.cloudflare.com/")
        ):
            errors.append(f"비공식 외부 링크 발견: {href}")
    return errors


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

    redesign_errors = validate_redesign_markup(html_content)
    if redesign_errors:
        print(f"❌ [실패] 랜딩 구성/필수 콘텐츠: {redesign_errors}")
        failed += 1
    else:
        print("✅ [통과] 히어로·대표 작업·필수 링크·캡처·금지 문구 확인")
        passed += 1

    # Turnstile 실제 공개 사이트 키 적용 확인
    if re.search(
        r'<div\b(?=[^>]*\bclass=["\'][^"\']*\bcf-turnstile\b[^"\']*["\'])(?=[^>]*\bdata-sitekey=["\']'
        + re.escape(TURNSTILE_PUBLIC_SITEKEY)
        + r'["\'])[^>]*>',
        html_content,
    ):
        print(f"✅ [통과] Turnstile 공개 사이트 키({TURNSTILE_PUBLIC_SITEKEY}) 적용 확인")
        passed += 1
    else:
        print(f"❌ [실패] index.html에 Turnstile 공개 사이트 키({TURNSTILE_PUBLIC_SITEKEY})가 적용되지 않음")
        failed += 1

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

    # 최상위 섹션 순서 확인
    if parser.sections == EXPECTED_SECTIONS:
        print(f"✅ [통과] {len(EXPECTED_SECTIONS)}개 섹션 순서 일치: {EXPECTED_SECTIONS}")
        passed += 1
    else:
        print(f"❌ [실패] 섹션 순서 불일치: 기대={EXPECTED_SECTIONS}, 실제={parser.sections}")
        failed += 1

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
    for kw in ["발전실적", "연료관리", "일일집계", "작업허가서", "실결재자", "MOOC"]:
        if kw in html_content:
            forbidden_issues.append(f"고객사 내부 업무 세부 키워드({kw}) 발견")
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
    for css_file in (WORKSPACE_DIR / "assets").glob("*.css"):
        if css_file.name in html_content or f"assets/{css_file.name}" in html_content:
            for u in re.findall(r"url\(['\"]?([^'\")]+)['\"]?\)", css_file.read_text(encoding="utf-8")):
                referenced_files.add(str((css_file.parent / u).relative_to(WORKSPACE_DIR)).replace("\\", "/"))

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
    target_shots = [
        "assets/newbie-home.webp",
        "assets/newbie-life.webp",
        "assets/idigdi-main.webp",
        "assets/idigdi-results.webp",
        "assets/idigdi-route.webp",
        "assets/idigdi-mobile.webp",
    ]
    shot_errors = []
    for shot_rel in target_shots:
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

    idigdi_shot_errors = []
    for name, width, height in (
        ("main", 1200, 750),
        ("results", 1200, 750),
        ("route", 1200, 750),
        ("mobile", 555, 1200),
    ):
        shot_rel = f"assets/idigdi-{name}.webp"
        shot = WORKSPACE_DIR / shot_rel
        if not shot.is_file():
            idigdi_shot_errors.append(f"{shot_rel} 파일 누락")
            continue
        size_bytes = os.path.getsize(shot)
        if size_bytes > 300000:
            idigdi_shot_errors.append(f"{shot_rel} 크기 초과 ({size_bytes} > 300,000 bytes)")
        try:
            with Image.open(shot) as img:
                if img.format != "WEBP":
                    idigdi_shot_errors.append(f"{shot_rel} 포맷 오류 ({img.format})")
                if img.size != (width, height):
                    idigdi_shot_errors.append(f"{shot_rel} 해상도 불일치 ({img.size} != ({width}, {height}))")
        except Exception as e:
            idigdi_shot_errors.append(f"{shot_rel} 이미지 로드 실패: {e}")
    if idigdi_shot_errors:
        print(f"❌ [실패] 이디그디 캡처 규격 위반: {idigdi_shot_errors}")
        failed += 1
    else:
        print("✅ [통과] 이디그디 WebP 4장 규격 만족 (지정 해상도, 크기 <= 300KB)")
        passed += 1

    naeil_shot = WORKSPACE_DIR / "assets/naeil-home.webp"
    naeil_shot_errors = []
    if not naeil_shot.is_file():
        naeil_shot_errors.append("assets/naeil-home.webp 파일 누락")
    else:
        naeil_bytes = os.path.getsize(naeil_shot)
        if naeil_bytes > 300000:
            naeil_shot_errors.append(f"assets/naeil-home.webp 크기 초과 ({naeil_bytes} > 300,000 bytes)")
        try:
            with Image.open(naeil_shot) as img:
                if img.format != "WEBP":
                    naeil_shot_errors.append(f"assets/naeil-home.webp 포맷 오류 ({img.format})")
                if img.size != (1280, 800):
                    naeil_shot_errors.append(f"assets/naeil-home.webp 해상도 불일치 ({img.size} != (1280, 800))")
        except Exception as e:
            naeil_shot_errors.append(f"assets/naeil-home.webp 이미지 로드 실패: {e}")

    if naeil_shot_errors:
        print(f"❌ [실패] 내일이음 캡처 규격 위반: {naeil_shot_errors}")
        failed += 1
    else:
        print("✅ [통과] 내일이음 WebP 캡처 규격 만족 (1280×800, 크기 <= 300KB)")
        passed += 1

    deulmaru_shot_errors = []
    for name, width, height in (
        ("main", 1280, 786),
        ("support", 1024, 617),
        ("pest", 1024, 626),
        ("consulting", 1024, 614),
        ("ai", 1024, 675),
    ):
        shot_rel = f"assets/deulmaru-{name}.webp"
        shot = WORKSPACE_DIR / shot_rel
        if not shot.is_file():
            deulmaru_shot_errors.append(f"{shot_rel} 파일 누락")
            continue
        size_bytes = os.path.getsize(shot)
        if size_bytes > 300000:
            deulmaru_shot_errors.append(f"{shot_rel} 크기 초과 ({size_bytes} > 300,000 bytes)")
        try:
            with Image.open(shot) as img:
                if img.format != "WEBP":
                    deulmaru_shot_errors.append(f"{shot_rel} 포맷 오류 ({img.format})")
                if img.size != (width, height):
                    deulmaru_shot_errors.append(f"{shot_rel} 해상도 불일치 ({img.size} != ({width}, {height}))")
        except Exception as e:
            deulmaru_shot_errors.append(f"{shot_rel} 이미지 로드 실패: {e}")
    if deulmaru_shot_errors:
        print(f"❌ [실패] 들마루 캡처 규격 위반: {deulmaru_shot_errors}")
        failed += 1
    else:
        print("✅ [통과] 들마루 WebP 5장 규격 만족 (지정 해상도, 크기 <= 300KB)")
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
    if "intoss://zerolanguage" in html_content and "Google Play" in html_content and "앱인토스" in html_content:
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
    if "(주)아이티맨" not in html_content or not re.search(r"2025\.06\.16\s*[~∼]\s*(현재|재직 중)", html_content):
        career_errors.append("(주)아이티맨 재직 기간 누락")
    if "(주)아이티맨 — " in html_content:
        career_errors.append("아이티맨 직급 표기 발견(비워 두어야 함)")
    if "(주)에이스퀘어" not in html_content or "현장실습생" not in html_content or not re.search(r"2023\.12\s*[~∼]\s*2024\.01", html_content):
        career_errors.append("(주)에이스퀘어 현장실습생(2023.12 ~ 2024.01) 누락")
    if "스마트인재개발원" not in html_content or "DCX 개발자 과정" not in html_content or not re.search(r"2024\.10\.07\s*[~∼]\s*2025\.04\.04", html_content):
        career_errors.append("스마트인재개발원 교육 과정(2024.10.07 ~ 2025.04.04) 누락")

    if career_errors:
        print(f"❌ [실패] 확정 경력/교육 요건 불일치: {career_errors}")
        failed += 1
    else:
        print("✅ [통과] 확정 경력((주)아이티맨, (주)에이스퀘어) 및 교육(스마트인재개발원) 분리 반영 확인")
        passed += 1

    # 15. 루트 홈페이지 개인정보처리방침(privacy.html) 존재 및 필수 항목 검사
    privacy_path = WORKSPACE_DIR / "privacy.html"
    if not privacy_path.is_file():
        print("❌ [실패] 루트 privacy.html 파일이 존재하지 않습니다.")
        failed += 1
    else:
        privacy_html = privacy_path.read_text(encoding="utf-8")
        privacy_errors = validate_privacy_markup(privacy_html)
        if privacy_errors:
            print(f"❌ [실패] 루트 privacy.html 요건 불일치: {privacy_errors}")
            failed += 1
        else:
            print("✅ [통과] 루트 privacy.html 존재 및 시행일·보유 1년·국외 이전·Cloudflare 공식 문서 링크 확인")
            passed += 1

    # 16. 공개 파일(index.html, privacy.html) 초안 문구 미포함 검사
    draft_hits = []
    for pub_rel in ("index.html", "privacy.html"):
        pub_path = WORKSPACE_DIR / pub_rel
        if pub_path.is_file():
            pub_text = pub_path.read_text(encoding="utf-8")
            for term in DRAFT_FORBIDDEN_TERMS:
                if term in pub_text:
                    draft_hits.append(f"{pub_rel}: {term}")
    if draft_hits:
        print(f"❌ [실패] 공개 파일 내 초안 문구 잔존: {draft_hits}")
        failed += 1
    else:
        print("✅ [통과] 공개 파일(index.html, privacy.html) 초안 문구 미포함 확인")
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
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, sync_playwright

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
                turnstile_requests = []

                def handle_turnstile_route(route):
                    turnstile_requests.append(route.request.url)
                    route.fulfill(
                        status=200,
                        content_type="application/javascript; charset=utf-8",
                        body="",
                    )

                page.route("https://challenges.cloudflare.com/**", handle_turnstile_route)

                page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
                page.on("response", lambda res: asset_404s.append(res.url) if res.status >= 400 else None)
                page.on(
                    "request",
                    lambda req: external_requests.append(req.url)
                    if not is_allowed_external_request(req.url, base_url)
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

                post_load_overflow = page.evaluate("""(() => {
                    const docW = document.documentElement.scrollWidth;
                    const cliW = document.documentElement.clientWidth;
                    const idigdi = document.getElementById('work-idigdi');
                    const r = idigdi ? idigdi.getBoundingClientRect() : null;
                    return {
                        docW,
                        cliW,
                        idigdiLeft: r ? r.left : 0,
                        idigdiRight: r ? r.right : 0,
                        overflow: docW > cliW || Boolean(r && (r.left < -1 || r.right > cliW + 1)),
                    };
                })()""")
                if post_load_overflow["overflow"]:
                    print(f"❌ [실패] [{tc['name']}] 이미지 로드 후 가로 넘침 발생: {post_load_overflow}")
                    failed += 1
                else:
                    passed += 1

                # [REWORK 2] 앵커 이동 완료 대기 및 헤더 가림 / 뷰포트 내 표시 검사
                # 부드러운 스크롤 끄고 즉각적이고 안정적인 이동 보장
                page.evaluate("document.documentElement.style.scrollBehavior = 'auto'")
                nav_anchors = page.evaluate("[...document.querySelectorAll('nav a[href^=\"#\"]')].map(a => a.getAttribute('href'))")
                nav_overflow_errors = []
                for href in nav_anchors:
                    page.click(f"nav a[href='{href}']")
                    page.wait_for_timeout(80)
                    pos = page.evaluate(f"""(() => {{
                        const header = document.querySelector('header');
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
                        "(() => { const el = document.querySelector('#work-zerolingual .font-gwangyang'); return el ? getComputedStyle(el).fontFamily : ''; })()"
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

                    expected_focus_order = (
                        "#contact .contact-mail",
                        "button#copy-email",
                        '#contact .collection-note a[href="privacy.html"]',
                        "input#contact-email",
                        "textarea#contact-message",
                        "input#contact-consent",
                        "button#contact-submit",
                    )
                    focus_steps = []
                    for expected in expected_focus_order:
                        page.keyboard.press("Tab")
                        focus_steps.append(page.evaluate("""(expected) => {
                            const el = document.activeElement;
                            const s = getComputedStyle(el);
                            return {
                                expected,
                                actual: el.tagName + (el.id ? '#' + el.id : '') + (el.className ? '.' + String(el.className).trim().replaceAll(' ', '.') : ''),
                                matches: el === document.querySelector(expected),
                                isHoneypot: Boolean(el && el.id === 'contact-website'),
                                width: parseFloat(s.outlineWidth),
                                style: s.outlineStyle,
                                offset: parseFloat(s.outlineOffset)
                            };
                        }""", expected))
                    if all(step["matches"] and not step["isHoneypot"] for step in focus_steps):
                        print("✅ [통과] 연락처·개인정보처리방침·양식 입력·동의·제출 버튼 Tab 포커스 순서(허니팟 건너뜀) 확인")
                        passed += 1
                    else:
                        print(f"❌ [실패] 키보드 포커스 순서 오류: {focus_steps}")
                        failed += 1

                    if all(step["width"] >= 2 and step["style"] != "none" and step["offset"] >= 3 for step in focus_steps):
                        print("✅ [통과] 연락처 및 노출된 문의 양식 요소의 키보드 포커스 링 확인")
                        passed += 1
                    else:
                        print(f"❌ [실패] 키보드 포커스 링 미흡: {focus_steps}")
                        failed += 1

                    copy_button = page.locator('#copy-email')
                    if copy_button.count():
                        copy_button.click()
                        try:
                            page.locator('#copy-status').filter(has_text=re.compile(r"복사했|복사하지 못했")).wait_for(timeout=5000)
                            print("✅ [통과] 이메일 복사 결과 접근성 알림 확인")
                            passed += 1
                        except PlaywrightTimeoutError:
                            print("❌ [실패] 이메일 복사 결과 접근성 알림 누락")
                            failed += 1
                    else:
                        print("❌ [실패] 이메일 복사 버튼 누락")
                        failed += 1

                    contact_state = page.evaluate("""(expectedSiteKey) => {
                        const contact = document.getElementById('contact');
                        const fallback = document.getElementById('contact-fallback');
                        const form = document.getElementById('contact-form');
                        const startedAt = document.getElementById('contact-started-at');
                        const widget = document.querySelector('#contact-form .cf-turnstile');
                        const scriptEl = document.head.querySelector('script[src="https://challenges.cloudflare.com/turnstile/v0/api.js"]');
                        const formFallbackLink = document.querySelector('#form-fallback a[href="mailto:2min@1min.dev"]');
                        const honeypotBox = document.querySelector('#contact-form .honeypot');
                        const honeypotInput = document.getElementById('contact-website');
                        const isVisible = el => Boolean(el && el.getClientRects().length > 0 && getComputedStyle(el).visibility !== 'hidden');
                        const visibleMailCount = contact ? [...contact.querySelectorAll('a[href="mailto:2min@1min.dev"]')].filter(isVisible).length : 0;
                        const visibleCopyButtonCount = contact ? [...contact.querySelectorAll('#copy-email')].filter(isVisible).length : 0;
                        const visibleButtonIds = contact ? [...contact.querySelectorAll('button')].filter(isVisible).map(btn => btn.id) : [];
                        return {
                            siteKeyMatches: Boolean(widget && widget.dataset.sitekey === expectedSiteKey),
                            formVisible: Boolean(form && !form.hidden && getComputedStyle(form).display !== 'none' && form.getClientRects().length > 0),
                            fallbackHidden: Boolean(fallback && fallback.hidden && getComputedStyle(fallback).display === 'none' && fallback.getClientRects().length === 0),
                            startedAtPopulated: Boolean(startedAt && /^\\d{13,}$/.test(startedAt.value)),
                            turnstileScriptInjected: Boolean(scriptEl && scriptEl.async && scriptEl.defer),
                            visibleMailCount,
                            visibleCopyButtonCount,
                            visibleButtonIds,
                            formFallbackLinkExists: Boolean(formFallbackLink),
                            honeypotHidden: Boolean(
                                honeypotBox &&
                                honeypotBox.hidden &&
                                honeypotBox.getAttribute('aria-hidden') === 'true' &&
                                getComputedStyle(honeypotBox).display === 'none' &&
                                honeypotBox.getClientRects().length === 0 &&
                                honeypotInput &&
                                honeypotInput.tabIndex === -1 &&
                                honeypotInput.getAttribute('autocomplete') === 'off' &&
                                honeypotInput.getClientRects().length === 0
                            ),
                        };
                    }""", TURNSTILE_PUBLIC_SITEKEY)
                    if (
                        contact_state["siteKeyMatches"]
                        and contact_state["formVisible"]
                        and contact_state["fallbackHidden"]
                        and contact_state["startedAtPopulated"]
                        and contact_state["turnstileScriptInjected"]
                        and TURNSTILE_SCRIPT_URL in turnstile_requests
                        and contact_state["visibleMailCount"] == 1
                        and contact_state["visibleCopyButtonCount"] == 1
                        and contact_state["visibleButtonIds"] == ["copy-email", "contact-submit"]
                        and contact_state["formFallbackLinkExists"]
                    ):
                        print("✅ [통과] 실제 Turnstile 키 상태에서 양식 노출·대체 안내 숨김·스크립트 요청 확인")
                        passed += 1
                    else:
                        print(
                            f"❌ [실패] 실제 Turnstile 키 양식 노출 또는 스크립트 로드 상태 오류: "
                            f"state={contact_state}, requests={turnstile_requests}"
                        )
                        failed += 1

                    if contact_state["honeypotHidden"]:
                        print("✅ [통과] 양식 노출 상태에서도 허니팟 필드 화면·보조기기 숨김 및 포커스 제외 확인")
                        passed += 1
                    else:
                        print(f"❌ [실패] 허니팟 필드 숨김 상태 미흡: {contact_state}")
                        failed += 1

                    # Turnstile 스크립트를 못 불러왔을 때(빈 응답 가로채기 상태) 미인증 제출 방어 및 메일 대체 수단 확인
                    page.fill("#contact-email", "tester@example.com")
                    page.fill("#contact-message", "문의 테스트입니다.")
                    page.check("#contact-consent")
                    page.click("#contact-submit")
                    blocked_submit_state = page.evaluate("""(() => {
                        const contact = document.getElementById('contact');
                        const status = document.getElementById('form-status');
                        const count = document.getElementById('character-count');
                        const directMail = document.querySelector('#contact .contact-mail[href="mailto:2min@1min.dev"]');
                        const copyBtn = document.getElementById('copy-email');
                        const formFallbackLink = document.querySelector('#form-fallback a[href="mailto:2min@1min.dev"]');
                        const isVisible = el => Boolean(el && el.getClientRects().length > 0 && getComputedStyle(el).visibility !== 'hidden');
                        return {
                            statusText: status ? status.textContent.trim() : '',
                            countText: count ? count.textContent.trim() : '',
                            directMailVisible: isVisible(directMail),
                            copyBtnVisible: isVisible(copyBtn),
                            visibleMailCount: contact ? [...contact.querySelectorAll('a[href="mailto:2min@1min.dev"]')].filter(isVisible).length : 0,
                            formFallbackLinkExists: Boolean(formFallbackLink),
                        };
                    })()""")
                    if (
                        blocked_submit_state["statusText"] == "보안 확인을 완료해 주세요."
                        and blocked_submit_state["countText"] == "10 / 4000자"
                        and blocked_submit_state["directMailVisible"]
                        and blocked_submit_state["copyBtnVisible"]
                        and blocked_submit_state["visibleMailCount"] == 1
                        and blocked_submit_state["formFallbackLinkExists"]
                        and not external_requests
                    ):
                        print("✅ [통과] Turnstile 스크립트 미로드(빈 응답) 시 미인증 제출 차단 안내 및 상시 메일 대체 수단 동작 확인")
                        passed += 1
                    else:
                        print(
                            f"❌ [실패] Turnstile 미로드 시 제출 방어 또는 메일 대체 안내 오류: "
                            f"state={blocked_submit_state}, external={external_requests}"
                        )
                        failed += 1

                    # (a), (c) 갤러리 키보드 열기 수단 및 #work-naeil 블록·링크·이미지 검증
                    gallery_naeil_state = page.evaluate("""(() => {
                        const galleryImgs = [...document.querySelectorAll('.gallery figure img')];
                        const allWrapped = galleryImgs.length === 15 && galleryImgs.every(img => {
                            const btn = img.closest('button[type="button"]');
                            if (!btn) return false;
                            const label = btn.getAttribute('aria-label') || '';
                            const r = btn.getBoundingClientRect();
                            return label.includes('크게 보기') && r.width >= 44 && r.height >= 44;
                        });
                        const idigdi = document.getElementById('work-idigdi');
                        const naeil = document.getElementById('work-naeil');
                        const deulmaru = document.getElementById('work-deulmaru');
                        const contestList = document.querySelector('#other-projects ol.contest-list');
                        const naeilLink = naeil ? naeil.querySelector('a[href="https://bw-tomorrow.1min.dev"]') : null;
                        const naeilImgs = naeil ? [...naeil.querySelectorAll('img')] : [];
                        const naeilImg = naeilImgs[0] || null;
                        const orderOk = Boolean(
                            idigdi && naeil && deulmaru && contestList &&
                            (idigdi.compareDocumentPosition(naeil) & Node.DOCUMENT_POSITION_FOLLOWING) &&
                            (naeil.compareDocumentPosition(deulmaru) & Node.DOCUMENT_POSITION_FOLLOWING) &&
                            (deulmaru.compareDocumentPosition(contestList) & Node.DOCUMENT_POSITION_FOLLOWING)
                        );
                        return {
                            galleryCount: galleryImgs.length,
                            allWrapped,
                            orderOk,
                            naeilTitle: naeil ? (naeil.querySelector('h3')?.textContent.trim() || '') : '',
                            naeilImgCount: naeilImgs.length,
                            naeilLinkOk: Boolean(
                                naeilLink &&
                                naeilLink.target === '_blank' &&
                                naeilLink.rel.includes('noopener') &&
                                naeilLink.rel.includes('noreferrer') &&
                                naeilLink.textContent.trim() === '서비스 방문하기'
                            ),
                            naeilImgOk: Boolean(
                                naeilImg &&
                                naeilImg.getAttribute('src') === 'assets/naeil-home.webp' &&
                                naeilImg.alt === '내일이음 첫 화면' &&
                                naeilImg.complete &&
                                naeilImg.naturalWidth === 1280 &&
                                naeilImg.naturalHeight === 800
                            ),
                        };
                    })()""")
                    if (
                        gallery_naeil_state["allWrapped"]
                        and gallery_naeil_state["orderOk"]
                        and gallery_naeil_state["naeilTitle"] == "내일이음"
                        and gallery_naeil_state["naeilImgCount"] == 1
                        and gallery_naeil_state["naeilLinkOk"]
                        and gallery_naeil_state["naeilImgOk"]
                    ):
                        print("✅ [통과] 전체 갤러리 키보드 열기 버튼(15장) 및 내일이음(#work-naeil) 블록·링크·이미지 확인")
                        passed += 1
                    else:
                        print(f"❌ [실패] 갤러리 키보드 버튼 또는 내일이음 블록 오류: {gallery_naeil_state}")
                        failed += 1

                    # (b) 라이트박스 dialog 열기(키보드·클릭), → 전환, 스와이프, Esc·배경 닫기, 포커스 복귀, 1장 갤러리 버튼 숨김 검증
                    first_gallery_btn = page.locator("#work-zerolingual .gallery button.gallery-item").first
                    first_gallery_btn.focus()
                    page.keyboard.press("Enter")
                    page.wait_for_timeout(240)
                    kb_open_state = page.evaluate("""(() => {
                        const dlg = document.getElementById('lightbox');
                        return {
                            open: Boolean(dlg && dlg.open),
                            activeId: document.activeElement ? document.activeElement.id : '',
                            bodyOverflow: getComputedStyle(document.body).overflow,
                        };
                    })()""")
                    page.keyboard.press("Escape")
                    kb_close_returned = page.evaluate(
                        "() => !document.getElementById('lightbox').open && "
                        "getComputedStyle(document.body).overflow !== 'hidden' && "
                        "document.activeElement === document.querySelector('#work-zerolingual .gallery button.gallery-item')"
                    )

                    first_gallery_btn.click()
                    page.wait_for_timeout(240)
                    step1 = page.evaluate("""(() => {
                        const dlg = document.getElementById('lightbox');
                        const img = document.getElementById('lightbox-image');
                        const prev = document.getElementById('lightbox-prev');
                        const next = document.getElementById('lightbox-next');
                        return {
                            open: Boolean(dlg && dlg.open),
                            activeId: document.activeElement ? document.activeElement.id : '',
                            bodyOverflow: getComputedStyle(document.body).overflow,
                            src: img ? img.getAttribute('src') : '',
                            count: document.getElementById('lightbox-count')?.textContent.trim() || '',
                            caption: document.getElementById('lightbox-caption')?.textContent.trim() || '',
                            navVisible: Boolean(prev && !prev.hidden && next && !next.hidden && prev.getClientRects().length > 0 && next.getClientRects().length > 0),
                        };
                    })()""")
                    page.keyboard.press("ArrowRight")
                    step2 = page.evaluate("""(() => ({
                        src: document.getElementById('lightbox-image')?.getAttribute('src') || '',
                        count: document.getElementById('lightbox-count')?.textContent.trim() || '',
                        caption: document.getElementById('lightbox-caption')?.textContent.trim() || '',
                    }))()""")
                    page.evaluate("""(() => {
                        const stage = document.getElementById('lightbox-stage');
                        stage.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, pointerId: 1, pointerType: 'touch', clientX: 320, clientY: 300 }));
                        stage.dispatchEvent(new PointerEvent('pointerup', { bubbles: true, pointerId: 1, pointerType: 'touch', clientX: 200, clientY: 305 }));
                    })()""")
                    step3 = page.evaluate("""(() => ({
                        src: document.getElementById('lightbox-image')?.getAttribute('src') || '',
                        count: document.getElementById('lightbox-count')?.textContent.trim() || '',
                        caption: document.getElementById('lightbox-caption')?.textContent.trim() || '',
                    }))()""")
                    page.keyboard.press("Escape")
                    after_esc = page.evaluate("""(() => ({
                        open: Boolean(document.getElementById('lightbox')?.open),
                        bodyOverflow: getComputedStyle(document.body).overflow,
                        focusReturned: document.activeElement === document.querySelector('#work-zerolingual .gallery button.gallery-item'),
                    }))()""")

                    naeil_btn = page.locator("#work-naeil .gallery button.gallery-item").first
                    naeil_btn.click()
                    page.wait_for_timeout(240)
                    single_state = page.evaluate("""(() => {
                        const dlg = document.getElementById('lightbox');
                        const prev = document.getElementById('lightbox-prev');
                        const next = document.getElementById('lightbox-next');
                        return {
                            open: Boolean(dlg && dlg.open),
                            src: document.getElementById('lightbox-image')?.getAttribute('src') || '',
                            count: document.getElementById('lightbox-count')?.textContent.trim() || '',
                            caption: document.getElementById('lightbox-caption')?.textContent.trim() || '',
                            navHidden: Boolean(prev && prev.hidden && prev.getClientRects().length === 0 && next && next.hidden && next.getClientRects().length === 0),
                        };
                    })()""")
                    page.mouse.click(5, 5)
                    after_backdrop = page.evaluate("""(() => ({
                        open: Boolean(document.getElementById('lightbox')?.open),
                        focusReturned: document.activeElement === document.querySelector('#work-naeil .gallery button.gallery-item'),
                    }))()""")

                    idigdi_thumb_state = page.evaluate("""(() => {
                        const imgs = [...document.querySelectorAll('#work-idigdi .gallery figure img')];
                        if (imgs.length !== 4) return { ok: false, count: imgs.length };
                        const rects = imgs.map(img => img.getBoundingClientRect());
                        const mobileStyle = getComputedStyle(imgs[3]);
                        return {
                            ok: (
                                imgs[0].naturalWidth === 1200 && imgs[0].naturalHeight === 750 &&
                                imgs[1].naturalWidth === 1200 && imgs[1].naturalHeight === 750 &&
                                imgs[2].naturalWidth === 1200 && imgs[2].naturalHeight === 750 &&
                                imgs[3].naturalWidth === 555 && imgs[3].naturalHeight === 1200 &&
                                rects[0].width > rects[1].width * 1.8 &&
                                Math.abs(rects[3].height - rects[1].height) <= 1 &&
                                Math.abs(rects[3].height - rects[2].height) <= 1 &&
                                rects[3].width > rects[3].height &&
                                mobileStyle.objectFit === 'cover'
                            ),
                            rects: rects.map(r => ({ width: r.width, height: r.height })),
                            objectFit: mobileStyle.objectFit,
                        };
                    })()""")
                    idigdi_btn = page.locator("#work-idigdi .gallery button.gallery-item").first
                    idigdi_btn.click()
                    idigdi_steps = []
                    for step in range(5):
                        page.wait_for_function(
                            "() => { const img = document.getElementById('lightbox-image'); return Boolean(img && img.complete && img.naturalWidth > 0); }",
                            timeout=5000,
                        )
                        idigdi_steps.append(page.evaluate("""(() => {
                            const dlg = document.getElementById('lightbox');
                            const img = document.getElementById('lightbox-image');
                            const r = img ? img.getBoundingClientRect() : { width: 0, height: 0 };
                            const s = img ? getComputedStyle(img) : { objectFit: '' };
                            return {
                                open: Boolean(dlg && dlg.open),
                                src: img ? img.getAttribute('src') : '',
                                count: document.getElementById('lightbox-count')?.textContent.trim() || '',
                                caption: document.getElementById('lightbox-caption')?.textContent.trim() || '',
                                attrWidth: img ? Number(img.getAttribute('width')) : 0,
                                attrHeight: img ? Number(img.getAttribute('height')) : 0,
                                naturalWidth: img ? img.naturalWidth : 0,
                                naturalHeight: img ? img.naturalHeight : 0,
                                renderWidth: r.width,
                                renderHeight: r.height,
                                objectFit: s.objectFit,
                            };
                        })()"""))
                        if step < 4:
                            page.locator("#lightbox-next").click()
                    page.keyboard.press("Escape")
                    expected_idigdi_steps = [
                        ("assets/idigdi-main.webp", "1 / 4", "첫 화면"),
                        ("assets/idigdi-results.webp", "2 / 4", "CLIP 분석 결과·닮은 여행지"),
                        ("assets/idigdi-route.webp", "3 / 4", "맞춤 여행 코스"),
                        ("assets/idigdi-mobile.webp", "4 / 4", "모바일 첫 화면"),
                        ("assets/idigdi-main.webp", "1 / 4", "첫 화면"),
                    ]
                    mobile_lb = idigdi_steps[3]
                    mobile_content_ratio = (
                        (mobile_lb["renderWidth"] - 2) / (mobile_lb["renderHeight"] - 2)
                        if mobile_lb["renderHeight"] > 2
                        else 0
                    )
                    idigdi_ok = (
                        idigdi_thumb_state["ok"]
                        and all(
                            actual["open"] and (actual["src"], actual["count"], actual["caption"]) == expected
                            for actual, expected in zip(idigdi_steps, expected_idigdi_steps)
                        )
                        and mobile_lb["attrWidth"] == 555
                        and mobile_lb["attrHeight"] == 1200
                        and mobile_lb["naturalWidth"] == 555
                        and mobile_lb["naturalHeight"] == 1200
                        and mobile_lb["objectFit"] == "contain"
                        and mobile_lb["renderHeight"] > mobile_lb["renderWidth"]
                        and abs(mobile_content_ratio - (555 / 1200)) < 0.02
                        and not page.locator("#lightbox").evaluate("(dlg) => dlg.open")
                    )
                    if idigdi_ok:
                        print("✅ [통과] 이디그디 갤러리 4장 배치(모바일 썸네일 높이 맞춤) 및 라이트박스 4장 순환·원본 세로 비율 표시 확인")
                        passed += 1
                    else:
                        print(f"❌ [실패] 이디그디 갤러리 또는 라이트박스 오류: thumb={idigdi_thumb_state}, steps={idigdi_steps}")
                        failed += 1

                    deulmaru_btn = page.locator("#work-deulmaru .gallery button.gallery-item").first
                    deulmaru_btn.click()
                    deulmaru_steps = []
                    for step in range(6):
                        deulmaru_steps.append(page.evaluate("""(() => ({
                            open: Boolean(document.getElementById('lightbox')?.open),
                            src: document.getElementById('lightbox-image')?.getAttribute('src') || '',
                            count: document.getElementById('lightbox-count')?.textContent.trim() || '',
                            caption: document.getElementById('lightbox-caption')?.textContent.trim() || '',
                        }))()"""))
                        if step < 5:
                            page.locator("#lightbox-next").click()
                    page.keyboard.press("Escape")
                    expected_deulmaru_steps = [
                        ("assets/deulmaru-main.webp", "1 / 5", "첫 화면"),
                        ("assets/deulmaru-support.webp", "2 / 5", "지원사업 정보"),
                        ("assets/deulmaru-pest.webp", "3 / 5", "병해충 사전"),
                        ("assets/deulmaru-consulting.webp", "4 / 5", "병해충 상담"),
                        ("assets/deulmaru-ai.webp", "5 / 5", "AI 병해충 판별"),
                        ("assets/deulmaru-main.webp", "1 / 5", "첫 화면"),
                    ]
                    deulmaru_ok = all(
                        actual["open"] and (actual["src"], actual["count"], actual["caption"]) == expected
                        for actual, expected in zip(deulmaru_steps, expected_deulmaru_steps)
                    ) and not page.locator("#lightbox").evaluate("(dlg) => dlg.open")
                    if deulmaru_ok:
                        print("✅ [통과] 들마루 라이트박스 5장 순서·캡션·카운트 및 첫 장 순환 확인")
                        passed += 1
                    else:
                        print(f"❌ [실패] 들마루 라이트박스 순환 오류: {deulmaru_steps}")
                        failed += 1

                    if (
                        kb_open_state["open"]
                        and kb_open_state["activeId"] == "lightbox-close"
                        and kb_open_state["bodyOverflow"] == "hidden"
                        and kb_close_returned
                        and step1["open"]
                        and step1["activeId"] == "lightbox-close"
                        and step1["bodyOverflow"] == "hidden"
                        and step1["src"] == "assets/today.webp"
                        and step1["count"] == "1 / 3"
                        and step1["caption"] == "오늘의 단어"
                        and step1["navVisible"]
                        and step2["src"] == "assets/card.webp"
                        and step2["count"] == "2 / 3"
                        and step2["caption"] == "어휘 카드"
                        and step3["src"] == "assets/quiz.webp"
                        and step3["count"] == "3 / 3"
                        and step3["caption"] == "복습 퀴즈"
                        and not after_esc["open"]
                        and after_esc["bodyOverflow"] != "hidden"
                        and after_esc["focusReturned"]
                        and single_state["open"]
                        and single_state["src"] == "assets/naeil-home.webp"
                        and single_state["count"] == "1 / 1"
                        and single_state["caption"] == "내일이음 첫 화면"
                        and single_state["navHidden"]
                        and not after_backdrop["open"]
                        and after_backdrop["focusReturned"]
                    ):
                        print("✅ [통과] 라이트박스 dialog 열기·→/스와이프 전환·Esc/배경 닫기·포커스 복귀·1장 버튼 숨김 확인")
                        passed += 1
                    else:
                        print(
                            f"❌ [실패] 라이트박스 동작 오류: kb={kb_open_state}/{kb_close_returned}, "
                            f"step1={step1}, step2={step2}, step3={step3}, esc={after_esc}, "
                            f"single={single_state}, backdrop={after_backdrop}"
                        )
                        failed += 1

                    page.mouse.move(0, 0)

                if tc["width"] in (1280, 390):
                    # A preceding click can leave the button hovered during its 140ms color transition.
                    page.wait_for_timeout(160)
                    contrast_issues = page.evaluate("""(() => {
                        const parse = value => {
                            const m = value.match(/[\\d.]+/g);
                            return m ? m.slice(0, 4).map(Number) : null;
                        };
                        const luminance = rgb => {
                            const c = rgb.slice(0, 3).map(v => {
                                v /= 255;
                                return v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4;
                            });
                            return .2126 * c[0] + .7152 * c[1] + .0722 * c[2];
                        };
                        const issues = [];
                        for (const el of document.querySelectorAll('p, h1, h2, h3, a, button, li, dt, dd, label, output, span, strong')) {
                            if (!el.textContent.trim() || !el.getClientRects().length) continue;
                            const fg = parse(getComputedStyle(el).color);
                            let bg = null;
                            for (let node = el; node && !bg; node = node.parentElement) {
                                const c = parse(getComputedStyle(node).backgroundColor);
                                if (c && (c.length < 4 || c[3] >= .99)) bg = c;
                            }
                            if (!bg) bg = parse(getComputedStyle(document.body).backgroundColor);
                            if (!fg || !bg) continue;
                            const a = luminance(fg), b = luminance(bg);
                            const ratio = (Math.max(a, b) + .05) / (Math.min(a, b) + .05);
                            if (ratio < 4.5) issues.push(`${el.tagName.toLowerCase()}${el.id ? '#' + el.id : ''}: ${ratio.toFixed(2)}`);
                        }
                        return issues.slice(0, 15);
                    })()""")
                    if contrast_issues:
                        print(f"❌ [실패] [{tc['name']}] 텍스트 대비 4.5:1 미만: {contrast_issues}")
                        failed += 1
                    else:
                        print(f"✅ [통과] [{tc['name']}] 본문·버튼·링크 대비 4.5:1 이상")
                        passed += 1

                    page.emulate_media(reduced_motion="reduce")
                    reduced = page.evaluate("""(() => {
                        if (!matchMedia('(prefers-reduced-motion: reduce)').matches) return false;
                        const el = document.querySelector('a');
                        const s = getComputedStyle(el);
                        return parseFloat(s.transitionDuration) <= .001 && getComputedStyle(document.documentElement).scrollBehavior === 'auto';
                    })()""")
                    if reduced:
                        print(f"✅ [통과] [{tc['name']}] 모션 감소 설정 반영")
                        passed += 1
                    else:
                        print(f"❌ [실패] [{tc['name']}] 모션 감소 설정 미반영")
                        failed += 1
                    page.emulate_media(reduced_motion="no-preference")

                if tc["width"] == 390:
                    small_targets = page.evaluate("""(() => [...document.querySelectorAll('a, button')]
                        .filter(el => el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden')
                        .map(el => ({name: el.textContent.trim().slice(0, 24) || el.getAttribute('aria-label') || el.tagName,
                                     width: el.getBoundingClientRect().width, height: el.getBoundingClientRect().height}))
                        .filter(el => el.width < 44 || el.height < 44)
                        .slice(0, 15))()""")
                    if small_targets:
                        print(f"❌ [실패] [{tc['name']}] 44×44px 미만 터치 영역: {small_targets}")
                        failed += 1
                    else:
                        print(f"✅ [통과] [{tc['name']}] 링크·버튼 44×44px 이상")
                        passed += 1

                # (d) 열린 dialog 상태에서의 터치 영역 44×44px·대비 4.5:1·모션 감소 검증
                if tc["width"] in (1280, 390):
                    page.locator("#work-zerolingual .gallery button.gallery-item").first.click()
                    page.mouse.move(0, 0)
                    page.wait_for_timeout(240)
                    dialog_a11y = page.evaluate("""(() => {
                        const dlg = document.getElementById('lightbox');
                        if (!dlg || !dlg.open) return { open: false, smallButtons: ['dialog-not-open'], contrastIssues: ['dialog-not-open'] };
                        const parse = value => {
                            const m = value.match(/[\\d.]+/g);
                            return m ? m.slice(0, 4).map(Number) : null;
                        };
                        const luminance = rgb => {
                            const c = rgb.slice(0, 3).map(v => {
                                v /= 255;
                                return v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4;
                            });
                            return .2126 * c[0] + .7152 * c[1] + .0722 * c[2];
                        };
                        const visibleBtns = [...dlg.querySelectorAll('button')].filter(
                            el => !el.hidden && el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden'
                        );
                        const smallButtons = visibleBtns
                            .map(el => ({ id: el.id || el.tagName, width: el.getBoundingClientRect().width, height: el.getBoundingClientRect().height }))
                            .filter(b => b.width < 44 || b.height < 44);
                        const contrastIssues = [];
                        for (const el of dlg.querySelectorAll('p, button, span, strong')) {
                            if (!el.textContent.trim() || !el.getClientRects().length) continue;
                            const fg = parse(getComputedStyle(el).color);
                            let bg = null;
                            for (let node = el; node && !bg; node = node.parentElement) {
                                const c = parse(getComputedStyle(node).backgroundColor);
                                if (c && (c.length < 4 || c[3] >= .99)) bg = c;
                            }
                            if (!bg) bg = parse(getComputedStyle(document.body).backgroundColor);
                            if (!fg || !bg) continue;
                            const a = luminance(fg), b = luminance(bg);
                            const ratio = (Math.max(a, b) + .05) / (Math.min(a, b) + .05);
                            if (ratio < 4.5) contrastIssues.push(`${el.tagName.toLowerCase()}${el.id ? '#' + el.id : ''}: ${ratio.toFixed(2)}`);
                        }
                        return { open: true, buttonCount: visibleBtns.length, smallButtons, contrastIssues };
                    })()""")
                    page.emulate_media(reduced_motion="reduce")
                    dialog_reduced = page.evaluate("""(() => {
                        const panel = document.querySelector('#lightbox .lightbox-panel');
                        if (!panel) return false;
                        const s = getComputedStyle(panel);
                        return s.animationName === 'none' || parseFloat(s.animationDuration) <= .001;
                    })()""")
                    page.emulate_media(reduced_motion="no-preference")
                    page.click("#lightbox-close")
                    page.mouse.move(0, 0)
                    dialog_closed_ok = page.evaluate("() => !document.getElementById('lightbox').open")

                    if (
                        dialog_a11y["open"]
                        and dialog_a11y["buttonCount"] == 3
                        and not dialog_a11y["smallButtons"]
                        and not dialog_a11y["contrastIssues"]
                        and dialog_reduced
                        and dialog_closed_ok
                    ):
                        print(f"✅ [통과] [{tc['name']}] 열린 dialog 버튼 44×44px 이상·대비 4.5:1 이상·모션 감소·닫기 버튼 확인")
                        passed += 1
                    else:
                        print(
                            f"❌ [실패] [{tc['name']}] 열린 dialog 접근성/대비/크기 오류: "
                            f"a11y={dialog_a11y}, reduced={dialog_reduced}, closed={dialog_closed_ok}"
                        )
                        failed += 1

                # [REWORK 1] 미리보기 캡처 직전 부드러운 스크롤 끄고 맨 위로 복귀 및 위치 안정화
                if tc["shot"]:
                    if tc["name"] == "desktop-1280-light":
                        page.evaluate("""(() => {
                            const form = document.getElementById('contact-form');
                            const count = document.getElementById('character-count');
                            const status = document.getElementById('form-status');
                            if (form) form.reset();
                            if (count) count.textContent = '0 / 4000자';
                            if (status) status.textContent = '';
                        })()""")
                    page.evaluate("if (document.activeElement && document.activeElement.blur) document.activeElement.blur()")
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
                    print(f"❌ [실패] [{tc['name']}] 허용되지 않은 외부 자산(CDN 등) 요청 감지: {external_requests}")
                    failed += 1
                else:
                    passed += 1

                if TURNSTILE_SCRIPT_URL not in turnstile_requests:
                    print(f"❌ [실패] [{tc['name']}] Turnstile 스크립트 요청 누락: {turnstile_requests}")
                    failed += 1
                else:
                    passed += 1

                context.close()

            # 테스트용 HTML 사본으로 자리표시 키(TURNSTILE_SITE_KEY) 상태 검증 (작업 트리에 임시 파일 미생성)
            index_html_raw = (WORKSPACE_DIR / "index.html").read_text(encoding="utf-8")
            placeholder_html = re.sub(
                r'(<div\b[^>]*\bclass=["\'][^"\']*\bcf-turnstile\b[^"\']*["\'][^>]*\bdata-sitekey=["\'])[^"\']*(["\'])',
                r"\1TURNSTILE_SITE_KEY\2",
                index_html_raw,
                count=1,
            )
            placeholder_context = browser.new_context(
                viewport={"width": 1280, "height": 800},
                color_scheme="light",
            )
            placeholder_page = placeholder_context.new_page()
            ph_console_errors = []
            ph_asset_404s = []
            ph_external_requests = []
            ph_turnstile_requests = []

            def handle_placeholder_html(route):
                route.fulfill(
                    status=200,
                    content_type="text/html; charset=utf-8",
                    body=placeholder_html,
                )

            def handle_placeholder_turnstile(route):
                ph_turnstile_requests.append(route.request.url)
                route.fulfill(
                    status=200,
                    content_type="application/javascript; charset=utf-8",
                    body="",
                )

            placeholder_page.route(f"{base_url}/__placeholder_key_test.html", handle_placeholder_html)
            placeholder_page.route("https://challenges.cloudflare.com/**", handle_placeholder_turnstile)
            placeholder_page.on("console", lambda msg: ph_console_errors.append(msg.text) if msg.type == "error" else None)
            placeholder_page.on("response", lambda res: ph_asset_404s.append(res.url) if res.status >= 400 else None)
            placeholder_page.on(
                "request",
                lambda req: ph_external_requests.append(req.url)
                if not is_allowed_external_request(req.url, base_url)
                else None,
            )

            ph_res = placeholder_page.goto(f"{base_url}/__placeholder_key_test.html", wait_until="networkidle")
            ph_state = placeholder_page.evaluate("""(() => {
                const contact = document.getElementById('contact');
                const fallback = document.getElementById('contact-fallback');
                const form = document.getElementById('contact-form');
                const isVisible = el => Boolean(el && el.getClientRects().length > 0 && getComputedStyle(el).visibility !== 'hidden');
                return {
                    fallbackVisible: Boolean(fallback && !fallback.hidden && getComputedStyle(fallback).display !== 'none' && fallback.getClientRects().length > 0),
                    formHidden: Boolean(form && form.hidden && getComputedStyle(form).display === 'none'),
                    visibleMailCount: contact ? [...contact.querySelectorAll('a[href="mailto:2min@1min.dev"]')].filter(isVisible).length : 0,
                    visibleCopyCount: contact ? [...contact.querySelectorAll('button')].filter(isVisible).length : 0,
                    turnstileScriptInDom: Boolean(document.querySelector('script[src*="challenges.cloudflare.com"]')),
                };
            })()""")
            if (
                ph_res
                and ph_res.status == 200
                and "TURNSTILE_SITE_KEY" in placeholder_html
                and TURNSTILE_PUBLIC_SITEKEY not in placeholder_html
                and ph_state["fallbackVisible"]
                and ph_state["formHidden"]
                and ph_state["visibleMailCount"] == 1
                and ph_state["visibleCopyCount"] == 1
                and not ph_state["turnstileScriptInDom"]
                and not ph_turnstile_requests
                and not ph_external_requests
                and not ph_console_errors
                and not ph_asset_404s
            ):
                print("✅ [통과] 자리표시 키(HTML 사본) 상태에서 대체 안내 노출·양식 숨김·Turnstile 미요청 확인")
                passed += 1
            else:
                print(
                    f"❌ [실패] 자리표시 키(HTML 사본) 상태 검증 오류: "
                    f"state={ph_state}, turnstile={ph_turnstile_requests}, external={ph_external_requests}, "
                    f"console={ph_console_errors}, 404={ph_asset_404s}"
                )
                failed += 1
            placeholder_context.close()

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
    tee_out = None
    tee_err = None
    try:
        tee_out = TeeLogger(VERIFY_LOG_FILE, orig_stdout)
        tee_err = TeeLogger(PWTMP_DIR / "verify-err.txt", orig_stderr)
    except Exception as e:
        if tee_out:
            try:
                tee_out.close()
            except Exception:
                pass
        orig_stderr.write(f"❌ [치명적 오류] 로그 파일 초기화 실패: {e}\n")
        sys.exit(1)

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
        try:
            if tee_out:
                tee_out.flush()
                tee_out.close()
        finally:
            if tee_err:
                tee_err.flush()
                tee_err.close()

    if total_failed > 0:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
