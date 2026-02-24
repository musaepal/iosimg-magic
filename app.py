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
st.markdown("이미지를 업로드하면 **퀄리티 훼손 없이** 원하는 해상도로 변환합니다.")

# --- 사이즈 선택 ---
size_label = st.selectbox("변환할 사이즈를 선택하세요", list(TARGET_SIZES.keys()))
target_w, target_h = TARGET_SIZES[size_label]
st.caption(f"선택된 해상도: **{target_w} × {target_h}px**")

# --- 배경색 선택 ---
bg_color = st.color_picker("여백(패딩) 배경색", "#FFFFFF")


def hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i : i + 2], 16) for i in (0, 2, 4))


def resize_image(img: Image.Image, target_w: int, target_h: int, bg: str) -> Image.Image:
    """이미지를 퀄리티 훼손 없이 목표 해상도에 맞춤.

    전략:
    - 원본 비율을 유지하면서 목표 영역 안에 맞게 축소/확대 (fit)
    - 남는 영역은 선택한 배경색으로 채움 (letterbox/pillarbox)
    - 확대 시에도 LANCZOS 리샘플링으로 최대한 품질 유지
    """
    original_w, original_h = img.size

    # 비율 계산 - 목표 영역에 맞게 fit
    scale = min(target_w / original_w, target_h / original_h)
    new_w = int(original_w * scale)
    new_h = int(original_h * scale)

    # 고품질 리샘플링
    resized = img.resize((new_w, new_h), Image.LANCZOS)

    # 배경 캔버스 생성
    bg_rgb = hex_to_rgb(bg)
    if img.mode == "RGBA":
        canvas = Image.new("RGBA", (target_w, target_h), (*bg_rgb, 255))
    else:
        canvas = Image.new("RGB", (target_w, target_h), bg_rgb)

    # 중앙 배치
    offset_x = (target_w - new_w) // 2
    offset_y = (target_h - new_h) // 2
    canvas.paste(resized, (offset_x, offset_y))

    return canvas


# --- 파일 업로드 ---
uploaded_files = st.file_uploader(
    "이미지를 업로드하세요 (여러 장 가능)",
    type=["png", "jpg", "jpeg", "webp"],
    accept_multiple_files=True,
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

        # PNG로 저장 (무손실)
        buf = io.BytesIO()
        result.save(buf, format="PNG", optimize=True)
        buf.seek(0)
        img_bytes = buf.getvalue()

        # 파일명 생성
        stem = uploaded.name.rsplit(".", 1)[0]
        filename = f"{stem}_{target_w}x{target_h}.png"
        processed_images.append((filename, img_bytes))

    st.divider()

    # --- 다운로드 ---
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
        # 여러 장이면 ZIP으로 묶어서 다운로드
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

# --- 사이드바 안내 ---
with st.sidebar:
    st.markdown("### 사용 안내")
    st.markdown(
        """
1. 변환할 **사이즈** 선택
2. 여백 **배경색** 선택
3. 이미지 **업로드** (여러 장 가능)
4. 변환 결과 확인 후 **다운로드**

---

**변환 방식**
- 원본 비율을 유지합니다
- 부족한 영역은 배경색으로 채웁니다
- PNG 무손실 포맷으로 저장됩니다
- LANCZOS 리샘플링 사용

**Streamlit Cloud 제약**
- 업로드 최대 200MB
- 대용량 이미지는 처리 시간이 걸릴 수 있습니다
"""
    )
