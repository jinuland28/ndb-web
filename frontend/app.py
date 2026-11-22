# -*- coding: utf-8 -*-
r"""생활시설 유지 위험 조기 진단 화면 (Streamlit)
2단계(뼈대): 사이드바 필터 3개 + 질문 5개, 오른쪽 요약·주의 배너·2칸. 질문별 내용은 3~7단계에서 채운다
폴더 구조 (frontend 폴더는 etl 폴더와 나란히 둔다)
  엔디비 팀플/
  ├─ etl/        50_query_app.py, 51_query_f3f5f6.py, db_common.py
  ├─ figures/    fig3·fig5·fig7 그림
  ├─ results/
  └─ frontend/   app.py  ← 이 파일
규칙
  - DB 조회는 50·51번 함수와 db_common.fetch만 쓴다 (값은 Prepared Statement의 %s 로만 전달, SELECT만)
  - 비밀번호는 코드에 쓰지 않고 환경 변수 NDB_MYSQL_PW로 받는다 (Streamlit에서는 getpass 입력이 동작하지 않을 수 있음)
접속할 DB
  - 내 PC: 환경 변수 NDB_MYSQL_PW로 로컬 MySQL(db_common.connect)에 접속
  - 클라우드(Streamlit Community Cloud): Secrets의 [tidb] 항목이 있으면 TiDB Cloud에 TLS로 접속 (db_common은 고치지 않음)
실행 (frontend 폴더에서, PowerShell)
  $env:NDB_MYSQL_PW = '비밀번호'
  py -m streamlit run app.py --server.headless true --server.address localhost --server.fileWatcherType poll
"""
import importlib
import os
import sys
from pathlib import Path

import altair as alt          # Streamlit을 설치하면 함께 설치됨
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent      # 엔디비 팀플 폴더
ETL = ROOT / "etl"                                  # 50·51번 조회 함수와 db_common이 있는 곳
FIGURES = ROOT / "figures"                          # PNG 그림을 읽는 곳
sys.path.insert(0, str(ETL))

st.set_page_config(page_title="충청권 생활시설 위험 진단", layout="wide")

# ---------------------------------------------------------------- 실행 전 확인
def cloud_db():
    """클라우드 Secrets의 [tidb] 접속 정보. 내 PC처럼 secrets 파일이 없으면 None"""
    try:
        return dict(st.secrets["tidb"])
    except Exception:
        return None


CLOUD = cloud_db()
if CLOUD is None and not os.environ.get("NDB_MYSQL_PW"):
    st.error("환경 변수 NDB_MYSQL_PW가 없습니다. 터미널에서 아래처럼 설정한 뒤 다시 실행하세요.")
    st.code("$env:NDB_MYSQL_PW = '비밀번호'\npy -m streamlit run app.py --server.headless true", language="powershell")
    st.stop()

missing = [p.name for p in (ETL / "db_common.py", ETL / "50_query_app.py", ETL / "51_query_f3f5f6.py") if not p.exists()]
if missing:
    st.error(f"etl 폴더에서 {missing} 를 찾지 못했습니다. frontend 폴더를 etl 폴더와 나란히 두었는지 확인하세요. (찾은 위치: {ETL})")
    st.stop()

from db_common import connect, fetch          # noqa: E402
q50 = importlib.import_module("50_query_app")  # 이름이 숫자로 시작해서 import 문 대신 사용 (51번도 함께 불러옴)
q51 = q50.q51
sys.path.insert(0, str(Path(__file__).resolve().parent))
import grid_map                                # noqa: E402  같은 frontend 폴더의 격자 지도 HTML


def new_conn():
    """내 PC = db_common.connect (로컬 MySQL), 클라우드 = Secrets의 TiDB Cloud (TLS 필수)"""
    if CLOUD is None:
        return connect()
    import mysql.connector
    c = mysql.connector.connect(
        host=CLOUD["host"], port=int(CLOUD.get("port", 4000)), user=CLOUD["user"], password=CLOUD["password"],
        database=CLOUD.get("database", "ndb_project"), charset="utf8mb4",
        ssl_ca=CLOUD.get("ssl_ca", "/etc/ssl/certs/ca-certificates.crt"),   # Streamlit Cloud(리눅스)의 기본 인증서 묶음
        ssl_verify_cert=True, ssl_verify_identity=True,
        use_pure=True,              # C 확장 대신 순수 Python 드라이버: 클라우드(Python 3.14)에서 연결이 끊길 때 앱 전체가 죽는(Segmentation fault) 것을 막음
        connection_timeout=20)
    c.autocommit = False
    return c


