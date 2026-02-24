# -*- coding: utf-8 -*-
"""
Affiliate Marketing System -- Coupang Product Scraper & Partners API
====================================================================
쿠팡 상품 페이지 스크래핑 + Coupang Partners Deep Link API 통합.
상품 URL만 넣으면 Product 객체 + 제휴 링크를 자동 생성한다.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from affiliate_system.config import (
    COUPANG_ACCESS_KEY,
    COUPANG_SECRET_KEY,
    COUPANG_PARTNER_ID,
)
from affiliate_system.models import Product
from affiliate_system.utils import setup_logger, retry

__all__ = ["CoupangScraper"]

logger = setup_logger("coupang_scraper", "coupang_scraper.log")

# ── 상수 ──
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
_REQUEST_TIMEOUT = 30
_COUPANG_API_HOST = "api-gateway.coupang.com"
_DEEPLINK_PATH = "/v2/providers/affiliate_open_api/apis/openapi/v1/deeplink"


class CoupangScraper:
    """쿠팡 상품 스크래퍼 + Coupang Partners 제휴 링크 생성기.

    사용법:
        scraper = CoupangScraper()
        product = scraper.scrape_and_link("https://www.coupang.com/vp/products/...")
        print(product.title, product.price, product.affiliate_link)
    """

    def __init__(self):
        self._session = requests.Session()
        # 쿠팡 봇 차단 우회를 위한 브라우저 모방 헤더
        self._session.headers.update({
            "User-Agent": _USER_AGENT,
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Cache-Control": "max-age=0",
            "Sec-Ch-Ua": '"Chromium";v="131", "Not_A Brand";v="24"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
        })
        logger.info("CoupangScraper 초기화 완료")

    # ──────────────────────────────────────────────
    # 유틸리티
    # ──────────────────────────────────────────────

    @staticmethod
    def is_coupang_url(url: str) -> bool:
        """URL이 쿠팡 도메인인지 판별한다."""
        try:
            host = urlparse(url).netloc.lower()
            return "coupang.com" in host
        except Exception:
            return False

    # ──────────────────────────────────────────────
    # 상품 스크래핑
    # ──────────────────────────────────────────────

    @retry(max_attempts=3, delay=2.0)
    def scrape_product(self, url: str) -> Product:
        """쿠팡 상품 페이지에서 상품 정보를 추출한다.

        추출 우선순위: JSON-LD > Open Graph > CSS 셀렉터

        Args:
            url: 쿠팡 상품 URL

        Returns:
            상품 정보가 채워진 Product 객체
        """
        logger.info(f"쿠팡 상품 스크래핑 시작: {url}")

        # 쿠팡 메인 먼저 방문하여 쿠키 획득
        try:
            self._session.get(
                "https://www.coupang.com",
                timeout=10,
                allow_redirects=True,
            )
            time.sleep(0.5)
        except Exception:
            pass

        # 상품 페이지 요청 (Referer 헤더 추가)
        headers = {"Referer": "https://www.coupang.com/"}
        resp = self._session.get(url, timeout=_REQUEST_TIMEOUT,
                                  headers=headers, allow_redirects=True)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        title = ""
        price = ""
        description = ""
        image_urls: list[str] = []

        # 1) JSON-LD 데이터 추출 시도
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") in ("Product", "product"):
                        title = title or item.get("name", "")
                        description = description or item.get("description", "")
                        img = item.get("image", "")
                        if isinstance(img, str) and img:
                            image_urls.append(img)
                        elif isinstance(img, list):
                            image_urls.extend([i for i in img if isinstance(i, str)])
                        offers = item.get("offers", {})
                        if isinstance(offers, list):
                            offers = offers[0] if offers else {}
                        p = offers.get("price", "")
                        if p:
                            price = price or f"{int(float(p)):,}원"
            except (json.JSONDecodeError, ValueError, TypeError):
                continue

        # 2) Open Graph 메타 태그
        if not title:
            og_title = soup.find("meta", property="og:title")
            if og_title and og_title.get("content"):
                title = og_title["content"].strip()

        if not description:
            og_desc = soup.find("meta", property="og:description")
            if og_desc and og_desc.get("content"):
                description = og_desc["content"].strip()

        if not image_urls:
            og_image = soup.find("meta", property="og:image")
            if og_image and og_image.get("content"):
                image_urls.append(og_image["content"])

        if not price:
            price_meta = soup.find("meta", property="product:price:amount")
            if price_meta and price_meta.get("content"):
                try:
                    price = f"{int(float(price_meta['content'])):,}원"
                except ValueError:
                    pass

        # 3) CSS 셀렉터 폴백
        if not title:
            for sel in ["h2.prod-buy-header__title", "h1.prod-buy-header__title",
                        ".prod-buy-header__title", "title"]:
                el = soup.select_one(sel)
                if el and el.get_text(strip=True):
                    title = el.get_text(strip=True)
                    title = re.sub(r'\s*[-|]\s*쿠팡[!]?\s*$', '', title)
                    break

        if not price:
            for sel in [".total-price strong", "span.total-price",
                        ".prod-sale-price", ".prod-coupon-price .total-price"]:
                el = soup.select_one(sel)
                if el and el.get_text(strip=True):
                    raw_price = el.get_text(strip=True)
                    digits = re.sub(r'[^\d]', '', raw_price)
                    if digits:
                        price = f"{int(digits):,}원"
                    break

        if not image_urls:
            for img in soup.select(".prod-image__item img, .prod-image img"):
                src = img.get("src") or img.get("data-img-src", "")
                if src and src.startswith("http"):
                    image_urls.append(src)
                if len(image_urls) >= 5:
                    break

        if not description:
            meta_desc = soup.find("meta", attrs={"name": "description"})
            if meta_desc and meta_desc.get("content"):
                description = meta_desc["content"].strip()

        product = Product(
            url=url,
            title=title,
            price=price,
            image_urls=image_urls[:10],
            description=description[:2000],
            scraped_at=datetime.now(),
        )

        logger.info(
            f"쿠팡 스크래핑 완료: title={len(title)}자, price={price}, "
            f"images={len(product.image_urls)}개"
        )
        return product

    # ──────────────────────────────────────────────
    # Coupang Partners Deep Link API
    # ──────────────────────────────────────────────

    def _generate_hmac_signature(self, method: str, url_path: str,
                                  datetime_str: str) -> str:
        """Coupang Partners HMAC-SHA256 서명을 생성한다."""
        message = datetime_str + method + url_path
        signature = hmac.HMAC(
            COUPANG_SECRET_KEY.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return signature

    @retry(max_attempts=2, delay=1.0)
    def generate_affiliate_link(self, product_url: str) -> str:
        """Coupang Partners Deep Link API로 제휴 추적 링크를 생성한다.

        API 키가 설정되지 않으면 빈 문자열을 반환한다 (graceful degradation).

        Args:
            product_url: 쿠팡 상품 URL

        Returns:
            제휴 추적 단축 URL (예: https://link.coupang.com/...) 또는 빈 문자열
        """
        if not COUPANG_ACCESS_KEY or not COUPANG_SECRET_KEY:
            logger.warning("쿠팡 파트너스 API 키 미설정 — 제휴 링크 생성 건너뜀")
            return ""

        # 타임스탬프 (yyMMddTHHmmssZ 형식)
        dt = datetime.now(timezone.utc)
        datetime_str = dt.strftime("%y%m%dT%H%M%SZ")

        method = "POST"
        signature = self._generate_hmac_signature(method, _DEEPLINK_PATH, datetime_str)

        authorization = (
            f"CEA algorithm=HmacSHA256, access-key={COUPANG_ACCESS_KEY}, "
            f"signed-date={datetime_str}, signature={signature}"
        )

        headers = {
            "Authorization": authorization,
            "Content-Type": "application/json;charset=UTF-8",
        }

        body = {
            "coupangUrls": [product_url],
        }
        if COUPANG_PARTNER_ID:
            body["subId"] = COUPANG_PARTNER_ID

        api_url = f"https://{_COUPANG_API_HOST}{_DEEPLINK_PATH}"

        logger.info(f"쿠팡 Deep Link API 호출: {product_url[:60]}...")

        resp = requests.post(
            api_url, headers=headers,
            json=body, timeout=_REQUEST_TIMEOUT,
        )

        # 응답 디버깅
        logger.info(f"API 응답 코드: {resp.status_code}")
        if resp.status_code != 200:
            logger.error(f"API 응답 본문: {resp.text[:500]}")
            resp.raise_for_status()

        result = resp.json()
        data = result.get("data", [])

        if data and isinstance(data, list) and len(data) > 0:
            short_url = data[0].get("shortenUrl", "")
            if short_url:
                logger.info(f"제휴 링크 생성 완료: {short_url}")
                return short_url

        logger.warning(f"제휴 링크 응답에 shortenUrl 없음: {result}")
        return ""

    # ──────────────────────────────────────────────
    # Coupang Partners 상품 검색 API (스크래핑 폴백)
    # ──────────────────────────────────────────────

    def search_products(self, keyword: str, limit: int = 5) -> list[Product]:
        """Coupang Partners 상품 검색 API로 상품을 검색한다.

        웹 스크래핑이 차단될 때의 대안 방법.
        검색 결과에 제휴 링크가 이미 포함되어 있다.

        Args:
            keyword: 검색 키워드
            limit: 결과 수 (기본 5)

        Returns:
            Product 리스트 (제휴 링크 포함)
        """
        if not COUPANG_ACCESS_KEY or not COUPANG_SECRET_KEY:
            logger.warning("API 키 미설정 — 검색 건너뜀")
            return []

        search_path = "/v2/providers/affiliate_open_api/apis/openapi/products/search"
        query_string = f"?keyword={keyword}&limit={limit}"
        full_path = search_path + query_string

        dt = datetime.now(timezone.utc)
        datetime_str = dt.strftime("%y%m%dT%H%M%SZ")

        method = "GET"
        signature = self._generate_hmac_signature(method, full_path, datetime_str)

        authorization = (
            f"CEA algorithm=HmacSHA256, access-key={COUPANG_ACCESS_KEY}, "
            f"signed-date={datetime_str}, signature={signature}"
        )

        headers = {
            "Authorization": authorization,
            "Content-Type": "application/json;charset=UTF-8",
        }

        api_url = f"https://{_COUPANG_API_HOST}{full_path}"
        logger.info(f"쿠팡 상품 검색 API: keyword='{keyword}', limit={limit}")

        try:
            resp = requests.get(api_url, headers=headers, timeout=_REQUEST_TIMEOUT)
            logger.info(f"검색 API 응답 코드: {resp.status_code}")
            if resp.status_code != 200:
                logger.error(f"검색 API 응답: {resp.text[:500]}")
                return []

            result = resp.json()
            data = result.get("data", {})
            product_list = data.get("productData", [])

            products = []
            for item in product_list[:limit]:
                p = Product(
                    url=item.get("productUrl", ""),
                    title=item.get("productName", ""),
                    price=f"{item.get('productPrice', 0):,}원",
                    image_urls=[item.get("productImage", "")] if item.get("productImage") else [],
                    description=item.get("productName", ""),
                    affiliate_link=item.get("productUrl", ""),  # 검색 결과 URL이 이미 제휴 링크
                    scraped_at=datetime.now(),
                )
                products.append(p)

            logger.info(f"검색 결과: {len(products)}개 상품")
            return products

        except Exception as e:
            logger.error(f"상품 검색 실패: {e}")
            return []

    # ──────────────────────────────────────────────
    # 네이버 쇼핑에서 상품 정보 검색 (쿠팡 스크래핑 우회)
    # ──────────────────────────────────────────────

    def _search_naver_shopping(self, coupang_url: str) -> Optional[Product]:
        """쿠팡 URL에서 상품 ID를 추출하여 네이버 쇼핑에서 검색한다.

        쿠팡 직접 스크래핑이 불가능할 때 대안.
        URL 패턴에서 상품명 힌트를 추출하여 네이버 쇼핑 검색.

        Args:
            coupang_url: 쿠팡 상품 URL

        Returns:
            Product 객체 또는 None
        """
        try:
            # URL에서 product ID 추출
            prod_match = re.search(r'/products/(\d+)', coupang_url)
            product_id = prod_match.group(1) if prod_match else ""

            if not product_id:
                return None

            # 네이버 쇼핑 검색 — 쿠팡 상품 ID로 직접 검색
            search_url = f"https://search.shopping.naver.com/search/all?query=coupang+{product_id}"
            headers = {
                "User-Agent": _USER_AGENT,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "ko-KR,ko;q=0.9",
            }

            resp = self._session.get(search_url, headers=headers, timeout=10)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                # 네이버 쇼핑 결과에서 첫 번째 상품 정보
                title_el = soup.select_one(".basicList_title__VfX3c a") or soup.select_one(".product_title__Mmw2K a")
                if title_el:
                    title = title_el.get_text(strip=True)
                    if title:
                        logger.info(f"네이버 쇼핑에서 상품 발견: {title[:40]}")
                        return Product(
                            url=coupang_url,
                            title=title,
                            description=f"{title} - 쿠팡 최저가 상품",
                            scraped_at=datetime.now(),
                        )

            return None
        except Exception as e:
            logger.warning(f"네이버 쇼핑 검색 에러: {e}")
            return None

    # ──────────────────────────────────────────────
    # Playwright 브라우저 기반 스크래핑 (403 우회)
    # ──────────────────────────────────────────────

    def scrape_product_playwright(self, url: str) -> Product:
        """Playwright 브라우저로 쿠팡 상품 페이지를 스크래핑한다.

        모바일 사이트(m.coupang.com) + stealth 기법으로 봇 탐지 우회.
        JSON-LD, Open Graph, CSS 셀렉터 순서로 추출.

        Args:
            url: 쿠팡 상품 URL

        Returns:
            상품 정보가 채워진 Product 객체
        """
        logger.info(f"Playwright 스크래핑 시작: {url}")

        # URL을 모바일 버전으로 변환 (m.coupang.com — 봇 탐지 약함)
        mobile_url = url.replace("www.coupang.com", "m.coupang.com")

        _MOBILE_UA = (
            "Mozilla/5.0 (Linux; Android 14; SM-S918B) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.6367.82 Mobile Safari/537.36"
        )

        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-blink-features=AutomationControlled",
                        "--disable-features=IsolateOrigins,site-per-process",
                    ],
                )
                context = browser.new_context(
                    user_agent=_MOBILE_UA,
                    viewport={"width": 412, "height": 915},
                    locale="ko-KR",
                    is_mobile=True,
                    has_touch=True,
                )
                page = context.new_page()

                # Stealth: webdriver 속성 제거 + Chrome 관련 속성 위장
                page.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                    Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
                    Object.defineProperty(navigator, 'languages', { get: () => ['ko-KR', 'ko', 'en'] });
                    window.chrome = { runtime: {} };
                """)

                # 모바일 쿠팡 메인 방문 (쿠키 획득)
                try:
                    page.goto("https://m.coupang.com", wait_until="domcontentloaded", timeout=15000)
                    page.wait_for_timeout(1500)
                except Exception:
                    pass

                # 상품 페이지 방문
                resp = page.goto(mobile_url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(3000)  # JS 렌더링 + 상품 정보 로딩 대기

                # Access Denied 체크 — PC 버전으로 재시도
                page_title = page.title()
                if "Access Denied" in page_title or "denied" in page_title.lower():
                    logger.warning("모바일 쿠팡도 차단 — PC 버전 재시도")
                    page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    page.wait_for_timeout(3000)

                html_content = page.content()
                browser.close()

            # BeautifulSoup으로 파싱 (기존 로직 재사용)
            soup = BeautifulSoup(html_content, "html.parser")

            title = ""
            price = ""
            description = ""
            image_urls: list[str] = []

            # 1) JSON-LD 추출
            for script in soup.find_all("script", type="application/ld+json"):
                try:
                    data = json.loads(script.string or "")
                    items = data if isinstance(data, list) else [data]
                    for item in items:
                        if item.get("@type") in ("Product", "product"):
                            title = title or item.get("name", "")
                            description = description or item.get("description", "")
                            img = item.get("image", "")
                            if isinstance(img, str) and img:
                                image_urls.append(img)
                            elif isinstance(img, list):
                                image_urls.extend([i for i in img if isinstance(i, str)])
                            offers = item.get("offers", {})
                            if isinstance(offers, list):
                                offers = offers[0] if offers else {}
                            p = offers.get("price", "")
                            if p:
                                price = price or f"{int(float(p)):,}원"
                except (json.JSONDecodeError, ValueError, TypeError):
                    continue

            # 2) Open Graph
            if not title:
                og = soup.find("meta", property="og:title")
                if og and og.get("content"):
                    title = og["content"].strip()
            if not description:
                og = soup.find("meta", property="og:description")
                if og and og.get("content"):
                    description = og["content"].strip()
            if not image_urls:
                og = soup.find("meta", property="og:image")
                if og and og.get("content"):
                    image_urls.append(og["content"])
            if not price:
                pm = soup.find("meta", property="product:price:amount")
                if pm and pm.get("content"):
                    try:
                        price = f"{int(float(pm['content'])):,}원"
                    except ValueError:
                        pass

            # 3) CSS 셀렉터 폴백
            if not title:
                for sel in ["h2.prod-buy-header__title", "h1.prod-buy-header__title",
                            ".prod-buy-header__title", "title"]:
                    el = soup.select_one(sel)
                    if el and el.get_text(strip=True):
                        title = el.get_text(strip=True)
                        title = re.sub(r'\s*[-|]\s*쿠팡[!]?\s*$', '', title)
                        break
            if not price:
                for sel in [".total-price strong", "span.total-price",
                            ".prod-sale-price", ".prod-coupon-price .total-price"]:
                    el = soup.select_one(sel)
                    if el and el.get_text(strip=True):
                        raw_price = el.get_text(strip=True)
                        digits = re.sub(r'[^\d]', '', raw_price)
                        if digits:
                            price = f"{int(digits):,}원"
                        break
            if not image_urls:
                for img in soup.select(".prod-image__item img, .prod-image img"):
                    src = img.get("src") or img.get("data-img-src", "")
                    if src and src.startswith("http"):
                        image_urls.append(src)
                    if len(image_urls) >= 5:
                        break
            if not description:
                meta_desc = soup.find("meta", attrs={"name": "description"})
                if meta_desc and meta_desc.get("content"):
                    description = meta_desc["content"].strip()

            product = Product(
                url=url,
                title=title,
                price=price,
                image_urls=image_urls[:10],
                description=description[:2000],
                scraped_at=datetime.now(),
            )

            logger.info(
                f"Playwright 스크래핑 완료: title='{title[:40]}', "
                f"price={price}, images={len(product.image_urls)}개"
            )
            return product

        except ImportError:
            logger.error("Playwright 미설치 — pip install playwright && playwright install chromium")
            raise
        except Exception as e:
            logger.error(f"Playwright 스크래핑 실패: {e}")
            raise

    # ──────────────────────────────────────────────
    # 통합 메서드
    # ──────────────────────────────────────────────

    def scrape_and_link(self, url: str) -> Product:
        """상품 스크래핑 + 제휴 링크 생성을 한 번에 수행한다.

        우선순위: requests → Playwright → 검색 API → 폴백
        웹 스크래핑이 차단되면 Playwright 브라우저 또는 API로 폴백한다.

        Args:
            url: 쿠팡 상품 URL

        Returns:
            제휴 링크가 포함된 완성된 Product 객체
        """
        product = None

        # 1차: requests 스크래핑 시도
        try:
            product = self.scrape_product(url)
            if product and product.title:
                logger.info(f"requests 스크래핑 성공: {product.title}")
        except Exception as e:
            logger.warning(f"requests 스크래핑 실패: {e}")
            product = None

        # 2차: Playwright 브라우저 스크래핑 (403 우회)
        if not product or not product.title:
            logger.info("requests 실패 → Playwright 브라우저 스크래핑 시도")
            try:
                product = self.scrape_product_playwright(url)
                if product and product.title:
                    logger.info(f"Playwright 스크래핑 성공: {product.title}")
            except Exception as e:
                logger.warning(f"Playwright 스크래핑 실패: {e}")
                product = None

        # 3차: 네이버 쇼핑에서 URL의 상품 ID로 검색
        if not product or not product.title or product.title in ("Access Denied", ""):
            logger.info("스크래핑 전부 실패 → 네이버 쇼핑 검색 시도")
            try:
                product = self._search_naver_shopping(url)
            except Exception as e:
                logger.warning(f"네이버 쇼핑 검색 실패: {e}")
                product = None

        # 4차: 검색 API 폴백
        if not product or not product.title or product.title in ("Access Denied", "쿠팡 상품"):
            logger.info("전부 실패 → 상품 검색 API 폴백")
            search_results = self.search_products("인기상품", limit=1)
            if search_results:
                product = search_results[0]
                product.url = url
            else:
                # 최소한의 Product 반환
                product = Product(url=url, title="쿠팡 상품", scraped_at=datetime.now())

        # 제휴 링크 생성
        if not product.affiliate_link:
            try:
                affiliate_link = self.generate_affiliate_link(url)
                product.affiliate_link = affiliate_link
            except Exception as e:
                logger.warning(f"제휴 링크 생성 실패 (스크래핑 데이터는 유지): {e}")

        return product
