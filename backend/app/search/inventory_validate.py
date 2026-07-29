"""
Post-extraction validation and optional vision verification for object inventory.

Runs after upload-time extraction to catch inconsistent counts, generic site labels,
and office chair/desk skew — and optionally re-reads the sheet to correct issues.
"""
from __future__ import annotations

import base64
import json
import logging
import re
from typing import Any, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

_CONF_RANK = {"high": 3, "medium": 2, "low": 1}


def _rank(conf: str) -> int:
    return _CONF_RANK.get(str(conf or "low").lower(), 1)


def _data_url(content: bytes, content_type: str) -> str:
    mime = content_type if content_type.startswith("image/") else "image/png"
    return f"data:{mime};base64,{base64.b64encode(content).decode('ascii')}"


def validate_inventory(inventory: dict[str, Any]) -> dict[str, Any]:
    """
    Rule-based checks per drawing method.
    Returns {status: pass|warn|fail, issues: [...], score: 0-100}.
    """
    issues: list[str] = []
    objects = inventory.get("objects") or []
    method = str(inventory.get("method") or "unknown")
    scene = str(inventory.get("scene") or "").lower()

    if not objects:
        return {"status": "fail", "issues": ["empty inventory"], "score": 0}

    by_type: dict[str, int] = {}
    for row in objects:
        if not isinstance(row, dict):
            continue
        t = str(row.get("type") or "").strip().lower()
        try:
            n = int(row.get("count") or 0)
        except (TypeError, ValueError):
            n = 0
        if n < 0:
            issues.append(f"negative count for {t}")
        if t:
            by_type[t] = by_type.get(t, 0) + n

    # --- method-specific rules ---
    if method == "office_full":
        desks = by_type.get("desk", 0)
        chairs = by_type.get("chair", 0)
        if desks and chairs:
            ratio = chairs / desks if desks else 0
            if ratio > 1.35:
                issues.append(f"chairs ({chairs}) exceed desks ({desks}) — possible double-count")
            elif ratio < 0.75:
                issues.append(f"chairs ({chairs}) below desks ({desks}) — possible under-count")

    if method == "residential_full":
        beds = by_type.get("bed", 0)
        if beds <= 0 and any(k in scene for k in ("residential", "bedroom", "hotel", "dorm")):
            issues.append("residential plan but bed count is zero")

    if method == "zone_breakdown" or method == "zone_breakdown+table_verify":
        chairs = by_type.get("chair", 0)
        tables = by_type.get("table", 0)
        if tables and chairs and chairs > tables * 14:
            issues.append(f"conference chairs ({chairs}) unusually high vs tables ({tables})")

    if method == "site_plan":
        generic = sum(
            1
            for row in objects
            if str(row.get("type") or "").strip().lower() in {"building", "buildings", "structure", "structures"}
        )
        if generic:
            issues.append(f"{generic} generic 'building' row(s) — labels may be missing")
        named_buildings = sum(
            1
            for row in objects
            if re.search(
                r"hostel|block|complex|house|playground|sports|admin|guest|plant|tank",
                str(row.get("type") or ""),
                re.I,
            )
        )
        if named_buildings < 1:
            issues.append("site plan has no named building labels")

    if method == "bom_table":
        rows = [o for o in objects if not str(o.get("location") or "").startswith("BOM aggregate")]
        if len(rows) < 2:
            issues.append("BOM inventory has very few line items")

    if method == "full_image+tiles":
        for t, n in by_type.items():
            if t in {"chair", "desk", "table"} and n > 0:
                issues.append(f"{t} count ({n}) from tiles only — consider dedicated path")

    conf = str(inventory.get("confidence") or "medium").lower()
    if _rank(conf) <= 1:
        issues.append("extractor reported low confidence")

    # Score: start at 100, deduct per issue
    score = max(0, 100 - len(issues) * 18)
    if method in {"office_full", "zone_breakdown+table_verify", "bom_table", "site_plan"} and not issues:
        score = min(100, score + 5)

    if any("double-count" in i or "generic" in i or "empty" in i for i in issues):
        status = "fail"
    elif issues:
        status = "warn"
    else:
        status = "pass"

    return {"status": status, "issues": issues, "score": score}


