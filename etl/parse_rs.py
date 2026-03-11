"""
RSシステム CSV パーサー
複数のCSVファイルを 予算事業ID で結合し、GovInsight用のデータモデルに変換する。
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd

from config import DIGITAL_AGENCY_NAME


# ---- 列名定数（CSVヘッダーに一致） ------------------------------------

class Col12:  # 1-2 基本情報_事業概要等
    KEY = "予算事業ID"
    YEAR = "事業年度"
    NAME = "事業名"
    MINISTRY = "府省庁"
    DEPT = "局・庁"
    DIV = "課"
    PURPOSE = "事業の目的"
    SITUATION = "現状・課題"
    OVERVIEW = "事業の概要"
    CATEGORY = "事業区分"
    START_YEAR = "事業開始年度"
    END_YEAR = "事業終了（予定）年度"
    URL = "事業概要URL"


class Col21:  # 2-1 予算・執行_サマリ
    KEY = "予算事業ID"
    YEAR = "事業年度"
    BUDGET_YEAR = "予算年度"
    INITIAL = "当初予算（合計）"
    EXPENDITURE = "執行額（合計）"
    EXEC_RATE = "執行率"
    TOTAL = "計（歳出予算現額合計）"
    NOTE = "主な増減理由"


class Col51:  # 5-1 支出先_支出情報
    KEY = "予算事業ID"
    YEAR = "事業年度"
    VENDOR_NAME = "支出先名"
    CORP_NUM = "法人番号"
    AMOUNT = "支出先の合計支出額"
    BLOCK = "支出先ブロック名"
    CONTRACT_TYPE = "契約方式等"


class Col41:  # 4-1 点検・評価
    KEY = "予算事業ID"
    YEAR = "事業年度"
    CHECK_RESULT = "事業所管部局による点検・改善ー点検結果"
    IMPROVEMENT = "事業所管部局による点検・改善ー改善の方向性"
    EXPERT_OPINION = "外部有識者による点検ー所見"
    REVIEW_OPINION = "行政事業レビュー推進チームの所見"
    REFLECT_STATUS = "所見を踏まえた改善点／概算要求における反映状況"


def _read_csv(path: Path) -> pd.DataFrame:
    """エンコーディングを自動判別してCSVを読み込む。"""
    for enc in ("utf-8-sig", "utf-8", "cp932"):
        try:
            return pd.read_csv(path, encoding=enc, dtype=str, low_memory=False)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"CSVの文字コードを判別できません: {path}")


def parse_projects(
    csv_12: Path,
    csv_21: Path,
    csv_51: Path,
    csv_41: Optional[Path] = None,
    ministry_filter: Optional[str] = DIGITAL_AGENCY_NAME,
) -> pd.DataFrame:
    """CSVを結合して事業DataFrameを返す。

    Args:
        csv_12: 1-2_基本情報_事業概要等.csv
        csv_21: 2-1_予算・執行_サマリ.csv
        csv_51: 5-1_支出先_支出情報.csv
        csv_41: 4-1_点検・評価.csv（省略可）
        ministry_filter: None なら全府省庁

    Returns:
        Columnsを持つDataFrame:
          project_id, year, name, ministry, dept, div, purpose, overview,
          start_year, end_year, url, budgets (list), vendors (list),
          evaluations (list, csv_41 がある場合のみ)
    """
    # 1-2 基本情報
    df12 = _read_csv(csv_12)
    if ministry_filter:
        df12 = df12[df12[Col12.MINISTRY] == ministry_filter].copy()
    if df12.empty:
        return pd.DataFrame()

    project_ids = set(df12[Col12.KEY].dropna())

    # 2-1 予算サマリ（同一事業の複数年度分を集約）
    df21 = _read_csv(csv_21)
    df21 = df21[df21[Col21.KEY].isin(project_ids)].copy()
    budgets = _aggregate_budgets(df21)

    # 5-1 支出情報（支出先を集約）
    df51 = _read_csv(csv_51)
    df51 = df51[df51[Col51.KEY].isin(project_ids)].copy()
    vendors = _aggregate_vendors(df51)

    # 結合
    df12 = df12.merge(budgets, on=Col12.KEY, how="left")
    df12 = df12.merge(vendors, on=Col12.KEY, how="left")

    # 4-1 点検・評価（省略可）
    if csv_41 is not None and csv_41.exists():
        df41 = _read_csv(csv_41)
        df41 = df41[df41[Col41.KEY].isin(project_ids)].copy()
        evaluations = _aggregate_evaluations(df41)
        df12 = df12.merge(evaluations, on=Col12.KEY, how="left")

    # 列名を正規化
    df12 = df12.rename(columns={
        Col12.KEY: "project_id",
        Col12.YEAR: "rs_year",
        Col12.NAME: "name",
        Col12.MINISTRY: "ministry",
        Col12.DEPT: "dept",
        Col12.DIV: "div",
        Col12.PURPOSE: "purpose",
        Col12.SITUATION: "situation",
        Col12.OVERVIEW: "overview",
        Col12.CATEGORY: "category",
        Col12.START_YEAR: "start_year",
        Col12.END_YEAR: "end_year",
        Col12.URL: "rs_url",
    })

    keep_cols = [
        "project_id", "rs_year", "name", "ministry", "dept", "div",
        "purpose", "situation", "overview", "category",
        "start_year", "end_year", "rs_url", "budgets", "vendors", "evaluations",
    ]
    return df12[[c for c in keep_cols if c in df12.columns]].reset_index(drop=True)


def _aggregate_budgets(df: pd.DataFrame) -> pd.DataFrame:
    """予算サマリをプロジェクトIDごとにリスト集約。"""
    def to_budget_list(group: pd.DataFrame) -> list[dict]:
        records = []
        for _, row in group.iterrows():
            records.append({
                "budget_year": _to_int(row.get(Col21.BUDGET_YEAR)),
                "initial": _to_float(row.get(Col21.INITIAL)),
                "expenditure": _to_float(row.get(Col21.EXPENDITURE)),
                "exec_rate": _to_float(row.get(Col21.EXEC_RATE)),
                "total": _to_float(row.get(Col21.TOTAL)),
                "note": _strip(row.get(Col21.NOTE)),
            })
        return records

    return (
        df.groupby(Col21.KEY)
        .apply(to_budget_list, include_groups=False)
        .reset_index()
        .rename(columns={0: "budgets", Col21.KEY: Col12.KEY})
    )


def _aggregate_vendors(df: pd.DataFrame) -> pd.DataFrame:
    """支出情報をプロジェクトIDごとにリスト集約。"""
    def to_vendor_list(group: pd.DataFrame) -> list[dict]:
        records = []
        for _, row in group.iterrows():
            name = _strip(row.get(Col51.VENDOR_NAME))
            if not name:
                continue
            records.append({
                "name": name,
                "corporate_number": _strip(row.get(Col51.CORP_NUM)),
                "amount": _to_float(row.get(Col51.AMOUNT)),
                "contract_type": _strip(row.get(Col51.CONTRACT_TYPE)),
                "block": _strip(row.get(Col51.BLOCK)),
            })
        return records

    return (
        df.groupby(Col51.KEY)
        .apply(to_vendor_list, include_groups=False)
        .reset_index()
        .rename(columns={0: "vendors", Col51.KEY: Col12.KEY})
    )


def _aggregate_evaluations(df: pd.DataFrame) -> pd.DataFrame:
    """点検・評価をプロジェクトIDごとにリスト集約。"""
    def to_evaluation_list(group: pd.DataFrame) -> list[dict]:
        records = []
        for _, row in group.iterrows():
            records.append({
                "year": _strip(row.get(Col41.YEAR)),
                "check_result": _strip(row.get(Col41.CHECK_RESULT)),
                "improvement": _strip(row.get(Col41.IMPROVEMENT)),
                "expert_opinion": _strip(row.get(Col41.EXPERT_OPINION)),
                "review_opinion": _strip(row.get(Col41.REVIEW_OPINION)),
                "reflect_status": _strip(row.get(Col41.REFLECT_STATUS)),
            })
        return records

    return (
        df.groupby(Col41.KEY)
        .apply(to_evaluation_list, include_groups=False)
        .reset_index()
        .rename(columns={0: "evaluations", Col41.KEY: Col12.KEY})
    )


# ---- ユーティリティ ---------------------------------------------------

def _strip(val) -> str:
    if pd.isna(val) or val is None:
        return ""
    return str(val).strip()


def _to_int(val) -> int | None:
    try:
        return int(float(str(val)))
    except (ValueError, TypeError):
        return None


def _to_float(val) -> float | None:
    try:
        return float(str(val).replace(",", ""))
    except (ValueError, TypeError):
        return None
