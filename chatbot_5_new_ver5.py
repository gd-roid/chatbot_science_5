#이제 디자인 다듬고, 배포까지 갈 진짜 최종본 제작 용도# -*- coding: utf-8 -*-
# chatbot_5_new_ver4.py - 메타인지 기능 추가

import os, json, re, random
from datetime import datetime
import streamlit as st
import openai
import gspread
from oauth2client.service_account import ServiceAccountCredentials

def now_kst():
    from datetime import timezone, timedelta
    kst = timezone(timedelta(hours=9))
    return datetime.now(kst)

# ==================== 설정 ====================
openai.api_key = os.environ.get("OPENAI_API_KEY")
if not openai.api_key:
    st.error("❌ OPENAI_API_KEY 환경 변수가 설정되지 않았습니다!")
    st.info("💡 Streamlit Cloud에서는 Settings > Secrets에서 설정하세요.")
    st.stop()
SPREADSHEET_TITLE = "chatbot_QA"
QNA_TAB = "QNA"
LOG_TAB = "Sheet1"
SUMMARY_TAB = "Summary"
FOLLOWUP_TAB = "FollowUp"
METACOG_TAB = "Metacognition"

LEVEL_EMOJI = {"잘함":"✅", "보통":"⚠️", "노력요함":"❌"}

# 메타인지 질문 (성취기준별)
METACOG_QUESTIONS = {
    "6과07-01": [
        "같은 거리를 이동할 때 물체의 빠르기는 어떻게 비교하나요?",
        "같은 시간동안 이동할 때 물체의 빠르기는 어떻게 비교하나요?",
        "운동하는 물체의 특징은 무엇인가요?"
    ],
    "6과07-02": [
        "속력을 구하는 방법은 무엇인가요?",
        "속력의 단위에는 어떤 것이 있나요?"
    ],
    "6과07-03": [
        "속력과 관련된 교통안전수칙에는 어떤 것이 있나요?",
        "속력과 관련된 사고에서 피해를 줄여주기 위한 장치에는 무엇이 있나요?",
        "어린이 보호구역에서 자동차의 빠르기를 조절하기 위한 방법에는 무엇이 있나요?"
    ]
}

# ==================== GPT ====================
def gpt(messages, temp=0.2):
    return openai.chat.completions.create(
        model="gpt-4o", messages=messages, temperature=temp
    ).choices[0].message.content

# ==================== Google Sheets ====================
@st.cache_resource
def get_sheets_client():
    try:
        
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        
        # Streamlit Cloud에서 실행 시
        if "gcp_service_account" in st.secrets:
            creds = ServiceAccountCredentials.from_json_keyfile_dict(
                st.secrets["gcp_service_account"], scope
            )
        # 로컬에서 실행 시
        else:
            creds = ServiceAccountCredentials.from_json_keyfile_name("service_account.json", scope)
        
        return gspread.authorize(creds)
    except Exception as e:
        st.error(f"❌ Google Sheets 연결 오류: {e}")
        st.stop()

def get_worksheet(sheet_name, headers=None):
    gc = get_sheets_client()
    sh = gc.open(SPREADSHEET_TITLE)
    try:
        return sh.worksheet(sheet_name)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=sheet_name, rows=2000, cols=30)
        if headers:
            ws.append_row(headers)
        return ws

def load_questions():
    ws = get_worksheet(QNA_TAB)
    rows = ws.get_all_records()
    if not rows:
        raise RuntimeError("QNA 탭에 문항이 없습니다.")
    items = []
    for r in rows:
        items.append({k: str(r.get(k, "")).strip() for k in [
            "id", "성취기준", "차시그룹", "문항유형", "질문", "정답", "허용답",
            "피드백", "힌트", "차시명", "학습요소", "오개념"
        ]})
    return items

def save_to_sheet(sheet_name, headers, data):
    try:
        ws = get_worksheet(sheet_name, headers)
        ws.append_row(data)
    except Exception as e:
        st.toast(f"⚠️ 저장 오류: {e}", icon="⚠️")

# ==================== 텍스트 정규화 ====================
HANGUL_NUM = {
    '1':'일', '2':'이', '3':'삼', '4':'사', '5':'오', '6':'육', '7':'칠', '8':'팔', '9':'구',
    '10':'십', '20':'이십', '30':'삼십', '40':'사십', '50':'오십', '60':'육십', '70':'칠십',
    '80':'팔십', '90':'구십', '100':'백', '120':'백이십', '150':'백오십', '180':'백팔십'
}

def clean_text(s):
    if not s:
        return ""
    s = s.lower().strip()
    
    # 한글 숫자 변환
    for num, han in HANGUL_NUM.items():
        s = s.replace(han, num)
    
    # 단위 통일 (띄어쓰기도 처리)
    s = s.replace("m / s", "m/s")
    s = s.replace("km / h", "km/h")
    s = s.replace("m/초", "m/s")
    s = s.replace("km/시간", "km/h")
    s = s.replace("킬로미터", "km").replace("미터", "m")
    s = s.replace("시간", "h").replace("초", "s")
    s = s.replace("매시", "/h").replace("매s", "/s")
    s = s.replace("매", "/").replace("당", "/")
    s = s.replace("시속", "").replace("초속", "")
    
    # 공백/조사 제거
    s = re.sub(r'\s+', '', s)
    for particle in ["이", "가", "을", "를", "은", "는", "와", "과"]:
        s = s.replace(particle, "")
    
    return re.sub(r'/+', '/', s)

def parse_allowed(s):
    return [p.strip() for p in re.split(r"[|,]", s) if p.strip()] if s else []

def similarity_score(s1, s2):
    s1, s2 = clean_text(s1), clean_text(s2)
    if not s1 or not s2:
        return 0.0
    if s1 == s2:
        return 1.0
    if s2 in s1:
        return 0.95
    if s1 in s2:
        return (len(s1) / len(s2)) * 0.9
    set1, set2 = set(s1), set(s2)
    common = len(set1 & set2)
    total = len(set1 | set2)
    return common / total if total > 0 else 0.0

# ==================== 안전한 JSON 파싱 ====================
def safe_json_loads(txt, fallback=None):
    """안전한 JSON 파싱"""
    fallback = fallback or {"is_correct": False}
    attempts = [
        lambda: json.loads(txt),
        lambda: json.loads(txt[txt.find("{"):txt.rfind("}")+1]),
        lambda: json.loads(re.search(r'\{[^{}]*\}', txt).group(0))
    ]
    for attempt in attempts:
        try:
            return attempt()
        except:
            continue
    return fallback

