import streamlit as st
from google import genai
import datetime

# 1. 페이지 기본 설정
st.set_page_config(page_title="주거복지사 상담 요약 시스템", page_icon="📝")

# 2. 보안 비밀번호 설정
def check_password():
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False

    if not st.session_state.authenticated:
        st.title("🔒 주거복지사 전용 시스템")
        pwd = st.text_input("접속 비밀번호를 입력하세요", type="password")
        if st.button("로그인"):
            if pwd == "social1234":  # <--- 사용하실 비밀번호로 변경 가능합니다!
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("비밀번호가 올바르지 않습니다.")
        return False
    return True

if check_password():
    st.title("🏡 주거복지 상담 기록 & 실시간 요약")
    st.caption("작성된 요약본은 로그인한 모든 팀원이 실시간으로 확인할 수 있습니다.")

    # 3. 데이터 저장소 초기화
    if "summary_logs" not in st.session_state:
        st.session_state.summary_logs = []

    # 4. API 키 및 입력창
    api_key = st.sidebar.text_input("Gemini API Key 입력", type="password")
    writer_name = st.text_input("작성자 이름 (예: 홍길동 복지사)", value="주거복지사")
    meeting_text = st.text_area("상담 및 회의 내용 입력", height=200, placeholder="상담한 내용을 여기에 자유롭게 입력하세요...")

    if st.button("✨ 요약 및 문서화 실행", type="primary"):
        if not api_key:
            st.warning("왼쪽 사이드바에 API 키를 입력해 주세요.")
        elif not meeting_text:
            st.warning("상담 내용을 입력해 주세요.")
        else:
            try:
                client = genai.Client(api_key=api_key)
                prompt = f"다음은 주거복지 상담/회의 내용이다. 핵심 내용, 요청사항, 향후 조치계획으로 구분하여 깔끔하게 요약해줘:\n\n{meeting_text}"
                
                response = client.models.generate_content(
                    model='gemini-2.0-flash',
                    contents=prompt,
                )
                
                now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
                result_data = {
                    "time": now,
                    "writer": writer_name,
                    "original": meeting_text,
                    "summary": response.text
                }
                st.session_state.summary_logs.insert(0, result_data)
                st.success("요약이 완료되어 저장되었습니다!")
                
            except Exception as e:
                st.error(f"오류가 발생했습니다: {e}")

    # 5. 실시간 요약 결과 목록 보기
    st.divider()
    st.subheader("📋 실시간 상담 요약 공유 목록")

    if not st.session_state.summary_logs:
        st.info("아직 등록된 요약 기록이 없습니다.")
    else:
        for item in st.session_state.summary_logs:
            with st.expander(f"[{item['time']}] {item['writer']} 복지사 작성 건"):
                st.markdown("**[ AI 요약 결과 ]**")
                st.write(item["summary"])
                st.markdown("---")
                st.caption("원문 내용:")
                st.text(item["original"])