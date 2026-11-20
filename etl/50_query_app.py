# -*- coding: utf-8 -*-
r"""50번 (75→100 문서 8·9번): 조회 프로그램 통합 메뉴 + F1·F2·F4·F6(위험 진단)·F7·F8 함수 (진우)
슬기님 51_query_f3f5f6.py의 F3·F5·모델 평가 함수와 공통 함수(pick_region, print_table 등)를 import해서 한 메뉴로 묶는다.
  F1 f1_region_trend      시군별·연도별 인구·소멸위험지수·업종별 영업 수·개업·폐업 (v_type_region_year)
  F2 f2_index_class       소멸위험지수 단계별 개업률·폐업률·순증감률 (한국고용정보원 단계 0.2/0.5/1.0/1.5, F8과 같음)
                          규칙은 40번과 같음: 2012~2025년, 작년 영업 수 5곳 이상, 비율 = 합계 ÷ 작년 영업 수 합계
  F4 f4_risk_band         업종별 위험 구간 (risk_band, band_v1) / f4_region_position: 시군의 2025년 값이 구간 안인지
  F6 f6_risk_diagnosis    비인구감소 11곳 등 시군·업종별 위험 등급과 고위험 시설 수 (risk_diagnosis)
  F7 f7_similar_region    시차 유사 지역과 그 지역의 3년 뒤 업종별 영업 수 변화 (similar_region)
  F8 f8_index_class       단계별 병원·초등학교 폐교율·어린이집 충원율 / f8_region: 한 시군의 연도별 값
규칙
  - 사용자가 고르는 값은 모두 Prepared Statement의 %s 로만 넘긴다 (51번과 같음). 이 파일은 DB에 쓰지 않는다 (SELECT만).
  - 집계는 SQL 안에서 한다 (GROUP BY, LAG 윈도우 함수). pandas는 출력과 --check 비교에만 쓴다.
  - 개인정보: 이 파일의 기능은 모두 시군 단위 집계라 사업장명도 내보내지 않는다.
사용법: py -I 50_query_app.py            통합 메뉴 (비밀번호는 실행할 때 입력)
        py -I 50_query_app.py --demo     공주시 예시를 기능마다 한 번씩 출력하고 끝냄
        py -I 50_query_app.py --check    조회 결과가 40·41·42·43·44번 결과와 같은지 확인 (OK / 다름)
"""
import argparse
import importlib
import sys
from pathlib import Path

import pandas as pd

ETL = Path(__file__).resolve().parent
sys.path.insert(0, str(ETL))                       # py -I 에서는 이 폴더가 자동으로 안 들어가므로 직접 추가
from db_common import connect, fetch               # noqa: E402

q51 = importlib.import_module("51_query_f3f5f6")   # 이름이 숫자로 시작해서 import 문 대신 사용
pick_region, print_table, _ask, _ask_region, _need = (q51.pick_region, q51.print_table, q51._ask,
                                                      q51._ask_region, q51._need)
MODEL_TYPES = q51.MODEL_TYPES

RESULTS = ETL.parent / "results"
YEAR_FROM, YEAR_TO, MIN_PREV = 2012, 2025, 5        # 40번과 같은 규칙
BAND_VERSIONS = ["band_v1", "band_bt2019"]
GROUPS = {"all": ("train", "diagnose"), "train": ("train", "train"), "diagnose": ("diagnose", "diagnose")}
GROUP_NAMES = {"all": "26곳 전체", "train": "인구감소 15곳", "diagnose": "비인구감소 11곳"}
SCENARIOS = ["current", "low", "mid", "high", "backtest"]
GRADES = ["위험", "주의", "안전", "판단 보류"]
IND_IDX, IND_PPF = "소멸위험지수", "1곳당 담당 인구"

INDEX_CLASS_SQL = """CASE WHEN {c} < 0.2 THEN '1 소멸고위험'
            WHEN {c} < 0.5 THEN '2 소멸위험진입'
            WHEN {c} < 1.0 THEN '3 소멸주의'
            WHEN {c} < 1.5 THEN '4 보통'
            ELSE '5 소멸저위험' END"""