# ==================== 정답 판정 ====================
def rule_match(ans, correct, allowed, qid=""):
    """규칙 기반 정답 판정"""
    if not ans:
        return False
    ca = clean_text(ans)
    tgt = [clean_text(correct)] if correct else []
    tgt += [clean_text(x) for x in parse_allowed(allowed)]

    # 예외 처리
    if qid == "2-1":
        if ("거리" in ca and "시간" in ca):
            if ca.find("거리") < ca.find("시간"):
                return True
        return False
    if qid == "2-8":
        if ("1초" in ans or "초당" in ans or "초에" in ans) and ("1m" in ca or "미터" in ans):
            return True

    if ca in set(tgt):
        return True
    for target in tgt:
        if similarity_score(ans, target) >= 0.85:
            return True
    return False

def check_correct(item, ans):
    """정답 확인 - GPT 유연 판단"""
    qtext = item.get('변형', item['질문'])
    needs_reason = any(k in qtext for k in ["이유를 쓰", "이유도", "왜 그런지", "근거를 쓰", "이유는"])
    
    # rule_match로 빠른 정답 판정 (확실한 경우만)
    if rule_match(ans, item['정답'], item['허용답'], qid=item['id']):
        if needs_reason:
            # 이유가 있는지 간단히 체크
            has_reason = re.search(r"(때문|왜냐|그래서|라서|므로|해서)", ans)
            has_key_concept = any(k in ans for k in [
                "시간", "짧", "빠르", "빨리", "느리", "빠름",
                "거리", "멀", "이동", "도착", "먼저", "늦"
            ])
            
            # 확실히 이유가 있으면 바로 정답
            if has_reason or has_key_concept or len(ans.strip()) >= 15:
                return True
            # 애매하면 GPT에게 물어보기 (차단하지 않음!)
        else:
            # 이유 불필요 문제는 바로 정답
            return True
    
    # rule_match 실패하거나 이유가 애매한 경우 → GPT 판단
    sys = (
        "너는 초등 5학년 과학 선생님이다. "
        "학생 답이 정답과 의미상 같은지 판단해. "
        "\n"
        "**[이유 판단 규칙]**\n"
        "- 문제에서 '이유를 쓰시오'를 요구한 경우:\n"
        "  1. 학생이 정답을 선택/입력했는지 확인\n"
        "  2. 이유가 논리적으로 타당한지 확인\n"
        "  3. 이유가 문제와 관련있는지 확인\n"
        "  4. 이유 표현이 짧거나 간결해도 의미가 통하면 인정\n"
        "  예시: '빨리 도착', '시간 짧음', '거리 멀어서' 등 모두 인정\n"
        "\n"
        "**[오답 케이스]**\n"
        "- 이유를 요구했는데 답만 쓴 경우 (예: 'C', '자전거'만)\n"
        "- 이유가 문제와 완전히 무관한 경우 (예: '색깔 예쁨')\n"
        "- 논리적으로 완전히 틀린 경우\n"
        "\n"
        "**중요: '거리/시간'과 '시간/거리'는 완전히 다르다. 순서가 바뀌면 틀린 것이다.**\n"
        "\n"
        "JSON만 출력: {\"is_correct\": true/false}"
    )
    usr = f"""
[문제] {qtext}
[정답] {item['정답']}
[허용답] {item.get('허용답','')}
[학생 답] {ans}
"""
    try:
        txt = gpt([{"role":"system","content":sys}, {"role":"user","content":usr}], temp=0.1)
        res = safe_json_loads(txt, {"is_correct": False})
        return bool(res.get("is_correct", False))
    except:
        return False

# ==================== 피드백 생성 ====================
def generate_feedback(mode, is_correct, attempts, item=None, ans=None):
    """모드에 따라 다른 피드백 생성"""
    if mode == "assessment":
        if is_correct:
            praises = [
                "정답이에요! 👏",
                "맞았어요! 🌟",
                "잘했어요! ✨",
                "훌륭해요! 💫"
            ]
            return random.choice(praises)
        else:
            if attempts == 1:
                return "다시 생각해볼까요? 😊"
            elif attempts == 2:
                return "조금만 더 생각해봐! 💪"
            else:
                return "괜찮아요. 다음 문제로 가요! 🌱"
    
    else:  # practice 모드
        if is_correct:
            sys = "초등 5학년 과학 선생님. 정답을 맞춘 학생을 칭찬해. 2-3문장, 이모지 1-2개."
            usr = f"학생이 {attempts}번 만에 정답을 맞췄어요. 칭찬해주세요."
        else:
            sys = (
                "초등 5학년 과학 선생님. "
                "틀린 학생에게 교육적 힌트를 제공해. "
                "정답을 직접 말하지 말고 소크라테스식 질문으로 유도. "
                "2-3문장, 이모지 1-2개."
            )
            usr = f"""
[문제] {item.get('변형', item['질문'])}
[정답] {item['정답']}
[학생 답] {ans}
[시도 횟수] {attempts}회

힌트를 주세요.
"""
        try:
            return gpt([{"role":"system","content":sys}, {"role":"user","content":usr}], temp=0.7)
        except:
            return "계속 도전해봐요! 😊" if not is_correct else "잘했어요! 🌟"

# ==================== 숫자 변형 ====================
def generate_variant(item):
    """GPT로 문제의 숫자를 변형하고 정답도 함께 계산"""
    qtext = item['질문']
    qtype = item.get('문항유형', '')
    original_answer = item.get('정답', '')
    
    if any(k in qtext for k in ['읽', '이 ', '그 ', '다음 ', '위 ', '아래 ', '표', '그림']):
        return qtext, original_answer
    if qtype == '선다':
        return qtext, original_answer
    
    if not re.search(r'\d+', qtext):
        return qtext, original_answer
    
    sys = (
        "너는 초등 5학년 과학 문제 출제자다. "
        "주어진 문제의 숫자만 변형하되, 다음 규칙을 **반드시** 지켜라:\n\n"
        "1. 문제의 맥락과 난이도는 유지\n"
        "2. **중요: 속력 계산 문제는 (거리 ÷ 시간)이 자연수가 되도록 숫자 설정**\n"
        "3. 숫자는 초등학생이 계산하기 쉬운 범위 (1~200)\n"
        "4. 시간 단위는 1~10 사이의 자연수\n"
        "5. JSON 형식으로 출력:\n"
        '   {"question": "변형된 문제", "answer": "새로운 정답"}\n\n'
        "**검증:**\n"
        "- 계산 문제는 answer에 계산 결과를 정확히 포함 (단위 포함)\n"
        "- 비계산 문제는 answer를 원본 정답 그대로 유지"
    )
    
    usr = f"""
원본 문제: {qtext}
원본 정답: {original_answer}

위 문제의 숫자를 변형하고, 계산 문제라면 새로운 정답도 함께 계산하세요.
"""
    
    try:
        response = gpt([{"role":"system","content":sys}, {"role":"user","content":usr}], temp=0.7)
        result = safe_json_loads(response, {"question": qtext, "answer": original_answer})
        
        variant_q = result.get("question", qtext).strip()
        variant_a = result.get("answer", original_answer).strip()
        
        original_numbers = re.findall(r'\d+', qtext)
        variant_numbers = re.findall(r'\d+', variant_q)
        
        if original_numbers == variant_numbers:
            return qtext, original_answer
        
        return variant_q, variant_a
    except Exception:
        return qtext, original_answer

