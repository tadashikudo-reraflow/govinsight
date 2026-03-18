"""
RS事業 × 落札案件 マッチングロジック
同一府省庁内でテキスト類似度（TF-IDF）+ 手動補正テーブルを使って紐付ける。
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import jaconv
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from config import CORRECTIONS_FILE, MATCHING_THRESHOLD, SECONDARY_LOWER_THRESHOLD

# Grok API（xAI）設定 — 環境変数 XAI_API_KEY が必要
_GROK_API_URL = "https://api.x.ai/v1/chat/completions"
_GROK_MODEL = "grok-4-1-fast-non-reasoning"   # 安価・高速
_GROK_CACHE_FILE = Path(__file__).parent / "grok_match_cache.json"
_GROK_MATCH_LIMIT = int(os.environ.get("GROK_MATCH_LIMIT", "50"))  # 1回の実行上限


def match(
    projects: pd.DataFrame,
    procurements: pd.DataFrame,
    corrections_file: Path = Path(CORRECTIONS_FILE),
    page_descriptions: dict[str, str] | None = None,
) -> pd.DataFrame:
    """RS事業と落札案件をマッチングし、procurementsにproject_idを付与して返す。

    改善点:
    - 調達案件名から「令和X年度」プレフィックスを除去して比較精度向上
    - overview テキスト + スクレイピングページテキストを TF-IDF に組み込み
    - ベンダー名・overview キーワードによるセカンダリマッチング
    - 閾値を 0.30 に引き下げて再現率向上

    注意: TF-IDF の project_texts は事業名のみ（テキスト長非対称問題を避けるため）。
    overview/purpose/scraped テキストはセカンダリマッチング専用。

    Args:
        projects: parse_rs.parse_projects() の出力
        procurements: parse_procurement.parse_procurement() の出力
        corrections_file: 手動補正テーブルのパス
        page_descriptions: {project_id: スクレイピング取得テキスト} の辞書（省略可）

    Returns:
        procurements に 'project_id' 列（null許容）を追加したDataFrame
    """
    if projects.empty or procurements.empty:
        procurements["project_id"] = None
        return procurements

    if page_descriptions is None:
        page_descriptions = {}

    # Step 1: TF-IDF自動マッチング
    proc = procurements.copy()
    proc["project_id"] = None

    project_ids = projects["project_id"].tolist()

    # RS事業: 事業名×3（重み付き）+ overview + purpose を結合
    # 事業名を3倍繰り返してTF-IDFベクトルを事業名主導にし、
    # overview/purpose のキーワード（ガバメントクラウド・GCAS等）も反映させる
    project_texts = []
    for _, row in projects.iterrows():
        name = _normalize_text(str(row["name"]) if row["name"] else "")
        overview = jaconv.normalize(str(row.get("overview") or "")[:200], "NFKC")
        purpose = jaconv.normalize(str(row.get("purpose") or "")[:100], "NFKC")
        project_texts.append(f"{name} {name} {name} {overview} {purpose}")

    # 調達案件: 「令和X年度」プレフィックスを除去して比較精度向上
    proc_texts = [
        _normalize_text(_normalize_proc_name(n)) for n in proc["name"].fillna("").tolist()
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

    # Step 3: overview/purpose テキスト + スクレイピングテキストによる救済マッチング
    _overview_secondary_match(proc, projects, project_ids, sim_matrix, page_descriptions)

    # Step 4: Grok API によるLLM判定（XAI_API_KEY が設定されている場合のみ実行）
    if os.environ.get("XAI_API_KEY"):
        _grok_tertiary_match(proc, projects, project_ids, sim_matrix)
    else:
        print("[Match] XAI_API_KEY 未設定 → Grok マッチングをスキップ")

    # Step 5: 手動補正テーブルで上書き
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


# 括弧注記（全角・半角）を除去: 「（令和5年度版）」「(仮称)」
_PAREN_PATTERN = re.compile(r"[（(][^）)]*[）)]")
# 末尾の汎用業務サフィックス: 「～整備」「～開発業務」「等」etc.
_SUFFIX_PATTERN = re.compile(
    r"(?:に(?:係る|関する)(?:業務)?|(?:システム)?(?:整備|開発|構築|運用|保守|管理)(?:業務)?|等)$"
)


def _normalize_text(text: str) -> str:
    """TF-IDF用テキスト正規化（事業名・調達案件名共通）。

    - 括弧注記を除去: 「（令和5年度）」「(仮称)」
    - 末尾の汎用業務サフィックスを除去: 「整備」「開発業務」「等」etc.
    """
    text = str(text).strip() if text else ""
    text = _PAREN_PATTERN.sub("", text)
    text = _SUFFIX_PATTERN.sub("", text)
    return text.strip()


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

    lower_threshold = SECONDARY_LOWER_THRESHOLD

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


def _overview_secondary_match(
    proc: pd.DataFrame,
    projects: pd.DataFrame,
    project_ids: list,
    sim_matrix,
    page_descriptions: dict[str, str] | None = None,
) -> None:
    """TF-IDF未達案件を overview/purpose テキスト + スクレイピングテキストで救済する（in-place）。

    TF-IDF スコアが [0.15, MATCHING_THRESHOLD) の候補に対し、
    調達案件名のキーワード（4文字以上の単語）が RS 事業の overview / purpose /
    スクレイピング取得テキストに含まれる場合に採用する。
    """
    if page_descriptions is None:
        page_descriptions = {}

    has_overview = "overview" in projects.columns
    has_purpose = "purpose" in projects.columns
    if not has_overview and not has_purpose and not page_descriptions:
        return

    # RS事業: project_id → enriched text のマップを構築
    project_text_map: dict[str, str] = {}
    for _, prow in projects.iterrows():
        pid = str(prow.get("project_id") or "")
        overview = str(prow.get("overview") or "")[:300]
        purpose = str(prow.get("purpose") or "")[:150]
        scraped = page_descriptions.get(pid, "")[:500]
        combined = jaconv.normalize(" ".join(filter(None, [overview, purpose, scraped])), "NFKC").lower()
        if combined.strip():
            project_text_map[pid] = combined

    if not project_text_map:
        return

    lower_threshold = SECONDARY_LOWER_THRESHOLD

    for pos, (idx, row) in enumerate(proc.iterrows()):
        if row["project_id"] is not None:
            continue  # 既にマッチ済み

        proc_name = _normalize_proc_name(str(row.get("name") or ""))
        proc_norm = jaconv.normalize(proc_name, "NFKC").lower()
        # 4文字以上のキーワードを抽出（日本語では4文字で意味的に十分）
        keywords = [proc_norm[i:i+4] for i in range(len(proc_norm) - 3)]
        if not keywords:
            continue

        sim_row = sim_matrix[pos]
        candidates = [
            (project_ids[j], sim_row[j])
            for j in range(len(project_ids))
            if lower_threshold <= sim_row[j] < MATCHING_THRESHOLD
        ]
        if not candidates:
            continue

        for pid, _ in sorted(candidates, key=lambda x: -x[1]):
            proj_text = project_text_map.get(str(pid), "")
            if not proj_text:
                continue
            # キーワードの過半数が overview/purpose/scraped に含まれるか確認
            matches = sum(1 for kw in keywords if kw in proj_text)
            if keywords and matches / len(keywords) >= 0.5:
                proc.at[idx, "project_id"] = pid
                break


def _grok_tertiary_match(
    proc: pd.DataFrame,
    projects: pd.DataFrame,
    project_ids: list,
    sim_matrix,
) -> None:
    """TF-IDF + 二次マッチでも未解決の案件を Grok API で判定する（in-place）。

    XAI_API_KEY が必要。実行上限は _GROK_MATCH_LIMIT 件（デフォルト50）。
    結果は grok_match_cache.json にキャッシュし、再実行時は API を呼ばない。
    """
    import requests as _req

    api_key = os.environ.get("XAI_API_KEY", "")
    if not api_key:
        return

    # キャッシュ読み込み（procurement_id → project_id or null）
    cache: dict[str, str | None] = {}
    if _GROK_CACHE_FILE.exists():
        try:
            cache = json.loads(_GROK_CACHE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, IOError):
            cache = {}

    # RS事業の辞書（project_id → {name, overview, purpose}）
    proj_lookup: dict[str, dict] = {}
    for _, prow in projects.iterrows():
        pid = str(prow.get("project_id") or "")
        proj_lookup[pid] = {
            "name": str(prow.get("name") or ""),
            "overview": str(prow.get("overview") or "")[:150],
            "purpose": str(prow.get("purpose") or "")[:100],
        }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    called = 0
    cache_hits = 0

    for pos, (idx, row) in enumerate(proc.iterrows()):
        if row["project_id"] is not None:
            continue  # 既マッチ

        proc_id = str(row.get("procurement_id") or idx)
        proc_name = str(row.get("name") or "")

        # キャッシュヒット
        if proc_id in cache:
            matched_pid = cache[proc_id]
            if matched_pid:
                proc.at[idx, "project_id"] = matched_pid
            cache_hits += 1
            continue

        # 上限チェック
        if called >= _GROK_MATCH_LIMIT:
            break

        # top-3 候補を取得（スコア問わず上位3件）
        sim_row = sim_matrix[pos]
        top_indices = sim_row.argsort()[::-1][:3]
        candidates = [
            (project_ids[j], float(sim_row[j]), proj_lookup.get(str(project_ids[j]), {}))
            for j in top_indices
        ]

        # 候補が全員スコア0なら Grok 不要
        if all(score == 0.0 for _, score, _ in candidates):
            cache[proc_id] = None
            continue

        # Grok プロンプト構築
        cand_lines = "\n".join(
            f"  [{i+1}] ID={pid} スコア={score:.3f}\n"
            f"      事業名: {info.get('name','')}\n"
            f"      概要: {info.get('overview','')}"
            for i, (pid, score, info) in enumerate(candidates)
        )
        prompt = (
            f"以下は日本のデジタル庁の調達案件です。\n"
            f"調達案件名: 「{proc_name}」\n\n"
            f"以下のRS事業（行政事業レビューシステム登録事業）の中で、\n"
            f"この調達案件が属する事業を1つ選んでください。\n"
            f"どれも該当しない場合は「なし」と答えてください。\n\n"
            f"候補:\n{cand_lines}\n\n"
            f"回答形式: 番号のみ（例: 1）または「なし」"
        )

        try:
            resp = _req.post(
                _GROK_API_URL,
                headers=headers,
                json={
                    "model": _GROK_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 10,
                    "temperature": 0,
                },
                timeout=30,
            )
            resp.raise_for_status()
            answer = resp.json()["choices"][0]["message"]["content"].strip()
            called += 1

            matched_pid = None
            if answer.isdigit():
                choice = int(answer) - 1
                if 0 <= choice < len(candidates):
                    matched_pid = str(candidates[choice][0])
                    proc.at[idx, "project_id"] = matched_pid

            cache[proc_id] = matched_pid
            time.sleep(0.3)  # レート制限対策

        except Exception as e:
            print(f"[Grok] API エラー (proc_id={proc_id}): {e}")
            cache[proc_id] = None

    # キャッシュ保存
    _GROK_CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[Match][Grok] 呼出={called}件 キャッシュヒット={cache_hits}件 / 上限={_GROK_MATCH_LIMIT}件")


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
