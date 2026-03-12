"""
RSシステム CSV ダウンロード + RS事業ページスクレイピング
rssystem.go.jp の ZIP ファイルを直接 curl（requests）で取得する。
Playwright 不要 - ファイルは静的配信されており認証なしで取得可能。

フォールバック: ダウンロード失敗時は etl/rs_cache/{year}/ 内のキャッシュZIPを使用。
GitHub Actions の IP がブロックされた場合でも ETL を継続可能。

追加機能: scrape_project_pages()
  rsUrl（digital.go.jp等）からページ本文テキストを取得し、
  マッチング精度向上のためのリッチテキストを生成する。
"""
from __future__ import annotations

import io
import json
import time
import zipfile
from pathlib import Path
from urllib.parse import urlparse

import requests

from config import RS_FILES, RS_TARGET_YEARS, rs_file_url

TIMEOUT = 60
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    "Referer": "https://rssystem.go.jp/",
}

# etl/rs_cache/{year}/{file_id}_RS_{year}_{name_ja}.zip
_CACHE_DIR = Path(__file__).parent / "rs_cache"


def download_rs_year(year: int, output_dir: Path) -> dict[str, Path]:
    """指定年度の RSシステム CSV を全てダウンロードし、解凍して返す。

    Returns:
        {ファイルID: 解凍済みCSVパス} のdict
    """
    year_dir = output_dir / f"rs_{year}"
    year_dir.mkdir(parents=True, exist_ok=True)

    results: dict[str, Path] = {}
    for file_id, name_ja in RS_FILES:
        url = rs_file_url(year, file_id, name_ja)
        csv_path = _download_and_extract(url, year_dir, file_id)
        if csv_path is None:
            csv_path = _extract_from_cache(year, file_id, name_ja, year_dir)
        if csv_path:
            results[file_id] = csv_path
        else:
            print(f"  [WARN] {year} {file_id} ({name_ja}) の取得をスキップ")

    return results


def _download_and_extract(url: str, dest_dir: Path, file_id: str) -> Path | None:
    """ZIP をダウンロードしてメモリ上で解凍、CSVパスを返す。"""
    print(f"  GET {url}")
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  [ERROR] ダウンロード失敗: {e}")
        return None

    try:
        with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
            csv_names = [n for n in z.namelist() if n.endswith(".csv")]
            if not csv_names:
                print(f"  [ERROR] ZIP内にCSVが見つからない")
                return None
            csv_name = csv_names[0]
            z.extract(csv_name, dest_dir)
            return dest_dir / csv_name
    except zipfile.BadZipFile as e:
        print(f"  [ERROR] ZIPファイル破損: {e}")
        return None


def _extract_from_cache(
    year: int, file_id: str, name_ja: str, dest_dir: Path
) -> Path | None:
    """ローカルキャッシュ (etl/rs_cache/{year}/) から ZIP を解凍して返す。"""
    zip_name = f"{file_id}_RS_{year}_{name_ja}.zip"
    cache_zip = _CACHE_DIR / str(year) / zip_name
    if not cache_zip.exists():
        return None

    print(f"  [CACHE] {cache_zip.name} を使用")
    try:
        with zipfile.ZipFile(cache_zip) as z:
            csv_names = [n for n in z.namelist() if n.endswith(".csv")]
            if not csv_names:
                return None
            csv_name = csv_names[0]
            z.extract(csv_name, dest_dir)
            return dest_dir / csv_name
    except zipfile.BadZipFile as e:
        print(f"  [ERROR] キャッシュZIP破損: {e}")
        return None


def fetch_all(data_dir: Path) -> dict[int, dict[str, Path]]:
    """全年度のRSデータを取得。{年度: {fileID: CSVパス}} を返す。"""
    all_results: dict[int, dict[str, Path]] = {}
    for year in RS_TARGET_YEARS:
        print(f"[RS] {year}年度 ダウンロード開始")
        all_results[year] = download_rs_year(year, data_dir)
        print(f"[RS] {year}年度 完了: {len(all_results[year])}ファイル")
    return all_results


# ---------------------------------------------------------------------------
# RS事業ページ スクレイピング
# ---------------------------------------------------------------------------

# スクレイプ対象ドメイン（政府公式サイト）
_SCRAPE_ALLOWED_DOMAINS = {
    "www.digital.go.jp",
    "services.digital.go.jp",
    "www.dmp-official.digital.go.jp",
    "myna.go.jp",
    "gbiz-id.go.jp",
    "trustedweb.go.jp",
}

