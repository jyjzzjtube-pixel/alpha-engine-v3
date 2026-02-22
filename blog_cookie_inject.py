# -*- coding: utf-8 -*-
"""네이버 쿠키 추출 후 Selenium에 주입"""
import sys, time, os, subprocess, json, sqlite3, base64, ctypes, ctypes.wintypes, shutil
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# ── 1. Chrome 종료 확인 ──
subprocess.run(['taskkill', '/F', '/IM', 'chrome.exe'], capture_output=True)
subprocess.run(['taskkill', '/F', '/IM', 'chromedriver.exe'], capture_output=True)
time.sleep(3)

# ── 2. DPAPI 복호화 ──
class DATA_BLOB(ctypes.Structure):
    _fields_ = [('cbData', ctypes.wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_char))]

def dpapi_decrypt(encrypted):
    blob_in = DATA_BLOB(len(encrypted), ctypes.create_string_buffer(encrypted, len(encrypted)))
    blob_out = DATA_BLOB()
    if ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)):
        data = ctypes.string_at(blob_out.pbData, blob_out.cbData)
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)
        return data
    return None

# ── 3. AES 키 추출 ──
with open(r'C:\Users\jyjzz\AppData\Local\Google\Chrome\User Data\Local State', 'r') as f:
    local_state = json.load(f)
enc_key = base64.b64decode(local_state['os_crypt']['encrypted_key'])[5:]
aes_key = dpapi_decrypt(enc_key)
print(f'AES key: {len(aes_key) if aes_key else 0} bytes')

# ── 4. 쿠키 DB 복사 (Chrome 종료 상태이므로 가능) ──
src_cookies = r'C:\Users\jyjzz\AppData\Local\Google\Chrome\User Data\Default\Network\Cookies'
tmp_cookies = r'C:\Users\jyjzz\AppData\Local\Temp\cookies_extract.db'

try:
    shutil.copy2(src_cookies, tmp_cookies)
    print(f'Cookies DB 복사 완료')
except Exception as e:
    print(f'직접 복사 실패: {e}')
    # Win32 API 시도
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateFileW(src_cookies, 0x80000000, 7, None, 3, 0, None)
    if handle != ctypes.c_void_p(-1).value:
        size = kernel32.GetFileSize(handle, None)
        buf = ctypes.create_string_buffer(size)
        read = ctypes.c_ulong(0)
        kernel32.ReadFile(handle, buf, size, ctypes.byref(read), None)
        kernel32.CloseHandle(handle)
        with open(tmp_cookies, 'wb') as f:
            f.write(buf.raw[:read.value])
        print(f'Win32 복사: {read.value} bytes')
    else:
        print('Win32도 실패!')
        sys.exit(1)

# ── 5. 네이버 쿠키 복호화 ──
from Cryptodome.Cipher import AES

conn = sqlite3.connect(tmp_cookies)
cur = conn.cursor()
cur.execute('SELECT name, encrypted_value, host_key, path, is_secure, expires_utc, is_httponly FROM cookies WHERE host_key LIKE "%naver%"')
rows = cur.fetchall()
print(f'네이버 쿠키: {len(rows)}개')

naver_cookies = []
for name, enc_val, host, path, secure, expires, httponly in rows:
    value = ''
    if len(enc_val) > 15 and enc_val[:3] in (b'v10', b'v20'):
        nonce = enc_val[3:15]
        ct = enc_val[15:-16]
        tag = enc_val[-16:]
        try:
            cipher = AES.new(aes_key, AES.MODE_GCM, nonce=nonce)
            value = cipher.decrypt_and_verify(ct, tag).decode('utf-8', errors='replace')
        except:
            continue
    elif enc_val:
        value = enc_val.decode('utf-8', errors='replace')

    if value:
        naver_cookies.append({
            'name': name,
            'value': value,
            'domain': host,
            'path': path,
            'secure': bool(secure),
            'httpOnly': bool(httponly),
        })

conn.close()
os.remove(tmp_cookies)
print(f'복호화 성공: {len(naver_cookies)}개')

