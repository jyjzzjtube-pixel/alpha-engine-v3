# -*- coding: utf-8 -*-
"""
듀얼 배포 시스템 테스트 - EXIF 세탁 + 콘텐츠 생성 + 영상 렌더링
=================================================================
업로드는 --skip-upload로 건너뛰고, 핵심 파이프라인만 테스트한다.
"""
import os
import sys
import time
import glob

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)


def test_image_launderer():
    """Step 1: EXIF 세탁 기능 단독 테스트"""
    from affiliate_system.dual_deployer import ImageLaunderer

    print("=" * 60)
    print("테스트 1: ImageLaunderer - EXIF 세탁")
    print("=" * 60)

    # 베베숲 이미지 사용
    img_dir = os.path.join(ROOT, "affiliate_system", "workspace", "extracted", "bebeshup_browser")
    images = sorted(glob.glob(os.path.join(img_dir, "*.png")))[:3]

    if not images:
        print("[!] 테스트 이미지 없음 - 건너뜀")
        return []

    print(f"원본 이미지 {len(images)}개:")
    for img in images:
        sz = os.path.getsize(img)
        print(f"  - {os.path.basename(img)} ({sz:,} bytes)")

    launderer = ImageLaunderer()
    laundered = launderer.launder_batch(images, full_wash=True)

    print(f"\n세탁 완료 이미지 {len(laundered)}개:")
    for img in laundered:
        if os.path.exists(img):
            sz = os.path.getsize(img)
            print(f"  - {os.path.basename(img)} ({sz:,} bytes)")

    # 해시 비교
    import hashlib
    print("\n파일 해시 비교 (원본 vs 세탁):")
    for orig, clean in zip(images, laundered):
        h1 = hashlib.md5(open(orig, "rb").read()).hexdigest()[:12]
        h2 = hashlib.md5(open(clean, "rb").read()).hexdigest()[:12]
        match = "동일" if h1 == h2 else "다름"
        print(f"  {os.path.basename(orig)}: {h1} -> {h2} [{match}]")

    print()
    return laundered


def test_dual_deployer_skip_upload():
    """Step 2: 듀얼 배포 시스템 (업로드 건너뛰기)"""
    from affiliate_system.dual_deployer import DualDeployer

    print("=" * 60)
    print("테스트 2: DualDeployer - 풀 파이프라인 (업로드 제외)")
    print("=" * 60)

    # 베베숲 로컬 이미지 사용
    img_dir = os.path.join(ROOT, "affiliate_system", "workspace", "extracted", "bebeshup_browser")
    local_images = sorted(glob.glob(os.path.join(img_dir, "*.png")))[:6]

    if not local_images:
        print("[!] 로컬 이미지 없음 - 건너뜀")
        return

    deployer = DualDeployer(
        manual_review=False,  # 테스트에서는 수동 확인 비활성화
        skip_upload=True,     # 업로드 건너뛰기
    )

    t0 = time.time()
    result = deployer.run(
        coupang_url_or_keyword="베베숲 오리진 물티슈 100매 6팩",
        platforms=["youtube", "naver_blog"],  # YouTube + 네이버 블로그만
        local_images=local_images,
    )
    elapsed = time.time() - t0

    print(f"\n소요 시간: {elapsed:.1f}초")
    print(f"상품: {result['product'].title}")
    print(f"원본 이미지: {len(result['images_raw'])}개")
    print(f"세탁 이미지: {len(result['images_laundered'])}개")
    print(f"AI 콘텐츠: {list(result['ai_contents'].keys())}")
    print(f"영상: {list(result['video_paths'].keys())}")
    print(f"블로그 HTML: {len(result['blog_html'])}자")

    # 영상 파일 확인
    for platform, path in result["video_paths"].items():
        if path and os.path.exists(path):
            sz = os.path.getsize(path) / (1024 * 1024)
            print(f"\n영상 [{platform}]: {os.path.basename(path)} ({sz:.1f}MB)")

    # 블로그 HTML 미리보기
    if result["blog_html"]:
        preview = result["blog_html"][:300]
        print(f"\n블로그 HTML 미리보기:\n{preview}...")


def main():
    print()
    print("*" * 60)
    print("  듀얼 배포 시스템 테스트")
    print("*" * 60)
    print()

    # 테스트 1: EXIF 세탁
    laundered = test_image_launderer()

    # 테스트 2: 풀 파이프라인 (업로드 제외)
    test_dual_deployer_skip_upload()


if __name__ == "__main__":
    main()