def query(fn, *args):
    """조회 한 번마다 연결을 새로 열고 바로 닫음.
    연결을 오래 들고 있으면 클라우드 DB가 쉬는 연결을 끊어 'Lost connection'이 나고,
    여러 화면 갱신이 한 연결을 같이 쓰다 꼬일 수 있음. 결과는 아래 캐시에 저장되므로 같은 조회를 반복하지 않음"""
    c = new_conn()
    try:
        return fn(c, *args)
    finally:
        try:
            c.close()
        except Exception:
            pass


# ---------------------------------------------------------------- 조회 결과 캐시
# 시연 중에는 DB 내용이 바뀌지 않으므로, 같은 조건의 조회 결과는 저장해 두고 다시 씀 (질문 전환이 빨라짐)
# DB를 다시 적재했다면 화면 오른쪽 위 ⋮ → Clear cache 를 누르거나 Streamlit을 다시 켜면 됨
@st.cache_data(show_spinner=False)
def run(mod, name, *args):
    """mod = '50' 또는 '51', name = 그 파일의 조회 함수 이름. 값은 그 함수 안에서 Prepared Statement로만 전달"""
    fn = getattr(q50 if mod == "50" else q51, name)
    return query(fn, *args)


@st.cache_data(show_spinner=False)
def run_sql(sql, params):
    return query(fetch, sql, params)


@st.cache_data(show_spinner=False)
def image_bytes(path):
    """Google 드라이브에서 그림 파일을 매번 읽지 않도록 한 번만 읽음"""
    return Path(path).read_bytes()


SQL_REGIONS = """
SELECT region_id, sido, sigungu, role
FROM region
WHERE role IN (%s, %s)
ORDER BY sido, sigungu
"""

try:
    regions = run_sql(SQL_REGIONS, ("train", "diagnose"))
except Exception as e:  # 접속 실패 원인을 화면에 그대로 보여 준다
    st.error(f"DB 연결 실패: {e}")
    st.stop()

# ---------------------------------------------------------------- 화면 설정값
SCENARIOS = {                     # 50번 SCENARIOS와 같은 값, 화면에는 한국어로
    "current": "2025 현재",
    "low": "2028 비관 (인구 예측 하한)",     # 중간 × (1 − 백테스트 MAPE)
    "mid": "2028 기본 (인구 예측값)",
    "high": "2028 낙관 (인구 예측 상한)",    # 중간 × (1 + 백테스트 MAPE)
    "backtest": "2019 백테스트",
}
ALL_TYPES = "전체 7개 업종"

# 질문별: 제목, 상시 주의 배너, 적용되는 필터 (시군, 시나리오, 업종)
QUESTIONS = {
    1: dict(title="1. 우리 시군에서 먼저 둔화될 생활시설은?",
            banner="위험 등급은 절대 감소가 아니라, 과거 비감소 지역 평균보다 느리게 늘어날 것으로 예측된다는 뜻입니다.",
            uses=("시군", "시나리오", "업종")),
    2: dict(title="2. 폐업 때문인가, 개업 정체 때문인가?",
            banner="단일 소멸위험지수 경계값은 없으며, 지수와 1곳당 담당 인구를 함께 봅니다. 식육판매업은 참고용입니다.",
            uses=("시군", "업종")),
    3: dict(title="3. 현장 점검이 필요한 취약 시설은?",
            banner="절대 확률이 아닌 현장 점검 우선순위입니다. 사업장명 등 식별 정보는 표시하지 않으며 시설번호로 내부 조회합니다.",
            uses=("시군", "시나리오", "업종")),
    4: dict(title="4. 닮은 과거 사례와 학교·보육 현황은?",
            banner="유사 지역은 판정 근거가 아닌 서술용 참고 사례입니다.",
            uses=("시군", "업종")),
    5: dict(title="5. 이 진단 결과는 얼마나 믿을 수 있는가?",
            banner="판정 기준은 결과를 보기 전에 고정했고 평가는 1회만 했습니다. 비인구감소 11곳 내부의 판별력은 약합니다(순위 상관 0.20).",
            uses=("업종",)),
}

