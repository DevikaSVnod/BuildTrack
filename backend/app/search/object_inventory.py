"""
Structured object inventory for drawings/images.

At upload: GPT vision + tiled counting → JSON inventory stored on the drawing.
At ask time: answer count/object questions from that inventory first.
"""
from __future__ import annotations

import base64
import io
import json
import logging
import re
from typing import Any, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

INVENTORY_MARKER = "\n---OBJECT INVENTORY---\n"

# Types that benefit from tile-based recounting (dense / repeated).
_DENSE_TYPES = frozenset({"chair", "chairs", "desk", "desks", "table", "tables", "bed", "beds"})

_COUNT_ELEMENT = re.compile(
    r"\b(chairs?|desks?|doors?|tables?|workstations?|beds?|sofas?|rooms?|"
    r"toilets?|sinks?|showers?|projectors?|screens?|"
    r"motors?|sprockets?|washers?|nuts?|screws?|bolts?|cabinets?|"
    r"roller\s+chains?|support\s+legs?|conveyors?|staircases?|windows?|"
    r"entries|exits|entry|exit|"
    r"gcp|grading\s+control\s+points?|buildings?|roads?|hostels?)\b",
    re.I,
)

_SITE_OBJECT_HINTS = (
    "building",
    "hostel",
    "road",
    "gcp",
    "grading control",
    "water tank",
    "playground",
    "play ground",
    "sports complex",
    "guest house",
    "green belt",
    "plot boundary",
    "ht line",
    "utility",
    "campus",
    "grading plan",
    "site grading",
)

_INTERIOR_FURNITURE = frozenset(
    {"chair", "bed", "desk", "sofa", "toilet", "shower", "table"}
)

_GENERIC_SITE_TYPES = frozenset(
    {
        "building",
        "buildings",
        "structure",
        "structures",
        "block",
        "blocks",
        "facility",
        "facilities",
        "site feature",
        "site features",
        "area",
        "areas",
    }
)

_VAGUE_SITE_LOCATIONS = frozenset(
    {
        "north",
        "south",
        "east",
        "west",
        "center",
        "centre",
        "central",
        "left",
        "right",
        "top",
        "bottom",
        "across site",
        "site",
        "campus",
        "unknown",
    }
)

_SITE_LEGEND_PHRASES = (
    "plot boundary",
    "finished ground",
    "finished road",
    "grading control point",
    "legend",
    "line type",
    "symbol",
)

def _vision_ready() -> bool:
    return bool(
        settings.AZURE_OPENAI_VISION_DEPLOYMENT
        and settings.AZURE_OPENAI_ENDPOINT
        and settings.AZURE_OPENAI_KEY
    )

def _client():
    from openai import AzureOpenAI

    return AzureOpenAI(
        azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
        api_key=settings.AZURE_OPENAI_KEY,
        api_version="2024-02-01",
    )

def _data_url(content: bytes, content_type: str) -> str:
    mime = content_type if content_type.startswith("image/") else "image/png"
    return f"data:{mime};base64,{base64.b64encode(content).decode('ascii')}"

def _normalize_item_name(name: str) -> str:
    n = (name or "").strip().lower()
    n = n.replace("/", " ").replace("-", " ")
    n = re.sub(r"\s+", " ", n).strip()
    # Common aliases
    if n in {"counter", "counter desk", "wall counter", "countertop"}:
        return "desk"
    if n in {"seat", "seating"}:
        return "chair"
    if n in {"stair", "stairs", "stairwell"}:
        return "staircase"
    if n in {"closet zone", "wardrobe", "hanger", "hangers", "hanger rod"}:
        return "closet"
    if n in {"pedestal", "locker", "cabinet pedestal"}:
        return "cabinet"
    if " " in n:
        # keep primary noun (last token usually): "conference table" → table
        parts = n.split()
        if parts[-1] in {"chair", "table", "desk", "door", "bed", "sofa", "sink"}:
            n = parts[-1]
    if n.endswith("ies") and len(n) > 3:
        return n[:-3] + "y"
    if n.endswith("ses"):
        return n[:-2]
    if n.endswith("s") and not n.endswith("ss"):
        return n[:-1]
    if n in {"gcp", "grading point", "grading control point", "control point"}:
        return "grading control point"
    if re.match(r"^gcp[\s-]?\d", n):
        return "grading control point"
    return n


def _pluralize(name: str, count: int) -> str:
    base = _normalize_item_name(name)
    if count == 1:
        return base
    if base.endswith("y") and base[-2:] not in ("ay", "ey", "oy", "uy"):
        return base[:-1] + "ies"
    if base.endswith(("s", "x", "z", "ch", "sh")):
        return base + "es"
    return base + "s"


def empty_inventory(scene: str = "unknown") -> dict[str, Any]:
    return {
        "scene": scene,
        "objects": [],
        "method": "none",
        "confidence": "low",
        "limitations": "",
    }


def inventory_to_search_text(inventory: Optional[dict[str, Any]]) -> str:
    """Plain text block for sheet_notes / RAG sidecar."""
    if not inventory or not isinstance(inventory, dict):
        return ""
    objects = inventory.get("objects") or []
    if not objects:
        return ""
    lines = [
        "OBJECT INVENTORY (structured):",
        f"Scene: {inventory.get('scene') or 'unknown'}",
    ]
    for row in objects:
        if not isinstance(row, dict):
            continue
        item = str(row.get("type") or row.get("item") or "").strip()
        if not item:
            continue
        count = row.get("count")
        loc = str(row.get("location") or "").strip()
        line = f"- {item}: {count}" if count is not None else f"- {item}"
        if loc:
            line += f" ({loc})"
        lines.append(line)
    conf = inventory.get("confidence")
    if conf:
        lines.append(f"Confidence: {conf}")
    lim = str(inventory.get("limitations") or "").strip()
    if lim:
        lines.append(f"Limitations: {lim}")
    return "\n".join(lines)


def embed_inventory_in_notes(notes: str, inventory: Optional[dict[str, Any]]) -> str:
    """Append / replace OBJECT INVENTORY JSON marker in sheet_notes."""
    base = notes or ""
    if INVENTORY_MARKER in base:
        base = base.split(INVENTORY_MARKER, 1)[0].rstrip()
    if not inventory or not inventory.get("objects"):
        return base
    payload = json.dumps(inventory, ensure_ascii=False)
    return f"{base}{INVENTORY_MARKER}{payload}"


def parse_inventory_from_notes(notes: Optional[str]) -> Optional[dict[str, Any]]:
    text = notes or ""
    if INVENTORY_MARKER not in text:
        return None
    raw = text.split(INVENTORY_MARKER, 1)[1].strip()
    # Stop at next marker-like section if present
    if "\n---" in raw:
        raw = raw.split("\n---", 1)[0].strip()
    try:
        data = json.loads(raw)
        if isinstance(data, dict) and data.get("objects") is not None:
            return data
    except json.JSONDecodeError:
        logger.debug("Could not parse object inventory JSON from sheet_notes")
    return None


def parse_inventory_json(raw: Optional[str]) -> Optional[dict[str, Any]]:
    if not raw or not str(raw).strip():
        return None
    try:
        data = json.loads(raw)
        if isinstance(data, dict) and data.get("objects") is not None:
            return data
    except json.JSONDecodeError:
        return None
    return None


