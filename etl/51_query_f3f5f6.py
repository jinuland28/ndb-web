# -*- coding: utf-8 -*-
r"""51번 (75→100 문서 9번): 조회 프로그램 F3·F5·F6 함수 (슬기)
진우님의 50_query_app.py 틀이 오면 이 파일의 함수를 import해서 메뉴에 붙인다. 그 전에는 이 파일의 시험용 메뉴로 확인한다.
  F3 f3_facility_risk       시설별 폐업 확률·고위험 시설 목록 (closure_prediction). 고위험 = 보정 확률(prob_calibrated, prob_raw 아님) >= results\base_rate.csv 의 base_rate_3y x 2 (업종별)
  F5 f5_population_forecast 인구 예측 (population_forecast, 시군·시나리오·모델별). 시나리오 low/mid/high = 중간 예측 x (1 -/+ 백테스트 MAPE)
  F6 f6_model_evaluation    모델 평가 결과 (model_evaluation). 주 결과 / 민감도 / 인구 예측을 구분해서 보여 줌
공통 함수: resolve_region (시군명 -> region_id, region_alias 사용), similar_names (없는 이름일 때 비슷한 이름), load_thresholds (base_rate.csv)

규칙
  - 사용자가 고르는 값(시군, 업종, 연도·시나리오·모델, 평가 종류, 건수)은 모두 Prepared Statement의 %s 로만 넘긴다. SQL 문자열에 값을 붙이지 않는다.
    (Python에서 값의 범위를 먼저 확인하지만, 확인을 통과한 값도 SQL에는 %s 로만 들어간다)
  - 연결과 조회는 db_common.py (connect, fetch). 이 파일은 DB에 쓰지 않는다 (SELECT만).
  - 각 기능 함수는 SQL 한 개와 출력 표(DataFrame) 한 개를 돌려준다.
  - 개인정보: 시설장명·전화번호는 DB에 없다(규칙 R8). F3은 주소·좌표도 내보내지 않고 사업장명과 읍면동까지만 보여 준다.
사용법: py -I 51_query_f3f5f6.py           시험용 메뉴 (비밀번호는 실행할 때 입력)
        py -I 51_query_f3f5f6.py --demo    공주시 예시를 한 번씩 출력하고 끝냄
"""
import argparse
import difflib
import sys
from pathlib import Path

import pandas as pd

ETL = Path(__file__).resolve().parent
sys.path.insert(0, str(ETL))                       # py -I 에서는 이 폴더가 자동으로 안 들어가므로 직접 추가
from db_common import connect, fetch               # noqa: E402

BASE_RATE = ETL.parent / "results" / "base_rate.csv"
FINAL_MODEL, FINAL_BASE_DATE = "clf_final_rf_v1", "2025-12-31"
MODEL_TYPES = ["약국", "의원", "이용업", "미용업", "식육판매업", "체육도장업", "목욕장업"]
FORECAST_MODELS = ["linear", "regression"]
SCENARIOS = ["low", "mid", "high"]
EVAL_SETS = ["cv", "time", "region", "external", "diag"]
KINDS = {"main": "주 결과", "sens": "민감도", "popfc": "인구 예측"}
TOP_N_DEFAULT, TOP_N_MAX = 50, 1000

# ---------------------------------------------------------------- 공통
SQL_RESOLVE_REGION = """
SELECT DISTINCT r.region_id, r.sido, r.sigungu, a.alias_name,
       CASE WHEN a.alias_name = %s THEN 0
            WHEN RIGHT(a.alias_name, CHAR_LENGTH(%s)) = %s THEN 1 ELSE 2 END AS rank_no
FROM region_alias a JOIN region r ON r.region_id = a.region_id
WHERE INSTR(a.alias_name, %s) > 0
ORDER BY rank_no, r.region_id
"""

SQL_ALIAS_LIST = """
SELECT a.alias_name, r.sigungu, r.region_id FROM region_alias a JOIN region r ON r.region_id = a.region_id
"""


def resolve_region(conn, text):
    """시군명(별칭 포함)을 region_id로. 정확히 일치(순위 0), 끝이 일치(1, 예: '공주시'), 부분 일치(2) 순으로 돌려준다"""
    text = (text or "").strip()
    if not text or len(text) > 50:
        raise ValueError("시군명은 1~50자로 입력하세요.")
    return fetch(conn, SQL_RESOLVE_REGION, (text, text, text, text))


def similar_names(conn, text, n=3):
    """없는 이름일 때 비슷한 이름 n개 (region_alias의 별칭·시군 이름과 글자 비교)"""
    al = fetch(conn, SQL_ALIAS_LIST)
    names = sorted(set(al.alias_name) | set(al.sigungu))
    return difflib.get_close_matches((text or "").strip(), names, n=n, cutoff=0.4)


