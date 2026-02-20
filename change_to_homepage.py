# -*- coding: utf-8 -*-
"""
홈페이지형 완성:
1) 레이아웃을 위젯이 타이틀 아래 가로로 보이는 타입으로 변경
2) 프로필/검색/RSS 제거
3) 글 영역 "보통"으로 변경
"""
import sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

BLOG_ID = "jyjzzj"
LAYOUT_URL = f"https://admin.blog.naver.com/LayoutSelect.naver?blogId={BLOG_ID}"
BLOG_URL = f"https://blog.naver.com/{BLOG_ID}"
SS = "C:/Users/jyjzz/OneDrive/바탕 화면/franchise-db"


def connect():
    opts = Options()
    opts.add_experimental_option("debuggerAddress", "localhost:9222")
    return webdriver.Chrome(options=opts)


def safe_alert(d):
    for _ in range(8):
        try:
            a = d.switch_to.alert
            print(f"    [알림] {a.text[:60]}")
            a.accept()
            time.sleep(1)
        except:
            break


def main():
    d = connect()

    print("=" * 60)
    print("홈페이지형 레이아웃 변경")
    print("=" * 60)

    d.get(LAYOUT_URL)
    time.sleep(15)
    safe_alert(d)

    for i in range(20):
        try:
            if d.execute_script('return typeof DD !== "undefined";'):
                break
        except:
            safe_alert(d)
        time.sleep(1)

    # 레이아웃 선택 이미지들 분석 (상단 가로 아이콘들)
    layout_selector = d.execute_script("""
        var r = {};
        // layout_vari div 내부
        var layoutDiv = document.getElementById('layout_vari');
        if (!layoutDiv) return {error: 'layout_vari not found'};

        var tds = layoutDiv.querySelectorAll('td');
        r.tdCount = tds.length;
        r.tds = [];
        for (var i = 0; i < tds.length; i++) {
            var td = tds[i];
            var img = td.querySelector('img');
            var input = td.querySelector('input[type="radio"]');
            r.tds.push({
                idx: i,
                cls: td.className.substring(0, 80),
                hasRadio: !!input,
                radioValue: input ? input.value : '',
                radioChecked: input ? input.checked : false,
                radioId: input ? input.id : '',
                imgSrc: img ? img.src.substring(0, 200) : '',
                imgAlt: img ? img.alt : '',
                onclick: td.getAttribute('onclick') || ''
            });
        }
        return r;
    """)

    if layout_selector.get('error'):
        print(f"  에러: {layout_selector['error']}")
    else:
        print(f"  레이아웃 TD 수: {layout_selector['tdCount']}")
        for td in layout_selector.get('tds', []):
            check = " ★CURRENT" if td['radioChecked'] else ""
            print(f"    [{td['idx']}] value={td['radioValue']} cls={td['cls'][:30]}{check}")

    # 현재 레이아웃 타입 확인
    lt = d.execute_script("return DD.layoutType;")
    print(f"\n  현재 layoutType: {lt}")

    # 레이아웃 타입별 설명:
    # 네이버 블로그의 레이아웃:
    # - 왼쪽 8개: 사이드바 있는 타입 (2열, 3열)
    # - 오른쪽 2개: 와이드형 (1열, 위젯이 가로로 배치)

    # 라디오 버튼 값으로 레이아웃 변경 시도
    # 와이드형 1열 = 보통 마지막 2개 중 하나

    # 현재 선택된 것 찾기
    current_idx = -1
    for td in layout_selector.get('tds', []):
        if td['radioChecked']:
            current_idx = td['idx']

    print(f"  현재 선택: [{current_idx}]")

    # 레이아웃 previewLayout 함수로 미리보기 시도
    # 마지막 2개(10,11번째) 또는 index 기준으로 와이드형 찾기

    # TD의 class가 "list"이고 onclick에 layout 관련이 있는 것
    # 실제 네이버에서는 TD 클릭 시 DD.previewLayout() 호출

    # 모든 TD의 라디오 값 확인
    print("\n  레이아웃 변경 시도...")

    # 레이아웃 타입 목록 확인
    available_types = d.execute_script("""
        var radios = document.querySelectorAll('#layout_vari input[type="radio"]');
        var types = [];
        for (var i = 0; i < radios.length; i++) {
            types.push({
                value: radios[i].value,
                name: radios[i].name,
                checked: radios[i].checked,
                idx: i
            });
        }
        return types;
    """)

    print(f"  사용 가능한 레이아웃 타입:")
    for t in available_types:
        check = " ★" if t['checked'] else ""
        print(f"    [{t['idx']}] name={t['name']} value={t['value']}{check}")

    # 와이드형으로 변경 — 보통 마지막 2개 (인덱스 기반)
    # 네이버 블로그: 레이아웃 타입들
    # 맨 오른쪽 2개가 와이드형 (타이틀+위젯 전체 폭)
    # 이전 블로그에서 타입 4였으니, 1열 전체폭으로 변경

    # previewLayout으로 변경
    for t in available_types:
        if t['value'] and not t['checked']:
            print(f"\n  레이아웃 {t['value']} 미리보기...")
            try:
                d.execute_script(f"""
                    var radio = document.querySelectorAll('#layout_vari input[type="radio"]')[{t['idx']}];
                    if (radio) {{
                        radio.click();
                        if (typeof DD.previewLayout === 'function') {{
                            DD.previewLayout({t['value']});
                        }}
                    }}
                """)
                time.sleep(2)
                new_lt = d.execute_script("return DD.layoutType;")
                print(f"    layoutType 변경: {new_lt}")

                if new_lt != lt:
                    # 변경됨 - 스크린샷 찍기
                    d.save_screenshot(f"{SS}/layout_type_{t['value']}.png")
            except Exception as e:
                print(f"    에러: {e}")

    # 최적 레이아웃 선택: 위젯이 타이틀 아래 가로 배치되는 것
    # 네이버 블로그에서 위젯이 가로로 배치되려면:
    # - 2열 레이아웃에서 사이드바에 위젯 5개 → 세로
    # - 3열 레이아웃에서 상단 영역 → 가로 (현재 방식)
    # - 1열 레이아웃 → 위젯이 본문 아래 가로

    # 타입 4(현재)가 실제로 상단에 위젯을 가로로 보여주는 타입일 수 있음
    # 문제는 글 영역이 "넓게"로 설정되어 위젯이 밀려난 것

    # 글 영역 설정 변경: "넓게" → "보통"
    print("\n  글 영역 설정 변경:")
    content_setting = d.execute_script("""
        // 글 영역 라디오 버튼
        var radios = document.querySelectorAll('input[name="s_contentAreaWidth"]');
        var result = [];
        for (var i = 0; i < radios.length; i++) {
            result.push({value: radios[i].value, checked: radios[i].checked, id: radios[i].id});
        }
        return result;
    """)
    for cs in content_setting:
        check = " ★" if cs['checked'] else ""
        print(f"    값={cs['value']} id={cs['id']}{check}")

    # "보통"으로 변경 (보통 = 1열에서 중간 너비)
    d.execute_script("""
        var radios = document.querySelectorAll('input[name="s_contentAreaWidth"]');
        for (var i = 0; i < radios.length; i++) {
            if (radios[i].value === 'N' || radios[i].value === 'normal') {
                radios[i].click();
                break;
            }
        }
    """)
    time.sleep(1)

    # 체크박스 설정
    d.execute_script("""
        // OFF
        ['r_profile','r_search','r_rss','r_buddyconnect','r_bloginfo','r_recentreply',
         'w_1','w_2','w_3','w_4','w_5'].forEach(function(id) {
            var cb = document.getElementById(id);
            if (cb && cb.checked) cb.click();
        });
        // ON
        ['r_title','r_menu','r_category','w_6','w_7','w_8','w_9','w_10'].forEach(function(id) {
            var cb = document.getElementById(id);
            if (cb && !cb.checked) cb.click();
        });
    """)

    # 적용
    print("\n  레이아웃 적용...")
    try:
        d.execute_script('doApplyConfirm();')
    except:
        safe_alert(d)

    time.sleep(2)
    safe_alert(d)
    time.sleep(5)
    safe_alert(d)
    time.sleep(3)
    safe_alert(d)
    print("  적용 완료!")

    # 블로그 확인
    print("\n" + "=" * 60)
    print("블로그 확인")
    print("=" * 60)

    d.get(BLOG_URL)
    time.sleep(8)

    try:
        d.switch_to.frame("mainFrame")
        r = d.execute_script("""
            var r = {};
            var t = document.getElementById('blog-title');
            if (t) {
                var cs = getComputedStyle(t);
                r.title = {h: t.offsetHeight, w: t.offsetWidth,
                    bg: cs.backgroundImage !== 'none' ? 'YES' : 'NO'};
            }
            var ws = document.querySelectorAll('[id^="externalwidget_"]');
            r.wc = ws.length;
            r.ws = [];
            for (var i = 0; i < ws.length; i++) {
                var w = ws[i]; var wr = w.getBoundingClientRect();
                r.ws.push({id:w.id, l:Math.round(wr.left), t:Math.round(wr.top),
                    w:Math.round(wr.width), h:Math.round(wr.height),
                    visible: wr.left < 1200 && wr.top < 2000});
            }
            r.pageH = document.body.scrollHeight;
            r.contentW = document.getElementById('content') ? document.getElementById('content').offsetWidth : 0;
            r.lnbW = document.getElementById('lnb') ? document.getElementById('lnb').offsetWidth : 0;
            return r;
        """)

        t = r.get('title', {})
        print(f"  타이틀: {t.get('w')}x{t.get('h')}px, 배경={t.get('bg')}")
        print(f"  콘텐츠 너비: {r.get('contentW')}px, 사이드바: {r.get('lnbW')}px")
        print(f"  위젯: {r['wc']}개")
        for w in r['ws']:
            vis = "visible" if w['visible'] else "HIDDEN"
            print(f"    {w['id']}: left={w['l']} top={w['t']} {w['w']}x{w['h']} [{vis}]")
        print(f"  페이지 높이: {r.get('pageH')}px")

        d.switch_to.default_content()
    except Exception as e:
        print(f"  에러: {e}")
        try: d.switch_to.default_content()
        except: pass

    d.save_screenshot(f"{SS}/blog_homepage.png")
    print(f"\n  스크린샷: blog_homepage.png")

    try:
        d.switch_to.frame("mainFrame")
        d.execute_script("window.scrollTo(0, 400);")
        time.sleep(2)
        d.switch_to.default_content()
        d.save_screenshot(f"{SS}/blog_homepage_scroll.png")
    except: pass

    print("\n완료!")


if __name__ == "__main__":
    main()
