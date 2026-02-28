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

    def generate_simple_link(self, keyword: str) -> str:
        """쿠팡 간편 링크 생성 — 검색 결과 페이지를 어필리에이트 링크로 변환

        직접 상품 URL 대신 검색 URL 사용:
        - 품절 리스크 없음 (검색 결과에서 아무 상품이나 구매해도 수수료 발생)
        - 24시간 쿠키로 수수료 범위 넓음
        - 4탄 핵심 전략: 쿠팡 간편 링크 = 검색 페이지 연결

        Args:
            keyword: 상품 검색 키워드 (예: "일회용 후드 그릴")

        Returns:
            제휴 추적 단축 URL 또는 빈 문자열
        """
        import urllib.parse
        # 쿠팡 검색 URL 생성
        encoded_keyword = urllib.parse.quote(keyword)
        search_url = f"https://www.coupang.com/np/search?component=&q={encoded_keyword}&channel=user"
        logger.info(f"쿠팡 간편 링크 생성: '{keyword}' → {search_url[:80]}...")
        return self.generate_affiliate_link(search_url)

    # ──────────────────────────────────────────────
    # Coupang Partners 상품 검색 API + 웹 스크래핑 폴백
    # ──────────────────────────────────────────────

    def search_products(self, keyword: str, limit: int = 5) -> list[Product]:
        """쿠팡 상품을 검색한다. API 우선 → 다나와 → 쿠팡 스크래핑 → 네이버 쇼핑 폴백.

        Args:
            keyword: 검색 키워드
            limit: 결과 수 (기본 5)

        Returns:
            Product 리스트
        """
        # 1차: Coupang Partners API
        if COUPANG_ACCESS_KEY and COUPANG_SECRET_KEY:
            products = self._search_via_api(keyword, limit)
            if products:
                return products
            logger.warning("API 검색 실패 → 다나와 검색으로 폴백")

        # 2차: 다나와 검색 (curl_cffi — 가장 안정적)
        products = self._search_via_danawa(keyword, limit)
        if products:
            return products

        # 3차: 쿠팡 Playwright 스크래핑
        logger.info("다나와도 실패 → 쿠팡 Playwright 검색 시도")
        products = self._search_via_scraping(keyword, limit)
        if products:
            return products

        # 4차: 네이버 쇼핑 검색 폴백
        logger.info("전부 실패 → 네이버 쇼핑 검색 시도")
        products = self._search_via_naver(keyword, limit)
        return products

    def _search_via_api(self, keyword: str, limit: int) -> list[Product]:
        """Coupang Partners 검색 API (기존 방식)"""
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
                    affiliate_link=item.get("productUrl", ""),
                    scraped_at=datetime.now(),
                )
                products.append(p)

            logger.info(f"API 검색 결과: {len(products)}개 상품")
            return products

        except Exception as e:
            logger.error(f"API 상품 검색 실패: {e}")
            return []

    def _search_via_danawa(self, keyword: str, limit: int) -> list[Product]:
        """다나와 가격비교 사이트에서 상품을 검색한다. (curl_cffi — Akamai 우회)

        다나와는 한국 최대 가격비교 사이트로, 쿠팡 포함 다양한 쇼핑몰의 상품을 보여줌.
        curl_cffi를 사용하여 TLS 핑거프린트를 Chrome으로 위장.
        """
        import urllib.parse
        encoded = urllib.parse.quote(keyword)
        # 인기순(saveCnt) 정렬
        search_url = f"https://search.danawa.com/dsearch.php?query={encoded}&tab=goods&sort=saveCnt"
        logger.info(f"다나와 검색: '{keyword}'")

        try:
            from curl_cffi import requests as cf_requests
        except ImportError:
            logger.warning("curl_cffi 미설치 — 다나와 검색 건너뜀")
            return []

        try:
            session = cf_requests.Session(impersonate="chrome131")
            resp = session.get(search_url, timeout=20)

            if resp.status_code != 200 or len(resp.text) < 5000:
                logger.warning(f"다나와 검색 HTTP {resp.status_code}, len={len(resp.text)}")
                return []

            soup = BeautifulSoup(resp.text, "html.parser")
            items = soup.select(".prod_main_info")
            logger.info(f"다나와 검색 HTML 아이템: {len(items)}개")

            products = []
            for item in items[:limit]:
                try:
                    # 상품명
                    name_el = item.select_one(".prod_name a, .prod_info .prod_name p a")
                    title = name_el.get_text(strip=True) if name_el else ""

                    # 가격
                    price_el = item.select_one(".price_sect, .price_wrap .price em")
                    price_text = ""
                    if price_el:
                        digits = re.sub(r'[^\d]', '', price_el.get_text(strip=True))
                        if digits:
                            price_text = f"{int(digits):,}원"

                    # 이미지 — 부모 요소에서 찾기
                    parent_li = item.parent
                    img_el = None
                    if parent_li:
                        img_el = parent_li.select_one("img.thumb_image, img[class*='thumb']")
                        if not img_el:
                            img_el = parent_li.select_one("img")
                    img_url = ""
                    if img_el:
                        img_url = (
                            img_el.get("data-original") or img_el.get("data-src") or
                            img_el.get("src") or ""
                        )
                        if img_url and not img_url.startswith("http"):
                            img_url = "https:" + img_url if img_url.startswith("//") else ""

                    # 다나와 상품 URL → 쿠팡 검색 URL로 변환 (제휴 링크 생성용)
                    link_el = name_el if name_el else item.select_one("a[href]")
                    danawa_url = link_el.get("href", "") if link_el else ""

                    # 쿠팡 검색 URL 생성 (간편 링크용)
                    coupang_search = f"https://www.coupang.com/np/search?q={urllib.parse.quote(title)}&channel=user"

                    if not title:
                        continue

                    products.append(Product(
                        url=danawa_url,
                        title=title,
                        price=price_text or "가격 확인 필요",
                        image_urls=[img_url] if img_url else [],
                        description=title,
                        affiliate_link=coupang_search,  # 쿠팡 검색 URL (간편 링크 변환 가능)
                        scraped_at=datetime.now(),
                    ))

                except Exception as e:
                    logger.debug(f"다나와 상품 파싱 에러: {e}")
                    continue

            logger.info(f"다나와 검색 결과: {len(products)}개 상품")
            return products

        except Exception as e:
            logger.error(f"다나와 검색 실패: {e}")
            return []

    def _search_via_scraping(self, keyword: str, limit: int) -> list[Product]:
        """Playwright 브라우저로 쿠팡 검색 페이지를 스크래핑한다. (API 불필요, 403 우회)"""
        import urllib.parse
        encoded = urllib.parse.quote(keyword)
        logger.info(f"쿠팡 Playwright 검색: '{keyword}'")

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.warning("Playwright 미설치 — requests 폴백 시도")
            return self._search_via_requests(keyword, limit)

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-blink-features=AutomationControlled",
                        "--disable-features=IsolateOrigins,site-per-process",
                    ],
                )
                # 모바일 컨텍스트 (봇 탐지 약함)
                _MOBILE_UA = (
                    "Mozilla/5.0 (Linux; Android 14; SM-S918B) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.6367.82 Mobile Safari/537.36"
                )
                context = browser.new_context(
                    user_agent=_MOBILE_UA,
                    viewport={"width": 412, "height": 915},
                    locale="ko-KR",
                    is_mobile=True,
                    has_touch=True,
                )
                page = context.new_page()

                # Stealth
                page.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                    Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
                    Object.defineProperty(navigator, 'languages', { get: () => ['ko-KR', 'ko', 'en'] });
                    window.chrome = { runtime: {} };
                """)

                # 쿠팡 메인 방문 (쿠키 획득)
                try:
                    page.goto("https://m.coupang.com", wait_until="domcontentloaded", timeout=15000)
                    page.wait_for_timeout(1500)
                except Exception:
                    pass

                # 검색 페이지
                search_url = f"https://m.coupang.com/nm/search?q={encoded}"
                page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(3000)  # JS 렌더링 대기

                html = page.content()
                browser.close()

            soup = BeautifulSoup(html, "html.parser")
            products = []

            # 모바일 쿠팡 검색결과 파싱 — 여러 셀렉터 시도
            items = soup.select("li.search-product")
            if not items:
                items = soup.select("ul.search-product-list > li")
            if not items:
                items = soup.select("[class*='search-product']")
            if not items:
                # 더 넓은 셀렉터
                items = soup.select("li[class*='product'], article[class*='product']")

            logger.info(f"Playwright 검색 HTML 아이템: {len(items)}개")

            for item in items[:limit]:
                try:
                    # 상품명
                    title_el = (
                        item.select_one("div.name, .name, .product-title, .title") or
                        item.select_one("[class*='name'], [class*='title']")
                    )
                    title = title_el.get_text(strip=True) if title_el else ""

                    # 가격
                    price_el = (
                        item.select_one("strong.price-value, .price-value") or
                        item.select_one("[class*='price'] strong, [class*='price'] em") or
                        item.select_one("[class*='price-value'], [class*='sale-price']")
                    )
                    price_text = ""
                    if price_el:
                        digits = re.sub(r'[^\d]', '', price_el.get_text(strip=True))
                        if digits:
                            price_text = f"{int(digits):,}원"

                    # 이미지
                    img_el = item.select_one("img")
                    img_url = ""
                    if img_el:
                        img_url = (
                            img_el.get("src") or img_el.get("data-img-src") or
                            img_el.get("data-lazy-src") or ""
                        )
                        if img_url and not img_url.startswith("http"):
                            img_url = "https:" + img_url if img_url.startswith("//") else ""

                    # 상품 URL
                    link_el = item.select_one("a[href*='/products/'], a[href*='/vp/'], a[href]")
                    product_url = ""
                    if link_el:
                        href = link_el.get("href", "")
                        if href.startswith("/"):
                            product_url = "https://www.coupang.com" + href
                        elif href.startswith("http"):
                            product_url = href

                    if not title:
                        continue

                    products.append(Product(
                        url=product_url,
                        title=title,
                        price=price_text or "가격 확인 필요",
                        image_urls=[img_url] if img_url else [],
                        description=title,
                        affiliate_link=product_url,
                        scraped_at=datetime.now(),
                    ))

                except Exception as e:
                    logger.debug(f"상품 파싱 에러 (건너뜀): {e}")
                    continue

            logger.info(f"Playwright 검색 결과: {len(products)}개 상품")
            return products

        except Exception as e:
            logger.error(f"Playwright 검색 실패: {e}")
            return self._search_via_requests(keyword, limit)

    def _search_via_requests(self, keyword: str, limit: int) -> list[Product]:
        """requests로 쿠팡 검색 (Playwright 없을 때 폴백)"""
        import urllib.parse
        encoded = urllib.parse.quote(keyword)
        search_url = f"https://www.coupang.com/np/search?component=&q={encoded}&channel=user"
        logger.info(f"쿠팡 requests 검색: '{keyword}'")

        try:
            try:
                self._session.get("https://www.coupang.com", timeout=8, allow_redirects=True)
                time.sleep(0.3)
            except Exception:
                pass

            headers = {"Referer": "https://www.coupang.com/"}
            resp = self._session.get(search_url, timeout=_REQUEST_TIMEOUT,
                                      headers=headers, allow_redirects=True)

            if resp.status_code != 200:
                logger.warning(f"쿠팡 검색 HTTP {resp.status_code}")
                return []

            soup = BeautifulSoup(resp.text, "html.parser")
            products = []
            items = soup.select("li.search-product, [class*='search-product']")

            for item in items[:limit]:
                try:
                    title_el = item.select_one("div.name, .name, [class*='name']")
                    title = title_el.get_text(strip=True) if title_el else ""
                    price_el = item.select_one("strong.price-value, [class*='price'] strong")
                    price_text = ""
                    if price_el:
                        digits = re.sub(r'[^\d]', '', price_el.get_text(strip=True))
                        if digits:
                            price_text = f"{int(digits):,}원"
                    img_el = item.select_one("img")
                    img_url = ""
                    if img_el:
                        img_url = img_el.get("src") or img_el.get("data-img-src") or ""
                        if img_url and not img_url.startswith("http"):
                            img_url = "https:" + img_url if img_url.startswith("//") else ""
                    link_el = item.select_one("a[href]")
                    product_url = ""
                    if link_el:
                        href = link_el.get("href", "")
                        if href.startswith("/"):
                            product_url = "https://www.coupang.com" + href
                        elif href.startswith("http"):
                            product_url = href
                    if title:
                        products.append(Product(
                            url=product_url, title=title, price=price_text or "가격 확인 필요",
                            image_urls=[img_url] if img_url else [], description=title,
                            affiliate_link=product_url, scraped_at=datetime.now(),
                        ))
                except Exception:
                    continue

            return products
        except Exception as e:
            logger.error(f"requests 검색 실패: {e}")
            return []

    def _search_via_naver(self, keyword: str, limit: int) -> list[Product]:
        """네이버 쇼핑 Playwright 검색 (최종 폴백)"""
        import urllib.parse
        encoded = urllib.parse.quote(keyword)
        search_url = f"https://search.shopping.naver.com/search/all?query={encoded}"
        logger.info(f"네이버 쇼핑 Playwright 검색: '{keyword}'")

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.warning("Playwright 미설치 — 네이버 쇼핑 검색 불가")
            return []

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
                )
                context = browser.new_context(
                    user_agent=_USER_AGENT,
                    viewport={"width": 1280, "height": 800},
                    locale="ko-KR",
                )
                page = context.new_page()
                page.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                """)

                page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(3000)

                html = page.content()
                browser.close()

            soup = BeautifulSoup(html, "html.parser")
            products = []

            # __NEXT_DATA__ JSON 파싱
            script_el = soup.find("script", id="__NEXT_DATA__")
            if script_el and script_el.string:
                try:
                    next_data = json.loads(script_el.string)
                    props = next_data.get("props", {}).get("pageProps", {})
                    initial = props.get("initialState", {})
                    prod_list = initial.get("products", {}).get("list", [])

                    for item in prod_list[:limit]:
                        item_data = item.get("item", {})
                        title = item_data.get("productTitle", "").replace("<b>", "").replace("</b>", "")
                        price_val = item_data.get("price", 0)
                        price_str = f"{int(price_val):,}원" if price_val else "가격 미정"
                        img = item_data.get("imageUrl", "")
                        mall = item_data.get("mallName", "")
                        prod_url = item_data.get("mallProductUrl", "") or item_data.get("crUrl", "")

                        is_coupang = "coupang" in mall.lower() or "쿠팡" in mall
                        if title:
                            products.append(Product(
                                url=prod_url,
                                title=f"{'[쿠팡] ' if is_coupang else ''}{title}",
                                price=price_str,
                                image_urls=[img] if img else [],
                                description=f"{title} - {mall}" if mall else title,
                                affiliate_link="",
                                scraped_at=datetime.now(),
                            ))
                except (json.JSONDecodeError, KeyError, TypeError) as e:
                    logger.debug(f"네이버 JSON 파싱 에러: {e}")

            # HTML 폴백
            if not products:
                items = soup.select("[class*='product_item'], [class*='basicList_item']")
                for item in items[:limit]:
                    title_el = item.select_one("[class*='title'] a, [class*='name'] a")
                    price_el = item.select_one("[class*='price'] em, [class*='price'] span")
                    img_el = item.select_one("img")
                    title = title_el.get_text(strip=True) if title_el else ""
                    price_text = ""
                    if price_el:
                        digits = re.sub(r'[^\d]', '', price_el.get_text(strip=True))
                        if digits:
                            price_text = f"{int(digits):,}원"
                    img_url = img_el.get("src", "") if img_el else ""
                    if title:
                        products.append(Product(
                            url="", title=title, price=price_text or "가격 미정",
                            image_urls=[img_url] if img_url else [],
                            description=title, scraped_at=datetime.now(),
                        ))

            logger.info(f"네이버 쇼핑 검색 결과: {len(products)}개 상품")
            return products

        except Exception as e:
            logger.error(f"네이버 쇼핑 Playwright 검색 실패: {e}")
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
