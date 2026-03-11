"""
正規化 JSON 生成
Next.js SSG が消費するデータファイルを public/data/ に出力する。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


def generate_all(
    projects: pd.DataFrame,
    procurements: pd.DataFrame,
    output_dir: Path,
) -> None:
    """全JSONファイルを生成・保存する。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    updated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    _write_json(output_dir / "projects.json", _build_projects(projects, updated_at))
    _write_json(output_dir / "procurements.json", _build_procurements(procurements, updated_at))
    _write_json(output_dir / "vendors.json", _build_vendors(procurements, updated_at))
    _write_json(output_dir / "dashboard.json", _build_dashboard(projects, procurements, updated_at))

    for pid in projects["project_id"]:
        proj_data = projects[projects["project_id"] == pid].iloc[0]
        proj_procs = procurements[procurements["project_id"] == pid] if "project_id" in procurements.columns else pd.DataFrame()
        detail = _build_project_detail(proj_data, proj_procs, updated_at)
        detail_dir = output_dir / "projects"
        detail_dir.mkdir(exist_ok=True)
        _write_json(detail_dir / f"{pid}.json", detail)

    print(f"[Generate] JSON出力完了 → {output_dir}")


# ---- 各JSON構築 ------------------------------------------------------

def _build_projects(df: pd.DataFrame, updated_at: str) -> dict:
    records = []
    for _, row in df.iterrows():
        budgets = row.get("budgets") or []
        vendors = row.get("vendors") or []
        latest_exec_rate, latest_budget = _latest_budget_stats(budgets)
        vendor_summary = _vendor_summary(vendors)
        records.append({
            "id": _s(row.get("project_id")),
            "name": _s(row.get("name")),
            "ministry": _s(row.get("ministry")),
            "dept": _s(row.get("dept")),
            "overview": _s(row.get("overview")),
            "startYear": _s(row.get("start_year")),
            "endYear": _s(row.get("end_year")),
            "rsUrl": _s(row.get("rs_url")),
            "rsYear": _s(row.get("rs_year")),
            "latestExecRate": latest_exec_rate,
            "latestBudget": latest_budget,
            "topVendor": vendor_summary.get("topVendor"),
            "totalRsSpend": vendor_summary.get("totalSpend"),
        })
    return {"updatedAt": updated_at, "items": records}


def _build_project_detail(row, proc_df: pd.DataFrame, updated_at: str) -> dict:
    procurements = []
    for _, p in proc_df.iterrows():
        procurements.append({
            "id": _s(p.get("procurement_id")),
            "name": _s(p.get("name")),
            "awardDate": _s(p.get("award_date")),
            "price": _num(p.get("price")),
            "vendorName": _s(p.get("vendor_name")),
            "corporateNumber": _s(p.get("corporate_number")),
            "bidMethodName": _s(p.get("bid_method_name")),
        })

    budgets = row.get("budgets") or []
    vendors = row.get("vendors") or []
    evaluations = row.get("evaluations") or []

    total_amount = proc_df["price"].sum() if not proc_df.empty and "price" in proc_df.columns else 0
    vendor_count = proc_df["corporate_number"].nunique() if not proc_df.empty and "corporate_number" in proc_df.columns else 0

    latest_exec_rate, latest_budget = _latest_budget_stats(budgets if isinstance(budgets, list) else [])
    vendor_summary = _vendor_summary(vendors if isinstance(vendors, list) else [])

    return {
        "updatedAt": updated_at,
        "id": _s(row.get("project_id")),
        "name": _s(row.get("name")),
        "ministry": _s(row.get("ministry")),
        "dept": _s(row.get("dept")),
        "div": _s(row.get("div")),
        "purpose": _s(row.get("purpose")),
        "situation": _s(row.get("situation")),
        "overview": _s(row.get("overview")),
        "category": _s(row.get("category")),
        "startYear": _s(row.get("start_year")),
        "endYear": _s(row.get("end_year")),
        "rsUrl": _s(row.get("rs_url")),
        "totalAmount": float(total_amount) if pd.notna(total_amount) else 0,
        "vendorCount": int(vendor_count),
        "latestExecRate": latest_exec_rate,
        "latestBudget": latest_budget,
        "vendorSummary": vendor_summary,
        "budgets": budgets if isinstance(budgets, list) else [],
        "rsVendors": vendors if isinstance(vendors, list) else [],
        "evaluations": evaluations if isinstance(evaluations, list) else [],
        "procurements": procurements,
    }


def _build_procurements(df: pd.DataFrame, updated_at: str) -> dict:
    records = []
    for _, row in df.iterrows():
        records.append({
            "id": _s(row.get("procurement_id")),
            "name": _s(row.get("name")),
            "awardDate": _s(row.get("award_date")),
            "price": _num(row.get("price")),
            "ministryCode": _s(row.get("ministry_code")),
            "bidMethodCode": _s(row.get("bid_method_code")),
            "bidMethodName": _s(row.get("bid_method_name")),
            "vendorName": _s(row.get("vendor_name")),
            "corporateNumber": _s(row.get("corporate_number")),
            "projectId": _s(row.get("project_id")),
            "fiscalYear": _num(row.get("fiscal_year")),
        })
    return {"updatedAt": updated_at, "items": records}


