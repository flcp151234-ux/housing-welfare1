import streamlit as st
import json
import os
import datetime
import base64
import io
from PIL import Image
import plotly.graph_objects as go
import pandas as pd

# PDF 생성을 위한 reportlab 모듈 import
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable, Image as RLImage
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

try:
    import gspread
    from google.oauth2.service_account import Credentials
    HAS_GSPREAD = True
except ImportError:
    HAS_GSPREAD = False

st.set_page_config(
    page_title="등촌7단지 통합 주거복지 관리 및 위험도 진단 시스템",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="expanded"
)

DATA_FILE = "cases_data.json"

def get_gsheet_worksheet():
    if not HAS_GSPREAD:
        return None
    if "gcp_service_account" in st.secrets and "spreadsheet_url" in st.secrets:
        try:
            scope = [
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive"
            ]
            creds_dict = dict(st.secrets["gcp_service_account"])
            credentials = Credentials.from_service_account_info(creds_dict, scopes=scope)
            client = gspread.authorize(credentials)
            sheet = client.open_by_url(st.secrets["spreadsheet_url"]).sheet1
            return sheet
        except Exception as e:
            st.error(f"⚠️ 구글 시트 연동 중 오류 발생: {e}")
            return None
    return None

def calculate_risk(scores):
    if not isinstance(scores, dict):
        return "관심"
    total = sum(scores.values())
    max_score = max(scores.values()) if scores else 0
    
    if total >= 15 or max_score >= 8:
        return "위험"
    elif total >= 8 or max_score >= 5:
        return "주의"
    else:
        return "관심"

