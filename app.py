import streamlit as st
from openai import OpenAI

# 페이지 기본 설정
st.set_page_config(
    page_title="주거복지 상담 및 대화 문서화 시스템",
    page_icon="📋",
    layout="wide"
)

# 비밀번호 확인 로직 (기본값: social1234)
def check_password():
    if "password_correct" not in st.session_state:
        st.session_state["password_correct"] = False

    if not st.session_state["password_correct"]:
        st.title("🔒 로그인")
        pwd = st.text_input("접속 비밀번호를 입력하세요", type="password")
        if st.button("로그인"):
            if pwd == "social1234":
                st.session_state["password_correct"] = True
                st.rerun()
            else:
                st.error("비밀번호가 올바르지 않습니다.")
        return False
    return True

if check_password():
    # 사이드바 설정
    with st.sidebar:
        st.header("⚙️ 설정")
        api_key = st.text_input("OpenAI API Key 입력", type="password", placeholder="sk-...")
        model = st.selectbox("사용할 모델", ["gpt-4o-mini", "gpt-4o"], index=0)
        
        st.markdown("---")
        st.markdown("### 💡 사용 방법")
        st.markdown("1. OpenAI API 키(`sk-...`)를 입력합니다.\n2. 대화 내용/상담 녹취록을 붙여넣습니다.\n3. **[요약 및 문서화]** 버튼을 클릭합니다.")

    # 메인 화면
    st.title("📋 다자간 대화 자동 문서화 시스템 (ChatGPT)")
    st.write("회의, 상담, 카카오톡 대화록 텍스트를 입력하시면 AI가 깔끔한 보고서 서식으로 자동 문서화해 드립니다.")

    user_input = st.text_area(
        "대화/상담 내용 입력",
        height=300,
        placeholder="[김팀장] 오늘 A주택 상담 건 진행상황 어떠한가요?\n[이대리] 신청 서류 검토 중입니다.\n..."
    )

    if st.button("✨ 요약 및 문서화 실행", type="primary"):
        if not api_key:
            st.warning("사이드바에 OpenAI API Key를 먼저 입력해 주세요!")
        elif not user_input.strip():
            st.warning("대화 내용을 입력해 주세요!")
        else:
            try:
                with st.spinner("ChatGPT가 대화 내용을 분석하여 문서화 중입니다..."):
                    client = OpenAI(api_key=api_key)
                    
                    prompt = f"""
                    당신은 전문 문서 작성 및 회의록 요약 전문가입니다.
                    아래 대화 내용을 바탕으로 깔끔하게 정리된 '상담 및 업무 처리 보고서'를 작성해 주세요.

                    [대화 내용]
                    {user_input}

                    [작성 규칙]
                    1. 불필요한 인사말이나 사담은 제외하세요.
                    2. 아래 서식에 맞추어 마크다운으로 작성해 주세요:
                       - 📋 기본 정보 (주요 화자 및 안건 주제)
                       - 🔍 주요 논의 및 서류/자격 현황
                       - 📌 결정 및 처리 사항
                       - 🚀 향후 조치 과제 (Action Items, 담당자/대상자별 명시)
                    """

                    response = client.chat.completions.create(
                        model=model,
                        messages=[
                            {"role": "system", "content": "유능하고 친절한 문서 요약 도우미입니다."},
                            {"role": "user", "content": prompt}
                        ],
                        temperature=0.3
                    )

                    result = response.choices[0].message.content
                    st.success("문서화가 완료되었습니다!")
                    st.markdown("---")
                    st.markdown(result)
                    
            except Exception as e:
                st.error(f"오류가 발생했습니다: {e}")
