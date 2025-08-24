#!/usr/bin/env python3

import sqlite3
import json
import logging
import re
from typing import Dict, Tuple, Optional
from src.apiUtils.ollama_utils import OllamaConfig, OllamaAPI
from src.raa_class_mapping import RAA_CLASS_MAPPING




# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---- Field parsing --------------------------------------------------------------

FIELD_MAP = {
    "Class": "class",
    "Klass": "class",
    "Skadestatus": "damage_status",
    "Undersökningsstatus": "exam_status",
    "Beskrivning": "description_sv",
    "Placering": "placement",
    "Terräng": "terrain",
    "Orientering": "orientation",
    "Province": "province_line",
    "County": "province_line",
    "Municipality": "province_line",
    "Parish": "province_line",
    "Aktualitetsstatus": "actuality_status",
    "Antikvarisk bedömning": "antiquarian_assessment",
    "Lämningsnummer": "lamningsnummer",
    "RAÄ-nummer": "raa_number",
    "Organization": "organization",
    "Build Date": "build_date",
    "Last Changed": "last_changed",
    "URL": "url",
    "Title": "title",
    "Tradition": "tradition",
    "Referens": "reference",
    "References": "reference",
}
SECTION_STARTERS = tuple(FIELD_MAP.keys())

DISCLAIMER_PATTERNS = [
    r"Beskrivningen är inte kvalitetssäkrad\.?",
    r"Information kan saknas, vara felaktig eller inaktuell\.?",
    r"Se även\s+Inventeringsbok\.?",
]
DISCLAIMER_REGEX = re.compile("|".join(DISCLAIMER_PATTERNS), flags=re.IGNORECASE)
URL_REGEX = re.compile(r"https?://\S+", re.IGNORECASE)

def parse_record(text: str) -> Dict[str, str]:
    """Parse semi-structured RAÄ-like text into a dict of canonical fields."""
    result: Dict[str, str] = {}
    current_key: Optional[str] = None
    buf: list[str] = []

    def flush():
        nonlocal current_key, buf
        if current_key is not None:
            value = "\n".join(buf).strip()
            if value:
                if current_key in result and result[current_key]:
                    result[current_key] += "\n" + value
                else:
                    result[current_key] = value
        buf = []
        current_key = None

    lines = [ln.rstrip() for ln in text.splitlines()]

    for raw in lines:
        line = raw.strip()
        if not line:
            if current_key is not None:
                buf.append("")
            continue

        if ":" in line:
            field, rest = line.split(":", 1)
            field = field.strip()
            rest = rest.lstrip()
            if field in FIELD_MAP:
                flush()
                current_key = FIELD_MAP[field]
                buf.append(rest)
                continue

        if current_key is None:
            continue
        buf.append(line)

    flush()

    # Split the combined province line into subfields
    if "province_line" in result:
        parts = [p.strip() for p in result["province_line"].split("|")]
        for p in parts:
            if ":" in p:
                k, v = p.split(":", 1)
                k = k.strip().lower()
                v = v.strip()
                if k == "province":
                    result["province"] = v
                elif k == "county":
                    result["county"] = v
                elif k == "municipality":
                    result["municipality"] = v
                elif k == "parish":
                    result["parish"] = v

    # Remove URLs from fields where they may sneak in
    for k in ("description_sv", "terrain", "orientation", "placement", "reference", "tradition", "title"):
        if k in result:
            result[k] = URL_REGEX.sub("", result[k]).strip()

    return result

def strip_disclaimers(text: str) -> str:
    """Remove known Swedish disclaimer sentences anywhere in a block."""
    return DISCLAIMER_REGEX.sub("", text).strip()

# ---- Build inputs for models ----------------------------------------------------

def build_description_input(parsed: Dict[str, str]) -> str:
    """
    Build the LLM input for English description generation.
    Uses full RAÄ mapping for Swedish → English labels.
    """
    cls_sv = parsed.get("class", "").strip()
    cls_en = RAA_CLASS_MAPPING.get(cls_sv)
    cls_line = f"{cls_sv} ({cls_en})" if cls_en else cls_sv

    desc_sv = strip_disclaimers(parsed.get("description_sv", ""))
    terrain = parsed.get("terrain", "").strip()
    orientation = parsed.get("orientation", "").strip()

    if not desc_sv:
        return ""

    parts = []
    if cls_line:
        parts.append(cls_line)
    parts.append(f"Description (sv): {desc_sv}")
    if terrain:
        parts.append(f"Terrain (sv): {terrain}")
    if orientation:
        parts.append(f"Orientation (sv): {orientation}")

    return "\n".join(parts)

# ---- Deterministic visibility / condition --------------------------------------

VIS_VISIBLE_PATTERNS = [
    r"\bSynlig ovan mark\b",
    r"\bTydligt synlig\b",
]
VIS_NOT_VISIBLE_PATTERNS = [
    r"\bEj synlig\b",
    r"\bundermark\b",
    r"\bunder mark\b",
    r"\bövertäckt\b",
]

MEASURE_PAT = re.compile(r"\b\d+(?:[\.,]\d+)?\s*(?:m|meter|cm|mm)\b", re.IGNORECASE)
FEATURE_HINTS = [
    "kantkedja", "rest sten", "stenkista", "mittgrop", "kerb", "cist",
    "skyttevärn", "häll", "hällrist", "älvkvarn", "kantställd", "vall",
    "röse", "stensättning", "tomtning"
]