def sanitize_case(c, index=0):
    if not isinstance(c, dict):
        c = {}
    if "id" not in c or not c["id"]:
        c["id"] = f"CASE-2026-{index+1:03d}"
    if "complex" not in c or not c["complex"]:
        c["complex"] = "등촌7단지"
    if "unit" not in c or not c["unit"]:
        c["unit"] = f"701동 {index+101}호"
    if "resident_name" not in c or not c["resident_name"]:
        c["resident_name"] = "입주민 님"
    if "created_at" not in c or not c["created_at"]:
        c["created_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    if "dialogue_history" not in c or not isinstance(c["dialogue_history"], list):
        c["dialogue_history"] = []
    if "ai_summary" not in c or not c["ai_summary"]:
        c["ai_summary"] = "아직 생성된 상담 요약이 없습니다."
    if "scores" not in c or not isinstance(c["scores"], dict):
        c["scores"] = {"contract": 0, "dues": 0, "facility": 0, "grievance": 0}
    if "risk_level" not in c or not c["risk_level"]:
        c["risk_level"] = calculate_risk(c["scores"])
    if "attachments" not in c or not isinstance(c["attachments"], list):
        c["attachments"] = []
    return c

def load_data():
    sheet = get_gsheet_worksheet()
    if sheet is not None:
        try:
            records = sheet.get_all_records()
            if records:
                cases = []
                for idx, row in enumerate(records):
                    # 점수 데이터 파싱
                    scores_raw = row.get("scores", "{}")
                    if isinstance(scores_raw, str):
                        try:
                            scores = json.loads(scores_raw) if scores_raw else {"contract":0,"dues":0,"facility":0,"grievance":0}
                        except json.JSONDecodeError:
                            scores = {"contract":0,"dues":0,"facility":0,"grievance":0}
                    else:
                        scores = scores_raw if isinstance(scores_raw, dict) else {"contract":0,"dues":0,"facility":0,"grievance":0}

                    # 대화 내역 파싱
                    dialogue_raw = row.get("dialogue_history", "[]")
                    if isinstance(dialogue_raw, str):
                        try:
                            dialogue = json.loads(dialogue_raw) if dialogue_raw else []
                        except json.JSONDecodeError:
                            dialogue = []
                    else:
                        dialogue = dialogue_raw if isinstance(dialogue_raw, list) else []

                    c = {
                        "id": str(row.get("id", "")),
                        "complex": str(row.get("complex", "")),
                        "unit": str(row.get("unit", "")),
                        "resident_name": str(row.get("resident_name", "")),
                        "created_at": str(row.get("created_at", "")),
                        "dialogue_history": dialogue,
                        "ai_summary": str(row.get("ai_summary", "")),
                        "scores": scores,
                        "risk_level": str(row.get("risk_level", ""))
                    }
                    cases.append(sanitize_case(c, idx))
                return cases
        except Exception as e:
            if "429" in str(e) or "Quota" in str(e):
                if "cases" in st.session_state and st.session_state.cases:
                    return st.session_state.cases
            st.warning(f"구글 시트 읽기 일시 지연 (기존 데이터 유지 중): {e}")

    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return [sanitize_case(item, i) for i, item in enumerate(data)]
        except Exception:
            return []
    return []

def save_data(data):
    # 1. 로컬 파일 저장
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        st.error(f"로컬 파일 저장 실패: {e}")

    # 2. 구글 시트 동기화 저장
    sheet = get_gsheet_worksheet()
    if sheet is not None:
        try:
            headers = ["id", "complex", "unit", "resident_name", "created_at", "risk_level", "scores", "dialogue_history", "ai_summary"]
            rows = [headers]
            
            for item in data:
                clean_dialogue = []
                for msg in item.get("dialogue_history", []):
                    msg_copy = dict(msg)
                    # 구글 시트 셀 용량 제한(50,000자) 대응: 대용량 이미지/동영상 base64 데이터 필터링
                    if msg_copy.get("media_type") == "video" and msg_copy.get("media_data"):
                        msg_copy["media_data"] = "[🎥 동영상 첨부 완료]"
                    elif msg_copy.get("media_type") == "image" and msg_copy.get("media_data") and len(str(msg_copy.get("media_data"))) > 30000:
                        msg_copy["media_data"] = "[📷 이미지 첨부 완료]"
                    clean_dialogue.append(msg_copy)

                rows.append([
                    str(item.get("id", "")),
                    str(item.get("complex", "")),
                    str(item.get("unit", "")),
                    str(item.get("resident_name", "")),
                    str(item.get("created_at", "")),
                    str(item.get("risk_level", "")),
                    json.dumps(item.get("scores", {}), ensure_ascii=False),
                    json.dumps(clean_dialogue, ensure_ascii=False),
                    str(item.get("ai_summary", ""))
                ])
            
            sheet.clear()
            sheet.update(range_name='A1', values=rows)
        except Exception as e:
            st.error(f"구글 시트 동기화 저장 실패: {e}")

def create_pdf_report(case_info):
    """나눔고딕 지원 한글 PDF 보고서(현장 이미지 포함)를 생성하는 함수"""
    buffer = io.BytesIO()
    
    current_dir = os.path.dirname(os.path.abspath(__file__))
    possible_font_paths = [
        os.path.join(current_dir, "NanumGothic.ttf"),
        "NanumGothic.ttf",
        "./NanumGothic.ttf",
        "/mount/src/housing-welfare1/NanumGothic.ttf",
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        "C:/Windows/Fonts/malgun.ttf"
    ]
    
    font_name = None
    font_error_msg = ""
    
    for path in possible_font_paths:
        if os.path.exists(path):
            try:
                if 'NanumGothic' not in pdfmetrics.getRegisteredFontNames():
                    pdfmetrics.registerFont(TTFont('NanumGothic', path))
                font_name = 'NanumGothic'
                break
            except Exception as e:
                font_error_msg = str(e)
                continue

    if not font_name:
        font_name = "Helvetica"

    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle('TitleStyle', parent=styles['Heading1'], fontName=font_name, fontSize=16, leading=20, alignment=1)
    meta_style = ParagraphStyle('MetaStyle', parent=styles['Normal'], fontName=font_name, fontSize=10, leading=14)
    body_style = ParagraphStyle('BodyStyle', parent=styles['Normal'], fontName=font_name, fontSize=10, leading=15)
    sub_style = ParagraphStyle('SubHeader', parent=meta_style, fontSize=12, leading=16)

    elements = []
    
    elements.append(Paragraph("<b>[주택관리공단] 주거복지 상담 및 현장 진단 보고서</b>", title_style))
    elements.append(Spacer(1, 15))
    elements.append(HRFlowable(width="100%", thickness=1, color="gray", spaceAfter=10))

    meta_text = f"""
    <b>관리 ID:</b> {case_info.get('id')} &nbsp;&nbsp;|&nbsp;&nbsp; <b>등록일시:</b> {case_info.get('created_at')}<br/>
    <b>대상 세대:</b> {case_info.get('complex')} {case_info.get('unit')} ({case_info.get('resident_name')})<br/>
    <b>위험도 단계:</b> {case_info.get('risk_level')}
    """
    elements.append(Paragraph(meta_text, meta_style))
    elements.append(Spacer(1, 10))
    elements.append(HRFlowable(width="100%", thickness=1, color="gray", spaceAfter=15))

    raw_summary = case_info.get('ai_summary', '내용 없음')
    summary_text = raw_summary.replace('\n', '<br/>')
    
    elements.append(Paragraph("<b>■ AI 자동 요약 및 종합 의견</b>", sub_style))
    elements.append(Spacer(1, 8))
    elements.append(Paragraph(summary_text, body_style))
    elements.append(Spacer(1, 15))

    image_attachments = [
        msg.get("media_data") for msg in case_info.get("dialogue_history", [])
        if msg.get("media_type") == "image" and msg.get("media_data") and msg.get("media_data").startswith("data:image")
    ]

    if image_attachments:
        elements.append(HRFlowable(width="100%", thickness=1, color="gray", spaceAfter=10))
        elements.append(Paragraph("<b>■ 현장 첨부 사진</b>", sub_style))
        elements.append(Spacer(1, 10))

        for idx, img_b64 in enumerate(image_attachments):
            try:
                if "," in img_b64:
                    img_data = base64.b64decode(img_b64.split(",")[1])
                else:
                    img_data = base64.b64decode(img_b64)
                
                img_stream = io.BytesIO(img_data)
                rl_img = RLImage(img_stream, width=400, height=250)
                elements.append(rl_img)
                elements.append(Spacer(1, 10))
            except Exception:
                continue

    doc.build(elements)
    buffer.seek(0)
    return buffer.getvalue()
    
APP_PASSWORD = st.secrets.get("APP_PASSWORD", "1234")

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.title("🔒 등촌7단지 통합 주거복지 관리 시스템 로그인")
    st.caption("본 시스템은 관계자 전용 보안 시스템입니다. 관리자 비밀번호를 입력해 주세요.")
    
    with st.form("login_form", clear_on_submit=False):
        pwd_input = st.text_input("🔑 로그인 비밀번호", type="password", help="기본 비밀번호는 1234 입니다.")
        submit_btn = st.form_submit_button("🔓 시스템 로그인", type="primary", use_container_width=True)
        
        if submit_btn:
            if pwd_input == APP_PASSWORD:
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("❌ 비밀번호가 올바르지 않습니다. 다시 확인 후 입력해 주세요.")
                
    st.info("💡 비밀번호 변경은 Streamlit Secrets에서 `APP_PASSWORD = \"원하는비밀번호\"` 로 설정 가능합니다.")
    st.stop()

if "cases" not in st.session_state:
    loaded_cases = load_data()
    if not loaded_cases:
        loaded_cases = [
            {
                "id": "CASE-2026-001",
                "complex": "등촌7단지",
                "unit": "701동 101호",
                "resident_name": "김OO 님",
                "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                "dialogue_history": [
                    {"speaker": "주거복지사", "text": "안녕하세요, 701동 101호 김OO 어르신 되시나요? 최근 임대료 체납 및 난방 파손 문의 건으로 방문 상담 드립니다.", "time": "10:00"},
                    {"speaker": "입주민", "text": "네... 보일러가 고장났는데 수리비가 없어서 그냥 참고 지내고 있어요. 최근 병원비 때문에 관리비도 3달 정도 밀렸습니다.", "time": "10:02"}
                ],
                "ai_summary": "■ 개요: 등촌7단지 701동 101호 (김OO 님)\n■ 현황: 보일러 파손으로 한파 노출, 임대료/관리비 3개월 체납\n■ 조치 요청: 긴급 주거비 지원 신청 및 난방 시설 즉시 수리 연계 필요",
                "scores": {
                    "contract": 2,
                    "dues": 8,
                    "facility": 9,
                    "grievance": 6
                },
                "risk_level": "위험"
            }
        ]
        save_data(loaded_cases)
    st.session_state.cases = loaded_cases

