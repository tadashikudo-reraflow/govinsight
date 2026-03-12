"use client";

import { useEffect, useState, useMemo } from "react";
import type { RiskAnalysis, RiskVendor, BigContract } from "@/lib/types";

function formatAmount(yen: number): string {
  if (yen >= 1e8) return `${(yen / 1e8).toFixed(1)}億円`;
  if (yen >= 1e4) return `${Math.round(yen / 1e4)}万円`;
  return `${yen.toLocaleString()}円`;
}

function RiskLevel({ score }: { score: number }) {
  if (score >= 500)
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-red-100 px-2 py-0.5 text-xs font-bold text-red-700">
        🔴 超高
      </span>
    );
  if (score >= 100)
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-orange-100 px-2 py-0.5 text-xs font-bold text-orange-700">
        🟠 高
      </span>
    );
  if (score >= 20)
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-yellow-100 px-2 py-0.5 text-xs font-bold text-yellow-700">
        🟡 中
      </span>
    );
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-500">
      ⚪ 低
    </span>
  );
}

const CATEGORY_COLOR: Record<string, string> = {
  外資クラウド: "bg-sky-100 text-sky-700",
  外資コンサル: "bg-purple-100 text-purple-700",
  国内大手SI: "bg-blue-100 text-blue-700",
  国内通信: "bg-green-100 text-green-700",
  "国内コンサル・ベンダー": "bg-teal-100 text-teal-700",
  その他: "bg-gray-100 text-gray-600",
};

