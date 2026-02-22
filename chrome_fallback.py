# -*- coding: utf-8 -*-
"""Chrome 디버깅 포트를 통한 백업 브라우저 제어
확장프로그램 끊어져도 이걸로 Chrome 제어 가능"""
import json, urllib.request, sys, websocket, time
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

PORT = 9222

def get_tabs():
    """열린 탭 목록 조회"""
    resp = urllib.request.urlopen(f'http://127.0.0.1:{PORT}/json', timeout=5)
    return json.loads(resp.read())

def find_tab(keyword):
    """키워드로 탭 찾기"""
    tabs = get_tabs()
    for t in tabs:
        if keyword.lower() in t.get('url', '').lower() or keyword.lower() in t.get('title', '').lower():
            return t
    return None

def execute_js(tab_ws_url, js_code):
    """탭에서 JavaScript 실행"""
    ws = websocket.create_connection(tab_ws_url, timeout=10)
    msg = json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {"expression": js_code, "returnByValue": True}})
    ws.send(msg)
    result = json.loads(ws.recv())
    ws.close()
    return result.get('result', {}).get('result', {}).get('value')

def click_element(tab_ws_url, selector):
    """CSS 선택자로 요소 클릭"""
    js = f"document.querySelector('{selector}')?.click(); 'clicked'"
    return execute_js(tab_ws_url, js)

def navigate(tab_ws_url, url):
    """페이지 이동"""
    ws = websocket.create_connection(tab_ws_url, timeout=10)
    msg = json.dumps({"id": 1, "method": "Page.navigate", "params": {"url": url}})
    ws.send(msg)
    result = json.loads(ws.recv())
    ws.close()
    return result

def screenshot(tab_ws_url, filename="screenshot.png"):
    """스크린샷 캡처"""
    import base64
    ws = websocket.create_connection(tab_ws_url, timeout=15)
    msg = json.dumps({"id": 1, "method": "Page.captureScreenshot", "params": {"format": "png"}})
    ws.send(msg)
    result = json.loads(ws.recv())
    ws.close()
    data = result.get('result', {}).get('data', '')
    if data:
        with open(filename, 'wb') as f:
            f.write(base64.b64decode(data))
        return filename
    return None

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Chrome 백업 제어')
    parser.add_argument('action', choices=['tabs', 'js', 'click', 'nav', 'shot'], help='실행할 액션')
    parser.add_argument('--tab', default='', help='탭 검색 키워드')
    parser.add_argument('--code', default='', help='JS 코드')
    parser.add_argument('--selector', default='', help='CSS 선택자')
    parser.add_argument('--url', default='', help='이동할 URL')
    parser.add_argument('--output', default='screenshot.png', help='스크린샷 저장 경로')
    args = parser.parse_args()

    if args.action == 'tabs':
        tabs = get_tabs()
        for i, t in enumerate(tabs):
            print(f"[{i}] {t.get('title', '?')[:50]} | {t.get('url', '?')[:80]}")

    elif args.action == 'js':
        tab = find_tab(args.tab)
        if tab and tab.get('webSocketDebuggerUrl'):
            result = execute_js(tab['webSocketDebuggerUrl'], args.code)
            print(result)
        else:
            print(f"탭 '{args.tab}' 없음 또는 ws 없음")

    elif args.action == 'click':
        tab = find_tab(args.tab)
        if tab and tab.get('webSocketDebuggerUrl'):
            result = click_element(tab['webSocketDebuggerUrl'], args.selector)
            print(result)

    elif args.action == 'nav':
        tab = find_tab(args.tab)
        if tab and tab.get('webSocketDebuggerUrl'):
            result = navigate(tab['webSocketDebuggerUrl'], args.url)
            print(result)

    elif args.action == 'shot':
        tab = find_tab(args.tab)
        if tab and tab.get('webSocketDebuggerUrl'):
            result = screenshot(tab['webSocketDebuggerUrl'], args.output)
            print(f"저장: {result}")