def pick_region(conn, text):
    """(region_id 또는 None, 안내 글). 한 시군으로 정해지면 그 id, 아니면 후보·비슷한 이름을 안내"""
    cand = resolve_region(conn, text)
    best = cand[cand.rank_no <= 1]
    ids = best.region_id.unique()
    if len(ids) == 1:
        return int(ids[0]), ""
    if len(ids) > 1 or len(cand):
        show = best if len(ids) > 1 else cand
        return None, "여러 곳이 해당됩니다. 정확히 입력하세요: " + ", ".join(sorted(set(show.alias_name))[:8])
    sim = similar_names(conn, text)
    return None, "해당하는 시군이 없습니다." + (" 비슷한 이름: " + ", ".join(sim) if sim else "")


def load_thresholds(path=BASE_RATE):
    """results\\base_rate.csv 에서 업종별 고위험 문턱 = base_rate_3y x 2 를 만든다 (판정은 prob_calibrated 기준).
    파일의 high_risk_threshold_2x 열은 반올림 전 폐업률의 2배라서 4번째 소수가 1 다를 수 있다. 크게(0.001 초과) 다르면 오류로 알린다"""
    d = pd.read_csv(path, encoding="utf-8-sig")
    thr = {r.type_name: round(float(r.base_rate_3y) * 2, 6) for r in d.itertuples()}
    missing = [t for t in MODEL_TYPES if t not in thr]
    if missing or not all(0 < v < 1 for v in thr.values()):
        raise ValueError(f"base_rate.csv 확인 필요: 없는 업종 {missing}, 문턱은 0~1 사이여야 함")
    col = {r.type_name: float(r.high_risk_threshold_2x) for r in d.itertuples()}
    if any(abs(thr[t] - col[t]) > 0.001 for t in MODEL_TYPES):
        raise ValueError("base_rate.csv의 base_rate_3y x 2 와 high_risk_threshold_2x 가 크게 다릅니다. 파일을 확인하세요.")
    return thr


def _need(cond, msg):
    if not cond:
        raise ValueError(msg)


# ---------------------------------------------------------------- F3
SQL_F3 = """
SELECT t.type_name AS 업종, r.sigungu AS 시군, f.facility_id AS 시설번호, f.name AS 사업장명,
       f.emd_name AS 읍면동, f.location_type AS 읍면동구분,
       ROUND(DATEDIFF(cp.base_date, f.permit_date) / 365.25, 1) AS 영업연수,
       cp.prob_raw AS 폐업확률_보정전, cp.prob_calibrated AS 폐업확률_보정후,
       th.thr AS 고위험문턱, (cp.prob_calibrated >= th.thr) AS 고위험
FROM closure_prediction cp
JOIN facility f ON f.facility_id = cp.facility_id
JOIN facility_type t ON t.type_id = f.type_id
JOIN region r ON r.region_id = f.region_id
JOIN (SELECT %s AS type_name, %s AS thr UNION ALL SELECT %s, %s UNION ALL SELECT %s, %s
      UNION ALL SELECT %s, %s UNION ALL SELECT %s, %s UNION ALL SELECT %s, %s UNION ALL SELECT %s, %s) th
  ON th.type_name = t.type_name
WHERE cp.model_version = %s AND cp.base_date = %s
  AND (%s = 0 OR f.region_id = %s)
  AND (%s = '' OR t.type_name = %s)
  AND (%s = 0 OR cp.prob_calibrated >= th.thr)
ORDER BY cp.prob_calibrated DESC, f.facility_id
LIMIT %s
"""


def f3_facility_risk(conn, region_id=0, type_name="", high_risk_only=False, top_n=TOP_N_DEFAULT):
    """F3 시설별 폐업 확률·고위험 시설 목록 (2025년 말 영업 중인 26곳 시설). region_id 0 = 전체 시군, type_name '' = 전체 업종"""
    region_id, top_n = int(region_id), int(top_n)
    _need(region_id >= 0, "region_id는 0 이상이어야 합니다.")
    _need(type_name == "" or type_name in MODEL_TYPES, f"업종은 {MODEL_TYPES} 중 하나이거나 비워 두세요.")
    _need(1 <= top_n <= TOP_N_MAX, f"건수는 1~{TOP_N_MAX} 사이여야 합니다.")
    thr = load_thresholds()
    params = []
    for t in MODEL_TYPES:
        params += [t, thr[t]]
    params += [FINAL_MODEL, FINAL_BASE_DATE, region_id, region_id, type_name, type_name, 1 if high_risk_only else 0, top_n]
    return fetch(conn, SQL_F3, tuple(params))


