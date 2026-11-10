"use client";
import { useId } from "react";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

const labels: Record<string, string> = {
  visible: "Visible vehicles", flow: "Vehicles / min", occupancy: "Image occupancy %", crossings: "Line crossings",
};

export default function TrafficChart({ data, metric = "visible", hourly = false }: { data: Record<string, unknown>[]; metric?: string; hourly?: boolean }) {
  const fillId = useId().replaceAll(":", "");
  const label = labels[metric] || "Traffic measurement";
  const integer = metric === "crossings" || metric === "visible" && !hourly;
  const format = (value: unknown) => typeof value === "number" && Number.isFinite(value)
    ? new Intl.NumberFormat("en", { maximumFractionDigits: integer ? 0 : 2 }).format(value)
    : "No observation";
  const time = (value: unknown) => hourly ? `${String(value).padStart(2, "0")}:00` : `${Number(value).toFixed(1)}s`;
  const common = <>
    <CartesianGrid vertical={false} stroke="#e9ece8" strokeDasharray="3 4" />
    <XAxis dataKey={hourly ? "hour" : "elapsed"} tickFormatter={time} axisLine={false} tickLine={false} minTickGap={36} tick={{ fontSize: 12, fill: "#788179" }} />
    <YAxis axisLine={false} tickLine={false} width={40} tick={{ fontSize: 12, fill: "#788179" }} allowDecimals={!integer} domain={metric === "occupancy" ? [0, 100] : [0, "auto"]} />
    <Tooltip contentStyle={{ background: "#fff", border: "1px solid #dde2dc", borderRadius: 10, fontSize: 14 }} labelFormatter={value => `${time(value)} ${hourly ? "local time" : "into observation"}`} formatter={value => [format(Number(value)), label]} />
  </>;

  return <>
    <div className="chart" role="img" aria-label={`${label} ${hourly ? "by local hour of day" : "over this analysis"}. Measurements are also available in the data table below.`}>
      <ResponsiveContainer width="100%" height="100%">
        {hourly ? <BarChart data={data} margin={{ top: 15, right: 15, bottom: 0, left: 0 }}>
          {common}<Bar dataKey={metric} fill="#749e43" radius={[4, 4, 0, 0]} maxBarSize={26} />
        </BarChart> : <AreaChart data={data} margin={{ top: 15, right: 15, bottom: 0, left: 0 }}>
          <defs><linearGradient id={fillId} x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#9cc45d" stopOpacity={0.3} /><stop offset="100%" stopColor="#9cc45d" stopOpacity={0} /></linearGradient></defs>
          {common}<Area type="linear" dataKey={metric} stroke="#649633" fill={`url(#${fillId})`} strokeWidth={2.5} dot={false} connectNulls={false} />
        </AreaChart>}
      </ResponsiveContainer>
    </div>
    <details className="chart-data">
      <summary>View measurement data</summary>
      <div className="table-scroll"><table>
        <caption>{label} · {hourly ? "each camera’s local time" : "time since observation started"}</caption>
        <thead><tr><th scope="col">{hourly ? "Local hour" : "Elapsed time"}</th><th scope="col">{label}</th>{hourly && <th scope="col">Observations</th>}</tr></thead>
        <tbody>{data.map((row, index) => <tr key={index}><th scope="row">{time(row[hourly ? "hour" : "elapsed"])}</th><td className="numeric">{format(row[metric])}</td>{hourly && <td className="numeric">{format(row.runs)}</td>}</tr>)}</tbody>
      </table></div>
    </details>
  </>;
}