# ==================== 범위 판단 ====================
def build_scope_keywords(items, group_name):
    """범위 키워드 구축"""
    kws = set()
    fields = ['성취기준','차시명','학습요소','질문']
    base = {"운동","빠르","느리","이동","거리","시간","속력","속도",
            "안전","교통","에어백","안전띠","과속","m/s","km/h","동물"}
    
    for it in items:
        if it.get('차시그룹') == group_name:
            for field in fields:
                txt = (it.get(field,'') or '').lower()
                kws.update(w for w in re.findall(r'[가-힣a-zA-Z0-9/]+', txt) if len(w) >= 2)
    return kws | base

def is_off_topic(msg: str, scope_keywords: set, group_name: str = "") -> bool:
    """GPT로 범위 외 질문 판단"""
    if not group_name:
        return False
    
    low = msg.lower()
    scope_count = sum(1 for kw in scope_keywords if kw in low)
    if scope_count >= 3:
        return False
    
    sys = (
        f"너는 초등학교 5학년 과학 '{group_name}' 단원만 가르치는 선생님이다.\n\n"
        "학습 내용: 물체의 운동, 속력, 안전\n\n"
        "**엄격한 기준:**\n"
        "1. 물체의 운동, 속력 계산, 교통안전과 **직접** 관련된 질문만 on_topic\n"
        "2. 다음은 **무조건 off_topic**:\n"
        "   - 음식, 식사, 간식 추천 (예: 점심메뉴, 빠르게 먹기)\n"
        "   - 날씨, 게임, 친구, 일상 추천\n"
        "3. '빠르게', '이동' 단어가 있어도 음식/일상이면 off_topic\n\n"
        "**예시:**\n"
        "- '점심메뉴 추천' → off_topic\n"
        "- '빠르게 이동하는 간식' → off_topic (간식=음식)\n"
        "- '속력은 어떻게 구해?' → on_topic\n"
        "- '가장 빠른 동물은?' → on_topic\n\n"
        "JSON만 출력: {\"on_topic\": true/false}"
    )
    usr = f"학생 질문: {msg}"
    
    try:
        txt = gpt([{"role":"system","content":sys}, {"role":"user","content":usr}], temp=0.1)
        res = safe_json_loads(txt, {"on_topic": True})
        return not res.get("on_topic", True)
    except:
        return False

# ==================== 메타인지 평가 ====================
def evaluate_metacog_answer(objective, question, student_answer):
    """학생의 메타인지 답변을 GPT로 평가"""
    is_movement_question = "운동하는 물체의 특징" in question
    is_unit_question = "속력의 단위" in question
    sys = (
        "너는 초등 5학년 과학 선생님이다. "
        "학생이 자기 언어로 개념을 설명한 답변을 평가해.\n\n"
        "**평가 기준:**\n"
        "1. 핵심 개념 포함 여부 (거리, 시간, 속력 관계 등)\n"
        "2. 논리적으로 맞는지\n"
        "3. 오개념 유무\n\n"
        "**중요:**\n"
        "- 답변이 짧아도 핵심 개념이 정확하면 excellent로 평가\n"
        "- 예시: '거리/시간', '위치가 변한다' 등 간결한 답도 충분함\n"
        "- 정답을 맞춘 학생에게 불필요한 예시나 추가 설명을 요구하지 말 것\n\n"
        "**needs_more = true 조건:**\n"
        "- 핵심 개념이 빠졌거나\n"
        "- 설명이 애매하거나\n"
        "- 논리적으로 불완전할 때만\n\n"
        "**오개념이 있으면 has_misconception: true**\n\n"
        "JSON 형식으로 출력:\n"
        "{\n"
        '  "understanding_level": "excellent/good/needs_improvement",\n'
        '  "needs_more": true/false,\n'
        '  "has_misconception": true/false,\n'
        '  "feedback": "학생에게 줄 피드백 (칭찬 위주, 1-2문장, 이모지 포함)"\n'
        "}"
    )
    
    # 운동하는 물체의 특징 질문에 대한 특별 지침 추가
    if is_movement_question:
        sys += (
            "\n**특별 지침 (운동하는 물체의 특징 질문):**\n"
            "- '거리가 변한다', '위치가 바뀐다', '장소가 달라진다', '이동한다' 등의 표현이 있으면 excellent\n"
            "- 간단하게 위치/거리 변화를 언급하면 충분함\n"
            "- 복잡한 설명을 요구하지 말 것\n"
        )
    
    # 속력의 단위 질문에 대한 특별 지침 추가
    if is_unit_question:
        sys += (
            "\n**특별 지침 (속력의 단위 질문):**\n"
            "- 'km/h' 또는 'm/s' 중 하나만 언급해도 excellent\n"
            "- 둘 다 언급하면 더 좋지만, 하나만 써도 충분함\n"
            "- 피드백에서 다른 단위도 있다는 걸 간단히 언급 (예: 'm/s도 있어요')\n"
        )

    usr = f"""
[성취기준] {objective}
[질문] {question}
[학생 답변] {student_answer}

학생의 이해도를 평가하고 피드백을 작성하세요.
"""
    
    try:
        response = gpt([{"role":"system","content":sys}, {"role":"user","content":usr}], temp=0.3)
        result = safe_json_loads(response, {
            "understanding_level": "needs_improvement",
            "needs_more": True,
            "has_misconception": False,
            "feedback": "조금 더 자세히 설명해볼까요? 😊"
        })
        return result
    except:
        return {
            "understanding_level": "needs_improvement",
            "needs_more": True,
            "has_misconception": False,
            "feedback": "조금 더 자세히 설명해볼까요? 😊"
        }

