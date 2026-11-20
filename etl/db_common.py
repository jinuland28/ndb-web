# -*- coding: utf-8 -*-
r"""
db_common.py  —  분석 코드가 DB와 주고받을 때 쓰는 공통 함수 (삽입 SQL 2·3단계)
쓰는 법 :
    from db_common import connect, fetch, save, replace_version
    conn = connect()                                   # 비밀번호는 실행할 때 입력
    df = fetch(conn, "SELECT * FROM v_panel WHERE base_year = %s", (2015,))
    save(conn, "risk_band", band_df)                   # 같은 키면 덮어씀
    replace_version(conn, "model_evaluation", "cv_v1", eval_df)   # 버전째 지우고 다시 넣음
규칙   : 값이 들어가는 SQL은 모두 Prepared Statement(cursor(prepared=True))로 실행
         비밀번호를 코드에 쓰지 않음 (getpass로 입력, 같은 실행 안에서는 한 번만 물음)
준비   : pip install pandas mysql-connector-python  (MySQL 8.0.19 이상)
"""
import getpass
import math
import os
from datetime import date, datetime
from decimal import Decimal

import pandas as pd
import mysql.connector

DB_NAME = "ndb_project"
_password = None          # 같은 실행 안에서 비밀번호를 다시 묻지 않으려고 기억 (파일에는 안 남음)


def connect(database=DB_NAME):
    """MySQL 접속. autocommit은 끔 (save가 직접 commit/rollback)"""
    global _password
    if _password is None:
        # run_all.py가 처음에 한 번 물어 자식 프로세스에만 넘겨 준 값 (파일·코드에는 저장하지 않음). 없으면 지금처럼 물음
        _password = os.environ.get("NDB_MYSQL_PW") or getpass.getpass("MySQL root 비밀번호: ")
    conn = mysql.connector.connect(host="localhost", port=3306, user="root",
                                   password=_password, database=database,
                                   charset="utf8mb4")
    conn.autocommit = False
    return conn


def _py(v):
    """pandas/numpy 값을 드라이버가 받는 파이썬 값으로 (NaN·NaT → NULL)"""
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    if v is pd.NaT:
        return None
    if isinstance(v, pd.Timestamp):
        return v.to_pydatetime()
    if hasattr(v, "item"):            # numpy.int64, numpy.float64 등
        v = v.item()
        if isinstance(v, float) and math.isnan(v):
            return None
    return v


def fetch(conn, sql, params=()):
    """SELECT 결과를 DataFrame으로. 값은 %s 자리로만 넘김 (Prepared Statement)"""
    cur = conn.cursor(prepared=True)
    try:
        cur.execute(sql, tuple(_py(p) for p in params))
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
    finally:
        cur.close()
    df = pd.DataFrame(rows, columns=cols)
    # DECIMAL은 Decimal로 오므로 계산하기 쉽게 float로 바꿈 (날짜는 그대로)
    for c in df.columns:
        if df[c].map(lambda x: isinstance(x, Decimal)).any():
            df[c] = pd.to_numeric(df[c])
    return df


def _insert_sql(table, cols, upsert):
    col_list = ", ".join(cols)
    marks = ", ".join(["%s"] * len(cols))
    sql = f"INSERT INTO {table} ({col_list}) VALUES ({marks})"
    if upsert:
        # MySQL 8.0.19+ 별칭 문법 (VALUES() 함수는 8.0.20부터 사용 중단 예고)
        sets = ", ".join(f"{c} = new.{c}" for c in cols)
        sql += f" AS new ON DUPLICATE KEY UPDATE {sets}"
    return sql


def save(conn, table, df, upsert=True):
    """df의 열 이름 = 표의 컬럼 이름. 같은 기본키/유일키면 덮어씀. 한 트랜잭션.
    돌려주는 값: 넣은 행 수"""
    if df is None or len(df) == 0:
        print(f"  [save] {table}: 넣을 행 없음")
        return 0
    cols = list(df.columns)
    rows = [tuple(_py(v) for v in r) for r in df.itertuples(index=False, name=None)]
    cur = conn.cursor(prepared=True)
    try:
        cur.executemany(_insert_sql(table, cols, upsert), rows)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
    print(f"  [save] {table}: {len(rows)}행 저장")
    return len(rows)


def replace_version(conn, table, model_version, df):
    """같은 model_version 행을 지우고 df를 넣음 (한 트랜잭션).
    model_evaluation처럼 유일키에 NULL(type_id = 전체)이 들어가 ON DUPLICATE KEY가 안 먹는 표에 씀"""
    if "model_version" in df.columns and (df["model_version"] != model_version).any():
        raise ValueError("df의 model_version이 인수와 다릅니다")
    cur = conn.cursor(prepared=True)
    try:
        cur.execute(f"DELETE FROM {table} WHERE model_version = %s", (model_version,))
        deleted = cur.rowcount
        if len(df):
            cur.executemany(_insert_sql(table, list(df.columns), upsert=False),
                            [tuple(_py(v) for v in r) for r in df.itertuples(index=False, name=None)])
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
    print(f"  [replace_version] {table} {model_version}: 지움 {deleted}행, 넣음 {len(df)}행")
    return len(df)