# ---------------------------------------------------------------- 사이드바
with st.sidebar:
    st.header("공통 필터")
    names = regions["sigungu"].tolist()
    sigungu = st.selectbox("시군", names, index=names.index("서산시") if "서산시" in names else 0)
    scenario = st.selectbox("시나리오", list(SCENARIOS), format_func=SCENARIOS.get)
    type_label = st.selectbox("업종", [ALL_TYPES] + q50.MODEL_TYPES)

    st.header("질문 선택")
    qno = st.radio("질문", list(QUESTIONS), format_func=lambda k: QUESTIONS[k]["title"],
                   label_visibility="collapsed")

    unused = [f for f in ("시군", "시나리오", "업종") if f not in QUESTIONS[qno]["uses"]]
    if unused:
        st.caption("이 질문에는 적용되지 않는 필터: " + ", ".join(unused))

row = regions.loc[regions["sigungu"] == sigungu].iloc[0]
F = dict(                                   # 질문 함수들이 함께 쓰는 필터 값
    region_id=int(row["region_id"]),
    sigungu=sigungu,
    role=row["role"],                       # train = 인구감소 15곳, diagnose = 비인구감소 11곳
    scenario=scenario,
    type_name="" if type_label == ALL_TYPES else type_label,   # 50·51번 함수는 '' = 전체
)


# ---------------------------------------------------------------- 질문별 화면 (3~7단계에서 채움)
def todo(step):
    left, right = st.columns(2)
    left.info(f"{step}단계에서 왼쪽 칸을 채웁니다.")
    right.info(f"{step}단계에서 오른쪽 칸을 채웁니다.")
    return "요약 문장은 이 질문을 구현할 때 조회 결과로 만듭니다."


DIAG_YEAR = {"current": 2025, "low": 2028, "mid": 2028, "high": 2028, "backtest": 2019}


def grade_style(v):
    """등급 칸 색 (격자 지도와 같은 색)"""
    if v in grid_map.GRADE_BG:
        return f"background-color:{grid_map.GRADE_BG[v]};color:{grid_map.GRADE_FG[v]}"
    return ""


def q1(f):
    """Q1 우리 시군에서 먼저 둔화될 생활시설: 왼쪽 업종별 등급표, 오른쪽 26곳 격자 지도 (둘 다 risk_diagnosis)"""
    # group='' = 인구감소 15곳·비인구감소 11곳 모두 (50번 기본값 diagnose는 11곳만이라 비워서 넘김)
    mine = run("50", "f6_risk_diagnosis", f["scenario"], f["region_id"], "", "", "")
    every = run("50", "f6_risk_diagnosis", f["scenario"], 0, f["type_name"], "", "")

    if f["role"] == "train":
        eleven = "·".join(grid_map.short(s) for s in regions.loc[regions["role"] == "diagnose", "sigungu"])
        st.info("인구감소 15곳은 진단 대상이 아니고 대부분 학습 범위 밖이라 '판단 보류'로 표시됩니다. "
                f"등급은 비인구감소 11곳({eleven})에서 봅니다.")

    left, right = st.columns(2)
    with left:
        st.markdown(f"**{f['sigungu']} 업종별 위험 등급** ({SCENARIOS[f['scenario']]})")
        cols = ["업종", "위험등급"]
        if f["scenario"] == "current":                 # 고위험 시설 수는 current에만 있음
            cols += ["고위험시설", "면_고위험시설"]
        t = mine[cols].rename(columns={"위험등급": "등급", "고위험시설": "고위험 시설",
                                       "면_고위험시설": "그중 면 소재"})
        sty = t.style
        paint = sty.map if hasattr(sty, "map") else sty.applymap      # pandas 2.1 미만은 applymap
        st.dataframe(paint(grade_style, subset=["등급"]), hide_index=True, width="stretch")
        st.caption("식육판매업은 위험 구간 분석에서 관계가 뚜렷하지 않아 참고용입니다.")

    with right:
        what = f["type_name"] or "위험 업종 수"
        st.markdown(f"**충청 26곳 격자 지도: {what}** ({SCENARIOS[f['scenario']]})")
        miss = grid_map.missing_tiles(regions["sigungu"])
        if miss:
            st.warning(f"격자 위치가 없는 시군: {miss} (이름 확인 필요)")
        roles = dict(zip(regions["sigungu"], regions["role"]))
        st.markdown(grid_map.grid_html(every, f["type_name"], f["sigungu"], roles), unsafe_allow_html=True)

    # 요약 문장: 조회 결과 숫자만 문장 틀에 넣음
    by = {g: mine.loc[mine["위험등급"] == g, "업종"].tolist() for g in grid_map.GRADES}
    year = DIAG_YEAR[f["scenario"]]
    text = f"{f['sigungu']} {year}년 진단: 위험 {len(by['위험'])}개 업종"
    if by["위험"]:
        text += f" ({'·'.join(by['위험'])})"
    text += f", 주의 {len(by['주의'])}개, 안전 {len(by['안전'])}개, 판단 보류 {len(by['판단 보류'])}개"
    return text