def _tidy(df):
    """화면용: 정수 값만 있는 실수 열은 정수로, F8에서 2025년에 해당 시군이 없는 단계의 어린이집 칸은 글로 표시.
    --check는 이 함수를 거치지 않은 원래 값으로 비교한다"""
    df = df.copy()
    for c in df.columns:
        if pd.api.types.is_float_dtype(df[c]):
            v = df[c].dropna()
            if len(v) and (v == v.round()).all() and not any(k in c for k in ("률", "율", "지수", "비율", "pct", "거리")):
                df[c] = df[c].round().astype("Int64")
    if "시군수_2025" in df.columns:
        none = df["시군수_2025"].isna()
        for c in ["시군수_2025", "어린이집", "정원", "현원", "충원율_pct"]:
            df[c] = df[c].astype(object).where(~none, "2025년 해당 없음" if c == "충원율_pct" else "-")
    return df


def show(df, title="", max_rows=60):
    print_table(_tidy(df), title, max_rows)


def _type_ok(type_name):
    _need(type_name == "" or type_name in MODEL_TYPES, f"업종은 {MODEL_TYPES} 중 하나이거나 비워 두세요.")


# ---------------------------------------------------------------- F1
SQL_F1 = """
SELECT sigungu AS 시군, base_year AS 연도, total_pop AS 총인구, extinction_index AS 소멸위험지수,
       ratio_65plus AS 고령비율, type_name AS 업종, n_operating AS 영업수, n_new_open AS 개업,
       n_close AS 폐업, net_change_rate AS 순증감률
FROM v_type_region_year
WHERE region_id = %s AND (%s = '' OR type_name = %s)
ORDER BY type_id, base_year
"""


def f1_region_trend(conn, region_id, type_name=""):
    """F1 시군 추이 2011~2025. type_name '' = 7개 업종 모두. 개업·폐업은 행정상 폐업(R1)과 그 짝 재개설을 뺀 값"""
    region_id = int(region_id)
    _need(region_id > 0, "region_id를 먼저 정하세요.")
    _type_ok(type_name)
    return fetch(conn, SQL_F1, (region_id, type_name, type_name))


# ---------------------------------------------------------------- F2
SQL_F2 = f"""
SELECT type_name AS 업종, {INDEX_CLASS_SQL.format(c="extinction_index")} AS 지수단계,
       COUNT(DISTINCT region_id) AS 시군수, COUNT(*) AS 시군연도,
       SUM(n_operating_prev) AS 작년영업수합,
       ROUND(SUM(n_new_open) / SUM(n_operating_prev), 4) AS 개업률,
       ROUND(SUM(n_close) / SUM(n_operating_prev), 4) AS 폐업률,
       ROUND((SUM(n_operating) - SUM(n_operating_prev)) / SUM(n_operating_prev), 4) AS 순증감률,
       CASE WHEN COUNT(DISTINCT region_id) < 3 THEN '참고(시군 3곳 미만)' ELSE '' END AS 비고
FROM v_type_region_year
WHERE (%s = '' OR type_name = %s) AND role IN (%s, %s)
  AND base_year BETWEEN %s AND %s AND n_operating_prev >= %s
GROUP BY type_id, type_name, 지수단계
ORDER BY type_id, 지수단계
"""


def f2_index_class(conn, type_name="", group="all"):
    """F2 소멸위험지수 단계별 비율. group = all(26곳) / train(인구감소 15곳) / diagnose(비인구감소 11곳)"""
    _type_ok(type_name)
    _need(group in GROUPS, f"지역 그룹은 {list(GROUPS)} 중 하나입니다.")
    r1, r2 = GROUPS[group]
    return fetch(conn, SQL_F2, (type_name, type_name, r1, r2, YEAR_FROM, YEAR_TO, MIN_PREV))


# ---------------------------------------------------------------- F4
SQL_F4_BAND = """
SELECT t.type_name AS 업종, b.indicator AS 지표, b.lower_bound AS 위험구간_하한, b.upper_bound AS 위험구간_상한,
       b.ci_lower AS 경계_80하한, b.ci_upper AS 경계_80상한,
       CASE WHEN b.lower_bound IS NULL THEN '경계 없음: 연속 위험도로 해석' ELSE '경계 있음' END AS 판정,
       b.method AS 산출방법, b.model_version AS 버전
FROM risk_band b JOIN facility_type t ON t.type_id = b.type_id
WHERE b.model_version = %s AND (%s = '' OR t.type_name = %s)
ORDER BY t.type_id, b.indicator
"""

