"""
프로그램 레벨 테스트: YouTube 프리셋 → 자동 framed 레이아웃 영상 렌더링
=======================================================================
- RenderConfig.from_platform_preset(YouTube) → canvas_layout="framed" 자동 적용
- 원본 이미지 → 자동 framed 캔버스 변환
- TTS 동기화 자막 + framed 스타일
- Lofi BGM + 자연스러운 속도
"""
import os
import sys
import glob
import shutil
import time

# 프로젝트 루트
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from affiliate_system.models import (
    Platform, PLATFORM_PRESETS, RenderConfig
)

def main():
    # 1. YouTube 프리셋에서 RenderConfig 자동 생성
    yt_preset = PLATFORM_PRESETS[Platform.YOUTUBE]
    cfg = RenderConfig.from_platform_preset(yt_preset)

    print("=" * 60)
    print("YouTube 프리셋 자동 설정 확인")
    print("=" * 60)
    print(f"  canvas_layout  : {cfg.canvas_layout}")
    print(f"  subtitle_style : {cfg.subtitle_style}")
    print(f"  video_bitrate  : {cfg.video_bitrate}")
    print(f"  audio_bitrate  : {cfg.audio_bitrate}")
    print(f"  encode_preset  : {cfg.encode_preset}")
    print(f"  fps            : {cfg.fps}")
    print(f"  tts_speed      : {cfg.tts_speed}")
    print(f"  bgm_genre      : {cfg.bgm_genre}")
    print(f"  bgm_volume     : {cfg.bgm_volume}")
    print(f"  subtitle_pos   : {cfg.subtitle_position}")
    print()

    # 2. 테스트 이미지 (교촌치킨 or 베베숍 아무거나 6장)
    img_dir = os.path.join(ROOT, "affiliate_system", "workspace", "references")
    images = sorted(glob.glob(os.path.join(img_dir, "*.jpg")))[:6]

    if len(images) < 3:
        # 폴백: media_downloads에서
        img_dir = os.path.join(ROOT, "affiliate_system", "workspace", "media_downloads")
        images = sorted(glob.glob(os.path.join(img_dir, "*.jpg")))[:6]

    print(f"이미지 {len(images)}장 로드")
    for i, p in enumerate(images):
        print(f"  [{i}] {os.path.basename(p)}")

    # 3. 찰진 나레이션 (레퍼런스 스타일)
    narrations = [
        "요즘 핫한 프랜차이즈 하나 소개해드릴게요",
        "이거 진짜 대박이거든요 가맹비도 착하고",
        "매장 인테리어 보세요 이 퀄리티 실화인가요",
        "가성비 끝판왕이라 초보 창업자한테 딱이에요",
        "매출도 꾸준히 나오고 리뷰도 진짜 좋아요",
        "관심 있으시면 아래 링크에서 확인해보세요",
    ]
    narrations = narrations[:len(images)]

    # 자막 = 나레이션 (TTS와 동기화)
    subtitle_text = "\n".join(narrations)

    # 4. VideoForge로 렌더링 (프로그램 파이프라인)
    from affiliate_system.video_editor import VideoForge

    forge = VideoForge(cfg)
    output_path = os.path.join(ROOT, "affiliate_system", "renders", "framed_test_v1.mp4")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    print()
    print("=" * 60)
    print("렌더링 시작 (프로그램 자동 framed 레이아웃)")
    print("=" * 60)

    t0 = time.time()
    result = forge.render_shorts(
        images=images,
        narrations=narrations,
        output_path=output_path,
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
        dest = os.path.join(desktop, "framed_test_v1.mp4")
        shutil.copy2(result, dest)
        print(f"\n★ 바탕화면에 복사 완료: {dest}")
    else:
        print("ERROR: 출력 파일이 생성되지 않았습니다!")

if __name__ == "__main__":
    main()
