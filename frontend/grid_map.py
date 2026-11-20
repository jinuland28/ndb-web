# -*- coding: utf-8 -*-
"""Q1 격자 지도: 충청 26곳을 같은 크기의 칸으로 그리는 HTML (Streamlit 없이도 시험 가능하게 분리)
칸 위치는 60_figures.py의 TILE과 같다. 색은 fig6과 같은 규칙 (등급 색 / 위험 업종 수 진하기)
"""
from html import escape

TILE = {  # (열, 행): 대략적인 위치. 왼쪽 충남, 오른쪽 충북, 위가 북쪽 (60_figures.py와 같음)
    "서산시": (1, 0), "당진시": (2, 0), "아산시": (3, 0), "천안시": (4, 0), "진천군": (5, 0), "음성군": (6, 0),
    "충주시": (7, 0), "제천시": (8, 0),
    "태안군": (0, 1), "홍성군": (1, 1), "예산군": (2, 1), "증평군": (5, 1), "괴산군": (6, 1), "단양군": (8, 1),
    "보령시": (1, 2), "청양군": (2, 2), "공주시": (3, 2), "청주시": (5, 2), "보은군": (6, 2),
    "서천군": (1, 3), "부여군": (2, 3), "논산시": (3, 3), "계룡시": (4, 3), "옥천군": (5, 3), "영동군": (6, 3),
    "금산군": (4, 4),
}
PLACEHOLDER = {"세종": (4, 1), "대전": (4, 2)}   # 분석 대상이 아닌 자리: 위치 기준점으로만 점선 칸 표시
GRADES = ["위험", "주의", "안전", "판단 보류"]
GRADE_BG = {"위험": "#d64545", "주의": "#f2a93b", "안전": "#2e9e44", "판단 보류": "#e1e0d9"}
GRADE_FG = {"위험": "#ffffff", "주의": "#1f1f1f", "안전": "#ffffff", "판단 보류": "#555555"}
SEQ = ["#eef3fb", "#d4e2f5", "#a9c5eb", "#7ea8e0", "#4f86d0", "#2f67b8", "#1f4e96", "#163a70"]  # 위험 업종 0~7개


def short(name):
    """서산시 -> 서산"""
    return name[:-1] if name[-1:] in ("시", "군") else name


def missing_tiles(sigungu_list):
    """DB 시군 이름 중 TILE에 위치가 없는 것 (이름이 다르면 지도에서 빠지므로 화면에 알린다)"""
    return sorted(set(sigungu_list) - set(TILE))


def grid_html(diag, type_name, selected, roles):
    """diag: f6_risk_diagnosis 결과 (열: 시군, 업종, 위험등급). type_name '' = 전체 업종 (위험 업종 수로 칠함)
    selected: 강조할 시군 이름, roles: {시군: 'train'/'diagnose'} (인구감소 15곳은 흐리게)"""
    if type_name:
        g = diag[diag["업종"] == type_name].set_index("시군")["위험등급"].to_dict()
    else:
        n_risk = diag[diag["위험등급"] == "위험"].groupby("시군").size().to_dict()

    cells = []
    for s, (cx, cy) in TILE.items():
        dim = roles.get(s) == "train"
        if type_name:
            grade = g.get(s)
            bg = GRADE_BG.get(grade, "#ffffff")
            fg = GRADE_FG.get(grade, "#999999")
            label = "보류" if grade == "판단 보류" else (grade or "-")
        elif dim:                       # fig6과 같게: 인구감소 15곳은 위험 업종 수를 세지 않음 (진단 대상 아님)
            bg, fg, label = "#e1e0d9", "#555555", ""
        else:
            n = int(n_risk.get(s, 0))
            bg = SEQ[min(n, len(SEQ) - 1)]
            fg = "#ffffff" if n >= 4 else "#1f1f1f"
            label = f"위험 {n}개"
        border = "3px solid #111111" if s == selected else "1px solid #ffffff"
        cells.append(
            f'<div style="grid-column:{cx + 1};grid-row:{cy + 1};background:{bg};color:{fg};'
            f'opacity:{0.45 if dim else 1};border:{border};border-radius:4px;'
            f'display:flex;flex-direction:column;align-items:center;justify-content:center;'
            f'height:58px;font-size:13px;line-height:1.25;">'
            f'<b>{escape(short(s))}</b><span style="font-size:11px">{escape(label)}</span></div>'
        )

    for name, (cx, cy) in PLACEHOLDER.items():
        cells.append(
            f'<div style="grid-column:{cx + 1};grid-row:{cy + 1};border:1px dashed #999999;border-radius:4px;'
            f'color:#999999;display:flex;flex-direction:column;align-items:center;justify-content:center;'
            f'height:58px;font-size:12px;line-height:1.25;">'
            f'<span>{escape(name)}</span><span style="font-size:10px">분석 제외</span></div>'
        )

    if type_name:
        legend = "".join(
            f'<span style="display:inline-block;width:12px;height:12px;background:{GRADE_BG[k]};'
            f'margin:0 4px 0 12px;vertical-align:middle"></span>{k}' for k in GRADES)
    else:
        legend = ('<span style="display:inline-block;width:80px;height:12px;vertical-align:middle;'
                  f'background:linear-gradient(to right,{SEQ[0]},{SEQ[-1]});margin:0 6px"></span>'
                  '위험 업종 수 0 → 7')
    note = ("흐린 칸 = 인구감소 15곳(진단 대상 아님). 굵은 테두리 = 선택한 시군. 점선 칸 = 위치 참고용(세종·대전, 분석 대상 아님). "
            "칸 위치는 대략적인 지리 배치이며 면적과 무관.")
    # 흰 바탕 판 위에 그린다: 어두운 테마에서도 흐린 칸이 '옅게' 보이도록 (fig6과 같은 모양)
    return (
        '<div style="background:#ffffff;color:#1f1f1f;padding:10px;border-radius:8px;">'
        '<div style="display:grid;grid-template-columns:repeat(9,1fr);grid-template-rows:repeat(5,58px);gap:4px;">'
        + "".join(cells) + "</div>"
        + f'<div style="font-size:12px;margin-top:8px">{legend}</div>'
        + f'<div style="font-size:11px;color:#666;margin-top:4px">{note}</div>'
        + "</div>"
    )
