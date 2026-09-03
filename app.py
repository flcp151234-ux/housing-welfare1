import streamlit as st
import pandas as pd
import json
import gspread
from google.oauth2.service_account import Credentials
import openai
import base64
from io import BytesIO
from PIL import Image
import os
import datetime

# WeasyPrint 예외 처리 (PDF 생성용)
try:
    from weasyprint import HTML
    WEASYPRINT_AVAILABLE = True
except Exception:
    WEASYPRINT_AVAILABLE = False

# --- 페이지 기본 설정 ---
st.set_page_config(
    page_title="등촌7단지 현장 상담 & 주거복지 관리 시스템",
    page_icon="🏢",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- 구글 시트 API 연동 설정 ---
SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]

SPREADSHEET_URL = st.secrets.get("spreadsheet_url", "https://docs.google.com/spreadsheets/d/1flgKlCCXqybljCFYO17RyTWOUWR-vUh6-56x9wmTutM")

@st.cache_resource(ttl=300)
def get_gspread_client():
    try:
        if "gcp_service_account" in st.secrets:
            creds_info = dict(st.secrets["gcp_service_account"])
            credentials = Credentials.from_service_account_info(creds_info, scopes=SCOPES)
            client = gspread.authorize(credentials)
            return client
    except Exception as e:
        st.error(f"구글 시트 인증 오류: {e}")
    return None

@st.cache_data(ttl=15, show_spinner=False)
def load_data_from_sheet():
    client = get_gspread_client()
    if not client:
        return {}
    try:
        sheet = client.open_by_url(SPREADSHEET_URL).sheet1
        records = sheet.get_all_records()
        cases = {}
        for row in records:
            case_id = str(row.get("case_id", ""))
            if case_id:
                details_json = row.get("details_json", "{}")
                messages_json = row.get("messages_json", "[]")
                try:
                    details = json.loads(details_json)
                except Exception:
                    details = {}
                try:
                    messages = json.loads(messages_json)
                except Exception:
                    messages = []
                cases[case_id] = {
                    "details": details,
                    "messages": messages
                }
        return cases
    except Exception as e:
        st.warning(f"구글 시트 데이터를 불러오는 중 주의: {e}")
        return st.session_state.get("cases_data", {})

def save_case_to_sheet(case_id, case_data):
    client = get_gspread_client()
    if not client:
        return False
    try:
        sheet = client.open_by_url(SPREADSHEET_URL).sheet1
        
        # 시트 용량 초과 및 오류 방지를 위한 미디어 정돈 (복사본 사용)
        clean_messages = []
        for msg in case_data.get("messages", []):
            msg_copy = dict(msg)
            # 구글 시트 저장용 미디어 텍스트 정돈
            if "media_data" in msg_copy and msg_copy["media_data"]:
                if len(str(msg_copy["media_data"])) > 500:
                    msg_copy["media_data"] = "[📷 사진/동영상 첨부 완료 - 웹 앱에서 확인 가능]"
            clean_messages.append(msg_copy)

        details_json = json.dumps(case_data.get("details", {}), ensure_ascii=False)
        messages_json = json.dumps(clean_messages, ensure_ascii=False)
        updated_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        cell = None
        try:
            cell = sheet.find(str(case_id), in_column=1)
        except Exception:
            cell = None

        if cell:
            row_idx = cell.row
            sheet.update(f"B{row_idx}:D{row_idx}", [[details_json, messages_json, updated_at]])
        else:
            sheet.append_row([str(case_id), details_json, messages_json, updated_at])

        st.cache_data.clear() # 저장 후 즉시 캐시 갱신
        return True
    except Exception as e:
        st.error(f"구글 시트 저장 오류: {e}")
        return False

# --- 이미지 용량 자동 압축 함수 ---
def compress_image(image_bytes, max_size=(600, 600), quality=70):
    try:
        img = Image.open(BytesIO(image_bytes))
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        img.thumbnail(max_size, Image.Resampling.LANCZOS)
        buffer = BytesIO()
        img.save(buffer, format="JPEG", quality=quality)
        return buffer.getvalue()
    except Exception:
        return image_bytes

