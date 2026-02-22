# -*- coding: utf-8 -*-
"""Remocon: 타이틀 텍스트 토글 (chk_title_display) 사용"""
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

print("=== 타이틀 텍스트 숨기기 (체크박스) ===")

opts = Options()
opts.add_experimental_option("debuggerAddress", "127.0.0.1:9222")
driver = webdriver.Chrome(options=opts)

try:
    # Remocon
    print("[1] Remocon...")
    driver.get(f"https://admin.blog.naver.com/Remocon.naver?blogId={BLOG_ID}&Redirect=Remocon")
    time.sleep(8)

    # 타이틀 메뉴 클릭
    print("[2] 타이틀 메뉴...")
    title_menu = driver.find_element(By.ID, "list_menu1")
    driver.execute_script("arguments[0].click();", title_menu)
    time.sleep(2)

    # 체크박스 상태 확인
    chk = driver.find_element(By.ID, "chk_title_display")
    is_checked = chk.is_selected()
    print(f"  chk_title_display: {'체크됨' if is_checked else '체크안됨'}")

    # 체크박스 영역 확인
    chk_info = driver.execute_script("""
        var chk = document.getElementById('chk_title_display');
        if (!chk) return null;
        var parent = chk.closest('.check_label') || chk.parentElement;
        return {
            checked: chk.checked,
            display: window.getComputedStyle(chk).display,
            parentText: parent ? parent.textContent.trim().substring(0, 50) : '',
            parentClass: parent ? parent.className : ''
        };
    """)
    print(f"  체크박스 정보: {chk_info}")

    # 체크 되어있으면 해제 (텍스트 표시 → 숨김)
    if is_checked:
        print("  체크 해제 (텍스트 숨기기)...")
        # _toggleTitleDisplay 클래스의 이벤트 핸들러 호출
        driver.execute_script("""
            var chk = document.getElementById('chk_title_display');
            if (chk) {
                chk.click();
            }
        """)
        time.sleep(2)

        # 확인
        is_checked_after = driver.execute_script("return document.getElementById('chk_title_display').checked;")
        print(f"  클릭 후 상태: {'체크됨' if is_checked_after else '체크안됨'}")
    else:
        print("  이미 해제되어 있음")

    driver.save_screenshot(os.path.join(SS_DIR, "title_toggle.png"))

    # 타이틀 높이 조정 (350px로)
    print("\n[3] 타이틀 높이 조정...")
    try:
        height_input = driver.find_element(By.ID, "title_height")
        current_height = height_input.get_attribute('value')
        print(f"  현재 높이: {current_height}")

        # 350으로 변경 (이미지 높이에 맞춤)
        height_input.clear()
        height_input.send_keys("350")
        time.sleep(1)

        # change 이벤트 발생
        driver.execute_script("""
            var input = document.getElementById('title_height');
            if (input) {
                input.value = '350';
                var evt = new Event('change', {bubbles: true});
                input.dispatchEvent(evt);
                var evt2 = new Event('input', {bubbles: true});
                input.dispatchEvent(evt2);
            }
        """)
        print(f"  높이 → 350px")
        time.sleep(2)
    except Exception as e:
        print(f"  높이 조정 오류: {e}")

    driver.save_screenshot(os.path.join(SS_DIR, "title_adjusted.png"))

    # 적용
    print("\n[4] 적용...")
    apply_btn = driver.find_element(By.CSS_SELECTOR, "a.btn_submit._showConfirmLayer")
    driver.execute_script("arguments[0].click();", apply_btn)
    time.sleep(2)

    submit_btn = driver.find_element(By.CSS_SELECTOR, "#skin_save_confirm_layer a._submit")
    driver.execute_script("arguments[0].click();", submit_btn)
    print("  적용 완료!")
    time.sleep(15)

    driver.save_screenshot(os.path.join(SS_DIR, "title_applied.png"))

    # 블로그 확인
    print("\n[5] 결과 확인...")
    driver.get(f"https://blog.naver.com/{BLOG_ID}")
    time.sleep(5)
    driver.save_screenshot(os.path.join(SS_DIR, "blog_title_clean.png"))

    # mainFrame에서 확인
    for iframe in driver.find_elements(By.TAG_NAME, "iframe"):
        fid = iframe.get_attribute('id') or ''
        if fid == 'mainFrame':
            driver.switch_to.frame(iframe)
            info = driver.execute_script("""
                var titleName = document.getElementById('blogTitleName');
                var titleText = document.getElementById('blogTitleText');
                var blogTitle = document.getElementById('blog-title');
                return {
                    titleHeight: blogTitle ? blogTitle.offsetHeight : 0,
                    nameDisplay: titleName ? window.getComputedStyle(titleName).display : 'N/A',
                    nameColor: titleName ? window.getComputedStyle(titleName).color : 'N/A',
                    nameText: titleName ? titleName.textContent : 'N/A',
                    textDisplay: titleText ? window.getComputedStyle(titleText).display : 'N/A'
                };
            """)
            print(f"  타이틀: {info}")
            driver.switch_to.default_content()
            break

    send_tg(photo=os.path.join(SS_DIR, "blog_title_clean.png"),
            caption="✅ 타이틀 텍스트 숨김 + 높이 조정 완료\nhttps://blog.naver.com/jyjzzj")

    print("\n✅ 완료!")

except Exception as e:
    print(f"\n❌ 오류: {e}")
    import traceback
    traceback.print_exc()

finally:
    print("스크립트 종료")
