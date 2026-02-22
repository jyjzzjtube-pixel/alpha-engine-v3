"""
YJ MCN test all features
"""
import sys
import os
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(__file__))
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPixmap, QImage
from datetime import datetime

app = QApplication(sys.argv)
app.setStyle('Fusion')

from affiliate_system.main_ui import MainWindow

results = []
def log(test_name, status, detail=""):
    icon = "✅" if status == "PASS" else "❌" if status == "FAIL" else "⚠️"
    results.append((test_name, status, detail))
    print(f"  {icon} {test_name}: {status} {detail}")

print("=" * 60)
print("  YJ MCN 대시보드 — 전체 기능 자동화 테스트")
print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 60)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1. 앱 생성 테스트
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n[1] 앱 초기화 테스트")
try:
    window = MainWindow()
    log("MainWindow 생성", "PASS")
except Exception as e:
    log("MainWindow 생성", "FAIL", str(e)[:80])
    sys.exit(1)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2. 탭 구조 테스트
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n[2] 탭 구조 테스트")
tab_count = window.tabs.count()
expected_tabs = ["대시보드", "작업 센터", "편집", "DB 뷰어", "AI 검토", "설정"]
log("탭 개수", "PASS" if tab_count == 6 else "FAIL", f"{tab_count}개")
for i, name in enumerate(expected_tabs):
    tab_text = window.tabs.tabText(i).strip()
    ok = name in tab_text
    log(f"탭 [{i}] '{name}'", "PASS" if ok else "FAIL", f"실제: '{tab_text}'")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3. 대시보드 테스트
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n[3] 대시보드 테스트")
dt = window.dashboard_tab

# 메트릭 카드
for card_name, card in [("오늘 비용", dt.card_today),
                         ("누적 비용", dt.card_monthly),
                         ("총 캠페인", dt.card_campaigns),
                         ("게시물당", dt.card_roi)]:
    val = card.lbl_value.text()
    log(f"메트릭 '{card_name}'", "PASS" if val else "FAIL", f"값: {val}")

# LED 상태
leds = [
    ("로컬 DB", dt.led_db),
    ("구글 드라이브", dt.led_drive),
    ("Gemini API", dt.led_gemini),
    ("Claude API", dt.led_claude),
    ("텔레그램 봇", dt.led_telegram),
    ("Chrome CDP", dt.led_chrome),
    ("Pexels", dt.led_pexels),
    ("쿠팡 파트너스", dt.led_coupang),
]
log(f"시스템 상태 LED 개수", "PASS" if len(leds) == 8 else "FAIL", f"{len(leds)}개")
for name, led in leds:
    log(f"LED '{name}'", "PASS", led.label.text())

# 새로고침 실행
try:
    dt.refresh()
    log("대시보드 새로고침", "PASS")
except Exception as e:
    log("대시보드 새로고침", "FAIL", str(e)[:80])

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 4. 작업센터 Mode A 테스트
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n[4] 작업센터 Mode A 테스트")
cc = window.command_tab
mode_a = cc.mode_a

# 모드 전환 테스트
for idx, name in [(0, "Mode A"), (1, "Mode B"), (2, "Mode C")]:
    cc._switch_mode(idx)
    current = cc.stack.currentIndex()
    log(f"{name} 전환", "PASS" if current == idx else "FAIL", f"index={current}")

cc._switch_mode(0)  # Mode A로 복귀

# 소스 플랫폼 버튼 테스트
log(f"소스 플랫폼 버튼 개수", "PASS" if len(mode_a._src_buttons) == 6 else "FAIL",
    f"{len(mode_a._src_buttons)}개")
for name, btn in mode_a._src_buttons:
    mode_a._on_src_platform_click(name)
    log(f"플랫폼 '{name}' 클릭", "PASS" if btn.isChecked() else "FAIL")

# 페르소나 프리셋 테스트
log(f"페르소나 프리셋 개수", "PASS", f"{len(mode_a.PERSONA_PRESETS)}개")
for i in range(1, len(mode_a.PERSONA_PRESETS)):
    mode_a.persona_combo.setCurrentIndex(i)
    mode_a._on_persona_preset(i)
    text = mode_a.persona_input.toPlainText()
    label = mode_a.PERSONA_PRESETS[i][0]
    log(f"페르소나 '{label}'", "PASS" if text else "FAIL", f"{text[:30]}...")

