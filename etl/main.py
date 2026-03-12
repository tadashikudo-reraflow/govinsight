"""
GovInsight ETL メインスクリプト
GitHub Actions から月1回実行される。

Usage:
    python main.py [--data-dir <path>] [--output-dir <path>] [--dry-run]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from config import DIGITAL_AGENCY_CODE, DIGITAL_AGENCY_NAME
from fetch_procurement import fetch_all as fetch_procurement_all
from fetch_rssystem import fetch_all as fetch_rs_all, scrape_project_pages
from generate_json import generate_all
from match import match
from parse_procurement import parse_procurement
from parse_rs import parse_projects


def run(data_dir: Path, output_dir: Path, dry_run: bool = False) -> int:
    """ETLパイプライン全体を実行。エラーがあれば1、成功なら0を返す。"""
    print("=" * 60)
    print("GovInsight ETL 開始")
    print(f"  data_dir  : {data_dir}")
    print(f"  output_dir: {output_dir}")
    print(f"  dry_run   : {dry_run}")
    print("=" * 60)

    # ---- Step 1: データ取得 ----------------------------------------
    print("\n[Step 1] データダウンロード")
    rs_files = fetch_rs_all(data_dir)
    procurement_files = fetch_procurement_all(data_dir)

    if not rs_files:
        print("[ERROR] RSシステムのデータ取得に失敗しました")
        return 1

    # ---- Step 2: RSデータパース（最新年度を優先） -------------------
    print("\n[Step 2] RSデータパース")
    rs_dfs: list[pd.DataFrame] = []
    for year in sorted(rs_files.keys(), reverse=True):
        year_files = rs_files[year]
        csv_12 = year_files.get("1-2")
        csv_21 = year_files.get("2-1")
        csv_51 = year_files.get("5-1")
        csv_41 = year_files.get("4-1")

        if not csv_12:
            print(f"  [WARN] {year}年度: 1-2_事業概要等が見つかりません。スキップ。")
            continue

        df = parse_projects(
            csv_12=csv_12,
            csv_21=csv_21 or csv_12,  # フォールバック
            csv_51=csv_51 or csv_12,
            csv_41=csv_41,
            ministry_filter=DIGITAL_AGENCY_NAME,
        )
        if not df.empty:
            rs_dfs.append(df)
            print(f"  {year}年度: {len(df)}事業（{DIGITAL_AGENCY_NAME}）")

    if not rs_dfs:
        print("[ERROR] RSデータのパースに失敗しました")
        return 1

    # 年度重複は最新年度を優先（project_idで dedup）
    all_projects = pd.concat(rs_dfs, ignore_index=True).drop_duplicates(
        subset="project_id", keep="first"
    )
    print(f"  合計: {len(all_projects)}事業")

    # ---- Step 3: 調達データパース -----------------------------------
    print("\n[Step 3] 調達データパース")
    proc_dfs: list[pd.DataFrame] = []
    for year, csv_path in sorted(procurement_files.items()):
        df = parse_procurement(csv_path, ministry_filter=DIGITAL_AGENCY_CODE)
        if not df.empty:
            proc_dfs.append(df)
            total = df["price"].sum() / 1e8
            print(f"  {year}年度: {len(df)}件 ({total:.1f}億円)")

    if not proc_dfs:
        print("[WARN] 調達データなし（RS事業のみで出力します）")
        all_procurements = pd.DataFrame()
    else:
        all_procurements = pd.concat(proc_dfs, ignore_index=True).drop_duplicates(
            subset="procurement_id"
        )
        print(f"  合計: {len(all_procurements)}件")

    # ---- Step 3.5: RS事業ページ スクレイピング（マッチング精度向上） -----------
    print("\n[Step 3.5] RS事業ページ スクレイピング")
    projects_with_url = [
        {"id": str(row["project_id"]), "rsUrl": row.get("rsUrl") or ""}
        for _, row in all_projects.iterrows()
        if row.get("rsUrl")
    ]
    page_descriptions = scrape_project_pages(projects_with_url)

    # ---- Step 4: マッチング -----------------------------------------
    print("\n[Step 4] RS事業 × 落札案件 マッチング")
    if not all_procurements.empty:
        all_procurements = match(
            all_projects, all_procurements, page_descriptions=page_descriptions
        )

    # ---- Step 5: JSON生成 ------------------------------------------
    print("\n[Step 5] JSON生成")
    if dry_run:
        print("  [DRY RUN] JSONファイルは出力しません")
        return 0

    generate_all(all_projects, all_procurements, output_dir)

    print("\n[完了] GovInsight ETL 正常終了")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="GovInsight ETL")
    parser.add_argument("--data-dir", default="../../60_data", help="データ保存ディレクトリ")
    parser.add_argument("--output-dir", default="../public/data", help="JSON出力先")
    parser.add_argument("--dry-run", action="store_true", help="JSON出力をスキップ")
    args = parser.parse_args()

    exit_code = run(
        data_dir=Path(args.data_dir),
        output_dir=Path(args.output_dir),
        dry_run=args.dry_run,
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