def q2(f):
    """Q2 폐업 때문인가, 개업 정체 때문인가: 왼쪽 지수 단계별 개업률·폐업률(F2), 오른쪽 위험 구간 그림(fig3) + 시군 위치(F4)"""
    # 7개 업종을 한 번에 조회한 뒤 화면에서 업종을 고름 (업종별로 따로 조회하지 않아 캐시 1개로 끝남)
    r = run("50", "f2_index_class", "", "all").copy()          # 26곳, 2012~2025년, 작년 영업 수 5곳 이상
    if f["type_name"]:
        r = r[r["업종"] == f["type_name"]]
    if r.empty:
        st.warning(f"조회 결과가 없습니다 (업종: {f['type_name'] or '전체'}). 사이드바 맨 아래 'DB 연결 확인'을 펼쳐 캡처해 주세요.")
        return "조회 결과 없음"
    r = r.copy()
    for k in ("개업률", "폐업률", "순증감률"):
        r[k] = r[k] * 100                                     # 화면은 % 단위

    left, right = st.columns(2)
    with left:
        if f["type_name"] and r.empty:
            # 업종을 골랐는데 0행이면 조회 조건(업종 이름 비교)이 DB에서 맞지 않은 것 → 원인 확인용 안내
            st.warning(f"'{f['type_name']}' 조회 결과가 0행입니다. DB 연결·업종 이름 비교를 확인해야 합니다. "
                       f"(접속 DB: {'클라우드 TiDB' if CLOUD else '내 PC MySQL'})")
        elif f["type_name"]:
            st.markdown(f"**{f['type_name']}: 소멸위험지수 단계별 개업률 vs 폐업률** (충청 26곳, 2012–2025년)")
            bars = r.set_index("지수단계")[["개업률", "폐업률"]]
            st.bar_chart(bars, stack=False, y_label="연평균 비율 (%)", x_label="소멸위험지수 단계 (1 = 소멸고위험)")
            t = r[["지수단계", "시군수", "개업률", "폐업률", "순증감률", "비고"]]
            st.dataframe(t, hide_index=True, width="stretch",
                         column_config={k: st.column_config.NumberColumn(format="%.2f%%")
                                        for k in ("개업률", "폐업률", "순증감률")})
        else:
            st.markdown("**업종별·단계별 순증감률 (%)** — 왼쪽 사이드바의 '업종'에서 고르면 개업률·폐업률 막대가 나옵니다")
            wide = r.pivot_table(index="업종", columns="지수단계", values="순증감률", aggfunc="first")
            st.dataframe(wide, width="stretch",
                         column_config={k: st.column_config.NumberColumn(format="%+.2f") for k in wide.columns})
        st.caption("비율 = 단계 안 시군·연도의 개업(폐업) 합계 ÷ 작년 영업 수 합계. 작년 영업 수 5곳 미만인 시군·연도는 제외.")

    with right:
        st.markdown("**업종별 위험 구간: 소멸위험지수 × 1곳당 담당 인구**")
        fig = FIGURES / "fig3_risk_band.png"
        if fig.exists():
            st.image(image_bytes(str(fig)), width="stretch")
        else:
            st.warning(f"그림 파일이 없습니다: {fig}")
        st.caption("그림은 2025년 현재 기준(2015–2022년 회귀, 점은 2025년 값)이며 필터에 따라 바뀌지 않습니다.")
        pos = run("50", "f4_region_position", f["region_id"], f["type_name"])
        if len(pos):
            st.markdown(f"**{f['sigungu']} 2025년 값은 위험 구간 안인가** (지표 하나씩 따로 본 위치)")
            word = {"구간 안": "위험 쪽", "구간 밖": "안전 쪽", "경계 없음": "관계 불분명"}

            def band(lo, hi, digits):
                return "-" if pd.isna(lo) else f"{lo:,.{digits}f}–{hi:,.{digits}f}"
            t = pd.DataFrame({
                "업종": pos["업종"],
                "지수": pos["소멸위험지수"].map(lambda v: f"{v:.2f}"),
                "지수 위험 구간": [band(a, b, 2) for a, b in zip(pos["지수_하한"], pos["지수_상한"])],
                "지수 판정": pos["지수_위치"].map(word),
                "담당 인구": pos["담당인구"].map(lambda v: f"{v:,.0f}명"),
                "담당 인구 위험 구간": [band(a, b, 0) for a, b in zip(pos["담당인구_하한"], pos["담당인구_상한"])],
                "담당 인구 판정": pos["담당인구_위치"].map(word),
            })
            st.dataframe(t, hide_index=True, width="stretch")
            st.caption("위험 구간 = 다른 지표를 중앙값에 두었을 때 예측 상대 순증감률이 0보다 낮아지는 범위"
                       "(비감소 지역 평균보다 느리게 늘 것으로 예측). 관계 불분명 = 기울기의 80% 구간이 0을 포함하거나 "
                       "경계가 자료 범위 밖. 최종 등급은 두 지표를 함께 넣은 예측으로 정하므로 1번 질문의 등급과 다를 수 있습니다.")

    if not f["type_name"]:
        return "왼쪽 사이드바의 '업종'에서 하나 고르면 단계별 개업률과 폐업률을 비교한 요약이 나옵니다."
    lo = r[r["지수단계"].str.startswith("1")]
    hi = r[r["지수단계"].str.startswith("5")]
    if lo.empty or hi.empty:
        return f"{f['type_name']}: 1단계 또는 5단계 자료가 없어 비교하지 않습니다."
    o1, o5 = lo["개업률"].iloc[0], hi["개업률"].iloc[0]
    c1, c5 = lo["폐업률"].iloc[0], hi["폐업률"].iloc[0]
    main = "개업" if abs(o5 - o1) > abs(c5 - c1) else "폐업"
    return (f"{f['type_name']}: 소멸고위험 단계 개업률 {o1:.1f}% vs 소멸저위험 {o5:.1f}% (차이 {o5 - o1:+.1f}%p), "
            f"폐업률 {c1:.1f}% vs {c5:.1f}% (차이 {c5 - c1:+.1f}%p) → 단계 간 차이는 주로 {main} 쪽")


