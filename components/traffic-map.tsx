"use client";
import { useEffect, useRef } from "react";
import type { Camera } from "@/lib/types";
import type * as Leaflet from "leaflet";
import "leaflet/dist/leaflet.css";

export default function TrafficMap({ cameras, selected, onSelect, compact = false }: { cameras: Camera[]; selected: Camera | null; onSelect: (c: Camera) => void; compact?: boolean }) {
  const element = useRef<HTMLDivElement>(null);
  const map = useRef<Leaflet.Map | null>(null);
  const layer = useRef<Leaflet.LayerGroup | null>(null);
  const lib = useRef<typeof Leaflet | null>(null);
  const callback = useRef(onSelect);
  const items = useRef(cameras);
  const choice = useRef(selected);
  const initialized = useRef(false);
  callback.current = onSelect; items.current = cameras; choice.current = selected;

  const draw = () => {
    const L = lib.current;
    if (!L || !layer.current) return;
    layer.current.clearLayers();
    for (const c of items.current) {
      const active = c.id === choice.current?.id;
      const marker = L.circleMarker([c.lat, c.lon], { radius: active ? 9 : c.saved ? 5 : 3, fillColor: active ? "#a5e446" : c.saved ? "#253e36" : "#718078", color: active ? "#263f29" : "#fff", weight: active ? 3 : 1, fillOpacity: active ? 1 : 0.7 });
      marker.bindTooltip(() => { const node = document.createElement("span"); node.textContent = c.name; return node; });
      marker.on("click", () => callback.current(c)); marker.addTo(layer.current); if (active) marker.bringToFront();
    }
  };
  useEffect(() => {
    let alive = true;
    import("leaflet").then(L => {
      if (!alive || !element.current) return;
      lib.current = L;
      const center = choice.current ? [choice.current.lat, choice.current.lon] as [number, number] : [51.5074, -0.1278] as [number, number];
      map.current = L.map(element.current, { zoomControl: false, attributionControl: true, scrollWheelZoom: !compact }).setView(center, compact ? 12 : 11);
      L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>' }).addTo(map.current);
      L.control.zoom({ position: "bottomright" }).addTo(map.current); layer.current = L.layerGroup().addTo(map.current); initialized.current = true; draw();
    });
    return () => { alive = false; initialized.current = false; map.current?.remove(); map.current = null; };
  }, [compact]);
  useEffect(() => { draw(); }, [cameras, selected]);
  useEffect(() => { if (initialized.current && selected) map.current?.flyTo([selected.lat, selected.lon], compact ? 12 : 13, { duration: 0.65 }); }, [selected?.id, compact]);
  return <div ref={element} className="traffic-map" aria-label="Map of public traffic camera locations" />;
}
