import streamlit as st
from openai import OpenAI
from datetime import datetime
import uuid
import re
import json
import plotly.graph_objects as go

ADMIN_PASSWORD = "social1234"

st.set_page_config(
    page_title="단지 통합 대화 누적 및 문서화 시스템",
    page_icon="🏢",
    layout="wide"
)

CHECKLIST_ITEMS = {
    "계약": [
        "1. 임대차 계약 만료 및 갱신 시기 도래 (6개월 이내)",
        "2. 임대조건 변경 및 입주 자격(소득·자산) 검토 필요",
        "3. 계약자 변동(사망, 이혼, 세대분리) 및 명의 변경 미비",
        "4. 재계약 필수 제출 서류 장기 미비 및 연락 두절",
        "5. 불법 전대/임차권 양도 의혹 또는 계약 관리 위기"
    ],
    "부금": [
        "1. 임대료 및 관리비 연속 체납 (3개월 이상 체납)",
        "2. 누적 체납 금액 과다 (50만원 이상 또는 독촉 단계)",
        "3. 단수·단전·가스 중단 등 생계 위기 신호 발생",
        "4. 실직·소득 중단·부채로 인한 자력 납부 불능 상태",
        "5. 긴급 주거비/임대보증금 지원 또는 납부 유예 필요"
    ],
    "시설": [
        "1. 세대 내 위생 및 청결 상태 불량 (저장강박, 쓰레기 방치)",
        "2. 주요 시설물 고장 및 파손 (누수, 난방, 도어락, 창문 등)",
        "3. 노후화로 인한 안전사고 위협 (전기 단선, 곰팡이, 붕괴 위험)",
        "4. 고령자/장애인 주거약자 편의시설 미비 (안전손잡이, 문턱 등)",
        "5. 승강기/공용부 이용 불편 및 소방·위생 안전 위해 요인"
    ],
    "민원": [
        "1. 이웃 간 지속적 갈등 발생 (층간소음, 흡연, 누수 분쟁)",
        "2. 사회적 고립 및 고독사 고위험군 (단독 고령, 외부 연락 두절)",
        "3. 정신건강/알코올 의존/우울증 등 집중 케어 필요",
        "4. 공단 직원 또는 이웃에 대한 언어·신체적 폭력/반복 민원",
        "5. 돌봄/식사 지원/지자체 복지서비스 연계 욕구"
    ]
}

@st.cache_resource
def get_shared_cases_store():
    """
    모든 사용자가 공유하는 전체 상담건(단지/호수) 저장소입니다.
    단지 데이터도 효율적으로 검색/관리할 수 있습니다.
    """
    return {}

def clean_markdown_for_txt(text: str) -> str:
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
                "summary": "",
                "checklist": {
                    "계약": [1, 2, 0, 1, 0],
                    "부금": [3, 2, 2, 2, 3],
                    "시설": [2, 1, 2, 3, 1],
                    "민원": [2, 3, 2, 1, 2]
                }
            }

    cleaned = re.sub(r'\*\*(.*?)\*\*', r'\1', cleaned)
    cleaned = re.sub(r'\*(.*?)\*', r'\1', cleaned)
    cleaned = re.sub(r'`(.*?)`', r'\1', cleaned)
    return cleaned