def compute_visibility(parsed: Dict[str, str]) -> int:
    placement = parsed.get("placement", "")
    text = "\n".join([placement]).lower()

    for pat in VIS_NOT_VISIBLE_PATTERNS:
        if re.search(pat, text, flags=re.IGNORECASE):
            return 0
    for pat in VIS_VISIBLE_PATTERNS:
        if re.search(pat, text, flags=re.IGNORECASE):
            return 2
    return 1

def disclaimers_present(original_text: str, parsed: Dict[str, str]) -> bool:
    # Check both original blob and parsed Swedish description
    if DISCLAIMER_REGEX.search(original_text):
        return True
    ds = parsed.get("description_sv", "")
    return bool(DISCLAIMER_REGEX.search(ds))

def detail_score(desc_sv: str) -> int:
    """Rough score for richness of info: counts measurements and feature hints."""
    score = 0
    if not desc_sv:
        return 0
    # Count measurements
    measures = MEASURE_PAT.findall(desc_sv)
    score += min(5, len(measures))  # cap to avoid runaway
    # Count feature hints
    low = desc_sv.lower()
    score += sum(1 for h in FEATURE_HINTS if h in low)
    return score

def compute_condition(original_text: str, parsed: Dict[str, str]) -> int:
    """
    c = 0 if disclaimer OR extremely sparse
    c = 2 if rich measurements/features and no disclaimer
    else 1
    """
    has_disclaimer = disclaimers_present(original_text, parsed)
    desc_sv = parsed.get("description_sv", "") or ""
    score = detail_score(desc_sv)

    if not desc_sv.strip():
        return 0
    if has_disclaimer:
        # If disclaimer but still a lot of detail, treat as uncertain (0), not good (2)
        return 0
    # Heuristic thresholds (tunable):
    if score >= 4:
        return 2
    if score <= 1:
        return 1
    return 1

# ---- DB + LLM pipeline ----------------------------------------------------------

def get_random_samples(db_path: str, num_samples: int = 10) -> list:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT inspireid, description 
        FROM fornlamningar 
        WHERE description IS NOT NULL AND description != ''
        ORDER BY RANDOM()
        LIMIT ?
    """, (num_samples,))
    samples = cursor.fetchall()
    conn.close()
    return samples

def generate_clean_description(api: OllamaAPI, desc_input: str) -> str:
    prompt = f"""
Write a concise description in English (1–3 sentences) for visitors.
Use the details under "Description (sv)" first (type, size, shape, structure, features, vegetation).
Add terrain/orientation only if space allows.
Do NOT include any headers like 'Site description:' or repeat the classification.
Do NOT mention reference numbers, status, verification, or data quality.
Return ONLY the description text.

Input:
{desc_input}
"""
    out = api.generate_description(desc_input, custom_instruction=prompt)
    return out.strip().replace("\n", " ")

def process_samples(samples: list) -> list:
    results = []
    desc_api = OllamaAPI(OllamaConfig(format=""))  # plain text only

    for i, (inspire_id, orig) in enumerate(samples, 1):
        logger.info(f"Processing {i}/{len(samples)}: {inspire_id}")

        try:
            parsed = parse_record(orig)
            desc_input = build_description_input(parsed)

            # If no usable description content => force missing + v=0,c=0, skip LLM
            if not desc_input.strip():
                v, c = 0, 0
                qc = {"reason": "no_usable_description"}
                results.append({
                    "inspireId": inspire_id,
                    "original_description": orig,
                    "parsed": parsed,
                    "desc_input": desc_input,
                    "qc_signals": qc,
                    "description": "missing",
                    "visibility": v,
                    "condition_known": c
                })
                continue

            # Generate English description
            description_en = generate_clean_description(desc_api, desc_input)

            # Deterministic v/c
            v = compute_visibility(parsed)
            c = compute_condition(orig, parsed)

            qc = {
                "placement": parsed.get("placement", ""),
                "disclaimer_present": disclaimers_present(orig, parsed),
                "detail_score": detail_score(parsed.get("description_sv", "") or ""),
            }

            results.append({
                "inspireId": inspire_id,
                "original_description": orig,
                "parsed": parsed,
                "desc_input": desc_input,
                "qc_signals": qc,
                "description": description_en,
                "visibility": v,
                "condition_known": c
            })

        except Exception as e:
            logger.error(f"Failed processing {inspire_id}: {e}")
            results.append({
                "inspireId": inspire_id,
                "original_description": orig,
                "parsed": {},
                "desc_input": "",
                "qc_signals": {"error": str(e)},
                "description": f"ERROR: {e}",
                "visibility": 1,
                "condition_known": 1
            })

    return results

def save_results(results: list, output_file: str = "generated_results.json"):
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    logger.info(f"Saved results to {output_file}")

def main():
    db_path = "src/data/fornlamningar_filtered_20km.sqlite"
    num_samples = 5
    samples = get_random_samples(db_path, num_samples)
    if not samples:
        logger.error("No samples found in database")
        return
    results = process_samples(samples)
    save_results(results)

if __name__ == "__main__":
    main()
