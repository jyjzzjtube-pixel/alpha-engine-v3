# -*- coding: utf-8 -*-
"""네이버 블로그 타이틀 적용 - Full Profile Copy + Remote Debugging"""
import sys, time, os, subprocess, shutil, json, urllib.request
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

print("=== 블로그 타이틀 적용 시작 ===")

# ── Chrome 종료 ──
subprocess.run(['taskkill', '/F', '/IM', 'chrome.exe'], capture_output=True)
subprocess.run(['taskkill', '/F', '/IM', 'chromedriver.exe'], capture_output=True)
time.sleep(3)

# ── Full profile copy ──
SRC_PROFILE = r"C:\Users\jyjzz\AppData\Local\Google\Chrome\User Data"
TMP_PROFILE = r"C:\Users\jyjzz\AppData\Local\Temp\chrome_full_copy"

print("프로필 복사 중... (1분 소요)")
if os.path.exists(TMP_PROFILE):
    shutil.rmtree(TMP_PROFILE, ignore_errors=True)

result = subprocess.run([
    'robocopy', SRC_PROFILE, TMP_PROFILE,
    '/E', '/XD', 'Cache', 'Code Cache', 'Service Worker', 'CacheStorage',
    'GrShaderCache', 'GPUCache', 'ShaderCache', 'blob_storage',
    '/XF', '*.log', '*.tmp',
    '/NFL', '/NDL', '/NJH', '/NJS', '/MT:4', '/R:0', '/W:0',
], capture_output=True, text=True, errors='replace', timeout=120)
print(f"복사 완료 (exit: {result.returncode})")

# Lock 파일 제거
for f in ['SingletonLock', 'SingletonSocket', 'SingletonCookie', 'lockfile', 'DevToolsActivePort']:
    try: os.remove(os.path.join(TMP_PROFILE, f))
    except: pass

