import { BarChart, LineChart, PieChart } from "echarts/charts";
import { GridComponent, LegendComponent, TooltipComponent } from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { useEffect, useRef } from "react";

echarts.use([BarChart, LineChart, PieChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer]);

type ChartProps = {
  data?: { name: string; value: number }[];
  type?: "bar" | "pie" | "line";
  series?: { name: string; data: number[] }[];
  labels?: string[];
  height?: number;
};

export function MiniChart({ data, type = "bar", series, labels, height }: ChartProps) {
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current);
    if (type === "pie") {
      chart.setOption({
        tooltip: {},
        color: ["#2563eb", "#dc2626", "#f59e0b", "#10b981"],
        series: [{ type: "pie", radius: ["48%", "72%"], data }]
      });
    } else if (type === "line") {
      chart.setOption({
        tooltip: { trigger: "axis" },
        legend: { bottom: 0, textStyle: { color: "#64748b", fontSize: 11 } },
        grid: { left: 36, right: 12, top: 16, bottom: 42 },
        xAxis: { type: "category", data: labels ?? [], axisLabel: { color: "#64748b" } },
        yAxis: { type: "value", min: 0, max: 1, splitLine: { lineStyle: { color: "#e2e8f0" } } },
        color: ["#2563eb", "#dc2626", "#f59e0b", "#10b981", "#7c3aed"],
        series: (series ?? []).map((item) => ({
          type: "line",
          name: item.name,
          data: item.data,
          smooth: true,
          symbolSize: 5,
          showSymbol: item.data.length <= 20
        }))
      });
    } else {
      chart.setOption({
        grid: { left: 24, right: 10, top: 12, bottom: 24 },
        xAxis: { type: "category", data: (data ?? []).map((item) => item.name), axisLabel: { color: "#64748b" } },
        yAxis: { type: "value", splitLine: { lineStyle: { color: "#e2e8f0" } } },
        color: ["#2563eb"],
        series: [{ type: "bar", data: (data ?? []).map((item) => item.value), barWidth: 24, itemStyle: { borderRadius: [6, 6, 0, 0] } }]
      });
    }
    const resize = () => chart.resize();
    window.addEventListener("resize", resize);
    return () => {
      window.removeEventListener("resize", resize);
      chart.dispose();
    };
  }, [data, type, series, labels]);

  return <div className="mini-chart" style={height ? { height } : undefined} ref={ref} />;
}