if st.session_state.cases:
    if "selected_case_id" not in st.session_state or not any(c.get("id") == st.session_state.selected_case_id for c in st.session_state.cases):
        st.session_state.selected_case_id = st.session_state.cases[0].get("id")

OPENAI_API_KEY = st.secrets.get("OPENAI_API_KEY", "")

with st.sidebar:
    st.header("⚙️ 시스템 설정 & 관리")
    st.write(f"👤 접속 상태: **인증 완료**")
    
    if get_gsheet_worksheet() is not None:
        st.success("🟢 구글 시트 영구 저장 연동 중")
    else:
        st.info("🟡 로컬 파일 저장 모드 (구글 시트 미연동)")

    if st.button("🚪 로그아웃", use_container_width=True):
        st.session_state.authenticated = False
        st.rerun()
    
    st.divider()
    
    if OPENAI_API_KEY:
        st.success("🔒 OpenAI API 키 연동 완료")
    else:
        st.warning("⚠️ OpenAI API 키 미설정")
        OPENAI_API_KEY = st.text_input("OpenAI API Key 수동 입력", type="password")

    st.divider()
    
    st.subheader("🔍 세대 및 위험도 필터")
    risk_filter = st.selectbox(
        "위험도 단계 필터",
        ["전체 보기", "🔴 위험군만 보기", "🟡 주의군만 보기", "🟢 관심군만 보기"]
    )
    search_query = st.text_input("단지/동호수/이름 검색", placeholder="예: 101동 또는 김OO")

    st.divider()
    
    st.subheader("➕ 신규 상담 세대 추가")
    with st.form("add_case_form", clear_on_submit=True):
        new_complex = st.text_input("단지명", placeholder="예: 등촌7단지")
        new_unit = st.text_input("동/호수", placeholder="예: 701동 102호")
        new_name = st.text_input("입주민 성명", placeholder="예: 이OO 님")
        add_submit = st.form_submit_button("신규 등록", type="primary", use_container_width=True)
        
        if add_submit:
            if new_complex and new_unit and new_name:
                new_id = f"CASE-{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"
                new_record = {
                    "id": new_id,
                    "complex": new_complex,
                    "unit": new_unit,
                    "resident_name": new_name,
                    "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "dialogue_history": [],
                    "ai_summary": "아직 생성된 상담 요약이 없습니다.",
                    "scores": {"contract": 0, "dues": 0, "facility": 0, "grievance": 0},
                    "risk_level": "관심"
                }
                st.session_state.cases.insert(0, new_record)
                st.session_state.selected_case_id = new_id
                save_data(st.session_state.cases)
                st.success("신규 세대가 추가되었습니다!")
                st.rerun()
            else:
                st.error("단지명, 동/호수, 입주민 성명을 모두 입력해주세요.")

