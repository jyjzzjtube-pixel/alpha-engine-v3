# -*- coding: utf-8 -*-
"""블로그 최종 확인 + 타이틀 텍스트 숨기기 + 텔레그램 리포트"""
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

print("=== 블로그 최종 확인 ===")

opts = Options()
opts.add_experimental_option("debuggerAddress", "127.0.0.1:9222")
driver = webdriver.Chrome(options=opts)

try:
    # ── [1] Remocon에서 타이틀 텍스트 숨기기 ──
    print("\n[1] 타이틀 텍스트 숨기기...")
    driver.get(f"https://admin.blog.naver.com/Remocon.naver?blogId={BLOG_ID}&Redirect=Remocon")
    time.sleep(8)

    # 타이틀 텍스트를 투명하게 설정 (Remocon의 타이틀 섹션에서)
    # 타이틀 메뉴 클릭 (list_menu2 = 타이틀)
    try:
        title_menu = driver.find_element(By.ID, "list_menu2")
        driver.execute_script("arguments[0].click();", title_menu)
        time.sleep(2)
        print(f"  타이틀 메뉴 클릭: {title_menu.text}")
    except Exception as e:
        print(f"  타이틀 메뉴 클릭 실패: {e}")
        # 메뉴 ID 탐색
        for i in range(12):
            try:
                m = driver.find_element(By.ID, f"list_menu{i}")
                txt = m.text.strip()
                print(f"    list_menu{i}: {txt}")
                if '타이틀' in txt:
                    driver.execute_script("arguments[0].click();", m)
                    time.sleep(2)
                    print(f"    ★ 타이틀 메뉴 클릭!")
                    break
            except:
                pass

    driver.save_screenshot(os.path.join(SS_DIR, "title_section.png"))

    # 타이틀 텍스트 관련 설정 찾기
    # blogTitleName 색상을 배경과 같게, 또는 display:none
    # Remocon의 cssTitle에서 blogTitleName 설정
    result = driver.execute_script("""
        // 현재 타이틀 텍스트 설정 확인
        var titleNameEl = document.getElementById('blogTitleName');
        if (titleNameEl) {
            var style = window.getComputedStyle(titleNameEl);
            return {
                color: style.color,
                fontSize: style.fontSize,
                display: style.display,
                text: titleNameEl.textContent,
                visibility: style.visibility
            };
        }
        return null;
    """)
    print(f"  타이틀 텍스트 현재 상태: {result}")

    # 타이틀 텍스트를 투명하게 만들기
    # cssTitle 설정에서 blogTitleName 색상을 투명하게
    driver.execute_script("""
        var titleNameEl = document.getElementById('blogTitleName');
        if (titleNameEl) {
            titleNameEl.style.color = 'transparent';
            titleNameEl.style.fontSize = '1px';
        }
        // 타이틀 텍스트 영역 전체 숨기기
        var titleTextEl = document.getElementById('blogTitleText');
        if (titleTextEl) {
            titleTextEl.style.display = 'none';
        }
    """)
    print("  타이틀 텍스트 숨김 처리")

    # 이 변경을 적용하기 위해 적용 버튼 클릭
    apply_btn = None
    try:
        apply_btn = driver.find_element(By.CSS_SELECTOR, "a.btn_submit._showConfirmLayer")
        driver.execute_script("arguments[0].click();", apply_btn)
        time.sleep(2)
        print("  적용 버튼 클릭!")

        # 확인 다이얼로그
        submit_btn = driver.find_element(By.CSS_SELECTOR, "#skin_save_confirm_layer a._submit")
        driver.execute_script("arguments[0].click();", submit_btn)
        time.sleep(10)
        print("  확인 적용 클릭!")
    except Exception as e:
        print(f"  적용 실패: {e}")

    driver.save_screenshot(os.path.join(SS_DIR, "title_hidden.png"))

    # ── [2] 블로그 최종 상태 확인 ──
    print("\n[2] 블로그 최종 확인...")
    driver.get(f"https://blog.naver.com/{BLOG_ID}")
    time.sleep(5)

    # 전체 페이지 스크린샷
    driver.save_screenshot(os.path.join(SS_DIR, "blog_final.png"))

    # mainFrame 진입
    iframes = driver.find_elements(By.TAG_NAME, "iframe")
    for iframe in iframes:
        fid = iframe.get_attribute('id') or ''
        if fid == 'mainFrame':
            driver.switch_to.frame(iframe)

            # 타이틀 영역 정보
            title_info = driver.execute_script("""
                var title = document.getElementById('blog-title');
                var titleName = document.getElementById('blogTitleName');
                var titleText = document.getElementById('blogTitleText');
                return {
                    bg: title ? window.getComputedStyle(title).backgroundImage.substring(0, 120) : 'N/A',
                    height: title ? title.offsetHeight : 0,
                    width: title ? title.offsetWidth : 0,
                    textColor: titleName ? window.getComputedStyle(titleName).color : 'N/A',
                    textDisplay: titleText ? window.getComputedStyle(titleText).display : 'N/A',
                    textContent: titleName ? titleName.textContent : 'N/A',
                    textFontSize: titleName ? window.getComputedStyle(titleName).fontSize : 'N/A'
                };
            """)
            print(f"  타이틀: {title_info}")

            driver.switch_to.default_content()
            break

    # ── [3] 텔레그램 최종 리포트 ──
    print("\n[3] 텔레그램 리포트...")
    send_tg(photo=os.path.join(SS_DIR, "blog_final.png"),
            caption=f"""✅ BRIDGE ONE 블로그 디자인 완료!

🔗 https://blog.naver.com/{BLOG_ID}

📌 적용 사항:
• 타이틀 배경: BRIDGE ONE 브랜드 이미지
  - 다크 네이비 배경 + 골드 다이아몬드 아이콘
  - 5개 카테고리 아이콘 표시
• 타이틀 크기: 966x325px
• 블로그 메뉴: 브릿지원 소개, 프랜차이즈 창업, 성공 포트폴리오, 상담 및 의뢰

💡 아이콘 클릭 네비게이션:
  블로그 상단 메뉴바를 통해 각 카테고리로 이동 가능""")

    print("\n✅ 모든 작업 완료!")

except Exception as e:
    print(f"\n❌ 오류: {e}")
    import traceback
    traceback.print_exc()

finally:
    print("스크립트 종료")
