import streamlit as st
from openai import OpenAI
from datetime import datetime
import uuid
import re

# ---------------------------------------------------------
# [보안 설정] 원하는 접속 비밀번호를 여기서 수정하세요!
# ---------------------------------------------------------
ADMIN_PASSWORD = "dltjdwo"

# 페이지 기본 설정
st.set_page_config(
    page_title="실시간 상담건별 다자간 대화 누적 및 자동 문서화 시스템",
    page_icon="📋",
    layout="wide"
)

# 서버 메모리에 모든 사용자가 공유할 상담건(룸/탭)별 대화 저장소 생성
@st.cache_resource
def get_shared_chat_store():
    """
    모든 접속자가 공유하는 실시간 상담건별 저장소입니다.
    dict 구조: { "상담건 이름": [대화목록] }
    """
    return {
        "등촌7단지 701동 104호": [],
        "공통 주거복지 상담": []
    }

def clean_markdown_for_txt(text: str) -> str:
    """마크다운 기호를 제거하여 일반 텍스트 파일용으로 변환해 줍니다."""
    cleaned = re.sub(r'#+\s*', '', text)
    cleaned = re.sub(r'\*\*(.*?)\*\*', r'\1', cleaned)
    cleaned = re.sub(r'\*(.*?)\*', r'\1', cleaned)
    cleaned = re.sub(r'`(.*?)`', r'\1', cleaned)
    return cleaned

def check_password():
    if "password_correct" not in st.session_state:
        st.session_state["password_correct"] = False

    if not st.session_state["password_correct"]:
        st.title("🔒 로그인")
        pwd = st.text_input("접속 비밀번호를 입력하세요", type="password")
        if st.button("로그인"):
            if pwd == ADMIN_PASSWORD:
                st.session_state["password_correct"] = True
                st.rerun()
            else:
                st.error("비밀번호가 올바르지 않습니다.")
        return False
    return True