def resolve_drawing_inventory(drawing: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Load inventory from hit metadata, sheet_notes marker, or SQL row."""
    meta = drawing.get("metadata") or {}
    inv = meta.get("object_inventory")
    if isinstance(inv, dict) and inv.get("objects") is not None:
        return inv
    if isinstance(inv, str):
        parsed = parse_inventory_json(inv)
        if parsed:
            return parsed

    from_notes = parse_inventory_from_notes(meta.get("sheet_notes") or drawing.get("snippet"))
    if from_notes:
        return from_notes

    # Fresh from SQL
    try:
        from app.core.database import SessionLocal
        from app.models.operational import EngineeringDrawing

        drawing_no = (meta.get("drawing_no") or "").strip()
        drawing_id = meta.get("drawing_id")
        db = SessionLocal()
        try:
            q = db.query(EngineeringDrawing)
            row = None
            if drawing_no:
                row = q.filter(EngineeringDrawing.drawing_no == drawing_no).first()
            elif drawing_id is not None:
                row = q.filter(EngineeringDrawing.id == int(drawing_id)).first()
            if not row:
                return None
            col = getattr(row, "object_inventory", None)
            parsed = parse_inventory_json(col)
            if parsed:
                return parsed
            return parse_inventory_from_notes(row.sheet_notes)
        finally:
            db.close()
    except Exception as exc:
        logger.debug("resolve_drawing_inventory SQL lookup failed: %s", exc)
        return None


def _tile_image(content: bytes, grid: int = 2, overlap: float = 0.05) -> list[tuple[bytes, str, str]]:
    """
    Split image into non-overlapping-ish tiles (small overlap for edge objects).
    Returns list of (png_bytes, content_type, tile_label).
    """
    try:
        from PIL import Image
    except ImportError:
        logger.warning("Pillow not installed — skipping tiled object counting")
        return []

    img = Image.open(io.BytesIO(content)).convert("RGB")
    w, h = img.size
    if w < 400 or h < 400:
        return []

    tiles: list[tuple[bytes, str, str]] = []
    step_x = w / grid
    step_y = h / grid
    ox = int(step_x * overlap)
    oy = int(step_y * overlap)

    for row in range(grid):
        for col in range(grid):
            left = max(0, int(col * step_x) - (ox if col else 0))
            upper = max(0, int(row * step_y) - (oy if row else 0))
            right = min(w, int((col + 1) * step_x) + (ox if col < grid - 1 else 0))
            lower = min(h, int((row + 1) * step_y) + (oy if row < grid - 1 else 0))
            crop = img.crop((left, upper, right, lower))
            buf = io.BytesIO()
            crop.save(buf, format="PNG")
            tiles.append((buf.getvalue(), "image/png", f"tile-r{row}c{col}"))
    return tiles


def _vision_json(
    *,
    client,
    deployment: str,
    system: str,
    prompt: str,
    image_bytes: bytes,
    content_type: str,
    max_tokens: int = 900,
    detail: str = "high",
) -> dict[str, Any]:
    image_payload: dict[str, Any] = {"url": _data_url(image_bytes, content_type)}
    if detail:
        image_payload["detail"] = detail
    resp = client.chat.completions.create(
        model=deployment,
        messages=[
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": image_payload},
                ],
            },
        ],
        max_tokens=max_tokens,
        temperature=0.0,
        response_format={"type": "json_object"},
    )
    raw = (resp.choices[0].message.content or "{}").strip()
    return json.loads(raw)


def _normalize_objects(raw_objects: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not isinstance(raw_objects, list):
        return out
    for row in raw_objects:
        if not isinstance(row, dict):
            continue
        item = str(row.get("type") or row.get("item") or "").strip().lower()
        if not item:
            continue
        try:
            count = int(row.get("count"))
        except (TypeError, ValueError):
            continue
        if count < 0:
            continue
        loc = str(row.get("location") or "").strip()
        out.append({"type": item, "count": count, "location": loc})
    return out


def _merge_object_lists(*lists: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sum counts by normalized type; keep first non-empty location."""
    totals: dict[str, dict[str, Any]] = {}
    for lst in lists:
        for row in lst:
            key = _normalize_item_name(str(row.get("type") or ""))
            if not key:
                continue
            try:
                n = int(row.get("count") or 0)
            except (TypeError, ValueError):
                n = 0
            if key not in totals:
                totals[key] = {
                    "type": key,
                    "count": n,
                    "location": str(row.get("location") or "").strip(),
                }
            else:
                totals[key]["count"] += n
                if not totals[key]["location"] and row.get("location"):
                    totals[key]["location"] = str(row.get("location")).strip()
    return sorted(totals.values(), key=lambda x: (-int(x["count"]), x["type"]))


def _full_image_inventory(client, deployment: str, content: bytes, content_type: str) -> dict[str, Any]:
    prompt = (
        "Inventory every distinct visible object in this image "
        "(photo, architectural floor-plan, OR mechanical/assembly drawing).\n\n"
        "If this is a MECHANICAL / assembly drawing with a parts list / BOM table:\n"
        "- Set scene to something like 'screw conveyor assembly drawing' or 'mechanical assembly'.\n"
        "- Prefer reading ITEM / QTY / PART from the BOM table (do not guess fastener counts from the isometric).\n"
        "- Still list major assemblies visible (motor, conveyor trough, sprockets, chain, legs).\n\n"
        "If this is an architectural floor-plan, include when visible:\n"
        "- beds, chairs/desk chairs (NOT pedestal X-boxes), desks/workstations, tables,\n"
        "- sofas, staircase, nightstands, closets, cabinets/pedestals, doors, windows,\n"
        "- toilets, sinks, showers.\n"
        "On office plans: one chair per workstation desk; sofas are not chairs.\n"
        "Closet hanger shapes are NOT chairs.\n"
        "Do not invent items.\n"
        'Return JSON: {"scene": "short scene label", "objects": ['
        '{"type": "desk", "count": 4, "location": "workstations"}, ...], '
        '"confidence": "high|medium|low", "limitations": "what is unclear"}'
    )
    system = (
        "You build a structured object inventory from images, floor plans, and mechanical drawings. "
        "If a BOM/parts table is present, treat its quantities as authoritative. "
        "Be precise on counts. Return valid JSON only."
    )
    payload = _vision_json(
        client=client,
        deployment=deployment,
        system=system,
        prompt=prompt,
        image_bytes=content,
        content_type=content_type,
        max_tokens=1400,
        detail="high",
    )
    return {
        "scene": str(payload.get("scene") or "unknown").strip() or "unknown",
        "objects": _normalize_objects(payload.get("objects")),
        "confidence": str(payload.get("confidence") or "medium").lower(),
        "limitations": str(payload.get("limitations") or "").strip(),
        "method": "full_image",
    }


def _is_mechanical_drawing(scene: str, objects: list[dict[str, Any]]) -> bool:
    s = (scene or "").lower()
    if any(
        k in s
        for k in (
            "mechanical",
            "assembly",
            "conveyor",
            "bom",
            "bill of materials",
            "parts list",
            "sprocket",
            "gearbox",
            "screw con",
            "technical drawing",
            "machine",
            "equipment",
        )
    ):
        return True
    types = {_normalize_item_name(str(o.get("type"))) for o in objects}
    mech = {
        "motor",
        "sprocket",
        "roller chain",
        "chain",
        "hex screw",
        "screw",
        "washer",
        "conveyor",
        "screw conveyor",
        "nut",
        "bolt",
    }
    # raw types may still have spaces before furniture normalize
    raw = {str(o.get("type") or "").strip().lower() for o in objects}
    if sum(1 for t in types if t in mech or any(m in t for m in mech)) >= 2:
        return True
    if any("screw" in t or "sprocket" in t or "conveyor" in t or "motor" in t for t in raw):
        return True
    return False


def _has_interior_furniture_focus(objects: list[dict[str, Any]]) -> bool:
    """True when the inventory is dominated by interior floor-plan furniture."""
    types = {_normalize_item_name(str(o.get("type"))) for o in objects}
    return len(types & _INTERIOR_FURNITURE) >= 2


def _site_object_signal(objects: list[dict[str, Any]]) -> int:
    """Count site/civil hints in object types and locations."""
    hits = 0
    for row in objects:
        hay = f"{row.get('type') or ''} {row.get('location') or ''}".lower()
        if any(h in hay for h in _SITE_OBJECT_HINTS):
            hits += 1
    return hits


def _is_site_plan(scene: str, objects: list[dict[str, Any]]) -> bool:
    """
    Detect civil / site / campus grading plans.
    Conservative: requires site keywords or multiple site features, and rejects
    interior furniture-heavy sheets so floor-plan paths stay unchanged.
    """
    s = (scene or "").lower()
    if _has_interior_furniture_focus(objects):
        return False

    strong_site = (
        "site grading",
        "grading plan",
        "site plan",
        "campus plan",
        "campus layout",
        "topographic",
        "topography",
        "civil site",
        "site layout",
        "land development",
        "site development",
        "grading control",
    )
    if any(k in s for k in strong_site):
        if ("floor plan" in s or "floor-plan" in s) and not any(
            k in s for k in ("site", "campus", "grading")
        ):
            return False
        return True

    # "master plan" alone is ambiguous — require a site feature signal too
    if "master plan" in s and _site_object_signal(objects) >= 1:
        return True

    site_hits = _site_object_signal(objects)
    if site_hits >= 2:
        return True
    if site_hits >= 1 and any(k in s for k in ("campus", "site", "grading", "civil")):
        return True
    return False


def _is_generic_site_type(name: str) -> bool:
    n = (name or "").strip().lower()
    return n in _GENERIC_SITE_TYPES or n in {"road", "utility", "utilities"}


def _is_site_legend_row(row: dict[str, Any]) -> bool:
    hay = f"{row.get('type') or ''} {row.get('location') or ''}".lower()
    return any(p in hay for p in _SITE_LEGEND_PHRASES)


def _promote_site_row(row: dict[str, Any]) -> dict[str, Any]:
    """Use printed label fields when vision returned a generic type like 'building'."""
    item = str(
        row.get("type") or row.get("name") or row.get("label") or row.get("item") or ""
    ).strip()
    loc = str(row.get("location") or row.get("zone") or "").strip()
    alt = str(row.get("label") or row.get("title") or row.get("name") or "").strip()

    if alt and _is_generic_site_type(item) and not _is_generic_site_type(alt):
        item = alt
    elif _is_generic_site_type(item) and loc:
        loc_l = loc.lower()
        if loc_l not in _VAGUE_SITE_LOCATIONS and len(loc) > 4:
            if not re.match(r"^(north|south|east|west|central|left|right|top|bottom)\b", loc_l):
                item = loc
                loc = ""

    item_l = item.lower()
    if item_l in {"gcp", "grading point", "grading control point"} or re.match(
        r"^gcp[\s-]?\d", item_l, re.I
    ):
        item = "grading control point"

    try:
        count = int(row.get("count"))
    except (TypeError, ValueError):
        count = 1
    return {"type": item, "count": max(0, count), "location": loc}


def _normalize_site_objects(raw_objects: Any) -> list[dict[str, Any]]:
    """Normalize site-plan inventory rows; preserve building/road names in type."""
    out: list[dict[str, Any]] = []
    if not isinstance(raw_objects, list):
        return out
    for row in raw_objects:
        if not isinstance(row, dict):
            continue
        promoted = _promote_site_row(row)
        item = promoted.get("type") or ""
        if not str(item).strip():
            continue
        if _is_site_legend_row(promoted) and _is_generic_site_type(str(item)):
            continue
        out.append(promoted)
    return out


def _generic_building_count(objects: list[dict[str, Any]]) -> int:
    return sum(
        1
        for o in objects
        if str(o.get("type") or "").strip().lower() in {"building", "buildings", "structure", "structures"}
    )


def _site_building_names_pass(
    client,
    deployment: str,
    content: bytes,
    content_type: str,
) -> list[dict[str, Any]]:
    """Second pass when vision returns generic 'building' instead of printed labels."""
    prompt = (
        "This is a site / campus / grading plan. List every NAMED building or block "
        "with its EXACT printed label on the drawing.\n\n"
        "Examples of good names: 'Girls Hostel', 'Boys Hostel', "
        "'Instructional & Administrative Block', 'Indoor Sports Complex', "
        "'Guest House', 'Water Tank', 'AC Plant RM', 'Play Ground'.\n\n"
        "Rules:\n"
        "- NEVER use the generic word 'building' alone as the name.\n"
        "- Copy the label text from the plan exactly.\n"
        "- One row per distinct labeled building footprint (count=1 each).\n"
        "- Skip roads, GCP markers, legend symbols, and plot boundary lines.\n\n"
        'Return JSON: {"buildings":[{"name":"Girls Hostel","location":"optional zone"},...], '
        '"confidence":"high|medium|low","limitations":""}'
    )
    system = (
        "You read building labels on civil site plans. Each name must be the printed "
        "label, not the generic word building. Return valid JSON only."
    )
    try:
        payload = _vision_json(
            client=client,
            deployment=deployment,
            system=system,
            prompt=prompt,
            image_bytes=content,
            content_type=content_type,
            max_tokens=1200,
            detail="high",
        )
    except Exception as exc:
        logger.warning("Site building name pass failed: %s", exc)
        return []

    rows: list[dict[str, Any]] = []
    for entry in payload.get("buildings") or []:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or entry.get("type") or entry.get("label") or "").strip()
        if not name or _is_generic_site_type(name):
            continue
        loc = str(entry.get("location") or entry.get("zone") or "").strip()
        rows.append({"type": name, "count": 1, "location": loc})
    return rows


def _polish_site_objects(
    objects: list[dict[str, Any]],
    *,
    client=None,
    deployment: str = "",
    content: bytes | None = None,
    content_type: str = "image/png",
) -> list[dict[str, Any]]:
    """Drop legend noise; replace generic building rows with named labels when possible."""
    cleaned: list[dict[str, Any]] = []
    for row in objects:
        promoted = _promote_site_row(row)
        t = str(promoted.get("type") or "").strip()
        if not t:
            continue
        t_l = t.lower()
        if _is_site_legend_row(promoted) and t_l not in {"grading control point"}:
            continue
        cleaned.append(promoted)

    if _generic_building_count(cleaned) >= 2 and client and deployment and content:
        named = _site_building_names_pass(client, deployment, content, content_type)
        if named:
            non_generic = [
                o
                for o in cleaned
                if str(o.get("type") or "").strip().lower()
                not in {"building", "buildings", "structure", "structures", "block", "blocks"}
            ]
            cleaned = non_generic + named

    # Dedupe by type label (case-insensitive)
    by_key: dict[str, dict[str, Any]] = {}
    for row in cleaned:
        key = str(row.get("type") or "").strip().lower()
        if not key:
            continue
        prev = by_key.get(key)
        if prev is None:
            by_key[key] = dict(row)
        else:
            try:
                prev["count"] = max(int(prev.get("count") or 0), int(row.get("count") or 0))
            except (TypeError, ValueError):
                pass
            if not prev.get("location") and row.get("location"):
                prev["location"] = row.get("location")
    return list(by_key.values())


def _site_display_label(row: dict[str, Any]) -> str:
    """User-facing label for a site inventory row."""
    item = str(row.get("type") or "").strip()
    loc = str(row.get("location") or "").strip()
    if _is_generic_site_type(item) and loc and loc.lower() not in _VAGUE_SITE_LOCATIONS:
        return loc
    return item