def _vision_verify_inventory(
    inventory: dict[str, Any],
    content: bytes,
    content_type: str,
) -> Optional[dict[str, Any]]:
    """
    Second vision pass: show proposed inventory + image, ask model to confirm/correct counts.
    Only applied when validation found issues.
    """
    deployment = settings.AZURE_OPENAI_VISION_DEPLOYMENT
    if not deployment or not settings.AZURE_OPENAI_ENDPOINT or not settings.AZURE_OPENAI_KEY:
        return None
    if not content:
        return None

    payload_json = json.dumps(
        {
            "scene": inventory.get("scene"),
            "method": inventory.get("method"),
            "objects": inventory.get("objects"),
        },
        ensure_ascii=False,
    )[:6000]

    prompt = (
        "You are verifying a structured object inventory against this engineering drawing.\n"
        "Proposed inventory JSON:\n"
        f"{payload_json}\n\n"
        "Re-count carefully on the image. Fix wrong quantities and remove hallucinated items.\n"
        "Keep the same JSON schema. Use printed labels for site plans (not generic 'building').\n"
        "If a count cannot be verified, lower confidence and note in limitations.\n"
        'Return JSON: {"scene":"...", "objects":[{"type":"...","count":N,"location":"..."}], '
        '"confidence":"high|medium|low", "limitations":"...", "corrections":"brief note"}'
    )
    system = (
        "You verify and correct drawing inventories. Be conservative — only change counts "
        "you can see evidence for. Return valid JSON only."
    )
    try:
        from openai import AzureOpenAI

        client = AzureOpenAI(
            azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
            api_key=settings.AZURE_OPENAI_KEY,
            api_version="2024-02-01",
        )
        resp = client.chat.completions.create(
            model=deployment,
            messages=[
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": _data_url(content, content_type), "detail": "high"}},
                    ],
                },
            ],
            max_tokens=1600,
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        raw = (resp.choices[0].message.content or "{}").strip()
        verified = json.loads(raw)
    except Exception as exc:
        logger.warning("Inventory verification vision pass failed: %s", exc)
        return None

    objects = verified.get("objects")
    if not isinstance(objects, list) or not objects:
        return None

    out = dict(inventory)
    out["objects"] = objects
    out["scene"] = str(verified.get("scene") or inventory.get("scene") or "").strip()
    vconf = str(verified.get("confidence") or "medium").lower()
    # Only upgrade confidence, never blindly trust downgrade to high without issues cleared
    if _rank(vconf) >= _rank(str(inventory.get("confidence") or "medium")):
        out["confidence"] = vconf
    lim = str(inventory.get("limitations") or "").strip()
    vlim = str(verified.get("limitations") or "").strip()
    corr = str(verified.get("corrections") or "").strip()
    parts = [p for p in (lim, vlim, corr) if p]
    if parts:
        out["limitations"] = " | ".join(dict.fromkeys(parts))[:500]
    out["method"] = str(inventory.get("method") or "unknown") + "+verified"
    return out


def finalize_inventory(
    inventory: dict[str, Any],
    content: bytes,
    content_type: str = "image/png",
    *,
    verify_on_issues: bool = True,
) -> dict[str, Any]:
    """
    Validate inventory; optionally run vision verification when issues or low confidence.
    Attaches validation block to returned inventory.
    """
    if not inventory or not inventory.get("objects"):
        inv = dict(inventory or {})
        inv["validation"] = validate_inventory(inv)
        return inv

    validation = validate_inventory(inventory)
    out = dict(inventory)
    out["validation"] = validation

    should_verify = verify_on_issues and (
        validation["status"] in {"fail", "warn"}
        or validation["score"] < 90
        or _rank(str(inventory.get("confidence") or "medium")) <= 1
    )
    # Per-side table/wall verification is more reliable than a second full-sheet guess
    method = str(inventory.get("method") or "")
    if method.startswith("zone_breakdown+table_verify"):
        should_verify = False
    if should_verify and content:
        corrected = _vision_verify_inventory(out, content, content_type)
        if corrected and corrected.get("objects"):
            revalidation = validate_inventory(corrected)
            corrected["validation"] = revalidation
            # Accept correction only if score improved or status upgraded
            if revalidation["score"] >= validation["score"] or revalidation["status"] != "fail":
                logger.info(
                    "Inventory verified: score %s→%s status %s→%s",
                    validation["score"],
                    revalidation["score"],
                    validation["status"],
                    revalidation["status"],
                )
                return corrected
            corrected["validation"]["issues"].append(
                "verification pass did not improve score — kept original"
            )

    # Adjust confidence from validation score
    if validation["score"] >= 90 and _rank(str(out.get("confidence") or "medium")) < 3:
        out["confidence"] = "high"
    elif validation["score"] < 60:
        out["confidence"] = "low"

    return out


def inventory_trustworthy_for_answer(inventory: dict[str, Any]) -> bool:
    """Whether stored inventory is safe to answer from without live vision fallback."""
    validation = inventory.get("validation") or {}
    status = str(validation.get("status") or "pass")
    score = int(validation.get("score") or 100)
    if status == "fail" or score < 50:
        return False
    if str(inventory.get("confidence") or "").lower() == "low" and score < 70:
        return False
    return True


def validation_note_for_answer(inventory: dict[str, Any]) -> str:
    """User-facing caveat from validation block."""
    validation = inventory.get("validation") or {}
    issues = validation.get("issues") or []
    score = validation.get("score")
    conf = str(inventory.get("confidence") or "medium")
    parts: list[str] = []
    if conf != "high":
        parts.append(f"Confidence: {conf}")
    if score is not None and int(score) < 85:
        parts.append(f"Validation score: {score}/100")
    if issues:
        parts.append("Checks: " + "; ".join(str(i) for i in issues[:3]))
    return " | ".join(parts)
