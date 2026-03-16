"""
正規化 JSON 生成
Next.js SSG が消費するデータファイルを public/data/ に出力する。
"""
from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


def _safe_float(val) -> float:
    """None/NaN/Inf を 0.0 に丸める浮動小数点変換。"""
    if val is None:
        return 0.0
    try:
        f = float(val)
        return 0.0 if (math.isnan(f) or math.isinf(f)) else f
    except (ValueError, TypeError):
        return 0.0


# ---- ベンダー分類定義 -------------------------------------------------------

# クラウドプラットフォーム名 → 検索パターン（小文字）
_CLOUD_PLATFORMS: dict[str, list[str]] = {
    "AWS": ["アマゾンウェブサービス", "amazon web services"],
    "Google Cloud": ["グーグル・クラウド", "google cloud", "グーグル合同会社"],
    "Azure": ["日本マイクロソフト", "microsoft azure", "azure"],
    "Oracle Cloud": ["日本オラクル", "oracle corporation"],
    "Salesforce": ["セールスフォース", "salesforce"],
    "SAP": ["sap ジャパン", "sap japan"],
}

# GSSはMicrosoft 365ベース（Office/Teams/SharePoint等）であり
# Azure IaaS/PaaSとは別物。プロジェクト名で判定して分離する。
_GSS_PROJECT_PATTERN = re.compile(r"ガバメントソリューションサービス|ＧＳＳ|GSS")

# ベンダーカテゴリ → 検索パターン（小文字）
_VENDOR_CATEGORIES: list[tuple[str, list[str]]] = [
    ("外資クラウド", ["アマゾンウェブサービス", "グーグル・クラウド", "グーグル合同", "日本マイクロソフト", "日本オラクル", "セールスフォース", "sap ジャパン"]),
    ("外資コンサル", ["アクセンチュア", "pwcコンサルティング", "デロイト", "kpmg", "ibmジャパン", "ibm japan", "ボストン コンサルティング"]),
    ("国内大手SI", ["富士通", "日本電気", "ｎｅｃ", "日立", "ｎｔｔデータ", "nttデータ", "ＮＴＴデータ"]),
    ("国内通信", ["ｎｔｔ東日本", "ｎｔｔ西日本", "ｋｄｄｉ", "ｓｂテクノロジー", "ソフトバンク", "さくらインターネット"]),
    ("国内コンサル・ベンダー", ["フューチャーアーキテクト", "野村総合研究", "電通国際情報", "伊藤忠テクノ", "みずほ情報", "大和総研"]),
]


_GOV_ENTITY_PATTERN = re.compile(
    r"(?:省$|庁$|局$|県$|市$|町$|村$|府$|国$|政府$|国立|独立行政法人|地方公共団体|都道府県)"
)
# 汎用プレースホルダーや非商業エンティティ
_GENERIC_NAMES = frozenset(["民間企業等", "民間企業", "その他支出先", "不明", ""])


def _is_gov_entity(name: str) -> bool:
    """支出先名が政府・自治体・独法・汎用プレースホルダー等であれば True。"""
    if name in _GENERIC_NAMES:
        return True
    return bool(_GOV_ENTITY_PATTERN.search(name))


def _classify_cloud_platform(name: str) -> str | None:
    """ベンダー名からクラウドプラットフォーム名を返す（非クラウドはNone）。"""
    n = name.lower()
    for platform, patterns in _CLOUD_PLATFORMS.items():
        if any(p in n for p in patterns):
            return platform
    return None


def _classify_vendor_category(name: str) -> str:
    """ベンダー名からカテゴリ名を返す（デフォルト: その他）。"""
    n = name.lower()
    for category, patterns in _VENDOR_CATEGORIES:
        if any(p in n for p in patterns):
            return category
    return "その他"


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
    _write_json(output_dir / "vendor_analysis.json", _build_vendor_analysis(projects, procurements, updated_at))
    _write_json(output_dir / "risk.json", _build_risk_analysis(procurements, updated_at))
    _write_json(output_dir / "trends.json", _build_trends(procurements, updated_at))

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


# ---- ベンダー分析 -------------------------------------------------------