SQL_N_PRED = """
SELECT COUNT(*) AS n
FROM closure_prediction cp
JOIN facility f ON f.facility_id = cp.facility_id
JOIN facility_type t ON t.type_id = f.type_id
WHERE cp.model_version = %s AND cp.base_date = %s
  AND (%s = 0 OR f.region_id = %s) AND (%s = '' OR t.type_name = %s)
"""


def q3(f):
    """Q3 현장 점검이 필요한 취약 시설: 왼쪽 고위험 시설 목록, 오른쪽 읍면동별 개수 (closure_prediction)"""
    if f["scenario"] != "current":
        st.info("고위험 시설은 2025년 말 영업 중인 시설에 대해서만 계산했습니다. 시나리오를 '2025 현재'로 바꾸면 보입니다.")
        return "이 시나리오에는 시설별 폐업 확률이 없습니다 (해당 없음)."

    whole = st.toggle("충청 26곳 전체 보기", value=False)
    rid = 0 if whole else f["region_id"]
    where = "충청 26곳" if whole else f["sigungu"]

    d = run("51", "f3_facility_risk", rid, f["type_name"], True, q51.TOP_N_MAX).copy()
    n_all = int(run_sql(SQL_N_PRED, (q51.FINAL_MODEL, q51.FINAL_BASE_DATE, rid, rid,
                                      f["type_name"], f["type_name"]))["n"].iloc[0])

    if d.empty:
        st.success(f"{where}에는 고위험 시설(보정 폐업 확률이 업종 기본 폐업률의 2배 이상)이 없습니다.")
        return f"{where}: 2025년 말 영업 시설 {n_all:,}곳 중 고위험 시설 0곳"

    # 사업장명은 화면에 내지 않음 (시설번호로 내부 조회). 업종마다 문턱이 달라 '문턱 대비 배수'로 순위를 매김
    d = d.drop(columns=["사업장명"])
    d["배수"] = (d["폐업확률_보정후"] / d["고위험문턱"]).round(2)
    d = d.sort_values(["배수", "시설번호"], ascending=[False, True]).reset_index(drop=True)
    d.insert(0, "순위", range(1, len(d) + 1))

    left, right = st.columns(2)
    with left:
        st.markdown(f"**현장 점검 우선순위: {where}** (고위험 {len(d)}곳)")
        # 순위를 정한 '문턱 대비 배수'를 앞쪽에 둬서 가로 스크롤 없이 보이게 함
        cols = ["순위"] + (["시군"] if whole else []) + ["읍면동", "읍면동구분", "업종", "배수", "영업연수",
                                                          "시설번호", "폐업확률_보정후", "고위험문턱"]
        t = d[cols].rename(columns={"읍면동구분": "구분", "폐업확률_보정후": "3년 폐업 확률",
                                     "고위험문턱": "문턱", "배수": "문턱 대비 배수"})
        st.dataframe(t, hide_index=True, width="stretch",
                     column_config={"3년 폐업 확률": st.column_config.NumberColumn(format="%.3f"),
                                    "문턱": st.column_config.NumberColumn(format="%.3f"),
                                    "문턱 대비 배수": st.column_config.NumberColumn(format="%.2f배")})
        st.caption("문턱 = 업종 기본 폐업률(3년) × 2. 확률은 보정 후 값이며, 절대 확률이 아니라 점검 순서를 정하는 데 씁니다.")

    with right:
        key = "시군" if whole else "읍면동"
        st.markdown(f"**{key}별 고위험 시설 수**")
        # st.bar_chart는 막대를 이름순으로 다시 정렬하므로 Altair로 직접 그려 많은 순으로 둠
        cnt = d.groupby([key, "업종"]).size().reset_index(name="시설 수")
        chart = alt.Chart(cnt).mark_bar().encode(
            y=alt.Y(f"{key}:N", sort="-x", title=None),
            x=alt.X("sum(시설 수):Q", title="고위험 시설 수", axis=alt.Axis(tickMinStep=1, format="d")),
            color=alt.Color("업종:N", legend=alt.Legend(orient="bottom")),
            tooltip=[key, "업종", "시설 수"],
        )
        st.altair_chart(chart, width="stretch")

    myeon = int((d["읍면동구분"] == "면").sum())
    by_type = d["업종"].value_counts()
    detail = ", ".join(f"{k} {v}곳" for k, v in by_type.items())
    return (f"{where}: 2025년 말 영업 시설 {n_all:,}곳 중 고위험 {len(d)}곳({len(d) / n_all:.1%}) · "
            f"{detail} · 면 소재 {myeon}곳")


