# -*- coding: utf-8 -*-
"""네이버 블로그 외부 위젯 등록 - 이미지맵 네비게이션"""
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

print("=== 외부 위젯 등록 (이미지맵) ===")

# 위젯 HTML 코드 - 네이버 블로그 허용 태그만 사용
# 허용: <table>, <img>, <a>, <map>, <area>, <font>, <b>
# 타이틀 이미지(966x350) 위의 5개 아이콘 위치에 대한 이미지맵
# 아이콘 위치 (966px 기준, 5개 균등 배치):
# 1. 브릿지원 소개 (ABOUT): ~97px 중심, x: 25-170
# 2. 점포개발 리징 (LEASING): ~290px 중심, x: 218-362
# 3. 프랜차이즈 창업 (FRANCHISE): ~483px 중심, x: 411-555
# 4. 성공 포트폴리오 (PORTFOLIO): ~676px 중심, x: 604-748
# 5. 상담 및 의뢰 (CONTACT): ~869px 중심, x: 797-941

WIDGET_CODE = """<table border="0" cellpadding="0" cellspacing="0"><img src="https://blogfiles.pstatic.net/MjAyNjAyMjFfMjUy/MDAxNzQwMTI3NjAwMDAw.title_combined.jpg" width="966" height="350" usemap="#bridgemap" border="0"><map name="bridgemap"><area shape="rect" coords="25,180,170,340" href="https://blog.naver.com/PostList.naver?blogId=jyjzzj&from=postList&categoryNo=1" target="mainFrame" alt="브릿지원 소개"><area shape="rect" coords="218,180,362,340" href="https://blog.naver.com/PostList.naver?blogId=jyjzzj&from=postList&categoryNo=13" target="mainFrame" alt="점포개발 리징"><area shape="rect" coords="411,180,555,340" href="https://blog.naver.com/PostList.naver?blogId=jyjzzj&from=postList&categoryNo=9" target="mainFrame" alt="프랜차이즈 창업"><area shape="rect" coords="604,180,748,340" href="https://blog.naver.com/PostList.naver?blogId=jyjzzj&from=postList&categoryNo=10" target="mainFrame" alt="성공 포트폴리오"><area shape="rect" coords="797,180,941,340" href="https://blog.naver.com/PostList.naver?blogId=jyjzzj&from=postList&categoryNo=12" target="mainFrame" alt="상담 및 의뢰"></map></table>"""

WIDGET_NAME = "BRIDGE ONE 네비게이션"
WIDGET_HEIGHT = "350"

# Selenium 연결
opts = Options()
opts.add_experimental_option("debuggerAddress", "127.0.0.1:9222")
driver = webdriver.Chrome(options=opts)
print(f"Selenium OK! URL: {driver.current_url}")

