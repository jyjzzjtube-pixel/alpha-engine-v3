# -*- coding: utf-8 -*-
"""네이버 블로그 위젯 등록 - 이미지맵 네비게이션"""
import sys, time, os
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

SS_DIR = r"C:\Users\jyjzz\OneDrive\바탕 화면\franchise-db\affiliate_system\renders\blog_widgets"
BLOG_ID = "jyjzzj"

from dotenv import load_dotenv
load_dotenv(r"C:\Users\jyjzz\OneDrive\바탕 화면\franchise-db\.env", override=True)

def send_tg(msg=None, photo=None, caption=None):
    import requests as req
    t = os.getenv('TELEGRAM_BOT_TOKEN')
    c = os.getenv('TELEGRAM_CHAT_ID')
    b = f'https://api.telegram.org/bot{t}'
    try:
        if msg:
            req.post(f'{b}/sendMessage', data={'chat_id': c, 'text': msg})
        if photo and os.path.exists(photo):
            with open(photo, 'rb') as f:
                req.post(f'{b}/sendPhoto', data={'chat_id': c, 'caption': caption or ''},
                         files={'photo': (os.path.basename(photo), f, 'image/png')})
    except:
        pass

print("=== 블로그 위젯 등록 ===")

# Selenium 연결
opts = Options()
opts.add_experimental_option("debuggerAddress", "127.0.0.1:9222")
driver = webdriver.Chrome(options=opts)
print(f"Selenium 연결! URL: {driver.current_url}")

