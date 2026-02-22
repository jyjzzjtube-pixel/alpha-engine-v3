# -*- coding: utf-8 -*-
"""Chrome에서 네이버 쿠키 추출"""
import sys, os, sqlite3, json, base64, ctypes, ctypes.wintypes, pickle
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

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

# AES 키
with open(r'C:\Users\jyjzz\AppData\Local\Google\Chrome\User Data\Local State', 'r') as f:
    local_state = json.load(f)
enc_key = base64.b64decode(local_state['os_crypt']['encrypted_key'])[5:]
aes_key = dpapi_decrypt(enc_key)
print(f'AES key: {len(aes_key)} bytes' if aes_key else 'FAIL')

# Win32 API로 잠긴 쿠키 파일 읽기
kernel32 = ctypes.windll.kernel32
GENERIC_READ = 0x80000000
ALL_SHARE = 0x07  # READ|WRITE|DELETE
OPEN_EXISTING = 3

src = r'C:\Users\jyjzz\AppData\Local\Google\Chrome\User Data\Default\Network\Cookies'
handle = kernel32.CreateFileW(src, GENERIC_READ, ALL_SHARE, None, OPEN_EXISTING, 0, None)

if handle == ctypes.c_void_p(-1).value or handle == -1:
    print(f'File open FAIL')
    sys.exit(1)

size = kernel32.GetFileSize(handle, None)
buf = ctypes.create_string_buffer(size)
read = ctypes.c_ulong(0)
kernel32.ReadFile(handle, buf, size, ctypes.byref(read), None)
kernel32.CloseHandle(handle)

dst = r'C:\Users\jyjzz\AppData\Local\Temp\cookies_copy.db'
with open(dst, 'wb') as f:
    f.write(buf.raw[:read.value])
print(f'Cookie DB: {read.value} bytes')

# 복호화
from Cryptodome.Cipher import AES
conn = sqlite3.connect(dst)
cur = conn.cursor()
cur.execute('SELECT name, encrypted_value, host_key FROM cookies WHERE host_key LIKE "%naver%"')
rows = cur.fetchall()
print(f'Naver cookies: {len(rows)}')

cookies = {}
for name, enc_val, host in rows:
    if len(enc_val) > 15 and enc_val[:3] in (b'v10', b'v20'):
        nonce = enc_val[3:15]
        ct = enc_val[15:-16]
        tag = enc_val[-16:]
        try:
            cipher = AES.new(aes_key, AES.MODE_GCM, nonce=nonce)
            dec = cipher.decrypt_and_verify(ct, tag).decode('utf-8', errors='replace')
            cookies[name] = {'value': dec, 'domain': host}
        except:
            pass

conn.close()
os.remove(dst)
print(f'Decrypted: {len(cookies)}')
for k, v in list(cookies.items())[:15]:
    val = v['value'][:25] + '...' if len(v['value']) > 25 else v['value']
    print(f'  {v["domain"]} | {k} = {val}')

with open(r'C:\Users\jyjzz\AppData\Local\Temp\naver_cookies.pkl', 'wb') as f:
    pickle.dump(cookies, f)
print('Saved!')