def _build_vendor_analysis(projects: pd.DataFrame, procurements: pd.DataFrame, updated_at: str) -> dict:
    """RS 5-1 支出データと調達データからベンダー依存分析JSONを生成する。"""

    # ── RS 5-1 ベンダー集計 ──────────────────────────────────────
    rs_by_vendor: dict[str, dict] = {}  # name -> {amount, project_ids, contract_types}

    for _, row in projects.iterrows():
        vendors = row.get("vendors") or []
        pid = str(row.get("project_id") or "")
        pname = str(row.get("name") or "")
        for v in vendors:
            vname = (v.get("name") or "").strip()
            if not vname:
                continue
            amt = _safe_float(v.get("amount"))
            # Microsoft のうち GSS 事業（M365 基盤）は Azure と分離して集計
            cloud_platform = _classify_cloud_platform(vname)
            if cloud_platform == "Azure" and _GSS_PROJECT_PATTERN.search(pname):
                cloud_platform = "Microsoft 365 (GSS)"
            # rs_by_vendor のキー: 通常はベンダー名、GSS配下はプラットフォーム名で分離
            key = vname if cloud_platform != "Microsoft 365 (GSS)" else f"{vname}__GSS"
            if key not in rs_by_vendor:
                rs_by_vendor[key] = {
                    "name": vname,
                    "amount": 0.0,
                    "project_ids": set(),
                    "contract_types": [],
                    "cloud_platform": cloud_platform,
                    "category": _classify_vendor_category(vname),
                }
            rs_by_vendor[key]["amount"] += amt
            rs_by_vendor[key]["project_ids"].add(pid)
            ct = v.get("contract_type") or ""
            if ct:
                rs_by_vendor[key]["contract_types"].append(ct)

    total_rs_spend = sum(v["amount"] for v in rs_by_vendor.values())

    # ── TOP ベンダーリスト（RS支出順）──────────────────────────────
    # 政府機関（省・庁・局等）を除いたベンダーリスト
    commercial_vendors = [v for v in rs_by_vendor.values() if not _is_gov_entity(v["name"])]
    sorted_vendors = sorted(commercial_vendors, key=lambda x: x["amount"], reverse=True)
    # 集中度は政府機関を除いた商業ベンダーの合計で計算
    commercial_total = sum(v["amount"] for v in commercial_vendors)

    top_vendors = []
    for v in sorted_vendors[:30]:
        total = v["amount"]
        cts = v["contract_types"]
        # 随意契約率（競争性なし・随意契約を含む行の割合）
        single_bid_count = sum(
            1 for c in cts
            if any(kw in c for kw in ["随意契約", "一者", "随契"])
        )
        single_bid_rate = round(single_bid_count / len(cts) * 100, 1) if cts else None
        top_vendors.append({
            "name": v["name"],
            "category": v["category"],
            "cloudPlatform": v["cloud_platform"],
            "totalAmount": total if total > 0 else None,
            "projectCount": len(v["project_ids"]),
            "share": round(total / commercial_total * 100, 2) if commercial_total > 0 else None,
            "singleBidRate": single_bid_rate,
        })

    # ── クラウドプラットフォーム分析 ────────────────────────────────
    cloud_by_platform: dict[str, dict] = {}
    for v in rs_by_vendor.values():
        p = v["cloud_platform"]
        if not p:
            continue
        # M365 (GSS) はクラウドプラットフォーム分析から除外（ライセンス費用であり IaaS/PaaS ではない）
        if p == "Microsoft 365 (GSS)":
            continue
        if p not in cloud_by_platform:
            cloud_by_platform[p] = {"platform": p, "amount": 0.0, "count": 0, "vendors": []}
        cloud_by_platform[p]["amount"] += v["amount"]
        cloud_by_platform[p]["count"] += len(v["project_ids"])
        cloud_by_platform[p]["vendors"].append(v["name"])

    total_cloud = sum(v["amount"] for v in cloud_by_platform.values())
    total_cloud_count = sum(v["count"] for v in cloud_by_platform.values())
    cloud_platforms = []
    for p in sorted(cloud_by_platform.values(), key=lambda x: x["amount"], reverse=True):
        cloud_platforms.append({
            "platform": p["platform"],
            "amount": p["amount"] if p["amount"] > 0 else None,
            "projectCount": p["count"],
            "share": round(p["amount"] / total_cloud * 100, 1) if total_cloud > 0 else None,
            "countShare": round(p["count"] / total_cloud_count * 100, 1) if total_cloud_count > 0 else None,
            "vendors": list(set(p["vendors"])),
        })

    # ── カテゴリ別内訳 ──────────────────────────────────────────
    cat_totals: dict[str, float] = {}
    cat_counts: dict[str, int] = {}
    for v in rs_by_vendor.values():
        cat = v["category"]
        cat_totals[cat] = cat_totals.get(cat, 0.0) + v["amount"]
        cat_counts[cat] = cat_counts.get(cat, 0) + len(v["project_ids"])

    total_cat_count = sum(cat_counts.values())
    category_breakdown = []
    for cat, amt in sorted(cat_totals.items(), key=lambda x: x[1], reverse=True):
        cnt = cat_counts.get(cat, 0)
        category_breakdown.append({
            "category": cat,
            "totalAmount": amt if amt > 0 else None,
            "projectCount": cnt,
            "share": round(amt / total_rs_spend * 100, 1) if total_rs_spend > 0 else None,
            "countShare": round(cnt / total_cat_count * 100, 1) if total_cat_count > 0 else None,
        })

    # ── 集中度指標 ──────────────────────────────────────────────
    amounts = [v["amount"] for v in sorted_vendors]
    def top_share(n: int) -> float | None:
        if not amounts or commercial_total <= 0:
            return None
        return round(sum(amounts[:n]) / commercial_total * 100, 1)

    # HHI (Herfindahl-Hirschman Index) 0-10000
    hhi = None
    if commercial_total > 0:
        hhi = round(sum((a / commercial_total * 100) ** 2 for a in amounts))

    # ── 調達データ側のベンダー統計（随意契約率 etc.）──────────────
    proc_vendor_stats: list[dict] = []
    if not procurements.empty and "corporate_number" in procurements.columns:
        pv = (
            procurements.groupby("corporate_number")
            .agg(
                name=("vendor_name", "last"),
                total_amount=("price", "sum"),
                count=("procurement_id", "count"),
                bid_methods=("bid_method_name", list),
            )
            .reset_index()
            .sort_values("total_amount", ascending=False)
        )
        for _, row in pv.head(20).iterrows():
            bids = row["bid_methods"]
            no_competition = sum(
                1 for b in bids
                if any(kw in str(b) for kw in ["随意", "一者応札", "競争性のない"])
            )
            proc_vendor_stats.append({
                "corporateNumber": str(row["corporate_number"]),
                "name": str(row["name"]),
                "category": _classify_vendor_category(str(row["name"])),
                "totalAmount": float(row["total_amount"]) if pd.notna(row["total_amount"]) else 0,
                "count": int(row["count"]),
                "noCompetitionRate": round(no_competition / len(bids) * 100, 1) if bids else None,
            })

    return {
        "updatedAt": updated_at,
        "totalRsSpend": total_rs_spend if total_rs_spend > 0 else None,
        "totalCloudSpend": total_cloud if total_cloud > 0 else None,
        "cloudShare": round(total_cloud / total_rs_spend * 100, 1) if total_rs_spend > 0 and total_cloud > 0 else None,
        "cloudPlatforms": cloud_platforms,
        "categoryBreakdown": category_breakdown,
        "topVendors": top_vendors,
        "procurementVendors": proc_vendor_stats,
        "concentrationMetrics": {
            "top3Share": top_share(3),
            "top5Share": top_share(5),
            "top10Share": top_share(10),
            "hhi": hhi,
            "vendorCount": len(rs_by_vendor),
        },
    }