# --- 보고서 파일 생성 함수 (PDF, HWP, TXT) ---
def generate_report_files(case_id, details, messages):
    resident_name = details.get("name", "미기재")
    phone = details.get("phone", "미기재")
    status = details.get("status", "진행중")
    summary = details.get("summary", "요약 내역이 없습니다.")
    checklist = details.get("checklist", {})
    
    # 1. HWP / TXT 공통 텍스트 구성
    report_text = f"""[주택관리공단 현장 상담 보고서]
------------------------------------------------------------------
■ 세대 기본 정보
- 동/호수 (세대): {case_id}
- 입주자 성명: {resident_name}
- 연락처: {phone}
- 진행 상태: {status}

■ AI 핵심 요약 및 분석
------------------------------------------------------------------
{summary}

■ 현장 점검 체크리스트
------------------------------------------------------------------
"""
    for item, checked in checklist.items():
        report_text += f"[{'V' if checked else ' '}] {item}\n"

    report_text += f"\n■ 상담 및 조치 이력\n------------------------------------------------------------------\n"
    for msg in messages:
        sender = msg.get("sender", "알 수 없음")
        time_str = msg.get("time", "")
        text = msg.get("text", "")
        media = "[미디어 첨부]" if msg.get("media_type") else ""
        report_text += f"[{time_str}] {sender}: {text} {media}\n"

    hwp_bytes = report_text.encode("utf-8-sig")
    txt_bytes = report_text.encode("utf-8")

    # 2. PDF 생성
    pdf_bytes = None
    if WEASYPRINT_AVAILABLE:
        try:
            checklist_rows = ""
            for item, checked in checklist.items():
                status_icon = "☑" if checked else "☐"
                checklist_rows += f"<tr><td>{item}</td><td style='text-align:center;'>{status_icon}</td></tr>"
            if not checklist_rows:
                checklist_rows = "<tr><td colspan='2' style='text-align:center; color:#888;'>등록된 체크리스트가 없습니다.</td></tr>"

            msg_rows = ""
            for msg in messages:
                sender = msg.get("sender", "알 수 없음")
                time_str = msg.get("time", "")
                text = msg.get("text", "")
                msg_rows += f"""
                <div style="margin-bottom: 8px; padding: 8px; background-color: #f8f9fa; border-radius: 4px; border-left: 3px solid #1e3a8a;">
                    <div style="font-size: 9pt; color: #555; margin-bottom: 4px;"><strong>[{sender}]</strong> <span style="float:right;">{time_str}</span></div>
                    <div style="font-size: 10pt;">{text}</div>
                </div>
                """
            if not msg_rows:
                msg_rows = "<p style='color:#888;'>상담 기록이 없습니다.</p>"

            html_content = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="utf-8">
                <style>
                    @page {{ size: A4; margin: 15mm 12mm; }}
                    body {{ font-family: sans-serif; color: #222; font-size: 10pt; line-height: 1.5; }}
                    .header {{ background-color: #1e3a8a; color: #fff; padding: 15px; margin: -15mm -12mm 15px -12mm; }}
                    .header h1 {{ margin: 0; font-size: 18pt; }}
                    .section-title {{ font-size: 12pt; font-weight: bold; color: #1e3a8a; border-left: 4px solid #1e3a8a; padding-left: 8px; margin-top: 15px; margin-bottom: 8px; }}
                    table {{ width: 100%; border-collapse: collapse; margin-bottom: 12px; }}
                    th, td {{ border: 1px solid #cbd5e1; padding: 6px 10px; font-size: 9.5pt; }}
                    th {{ background-color: #f1f5f9; font-weight: bold; text-align: left; }}
                    .summary-box {{ background-color: #eff6ff; border: 1px solid #bfdbfe; padding: 10px; border-radius: 4px; white-space: pre-wrap; }}
                </style>
            </head>
            <body>
                <div class="header">
                    <h1>주택관리공단 현장 상담 보고서</h1>
                    <p>등촌7단지 주거복지 현장 관리 시스템</p>
                </div>
                <div class="section-title">세대 기본 정보</div>
                <table>
                    <tr><th width="20%">동/호수</th><td width="30%"><strong>{case_id}</strong></td><th width="20%">입주자 성명</th><td width="30%">{resident_name}</td></tr>
                    <tr><th>연락처</th><td>{phone}</td><th>진행 상태</th><td><strong>{status}</strong></td></tr>
                </table>
                <div class="section-title">AI 핵심 요약 및 분석</div>
                <div class="summary-box">{summary}</div>
                <div class="section-title">현장 점검 체크리스트</div>
                <table><thead><tr><th>점검 항목</th><th width="25%" style="text-align:center;">점검 여부</th></tr></thead><tbody>{checklist_rows}</tbody></table>
                <div class="section-title">상담 및 조치 이력</div>
                {msg_rows}
            </body>
            </html>
            """
            pdf_bytes = HTML(string=html_content).write_pdf()
        except Exception as e:
            st.error(f"PDF 생성 중 예외 발생: {e}")

    return pdf_bytes, hwp_bytes, txt_bytes


# --- 세션 상태 초기화 및 데이터 로드 ---
if "cases_data" not in st.session_state:
    st.session_state.cases_data = load_data_from_sheet()

# --- 비밀번호 인증 ---
APP_PASSWORD = st.secrets.get("APP_PASSWORD", "1234")
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.title("🔒 주택관리공단 현장 업무 시스템")
    pwd_input = st.text_input("접속 비밀번호를 입력하세요:", type="password")
    if st.button("로그인"):
        if pwd_input == APP_PASSWORD:
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("비밀번호가 올바르지 않습니다.")
    st.stop()

# --- 메인 대시보드 UI ---
st.sidebar.markdown("### 🟢 구글 시트 영구 저장 연동 중")
if st.sidebar.button("🔄 데이터 강제 새로고침"):
    st.cache_data.clear()
    st.session_state.cases_data = load_data_from_sheet()
    st.success("최신 데이터를 불러왔습니다.")

st.title("🏢 등촌7단지 주거복지 현장 관리 시스템")

# 신규 세대 추가
with st.sidebar.expander("➕ 신규 상담 세대 추가"):
    new_case_id = st.text_input("세대 (예: 701동 101호)")
    new_name = st.text_input("입주자 성명")
    new_phone = st.text_input("연락처")
    if st.button("세대 등록"):
        if new_case_id:
            if new_case_id not in st.session_state.cases_data:
                st.session_state.cases_data[new_case_id] = {
                    "details": {
                        "name": new_name,
                        "phone": new_phone,
                        "status": "진행중",
                        "summary": "신규 등록된 세대입니다.",
                        "checklist": {
                            "보일러 및 난방 상태": False,
                            "누수 및 벽지 곰팡이": False,
                            "위생 및 청결 상태": False,
                            "거주자 건강 및 안부": False
                        }
                    },
                    "messages": []
                }
                save_case_to_sheet(new_case_id, st.session_state.cases_data[new_case_id])
                st.success(f"{new_case_id} 등록 완료!")
                st.rerun()
            else:
                st.warning("이미 등록된 세대입니다.")
        else:
            st.error("세대 번호를 입력하세요.")

# 세대 선택
case_list = list(st.session_state.cases_data.keys())
if not case_list:
    st.info("좌측 사이드바에서 신규 세대를 등록해 주세요.")
    st.stop()

current_case = st.selectbox("📌 관리할 세대를 선택하세요:", case_list)

if current_case:
    case_info = st.session_state.cases_data[current_case]
    details = case_info.get("details", {})
    messages = case_info.get("messages", [])

    st.markdown("---")
    col1, col2 = st.columns([1, 1])

    with col1:
        st.subheader(f"🏠 {current_case} 세대 정보")
        st.write(f"**성명:** {details.get('name', '미기재')}")
        st.write(f"**연락처:** {details.get('phone', '미기재')}")
        st.write(f"**상태:** {details.get('status', '진행중')}")

        # 체크리스트
        st.markdown("#### 📋 현장 점검 체크리스트")
        checklist = details.get("checklist", {})
        updated_checklist = {}
        checklist_changed = False

        for k, v in checklist.items():
            val = st.checkbox(k, value=v, key=f"check_{current_case}_{k}")
            updated_checklist[k] = val
            if val != v:
                checklist_changed = True

        if checklist_changed:
            details["checklist"] = updated_checklist
            save_case_to_sheet(current_case, case_info)
            st.toast("체크리스트가 구글 시트에 업데이트되었습니다.")

        # AI 요약 및 다운로드
        st.markdown("#### 🤖 AI 현장 요약")
        st.info(details.get("summary", "요약 정보가 없습니다."))

        if st.button("✨ AI 현장 상담 요약 생성"):
            api_key = st.secrets.get("OPENAI_API_KEY")
            if api_key:
                try:
                    client = openai.OpenAI(api_key=api_key)
                    msg_text = "\n".join([f"[{m.get('sender')}] {m.get('text')}" for m in messages])
                    prompt = f"다음은 {current_case} 세대의 현장 상담 기록입니다. 핵심 내용과 조치 필요 사항을 3줄 이내로 명확히 요약해 주세요:\n\n{msg_text}"
                    response = client.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=[{"role": "user", "content": prompt}]
                    )
                    new_summary = response.choices[0].message.content
                    details["summary"] = new_summary
                    save_case_to_sheet(current_case, case_info)
                    st.success("AI 요약이 생성되어 구글 시트에 저장되었습니다.")
                    st.rerun()
                except Exception as e:
                    st.error(f"AI 요약 실패: {e}")
            else:
                st.error("OpenAI API 키가 설정되지 않았습니다.")

        # 📥 3종 보고서 다운로드 영역
        st.markdown("---")
        st.markdown("#### 📥 상담 보고서 다운로드")
        pdf_data, hwp_data, txt_data = generate_report_files(current_case, details, messages)
        
        d_col1, d_col2, d_col3 = st.columns(3)
        with d_col1:
            if pdf_data:
                st.download_button("📄 PDF 저장", data=pdf_data, file_name=f"상담보고서_{current_case}.pdf", mime="application/pdf", use_container_width=True)
            else:
                st.caption("📄 PDF 지원 안 됨")
        with d_col2:
            st.download_button("📝 한글(HWP) 저장", data=hwp_data, file_name=f"상담보고서_{current_case}.hwp", mime="text/plain;charset=utf-8-sig", use_container_width=True)
        with d_col3:
            st.download_button("TXT 저장", data=txt_data, file_name=f"상담보고서_{current_case}.txt", mime="text/plain", use_container_width=True)

    with col2:
        st.subheader("💬 현장 상담 및 조치 이력")

        # 대화 출력
        for msg in messages:
            sender = msg.get("sender", "알 수 없음")
            text = msg.get("text", "")
            time_str = msg.get("time", "")
            media_data = msg.get("media_data")
            media_type = msg.get("media_type")

            with st.chat_message("user" if sender == "현장담당자" else "assistant"):
                st.write(f"**[{sender}]** <span style='font-size:0.8em; color:gray;'>{time_str}</span>", unsafe_allow_html=True)
                st.write(text)

                if media_data:
                    # 안전한 미디어 표시 로직
                    if str(media_data).startswith("data:image"):
                        st.image(media_data, caption="📷 현장 첨부 사진", use_container_width=True)
                    elif str(media_data).startswith("data:video"):
                        st.video(media_data)
                    else:
                        st.caption(f"ℹ️ {media_data}")

        # 입력 Form
        st.markdown("---")
        with st.form("chat_form", clear_on_submit=True):
            sender_type = st.radio("작성자 구분", ["현장담당자", "입주민"], horizontal=True)
            input_text = st.text_area("상담 내용 입력:")
            uploaded_file = st.file_uploader("📷 사진/동영상 첨부 (선택)", type=["png", "jpg", "jpeg", "webp", "mp4", "mov"])
            submit_btn = st.form_submit_button("메시지 및 미디어 등록")

            if submit_btn:
                if input_text or uploaded_file:
                    media_b64 = None
                    m_type = None

                    if uploaded_file:
                        file_bytes = uploaded_file.read()
                        file_ext = uploaded_file.name.split(".")[-1].lower()

                        if file_ext in ["png", "jpg", "jpeg", "webp"]:
                            compressed_bytes = compress_image(file_bytes)
                            media_b64 = f"data:image/jpeg;base64,{base64.b64encode(compressed_bytes).decode('utf-8')}"
                            m_type = "image"
                        elif file_ext in ["mp4", "mov"]:
                            media_b64 = f"data:video/mp4;base64,{base64.b64encode(file_bytes).decode('utf-8')}"
                            m_type = "video"

                    new_msg = {
                        "sender": sender_type,
                        "text": input_text if input_text else "(미디어 첨부)",
                        "time": datetime.datetime.now().strftime("%m/%d %H:%M"),
                        "media_data": media_b64,
                        "media_type": m_type
                    }

                    messages.append(new_msg)
                    save_case_to_sheet(current_case, case_info)
                    st.success("등록 완료 및 구글 시트 반영!")
                    st.rerun()