function CategoryBadge({ cat }: { cat: string }) {
  const cls = CATEGORY_COLOR[cat] ?? CATEGORY_COLOR["その他"];
  return (
    <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${cls}`}>
      {cat}
    </span>
  );
}

export default function RiskPage() {
  const [data, setData] = useState<RiskAnalysis | null>(null);
  const [tab, setTab] = useState<"vendors" | "contracts" | "methods">("vendors");
  const [contractSearch, setContractSearch] = useState("");

  useEffect(() => {
    fetch("/data/risk.json")
      .then((r) => r.json())
      .then(setData);
  }, []);

  const filteredContracts = useMemo(() => {
    if (!data) return [];
    const q = contractSearch.toLowerCase();
    return data.bigContracts.filter(
      (c) =>
        !q ||
        c.name.toLowerCase().includes(q) ||
        c.vendorName.toLowerCase().includes(q)
    );
  }, [data, contractSearch]);

  const maxScore = useMemo(
    () => (data ? Math.max(...data.riskVendors.map((v) => v.lockInScore), 1) : 1),
    [data]
  );

  if (!data) {
    return <div className="py-20 text-center text-sm text-gray-400">読み込み中…</div>;
  }

  const { summary } = data;

  return (
    <div className="space-y-6">
      {/* ヘッダー */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900">ロックインリスク分析</h1>
        <p className="mt-1 text-sm text-gray-500">
          デジタル庁 調達ポータル — 随意契約・競争性なし案件の集中分析
        </p>
      </div>

      {/* KPIカード */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <KpiCard
          label="随意契約率"
          value={`${summary.noCompRate}%`}
          sub={`${summary.noCompCount}件 / ${summary.totalCount}件`}
          alert={summary.noCompRate >= 40}
          highlight
        />
        <KpiCard
          label="随意契約総額"
          value={formatAmount(summary.noCompAmount)}
          sub={`全体 ${formatAmount(summary.totalAmount)}`}
          alert={false}
        />
        <KpiCard
          label="大型随意契約"
          value={`${summary.bigNoCompCount}件`}
          sub={`1億円超 計${formatAmount(summary.bigNoCompAmount)}`}
          alert={summary.bigNoCompCount >= 10}
        />
        <KpiCard
          label="競争入札"
          value={`${summary.compCount}件`}
          sub={formatAmount(summary.compAmount)}
          alert={false}
        />
      </div>

      {/* 随意契約 vs 競争 ビジュアル */}
      <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
        <h2 className="mb-4 text-sm font-semibold text-gray-700">調達方式の内訳</h2>
        <div className="flex h-10 w-full overflow-hidden rounded-full">
          <div
            className="flex items-center justify-center bg-red-400 text-xs font-bold text-white"
            style={{ width: `${summary.noCompRate}%` }}
          >
            {summary.noCompRate >= 15 ? `随意 ${summary.noCompRate}%` : ""}
          </div>
          <div
            className="flex items-center justify-center bg-gov-light-blue text-xs font-bold text-white"
            style={{ width: `${100 - summary.noCompRate}%` }}
          >
            競争入札 {(100 - summary.noCompRate).toFixed(1)}%
          </div>
        </div>
        <div className="mt-3 flex gap-6 text-xs text-gray-500">
          <span className="flex items-center gap-1.5">
            <span className="inline-block h-3 w-3 rounded-sm bg-red-400" />
            随意契約・公募型プロポーザル（競争性なし）
          </span>
          <span className="flex items-center gap-1.5">
            <span className="inline-block h-3 w-3 rounded-sm bg-gov-light-blue" />
            一般競争入札（競争あり）
          </span>
        </div>
        {/* 入札方式詳細 */}
        <div className="mt-4 space-y-2">
          {data.methodSummary.map((m) => {
            const maxAmt = Math.max(...data.methodSummary.map((x) => x.amount), 1);
            return (
              <div key={m.method} className="flex items-center gap-3">
                <div className="w-52 truncate text-xs text-gray-600">{m.method}</div>
                <div className="flex-1 rounded-full bg-gray-100 h-2 overflow-hidden">
                  <div
                    className={`h-full rounded-full ${m.isNoComp ? "bg-red-400" : "bg-gov-light-blue"}`}
                    style={{ width: `${(m.amount / maxAmt) * 100}%` }}
                  />
                </div>
                <div className="w-24 text-right text-xs font-mono text-gray-600">
                  {formatAmount(m.amount)}
                </div>
                <div className="w-10 text-right text-xs font-mono text-gray-400">
                  {m.count}件
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* タブ切替 */}
      <div className="flex gap-2 border-b border-gray-200">
        {(
          [
            { key: "vendors", label: "🏢 ベンダー別リスク" },
            { key: "contracts", label: "📋 大型随意契約一覧" },
            { key: "methods", label: "📊 価格帯分析" },
          ] as const
        ).map(({ key, label }) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              tab === key
                ? "border-gov-blue text-gov-blue"
                : "border-transparent text-gray-500 hover:text-gray-700"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {/* ベンダー別ロックインリスク */}
      {tab === "vendors" && (
        <div className="space-y-3">
          <p className="text-xs text-gray-500">
            ロックインリスクスコア = 随意契約額（億円）× 随意契約率（%）。高いほどベンダー依存が深刻。
          </p>
          {data.riskVendors.map((v, i) => (
            <VendorRiskRow key={v.corporateNumber} rank={i + 1} vendor={v} maxScore={maxScore} />
          ))}
        </div>
      )}

      {/* 大型随意契約一覧 */}
      {tab === "contracts" && (
        <div className="space-y-4">
          <input
            type="text"
            placeholder="案件名・ベンダー名で検索…"
            value={contractSearch}
            onChange={(e) => setContractSearch(e.target.value)}
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-gov-blue focus:outline-none focus:ring-1 focus:ring-gov-blue"
          />
          <div className="overflow-x-auto rounded-xl border border-gray-200 bg-white shadow-sm">
            <table className="min-w-full divide-y divide-gray-100 text-sm">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500">案件名</th>
                  <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500">受注先</th>
                  <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500">カテゴリ</th>
                  <th className="px-4 py-3 text-right text-xs font-semibold text-gray-500">金額</th>
                  <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500">調達方式</th>
                  <th className="px-4 py-3 text-right text-xs font-semibold text-gray-500">年度</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {filteredContracts.map((c) => (
                  <BigContractRow key={c.id} contract={c} />
                ))}
                {filteredContracts.length === 0 && (
                  <tr>
                    <td colSpan={6} className="py-10 text-center text-sm text-gray-400">
                      該当案件なし
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* 価格帯別分析 */}
      {tab === "methods" && (
        <div className="space-y-6">
          <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
            <h2 className="mb-4 text-sm font-semibold text-gray-700">随意契約の価格帯分布</h2>
            <div className="space-y-3">
              {data.priceDistribution.map((t) => {
                const maxAmt = Math.max(...data.priceDistribution.map((x) => x.amount), 1);
                return (
                  <div key={t.tier} className="flex items-center gap-3">
                    <div className="w-32 text-xs font-medium text-gray-700">{t.tier}</div>
                    <div className="flex-1 rounded-full bg-gray-100 h-5 overflow-hidden">
                      <div
                        className="h-full rounded-full bg-red-400 flex items-center justify-end pr-2"
                        style={{ width: `${(t.amount / maxAmt) * 100}%` }}
                      >
                        {t.amount / maxAmt > 0.15 && (
                          <span className="text-xs font-bold text-white">
                            {formatAmount(t.amount)}
                          </span>
                        )}
                      </div>
                    </div>
                    <div className="w-16 text-right text-xs font-mono text-gray-500">
                      {t.count}件
                    </div>
                    {t.amount / maxAmt <= 0.15 && (
                      <div className="w-20 text-right text-xs font-mono text-gray-500">
                        {formatAmount(t.amount)}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>

          <div className="rounded-xl border border-orange-200 bg-orange-50 p-5">
            <h3 className="font-semibold text-orange-800">⚠️ リスク評価サマリー</h3>
            <ul className="mt-3 space-y-2 text-sm text-orange-700">
              <li>
                • 全調達の <strong>{summary.noCompRate}%</strong>（{summary.noCompCount}件）が随意契約・公募型プロポーザル
              </li>
              <li>
                • 1億円超の大型随意契約が <strong>{summary.bigNoCompCount}件</strong>（計{formatAmount(summary.bigNoCompAmount)}）
              </li>
              <li>
                • 特定ベンダーへの随意契約集中がロックインリスクの主因
              </li>
              <li>
                • 公募型プロポーザルは競争形式だが実質的な競争性は低い場合がある
              </li>
            </ul>
          </div>
        </div>
      )}
    </div>
  );
}

function KpiCard({
  label,
  value,
  sub,
  alert,
  highlight = false,
}: {
  label: string;
  value: string;
  sub: string;
  alert: boolean;
  highlight?: boolean;
}) {
  return (
    <div
      className={`rounded-xl border p-5 shadow-sm ${
        highlight
          ? alert
            ? "border-red-300 bg-red-50"
            : "border-gov-blue bg-gov-blue text-white"
          : "border-gray-200 bg-white"
      }`}
    >
      <p
        className={`text-xs font-medium ${
          highlight ? (alert ? "text-red-500" : "text-blue-100") : "text-gray-500"
        }`}
      >
        {label}
      </p>
      <p
        className={`mt-1 text-xl font-bold ${
          highlight ? (alert ? "text-red-700" : "text-white") : "text-gray-900"
        }`}
      >
        {value}
      </p>
      <p
        className={`mt-0.5 text-xs ${
          highlight ? (alert ? "text-red-400" : "text-blue-200") : "text-gray-400"
        }`}
      >
        {sub}
      </p>
    </div>
  );
}

function VendorRiskRow({
  rank,
  vendor,
  maxScore,
}: {
  rank: number;
  vendor: RiskVendor;
  maxScore: number;
}) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm hover:shadow-md transition-shadow">
      <div className="flex items-start gap-4">
        <div className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-gray-100 text-sm font-bold text-gray-500">
          {rank}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-semibold text-gray-900">{vendor.name}</span>
            <CategoryBadge cat={vendor.category} />
            <RiskLevel score={vendor.lockInScore} />
          </div>
          <div className="mt-2 grid grid-cols-3 gap-3 text-xs text-gray-500 sm:grid-cols-5">
            <Stat label="随意契約額" value={formatAmount(vendor.noCompAmount)} bold />
            <Stat label="随意契約率" value={`${vendor.noCompRate}%`} bold alert={vendor.noCompRate >= 60} />
            <Stat label="総受注額" value={formatAmount(vendor.totalAmount)} />
            <Stat label="随意件数" value={`${vendor.noCompCount}件`} />
            <Stat label="ロックインスコア" value={vendor.lockInScore.toFixed(1)} bold />
          </div>
          {/* スコアバー */}
          <div className="mt-3 h-2 w-full rounded-full bg-gray-100 overflow-hidden">
            <div
              className={`h-full rounded-full transition-all ${
                vendor.lockInScore >= 500
                  ? "bg-red-500"
                  : vendor.lockInScore >= 100
                  ? "bg-orange-400"
                  : vendor.lockInScore >= 20
                  ? "bg-yellow-400"
                  : "bg-gray-300"
              }`}
              style={{ width: `${Math.min((vendor.lockInScore / maxScore) * 100, 100)}%` }}
            />
          </div>
        </div>
      </div>
    </div>
  );
}

function Stat({
  label,
  value,
  bold = false,
  alert = false,
}: {
  label: string;
  value: string;
  bold?: boolean;
  alert?: boolean;
}) {
  return (
    <div>
      <div className="text-gray-400">{label}</div>
      <div
        className={`mt-0.5 font-mono ${
          bold ? (alert ? "font-bold text-red-600" : "font-semibold text-gray-800") : "text-gray-600"
        }`}
      >
        {value}
      </div>
    </div>
  );
}

function BigContractRow({ contract }: { contract: BigContract }) {
  return (
    <tr className="hover:bg-red-50 transition-colors">
      <td className="px-4 py-3">
        <span className="line-clamp-2 text-sm text-gray-800">{contract.name}</span>
      </td>
      <td className="px-4 py-3">
        <span className="whitespace-nowrap font-medium text-gray-900">
          {contract.vendorName}
        </span>
      </td>
      <td className="px-4 py-3">
        <CategoryBadge cat={contract.category} />
      </td>
      <td className="px-4 py-3 text-right font-mono font-semibold text-red-700">
        {formatAmount(contract.price)}
      </td>
      <td className="px-4 py-3">
        <span className="rounded bg-red-100 px-2 py-0.5 text-xs text-red-700">
          {contract.bidMethodName.length > 12
            ? contract.bidMethodName.slice(0, 12) + "…"
            : contract.bidMethodName}
        </span>
      </td>
      <td className="px-4 py-3 text-right text-xs text-gray-500">
        {contract.fiscalYear ? `${contract.fiscalYear}年度` : "—"}
      </td>
    </tr>
  );
}
