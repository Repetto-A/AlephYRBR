"""Store local de encuentros y HC actualizada tras approve.

Persiste en out/encounters/ (JSON). Nada sale de la máquina.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from .schemas import EstudioRegistro, MedicacionActual, PatientRecord, RunResult

_ROOT = Path(__file__).resolve().parent.parent
STORE_DIR = _ROOT / "out" / "encounters"


def _patient_dir(patient_id: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in patient_id)
    return STORE_DIR / safe


def load_hc_overlay(patient_id: str, base_hc: PatientRecord) -> PatientRecord:
    """Si hay HC aprobada previa, la usa; si no, la base del corpus."""
    path = _patient_dir(patient_id) / "hc.json"
    if not path.exists():
        return base_hc
    try:
        return PatientRecord.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except Exception:  # noqa: BLE001
        return base_hc


def list_encounters(patient_id: str) -> list[dict[str, Any]]:
    path = _patient_dir(patient_id) / "encounters.jsonl"
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _apply_med_actions(
    hc: PatientRecord, actions: list[dict[str, Any]]
) -> list[str]:
    """Mutates hc.medicacion_actual. Returns applied action_ids."""
    applied: list[str] = []
    meds = {m.droga.lower(): m for m in hc.medicacion_actual}

    for act in actions:
        if act.get("status") != "pending_human":
            continue
        target = act.get("target", "")
        payload = act.get("payload") or {}
        nombre = (payload.get("nombre") or "").strip()
        if not nombre:
            continue
        key = nombre.lower()

        if target == "meds.active.add":
            meds[key] = MedicacionActual(
                droga=nombre,
                dosis=payload.get("dosis"),
                frecuencia=payload.get("frecuencia"),
                via=payload.get("via"),
            )
            applied.append(act["action_id"])
        elif target == "meds.active.change":
            prev = meds.get(key)
            meds[key] = MedicacionActual(
                droga=nombre,
                dosis=payload.get("dosis") or (prev.dosis if prev else None),
                frecuencia=payload.get("frecuencia")
                or (prev.frecuencia if prev else None),
                via=payload.get("via") or (prev.via if prev else None),
            )
            applied.append(act["action_id"])
        elif target == "meds.active.stop":
            if key in meds:
                del meds[key]
            applied.append(act["action_id"])

    hc.medicacion_actual = list(meds.values())
    return applied


def _apply_allergy_actions(
    hc: PatientRecord, actions: list[dict[str, Any]]
) -> list[str]:
    """Mutates hc.alergias. Returns applied action_ids."""
    applied: list[str] = []
    alergias = list(hc.alergias)
    known = {a.lower() for a in alergias}

    for act in actions:
        if act.get("status") != "pending_human":
            continue
        if act.get("target") != "allergies.add":
            continue
        payload = act.get("payload") or {}
        sustancia = (payload.get("sustancia") or "").strip()
        if not sustancia:
            continue
        key = sustancia.lower()
        already = key in known or any(key in k for k in known)
        if not already:
            label = sustancia
            reaccion = (payload.get("reaccion") or "").strip()
            if reaccion:
                label = f"{sustancia} ({reaccion})"
            alergias.append(label)
            known.add(key)
        applied.append(act["action_id"])

    hc.alergias = alergias
    return applied


def _apply_order_actions(
    hc: PatientRecord,
    actions: list[dict[str, Any]],
    *,
    encounter_id: str,
    pedido_en: str,
) -> list[str]:
    """Agrega pedidos de lab/estudio/derivación a hc.estudios."""
    applied: list[str] = []

    for act in actions:
        if act.get("status") != "pending_human":
            continue
        target = str(act.get("target") or "")
        if not target.startswith("orders."):
            continue
        payload = act.get("payload") or {}
        detalle = (payload.get("detalle") or "").strip()
        if not detalle:
            continue
        tipo = payload.get("tipo") or target.split(".", 1)[-1] or "otro"
        if tipo not in ("lab", "estudio", "derivacion", "otro"):
            tipo = "otro"
        dup = any(
            e.tipo == tipo
            and (e.detalle or "").strip().lower() == detalle.lower()
            and e.estado in ("pedido", "pendiente_resultado")
            for e in hc.estudios
        )
        if not dup:
            hc.estudios.append(
                EstudioRegistro(
                    estudio_id=f"est-{uuid.uuid4().hex[:8]}",
                    tipo=tipo,  # type: ignore[arg-type]
                    detalle=detalle,
                    estado="pedido",
                    pedido_en=pedido_en,
                    evidencia=payload.get("evidencia"),
                    encounter_id=encounter_id,
                )
            )
        applied.append(act["action_id"])

    return applied


def _collect_encounter_clinical(
    selected: list[dict[str, Any]],
    *,
    skip_ids: set[str],
) -> tuple[dict[str, Any], list[str]]:
    """Persiste vitales/seguimiento/alertas/evidencia en el encuentro."""
    clinical: dict[str, Any] = {
        "ordenes": [],
        "vitales": None,
        "seguimiento": None,
        "alerts": None,
        "evidence": [],
    }
    applied: list[str] = []

    for act in selected:
        aid = act.get("action_id")
        if not aid or aid in skip_ids:
            continue
        if act.get("status") != "pending_human":
            continue
        target = str(act.get("target") or "")
        payload = act.get("payload") or {}

        if target.startswith("orders."):
            # Ya aplicado a HC; igual se refleja en el encuentro.
            clinical["ordenes"].append(payload)
            applied.append(aid)
        elif target == "encounter.vitals":
            clinical["vitales"] = payload
            applied.append(aid)
        elif target == "encounter.followup":
            clinical["seguimiento"] = payload
            applied.append(aid)
        elif target == "encounter.alerts":
            clinical["alerts"] = payload
            applied.append(aid)
        elif target == "encounter.evidence":
            clinical["evidence"].append(payload)
            applied.append(aid)
        else:
            # soap y demas pending_human
            applied.append(aid)

    return clinical, applied


def apply_approval(
    *,
    patient_id: str,
    run_id: str,
    base_hc: PatientRecord,
    result: RunResult,
    proposal: dict[str, Any],
    edited_soap: str | None = None,
    action_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Aplica writes pending_human y guarda encuentro + HC overlay.

    Si action_ids es None, aplica todos los pending_human de meds + soap + etc.
    blocked_by_safety nunca se aplica.
    """
    if proposal.get("safety_gate") == "closed":
        raise ValueError("Safety gate cerrado: approve deshabilitado.")
    if result.status == "blocked":
        raise ValueError("No se puede aprobar un run blocked; corregí el plan primero.")
    if result.status == "escalate":
        raise ValueError("No se puede aprobar un run escalate; falta nota validada.")

    hc = load_hc_overlay(patient_id, base_hc).model_copy(deep=True)
    write_actions = list(proposal.get("write_actions") or [])

    if action_ids is not None:
        wanted = set(action_ids)
        selected = [a for a in write_actions if a.get("action_id") in wanted]
    else:
        selected = [a for a in write_actions if a.get("status") == "pending_human"]

    applied_meds = _apply_med_actions(hc, selected)
    applied_allergies = _apply_allergy_actions(hc, selected)

    encounter_id = uuid.uuid4().hex[:12]
    pedido_en = time.strftime("%Y-%m-%d")
    applied_orders = _apply_order_actions(
        hc, selected, encounter_id=encounter_id, pedido_en=pedido_en
    )

    skip_ids = set(applied_meds) | set(applied_allergies) | set(applied_orders)
    clinical, applied_other = _collect_encounter_clinical(selected, skip_ids=skip_ids)
    # Órdenes ya están en applied_orders; re-agregar al encuentro desde HC nuevas.
    clinical["ordenes"] = [
        e.model_dump(mode="json")
        for e in hc.estudios
        if e.encounter_id == encounter_id
    ]

    soap = proposal.get("soap_delta") or {}
    if edited_soap:
        soap = {**soap, "edited_text": edited_soap}

    record = {
        "encounter_id": encounter_id,
        "run_id": run_id,
        "patient_id": patient_id,
        "approved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "status": result.status,
        "soap": soap,
        "ordenes": clinical["ordenes"],
        "vitales": clinical["vitales"],
        "seguimiento": clinical["seguimiento"],
        "alerts": clinical["alerts"],
        "evidence": clinical["evidence"],
        "applied_action_ids": (
            applied_meds + applied_allergies + applied_orders + applied_other
        ),
        "skipped_blocked": [
            a.get("action_id")
            for a in write_actions
            if a.get("status") == "blocked_by_safety"
        ],
        "result_summary": {
            "transcript_source": result.transcript_source,
            "findings": [f.model_dump() for f in result.findings],
        },
    }

    pdir = _patient_dir(patient_id)
    pdir.mkdir(parents=True, exist_ok=True)
    with (pdir / "encounters.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    (pdir / "hc.json").write_text(
        hc.model_dump_json(indent=2), encoding="utf-8"
    )

    return {
        "encounter_id": encounter_id,
        "patient_id": patient_id,
        "applied_action_ids": record["applied_action_ids"],
        "hc": hc.model_dump(mode="json"),
        "encounters_count": len(list_encounters(patient_id)),
    }