filtered_cases = st.session_state.cases

if risk_filter == "🔴 위험군만 보기":
    filtered_cases = [c for c in filtered_cases if c.get("risk_level") == "위험"]
elif risk_filter == "🟡 주의군만 보기":
    filtered_cases = [c for c in filtered_cases if c.get("risk_level") == "주의"]
elif risk_filter == "🟢 관심군만 보기":
    filtered_cases = [c for c in filtered_cases if c.get("risk_level") == "관심"]

if search_query:
    filtered_cases = [
        c for c in filtered_cases 
        if search_query.lower() in c.get("complex", "").lower() 
        or search_query.lower() in c.get("unit", "").lower()
        or search_query.lower() in c.get("resident_name", "").lower()
    ]

st.title("🏠 등촌7단지 통합 주거복지 관리 & 위험도 진단 시스템")
st.caption("주택관리공단 현장 맞춤형: 계약, 부금, 시설, 민원 4대 영역 진단 및 구글 시트 실시간 자동 보존 체계")

col_m1, col_m2, col_m3, col_m4, col_m5 = st.columns(5)

total_count = len(st.session_state.cases)
red_count = sum(1 for c in st.session_state.cases if c.get("risk_level") == "위험")
yellow_count = sum(1 for c in st.session_state.cases if c.get("risk_level") == "주의")
green_count = sum(1 for c in st.session_state.cases if c.get("risk_level") == "관심")

col_m1.metric("총 등록 세대", f"{total_count} 건")
col_m2.metric("🔴 위험 (긴급 연계)", f"{red_count} 세대", delta=f"{red_count}건 관리중", delta_color="inverse")
col_m3.metric("🟡 주의 (지속 관찰)", f"{yellow_count} 세대")
col_m4.metric("🟢 관심 (일반 관리)", f"{green_count} 세대")
col_m5.metric("📋 관리 대상 단지", "500+ 단지")

st.divider()

if not filtered_cases:
    st.warning("조건에 해당하는 검색 세대가 없습니다. 사이드바에서 필터를 변경하거나 세대를 등록해주세요.")
    st.stop()

case_options = {c.get("id"): f"[{c.get('risk_level','관심')}] {c.get('complex','')} {c.get('unit','')} - {c.get('resident_name','')}" for c in filtered_cases}

selected_id = st.selectbox(
    "📌 대상 세대 선택", 
    options=list(case_options.keys()), 
    format_func=lambda x: case_options.get(x, x),
    index=0
)

current_case = next((c for c in st.session_state.cases if c.get("id") == selected_id), st.session_state.cases[0])