# 주요 쿠키 출력
for c in naver_cookies:
    val = c['value'][:20] + '...' if len(c['value']) > 20 else c['value']
    print(f"  {c['domain']} | {c['name']} = {val}")

# NID_AUT, NID_SES 확인
important = ['NID_AUT', 'NID_SES', 'NID_JKL', 'nid_inf']
found_important = [c['name'] for c in naver_cookies if c['name'] in important]
print(f'\n중요 쿠키: {found_important}')

if 'NID_AUT' not in found_important:
    print('❌ NID_AUT 없음 - 네이버 로그인 안됨')
    # 텔레그램으로 알림
    from dotenv import load_dotenv
    load_dotenv(r"C:\Users\jyjzz\OneDrive\바탕 화면\franchise-db\.env", override=True)
    import requests
    t = os.getenv('TELEGRAM_BOT_TOKEN')
    c_id = os.getenv('TELEGRAM_CHAT_ID')
    requests.post(f'https://api.telegram.org/bot{t}/sendMessage',
                  data={'chat_id': c_id, 'text': '❌ 네이버 로그인 쿠키가 없습니다.\nChrome에서 네이버 로그인 후 다시 실행해주세요.'})
    sys.exit(1)

# ── 6. Selenium 시작 + 쿠키 주입 ──
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

SS_DIR = r"C:\Users\jyjzz\OneDrive\바탕 화면\franchise-db\affiliate_system\renders\blog_widgets"
TITLE_IMG = os.path.join(SS_DIR, "title_combined.jpg")
BLOG_ID = "jyjzzj"

from dotenv import load_dotenv
load_dotenv(r"C:\Users\jyjzz\OneDrive\바탕 화면\franchise-db\.env", override=True)

def send_tg(msg=None, photo=None, caption=None):
    import requests
    t = os.getenv('TELEGRAM_BOT_TOKEN')
    c_id = os.getenv('TELEGRAM_CHAT_ID')
    b = f'https://api.telegram.org/bot{t}'
    if msg:
        requests.post(f'{b}/sendMessage', data={'chat_id': c_id, 'text': msg})
    if photo and os.path.exists(photo):
        with open(photo, 'rb') as f:
            requests.post(f'{b}/sendPhoto', data={'chat_id': c_id, 'caption': caption or ''},
                         files={'photo': (os.path.basename(photo), f, 'image/png')})

opts = Options()
opts.add_argument("--window-size=1400,900")
opts.add_argument("--disable-gpu")
opts.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])

print('\nChrome 시작 (새 프로필)...')
driver = webdriver.Chrome(options=opts)

# naver.com에 먼저 접근 (쿠키 설정을 위해 도메인 필요)
driver.get("https://www.naver.com")
time.sleep(2)

# 쿠키 주입
injected = 0
for cookie in naver_cookies:
    try:
        # domain이 .naver.com인 쿠키만
        domain = cookie['domain']
        if not domain.endswith('naver.com'):
            continue

        selenium_cookie = {
            'name': cookie['name'],
            'value': cookie['value'],
            'domain': domain,
            'path': cookie['path'],
            'secure': cookie['secure'],
        }
        driver.add_cookie(selenium_cookie)
        injected += 1
    except Exception as e:
        pass

print(f'쿠키 주입: {injected}개')

# 새로고침으로 로그인 확인
driver.get("https://www.naver.com")
time.sleep(3)
driver.save_screenshot(os.path.join(SS_DIR, "naver_check.png"))

# 로그인 확인
page_src = driver.page_source
if 'gnb_my' in page_src or 'MyView' in page_src or 'log.nhn' in page_src:
    print('✅ 네이버 로그인 확인!')
    send_tg(photo=os.path.join(SS_DIR, "naver_check.png"), caption="✅ 네이버 로그인 성공!")
else:
    print('❌ 로그인 실패')
    send_tg(photo=os.path.join(SS_DIR, "naver_check.png"), caption="❌ 쿠키 주입했지만 로그인 안됨")
    driver.quit()
    sys.exit(1)

