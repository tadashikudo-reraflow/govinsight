"use client";

import { useEffect, useState, useMemo } from "react";
import type { TrendsData, TrendYear } from "@/lib/types";

function formatAmount(yen: number): string {
  if (yen >= 1e8) return `${(yen / 1e8).toFixed(1)}億円`;
  if (yen >= 1e4) return `${Math.round(yen / 1e4)}万円`;
  return `${yen.toLocaleString()}円`;
}

const CATEGORY_COLORS: Record<string, string> = {
  国内大手SI: "#3b82f6",
  外資コンサル: "#a855f7",
  外資クラウド: "#0ea5e9",
  国内通信: "#22c55e",
  "国内コンサル・ベンダー": "#14b8a6",
  その他: "#9ca3af",
};

export default function TrendsPage() {
  const [data, setData] = useState<TrendsData | null>(null);
  const [tab, setTab] = useState<"overview" | "competition" | "category" | "monthly">("overview");

  useEffect(() => {
    fetch("/data/trends.json")
      .then((r) => r.json())
      .then(setData);
  }, []);

  const years = useMemo(() => data?.byYear ?? [], [data]);
  const maxAmount = useMemo(() => Math.max(...years.map((y) => y.totalAmount), 1), [years]);

  if (!data) {
    return <div className="py-20 text-center text-sm text-gray-400">読み込み中…</div>;
  }

  const latestYear = years[years.length - 1];
  const prevYear = years.length >= 2 ? years[years.length - 2] : null;

  function delta(curr: number, prev: number): string {
    const d = curr - prev;
    const sign = d >= 0 ? "▲" : "▼";
    return `${sign} ${formatAmount(Math.abs(d))}`;
  }
  function deltaRate(curr: number, prev: number): string {
    const d = curr - prev;
    const sign = d >= 0 ? "▲" : "▼";
    return `${sign} ${Math.abs(d - prev >= 0 ? d : -d).toFixed(1)}pt`;
  }

  return (
    <div className="space-y-6">
      {/* ヘッダー */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900">年度別トレンド分析</h1>
        <p className="mt-1 text-sm text-gray-500">
          デジタル庁 調達ポータル — 年度をまたいだ調達パターンの変化
        </p>
      </div>

      {/* 年度比較KPIカード */}
      {latestYear && prevYear && (
        <div className="rounded-xl border border-blue-100 bg-blue-50 p-5">
          <h2 className="mb-4 text-sm font-semibold text-blue-800">
            {prevYear.year}年度 → {latestYear.year}年度 変化サマリー
          </h2>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <DeltaCard
              label="調達総額"
              curr={formatAmount(latestYear.totalAmount)}
              delta={delta(latestYear.totalAmount, prevYear.totalAmount)}
              up={latestYear.totalAmount > prevYear.totalAmount}
            />
            <DeltaCard
              label="件数"
              curr={`${latestYear.count}件`}
              delta={`${latestYear.count > prevYear.count ? "▲" : "▼"} ${Math.abs(latestYear.count - prevYear.count)}件`}
              up={latestYear.count > prevYear.count}
            />
            <DeltaCard
              label="随意契約率"
              curr={`${latestYear.noCompRate}%`}
              delta={deltaRate(latestYear.noCompRate, prevYear.noCompRate)}
              up={latestYear.noCompRate < prevYear.noCompRate}
              upLabel="改善"
              downLabel="悪化"
            />
            <DeltaCard
              label="ベンダー数"
              curr={`${latestYear.vendorCount}社`}
              delta={`${latestYear.vendorCount > prevYear.vendorCount ? "▲" : "▼"} ${Math.abs(latestYear.vendorCount - prevYear.vendorCount)}社`}
              up={latestYear.vendorCount > prevYear.vendorCount}
            />
          </div>
        </div>
      )}

      {/* タブ */}
      <div className="flex gap-2 border-b border-gray-200">
        {(
          [
            { key: "overview", label: "📊 年度別概要" },
            { key: "competition", label: "⚖️ 競争性推移" },
            { key: "category", label: "🏢 カテゴリ推移" },
            { key: "monthly", label: "📅 月次推移" },
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

      {/* 年度別概要 */}
      {tab === "overview" && (
        <div className="space-y-4">
          {years.map((y) => (
            <YearSummaryCard key={y.year} year={y} maxAmount={maxAmount} />
          ))}
        </div>
      )}

      {/* 競争性推移 */}
      {tab === "competition" && (
        <div className="space-y-6">
          <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
            <h2 className="mb-1 text-sm font-semibold text-gray-700">
              競争入札 vs 随意契約の年度別比較
            </h2>
            <p className="mb-5 text-xs text-gray-400">
              随意契約率の変化に注目。数値が下がるほど競争性が改善。
            </p>
            <div className="space-y-4">
              {years.map((y) => (
                <div key={y.year}>
                  <div className="mb-1 flex items-center justify-between text-xs">
                    <span className="font-medium text-gray-700">{y.year}年度</span>
                    <span className="text-gray-500">
                      随意契約率{" "}
                      <span
                        className={`font-bold ${
                          y.noCompRate >= 50
                            ? "text-red-600"
                            : y.noCompRate >= 35
                            ? "text-orange-500"
                            : "text-green-600"
                        }`}
                      >
                        {y.noCompRate}%
                      </span>
                    </span>
                  </div>
                  <div className="flex h-8 w-full overflow-hidden rounded-lg">
                    <div
                      className="flex items-center justify-end pr-2 bg-red-400 text-xs font-bold text-white transition-all"
                      style={{ width: `${y.noCompRate}%` }}
                    >
                      {y.noCompRate >= 15 && `${y.noCompRate}%`}
                    </div>
                    <div
                      className="flex items-center pl-2 bg-gov-light-blue text-xs font-bold text-white"
                      style={{ width: `${100 - y.noCompRate}%` }}
                    >
                      {100 - y.noCompRate >= 15 && `${(100 - y.noCompRate).toFixed(1)}%`}
                    </div>
                  </div>
                  <div className="mt-1 flex gap-4 text-xs text-gray-400">
                    <span>随意: {formatAmount(y.noCompAmount)} ({y.noCompCount}件)</span>
                    <span>競争: {formatAmount(y.totalAmount - y.noCompAmount)} ({y.count - y.noCompCount}件)</span>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* 調達方式詳細 */}
          <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
            <h2 className="mb-4 text-sm font-semibold text-gray-700">入札方式 × 年度 詳細</h2>
            <div className="overflow-x-auto">
              <table className="min-w-full text-xs">
                <thead>
                  <tr className="border-b border-gray-100">
                    <th className="py-2 text-left font-semibold text-gray-500">入札方式</th>
                    {years.map((y) => (
                      <th key={y.year} className="py-2 text-right font-semibold text-gray-500">
                        {y.year}年度
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-50">
                  {Array.from(
                    new Set(data.byYearAndMethod.map((r) => r.method))
                  ).map((method) => {
                    const isNoComp = data.byYearAndMethod.find((r) => r.method === method)?.isNoComp ?? false;
                    return (
                      <tr key={method} className="hover:bg-gray-50">
                        <td className="py-2 pr-4">
                          <span
                            className={`inline-flex rounded px-1.5 py-0.5 text-xs ${
                              isNoComp ? "bg-red-100 text-red-700" : "bg-blue-100 text-blue-700"
                            }`}
                          >
                            {method.length > 18 ? method.slice(0, 18) + "…" : method}
                          </span>
                        </td>
                        {years.map((y) => {
                          const r = data.byYearAndMethod.find(
                            (x) => x.year === y.year && x.method === method
                          );
                          return (
                            <td key={y.year} className="py-2 text-right font-mono text-gray-600">
                              {r ? (
                                <>
                                  <div>{formatAmount(r.amount)}</div>
                                  <div className="text-gray-400">{r.count}件</div>
                                </>
                              ) : (
                                <span className="text-gray-300">—</span>
                              )}
                            </td>
                          );
                        })}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* カテゴリ推移 */}
      {tab === "category" && (
        <div className="space-y-6">
          <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
            <h2 className="mb-4 text-sm font-semibold text-gray-700">
              ベンダーカテゴリ別 年度比較
            </h2>
            <div className="overflow-x-auto">
              <table className="min-w-full text-xs">
                <thead>
                  <tr className="border-b border-gray-100">
                    <th className="py-2 text-left font-semibold text-gray-500">カテゴリ</th>
                    {years.map((y) => (
                      <th key={y.year} className="py-2 text-right font-semibold text-gray-500">
                        {y.year}年度
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-50">
                  {Array.from(
                    new Set(data.byYearAndCategory.map((r) => r.category))
                  )
                    .sort((a, b) => {
                      const latestA = data.byYearAndCategory
                        .filter((r) => r.category === a)
                        .reduce((s, r) => s + r.amount, 0);
                      const latestB = data.byYearAndCategory
                        .filter((r) => r.category === b)
                        .reduce((s, r) => s + r.amount, 0);
                      return latestB - latestA;
                    })
                    .map((cat) => {
                      const color = CATEGORY_COLORS[cat] ?? "#9ca3af";
                      return (
                        <tr key={cat} className="hover:bg-gray-50">
                          <td className="py-2 pr-4">
                            <span className="flex items-center gap-1.5">
                              <span
                                className="inline-block h-2.5 w-2.5 rounded-sm flex-shrink-0"
                                style={{ backgroundColor: color }}
                              />
                              <span className="font-medium text-gray-700">{cat}</span>
                            </span>
                          </td>
                          {years.map((y) => {
                            const r = data.byYearAndCategory.find(
                              (x) => x.year === y.year && x.category === cat
                            );
                            return (
                              <td key={y.year} className="py-2 text-right font-mono text-gray-600">
                                {r ? (
                                  <>
                                    <div>{formatAmount(r.amount)}</div>
                                    <div className="text-gray-400">{r.count}件</div>
                                  </>
                                ) : (
                                  <span className="text-gray-300">—</span>
                                )}
                              </td>
                            );
                          })}
                        </tr>
                      );
                    })}
                </tbody>
              </table>
            </div>
          </div>

          {/* カテゴリ別シェアバー */}
          {years.map((y) => {
            const cats = data.byYearAndCategory.filter((r) => r.year === y.year);
            const total = cats.reduce((s, r) => s + r.amount, 0);
            if (!total) return null;
            return (
              <div key={y.year} className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
                <div className="mb-3 flex items-center justify-between">
                  <h3 className="font-semibold text-gray-800">{y.year}年度 カテゴリ構成</h3>
                  <span className="text-sm text-gray-500">{formatAmount(total)}</span>
                </div>
                <div className="flex h-6 w-full overflow-hidden rounded-full">
                  {cats
                    .sort((a, b) => b.amount - a.amount)
                    .map((r) => (
                      <div
                        key={r.category}
                        style={{
                          width: `${(r.amount / total) * 100}%`,
                          backgroundColor: CATEGORY_COLORS[r.category] ?? "#9ca3af",
                        }}
                        title={`${r.category}: ${formatAmount(r.amount)}`}
                      />
                    ))}
                </div>
                <div className="mt-3 flex flex-wrap gap-3">
                  {cats
                    .sort((a, b) => b.amount - a.amount)
                    .map((r) => (
                      <span key={r.category} className="flex items-center gap-1 text-xs text-gray-600">
                        <span
                          className="inline-block h-2 w-2 rounded-sm"
                          style={{ backgroundColor: CATEGORY_COLORS[r.category] ?? "#9ca3af" }}
                        />
                        {r.category} {((r.amount / total) * 100).toFixed(1)}%
                      </span>
                    ))}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* 月次推移 */}
      {tab === "monthly" && (
        <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
          <h2 className="mb-4 text-sm font-semibold text-gray-700">月次落札額・件数推移</h2>
          {data.monthly.length === 0 ? (
            <p className="text-sm text-gray-400">月次データなし</p>
          ) : (
            <div className="space-y-2">
              {(() => {
                const maxAmt = Math.max(...data.monthly.map((m) => m.amount), 1);
                const maxCnt = Math.max(...data.monthly.map((m) => m.count), 1);
                return data.monthly.map((m) => (
                  <div key={m.month} className="flex items-center gap-3">
                    <div className="w-16 flex-shrink-0 text-xs font-mono text-gray-500">{m.month}</div>
                    <div className="flex-1 space-y-0.5">
                      <div className="h-3 w-full rounded-full bg-gray-100 overflow-hidden">
                        <div
                          className="h-full rounded-full bg-gov-light-blue"
                          style={{ width: `${(m.amount / maxAmt) * 100}%` }}
                        />
                      </div>
                      <div className="h-1.5 w-full rounded-full bg-gray-100 overflow-hidden">
                        <div
                          className="h-full rounded-full bg-gray-400"
                          style={{ width: `${(m.count / maxCnt) * 100}%` }}
                        />
                      </div>
                    </div>
                    <div className="w-20 text-right text-xs font-mono text-gray-700">
                      {formatAmount(m.amount)}
                    </div>
                    <div className="w-10 text-right text-xs font-mono text-gray-400">
                      {m.count}件
                    </div>
                  </div>
                ));
              })()}
            </div>
          )}
          <div className="mt-4 flex gap-4 text-xs text-gray-400">
            <span className="flex items-center gap-1.5">
              <span className="inline-block h-2 w-4 rounded-sm bg-gov-light-blue" />
              調達額
            </span>
            <span className="flex items-center gap-1.5">
              <span className="inline-block h-1.5 w-4 rounded-sm bg-gray-400" />
              件数
            </span>
          </div>
        </div>
      )}
    </div>
  );
}

function YearSummaryCard({
  year,
  maxAmount,
}: {
  year: TrendYear;
  maxAmount: number;
}) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
      <div className="flex items-start gap-4">
        <div className="flex-shrink-0 rounded-lg bg-gov-blue px-3 py-2 text-center text-white">
          <div className="text-xs font-medium">FY</div>
          <div className="text-xl font-bold">{year.year}</div>
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap items-center gap-4">
            <div>
              <span className="text-2xl font-bold text-gray-900">
                {formatAmount(year.totalAmount)}
              </span>
              <span className="ml-2 text-sm text-gray-500">{year.count}件</span>
            </div>
            <span
              className={`rounded-full px-2 py-0.5 text-xs font-bold ${
                year.noCompRate >= 50
                  ? "bg-red-100 text-red-700"
                  : year.noCompRate >= 35
                  ? "bg-orange-100 text-orange-700"
                  : "bg-green-100 text-green-700"
              }`}
            >
              随意契約率 {year.noCompRate}%
            </span>
            {year.hhi !== null && (
              <span className="text-xs text-gray-400">HHI: {year.hhi}</span>
            )}
          </div>

          {/* 金額バー */}
          <div className="mt-3 h-3 w-full rounded-full bg-gray-100 overflow-hidden">
            <div
              className="h-full rounded-full bg-gov-light-blue"
              style={{ width: `${(year.totalAmount / maxAmount) * 100}%` }}
            />
          </div>

          {/* 統計グリッド */}
          <div className="mt-3 grid grid-cols-3 gap-3 text-xs sm:grid-cols-5">
            <MiniStat label="随意契約額" value={formatAmount(year.noCompAmount)} />
            <MiniStat label="平均契約額" value={`${year.avgContractSize.toLocaleString()}万円`} />
            <MiniStat label="ベンダー数" value={`${year.vendorCount}社`} />
            {year.topVendors.slice(0, 2).map((v, i) => (
              <MiniStat
                key={i}
                label={`受注${i + 1}位`}
                value={v.name.length > 10 ? v.name.slice(0, 10) + "…" : v.name}
              />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-gray-400">{label}</div>
      <div className="mt-0.5 font-medium text-gray-700">{value}</div>
    </div>
  );
}

function DeltaCard({
  label,
  curr,
  delta,
  up,
  upLabel = "増加",
  downLabel = "減少",
}: {
  label: string;
  curr: string;
  delta: string;
  up: boolean;
  upLabel?: string;
  downLabel?: string;
}) {
  return (
    <div className="rounded-lg bg-white border border-blue-100 p-4">
      <p className="text-xs text-gray-500">{label}</p>
      <p className="mt-1 text-lg font-bold text-gray-900">{curr}</p>
      <p className={`mt-0.5 text-xs font-medium ${up ? "text-green-600" : "text-red-500"}`}>
        {delta} {up ? upLabel : downLabel}
      </p>
    </div>
  );
}