SQL_F4_POS = """
SELECT v.sigungu AS 시군, v.type_name AS 업종, v.base_year AS 연도, v.n_operating AS 영업수,
       v.extinction_index AS 소멸위험지수, bi.lower_bound AS 지수_하한, bi.upper_bound AS 지수_상한,
       CASE WHEN bi.lower_bound IS NULL THEN '경계 없음'
            WHEN v.extinction_index BETWEEN bi.lower_bound AND bi.upper_bound THEN '구간 안' ELSE '구간 밖' END AS 지수_위치,
       v.pop_per_facility AS 담당인구, bp.lower_bound AS 담당인구_하한, bp.upper_bound AS 담당인구_상한,
       CASE WHEN bp.lower_bound IS NULL THEN '경계 없음'
            WHEN v.pop_per_facility BETWEEN bp.lower_bound AND bp.upper_bound THEN '구간 안' ELSE '구간 밖' END AS 담당인구_위치
FROM v_type_region_year v
LEFT JOIN risk_band bi ON bi.type_id = v.type_id AND bi.model_version = %s AND bi.indicator = %s
LEFT JOIN risk_band bp ON bp.type_id = v.type_id AND bp.model_version = %s AND bp.indicator = %s
WHERE v.region_id = %s AND v.base_year = %s AND (%s = '' OR v.type_name = %s)
ORDER BY v.type_id
"""


def f4_risk_band(conn, type_name="", version="band_v1"):
    """F4 업종별 위험 구간. 경계가 NULL이면 기울기의 80% 구간이 0을 포함하거나 경계가 자료 범위 밖 → 연속 위험도"""
    _type_ok(type_name)
    _need(version in BAND_VERSIONS, f"버전은 {BAND_VERSIONS} 중 하나입니다.")
    return fetch(conn, SQL_F4_BAND, (version, type_name, type_name))


def f4_region_position(conn, region_id, type_name="", year=2025, version="band_v1"):
    """F4 한 시군의 그해 값(지수, 1곳당 담당 인구 = 43번 진단과 같은 그해 값)이 위험 구간 안인지.
    '구간 안'은 위험 구간 경계 기준의 위치일 뿐이고, 등급(판단 보류 포함)은 F6에서 본다"""
    region_id, year = int(region_id), int(year)
    _need(region_id > 0, "region_id를 먼저 정하세요.")
    _need(2011 <= year <= 2025, "연도는 2011~2025 사이입니다.")
    _type_ok(type_name)
    _need(version in BAND_VERSIONS, f"버전은 {BAND_VERSIONS} 중 하나입니다.")
    return fetch(conn, SQL_F4_POS, (version, IND_IDX, version, IND_PPF, region_id, year, type_name, type_name))


# ---------------------------------------------------------------- F6 (위험 진단)
SQL_F6_DIAG = """
SELECT r.sigungu AS 시군, CASE r.role WHEN 'diagnose' THEN '비인구감소' ELSE '인구감소' END AS 구분,
       t.type_name AS 업종, d.scenario AS 시나리오, d.diag_year AS 진단연도, d.risk_grade AS 위험등급,
       d.high_risk_count AS 고위험시설, d.high_risk_ratio AS 고위험비율, d.myeon_high_risk_count AS 면_고위험시설
FROM risk_diagnosis d
JOIN region r ON r.region_id = d.region_id
JOIN facility_type t ON t.type_id = d.type_id
WHERE d.scenario = %s AND (%s = 0 OR d.region_id = %s) AND (%s = '' OR t.type_name = %s)
  AND (%s = '' OR r.role = %s) AND (%s = '' OR d.risk_grade = %s)
ORDER BY CASE d.risk_grade WHEN '위험' THEN 1 WHEN '주의' THEN 2 WHEN '안전' THEN 3 ELSE 4 END,
         r.region_id, t.type_id
"""