# ---- ロックインリスク分析 -----------------------------------------------

def _is_no_competition(method: str) -> bool:
    """入札方式が競争性なし（随意契約・一者応札等）かどうかを判定する。"""
    return any(kw in str(method) for kw in ["随意", "一者応札", "競争性のない", "プロポーザル"])


def _build_risk_analysis(procurements: pd.DataFrame, updated_at: str) -> dict:
    """随意契約・ロックインリスク分析JSONを生成する。"""
    if procurements.empty:
        return {"updatedAt": updated_at, "summary": {}, "riskVendors": [], "bigContracts": [], "methodSummary": []}

    procs = procurements.copy()
    procs["is_no_comp"] = procs["bid_method_name"].apply(_is_no_competition)

    total_amount = float(procs["price"].sum())
    no_comp_procs = procs[procs["is_no_comp"]]
    comp_procs = procs[~procs["is_no_comp"]]
    no_comp_amount = float(no_comp_procs["price"].sum())
    no_comp_rate = round(no_comp_amount / total_amount * 100, 1) if total_amount > 0 else 0

    # ── ベンダー別リスクスコア ────────────────────────────────────
    vendor_risk = (
        no_comp_procs.groupby("corporate_number")
        .agg(
            name=("vendor_name", "last"),
            no_comp_amount=("price", "sum"),
            no_comp_count=("procurement_id", "count"),
        )
        .reset_index()
    )
    vendor_total = (
        procs.groupby("corporate_number")
        .agg(total_amount=("price", "sum"), total_count=("procurement_id", "count"))
        .reset_index()
    )
    vm = vendor_risk.merge(vendor_total, on="corporate_number", how="left")
    vm["no_comp_rate"] = (vm["no_comp_amount"] / vm["total_amount"] * 100).round(1)
    # ロックインリスクスコア = 随意契約額（億円） × 随意契約率（%）
    vm["lock_in_score"] = (vm["no_comp_amount"] / 1e8 * vm["no_comp_rate"]).round(1)
    vm = vm.sort_values("lock_in_score", ascending=False)

    risk_vendors = []
    for _, row in vm.head(25).iterrows():
        risk_vendors.append({
            "corporateNumber": str(row["corporate_number"]),
            "name": str(row["name"]),
            "category": _classify_vendor_category(str(row["name"])),
            "noCompAmount": float(row["no_comp_amount"]),
            "noCompRate": float(row["no_comp_rate"]),
            "totalAmount": float(row["total_amount"]),
            "noCompCount": int(row["no_comp_count"]),
            "totalCount": int(row["total_count"]),
            "lockInScore": float(row["lock_in_score"]),
        })

    # ── 大型随意契約案件（1億円以上）────────────────────────────
    big_no_comp = no_comp_procs[no_comp_procs["price"] >= 1e8].sort_values("price", ascending=False)
    big_contracts = []
    for _, row in big_no_comp.head(50).iterrows():
        fy = row.get("fiscal_year")
        big_contracts.append({
            "id": str(row.get("procurement_id", "")),
            "name": str(row.get("name", "")),
            "vendorName": str(row.get("vendor_name", "")),
            "price": float(row["price"]),
            "bidMethodName": str(row.get("bid_method_name", "")),
            "awardDate": str(row.get("award_date", "") or ""),
            "projectId": str(row.get("project_id", "") or ""),
            "fiscalYear": int(fy) if fy is not None and pd.notna(fy) else None,
            "category": _classify_vendor_category(str(row.get("vendor_name", ""))),
        })

    # ── 入札方式別サマリー ─────────────────────────────────────────
    method_rows = []
    for method, grp in procs.groupby("bid_method_name"):
        method_rows.append({
            "method": str(method),
            "count": int(len(grp)),
            "amount": float(grp["price"].sum()),
            "isNoComp": _is_no_competition(str(method)),
        })
    method_rows.sort(key=lambda x: x["amount"], reverse=True)

    # ── 価格帯別随意契約分布 ─────────────────────────────────────
    def price_tier(price: float) -> str:
        if price >= 10e8:   return "10億円以上"
        if price >= 1e8:    return "1〜10億円"
        if price >= 1000e4: return "1千万〜1億円"
        return "1千万円未満"

    tier_dist: dict[str, dict] = {}
    for _, row in no_comp_procs.iterrows():
        t = price_tier(float(row["price"]))
        if t not in tier_dist:
            tier_dist[t] = {"tier": t, "count": 0, "amount": 0.0}
        tier_dist[t]["count"] += 1
        tier_dist[t]["amount"] += float(row["price"])
    tiers_order = ["10億円以上", "1〜10億円", "1千万〜1億円", "1千万円未満"]
    price_distribution = [tier_dist[t] for t in tiers_order if t in tier_dist]

    return {
        "updatedAt": updated_at,
        "summary": {
            "totalAmount": total_amount,
            "noCompAmount": no_comp_amount,
            "compAmount": float(comp_procs["price"].sum()),
            "noCompRate": no_comp_rate,
            "noCompCount": int(len(no_comp_procs)),
            "compCount": int(len(comp_procs)),
            "totalCount": int(len(procs)),
            "bigNoCompCount": int(len(big_no_comp)),
            "bigNoCompAmount": float(big_no_comp["price"].sum()),
            "maxLockInScore": float(vm["lock_in_score"].max()) if not vm.empty else 0,
        },
        "riskVendors": risk_vendors,
        "bigContracts": big_contracts,
        "methodSummary": method_rows,
        "priceDistribution": price_distribution,
    }