tab1, tab2, tab3 = st.tabs([
    "📋 주거복지 대화 및 AI 요약", 
    "📊 4대 영역 체크리스트 & 위험도 진단", 
    "📁 세대 관리 및 구글 시트 데이터"
])

with tab1:
    st.subheader(f"🗣️ {current_case.get('complex')} {current_case.get('unit')} ({current_case.get('resident_name')}) 대화 및 현장 기록")
    
    col_chat, col_summary = st.columns([1.2, 1])
    
    with col_chat:
        st.write("##### 💬 현장 대화 및 사진/동영상 기록")
        
        auto_sync = st.toggle("🔴 실시간 자동 갱신 (15초 주기)", value=False, help="다자간 동시 접속 시 다른 사용자의 입력값을 15초마다 자동 불러옵니다.")
        
        with st.form("chat_input_form", clear_on_submit=True):
            speaker = st.text_input("발화자 (직접 입력)", placeholder="예: 주거복지사, 관리소장, 입주민, 지자체 담당자 등")
            message_text = st.text_area("대화 및 현장 메모를 입력하세요", height=80, placeholder="예: 보일러 누수 현장 확인 사진 첨부합니다.")
            
            uploaded_file = st.file_uploader(
                "📷 현장 사진 또는 🎥 동영상 첨부 (선택)", 
                type=["png", "jpg", "jpeg", "webp", "mp4", "mov", "avi"],
                help="현장 파손 사진, 증빙 서류, 현장 녹화 동영상 등을 첨부할 수 있습니다."
            )
            
            submitted = st.form_submit_button("기록 및 첨부파일 저장", type="primary", use_container_width=True)
            
            if submitted and (message_text.strip() or uploaded_file is not None):
                media_type = None
                media_data = None
                
                if uploaded_file is not None:
                    file_type = uploaded_file.type
                    
                    if "image" in file_type:
                        media_type = "image"
                        try:
                            img = Image.open(uploaded_file)
                            if img.mode in ("RGBA", "P"):
                                img = img.convert("RGB")
                            img.thumbnail((600, 600))
                            buffer = io.BytesIO()
                            img.save(buffer, format="JPEG", quality=65)
                            b64_str = base64.b64encode(buffer.getvalue()).decode("utf-8")
                            media_data = f"data:image/jpeg;base64,{b64_str}"
                        except Exception:
                            file_bytes = uploaded_file.read()
                            b64_str = base64.b64encode(file_bytes).decode("utf-8")
                            media_data = f"data:{file_type};base64,{b64_str}"
                    elif "video" in file_type:
                        media_type = "video"
                        file_bytes = uploaded_file.read()
                        b64_str = base64.b64encode(file_bytes).decode("utf-8")
                        media_data = f"data:{file_type};base64,{b64_str}"
                
                new_msg = {
                    "speaker": speaker.strip() if speaker.strip() else "기타",
                    "text": message_text.strip(),
                    "time": datetime.datetime.now().strftime("%H:%M"),
                    "media_type": media_type,
                    "media_data": media_data
                }
                current_case["dialogue_history"].append(new_msg)
                save_data(st.session_state.cases)
                st.success("대화 기록 및 미디어 첨부가 성공적으로 추가 및 구글 시트에 저장되었습니다.")
                st.rerun()

        st.divider()
        
        def display_messages(case_obj=None):
            if case_obj is None:
                case_obj = current_case
            st.write("**[누적 대화 및 미디어 기록 목록]**")
            history = case_obj.get("dialogue_history", [])
            if not history:
                st.info("등록된 대화 내용이 없습니다.")
            else:
                for idx, msg in enumerate(history):
                    badge = "🔵" if msg.get("speaker") == "주거복지사" else ("🟢" if msg.get("speaker") == "입주민" else "🟡")
                    st.markdown(f"{badge} **[{msg.get('speaker','기타')}]** `[{msg.get('time','')}]`\n{msg.get('text','')}")
                    
                    m_data = msg.get("media_data")
                    m_type = msg.get("media_type")
                    
                    if m_type == "image" and m_data:
                        if isinstance(m_data, str) and (m_data.startswith("data:image") or m_data.startswith("http://") or m_data.startswith("https://")):
                            try:
                                st.image(m_data, caption="📷 현장 첨부 사진", use_container_width=True)
                            except Exception:
                                st.caption(f"📷 현장 사진: {m_data}")
                        else:
                            st.caption(f"📷 현장 사진 상태: {m_data}")
                    elif m_type == "video" and m_data:
                        if isinstance(m_data, str) and (m_data.startswith("data:video") or m_data.startswith("http://") or m_data.startswith("https://")):
                            try:
                                st.video(m_data)
                                st.caption("🎥 현장 첨부 동영상")
                            except Exception:
                                st.caption(f"🎥 현장 동영상: {m_data}")
                        else:
                            st.caption(f"🎥 현장 동영상 상태: {m_data}")
                        
                    st.divider()

        if auto_sync:
            @st.fragment(run_every=15)
            def live_chat_area():
                st.session_state.cases = load_data()
                fresh_case = next((c for c in st.session_state.cases if c.get("id") == selected_id), current_case)
                display_messages(fresh_case)
            live_chat_area()
        else:
            display_messages(current_case)

    with col_summary:
        st.write("##### 🤖 AI 자동 문서화 및 보고서 요약")
        
        if st.button("✨ 전체 대화 내용 AI 자동 요약 생성", type="primary", use_container_width=True):
            history = current_case.get("dialogue_history", [])
            if not history:
                st.warning("요약할 대화 내용이 없습니다.")
            elif not OPENAI_API_KEY:
                st.error("OpenAI API 키가 필요합니다. 사이드바에서 키를 입력해주세요.")
            else:
                with st.spinner("AI가 대화 내용을 분석하여 표준 문서를 작성 중입니다..."):
                    try:
                        import openai
                        client = openai.OpenAI(api_key=OPENAI_API_KEY)
                        
                        raw_dialogue = "\n".join([f"{m.get('speaker')}: {m.get('text')}" for m in history])
                        prompt = f"""
                        당신은 주택관리공단의 주거복지 전문가입니다. 아래 대화 내용을 바탕으로 표준 주거복지 상담보고서를 작성하세요.
                        
                        [대화 내용]
                        {raw_dialogue}
                        
                        [작성 양식]
                        ■ 개요 및 현황
                        ■ 주거 위기 주요 문제점 (계약/부금/시설/민원 관점)
                        ■ 향후 조치 및 주거복지사 지원 계획
                        """
                        
                        response = client.chat.completions.create(
                            model="gpt-4o-mini",
                            messages=[{"role": "user", "content": prompt}],
                            temperature=0.3
                        )
                        
                        summary_result = response.choices[0].message.content
                        current_case["ai_summary"] = summary_result
                        save_data(st.session_state.cases)
                        st.success("AI 보고서 요약 작성이 완료되었으며 구글 시트에 저장되었습니다!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"AI 생성 중 오류가 발생했습니다: {e}")

        edited_summary = st.text_area("AI 생성 보고서 요약본", value=current_case.get("ai_summary", ""), height=300)
        if edited_summary != current_case.get("ai_summary", ""):
            current_case["ai_summary"] = edited_summary
            save_data(st.session_state.cases)

        image_attachments = [
            msg.get("media_data") for msg in current_case.get("dialogue_history", [])
            if msg.get("media_type") == "image" and msg.get("media_data") and str(msg.get("media_data")).startswith("data:image")
        ]
        
        if image_attachments:
            st.markdown("##### 📷 보고서 포함 현장 이미지")
            img_cols = st.columns(min(len(image_attachments), 3))
            for idx, img_data in enumerate(image_attachments):
                with img_cols[idx % 3]:
                    try:
                        st.image(img_data, caption=f"현장 사진 #{idx+1}", use_container_width=True)
                    except Exception:
                        pass

        st.markdown("##### 📥 보고서 파일 내보내기")
        col_exp1, col_exp2 = st.columns(2)
        
        with col_exp1:
            report_txt_content = f"""[주택관리공단 주거복지 상담 보고서]
--------------------------------------------------
관리 ID: {current_case.get('id')}
등록일시: {current_case.get('created_at')}
단지명: {current_case.get('complex')} {current_case.get('unit')}
입주민: {current_case.get('resident_name')}
위험도: {current_case.get('risk_level')}
--------------------------------------------------

[AI 자동 요약 및 종합 의견]
{current_case.get('ai_summary', '')}
"""
            st.download_button(
                label="📄 TXT 파일 저장",
                data=report_txt_content,
                file_name=f"상담보고서_{current_case.get('id')}.txt",
                mime="text/plain",
                use_container_width=True
            )

        with col_exp2:
            try:
                pdf_bytes = create_pdf_report(current_case)
                st.download_button(
                    label="📕 PDF 보고서 저장",
                    data=pdf_bytes,
                    file_name=f"상담보고서_{current_case.get('id')}.pdf",
                    mime="application/pdf",
                    use_container_width=True
                )
            except Exception as e:
                st.error(f"PDF 생성 오류: {e}")

with tab2:
    st.subheader("📊 주택관리공단 맞춤 4대 영역 체크리스트 & 진단")
    st.caption("각 영역별 항목을 체크하여 위험도 점수를 산정합니다.")
    
    col_chk, col_chart = st.columns([1.2, 1])
    
    with col_chk:
        scores = current_case.get("scores", {"contract": 0, "dues": 0, "facility": 0, "grievance": 0})
        
        st.markdown("#### 1️⃣ 임대차 계약 (Contract)")
        chk_c1 = st.checkbox("임대차 계약 만료 예정 및 미갱신 상태", value=(scores.get("contract", 0) >= 3))
        chk_c2 = st.checkbox("소득/자격 초과로 인한 퇴거 위기 세대", value=(scores.get("contract", 0) >= 6))
        chk_c3 = st.checkbox("불법 전대 또는 명의 도용/고독사 의심 세대", value=(scores.get("contract", 0) >= 9))
        
        c_score = (3 if chk_c1 else 0) + (3 if chk_c2 else 0) + (3 if chk_c3 else 0)
        
        st.markdown("#### 2️⃣ 부금 및 체납 (Dues)")
        chk_d1 = st.checkbox("임대료 또는 관리비 3개월 이상 체납", value=(scores.get("dues", 0) >= 3))
        chk_d2 = st.checkbox("단수/단전 또는 생계 위기 가구", value=(scores.get("dues", 0) >= 6))
        chk_d3 = st.checkbox("자력 납부 불능 상태 (긴급 주거비 지원 필요)", value=(scores.get("dues", 0) >= 9))
        
        d_score = (3 if chk_d1 else 0) + (3 if chk_d2 else 0) + (3 if chk_d3 else 0)

        st.markdown("#### 3️⃣ 주거 시설 및 환경 (Facility)")
        chk_f1 = st.checkbox("보일러/누수/난방 파손 등 긴급 수리 필요", value=(scores.get("facility", 0) >= 3))
        chk_f2 = st.checkbox("저장강박증(쓰레기 방치) 및 위생 극심 악화", value=(scores.get("facility", 0) >= 6))
        chk_f3 = st.checkbox("주거약자 편의시설(안전손잡이 등) 미비 및 안전사고 위험", value=(scores.get("facility", 0) >= 9))
        
        f_score = (3 if chk_f1 else 0) + (3 if chk_f2 else 0) + (3 if chk_f3 else 0)

        st.markdown("#### 4️⃣ 민원 및 사회적 고립 (Grievance)")
        chk_g1 = st.checkbox("이웃 간 층간소음 또는 분쟁 빈발 세대", value=(scores.get("grievance", 0) >= 3))
        chk_g2 = st.checkbox("사회적 고립/알코올/정신건강 고위험군", value=(scores.get("grievance", 0) >= 6))
        chk_g3 = st.checkbox("외부 복지 서비스 강력 거부 또는 심각한 민원", value=(scores.get("grievance", 0) >= 9))
        
        g_score = (3 if chk_g1 else 0) + (3 if chk_g2 else 0) + (3 if chk_g3 else 0)

        updated_scores = {
            "contract": c_score,
            "dues": d_score,
            "facility": f_score,
            "grievance": g_score
        }
        
        if st.button("💾 체크리스트 점수 및 위험도 진단 저장", type="primary", use_container_width=True):
            current_case["scores"] = updated_scores
            current_case["risk_level"] = calculate_risk(updated_scores)
            save_data(st.session_state.cases)
            st.success(f"진단 결과 저장 완료! 위험도: [{current_case['risk_level']}]")
            st.rerun()

    with col_chart:
        st.markdown("#### 📈 영역별 취약도 레이더 차트")
        
        categories = ['계약 (Contract)', '부금 (Dues)', '시설 (Facility)', '민원 (Grievance)']
        values = [
            updated_scores["contract"],
            updated_scores["dues"],
            updated_scores["facility"],
            updated_scores["grievance"]
        ]
        
        fig = go.Figure(data=go.Scatterpolar(
            r=values + [values[0]],
            theta=categories + [categories[0]],
            fill='toself',
            fillcolor='rgba(239, 68, 68, 0.3)' if current_case.get("risk_level") == "위험" else 'rgba(59, 130, 246, 0.3)',
            line=dict(color='red' if current_case.get("risk_level") == "위험" else 'blue')
        ))

        fig.update_layout(
            polar=dict(radialaxis=dict(visible=True, range=[0, 10])),
            showlegend=False,
            margin=dict(l=40, r=40, t=30, b=30)
        )
        
        st.plotly_chart(fig, use_container_width=True)
        
        risk = current_case.get("risk_level", "관심")
        total_score = sum(updated_scores.values())
        
        st.divider()
        
        if risk == "위험":
            st.error(f"🚨 **위험 세대 (총점: {total_score}점)**")
            st.markdown("""
            **[주거복지사 현장 개입 수칙]**
            1. **지자체 긴급 복지 지원팀**과 즉시 연계하여 임대료 지원 신청
            2. 시설 파손 시 주택관리공단 긴급 수리비 예비비 즉시 집행
            3. 2인 1조 현장 방문을 통한 고독사 및 인명 사고 예방
            """)
        elif risk == "주의":
            st.warning(f"🟡 **주의 세대 (총점: {total_score}점)**")
            st.markdown("""
            **[지속 관찰 수칙]**
            1. 월 1회 주기적 상담 및 모니터링 실시
            2. 체납금 분납 유도 및 복지 바우처 안내
            """)
        else:
            st.success(f"🟢 **관심 세대 (총점: {total_score}점)**")
            st.info("정상 관리 세대입니다. 정기점검 시 상태를 확인하세요.")

with tab3:
    st.subheader("📁 세대 전체 관리 및 데이터 영구 보존 현황")
    
    if get_gsheet_worksheet() is not None:
        st.success("🎉 **구글 시트(Google Sheets)와 연동되어 데이터가 실시간 영구 보존되고 있습니다.**")
    else:
        st.warning("⚠️ 현재 구글 시트 미연동 상태로, 로컬 파일에만 저장됩니다.")

    st.divider()

    st.markdown("#### 💾 수동 백업 및 1초 복원 (비상용)")
    
    col_bak1, col_bak2 = st.columns(2)
    with col_bak1:
        json_string = json.dumps(st.session_state.cases, ensure_ascii=False, indent=2)
        st.download_button(
            label="📥 전체 데이터 백업 다운로드 (.json)",
            data=json_string,
            file_name=f"housing_welfare_backup_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
            mime="application/json",
            use_container_width=True
        )
    
    with col_bak2:
        uploaded_file = st.file_uploader("📤 백업 파일(.json) 선택하여 복원", type=["json"])
        if uploaded_file is not None:
            try:
                restored_data = json.load(uploaded_file)
                if isinstance(restored_data, list):
                    st.session_state.cases = [sanitize_case(item, i) for i, item in enumerate(restored_data)]
                    save_data(st.session_state.cases)
                    st.success("🎉 데이터 복원이 성공적으로 완료되었습니다!")
                    st.rerun()
            except Exception as e:
                st.error(f"❌ 복원 실패: {e}")

    st.divider()

    st.markdown("#### 🗑️ 선택 세대 삭제")
    col_del1, col_del2 = st.columns([3, 1])
    with col_del1:
        st.write(f"현재 선택된 세대: **[{current_case.get('id')}] {current_case.get('complex')} {current_case.get('unit')} - {current_case.get('resident_name')}**")
    with col_del2:
        if st.button("❌ 선택 세대 삭제", type="secondary", use_container_width=True):
            st.session_state.cases = [c for c in st.session_state.cases if c.get("id") != current_case.get("id")]
            save_data(st.session_state.cases)
            st.success("해당 세대가 삭제되었습니다.")
            st.rerun()

    st.divider()
    
    st.markdown("#### 📋 전체 세대 진단 요약 목록")
    
    summary_list = []
    for c in st.session_state.cases:
        sc = c.get("scores", {"contract": 0, "dues": 0, "facility": 0, "grievance": 0})
        summary_list.append({
            "ID": c.get("id", ""),
            "단지명": c.get("complex", ""),
            "동호수": c.get("unit", ""),
            "성명": c.get("resident_name", ""),
            "위험도": c.get("risk_level", "관심"),
            "계약점수": sc.get("contract", 0),
            "부금점수": sc.get("dues", 0),
            "시설점수": sc.get("facility", 0),
            "민원점수": sc.get("grievance", 0),
            "총점": sum(sc.values())
        })
    
    if summary_list:
        df_summary = pd.DataFrame(summary_list)
        st.dataframe(df_summary, use_container_width=True, hide_index=True)
    else:
        st.info("등록된 세대가 없습니다.")