def q4(f):
    """Q4 닮은 과거 사례와 학교·보육: 왼쪽 시차 유사 지역(similar_region), 오른쪽 지수 단계별 병원·폐교·어린이집(F8)"""
    sim = run("50", "f7_similar_region", f["region_id"], f["type_name"]).copy()
    f8 = q50._tidy(run("50", "f8_index_class"))            # 50번 화면용 정리 (2025년 해당 없는 단계 표시 포함)
    mine = run("50", "f8_region", f["region_id"])
    cc = run("50", "f8_childcare_region", f["region_id"])
    stage = mine.loc[mine["연도"] == mine["연도"].max(), "지수단계"].iloc[0] if len(mine) else None

    left, right = st.columns(2)
    with left:
        st.markdown(f"**{f['sigungu']}와 닮은 과거 시점 (상위 3곳)**")
        if sim.empty:
            st.info("시차 유사 지역은 비인구감소 11곳에 대해서만 찾았습니다. 인구감소 지역은 비교 대상(과거 사례) 쪽입니다.")
        else:
            top = sim.drop_duplicates("순위")[["순위", "유사시군", "유사연도", "거리"]]
            st.dataframe(top, hide_index=True, width="stretch",
                         column_config={"거리": st.column_config.NumberColumn(format="%.2f")})
            # 업종 × 순위: 유사 지역에서 그 시점 이후 3년 동안 영업 수가 얼마나 변했는지
            sim["사례"] = sim["순위"].astype(str) + "순위 " + sim["유사시군"] + " " + sim["유사연도"].astype(str)
            wide = sim.pivot_table(index="업종", columns="사례", values="변화율_3년", aggfunc="first") * 100
            st.markdown("유사 지역의 이후 3년 영업 수 변화율")
            st.dataframe(wide, width="stretch",
                         column_config={k: st.column_config.NumberColumn(format="%+.1f%%") for k in wide.columns})
            st.caption("유사 지역은 판정 근거가 아니라 서술용 참고 사례입니다. 거리가 작을수록 닮았습니다.")

    with right:
        st.markdown("**소멸위험지수 단계별 공공·보육 현황**")
        # 열 이름을 짧게 해서 가로 스크롤 없이 보이게 함 (뜻은 아래 설명 줄에 적음)
        show = f8[["지수단계", "시군수", "인구10만명당_병원", "연평균_폐교율_pct", "충원율_pct"]].rename(
            columns={"인구10만명당_병원": "병원", "연평균_폐교율_pct": "폐교율(%)", "충원율_pct": "충원율(%)"})
        fmt = {"병원": "{:.1f}", "폐교율(%)": "{:.2f}", "충원율(%)": lambda v: f"{v:.1f}" if isinstance(v, float) else v}

        def mark(row):  # 선택 시군의 최근 단계 행을 굵게
            hit = row["지수단계"] == stage
            return ["font-weight:bold;background-color:rgba(255,215,0,0.25)" if hit else "" for _ in row]
        st.dataframe(show.style.apply(mark, axis=1).format(fmt), hide_index=True, width="stretch")
        line = f"{f['sigungu']}의 최근 단계: {stage or '-'} (노란 줄)"
        if len(cc) and cc["충원율_pct"].notna().iloc[0]:
            line += f" · 어린이집 {int(cc['어린이집'].iloc[0])}곳, 충원율 {cc['충원율_pct'].iloc[0]:.1f}%"
        # '~'를 두 번 쓰면 마크다운 취소선이 되므로 '–'로 씀
        st.caption(line + ". 병원 = 인구 10만 명당 병원 수(2011–2025년), 폐교율 = 초등학교 연평균 폐교율(2012–2025년), "
                   "충원율 = 어린이집 현원 ÷ 정원(2025-12-31).")

    if sim.empty:
        return f"{f['sigungu']}: 유사 지역 없음(인구감소 지역) · 소멸위험지수 단계 {stage or '-'}"
    r1 = sim.iloc[0]
    return (f"{f['sigungu']}(현재) ≈ {r1['유사시군']}({int(r1['유사연도'])}년), 거리 {r1['거리']:.2f} · "
            f"소멸위험지수 단계 {stage or '-'}")


