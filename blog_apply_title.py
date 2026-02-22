# -*- coding: utf-8 -*-
"""네이버 블로그 Remocon - 타이틀 이미지 업로드 + 적용"""
import sys, time, os
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

SS_DIR = r"C:\Users\jyjzz\OneDrive\바탕 화면\franchise-db\affiliate_system\renders\blog_widgets"
TITLE_IMG = os.path.join(SS_DIR, "title_combined.jpg")
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

print("=== 블로그 타이틀 적용 (Remocon) ===")

# Selenium 연결 (이미 실행 중인 Chrome 9222)
opts = Options()
opts.add_experimental_option("debuggerAddress", "127.0.0.1:9222")
driver = webdriver.Chrome(options=opts)
print(f"Selenium 연결 OK! URL: {driver.current_url}")

try:
    # ── [1] Remocon 페이지로 이동 ──
    print("\n[1] Remocon 페이지...")
    remocon_url = f"https://admin.blog.naver.com/Remocon.naver?blogId={BLOG_ID}&Redirect=Remocon"

    if "Remocon.naver" not in driver.current_url:
        driver.get(remocon_url)
        time.sleep(8)

    print(f"  URL: {driver.current_url}")
    driver.save_screenshot(os.path.join(SS_DIR, "step1_remocon.png"))

    # ── [2] 타이틀 섹션 찾기 & 이미지 업로드 ──
    print("\n[2] 타이틀 이미지 업로드...")

    # 타이틀 입력 필드 찾기
    title_input = None
    file_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
    print(f"  파일 입력: {len(file_inputs)}개")

    for i, fi in enumerate(file_inputs):
        name = fi.get_attribute('name') or ''
        fid = fi.get_attribute('id') or ''
        if name == 'title' or fid == 'titleInputFile':
            title_input = fi
            print(f"  ★ TITLE INPUT: [{i}] name={name}, id={fid}")
            break

    if not title_input:
        print("  ❌ titleInputFile 못 찾음!")
        sys.exit(1)

    # 파일 업로드
    print(f"  이미지: {TITLE_IMG}")
    print(f"  존재: {os.path.exists(TITLE_IMG)}, 크기: {os.path.getsize(TITLE_IMG)} bytes")
    title_input.send_keys(TITLE_IMG)
    print("  ✅ 파일 전송 완료!")
    time.sleep(5)

    driver.save_screenshot(os.path.join(SS_DIR, "step2_uploaded.png"))
    send_tg(photo=os.path.join(SS_DIR, "step2_uploaded.png"), caption="타이틀 이미지 업로드 후")

    # ── [3] 적용 버튼 클릭 ──
    print("\n[3] 적용 버튼 클릭...")

    # 방법1: CSS 클래스로 찾기
    apply_btn = None
    try:
        apply_btn = driver.find_element(By.CSS_SELECTOR, "a.btn_submit._showConfirmLayer")
        print(f"  적용 버튼 발견: {apply_btn.text}")
    except:
        # 방법2: 텍스트로 찾기
        try:
            links = driver.find_elements(By.CSS_SELECTOR, "#remocon_apply_area a")
            for link in links:
                if '적용' in link.text:
                    apply_btn = link
                    print(f"  적용 버튼 (텍스트): {link.text}")
                    break
        except:
            pass

    if not apply_btn:
        # 방법3: JavaScript로 직접 찾기
        try:
            apply_btn = driver.execute_script("""
                var btns = document.querySelectorAll('a._showConfirmLayer, a.btn_submit');
                for (var i = 0; i < btns.length; i++) {
                    if (btns[i].textContent.trim().includes('적용')) {
                        return btns[i];
                    }
                }
                return null;
            """)
            if apply_btn:
                print(f"  적용 버튼 (JS): found")
        except:
            pass

    if not apply_btn:
        print("  ❌ 적용 버튼 못 찾음! JavaScript 직접 실행 시도...")
        # 직접 confirm layer 표시 시도
        driver.execute_script("""
            var layer = document.getElementById('skin_save_confirm_layer');
            var dimmed = document.getElementById('dimmed');
            var wrap = document.getElementById('wrap_layer_popup');
            if (wrap) wrap.style.display = '';
            if (layer) layer.style.display = '';
            if (dimmed) dimmed.style.display = '';
        """)
        time.sleep(1)
    else:
        # 적용 버튼 클릭
        driver.execute_script("arguments[0].click();", apply_btn)
        print("  ✅ 적용 버튼 클릭!")
        time.sleep(2)

    driver.save_screenshot(os.path.join(SS_DIR, "step3_confirm.png"))
    send_tg(photo=os.path.join(SS_DIR, "step3_confirm.png"), caption="적용 확인 다이얼로그")

    # ── [4] 확인 다이얼로그에서 '적용' 클릭 ──
    print("\n[4] 확인 다이얼로그 '적용' 클릭...")

    submit_btn = None
    try:
        # 확인 레이어의 적용 버튼
        submit_btn = driver.find_element(By.CSS_SELECTOR, "#skin_save_confirm_layer a._submit")
        print(f"  확인 적용 버튼: {submit_btn.text}")
    except:
        try:
            submit_btn = driver.find_element(By.CSS_SELECTOR, "a.button_next._submit")
            print(f"  확인 적용 버튼 (alt): {submit_btn.text}")
        except:
            pass

    if not submit_btn:
        # JavaScript로 찾기
        try:
            submit_btn = driver.execute_script("""
                var layer = document.getElementById('skin_save_confirm_layer');
                if (layer) {
                    var btns = layer.querySelectorAll('a._submit, a.button_next');
                    for (var i = 0; i < btns.length; i++) {
                        if (btns[i].textContent.trim().includes('적용')) {
                            return btns[i];
                        }
                    }
                }
                return null;
            """)
            if submit_btn:
                print(f"  확인 적용 버튼 (JS): found")
        except:
            pass

    if submit_btn:
        driver.execute_script("arguments[0].click();", submit_btn)
        print("  ✅ 확인 적용 클릭!")
    else:
        # 최후 수단: _submit 클래스 직접 클릭
        print("  _submit 버튼 직접 클릭 시도...")
        driver.execute_script("""
            var btns = document.querySelectorAll('a._submit');
            for (var i = 0; i < btns.length; i++) {
                btns[i].click();
            }
        """)
        print("  모든 _submit 클릭!")

    # 저장 대기
    print("  저장 대기 중...")
    time.sleep(15)

    driver.save_screenshot(os.path.join(SS_DIR, "step4_saving.png"))
    send_tg(photo=os.path.join(SS_DIR, "step4_saving.png"), caption="저장 진행 중")

    # ── [5] 결과 확인 ──
    print("\n[5] 블로그 확인...")

    # 새 탭에서 블로그 확인
    driver.execute_script(f"window.open('https://blog.naver.com/{BLOG_ID}', '_blank');")
    time.sleep(3)

    # 새 탭으로 전환
    handles = driver.window_handles
    if len(handles) > 1:
        driver.switch_to.window(handles[-1])
        time.sleep(5)

        print(f"  블로그 URL: {driver.current_url}")
        driver.save_screenshot(os.path.join(SS_DIR, "step5_blog_result.png"))
        send_tg(photo=os.path.join(SS_DIR, "step5_blog_result.png"),
                caption="✅ 블로그 타이틀 적용 결과")

        # 블로그 페이지 소스 확인 (타이틀 이미지 URL)
        src = driver.page_source

        # mainFrame 안에서 확인
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        for iframe in iframes:
            fid = iframe.get_attribute('id') or ''
            if fid == 'mainFrame':
                driver.switch_to.frame(iframe)
                inner_src = driver.page_source
                if 'blog-title' in inner_src:
                    # 타이틀 영역 스크린샷
                    try:
                        title_el = driver.find_element(By.ID, "blog-title")
                        bg = title_el.value_of_css_property("background-image")
                        h = title_el.value_of_css_property("height")
                        print(f"  타이틀 배경: {bg[:80]}")
                        print(f"  타이틀 높이: {h}")
                    except:
                        pass
                driver.switch_to.default_content()
                break

        # 원래 탭으로
        driver.switch_to.window(handles[0])

    print("\n✅ 완료!")
    send_tg(msg="✅ 블로그 타이틀 적용 완료!\nhttps://blog.naver.com/jyjzzj")

except Exception as e:
    print(f"\n❌ 오류: {e}")
    import traceback
    traceback.print_exc()
    try:
        driver.save_screenshot(os.path.join(SS_DIR, "error_apply.png"))
        send_tg(msg=f"❌ 타이틀 적용 오류: {str(e)[:200]}")
    except:
        pass

finally:
    print("스크립트 종료 (Chrome 유지)")