if check_password():
    shared_store = get_shared_chat_store()

    # 사이드바 설정
    with st.sidebar:
        st.header("⚙️ 설정 및 관리")
        api_key = st.text_input("OpenAI API Key 입력", type="password", placeholder="sk-...")
        model = st.selectbox("사용할 ChatGPT 모델", ["gpt-4o-mini", "gpt-4o"], index=0)

        st.markdown("---")
        st.markdown("### 🏢 상담건(탭) 관리")
        new_room_name = st.text_input("새 상담건 / 호명 입력", placeholder="예: 등촌7단지 701동 105호")
        if st.button("➕ 상담건(탭) 추가하기", use_container_width=True):
            room_clean = new_room_name.strip()
            if room_clean:
                if room_clean not in shared_store:
                    shared_store[room_clean] = []
                    st.success(f"'{room_clean}' 상담건이 추가되었습니다!")
                    st.rerun()
                else:
                    st.warning("이미 존재하는 상담건 이름입니다.")
            else:
                st.warning("상담건 이름을 입력해 주세요.")

        st.markdown("---")
        if st.button("🔄 새로고침", help="다른 사람이 등록한 최신 글을 불러옵니다.", use_container_width=True):
            st.rerun()

        st.markdown("---")
        st.markdown("### 💡 사용 가이드")
        st.markdown("""
        1. **상담건 선택**: 상단 탭에서 해당하는 상담건(예: 701동 104호)을 선택합니다.
        2. **대화 등록**: 팀원 및 상담자가 해당 탭에서 발언 내용을 등록합니다.
        3. **독립 요약**: 각 탭별로 대화가 완벽히 분리되어 개별 보고서로 요약됩니다.
        """)

    # 메인 타이틀
    st.title("👥 실시간 상담건별 다자간 대화 누적 & 자동 문서화 시스템")
    st.caption("상담건(세대/팀)별로 탭을 나누어 대화를 입력하고, 각 탭의 내용을 개별 보고서로 종합합니다.")
    st.markdown("---")

    room_names = list(shared_store.keys())

    if not room_names:
        st.info("현재 생성된 상담건이 없습니다. 사이드바에서 새 상담건을 추가해 주세요.")
    else:
        # 상단 탭 생성
        tabs = st.tabs(room_names)

        for i, room in enumerate(room_names):
            with tabs[i]:
                chat_list = shared_store[room]

                # 삭제 및 비우기 컨트롤
                col_title, col_del = st.columns([3, 1])
                with col_title:
                    st.markdown(f"### 📍 [{room}] 상담 대화방")
                with col_del:
                    if len(room_names) > 1:
                        if st.button(f"🗑️ '{room}' 탭 삭제", key=f"del_room_{i}"):
                            del shared_store[room]
                            st.rerun()

                col1, col2 = st.columns([1, 1])

                with col1:
                    st.subheader("💬 대화 내용 등록")
                    form_key = f"form_{room}"
                    with st.form(form_key, clear_on_submit=True):
                        speaker_name = st.text_input("발언자 이름/직급", placeholder="예: 김철수 팀장, 박OO 신청자", key=f"spk_{room}")
                        chat_text = st.text_area("대화 / 발언 / 상담 내용", height=120, placeholder="대화 내용을 입력하세요...", key=f"txt_{room}")
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
                                chat_list.append(new_entry)
                                st.success(f"'{speaker_name}'님의 대화가 등록되었습니다!")
                                st.rerun()

                    st.markdown("---")
                    st.subheader(f"📜 누적 대화 목록 (총 {len(chat_list)}건)")

                    col_c1, col_c2 = st.columns([2, 1])
                    with col_c2:
                        if st.button("🗑️ 대화 전체 비우기", key=f"clear_chats_{room}", help="현재 탭의 모든 대화를 삭제합니다."):
                            chat_list.clear()
                            st.rerun()

                    if not chat_list:
                        st.info("아직 등록된 대화 내용이 없습니다. 위 양식에서 대화를 등록해 보세요!")
                    else:
                        to_delete = None
                        for idx, item in enumerate(chat_list):
                            with st.expander(f"[{item['time']}] {item['speaker']}: {item['content'][:25]}...", expanded=True):
                                st.write(f"**화자:** {item['speaker']}")
                                st.write(f"**시간:** {item['time']}")
                                st.write(f"**내용:**\n{item['content']}")
                                if st.button("❌ 항목 삭제", key=f"del_item_{room}_{item['id']}"):
                                    to_delete = idx

                        if to_delete is not None:
                            chat_list.pop(to_delete)
                            st.rerun()

                with col2:
                    st.subheader("📋 통합 문서화 결과")

                    # 전체 대화 텍스트 생성
                    formatted_full_transcript = ""
                    for item in chat_list:
                        formatted_full_transcript += f"[{item['speaker']}] ({item['time']})\n{item['content']}\n\n"

                    summary_key = f"summary_{room}"

                    if st.button(f"✨ [{room}] 전체 요약 및 문서화 실행", type="primary", use_container_width=True, key=f"btn_sum_{room}"):
                        if not api_key:
                            st.warning("사이드바에 OpenAI API Key(`sk-...`)를 먼저 입력해 주세요!")
                        elif not chat_list:
                            st.warning("요약할 대화 내용이 없습니다. 대화를 먼저 등록해 주세요!")
                        else:
                            try:
                                with st.spinner(f"ChatGPT가 '{room}'의 대화 내용을 종합 분석 중입니다..."):
                                    client = OpenAI(api_key=api_key)

                                    prompt = f"""
당신은 주거복지 및 업무 회의 전문 요약 도우미입니다.
아래 대화 내용은 [{room}] 건에 관련된 대화 기록입니다. 
핵심 정보 위주로 정제하여 깔끔한 '상담 및 업무 처리 보고서'를 작성해 주세요.

[상담건/대상]
{room}

[누적 대화 내용]
{formatted_full_transcript}

[작성 규칙]
1. 불필요한 인사말 및 사담은 제외하고 작성하세요.
2. 아래 서식에 맞춰 마크다운 형태로 깔끔하게 정리하세요:
   # 📋 [{room}] 상담 및 업무 보고서
   ## 1. 개요 및 참여자
   - 주요 참여자 및 핵심 상담 주제
   ## 2. 주요 논의 및 사실관계 현황
   - 구체적 논의 내용, 자격/서류 검토 현황 등
   ## 3. 결정 및 합의 사항
   ## 4. 향후 조치 과제 (Action Items)
   - 담당자/신청자별 할 일 및 기한
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
                                    st.session_state[summary_key] = result_text

                            except Exception as e:
                                st.error(f"오류가 발생했습니다: {e}")

                    # 요약 결과 출력 및 다운로드
                    if summary_key in st.session_state and st.session_state[summary_key]:
                        st.markdown("---")
                        summary_content = st.session_state[summary_key]
                        st.markdown(summary_content)

                        st.markdown("---")
                        st.markdown("### 📥 요약 보고서 저장하기")

                        col_dl1, col_dl2 = st.columns(2)

                        txt_content = clean_markdown_for_txt(summary_content)
                        with col_dl1:
                            st.download_button(
                                label="📄 텍스트 파일 (.txt) 다운로드",
                                data=txt_content,
                                file_name=f"{room}_보고서_{datetime.now().strftime('%Y%m%d_%H%M')}.txt",
                                mime="text/plain",
                                use_container_width=True,
                                key=f"dl_txt_{room}"
                            )

                        with col_dl2:
                            st.download_button(
                                label="📝 마크다운 파일 (.md) 다운로드",
                                data=summary_content,
                                file_name=f"{room}_보고서_{datetime.now().strftime('%Y%m%d_%H%M')}.md",
                                mime="text/markdown",
                                use_container_width=True,
                                key=f"dl_md_{room}"
                            )

                        st.info("""
                        💡 **PDF 저장 팁:** 브라우저에서 `Ctrl + P` (Mac은 `Cmd + P`)를 누른 후 **[PDF로 저장]**을 선택하시면 이 보고서 화면을 그대로 PDF 파일로 저장하실 수 있습니다.
                        """)
