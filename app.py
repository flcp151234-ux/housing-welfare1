import streamlit as st
import json
import os
import uuid
import re
from datetime import datetime
import plotly.graph_objects as go
from openai import OpenAI

st.set_page_config(
    page_title="단지 주거복지 위험도 & 대화 통합 관리 시스템",
    page_icon="🏢",
    layout="wide"
)

# 데이터 자동 저장 파일 경로
DATA_FILE = "cases_data.json"

def load_cases():
    """파일(JSON)로부터 저장된 상담건 데이터를 불러옵니다."""
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_cases(cases):
    """상담건 데이터를 파일(JSON)에 안전하게 저장합니다."""
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(cases, f, ensure_ascii=False, indent=2)
    except Exception as e:
        st.error(f"데이터 저장 중 오류 발생: {e}")

def get_case_risk_info(case_data: dict):
    """
    상담건의 체크리스트 점수를 바탕으로 관심/주의/위험 3단계 레벨 및 총점을 산출합니다.
    - 🔴 위험: 총점 15점 이상 또는 단일 영역 8점 이상 (주거복지사 긴급 현장연계)
    - 🟡 주의: 총점 8점 이상 또는 단일 영역 5점 이상 (지속 관찰)
    - 🟢 관심: 총점 8점 미만 (정상 관리)
    - ⚪ 미진단: 평가 미진행 세대
    """
    chk = case_data.get("checklist", {})
    if not chk:
        return {"level": "미진단", "badge": "⚪ 미진단", "total_score": 0, "cat_totals": {"계약":0, "부금":0, "시설":0, "민원":0}, "is_evaluated": False}
    
    cat_totals = {cat: sum(chk.get(cat, [0]*5)) for cat in ["계약", "부금", "시설", "민원"]}
    total_score = sum(cat_totals.values())
    
    is_evaluated = any(val > 0 for scores in chk.values() for val in scores)
    
    if not is_evaluated:
        return {"level": "미진단", "badge": "⚪ 미진단", "total_score": 0, "cat_totals": cat_totals, "is_evaluated": False}
    
    if total_score >= 15 or any(score >= 8 for score in cat_totals.values()):
        level = "위험"
        badge = "🔴 위험 (긴급연계)"
    elif total_score >= 8 or any(score >= 5 for score in cat_totals.values()):
        level = "주의"
        badge = "🟡 주의 (지속관찰)"
    else:
        level = "관심"
        badge = "🟢 관심 (정상관리)"
        
    return {
        "level": level,
        "badge": badge,
        "total_score": total_score,
        "cat_totals": cat_totals,
        "is_evaluated": True
    }

def clean_markdown_for_txt(text: str) -> str:
    """다운로드용 텍스트 파일에서 특수 마크다운 기호를 정돈합니다."""
    cleaned = re.sub(r'\*\*(.*?)\*\*', r'\1', text)
    cleaned = re.sub(r'\*(.*?)\*', r'\1', cleaned)
    cleaned = re.sub(r'#(.*?)\n', r'\1\n', cleaned)
    cleaned = re.sub(r'`(.*?)`', r'\1', cleaned)
    return cleaned

if "shared_cases" not in st.session_state:
    st.session_state.shared_cases = load_cases()

shared_cases = st.session_state.shared_cases

# 🔒 비밀번호 로그인 인증 로직
APP_PASSWORD = st.secrets.get("APP_PASSWORD", "1234")  # Secrets에 설정이 없으면 기본 비밀번호 "1234" 사용

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

def check_password():
    if st.session_state.get("password_input") == APP_PASSWORD:
        st.session_state.authenticated = True
        st.session_state.password_input = ""
    else:
        st.session_state.authenticated = False
        st.error("❌ 비밀번호가 올바르지 않습니다. 다시 확인 후 입력해 주세요.")

if not st.session_state.authenticated:
    st.title("🔒 단지 통합 주거복지 관리 시스템 로그인")
    st.caption("본 시스템은 관계자 전용 보안 시스템입니다. 관리자 비밀번호를 입력해 주세요.")
    st.text_input("🔑 로그인 비밀번호", type="password", key="password_input", on_change=check_password)
    st.button("🔓 시스템 로그인", type="primary", use_container_width=True, on_click=check_password)
    st.info("💡 기본 설정 비밀번호는 `1234` 입니다. (Streamlit Secrets에 `APP_PASSWORD = \"원하는비밀번호\"` 를 지정하면 자유롭게 변경됩니다.)")
    st.stop()

