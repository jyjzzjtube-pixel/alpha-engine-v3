"""
베베숲 물티슈 쿠팡파트너스 - Pro 스타일 + 타이핑 애니메이션 테스트
================================================================
- YouTube 프리셋 자동: canvas_layout=framed, subtitle_style=pro, subtitle_animation=typing
- 쿠팡파트너스 제품 홍보 나레이션
"""
import os
import sys
import shutil
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from affiliate_system.models import Platform, PLATFORM_PRESETS, RenderConfig
from affiliate_system.video_editor import VideoForge


def main():
    # 1. YouTube HQ 프리셋
    yt = PLATFORM_PRESETS[Platform.YOUTUBE]
    cfg = RenderConfig.from_platform_preset(yt)

    print("=" * 60)
    print("베베숲 물티슈 쿠팡파트너스 - Pro 타이핑 렌더링")
    print("=" * 60)
    print(f"  subtitle_style    : {cfg.subtitle_style}")
    print(f"  subtitle_animation: {cfg.subtitle_animation}")
    print(f"  canvas_layout     : {cfg.canvas_layout}")
    print(f"  video_bitrate     : {cfg.video_bitrate}")
    print(f"  fps               : {cfg.fps}")
    print()

    # 2. 베베숲 제품 이미지 (6장)
    img_dir = os.path.join(ROOT, "affiliate_system", "workspace", "extracted", "bebeshup_browser")
    images = [
        os.path.join(img_dir, "bebeshup_000.png"),  # 메인 패키지 (Origin 6팩)
        os.path.join(img_dir, "bebeshup_001.png"),  # 제품 감성샷
        os.path.join(img_dir, "bebeshup_010.png"),  # 클로즈업 (뚜껑)
        os.path.join(img_dir, "bebeshup_003.png"),  # Original 대량 패키지
        os.path.join(img_dir, "bebeshup_009.png"),  # Origin 대량 패키지
        os.path.join(img_dir, "bebeshup_002.png"),  # 성분/디테일
    ]
    # 실제 존재하는 이미지만 필터
    images = [p for p in images if os.path.exists(p)]
    print(f"이미지 {len(images)}장 로드")

    # 3. 쿠팡파트너스 나레이션 (찰진 구어체 + 쿠팡 유도)
    narrations = [
        "육아맘들 물티슈 뭐 쓰세요?",
        "베베숲 오리진 써봤는데 진짜 대박이에요",
        "뚜껑 달려있어서 마르지도 않고 완전 편해요",
        "100매짜리가 이 가격이면 가성비 미쳤죠",
        "피부 약한 아기한테도 걱정 없이 쓸 수 있어요",
        "쿠팡에서 로켓배송으로 바로 받아보세요",
    ]
    narrations = narrations[:len(images)]
    subtitle_text = "\n".join(narrations)

    # 4. 렌더링
    forge = VideoForge(cfg)
    output = os.path.join(ROOT, "affiliate_system", "renders", "bebeshup_pro_v1.mp4")
    os.makedirs(os.path.dirname(output), exist_ok=True)

    print("\n렌더링 시작...")
    t0 = time.time()
    result = forge.render_shorts(
        images=images,
        narrations=narrations,
        output_path=output,
        subtitle_text=subtitle_text,
    )
    elapsed = time.time() - t0

    print(f"\n렌더링 완료! ({elapsed:.1f}초)")
    print(f"출력: {result}")

    if os.path.exists(result):
        sz = os.path.getsize(result) / (1024 * 1024)
        print(f"파일 크기: {sz:.1f}MB")

        # 5. 바탕화면에 복사
        desktop = r"C:\Users\jyjzz\OneDrive\바탕 화면"
        dest = os.path.join(desktop, "bebeshup_pro_v1.mp4")
        shutil.copy2(result, dest)
        print(f"\n★ 바탕화면 복사 완료: {dest}")
    else:
        print("ERROR: 출력 파일 미생성!")


if __name__ == "__main__":
    main()
