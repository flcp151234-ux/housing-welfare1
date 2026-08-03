import streamlit as st
from openai import OpenAI
from datetime import datetime
import uuid

# 페이지 기본 설정
st.set_page_config(
    page_title="실시간 다자간 대화 누적 및 자동 문서화 시스템",
    page_icon="📋",
    layout="wide"
)

# 서버 메모리에 모든 사용자가 공유할 대화 목록 저장소 생성
@st.cache_resource
def get_shared_chat_store():
    """
    모든 접속자(A, B, C...)가 공유하는 실시간 대화 저장소입니다.
    서버 메모리에 보관되어 각 사용자가 등록한 내용이 함께 쌓입니다.
    """
    return []

def check_password():
    if "password_correct" not in st.session_state:
        st.session_state["password_correct"] = False

    if not st.session_state["password_correct"]:
        st.title("🔒 로그인")
        pwd = st.text_input("접속 비밀번호를 입력하세요 (기본: social1234)", type="password")
        if st.button("로그인"):
            if pwd == "social1234":
                st.session_state["password_correct"] = True
                st.rerun()
            else:
                st.error("비밀번호가 올바르지 않습니다.")
        return False
    return True

if check_password():
    # 공유 저장소 가져오기
    shared_chats = get_shared_chat_store()

    with st.sidebar:
        st.header("⚙️ 설정 및 관리")
        api_key = st.text_input("OpenAI API Key 입력", type="password", placeholder="sk-...")
        model = st.selectbox("사용할 ChatGPT 모델", ["gpt-4o-mini", "gpt-4o"], index=0)
        
        st.markdown("---")
        st.markdown("### 🔄 공유 데이터 관리")
        col_side1, col_side2 = st.columns(2)
        with col_side1:
            if st.button("🔄 새로고침", help="다른 사람이 새로 등록한 글을 불러옵니다."):
                st.rerun()
        with col_side2:
            if st.button("🗑️ 전체 비우기", type="secondary", help="누적된 대화 기록을 모두 삭제합니다."):
                shared_chats.clear()
                st.success("대화 기록이 초기화되었습니다.")
                st.rerun()

        st.markdown("---")
        st.markdown("### 💡 실시간 사용 가이드")
        st.markdown("""
        1. **각자 대화 등록**: A, B, C가 자신의 이름과 대화 내용/녹취록을 등록합니다.
        2. **실시간 공유**: 모든 사용자가 누적된 대화 목록을 확인할 수 있습니다.
        3. **통합 요약**: 대화 축적이 완료되면 아래 **[✨ 누적 대화 전체 요약]** 버튼을 누릅니다.
        """)

    # 메인 타이틀
    st.title("👥 실시간 다자간 대화 누적 & 통합 문서화 시스템")
    st.caption("A, B, C 각 컴퓨터에서 대화를 등록하면 한곳에 누적되며, AI가 전체 내용을 종합하여 보고서로 정리합니다.")
    st.markdown("---")

    # 메인 레이아웃: 좌측(대화 입력 및 누적 목록), 우측(요약 문서 결과)
    col1, col2 = st.columns([1, 1])

    with col1:
        st.subheader("💬 1. 대화 내용 등록 (각자 입력)")
        
        with st.form("chat_entry_form", clear_on_submit=True):
            speaker_name = st.text_input("발언자 이름/직급", placeholder="예: 김철수 팀장, 이영희 대리, 박OO 신청자 등")
            chat_text = st.text_area("대화 / 발언 / 상담 내용", height=120, placeholder="녹취록 텍스트나 발언 내용을 입력하세요...")
            submit_button = st.form_submit_button("➕ 대화 등록하기", use_container_width=True)

            if submit_button:
                if not speaker_name.strip():
                    st.warning("발언자 이름을 입력해 주세요!")
                elif not chat_text.strip():
                    st.warning("대화 내용을 입력해 주세요!")
                else:
                    new_entry = {
                        "id": str(uuid.uuid4()),
                        "time": datetime.now().strftime("%H:%M:%S"),
                        "speaker": speaker_name.strip(),
                        "content": chat_text.strip()
                    }
                    shared_chats.append(new_entry)
                    st.success(f"'{speaker_name}'님의 대화가 공용 저장소에 등록되었습니다!")
                    st.rerun()

        st.markdown("---")
        st.subheader(f"📜 2. 누적 대화 목록 (총 {len(shared_chats)}건)")

        if not shared_chats:
            st.info("아직 등록된 대화 내용이 없습니다. 위 양식에서 첫 대화를 등록해 보세요!")
        else:
            # 삭제 처리를 위한 항목 추적
            to_delete = None
            for idx, item in enumerate(shared_chats):
                with st.expander(f"[{item['time']}] {item['speaker']}: {item['content'][:30]}...", expanded=True):
                    st.write(f"**화자:** {item['speaker']}")
                    st.write(f"**시간:** {item['time']}")
                    st.write(f"**내용:**\n{item['content']}")
                    if st.button("❌ 항목 삭제", key=f"del_{item['id']}"):
                        to_delete = idx

            if to_delete is not None:
                shared_chats.pop(to_delete)
                st.rerun()

    with col2:
        st.subheader("📋 3. 통합 문서화 결과")

        # 저장된 전체 대화록을 하나의 텍스트로 합치기
        formatted_full_transcript = ""
        for item in shared_chats:
            formatted_full_transcript += f"[{item['speaker']}] ({item['time']})\n{item['content']}\n\n"

        if st.button("✨ 누적 대화 전체 요약 및 문서화 실행", type="primary", use_container_width=True):
            if not api_key:
                st.warning("사이드바에 OpenAI API Key(`sk-...`)를 먼저 입력해 주세요!")
            elif not shared_chats:
                st.warning("요약할 누적 대화가 없습니다. 대화를 먼저 등록해 주세요!")
            else:
                try:
                    with st.spinner("ChatGPT가 누적된 모든 대화 내용을 종합 분석하여 보고서를 작성 중입니다..."):
                        client = OpenAI(api_key=api_key)

                        prompt = f"""
당신은 전문 문서 작성 및 회의록 요약 전문가입니다.
여러 명의 작성자 및 참여자가 실시간으로 등록한 전체 대화 내용을 바탕으로 깔끔하게 정리된 '통합 상담 및 업무 처리 보고서'를 작성해 주세요.

[누적 전체 대화 내용]
{formatted_full_transcript}

[작성 규칙]
1. 불필요한 인사말, 사담, 중복 표현은 제외하고 핵심 정보 위주로 정제하세요.
2. 아래 서식 구조에 맞추어 마크다운으로 깔끔하게 작성해 주세요:
   # 📋 실시간 통합 상담 및 업무 보고서
   ## 1. 개요 및 참여자
   - 주요 참여자/화자 목록 및 핵심 주제 요약
   ## 2. 주요 논의 현황 및 주요 사실관계
   - 각 사안별 논의 내용 및 서류/자격 등 현황
   ## 3. 결정 및 합의 사항
   - 회의/상담을 통해 확정된 사항
   ## 4. 향후 조치 과제 (Action Items)
   - 담당자/대상자별 할 일 및 기한 명시 (예: [이대리] ~서류 접수 처리, [신청자] ~제출 등)
"""

                        response = client.chat.completions.create(
                            model=model,
                            messages=[
                                {"role": "system", "content": "유능하고 친절한 문서 요약 도우미입니다."},
                                {"role": "user", "content": prompt}
                            ],
                            temperature=0.3
                        )

                        result_text = response.choices[0].message.content
                        st.session_state["last_summary"] = result_text

                except Exception as e:
                    st.error(f"오류가 발생했습니다: {e}")

        # 요약 결과 출력 및 다운로드 기능 제공
        if "last_summary" in st.session_state and st.session_state["last_summary"]:
            st.markdown("---")
            st.markdown(st.session_state["last_summary"])
            
            st.download_button(
                label="📥 요약 보고서 다운로드 (.md)",
                data=st.session_state["last_summary"],
                file_name=f"통합_상담보고서_{datetime.now().strftime('%Y%m%d_%H%M')}.md",
                mime="text/markdown"
            )
