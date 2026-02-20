"""Google Drive OAuth - 수동 인증 방식 (redirect 없이)"""
import os, sys, json, io, webbrowser, urllib.parse, urllib.request
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / '.env')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

CLIENT_ID = os.getenv('DRIVE_CLIENT_ID', '')
CLIENT_SECRET = os.getenv('DRIVE_CLIENT_SECRET', '')
SCOPES = 'https://www.googleapis.com/auth/drive'
TOKEN_PATH = Path(__file__).parent / "drive_token.json"
REDIRECT_URI = 'http://localhost:8090'

auth_code = None

class AuthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global auth_code
        query = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(query)

        if 'code' in params:
            auth_code = params['code'][0]
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write('<html><body><h1>인증 성공! 이 창을 닫아주세요.</h1></body></html>'.encode('utf-8'))
        elif 'error' in params:
            self.send_response(400)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            err = params.get('error', ['unknown'])[0]
            self.wfile.write(f'<html><body><h1>에러: {err}</h1></body></html>'.encode('utf-8'))
        else:
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            self.wfile.write(b'<html><body>Waiting...</body></html>')

    def log_message(self, format, *args):
        pass  # Suppress logs

def get_token():
    global auth_code

    # Check existing token
    if TOKEN_PATH.exists():
        token = json.loads(TOKEN_PATH.read_text(encoding='utf-8'))
        if token.get('token'):
            # Try refresh
            if token.get('refresh_token'):
                try:
                    data = urllib.parse.urlencode({
                        'client_id': CLIENT_ID,
                        'client_secret': CLIENT_SECRET,
                        'refresh_token': token['refresh_token'],
                        'grant_type': 'refresh_token'
                    }).encode()
                    req = urllib.request.Request('https://oauth2.googleapis.com/token', data=data, method='POST')
                    resp = json.loads(urllib.request.urlopen(req).read())
                    token['token'] = resp['access_token']
                    if 'refresh_token' in resp:
                        token['refresh_token'] = resp['refresh_token']
                    TOKEN_PATH.write_text(json.dumps(token), encoding='utf-8')
                    print("Token refreshed successfully!")
                    return token['token']
                except Exception as e:
                    print(f"Refresh failed: {e}")
            else:
                return token['token']

    # Start local server
    server = HTTPServer(('localhost', 8090), AuthHandler)
    server_thread = threading.Thread(target=server.handle_request)
    server_thread.daemon = True
    server_thread.start()

    # Open browser for auth
    auth_url = (
        'https://accounts.google.com/o/oauth2/v2/auth?'
        f'client_id={CLIENT_ID}'
        f'&redirect_uri={urllib.parse.quote(REDIRECT_URI)}'
        '&response_type=code'
        f'&scope={urllib.parse.quote(SCOPES)}'
        '&access_type=offline'
        '&prompt=consent'
    )

    print(f"\n브라우저에서 Google 로그인해주세요...")
    print(f"URL: {auth_url[:80]}...")
    webbrowser.open(auth_url)

    # Wait for callback
    server_thread.join(timeout=120)
    server.server_close()

    if not auth_code:
        print("ERROR: 인증 시간 초과 (120초)")
        sys.exit(1)

    # Exchange code for token
    data = urllib.parse.urlencode({
        'code': auth_code,
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'redirect_uri': REDIRECT_URI,
        'grant_type': 'authorization_code'
    }).encode()

    req = urllib.request.Request('https://oauth2.googleapis.com/token', data=data, method='POST')
    resp = json.loads(urllib.request.urlopen(req).read())

    token = {
        'token': resp['access_token'],
        'refresh_token': resp.get('refresh_token', ''),
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET
    }
    TOKEN_PATH.write_text(json.dumps(token), encoding='utf-8')
    print(f"Token saved: {TOKEN_PATH}")

    # Copy to shorts_factory
    import shutil
    shorts = Path(__file__).parent / "shorts_factory" / "drive_token.json"
    shutil.copy2(str(TOKEN_PATH), str(shorts))
    print("Token copied to shorts_factory")

    return token['token']

if __name__ == '__main__':
    print("=" * 50)
    print("  Google Drive OAuth 인증")
    print("=" * 50)
    token = get_token()
    print(f"\nAccess token: {token[:20]}...")
    print("인증 완료!")