# ==================== Streamlit UI ====================
# ==================== Streamlit UI ====================
st.set_page_config(
    page_title="🔬 5학년 과학 평가", 
    layout="centered",
    page_icon="🔬",
    initial_sidebar_state="expanded"
)

# 초등학생 친화적 디자인
st.markdown("""
    <style>
    /* 전체 배경 - 부드러운 그라데이션 */
    .main {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        background-attachment: fixed;
    }
    
    /* 컨텐츠 영역 - 흰색 카드 느낌 */
    .block-container {
        background-color: white;
        border-radius: 20px;
        padding: 2rem;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
    }
    
    /* 제목 스타일 */
    h1 {
        color: #667eea;
        text-align: center;
        font-size: 2.5rem !important;
        padding: 20px;
        background: linear-gradient(90deg, #667eea, #764ba2);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-weight: bold;
    }
    
    /* 버튼 스타일 - 크고 둥글게 */
    .stButton>button {
        background: linear-gradient(90deg, #667eea, #764ba2);
        color: white;
        border-radius: 25px;
        padding: 15px 30px;
        font-size: 18px;
        font-weight: bold;
        border: none;
        box-shadow: 0 4px 15px rgba(102, 126, 234, 0.4);
        transition: all 0.3s;
    }
    
    .stButton>button:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 20px rgba(102, 126, 234, 0.6);
    }
    
    /* 입력창 스타일 */
    .stTextInput>div>div>input, .stSelectbox>div>div>select, .stNumberInput>div>div>input {
        border-radius: 15px;
        border: 2px solid #667eea;
        padding: 10px;
        font-size: 16px;
    }
    
    /* 챗봇 메시지 애니메이션 */
    .stChatMessage {
        border-radius: 15px;
        padding: 15px;
        margin: 10px 0;
        animation: slideIn 0.3s ease-out;
    }
    
    @keyframes slideIn {
        from {
            opacity: 0;
            transform: translateY(10px);
        }
        to {
            opacity: 1;
            transform: translateY(0);
        }
    }
    
    /* 사이드바 스타일 */
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #667eea 0%, #764ba2 100%);
    }
    
    [data-testid="stSidebar"] * {
        color: white !important;
    }
    
    /* 구분선 */
    hr {
        border: none;
        height: 2px;
        background: linear-gradient(90deg, #667eea, #764ba2);
        margin: 20px 0;
    }
    </style>
""", unsafe_allow_html=True)

# 제목
st.markdown("""
    <h1>
        🔬 5학년 과학 – 물체의 운동 🚀
    </h1>
""", unsafe_allow_html=True)

def S(k, v):
    if k not in st.session_state:
        st.session_state[k] = v
    return st.session_state[k]

def init_session():
    st.session_state.mode = "idle"
    st.session_state.phase = "assessment"
    st.session_state.plan = []
    st.session_state.current = None
    st.session_state.attempts = 0
    st.session_state.messages = []
    st.session_state.assessment_log = []
    st.session_state.practice_log = []
    st.session_state.weak_objectives = []
    st.session_state.unit_asked = False
    st.session_state.reason_asked = False 
    st.session_state.scope_keywords = set()
    st.session_state.input_counter = 0
    st.session_state.ignore_next_input = False
    st.session_state.practice_result_shown = False
    st.session_state.metacog_objectives = []
    st.session_state.metacog_current_obj = None
    st.session_state.metacog_current_q_idx = 0
    st.session_state.metacog_responses = []
    st.session_state.metacog_retry_count = 0

S("student", "")
S("student_class", "1반")
S("student_number", "")
S("group", None)
S("n_per_topic", 3)
S("mode", "idle")
S("phase", "assessment")
S("plan", [])
S("current", None)
S("attempts", 0)
S("messages", [])
S("assessment_log", [])
S("practice_log", [])
S("weak_objectives", [])
S("unit_asked", False)
S("reason_asked", False)
S("scope_keywords", set())
S("input_counter", 0)
S("ignore_next_input", False)
S("practice_result_shown", False)
S("metacog_objectives", [])
S("metacog_current_obj", None)
S("metacog_current_q_idx", 0)
S("metacog_responses", [])
S("metacog_retry_count", 0)

# 학생 정보 입력
st.markdown("### 👤 학생 정보")
col_name, col_class, col_num = st.columns([2, 1, 1])

with col_name:
    st.session_state.student = st.text_input("이름", value=st.session_state.student,
                                             placeholder="예: 김가람", key="name")
with col_class:
    st.session_state.student_class = st.selectbox("반", ["1반", "2반", "3반"],
                                                   index=["1반", "2반", "3반"].index(st.session_state.student_class) if st.session_state.student_class in ["1반", "2반", "3반"] else 0,
                                                   key="class_select")
with col_num:
    student_num = st.text_input("번호", value=st.session_state.student_number,
                                placeholder="1", key="num", max_chars=2)
    if student_num and not student_num.isdigit():
        st.error("숫자만 입력하세요")
        st.session_state.student_number = ""
    else:
        st.session_state.student_number = student_num

st.markdown("---")

col1, col2 = st.columns([2,1])

try:
    all_items = load_questions()
    q_bank = {}
    for it in all_items:
        grp = it['차시그룹'] or "기타"
        q_bank.setdefault(grp, []).append(it)
    choices = ["-- 선택 --"] + list(q_bank.keys())
except Exception as e:
    st.error(f"문항 로드 오류: {e}")
    st.stop()

with col1:
    group_sel = st.selectbox("차시 묶음", choices, key="grp")
with col2:
    st.number_input("문항 수", 1, 10, key="n_per_topic")

def push(role, content):
    st.session_state.messages.append({"role":role, "content":content})
    with st.chat_message(role):
        st.markdown(content)

for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])

def get_level(attempts, correct):
    """시도 횟수와 정답 여부로 레벨 판정"""
    if not correct:
        return "노력요함"
    return {1: "잘함", 2: "보통"}.get(attempts, "노력요함")

