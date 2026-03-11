"""
RSシステム CSV ダウンロード
rssystem.go.jp の ZIP ファイルを直接 curl（requests）で取得する。
Playwright 不要 - ファイルは静的配信されており認証なしで取得可能。
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

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


def fetch_all(data_dir: Path) -> dict[int, dict[str, Path]]:
    """全年度のRSデータを取得。{年度: {fileID: CSVパス}} を返す。"""
    all_results: dict[int, dict[str, Path]] = {}
    for year in RS_TARGET_YEARS:
        print(f"[RS] {year}年度 ダウンロード開始")
        all_results[year] = download_rs_year(year, data_dir)
        print(f"[RS] {year}年度 完了: {len(all_results[year])}ファイル")
    return all_results


if __name__ == "__main__":
    import sys
    data_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("../../60_data")
    fetch_all(data_dir)