def _is_site_building_row(row: dict[str, Any]) -> bool:
    hay = _site_display_label(row).lower()
    if _is_site_legend_row(row) and "grading control" not in hay:
        return False
    if hay in {"grading control point", "gcp"}:
        return False
    if _is_generic_site_type(hay):
        return False
    return bool(
        re.search(
            r"building|hostel|block|complex|house|tank|playground|play\s+ground|"
            r"sports|admin|guest|plant|school|library|auditorium|cafeteria|"
            r"warehouse|factory|tower|hall|dormitory|dorm",
            hay,
        )
    )


def _is_site_road_row(row: dict[str, Any]) -> bool:
    hay = _site_display_label(row).lower()
    return bool(re.search(r"\broad\b|carriageway|street|avenue|drive|belt|circulation", hay))


def _site_gcp_tile_count(
    client,
    deployment: str,
    content: bytes,
    content_type: str,
) -> int:
    """Tile-based recount for dense grading control point (GCP) symbols."""
    tiles = _tile_image(content, grid=3, overlap=0.0)
    if not tiles:
        return 0

    system = (
        "You count grading control point (GCP) symbols on a civil/site plan crop. "
        "Count each visible GCP circle/marker labeled GCP-XX or matching the legend "
        "grading-control-point symbol. Count only in THIS crop. Return JSON only."
    )
    total = 0
    for tile_bytes, tile_type, label in tiles:
        prompt = (
            f"This is crop {label} of a larger site grading / campus plan.\n"
            "Count every visible grading control point (GCP) marker in this crop.\n"
            'Return JSON: {"gcp_count": N}'
        )
        try:
            payload = _vision_json(
                client=client,
                deployment=deployment,
                system=system,
                prompt=prompt,
                image_bytes=tile_bytes,
                content_type=tile_type,
                max_tokens=200,
                detail="high",
            )
            total += max(0, int(payload.get("gcp_count") or 0))
        except Exception as exc:
            logger.warning("Site GCP tile count failed for %s: %s", label, exc)
    return total


def _site_plan_inventory(
    client,
    deployment: str,
    content: bytes,
    content_type: str,
    *,
    use_tiling: bool = True,
) -> dict[str, Any]:
    """
    Civil / site / campus grading plans: buildings, roads, utilities, GCPs.
    Separate from interior floor-plan furniture paths.
    """
    prompt = (
        "This is a CIVIL / SITE / CAMPUS engineering drawing (site plan, grading plan, "
        "master plan, or campus layout) — NOT an interior furniture floor plan.\n\n"
        "Inventory SITE FEATURES only. For each row, set \"type\" to the EXACT printed "
        "label on the drawing — NEVER the generic word \"building\" alone.\n\n"
        "Good examples:\n"
        '- {"type":"Girls Hostel","count":1,"location":"central-left"}\n'
        '- {"type":"Instructional & Administrative Block","count":1,"location":"center"}\n'
        '- {"type":"Proposed 26.0M Wide Road","count":1,"location":"west edge"}\n'
        '- {"type":"Play Ground","count":1,"location":"center"}\n'
        '- {"type":"grading control point","count":42,"location":"across site"}\n\n'
        "Include when visible:\n"
        "- Named buildings/blocks (hostels, admin block, sports complex, guest house, water tank, etc.)\n"
        "- Roads / carriageways (include width in the type if labeled)\n"
        "- Open areas (playground, parking, green belt)\n"
        "- Utilities (HT line, AC plant, etc.)\n"
        "- One aggregate row for all GCP / grading control point markers\n\n"
        "Put legend symbol definitions (plot boundary line type, hatching meanings) in "
        "legend_notes — NOT as separate building rows.\n"
        "Do NOT count interior furniture. Do NOT guess GCP count.\n"
        'Return JSON: {"scene":"site grading plan - ...", "objects":[...], '
        '"legend_notes":["..."], "confidence":"high|medium|low", "limitations":""}'
    )
    system = (
        "You build a structured site/civil plan inventory. Each object type must be the "
        "printed label from the plan, never the generic word building. Return valid JSON only."
    )
    payload = _vision_json(
        client=client,
        deployment=deployment,
        system=system,
        prompt=prompt,
        image_bytes=content,
        content_type=content_type,
        max_tokens=1600,
        detail="high",
    )
    objects = _normalize_site_objects(payload.get("objects"))
    objects = _polish_site_objects(
        objects,
        client=client,
        deployment=deployment,
        content=content,
        content_type=content_type,
    )
    scene = str(payload.get("scene") or "site plan").strip() or "site plan"
    confidence = str(payload.get("confidence") or "medium").lower()
    limitations = str(payload.get("limitations") or "").strip()
    legend_notes = payload.get("legend_notes") or []
    if isinstance(legend_notes, list) and legend_notes:
        lim_extra = "Legend: " + "; ".join(str(x).strip() for x in legend_notes[:6] if str(x).strip())
        limitations = f"{limitations} {lim_extra}".strip() if limitations else lim_extra

    gcp_full = 0
    for row in objects:
        if _normalize_item_name(str(row.get("type"))) == "grading control point":
            try:
                gcp_full = int(row.get("count") or 0)
            except (TypeError, ValueError):
                gcp_full = 0
            break

    gcp_tiled = 0
    if use_tiling and (gcp_full >= 8 or gcp_full == 0):
        try:
            gcp_tiled = _site_gcp_tile_count(client, deployment, content, content_type)
        except Exception as exc:
            logger.warning("Site GCP tiling failed: %s", exc)

    if gcp_tiled > 0:
        best_gcp = gcp_tiled
        if gcp_full > 0 and gcp_full < gcp_tiled * 0.6:
            note = f"GCP count uses 3×3 tile recount ({gcp_tiled}); full-sheet pass saw {gcp_full}."
        elif gcp_full > gcp_tiled * 1.4:
            best_gcp = gcp_full
            note = f"GCP count uses full-sheet pass ({gcp_full}); tiles summed {gcp_tiled}."
        else:
            best_gcp = max(gcp_full, gcp_tiled)
            note = ""
        updated = False
        for row in objects:
            if _normalize_item_name(str(row.get("type"))) == "grading control point":
                row["count"] = best_gcp
                row["location"] = str(row.get("location") or "across site").strip() or "across site"
                updated = True
                break
        if not updated:
            objects.append(
                {
                    "type": "grading control point",
                    "count": best_gcp,
                    "location": "across site (tiled recount)",
                }
            )
        if note:
            limitations = f"{limitations} {note}".strip() if limitations else note

    return {
        "scene": scene,
        "objects": sorted(objects, key=lambda x: (-int(x.get("count") or 0), str(x.get("type")))),
        "confidence": confidence,
        "limitations": limitations,
        "method": "site_plan",
    }


def _normalize_bom_type(name: str) -> str:
    """Light normalize for BOM part names — keep size/spec suffixes."""
    n = (name or "").strip().lower()
    n = n.replace("plan washer", "plain washer")
    n = re.sub(r"\s+", " ", n)
    return n


def _bom_inventory(
    client,
    deployment: str,
    content: bytes,
    content_type: str,
) -> dict[str, Any]:
    """
    Mechanical/assembly drawings: read the BOM / parts list table as the
    authoritative inventory (not guesses from the isometric view).
    """
    from PIL import Image

    table_inv: dict[str, Any] = {"objects": []}
    try:
        img = Image.open(io.BytesIO(content)).convert("RGB")
        w, h = img.size
        # Right-side BOM region (upper+lower if table is tall)
        crops = [
            (0.52, 0.06, 0.99, 0.72),  # main parts list
            (0.52, 0.45, 0.99, 0.88),  # lower rows / title-block adjacent
        ]
        by_item: dict[str, dict[str, Any]] = {}
        best_conf = "low"
        lim_parts: list[str] = []
        for x0, y0, x1, y1 in crops:
            buf = io.BytesIO()
            img.crop((int(w * x0), int(h * y0), int(w * x1), int(h * y1))).save(
                buf, format="PNG"
            )
            part = _bom_table_read(client, deployment, buf.getvalue(), "image/png")
            if part.get("confidence") == "high":
                best_conf = "high"
            elif part.get("confidence") == "medium" and best_conf != "high":
                best_conf = "medium"
            if part.get("limitations"):
                lim_parts.append(str(part["limitations"]))
            for row in part.get("objects") or []:
                key = _bom_item_key(row)
                if not key:
                    continue
                prev = by_item.get(key)
                # Prefer higher qty when same item re-read (misreads often under-count)
                if prev is None or int(row.get("count") or 0) > int(prev.get("count") or 0):
                    by_item[key] = row
        if by_item:
            table_inv = {
                "scene": "mechanical assembly drawing",
                "objects": list(by_item.values()),
                "confidence": best_conf,
                "limitations": " ".join(dict.fromkeys(lim_parts))[:400],
            }
    except Exception as exc:
        logger.warning("BOM crop failed: %s", exc)

    if not (table_inv.get("objects")):
        table_inv = _bom_table_read(client, deployment, content, content_type)

    assemblies = _bom_assembly_overview(client, deployment, content, content_type)

    bom_objects = list(table_inv.get("objects") or [])
    bom_types = {_normalize_bom_type(str(o.get("type") or "")) for o in bom_objects}
    for row in assemblies.get("objects") or []:
        t = _normalize_bom_type(str(row.get("type") or ""))
        if not t:
            continue
        if any(t in bt or bt in t for bt in bom_types if bt):
            continue
        # Skip fastener-ish assembly guesses when BOM already has fasteners
        if any(k in t for k in ("screw", "washer", "nut", "bolt")) and any(
            k in bt for bt in bom_types for k in ("screw", "washer", "nut")
        ):
            continue
        bom_objects.append(row)

    bom_objects = _add_bom_aggregates(bom_objects)

    scene = (
        str(assemblies.get("scene") or table_inv.get("scene") or "").strip()
        or "mechanical assembly drawing"
    )
    lim = " ".join(
        p
        for p in (
            str(table_inv.get("limitations") or "").strip(),
            str(assemblies.get("limitations") or "").strip(),
            "Quantities taken from the drawing BOM/parts list where readable.",
        )
        if p
    )
    return {
        "scene": scene,
        "objects": bom_objects,
        "confidence": str(
            table_inv.get("confidence") or assemblies.get("confidence") or "medium"
        ).lower(),
        "limitations": lim,
        "method": "bom_table",
    }


def _bom_item_key(row: dict[str, Any]) -> str:
    loc = str(row.get("location") or "")
    m = re.search(r"BOM item\s+(\d+)", loc, re.I)
    if m:
        return f"item:{m.group(1)}"
    t = _normalize_bom_type(str(row.get("type") or ""))
    return f"type:{t}" if t else ""