try:
    # ── [1] LayoutSelect 페이지로 이동 ──
    print("\n[1] LayoutSelect 페이지...")
    layout_url = f"https://admin.blog.naver.com/LayoutSelect.naver?blogId={BLOG_ID}&layoutType=3&skinType=&skinId="
    driver.get(layout_url)
    time.sleep(8)
    print(f"  URL: {driver.current_url}")
    driver.save_screenshot(os.path.join(SS_DIR, "w1_layout.png"))

    # ── [2] addExternalWidget 클릭 ──
    print("\n[2] 외부 위젯 추가 버튼...")
    add_btn = driver.find_element(By.ID, "addExternalWidget")
    print(f"  버튼: {add_btn.text}, tag={add_btn.tag_name}")
    driver.execute_script("arguments[0].click();", add_btn)
    time.sleep(2)
    driver.save_screenshot(os.path.join(SS_DIR, "w2_add_click.png"))

    # ── [3] 위젯 이름 입력 ──
    print("\n[3] 위젯 정보 입력...")

    # 위젯 이름
    name_input = driver.find_element(By.CSS_SELECTOR, "._widgetName")
    name_input.clear()
    name_input.send_keys(WIDGET_NAME)
    print(f"  이름: {WIDGET_NAME}")

    # 위젯 코드
    code_input = driver.find_element(By.CSS_SELECTOR, "._widgetCode")
    code_input.clear()
    code_input.send_keys(WIDGET_CODE)
    print(f"  코드: {len(WIDGET_CODE)}자")

    # 위젯 높이
    height_input = driver.find_element(By.CSS_SELECTOR, "._widgetHeight")
    height_input.clear()
    height_input.send_keys(WIDGET_HEIGHT)
    print(f"  높이: {WIDGET_HEIGHT}px")

    time.sleep(1)
    driver.save_screenshot(os.path.join(SS_DIR, "w3_filled.png"))
    send_tg(photo=os.path.join(SS_DIR, "w3_filled.png"), caption="위젯 정보 입력 완료")

    # ── [4] 다음 버튼 ──
    print("\n[4] 다음 버튼 클릭...")
    next_btn = driver.find_element(By.CSS_SELECTOR, "._btnNext")
    print(f"  다음 버튼: {next_btn.text}, tag={next_btn.tag_name}")
    driver.execute_script("arguments[0].click();", next_btn)
    time.sleep(3)
    driver.save_screenshot(os.path.join(SS_DIR, "w4_next.png"))

    # 에러 메시지 확인
    try:
        error_msg = driver.execute_script("""
            var alerts = document.querySelectorAll('.alert, .error, [class*='error'], [class*='alert']');
            var result = [];
            alerts.forEach(function(el) {
                var txt = el.textContent.trim();
                var display = window.getComputedStyle(el).display;
                if (txt && display !== 'none') result.push(txt.substring(0, 100));
            });
            return result;
        """)
        if error_msg:
            print(f"  경고/에러: {error_msg}")
    except:
        pass

    # ── [5] 제출 버튼 ──
    print("\n[5] 제출 버튼 클릭...")
    submit_btns = driver.find_elements(By.CSS_SELECTOR, "._btnSubmit")
    print(f"  Submit 버튼: {len(submit_btns)}개")
    for i, btn in enumerate(submit_btns):
        txt = btn.text.strip()
        display = btn.value_of_css_property("display")
        visible = display != 'none'
        print(f"    [{i}] text='{txt}', display={display}, visible={visible}")
        if visible and txt:
            driver.execute_script("arguments[0].click();", btn)
            print(f"    ✅ 클릭!")
            time.sleep(3)
            break

    driver.save_screenshot(os.path.join(SS_DIR, "w5_submit.png"))
    send_tg(photo=os.path.join(SS_DIR, "w5_submit.png"), caption="위젯 제출 완료")

    # ── [6] 결과 확인 ──
    print("\n[6] 결과 확인...")
    time.sleep(5)
    print(f"  URL: {driver.current_url}")
    driver.save_screenshot(os.path.join(SS_DIR, "w6_result.png"))

    # alert 확인
    try:
        alert = driver.switch_to.alert
        alert_text = alert.text
        print(f"  Alert: {alert_text}")
        alert.accept()
        time.sleep(2)
    except:
        pass

    # 블로그 확인
    print("\n[7] 블로그 확인...")
    driver.get(f"https://blog.naver.com/{BLOG_ID}")
    time.sleep(5)
    driver.save_screenshot(os.path.join(SS_DIR, "w7_blog.png"))
    send_tg(photo=os.path.join(SS_DIR, "w7_blog.png"), caption="✅ 위젯 등록 후 블로그 상태")

    print("\n✅ 완료!")

except Exception as e:
    print(f"\n❌ 오류: {e}")
    import traceback
    traceback.print_exc()
    try:
        driver.save_screenshot(os.path.join(SS_DIR, "widget_err.png"))
        send_tg(msg=f"❌ 위젯 오류: {str(e)[:200]}")
    except:
        pass

finally:
    print("스크립트 종료")
