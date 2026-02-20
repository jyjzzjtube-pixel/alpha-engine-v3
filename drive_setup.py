"""Google Drive OAuth + 전체 프로젝트 자동 분류/폴더 정리"""
import os, sys, json, io, shutil
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# .env 로드
env_path = Path(__file__).parent / "shorts_factory" / ".env"
if env_path.exists():
    for line in env_path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            k, v = k.strip(), v.strip()
            if v and not os.environ.get(k):
                os.environ[k] = v

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

SCOPES = ['https://www.googleapis.com/auth/drive.file']
TOKEN_PATH = Path(__file__).parent / "drive_token.json"

def get_drive_service():
    creds = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except:
                creds = None

        if not creds or not creds.valid:
            cid = os.environ.get("DRIVE_CLIENT_ID", "")
            csec = os.environ.get("DRIVE_CLIENT_SECRET", "")
            if not cid or not csec:
                print("ERROR: DRIVE_CLIENT_ID / DRIVE_CLIENT_SECRET not set")
                sys.exit(1)

            client_config = {
                "installed": {
                    "client_id": cid,
                    "client_secret": csec,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": ["http://localhost:8090/"]
                }
            }
            flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
            print("\n*** 브라우저에서 Google 계정으로 로그인해주세요 ***\n")
            creds = flow.run_local_server(port=8090, open_browser=True)

        TOKEN_PATH.write_text(creds.to_json(), encoding='utf-8')
        print(f"Token saved: {TOKEN_PATH}")

    # shorts_factory에도 토큰 복사
    shorts_token = Path(__file__).parent / "shorts_factory" / "drive_token.json"
    if TOKEN_PATH.exists():
        shutil.copy2(str(TOKEN_PATH), str(shorts_token))
        print(f"Token copied to shorts_factory")

    return build('drive', 'v3', credentials=creds)

def find_or_create_folder(svc, name, parent_id=None):
    """폴더 찾기 또는 생성"""
    q = f"name='{name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    if parent_id:
        q += f" and '{parent_id}' in parents"

    r = svc.files().list(q=q, spaces='drive', fields='files(id,name)').execute()
    if r.get('files'):
        return r['files'][0]['id']

    meta = {'name': name, 'mimeType': 'application/vnd.google-apps.folder'}
    if parent_id:
        meta['parents'] = [parent_id]

    f = svc.files().create(body=meta, fields='id').execute()
    print(f"  Created folder: {name}")
    return f['id']

def upload_file(svc, local_path, folder_id, filename=None):
    """파일 업로드 (동일 이름 존재 시 업데이트)"""
    fname = filename or os.path.basename(local_path)

    # 기존 파일 확인
    q = f"name='{fname}' and '{folder_id}' in parents and trashed=false"
    existing = svc.files().list(q=q, spaces='drive', fields='files(id)').execute().get('files', [])

    ext = Path(local_path).suffix.lower()
    mime_map = {
        '.html': 'text/html', '.js': 'application/javascript', '.css': 'text/css',
        '.json': 'application/json', '.py': 'text/x-python', '.md': 'text/markdown',
        '.txt': 'text/plain', '.png': 'image/png', '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg', '.gif': 'image/gif', '.svg': 'image/svg+xml',
        '.mp4': 'video/mp4', '.mp3': 'audio/mpeg', '.wav': 'audio/wav',
        '.env': 'text/plain', '.yml': 'text/yaml', '.yaml': 'text/yaml',
    }
    mime = mime_map.get(ext, 'application/octet-stream')
    media = MediaFileUpload(local_path, mimetype=mime, resumable=True)

    if existing:
        # 업데이트
        svc.files().update(fileId=existing[0]['id'], media_body=media).execute()
        return existing[0]['id']
    else:
        # 새로 생성
        meta = {'name': fname, 'parents': [folder_id]}
        r = svc.files().create(body=meta, media_body=media, fields='id').execute()
        return r['id']

