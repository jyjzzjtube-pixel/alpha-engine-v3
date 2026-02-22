# -*- coding: utf-8 -*-
"""네이버 블로그 위젯 페이지 탐색"""
import sys, time, os
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

SS_DIR = r"C:\Users\jyjzz\OneDrive\바탕 화면\franchise-db\affiliate_system\renders\blog_widgets"
BLOG_ID = "jyjzzj"

print("=== 위젯 페이지 탐색 ===")

opts = Options()
opts.add_experimental_option("debuggerAddress", "127.0.0.1:9222")
driver = webdriver.Chrome(options=opts)
print(f"Selenium OK! URL: {driver.current_url}")

try:
    # ── [1] 새 관리자 페이지에서 위젯/레이아웃 메뉴 찾기 ──
    print("\n[1] admin.blog.naver.com 메뉴 탐색...")
    driver.get(f"https://admin.blog.naver.com/{BLOG_ID}")
    time.sleep(5)
    driver.save_screenshot(os.path.join(SS_DIR, "admin_main.png"))

    # 모든 링크 출력
    links = driver.find_elements(By.TAG_NAME, "a")
    print(f"  링크: {len(links)}개")
    for link in links:
        href = link.get_attribute('href') or ''
        txt = link.text.strip()
        if txt and href and ('widget' in href.lower() or '위젯' in txt or 'layout' in href.lower() or
                            '레이아웃' in txt or '꾸미기' in txt or 'design' in href.lower() or
                            'decor' in href.lower() or '설정' in txt):
            print(f"    ★ {txt} → {href[:80]}")

    # 모든 nav/sidebar 링크
    nav_links = driver.find_elements(By.CSS_SELECTOR, "nav a, aside a, .sidebar a, .lnb a, .snb a, [class*='menu'] a, [class*='nav'] a, [class*='side'] a")
    for link in nav_links:
        href = link.get_attribute('href') or ''
        txt = link.text.strip()
        if txt:
            print(f"    {txt} → {href[:60]}")

    # ── [2] Remocon 위젯 메뉴 → WidgetSetting으로 이동 ──
    print("\n[2] Remocon에서 위젯 페이지 이동...")
    driver.get(f"https://admin.blog.naver.com/Remocon.naver?blogId={BLOG_ID}&Redirect=Remocon")
    time.sleep(8)

    # 위젯 메뉴 클릭
    try:
        widget_menu = driver.find_element(By.ID, "list_menu10")
        print(f"  위젯 메뉴 텍스트: '{widget_menu.text}', class: '{widget_menu.get_attribute('class')}'")
        # 부모 li의 class 확인
        parent_li = widget_menu.find_element(By.XPATH, "./..")
        print(f"  부모 li class: '{parent_li.get_attribute('class')}'")

        # not_use 클래스 제거
        driver.execute_script("""
            var li = arguments[0].closest('li');
            if (li) {
                li.classList.remove('not_use');
                li.style.display = '';
            }
        """, widget_menu)
        time.sleep(1)

        # 클릭
        driver.execute_script("arguments[0].click();", widget_menu)
        time.sleep(3)
        driver.save_screenshot(os.path.join(SS_DIR, "widget_click.png"))
        print(f"  클릭 후 상태 확인")

        # 이동 확인 레이어 처리
        layer = driver.find_element(By.ID, "go_widget_confirm_layer")
        display = layer.value_of_css_property("display")
        print(f"  go_widget_confirm_layer display: {display}")

        if display != 'none':
            # 이동 버튼 클릭
            go_btn = layer.find_element(By.CSS_SELECTOR, "a._goLayoutWidgetPage")
            driver.execute_script("arguments[0].click();", go_btn)
            print("  이동 버튼 클릭!")
            time.sleep(8)
            print(f"  이동 후 URL: {driver.current_url}")
            driver.save_screenshot(os.path.join(SS_DIR, "widget_navigate.png"))
        else:
            # 레이어가 안 보이면 직접 표시
            print("  레이어 직접 표시...")
            driver.execute_script("""
                var wrap = document.getElementById('wrap_layer_popup');
                var layer = document.getElementById('go_widget_confirm_layer');
                var dimmed = document.getElementById('dimmed');
                if (wrap) wrap.style.display = '';
                if (layer) layer.style.display = '';
                if (dimmed) { dimmed.style.display = ''; dimmed.style.zIndex = '1000'; }
            """)
            time.sleep(1)
            driver.save_screenshot(os.path.join(SS_DIR, "widget_layer_show.png"))

            go_btn = layer.find_element(By.CSS_SELECTOR, "a._goLayoutWidgetPage")
            driver.execute_script("arguments[0].click();", go_btn)
            print("  이동 버튼 클릭!")
            time.sleep(8)
            print(f"  이동 후 URL: {driver.current_url}")
            driver.save_screenshot(os.path.join(SS_DIR, "widget_navigate2.png"))

    except Exception as e:
        print(f"  위젯 메뉴 오류: {e}")

    # ── [3] 현재 페이지에서 위젯 입력 찾기 ──
    print(f"\n[3] 현재 URL: {driver.current_url}")

    # iframe 확인
    iframes = driver.find_elements(By.TAG_NAME, "iframe")
    print(f"  iframes: {len(iframes)}개")
    for i, ifr in enumerate(iframes):
        src = ifr.get_attribute('src') or ''
        fid = ifr.get_attribute('id') or ''
        name = ifr.get_attribute('name') or ''
        print(f"    [{i}] id={fid}, name={name}, src={src[:80]}")

    # 위젯 관련 요소 JavaScript로 찾기
    result = driver.execute_script("""
        var result = [];
        // _widgetName, _widgetCode, _widgetHeight 찾기
        var ids = ['_widgetName', '_widgetCode', '_widgetHeight', '_btnNext', '_btnSubmit',
                   'widgetName', 'widgetCode', 'widgetHeight', 'externalWidgetName',
                   'externalWidgetCode', 'addExternalWidget'];
        ids.forEach(function(id) {
            var el = document.getElementById(id);
            if (el) result.push('Found: #' + id + ' tag=' + el.tagName);
        });

        // 클래스로 찾기
        var classes = ['_widgetName', '_widgetCode', '_widgetHeight', '_btnNext', '_btnSubmit',
                       'addExternalWidget', 'btn_add_widget'];
        classes.forEach(function(cls) {
            var els = document.getElementsByClassName(cls);
            if (els.length > 0) result.push('Class .' + cls + ' count=' + els.length);
        });

        // iframe 내부도 확인
        var frames = document.querySelectorAll('iframe');
        result.push('Iframes: ' + frames.length);

        return result;
    """)
    print(f"  JS 탐색: {result}")

    # ── [4] iframe 내부 확인 ──
    print("\n[4] iframe 내부 탐색...")
    for i, ifr in enumerate(iframes[:5]):
        try:
            driver.switch_to.frame(ifr)
            inner_src = driver.page_source[:500]
            has_widget = 'widget' in inner_src.lower() or '위젯' in inner_src
            print(f"  iframe[{i}]: widget관련={'예' if has_widget else '아니오'}, len={len(driver.page_source)}")

            # 위젯 입력 찾기
            inner_ids = driver.execute_script("""
                var result = [];
                var inputs = document.querySelectorAll('input, textarea, select');
                inputs.forEach(function(el) {
                    var id = el.id || '';
                    var name = el.name || '';
                    if (id || name) result.push(el.tagName + ' id=' + id + ' name=' + name);
                });
                return result.slice(0, 20);
            """)
            if inner_ids:
                print(f"  내부 입력: {inner_ids}")

            driver.switch_to.default_content()
        except:
            driver.switch_to.default_content()

    # ── [5] JavaScript로 직접 위젯 등록 시도 ──
    print("\n[5] JS로 직접 위젯 관련 함수 확인...")
    js_functions = driver.execute_script("""
        var result = [];
        // window에서 위젯 관련 함수 찾기
        for (var key in window) {
            if (typeof window[key] === 'function') {
                var name = key.toLowerCase();
                if (name.includes('widget') || name.includes('external')) {
                    result.push(key);
                }
            }
        }
        return result;
    """)
    print(f"  위젯 함수: {js_functions}")

    # 페이지 소스에서 위젯 관련 URL/함수 검색
    src = driver.page_source
    import re
    widget_patterns = re.findall(r'(addExternal\w+|WidgetSetting\w*|widget\w*Setting|_widgetName|_widgetCode)', src)
    print(f"  소스 패턴: {list(set(widget_patterns))}")

    driver.save_screenshot(os.path.join(SS_DIR, "widget_explore_final.png"))

except Exception as e:
    print(f"\n❌ 오류: {e}")
    import traceback
    traceback.print_exc()

finally:
    print("\n스크립트 종료")
