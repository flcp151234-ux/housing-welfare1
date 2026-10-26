import streamlit as st
import json
import re
import os
import datetime
import hashlib
import hmac
from datetime import timezone, timedelta
import base64
import io
import uuid
import mimetypes
import tempfile
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
from google.oauth2.credentials import Credentials as UserCredentials
from google.auth.transport.requests import Request
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


# 첨부파일: 기존 sheetmedia 데이터는 읽기 전용으로 호환, 신규 업로드는 Drive 원본 보존.
IMAGE_LIMIT = 20 * 1024 * 1024
VIDEO_LIMIT = 200 * 1024 * 1024
MEDIA_CHUNK_SIZE = 24000

def db_enabled():
    return False

def media_storage_enabled():
    try:
        return get_drive_service() is not None
    except Exception:
        return False

@st.cache_resource(show_spinner=False)
def get_drive_service():
    """Google Drive OAuth 연결. 설정 누락과 인증 실패를 구분하여 안내합니다."""
    oauth = st.secrets.get("drive_oauth", None)
    if oauth is not None:
        missing = [k for k in ("client_id", "client_secret", "refresh_token") if not oauth.get(k)]
        if missing:
            raise RuntimeError("Streamlit Secrets [drive_oauth]에 누락된 항목: " + ", ".join(missing))
        try:
            creds = UserCredentials(
                token=None,
                refresh_token=str(oauth["refresh_token"]).strip(),
                client_id=str(oauth["client_id"]).strip(),
                client_secret=str(oauth["client_secret"]).strip(),
                token_uri="https://oauth2.googleapis.com/token",
                scopes=["https://www.googleapis.com/auth/drive"],
            )
            creds.refresh(Request())
            return build("drive", "v3", credentials=creds, cache_discovery=False)
        except Exception as exc:
            # 원본 오류 메시지에 토큰이 포함될 수 있으므로 사용자 화면에는 예외 종류만 표시.
            raise RuntimeError(
                f"Google Drive OAuth 연결 실패 ({type(exc).__name__}). "
                "토큰 만료/취소, OAuth 클라이언트 불일치, Drive API 활성화, "
                "Google Cloud OAuth 게시 상태를 확인하세요."
            ) from exc
    if st.secrets.get("DRIVE_SHARED_FOLDER_ID") and "gcp_service_account" in st.secrets:
        try:
            creds = Credentials.from_service_account_info(
                dict(st.secrets["gcp_service_account"]),
                scopes=["https://www.googleapis.com/auth/drive"],
            )
            return build("drive", "v3", credentials=creds, cache_discovery=False)
        except Exception as exc:
            raise RuntimeError(f"공유 드라이브 서비스 계정 연결 실패 ({type(exc).__name__}).") from exc
    raise RuntimeError(
        "Streamlit Secrets에 [drive_oauth] 설정이 없습니다. "
        "앱의 Settings > Secrets에 client_id, client_secret, refresh_token을 입력하세요."
    )

def _drive_folder():
    folder = str(st.secrets.get("DRIVE_FOLDER_ID", st.secrets.get("DRIVE_SHARED_FOLDER_ID", ""))).strip()
    if not folder:
        raise ValueError("Secrets에 DRIVE_FOLDER_ID를 설정해야 합니다.")
    return folder

def save_media_file(file_obj, complex_name, case_id):
    service = get_drive_service()
    mime = (file_obj.type or mimetypes.guess_type(file_obj.name)[0] or "").lower()
    is_image = mime in {"image/jpeg", "image/png", "image/webp"}
    is_video = mime in {"video/mp4", "video/quicktime", "video/x-msvideo"}
    if not (is_image or is_video):
        raise ValueError("JPG, PNG, WEBP, MP4, MOV, AVI만 지원합니다.")
    size = file_obj.size
    limit = IMAGE_LIMIT if is_image else VIDEO_LIMIT
    if size > limit:
        raise ValueError(f"업로드 제한 초과: 사진 20MB / 동영상 200MB (현재 {size / 1024**2:.1f}MB)")
    # SpooledTemporaryFile을 이용하여 전체 파일의 base64 복제를 피합니다.
    with tempfile.NamedTemporaryFile(suffix="_upload", delete=True) as temp:
        file_obj.seek(0)
        while True:
            chunk = file_obj.read(4 * 1024 * 1024)
            if not chunk:
                break
            temp.write(chunk)
        temp.flush()
        safe_name = os.path.basename(file_obj.name).replace("/", "_")[:120]
        metadata = {
            "name": f"{uuid.uuid4().hex}_{safe_name}",
            "parents": [_drive_folder()],
            "appProperties": {"complex": str(complex_name), "case_id": str(case_id)}
        }
        media = MediaFileUpload(temp.name, mimetype=mime, resumable=True, chunksize=8 * 1024 * 1024)
        request = service.files().create(body=metadata, media_body=media, fields="id", supportsAllDrives=True)
        result = None
        while result is None:
            _, result = request.next_chunk(num_retries=3)
    return "drivefile:" + result["id"]

