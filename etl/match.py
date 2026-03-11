"""
RS事業 × 落札案件 マッチングロジック
同一府省庁内でテキスト類似度（TF-IDF）+ 手動補正テーブルを使って紐付ける。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import jaconv
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from config import CORRECTIONS_FILE, MATCHING_THRESHOLD


def match(
    projects: pd.DataFrame,
    procurements: pd.DataFrame,
    corrections_file: Path = Path(CORRECTIONS_FILE),
) -> pd.DataFrame:
    """RS事業と落札案件をマッチングし、procurementsにproject_idを付与して返す。

    改善点:
    - 調達案件名から「令和X年度」プレフィックスを除去して比較精度向上
    - RS事業のマッチングテキストに overview を付加（先頭200字）
    - 閾値を 0.30 に引き下げて再現率向上

    Args:
        projects: parse_rs.parse_projects() の出力
        procurements: parse_procurement.parse_procurement() の出力

    Returns:
        procurements に 'project_id' 列（null許容）を追加したDataFrame
    """
    if projects.empty or procurements.empty:
        procurements["project_id"] = None
        return procurements

    # Step 1: TF-IDF自動マッチング
    proc = procurements.copy()
    proc["project_id"] = None

    project_ids = projects["project_id"].tolist()

    # RS事業: 事業名 + overview（先頭200字）+ purpose（先頭100字）
    project_texts = [
        _build_project_text(row["name"], row.get("overview", ""), row.get("purpose", ""))
        for _, row in projects.iterrows()
    ]

    # 調達案件: 「令和X年度」プレフィックスを除去して比較精度向上
    proc_texts = [
        _normalize_proc_name(n) for n in proc["name"].fillna("").tolist()
    ]

    # TF-IDF行列を生成
    all_texts = project_texts + proc_texts
    vectorizer = TfidfVectorizer(
        analyzer=_char_ngram_analyzer,
        min_df=1,
        sublinear_tf=True,
    )
    try:
        tfidf_matrix = vectorizer.fit_transform(all_texts)
    except ValueError:
        # テキストが空の場合はスキップ
        procurements["project_id"] = None
        return procurements

    project_matrix = tfidf_matrix[: len(project_texts)]
    proc_matrix = tfidf_matrix[len(project_texts):]

    # コサイン類似度計算
    sim_matrix = cosine_similarity(proc_matrix, project_matrix)

    for i, row in enumerate(sim_matrix):
        best_idx = row.argmax()
        best_score = row[best_idx]
        if best_score >= MATCHING_THRESHOLD:
            proc.at[i, "project_id"] = project_ids[best_idx]

    # Step 2: ベンダー名クロスマッチング（TF-IDF未達候補の救済）
    _vendor_secondary_match(proc, projects, project_ids, sim_matrix)

    # Step 3: 手動補正テーブルで上書き
    corrections = _load_corrections(corrections_file)
    for corr in corrections:
        pid = corr.get("project_id")
        prid = corr.get("procurement_id")
        if pid and prid:
            mask = proc["procurement_id"] == prid
            proc.loc[mask, "project_id"] = pid

    matched = proc["project_id"].notna().sum()
    total = len(proc)
    print(f"[Match] {matched}/{total} 件マッチ ({matched/total*100:.1f}%)")

    return proc


def _normalize_proc_name(name: str) -> str:
    """調達案件名から「令和X年度」「平成X年度」プレフィックスを除去する。"""
    name = re.sub(r"^(令和|平成)\d+年度[　\s]*", "", str(name))
    return name


def _build_project_text(name: str, overview: str, purpose: str = "") -> str:
    """事業名 + overview先頭200字 + purpose先頭100字を結合してマッチング用テキストを構築する。"""
    name_str = str(name) if name else ""
    overview_str = str(overview)[:200] if overview else ""
    purpose_str = str(purpose)[:100] if purpose else ""
    return f"{name_str} {overview_str} {purpose_str}".strip()


def _vendor_secondary_match(
    proc: pd.DataFrame,
    projects: pd.DataFrame,
    project_ids: list,
    sim_matrix,
) -> None:
    """TF-IDF未達（0.15〜閾値未満）案件をベンダー名で救済マッチングする（in-place）。

    RS 5-1 の vendors リスト内の法人名と調達案件の vendor_name を比較し、
    一致する場合に TF-IDF best_score の事業を割り当てる。
    """
    if "vendors" not in projects.columns or "vendor_name" not in proc.columns:
        return

    # RS事業: vendor_name 正規化マップ {project_id: [normalized_vendor, ...]}
    project_vendor_map: dict[str, list[str]] = {}
    for _, prow in projects.iterrows():
        vendors = prow.get("vendors") or []
        normalized = [
            jaconv.normalize(str(v.get("name", "")), "NFKC").lower()
            for v in vendors
            if isinstance(v, dict) and v.get("name")
        ]
        if normalized:
            project_vendor_map[prow["project_id"]] = normalized

    if not project_vendor_map:
        return

    lower_threshold = 0.15

    for pos, (idx, row) in enumerate(proc.iterrows()):
        if row["project_id"] is not None:
            continue  # 既にマッチ済み

        proc_vendor = row.get("vendor_name") or ""
        if not proc_vendor:
            continue
        proc_vendor_norm = jaconv.normalize(str(proc_vendor), "NFKC").lower()

        # TF-IDF スコアが lower_threshold 以上の候補プロジェクトを取得
        sim_row = sim_matrix[pos]
        candidates = [
            (project_ids[j], sim_row[j])
            for j in range(len(project_ids))
            if lower_threshold <= sim_row[j] < MATCHING_THRESHOLD
        ]
        if not candidates:
            continue

        # ベンダー名照合
        for pid, _ in sorted(candidates, key=lambda x: -x[1]):
            rs_vendors = project_vendor_map.get(pid, [])
            if any(proc_vendor_norm in rv or rv in proc_vendor_norm for rv in rs_vendors):
                proc.at[idx, "project_id"] = pid
                break


def _char_ngram_analyzer(text: str) -> list[str]:
    """日本語テキスト用 n-gram アナライザー（2-3文字）。"""
    # 全角→半角、カタカナ正規化
    text = jaconv.normalize(text, "NFKC")
    # 記号・空白を除去
    text = re.sub(r"[^\w\u3040-\u30ff\u4e00-\u9fff]", "", text)
    tokens = []
    for n in (2, 3):
        tokens.extend(text[i : i + n] for i in range(len(text) - n + 1))
    return tokens


def _load_corrections(path: Path) -> list[dict]:
    """手動補正テーブルを読み込む。ファイルが存在しない場合は空リストを返す。"""
    if not path.exists():
        return []
    try:
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []
