# banner.py
import streamlit as st

PRODUCT = {
    "title": "플러스박스",
    "subtitle": "조건없이 심플하게 누구나 연1.7%(세전)",
    "image": "assets/navy_left.png",
    "url": "https://www.kbanknow.com/ib20/mnu/FPMDPT130100?phashid=vxCheBJ"
}

# ✅ 이미 열린 st.chat_message 컨텍스트 내부에서 호출되는 형태로 변경
def render_banner(seq: int):

    st.markdown("""
    ✅ 사용자가 요청한 내용을 정상적으로 잘 수행하였습니다.  

    ---

    더 필요하신 내용은 없으신가요?  
    ### 이런 상품은 어떠세요?
    """)
    
    col1, col2 = st.columns([1, 2], vertical_alignment="center")
    with col1:
        st.image(PRODUCT["image"], width=100, use_container_width=False)
    with col2:
        st.markdown(f"**{PRODUCT['title']}**  \n{PRODUCT['subtitle']}")
        st.caption(f"추천 사유: {st.session_state.banner_ctx.get('reason', '이벤트')}")

    b1, b2 = st.columns(2)
    # 🔑 각 버튼에 seq를 suffix로 부여해 키 충돌 방지
    with b1:
        see_more = st.button("자세히 보기 🔗", key=f"cta_detail_{seq}")
    with b2:
        dismiss = st.button("관심 없음 🙅", key=f"cta_dismiss_{seq}")

    # 버튼 처리 -> 대화로 연결
    if see_more:
        st.session_state.messages.append({
            "role": "assistant",
            "content": f"[{PRODUCT['title']}] 자세한 정보는 여기서 확인해 보세요: {PRODUCT['url']}"
        })
        st.rerun()

    if dismiss:
        st.session_state.messages.append({
            "role": "assistant",
            "content": "알겠습니다. 추가적으로 더 필요한 것이 있으면 문의주세요."
        })
        st.rerun()