def next_question():
    """다음 문제 출제"""
    if not st.session_state.plan:
        if st.session_state.phase == "assessment":
            st.session_state.mode = "show_diagnosis"
            st.session_state.ignore_next_input = True
        elif st.session_state.phase == "practice":
            st.session_state.mode = "practice_done"
            st.session_state.practice_result_shown = False
            st.session_state.ignore_next_input = True
        return

    base = dict(st.session_state.plan.pop(0))
    
    variant_q, variant_a = generate_variant(base)
    base['변형'] = variant_q
    base['정답'] = variant_a
    
    st.session_state.current = base
    st.session_state.attempts = 0
    st.session_state.unit_asked = False
    st.session_state.reason_asked = False
    
    phase_label = "평가" if st.session_state.phase == "assessment" else "연습"
    push("assistant", f"**[{phase_label}] [{base['id']}]** {base['변형']}\n\n답을 입력해주세요!")

def evaluate(cur, ans):
    """평가 또는 연습 진행"""
    st.session_state.attempts += 1
    att = st.session_state.attempts
    phase = st.session_state.phase
    
    def has_unit_pattern(text):
        return bool(re.search(r'(?:m/s|km/h|m/초|km/시간|m|km|초|s|h|미터|킬로미터|매초|매시간)', text or "", flags=re.I))
    
    qtext = cur.get('변형', cur.get('질문', ''))
    is_calc = (cur.get('문항유형','') == '계산')
    is_reading = any(k in qtext for k in ["읽을까", "읽나요", "읽습니까", "문장으로"])
        
    # 속력 계산 문제 (키워드 + 계산 동사)
    is_speed_calc = (
        ("속력" in qtext or "속도" in qtext or "빠르기" in qtext) and
        any(verb in qtext for verb in ["구하", "계산", "구해", "몇", "얼마"])
    )
    if is_speed_calc and not is_reading:
        numbers = re.findall(r'\d+\.?\d*', ans)
        has_unit_ans = has_unit_pattern(ans)
        
        # 숫자만 있고 단위가 없는 경우
        if numbers and not has_unit_ans and not st.session_state.get('unit_asked', False):
            # 숫자만으로 정답 판별
            ans_number = numbers[0] if numbers else ""
            correct_number = re.findall(r'\d+\.?\d*', cur.get('정답', ''))
            correct_number = correct_number[0] if correct_number else ""
            
            # 숫자가 맞으면
            if ans_number == correct_number:
                st.session_state.unit_asked = True
                st.session_state.attempts -= 1
                push("assistant", f"✅ 답은 맞았어요! 단위도 함께 써주면 더 완벽해요. 단위를 함께 써볼까요?")
                return
            # 숫자도 틀렸으면 그냥 오답 처리 (아래로 계속)

    st.session_state.unit_asked = False
    # 이유 요구 문제 체크
    qtext = cur.get('변형', cur.get('질문', ''))
    needs_reason = any(k in qtext for k in ["이유를 쓰", "이유도", "왜 그런지", "근거를 쓰", "이유는"])
    
    if needs_reason and not st.session_state.get('reason_asked', False):
        ans_clean = ans.strip()
        
        # 정답과 정확히 일치하는지만 체크 (답만 입력한 경우)
        ans_upper = ans_clean.upper()
        correct_upper = cur.get('정답', '').strip().upper()
        
        # 정답과 정확히 일치
        if ans_upper == correct_upper:
            st.session_state.reason_asked = True
            st.session_state.attempts -= 1
            push("assistant", "✅ 답은 맞았어요! 이유도 함께 설명해주면 더 좋겠어요. 왜 그렇게 생각했는지 설명해볼까요?")
            return
        
        # 허용답과 정확히 일치
        allowed_list = parse_allowed(cur.get('허용답', ''))
        for allowed_ans in allowed_list:
            if ans_upper == allowed_ans.strip().upper():
                st.session_state.reason_asked = True
                st.session_state.attempts -= 1
                push("assistant", "✅ 답은 맞았어요! 이유도 함께 설명해주면 더 좋겠어요. 왜 그렇게 생각했는지 설명해볼까요?")
                return
    
    st.session_state.reason_asked = False

    is_correct = check_correct(cur, ans)
    feedback = generate_feedback(phase, is_correct, att, cur, ans)
    level = get_level(att, is_correct)
    
    log_entry = {
        "qid": cur['id'],
        "level": level,
        "correct": is_correct,
        "attempts": att,
        "question": cur['변형'],
        "user_answer": ans,
        "correct_answer": cur['정답'],
        "objective": cur['성취기준']
    }
    
    if phase == "assessment":
        st.session_state.assessment_log.append(log_entry)
    else:
        st.session_state.practice_log.append(log_entry)
    
    save_to_sheet(LOG_TAB,
                  ["ts","student","class","number","group","phase","objective","qid",
                   "question","user_answer","correct_answer","level","correct","attempts"],
                  [now_kst().isoformat(timespec="seconds"), st.session_state.student,
                   st.session_state.student_class, st.session_state.student_number,
                   st.session_state.group, phase, cur['성취기준'], cur['id'], cur['변형'], ans, cur['정답'], level, str(is_correct), att])
    
    # 다음 액션
    if is_correct:
        push("assistant", f"{feedback}\n\n다음 문제로 가요!")
        next_question()
    elif att >= 3:
        if phase == "assessment":
            push("assistant", f"{feedback}")
            next_question()
        else:
            sys = "초등 5학년 과학 선생님. 정답과 간단한 설명을 2-3문장으로. 쉬운 말로. 수식 금지."
            usr = f"[문제]{cur['변형']}\n[정답]{cur['정답']}\n설명해주세요."
            try:
                explanation = gpt([{"role":"system","content":sys}, {"role":"user","content":usr}], temp=0.3)
            except:
                explanation = ""
            push("assistant", f"💡 정답은 **{cur['정답']}** 이에요.\n\n{explanation}\n\n다음 문제로 가요!")
            next_question()
    else:
        push("assistant", f"{feedback}")
        st.session_state.mode = "asking"

# ==================== 메타인지 함수 ====================
def start_metacognition():
    """메타인지 활동 시작"""
    # 평가 결과에서 다룬 성취기준 추출
    objectives_covered = list(set(r['objective'] for r in st.session_state.assessment_log))
    
    # 메타인지 질문이 있는 성취기준만 필터링
    st.session_state.metacog_objectives = [obj for obj in objectives_covered if obj in METACOG_QUESTIONS]
    
    if not st.session_state.metacog_objectives:
        push("assistant", "🎉 모든 활동을 완료했어요! 수고했어요!")
        st.session_state.mode = "ended"
        return
    
    st.session_state.metacog_current_obj = st.session_state.metacog_objectives[0]
    st.session_state.metacog_current_q_idx = 0
    st.session_state.metacog_retry_count = 0
    st.session_state.mode = "metacognition"
    st.session_state.ignore_next_input = False
    
    push("assistant", 
         "📝 **이제 배운 내용을 나만의 언어로 정리해볼까요?**\n\n"
         "선생님이 질문하면, 여러분이 이해한 대로 자유롭게 설명해주세요! "
         "완벽하지 않아도 괜찮아요. 😊")
    
    ask_next_metacog_question()