# ---- 年度別トレンド分析 -------------------------------------------------

def _build_trends(procurements: pd.DataFrame, updated_at: str) -> dict:
    """年度別・入札方式別・カテゴリ別トレンドJSONを生成する。"""
    if procurements.empty:
        return {"updatedAt": updated_at, "byYear": [], "byYearAndMethod": [], "byYearAndCategory": []}

    procs = procurements.copy()
    procs["fiscal_year"] = pd.to_numeric(procs["fiscal_year"], errors="coerce")
    procs = procs.dropna(subset=["fiscal_year"])
    procs["fiscal_year"] = procs["fiscal_year"].astype(int)
    procs["is_no_comp"] = procs["bid_method_name"].apply(_is_no_competition)
    procs["category"] = procs["vendor_name"].apply(_classify_vendor_category)

    # ── 年度別サマリー ───────────────────────────────────────────
    by_year = []
    for year, grp in procs.groupby("fiscal_year"):
        total = float(grp["price"].sum())
        no_comp = grp[grp["is_no_comp"]]
        no_comp_amt = float(no_comp["price"].sum())

        # トップ3ベンダー
        top3 = grp.groupby("vendor_name")["price"].sum().nlargest(3)

        # ベンダー多様性（Herfindahl）
        vendor_totals = grp.groupby("corporate_number")["price"].sum()
        hhi = round(sum((v / total * 100) ** 2 for v in vendor_totals)) if total > 0 else None

        by_year.append({
            "year": int(year),
            "totalAmount": total,
            "count": int(len(grp)),
            "noCompAmount": no_comp_amt,
            "noCompCount": int(len(no_comp)),
            "noCompRate": round(no_comp_amt / total * 100, 1) if total > 0 else 0,
            "avgContractSize": round(total / len(grp) / 1e4) if len(grp) > 0 else 0,
            "vendorCount": int(grp["corporate_number"].nunique()),
            "hhi": hhi,
            "topVendors": [{"name": k, "amount": float(v)} for k, v in top3.items()],
        })
    by_year.sort(key=lambda x: x["year"])

    # ── 年度×入札方式 ────────────────────────────────────────────
    by_year_method = []
    for (year, method), grp in procs.groupby(["fiscal_year", "bid_method_name"]):
        by_year_method.append({
            "year": int(year),
            "method": str(method),
            "count": int(len(grp)),
            "amount": float(grp["price"].sum()),
            "isNoComp": _is_no_competition(str(method)),
        })

    # ── 年度×ベンダーカテゴリ ────────────────────────────────────
    by_year_category = []
    for (year, cat), grp in procs.groupby(["fiscal_year", "category"]):
        by_year_category.append({
            "year": int(year),
            "category": str(cat),
            "count": int(len(grp)),
            "amount": float(grp["price"].sum()),
        })

    # ── 月次推移（award_date ベース）────────────────────────────
    monthly = []
    if "award_date" in procs.columns:
        mdf = (
            procs.dropna(subset=["award_date"])
            .assign(month=lambda d: d["award_date"].str[:7])
            .groupby("month")
            .agg(count=("procurement_id", "count"), amount=("price", "sum"))
            .reset_index()
            .sort_values("month")
        )
        for _, row in mdf.iterrows():
            monthly.append({
                "month": str(row["month"]),
                "count": int(row["count"]),
                "amount": float(row["amount"]),
            })

    return {
        "updatedAt": updated_at,
        "byYear": by_year,
        "byYearAndMethod": by_year_method,
        "byYearAndCategory": by_year_category,
        "monthly": monthly,
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

    total = sum(_safe_float(v.get("amount")) for v in vendors)
    by_vendor: dict[str, float] = {}
    for v in vendors:
        name = v.get("name") or ""
        amt = _safe_float(v.get("amount"))
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
