import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "GovInsight - デジタル庁事業可視化",
  description:
    "デジタル庁のIT事業と調達情報を可視化するオープンデータプラットフォーム",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="ja">
      <body className="min-h-screen bg-gray-50 text-gray-900">
        <header className="bg-gov-blue text-white shadow-md">
          <div className="mx-auto max-w-7xl px-4 py-4 flex items-center gap-4">
            <a href="/" className="flex items-center gap-2 hover:opacity-90">
              <span className="text-xl font-bold tracking-tight">
                GovInsight
              </span>
              <span className="text-xs bg-white/20 px-2 py-0.5 rounded">
                β
              </span>
            </a>
            <nav className="ml-8 flex gap-6 text-sm">
              <a href="/" className="hover:text-blue-200 transition-colors">
                ダッシュボード
              </a>
              <a
                href="/projects"
                className="hover:text-blue-200 transition-colors"
              >
                IT事業一覧
              </a>
              <a
                href="/procurements"
                className="hover:text-blue-200 transition-colors"
              >
                調達案件
              </a>
              <a
                href="/vendors"
                className="hover:text-blue-200 transition-colors"
              >
                ベンダー
              </a>
              <a
                href="/analysis"
                className="hover:text-blue-200 transition-colors"
              >
                依存分析
              </a>
              <a
                href="/risk"
                className="hover:text-blue-200 transition-colors"
              >
                リスク
              </a>
              <a
                href="/trends"
                className="hover:text-blue-200 transition-colors"
              >
                トレンド
              </a>
            </nav>
            <div className="ml-auto text-xs text-white/60">
              データソース: 政府RS情報システム・政府調達ポータル
            </div>
          </div>
        </header>
        <main className="mx-auto max-w-7xl px-4 py-8">{children}</main>
        <footer className="border-t border-gray-200 mt-16 py-8 text-center text-xs text-gray-400">
          <p>
            GovInsight — デジタル庁IT事業データの可視化プラットフォーム（非公式）
          </p>
          <p className="mt-1">
            データ出典:{" "}
            <a
              href="https://rssystem.go.jp"
              className="underline hover:text-gray-600"
            >
              RSシステム
            </a>{" "}
            /{" "}
            <a
              href="https://www.p-portal.go.jp"
              className="underline hover:text-gray-600"
            >
              政府調達ポータル
            </a>
          </p>
        </footer>
      </body>
    </html>
  );
}