# ---------------------------------------------------------------- F5
SQL_F5 = """
WITH fc AS (
  SELECT pf.region_id, pf.forecast_year, pf.model_name,
         SUM(pf.forecast_pop) AS total_pop,
         SUM(CASE WHEN pf.sex = 'F' AND a.age_from BETWEEN 20 AND 35 THEN pf.forecast_pop ELSE 0 END) AS female_20_39,
         SUM(CASE WHEN a.age_from >= 65 THEN pf.forecast_pop ELSE 0 END) AS pop_65plus
  FROM population_forecast pf JOIN age_group a ON a.age_group_id = pf.age_group_id
  WHERE pf.region_id = %s AND (%s = '' OR pf.model_name = %s)
  GROUP BY pf.region_id, pf.forecast_year, pf.model_name),
sc AS (SELECT 'low' AS scenario, -1 AS sgn UNION ALL SELECT 'mid', 0 UNION ALL SELECT 'high', 1)
SELECT r.sigungu AS 시군, fc.model_name AS 모델, sc.scenario AS 시나리오, fc.forecast_year AS 연도,
       ROUND(fc.total_pop * (1 + sc.sgn * mp.value / 100)) AS 총인구,
       ROUND(fc.female_20_39 / NULLIF(fc.pop_65plus, 0) * (1 + sc.sgn * mi.value / 100), 4) AS 소멸위험지수,
       mp.value AS 총인구_MAPE, mi.value AS 지수_MAPE
FROM fc
JOIN region r ON r.region_id = fc.region_id
CROSS JOIN sc
JOIN model_evaluation mp ON mp.model_version = CONCAT('popfc_', fc.model_name, '_v1') AND mp.eval_set = 'time'
     AND mp.subgroup = CONCAT('all_h', fc.forecast_year - 2025) AND mp.metric = 'MAPE' AND mp.type_id IS NULL
JOIN model_evaluation mi ON mi.model_version = mp.model_version AND mi.eval_set = 'time'
     AND mi.subgroup = mp.subgroup AND mi.metric = 'MAPE_INDEX' AND mi.type_id IS NULL
WHERE (%s = '' OR sc.scenario = %s)
ORDER BY fc.model_name, sc.sgn, fc.forecast_year
"""


def f5_population_forecast(conn, region_id, model_name="", scenario=""):
    """F5 인구 예측 2026~2028 (총인구, 소멸위험지수). model_name '' = 두 모델 모두, scenario '' = low·mid·high 모두"""
    region_id = int(region_id)
    _need(region_id > 0, "region_id를 먼저 정하세요.")
    _need(model_name == "" or model_name in FORECAST_MODELS, f"모델은 {FORECAST_MODELS} 중 하나이거나 비워 두세요.")
    _need(scenario == "" or scenario in SCENARIOS, f"시나리오는 {SCENARIOS} 중 하나이거나 비워 두세요.")
    return fetch(conn, SQL_F5, (region_id, model_name, model_name, scenario, scenario))


# ---------------------------------------------------------------- F6
SQL_F6 = """
SELECT x.구분, me.model_version AS 모델버전, me.eval_set AS 평가, COALESCE(t.type_name, '전체') AS 업종,
       me.subgroup AS 하위집단, me.n_rows AS 행, me.n_events AS 폐업,
       MAX(CASE WHEN me.metric = 'AUC' THEN me.value END) AS AUC,
       MAX(CASE WHEN me.metric = 'BRIER' THEN me.value END) AS 브라이어,
       MAX(CASE WHEN me.metric = 'F1' THEN me.value END) AS F1,
       MAX(CASE WHEN me.metric = 'RECALL' THEN me.value END) AS 재현율,
       MAX(CASE WHEN me.metric = 'MAPE' THEN me.value END) AS MAPE,
       MAX(CASE WHEN me.metric = 'MAPE_INDEX' THEN me.value END) AS MAPE_지수
FROM model_evaluation me
LEFT JOIN facility_type t ON t.type_id = me.type_id
JOIN (SELECT model_version,
             CASE WHEN LEFT(model_version, 6) = 'popfc_' THEN 'popfc'
                  WHEN RIGHT(model_version, 10) = '_exof_incl' OR RIGHT(model_version, 9) = '_gym_excl'
                       OR RIGHT(model_version, 7) = '_noarea'
                       OR model_version IN ('clf_tm_cmp_v1', 'clf_rg_cmp_v1', 'clf_ex_cmp_v1') THEN 'sens'
                  ELSE 'main' END AS 구분
      FROM model_evaluation GROUP BY model_version) x ON x.model_version = me.model_version
WHERE (%s = '' OR me.eval_set = %s) AND (%s = '' OR COALESCE(t.type_name, '전체') = %s)
  AND (%s = '' OR me.subgroup = %s) AND (%s = '' OR x.구분 = %s)
GROUP BY x.구분, me.model_version, me.eval_set, me.type_id, t.type_name, me.subgroup, me.n_rows, me.n_events
ORDER BY x.구분, me.eval_set, me.model_version, me.type_id, me.subgroup
"""


