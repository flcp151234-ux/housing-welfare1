import streamlit as st
import json
import os
import datetime
import hashlib
import hmac
from datetime import timezone, timedelta
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
    page_title="통합 주거복지 관리 및 위험도 진단 시스템",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="expanded"
)

DATA_FILE = "cases_data.json"
COMPLEX_FILE = "complexes_data.json"

# 관리자 비밀번호: Streamlit Secrets에서 ADMIN_PASSWORD로 설정하세요.
ADMIN_PASSWORD = st.secrets.get("ADMIN_PASSWORD", "")
if not ADMIN_PASSWORD:
    st.error("Streamlit Secrets에 ADMIN_PASSWORD를 설정해야 합니다.")
    st.stop()

def hash_password(password):
    """PBKDF2-HMAC-SHA256 + 랜덤 salt로 단지 비밀번호를 안전하게 저장."""
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)
    return f"pbkdf2_sha256$200000${salt.hex()}${digest.hex()}"

def verify_password(password, stored_hash):
    """신규 PBKDF2 해시와 이전 버전 SHA-256 해시를 모두 검증하여 기존 설정도 호환."""
    try:
        if str(stored_hash).startswith("pbkdf2_sha256$"):
            _, iterations, salt_hex, digest_hex = str(stored_hash).split("$", 3)
            candidate = hashlib.pbkdf2_hmac(
                "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations)
            ).hex()
            return hmac.compare_digest(candidate, digest_hex)
        legacy = hashlib.sha256(password.encode("utf-8")).hexdigest()
        return hmac.compare_digest(legacy, str(stored_hash))
    except Exception:
        return False

@st.cache_resource(show_spinner=False)
def get_gspread_client():
    if not HAS_GSPREAD:
        return None
    if "gcp_service_account" not in st.secrets or "spreadsheet_url" not in st.secrets:
        return None
    try:
        scope = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        creds_dict = dict(st.secrets["gcp_service_account"])
        credentials = Credentials.from_service_account_info(creds_dict, scopes=scope)
        return gspread.authorize(credentials)
    except Exception as e:
        st.error(f"⚠️ 구글 시트 인증 중 오류 발생: {e}")
        return None

@st.cache_resource(show_spinner=False)
def get_spreadsheet():
    client = get_gspread_client()
    if client is None:
        return None
    try:
        return client.open_by_url(st.secrets["spreadsheet_url"])
    except Exception as e:
        st.error(f"⚠️ 구글 스프레드시트 연결 오류: {e}")
        return None

@st.cache_data(ttl=45, show_spinner=False)
def load_complexes():
    """단지 설정은 Google Sheets의 complexes 워크시트를 우선 사용하고 JSON은 비상 백업으로 사용."""
    spreadsheet = get_spreadsheet()
    if spreadsheet is not None:
        try:
            try:
                ws = spreadsheet.worksheet("complexes")
            except gspread.WorksheetNotFound:
                ws = spreadsheet.add_worksheet(title="complexes", rows=200, cols=5)
                ws.update(range_name="A1", values=[["complex_name", "password_hash", "created_at", "updated_at", "active"]])
            records = ws.get_all_records()
            data = {}
            for row in records:
                name = str(row.get("complex_name", "")).strip()
                pwd_hash = str(row.get("password_hash", "")).strip()
                if name and pwd_hash:
                    data[name] = {
                        "password_hash": pwd_hash,
                        "created_at": str(row.get("created_at", "")),
                        "updated_at": str(row.get("updated_at", "")),
                        "active": str(row.get("active", "TRUE")).upper() not in ("FALSE", "0", "NO")
                    }
            return data
        except Exception as e:
            st.warning(f"단지 설정 시트 읽기 지연: {e}")

    if os.path.exists(COMPLEX_FILE):
        try:
            with open(COMPLEX_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict) and data:
                    return data
        except Exception:
            pass

    initial_password = st.secrets.get("INITIAL_COMPLEX_PASSWORD", "1234")
    data = {
        "등촌7단지": {
            "password_hash": hash_password(initial_password),
            "created_at": get_kst_now().strftime("%Y-%m-%d %H:%M"),
            "updated_at": get_kst_now().strftime("%Y-%m-%d %H:%M"),
            "active": True
        }
    }
    save_complexes(data)
    return data