def check_password():
    if "password_correct" not in st.session_state:
        st.session_state["password_correct"] = False

    if not st.session_state["password_correct"]:
        st.title("🔒 단지 상담 통합 관리 시스템 로그인")
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
        
        # 1. Streamlit Secrets(서버 비밀 저장소)에 키가 등록되어 있는지 확인
        default_api_key = ""
        try:
            if "OPENAI_API_KEY" in st.secrets:
                default_api_key = st.secrets["OPENAI_API_KEY"]
        except Exception:
            pass

        if default_api_key:
            st.success("🔒 관리자 서버 API Key 자동 연동됨")
            st.caption("일반 사용자는 별도 API Key 입력 없이 요약 기능을 이용할 수 있습니다.")
            api_key = default_api_key
        else:
            api_key = st.text_input(
                "OpenAI API Key (sk-...)", 
                type="password", 
                help="Streamlit Cloud 설정(Secrets)에 API Key를 등록하면 이 입력창은 자동으로 숨겨집니다."
            )
        
        model = st.selectbox("ChatGPT 모델", ["gpt-4o-mini", "gpt-4o"], index=0)
        
        st.markdown("---")
        st.markdown("### 💾 백업 & 복원 (단지 데이터 보호)")
        
        # JSON 백업 내보내기
        json_data = json.dumps(shared_cases, ensure_ascii=False, indent=2)
        st.download_button(
            label="📥 전체 데이터 백업 (.json)",
            data=json_data,
            file_name=f"housing_cases_backup_{datetime.now().strftime('%Y%m%d_%H%M')}.json",
            mime="application/json",
            use_container_width=True,
            help="서버 재부팅 시를 대비해 전체 단지 데이터를 컴퓨터에 백업합니다."
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
        st.markdown("### ⚡ 수동 화면 갱신")
        if st.button("🔄 즉시 새로고침", use_container_width=True):
            st.rerun()

    st.title("🏢 단지 다자간 상담 대화 통합 관리 시스템")
    st.caption("개 이상의 아파트 단지 및 호수별 상담건을 빠른 검색으로 찾아내고 대화를 실시간 누적하여 AI 문서로 생성합니다.")
    
    # 상단 요약 현황판
    total_cases = len(shared_cases)
    total_chats = sum(len(c["chats"]) for c in shared_cases.values())
    
    col_stat1, col_stat2, col_stat3 = st.columns(3)
    col_stat1.metric("총 등록 상담건수", f"{total_cases} 건")
    col_stat2.metric("누적 발언/대화수", f"{total_chats} 건")
    col_stat3.metric("검색 가능 단지수", "단지 지원")

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
        
        # 체크리스트 기본 데이터 구조 보장
        if "checklist" not in current_case:
            current_case["checklist"] = {
                "계약": [0]*5,
                "부금": [0]*5,
                "시설": [0]*5,
                "민원": [0]*5
            }

        # 헤더 표시
        st.markdown(f"## 📌 선택된 상담건: **[{current_case['complex']}] {current_case['unit']}**")
        st.caption(f"생성일시: {current_case.get('created_at', '-')} | 현재 상태: **{current_case.get('status', '상담중')}** | 누적 대화: **{len(current_case['chats'])}건**")

        # 탭 1: 대화 / 탭 2: 주거복지 진단 체크리스트 / 탭 3: AI 요약 / 탭 4: 관리
        tab_chat, tab_checklist, tab_summary, tab_manage = st.tabs([
            "💬 대화 등록 & 실시간 누적", 
            "📊 주거복지 진단 체크리스트", 
            "📋 통합 문서화 (AI 요약)", 
            "⚙️ 상담건 상태 변경/삭제"
        ])

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
                col_title, col_toggle = st.columns([2, 1])
                with col_title:
                    st.subheader(f"📜 누적 대화 목록 ({len(current_case['chats'])}건)")
                with col_toggle:
                    auto_refresh = st.toggle("🔴 실시간 자동 동기화", value=False)

                if auto_refresh:
                    @st.fragment(run_every="5s")
                    def render_live_chat_list(case_data):
                        st.caption("⚡ 5초 주기 실시간 자동 동기화 중...")
                        if not case_data["chats"]:
                            st.info("아직 누적된 대화가 없습니다.")
                        else:
                            del_idx = None
                            for idx, chat in enumerate(case_data["chats"]):
                                with st.expander(f"[{chat['time']}] {chat['speaker']}: {chat['content'][:25]}...", expanded=True):
                                    st.write(f"**화자:** {chat['speaker']}")
                                    st.write(f"**내용:**\n{chat['content']}")
                                    if st.button("❌ 삭제", key=f"del_{case_data['id']}_{chat['id']}"):
                                        del_idx = idx
                            if del_idx is not None:
                                case_data["chats"].pop(del_idx)
                                st.rerun()

                    render_live_chat_list(current_case)
                else:
                    if not current_case["chats"]:
                        st.info("아직 누적된 대화가 없습니다.")
                    else:
                        del_idx = None
                        for idx, chat in enumerate(current_case["chats"]):
                            with st.expander(f"[{chat['time']}] {chat['speaker']}: {chat['content'][:25]}...", expanded=True):
                                st.write(f"**화자:** {chat['speaker']}")
                                st.write(f"**내용:**\n{chat['content']}")
                                if st.button("❌ 삭제", key=f"del_manual_{current_case['id']}_{chat['id']}"):
                                    del_idx = idx
                        if del_idx is not None:
                            current_case["chats"].pop(del_idx)
                            st.rerun()

        with tab_checklist:
            st.subheader("📋 주택관리공단 주거복지 4대 영역 진단 체크리스트")
            st.caption("계약, 부금, 시설, 민원 각 항목별 심각도 점수를 입력하면 종합 위험도 분석 그래프와 주거복지사 연계 여부가 판정됩니다.")

            # 점수 체계 안내
            st.info("💡 **점수 기준:** 0점 (양호/해당없음) | 1점 (경미/관심) | 2점 (주의/개입필요) | 3점 (심각/긴급지원)")

            col_chk_input, col_chk_graph = st.columns([1.2, 1])

            with col_chk_input:
                # 4대 영역 탭 분리
                subtab_contract, subtab_payment, subtab_facility, subtab_civil = st.tabs([
                    "📑 계약", "💰 부금", "🔧 시설", "🗣️ 민원"
                ])

                categories_map = {
                    "계약": subtab_contract,
                    "부금": subtab_payment,
                    "시설": subtab_facility,
                    "민원": subtab_civil
                }

                updated_scores = {}

                for cat_name, subtab_obj in categories_map.items():
                    with subtab_obj:
                        st.markdown(f"#### [{cat_name}] 영역 진단 항목")
                        cat_scores = []
                        current_scores = current_case["checklist"].get(cat_name, [0]*5)

                        for idx, item_text in enumerate(CHECKLIST_ITEMS[cat_name]):
                            val = st.slider(
                                item_text,
                                min_value=0,
                                max_value=3,
                                value=current_scores[idx] if idx < len(current_scores) else 0,
                                key=f"chk_{current_case['id']}_{cat_name}_{idx}"
                            )
                            cat_scores.append(val)

                        updated_scores[cat_name] = cat_scores

                # 점수 저장 버튼
                if st.button("💾 체크리스트 점수 저장 및 결과 업데이트", type="primary", use_container_width=True):
                    current_case["checklist"] = updated_scores
                    st.success("체크리스트 점수가 저장되었습니다!")
                    st.rerun()

            with col_chk_graph:
                st.subheader("📈 진단 결과 시각화 & 연계 판정")

                # 영역별 점수 계산
                cat_totals = {
                    cat: sum(current_case["checklist"].get(cat, [0]*5))
                    for cat in ["계약", "부금", "시설", "민원"]
                }
                total_score = sum(cat_totals.values())
                max_total = 60 # 4 영역 * 5 항목 * 3점

                # 연계 기준 판정
                # 종합점수 15점 이상 OR 특정 영역 8점 이상일 때 주거복지사 연계 대상
                is_high_risk = (total_score >= 15) or any(score >= 8 for score in cat_totals.values())

                # 연계 판정 배지 출력
                if is_high_risk:
                    st.error(f"🚨 **[주거복지사 현장 연계 대상]** (종합 위험 점수: {total_score} / {max_total}점)")
                    st.markdown("""
                    **[조치 가이드]**
                    - ⚠️ 해당 세대는 주거 위험도가 높아 **주거복지사 현장 방문 및 집중 케어**가 필요합니다.
                    - 📞 **주택관리공단 주거복지지원센터** 또는 **지자체 맞춤형복지팀** 긴급 지원 연계를 권장합니다.
                    """)
                elif total_score >= 8:
                    st.warning(f"🟡 **[주의 / 지속 관찰 대상]** (종합 위험 점수: {total_score} / {max_total}점)")
                    st.caption("주기적인 현장점검 및 체납/민원 상태 모니터링이 권장됩니다.")
                else:
                    st.success(f"🟢 **[정상 / 일반 관리 대상]** (종합 위험 점수: {total_score} / {max_total}점)")
                    st.caption("특이사항 없는 정상 세대입니다.")

                st.markdown("---")

                # Plotly 레이더 차트 (거미줄 그래프) 생성
                radar_categories = ["계약", "부금", "시설", "민원"]
                radar_scores = [cat_totals[c] for c in radar_categories]

                fig = go.Figure()

                fig.add_trace(go.Scatterpolar(
                    r=radar_scores + [radar_scores[0]],
                    theta=radar_categories + [radar_categories[0]],
                    fill='toself',
                    name='위험도 점수',
                    line_color='#ef4444' if is_high_risk else '#3b82f6'
                ))

                fig.update_layout(
                    polar=dict(
                        radialaxis=dict(
                            visible=True,
                            range=[0, 15] # 영역별 최대점수 15점
                        )
                    ),
                    showlegend=False,
                    margin=dict(l=40, r=40, t=30, b=30),
                    height=300
                )

                st.plotly_chart(fig, use_container_width=True)

                # 영역별 세부 점수 막대 그래프
                st.markdown("#### 📊 영역별 위험점수 현황 (영역당 만점 15점)")
                for cat, score in cat_totals.items():
                    progress_val = min(score / 15.0, 1.0)
                    st.write(f"**{cat}**: {score}점 / 15점")
                    st.progress(progress_val)

        with tab_summary:
            st.subheader(f"📋 [{current_case['complex']} {current_case['unit']}] AI 요약 및 문서화")
            
            # 대화 전체 결합
            formatted_transcript = ""
            for item in current_case["chats"]:
                formatted_transcript += f"[{item['speaker']}] ({item['time']})\n{item['content']}\n\n"

            # 체크리스트 점수 요약 텍스트 생성
            chk_data = current_case.get("checklist", {})
            chk_summary_str = ""
            for cat, scores in chk_data.items():
                chk_summary_str += f"- {cat} 영역 합계: {sum(scores)}점/15점\n"

            if st.button("✨ 이 상담건 전체 요약 실행", type="primary", use_container_width=True):
                if not api_key:
                    st.warning("사이드바에 OpenAI API Key(`sk-...`)를 입력해 주세요!")
                elif not current_case["chats"]:
                    st.warning("요약할 대화 내역이 없습니다. 먼저 대화를 입력해 주세요!")
                else:
                    try:
                        with st.spinner("ChatGPT가 해당 단지/호수의 대화 및 체크리스트 결과를 문서화 중입니다..."):
                            client = OpenAI(api_key=api_key)
                            prompt = f"""
당신은 주택관리공단 주거복지 전문가입니다.
아래 [{current_case['complex']} {current_case['unit']}] 상담건의 전체 대화 및 4대 영역 진단 결과를 바탕으로 '주거복지 종합 관리 및 보고서'를 작성해 주세요.

[상담 대상 및 위치]
- 단지명: {current_case['complex']}
- 동/호수: {current_case['unit']}

[4대 영역 진단 점수]
{chk_summary_str}

[누적 대화 내역]
{formatted_transcript}

[작성 규칙]
1. 아래 서식에 맞추어 마크다운으로 작성하세요:
   # 📋 주거복지 상담 및 종합 관리 보고서
   **단지명:** {current_case['complex']} | **대상:** {current_case['unit']}
   
   ## 1. 개요 및 상담 배경
   - 주요 참여자 및 핵심 상담 목적 요약
   
   ## 2. 4대 영역(계약·부금·시설·민원) 현황 및 위험도 평가
   - 체크리스트 진단 점수 기반 주요 위기 요인 요약
   
   ## 3. 핵심 결정 사항 및 주거복지사 연계 필요성
   - 상담을 통해 합의된 사항 및 복지 연계 판단
   
   ## 4. 향후 조치 과제 (Action Items)
   - [담당자/신청자/주거복지사] 할 일 및 기한 명시
"""
                            response = client.chat.completions.create(
                                model=model,
                                messages=[
                                    {"role": "system", "content": "유능한 주택관리공단 주거복지 전문 작성 도우미입니다."},
                                    {"role": "user", "content": prompt}
                                ],
                                temperature=0.3
                            )
                            current_case["summary"] = response.choices[0].message.content
                            st.success("요약 생성이 완료되었습니다!")
                            st.rerun()
                    except Exception as e:
                        st.error(f"오류가 발생했습니다: {e}")

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