# ページキャッシュファイル（ETL毎に再利用してレート制限を避ける）
_SCRAPE_CACHE_FILE = _CACHE_DIR / "page_descriptions.json"

_SCRAPE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; GovInsight-bot/1.0; "
        "+https://github.com/tadashikudo-design/govinsight)"
    ),
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja,en;q=0.5",
}

_SCRAPE_TIMEOUT = 15
_SCRAPE_DELAY = 1.0  # 秒（サーバー負荷軽減）
_SCRAPE_MAX_CHARS = 800  # 取得テキストの上限（TF-IDF用）


def scrape_project_pages(
    projects_with_url: list[dict],
    force_refresh: bool = False,
) -> dict[str, str]:
    """RS事業の rsUrl からページ本文テキストを取得する。

    Args:
        projects_with_url: [{"id": str, "rsUrl": str, ...}, ...] のリスト
        force_refresh: キャッシュを無視して再取得するか

    Returns:
        {project_id: テキスト} のdict（取得失敗は空文字列）
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        print("  [WARN] beautifulsoup4 が未インストール。スクレイピングをスキップ。")
        return {}

    # キャッシュ読み込み
    cache: dict[str, str] = {}
    if not force_refresh and _SCRAPE_CACHE_FILE.exists():
        try:
            cache = json.loads(_SCRAPE_CACHE_FILE.read_text(encoding="utf-8"))
            print(f"  [Scrape] キャッシュ読み込み: {len(cache)}件")
        except Exception:
            cache = {}

    results: dict[str, str] = dict(cache)
    new_count = 0

    for proj in projects_with_url:
        pid = str(proj.get("id") or proj.get("project_id") or "")
        url = proj.get("rsUrl") or ""

        if not url or not pid:
            continue

        # キャッシュ済みはスキップ
        if pid in results and results[pid]:
            continue

        # 対象ドメインチェック
        domain = urlparse(url).netloc
        if domain not in _SCRAPE_ALLOWED_DOMAINS:
            results[pid] = ""
            continue

        # PDFはスキップ
        if url.lower().endswith(".pdf"):
            results[pid] = ""
            continue

        text = _fetch_page_text(url, BeautifulSoup)
        results[pid] = text
        new_count += 1

        if new_count > 1:
            time.sleep(_SCRAPE_DELAY)  # 最初の1件以降はウェイト

    # キャッシュ保存
    if new_count > 0:
        _SCRAPE_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _SCRAPE_CACHE_FILE.write_text(
            json.dumps(results, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"  [Scrape] {new_count}件 新規取得 → キャッシュ更新")

    scraped = sum(1 for v in results.values() if v)
    print(f"  [Scrape] 完了: {scraped}/{len(projects_with_url)}件 テキスト取得済み")
    return results


def _fetch_page_text(url: str, BeautifulSoup) -> str:
    """指定URLのページ本文テキストを取得して返す（失敗時は空文字列）。"""
    try:
        resp = requests.get(url, headers=_SCRAPE_HEADERS, timeout=_SCRAPE_TIMEOUT)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding or "utf-8"
    except requests.RequestException as e:
        print(f"    [WARN] GET失敗 {url}: {e}")
        return ""

    try:
        soup = BeautifulSoup(resp.text, "lxml")

        # noisy要素を除去
        for tag in soup(["script", "style", "nav", "header", "footer",
                         "aside", "form", "button", "noscript"]):
            tag.decompose()

        # メインコンテンツを優先取得
        main = (
            soup.find("main")
            or soup.find("article")
            or soup.find(id="main")
            or soup.find(class_=lambda c: c and "main" in str(c).lower())
            or soup.body
        )

        if not main:
            return ""

        # テキスト抽出（p, h1-h4, li タグを優先）
        texts = []
        for elem in main.find_all(["p", "h1", "h2", "h3", "h4", "li"]):
            t = elem.get_text(separator=" ", strip=True)
            if len(t) > 10:  # 短すぎるものは除外
                texts.append(t)

        combined = " ".join(texts)
        # 上限カット
        return combined[:_SCRAPE_MAX_CHARS]

    except Exception as e:
        print(f"    [WARN] パース失敗 {url}: {e}")
        return ""


if __name__ == "__main__":
    import sys
    data_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("../../60_data")
    fetch_all(data_dir)
