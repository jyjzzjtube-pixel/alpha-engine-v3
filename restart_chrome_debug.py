# -*- coding: utf-8 -*-
"""Chrome을 remote debugging 모드로 재시작 (세션 복원 포함)"""
import sys, time, os, subprocess, json, urllib.request
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# 1. Chrome 종료
print("Chrome 종료 중...")
subprocess.run(['taskkill', '/F', '/IM', 'chrome.exe'], capture_output=True)
time.sleep(3)

# 2. Lock 파일 제거
profile = r'C:\Users\jyjzz\AppData\Local\Google\Chrome\User Data'
for f in ['SingletonLock', 'SingletonSocket', 'SingletonCookie', 'lockfile', 'DevToolsActivePort']:
    try:
        os.remove(os.path.join(profile, f))
    except:
        pass

# 3. Chrome 설정에서 세션 복원 활성화 (이전 탭 복원)
prefs_file = os.path.join(profile, 'Default', 'Preferences')
try:
    with open(prefs_file, 'r', encoding='utf-8') as f:
        prefs = json.load(f)
    # startup에서 이전 탭 복원 설정
    if 'session' not in prefs:
        prefs['session'] = {}
    prefs['session']['restore_on_startup'] = 1  # 1 = restore last session
    with open(prefs_file, 'w', encoding='utf-8') as f:
        json.dump(prefs, f)
    print("세션 복원 설정 완료")
except Exception as e:
    print(f"Preferences 수정 실패: {e}")

# 4. Chrome을 remote debugging 모드로 시작 (기존 프로필)
chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

# 먼저 Chrome shortcut에 argument 추가하는 대신, 직접 실행
chrome_proc = subprocess.Popen([
    chrome_path,
    f'--user-data-dir={profile}',
    '--profile-directory=Default',
    '--remote-debugging-port=9222',
    '--restore-last-session',
    '--window-size=1400,900',
    '--no-first-run',
    '--no-default-browser-check',
], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

print(f"Chrome PID: {chrome_proc.pid}")

# 5. 포트 확인
time.sleep(8)
port_ok = False

# DevToolsActivePort 파일 확인
port_file = os.path.join(profile, 'DevToolsActivePort')
actual_port = 9222

if os.path.exists(port_file):
    with open(port_file, 'r') as f:
        content = f.read().strip()
    actual_port = int(content.split('\n')[0])
    print(f"DevToolsActivePort: {actual_port}")

for i in range(15):
    try:
        resp = urllib.request.urlopen(f'http://127.0.0.1:{actual_port}/json/version', timeout=3)
        data = json.loads(resp.read())
        print(f"Port {actual_port} OK! Browser: {data.get('Browser')}")
        port_ok = True
        break
    except:
        # Also try 9222
        if actual_port != 9222:
            try:
                resp = urllib.request.urlopen('http://127.0.0.1:9222/json/version', timeout=2)
                actual_port = 9222
                port_ok = True
                print(f"Port 9222 OK!")
                break
            except:
                pass
        time.sleep(2)
        print(f"Wait {i+1}/15...")

if port_ok:
    # Tabs 확인
    resp = urllib.request.urlopen(f'http://127.0.0.1:{actual_port}/json', timeout=3)
    tabs = json.loads(resp.read())
    print(f"\nTabs: {len(tabs)}")
    for t in tabs:
        print(f"  {t.get('url', '?')[:80]}")

    print(f"\n✅ Chrome debugging port: {actual_port}")
    print("Selenium으로 연결 가능!")
else:
    print("\n❌ Chrome debugging port 실패")
    poll = chrome_proc.poll()
    print(f"Chrome alive: {poll is None}")