def _build_vendors(df: pd.DataFrame, updated_at: str) -> dict:
    if df.empty or "corporate_number" not in df.columns:
        return {"updatedAt": updated_at, "items": []}

    agg = (
        df.groupby("corporate_number")
        .agg(
            name=("vendor_name", "last"),
            total_amount=("price", "sum"),
            count=("procurement_id", "count"),
            procurement_ids=("procurement_id", list),
        )
        .reset_index()
        .sort_values("total_amount", ascending=False)
    )

    records = []
    for _, row in agg.iterrows():
        records.append({
            "corporateNumber": _s(row["corporate_number"]),
            "name": _s(row["name"]),
            "totalAmount": float(row["total_amount"]) if pd.notna(row["total_amount"]) else 0,
            "count": int(row["count"]),
            "procurementIds": row["procurement_ids"],
        })

    return {"updatedAt": updated_at, "items": records}


def _build_dashboard(projects: pd.DataFrame, procurements: pd.DataFrame, updated_at: str) -> dict:
    total_amount = float(procurements["price"].sum()) if not procurements.empty and "price" in procurements.columns else 0
    vendor_count = procurements["corporate_number"].nunique() if not procurements.empty else 0

    # 月別落札額・件数（配列形式）
    monthly_awards: list[dict] = []
    if not procurements.empty and "award_date" in procurements.columns:
        agg = (
            procurements.dropna(subset=["award_date"])
            .assign(month=lambda d: d["award_date"].str[:7])
            .groupby("month")
            .agg(count=("procurement_id", "count"), amount=("price", "sum"))
            .reset_index()
            .sort_values("month")
        )
        for _, row in agg.iterrows():
            monthly_awards.append({
                "month": row["month"],
                "count": int(row["count"]),
                "amount": float(row["amount"]) if pd.notna(row["amount"]) else 0,
            })

    # 入札方式別集計（配列形式）
    bid_method_summary: list[dict] = []
    if not procurements.empty and "bid_method_name" in procurements.columns:
        bm = (
            procurements.groupby("bid_method_name")
            .agg(count=("procurement_id", "count"), total=("price", "sum"))
            .reset_index()
            .sort_values("count", ascending=False)
        )
        for _, row in bm.iterrows():
            bid_method_summary.append({
                "method": str(row["bid_method_name"]),
                "count": int(row["count"]),
                "amount": float(row["total"]) if pd.notna(row["total"]) else 0,
            })

    return {
        "updatedAt": updated_at,
        "summary": {
            "projectCount": len(projects),
            "procurementCount": len(procurements),
            "totalAmount": total_amount,
            "vendorCount": int(vendor_count),
        },
        "monthlyAwards": monthly_awards,
        "bidMethodSummary": bid_method_summary,
    }


# ---- 集計ヘルパー -------------------------------------------------------

def _latest_budget_stats(budgets: list[dict]) -> tuple[float | None, float | None]:
    """budgets リストから最新年度の執行率・当初予算を返す。"""
    if not budgets:
        return None, None
    valid = [b for b in budgets if b.get("budget_year") is not None]
    if not valid:
        return None, None
    latest = max(valid, key=lambda b: b["budget_year"])
    return latest.get("exec_rate"), latest.get("initial")


def _vendor_summary(vendors: list[dict]) -> dict:
    """RS 5-1 vendors リストから支出集中度サマリを生成する。

    Returns:
        {totalSpend, topVendor, topVendorAmount, concentration, vendorCount}
        concentration: TOP1ベンダーの支出シェア（0〜100%）
    """
    if not vendors:
        return {"totalSpend": None, "topVendor": None, "topVendorAmount": None,
                "concentration": None, "vendorCount": 0}

    total = sum(v.get("amount") or 0 for v in vendors)
    by_vendor: dict[str, float] = {}
    for v in vendors:
        name = v.get("name") or ""
        amt = v.get("amount") or 0
        by_vendor[name] = by_vendor.get(name, 0) + amt

    top_name = max(by_vendor, key=lambda k: by_vendor[k]) if by_vendor else None
    top_amount = by_vendor.get(top_name, 0) if top_name else 0
    concentration = round(top_amount / total * 100, 1) if total > 0 else None

    return {
        "totalSpend": total if total > 0 else None,
        "topVendor": top_name,
        "topVendorAmount": top_amount if top_amount > 0 else None,
        "concentration": concentration,
        "vendorCount": len(by_vendor),
    }


# ---- ユーティリティ -------------------------------------------------------

def _s(val) -> str:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ""
    return str(val).strip()


def _num(val) -> float | None:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


class _NaNSafeEncoder(json.JSONEncoder):
    """float NaN/Inf を null に変換する JSON エンコーダー。"""

    def iterencode(self, o, _one_shot=False):
        # 標準の iterencode は NaN をそのまま出力するので再帰的に置換
        return super().iterencode(self._clean(o), _one_shot)

    def _clean(self, obj):
        if isinstance(obj, float):
            import math
            return None if (math.isnan(obj) or math.isinf(obj)) else obj
        if isinstance(obj, dict):
            return {k: self._clean(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self._clean(v) for v in obj]
        return obj


def _write_json(path: Path, data: dict | list) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, cls=_NaNSafeEncoder)
    size = path.stat().st_size / 1024
    print(f"  → {path.name} ({size:.1f}KB)")
