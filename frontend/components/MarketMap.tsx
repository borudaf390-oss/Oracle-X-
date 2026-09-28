"use client";

import { useEffect, useRef, useState } from "react";
import { forceSimulation, forceLink, forceManyBody, forceCenter, forceCollide, SimulationNodeDatum } from "d3-force";
import { select } from "d3-selection";
import { drag } from "d3-drag";
import { zoom } from "d3-zoom";
import { MarketMapData } from "@/lib/api";

type Node = SimulationNodeDatum & {
  id: number;
  symbol: string;
  sector: string | null;
  change_pct: number;
  radius: number;
};

type Edge = {
  source: number | Node;
  target: number | Node;
  correlation: number;
};

const SECTOR_COLOR: Record<string, string> = {
  semiconductors: "#8B7FD9",
  big_tech: "#9AA2B2",
  auto_tech: "#34d399",
  media_tech: "#9AA2B2",
  crypto_equity: "#fb7185",
  software: "#9AA2B2",
  crypto: "#34d399",
  index: "#5C6474",
};

export default function MarketMap({ data, activePath }: { data: MarketMapData; activePath?: number[] }) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const [dimensions, setDimensions] = useState({ width: 800, height: 560 });

  useEffect(() => {
    const el = svgRef.current?.parentElement;
    if (!el) return;
    const resize = () => setDimensions({ width: el.clientWidth, height: el.clientHeight });
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    if (!svgRef.current || data.nodes.length === 0) return;
    const { width, height } = dimensions;

    const nodes: Node[] = data.nodes.map((n) => ({
      ...n,
      radius: 12 + Math.min(Math.abs(n.change_pct) * 200, 18),
    }));
    const edges: Edge[] = data.edges
      .filter((e) => Math.abs(e.correlation) > 0.25)
      .map((e) => ({ source: e.source, target: e.target, correlation: e.correlation }));

    const svg = select(svgRef.current);
    svg.selectAll("*").remove();

    const defs = svg.append("defs");
    nodes.forEach((n) => {
      const color = SECTOR_COLOR[n.sector ?? ""] ?? "#5C6474";
      const isActive = activePath?.includes(n.id);
      const grad = defs.append("radialGradient").attr("id", `glow-${n.id}`);
      grad.append("stop").attr("offset", "0%").attr("stop-color", color).attr("stop-opacity", isActive ? 0.55 : 0.3);
      grad.append("stop").attr("offset", "100%").attr("stop-color", color).attr("stop-opacity", 0);
    });

    const g = svg.append("g");

    svg.call(
      zoom<SVGSVGElement, unknown>()
        .scaleExtent([0.5, 2.5])
        .on("zoom", (event) => g.attr("transform", event.transform))
    );

    const simulation = forceSimulation<Node>(nodes)
      .force(
        "link",
        forceLink<Node, Edge>(edges as any)
          .id((d: any) => d.id)
          .distance((d: any) => 140 - Math.abs(d.correlation) * 80)
          .strength((d: any) => Math.abs(d.correlation) * 0.6)
      )
      .force("charge", forceManyBody().strength(-260))
      .force("center", forceCenter(width / 2, height / 2))
      .force("collide", forceCollide<Node>((d) => d.radius + 18));

    const link = g
      .append("g")
      .selectAll<SVGLineElement, Edge>("line")
      .data(edges)
      .join("line")
      .attr("stroke", (d) => (d.correlation >= 0 ? "#34d399" : "#fb7185"))
      .attr("stroke-opacity", (d) => 0.18 + Math.abs(d.correlation) * 0.35)
      .attr("stroke-width", (d) => 0.6 + Math.abs(d.correlation) * 2);

    const dragBehavior = drag<SVGGElement, Node>()
      .on("start", (event, d) => {
        if (!event.active) simulation.alphaTarget(0.2).restart();
        d.fx = d.x;
        d.fy = d.y;
      })
      .on("drag", (event, d) => {
        d.fx = event.x;
        d.fy = event.y;
      })
      .on("end", (event, d) => {
        if (!event.active) simulation.alphaTarget(0);
        d.fx = null;
        d.fy = null;
      });

    const node = g
      .append("g")
      .selectAll<SVGGElement, Node>("g")
      .data(nodes)
      .join("g")
      .attr("cursor", "grab")
      .call(dragBehavior as any);

    // Glow halo
    node
      .append("circle")
      .attr("r", (d) => d.radius + 14)
      .attr("fill", (d) => `url(#glow-${d.id})`);

    // Core node
    node
      .append("circle")
      .attr("r", (d) => d.radius)
      .attr("fill", "#0a120d")
      .attr("stroke", (d) => SECTOR_COLOR[d.sector ?? ""] ?? "#5C6474")
      .attr("stroke-width", (d) => (activePath?.includes(d.id) ? 2.5 : 1.6));

    node
      .append("circle")
      .attr("r", 3)
      .attr("fill", (d) => (d.change_pct >= 0 ? "#34d399" : "#fb7185"));

    node
      .append("text")
      .text((d) => d.symbol)
      .attr("x", 0)
      .attr("y", (d) => d.radius + 16)
      .attr("text-anchor", "middle")
      .attr("fill", "#F4F7F5")
      .attr("font-family", "var(--font-plex-mono)")
      .attr("font-weight", 500)
      .attr("font-size", 11);

    node
      .append("text")
      .text((d) => `${d.change_pct >= 0 ? "+" : ""}${(d.change_pct * 100).toFixed(1)}%`)
      .attr("x", 0)
      .attr("y", (d) => d.radius + 29)
      .attr("text-anchor", "middle")
      .attr("fill", (d) => (d.change_pct >= 0 ? "#34d399" : "#fb7185"))
      .attr("font-family", "var(--font-plex-mono)")
      .attr("font-size", 10);

    simulation.on("tick", () => {
      link
        .attr("x1", (d: any) => d.source.x)
        .attr("y1", (d: any) => d.source.y)
        .attr("x2", (d: any) => d.target.x)
        .attr("y2", (d: any) => d.target.y);
      node.attr("transform", (d) => `translate(${d.x},${d.y})`);
    });

    return () => {
      simulation.stop();
    };
  }, [data, dimensions, activePath]);

  return (
    <div style={{ position: "relative", height: "100%", width: "100%" }}>
      <svg ref={svgRef} width={dimensions.width} height={dimensions.height} style={{ height: "100%", width: "100%" }} />
      <div className="map-legend">
        <span><span className="sw" style={{ background: "rgba(52,211,153,0.7)" }} /> positive correlation</span>
        <span><span className="sw" style={{ background: "rgba(251,113,133,0.7)" }} /> negative correlation</span>
      </div>
    </div>
  );
}
