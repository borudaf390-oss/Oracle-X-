"use client";

import { useEffect, useRef } from "react";
import { EXCHANGE_HUBS } from "@/lib/globe";

export type FlightDatum = {
  id: string | number;
  label: string;
  direction: "LONG" | "SHORT";
  changeLabel: string;
  from: number;
  to: number;
  /** 0..1 strength — drives glow size, altitude and label brightness */
  norm: number;
};

type AnimatedFlight = FlightDatum & { progress: number; speed: number };

export default function GlobeCanvas({ flights }: { flights: FlightDatum[] }) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const flightsRef = useRef<Map<string, AnimatedFlight>>(new Map());

  // Sync incoming data into the animated map, preserving in-flight progress
  // for tickers that were already present so recomputing weights doesn't
  // make every dot jump back to the start of its arc.
  useEffect(() => {
    const map = flightsRef.current;
    const seen = new Set<string>();
    flights.forEach((f) => {
      const key = String(f.id);
      seen.add(key);
      const prev = map.get(key);
      map.set(key, {
        ...f,
        progress: prev ? prev.progress : Math.random(),
        speed: prev ? prev.speed : 0.003 + Math.random() * 0.004,
      });
    });
    Array.from(map.keys()).forEach((k) => {
      if (!seen.has(k)) map.delete(k);
    });
  }, [flights]);

  useEffect(() => {
    const canvas = canvasRef.current;
    const wrap = canvas?.parentElement;
    if (!canvas || !wrap) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let width = 0;
    let height = 0;
    function resize() {
      width = canvas!.width = wrap!.clientWidth;
      height = canvas!.height = wrap!.clientHeight;
    }
    resize();

    const GLOBE_RADIUS = Math.min(width, height) * 0.34;
    function latLonTo3D(lat: number, lon: number, radius = GLOBE_RADIUS) {
      const phi = (90 - lat) * (Math.PI / 180);
      const theta = (lon + 180) * (Math.PI / 180);
      return {
        x: -(radius * Math.sin(phi) * Math.cos(theta)),
        y: radius * Math.cos(phi),
        z: radius * Math.sin(phi) * Math.sin(theta),
      };
    }
    const globePoints: { x: number; y: number; z: number }[] = [];
    for (let lat = -80; lat <= 80; lat += 9) {
      for (let lon = -180; lon <= 180; lon += 13) globePoints.push(latLonTo3D(lat, lon));
    }

    let rotationX = 0.25;
    let rotationY = 0.5;
    let isDragging = false;
    let lastX = 0;
    let lastY = 0;
    let active = true;

    function onDown(e: MouseEvent) {
      isDragging = true;
      lastX = e.clientX;
      lastY = e.clientY;
      canvas!.style.cursor = "grabbing";
    }
    function onMove(e: MouseEvent) {
      if (!isDragging) return;
      rotationY += (e.clientX - lastX) * 0.004;
      rotationX += (e.clientY - lastY) * 0.004;
      lastX = e.clientX;
      lastY = e.clientY;
    }
    function onUp() {
      isDragging = false;
      canvas!.style.cursor = "grab";
    }
    canvas.addEventListener("mousedown", onDown);
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    window.addEventListener("resize", resize);

    function project3D(x: number, y: number, z: number, cx: number, cy: number, cosX: number, sinX: number, cosY: number, sinY: number) {
      const x1 = x * cosY - z * sinY;
      const z1 = z * cosY + x * sinY;
      const y1 = y * cosX - z1 * sinX;
      const z2 = z1 * cosX + y * sinX;
      const focal = 650;
      const scale = focal / (focal + z2 + 400);
      return { x: x1 * scale + cx, y: y1 * scale + cy, z: z2, scale };
    }
    function arcPoint(p1: { x: number; y: number; z: number }, p2: { x: number; y: number; z: number }, t: number, peak: number) {
      const x = p1.x + (p2.x - p1.x) * t;
      const y = p1.y + (p2.y - p1.y) * t;
      const z = p1.z + (p2.z - p1.z) * t;
      const dist = Math.sqrt(x * x + y * y + z * z) || 1;
      const arc = Math.sin(t * Math.PI) * peak;
      const r = GLOBE_RADIUS + arc;
      return { x: (x / dist) * r, y: (y / dist) * r, z: (z / dist) * r };
    }

    function render() {
      if (!active) return;
      ctx!.fillStyle = "#03060d";
      ctx!.fillRect(0, 0, width, height);
      const cx = width / 2;
      const cy = height / 2;
      if (!isDragging) rotationY += 0.0016;
      const cosX = Math.cos(rotationX);
      const sinX = Math.sin(rotationX);
      const cosY = Math.cos(rotationY);
      const sinY = Math.sin(rotationY);

      globePoints.forEach((pt) => {
        const proj = project3D(pt.x, pt.y, pt.z, cx, cy, cosX, sinX, cosY, sinY);
        if (proj.z + 400 > 0) {
          ctx!.fillStyle = `rgba(51,65,85,${Math.max(0.05, (proj.scale - 0.5) * 0.8)})`;
          ctx!.beginPath();
          ctx!.arc(proj.x, proj.y, 1.1 * proj.scale, 0, Math.PI * 2);
          ctx!.fill();
        }
      });

      EXCHANGE_HUBS.forEach((hub) => {
        const pt = latLonTo3D(hub.lat, hub.lon);
        const proj = project3D(pt.x, pt.y, pt.z, cx, cy, cosX, sinX, cosY, sinY);
        if (proj.z + 400 > 0) {
          ctx!.strokeStyle = "rgba(52,211,153,0.4)";
          ctx!.lineWidth = 1;
          ctx!.beginPath();
          ctx!.arc(proj.x, proj.y, 5 * proj.scale, 0, Math.PI * 2);
          ctx!.stroke();
          ctx!.fillStyle = "#34d399";
          ctx!.beginPath();
          ctx!.arc(proj.x, proj.y, 2.4 * proj.scale, 0, Math.PI * 2);
          ctx!.fill();
          ctx!.font = `${Math.max(9, Math.floor(10 * proj.scale))}px ui-monospace, monospace`;
          ctx!.fillStyle = "rgba(226,232,240,0.85)";
          ctx!.fillText(hub.code, proj.x + 7, proj.y + 3);
        }
      });

      flightsRef.current.forEach((flight) => {
        const hubA = EXCHANGE_HUBS[flight.from];
        const hubB = EXCHANGE_HUBS[flight.to];
        const p1 = latLonTo3D(hubA.lat, hubA.lon);
        const p2 = latLonTo3D(hubB.lat, hubB.lon);
        const isLong = flight.direction === "LONG";
        const altitude = GLOBE_RADIUS * (0.14 + flight.norm * 0.26);
        const glow = 0.12 + flight.norm * 0.22;

        ctx!.beginPath();
        let visible = false;
        for (let i = 0; i <= 28; i++) {
          const t = i / 28;
          const arcPt = arcPoint(p1, p2, t, altitude);
          const proj = project3D(arcPt.x, arcPt.y, arcPt.z, cx, cy, cosX, sinX, cosY, sinY);
          if (proj.z + 400 > 0) {
            visible = true;
            if (i === 0) ctx!.moveTo(proj.x, proj.y);
            else ctx!.lineTo(proj.x, proj.y);
          }
        }
        if (visible) {
          ctx!.strokeStyle = isLong ? `rgba(52,211,153,${glow.toFixed(2)})` : `rgba(244,63,94,${glow.toFixed(2)})`;
          ctx!.lineWidth = 1.2;
          ctx!.stroke();
        }

        flight.progress += flight.speed;
        if (flight.progress > 1) flight.progress = 0;
        const cur = arcPoint(p1, p2, flight.progress, altitude);
        const projCur = project3D(cur.x, cur.y, cur.z, cx, cy, cosX, sinX, cosY, sinY);
        if (projCur.z + 400 > 0) {
          ctx!.save();
          ctx!.shadowBlur = 8 + flight.norm * 10;
          ctx!.shadowColor = isLong ? "#10b981" : "#f43f5e";
          ctx!.fillStyle = isLong ? "#10b981" : "#f43f5e";
          ctx!.beginPath();
          ctx!.arc(projCur.x, projCur.y, (2.4 + flight.norm * 2.2) * projCur.scale, 0, Math.PI * 2);
          ctx!.fill();
          ctx!.font = "bold 10px ui-monospace, monospace";
          ctx!.fillStyle = isLong ? "#34d399" : "#f87171";
          ctx!.fillText(`${flight.label} ${flight.changeLabel}`, projCur.x + 8, projCur.y - 4);
          ctx!.restore();
        }
      });

      requestAnimationFrame(render);
    }
    render();

    return () => {
      active = false;
      canvas!.removeEventListener("mousedown", onDown);
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
      window.removeEventListener("resize", resize);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <canvas
      ref={canvasRef}
      style={{ position: "absolute", inset: 0, width: "100%", height: "100%", cursor: "grab" }}
    />
  );
}