def ask_next_metacog_question():
    """다음 메타인지 질문 제시"""
    obj = st.session_state.metacog_current_obj
    q_idx = st.session_state.metacog_current_q_idx
    questions = METACOG_QUESTIONS.get(obj, [])
    
    if q_idx >= len(questions):
        # 현재 성취기준의 모든 질문 완료
        move_to_next_objective()
        return
    
    question = questions[q_idx]
    push("assistant", f"**[{obj}]**\n\n❓ {question}")

def move_to_next_objective():
    """다음 성취기준으로 이동"""
    current_idx = st.session_state.metacog_objectives.index(st.session_state.metacog_current_obj)
    
    if current_idx + 1 < len(st.session_state.metacog_objectives):
        # 다음 성취기준으로
        st.session_state.metacog_current_obj = st.session_state.metacog_objectives[current_idx + 1]
        st.session_state.metacog_current_q_idx = 0
        st.session_state.metacog_retry_count = 0
        
        push("assistant", "좋아요! 다음 내용도 설명해볼까요? 💪")
        ask_next_metacog_question()
    else:
        # 모든 성취기준 완료
        finish_metacognition()

def finish_metacognition():
    """메타인지 활동 완료"""
    push("assistant", 
         "🎉 **모든 정리를 마쳤어요!**\n\n"
         "나만의 언어로 설명하면서 개념을 더 확실히 이해했을 거예요. "
         "정말 잘했어요! 👏✨\n\n"
         "궁금한 점이 있으면 질문해주세요. 끝내려면 '끝'이라고 입력하세요.")
    
    st.session_state.mode = "ended"

def handle_metacog_answer(ans):
    """메타인지 답변 처리"""
    obj = st.session_state.metacog_current_obj
    q_idx = st.session_state.metacog_current_q_idx
    question = METACOG_QUESTIONS[obj][q_idx]
    
    # GPT 평가
    evaluation = evaluate_metacog_answer(obj, question, ans)
    
    # 로그 저장
    save_to_sheet(METACOG_TAB,
                  ["ts","student","class","number","group","objective","question","answer",
                   "understanding_level","needs_more","has_misconception"],
                  [now_kst().isoformat(timespec="seconds"), st.session_state.student,
                   st.session_state.student_class, st.session_state.student_number,
                   st.session_state.group, obj, question, ans,
                   evaluation.get("understanding_level",""),
                   str(evaluation.get("needs_more",False)),
                   str(evaluation.get("has_misconception",False))])
    
    st.session_state.metacog_responses.append({
        "objective": obj,
        "question": question,
        "answer": ans,
        "evaluation": evaluation
    })
    
    feedback = evaluation.get("feedback", "좋아요! 😊")
    needs_more = evaluation.get("needs_more", False)
    has_misconception = evaluation.get("has_misconception", False)
    
    if has_misconception:
        # 오개념이 있으면 교정 후 재시도
        push("assistant", f"{feedback}\n\n다시 한 번 설명해볼까요?")
        st.session_state.metacog_retry_count += 1
        if st.session_state.metacog_retry_count >= 2:
            # 2번 재시도해도 안되면 넘어감
            push("assistant", "괜찮아요! 다음 질문으로 가볼까요? 😊")
            st.session_state.metacog_current_q_idx += 1
            st.session_state.metacog_retry_count = 0
            ask_next_metacog_question()
    elif needs_more:
        # 더 자세한 설명 필요
        push("assistant", f"{feedback}")
        st.session_state.metacog_retry_count += 1
        if st.session_state.metacog_retry_count >= 2:
            push("assistant", "이 정도면 충분해요! 다음으로 가요! 👍")
            st.session_state.metacog_current_q_idx += 1
            st.session_state.metacog_retry_count = 0
            ask_next_metacog_question()
    else:
        # 잘 설명함
        push("assistant", f"{feedback}\n\n다음 질문으로 가요!")
        st.session_state.metacog_current_q_idx += 1
        st.session_state.metacog_retry_count = 0
        ask_next_metacog_question()

# 평가 시작
# 평가 시작 - 초기 상태일 때만 표시
if st.session_state.mode == "idle":
    if st.button("평가 시작", key="start"):
        if not st.session_state.student.strip():
            st.error("❌ 이름을 입력해주세요!")
        elif not st.session_state.student_number.strip():
            st.error("❌ 번호를 입력해주세요!")
        elif group_sel == "-- 선택 --":
            st.warning("차시 묶음을 먼저 선택하세요.")
        else:
            init_session()
            base = q_bank[group_sel][:]
            n_items = int(st.session_state.n_per_topic)
            
            by_type = {}
            for item in base:
                qtype = item.get('문항유형', '기타')
                by_type.setdefault(qtype, []).append(item)
            
            selected = []
            type_list = list(by_type.keys())
            random.shuffle(type_list)
            type_idx = 0
            attempts = 0
            max_attempts = n_items * len(type_list)
            
            while len(selected) < n_items and attempts < max_attempts:
                current_type = type_list[type_idx % len(type_list)]
                if by_type[current_type]:
                    available = [q for q in by_type[current_type] if q not in selected]
                    if available:
                        selected.append(random.choice(available))
                type_idx += 1
                attempts += 1
            
            if len(selected) < n_items:
                remaining = [q for q in base if q not in selected]
                random.shuffle(remaining)
                selected.extend(remaining[:n_items - len(selected)])
            
            st.session_state.plan = selected
            st.session_state.group = group_sel
            st.session_state.scope_keywords = build_scope_keywords(all_items, group_sel)
            st.session_state.phase = "assessment"
            st.session_state.mode = "asking"
            
            student_info = f"{st.session_state.student}({st.session_state.student_class} {st.session_state.student_number}번)"
            push("assistant", f"🔬 {student_info} 학생, **평가**를 시작합니다!\n\n{st.session_state.group} 범위에서 {n_items}문항을 풀어요.")
            next_question()

# ==================== 입력 처리 ====================
user_msg = st.chat_input("여기에 입력…", key=f"input_{st.session_state.input_counter}")