try:
    # ── [1] WidgetSetting 페이지 접근 ──
    print("\n[1] WidgetSetting 페이지 탐색...")

    # 여러 가능한 URL 시도
    widget_urls = [
        f"https://admin.blog.naver.com/WidgetSetting.naver?blogId={BLOG_ID}",
        f"https://admin.blog.naver.com/{BLOG_ID}/manage/widget",
        f"https://admin.blog.naver.com/BlogWidgetSetting.naver?blogId={BLOG_ID}",
    ]

    working_url = None
    for url in widget_urls:
        driver.get(url)
        time.sleep(5)
        src = driver.page_source[:2000]
        title = driver.title
        cur_url = driver.current_url
        has_error = '유효하지 않은' in src or '페이지 주소' in src or '에러' in src
        print(f"  {'❌' if has_error else '✅'} {url.split('/')[-1][:40]} → {cur_url[:60]} [{title[:30]}]")

        if not has_error and 'error' not in title.lower():
            working_url = url
            driver.save_screenshot(os.path.join(SS_DIR, "widget_page.png"))

            # 페이지 구조 파악
            inputs = driver.find_elements(By.CSS_SELECTOR, "input, textarea, select")
            print(f"  입력 필드: {len(inputs)}개")
            for inp in inputs:
                itype = inp.get_attribute('type') or ''
                iname = inp.get_attribute('name') or ''
                iid = inp.get_attribute('id') or ''
                ival = (inp.get_attribute('value') or '')[:50]
                if iname or iid:
                    print(f"    {itype}: name={iname}, id={iid}, val={ival[:30]}")

            # 외부 위젯 관련 요소 찾기
            widget_els = driver.find_elements(By.CSS_SELECTOR,
                "[id*='widget'], [class*='widget'], [id*='Widget'], [class*='Widget']")
            print(f"  위젯 요소: {len(widget_els)}개")
            for el in widget_els[:20]:
                eid = el.get_attribute('id') or ''
                ecls = el.get_attribute('class') or ''
                etag = el.tag_name
                etxt = el.text.strip()[:40] if el.text else ''
                if eid or etxt:
                    print(f"    <{etag}> id={eid[:30]} class={ecls[:30]} text={etxt}")
            break

    if not working_url:
        print("\n  직접 URL 접근 실패. Remocon에서 위젯 메뉴 클릭...")

        # Remocon 페이지로 이동
        driver.get(f"https://admin.blog.naver.com/Remocon.naver?blogId={BLOG_ID}&Redirect=Remocon")
        time.sleep(8)

        # 위젯 메뉴 클릭 시도
        widget_menu = None
        try:
            widget_menu = driver.find_element(By.ID, "list_menu10")
            print(f"  위젯 메뉴: {widget_menu.text}")
            driver.execute_script("arguments[0].click();", widget_menu)
            time.sleep(3)
            driver.save_screenshot(os.path.join(SS_DIR, "widget_menu_click.png"))
        except Exception as e:
            print(f"  위젯 메뉴 클릭 실패: {e}")

        # 위젯 페이지 이동 확인 다이얼로그 처리
        try:
            go_widget = driver.find_element(By.CSS_SELECTOR, "#go_widget_confirm_layer a._goLayoutWidgetPage")
            if go_widget:
                print(f"  위젯 페이지 이동 버튼 발견")
                driver.execute_script("arguments[0].click();", go_widget)
                time.sleep(5)
                print(f"  이동 후 URL: {driver.current_url}")
                driver.save_screenshot(os.path.join(SS_DIR, "widget_page_from_remocon.png"))
                working_url = driver.current_url
        except Exception as e:
            print(f"  이동 버튼 처리 실패: {e}")

        # JavaScript로 위젯 페이지 URL 찾기
        if not working_url:
            try:
                js_url = driver.execute_script("""
                    // RemoconBottom에서 위젯 페이지 URL 찾기
                    if (typeof gBlogID !== 'undefined') {
                        return 'https://admin.blog.naver.com/WidgetSetting.naver?blogId=' + gBlogID;
                    }
                    return null;
                """)
                if js_url:
                    print(f"  JS URL: {js_url}")
            except:
                pass

    # ── [2] 위젯 등록 시도 ──
    print(f"\n[2] 현재 URL: {driver.current_url}")

    # 위젯 페이지에서 외부 위젯 추가 찾기
    # 방법 A: addExternalWidget 버튼 찾기
    add_btns = driver.find_elements(By.CSS_SELECTOR,
        "[id*='addExternal'], [class*='addExternal'], [id*='add_widget'], [class*='add_widget']")
    print(f"  추가 버튼: {len(add_btns)}개")
    for btn in add_btns:
        print(f"    {btn.tag_name} id={btn.get_attribute('id')} text={btn.text[:30]}")

    # 방법 B: 외부 위젯 입력 필드 찾기
    widget_inputs = driver.find_elements(By.CSS_SELECTOR,
        "[id='_widgetName'], [id='_widgetCode'], [id='_widgetHeight']")
    print(f"  위젯 입력 필드: {len(widget_inputs)}개")
    for wi in widget_inputs:
        print(f"    id={wi.get_attribute('id')}, name={wi.get_attribute('name')}")

    # 현재 페이지 소스 저장
    with open(os.path.join(SS_DIR, "widget_source.html"), 'w', encoding='utf-8') as f:
        f.write(driver.page_source[:200000])

    driver.save_screenshot(os.path.join(SS_DIR, "widget_final.png"))
    send_tg(photo=os.path.join(SS_DIR, "widget_final.png"), caption="위젯 페이지 상태")

    # ── [3] 페이지 구조 분석 ──
    print("\n[3] 전체 페이지 분석...")
    page_src = driver.page_source

    # 중요 키워드 찾기
    keywords = ['외부위젯', '위젯 추가', 'addWidget', 'externalWidget', '_widgetName',
                '_widgetCode', 'widgetHeight', 'widget_add', 'btn_add']
    for kw in keywords:
        if kw in page_src:
            idx = page_src.index(kw)
            context = page_src[max(0,idx-100):idx+200]
            print(f"  ★ '{kw}' found: ...{context[:100]}...")

    print("\n✅ 위젯 탐색 완료!")

except Exception as e:
    print(f"\n❌ 오류: {e}")
    import traceback
    traceback.print_exc()
    try:
        driver.save_screenshot(os.path.join(SS_DIR, "widget_error.png"))
        send_tg(msg=f"❌ 위젯 오류: {str(e)[:200]}")
    except:
        pass

finally:
    print("스크립트 종료")