# ── Chrome 시작 (Remote Debugging) ──
chrome_proc = subprocess.Popen([
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    f"--user-data-dir={TMP_PROFILE}",
    "--profile-directory=Default",
    "--remote-debugging-port=9222",
    "--window-size=1400,900",
    "--no-first-run",
    "--no-default-browser-check",
    "about:blank"
], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

print(f"Chrome PID: {chrome_proc.pid}")
time.sleep(8)

# Port 확인
port_ok = False
for i in range(15):
    try:
        resp = urllib.request.urlopen("http://127.0.0.1:9222/json/version", timeout=3)
        data = json.loads(resp.read())
        print(f"Port 9222 OK! {data.get('Browser')}")
        port_ok = True
        break
    except:
        time.sleep(2)

if not port_ok:
    send_tg(msg="❌ Chrome debug port 실패")
    sys.exit(1)

# Selenium 연결
opts = Options()
opts.add_experimental_option("debuggerAddress", "127.0.0.1:9222")
driver = webdriver.Chrome(options=opts)
print(f"Selenium OK! URL: {driver.current_url}")

try:
    # ── [1] 로그인 확인 ──
    print("\n[1] 네이버 로그인 확인...")
    driver.get("https://www.naver.com")
    time.sleep(3)
    driver.save_screenshot(os.path.join(SS_DIR, "naver_main.png"))

    page = driver.page_source
    logged_in = 'gnb_my' in page or 'MyView' in page or 'log.nhn' in page
    print(f"  로그인: {logged_in}")

    if not logged_in:
        print("  쿠키 로그인 실패 - QR 시도")
        driver.get("https://nid.naver.com/nidlogin.login?mode=form&url=https%3A%2F%2Fblog.naver.com")
        time.sleep(2)

        # QR 탭
        try:
            for tab in driver.find_elements(By.CSS_SELECTOR, ".login_tab a, [role='tab']"):
                if 'QR' in tab.text:
                    tab.click()
                    time.sleep(2)
                    break
        except:
            pass

        driver.save_screenshot(os.path.join(SS_DIR, "qr_login.png"))
        send_tg(photo=os.path.join(SS_DIR, "qr_login.png"),
                caption="🔑 QR 로그인!\n네이버 앱 > QR > 스캔 (300초)")

        for i in range(300):
            time.sleep(1)
            if "nid.naver.com" not in driver.current_url:
                print(f"  로그인 성공! ({i+1}초)")
                logged_in = True
                break
            if i % 60 == 59:
                driver.save_screenshot(os.path.join(SS_DIR, f"wait_{i+1}.png"))
                send_tg(photo=os.path.join(SS_DIR, f"wait_{i+1}.png"), caption=f"⏰ QR {i+1}/300초")

        if not logged_in:
            send_tg(msg="❌ QR 타임아웃")
            sys.exit(1)

    send_tg(photo=os.path.join(SS_DIR, "naver_main.png"), caption="✅ 로그인!")

    # ── [2] 블로그 관리자 접근 ──
    print("\n[2] 블로그 관리...")
    driver.get(f"https://blog.naver.com/{BLOG_ID}/manage")
    time.sleep(5)
    driver.save_screenshot(os.path.join(SS_DIR, "manage_page.png"))
    print(f"  URL: {driver.current_url}")
    send_tg(photo=os.path.join(SS_DIR, "manage_page.png"), caption="블로그 관리 페이지")

    # 관리 페이지 소스 저장
    with open(os.path.join(SS_DIR, "manage_source.html"), 'w', encoding='utf-8') as f:
        f.write(driver.page_source[:100000])

    # 모든 링크 출력
    links = driver.find_elements(By.TAG_NAME, "a")
    print(f"  링크: {len(links)}개")
    admin_links = {}
    for link in links:
        href = link.get_attribute('href') or ''
        txt = link.text.strip()
        if txt and href:
            admin_links[txt] = href
            if any(k in txt or k in href.lower() for k in ['꾸미기', 'layout', 'skin', 'design', '레이아웃', '위젯', 'widget', '타이틀']):
                print(f"    ★ {txt} → {href[:80]}")

    # ── [3] 꾸미기 설정 찾기 ──
    print("\n[3] 꾸미기 설정...")

    # 네이버 블로그 관리자 메뉴 탐색
    manage_urls = [
        f"https://blog.naver.com/{BLOG_ID}/manage/design",
        f"https://blog.naver.com/{BLOG_ID}/manage/layout",
        f"https://blog.naver.com/{BLOG_ID}/manage/decoration",
        f"https://blog.naver.com/{BLOG_ID}/manage/skin",
        f"https://blog.naver.com/{BLOG_ID}/manage/widget",
    ]

    working_url = None
    for url in manage_urls:
        driver.get(url)
        time.sleep(3)
        title = driver.title
        src = driver.page_source[:1000]
        has_error = "페이지 주소" in src
        is_login = "nid.naver.com" in driver.current_url
        status = "❌" if (has_error or is_login) else "✅"
        path = url.split('/')[-1]
        print(f"  {status} {path}: {driver.current_url[:60]}")

        if not has_error and not is_login:
            driver.save_screenshot(os.path.join(SS_DIR, f"manage_{path}.png"))
            working_url = url

            # iframe 확인
            iframes = driver.find_elements(By.TAG_NAME, "iframe")
            if iframes:
                print(f"    iframe: {len(iframes)}개")
                for idx, ifr in enumerate(iframes):
                    src_attr = ifr.get_attribute('src') or ''
                    fid = ifr.get_attribute('id') or ''
                    print(f"      [{idx}] id={fid}, src={src_attr[:60]}")

            # 파일 입력 확인
            file_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
            if file_inputs:
                print(f"    파일 입력: {len(file_inputs)}개")
                for i, fi in enumerate(file_inputs):
                    print(f"      [{i}] name={fi.get_attribute('name')}, id={fi.get_attribute('id')}")

    # ── [4] 메인 관리 페이지에서 꾸미기 메뉴 클릭 시도 ──
    print("\n[4] 관리 메뉴 탐색...")
    driver.get(f"https://blog.naver.com/{BLOG_ID}/manage")
    time.sleep(5)

    # 사이드바에서 '꾸미기 설정' 또는 유사 메뉴 찾기
    menu_items = driver.find_elements(By.CSS_SELECTOR, "nav a, .lnb a, .snb a, [class*='menu'] a, [class*='nav'] a")
    print(f"  메뉴 항목: {len(menu_items)}개")
    for item in menu_items:
        txt = item.text.strip()
        href = item.get_attribute('href') or ''
        if txt:
            print(f"    {txt} → {href[:60]}")

    # 또한 버튼들 확인
    buttons = driver.find_elements(By.TAG_NAME, "button")
    for btn in buttons:
        txt = btn.text.strip()
        if txt and any(k in txt for k in ['꾸미기', '레이아웃', '위젯', '타이틀', '스킨', '디자인']):
            print(f"    ★ 버튼: {txt}")

    # React SPA일 수 있으므로 JavaScript로 네비게이션 시도
    try:
        # React Router로 직접 네비게이션
        nav_result = driver.execute_script("""
            // 현재 페이지의 React 라우터 확인
            var links = document.querySelectorAll('a');
            var result = [];
            links.forEach(function(a) {
                var text = a.textContent.trim();
                var href = a.getAttribute('href') || '';
                if (text && (text.includes('꾸미기') || text.includes('레이아웃') || text.includes('디자인') || text.includes('위젯') || text.includes('설정'))) {
                    result.push(text + ' -> ' + href);
                }
            });
            return result;
        """)
        if nav_result:
            print(f"  JS 메뉴 발견: {nav_result}")
    except:
        pass

    # 전체 페이지 소스 저장 (분석용)
    with open(os.path.join(SS_DIR, "full_manage_source.html"), 'w', encoding='utf-8') as f:
        f.write(driver.page_source)

    # ── [5] 스크린샷 텔레그램 전송 ──
    driver.save_screenshot(os.path.join(SS_DIR, "manage_explore.png"))
    send_tg(photo=os.path.join(SS_DIR, "manage_explore.png"), caption="블로그 관리 탐색 결과")

    # 관리 페이지 구조 정보 전송
    info = f"""🔍 블로그 관리 구조 분석:
URL: {driver.current_url}
메뉴: {len(menu_items)}개
링크: {len(admin_links)}개
꾸미기 관련: {[k for k in admin_links if any(x in k for x in ['꾸미기', '레이아웃', '위젯', '스킨'])]}"""
    send_tg(msg=info)

    # ── [6] 최종 블로그 상태 ──
    print("\n[6] 현재 블로그 상태...")
    driver.get(f"https://blog.naver.com/{BLOG_ID}")
    time.sleep(4)
    driver.save_screenshot(os.path.join(SS_DIR, "blog_current.png"))
    send_tg(photo=os.path.join(SS_DIR, "blog_current.png"), caption="현재 블로그 상태")

    print("✅ 탐색 완료!")

except Exception as e:
    print(f"\n❌ 오류: {e}")
    import traceback
    traceback.print_exc()
    try:
        driver.save_screenshot(os.path.join(SS_DIR, "error.png"))
        send_tg(msg=f"❌ {str(e)[:200]}")
    except:
        pass

finally:
    # Chrome은 유지 (이후 작업용)
    print("스크립트 종료")