if user_msg:
    if st.session_state.get("ignore_next_input", False):
        st.session_state.ignore_next_input = False
        st.session_state.input_counter += 1
        st.rerun()
    else:
        mode = st.session_state.mode
        cur = st.session_state.current
        
        if mode == "asking" and cur:
            push("user", user_msg)
            evaluate(cur, user_msg)
        
        elif mode == "show_diagnosis":
            pass
        
        elif mode == "await_practice_decision":
            if user_msg.strip().isdigit() and len(user_msg.strip()) <= 2:
                pass
            elif any(t in user_msg.lower() for t in ["없어요","끝","그만","아니"]):
                push("user", user_msg)
                # 평가만 하고 종료하는 경우에도 메타인지는 필수
                start_metacognition()
            elif "연습" in user_msg:
                push("user", user_msg)
                weak_objs = st.session_state.get("weak_objectives", [])
                if weak_objs:
                    all_items = load_questions()
                    solved_qids = set(r['qid'] for r in st.session_state.assessment_log)
                    practice_items = [
                        it for it in all_items 
                        if it['성취기준'] in weak_objs and it['id'] not in solved_qids
                    ]
                    if practice_items:
                        random.shuffle(practice_items)
                        st.session_state.plan = practice_items[:3]
                        st.session_state.phase = "practice"
                        st.session_state.mode = "asking"
                        st.session_state.attempts = 0
                        push("assistant", "좋아요! 부족한 부분을 연습해봅시다! 💪")
                        next_question()
                    else:
                        push("assistant", "연습 문제를 준비 중이에요. 다른 질문이 있나요?")
                else:
                    push("assistant", "이미 모든 내용을 잘 이해했어요! 다른 질문이 있나요?")
            else:
                push("user", user_msg)
                group_name = st.session_state.get('group', '물체의 운동')
                scope_keywords = st.session_state.get("scope_keywords", set())
                
                if is_off_topic(user_msg, scope_keywords, group_name):
                    push("assistant", f"저는 5학년 과학 '{group_name}' 범위를 도와주는 챗봇이에요 🙂\n오늘 범위와 관련된 질문을 해주세요!")
                else:
                    sys = "초등 5학년 과학 선생님. 친절하고 간결하게. 쉬운 말로."
                    try:
                        ans = gpt([{"role":"system","content":sys},
                                  {"role":"user","content":f"[범위]{st.session_state.group}\n[질문]{user_msg}"}], 0.3)
                        push("assistant", ans)
                        save_to_sheet(FOLLOWUP_TAB, ["ts","student","class","number","group","question","answer"],
                                     [now_kst().isoformat(timespec="seconds"), st.session_state.student,
                                      st.session_state.student_class, st.session_state.student_number,
                                      st.session_state.group, user_msg, ans])
                    except Exception:
                        push("assistant", "죄송해요, 오류가 발생했어요.")
        
        elif mode == "practice_done":
            if user_msg.strip().isdigit() and len(user_msg.strip()) <= 2:
                pass
            elif any(t in user_msg.lower() for t in ["없어요","끝","그만","아니"]):
                push("user", user_msg)
                # 연습 후에는 반드시 메타인지
                start_metacognition()
            else:
                push("user", user_msg)
                group_name = st.session_state.get('group', '물체의 운동')
                scope_keywords = st.session_state.get("scope_keywords", set())
                
                if is_off_topic(user_msg, scope_keywords, group_name):
                    push("assistant", f"저는 5학년 과학 '{group_name}' 범위를 도와주는 챗봇이에요 🙂\n오늘 범위와 관련된 질문을 해주세요!")
                else:
                    sys = "초등 5학년 과학 선생님. 친절하고 간결하게. 쉬운 말로."
                    try:
                        ans = gpt([{"role":"system","content":sys},
                                  {"role":"user","content":f"[범위]{st.session_state.group}\n[질문]{user_msg}"}], 0.3)
                        push("assistant", ans)
                        save_to_sheet(FOLLOWUP_TAB, ["ts","student","class","number","group","question","answer"],
                                     [now_kst().isoformat(timespec="seconds"), st.session_state.student,
                                      st.session_state.student_class, st.session_state.student_number,
                                      st.session_state.group, user_msg, ans])
                    except Exception:
                        push("assistant", "죄송해요, 오류가 발생했어요.")
        
        elif mode == "metacognition":
            # 메타인지 답변 처리
            push("user", user_msg)
            handle_metacog_answer(user_msg)

        elif mode == "ended":
            # 종료 상태에서도 추가 질문 받기
            if user_msg.strip().isdigit() and len(user_msg.strip()) <= 2:
                pass
            elif any(t in user_msg.lower() for t in ["끝","종료","그만"]):
                push("user", user_msg)
                push("assistant", "👋 정말 수고했어요! 안녕!")
            else:
                push("user", user_msg)
                group_name = st.session_state.get('group', '물체의 운동')
                scope_keywords = st.session_state.get("scope_keywords", set())
                
                if is_off_topic(user_msg, scope_keywords, group_name):
                    push("assistant", f"저는 5학년 과학 '{group_name}' 범위를 도와주는 챗봇이에요 🙂\n오늘 범위와 관련된 질문을 해주세요!")
                else:
                    sys = "초등 5학년 과학 선생님. 친절하고 간결하게. 쉬운 말로."
                    try:
                        ans = gpt([{"role":"system","content":sys},
                                  {"role":"user","content":f"[범위]{st.session_state.group}\n[질문]{user_msg}"}], 0.3)
                        push("assistant", ans)
                        save_to_sheet(FOLLOWUP_TAB, ["ts","student","class","number","group","question","answer"],
                                     [now_kst().isoformat(timespec="seconds"), st.session_state.student,
                                      st.session_state.student_class, st.session_state.student_number,
                                      st.session_state.group, user_msg, ans])
                    except Exception:
                        push("assistant", "죄송해요, 오류가 발생했어요.")