EVAL_LABEL = {"cv": "교차검증", "time": "① 시간", "region": "② 지역", "external": "③ 외부"}
MODEL_LABEL = {"base": "기준", "logit": "로지스틱", "rf_raw": "RF", "rf_cal": "최종"}   # 표가 잘리지 않게 짧게 (뜻은 설명 줄)
# 국세청 교차 확인 (31_check_nts.py 결과, 충청 26곳 2025년 12월). 판정 기준 없는 데이터 점검용이라 고정 표로 둠
NTS = pd.DataFrame([
    ("약국", "약국", 1773, 1762), ("미용실", "미용업", 9038, 9356), ("이발소", "이용업", 1104, 1357),
    ("목욕탕", "목욕장업", 301, 383), ("정육점", "식육판매업", 1959, 4179),
], columns=["국세청 업종", "인허가 업종", "국세청", "인허가"])
NTS["비율 (인허가÷국세청)"] = (NTS["인허가"] / NTS["국세청"]).round(2)


def q5(f):
    """Q5 이 진단 결과는 얼마나 믿을 수 있는가: 왼쪽 평가 결과 표(model_evaluation)·국세청 교차 확인, 오른쪽 fig7·fig5"""
    who = f["type_name"] or "전체"                       # '전체' = 업종 합계 행
    ev = run("51", "f6_model_evaluation", "", who, "all", "main").copy()
    # 주 결과 버전 이름: clf_<평가>_<모델>_v1 (예: clf_time_rf_cal_v1). 약국·의원 비교 모델(cmp)은 뺌
    ev["모델"] = ev["모델버전"].str.extract(r"^clf_[a-z]+_(base|logit|rf_raw|rf_cal)_v1$", expand=False)
    ev = ev.dropna(subset=["모델"])
    ev = ev[ev["평가"].isin(EVAL_LABEL)]

    left, right = st.columns(2)
    with left:
        st.markdown(f"**폐업 예측 모델 평가 AUC ({who})** — 0.5 = 무작위, 높을수록 폐업 순서를 잘 맞힘")
        if ev.empty:
            st.info("이 업종의 평가 결과가 없습니다.")
            auc = pd.DataFrame()
        else:
            auc = ev.pivot_table(index="평가", columns="모델", values="AUC", aggfunc="first")
            auc = auc.reindex(index=[k for k in EVAL_LABEL if k in auc.index],
                              columns=[k for k in MODEL_LABEL if k in auc.columns])
            brier = ev[ev["모델"] == "rf_cal"].set_index("평가")["브라이어"]
            t = auc.rename(index=EVAL_LABEL, columns=MODEL_LABEL)
            t["최종 브라이어"] = brier.reindex(auc.index).values
            st.dataframe(t, width="stretch",
                         column_config={k: st.column_config.NumberColumn(format="%.3f") for k in t.columns})
            st.caption("브라이어 점수 = 예측 확률과 실제(폐업 0/1)의 차이 제곱 평균, 낮을수록 좋음. "
                       "기준 = 업종 평균 폐업률만 쓰는 단순 모델, RF = 랜덤포레스트(보정 전), 최종 = 랜덤포레스트 + 확률 보정(sigmoid).")

        st.markdown("**국세청 교차 확인** (충청 26곳, 2025년 12월)")
        st.dataframe(NTS, hide_index=True, width="stretch")
        st.caption("인허가 자료가 실제 영업을 얼마나 반영하는지 보는 데이터 점검(판정 기준 없음). "
                   "약국·미용업은 거의 일치하고, 이용업·목욕장업·식육판매업은 인허가가 더 많아 결과를 참고로만 봅니다.")

    with right:
        for name, title in (("fig7_eval_summary.png", "평가 ①~③ 요약"), ("fig5_backtest.png", "평가 ④ 진단 백테스트")):
            st.markdown(f"**{title}**")
            p = FIGURES / name
            if p.exists():
                st.image(image_bytes(str(p)), width="stretch")
            else:
                st.warning(f"그림 파일이 없습니다: {p}")
        st.caption("그림은 보고서와 같은 고정 그림이며 필터에 따라 바뀌지 않습니다.")

    if auc.empty or "rf_cal" not in auc.columns:
        return f"{who}: 평가 결과를 찾지 못했습니다."
    parts = " · ".join(f"{EVAL_LABEL[k]} {v:.3f}" for k, v in auc["rf_cal"].dropna().items())
    text = f"최종 모델 AUC ({who}): {parts}"
    if "base" in auc.columns:
        text += f" (기준 모델 {auc['base'].min():.3f}~{auc['base'].max():.3f})"
    return text + " · 진단 백테스트 순위 상관 26곳 0.30, 11곳 0.20"