@st.cache_resource(show_spinner=False)
def get_media_sheet():
    book = get_spreadsheet()
    if book is None:
        return None
    try:
        return book.worksheet("media_chunks")
    except gspread.WorksheetNotFound:
        return None

@st.cache_data(ttl=300, show_spinner=False, max_entries=16)
def read_legacy_sheet_media(token, complex_name, case_id):
    ws = get_media_sheet()
    if ws is None:
        raise ValueError("이전 첨부파일 저장 시트를 찾을 수 없습니다.")
    ids = ws.col_values(1)
    rows = [i + 1 for i, x in enumerate(ids) if i > 0 and x == token]
    if not rows:
        raise ValueError("첨부파일을 찾을 수 없습니다.")
    parts = []
    for rownum in rows:
        values = ws.row_values(rownum)
        if len(values) < 6 or values[1] != complex_name or values[2] != case_id:
            raise PermissionError("현재 상담 건의 첨부파일이 아닙니다.")
        parts.append((int(values[4]), values[5]))
    return base64.b64decode("".join(v for _, v in sorted(parts)))

@st.cache_data(ttl=180, show_spinner=False, max_entries=6)
def read_drive_media(file_id, complex_name, case_id):
    service = get_drive_service()
    meta = service.files().get(fileId=file_id, fields="id,size,mimeType,appProperties,parents", supportsAllDrives=True).execute()
    props = meta.get("appProperties", {})
    if props.get("complex") != str(complex_name) or props.get("case_id") != str(case_id):
        raise PermissionError("다른 단지 또는 상담 건의 파일입니다.")
    if _drive_folder() not in meta.get("parents", []):
        raise PermissionError("설정된 보관 폴더 밖의 파일입니다.")
    if int(meta.get("size", 0)) > VIDEO_LIMIT:
        raise ValueError("허용된 최대 파일 크기를 초과합니다.")
    request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
    output = io.BytesIO()
    downloader = MediaIoBaseDownload(output, request, chunksize=4 * 1024 * 1024)
    done = False
    while not done:
        _, done = downloader.next_chunk(num_retries=3)
    return output.getvalue()

def resolve_media(data, complex_name=None, case_id=None):
    if isinstance(data, str) and data.startswith("drivefile:"):
        return read_drive_media(data[len("drivefile:"):], complex_name, case_id)
    if isinstance(data, str) and data.startswith("sheetmedia:"):
        return read_legacy_sheet_media(data[len("sheetmedia:"):], complex_name, case_id)
    return data

def display_saved_media(data, kind, complex_name, case_id, key):
    """대용량 파일은 사용자가 열기를 선택한 경우에만 Drive에서 읽음."""
    if isinstance(data, str) and data.startswith(("drivefile:", "sheetmedia:")):
        with st.expander("📷 사진 보기" if kind == "image" else "🎥 동영상 재생 / 다운로드", expanded=False):
            if st.button("원본 불러오기", key=f"load_{key}"):
                st.session_state[f"opened_{key}"] = True
            if st.session_state.get(f"opened_{key}"):
                try:
                    payload = resolve_media(data, complex_name, case_id)
                    if kind == "image":
                        st.image(payload, use_container_width=True)
                    else:
                        st.video(payload)
                    st.download_button("원본 다운로드", data=payload,
                                       file_name=f"현장첨부_{case_id}_{key}.{'jpg' if kind == 'image' else 'mp4'}",
                                       key=f"download_{key}")
                except Exception as exc:
                    st.error(f"첨부파일을 열 수 없습니다: {exc}")
    elif kind == "image":
        try:
            st.image(data, use_container_width=True)
        except Exception:
            st.caption("이전 사진 형식은 미리보기를 지원하지 않습니다.")
    elif kind == "video":
        try:
            st.video(data)
        except Exception:
            st.caption("이전 동영상 형식은 미리보기를 지원하지 않습니다.")