def save_complexes(data):
    """단지 설정을 로컬 백업 + Google Sheets complexes 워크시트에 저장."""
    load_complexes.clear()
    try:
        with open(COMPLEX_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        st.warning(f"단지 설정 로컬 백업 실패: {e}")

    spreadsheet = get_spreadsheet()
    if spreadsheet is not None:
        try:
            try:
                ws = spreadsheet.worksheet("complexes")
            except gspread.WorksheetNotFound:
                ws = spreadsheet.add_worksheet(title="complexes", rows=max(200, len(data)+20), cols=5)
            rows = [["complex_name", "password_hash", "created_at", "updated_at", "active"]]
            for name, info in sorted(data.items()):
                rows.append([name, info.get("password_hash", ""), info.get("created_at", ""), info.get("updated_at", ""), "TRUE" if info.get("active", True) else "FALSE"])
            ws.update(range_name="A1", values=rows)
            if ws.row_count > len(rows):
                ws.batch_clear([f"A{len(rows)+1}:E{ws.row_count}"])
        except Exception as e:
            st.error(f"단지 설정 Google Sheets 저장 실패: {e}")

def ensure_complexes_from_cases(complexes, cases):
    changed = False
    initial_password = st.secrets.get("INITIAL_COMPLEX_PASSWORD", "1234")
    now = get_kst_now().strftime("%Y-%m-%d %H:%M")
    for case in cases:
        name = str(case.get("complex", "")).strip()
        if name and name not in complexes:
            complexes[name] = {"password_hash": hash_password(initial_password), "created_at": now, "updated_at": now, "active": True}
            changed = True
    if changed:
        save_complexes(complexes)
    return complexes

# 한국 표준시(KST, UTC+9) 시간 반환 함수
def get_kst_now():
    return datetime.datetime.now(timezone(timedelta(hours=9)))

@st.cache_resource(show_spinner=False)
def get_gsheet_worksheet():
    spreadsheet = get_spreadsheet()
    return spreadsheet.sheet1 if spreadsheet is not None else None

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
        c["created_at"] = get_kst_now().strftime("%Y-%m-%d %H:%M")
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

@st.cache_data(ttl=30, show_spinner=False)
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
            return []
        except Exception as e:
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

CASE_HEADERS = ["id", "complex", "unit", "resident_name", "created_at", "risk_level", "scores", "dialogue_history", "ai_summary"]


def case_to_sheet_row(item):
    """Keep large media out of Sheets (same policy as the original app)."""
    clean_dialogue = []
    for msg in item.get("dialogue_history", []):
        msg_copy = dict(msg)
        media = msg_copy.get("media_data")
        if msg_copy.get("media_type") == "video" and media:
            msg_copy["media_data"] = "[🎥 동영상 첨부 완료]"
        elif msg_copy.get("media_type") == "image" and media and len(str(media)) > 30000:
            msg_copy["media_data"] = "[📷 이미지 첨부 완료]"
        clean_dialogue.append(msg_copy)
    return [str(item.get("id", "")), str(item.get("complex", "")),
            str(item.get("unit", "")), str(item.get("resident_name", "")),
            str(item.get("created_at", "")), str(item.get("risk_level", "")),
            json.dumps(item.get("scores", {}), ensure_ascii=False),
            json.dumps(clean_dialogue, ensure_ascii=False), str(item.get("ai_summary", ""))]


def save_data(data, changed_id=None):
    """Update a single case in place when possible; use full sync for deletion/restore.

    Existing Sheet rows are looked up by stable case ID, not by a cached row number.
    Full rewrites remain for destructive operations and need a single-writer migration
    before large-scale multi-office use.
    """
    sheet = get_gsheet_worksheet()
    if sheet is not None:
        try:
            if changed_id is not None:
                item = next((c for c in data if str(c.get("id")) == str(changed_id)), None)
                if item is None:
                    raise ValueError("수정 대상 세대를 찾을 수 없습니다.")
                # Only column A is fetched to locate a stable ID, avoiding a full-sheet read.
                ids = sheet.col_values(1)
                if ids and ids[0] != "id":
                    raise ValueError("시트의 첫 번째 열이 id가 아닙니다. 저장을 중단합니다.")
                matches = [i + 1 for i, value in enumerate(ids) if i > 0 and value == str(changed_id)]
                if len(matches) > 1:
                    raise ValueError("중복 세대 ID가 발견되어 저장을 중단합니다.")
                target_row = matches[0] if matches else max(2, len(ids) + 1)
                if not ids:
                    sheet.update(range_name="A1:I1", values=[CASE_HEADERS])
                sheet.update(range_name=f"A{target_row}:I{target_row}", values=[case_to_sheet_row(item)])
            else:
                rows = [CASE_HEADERS] + [case_to_sheet_row(item) for item in data]
                sheet.update(range_name=f"A1:I{len(rows)}", values=rows)
                if sheet.row_count > len(rows):
                    sheet.batch_clear([f"A{len(rows)+1}:I{sheet.row_count}"])
        except Exception as e:
            st.error(f"구글 시트 저장 실패: {e}")
            return False
    # Local JSON is a best-effort backup, not the authoritative shared database.
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        st.warning(f"로컬 백업 저장 실패: {e}")
    load_data.clear()
    return True

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
    
    for path in possible_font_paths:
        if os.path.exists(path):
            try:
                if 'NanumGothic' not in pdfmetrics.getRegisteredFontNames():
                    pdfmetrics.registerFont(TTFont('NanumGothic', path))
                font_name = 'NanumGothic'
                break
            except Exception:
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
    
    elements.append(Paragraph("<b>■ AI 자동 요약 및 맞춤 복지 연계 안</b>", sub_style))
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
    
# ─────────────────────────────────────────────────────────────
# 단지별 접근 인증
# ─────────────────────────────────────────────────────────────
if "complex_authenticated" not in st.session_state:
    st.session_state.complex_authenticated = {}
if "active_complex" not in st.session_state:
    st.session_state.active_complex = None

if "cases" not in st.session_state:
    loaded_cases = load_data()
    if not loaded_cases and get_gsheet_worksheet() is None and not os.path.exists(DATA_FILE):
        loaded_cases = [
            {
                "id": "CASE-2026-001",
                "complex": "등촌7단지",
                "unit": "701동 101호",
                "resident_name": "김OO 님",
                "created_at": get_kst_now().strftime("%Y-%m-%d %H:%M"),
                "dialogue_history": [
                    {"speaker": "주거복지사", "text": "안녕하세요, 701동 101호 김OO 어르신 되시나요? 최근 임대료 체납 및 난방 파손 문의 건으로 방문 상담 드립니다.", "time": "10:00"},
                    {"speaker": "입주민", "text": "네... 보일러가 고장났는데 수리비가 없어서 그냥 참고 지내고 있어요. 최근 병원비 때문에 관리비도 3달 정도 밀렸습니다.", "time": "10:02"}
                ],
                "ai_summary": "■ 개요: 등촌7단지 701동 101호 (김OO 님)\n■ 현황: 보일러 파손으로 한파 노출, 임대료/관리비 3개월 체납\n■ 조치 요청: 긴급 주거비 지원 신청 및 난방 시설 즉시 수리 연계 필요\n\n■ 💡 맞춤형 위기 지원 및 신청 안내\n• 임대료/관리비 체납 위기: 긴급복지 주거지원\n  - 연계/신청 기관: 관할 동 주민센터 복지팀\n  - 대표 전화번호: ☎ 129 (보건복지상담센터)\n  - 공식 신청 사이트: 복지로 (bokjiro.go.kr)\n  - 신청 가능한 주요 서비스: 체납 임대료 및 생계비 지원\n• 보일러 파손: 주택관리공단 긴급 수리 연계 및 에너지 바우처\n  - 연계/신청 기관: 관리사무소 및 동 주민센터\n  - 대표 전화번호: ☎ 1600-0777 (주택관리공단)\n  - 공식 신청 사이트: 에너지바우처 (energyv.or.kr)",
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

# 단지 목록 구성: 기존 데이터의 단지명도 자동 포함
complexes = load_complexes()
complexes = ensure_complexes_from_cases(complexes, st.session_state.cases)

st.title("🏠 통합 주거복지 관리 & 위험도 진단 시스템")
st.caption("단지를 선택한 뒤 해당 단지 비밀번호로 인증해야 상담 자료를 열람할 수 있습니다.")

# 단지 선택 / 신규 단지 생성
select_tab, create_tab, restore_tab = st.tabs(["🏢 단지 선택", "➕ 새 단지 추가", "♻️ 보관 단지 복구"])
with select_tab:
    complex_names = sorted([name for name, info in complexes.items() if info.get("active", True)])
    if complex_names:
        chosen_complex = st.selectbox("접속할 단지를 선택하세요", complex_names, key="complex_selector")
        already_auth = st.session_state.complex_authenticated.get(chosen_complex, False)
        if already_auth:
            st.success(f"🔓 {chosen_complex} 인증 완료")
            if st.button(f"{chosen_complex} 들어가기", type="primary", use_container_width=True):
                st.session_state.active_complex = chosen_complex
                st.rerun()
        else:
            with st.form("complex_login_form"):
                complex_pwd = st.text_input(f"🔑 {chosen_complex} 비밀번호", type="password")
                complex_login = st.form_submit_button("단지 로그인", type="primary", use_container_width=True)
                if complex_login:
                    if verify_password(complex_pwd, complexes[chosen_complex]["password_hash"]):
                        st.session_state.complex_authenticated[chosen_complex] = True
                        st.session_state.active_complex = chosen_complex
                        st.rerun()
                    else:
                        st.error("❌ 단지 비밀번호가 올바르지 않습니다.")
    else:
        st.info("등록된 단지가 없습니다. 새 단지를 추가해 주세요.")

with create_tab:
    st.info("새 단지는 원하는 단지명과 비밀번호를 직접 설정할 수 있습니다.")
    with st.form("create_complex_form", clear_on_submit=True):
        new_complex_name = st.text_input("새 단지명", placeholder="예: 등촌11단지")
        new_complex_pwd = st.text_input("단지 비밀번호", type="password")
        new_complex_pwd2 = st.text_input("단지 비밀번호 확인", type="password")
        create_admin_pwd = st.text_input("관리자 비밀번호 (단지 생성 승인)", type="password")
        create_complex = st.form_submit_button("새 단지 만들기", type="primary", use_container_width=True)
        if create_complex:
            name = new_complex_name.strip()
            if not name:
                st.error("단지명을 입력해 주세요.")
            elif name in complexes:
                st.error("이미 등록된 단지명입니다.")
            elif not hmac.compare_digest(str(create_admin_pwd), str(ADMIN_PASSWORD)):
                st.error("관리자 비밀번호가 올바르지 않아 단지를 생성할 수 없습니다.")
            elif len(new_complex_pwd) < 6:
                st.error("단지 비밀번호는 최소 6자 이상으로 설정해 주세요.")
            elif new_complex_pwd != new_complex_pwd2:
                st.error("비밀번호 확인이 일치하지 않습니다.")
            else:
                complexes[name] = {
                    "password_hash": hash_password(new_complex_pwd),
                    "created_at": get_kst_now().strftime("%Y-%m-%d %H:%M"),
                    "updated_at": get_kst_now().strftime("%Y-%m-%d %H:%M"),
                    "active": True
                }
                save_complexes(complexes)
                st.session_state.complex_authenticated[name] = True
                st.session_state.active_complex = name
                st.success(f"{name} 단지가 생성되었습니다.")
                st.rerun()

with restore_tab:
    archived_names = sorted([name for name, info in complexes.items() if not info.get("active", True)])
    if not archived_names:
        st.info("현재 보관(사용중지)된 단지가 없습니다.")
    else:
        with st.form("restore_complex_form"):
            restore_name = st.selectbox("복구할 단지", archived_names)
            restore_admin_pwd = st.text_input("🔐 관리자 비밀번호", type="password")
            restore_submit = st.form_submit_button("♻️ 단지 다시 사용", type="primary", use_container_width=True)
            if restore_submit:
                if not hmac.compare_digest(str(restore_admin_pwd), str(ADMIN_PASSWORD)):
                    st.error("❌ 관리자 비밀번호가 올바르지 않습니다.")
                else:
                    complexes[restore_name]["active"] = True
                    complexes[restore_name]["updated_at"] = get_kst_now().strftime("%Y-%m-%d %H:%M")
                    save_complexes(complexes)
                    st.success(f"{restore_name} 단지가 다시 활성화되었습니다.")
                    st.rerun()

active_complex = st.session_state.active_complex
if (not active_complex or not st.session_state.complex_authenticated.get(active_complex, False)
        or not complexes.get(active_complex, {}).get("active", False)):
    st.stop()

# 여기부터는 인증한 단지의 자료만 사용
complex_cases = [c for c in st.session_state.cases if c.get("complex") == active_complex]

# 관리자용 단지 삭제/보관 상태
if "complex_delete_requested" not in st.session_state:
    st.session_state.complex_delete_requested = False

if complex_cases:
    if "selected_case_id" not in st.session_state or not any(c.get("id") == st.session_state.selected_case_id for c in complex_cases):
        st.session_state.selected_case_id = complex_cases[0].get("id")

OPENAI_API_KEY = st.secrets.get("OPENAI_API_KEY", "")

with st.sidebar:
    st.header("⚙️ 시스템 설정 & 관리")
    st.write(f"🏢 접속 단지: **{active_complex}**")
    st.write("👤 접속 상태: **단지 인증 완료**")
    
    if get_gsheet_worksheet() is not None:
        st.success("🟢 구글 시트 영구 저장 연동 중")
    else:
        st.info("🟡 로컬 파일 저장 모드 (구글 시트 미연동)")

    if st.button("🚪 단지 로그아웃", use_container_width=True):
        st.session_state.complex_authenticated[active_complex] = False
        st.session_state.active_complex = None
        st.session_state.pop("selected_case_id", None)
        st.rerun()
    
    st.divider()
    
    if OPENAI_API_KEY:
        st.success("🔒 OpenAI API 키 연동 완료")
    else:
        st.warning("⚠️ OpenAI API 키 미설정")
        OPENAI_API_KEY = st.text_input("OpenAI API Key 수동 입력", type="password")

    st.divider()

    with st.expander("🗑️ 관리자용 단지 삭제 / 보관"):
        st.warning("단지 삭제는 관리자 전용 기능입니다. 실수 방지를 위해 관리자 비밀번호와 단지명을 다시 확인합니다.")
        delete_mode = st.radio(
            "처리 방법",
            ["단지만 사용중지 (세대자료 보존)", "단지 + 모든 세대자료 완전삭제"],
            key="complex_delete_mode"
        )
        if not st.session_state.complex_delete_requested:
            if st.button("⚠️ 단지 삭제 절차 시작", use_container_width=True):
                st.session_state.complex_delete_requested = True
                st.rerun()
        else:
            with st.form("complex_delete_admin_form"):
                st.error(f"현재 대상: {active_complex}")
                complex_admin_pwd = st.text_input("🔐 관리자 비밀번호", type="password")
                complex_name_confirm = st.text_input(f"확인을 위해 단지명 '{active_complex}'을 정확히 입력하세요")
                final_complex_delete = st.form_submit_button("🗑️ 최종 처리", type="primary", use_container_width=True)
                cancel_complex_delete = st.form_submit_button("취소", use_container_width=True)

                if cancel_complex_delete:
                    st.session_state.complex_delete_requested = False
                    st.rerun()

                if final_complex_delete:
                    if not hmac.compare_digest(str(complex_admin_pwd), str(ADMIN_PASSWORD)):
                        st.error("❌ 관리자 비밀번호가 올바르지 않습니다.")
                    elif complex_name_confirm.strip() != active_complex:
                        st.error("❌ 단지명이 일치하지 않습니다.")
                    elif delete_mode == "단지만 사용중지 (세대자료 보존)":
                        # 세대자료는 그대로 두고 단지만 비활성화하여 로그인 목록에서 제외
                        complexes[active_complex]["active"] = False
                        complexes[active_complex]["updated_at"] = get_kst_now().strftime("%Y-%m-%d %H:%M")
                        save_complexes(complexes)
                        st.session_state.complex_authenticated[active_complex] = False
                        st.session_state.active_complex = None
                        st.session_state.complex_delete_requested = False
                        st.success("단지를 사용중지 처리했습니다. 세대자료는 보존됩니다.")
                        st.rerun()
                    else:
                        # 단지 설정과 해당 단지의 모든 세대자료를 함께 영구 삭제
                        target = active_complex
                        st.session_state.cases = [c for c in st.session_state.cases if c.get("complex") != target]
                        save_data(st.session_state.cases)
                        complexes.pop(target, None)
                        save_complexes(complexes)
                        st.session_state.complex_authenticated.pop(target, None)
                        st.session_state.active_complex = None
                        st.session_state.complex_delete_requested = False
                        st.session_state.pop("selected_case_id", None)
                        st.success("단지 설정과 해당 단지의 모든 세대자료가 삭제되었습니다.")
                        st.rerun()

    with st.expander("🔐 현재 단지 비밀번호 변경"):
        with st.form("change_complex_password_form", clear_on_submit=True):
            old_pwd = st.text_input("현재 단지 비밀번호", type="password")
            new_pwd = st.text_input("새 비밀번호 (6자 이상)", type="password")
            new_pwd2 = st.text_input("새 비밀번호 확인", type="password")
            change_pwd_submit = st.form_submit_button("비밀번호 변경", use_container_width=True)
            if change_pwd_submit:
                if not verify_password(old_pwd, complexes[active_complex]["password_hash"]):
                    st.error("현재 단지 비밀번호가 올바르지 않습니다.")
                elif len(new_pwd) < 6:
                    st.error("새 비밀번호는 6자 이상으로 설정해 주세요.")
                elif new_pwd != new_pwd2:
                    st.error("새 비밀번호 확인이 일치하지 않습니다.")
                else:
                    complexes[active_complex]["password_hash"] = hash_password(new_pwd)
                    complexes[active_complex]["updated_at"] = get_kst_now().strftime("%Y-%m-%d %H:%M")
                    save_complexes(complexes)
                    st.session_state.complex_authenticated[active_complex] = False
                    st.session_state.active_complex = None
                    st.success("비밀번호가 변경되었습니다. 새 비밀번호로 다시 로그인해 주세요.")
                    st.rerun()

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
        st.text_input("단지명", value=active_complex, disabled=True)
        new_complex = active_complex
        new_unit = st.text_input("동/호수", placeholder="예: 701동 102호")
        new_name = st.text_input("입주민 성명", placeholder="예: 이OO 님")
        add_submit = st.form_submit_button("신규 등록", type="primary", use_container_width=True)
        
        if add_submit:
            if new_complex and new_unit and new_name:
                new_id = f"CASE-{get_kst_now().strftime('%Y%m%d%H%M%S')}"
                new_record = {
                    "id": new_id,
                    "complex": new_complex,
                    "unit": new_unit,
                    "resident_name": new_name,
                    "created_at": get_kst_now().strftime("%Y-%m-%d %H:%M"),
                    "dialogue_history": [],
                    "ai_summary": "아직 생성된 상담 요약이 없습니다.",
                    "scores": {"contract": 0, "dues": 0, "facility": 0, "grievance": 0},
                    "risk_level": "관심"
                }
                st.session_state.cases.insert(0, new_record)
                st.session_state.selected_case_id = new_id
                if not save_data(st.session_state.cases, changed_id=new_id):
                    st.session_state.cases = [c for c in st.session_state.cases if c.get("id") != new_id]
                    st.error("저장에 실패했습니다. 세대 등록을 취소했습니다.")
                    st.stop()
                st.success("신규 세대가 추가되었습니다!")
                st.rerun()
            else:
                st.error("단지명, 동/호수, 입주민 성명을 모두 입력해주세요.")

filtered_cases = [c for c in st.session_state.cases if c.get("complex") == active_complex]

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

st.title(f"🏠 {active_complex} 통합 주거복지 관리 & 위험도 진단 시스템")
st.caption("주택관리공단 현장 맞춤형: 계약, 부금, 시설, 민원 4대 영역 진단 및 구글 시트 실시간 자동 보존 체계")

col_m1, col_m2, col_m3, col_m4, col_m5 = st.columns(5)

active_cases = [c for c in st.session_state.cases if c.get("complex") == active_complex]
total_count = len(active_cases)
red_count = sum(1 for c in active_cases if c.get("risk_level") == "위험")
yellow_count = sum(1 for c in active_cases if c.get("risk_level") == "주의")
green_count = sum(1 for c in active_cases if c.get("risk_level") == "관심")

col_m1.metric("총 등록 세대", f"{total_count} 건")
col_m2.metric("🔴 위험 (긴급 연계)", f"{red_count} 세대", delta=f"{red_count}건 관리중", delta_color="inverse")
col_m3.metric("🟡 주의 (지속 관찰)", f"{yellow_count} 세대")
col_m4.metric("🟢 관심 (일반 관리)", f"{green_count} 세대")
col_m5.metric("📋 현재 단지", active_complex)

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

current_case = next((c for c in active_cases if c.get("id") == selected_id), active_cases[0])

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
        
        auto_sync = st.toggle("🔄 자동 갱신 (60초 주기)", value=False, help="자동 갱신 시 60초마다 Google Sheets에서 변경된 기록을 조회합니다.")
        
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
                    "time": get_kst_now().strftime("%H:%M"),
                    "media_type": media_type,
                    "media_data": media_data
                }
                current_case["dialogue_history"].append(new_msg)
                if not save_data(st.session_state.cases, changed_id=current_case["id"]):
                    current_case["dialogue_history"].pop()
                    st.error("저장에 실패했습니다. 다시 시도해 주세요.")
                    st.stop()
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
            @st.fragment(run_every=60)
            def live_chat_area():
                load_data.clear()
                fresh_cases = load_data()
                fresh_case = next((c for c in fresh_cases if c.get("id") == selected_id and c.get("complex") == active_complex), current_case)
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
                with st.spinner("AI가 대화 내용을 분석하여 위기 상황별 상세 기관, 전화번호, 신청 사이트를 추출 중입니다..."):
                    try:
                        import openai
                        client = openai.OpenAI(api_key=OPENAI_API_KEY)
                        
                        raw_dialogue = "\n".join([f"{m.get('speaker')}: {m.get('text')}" for m in history])
                        
                        # 범용 위기 상황 감지 및 기관/전화번호/사이트/서비스 자동 도출 프롬프트
                        prompt = f"""
                        당신은 대한민국 주택관리공단의 현장 맞춤형 주거복지 전문가입니다. 
                        아래 대화 내용을 바탕으로 표준 주거복지 상담보고서를 작성하세요.

                        [대상 세대 정보]
                        - 단지/동호수: {current_case.get('complex')} {current_case.get('unit')}
                        - 입주민 성명: {current_case.get('resident_name')}

                        [대화 내용]
                        {raw_dialogue}

                        [작성 지침 및 원칙]
                        1. "관련 기관과의 협력 체계 강화", "지자체 연계 추진" 등의 추상적이고 단순한 표현은 절대 사용하지 마세요.
                        2. 대화에 나타난 입주민의 모든 위기 요소(예: 치매/건강, 임대료/관리비 체납, 저장강박/쓰레기 방치, 정신건강/우울/알코올, 사회적 고립, 보일러/시설 파손 등)를 자동으로 추출하세요.
                        3. 추출된 위기 요소별로 실제 입주민 또는 주거복지사가 즉시 연계 신청할 수 있도록 **복지 제도명, 전문 연계 기관, 대표 전화번호, 공식 신청 사이트(URL), 구체적 지원 서비스 목록**을 상세하게 작성하세요.
                        4. **[중요 - 전화번호 작성 규칙]** 절대 '02-1234-5678'이나 '010-0000-0000' 같은 임의의 가짜 예시 번호를 작성하지 마세요. 해당 위기 영역의 실제 전국 공공 대표 콜센터 번호(예: 보건복지상담센터 ☎ 129, 지자체 통합콜센터 ☎ 120, 치매상담콜센터 ☎ 1899-9988, 정신건강상담전화 ☎ 1577-0199, 주택관리공단 ☎ 1600-0777 등)를 정확히 명시하세요.

                        [작성 양식]
                        ■ 개요 및 현황
                        ■ 주거 위기 주요 문제점

                        ■ 💡 위기 상황별 맞춤 지원 기관 및 복지 제도 안내 (필수 작성)
                        (대화에서 감지된 위기 유형별로 아래 포맷을 유지하며 구체적으로 작성하세요)

                        • [위기 유형 1] (예: 치매 및 인지기능 장애 / 임대료 체납 / 저장강박 등)
                          - 지원 복지 제도: (정확한 제도명)
                          - 연계/신청 기관: (담당 공공기관 또는 전문 센터명)
                          - 대표 전화번호: (실제 공공 대표 전화번호, 예: ☎ 129 보건복지상담센터 / ☎ 120 다산콜센터)
                          - 공식 신청 사이트: (신청 가능한 웹사이트 URL, 예: 복지로 bokjiro.go.kr)
                          - 신청 가능한 주요 서비스:
                            1) (구체적 지원 서비스 1)
                            2) (구체적 지원 서비스 2)
                            3) (구체적 지원 서비스 3)

                        • [위기 유형 2] (감지된 다른 위기 요소가 있을 경우 계속 작성)
                          - 지원 복지 제도: ...
                          - 연계/신청 기관: ...
                          - 대표 전화번호: ...
                          - 공식 신청 사이트: ...
                          - 신청 가능한 주요 서비스: ...
                        """
                        
                        response = client.chat.completions.create(
                            model="gpt-4o-mini",
                            messages=[{"role": "user", "content": prompt}],
                            temperature=0.2
                        )
                        
                        summary_result = response.choices[0].message.content
                        current_case["ai_summary"] = summary_result
                        save_data(st.session_state.cases, changed_id=current_case["id"])
                        st.success("AI 보고서 요약 및 위기별 상세 기관/연락처/사이트 연계 안 작성이 완료되었습니다!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"AI 생성 중 오류가 발생했습니다: {e}")

        with st.form(key=f"summary_edit_{current_case['id']}"):
            edited_summary = st.text_area("AI 생성 보고서 요약본", value=current_case.get("ai_summary", ""), height=320)
            save_summary = st.form_submit_button("💾 수정한 요약문 저장")
        if save_summary and edited_summary != current_case.get("ai_summary", ""):
            current_case["ai_summary"] = edited_summary
            if save_data(st.session_state.cases, changed_id=current_case["id"]):
                st.success("요약문이 저장되었습니다.")
                st.rerun()

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

[AI 자동 요약 및 맞춤 복지 연계 안]
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
            # PDF image decoding and ReportLab work are deferred until requested.
            pdf_fingerprint = hashlib.sha256(json.dumps(current_case, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]
            pdf_key = f"pdf_{current_case['id']}_{pdf_fingerprint}"
            if st.button("📕 PDF 보고서 생성", key=f"prepare_{current_case['id']}", use_container_width=True):
                try:
                    st.session_state[pdf_key] = create_pdf_report(current_case)
                except Exception as e:
                    st.error(f"PDF 생성 오류: {e}")
            if pdf_key in st.session_state:
                st.download_button(
                    label="📥 생성된 PDF 다운로드",
                    data=st.session_state[pdf_key],
                    file_name=f"상담보고서_{current_case.get('id')}.pdf",
                    mime="application/pdf",
                    use_container_width=True,
                    on_click="ignore"
                )

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
            save_data(st.session_state.cases, changed_id=current_case["id"])
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
        json_string = json.dumps(active_cases, ensure_ascii=False, indent=2)
        st.download_button(
            label="📥 전체 데이터 백업 다운로드 (.json)",
            data=json_string,
            file_name=f"housing_welfare_backup_{get_kst_now().strftime('%Y%m%d_%H%M%S')}.json",
            mime="application/json",
            use_container_width=True
        )
    
    with col_bak2:
        uploaded_file = st.file_uploader("📤 백업 파일(.json) 선택하여 복원", type=["json"])
        if uploaded_file is not None and st.button("선택한 백업 파일 복원 실행", type="primary"):
            try:
                uploaded_file.seek(0)
                restored_data = json.load(uploaded_file)
                if isinstance(restored_data, list):
                    restored = [sanitize_case(item, i) for i, item in enumerate(restored_data)]
                    for item in restored:
                        item["complex"] = active_complex
                    st.session_state.cases = [c for c in st.session_state.cases if c.get("complex") != active_complex] + restored
                    save_data(st.session_state.cases)
                    st.success("🎉 데이터 복원이 성공적으로 완료되었습니다!")
                    st.rerun()
            except Exception as e:
                st.error(f"❌ 복원 실패: {e}")

    st.divider()

    st.markdown("#### 🗑️ 선택 세대 삭제")
    st.write(f"현재 선택된 세대: **[{current_case.get('id')}] {current_case.get('complex')} {current_case.get('unit')} - {current_case.get('resident_name')}**")
    st.warning("삭제 버튼만 눌러서는 삭제되지 않습니다. 관리자 비밀번호 확인 후 최종 삭제됩니다.")

    if "delete_confirm_id" not in st.session_state:
        st.session_state.delete_confirm_id = None

    if st.session_state.delete_confirm_id != current_case.get("id"):
        if st.button("❌ 삭제 요청", type="secondary", use_container_width=True):
            st.session_state.delete_confirm_id = current_case.get("id")
            st.rerun()
    else:
        with st.form("admin_delete_form"):
            st.error("⚠️ 최종 삭제 확인 단계입니다. 삭제 후 복구하려면 백업본이 필요합니다.")
            delete_admin_pwd = st.text_input("🔐 관리자 비밀번호", type="password")
            confirm_text = st.text_input("확인을 위해 '삭제'라고 입력하세요")
            col_confirm, col_cancel = st.columns(2)
            with col_confirm:
                final_delete = st.form_submit_button("🗑️ 관리자 확인 후 최종 삭제", type="primary", use_container_width=True)
            with col_cancel:
                cancel_delete = st.form_submit_button("취소", use_container_width=True)

            if cancel_delete:
                st.session_state.delete_confirm_id = None
                st.rerun()

            if final_delete:
                if not hmac.compare_digest(str(delete_admin_pwd), str(ADMIN_PASSWORD)):
                    st.error("❌ 관리자 비밀번호가 올바르지 않습니다.")
                elif confirm_text.strip() != "삭제":
                    st.error("❌ 확인란에 '삭제'라고 정확히 입력해 주세요.")
                else:
                    delete_id = current_case.get("id")
                    st.session_state.cases = [c for c in st.session_state.cases if c.get("id") != delete_id]
                    save_data(st.session_state.cases)
                    st.session_state.delete_confirm_id = None
                    st.session_state.pop("selected_case_id", None)
                    st.success("해당 세대가 삭제되었습니다.")
                    st.rerun()

    st.divider()
    
    st.markdown("#### 📋 전체 세대 진단 요약 목록")
    
    summary_list = []
    for c in active_cases:
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