def f6_risk_diagnosis(conn, scenario="current", region_id=0, type_name="", group="diagnose", grade=""):
    """F6 위험 등급. scenario: current(2025) / low·mid·high(2028) / backtest(2019).
    group: diagnose(비인구감소 11곳, 기본) / train(15곳) / '' 전체. 고위험 시설 수는 current에만 있음"""
    region_id = int(region_id)
    _need(scenario in SCENARIOS, f"시나리오는 {SCENARIOS} 중 하나입니다.")
    _need(region_id >= 0, "region_id는 0 이상이어야 합니다.")
    _type_ok(type_name)
    _need(group in ("", "diagnose", "train"), "구분은 diagnose / train 이거나 비워 두세요.")
    _need(grade == "" or grade in GRADES, f"등급은 {GRADES} 중 하나이거나 비워 두세요.")
    return fetch(conn, SQL_F6_DIAG, (scenario, region_id, region_id, type_name, type_name, group, group, grade, grade))


# ---------------------------------------------------------------- F7
SQL_F7 = """
SELECT rt.sigungu AS 대상시군, s.target_year AS 대상연도, s.rank_no AS 순위, rs.sigungu AS 유사시군,
       s.similar_year AS 유사연도, s.distance AS 거리, v0.type_name AS 업종,
       v0.n_operating AS 그때_영업수, v3.n_operating AS 영업수_3년뒤,
       ROUND(v3.n_operating / NULLIF(v0.n_operating, 0) - 1, 4) AS 변화율_3년
FROM similar_region s
JOIN region rt ON rt.region_id = s.target_region_id
JOIN region rs ON rs.region_id = s.similar_region_id
JOIN v_type_region_year v0 ON v0.region_id = s.similar_region_id AND v0.base_year = s.similar_year
JOIN v_type_region_year v3 ON v3.region_id = s.similar_region_id AND v3.base_year = s.similar_year + 3
                          AND v3.type_id = v0.type_id
WHERE s.target_region_id = %s AND (%s = '' OR v0.type_name = %s)
ORDER BY s.rank_no, v0.type_id
"""


def f7_similar_region(conn, region_id, type_name=""):
    """F7 대상 시군의 현재와 닮은 인구감소 시군의 과거 시점(상위 3곳)과 그 뒤 3년의 업종별 영업 수 변화"""
    region_id = int(region_id)
    _need(region_id > 0, "region_id를 먼저 정하세요.")
    _type_ok(type_name)
    return fetch(conn, SQL_F7, (region_id, type_name, type_name))


# ---------------------------------------------------------------- F8
SQL_F8_CLASS = """
WITH d AS (
  SELECT region_id, base_year, total_pop, index_class, n_hospital, n_school_closed,
         LAG(n_school) OVER (PARTITION BY region_id ORDER BY base_year) AS n_school_prev
  FROM v_f8_region_year
  WHERE base_year BETWEEN %s AND %s),
k AS (SELECT region_id, index_class FROM v_f8_region_year WHERE base_year = %s),
cc AS (SELECT k.index_class, COUNT(DISTINCT k.region_id) AS n_region_now, COUNT(c.region_id) AS n_cc,
              SUM(c.capacity) AS cap, SUM(c.current_children) AS cur
       FROM k LEFT JOIN childcare c ON c.region_id = k.region_id
       GROUP BY k.index_class)
SELECT d.index_class AS 지수단계, COUNT(DISTINCT d.region_id) AS 시군수, COUNT(*) AS 시군연도,
       ROUND(SUM(d.n_hospital) / SUM(d.total_pop) * 100000, 2) AS 인구10만명당_병원,
       SUM(CASE WHEN d.base_year >= %s THEN d.n_school_closed END) AS 폐교,
       ROUND(SUM(CASE WHEN d.base_year >= %s THEN d.n_school_closed END)
           / SUM(CASE WHEN d.base_year >= %s THEN d.n_school_prev END) * 100, 2) AS 연평균_폐교율_pct,
       MAX(cc.n_region_now) AS 시군수_2025, MAX(cc.n_cc) AS 어린이집, MAX(cc.cap) AS 정원, MAX(cc.cur) AS 현원,
       ROUND(MAX(cc.cur) / MAX(cc.cap) * 100, 1) AS 충원율_pct,
       CASE WHEN COUNT(DISTINCT d.region_id) < 3 THEN '참고(시군 3곳 미만)' ELSE '' END AS 비고
FROM d LEFT JOIN cc ON cc.index_class = d.index_class
GROUP BY d.index_class
ORDER BY d.index_class
"""