def upload_directory(svc, local_dir, drive_folder_id, exclude=None):
    """디렉토리 전체 업로드 (재귀)"""
    exclude = exclude or {'.git', 'node_modules', '__pycache__', '.env', 'venv', 'uploads', 'logs', 'output', '.gitignore'}
    count = 0

    for item in sorted(Path(local_dir).iterdir()):
        if item.name in exclude or item.name.startswith('.'):
            continue

        if item.is_dir():
            sub_id = find_or_create_folder(svc, item.name, drive_folder_id)
            count += upload_directory(svc, str(item), sub_id, exclude)
        elif item.is_file() and item.stat().st_size < 50 * 1024 * 1024:  # 50MB limit
            try:
                upload_file(svc, str(item), drive_folder_id)
                count += 1
            except Exception as e:
                print(f"    SKIP {item.name}: {e}")

    return count

def main():
    print("=" * 60)
    print("  Google Drive 자동 분류 & 폴더 정리")
    print("=" * 60)

    # 1. Drive 연결
    print("\n[1] Drive 연결 중...")
    svc = get_drive_service()
    print("  Drive 연결 성공!")

    # 2. 루트 폴더 생성
    print("\n[2] 폴더 구조 생성 중...")
    root_id = find_or_create_folder(svc, "YJ Partners - 전체 프로젝트")

    # 폴더 구조 설계
    folders = {
        "01_배포사이트": {
            "desc": "GitHub Pages 배포된 웹사이트",
            "sub": {
                "Alpha Engine v4 (주식분석)": None,
                "YJ Tax Master v7 (세무)": None,
                "제안서 시뮬레이터 (wonwill)": None,
                "파운더원 홈페이지": None,
                "통합DB 자동화": None,
                "네이버 블로그 마스터": None,
            }
        },
        "02_서버프로그램": {
            "desc": "로컬 서버 실행 프로그램",
            "sub": {
                "Shorts Factory v8": None,
            }
        },
        "03_API키_설정": {
            "desc": "API 키 관리 문서",
            "sub": {}
        },
        "04_백업": {
            "desc": "프로젝트 백업",
            "sub": {
                "소스코드": None,
                "설정파일": None,
            }
        }
    }

    folder_ids = {}
    for cat_name, cat_info in folders.items():
        cat_id = find_or_create_folder(svc, cat_name, root_id)
        folder_ids[cat_name] = cat_id
        for sub_name in cat_info.get("sub", {}).keys():
            sub_id = find_or_create_folder(svc, sub_name, cat_id)
            folder_ids[f"{cat_name}/{sub_name}"] = sub_id

    print("  폴더 구조 생성 완료!")

    # 3. 프로젝트 파일 업로드
    print("\n[3] 프로젝트 파일 업로드 중...")

    base = Path(r"C:\Users\jyjzz\OneDrive\바탕 화면")

    projects = [
        {
            "name": "Alpha Engine v4 (주식분석)",
            "category": "01_배포사이트",
            "path": base / "franchise-db",
            "files": ["alpha-v4.html", "index.html"],
            "url": "https://jyjzzjtube-pixel.github.io/alpha-engine-v3/"
        },
        {
            "name": "YJ Tax Master v7 (세무)",
            "category": "01_배포사이트",
            "path": base / "franchise-db" / "yjtax_v8_extracted",
            "files": ["index.html"],
            "url": "https://jyjzzjtube-pixel.github.io/yjtax-v8/"
        },
        {
            "name": "제안서 시뮬레이터 (wonwill)",
            "category": "01_배포사이트",
            "path": base / "franchise-db" / "wonwill_app",
            "files": ["index.html"],
            "url": "https://jyjzzjtube-pixel.github.io/wonwill-app/"
        },
        {
            "name": "파운더원 홈페이지",
            "category": "01_배포사이트",
            "path": base / "founderone_site",
            "files": None,  # 전체 폴더 업로드
            "url": "https://jyjzzjtube-pixel.github.io/founderone-site/"
        },
        {
            "name": "통합DB 자동화",
            "category": "01_배포사이트",
            "path": base / "yj-db-automation",
            "files": ["index.html", "DB자동화.html", "DB자동화_모바일.html"],
            "url": "https://jyjzzjtube-pixel.github.io/yj-db-automation/"
        },
        {
            "name": "네이버 블로그 마스터",
            "category": "01_배포사이트",
            "path": base / "naver-blog-master",
            "files": ["index.html"],
            "url": "https://jyjzzjtube-pixel.github.io/naver-blog-master/"
        },
        {
            "name": "Shorts Factory v8",
            "category": "02_서버프로그램",
            "path": base / "franchise-db" / "shorts_factory",
            "files": None,  # 전체 폴더
            "url": "http://localhost:5000"
        },
    ]

    total_files = 0
    for proj in projects:
        folder_key = f"{proj['category']}/{proj['name']}"
        fid = folder_ids.get(folder_key)
        if not fid:
            print(f"  SKIP {proj['name']}: folder not found")
            continue

        print(f"\n  >> {proj['name']}")
        print(f"     URL: {proj['url']}")

        # README 생성
        readme = f"# {proj['name']}\n\nURL: {proj['url']}\n\nCategory: {proj['category']}\n"
        readme_path = Path(__file__).parent / "_temp_readme.md"
        readme_path.write_text(readme, encoding='utf-8')
        upload_file(svc, str(readme_path), fid, "README.md")
        readme_path.unlink()

        if proj['files']:
            # 특정 파일만 업로드
            for fname in proj['files']:
                fpath = proj['path'] / fname
                if fpath.exists():
                    upload_file(svc, str(fpath), fid)
                    total_files += 1
                    print(f"     Uploaded: {fname} ({fpath.stat().st_size // 1024}KB)")
                else:
                    print(f"     MISSING: {fname}")
        else:
            # 전체 폴더 업로드
            n = upload_directory(svc, str(proj['path']), fid)
            total_files += n
            print(f"     Uploaded: {n} files")

    # 4. API 키 관리 문서 업로드
    print("\n[4] API 키 관리 문서 생성...")
    api_doc = """# API KEY MANAGEMENT
# Updated: auto-generated

## Active APIs
- Gemini: Set (AIzaSy...)
- Claude: Set (sk-ant-api03...)
- Perplexity: Set (pplx-...)
- NTS (국세청): Set
- Naver Client ID/Secret: Set
- Google Drive: Configured

## Deployed Sites
1. Alpha Engine v4: https://jyjzzjtube-pixel.github.io/alpha-engine-v3/
2. YJ Tax Master v7: https://jyjzzjtube-pixel.github.io/yjtax-v8/
3. 제안서 시뮬레이터: https://jyjzzjtube-pixel.github.io/wonwill-app/
4. 파운더원: https://jyjzzjtube-pixel.github.io/founderone-site/
5. 통합DB: https://jyjzzjtube-pixel.github.io/yj-db-automation/
6. 네이버 블로그: https://jyjzzjtube-pixel.github.io/naver-blog-master/
7. Shorts Factory: http://localhost:5000 (local server)
"""
    api_doc_path = Path(__file__).parent / "_temp_api.md"
    api_doc_path.write_text(api_doc, encoding='utf-8')
    upload_file(svc, str(api_doc_path), folder_ids["03_API키_설정"], "API_키_관리.md")
    api_doc_path.unlink()
    total_files += 1

    # 5. 최종 결과
    print(f"\n{'='*60}")
    print(f"  COMPLETE!")
    print(f"  Root: YJ Partners - 전체 프로젝트")
    print(f"  Total files uploaded: {total_files}")
    print(f"  Folder structure:")
    print(f"    YJ Partners - 전체 프로젝트/")
    for cat_name in folders:
        print(f"      {cat_name}/")
        for sub in folders[cat_name].get("sub", {}):
            print(f"        {sub}/")
    print(f"{'='*60}")

if __name__ == '__main__':
    main()
