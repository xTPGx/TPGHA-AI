"""Approval-first house knowledge assets.

Floor plans, blueprints, room photos, and notes are stored as durable assets.
Drafts are visible in the management UI; only approved assets are injected into
general conversation context.
"""
from __future__ import annotations

import base64
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config_loader import get_config
from .db.database import get_session
from .db.models import HouseAsset
from .settings import get_settings

MAX_UPLOAD_BYTES = 15 * 1024 * 1024
ALLOWED_CONTENT_PREFIXES = ("image/",)
ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "application/json",
    "text/plain",
    "text/markdown",
}


def list_assets(status: str | None = None) -> list[dict[str, Any]]:
    with get_session() as session:
        query = session.query(HouseAsset)
        if status:
            query = query.filter(HouseAsset.status == status)
        rows = query.order_by(HouseAsset.updated_at.desc(), HouseAsset.id.desc()).all()
        return [_row_to_dict(row) for row in rows]


def get_asset(asset_id: int) -> dict[str, Any] | None:
    with get_session() as session:
        row = session.get(HouseAsset, asset_id)
        return _row_to_dict(row) if row else None


def upload_asset(
    *,
    data: bytes,
    original_filename: str,
    content_type: str,
    title: str = "",
    asset_type: str = "floorplan",
    room: str = "",
    uploaded_by: str = "",
    description: str = "",
) -> dict[str, Any]:
    content_type = (content_type or "application/octet-stream").split(";")[0].strip().lower()
    if not _allowed_content_type(content_type):
        raise ValueError(f"Unsupported file type: {content_type}.")
    if not data:
        raise ValueError("Uploaded file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError("Uploaded file is too large. Limit is 15 MB.")

    asset_dir = _asset_dir()
    asset_dir.mkdir(parents=True, exist_ok=True)
    safe_name = _safe_filename(original_filename or "house-asset")
    stored_filename = f"{uuid.uuid4().hex}_{safe_name}"
    path = asset_dir / stored_filename
    path.write_bytes(data)

    analysis = analyze_asset(
        data=data,
        content_type=content_type,
        title=title or Path(safe_name).stem,
        asset_type=asset_type,
        room=room,
        filename=original_filename,
        description=description,
    )

    now = datetime.now(timezone.utc)
    with get_session() as session:
        row = HouseAsset(
            created_at=now,
            updated_at=now,
            title=(title or Path(safe_name).stem).strip(),
            asset_type=(asset_type or "floorplan").strip().lower(),
            room=(room or "").strip(),
            original_filename=original_filename or safe_name,
            stored_filename=stored_filename,
            content_type=content_type,
            storage_path=str(path),
            status="draft",
            description=(description or "").strip(),
            analysis=json.dumps(analysis),
            uploaded_by=(uploaded_by or "").strip(),
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return _row_to_dict(row)


def approve_asset(asset_id: int) -> dict[str, Any]:
    return _set_status(asset_id, "approved")


def ignore_asset(asset_id: int) -> dict[str, Any]:
    return _set_status(asset_id, "ignored")


def asset_file_path(asset_id: int) -> Path | None:
    asset = get_asset(asset_id)
    if not asset:
        return None
    path = Path(asset.get("storage_path") or "")
    root = _asset_dir().resolve()
    try:
        resolved = path.resolve()
    except OSError:
        return None
    if root not in resolved.parents and resolved != root:
        return None
    return resolved if resolved.is_file() else None


def approved_asset_context(limit: int = 6) -> str:
    assets = list_assets(status="approved")[:limit]
    if not assets:
        return ""
    lines = ["Approved house knowledge assets:"]
    for asset in assets:
        analysis = asset.get("analysis") or {}
        summary = analysis.get("summary") or asset.get("description") or "No summary yet."
        rooms = analysis.get("room_candidates") or []
        uses = analysis.get("dashboard_uses") or []
        room_text = ", ".join(rooms[:4]) if rooms else (asset.get("room") or "whole house")
        use_text = "; ".join(uses[:3]) if uses else "Use as reference for rooms, zones, dashboards, and device placement."
        lines.append(
            f"- {asset.get('title')} ({asset.get('asset_type')}, rooms: {room_text}): "
            f"{summary} Dashboard/context uses: {use_text}"
        )
    return "\n".join(lines)


def analyze_asset(
    *,
    data: bytes,
    content_type: str,
    title: str,
    asset_type: str,
    room: str,
    filename: str,
    description: str,
) -> dict[str, Any]:
    if get_settings().openai_configured and content_type.startswith("image/"):
        try:
            return _analyze_image_with_openai(
                data=data,
                content_type=content_type,
                title=title,
                asset_type=asset_type,
                room=room,
                filename=filename,
                description=description,
            )
        except Exception as err:  # noqa: BLE001 - analysis must degrade
            fallback = _fallback_analysis(title, asset_type, room, filename, description)
            fallback["provider"] = "fallback"
            fallback["fallback_reason"] = f"OpenAI image analysis failed: {type(err).__name__}."
            return fallback
    return _fallback_analysis(title, asset_type, room, filename, description)


def _analyze_image_with_openai(
    *,
    data: bytes,
    content_type: str,
    title: str,
    asset_type: str,
    room: str,
    filename: str,
    description: str,
) -> dict[str, Any]:
    from openai import OpenAI

    settings = get_settings()
    data_url = f"data:{content_type};base64,{base64.b64encode(data).decode('ascii')}"
    room_names = ", ".join(r.name for r in get_config().devices.rooms) or "none configured"
    prompt = (
        "Analyze this uploaded smart-home house asset for TPG HomeAI. Return only compact JSON with "
        "summary, asset_type, room_candidates, dashboard_uses, automation_ideas, mapping_questions, "
        "and safety_notes. Be practical for Home Assistant dashboards, zones, rooms, cameras, lights, "
        "switches, displays, and voice assistants.\n"
        f"Title: {title}\nFilename: {filename}\nDeclared type: {asset_type}\nDeclared room: {room or 'unknown'}\n"
        f"User description: {description or 'none'}\nConfigured rooms: {room_names}"
    )
    client = OpenAI(api_key=settings.openai_api_key)
    response = client.chat.completions.create(
        model=settings.openai_model,
        temperature=0.2,
        messages=[
            {"role": "system", "content": "You extract structured house intelligence for a Home Assistant AI."},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            },
        ],
    )
    content = response.choices[0].message.content or "{}"
    payload = _json_object(content)
    payload.setdefault("provider", "openai")
    payload.setdefault("fallback_reason", "")
    return _normalized_analysis(payload, title, asset_type, room, filename, description)


def _fallback_analysis(title: str, asset_type: str, room: str, filename: str, description: str) -> dict[str, Any]:
    config = get_config()
    text = " ".join([title, asset_type, room, filename, description]).lower()
    room_candidates = [
        r.name for r in config.devices.rooms
        if _matches_room(text, r.name, getattr(r, "aliases", []))
    ]
    if room and room not in room_candidates:
        room_candidates.insert(0, room)
    inferred_type = _infer_asset_type(text, asset_type)
    payload = {
        "provider": "fallback",
        "fallback_reason": "",
        "summary": (
            description.strip()
            or f"Uploaded {inferred_type.replace('_', ' ')} asset for {', '.join(room_candidates) if room_candidates else 'the house'}."
        ),
        "asset_type": inferred_type,
        "room_candidates": room_candidates,
        "dashboard_uses": [
            "Use as reference when drafting room dashboards and tablet panels.",
            "Use room candidates to suggest zone/device grouping before changing Home Assistant.",
            "Keep this asset approval-first so layout assumptions are visible before automation use.",
        ],
        "automation_ideas": [
            "Suggest lighting, media, and bedtime routines only after mapped devices are approved.",
        ],
        "mapping_questions": _mapping_questions(inferred_type, room_candidates),
        "safety_notes": [
            "Do not infer security device placement as final until the owner approves it.",
        ],
    }
    return _normalized_analysis(payload, title, asset_type, room, filename, description)


def _mapping_questions(asset_type: str, rooms: list[str]) -> list[str]:
    area = ", ".join(rooms) if rooms else "this area"
    questions = [
        f"Which lights, switches, fans, speakers, cameras, and displays belong to {area}?",
        f"Where should wall tablets, voice sources, and dashboards be mounted for {area}?",
    ]
    if asset_type in {"floorplan", "blueprint"}:
        questions.append("Which doors, windows, garage entries, and exterior zones should be labeled?")
    return questions


def _set_status(asset_id: int, status: str) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    with get_session() as session:
        row = session.get(HouseAsset, asset_id)
        if not row:
            raise ValueError("House asset not found.")
        row.status = status
        row.updated_at = now
        session.commit()
        session.refresh(row)
        return _row_to_dict(row)


def _asset_dir() -> Path:
    return get_settings().config_path / "house_assets"


def _safe_filename(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", name.strip()).strip(".-")
    return cleaned[:120] or "house-asset"


def _allowed_content_type(content_type: str) -> bool:
    return (
        content_type in ALLOWED_CONTENT_TYPES
        or any(content_type.startswith(prefix) for prefix in ALLOWED_CONTENT_PREFIXES)
    )


def _infer_asset_type(text: str, default: str) -> str:
    if "blueprint" in text:
        return "blueprint"
    if "floor" in text or "plan" in text or "layout" in text:
        return "floorplan"
    if "photo" in text or "picture" in text or "image" in text:
        return "photo"
    if "note" in text:
        return "note"
    return (default or "floorplan").strip().lower()


def _matches_room(text: str, name: str, aliases: list[str]) -> bool:
    values = [name, *(aliases or [])]
    for value in values:
        needle = re.sub(r"\s+", " ", str(value).strip().lower())
        if needle and needle in text:
            return True
    return False


def _json_object(text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.S)
        if not match:
            return {}
        try:
            parsed = json.loads(match.group(0))
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}


def _normalized_analysis(
    payload: dict[str, Any],
    title: str,
    asset_type: str,
    room: str,
    filename: str,
    description: str,
) -> dict[str, Any]:
    def list_value(key: str) -> list[str]:
        value = payload.get(key)
        if isinstance(value, list):
            return [str(v).strip() for v in value if str(v).strip()]
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        return []

    return {
        "provider": str(payload.get("provider") or "fallback"),
        "fallback_reason": str(payload.get("fallback_reason") or ""),
        "summary": str(payload.get("summary") or description or f"Uploaded house asset: {title or filename}."),
        "asset_type": str(payload.get("asset_type") or _infer_asset_type(" ".join([title, filename]), asset_type)),
        "room_candidates": list_value("room_candidates") or ([room] if room else []),
        "dashboard_uses": list_value("dashboard_uses"),
        "automation_ideas": list_value("automation_ideas"),
        "mapping_questions": list_value("mapping_questions"),
        "safety_notes": list_value("safety_notes"),
    }


def _row_to_dict(row: HouseAsset) -> dict[str, Any]:
    try:
        analysis = json.loads(row.analysis or "{}")
    except json.JSONDecodeError:
        analysis = {}
    return {
        "id": row.id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "title": row.title,
        "asset_type": row.asset_type,
        "room": row.room,
        "original_filename": row.original_filename,
        "stored_filename": row.stored_filename,
        "content_type": row.content_type,
        "storage_path": row.storage_path,
        "status": row.status,
        "description": row.description,
        "analysis": analysis,
        "uploaded_by": row.uploaded_by,
    }