@st.cache_data(ttl=30, show_spinner=False)
def load_data(complex_name=None):
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
        if msg_copy.get("media_type") == "video" and media and not str(media).startswith(("sheetmedia:", "drivefile:")):
            msg_copy["media_data"] = "[🎥 동영상 첨부 완료]"
        elif msg_copy.get("media_type") == "image" and media and len(str(media)) > 30000 and not str(media).startswith(("sheetmedia:", "drivefile:")):
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
                snapshot_key = f"case_baseline_{changed_id}"
                if matches:
                    remote = sheet.row_values(target_row)
                    remote_hash = hashlib.sha256(json.dumps(remote[:9], ensure_ascii=False).encode()).hexdigest()
                    baseline = st.session_state.get(snapshot_key)
                    if baseline is not None and baseline != remote_hash:
                        raise ValueError("다른 담당자가 먼저 수정했습니다. 변경 내용이 덮어써지지 않도록 저장을 중단했습니다. 새로고침 후 확인해 주세요.")
                if not ids:
                    sheet.update(range_name="A1:I1", values=[CASE_HEADERS])
                updated_row = case_to_sheet_row(item)
                sheet.update(range_name=f"A{target_row}:I{target_row}", values=[updated_row])
                st.session_state[snapshot_key] = hashlib.sha256(json.dumps([str(v) for v in updated_row], ensure_ascii=False).encode()).hexdigest()
            else:
                raise ValueError("전체 상담 시트 덮어쓰기는 동시 사용자 데이터 손실 방지를 위해 비활성화되었습니다.")
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
        if msg.get("media_type") == "image" and msg.get("media_data") and (str(msg.get("media_data")).startswith("data:image") or str(msg.get("media_data")).startswith(("sheetmedia:", "drivefile:")))
    ]

    if image_attachments:
        elements.append(HRFlowable(width="100%", thickness=1, color="gray", spaceAfter=10))
        elements.append(Paragraph("<b>■ 현장 첨부 사진</b>", sub_style))
        elements.append(Spacer(1, 10))

        for idx, img_b64 in enumerate(image_attachments):
            try:
                if str(img_b64).startswith(("sheetmedia:", "drivefile:")):
                    img_data = resolve_media(img_b64, case_info.get("complex"), case_info.get("id"))
                elif "," in img_b64:
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
    loaded_cases = load_data(st.session_state.active_complex)
    if not db_enabled() and not loaded_cases and get_gsheet_worksheet() is None and not os.path.exists(DATA_FILE):
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

# 최초 불러온 상담 건의 저장 당시 원본을 기록합니다.
# Google Sheets는 원자적 비교 후 갱신을 제공하지 않으므로 동시 클릭 경합은 완전히 막지 못합니다.
def initialize_case_baselines():
    ws = get_gsheet_worksheet()
    if ws is None:
        return
    try:
        values = ws.get_all_values()
        for row in values[1:]:
            if row and row[0]:
                key = f"case_baseline_{row[0]}"
                if key not in st.session_state:
                    st.session_state[key] = hashlib.sha256(json.dumps(row[:9], ensure_ascii=False).encode()).hexdigest()
    except Exception:
        pass

if not st.session_state.get("_baselines_initialized"):
    initialize_case_baselines()
    st.session_state["_baselines_initialized"] = True

# 단지 목록 구성: 기존 데이터의 단지명도 자동 포함
complexes = load_complexes()
if not db_enabled():
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
                if db_enabled():
                    st.session_state.cases = load_data(chosen_complex)
                st.rerun()
        else:
            with st.form("complex_login_form"):
                complex_pwd = st.text_input(f"🔑 {chosen_complex} 비밀번호", type="password")
                complex_login = st.form_submit_button("단지 로그인", type="primary", use_container_width=True)
                if complex_login:
                    if verify_password(complex_pwd, complexes[chosen_complex]["password_hash"]):
                        st.session_state.complex_authenticated[chosen_complex] = True
                        st.session_state.active_complex = chosen_complex
                        if db_enabled():
                            st.session_state.cases = load_data(chosen_complex)
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
                if db_enabled():
                    st.session_state.cases = []
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

