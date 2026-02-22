# -*- coding: utf-8 -*-
"""Remocon에서 타이틀 텍스트 숨기기 (CSS 변경 방식)"""
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

print("=== 타이틀 텍스트 숨기기 ===")

opts = Options()
opts.add_experimental_option("debuggerAddress", "127.0.0.1:9222")
driver = webdriver.Chrome(options=opts)

try:
    # Remocon 페이지로
    print("[1] Remocon 페이지...")
    driver.get(f"https://admin.blog.naver.com/Remocon.naver?blogId={BLOG_ID}&Redirect=Remocon")
    time.sleep(8)
    print(f"  URL: {driver.current_url}")

    # 리모콘 메뉴 목록 확인
    print("\n[2] 메뉴 확인...")
    for i in range(12):
        try:
            m = driver.find_element(By.ID, f"list_menu{i}")
            txt = m.text.strip().replace('\n', ' ')
            cls = m.get_attribute('class') or ''
            parent = m.find_element(By.XPATH, "./..").get_attribute('class') or ''
            print(f"  list_menu{i}: '{txt}' class='{cls[:40]}' parent_class='{parent}'")
        except:
            pass

    # 타이틀 메뉴 클릭 (보통 list_menu2)
    print("\n[3] 타이틀 메뉴 클릭...")
    title_clicked = False
    for i in range(12):
        try:
            m = driver.find_element(By.ID, f"list_menu{i}")
            txt = m.text.strip()
            if '타이틀' in txt:
                driver.execute_script("arguments[0].click();", m)
                time.sleep(2)
                print(f"  ★ list_menu{i} '{txt}' 클릭!")
                title_clicked = True
                break
        except:
            pass

    if not title_clicked:
        # CSS 클래스로 찾기
        try:
            title_btn = driver.find_element(By.CSS_SELECTOR, ".remocon_title, [class*='remocon_title']")
            driver.execute_script("arguments[0].click();", title_btn)
            time.sleep(2)
            print(f"  타이틀 버튼 클릭!")
            title_clicked = True
        except:
            pass

    driver.save_screenshot(os.path.join(SS_DIR, "title_menu.png"))

    # [4] 타이틀 텍스트 영역 찾기 - 위치, 색상, 폰트 관련 설정
    print("\n[4] 타이틀 설정 탐색...")

    # 타이틀 섹션의 설정 요소 확인
    title_settings = driver.execute_script("""
        var content = document.getElementById('content_menu2');
        if (!content) {
            // 모든 content_menu 확인
            for (var i = 0; i < 12; i++) {
                var el = document.getElementById('content_menu' + i);
                if (el && el.classList.contains('on')) {
                    content = el;
                    break;
                }
            }
        }

        var result = {found: !!content};
        if (content) {
            result.id = content.id;
            result.display = window.getComputedStyle(content).display;
            result.html = content.innerHTML.substring(0, 500);

            // 폰트 색상 관련 요소 찾기
            var colorInputs = content.querySelectorAll('input[type="color"], input[type="text"][id*="color"], input[class*="color"], .colorpicker, [id*="fontColor"], [id*="titleColor"]');
            result.colorInputs = colorInputs.length;

            // 폰트 크기 관련 요소
            var fontInputs = content.querySelectorAll('select[id*="font"], input[id*="font"], [class*="font_size"], [id*="fontSize"]');
            result.fontInputs = fontInputs.length;

            // 정렬 관련
            var alignInputs = content.querySelectorAll('[id*="align"], [class*="align"]');
            result.alignInputs = alignInputs.length;
        }
        return result;
    """)
    print(f"  설정: {title_settings}")

    # 타이틀 영역의 모든 설정 입력 확인
    all_settings = driver.execute_script("""
        // 현재 활성 컨텐츠 패널 찾기
        var panels = document.querySelectorAll('.content_remocon > div');
        var activePanel = null;
        for (var i = 0; i < panels.length; i++) {
            if (panels[i].classList.contains('on') ||
                window.getComputedStyle(panels[i]).display !== 'none') {
                activePanel = panels[i];
                break;
            }
        }

        if (!activePanel) return {error: 'no active panel'};

        var result = {
            panelId: activePanel.id,
            panelClass: activePanel.className
        };

        // 모든 input/select/button 찾기
        var inputs = activePanel.querySelectorAll('input, select, button, a[role="button"]');
        result.inputs = [];
        for (var i = 0; i < inputs.length; i++) {
            var el = inputs[i];
            var display = window.getComputedStyle(el).display;
            if (display !== 'none') {
                result.inputs.push({
                    tag: el.tagName,
                    type: el.type || '',
                    id: el.id || '',
                    name: el.name || '',
                    class: el.className.substring(0, 60),
                    value: (el.value || '').substring(0, 30),
                    text: (el.textContent || '').trim().substring(0, 30)
                });
            }
        }
        return result;
    """)
    print(f"  활성 패널: {all_settings.get('panelId')}, {all_settings.get('panelClass', '')[:50]}")
    if 'inputs' in all_settings:
        print(f"  입력 필드: {len(all_settings['inputs'])}개")
        for inp in all_settings['inputs'][:20]:
            print(f"    <{inp['tag']}> type={inp['type']}, id={inp['id'][:30]}, class={inp['class'][:30]}, text={inp['text']}")

    # [5] Remocon CSS 방식으로 타이틀 텍스트 숨기기
    # cssRule 객체를 통해 타이틀 텍스트를 수정
    print("\n[5] CSS Rule로 타이틀 텍스트 숨기기...")

    # cssRule['title'] 확인
    css_title = driver.execute_script("""
        if (typeof cssRule !== 'undefined' && cssRule['title']) {
            return JSON.stringify(cssRule['title']);
        }
        return 'cssRule not found';
    """)
    print(f"  cssRule['title']: {css_title}")

    # blogTitleName을 transparent로 변경
    driver.execute_script("""
        if (typeof cssRule !== 'undefined') {
            // 타이틀 텍스트를 투명하게
            cssRule['title']['#blogTitleName'] = 'display: inline; color: transparent; font-family: "나눔고딕", NanumGothic; font-size: 1px';
            // 타이틀 텍스트 영역도 숨기기
            cssRule['title']['#blogTitleText'] = 'vertical-align: top; text-align: center; visibility: hidden; height: 0; overflow: hidden';
        }
    """)
    print("  cssRule 수정 완료!")

    # remoconForm에 CSS 값 설정
    driver.execute_script("""
        var form = document.forms['remoconForm'];
        if (form && form.cssTitle) {
            // CSS 값 직렬화
            var css = '';
            if (typeof cssRule !== 'undefined' && cssRule['title']) {
                for (var selector in cssRule['title']) {
                    css += selector + '{' + cssRule['title'][selector] + '}';
                }
            }
            form.cssTitle.value = css;
        }
    """)
    print("  remoconForm.cssTitle 업데이트!")

    # preview 업데이트
    driver.execute_script("""
        // 프리뷰에서 타이틀 텍스트 숨기기
        var titleName = document.getElementById('blogTitleName');
        var titleText = document.getElementById('blogTitleText');
        if (titleName) {
            titleName.style.color = 'transparent';
            titleName.style.fontSize = '1px';
        }
        if (titleText) {
            titleText.style.visibility = 'hidden';
            titleText.style.height = '0';
            titleText.style.overflow = 'hidden';
        }
    """)
    time.sleep(1)

    driver.save_screenshot(os.path.join(SS_DIR, "title_text_hidden_preview.png"))

    # [6] 적용
    print("\n[6] 적용...")
    try:
        apply_btn = driver.find_element(By.CSS_SELECTOR, "a.btn_submit._showConfirmLayer")
        driver.execute_script("arguments[0].click();", apply_btn)
        time.sleep(2)
        print("  적용 버튼 클릭!")

        submit_btn = driver.find_element(By.CSS_SELECTOR, "#skin_save_confirm_layer a._submit")
        driver.execute_script("arguments[0].click();", submit_btn)
        time.sleep(15)
        print("  확인 적용!")
    except Exception as e:
        print(f"  적용 오류: {e}")

    # [7] 결과 확인
    print("\n[7] 블로그 결과...")
    driver.get(f"https://blog.naver.com/{BLOG_ID}")
    time.sleep(5)
    driver.save_screenshot(os.path.join(SS_DIR, "blog_after_hide.png"))

    # mainFrame에서 확인
    for iframe in driver.find_elements(By.TAG_NAME, "iframe"):
        fid = iframe.get_attribute('id') or ''
        if fid == 'mainFrame':
            driver.switch_to.frame(iframe)
            info = driver.execute_script("""
                var titleName = document.getElementById('blogTitleName');
                var titleText = document.getElementById('blogTitleText');
                return {
                    nameColor: titleName ? window.getComputedStyle(titleName).color : 'N/A',
                    nameFont: titleName ? window.getComputedStyle(titleName).fontSize : 'N/A',
                    nameDisplay: titleName ? window.getComputedStyle(titleName).display : 'N/A',
                    textVis: titleText ? window.getComputedStyle(titleText).visibility : 'N/A',
                    textDisplay: titleText ? window.getComputedStyle(titleText).display : 'N/A',
                    titleHeight: document.getElementById('blog-title') ? document.getElementById('blog-title').offsetHeight : 0
                };
            """)
            print(f"  타이틀 정보: {info}")
            driver.switch_to.default_content()
            break

    send_tg(photo=os.path.join(SS_DIR, "blog_after_hide.png"), caption="타이틀 텍스트 처리 후 블로그")

    print("\n✅ 완료!")

except Exception as e:
    print(f"\n❌ 오류: {e}")
    import traceback
    traceback.print_exc()

finally:
    print("스크립트 종료")