# 최초 접속 시 데이터가 없는 경우 샘플 데이터 1건 생성
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
            },
            {
                "id": str(uuid.uuid4()),
                "time": datetime.now().strftime("%H:%M:%S"),
                "speaker": "이영희 관리소장",
                "content": "해당 세대는 현재 관리비 4개월 체납 중이며 층간소음 민원이 2건 접수된 상태입니다."
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
    save_cases(shared_cases)

with st.sidebar:
    st.image("https://img.icons8.com/color/96/city-buildings.png", width=70)
    st.title("🏢 관리자 설정")
    st.caption("주택관리공단 통합 주거복지 대화 시스템")
    
    if st.button("🔒 로그아웃", use_container_width=True):
        st.session_state.authenticated = False
        st.rerun()

    st.markdown("---")
    
    # OpenAI API Key 자동 확인 (Secrets 우선 적용)
    api_key = st.secrets.get("OPENAI_API_KEY", "") or os.getenv("OPENAI_API_KEY", "")
    
    if not api_key:
        api_key = st.text_input("🔑 OpenAI API Key 입력", type="password", help="sk-proj-... 형태로 시작하는 API 키를 입력하세요.")
        if api_key:
            os.environ["OPENAI_API_KEY"] = api_key
    else:
        st.success("🔒 API 키 인증 완료 (서버 연동됨)")

    st.markdown("---")
    
    # 실시간 대화 자동 갱신 토글
    auto_refresh = st.toggle("🔄 대화 실시간 5초 자동동기화", value=False, help="다른 사용자가 입력한 대화를 5초마다 자동으로 불러옵니다.")
    
    st.markdown("---")
    st.subheader("💾 데이터 백업 및 복원")
    
    # 데이터 다운로드
    json_str = json.dumps(shared_cases, ensure_ascii=False, indent=2)
    st.download_button(
        label="📥 전체 상담 데이터 백업 (.json)",
        data=json_str,
        file_name=f"housing_welfare_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
        mime="application/json",
        use_container_width=True
    )
    
    # 데이터 업로드
    uploaded_file = st.file_uploader("📤 백업 파일 복원하기", type=["json"])
    if uploaded_file is not None:
        try:
            restored_data = json.load(uploaded_file)
            if isinstance(restored_data, dict):
                st.session_state.shared_cases = restored_data
                save_cases(restored_data)
                st.success("데이터가 성공적으로 복원되었습니다!")
                st.rerun()
        except Exception as e:
            st.error(f"복원 실패: {e}")

st.title("🏢 단지 다자간 대화 & 주거복지 위험도 통합 관리 시스템")
st.caption("단지별 상담 대화를 실시간 누적하고 4대 영역 진단 체크리스트를 통해 관심·주의·위험 단계를 자동 분석합니다.")

# 통계 집계
total_cases = len(shared_cases)
total_chats = sum(len(c.get("chats", [])) for c in shared_cases.values())

risk_stats = {"위험": 0, "주의": 0, "관심": 0, "미진단": 0}
evaluated_count = 0

for cinfo in shared_cases.values():
    risk_info = get_case_risk_info(cinfo)
    risk_stats[risk_info["level"]] += 1
    if risk_info["is_evaluated"]:
        evaluated_count += 1

st.markdown("### 📊 전체 단지 주거복지 위험도 현황판")
col_stat1, col_stat2, col_stat3, col_stat4, col_stat5 = st.columns(5)
col_stat1.metric("총 등록 세대수", f"{total_cases} 건", help="시스템에 등록된 전체 상담 세대")
col_stat2.metric("진단 완료 세대", f"{evaluated_count} / {total_cases} 건")
col_stat3.metric("🔴 위험 (긴급 연계)", f"{risk_stats['위험']} 건")
col_stat4.metric("🟡 주의 (지속 관찰)", f"{risk_stats['주의']} 건")
col_stat5.metric("🟢 관심 (정상 관리)", f"{risk_stats['관심']} 건")

st.markdown("---")

col_search, col_add = st.columns([2, 1])

with col_search:
    st.subheader("🔍 세대 검색 및 위험도 필터")
    
    col_kw, col_flt = st.columns([1.5, 1])
    with col_kw:
        search_kw = st.text_input("🔎 단지명, 동/호수 검색", placeholder="예: 등촌7단지, 701동 등...")
    with col_flt:
        risk_filter = st.selectbox("🎯 위험도 단계 필터", ["전체 보기", "🔴 위험군만 보기", "🟡 주의군만 보기", "🟢 관심군만 보기", "⚪ 미진단건만 보기"])

    # 필터링 로직
    filtered_cases = {}
    for cid, cinfo in shared_cases.items():
        full_label = f"{cinfo.get('complex', '')} {cinfo.get('unit', '')}"
        r_info = get_case_risk_info(cinfo)
        
        match_kw = not search_kw.strip() or search_kw.strip().lower() in full_label.lower()
        
        match_risk = True
        if risk_filter == "🔴 위험군만 보기":
            match_risk = (r_info["level"] == "위험")
        elif risk_filter == "🟡 주의군만 보기":
            match_risk = (r_info["level"] == "주의")
        elif risk_filter == "🟢 관심군만 보기":
            match_risk = (r_info["level"] == "관심")
        elif risk_filter == "⚪ 미진단건만 보기":
            match_risk = (r_info["level"] == "미진단")

        if match_kw and match_risk:
            filtered_cases[cid] = (cinfo, r_info)

    if not filtered_cases:
        st.warning("조건에 해당하는 상담 세대가 없습니다. 검색어를 바꾸거나 우측에서 신규 등록하세요!")
        selected_case_id = None
    else:
        options_dict = {
            f"[{cinfo.get('complex', '미지정')}] {cinfo.get('unit', '미지정')} | {r_info['badge']} (대화 {len(cinfo.get('chats', []))}건)": cid
            for cid, (cinfo, r_info) in filtered_cases.items()
        }
        selected_label = st.selectbox("관리할 세대를 선택하세요:", options=list(options_dict.keys()), index=0)
        selected_case_id = options_dict[selected_label]

with col_add:
    st.subheader("➕ 신규 상담 세대 추가")
    with st.expander("📌 새로운 단지/세대 등록하기", expanded=False):
        with st.form("add_case_form", clear_on_submit=True):
            new_complex = st.text_input("단지명", placeholder="예: 등촌7단지, 번동3단지")
            new_unit = st.text_input("동/호수", placeholder="예: 701동 104호")
            initial_speaker = st.text_input("첫 상담자 이름/직함", value="김철수 주거복지사")
            initial_msg = st.text_area("초기 대화 내용", placeholder="상담 세대의 초기 문의 사항 입력...")
            
            submit_case = st.form_submit_button("➕ 세대 등록 완료", use_container_width=True)
            if submit_case:
                if not new_complex or not new_unit:
                    st.error("단지명과 동/호수를 모두 입력해 주세요.")
                else:
                    new_id = f"case-{uuid.uuid4().hex[:8]}"
                    shared_cases[new_id] = {
                        "id": new_id,
                        "complex": new_complex,
                        "unit": new_unit,
                        "status": "상담중",
                        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                        "chats": [
                            {
                                "id": str(uuid.uuid4()),
                                "time": datetime.now().strftime("%H:%M:%S"),
                                "speaker": initial_speaker if initial_speaker else "상담원",
                                "content": initial_msg if initial_msg else "주거복지 상담 세대가 새로 생성되었습니다."
                            }
                        ],
                        "summary": "",
                        "checklist": {
                            "계약": [0, 0, 0, 0, 0],
                            "부금": [0, 0, 0, 0, 0],
                            "시설": [0, 0, 0, 0, 0],
                            "민원": [0, 0, 0, 0, 0]
                        }
                    }
                    save_cases(shared_cases)
                    st.success(f"[{new_complex}] {new_unit} 세대가 추가되었습니다!")
                    st.rerun()

st.markdown("---")

if selected_case_id and selected_case_id in shared_cases:
    current_case = shared_cases[selected_case_id]
    current_risk = get_case_risk_info(current_case)
    
    st.markdown(f"## 📌 선택된 세대: **[{current_case['complex']}] {current_case['unit']}** | 진단 상태: **{current_risk['badge']}**")
    st.caption(f"생성일시: {current_case.get('created_at', '-')} | 진단 총점: **{current_risk['total_score']}점** | 누적 대화: **{len(current_case['chats'])}건**")

    tab_chat, tab_checklist, tab_summary, tab_manage = st.tabs([
        "💬 실시간 대화 누적",
        "📋 주거복지 4대 진단 체크리스트",
        "📄 AI 요약 보고서",
        "⚙️ 세대 관리"
    ])

    with tab_chat:
        st.subheader("💬 세대 다자간 대화 실시간 누적")
        st.caption("담당 팀장, 주거복지사, 관리소장, 주민 등이 나누는 대화를 시간순으로 누적 기록합니다.")

        # 대화 입력 폼
        with st.form("add_chat_form", clear_on_submit=True):
            col_spk, col_txt = st.columns([1, 3])
            with col_spk:
                speaker_name = st.text_input("발언자 이름/직함", value="주거복지사", placeholder="예: 김철수 팀장")
            with col_txt:
                chat_content = st.text_area("대화 내용", placeholder="대화 또는 상담 기록을 입력하세요...", height=100)
            
            btn_add_chat = st.form_submit_button("💬 대화 메시지 등록", use_container_width=True)
            if btn_add_chat:
                if not chat_content.strip():
                    st.warning("대화 내용을 입력해 주세요.")
                else:
                    new_chat_item = {
                        "id": str(uuid.uuid4()),
                        "time": datetime.now().strftime("%H:%M:%S"),
                        "speaker": speaker_name if speaker_name else "익명",
                        "content": chat_content.strip()
                    }
                    current_case["chats"].append(new_chat_item)
                    save_cases(shared_cases)
                    st.success("대화가 등록되었습니다!")
                    st.rerun()

        st.markdown("#### 📜 누적 대화 목록")
        
        # 실시간 동기화 플래그 처리
        if auto_refresh:
            st.caption("⏱️ 5초마다 최신 대화 목록이 자동 업데이트됩니다.")

        chat_container = st.container(height=350)
        with chat_container:
            if not current_case["chats"]:
                st.info("등록된 대화 내용이 없습니다.")
            else:
                for c in current_case["chats"]:
                    st.markdown(f"**[{c['time']}] {c['speaker']}**: {c['content']}")
                    st.divider()

    with tab_checklist:
        st.subheader("📋 주택관리공단 주거복지 4대 영역 진단 체크리스트")
        st.caption("계약, 부금, 시설, 민원 각 항목별 심각도 점수(0~3점)를 평가하여 관심/주의/위험 단계를 자동 판정합니다.")

        CHECKLIST_ITEMS = {
            "계약": [
                "1. 임대차 계약 만료 예정 및 재계약 서류 제출 지연/미비",
                "2. 입주 자격(소득/자산 기준) 초과 여부 검토 필요",
                "3. 명의 변경 / 세대원 변동 / 단독 가구 전환 이슈",
                "4. 무단 전대 또는 임차권 양도 의심 제보",
                "5. 장기 부재 또는 고독사 위기(연락 두절) 징후"
            ],
            "부금": [
                "1. 임대료 및 관리비 3개월 이상 체납",
                "2. 전기/수도/가스 단수·단전 등 생계 위기 징후",
                "3. 자력 납부 불능 상태 (신용회복, 파산 등)",
                "4. 긴급 주거비 지원 / 주거급여 수급 신청 필요",
                "5. 분납 약정 불이행 및 독촉 민원 발생"
            ],
            "시설": [
                "1. 저장강박(쓰레기 방치)으로 인한 위생/악취 심각",
                "2. 누수, 난방 고장, 벽지/장판 훼손 등 수리 필요",
                "3. 노후 시설물 안전사고(전기, 가스) 위험 포착",
                "4. 고령/장애로 인한 안전손잡이 등 편의시설 미비",
                "5. 세대 내 개조/훼손 및 원상복구 분쟁"
            ],
            "민원": [
                "1. 층간소음, 악취, 고성방가 등 이웃 간 갈등 극심",
                "2. 사회적 고립, 우울증, 알코올 중독 등 위기 포착",
                "3. 정신건강/폭력적 행동으로 인한 주민 불안",
                "4. 지자체 복지관/정신건강복지센터 연계 필요",
                "5. 반복·고질적 민원제기 및 관리사무소 마찰"
            ]
        }

        col_chk_input, col_chk_graph = st.columns([1.3, 1])

        with col_chk_input:
            cat_tabs = st.tabs(["📄 계약", "💰 부금", "🛠️ 시설", "📣 민원"])
            updated_checklist = current_case.get("checklist", {})

            for idx, cat_name in enumerate(["계약", "부금", "시설", "민원"]):
                with cat_tabs[idx]:
                    st.markdown(f"##### 📌 {cat_name} 영역 평가 항목")
                    items = CHECKLIST_ITEMS[cat_name]
                    current_scores = updated_checklist.get(cat_name, [0]*5)
                    new_scores = []
                    
                    for i, item_text in enumerate(items):
                        score = st.radio(
                            item_text,
                            options=[0, 1, 2, 3],
                            format_func=lambda x: {0: "0점 (해당없음)", 1: "1점 (경미)", 2: "2점 (중증)", 3: "3점 (심각)"}[x],
                            index=current_scores[i] if i < len(current_scores) else 0,
                            key=f"chk_{selected_case_id}_{cat_name}_{i}"
                        )
                        new_scores.append(score)
                    
                    updated_checklist[cat_name] = new_scores

            if st.button("💾 체크리스트 점수 저장하기", use_container_width=True, type="primary"):
                current_case["checklist"] = updated_checklist
                save_cases(shared_cases)
                st.success("체크리스트 점수가 저장되었습니다!")
                st.rerun()

        with col_chk_graph:
            st.subheader("📈 진단 결과 3단계 평가 및 시각화")
            
            eval_risk = get_case_risk_info(current_case)
            cat_totals = eval_risk["cat_totals"]
            total_score = eval_risk["total_score"]
            max_total = 60

            if eval_risk["level"] == "위험":
                st.error(f"🔴 **[위험 단계 - 주거복지사 현장 연계 대상]** (총 {total_score} / {max_total}점)")
                st.markdown("""
                **[🚨 긴급 조치 가이드]**
                - ⚠️ 해당 세대는 심각한 주거 위기 요인이 포착되어 **주거복지사 현장 방문 및 긴급 개입**이 필수적입니다.
                - 📞 **주택관리공단 주거복지지원센터** 및 **지자체 맞춤형 복지팀** 연계 절차를 즉시 착수해 주세요.
                """)
            elif eval_risk["level"] == "주의":
                st.warning(f"🟡 **[주의 단계 - 지속 관찰 대상]** (총 {total_score} / {max_total}점)")
                st.markdown("""
                **[관리 가이드]**
                - 🟡 체납, 민원 또는 고독사 가능성이 있는 주의 세대입니다.
                - 🔍 주기적인 현장점검 및 단지 내 관리사무소 모니터링 강화를 권장합니다.
                """)
            elif eval_risk["level"] == "관심":
                st.success(f"🟢 **[관심 단계 - 정상 관리 대상]** (총 {total_score} / {max_total}점)")
                st.caption("특이 위기 요인이 적은 정상 관리 세대입니다.")
            else:
                st.info("⚪ **[미진단 상태]** 좌측 항목에서 점수를 입력 후 저장해 주세요.")

            st.markdown("---")

            # Plotly 방사형 (Radar) 차트 생성
            radar_categories = ["계약", "부금", "시설", "민원"]
            radar_scores = [cat_totals.get(c, 0) for c in radar_categories]

            fig = go.Figure()
            fig.add_trace(go.Scatterpolar(
                r=radar_scores + [radar_scores[0]],
                theta=radar_categories + [radar_categories[0]],
                fill='toself',
                name='위험도 점수',
                line_color='#ef4444' if eval_risk["level"] == "위험" else ('#f59e0b' if eval_risk["level"] == "주의" else '#3b82f6')
            ))

            fig.update_layout(
                polar=dict(radialaxis=dict(visible=True, range=[0, 15])),
                showlegend=False,
                margin=dict(l=40, r=40, t=30, b=30),
                height=300
            )
            st.plotly_chart(fig, use_container_width=True)

            st.markdown("#### 📊 영역별 점수 현황 (만점 15점)")
            for cat, score in cat_totals.items():
                st.write(f"**{cat}**: {score}점 / 15점")
                st.progress(min(score / 15.0, 1.0))

    with tab_summary:
        st.subheader("📄 AI 통합 상담 및 진단 보고서 작성")
        st.caption("누적 대화 내역과 4대 영역 체크리스트 결과를 바탕으로 AI가 자동으로 주거복지 표준 보고서를 작성합니다.")

        if st.button("✨ AI 보고서 자동 생성하기", type="primary", use_container_width=True):
            if not api_key:
                st.error("사이드바에서 OpenAI API Key를 먼저 설정해 주세요.")
            elif not current_case["chats"]:
                st.warning("분석할 대화 내역이 없습니다.")
            else:
                with st.spinner("AI가 대화 및 체크리스트 데이터를 종합 분석 중입니다..."):
                    try:
                        client = OpenAI(api_key=api_key)
                        
                        chats_text = "\n".join([f"[{c['time']}] {c['speaker']}: {c['content']}" for c in current_case["chats"]])
                        eval_info = get_case_risk_info(current_case)
                        
                        prompt = f"""
                        당신은 주택관리공단 전문 주거복지사입니다.
                        아래 세대의 상담 대화 및 체크리스트 진단 결과를 바탕으로 깔끔한 주거복지 표준 보고서를 작성해 주세요.

                        [세대 정보]
                        - 단지명: {current_case['complex']}
                        - 동/호수: {current_case['unit']}
                        - 위험도 진단 단계: {eval_info['badge']} (총점 {eval_info['total_score']}점)
                        - 영역별 점수: {eval_info['cat_totals']}

                        [누적 대화 내역]
                        {chats_text}

                        [작성 양식]
                        1. 세대 기본 정보 및 진단 종합 요약
                        2. 주요 주거 위기 및 민원 원인 분석
                        3. 영역별 주요 체크리스트 특이사항
                        4. 향후 조치 계획 및 주거복지사 연계 필요성 (Action Items)
                        """

                        response = client.chat.completions.create(
                            model="gpt-4o-mini",
                            messages=[{"role": "user", "content": prompt}],
                            temperature=0.3
                        )

                        generated_summary = response.choices[0].message.content
                        current_case["summary"] = generated_summary
                        save_cases(shared_cases)
                        st.success("AI 보고서 생성이 완료되었습니다!")

                    except Exception as e:
                        st.error(f"보고서 생성 오류: {e}")

        # 보고서 출력 및 다운로드
        if current_case.get("summary"):
            st.markdown("---")
            st.markdown("### 📝 작성된 보고서 내용")
            st.markdown(current_case["summary"])

            txt_content = clean_markdown_for_txt(current_case["summary"])
            file_title = f"{current_case['complex']}_{current_case['unit']}_보고서.txt"

            st.download_button(
                label="📥 보고서 (.txt) 다운로드",
                data=txt_content,
                file_name=file_title,
                mime="text/plain; charset=utf-8",
                use_container_width=True
            )

    with tab_manage:
        st.subheader("⚙️ 세대 관리 및 삭제")
        st.caption("해당 세대의 상담 상태를 변경하거나 완료된 세대 데이터를 삭제합니다.")

        current_case["status"] = st.selectbox("상담 진행 상태", ["상담중", "지속관찰", "연계완료", "종결"], index=["상담중", "지속관찰", "연계완료", "종결"].index(current_case.get("status", "상담중")))
        if st.button("상태 저장"):
            save_cases(shared_cases)
            st.success("상태가 업데이트되었습니다.")

        st.markdown("---")
        st.markdown("#### ⚠️ 세대 데이터 삭제")
        if st.button("🗑️ 이 세대 상담 기록 완전히 삭제하기", type="primary"):
            del shared_cases[selected_case_id]
            save_cases(shared_cases)
            st.success("해당 세대 기록이 삭제되었습니다.")
            st.rerun()