# 실제 공개된 대표 상담번호만 코드에 등록합니다.
# 각 지역 치매안심센터/복지관의 개별 전화번호는 조회되지 않는 한 만들지 않습니다.
VERIFIED_CONTACTS = (
    (('치매', '인지저하', '기억력 저하', '치매안심센터'), '중앙치매센터 치매상담콜센터', '1899-9988'),
    (('정신건강', '저장강박', '우울', '조현병', '불안장애', '정신질환', '정신건강복지센터'), '정신건강상담전화', '1577-0199'),
    (('자살', '자해', '극단적 선택', '자살예방'), '자살예방상담전화', '109'),
    (('노인일자리', '어르신 일자리', '시니어 일자리'), '노인일자리 상담안내', '1544-3388'),
    (('생계', '긴급복지', '기초생활', '주거급여', '의료급여', '복지관', '주거복지', '청소 지원', '도배', '고독사', '독거', '노인복지', '돌봄', '장애인복지', '복지서비스'), '보건복지상담센터', '129'),
    (('장기요양', '요양등급', '방문요양', '건강보험', '건보'), '국민건강보험공단 고객센터', '1577-1000'),
    (('국민연금', '기초연금', '연금수급'), '국민연금공단 고객센터', '1355'),
    (('실직', '실업급여', '구직', '취업', '고용노동', '임금체불', '근로'), '고용노동부 고객상담센터', '1350'),
    (('채무', '대출', '금융', '고금리', '서민금융', '생활자금', '소액대출'), '서민금융콜센터', '1397'),
    (('신용회복', '개인워크아웃', '채무조정', '연체', '빚'), '신용회복위원회', '1600-5500'),
    (('법률', '소송', '법률구조', '임대차 분쟁', '법적 대응', '법률상담'), '대한법률구조공단', '132'),
    (('가정폭력', '성폭력', '스토킹', '여성긴급', '데이트폭력'), '여성긴급전화', '1366'),
    (('청소년', '학교밖', '청소년상담', '가출 청소년'), '청소년상담전화', '1388'),
    (('학교폭력', '학폭'), '학교폭력 신고·상담', '117'),
    (('중독', '알코올', '도박중독', '약물중독'), '정신건강상담전화', '1577-0199'),
    (('자살위기', '생명의전화'), '한국생명의전화', '1588-9191'),
    (('세금', '국세', '종합소득세', '근로장려금'), '국세상담센터', '126'),
    (('금융사기', '불완전판매', '금융민원', '보이스피싱'), '금융감독원 콜센터', '1332'),
    (('정부민원', '행정민원', '정부24', '민원안내'), '정부민원안내콜센터', '110'),
    (('여성취업', '경력단절', '새일센터'), '여성새로일하기센터', '1544-1199'),
    (('범죄', '폭행', '학대', '신변위협'), '경찰 긴급신고', '112'),
    (('응급', '심정지', '의식불명', '화재', '구급'), '소방·구급 긴급신고', '119'),
)
PHONE_LIKE_RE = re.compile(r"(?<!\w)(?:\+82[- .]?)?(?:0\d{1,2}[- .]?)?\d{3,4}[- .]?\d{4}(?!\w)|(?<!\d)(?:129|110|109|112|119|1366)(?!\d)")
CONTACT_LINE_RE = re.compile(r"^\s*[-•]?\s*(?:대표\s*)?(?:전화번호|연락처|직통번호|대표번호)\s*[:：]")
def clean_summary_and_add_official_hotlines(report, dialogue):
    """추천 기관의 지원서비스 설명 바로 아래에 공식 대표 상담번호를 표시."""
    report = str(report).replace("\\r\\n", "\n").replace("\\n", "\n")
    # 과거 버전이 생성한 별도 번호 목록 및 이 버전의 자동 삽입 행은 다시 생성
    report = report.split("## 상담 내용별 공식 대표 상담번호")[0].rstrip()
    cleaned = []
    for line in report.splitlines():
        if line.strip().startswith("- **관련 공식 상담전화**:") or line.strip().startswith("- **지원 신청 안내**:"):
            continue
        if CONTACT_LINE_RE.match(line):
            continue
        cleaned.append(PHONE_LIKE_RE.sub("", line))
    report = "\n".join(cleaned)

    # 기관별 지원내용이 이미 작성된 경우 그 내용을 그대로 살리고, 번호와 신청경로만 보강
    sections = re.split(r"(?=^### \[우선순위\s*\d+\])", report, flags=re.MULTILINE)
    output = []
    any_inline = False
    for section in sections:
        if not re.match(r"^### \[우선순위\s*\d+\]", section):
            output.append(section)
            continue
        matched = []
        low = section.lower()
        for keywords, agency, phone in VERIFIED_CONTACTS:
            if any(k.lower() in low for k in keywords):
                item = (agency, phone)
                if item not in matched:
                    matched.append(item)
        if not matched:
            output.append(section)
            continue
        any_inline = True
        contact_lines = ["- **관련 공식 상담전화**: " + " / ".join(f"{agency} ☎ {phone}" for agency, phone in matched[:3]),
                         "- **지원 신청 안내**: 위 대표 상담번호로 지원 대상·필요서류·관할 접수기관을 문의한 뒤 해당 기관에 신청하세요. (표시된 번호는 지역 개별 기관의 직통번호가 아닙니다.)"]
        sec_lines = section.rstrip().splitlines()
        insert_at = next((i+1 for i, line in enumerate(sec_lines) if "연계할 문제/지원받을 수 있는 서비스" in line), None)
        if insert_at is None:
            insert_at = next((i+1 for i, line in enumerate(sec_lines) if "추천 이유 및 상담 근거" in line), 1)
        sec_lines[insert_at:insert_at] = contact_lines
        output.append("\n".join(sec_lines) + "\n")
    result = "".join(output).rstrip()
    if not any_inline:
        source = (dialogue + "\n" + report).lower()
        matched = []
        for keywords, agency, phone in VERIFIED_CONTACTS:
            if any(k.lower() in source for k in keywords) and (agency, phone) not in matched:
                matched.append((agency, phone))
        if matched:
            result += "\n\n## 상담 내용별 공식 대표 상담번호\n" + "\n".join(
                f"- {agency}: {phone}" for agency, phone in matched
            ) + "\n※ 지역 기관 직통번호가 아닌 전국 대표 상담번호입니다."
    return result

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
        if db_enabled():
            st.session_state.cases = []
        st.session_state.pop("selected_case_id", None)
        st.rerun()
    
    if db_enabled():
        st.success("🟢 PostgreSQL 상담 데이터 저장 (동시 수정 보호)")
    else:
        st.caption("Google Sheets 저장: 수정 전 변경 감지 적용. 동시에 저장 버튼을 누르는 경우 완전한 충돌 방지는 어렵습니다.")
    if not media_storage_enabled():
        st.caption("첨부파일 보존: Google Sheets 연결 필요")

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
                        if db_enabled():
                            db_delete_complex(target)
                        else:
                            st.error("전체 단지 삭제는 동시 접속 중 데이터 손상 위험이 있어 차단했습니다. 관리자가 별도 백업 후 시트에서 처리해 주세요.")
                        st.stop()
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
                new_id = f"CASE-{uuid.uuid4().hex[:16]}"
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
                "📷 현장 사진 (20MB 이하) 또는 🎥 동영상 (200MB 이하) 첨부", 
                type=["png", "jpg", "jpeg", "webp", "mp4", "mov", "avi"],
                help="원본 저장: 사진 최대 20MB, 동영상 최대 200MB. Drive 무료 용량 및 Streamlit 서버 메모리 제한이 적용됩니다."
            )
            
            submitted = st.form_submit_button("기록 및 첨부파일 저장", type="primary", use_container_width=True)
            
            if submitted and (message_text.strip() or uploaded_file is not None):
                media_type = None
                media_data = None
                
                if uploaded_file is not None:
                    try:
                        media_type = "image" if uploaded_file.type.startswith("image/") else "video"
                        media_data = save_media_file(uploaded_file, active_complex, current_case["id"])
                    except Exception as e:
                        st.error(f"첨부파일 저장 실패: {e}")
                        st.stop()

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
                    
                    if m_type in ("image", "video") and m_data:
                        display_saved_media(m_data, m_type, active_complex, current_case["id"], f"chat_{current_case['id']}_{idx}")

                    st.divider()

        if auto_sync:
            @st.fragment(run_every=60)
            def live_chat_area():
                load_data.clear()
                fresh_cases = load_data(active_complex)
                fresh_case = next((c for c in fresh_cases if c.get("id") == selected_id and c.get("complex") == active_complex), current_case)
                display_messages(fresh_case)
            live_chat_area()
        else:
            display_messages(current_case)

    with col_summary:
        st.write("##### 🤖 AI 자동 문서화 · 기관 우선순위 · 선제 조치")
        st.caption("상담 내용에 관련된 기관을 개수 제한 없이 우선순위로 제시하고, 관리소의 즉시·당일·후속 조치를 안내합니다. 실제 기관 접수 및 지원 가능 여부는 확인이 필요합니다.")
        
        if st.button("✨ 전체 대화 내용 AI 자동 요약 생성", type="primary", use_container_width=True):
            history = current_case.get("dialogue_history", [])
            if not history:
                st.warning("요약할 대화 내용이 없습니다.")
            elif not OPENAI_API_KEY:
                st.error("OpenAI API 키가 필요합니다. 사이드바에서 키를 입력해주세요.")
            else:
                with st.spinner("AI가 관련 기관 전체의 우선순위와 관리소 선제 조치를 분석 중입니다..."):
                    try:
                        import openai
                        client = openai.OpenAI(api_key=OPENAI_API_KEY, max_retries=2)
                        
                        raw_dialogue = "\n".join([f"{m.get('speaker')}: {m.get('text')}" for m in history])[-45000:]
                        
                        # 관련 기관 수를 임의로 3개로 제한하지 않고, 상담 내용에 근거한 기관을 우선순위별로 제시.
                        # 특정 기관의 실제 접수 가능 여부는 확인되지 않았으므로 기관 "유형"과 확인 경로를 구분한다.
                        prompt = f"""
당신은 대한민국 주거복지 현장 상담을 지원하는 실무 보조 전문가입니다.
상담 기록에 근거하여 주거복지 상담보고서와 선제 조치 계획을 한국어로 작성하세요.
대화에 없는 사실, 진단, 수급 자격, 기관 실명/주소/전화번호/URL을 만들어내지 마세요.
지원 자격 및 지원 여부는 담당 기관 확인이 필요하며, AI 결과는 신청/접수/승인을 뜻하지 않습니다.

[대상 세대 정보]
- 단지/동호수: {current_case.get('complex')} {current_case.get('unit')}
- 입주민 성명: {current_case.get('resident_name')}
- 현재 체크리스트 위험도: {current_case.get('risk_level', '관심')}
- 영역별 점수: {json.dumps(current_case.get('scores', {}), ensure_ascii=False)}

[상담 내용]
{raw_dialogue}

[분석 원칙]
1. 상담에서 확인된 사실과 추정/확인 필요 사항을 분리합니다. 언급되지 않은 문제는 임의로 추가하지 않습니다.
2. 주거비/체납, 생계, 건강, 돌봄, 치매, 정신건강, 고립, 장애, 아동, 노인, 안전, 시설, 위생, 폭력 등 실제 드러난 문제를 빠짐없이 분석합니다.
3. **추천 기관을 3개로 제한하지 마세요.** 실제 문제와 관련된 기관 유형을 가능한 한 모두 제시하되, 관련성이 낮은 기관을 수만 채우려고 나열하지 마세요. 중복 기관은 묶고, 복수의 문제가 있으면 분야별로 충분히 추천하세요.
4. 각 기관의 **우선순위(1순위부터)**는 긴급성, 현장 개입 가능성, 신청 접근성, 중복지원 가능성 확인 필요 등을 고려하여 정렬하고 근거를 명시합니다.
5. 기관명, 지원받을 수 있는 서비스, 신청 방법을 충실히 작성합니다. 전화번호는 절대 생성하지 마세요. 상담 분야별로 공식 확인된 대표 상담번호만 프로그램에서 별도로 삽입합니다. 개별 지역 기관의 번호를 모르면 번호를 쓰지 않습니다.
6. 복지 지원은 대상자의 동의, 자격, 예산, 지역별 사업 유무에 따라 달라집니다. 지원 확정처럼 단정하지 마세요.
7. 관리사무소가 자체적으로 할 수 있는 조치와 외부 기관이 판단/처리할 사항을 명확히 구분합니다. 개인정보는 적법한 근거 없이 외부 전송하지 않습니다.
8. 응급 위험(의식 저하, 자·타해 급박 위험, 화재/가스/전기 사고 등)이 확인되는 경우, 일반 복지 신청보다 119/112 등 적절한 긴급 대응을 우선 제안합니다. 위기 신호가 불명확하면 확인할 질문을 제시합니다.
9. 긴급복지, 기초생활보장, 주거급여, 에너지 지원 등 제도는 '검토 가능한 후보'로 표시하고 적격 여부를 확정하지 않습니다.
10. 모호한 '협력 체계 강화' 대신 담당자가 실제로 할 일, 기한, 확인 증빙을 구체적으로 적습니다.\n11. 저장강박이나 위생 악화 사례에서는 당사자 동의에 따른 방문상담, 보건소·정신건강복지센터 평가, 지자체 통합사례관리, 주거환경 개선사업 가능 여부를 구체적으로 검토하되 서비스 제공을 확정하지 않습니다.\n12. Markdown 제목과 줄바꿈은 실제 개행문자로 출력합니다. 백슬래시+n 문자를 출력하지 마세요.

[출력 형식 - 아래 순서와 제목 준수]
■ 1. 상담 핵심 요약
- 확인된 사실 / 추가 확인이 필요한 사항 / 주요 위험 요소

■ 2. 위기 상황별 지원 필요성
- 각 위기 요소의 근거(상담 발언), 긴급성, 검토할 지원 제도와 확인할 자격

■ 3. 지원 가능 기관 우선순위 전체 목록
상담에 실질적으로 관련 있는 기관을 1순위부터 빠짐없이 작성하세요. **기관 수 고정 제한 없음.**
각 기관마다 아래 내용을 반복하되, 같은 말을 반복하지 말고 구체적인 행동과 실제 가능한 지원 후보를 간결하게 작성하세요. 지역 기관의 실명이나 전화번호를 모르면 만들어내지 말고 기관 유형을 명확히 쓰세요.
[우선순위 N] 기관 유형(실제 지역 기관명 미확인 시 유형으로만 표기)
- 추천 이유 및 상담 근거:
- 연계할 문제/지원받을 수 있는 서비스(확정이 아닌 검토 대상):
- 공식 신청 사이트 또는 연락처 확인 경로(확인된 경로만; 불명확하면 확인 필요):
- 신청/상담 경로(확인된 경로만; 불명확하면 확인 필요):
- 관리소가 준비할 자료 및 입주민 동의 사항:
- 기관에 확인할 사항(대상 자격, 접수 방법, 지역 담당 여부):
- 우선순위 선정 이유:

■ 4. 관리소 선제 조치 계획 (우선순위 순)
[즉시: 안전 위험이 있는 경우 우선]
[당일: 현장 확인, 안전조치, 입주민 의사 확인, 담당자 보고 등]
[1~3일 이내: 기관 연락, 상담 예약, 신청 준비, 내부 승인 등]
[1~2주 이내: 접수 확인, 결과 점검, 미연계 사유 보완 등]
각 항목은 '조치 내용 / 담당 주체(관리소·입주민·외부기관 구분) / 기한 / 완료 확인 방법'으로 작성하세요.
해당 상황에 필요하지 않은 조치는 '해당 없음'으로 표시하세요.

■ 5. 입주민에게 추가로 확인할 질문
- 지원 신청 및 안전 판단에 꼭 필요한 질문을 3~7개 작성

■ 6. 연계·사후관리 체크리스트
- 동의 및 최소정보 제공 확인, 연락 시도, 신청 여부, 기관 접수 확인, 지원 결과, 다음 확인일

■ 7. 유의사항
- 본 내용은 상담에 기반한 검토안이며, 실제 지원 가능 여부는 기관 확인 후 결정됩니다.
"""

                        response = client.chat.completions.create(
                            model="gpt-4o-mini",
                            messages=[
                                {"role": "system", "content": "상담에 근거해 실무적으로 정확하고 구조적인 한국어 보고서를 작성하세요. 기관 수를 임의로 제한하지 마세요. 전화번호를 절대로 작성하지 마세요. 전화번호는 프로그램에서 별도로 삽입합니다. 상담에 없는 사실을 꾸미지 마세요. 추천 기관별로 지원받을 수 있는 서비스와 신청 방법을 구체적으로 작성하세요. 각 추천 기관마다 지원받을 수 있는 서비스 항목에 실제 신청 가능한 지원 후보를 명확히 적으세요. 전화번호는 프로그램이 추천 기관별 항목 안에 자동 삽입합니다."},
                                {"role": "user", "content": prompt}
                            ],
                            temperature=0.2,
                            max_tokens=6500,
                            timeout=75.0,
                        )

                        summary_result = response.choices[0].message.content
                        if not summary_result or not summary_result.strip():
                            raise ValueError("AI가 빈 요약문을 반환했습니다.")
                        summary_result = clean_summary_and_add_official_hotlines(summary_result, raw_dialogue)
                        previous_summary = current_case.get("ai_summary", "")
                        current_case["ai_summary"] = summary_result
                        if not save_data(st.session_state.cases, changed_id=current_case["id"]):
                            current_case["ai_summary"] = previous_summary
                            st.error("요약문 저장에 실패했습니다. 기존 요약문을 유지합니다.")
                            st.stop()
                        st.success("AI 보고서에 관련 기관 우선순위와 선제 조치 계획을 작성했습니다.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"AI 생성 중 오류가 발생했습니다: {e}")

        # 기존 저장된 요약문도 매 화면 표시 시 공식 대표번호를 연결합니다.
        history_for_numbers = current_case.get("dialogue_history", [])
        dialogue_for_numbers = "\n".join(str(m.get("text", "")) for m in history_for_numbers)
        displayed_summary = clean_summary_and_add_official_hotlines(
            str(current_case.get("ai_summary", "")), dialogue_for_numbers
        )
        st.markdown("##### ☎ 상담 내용에 맞는 공식 대표번호")
        number_section = displayed_summary.split("## 상담 내용별 공식 대표 상담번호")
        if len(number_section) > 1:
            st.markdown(number_section[-1])
        else:
            st.caption("현재 상담 내용에 대응하는 등록 대표번호가 없습니다.")

        with st.form(key=f"summary_edit_{current_case['id']}"):
            edited_summary = st.text_area("AI 생성 보고서 요약본", value=displayed_summary.replace("\\n", "\n"), height=320)
            save_summary = st.form_submit_button("💾 수정한 요약문 저장")
        if save_summary and edited_summary != current_case.get("ai_summary", ""):
            current_case["ai_summary"] = edited_summary
            if save_data(st.session_state.cases, changed_id=current_case["id"]):
                st.success("요약문이 저장되었습니다.")
                st.rerun()

        attachments = [(idx, msg) for idx, msg in enumerate(current_case.get("dialogue_history", []))
                       if msg.get("media_type") in ("image", "video") and msg.get("media_data")]
        if attachments:
            st.markdown("##### 📷🎥 AI 요약 관련 현장 첨부파일")
            st.caption("요약과 함께 사진·동영상을 확인할 수 있습니다. 파일은 열기를 누를 때만 불러옵니다. AI가 영상을 분석한 것은 아닙니다.")
            for idx, msg in attachments:
                display_saved_media(msg["media_data"], msg["media_type"], active_complex,
                                    current_case["id"], f"summary_{current_case['id']}_{idx}")

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
{displayed_summary}
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
        st.success("Google Sheets 저장 중 · 수정 전 원본 비교로 충돌을 감지합니다 (완전한 동시성 보장은 아님).")
    else:
        st.warning("Google Sheets 미연동: 클라우드 영구 저장을 보장하지 않습니다.")

    st.divider()

    st.markdown("#### 💾 수동 백업 및 복원 (비상용)")
    
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
                    # 다른 관리소 데이터는 건드리지 않고 신규 ID만 추가합니다.
                    existing_ids = {c.get("id") for c in st.session_state.cases}
                    imported = 0
                    for item in restored:
                        if item.get("id") not in existing_ids:
                            if save_data(st.session_state.cases + [item], changed_id=item["id"]):
                                st.session_state.cases.append(item)
                                existing_ids.add(item["id"])
                                imported += 1
                    st.info(f"신규 상담 {imported}건을 추가했습니다. 기존 상담은 덮어쓰지 않았습니다.")
                    st.success("🎉 복원 완료 (DB 모드에서는 기존 건을 덮어쓰지 않음)")
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
                    try:
                        remaining=[c for c in st.session_state.cases if c.get("id") != delete_id]
                        # 전체 시트 재작성은 다른 관리소 데이터를 손상시킬 수 있으므로 사용하지 않습니다.
                        ws = get_gsheet_worksheet()
                        ids = ws.col_values(1)
                        matches = [i+1 for i,v in enumerate(ids) if i>0 and v==delete_id]
                        if len(matches) != 1:
                            raise ValueError("삭제할 상담 건을 유일하게 확인할 수 없습니다.")
                        rownum = matches[0]
                        remote = ws.row_values(rownum)
                        baseline = st.session_state.get(f"case_baseline_{delete_id}")
                        remote_hash = hashlib.sha256(json.dumps(remote[:9],ensure_ascii=False).encode()).hexdigest()
                        if baseline and remote_hash != baseline:
                            raise ValueError("다른 담당자가 수정했습니다. 다시 불러온 뒤 삭제해 주세요.")
                        ws.delete_rows(rownum)
                        load_data.clear()
                        st.session_state.cases=[c for c in st.session_state.cases if c.get("id") != delete_id]
                    except Exception as e:
                        st.error(f"삭제 실패: {e}")
                        st.stop()
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