def f6_model_evaluation(conn, eval_set="", type_name="", subgroup="", kind=""):
    """F6 모델 평가 결과. 각 칸이 '' 이면 전체. kind = main(주 결과) / sens(민감도) / popfc(인구 예측)"""
    _need(eval_set == "" or eval_set in EVAL_SETS, f"평가 종류는 {EVAL_SETS} 중 하나이거나 비워 두세요.")
    _need(type_name == "" or type_name == "전체" or type_name in MODEL_TYPES, f"업종은 {MODEL_TYPES} 또는 '전체'이거나 비워 두세요.")
    _need(len(subgroup) <= 20, "하위집단은 20자 이하입니다.")
    _need(kind == "" or kind in KINDS, f"구분은 {list(KINDS)} 중 하나이거나 비워 두세요.")
    return fetch(conn, SQL_F6, (eval_set, eval_set, type_name, type_name, subgroup, subgroup, kind, kind))


# ---------------------------------------------------------------- 출력·시험용 메뉴
def print_table(df, title="", max_rows=60):
    print(f"\n[{title}] {len(df):,}행" if title else f"\n{len(df):,}행")
    if len(df):
        print(df.head(max_rows).to_string(index=False))
        if len(df) > max_rows:
            print(f"... (앞 {max_rows}행만 보임)")


def _ask(prompt, default=""):
    v = input(f"{prompt}{f' [{default}]' if default != '' else ''}: ").strip()
    return v if v else default


def _ask_region(conn, required):
    while True:
        text = _ask("시군명 (예: 공주시)" + ("" if required else ", 비우면 전체"))
        if not text and not required:
            return 0
        if not text:
            continue
        rid, msg = pick_region(conn, text)
        if rid is not None:
            return rid
        print(msg)


def menu(conn):
    while True:
        print("\n===== 조회 (슬기: F3·F5·F6) =====\n1) F3 시설별 폐업 확률·고위험 시설\n2) F5 인구 예측\n3) F6 모델 평가 결과\n0) 종료")
        c = _ask("번호")
        try:
            if c == "1":
                rid = _ask_region(conn, False)
                typ = _ask("업종 (" + "/".join(MODEL_TYPES) + ", 비우면 전체)")
                hi = _ask("고위험 시설만? (y/n)", "y").lower().startswith("y")
                n = int(_ask(f"보여 줄 건수 (1~{TOP_N_MAX})", str(TOP_N_DEFAULT)))
                print_table(f3_facility_risk(conn, rid, typ, hi, n), "F3")
            elif c == "2":
                rid = _ask_region(conn, True)
                mod = _ask("모델 (linear/regression, 비우면 둘 다)")
                sc = _ask("시나리오 (low/mid/high, 비우면 전부)")
                print_table(f5_population_forecast(conn, rid, mod, sc), "F5")
            elif c == "3":
                es = _ask("평가 종류 (" + "/".join(EVAL_SETS) + ", 비우면 전체)")
                typ = _ask("업종 (비우면 전체, '전체'는 업종 합계 행)")
                sub = _ask("하위집단 (all/metro/other 등, 비우면 전체)")
                kd = _ask("구분 (main=주 결과 / sens=민감도 / popfc=인구 예측, 비우면 전체)")
                print_table(f6_model_evaluation(conn, es, typ, sub, kd), "F6")
            elif c in ("0", "q", "Q"):
                return
        except ValueError as e:
            print("입력 확인:", e)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true", help="공주시 예시를 한 번씩 출력하고 끝냄")
    args = ap.parse_args()
    conn = connect()
    try:
        if args.demo:
            rid, msg = pick_region(conn, "공주시")
            print("공주시 ->", rid, msg)
            print_table(f3_facility_risk(conn, rid, "", True, 5), "F3 공주시 고위험 시설 상위 5곳")
            print_table(f5_population_forecast(conn, rid, "", "mid"), "F5 공주시 mid")
            print_table(f6_model_evaluation(conn, "time", "전체", "all", "main"), "F6 평가 ① 시간 전체 업종 (주 결과)")
        else:
            menu(conn)
    finally:
        conn.close()