SQL_F8_REGION = """
SELECT sigungu AS 시군, base_year AS 연도, total_pop AS 총인구, extinction_index AS 소멸위험지수,
       index_class AS 지수단계, n_hospital AS 병원, n_school AS 초등학교, n_school_closed AS 폐교
FROM v_f8_region_year WHERE region_id = %s ORDER BY base_year
"""

SQL_F8_CC = """
SELECT r.sigungu AS 시군, COUNT(c.region_id) AS 어린이집, SUM(c.capacity) AS 정원, SUM(c.current_children) AS 현원,
       ROUND(SUM(c.current_children) / NULLIF(SUM(c.capacity), 0) * 100, 1) AS 충원율_pct
FROM region r LEFT JOIN childcare c ON c.region_id = r.region_id
WHERE r.region_id = %s GROUP BY r.region_id, r.sigungu
"""


def f8_index_class(conn):
    """F8 단계별 요약 (42번과 같은 정의). 병원은 2011~2025, 폐교율은 2012~2025, 어린이집은 2025-12-31 한 시점(2025년 단계)"""
    return fetch(conn, SQL_F8_CLASS, (2011, 2025, 2025, YEAR_FROM, YEAR_FROM, YEAR_FROM))


def f8_region(conn, region_id):
    """F8 한 시군의 연도별 병원·초등학교·폐교"""
    region_id = int(region_id)
    _need(region_id > 0, "region_id를 먼저 정하세요.")
    return fetch(conn, SQL_F8_REGION, (region_id,))


def f8_childcare_region(conn, region_id):
    """F8 한 시군의 어린이집 정원·현원·충원율 (2025-12-31)"""
    region_id = int(region_id)
    _need(region_id > 0, "region_id를 먼저 정하세요.")
    return fetch(conn, SQL_F8_CC, (region_id,))


# ---------------------------------------------------------------- --check
def _num_eq(a, b, tol):
    if pd.isna(a) and pd.isna(b):
        return True
    if pd.isna(a) or pd.isna(b):
        return False
    return abs(float(a) - float(b)) <= tol


