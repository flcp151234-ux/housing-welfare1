import streamlit as st
from openai import OpenAI
from datetime import datetime
import uuid
import re
import json

ADMIN_PASSWORD = "dltjdwoghdwjdantlswhdgur"

st.set_page_config(
    page_title="주택관리공단 주거복지 경진대회",
    page_icon="🏢",
    layout="wide"
)

@st.cache_resource
def get_shared_cases_store():
    """
    모든 사용자가 공유하는 전체 상담건(단지/호수) 저장소입니다.
    500개 이상의 단지 데이터도 효율적으로 검색/관리할 수 있습니다.
    """
    return {}

def clean_markdown_for_txt(text: str) -> str:
    cleaned = re.sub(r'#+\s*', '', text)
    cleaned = re.sub(r'\*\*(.*?)\*\*', r'\1', cleaned)
    cleaned = re.sub(r'\*(.*?)\*', r'\1', cleaned)
    cleaned = re.sub(r'`(.*?)`', r'\1', cleaned)
    return cleaned

def check_password():
    if "password_correct" not in st.session_state:
        st.session_state["password_correct"] = False

    if not st.session_state["password_correct"]:
        st.title("🔒 500+ 단지 상담 통합 관리 시스템 로그인")
        pwd = st.text_input("접속 비밀번호를 입력하세요", type="password")
        if st.button("로그인", use_container_width=True):
            if pwd == ADMIN_PASSWORD:
                st.session_state["password_correct"] = True
                st.rerun()
            else:
                st.error("비밀번호가 올바르지 않습니다.")
        return False
    return True

