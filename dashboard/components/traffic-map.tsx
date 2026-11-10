"use client";
import { useCallback, useEffect, useMemo, useRef } from "react";
import type { Camera } from "@/lib/types";
import type * as Leaflet from "leaflet";
import "leaflet/dist/leaflet.css";

type LocatedCamera = Camera & { lat: number; lon: number };

export default function TrafficMap({ cameras, selected, onSelect, compact = false }: { cameras: Camera[]; selected: Camera | null; onSelect: (c: Camera) => void; compact?: boolean }) {
  const locations = useMemo(() => cameras.filter((c): c is LocatedCamera => typeof c.lat === "number" && typeof c.lon === "number"), [cameras]);
  const locatedSelection = selected && typeof selected.lat === "number" && typeof selected.lon === "number" ? selected as LocatedCamera : null;
  const element = useRef<HTMLDivElement>(null);
  const map = useRef<Leaflet.Map | null>(null);
  const layer = useRef<Leaflet.LayerGroup | null>(null);
  const lib = useRef<typeof Leaflet | null>(null);
  const callback = useRef(onSelect);
  const items = useRef(locations);
  const choice = useRef(locatedSelection);
  const initialized = useRef(false);
  const previousSelection = useRef(selected?.id);
  useEffect(() => { callback.current = onSelect; items.current = locations; choice.current = locatedSelection; }, [onSelect, locations, locatedSelection]);

  const draw = useCallback(() => {
    const L = lib.current;
    if (!L || !layer.current || !map.current) return;
    layer.current.clearLayers();
    const visible = map.current?.getBounds().pad(0.2);
    for (const c of items.current) {
      if (visible && !visible.contains([c.lat, c.lon])) continue;
      const active = c.id === choice.current?.id;
      const marker = L.circleMarker([c.lat, c.lon], { radius: active ? 9 : c.saved ? 5 : 3, fillColor: active ? "#a5e446" : c.saved ? "#253e36" : "#718078", color: active ? "#263f29" : "#fff", weight: active ? 3 : 1, fillOpacity: active ? 1 : 0.7 });
      marker.bindTooltip(() => { const node = document.createElement("span"); node.textContent = c.name; return node; });
      marker.on("click", () => callback.current(c)); marker.addTo(layer.current); if (active) marker.bringToFront();
    }
  }, []);
  const boundsKey = useMemo(() => locations.length ? [locations.length, ...locations.reduce((b, c) => [Math.min(b[0], c.lat), Math.max(b[1], c.lat), Math.min(b[2], c.lon), Math.max(b[3], c.lon)], [Infinity, -Infinity, Infinity, -Infinity])].join(":") : "", [locations]);
  const fitNetwork = useCallback(() => {
    if (compact || !map.current || !lib.current) return;
    if (!items.current.length) { map.current.setView([20, 0], 2, { animate: false }); return; }
    map.current.fitBounds(lib.current.latLngBounds(items.current.map(c => [c.lat, c.lon] as [number, number])), { padding: [30, 30], maxZoom: 13, animate: false });
  }, [compact]);
  useEffect(() => {
    let alive = true;
    import("leaflet").then(L => {
      if (!alive || !element.current) return;
      lib.current = L;
      const center = compact && choice.current ? [choice.current.lat, choice.current.lon] as [number, number] : [20, 0] as [number, number];
      map.current = L.map(element.current, { preferCanvas: true, zoomAnimation: false, zoomControl: false, attributionControl: true, scrollWheelZoom: !compact }).setView(center, compact && choice.current ? 12 : 2);
      L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>' }).addTo(map.current);
      L.control.zoom({ position: "bottomright" }).addTo(map.current); layer.current = L.layerGroup().addTo(map.current); initialized.current = true;
      map.current.on("moveend", draw); fitNetwork(); draw();
    });
    return () => { alive = false; initialized.current = false; map.current?.off("moveend", draw); map.current?.remove(); map.current = null; layer.current = null; };
  }, [compact, draw, fitNetwork]);
  useEffect(() => { draw(); }, [cameras, selected, draw]);
  useEffect(() => { if (initialized.current) fitNetwork(); }, [boundsKey, fitNetwork]);
  const selectedId = selected?.id;
  useEffect(() => { const camera = choice.current; const changed = previousSelection.current !== undefined && previousSelection.current !== selectedId; previousSelection.current = selectedId; if (initialized.current && camera && (compact || changed)) map.current?.flyTo([camera.lat, camera.lon], compact ? 12 : 13, { duration: 0.65 }); }, [selectedId, compact]);
  return <><div ref={element} className="traffic-map" aria-label="Map of public traffic camera locations" />{(!locations.length || (compact && selected && !locatedSelection)) && <div className="map-position-note">{compact ? "This provider does not publish map coordinates for this camera." : "Map coordinates are not published for these cameras. Choose a camera from the list."}</div>}</>;
}