def run_check(conn):
    rows = []

    def add(item, ok, detail):
        rows.append((item, "OK" if ok else "다름", detail))

    # F1: 공주시 2025년 인구 (00번 정답)
    rid, _ = pick_region(conn, "공주시")
    d = f1_region_trend(conn, rid)
    v = d.loc[d["연도"] == 2025, "총인구"]
    add("F1 공주시 2025년 인구", len(v) > 0 and int(v.iloc[0]) == 99719, f"{int(v.iloc[0]) if len(v) else None} (정답 99719)")

    # F2: 26곳 단계별 시군연도 합 = 40번 F1-수준 회귀의 행수 (같은 자료 범위)
    f1l = pd.read_csv(RESULTS / "f1_level.csv", encoding="utf-8-sig")
    f2 = f2_index_class(conn, "", "all")
    got = f2.groupby("업종")["시군연도"].sum()
    for t in MODEL_TYPES:
        exp = f1l.loc[(f1l["업종"] == t) & (f1l["지표"] == "순증감률"), "행수"]
        add(f"F2 {t} 시군연도 합", len(exp) > 0 and int(got.get(t, -1)) == int(exp.iloc[0]),
            f"{int(got.get(t, -1))} / 40번 {int(exp.iloc[0]) if len(exp) else None}")

    # F4: DB 경계 = 41번 요약의 경계값 (경계가 뚜렷하고 자료 범위 안인 칸만 값이 있어야 함)
    s = pd.read_csv(RESULTS / "risk_band_summary.csv", encoding="utf-8-sig")
    s = s[s["버전"] == "band_v1"]
    b = f4_risk_band(conn, "", "band_v1")
    add("F4 band_v1 행 수", len(b) == len(s), f"{len(b)} / 41번 {len(s)}")
    for _, r in s.iterrows():
        t, ind = r["업종"], r["지표"]
        row = b[(b["업종"] == t) & (b["지표"] == ind)]
        has = str(r["경계_뚜렷"]) == "True" and str(r["자료범위_안"]) == "True"
        if len(row) != 1:
            add(f"F4 {t}·{ind}", False, "DB에 행이 없거나 여러 개")
            continue
        lo, hi = row["위험구간_하한"].iloc[0], row["위험구간_상한"].iloc[0]
        x0 = round(float(r["경계값(예측=0)"]), 4) if has else None
        ok = (pd.isna(lo) and pd.isna(hi)) if not has else (_num_eq(lo, x0, 1e-4) or _num_eq(hi, x0, 1e-4))
        add(f"F4 {t}·{ind}", ok, "경계 없음" if not has else f"경계 {x0}")

    # F6: 2025년 등급 개수 = 43번 diag_current.csv
    dc = pd.read_csv(RESULTS / "diag_current.csv", encoding="utf-8-sig")
    g = f6_risk_diagnosis(conn, "current", 0, "", "", "")
    for gr in GRADES:
        a, e = int((g["위험등급"] == gr).sum()), int((dc["risk_grade"] == gr).sum())
        add(f"F6 current {gr} (26곳)", a == e, f"{a} / 43번 {e}")

    # F7: 11곳 × 3순위 = 33행
    n7 = fetch(conn, "SELECT COUNT(*) AS n FROM similar_region WHERE rank_no BETWEEN %s AND %s", (1, 3))["n"].iloc[0]
    add("F7 similar_region 행 수", int(n7) == 33, f"{int(n7)} (기대 33)")

    # F8: 42번 f8_by_index_class.csv와 단계별 값
    e8 = pd.read_csv(RESULTS / "f8_by_index_class.csv", encoding="utf-8-sig").set_index("index_class")
    a8 = f8_index_class(conn).set_index("지수단계")
    pairs = [("인구10만명당_병원", "인구10만명당_병원", 0.011), ("연평균_폐교율_pct", "연평균_폐교율(%)", 0.011),
             ("충원율_pct", "충원율(%)", 0.11), ("시군수", "시군수", 0)]
    for k in e8.index:
        for ac, ec, tol in pairs:
            ok = k in a8.index and _num_eq(a8.at[k, ac], e8.at[k, ec], tol)
            add(f"F8 {k} {ec}", ok, f"{a8.at[k, ac] if k in a8.index else None} / 42번 {e8.at[k, ec]}")

    out = pd.DataFrame(rows, columns=["항목", "결과", "값"])
    print_table(out, "조회 = 분석 결과 확인", max_rows=200)
    print(f"\nOK {int((out['결과'] == 'OK').sum())} / 다름 {int((out['결과'] == '다름').sum())}")
    return out


# ---------------------------------------------------------------- 통합 메뉴
MENU = """
===== 충남·충북 생활시설 유지 위험 조기 진단 조회 =====
1) F1 시군별·연도별 추이                 (진우)
2) F2 소멸위험지수 단계별 개업·폐업·순증감 (진우)
3) F3 시설별 폐업 확률·고위험 시설        (슬기)
4) F4 업종별 위험 구간과 시군 위치        (진우)
5) F5 인구 예측                          (슬기)
6) F6 시군·업종별 위험 등급               (진우)
7) F7 시차 유사 지역                     (진우)
8) F8 병원·초등학교·어린이집              (진우)
9) 모델 평가 결과                        (슬기)
0) 종료"""


