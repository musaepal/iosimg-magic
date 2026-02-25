import io
import zipfile

import streamlit as st
from PIL import Image

# Streamlit Cloud 제약사항: 기본 업로드 제한 200MB, 메모리 1GB
# Pillow만 사용하여 외부 의존성 최소화

TARGET_SIZES = {
    "1242 × 2688 (iPhone XS Max / 6.5인치)": (1242, 2688),
    "2064 × 2752 (iPad 6th gen / 스크린샷)": (2064, 2752),
}

st.set_page_config(page_title="iOS Image Magic", page_icon="✨", layout="centered")

st.title("✨ iOS Image Magic")


def hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i : i + 2], 16) for i in (0, 2, 4))


def resize_image(img: Image.Image, target_w: int, target_h: int, bg: str) -> Image.Image:
    """이미지를 퀄리티 훼손 없이 목표 해상도에 맞춤."""
    original_w, original_h = img.size

    scale = min(target_w / original_w, target_h / original_h)
    new_w = int(original_w * scale)
    new_h = int(original_h * scale)

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


# ===== 탭 구성 =====
tab_resize, tab_webp = st.tabs(["📐 사이즈 변환", "🔄 WebP 변환"])

# ===== 탭 1: 사이즈 변환 (기존 기능) =====
with tab_resize:
    st.markdown("이미지를 업로드하면 **퀄리티 훼손 없이** 원하는 해상도로 변환합니다.")

    size_label = st.selectbox("변환할 사이즈를 선택하세요", list(TARGET_SIZES.keys()))
    target_w, target_h = TARGET_SIZES[size_label]
    st.caption(f"선택된 해상도: **{target_w} × {target_h}px**")

    bg_color = st.color_picker("여백(패딩) 배경색", "#FFFFFF")

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

            col1, col2 = st.columns(2)
            with col1:
                st.caption(f"원본: {original_w}×{original_h}")
                st.image(uploaded, use_container_width=True)

            result = resize_image(img, target_w, target_h, bg_color)

            with col2:
                st.caption(f"변환: {target_w}×{target_h}")
                st.image(result, use_container_width=True)

            buf = io.BytesIO()
            result.save(buf, format="PNG", optimize=True)
            buf.seek(0)
            img_bytes = buf.getvalue()

            stem = uploaded.name.rsplit(".", 1)[0]
            filename = f"{stem}_{target_w}x{target_h}.png"
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
                file_name=f"ios_images_{target_w}x{target_h}.zip",
                mime="application/zip",
                use_container_width=True,
            )

# ===== 탭 2: WebP 변환 =====
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

            # RGBA → WebP는 지원되지만, 필요시 RGB 변환
            if img.mode == "RGBA":
                save_img = img
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

**🔄 WebP 변환**
1. **품질** 설정 (100 = 무손실)
2. 이미지 **업로드** (PNG, JPEG 등)
3. 파일 크기 절감율 확인 후 **다운로드**

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