# ==================== 진단 결과 표시 ====================
if st.session_state.mode == "show_diagnosis":
    score = {"잘함":2, "보통":1, "노력요함":0}
    last = {r['qid']:r for r in st.session_state.assessment_log}
    
    if not last:
        st.warning("결과가 없습니다.")
        st.stop()
    
    avg = sum(score[last[q]['level']] for q in last) / len(last)
    overall = "잘함" if avg >= 1.5 else ("보통" if avg >= 0.75 else "노력요함")
    
    push("assistant", f"**📊 평가 종료! 종합 판정: {overall}**")
    
    answer_sheet = "**📋 정오표**\n\n"
    for qid in sorted(last.keys()):
        rec = last[qid]
        emoji = "✅" if rec['correct'] else "❌"
        answer_sheet += f"{emoji} **[{qid}]** {rec['level']} ({rec['attempts']}회)\n"
        answer_sheet += f"   문제: {rec['question']}\n"
        answer_sheet += f"   학생 답: {rec['user_answer']}\n"
        answer_sheet += f"   정답: {rec['correct_answer']}\n\n"
    
    push("assistant", answer_sheet)
    
    by_objective = {}
    for rec in last.values():
        obj = rec['objective']
        by_objective.setdefault(obj, []).append(rec['level'])
    
    weak_objectives = []
    analysis_text = "**🎯 성취기준별 분석**\n\n"
    for obj, levels in by_objective.items():
        obj_avg = sum(score[l] for l in levels) / len(levels)
        obj_status = "잘함" if obj_avg >= 1.5 else ("보통" if obj_avg >= 0.75 else "노력요함")
        obj_emoji = LEVEL_EMOJI[obj_status]
        analysis_text += f"{obj_emoji} **{obj}**: {obj_status} ({len(levels)}문항)\n"
        if obj_status in ["보통", "노력요함"]:
            weak_objectives.append(obj)
    
    push("assistant", analysis_text)
    
    if weak_objectives:
        weak_questions = []
        for rec in last.values():
            if rec['objective'] in weak_objectives:
                weak_questions.append(f"- [{rec['qid']}] {rec['question']}")
        
        sys = (
            "초등 5학년 과학 선생님. "
            "**실제 출제된 문제들을 보고** 해당 단원의 학습 조언 제공. "
            "문제들에서 다루는 주제를 파악해서 맞춤형 피드백 작성.\n"
            "각 성취기준마다:\n"
            "1. 출제된 문제 내용 기반 핵심 개념 설명 (2-3문장, 쉬운 말로)\n"
            "2. 집에서 할 수 있는 활동 제안 (1개)\n"
            "이모지 사용, 친근한 말투. 엉뚱한 단원 설명 금지!"
        )
        usr = f"""
부족한 성취기준:
{chr(10).join([f"- {obj}" for obj in weak_objectives])}

실제 출제된 문제들:
{chr(10).join(weak_questions)}

**위 문제들의 주제(교통안전, 속력, 운동 등)를 정확히 파악하고** 그에 맞는 학습 피드백을 작성하세요.
절대로 다른 단원(지구, 식물, 동물 분류 등) 내용을 쓰지 마세요!
"""
        try:
            learning_feedback = gpt([{"role":"system","content":sys}, {"role":"user","content":usr}], temp=0.5)
            push("assistant", f"**💡 학습 피드백**\n\n{learning_feedback}")
        except:
            pass
        
        push("assistant",
             "**📚 연습 문제를 풀어볼까요?**\n\n"
             "연습 문제를 풀고 싶으면 '연습'이라고 입력하세요.\n"
             "연습 없이 바로 정리하고 싶으면 '끝'이라고 입력하세요.")
    else:
        push("assistant",
             "모든 성취기준을 잘 이해했어요! 👏\n\n"
             "이제 배운 내용을 정리해볼까요? '끝'이라고 입력하면 정리를 시작할게요!")
    
    st.session_state.weak_objectives = weak_objectives
    st.session_state.mode = "await_practice_decision"
    st.session_state.ignore_next_input = False  # 플래그 해제

    save_to_sheet(SUMMARY_TAB, ["ts","student","class","number","group","overall"],
                 [now_kst().isoformat(timespec="seconds"), st.session_state.student,
                  st.session_state.student_class, st.session_state.student_number,
                  st.session_state.group, overall])

# ==================== 연습 완료 ====================
if st.session_state.mode == "practice_done":
    if not st.session_state.get("practice_result_shown", False):
        practice_summary = {}
        for rec in st.session_state.practice_log:
            practice_summary[rec['qid']] = rec
        
        practice_results = "**📊 연습 결과**\n\n"
        for qid in sorted(practice_summary.keys()):
            rec = practice_summary[qid]
            emoji = LEVEL_EMOJI.get(rec['level'], "➖")
            practice_results += f"{emoji} **[{qid}] {rec['level']}** ({rec['attempts']}회)\n"
        
        push("assistant", practice_results + "\n\n연습을 모두 마쳤어요! 잘했어요! 👏\n\n이제 배운 내용을 정리해볼까요? '끝'이라고 입력하면 시작할게요!")
        st.session_state.practice_result_shown = True

with st.sidebar:
    st.markdown("### 🚀 나의 학습 여정")
    
    current_phase = st.session_state.phase
    current_mode = st.session_state.mode
    
    # 이모지로 단계 표시
    steps = {
        "assessment": ("🔍", "실력 확인", "내가 얼마나 알고 있을까?"),
        "practice": ("📚", "더 연습", "조금만 더 힘내자!"),
        "metacognition": ("✏️", "스스로 정리", "내 말로 설명해보기!")
    }
    
    # 단계별 표시
    for i, (key, (emoji, title, desc)) in enumerate(steps.items(), 1):
        if current_phase == key or (key == "metacognition" and current_mode == "metacognition"):
            # 현재 단계
            st.markdown(f"### {i}. {emoji} {title}")
            st.success(f"← **지금 여기!**\n\n*{desc}*")
        elif (key == "assessment" and current_phase in ["practice", "metacognition"]) or \
             (key == "practice" and current_mode == "metacognition"):
            # 완료한 단계
            st.markdown(f"~~{i}. {emoji} {title}~~ ✅")
        else:
            # 아직 안 한 단계
            st.markdown(f"{i}. {emoji} {title}")
    
    # 완료 시
    if current_mode == "ended":
        st.markdown("---")
        # st.balloons()
        st.success("### 🎉 모든 단계 완료!\n\n정말 잘했어요! 👏")
    
    st.markdown("---")
    
    # 진행률
    if st.session_state.mode == "asking" and st.session_state.plan:
        total = st.session_state.n_per_topic
        remaining = len(st.session_state.plan)
        completed = total - remaining
        progress = completed / total if total > 0 else 0
        
        st.progress(progress)
        st.write(f"🎯 **{completed}**개 완료 / 전체 **{total}**개")
    
    st.markdown("---")

    st.info("💡 **선생님 팁**\n\n천천히, 차근차근 생각하면서 풀어봐요!")

