# ── 7. 블로그 관리 접근 ──
try:
    print('\n[2] 블로그 관리...')

    # 블로그 관리 페이지 URL 탐색
    admin_urls = [
        f"https://blog.naver.com/{BLOG_ID}/manage",
        f"https://blog.naver.com/BlogSettingMain.naver?blogId={BLOG_ID}",
        f"https://admin.blog.naver.com/{BLOG_ID}",
    ]

    admin_ok = False
    for url in admin_urls:
        driver.get(url)
        time.sleep(5)
        cur = driver.current_url
        title = driver.title
        print(f"  {url[:60]} → {cur[:60]} | {title[:30]}")

        if "nid.naver.com" not in cur and "login" not in cur.lower():
            admin_ok = True
            driver.save_screenshot(os.path.join(SS_DIR, "admin_page.png"))
            send_tg(photo=os.path.join(SS_DIR, "admin_page.png"), caption=f"관리 페이지: {cur[:60]}")

            # 페이지 구조 분석
            iframes = driver.find_elements(By.TAG_NAME, "iframe")
            print(f"  iframe: {len(iframes)}개")
            for idx, ifr in enumerate(iframes):
                src = ifr.get_attribute('src') or ''
                fid = ifr.get_attribute('id') or ''
                print(f"    [{idx}] id={fid}, src={src[:80]}")

            # 페이지 소스 저장
            with open(os.path.join(SS_DIR, "admin_source.html"), 'w', encoding='utf-8') as f:
                f.write(driver.page_source[:100000])

            # 관리 메뉴 링크 찾기
            all_links = driver.find_elements(By.TAG_NAME, "a")
            print(f"  링크: {len(all_links)}개")
            for link in all_links[:50]:
                href = link.get_attribute('href') or ''
                txt = link.text.strip()[:40]
                if txt and href:
                    print(f"    {txt} → {href[:80]}")
            break

    if not admin_ok:
        print("관리 페이지 접근 실패")
        send_tg(msg="❌ 블로그 관리 페이지 접근 실패")

    # ── 꾸미기/레이아웃 설정 찾기 ──
    print('\n[3] 꾸미기 설정 찾기...')

    # 네이버 블로그 새 관리자에서 꾸미기 관련 URL
    deco_urls = [
        f"https://blog.naver.com/{BLOG_ID}/manage/layout",
        f"https://blog.naver.com/{BLOG_ID}/manage/design",
        f"https://blog.naver.com/{BLOG_ID}/manage/skin",
        f"https://blog.naver.com/{BLOG_ID}/manage/widget",
        f"https://blog.naver.com/{BLOG_ID}/manage/decoration",
        f"https://blog.naver.com/manage/layout?blogId={BLOG_ID}",
        f"https://blog.naver.com/manage/design?blogId={BLOG_ID}",
    ]

    for url in deco_urls:
        driver.get(url)
        time.sleep(3)
        cur = driver.current_url
        title = driver.title
        has_error = "페이지 주소" in driver.page_source[:500] or "error" in title.lower()
        status = "❌" if has_error or "login" in cur.lower() else "✅"
        print(f"  {status} {url.split('/')[-1][:30]} → {cur[:60]} | err={has_error}")

        if status == "✅" and not has_error:
            driver.save_screenshot(os.path.join(SS_DIR, f"deco_{url.split('/')[-1][:20]}.png"))
            send_tg(photo=os.path.join(SS_DIR, f"deco_{url.split('/')[-1][:20]}.png"),
                    caption=f"꾸미기: {url.split('/')[-1]}")

    # 최종 결과
    driver.get(f"https://blog.naver.com/{BLOG_ID}")
    time.sleep(4)
    driver.save_screenshot(os.path.join(SS_DIR, "final.png"))
    send_tg(photo=os.path.join(SS_DIR, "final.png"), caption="블로그 현재 상태")

except Exception as e:
    print(f'오류: {e}')
    import traceback
    traceback.print_exc()
    try:
        driver.save_screenshot(os.path.join(SS_DIR, "error.png"))
        send_tg(msg=f"❌ {str(e)[:200]}")
    except:
        pass

finally:
    driver.quit()
    print('종료')