def _bom_table_read(
    client,
    deployment: str,
    image_bytes: bytes,
    content_type: str,
) -> dict[str, Any]:
    # Upscale small table crops — improves digit readout for QTY
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        w, h = img.size
        if w < 1400:
            scale = max(2.0, 1600 / max(w, 1))
            img = img.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            image_bytes, content_type = buf.getvalue(), "image/png"
    except Exception:
        pass

    # Pass 1: raw table transcription (often more accurate on digits)
    transcript_prompt = (
        "Transcribe the PARTS LIST / BOM table as plain text.\n"
        "One row per line in this exact format:\n"
        "ITEM_NO|QTY|DESCRIPTION\n"
        "Example: 11|20|FORMED HEX SCREW M6X1.0X16\n"
        "Copy digits carefully. ITEM_NO is not QTY.\n"
        "Return JSON: {\"lines\": [\"1|1|2020-01-SB-000\", \"7|29|ROLLER CHAIN B ANSI\", ...], "
        "\"confidence\": \"high|medium|low\", \"limitations\": \"\"}"
    )
    try:
        transcript = _vision_json(
            client=client,
            deployment=deployment,
            system=(
                "You OCR engineering BOM tables. Preserve ITEM_NO and QTY exactly. "
                "Return valid JSON only."
            ),
            prompt=transcript_prompt,
            image_bytes=image_bytes,
            content_type=content_type,
            max_tokens=2500,
            detail="high",
        )
    except Exception as exc:
        logger.warning("BOM transcript failed: %s", exc)
        transcript = {}

    objects = _parse_bom_transcript_lines(transcript.get("lines") or [])
    if len(objects) >= 5:
        return {
            "scene": "mechanical assembly drawing",
            "objects": objects,
            "confidence": str(transcript.get("confidence") or "medium").lower(),
            "limitations": str(transcript.get("limitations") or "").strip(),
        }

    # Pass 2: structured JSON fallback
    prompt = (
        "This image is (or contains) a mechanical drawing PARTS LIST / BOM table "
        "with columns like ITEM NO. | QTY | PART NUMBER / DESCRIPTION.\n\n"
        "Read EVERY visible row carefully.\n"
        "CRITICAL: ITEM NO. and QTY are different columns.\n"
        "- item_no = left column (1, 2, 3, ...)\n"
        "- qty = QTY column (the quantity to order/assemble) — copy this digit exactly\n"
        "- Do NOT use the item number as the quantity.\n"
        "- Chain link rows often have large QTY (e.g. 20-40), not 1-2.\n"
        "- Washer/screw/nut rows often have large QTY too.\n\n"
        "Return JSON with keys scene, row_count, objects, confidence, limitations.\n"
        "Each objects[] entry must have: item_no (int), type (short part name), "
        "count (the QTY int), location (string like 'BOM item N; PART NUMBER OR DESC')."
    )
    system = (
        "You extract Bill of Materials rows from engineering drawings. "
        "Never confuse ITEM NO with QTY. QTY is authoritative. Return valid JSON only."
    )
    payload = _vision_json(
        client=client,
        deployment=deployment,
        system=system,
        prompt=prompt,
        image_bytes=image_bytes,
        content_type=content_type,
        max_tokens=2500,
        detail="high",
    )
    objects = []
    for row in payload.get("objects") or []:
        if not isinstance(row, dict):
            continue
        item = _normalize_bom_type(str(row.get("type") or row.get("item") or ""))
        if not item:
            continue
        try:
            count = int(row.get("count") or row.get("qty") or 0)
        except (TypeError, ValueError):
            continue
        if count <= 0:
            continue
        loc = str(row.get("location") or "").strip()
        item_no = row.get("item_no")
        if item_no is not None and "BOM item" not in loc:
            loc = f"BOM item {item_no}; {loc}".strip("; ")
        try:
            ino = int(item_no) if item_no is not None else None
        except (TypeError, ValueError):
            ino = None
        if ino is not None and count == ino and count <= 19:
            if any(k in item for k in ("chain", "washer", "screw", "nut", "bolt")):
                continue
        objects.append({"type": item, "count": count, "location": loc})
    return {
        "scene": str(payload.get("scene") or "mechanical assembly drawing").strip(),
        "objects": objects,
        "confidence": str(payload.get("confidence") or "medium").lower(),
        "limitations": str(payload.get("limitations") or "").strip(),
    }


def _parse_bom_transcript_lines(lines: Any) -> list[dict[str, Any]]:
    if not isinstance(lines, list):
        return []
    out: list[dict[str, Any]] = []
    for line in lines:
        text = str(line or "").strip()
        if not text or text.lower().startswith("item"):
            continue
        # ITEM|QTY|DESC or ITEM,QTY,DESC or whitespace-separated
        parts = re.split(r"[|,\t]", text)
        if len(parts) < 3:
            m = re.match(r"^\s*(\d+)\s+(\d+)\s+(.+)$", text)
            if not m:
                continue
            item_no, qty, desc = m.group(1), m.group(2), m.group(3)
        else:
            item_no, qty, desc = parts[0].strip(), parts[1].strip(), "|".join(parts[2:]).strip()
        try:
            ino = int(re.sub(r"\D", "", item_no) or 0)
            count = int(re.sub(r"\D", "", qty) or 0)
        except ValueError:
            continue
        if ino <= 0 or count <= 0:
            continue
        desc_clean = _normalize_bom_type(desc) or f"item {ino}"
        # Prefer readable type from description; keep PN codes as-is
        out.append(
            {
                "type": desc_clean,
                "count": count,
                "location": f"BOM item {ino}; {desc.strip()}",
            }
        )
    return out


def _bom_assembly_overview(
    client,
    deployment: str,
    content: bytes,
    content_type: str,
) -> dict[str, Any]:
    prompt = (
        "This is a mechanical / equipment assembly drawing (may include isometric + views).\n"
        "List MAJOR assemblies/components visible (not every bolt):\n"
        "e.g. screw conveyor / trough, motor, gearbox, roller chain drive, sprockets, "
        "support legs/stands, inlet hopper, access hatch.\n"
        "Use count 1 for unique assemblies; for support legs count distinct leg frames.\n"
        "Do NOT invent fastener quantities here.\n"
        'Return JSON: {"scene":"short product label",'
        '"objects":[{"type":"motor","count":1,"location":"drive end"},...],'
        '"confidence":"high|medium|low","limitations":""}'
    )
    system = (
        "You identify major mechanical assemblies on engineering drawings. "
        "Return valid JSON only."
    )
    payload = _vision_json(
        client=client,
        deployment=deployment,
        system=system,
        prompt=prompt,
        image_bytes=content,
        content_type=content_type,
        max_tokens=800,
        detail="high",
    )
    objects: list[dict[str, Any]] = []
    for row in payload.get("objects") or []:
        if not isinstance(row, dict):
            continue
        item = _normalize_bom_type(str(row.get("type") or ""))
        if not item:
            continue
        try:
            count = int(row.get("count") or 0)
        except (TypeError, ValueError):
            continue
        if count <= 0:
            continue
        objects.append(
            {
                "type": item,
                "count": count,
                "location": str(row.get("location") or "").strip(),
            }
        )
    return {
        "scene": str(payload.get("scene") or "").strip(),
        "objects": objects,
        "confidence": str(payload.get("confidence") or "medium").lower(),
        "limitations": str(payload.get("limitations") or "").strip(),
    }


