# -*- coding: utf-8 -*-
"""네이버 블로그 관리자 URL 탐색"""
import sys, time, os, subprocess, shutil, json
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
import urllib.request

SS_DIR = r"C:\Users\jyjzz\OneDrive\바탕 화면\franchise-db\affiliate_system\renders\blog_widgets"
BLOG_ID = "jyjzzj"

from dotenv import load_dotenv
load_dotenv(r"C:\Users\jyjzz\OneDrive\바탕 화면\franchise-db\.env", override=True)

def send_tg(msg=None, photo=None, caption=None):
    import requests
    t = os.getenv('TELEGRAM_BOT_TOKEN')
    c = os.getenv('TELEGRAM_CHAT_ID')
    b = f'https://api.telegram.org/bot{t}'
    if msg:
        requests.post(f'{b}/sendMessage', data={'chat_id': c, 'text': msg})
    if photo and os.path.exists(photo):
        with open(photo, 'rb') as f:
            requests.post(f'{b}/sendPhoto', data={'chat_id': c, 'caption': caption or ''},
                         files={'photo': (os.path.basename(photo), f, 'image/png')})

# Chrome 종료 & 시작
subprocess.run(['taskkill', '/F', '/IM', 'chrome.exe'], capture_output=True)
subprocess.run(['taskkill', '/F', '/IM', 'chromedriver.exe'], capture_output=True)
time.sleep(3)

SRC_PROFILE = r"C:\Users\jyjzz\AppData\Local\Google\Chrome\User Data"
TMP_PROFILE = r"C:\Users\jyjzz\AppData\Local\Temp\chrome_naver"

# 프로필 복사
if os.path.exists(TMP_PROFILE):
    shutil.rmtree(TMP_PROFILE, ignore_errors=True)
os.makedirs(TMP_PROFILE, exist_ok=True)

shutil.copy2(os.path.join(SRC_PROFILE, "Local State"), os.path.join(TMP_PROFILE, "Local State"))
src_default = os.path.join(SRC_PROFILE, "Default")
dst_default = os.path.join(TMP_PROFILE, "Default")
os.makedirs(os.path.join(dst_default, "Network"), exist_ok=True)

for f in ["Network/Cookies", "Network/Cookies-journal", "Login Data", "Login Data-journal", "Preferences", "Secure Preferences", "Web Data"]:
    try:
        shutil.copy2(os.path.join(src_default, f), os.path.join(dst_default, f))
    except:
        pass

chrome_proc = subprocess.Popen([
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    f"--user-data-dir={TMP_PROFILE}",
    "--profile-directory=Default",
    "--remote-debugging-port=9222",
    "--window-size=1400,900",
    "--disable-gpu",
    "--no-first-run",
    "--no-default-browser-check",
    "about:blank"
], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(7)

# Port 확인
for i in range(10):
    try:
        resp = urllib.request.urlopen("http://127.0.0.1:9222/json/version", timeout=3)
        print("Port OK!")
        break
    except:
        time.sleep(2)

opts = Options()
opts.add_experimental_option("debuggerAddress", "127.0.0.1:9222")
driver = webdriver.Chrome(options=opts)
print(f"연결: {driver.current_url}")

# ── 관리자 URL 탐색 ──
urls_to_try = [
    "https://admin.blog.naver.com/",
    f"https://admin.blog.naver.com/{BLOG_ID}",
    f"https://admin.blog.naver.com/home?blogId={BLOG_ID}",
    f"https://blog.naver.com/BlogSettingMain.naver?blogId={BLOG_ID}",
    f"https://blog.naver.com/{BLOG_ID}/manage",
    f"https://blog.naver.com/{BLOG_ID}/admin",
    "https://blog.naver.com/manage/home",
    f"https://admin.blog.naver.com/settings?blogId={BLOG_ID}",
]

results = []
for url in urls_to_try:
    driver.get(url)
    time.sleep(3)
    cur = driver.current_url
    title = driver.title
    has_login = "nid.naver.com" in cur or "login" in cur.lower()
    result = f"{'❌' if has_login else '✅'} {url[:60]} → {cur[:70]} | {title[:30]}"
    print(result)
    results.append(result)

    if not has_login and "error" not in title.lower() and "페이지 주소" not in driver.page_source[:500]:
        driver.save_screenshot(os.path.join(SS_DIR, f"admin_found.png"))
        print("  ✅ 유효한 관리 페이지 발견!")

        # 이 페이지에서 링크 수집
        links = driver.find_elements(By.TAG_NAME, "a")
        print(f"  링크: {len(links)}개")
        for link in links[:30]:
            href = link.get_attribute('href') or ''
            txt = link.text.strip()[:30]
            if href and ('admin' in href or 'setting' in href.lower() or 'skin' in href.lower() or 'layout' in href.lower() or 'widget' in href.lower() or '꾸미기' in txt or '레이아웃' in txt or '위젯' in txt or '타이틀' in txt):
                print(f"    {txt} → {href[:80]}")

# 네이버 로그인 확인을 위해 네이버 메인 접근
driver.get("https://www.naver.com")
time.sleep(3)
driver.save_screenshot(os.path.join(SS_DIR, "naver_main.png"))

# 로그인 상태 확인 (프로필 아이콘 또는 로그인 버튼)
login_btns = driver.find_elements(By.XPATH, "//a[contains(@href, 'nid.naver.com')]|//button[contains(text(), '로그인')]")
print(f"\n네이버 메인 로그인 버튼: {len(login_btns)}개")
if login_btns:
    print("  → 로그인 안됨 (쿠키 복사 실패)")
else:
    print("  → 로그인됨!")

# 블로그 관리자 메인
driver.get(f"https://admin.blog.naver.com/{BLOG_ID}")
time.sleep(5)
driver.save_screenshot(os.path.join(SS_DIR, "admin_main.png"))
print(f"\n관리자 메인: {driver.current_url}")
print(f"제목: {driver.title}")

# 페이지 소스 일부 확인
page_src = driver.page_source
with open(os.path.join(SS_DIR, "admin_main.html"), 'w', encoding='utf-8') as f:
    f.write(page_src[:100000])
print(f"페이지 소스 저장: {len(page_src)}자")

# 주요 링크 모두 출력
links = driver.find_elements(By.TAG_NAME, "a")
print(f"\n모든 링크 ({len(links)}개):")
for link in links[:50]:
    href = link.get_attribute('href') or ''
    txt = link.text.strip()[:40]
    if href and txt:
        print(f"  {txt} → {href[:80]}")

# 텔레그램
send_tg(msg="\n".join(results[:10]))
send_tg(photo=os.path.join(SS_DIR, "admin_main.png"), caption=f"블로그 관리자: {driver.current_url[:80]}")

print("\n탐색 완료!")