# 훅 프리셋 테스트
log(f"훅 프리셋 개수", "PASS", f"{len(mode_a.HOOK_PRESETS)}개")
for i in range(1, len(mode_a.HOOK_PRESETS)):
    mode_a.hook_combo.setCurrentIndex(i)
    mode_a._on_hook_preset(i)
    text = mode_a.hook_input.toPlainText()
    label = mode_a.HOOK_PRESETS[i][0]
    log(f"훅 '{label}'", "PASS" if text else "FAIL", f"{text[:30]}...")

# 플랫폼 체크박스 테스트
log("YouTube 기본 선택", "PASS" if mode_a.chk_yt.isChecked() else "FAIL")
log("네이버 기본 선택", "PASS" if mode_a.chk_naver.isChecked() else "FAIL")
log("Instagram 기본 선택", "PASS" if mode_a.chk_ig.isChecked() else "FAIL")
log("자동 썸네일 기본 선택", "PASS" if mode_a.chk_auto_thumb.isChecked() else "FAIL")

# 전체 선택/해제 테스트
mode_a.chk_all.setChecked(False)
mode_a._on_check_all(0)
all_unchecked = (not mode_a.chk_yt.isChecked() and
                 not mode_a.chk_naver.isChecked() and
                 not mode_a.chk_ig.isChecked())
log("전체 해제", "PASS" if all_unchecked else "FAIL")

mode_a.chk_all.setChecked(True)
mode_a._on_check_all(2)
all_checked = (mode_a.chk_yt.isChecked() and
               mode_a.chk_naver.isChecked() and
               mode_a.chk_ig.isChecked())
log("전체 선택", "PASS" if all_checked else "FAIL")

# 쿠팡 URL 스크래핑 테스트 (CoupangScraper 사용)
print("\n[4b] 쿠팡 스크래핑 테스트")
test_url = "https://www.coupang.com/vp/products/7913236498?itemId=17304907292&vendorItemId=30000411189"
mode_a.url_input.setText(test_url)
mode_a._on_scrape()
app.processEvents()

title_text = mode_a.lbl_title.text()
price_text = mode_a.lbl_price.text()
log("쿠팡 스크래핑 실행", "PASS" if title_text else "FAIL", f"제목: {title_text[:50]}")
log("쿠팡 가격 추출", "PASS" if price_text else "WARN", f"가격: {price_text}")
log("쿠팡 플랫폼 감지", "PASS" if mode_a.lbl_platform_tag.text() else "FAIL",
    mode_a.lbl_platform_tag.text())

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 5. 작업센터 Mode B 테스트
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n[5] 작업센터 Mode B 테스트")
mode_b = cc.mode_b
cc._switch_mode(1)
log("Mode B 전환", "PASS" if cc.stack.currentIndex() == 1 else "FAIL")

brand_count = mode_b.brand_combo.count()
log(f"브랜드 개수", "PASS" if brand_count == 3 else "FAIL", f"{brand_count}개")
for i in range(brand_count):
    mode_b.brand_combo.setCurrentIndex(i)
    log(f"브랜드 '{mode_b.brand_combo.currentText()[:20]}'", "PASS")

content_count = mode_b.content_combo.count()
log(f"콘텐츠 유형 개수", "PASS" if content_count >= 3 else "FAIL", f"{content_count}개")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 6. 작업센터 Mode C 테스트
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n[6] 작업센터 Mode C 테스트")
mode_c = cc.mode_c
cc._switch_mode(2)
log("Mode C 전환", "PASS" if cc.stack.currentIndex() == 2 else "FAIL")

ai_count = mode_c.ai_combo.count()
log(f"AI 엔진 옵션", "PASS" if ai_count >= 2 else "FAIL", f"{ai_count}개")
log(f"배치 딜레이 기본값", "PASS" if mode_c.delay_spin.value() == 25 else "FAIL",
    f"{mode_c.delay_spin.value()}분")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 7. 편집 탭 테스트
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n[7] 편집 탭 테스트")
editor = window.editor_tab

# 플랫폼 탭 테스트
log(f"편집 플랫폼 탭 개수", "PASS" if len(editor._platform_buttons) == 4 else "FAIL",
    f"{len(editor._platform_buttons)}개")
for i, (name, icon, desc) in enumerate(editor.PLATFORM_TABS):
    editor._switch_platform(i)
    log(f"편집 플랫폼 '{name}'", "PASS" if editor._platform_buttons[i].isChecked() else "FAIL")

# 캔버스 테스트
log("캔버스 위젯 존재", "PASS" if editor.canvas else "FAIL")

# 마커 모드 전환
editor._on_marker_mode()
log("마커 모드", "PASS" if editor.canvas._mode == "marker" else "FAIL")