if check_password():
    shared_cases = get_shared_cases_store()

    # 샘플 데이터가 없으면 예시 1개 자동 생성
    if not shared_cases:
        sample_id = "sample-101"
        shared_cases[sample_id] = {
            "id": sample_id,
            "complex": "등촌7단지",
            "unit": "701동 104호",
            "status": "상담중",
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "chats": [
                {
                    "id": str(uuid.uuid4()),
                    "time": datetime.now().strftime("%H:%M:%S"),
                    "speaker": "김철수 팀장",
                    "content": "등촌7단지 701동 104호 주거복지 지원 신청 관련 상담 시작합니다."
                }
            ],
            "summary": ""
        }

    with st.sidebar:
        st.header("⚙️ 시스템 설정 및 관리")
        api_key = st.text_input("OpenAI API Key (sk-...)", type="password")
        model = st.selectbox("ChatGPT 모델", ["gpt-4o-mini", "gpt-4o"], index=0)
        
        st.markdown("---")
        st.markdown("### 💾 백업 & 복원 (500+ 단지 데이터 보호)")
        
        # JSON 백업 내보내기
        json_data = json.dumps(shared_cases, ensure_ascii=False, indent=2)
        st.download_button(
            label="📥 전체 데이터 백업 (.json)",
            data=json_data,
            file_name=f"housing_cases_backup_{datetime.now().strftime('%Y%m%d_%H%M')}.json",
            mime="application/json",
            use_container_width=True,
            help="서버 재부팅 시를 대비해 전체 500+ 단지 데이터를 컴퓨터에 백업합니다."
        )

        # JSON 백업 복원하기
        uploaded_file = st.file_uploader("📤 백업 파일 복원", type=["json"])
        if uploaded_file is not None:
            if st.button("🔄 백업 데이터 덮어쓰기 복원", type="secondary", use_container_width=True):
                try:
                    data = json.load(uploaded_file)
                    shared_cases.clear()
                    shared_cases.update(data)
                    st.success("데이터가 성공적으로 복원되었습니다!")
                    st.rerun()
                except Exception as e:
                    st.error(f"복원 실패: {e}")

        st.markdown("---")
        st.markdown("### 🔄 공유 데이터 제어")
        col_sb1, col_sb2 = st.columns(2)
        with col_sb1:
            if st.button("🔄 새로고침", use_container_width=True):
                st.rerun()
        with col_sb2:
            if st.button("🗑️ 전체 초기화", type="secondary", use_container_width=True):
                shared_cases.clear()
                st.success("전체 목록이 초기화되었습니다.")
                st.rerun()

    st.title("🏢 500+ 단지 다자간 상담 대화 통합 관리 시스템")
    st.caption("500개 이상의 아파트 단지 및 호수별 상담건을 빠른 검색으로 찾아내고 대화를 실시간 누적하여 AI 문서로 생성합니다.")
    
    # 상단 요약 현황판
    total_cases = len(shared_cases)
    total_chats = sum(len(c["chats"]) for c in shared_cases.values())
    
    col_stat1, col_stat2, col_stat3 = st.columns(3)
    col_stat1.metric("총 등록 상담건수", f"{total_cases} 건")
    col_stat2.metric("누적 발언/대화수", f"{total_chats} 건")
    col_stat3.metric("검색 가능 단지수", "500+ 단지 지원")

    st.markdown("---")

    col_search, col_add = st.columns([2, 1])

    with col_search:
        st.subheader("🔍 상담건 빠른 검색 & 선택")
        search_kw = st.text_input("🔎 단지명, 동/호수 검색어 입력", placeholder="예: 등촌7단지, 701동, 104호 등...")
        
        # 검색 필터링 로직
        filtered_cases = {}
        for cid, cinfo in shared_cases.items():
            full_label = f"{cinfo.get('complex', '')} {cinfo.get('unit', '')}"
            if not search_kw.strip() or search_kw.strip().lower() in full_label.lower():
                filtered_cases[cid] = cinfo

        if not filtered_cases:
            st.warning("검색 결과가 없습니다. 우측에서 새 상담건을 등록해 보세요!")
            selected_case_id = None
        else:
            options_dict = {
                f"[{cinfo.get('complex', '미지정')}] {cinfo.get('unit', '미지정')} (대화 {len(cinfo.get('chats', []))}건) - {cinfo.get('status', '상담중')}": cid
                for cid, cinfo in filtered_cases.items()
            }
            selected_label = st.selectbox(
                "목록에서 관리할 상담건을 선택하세요 (키보드로 타이핑 검색 가능):",
                options=list(options_dict.keys()),
                index=0
            )
            selected_case_id = options_dict[selected_label]

    with col_add:
        st.subheader("➕ 새 상담건(단지/호수) 등록")
        with st.form("add_new_case_form", clear_on_submit=True):
            new_complex = st.text_input("단지명", placeholder="예: 등촌7단지, 가양9단지 등")
            new_unit = st.text_input("동 / 호수 / 대상자", placeholder="예: 701동 104호, 김OO 대상자")
            new_status = st.selectbox("진행 상태", ["상담중", "서류대기", "완료", "보류"])
            submit_case = st.form_submit_button("✨ 새 상담건 추가하기", use_container_width=True)

            if submit_case:
                if not new_complex.strip() or not new_unit.strip():
                    st.warning("단지명과 동/호수를 모두 입력해 주세요!")
                else:
                    new_id = str(uuid.uuid4())
                    shared_cases[new_id] = {
                        "id": new_id,
                        "complex": new_complex.strip(),
                        "unit": new_unit.strip(),
                        "status": new_status,
                        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                        "chats": [],
                        "summary": ""
                    }
                    st.success(f"'{new_complex} {new_unit}' 상담건이 생성되었습니다!")
                    st.rerun()

    st.markdown("---")

    if selected_case_id and selected_case_id in shared_cases:
        current_case = shared_cases[selected_case_id]
        
        # 헤더 표시
        st.markdown(f"## 📌 선택된 상담건: **[{current_case['complex']}] {current_case['unit']}**")
        st.caption(f"생성일시: {current_case.get('created_at', '-')} | 현재 상태: **{current_case.get('status', '상담중')}** | 누적 대화: **{len(current_case['chats'])}건**")

        # 탭 1: 대화 등록 및 목록 / 탭 2: 요약 및 문서화
        tab_chat, tab_summary, tab_manage = st.tabs(["💬 대화 등록 & 실시간 누적", "📋 통합 문서화 (AI 요약)", "⚙️ 상담건 상태 변경/삭제"])

        with tab_chat:
            col_in1, col_in2 = st.columns([1, 1])

            with col_in1:
                st.subheader("💬 대화 내용 입력")
                with st.form(f"chat_form_{current_case['id']}", clear_on_submit=True):
                    speaker_name = st.text_input("발언자 이름/직급", placeholder="예: 김철수 팀장, 이영희 대리, 신청자 본인")
                    chat_text = st.text_area("대화 / 발언 / 상담 내용", height=140, placeholder="녹취록 텍스트나 대화 내용을 복사해서 입력하세요...")
                    btn_submit_chat = st.form_submit_button("➕ 대화 등록하기", use_container_width=True)

                    if btn_submit_chat:
                        if not speaker_name.strip() or not chat_text.strip():
                            st.warning("발언자와 대화 내용을 모두 입력해 주세요!")
                        else:
                            new_chat = {
                                "id": str(uuid.uuid4()),
                                "time": datetime.now().strftime("%H:%M:%S"),
                                "speaker": speaker_name.strip(),
                                "content": chat_text.strip()
                            }
                            current_case["chats"].append(new_chat)
                            st.success("대화가 등록되었습니다!")
                            st.rerun()

            with col_in2:
                st.subheader(f"📜 누적 대화 목록 ({len(current_case['chats'])}건)")
                if not current_case["chats"]:
                    st.info("아직 누적된 대화가 없습니다. 왼쪽 양식에서 대화를 등록하세요!")
                else:
                    del_idx = None
                    for idx, chat in enumerate(current_case["chats"]):
                        with st.expander(f"[{chat['time']}] {chat['speaker']}: {chat['content'][:25]}...", expanded=True):
                            st.write(f"**화자:** {chat['speaker']}")
                            st.write(f"**시간:** {chat['time']}")
                            st.write(f"**내용:**\n{chat['content']}")
                            if st.button("❌ 삭제", key=f"del_{current_case['id']}_{chat['id']}"):
                                del_idx = idx

                    if del_idx is not None:
                        current_case["chats"].pop(del_idx)
                        st.rerun()

        with tab_summary:
            st.subheader(f"📋 [{current_case['complex']} {current_case['unit']}] AI 요약 및 문서화")
            
            # 대화 전체 결합
            formatted_transcript = ""
            for item in current_case["chats"]:
                formatted_transcript += f"[{item['speaker']}] ({item['time']})\n{item['content']}\n\n"

            if st.button("✨ 이 상담건 전체 요약 실행", type="primary", use_container_width=True):
                if not api_key:
                    st.warning("사이드바에 OpenAI API Key(`sk-...`)를 입력해 주세요!")
                elif not current_case["chats"]:
                    st.warning("요약할 대화 내역이 없습니다. 먼저 대화를 입력해 주세요!")
                else:
                    try:
                        with st.spinner("ChatGPT가 해당 단지/호수의 전체 대화를 정리 및 요약 중입니다..."):
                            client = OpenAI(api_key=api_key)
                            prompt = f"""
당신은 주거복지 상담 및 업무 처리 전문가입니다.
아래 [{current_case['complex']} {current_case['unit']}] 상담건의 전체 대화 내역을 바탕으로 공식 '상담 및 업무 보고서'를 작성해 주세요.

[상담 대상 및 위치]
- 단지명: {current_case['complex']}
- 동/호수: {current_case['unit']}

[누적 대화 내역]
{formatted_transcript}

[작성 규칙]
1. 사담, 중복 표현, 인사말은 배제하고 핵심 업무 및 상담 정보 위주로 정리하세요.
2. 아래 서식에 맞추어 마크다운으로 깔끔하게 작성하세요:
   # 📋 주거복지 상담 및 업무 처리 보고서
   **단지명:** {current_case['complex']} | **대상:** {current_case['unit']}
   
   ## 1. 개요 및 상담 배경
   - 주요 참여자 및 핵심 상담 목적 요약
   
   ## 2. 주요 논의 현황 및 서류/자격 검토
   - 자격 조건, 제출 서류 및 미비 사항
   
   ## 3. 핵심 결정 사항
   - 회의 및 상담을 통해 최종 합의/결정된 사항
   
   ## 4. 담당자별 향후 조치 과제 (Action Items)
   - [담당자/신청자] 할 일 및 기한 명시
"""
                            response = client.chat.completions.create(
                                model=model,
                                messages=[
                                    {"role": "system", "content": "유능한 주거복지 상담 전문 문서 작성 도우미입니다."},
                                    {"role": "user", "content": prompt}
                                ],
                                temperature=0.3
                            )
                            current_case["summary"] = response.choices[0].message.content
                            st.success("요약 생성이 완료되었습니다!")
                            st.rerun()
                    except Exception as e:
                        st.error(f"오류가 발생했습니다: {e}")

            # 요약 결과 출력
            if current_case.get("summary"):
                st.markdown("---")
                summary_text = current_case["summary"]
                st.markdown(summary_text)

                st.markdown("---")
                st.markdown("### 📥 요약 보고서 저장")
                col_dl1, col_dl2 = st.columns(2)
                
                txt_content = clean_markdown_for_txt(summary_text)
                with col_dl1:
                    st.download_button(
                        label="📄 텍스트 파일 (.txt) 다운로드",
                        data=txt_content,
                        file_name=f"상담보고서_{current_case['complex']}_{current_case['unit']}_{datetime.now().strftime('%Y%m%d')}.txt",
                        mime="text/plain",
                        use_container_width=True
                    )
                with col_dl2:
                    st.download_button(
                        label="📝 마크다운 파일 (.md) 다운로드",
                        data=summary_text,
                        file_name=f"상담보고서_{current_case['complex']}_{current_case['unit']}_{datetime.now().strftime('%Y%m%d')}.md",
                        mime="text/markdown",
                        use_container_width=True
                    )
                
                st.info("💡 **PDF 저장 방법:** 브라우저에서 `Ctrl + P` (Mac은 `Cmd + P`)를 눌러 **[PDF로 저장]**을 선택하세요.")

        with tab_manage:
            st.subheader("⚙️ 상담건 상태 변경 및 삭제")
            col_m1, col_m2 = st.columns(2)
            
            with col_m1:
                st.markdown("### 🔄 상태 변경")
                new_st = st.selectbox("진행 상태 선택", ["상담중", "서류대기", "완료", "보류"], index=["상담중", "서류대기", "완료", "보류"].index(current_case.get("status", "상담중")))
                if st.button("상태 업데이트", use_container_width=True):
                    current_case["status"] = new_st
                    st.success(f"상태가 '{new_st}'(으)로 변경되었습니다.")
                    st.rerun()

            with col_m2:
                st.markdown("### 🗑️ 상담건 삭제")
                st.warning("이 상담건과 누적된 모든 대화 및 요약 보고서가 완전히 삭제됩니다.")
                if st.button("⚠️ 이 상담건 전체 삭제하기", type="secondary", use_container_width=True):
                    del shared_cases[selected_case_id]
                    st.success("상담건이 삭제되었습니다.")
                    st.rerun()