def _add_bom_aggregates(objects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Add rolled-up totals for common fastener families so count questions work.
    Keeps detailed BOM lines intact.
    """
    families = {
        "hex screw": re.compile(r"\bhex\s+screw\b|\bscrew\s+m\d", re.I),
        "plain washer": re.compile(r"\bplain\s+washer\b|\bwasher\s+m\d", re.I),
        "hex nut": re.compile(r"\bhex\s+(flange\s+)?nut\b|\bnut\s+m\d", re.I),
        "sprocket": re.compile(r"\bsprocket\b", re.I),
        "roller chain": re.compile(r"\broller\s+chain\b", re.I),
    }
    totals: dict[str, int] = {k: 0 for k in families}
    locs: dict[str, list[str]] = {k: [] for k in families}
    for row in objects:
        t = str(row.get("type") or "")
        try:
            n = int(row.get("count") or 0)
        except (TypeError, ValueError):
            n = 0
        if n <= 0:
            continue
        for fam, pat in families.items():
            if pat.search(t):
                totals[fam] += n
                loc = str(row.get("location") or "").strip()
                if loc:
                    locs[fam].append(loc)
    out = list(objects)
    existing = {_normalize_bom_type(str(o.get("type") or "")) for o in objects}
    for fam, total in totals.items():
        if total <= 0 or fam in existing:
            continue
        if len(locs[fam]) < 2:
            continue
        out.append(
            {
                "type": fam,
                "count": total,
                "location": "BOM aggregate: " + "; ".join(locs[fam][:8]),
            }
        )
    return out


def _is_residential_plan(scene: str, objects: list[dict[str, Any]]) -> bool:
    s = (scene or "").lower()
    if any(k in s for k in ("residential", "bedroom", "apartment", "hotel", "studio", "dorm")):
        return True
    types = {_normalize_item_name(str(o.get("type"))) for o in objects}
    if "bed" in types:
        return True
    if {"toilet", "shower", "sink"} & types and "table" not in types:
        return True
    return False


def _residential_inventory(
    client,
    deployment: str,
    content: bytes,
    content_type: str,
) -> dict[str, Any]:
    """
    Residential / hotel / dorm unit plans: count the center (complete units)
    separately from left/right edge strips (partial units), then merge.
    Avoids L+R zone double-counting and edge hallucination.
    """
    from PIL import Image

    img = Image.open(io.BytesIO(content)).convert("RGB")
    w, h = img.size
    edge = max(int(w * 0.14), 1)
    center = img.crop((edge, 0, w - edge, h))
    left = img.crop((0, 0, edge, h))
    right = img.crop((w - edge, 0, w, h))

    def _png(im: Image.Image) -> bytes:
        buf = io.BytesIO()
        im.save(buf, format="PNG")
        return buf.getvalue()

    center_inv = _residential_crop_count(
        client,
        deployment,
        _png(center),
        "image/png",
        region="CENTER of the sheet (complete bedroom units only; edges already cropped away)",
        allow_partial=False,
    )
    left_inv = _residential_crop_count(
        client,
        deployment,
        _png(left),
        "image/png",
        region="LEFT EDGE STRIP only (partial unit fragment)",
        allow_partial=True,
    )
    right_inv = _residential_crop_count(
        client,
        deployment,
        _png(right),
        "image/png",
        region="RIGHT EDGE STRIP only (partial unit fragment)",
        allow_partial=True,
    )

    merged = _merge_object_lists(
        center_inv.get("objects") or [],
        left_inv.get("objects") or [],
        right_inv.get("objects") or [],
    )
    # Normalize aliases (closet zone → closet; drop freestanding "table" on unit plans)
    cleaned: list[dict[str, Any]] = []
    for row in merged:
        t = _normalize_item_name(str(row.get("type") or ""))
        if t in ("closet zone", "wardrobe", "hanger"):
            t = "closet"
        if t == "table":
            # Residential unit plans use desks, not conference tables
            continue
        if not t:
            continue
        cleaned.append({**row, "type": t})
    merged = _merge_object_lists(cleaned)

    try:
        complete_units = max(0, int(center_inv.get("complete_units") or 0))
    except (TypeError, ValueError):
        complete_units = 0
    if complete_units <= 0:
        beds = next(
            (
                int(o.get("count") or 0)
                for o in (center_inv.get("objects") or [])
                if _normalize_item_name(str(o.get("type"))) == "bed"
            ),
            0,
        )
        complete_units = max(1, beds // 2) if beds else 0

    partial_units = 0
    if left_inv.get("objects"):
        partial_units += 1
    if right_inv.get("objects"):
        partial_units += 1
    if complete_units > 0:
        merged = _cap_residential_counts(merged, complete_units, partial_units)

    lim_parts = [
        str(center_inv.get("limitations") or "").strip(),
        "Center crop for complete units; edge strips for partials only.",
        f"complete_units≈{complete_units}.",
    ]
    return {
        "scene": str(
            center_inv.get("scene") or "residential unit floor-plan"
        ).strip(),
        "objects": merged,
        "confidence": str(center_inv.get("confidence") or "medium").lower(),
        "limitations": " ".join(p for p in lim_parts if p),
        "method": "residential_full",
        "complete_units": complete_units,
        "partial_units": partial_units,
    }


def _residential_crop_count(
    client,
    deployment: str,
    image_bytes: bytes,
    content_type: str,
    *,
    region: str,
    allow_partial: bool,
) -> dict[str, Any]:
    partial_rule = (
        "This is a cropped EDGE fragment. Count only symbols that are mostly visible. "
        "Do not invent missing furniture for an incomplete unit."
        if allow_partial
        else (
            "This crop shows COMPLETE unit(s) only. Count every bed, desk, desk chair, "
            "nightstand, closet zone, door, toilet, sink, shower, and window symbol. "
            "Typical unit: 2 beds, 1 desk, 1 chair, 1 bathroom set, 1 closet. "
            "Closet hanger kidney shapes are NOT chairs."
        )
    )
    prompt = (
        f"Architectural floor-plan crop — {region}.\n"
        f"{partial_rule}\n"
        "Return JSON:\n"
        '{"scene":"residential unit floor-plan",'
        '"complete_units":N,'
        '"objects":[{"type":"bed","count":N,"location":"brief"},...],'
        '"confidence":"high|medium|low",'
        '"limitations":""}'
    )
    system = (
        "You count residential floor-plan furniture symbols in this crop only. "
        "Never count closet hangers as chairs. Return valid JSON only."
    )
    payload = _vision_json(
        client=client,
        deployment=deployment,
        system=system,
        prompt=prompt,
        image_bytes=image_bytes,
        content_type=content_type,
        max_tokens=900,
        detail="high",
    )
    objects = _normalize_objects(payload.get("objects"))
    return {
        "scene": str(payload.get("scene") or "residential unit floor-plan").strip(),
        "objects": objects,
        "confidence": str(payload.get("confidence") or "medium").lower(),
        "limitations": str(payload.get("limitations") or "").strip(),
        "complete_units": payload.get("complete_units") or 0,
    }


def _cap_residential_counts(
    objects: list[dict[str, Any]],
    complete_units: int,
    partial_units: int,
) -> list[dict[str, Any]]:
    """
    Soft cap when vision over-counts by treating partial edges as full units.
    Per complete twin-bed unit: ~2 beds, 1 desk/chair/nightstand/closet/fixture.
    Desks/chairs sit on the party wall (center) — do not add extras from edge strips.
    """
    per_complete = {
        "bed": 2,
        "desk": 1,
        "chair": 1,
        "nightstand": 1,
        "closet": 1,
        "toilet": 1,
        "sink": 1,
        "shower": 1,
        "door": 2,
        "window": 2,
    }
    # Edge fragments may show beds/doors/fixtures; desks & chairs are central.
    partial_ok = {"bed", "door", "window", "toilet", "sink", "shower", "closet"}
    out: list[dict[str, Any]] = []
    for row in objects:
        t = _normalize_item_name(str(row.get("type") or ""))
        try:
            n = int(row.get("count") or 0)
        except (TypeError, ValueError):
            n = 0
        if n <= 0 or not t:
            continue
        if t in per_complete and complete_units > 0:
            if t in partial_ok and partial_units > 0:
                # Edge strips: at most one mostly-visible symbol per type per edge
                extra = 1 * partial_units
            else:
                extra = 0
            max_n = per_complete[t] * complete_units + extra
            if t == "door":
                max_n = 2 * complete_units + 1 * partial_units
            if n > max_n:
                n = max_n
                loc = str(row.get("location") or "").strip()
                loc = (
                    f"{loc} (capped to visible units)".strip()
                    if loc
                    else "capped to visible units"
                )
                out.append({"type": t, "count": n, "location": loc})
                continue
        out.append(
            {"type": t, "count": n, "location": str(row.get("location") or "").strip()}
        )
    return out


def _zone_furniture_count(
    client,
    deployment: str,
    content: bytes,
    content_type: str,
) -> dict[str, Any]:
    """
    Floor-plan specialized pass for conference rooms AND residential bedroom units.
    """
    prompt = (
        "This is an architectural FLOOR PLAN. Count furniture/fixture SYMBOLS carefully.\n"
        "Scan the ENTIRE sheet (all repeated units), not only bathrooms.\n\n"
        "ALWAYS inventory these types when visible:\n"
        "1) beds — rectangle with pillow + diagonal blanket fold. Count each bed symbol.\n"
        "2) chairs — desk chairs or seating symbols (do NOT count closet hangers as chairs).\n"
        "3) desks — built-in desks/workstations (e.g. labeled KD2).\n"
        "4) tables — freestanding conference/meeting tables only.\n"
        "5) nightstand — small square between beds.\n"
        "6) closet / wardrobe — hanger-rod areas (count closet zones, not every hanger).\n"
        "7) doors — each door opening (entry + bathroom doors).\n"
        "8) toilet, sink, shower — bathroom fixtures.\n"
        "9) window — window wall symbols if labeled/clear.\n\n"
        "If this is a RESIDENTIAL / bedroom unit plan:\n"
        "- Count fully visible units; note partial edge units in limitations.\n"
        "- Typical unit has 2 beds, 1 desk+chair, 1 bathroom (toilet+sink+shower), closet.\n"
        "- Closet kidney/hanger shapes are NOT chairs.\n\n"
        "If this is a CONFERENCE room plan:\n"
        "- Count chairs around the table AND wall-line chairs separately.\n"
        "- Do not invent chairs on cropped edges or for symmetry.\n\n"
        "Return JSON ONLY with an objects array of "
        '{"type","count","location","breakdown"} entries. '
        "Omit types with count 0. Breakdown numbers must sum to each type's count."
    )
    system = (
        "You are an expert at counting furniture symbols on architectural CAD floor plans. "
        "Never skip beds/desks/chairs on residential plans. "
        "Never count closet hangers as chairs. "
        "Never invent chairs for symmetry. Return valid JSON only."
    )
    payload = _vision_json(
        client=client,
        deployment=deployment,
        system=system,
        prompt=prompt,
        image_bytes=content,
        content_type=content_type,
        max_tokens=1800,
        detail="high",
    )

    objects: list[dict[str, Any]] = []
    for row in payload.get("objects") or []:
        if not isinstance(row, dict):
            continue
        item = str(row.get("type") or "").strip().lower()
        if not item:
            continue
        breakdown = row.get("breakdown") or []
        nums: list[int] = []
        if isinstance(breakdown, list):
            for line in breakdown:
                m = re.search(r":\s*(\d+)\s*$", str(line).strip()) or re.search(
                    r"(\d+)\s*$", str(line).strip()
                )
                if m:
                    nums.append(int(m.group(1)))
        try:
            total = int(row.get("count"))
        except (TypeError, ValueError):
            total = sum(nums) if nums else 0
        if nums and total != sum(nums):
            total = sum(nums)
        if total <= 0:
            continue
        loc = str(row.get("location") or "").strip()
        if isinstance(breakdown, list) and breakdown:
            loc = "; ".join(str(b).strip() for b in breakdown if str(b).strip()) or loc
        objects.append({"type": _normalize_item_name(item), "count": total, "location": loc})

    return {
        "scene": str(payload.get("scene") or "architectural floor-plan").strip(),
        "objects": objects,
        "confidence": str(payload.get("confidence") or "medium").lower(),
        "limitations": str(payload.get("limitations") or "").strip(),
        "method": "zone_breakdown",
    }


def _verify_conference_table_chairs(
    client,
    deployment: str,
    content: bytes,
    content_type: str,
) -> Optional[dict[str, int]]:
    """
    Count conference-table chairs with separate per-side questions.
    Avoids symmetry padding and double-counting corner seats.
    """
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(content)).convert("RGB")
        w, h = img.size
        crop = img.crop((int(w * 0.02), int(h * 0.28), int(w * 0.55), int(h * 0.72)))  # tight oval-table band; excludes wall chairs
        buf = io.BytesIO()
        crop.save(buf, format="PNG")
        focus_bytes, focus_type = buf.getvalue(), "image/png"
    except Exception:
        focus_bytes, focus_type = content, content_type

    sides = {"top": 0, "bottom": 0, "left_end": 0, "right_end": 0}
    side_prompts = {
        "top": (
            "Look at the oval/rectangular CONFERENCE TABLE only. "
            "How many distinct chair symbols sit along the TOP long side of that table "
            "(not wall chairs, not end chairs)? "
            "Count only chairs on the upper long edge. Do not include left_end or right_end chairs. "
            "List each chair briefly in evidence. "
            'Return JSON: {"count": N, "evidence": ["brief note per chair"]}'
        ),
        "bottom": (
            "Look at the oval/rectangular CONFERENCE TABLE only. "
            "How many distinct chair symbols sit along the BOTTOM long side of that table "
            "(not wall chairs, not end chairs)? "
            "Count only chairs on the lower long edge. Do not include left_end or right_end chairs. "
            "List each chair briefly in evidence. "
            'Return JSON: {"count": N, "evidence": ["brief note per chair"]}'
        ),
        "left_end": (
            "Look at the oval/rectangular CONFERENCE TABLE only. "
            "Is there a chair symbol at the LEFT short end of the table? "
            "If the left end is cropped off or no clear chair is drawn, count 0. "
            "Do not invent a chair for symmetry. "
            'Return JSON: {"count": 0 or 1, "evidence": "what you see"}'
        ),
        "right_end": (
            "Look at the oval/rectangular CONFERENCE TABLE only. "
            "Is there a chair symbol at the RIGHT short end of the table? "
            "If no clear chair is drawn, count 0. Do not invent a chair for symmetry. "
            'Return JSON: {"count": 0 or 1, "evidence": "what you see"}'
        ),
    }
    system = (
        "You count CAD chair symbols on one side of a conference table. "
        "Be literal. Never invent chairs. Return valid JSON only."
    )

    for side, prompt in side_prompts.items():
        try:
            payload = _vision_json(
                client=client,
                deployment=deployment,
                system=system,
                prompt=prompt,
                image_bytes=focus_bytes,
                content_type=focus_type,
                max_tokens=300,
                detail="high",
            )
            n = int(payload.get("count") or 0)
            evidence = payload.get("evidence")
            if isinstance(evidence, list) and evidence:
                n = min(n, len([e for e in evidence if str(e).strip()]))
            if side in ("left_end", "right_end"):
                n = 1 if n >= 1 else 0
            sides[side] = max(0, n)
        except Exception as exc:
            logger.warning("Per-side table chair count failed (%s): %s", side, exc)

    # Left-cropped conference tables often get a hallucinated left_end chair for symmetry.
    try:
        from PIL import Image

        img0 = Image.open(io.BytesIO(content)).convert("L")
        w0, h0 = img0.size
        strip = img0.crop((0, int(h0 * 0.35), max(2, int(w0 * 0.01)), int(h0 * 0.65)))
        pixels = list(strip.getdata())
        dark = sum(1 for px in pixels if px < 200)
        if pixels and (dark / len(pixels)) > 0.02 and sides.get("left_end", 0):
            sides["left_end"] = 0
    except Exception:
        pass

    # If long sides are equal/high and both ends claimed, drop left_end (common double-count).
    if sides["top"] >= 3 and sides["bottom"] >= 3 and sides["left_end"] and sides["right_end"]:
        if sides["top"] == sides["bottom"]:
            sides["left_end"] = 0

    sides["total"] = sides["top"] + sides["bottom"] + sides["left_end"] + sides["right_end"]
    if sides["total"] <= 0:
        return None
    return sides


def _looks_like_floor_plan(scene: str, objects: list[dict[str, Any]]) -> bool:
    s = (scene or "").lower()
    if any(k in s for k in ("floor-plan", "floor plan", "architectural", "drawing", "cad")):
        return True
    types = {_normalize_item_name(str(o.get("type"))) for o in objects}
    return "door" in types and ("chair" in types or "table" in types)


def _pick_better_count(full_n: int, zone_n: int, tile_n: int) -> tuple[int, str]:
    """
    Choose the most reliable count.
    Prefer zone breakdown for floor plans; reject tile totals that look like
    classic 2× double-counts from a 2×2 grid.
    """
    if full_n > 0 and tile_n > 0:
        # 2×2 tile grids often double-count the same furniture symbols
        if tile_n >= full_n * 1.75 and tile_n <= full_n * 2.4:
            tile_n = 0
        elif tile_n > full_n * 1.5 and zone_n == 0:
            tile_n = 0
    if zone_n > 0 and tile_n > 0 and tile_n > zone_n * 1.4:
        tile_n = 0

    if zone_n > 0:
        return max(zone_n, full_n), "zone" if zone_n >= full_n else "zone+full"
    if full_n > 0 and tile_n > 0:
        return max(full_n, tile_n), "full" if full_n >= tile_n else "tiles"
    if full_n > 0:
        return full_n, "full"
    if tile_n > 0:
        return tile_n, "tiles"
    return 0, "none"


def _is_office_plan(scene: str, objects: list[dict[str, Any]]) -> bool:
    """Open office / workstation floor plans (not residential, not conference-only)."""
    if _is_residential_plan(scene, objects):
        return False
    types = {_normalize_item_name(str(o.get("type"))) for o in objects}
    if "bed" in types:
        return False
    s = (scene or "").lower()
    if any(k in s for k in ("office", "workstation", "workspace", "lounge")):
        return True
    if "desk" in types and ({"sofa", "staircase", "stair"} & types):
        return True
    if "desk" in types and "chair" in types and "table" not in types:
        return True
    return False


def _is_conference_plan(scene: str, objects: list[dict[str, Any]]) -> bool:
    """Conference / meeting room floor plans (table + chairs, not office desks)."""
    if _is_residential_plan(scene, objects) or _is_office_plan(scene, objects):
        return False
    s = (scene or "").lower()
    if any(k in s for k in ("conference", "meeting room", "boardroom", "meeting")):
        return True
    types = {_normalize_item_name(str(o.get("type"))) for o in objects}
    return "table" in types and "chair" in types and "bed" not in types and "desk" not in types


def _office_inventory(
    client,
    deployment: str,
    content: bytes,
    content_type: str,
) -> dict[str, Any]:
    """
    Dedicated pass for open-office / workstation floor plans.
    Count workstations on an office crop (exclude stairwell), then merge
    building elements from the full sheet.
    """
    from PIL import Image

    img = Image.open(io.BytesIO(content)).convert("RGB")
    w, h = img.size
    # Stairwell is typically the left bay; furniture lives in the right open area
    office_crop = img.crop((int(w * 0.30), 0, w, h))
    buf = io.BytesIO()
    office_crop.save(buf, format="PNG")
    office_bytes = buf.getvalue()

    furniture = _office_furniture_count(
        client, deployment, office_bytes, "image/png", region="office furniture zone"
    )
    building = _office_building_count(client, deployment, content, content_type)
    merged = _merge_object_lists(
        furniture.get("objects") or [],
        building.get("objects") or [],
    )
    merged = _reconcile_workstation_chairs(merged)
    lim = " ".join(
        p
        for p in (
            str(furniture.get("limitations") or "").strip(),
            str(building.get("limitations") or "").strip(),
            "Office furniture counted on right-side crop; doors/stairs/windows on full sheet.",
        )
        if p
    )
    return {
        "scene": str(
            furniture.get("scene") or building.get("scene") or "office floor-plan"
        ).strip(),
        "objects": merged,
        "confidence": str(
            furniture.get("confidence") or building.get("confidence") or "medium"
        ).lower(),
        "limitations": lim,
        "method": "office_full",
    }


def _office_furniture_count(
    client,
    deployment: str,
    image_bytes: bytes,
    content_type: str,
    *,
    region: str,
) -> dict[str, Any]:
    prompt = (
        f"Architectural floor-plan crop — {region}.\n"
        "Count WORKSTATION furniture carefully.\n"
        "Each workstation = one desk rectangle + one office chair + usually one pedestal (X).\n"
        "Sofas at the bottom are NOT workstations.\n\n"
        "STEP 1: List every workstation in evidence (one short label each), e.g. "
        '["left-top","left-mid","left-bot","right-top","right-mid","right-bot"].\n'
        "STEP 2: Set desk/chair/cabinet counts = length of that evidence list "
        "(cabinet may be lower if some pedestals missing).\n"
        "Also count sofa symbols separately (usually 2 lounge sofas).\n"
        "Do NOT invent a 4th row if only 3 stations are drawn per column.\n\n"
        "Return JSON:\n"
        '{"scene":"office floor-plan",'
        '"workstation_layout":"e.g. 2 columns × 3",'
        '"evidence":["left-top","left-mid",...],'
        '"objects":[{"type":"desk","count":N,"location":"workstations"},'
        '{"type":"chair","count":N,"location":"at workstations"},'
        '{"type":"cabinet","count":N,"location":"pedestals"},'
        '{"type":"sofa","count":N,"location":"lounge"}],'
        '"confidence":"high|medium|low","limitations":""}'
    )
    system = (
        "You count office workstation symbols in this crop only. "
        "Evidence list length is the workstation total. "
        "One chair per desk. Pedestal X = cabinet, not chair. Return valid JSON only."
    )
    payload = _vision_json(
        client=client,
        deployment=deployment,
        system=system,
        prompt=prompt,
        image_bytes=image_bytes,
        content_type=content_type,
        max_tokens=900,
        detail="high",
    )
    objects = _normalize_objects(payload.get("objects"))
    evidence = payload.get("evidence") or []
    evidence_n = len(evidence) if isinstance(evidence, list) else 0
    layout = str(payload.get("workstation_layout") or "").strip()
    layout_n = _parse_workstation_layout_count(layout)
    # Prefer explicit evidence list; fall back to layout only if close to desk count
    desk_n = next(
        (
            int(o.get("count") or 0)
            for o in objects
            if _normalize_item_name(str(o.get("type"))) == "desk"
        ),
        0,
    )
    if evidence_n >= 2:
        objects = _force_workstation_totals(objects, evidence_n)
    elif layout_n and desk_n and abs(layout_n - desk_n) <= 1:
        objects = _force_workstation_totals(objects, layout_n)
    lim = str(payload.get("limitations") or "").strip()
    if layout:
        lim = f"{lim} Layout: {layout}".strip()
    if evidence_n:
        lim = f"{lim} evidence={evidence_n}.".strip()
    return {
        "scene": str(payload.get("scene") or "office floor-plan").strip(),
        "objects": objects,
        "confidence": str(payload.get("confidence") or "medium").lower(),
        "limitations": lim,
    }


def _parse_workstation_layout_count(layout: str) -> Optional[int]:
    """Parse '2 columns × 3' / '2x3' / '3 by 2' into a workstation total."""
    if not layout:
        return None
    m = re.search(r"(\d+)\s*[x×]\s*(\d+)", layout, re.I)
    if m:
        return int(m.group(1)) * int(m.group(2))
    m = re.search(
        r"(\d+)\s*columns?\s*(?:of|×|x|by)?\s*(\d+)",
        layout,
        re.I,
    )
    if m:
        return int(m.group(1)) * int(m.group(2))
    m = re.search(r"(\d+)\s*(?:by|×|x)\s*(\d+)", layout, re.I)
    if m:
        return int(m.group(1)) * int(m.group(2))
    return None


def _force_workstation_totals(
    objects: list[dict[str, Any]],
    n: int,
) -> list[dict[str, Any]]:
    """When workstation total is known, set desk/chair to that count; keep sofa as-is."""
    by = {
        _normalize_item_name(str(o.get("type"))): dict(o)
        for o in objects
        if _normalize_item_name(str(o.get("type") or ""))
    }
    for t, default_loc in (
        ("desk", "workstations"),
        ("chair", "at workstations"),
    ):
        loc = by.get(t, {}).get("location") or default_loc
        by[t] = {"type": t, "count": n, "location": f"{loc} (from evidence)"}
    # Cabinets usually match stations; only override if missing or far off
    cab = int(by.get("cabinet", {}).get("count") or 0)
    if cab == 0 or abs(cab - n) > 1:
        by["cabinet"] = {
            "type": "cabinet",
            "count": n,
            "location": "pedestals (from evidence)",
        }
    return list(by.values())


def _office_building_count(
    client,
    deployment: str,
    content: bytes,
    content_type: str,
) -> dict[str, Any]:
    prompt = (
        "This is an OFFICE floor plan. Count building elements only (not desks/chairs):\n"
        "- staircase / stairs (count the stair run as 1 if one stairwell)\n"
        "- door: each swing-door opening (a double-leaf entry like FM1521 counts as 1)\n"
        "- window: labeled openings (C1520, C1820, etc.)\n"
        "Omit desks, chairs, cabinets, and sofas (furniture counted separately).\n"
        'Return JSON: {"scene":"office floor-plan","objects":['
        '{"type":"staircase","count":N,"location":"stairwell"},...],'
        '"confidence":"high|medium|low","limitations":""}'
    )
    system = (
        "You count doors, windows, stairs, and sofas on office floor plans. "
        "Return valid JSON only."
    )
    payload = _vision_json(
        client=client,
        deployment=deployment,
        system=system,
        prompt=prompt,
        image_bytes=content,
        content_type=content_type,
        max_tokens=700,
        detail="high",
    )
    return {
        "scene": str(payload.get("scene") or "office floor-plan").strip(),
        "objects": _normalize_objects(payload.get("objects")),
        "confidence": str(payload.get("confidence") or "medium").lower(),
        "limitations": str(payload.get("limitations") or "").strip(),
    }


def _reconcile_workstation_chairs(
    objects: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """If chairs ≫ desks on a workstation plan, align chairs to desks."""
    by: dict[str, dict[str, Any]] = {}
    for row in objects:
        t = _normalize_item_name(str(row.get("type") or ""))
        if not t:
            continue
        by[t] = {
            "type": t,
            "count": int(row.get("count") or 0),
            "location": str(row.get("location") or "").strip(),
        }
    # Normalize stair alias
    if "stair" in by and "staircase" not in by:
        by["staircase"] = {**by.pop("stair"), "type": "staircase"}
    desks = int(by.get("desk", {}).get("count") or 0)
    chairs = int(by.get("chair", {}).get("count") or 0)
    has_table = "table" in by and int(by["table"].get("count") or 0) > 0
    if desks > 0 and chairs > desks and not has_table:
        # Workstation: 1 chair per desk (ignore inflated tile/sofa miscounts)
        if chairs >= desks * 1.4 or chairs == desks * 2:
            loc = by.get("chair", {}).get("location") or "at workstations"
            by["chair"] = {
                "type": "chair",
                "count": desks,
                "location": f"{loc} (aligned to desks)".strip(),
            }
    return list(by.values())


def _parse_conference_table_chairs(location: str) -> Optional[int]:
    m = re.search(r"around\s+(?:conference\s+)?table:\s*(\d+)", location or "", re.I)
    if not m:
        return None
    try:
        return int(m.group(1))
    except (TypeError, ValueError):
        return None


def _reconcile_conference_chairs(objects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Cap inflated conference chair totals; trust table-verify breakdown in location."""
    by: dict[str, dict[str, Any]] = {}
    for row in objects:
        t = _normalize_item_name(str(row.get("type") or ""))
        if not t:
            continue
        by[t] = {
            "type": t,
            "count": int(row.get("count") or 0),
            "location": str(row.get("location") or "").strip(),
        }
    tables = int(by.get("table", {}).get("count") or 0)
    desks = int(by.get("desk", {}).get("count") or 0)
    if tables <= 0 or desks > 0:
        return list(by.values())

    chair_row = by.get("chair")
    if not chair_row:
        return list(by.values())

    chairs = int(chair_row.get("count") or 0)
    loc = chair_row.get("location") or ""
    table_ch = _parse_conference_table_chairs(loc)
    wall_sum = 0
    for part in re.split(r";\s*", loc):
        part = part.strip()
        if not part or re.search(r"around\s+(conference\s+)?table", part, re.I):
            continue
        m = re.search(r":\s*(\d+)\s*$", part)
        if m:
            wall_sum += int(m.group(1))

    if table_ch is not None:
        expected = table_ch + wall_sum
        if expected > 0 and chairs > expected + 1:
            chair_row = {
                **chair_row,
                "count": expected,
                "location": f"{loc} (table+wall reconciled)".strip(),
            }
            by["chair"] = chair_row
    elif chairs > max(16, tables * 12):
        by["chair"] = {
            **chair_row,
            "count": min(chairs, 16),
            "location": f"{loc} (conference cap)".strip(),
        }
    return list(by.values())


def _tile_counts_for_types(
    client,
    deployment: str,
    content: bytes,
    content_type: str,
    types: list[str],
) -> dict[str, int]:
    """Count dense object types per tile and sum (non-overlapping grid preferred)."""
    tiles = _tile_image(content, grid=2, overlap=0.0)
    if not tiles:
        return {}

    type_list = ", ".join(sorted({_normalize_item_name(t) for t in types if t}))
    if not type_list:
        return {}

    totals: dict[str, int] = {t: 0 for t in {_normalize_item_name(t) for t in types}}
    system = (
        "You count floor-plan symbols in one image crop only. "
        "Count only fully or mostly visible instances in THIS crop. "
        "Chair = each small seat/U-shape symbol. Door = each swing-door opening. "
        "Do not estimate beyond what is visible. Return JSON only."
    )

    for tile_bytes, tile_type, label in tiles:
        prompt = (
            f"This is crop {label} of a larger floor-plan image.\n"
            f"Count these object types only: {type_list}.\n"
            "Count each visible chair/seat symbol carefully (rows along walls AND around tables).\n"
            'Return JSON: {"counts": {"chair": N, "table": N, "door": N, ...}}'
        )
        try:
            payload = _vision_json(
                client=client,
                deployment=deployment,
                system=system,
                prompt=prompt,
                image_bytes=tile_bytes,
                content_type=tile_type,
                max_tokens=400,
                detail="high",
            )
            counts = payload.get("counts") or {}
            if not isinstance(counts, dict):
                continue
            for k, v in counts.items():
                key = _normalize_item_name(str(k))
                if key not in totals:
                    for t in list(totals.keys()):
                        if t in key or key in t:
                            key = t
                            break
                    else:
                        continue
                try:
                    totals[key] += max(0, int(v))
                except (TypeError, ValueError):
                    continue
        except Exception as exc:
            logger.warning("Tile count failed for %s: %s", label, exc)

    return totals


def _finalize_extraction(
    inventory: dict[str, Any],
    content: bytes,
    content_type: str,
) -> dict[str, Any]:
    """Validate and optionally vision-verify inventory before persisting."""
    from app.search.inventory_validate import finalize_inventory

    return finalize_inventory(inventory, content, content_type)


def extract_object_inventory(
    content: bytes,
    content_type: str = "image/png",
    *,
    use_tiling: bool = True,
) -> dict[str, Any]:
    """
    Build structured object inventory for an image.
    Floor plans: zone breakdown (preferred) + full image + optional tiles.
    """
    if not _vision_ready() or not content:
        return empty_inventory()

    deployment = settings.AZURE_OPENAI_VISION_DEPLOYMENT
    try:
        client = _client()
        inventory = _full_image_inventory(client, deployment, content, content_type)
        objects = list(inventory.get("objects") or [])
        scene = inventory.get("scene") or "unknown"

        # Mechanical / assembly drawings: BOM table is authoritative
        if _is_mechanical_drawing(str(scene), objects):
            try:
                bom_inv = _bom_inventory(client, deployment, content, content_type)
                if bom_inv and bom_inv.get("objects"):
                    return _finalize_extraction(bom_inv, content, content_type)
            except Exception as exc:
                logger.warning("BOM inventory failed: %s", exc)

        # Civil / site / campus grading plans — before interior floor-plan routing
        if _is_site_plan(str(scene), objects):
            try:
                site_inv = _site_plan_inventory(
                    client,
                    deployment,
                    content,
                    content_type,
                    use_tiling=use_tiling,
                )
                if site_inv and site_inv.get("objects"):
                    return _finalize_extraction(site_inv, content, content_type)
            except Exception as exc:
                logger.warning("Site plan inventory failed: %s", exc)

        is_residential = _is_residential_plan(str(scene), objects)
        is_office = (not is_residential) and _is_office_plan(str(scene), objects)
        is_conference = (not is_residential and not is_office) and _is_conference_plan(
            str(scene), objects
        )

        zone_inv: dict[str, Any] | None = None
        residential_inv: dict[str, Any] | None = None
        office_inv: dict[str, Any] | None = None

        if _looks_like_floor_plan(str(scene), objects) or any(
            _normalize_item_name(str(o.get("type"))) == "chair" for o in objects
        ):
            if is_residential:
                try:
                    residential_inv = _residential_inventory(
                        client, deployment, content, content_type
                    )
                except Exception as exc:
                    logger.warning("Residential inventory failed: %s", exc)
            elif is_office:
                try:
                    office_inv = _office_inventory(
                        client, deployment, content, content_type
                    )
                except Exception as exc:
                    logger.warning("Office inventory failed: %s", exc)
            else:
                try:
                    zone_inv = _zone_furniture_count(
                        client, deployment, content, content_type
                    )
                except Exception as exc:
                    logger.warning("Zone furniture count failed: %s", exc)
                # Zone pass may reveal beds → switch to residential path
                if zone_inv and _is_residential_plan(
                    str(zone_inv.get("scene") or scene),
                    zone_inv.get("objects") or [],
                ):
                    is_residential = True
                    try:
                        residential_inv = _residential_inventory(
                            client, deployment, content, content_type
                        )
                    except Exception as exc:
                        logger.warning("Residential inventory failed: %s", exc)
                    zone_inv = None
                elif zone_inv and _is_office_plan(
                    str(zone_inv.get("scene") or scene),
                    zone_inv.get("objects") or [],
                ):
                    is_office = True
                    try:
                        office_inv = _office_inventory(
                            client, deployment, content, content_type
                        )
                    except Exception as exc:
                        logger.warning("Office inventory failed: %s", exc)
                    zone_inv = None

        # Verify conference-table chairs for conference-style plans
        if zone_inv and is_conference and any(
            _normalize_item_name(str(o.get("type"))) == "chair"
            for o in (zone_inv.get("objects") or [])
        ):
            verified = _verify_conference_table_chairs(
                client, deployment, content, content_type
            )
            if verified and verified.get("total", 0) > 0:
                fixed_objects: list[dict[str, Any]] = []
                for o in zone_inv.get("objects") or []:
                    if _normalize_item_name(str(o.get("type"))) != "chair":
                        fixed_objects.append(o)
                        continue
                    loc = str(o.get("location") or "")
                    # Replace "around conference table: N" with verified total
                    wall_parts = [
                        p.strip()
                        for p in re.split(r";\s*", loc)
                        if p.strip()
                        and not re.search(r"around\s+(conference\s+)?table", p, re.I)
                        and not re.search(r"^(top|bottom|left|right)\b", p, re.I)
                    ]
                    side_bits = []
                    for label, key in (
                        ("top", "top"),
                        ("bottom", "bottom"),
                        ("left end", "left_end"),
                        ("right end", "right_end"),
                    ):
                        n = int(verified.get(key) or 0)
                        if n > 0:
                            side_bits.append(f"{label}: {n}")
                    table_part = (
                        f"around conference table: {verified['total']} ("
                        + ", ".join(side_bits)
                        + ")"
                        if side_bits
                        else f"around conference table: {verified['total']}"
                    )
                    wall_sum = 0
                    for p in wall_parts:
                        m = re.search(r":\s*(\d+)\s*$", p)
                        if m:
                            wall_sum += int(m.group(1))
                    new_total = verified["total"] + wall_sum
                    new_loc = table_part
                    if wall_parts:
                        new_loc += "; " + "; ".join(wall_parts)
                    fixed_objects.append(
                        {"type": "chair", "count": new_total, "location": new_loc}
                    )
                zone_inv["objects"] = fixed_objects
                note = (
                    "Conference-table chairs verified side-by-side "
                    f"(top={verified['top']}, bottom={verified['bottom']}, "
                    f"left={verified['left_end']}, right={verified['right_end']})."
                )
                lim = str(zone_inv.get("limitations") or "").strip()
                zone_inv["limitations"] = f"{lim} {note}".strip() if lim else note
                zone_inv["method"] = "zone_breakdown+table_verify"

        tile_totals: dict[str, int] = {}
        zone_verified = str((zone_inv or {}).get("method") or "").startswith(
            "zone_breakdown+table_verify"
        )
        # Skip tiling for residential/office/conference — tiles double-count dense furniture
        if (
            use_tiling
            and not is_residential
            and not is_office
            and not is_conference
            and not office_inv
            and not zone_verified
        ):
            dense_types = ["chair", "table", "desk", "door", "bed"]
            try:
                tile_totals = _tile_counts_for_types(
                    client, deployment, content, content_type, dense_types
                )
            except Exception as exc:
                logger.warning("Tile recount failed: %s", exc)

        by_type: dict[str, dict[str, Any]] = {
            _normalize_item_name(str(o.get("type"))): dict(o) for o in objects
        }

        if office_inv and office_inv.get("objects"):
            for z in office_inv["objects"]:
                t = _normalize_item_name(str(z.get("type")))
                if not t:
                    continue
                office_n = int(z.get("count") or 0)
                full_n = int(by_type.get(t, {}).get("count") or 0)
                best = office_n if office_n > 0 else full_n
                if best <= 0:
                    continue
                loc = str(z.get("location") or "").strip() or (
                    by_type.get(t, {}).get("location") or ""
                )
                by_type[t] = {"type": t, "count": best, "location": loc}
            scene = office_inv.get("scene") or scene
            inventory["method"] = "office_full"
            inventory["confidence"] = (
                office_inv.get("confidence") or inventory.get("confidence")
            )
            lim = str(office_inv.get("limitations") or "").strip()
            note = "Counts use office/workstation inventory (chairs aligned to desks)."
            inventory["limitations"] = f"{lim} {note}".strip() if lim else note
        elif residential_inv and residential_inv.get("objects"):
            # Prefer dedicated residential full-sheet counts (avoids L+R double-count)
            for z in residential_inv["objects"]:
                t = _normalize_item_name(str(z.get("type")))
                if not t:
                    continue
                full_n = int(by_type.get(t, {}).get("count") or 0)
                res_n = int(z.get("count") or 0)
                tile_n = int(tile_totals.get(t) or 0)
                # Prefer residential pass; tiles only if full+res both missed
                best = res_n if res_n > 0 else full_n
                if best <= 0 and tile_n > 0:
                    best = tile_n
                elif tile_n > 0 and best > 0 and tile_n < best * 0.5:
                    # tiles much lower — keep residential
                    pass
                loc = str(z.get("location") or "").strip() or (
                    by_type.get(t, {}).get("location") or ""
                )
                by_type[t] = {"type": t, "count": best, "location": loc}
            scene = residential_inv.get("scene") or scene
            inventory["method"] = "residential_full"
            inventory["confidence"] = (
                residential_inv.get("confidence") or inventory.get("confidence")
            )
            lim = str(residential_inv.get("limitations") or "").strip()
            note = "Counts use full-sheet residential inventory (no left/right zone sum)."
            inventory["limitations"] = f"{lim} {note}".strip() if lim else note
        elif zone_inv and zone_inv.get("objects"):
            zone_method = str(zone_inv.get("method") or "zone_breakdown")
            for z in zone_inv["objects"]:
                t = _normalize_item_name(str(z.get("type")))
                if not t:
                    continue
                full_n = int(by_type.get(t, {}).get("count") or 0)
                zone_n = int(z.get("count") or 0)
                tile_n = int(tile_totals.get(t) or 0)
                if zone_method.startswith("zone_breakdown+table_verify") and t == "chair":
                    best = zone_n
                elif is_conference and t == "chair":
                    best = zone_n if zone_n > 0 else full_n
                else:
                    best, _src = _pick_better_count(full_n, zone_n, tile_n)
                if best <= 0:
                    continue
                loc = str(z.get("location") or "").strip() or (
                    by_type.get(t, {}).get("location") or ""
                )
                by_type[t] = {"type": t, "count": best, "location": loc}
            scene = zone_inv.get("scene") or scene
            inventory["method"] = zone_method
            inventory["confidence"] = zone_inv.get("confidence") or inventory.get("confidence")
            lim = str(zone_inv.get("limitations") or "").strip()
            note = (
                "Counts use verified conference table breakdown."
                if zone_method.startswith("zone_breakdown+table_verify")
                else "Counts use zone breakdown (table chairs + wall chairs counted separately)."
            )
            inventory["limitations"] = f"{lim} {note}".strip() if lim else note
        elif tile_totals:
            for t, n in tile_totals.items():
                if n <= 0:
                    continue
                full_n = int(by_type.get(t, {}).get("count") or 0)
                best, _src = _pick_better_count(full_n, 0, n)
                if t in by_type:
                    by_type[t]["count"] = best
                else:
                    by_type[t] = {"type": t, "count": best, "location": "tiled recount"}
            inventory["method"] = "full_image+tiles"

        # Ensure door is counted even if first pass missed it
        if "door" not in by_type and tile_totals.get("door"):
            by_type["door"] = {
                "type": "door",
                "count": int(tile_totals["door"]),
                "location": "tiled recount",
            }

        # Final safety reconcilers
        reconciled = _reconcile_workstation_chairs(list(by_type.values()))
        reconciled = _reconcile_conference_chairs(reconciled)
        by_type = {_normalize_item_name(str(o.get("type"))): dict(o) for o in reconciled}

        inventory["scene"] = scene
        inventory["objects"] = sorted(
            by_type.values(),
            key=lambda x: (-int(x.get("count") or 0), str(x.get("type"))),
        )
        return _finalize_extraction(inventory, content, content_type)
    except Exception as exc:
        logger.warning("Object inventory extraction failed: %s", exc)
        return empty_inventory()


def lookup_count(inventory: dict[str, Any], element: str) -> Optional[int]:
    target = _normalize_item_name(element)
    target_raw = (element or "").strip().lower()
    if not target and not target_raw:
        return None

    objects = inventory.get("objects") or []
    is_bom = str(inventory.get("method") or "") == "bom_table"
    is_site = str(inventory.get("method") or "") == "site_plan"

    if is_site and target in {"building", "buildings", "structure", "structures", "block", "blocks"}:
        total = 0
        found = False
        for row in objects:
            if not _is_site_building_row(row):
                continue
            try:
                total += max(1, int(row.get("count") or 1))
                found = True
            except (TypeError, ValueError):
                continue
        return total if found else None

    if is_site and target in {"road", "roads", "carriageway", "carriageways"}:
        total = 0
        found = False
        for row in objects:
            raw = str(row.get("type") or "").strip().lower()
            if "road" in raw or "carriageway" in raw or "street" in raw:
                try:
                    total += max(1, int(row.get("count") or 1))
                    found = True
                except (TypeError, ValueError):
                    continue
        return total if found else None

    if is_bom:
        # Prefer rolled-up aggregate rows for family queries (screws, washers, …)
        for row in objects:
            if not isinstance(row, dict):
                continue
            loc = str(row.get("location") or "")
            if not loc.startswith("BOM aggregate"):
                continue
            raw = _normalize_bom_type(str(row.get("type") or ""))
            if (
                target == raw
                or target_raw == raw
                or target in raw.split()
                or target_raw in raw
            ):
                try:
                    return int(row.get("count") or 0)
                except (TypeError, ValueError):
                    continue

    total = 0
    found = False
    for row in objects:
        if not isinstance(row, dict):
            continue
        loc = str(row.get("location") or "")
        if is_bom and loc.startswith("BOM aggregate"):
            continue
        raw = str(row.get("type") or "").strip().lower()
        name = _normalize_item_name(raw) if not is_bom else _normalize_bom_type(raw)
        if (
            name == target
            or target in name
            or name in target
            or target_raw in raw
            or raw in target_raw
        ):
            try:
                total += int(row.get("count") or 0)
                found = True
            except (TypeError, ValueError):
                continue
    return total if found else None


def format_inventory_answer(
    query: str,
    inventory: dict[str, Any],
    *,
    drawing_label: str = "",
) -> Optional[str]:
    """Format a user-facing answer from stored inventory for count/object questions."""
    objects = inventory.get("objects") or []
    if not objects:
        return None

    q = query or ""
    scene = str(inventory.get("scene") or "").strip()
    limitations = str(inventory.get("limitations") or "").strip()
    prefix = f"On {drawing_label}, " if drawing_label else ""

    # Specific count question
    m = _COUNT_ELEMENT.search(q)
    if m and re.search(r"\b(how\s+many|number\s+of|count|no\.?\s*of)\b", q, re.I):
        element = m.group(1).lower()
        total = lookup_count(inventory, element)
        if total is None:
            return None
        label = _pluralize(element, total)
        parts = [f"**Answer:** {prefix}there are **{total} {label}** visible."]
        # Optional breakdown by matching rows
        rows = []
        target = _normalize_item_name(element)
        for row in objects:
            if str(inventory.get("method") or "") == "site_plan" and target in {
                "building",
                "buildings",
                "structure",
                "structures",
            }:
                if not _is_site_building_row(row):
                    continue
                label = _site_display_label(row)
                cnt = row.get("count")
                loc = str(row.get("location") or "").strip()
                rows.append(f"{label}: {cnt}" + (f" ({loc})" if loc else ""))
                continue
            name = _normalize_item_name(str(row.get("type") or ""))
            if name == target or target in name or name in target:
                loc = str(row.get("location") or "").strip()
                cnt = row.get("count")
                display = _site_display_label(row) if str(inventory.get("method") or "") == "site_plan" else name
                rows.append(f"{display}: {cnt}" + (f" ({loc})" if loc else ""))
        if len(rows) > 1:
            parts.append("**Breakdown:**\n" + "\n".join(f"- {r}" for r in rows))
        if scene:
            parts.append(f"**Scene:** {scene}")
        if limitations:
            parts.append(f"**Note:** {limitations}")
        from app.search.inventory_validate import validation_note_for_answer

        vnote = validation_note_for_answer(inventory)
        if vnote:
            parts.append(f"**Validation:** {vnote}")
        parts.append("*Source: structured object inventory (upload-time analysis).*")
        return "\n\n".join(parts)

    # General object / furniture / site inventory
    lines = []
    site_method = str(inventory.get("method") or "") == "site_plan"
    building_q = bool(re.search(r"\b(buildings?|structures?|blocks?|hostels?)\b", q, re.I))
    road_q = bool(re.search(r"\b(roads?|carriageways?|streets?)\b", q, re.I))
    for row in objects:
        if site_method and building_q and not _is_site_building_row(row):
            continue
        if site_method and road_q and not _is_site_road_row(row):
            continue
        item = _site_display_label(row) if site_method else str(row.get("type") or "").strip()
        if not item or (site_method and _is_generic_site_type(item)):
            continue
        if site_method and _is_site_legend_row(row) and "grading control" not in item.lower():
            continue
        count = row.get("count")
        loc = str(row.get("location") or "").strip()
        line = f"{item}: {count}" if count is not None else item
        if loc and loc.lower() not in item.lower():
            line += f" ({loc})"
        lines.append(line)

    if not lines and site_method and building_q:
        for row in objects:
            if _is_site_building_row(row):
                lines.append(f"{_site_display_label(row)}: {row.get('count', 1)}")

    if not lines:
        return None

    summary = (
        f"{prefix}the site plan shows a **{scene or 'campus/site layout'}** with these features:"
        if site_method and scene
        else (
            f"{prefix}the image shows a **{scene or 'space'}** with these objects:"
            if scene
            else f"{prefix}these objects are visible:"
        )
    )
    parts = [
        f"**Answer:** {summary}",
        "**Objects:**\n" + "\n".join(f"- {ln}" for ln in lines),
    ]
    if limitations:
        parts.append(f"**Note:** {limitations}")
    from app.search.inventory_validate import validation_note_for_answer

    vnote = validation_note_for_answer(inventory)
    if vnote:
        parts.append(f"**Validation:** {vnote}")
    parts.append("*Source: structured object inventory (upload-time analysis).*")
    return "\n\n".join(parts)

def answer_from_stored_inventory(
    *,
    query: str,
    drawing: dict[str, Any],
) -> Optional[str]:
    """Prefer stored inventory for object/count questions when available."""
    from app.search.query_intel import (
        is_drawing_count_query,
        is_drawing_furniture_inventory_query,
        is_drawing_object_query,
        is_drawing_site_inventory_query,
    )

    if not (
        is_drawing_count_query(query)
        or is_drawing_furniture_inventory_query(query)
        or is_drawing_object_query(query)
        or is_drawing_site_inventory_query(query)
    ):
        return None

    inventory = resolve_drawing_inventory(drawing)
    if not inventory:
        return None

    from app.search.inventory_validate import inventory_trustworthy_for_answer

    if not inventory_trustworthy_for_answer(inventory):
        logger.info(
            "Stored inventory failed validation — deferring to live vision for: %s",
            (query or "")[:80],
        )
        return None

    label = ""
    meta = drawing.get("metadata") or {}
    drawing_no = (meta.get("drawing_no") or "").strip()
    title = (drawing.get("title") or "").strip()
    if drawing_no:
        label = drawing_no
    elif title:
        label = title

    return format_inventory_answer(query, inventory, drawing_label=label)