def menu(conn):
    while True:
        print(MENU)
        c = _ask("번호")
        try:
            if c == "1":
                rid = _ask_region(conn, True)
                typ = _ask("업종 (" + "/".join(MODEL_TYPES) + ", 비우면 전체)")
                show(f1_region_trend(conn, rid, typ), "F1", max_rows=120)
            elif c == "2":
                typ = _ask("업종 (비우면 전체)")
                grp = _ask("지역 그룹 (all=26곳 / train=인구감소 15곳 / diagnose=비인구감소 11곳)", "all")
                show(f2_index_class(conn, typ, grp), f"F2 {GROUP_NAMES.get(grp, grp)}")
            elif c == "3":
                rid = _ask_region(conn, False)
                typ = _ask("업종 (비우면 전체)")
                hi = _ask("고위험 시설만? (y/n)", "y").lower().startswith("y")
                n = int(_ask(f"보여 줄 건수 (1~{q51.TOP_N_MAX})", str(q51.TOP_N_DEFAULT)))
                print_table(q51.f3_facility_risk(conn, rid, typ, hi, n), "F3")
            elif c == "4":
                typ = _ask("업종 (비우면 전체)")
                show(f4_risk_band(conn, typ), "F4 위험 구간 (band_v1)")
                rid = _ask_region(conn, False)
                if rid:
                    show(f4_region_position(conn, rid, typ), "F4 2025년 시군 위치")
            elif c == "5":
                rid = _ask_region(conn, True)
                mod = _ask("모델 (linear/regression, 비우면 둘 다)")
                sc = _ask("시나리오 (low/mid/high, 비우면 전부)")
                print_table(q51.f5_population_forecast(conn, rid, mod, sc), "F5")
            elif c == "6":
                sc = _ask("시나리오 (" + "/".join(SCENARIOS) + ")", "current")
                rid = _ask_region(conn, False)
                typ = _ask("업종 (비우면 전체)")
                grp = _ask("구분 (diagnose=비인구감소 11곳 / train=15곳 / 비우면 전체)", "diagnose")
                gr = _ask("등급 (위험/주의/안전/판단 보류, 비우면 전체)")
                show(f6_risk_diagnosis(conn, sc, rid, typ, grp, gr), f"F6 {sc}", max_rows=200)
            elif c == "7":
                rid = _ask_region(conn, True)
                typ = _ask("업종 (비우면 전체)")
                show(f7_similar_region(conn, rid, typ), "F7")
            elif c == "8":
                rid = _ask_region(conn, False)
                if rid:
                    show(f8_region(conn, rid), "F8 시군 연도별")
                    show(f8_childcare_region(conn, rid), "F8 어린이집 (2025-12-31)")
                else:
                    show(f8_index_class(conn), "F8 소멸위험지수 단계별")
            elif c == "9":
                es = _ask("평가 종류 (" + "/".join(q51.EVAL_SETS) + ", 비우면 전체)")
                typ = _ask("업종 (비우면 전체, '전체'는 업종 합계 행)")
                sub = _ask("하위집단 (all/metro/other 등, 비우면 전체)")
                kd = _ask("구분 (main / sens / popfc, 비우면 전체)")
                print_table(q51.f6_model_evaluation(conn, es, typ, sub, kd), "모델 평가")
            elif c in ("0", "q", "Q"):
                return
        except ValueError as e:
            print("입력 확인:", e)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true", help="공주시 예시를 기능마다 한 번씩 출력하고 끝냄")
    ap.add_argument("--check", action="store_true", help="조회 결과가 40~44번 결과와 같은지 확인")
    args = ap.parse_args()
    conn = connect()
    try:
        if args.check:
            run_check(conn)
        elif args.demo:
            rid, msg = pick_region(conn, "공주시")
            print("공주시 ->", rid, msg)
            show(f1_region_trend(conn, rid, "약국"), "F1 공주시 약국")
            show(f2_index_class(conn, "약국", "all"), "F2 약국 26곳")
            show(f4_risk_band(conn, "약국"), "F4 약국 위험 구간")
            rid2, _ = pick_region(conn, "아산시")
            show(f4_region_position(conn, rid2, ""), "F4 아산시 2025년 위치")
            show(f6_risk_diagnosis(conn, "current", 0, "", "diagnose", "위험"), "F6 비인구감소 11곳 위험")
            show(f7_similar_region(conn, rid2, "약국"), "F7 아산시 약국")
            show(f8_index_class(conn), "F8 단계별")
        else:
            menu(conn)
    finally:
        conn.close()
