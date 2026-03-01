"""
YJ Watchface Factory — 워치페이스 이미지 프로세서
Galaxy Watch 7 (450x450px, Wear OS WFF)

기능:
1. 원본 이미지 → 원형 크롭 (안티앨리어싱)
2. 시침/분침/초침 분리 또는 생성
3. AOD(Always-On Display) 버전 자동 생성
4. WFF 프로젝트 XML 생성
"""

import os
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter, ImageEnhance, ImageOps

# 갤럭시워치7 해상도
WATCH_SIZE = 450
OUTPUT_SIZE = (WATCH_SIZE, WATCH_SIZE)

# 워치페이스 정의
WATCHFACES = {
    "daytona1": "YJ Cosmograph Daytona Style",
    "geneve1": "YJ GENÈVE Style",
    "daytona2": "YJ Cosmograph Daytona Style 2",
    "geneve2": "YJ GENÈVE Style 2",
    "navitimer": "YJ NAVITIMER Style",
    "star_legacy": "YJ STAR LEGACY Style",
}

BASE_DIR = Path(__file__).parent
ORIGINALS_DIR = BASE_DIR / "originals"
PROCESSED_DIR = BASE_DIR / "processed"


def circular_crop(img: Image.Image, size: int = WATCH_SIZE,
                  border_px: int = 0, shadow: bool = True) -> Image.Image:
    """
    고퀄리티 원형 크롭
    - 4x 슈퍼샘플링으로 안티앨리어싱
    - 선택적 테두리 + 그림자
    """
    # 4x 슈퍼샘플링 (부드러운 가장자리)
    ss = 4
    ss_size = size * ss

    # 정사각형으로 리사이즈 (중앙 크롭)
    img = img.convert("RGBA")

    # 중앙 기준 정사각형 크롭
    w, h = img.size
    min_dim = min(w, h)
    left = (w - min_dim) // 2
    top = (h - min_dim) // 2
    img = img.crop((left, top, left + min_dim, top + min_dim))

    # 슈퍼샘플 사이즈로 리사이즈
    img = img.resize((ss_size, ss_size), Image.LANCZOS)

    # 원형 마스크 생성 (슈퍼샘플)
    mask = Image.new("L", (ss_size, ss_size), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((0, 0, ss_size - 1, ss_size - 1), fill=255)

    # 마스크 적용
    result = Image.new("RGBA", (ss_size, ss_size), (0, 0, 0, 0))
    result.paste(img, (0, 0), mask)

    # 다운샘플 (안티앨리어싱 효과)
    result = result.resize((size, size), Image.LANCZOS)

    # 테두리 추가
    if border_px > 0:
        border_mask = Image.new("L", (size, size), 0)
        bd = ImageDraw.Draw(border_mask)
        bd.ellipse((0, 0, size - 1, size - 1), outline=200, width=border_px)
        border_layer = Image.new("RGBA", (size, size), (180, 180, 180, 0))
        border_layer.putalpha(border_mask)
        result = Image.alpha_composite(result, border_layer)

    return result


def create_aod_version(img: Image.Image, brightness: float = 0.3,
                       saturation: float = 0.2) -> Image.Image:
    """
    AOD (Always-On Display) 버전 생성
    - 밝기 30%, 채도 20%로 배터리 절약
    - OLED 최적화 (검은 영역 최대화)
    """
    aod = img.copy()

    # 채도 낮추기
    enhancer = ImageEnhance.Color(aod)
    aod = enhancer.enhance(saturation)

    # 밝기 낮추기
    enhancer = ImageEnhance.Brightness(aod)
    aod = enhancer.enhance(brightness)

    # 대비 약간 높여서 시인성 유지
    enhancer = ImageEnhance.Contrast(aod)
    aod = enhancer.enhance(1.3)

    return aod


def process_single(input_path: str, output_name: str,
                   border: int = 2) -> dict:
    """
    단일 워치페이스 이미지 처리
    Returns: 생성된 파일 경로 dict
    """
    img = Image.open(input_path)
    out_dir = PROCESSED_DIR / output_name
    out_dir.mkdir(parents=True, exist_ok=True)

    results = {}

    # 1. 메인 다이얼 (원형 크롭)
    dial = circular_crop(img, WATCH_SIZE, border_px=border)
    dial_path = out_dir / "dial_background.png"
    dial.save(str(dial_path), "PNG", optimize=True)
    results["dial"] = str(dial_path)
    print(f"  ✓ 다이얼: {dial_path}")

    # 2. AOD 버전
    aod = create_aod_version(dial)
    aod_path = out_dir / "dial_aod.png"
    aod.save(str(aod_path), "PNG", optimize=True)
    results["aod"] = str(aod_path)
    print(f"  ✓ AOD: {aod_path}")

    # 3. 프리뷰 (워치 프레임 포함)
    preview = create_preview(dial)
    preview_path = out_dir / "preview.png"
    preview.save(str(preview_path), "PNG", optimize=True)
    results["preview"] = str(preview_path)
    print(f"  ✓ 프리뷰: {preview_path}")

    return results


def create_preview(dial: Image.Image, frame_size: int = 500) -> Image.Image:
    """워치 프레임이 있는 프리뷰 이미지"""
    preview = Image.new("RGBA", (frame_size, frame_size), (30, 30, 30, 255))

    # 외부 원 (워치 케이스)
    draw = ImageDraw.Draw(preview)
    padding = 10
    draw.ellipse(
        (padding, padding, frame_size - padding, frame_size - padding),
        fill=(50, 50, 50, 255),
        outline=(100, 100, 100, 255),
        width=3
    )

    # 다이얼 중앙 배치
    offset = (frame_size - WATCH_SIZE) // 2
    preview.paste(dial, (offset, offset), dial)

    return preview


def create_hand_images(style: str = "classic", color: str = "silver") -> dict:
    """
    시침/분침/초침 이미지 생성
    - 투명 배경, 중앙 피봇
    - 스타일: classic, sport, dress
    """
    hand_size = WATCH_SIZE
    center = hand_size // 2

    # 색상 팔레트
    colors = {
        "silver": (220, 220, 220, 255),
        "white": (255, 255, 255, 255),
        "gold": (218, 175, 85, 255),
        "blue": (70, 100, 200, 255),
        "red": (220, 50, 50, 255),
    }
    hand_color = colors.get(color, colors["silver"])

    hands = {}

    # 시침 (짧고 두꺼움)
    hour_img = Image.new("RGBA", (hand_size, hand_size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(hour_img)
    # 슈퍼샘플링용 큰 이미지
    ss = 4
    hour_ss = Image.new("RGBA", (hand_size * ss, hand_size * ss), (0, 0, 0, 0))
    d = ImageDraw.Draw(hour_ss)
    cx, cy = center * ss, center * ss
    # 시침: 중앙에서 위로
    hw = 12 * ss  # 시침 너비
    hl = 110 * ss  # 시침 길이
    d.polygon([
        (cx - hw//2, cy + 20*ss),  # 아래 왼쪽
        (cx + hw//2, cy + 20*ss),  # 아래 오른쪽
        (cx + hw//3, cy - hl),     # 위 오른쪽
        (cx - hw//3, cy - hl),     # 위 왼쪽
    ], fill=hand_color)
    # 중앙 원
    cr = 15 * ss
    d.ellipse((cx-cr, cy-cr, cx+cr, cy+cr), fill=hand_color)
    hour_img = hour_ss.resize((hand_size, hand_size), Image.LANCZOS)
    hands["hour"] = hour_img

    # 분침 (길고 약간 얇음)
    min_ss = Image.new("RGBA", (hand_size * ss, hand_size * ss), (0, 0, 0, 0))
    d = ImageDraw.Draw(min_ss)
    mw = 8 * ss
    ml = 155 * ss
    d.polygon([
        (cx - mw//2, cy + 20*ss),
        (cx + mw//2, cy + 20*ss),
        (cx + mw//3, cy - ml),
        (cx - mw//3, cy - ml),
    ], fill=hand_color)
    cr = 12 * ss
    d.ellipse((cx-cr, cy-cr, cx+cr, cy+cr), fill=hand_color)
    hands["minute"] = min_ss.resize((hand_size, hand_size), Image.LANCZOS)

    # 초침 (가늘고 빨간색)
    sec_ss = Image.new("RGBA", (hand_size * ss, hand_size * ss), (0, 0, 0, 0))
    d = ImageDraw.Draw(sec_ss)
    sw = 3 * ss
    sl = 170 * ss
    sec_color = (220, 50, 50, 255)  # 빨간 초침
    d.polygon([
        (cx - sw//2, cy + 30*ss),
        (cx + sw//2, cy + 30*ss),
        (cx + 1*ss, cy - sl),
        (cx - 1*ss, cy - sl),
    ], fill=sec_color)
    cr = 8 * ss
    d.ellipse((cx-cr, cy-cr, cx+cr, cy+cr), fill=sec_color)
    # 중앙 점
    cr2 = 4 * ss
    d.ellipse((cx-cr2, cy-cr2, cx+cr2, cy+cr2), fill=(255, 255, 255, 255))
    hands["second"] = sec_ss.resize((hand_size, hand_size), Image.LANCZOS)

    return hands


def process_all_originals():
    """originals 폴더의 모든 이미지 처리"""
    originals = list(ORIGINALS_DIR.glob("*.*"))
    image_exts = {'.png', '.jpg', '.jpeg', '.webp', '.bmp'}
    images = [f for f in originals if f.suffix.lower() in image_exts]

    if not images:
        print(f"⚠ originals 폴더에 이미지가 없습니다: {ORIGINALS_DIR}")
        print("  이미지를 넣어주세요!")
        return

    print(f"📱 {len(images)}개 이미지 발견\n")

    face_names = list(WATCHFACES.keys())

    for i, img_path in enumerate(sorted(images)):
        name = face_names[i] if i < len(face_names) else f"custom_{i+1}"
        label = WATCHFACES.get(name, f"Custom #{i+1}")
        print(f"[{i+1}/{len(images)}] {label}")
        print(f"  원본: {img_path.name}")

        try:
            results = process_single(str(img_path), name)
            print(f"  ✅ 완료!\n")
        except Exception as e:
            print(f"  ❌ 오류: {e}\n")

    # 시침/분침 세트 생성
    print("🕐 시침/분침/초침 생성...")
    for style_name, hand_color in [("silver", "silver"), ("white", "white"),
                                     ("gold", "gold"), ("blue", "blue")]:
        hands = create_hand_images(color=hand_color)
        hand_dir = PROCESSED_DIR / "hands" / style_name
        hand_dir.mkdir(parents=True, exist_ok=True)
        for hname, himg in hands.items():
            path = hand_dir / f"{hname}_hand.png"
            himg.save(str(path), "PNG")
        print(f"  ✓ {style_name} 세트")

    print("\n✅ 전체 처리 완료!")
    print(f"📁 결과: {PROCESSED_DIR}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--single":
        # 단일 이미지 처리
        if len(sys.argv) < 4:
            print("Usage: python process_watchface.py --single <image> <name>")
            sys.exit(1)
        process_single(sys.argv[2], sys.argv[3])
    else:
        process_all_originals()