# ---------------------------------------------------------------- 오른쪽 화면
# 제목이 두 줄로 꺾이지 않게: 화면 폭에 맞춰 글자 크기를 줄이고(최소 1.2rem ~ 최대 2.25rem) 줄바꿈을 막음
st.markdown(
    '<h1 style="font-size:clamp(1.2rem, 2vw, 2.25rem); white-space:nowrap; margin:0 0 0.5rem 0;">'
    '개·폐업 이력으로 본 충청권 생활시설 위험 진단 정보시스템</h1>',
    unsafe_allow_html=True)
summary_box = st.container()                # 요약은 질문 화면을 그린 뒤 위쪽에 채운다
st.warning(QUESTIONS[qno]["banner"])
summary = {1: q1, 2: q2, 3: q3, 4: q4, 5: q5}[qno](F)
summary_box.subheader(QUESTIONS[qno]["title"])
summary_box.markdown(f"**{summary}**")

APP_VERSION = "2026-11-22 d"                    # 화면을 고칠 때마다 바꿔서, 클라우드에 새 코드가 올라갔는지 확인하는 용도

with st.sidebar.expander("DB 연결 확인"):
    st.write(f"코드 버전: {APP_VERSION}")
    st.write(f"접속 DB: {'클라우드 TiDB' if CLOUD else '내 PC MySQL'}")
    st.write(f"시군 {len(regions)}곳, 업종 {len(q50.MODEL_TYPES)}개")
    st.write(f"선택: {F}")