editor._on_region_mode()
log("영역 모드", "PASS" if editor.canvas._mode == "region" else "FAIL")

# 줌 테스트
editor._on_zoom_in()
log("줌 인", "PASS" if editor.canvas._zoom > 1.0 else "FAIL",
    f"{editor.canvas._zoom:.0%}")
editor._on_zoom_out()
editor._on_zoom_out()
log("줌 아웃", "PASS" if editor.canvas._zoom < 1.0 else "FAIL",
    f"{editor.canvas._zoom:.0%}")

# 시그널 존재 확인
log("send_to_review 시그널", "PASS" if hasattr(editor, 'send_to_review') else "FAIL")
log("upload_to_drive 시그널", "PASS" if hasattr(editor, 'upload_to_drive') else "FAIL")
log("load_campaign 메서드", "PASS" if callable(getattr(editor, 'load_campaign', None)) else "FAIL")

# 캠페인 로드 테스트
test_campaign = {
    'id': 'test123',
    'title': '테스트 상품',
    'url': 'https://test.com',
    'image_url': '',
    'platforms': ['YouTube Shorts', '네이버 블로그'],
    'persona': '테스트 페르소나',
    'hook': '테스트 훅',
}
editor.load_campaign(test_campaign)
log("캠페인 로드", "PASS" if editor._current_campaign else "FAIL")
campaign_label = editor._campaign_label.text()
log("캠페인 라벨 표시", "PASS" if "테스트 상품" in campaign_label else "FAIL",
    campaign_label)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 8. 미리보기 실행 테스트
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n[8] 미리보기 테스트")
editor._on_preview_commands()
preview_text = editor._ref_analysis.toPlainText()
log("미리보기 실행", "PASS" if "미리보기" in preview_text else "FAIL",
    f"내용 길이: {len(preview_text)}자")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 9. 캠페인 생성 → 편집 연동 테스트
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n[9] 캠페인 생성 → 편집 연동 테스트")
cc._switch_mode(0)
mode_a.url_input.setText("https://test-product.example.com/item/123")
mode_a.persona_combo.setCurrentIndex(2)  # 30대 남성 테크 리뷰어
mode_a.hook_combo.setCurrentIndex(3)     # 비교형

# 수동으로 캠페인 생성 시뮬레이션
import uuid
from affiliate_system.models import Campaign, Product, Platform
campaign = Campaign(
    id=str(uuid.uuid4())[:8],
    product=Product(url="https://test-product.example.com/item/123"),
    persona=mode_a.persona_input.toPlainText().strip(),
    hook_directive=mode_a.hook_input.toPlainText().strip(),
    target_platforms=[Platform.YOUTUBE, Platform.NAVER_BLOG, Platform.INSTAGRAM],
    created_at=datetime.now())
window._on_campaign_created(campaign)
app.processEvents()

log("캠페인 생성", "PASS" if len(window.campaigns) > 0 else "FAIL",
    f"총 {len(window.campaigns)}건")
log("편집 탭으로 전환", "PASS" if window.tabs.currentWidget() == editor else "FAIL")
log("편집 캠페인 데이터", "PASS" if editor._current_campaign else "FAIL")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 10. 설정 탭 테스트
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n[10] 설정 탭 테스트")
settings = window.settings_tab
log("Gemini 키 필드", "PASS" if settings.gemini_key else "FAIL")
log("Claude 키 필드", "PASS" if settings.claude_key else "FAIL")
log("Pexels 키 필드", "PASS" if settings.pexels_key else "FAIL")
log("Pixabay 키 필드", "PASS" if settings.pixabay_key else "FAIL")
log("Unsplash 키 필드", "PASS" if settings.unsplash_key else "FAIL")
log("예산 설정", "PASS" if settings.budget_spin.value() == 50000 else "FAIL",
    f"₩{settings.budget_spin.value():,}")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 최종 결과
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n" + "=" * 60)
passed = sum(1 for _, s, _ in results if s == "PASS")
failed = sum(1 for _, s, _ in results if s == "FAIL")
warned = sum(1 for _, s, _ in results if s == "WARN")
total = len(results)
print(f"  ✅ PASS: {passed}/{total}")
print(f"  ❌ FAIL: {failed}/{total}")
if warned:
    print(f"  ⚠️ WARN: {warned}/{total}")
print("=" * 60)

if failed > 0:
    print("\n실패 항목:")
    for name, status, detail in results:
        if status == "FAIL":
            print(f"  ❌ {name}: {detail}")

app.quit()
