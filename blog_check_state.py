# -*- coding: utf-8 -*-
"""블로그 현재 상태 확인"""
import sys, time, os
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

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

print("=== 블로그 상태 확인 ===")

opts = Options()
opts.add_experimental_option("debuggerAddress", "127.0.0.1:9222")
driver = webdriver.Chrome(options=opts)

try:
    # 블로그 페이지
    driver.get(f"https://blog.naver.com/{BLOG_ID}")
    time.sleep(5)
    driver.save_screenshot(os.path.join(SS_DIR, "blog_current_state.png"))
    send_tg(photo=os.path.join(SS_DIR, "blog_current_state.png"), caption="현재 블로그 상태")

    print(f"URL: {driver.current_url}")

    # mainFrame에서 타이틀 정보 확인
    iframes = driver.find_elements(By.TAG_NAME, "iframe")
    for iframe in iframes:
        fid = iframe.get_attribute('id') or ''
        if fid == 'mainFrame':
            driver.switch_to.frame(iframe)

            # 타이틀 영역
            try:
                title_el = driver.find_element(By.ID, "blog-title")
                bg = title_el.value_of_css_property("background-image")
                h = title_el.value_of_css_property("height")
                w = title_el.value_of_css_property("width")
                print(f"\n타이틀 영역:")
                print(f"  배경: {bg[:100]}")
                print(f"  크기: {w} x {h}")

                # 타이틀 텍스트
                try:
                    title_text = driver.find_element(By.ID, "blogTitleName")
                    print(f"  텍스트: {title_text.text}")
                    print(f"  텍스트 display: {title_text.value_of_css_property('display')}")
                except:
                    pass

            except Exception as e:
                print(f"  타이틀 오류: {e}")

            # wrapper 너비
            try:
                wrapper = driver.find_element(By.ID, "wrapper")
                print(f"\n래퍼:")
                print(f"  너비: {wrapper.value_of_css_property('width')}")
            except:
                pass

            # content-area
            try:
                content = driver.find_element(By.ID, "content-area")
                print(f"\n컨텐츠 영역:")
                print(f"  너비: {content.value_of_css_property('width')}")
            except:
                pass

            # 사이드바
            try:
                sidebar = driver.find_element(By.ID, "top-tight-area")
                print(f"\n사이드바:")
                print(f"  너비: {sidebar.value_of_css_property('width')}")

                # 외부 위젯 확인
                ext_widgets = driver.find_elements(By.CSS_SELECTOR, "[id^='externalwidget']")
                print(f"  외부 위젯: {len(ext_widgets)}개")
                for ew in ext_widgets:
                    eid = ew.get_attribute('id')
                    eh = ew.value_of_css_property('height')
                    ed = ew.value_of_css_property('display')
                    print(f"    {eid}: h={eh}, display={ed}")
            except:
                pass

            # 블로그 메뉴
            try:
                menu = driver.find_element(By.ID, "blog-menu")
                menu_links = menu.find_elements(By.TAG_NAME, "a")
                print(f"\n블로그 메뉴:")
                for ml in menu_links:
                    txt = ml.text.strip()
                    href = ml.get_attribute('href') or ''
                    if txt:
                        print(f"  {txt} → {href[:60]}")
            except:
                pass

            # 레이아웃 타입 확인
            layout_info = driver.execute_script("""
                var body = document.getElementById('body');
                var wrapper = document.getElementById('wrapper');
                var sidebar = document.getElementById('top-tight-area');
                var twocols = document.getElementById('twocols');
                return {
                    bodyWidth: body ? body.offsetWidth : 0,
                    wrapperWidth: wrapper ? wrapper.offsetWidth : 0,
                    sidebarWidth: sidebar ? sidebar.offsetWidth : 0,
                    twocolsWidth: twocols ? twocols.offsetWidth : 0,
                    sidebarExists: !!sidebar,
                    titleHeight: document.getElementById('blog-title') ? document.getElementById('blog-title').offsetHeight : 0,
                    titleWidth: document.getElementById('blog-title') ? document.getElementById('blog-title').offsetWidth : 0
                };
            """)
            print(f"\n레이아웃 정보: {layout_info}")

            driver.switch_to.default_content()
            break

    print("\n✅ 확인 완료!")

except Exception as e:
    print(f"\n❌ 오류: {e}")
    import traceback
    traceback.print_exc()

finally:
    print("스크립트 종료")
