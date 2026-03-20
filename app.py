import io
import zipfile

import numpy as np
import streamlit as st
from PIL import Image

try:
    import tinify

    TINIFY_AVAILABLE = True
except ImportError:
    TINIFY_AVAILABLE = False

# Streamlit Cloud 제약사항: 기본 업로드 제한 200MB, 메모리 1GB

TARGET_SIZES = {
    "원본 사이즈 (리사이즈 없음)": None,
    "1242 × 2688 (iPhone XS Max / 6.5인치)": (1242, 2688),
    "2064 × 2752 (iPad 6th gen / 스크린샷)": (2064, 2752),
}

st.set_page_config(page_title="iOS Image Magic", page_icon="✨", layout="centered")

st.title("✨ iOS Image Magic")


def hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i : i + 2], 16) for i in (0, 2, 4))


def resize_image(
    img: Image.Image, target_w: int, target_h: int, bg: str, transparent: bool = False
) -> Image.Image:
    """이미지를 퀄리티 훼손 없이 목표 해상도에 맞춤."""
    original_w, original_h = img.size

    scale = min(target_w / original_w, target_h / original_h)
    new_w = int(original_w * scale)
    new_h = int(original_h * scale)

    # 투명 배경일 때는 항상 RGBA로 처리
    if transparent:
        resized = img.convert("RGBA").resize((new_w, new_h), Image.LANCZOS)
        canvas = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
        canvas.paste(resized, ((target_w - new_w) // 2, (target_h - new_h) // 2), resized)
    else:
        resized = img.resize((new_w, new_h), Image.LANCZOS)
        bg_rgb = hex_to_rgb(bg)
        if img.mode == "RGBA":
            canvas = Image.new("RGBA", (target_w, target_h), (*bg_rgb, 255))
        else:
            canvas = Image.new("RGB", (target_w, target_h), bg_rgb)
        offset_x = (target_w - new_w) // 2
        offset_y = (target_h - new_h) // 2
        canvas.paste(resized, (offset_x, offset_y))

    return canvas


# ===== TinyPNG 인증 (사이드바) =====
tinify_authenticated = False
with st.sidebar:
    st.markdown("### TinyPNG 압축")
    if not TINIFY_AVAILABLE:
        st.warning("tinify 패키지가 설치되지 않았습니다")
    else:
        tiny_password = st.text_input("비밀번호 입력", type="password", key="tiny_pw")
        if tiny_password:
            if tiny_password == st.secrets.get("APP_PASSWORD", ""):
                tinify.key = st.secrets["TINIFY_API_KEY"]
                tinify_authenticated = True
                st.success("TinyPNG 인증 완료")
            else:
                st.error("비밀번호가 일치하지 않습니다")


def extract_icon(img: Image.Image, tolerance: int = 30, padding: int = 10) -> Image.Image:
    """배경을 제거하고 아이콘만 정사각형으로 추출. 외곽 연결 영역만 투명 처리."""
    from scipy import ndimage

    rgba = img.convert("RGBA")
    arr = np.array(rgba)
    h, w = arr.shape[:2]

    # 가장자리 픽셀 전체에서 배경색 추정 (모서리 4개 + 각 변 중앙)
    edge_pixels = [
        arr[0, 0], arr[0, -1], arr[-1, 0], arr[-1, -1],  # 모서리
        arr[0, w // 2], arr[-1, w // 2],  # 상하 중앙
        arr[h // 2, 0], arr[h // 2, -1],  # 좌우 중앙
    ]
    bg_color = np.median(edge_pixels, axis=0).astype(np.uint8)

    # 배경색과 유사한 픽셀 마스크 (True = 배경색과 비슷함)
    diff = np.abs(arr[:, :, :3].astype(int) - bg_color[:3].astype(int))
    is_bg_color = np.all(diff <= tolerance, axis=2)

    # 이미 투명한 픽셀도 배경으로 취급
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        is_bg_color = is_bg_color | (arr[:, :, 3] < 10)

    # 연결 영역 라벨링 (C 구현이라 대형 이미지에서도 빠름)
    labeled, num_features = ndimage.label(is_bg_color)

    # 가장자리에 닿는 라벨만 수집 → 외곽 배경
    edge_labels = set()
    edge_labels.update(labeled[0, :].tolist())      # 상단
    edge_labels.update(labeled[-1, :].tolist())     # 하단
    edge_labels.update(labeled[:, 0].tolist())      # 좌측
    edge_labels.update(labeled[:, -1].tolist())     # 우측
    edge_labels.discard(0)  # 0은 배경이 아닌 픽셀

    # 외곽 연결 배경만 투명으로 설정 (내부 흰색은 유지)
    if not edge_labels:
        # 가장자리에 배경색이 없는 경우: 전체 배경색 픽셀을 투명 처리 (fallback)
        outer_bg = is_bg_color
    else:
        outer_bg = np.isin(labeled, list(edge_labels))
    result_arr = arr.copy()
    result_arr[outer_bg, 3] = 0

    result_img = Image.fromarray(result_arr, "RGBA")

    # 컨텐츠 바운딩 박스로 크롭
    bbox = result_img.getbbox()
    if bbox is None:
        # 전체가 투명이면 원본 RGBA 반환
        return Image.fromarray(arr, "RGBA")

    cropped = result_img.crop(bbox)

    # 정사각형으로 만들기 (패딩 포함)
    w, h = cropped.size
    side = max(w, h) + padding * 2
    square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    offset_x = (side - w) // 2
    offset_y = (side - h) // 2
    square.paste(cropped, (offset_x, offset_y), cropped)

    return square


def compress_with_tinify(img_bytes: bytes) -> bytes:
    """TinyPNG API로 PNG 압축."""
    return tinify.from_buffer(img_bytes).to_buffer()


def convert_to_webp_with_tinify(img_bytes: bytes) -> bytes:
    """TinyPNG API로 WebP 변환 압축."""
    source = tinify.from_buffer(img_bytes)
    return source.convert(type="image/webp").to_buffer()


# ===== 탭 구성 =====
tabs = ["📐 사이즈 변환", "📏 커스텀 리사이즈", "🔄 WebP 변환", "✂️ 아이콘 추출"]
if tinify_authenticated:
    tabs += ["🐼 TinyPNG 압축", "🐼 TinyPNG WebP"]
all_tabs = st.tabs(tabs)
tab_resize = all_tabs[0]
tab_custom = all_tabs[1]
tab_webp = all_tabs[2]
tab_icon = all_tabs[3]

# ===== 탭 1: 사이즈 변환 (기존 기능) =====
with tab_resize:
    st.markdown("이미지를 업로드하면 **퀄리티 훼손 없이** 원하는 해상도로 변환합니다.")

    size_label = st.selectbox("변환할 사이즈를 선택하세요", list(TARGET_SIZES.keys()))
    target_size = TARGET_SIZES[size_label]
    keep_original = target_size is None
    if not keep_original:
        target_w, target_h = target_size
        st.caption(f"선택된 해상도: **{target_w} × {target_h}px**")

    if not keep_original:
        use_transparent = st.checkbox("투명 배경 (알파 100%)", value=False, key="resize_transparent")
        if not use_transparent:
            bg_color = st.color_picker("여백(패딩) 배경색", "#FFFFFF")
        else:
            bg_color = "#FFFFFF"

    png_compress = st.slider(
        "PNG 압축 레벨 (0=빠름/큰파일, 9=느림/작은파일)", 0, 9, 6, key="resize_compress"
    )

    uploaded_files = st.file_uploader(
        "이미지를 업로드하세요 (여러 장 가능)",
        type=["png", "jpg", "jpeg", "webp"],
        accept_multiple_files=True,
        key="resize_uploader",
    )

    if uploaded_files:
        st.divider()
        st.subheader(f"📷 {len(uploaded_files)}개 이미지 업로드됨")

        processed_images: list[tuple[str, bytes]] = []

        for uploaded in uploaded_files:
            img = Image.open(uploaded)
            original_w, original_h = img.size

            if keep_original:
                result = img
                result_w, result_h = original_w, original_h
            else:
                result = resize_image(img, target_w, target_h, bg_color, use_transparent)
                result_w, result_h = target_w, target_h

            col1, col2 = st.columns(2)
            with col1:
                st.caption(f"원본: {original_w}×{original_h}")
                st.image(uploaded, use_container_width=True)
            with col2:
                label = "원본 유지" if keep_original else f"변환: {result_w}×{result_h}"
                st.caption(label)
                st.image(result, use_container_width=True)

            buf = io.BytesIO()
            result.save(buf, format="PNG", compress_level=png_compress)
            buf.seek(0)
            img_bytes = buf.getvalue()

            stem = uploaded.name.rsplit(".", 1)[0]
            suffix = f"_{result_w}x{result_h}" if not keep_original else ""
            filename = f"{stem}{suffix}.png"
            processed_images.append((filename, img_bytes))

        st.divider()

        if len(processed_images) == 1:
            fname, data = processed_images[0]
            st.download_button(
                label=f"⬇️ {fname} 다운로드",
                data=data,
                file_name=fname,
                mime="image/png",
                use_container_width=True,
            )
        else:
            zip_buf = io.BytesIO()
            with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for fname, data in processed_images:
                    zf.writestr(fname, data)
            zip_buf.seek(0)

            st.download_button(
                label=f"⬇️ 전체 {len(processed_images)}개 이미지 ZIP 다운로드",
                data=zip_buf.getvalue(),
                file_name="ios_images_original.zip" if keep_original else f"ios_images_{target_w}x{target_h}.zip",
                mime="application/zip",
                use_container_width=True,
            )

# ===== 탭 2: 커스텀 리사이즈 =====
with tab_custom:
    st.markdown("**가로 × 세로(px)**를 직접 입력하여 이미지를 리사이즈합니다.")

    col_w, col_h = st.columns(2)
    with col_w:
        custom_w = st.number_input("가로 (px)", min_value=1, max_value=10000, value=800, step=1, key="custom_w")
    with col_h:
        custom_h = st.number_input("세로 (px)", min_value=1, max_value=10000, value=600, step=1, key="custom_h")

    custom_transparent = st.checkbox("투명 배경 (알파 100%)", value=False, key="custom_transparent")
    if not custom_transparent:
        custom_bg = st.color_picker("여백(패딩) 배경색", "#FFFFFF", key="custom_bg")
    else:
        custom_bg = "#FFFFFF"

    custom_compress = st.slider(
        "PNG 압축 레벨 (0=빠름/큰파일, 9=느림/작은파일)", 0, 9, 6, key="custom_compress"
    )

    custom_files = st.file_uploader(
        "이미지를 업로드하세요 (여러 장 가능)",
        type=["png", "jpg", "jpeg", "webp", "bmp", "tiff"],
        accept_multiple_files=True,
        key="custom_uploader",
    )

    if custom_files:
        st.divider()
        st.subheader(f"📏 {len(custom_files)}개 이미지 → {custom_w}×{custom_h} 변환")

        custom_images: list[tuple[str, bytes]] = []

        for uploaded in custom_files:
            img = Image.open(uploaded)
            original_w, original_h = img.size

            col1, col2 = st.columns(2)
            with col1:
                st.caption(f"원본: {original_w}×{original_h}")
                st.image(uploaded, use_container_width=True)

            result = resize_image(img, custom_w, custom_h, custom_bg, custom_transparent)

            with col2:
                st.caption(f"변환: {custom_w}×{custom_h}")
                st.image(result, use_container_width=True)

            buf = io.BytesIO()
            result.save(buf, format="PNG", compress_level=custom_compress)
            buf.seek(0)
            img_bytes = buf.getvalue()

            stem = uploaded.name.rsplit(".", 1)[0]
            filename = f"{stem}_{custom_w}x{custom_h}.png"
            custom_images.append((filename, img_bytes))

        st.divider()

        if len(custom_images) == 1:
            fname, data = custom_images[0]
            st.download_button(
                label=f"⬇️ {fname} 다운로드",
                data=data,
                file_name=fname,
                mime="image/png",
                use_container_width=True,
                key="custom_download_single",
            )
        else:
            zip_buf = io.BytesIO()
            with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for fname, data in custom_images:
                    zf.writestr(fname, data)
            zip_buf.seek(0)

            st.download_button(
                label=f"⬇️ 전체 {len(custom_images)}개 이미지 ZIP 다운로드",
                data=zip_buf.getvalue(),
                file_name=f"custom_images_{custom_w}x{custom_h}.zip",
                mime="application/zip",
                use_container_width=True,
                key="custom_download_zip",
            )

# ===== 탭 3: WebP 변환 =====
with tab_webp:
    st.markdown("PNG, JPEG 등 이미지를 **WebP 포맷**으로 변환합니다.")

    webp_quality = st.slider("WebP 품질 (100 = 무손실)", 1, 100, 90, key="webp_quality")
    webp_lossless = webp_quality == 100

    webp_files = st.file_uploader(
        "변환할 이미지를 업로드하세요 (여러 장 가능)",
        type=["png", "jpg", "jpeg", "bmp", "tiff"],
        accept_multiple_files=True,
        key="webp_uploader",
    )

    if webp_files:
        st.divider()
        st.subheader(f"🔄 {len(webp_files)}개 이미지 → WebP 변환")

        converted_images: list[tuple[str, bytes]] = []

        for uploaded in webp_files:
            img = Image.open(uploaded)
            w, h = img.size

            # 투명도가 있는 이미지는 RGBA로 변환하여 알파 채널 유지
            has_alpha = img.mode in ("RGBA", "LA") or (
                img.mode == "P" and "transparency" in img.info
            )
            if has_alpha:
                save_img = img.convert("RGBA")
            else:
                save_img = img.convert("RGB")

            buf = io.BytesIO()
            if webp_lossless:
                save_img.save(buf, format="WEBP", lossless=True)
            else:
                save_img.save(buf, format="WEBP", quality=webp_quality)
            buf.seek(0)
            webp_bytes = buf.getvalue()

            stem = uploaded.name.rsplit(".", 1)[0]
            filename = f"{stem}.webp"
            converted_images.append((filename, webp_bytes))

            # 원본 크기 vs WebP 크기 비교
            original_size = len(uploaded.getvalue())
            webp_size = len(webp_bytes)
            ratio = (1 - webp_size / original_size) * 100 if original_size > 0 else 0

            col1, col2 = st.columns(2)
            with col1:
                st.caption(f"원본: {uploaded.name} ({w}×{h}, {original_size / 1024:.1f} KB)")
                st.image(uploaded, use_container_width=True)
            with col2:
                st.caption(f"WebP: {filename} ({webp_size / 1024:.1f} KB, {ratio:.1f}% 절감)")
                st.image(webp_bytes, use_container_width=True)

        st.divider()

        if len(converted_images) == 1:
            fname, data = converted_images[0]
            st.download_button(
                label=f"⬇️ {fname} 다운로드",
                data=data,
                file_name=fname,
                mime="image/webp",
                use_container_width=True,
                key="webp_download_single",
            )
        else:
            zip_buf = io.BytesIO()
            with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for fname, data in converted_images:
                    zf.writestr(fname, data)
            zip_buf.seek(0)

            st.download_button(
                label=f"⬇️ 전체 {len(converted_images)}개 WebP 이미지 ZIP 다운로드",
                data=zip_buf.getvalue(),
                file_name="webp_images.zip",
                mime="application/zip",
                use_container_width=True,
                key="webp_download_zip",
            )

# ===== 탭 4: 아이콘 추출 =====
with tab_icon:
    st.markdown("아이콘 이미지의 **배경을 제거**하고 아이콘만 **정사각형으로 추출**합니다.")

    icon_tolerance = st.slider(
        "배경 제거 민감도 (낮을수록 엄격)", 5, 80, 30, key="icon_tolerance"
    )
    icon_padding = st.slider(
        "아이콘 주변 여백 (px)", 0, 100, 10, key="icon_padding"
    )
    icon_output_size = st.number_input(
        "출력 크기 (px, 0 = 자동)", min_value=0, max_value=4096, value=0, step=1, key="icon_size"
    )

    if tinify_authenticated:
        icon_tinify_webp = st.checkbox(
            "🐼 TinyPNG WebP 변환도 함께 생성", value=False, key="icon_tinify_webp"
        )
    else:
        icon_tinify_webp = False

    icon_files = st.file_uploader(
        "아이콘 이미지를 업로드하세요 (여러 장 가능)",
        type=["png", "jpg", "jpeg", "webp", "bmp"],
        accept_multiple_files=True,
        key="icon_uploader",
    )

    if icon_files:
        st.divider()
        st.subheader(f"✂️ {len(icon_files)}개 아이콘 추출")

        icon_results: list[tuple[str, bytes]] = []
        icon_webp_results: list[tuple[str, bytes]] = []

        for uploaded in icon_files:
            img = Image.open(uploaded)
            original_w, original_h = img.size

            result = extract_icon(img, tolerance=icon_tolerance, padding=icon_padding)

            # 출력 크기 지정 시 리사이즈
            if icon_output_size > 0:
                result = result.resize(
                    (icon_output_size, icon_output_size), Image.LANCZOS
                )

            # 반드시 RGBA 모드로 저장 (알파 채널 보존)
            if result.mode != "RGBA":
                result = result.convert("RGBA")

            rw, rh = result.size

            buf = io.BytesIO()
            result.save(buf, format="PNG", compress_level=6)
            buf.seek(0)
            png_bytes = buf.getvalue()

            stem = uploaded.name.rsplit(".", 1)[0]
            png_filename = f"{stem}_icon_{rw}x{rh}.png"
            icon_results.append((png_filename, png_bytes))

            # TinyPNG WebP 변환
            webp_bytes = None
            if icon_tinify_webp:
                try:
                    webp_bytes = convert_to_webp_with_tinify(png_bytes)
                    webp_filename = f"{stem}_icon_{rw}x{rh}.webp"
                    icon_webp_results.append((webp_filename, webp_bytes))
                except Exception as e:
                    st.error(f"{uploaded.name} TinyPNG WebP 변환 실패: {e}")

            # 미리보기
            col1, col2 = st.columns(2)
            with col1:
                st.caption(f"원본: {original_w}×{original_h}")
                st.image(uploaded, use_container_width=True)
            with col2:
                st.caption(f"추출: {rw}×{rh} (투명 배경, {len(png_bytes) / 1024:.1f} KB)")
                st.image(result, use_container_width=True)

            if webp_bytes:
                webp_ratio = (1 - len(webp_bytes) / len(png_bytes)) * 100
                st.caption(
                    f"🐼 WebP: {len(webp_bytes) / 1024:.1f} KB ({webp_ratio:.1f}% 절감)"
                )
                st.image(webp_bytes, use_container_width=True)

        st.divider()

        # PNG 다운로드
        if len(icon_results) == 1:
            fname, data = icon_results[0]
            st.download_button(
                label=f"⬇️ {fname} 다운로드",
                data=data,
                file_name=fname,
                mime="image/png",
                use_container_width=True,
                key="icon_download_single",
            )
        else:
            zip_buf = io.BytesIO()
            with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for fname, data in icon_results:
                    zf.writestr(fname, data)
            zip_buf.seek(0)

            st.download_button(
                label=f"⬇️ 전체 {len(icon_results)}개 아이콘 PNG ZIP 다운로드",
                data=zip_buf.getvalue(),
                file_name="icons_extracted.zip",
                mime="application/zip",
                use_container_width=True,
                key="icon_download_zip",
            )

        # WebP 다운로드
        if icon_webp_results:
            if len(icon_webp_results) == 1:
                fname, data = icon_webp_results[0]
                st.download_button(
                    label=f"⬇️ {fname} 다운로드",
                    data=data,
                    file_name=fname,
                    mime="image/webp",
                    use_container_width=True,
                    key="icon_webp_download_single",
                )
            else:
                zip_buf = io.BytesIO()
                with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
                    for fname, data in icon_webp_results:
                        zf.writestr(fname, data)
                zip_buf.seek(0)

                st.download_button(
                    label=f"⬇️ 전체 {len(icon_webp_results)}개 아이콘 WebP ZIP 다운로드",
                    data=zip_buf.getvalue(),
                    file_name="icons_webp.zip",
                    mime="application/zip",
                    use_container_width=True,
                    key="icon_webp_download_zip",
                )

# ===== 탭 5: TinyPNG PNG 압축 =====
if tinify_authenticated:
    with all_tabs[4]:
        st.markdown("**TinyPNG** API를 사용하여 PNG를 최대한 압축합니다 (무손실~준무손실).")

        tiny_transparent = st.checkbox("투명 배경 유지 (알파 채널 보존)", value=True, key="tiny_transparent")

        tiny_png_files = st.file_uploader(
            "압축할 PNG 이미지를 업로드하세요 (여러 장 가능)",
            type=["png", "jpg", "jpeg"],
            accept_multiple_files=True,
            key="tiny_png_uploader",
        )

        if tiny_png_files:
            st.divider()
            st.subheader(f"🐼 {len(tiny_png_files)}개 이미지 TinyPNG 압축")

            tiny_results: list[tuple[str, bytes]] = []

            for uploaded in tiny_png_files:
                img = Image.open(uploaded)
                w, h = img.size
                original_bytes = uploaded.getvalue()
                original_size = len(original_bytes)

                # 투명 배경 유지: RGBA로 변환 후 PNG으로 저장
                if tiny_transparent:
                    has_alpha = img.mode in ("RGBA", "LA") or (
                        img.mode == "P" and "transparency" in img.info
                    )
                    if has_alpha:
                        img = img.convert("RGBA")
                    buf = io.BytesIO()
                    img.save(buf, format="PNG")
                    buf.seek(0)
                    original_bytes = buf.getvalue()

                try:
                    compressed = compress_with_tinify(original_bytes)
                    compressed_size = len(compressed)
                    ratio = (1 - compressed_size / original_size) * 100 if original_size > 0 else 0

                    stem = uploaded.name.rsplit(".", 1)[0]
                    filename = f"{stem}_tiny.png"
                    tiny_results.append((filename, compressed))

                    col1, col2 = st.columns(2)
                    with col1:
                        st.caption(f"원본: {uploaded.name} ({w}×{h}, {original_size / 1024:.1f} KB)")
                        st.image(uploaded, use_container_width=True)
                    with col2:
                        st.caption(f"압축: {filename} ({compressed_size / 1024:.1f} KB, {ratio:.1f}% 절감)")
                        st.image(compressed, use_container_width=True)
                except Exception as e:
                    st.error(f"{uploaded.name} 압축 실패: {e}")

            if tiny_results:
                st.divider()
                if len(tiny_results) == 1:
                    fname, data = tiny_results[0]
                    st.download_button(
                        label=f"⬇️ {fname} 다운로드",
                        data=data,
                        file_name=fname,
                        mime="image/png",
                        use_container_width=True,
                        key="tiny_png_download_single",
                    )
                else:
                    zip_buf = io.BytesIO()
                    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
                        for fname, data in tiny_results:
                            zf.writestr(fname, data)
                    zip_buf.seek(0)
                    st.download_button(
                        label=f"⬇️ 전체 {len(tiny_results)}개 압축 PNG ZIP 다운로드",
                        data=zip_buf.getvalue(),
                        file_name="tinypng_compressed.zip",
                        mime="application/zip",
                        use_container_width=True,
                        key="tiny_png_download_zip",
                    )

# ===== 탭 6: TinyPNG WebP 변환 =====
if tinify_authenticated:
    with all_tabs[5]:
        st.markdown("**TinyPNG** API를 사용하여 이미지를 **WebP로 변환 + 압축**합니다.")

        tiny_webp_transparent = st.checkbox("투명 배경 유지 (알파 채널 보존)", value=True, key="tiny_webp_transparent")

        tiny_webp_files = st.file_uploader(
            "변환할 이미지를 업로드하세요 (여러 장 가능)",
            type=["png", "jpg", "jpeg"],
            accept_multiple_files=True,
            key="tiny_webp_uploader",
        )

        if tiny_webp_files:
            st.divider()
            st.subheader(f"🐼 {len(tiny_webp_files)}개 이미지 → TinyPNG WebP 변환")

            tiny_webp_results: list[tuple[str, bytes]] = []

            for uploaded in tiny_webp_files:
                img = Image.open(uploaded)
                w, h = img.size
                original_bytes = uploaded.getvalue()
                original_size = len(original_bytes)

                # 투명 배경 유지: RGBA로 변환 후 PNG으로 전달
                if tiny_webp_transparent:
                    has_alpha = img.mode in ("RGBA", "LA") or (
                        img.mode == "P" and "transparency" in img.info
                    )
                    if has_alpha:
                        img = img.convert("RGBA")
                    buf = io.BytesIO()
                    img.save(buf, format="PNG")
                    buf.seek(0)
                    original_bytes = buf.getvalue()

                try:
                    webp_bytes = convert_to_webp_with_tinify(original_bytes)
                    webp_size = len(webp_bytes)
                    ratio = (1 - webp_size / original_size) * 100 if original_size > 0 else 0

                    stem = uploaded.name.rsplit(".", 1)[0]
                    filename = f"{stem}_tiny.webp"
                    tiny_webp_results.append((filename, webp_bytes))

                    col1, col2 = st.columns(2)
                    with col1:
                        st.caption(f"원본: {uploaded.name} ({w}×{h}, {original_size / 1024:.1f} KB)")
                        st.image(uploaded, use_container_width=True)
                    with col2:
                        st.caption(f"WebP: {filename} ({webp_size / 1024:.1f} KB, {ratio:.1f}% 절감)")
                        st.image(webp_bytes, use_container_width=True)
                except Exception as e:
                    st.error(f"{uploaded.name} 변환 실패: {e}")

            if tiny_webp_results:
                st.divider()
                if len(tiny_webp_results) == 1:
                    fname, data = tiny_webp_results[0]
                    st.download_button(
                        label=f"⬇️ {fname} 다운로드",
                        data=data,
                        file_name=fname,
                        mime="image/webp",
                        use_container_width=True,
                        key="tiny_webp_download_single",
                    )
                else:
                    zip_buf = io.BytesIO()
                    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
                        for fname, data in tiny_webp_results:
                            zf.writestr(fname, data)
                    zip_buf.seek(0)
                    st.download_button(
                        label=f"⬇️ 전체 {len(tiny_webp_results)}개 WebP ZIP 다운로드",
                        data=zip_buf.getvalue(),
                        file_name="tinypng_webp.zip",
                        mime="application/zip",
                        use_container_width=True,
                        key="tiny_webp_download_zip",
                    )

# --- 사이드바 안내 ---
with st.sidebar:
    st.markdown("### 사용 안내")
    st.markdown(
        """
**📐 사이즈 변환**
1. 변환할 **사이즈** 선택
2. 여백 **배경색** 선택
3. 이미지 **업로드** (여러 장 가능)
4. 변환 결과 확인 후 **다운로드**

---

**📏 커스텀 리사이즈**
1. 원하는 **가로 × 세로(px)** 입력
2. 여백 **배경색** 선택
3. 이미지 **업로드** (여러 장 가능)
4. 변환 결과 확인 후 **다운로드**

---

**🔄 WebP 변환**
1. **품질** 설정 (100 = 무손실)
2. 이미지 **업로드** (PNG, JPEG 등)
3. 파일 크기 절감율 확인 후 **다운로드**

---

**✂️ 아이콘 추출**
1. **민감도 / 여백** 조정
2. 아이콘 이미지 **업로드**
3. 배경 제거 + 정사각형 크롭 확인 후 **다운로드**

---

**🐼 TinyPNG (비밀번호 필요)**
- 사이드바에서 비밀번호 입력 후 사용
- PNG 압축 / WebP 변환 압축
- 투명 배경 유지 옵션 지원

---

**변환 방식**
- 원본 비율을 유지합니다
- 부족한 영역은 배경색으로 채웁니다
- LANCZOS 리샘플링 사용

**Streamlit Cloud 제약**
- 업로드 최대 200MB
- 대용량 이미지는 처리 시간이 걸릴 수 있습니다
"""
    )
