import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

const STORAGE_KEY = "tpg.chatFab.position";
const SIZE = 64;
const EDGE = 16;

type Point = { x: number; y: number };

function defaultPosition(): Point {
  if (typeof window === "undefined") return { x: 0, y: 0 };
  return {
    x: Math.max(EDGE, window.innerWidth - SIZE - EDGE),
    y: Math.max(EDGE, window.innerHeight - SIZE - 88),
  };
}

function clamp(point: Point): Point {
  if (typeof window === "undefined") return point;
  return {
    x: Math.min(Math.max(EDGE, point.x), Math.max(EDGE, window.innerWidth - SIZE - EDGE)),
    y: Math.min(Math.max(EDGE, point.y), Math.max(EDGE, window.innerHeight - SIZE - EDGE)),
  };
}

function readPosition(): Point {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return defaultPosition();
    const parsed = JSON.parse(raw);
    if (typeof parsed?.x !== "number" || typeof parsed?.y !== "number") return defaultPosition();
    return clamp(parsed);
  } catch {
    return defaultPosition();
  }
}

export default function ChatFab({ canUseChat }: { canUseChat: boolean }) {
  const navigate = useNavigate();
  const location = useLocation();
  const [position, setPosition] = useState<Point>(() => readPosition());
  const [dragging, setDragging] = useState(false);
  const dragRef = useRef<{ pointerId: number; offsetX: number; offsetY: number; moved: boolean } | null>(null);
  const latestPositionRef = useRef(position);

  useEffect(() => {
    latestPositionRef.current = position;
  }, [position]);

  useEffect(() => {
    const onResize = () => {
      setPosition((current) => {
        const next = clamp(current);
        try {
          localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
        } catch {
          /* ignore */
        }
        return next;
      });
    };
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  if (!canUseChat || location.pathname === "/chat") return null;

  const persist = (point: Point) => {
    const next = clamp(point);
    setPosition(next);
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    } catch {
      /* ignore */
    }
  };

  return (
    <button
      className={`tpg-fab fixed z-50 flex h-16 w-16 touch-none select-none items-center justify-center rounded-full text-sm font-bold transition hover:scale-105 focus:outline-none focus:ring-2 focus:ring-cyan-100/80 ${dragging ? "cursor-grabbing scale-105" : "cursor-grab"}`}
      style={{ left: position.x, top: position.y }}
      aria-label="Open TPG HomeAI chat"
      title="Drag to move. Tap to open chat."
      onPointerDown={(event) => {
        const rect = event.currentTarget.getBoundingClientRect();
        dragRef.current = {
          pointerId: event.pointerId,
          offsetX: event.clientX - rect.left,
          offsetY: event.clientY - rect.top,
          moved: false,
        };
        event.currentTarget.setPointerCapture(event.pointerId);
        setDragging(true);
      }}
      onPointerMove={(event) => {
        const drag = dragRef.current;
        if (!drag || drag.pointerId !== event.pointerId) return;
        const next = clamp({ x: event.clientX - drag.offsetX, y: event.clientY - drag.offsetY });
        if (Math.abs(next.x - latestPositionRef.current.x) > 3 || Math.abs(next.y - latestPositionRef.current.y) > 3) drag.moved = true;
        latestPositionRef.current = next;
        setPosition(next);
      }}
      onPointerUp={(event) => {
        const drag = dragRef.current;
        if (!drag || drag.pointerId !== event.pointerId) return;
        persist(latestPositionRef.current);
        dragRef.current = null;
        setDragging(false);
        if (!drag.moved) navigate("/chat");
      }}
      onPointerCancel={() => {
        persist(latestPositionRef.current);
        dragRef.current = null;
        setDragging(false);
      }}
    >
      AI
    </button>
  );
}
