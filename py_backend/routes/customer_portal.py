from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request, status
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from config import settings
from services.customer_portal import (
    CustomerPortalConflict,
    CustomerPortalError,
    CustomerPortalExpired,
    CustomerPortalForbidden,
    CustomerPortalNotFound,
    CustomerPortalOutOfTokens,
    CustomerPortalService,
)

router = APIRouter()
templates = Jinja2Templates(directory=str(settings.templates_dir_abs))
PORTAL_PREFIX = settings.portal_path_prefix_normalized
RATING_OPTIONS = [
    (1, "Foarte nesatisfacut"),
    (2, "Nesatisfacut"),
    (3, "Acceptabil"),
    (4, "Satisfacut"),
    (5, "Foarte satisfacut"),
]


class CreateCustomerLinkBody(BaseModel):
    event_id: str = Field(min_length=1, description="ID eveniment (folder name in events/)")
    license_plate: str = Field(min_length=1, description="Numărul de înmatriculare")
    owner_name: str = Field(min_length=1, description="Numele proprietarului")
    mechanic_name: str = Field(min_length=1, description="Numele mecanicului")
    phone_number: str = Field(min_length=1, description="Nr. telefon destinatar SMS")
    send_sms: bool = Field(default=True, description="Trimite SMS automat cu link-ul")


class SendVideoLinkBody(BaseModel):
    """Cerere pentru trimiterea unui link video către client — match după plăcuță.

    Dacă `event_id` lipsește, serverul caută automat cel mai recent eveniment
    în care ALPR a detectat plăcuța specificată.
    """
    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "phone_number": "0767991625",
                    "license_plate": "TM14TZJ",
                    "owner_name": "Ion Popescu",
                    "mechanic_name": "Andrei Mecanicu",
                }
            ]
        }
    }

    phone_number: str = Field(
        min_length=4,
        description="Nr. telefon destinatar (ex. 0767991625 sau +40767991625)",
        examples=["0767991625"],
    )
    license_plate: str = Field(
        min_length=2,
        description="Nr. de înmatriculare al mașinii (ex. TM14TZJ, B123ABC)",
        examples=["TM14TZJ"],
    )
    owner_name: str = Field(
        min_length=1, description="Numele proprietarului", examples=["Ion Popescu"]
    )
    mechanic_name: str = Field(
        min_length=1,
        description="Numele mecanicului care a făcut constatarea",
        examples=["Andrei Mecanicu"],
    )
    event_id: str | None = Field(
        default=None,
        description="Opțional. Dacă lipsește, se folosește cel mai recent eveniment cu plăcuța dată.",
    )


def _service(request: Request) -> CustomerPortalService:
    return request.app.state.customer_portal_service


def _portal_base_context() -> dict:
    return {
        "brand_name": settings.portal_brand_name,
        "brand_subtitle": "Constatare video service",
        "footer_phone": settings.portal_footer_phone,
        "footer_email": settings.portal_footer_email,
        "footer_address": settings.portal_footer_address,
        "footer_hours": settings.portal_footer_hours,
        "theme_accent": settings.portal_theme_accent,
        "theme_dark": settings.portal_theme_dark,
        "logo_url": settings.portal_logo_url,
        "bumper_video_url": settings.portal_bumper_video_url,
        "rating_options": RATING_OPTIONS,
    }


def _portal_video_card_count(record: dict) -> int:
    ev = record.get("event") or {}
    n = 0
    if ev.get("camera1_url"):
        n += 1
    if ev.get("camera2_url"):
        n += 1
    return n


def _render_error_page(request: Request, *, status_code: int, title: str, message: str):
    context = {
        "request": request,
        "title": title,
        "message": message,
        **_portal_base_context(),
    }
    return templates.TemplateResponse(
        request=request,
        name="customer_portal_error.html",
        context=context,
        status_code=status_code,
    )


def _event_metadata(record: dict) -> dict:
    event = record["event"]
    recorded_at_iso = event["recorded_at"]
    try:
        recorded_at = datetime.fromisoformat(recorded_at_iso.replace("Z", "+00:00"))
        recorded_at_long = recorded_at.astimezone().strftime("%d.%m.%Y %H:%M")
    except ValueError:
        recorded_at_long = event["recorded_at_display"]
    return {
        "recorded_at": recorded_at_iso,
        "recorded_at_display": event["recorded_at_display"],
        "recorded_at_long": recorded_at_long,
    }


@router.post(
    "/api/v1/send-video-link",
    tags=["Customer Portal"],
    summary="Trimite link video către client (auto-match după plăcuță)",
    response_description="Link generat, token și status SMS",
    responses={
        200: {
            "description": "Link generat și SMS trimis cu succes",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "matched_event_id": "EVENT_2026-04-20T22-51-17Z_TM14TZJ",
                        "license_plate": "TM14TZJ",
                        "owner_name": "Ion Popescu",
                        "mechanic_name": "Andrei Mecanicu",
                        "phone_number": "0767991625",
                        "public_url": "https://video.scoala-ai.ro/verificare/abcd1234",
                        "token": "abcd1234efgh5678",
                        "expires_at": "2026-05-20T22:51:17+00:00",
                        "sms_status": "sent",
                        "sms_error": None,
                        "sms_preview": "Tedde Auto: Ion Popescu, am pregatit constatarea video...",
                        "warnings": [],
                    }
                }
            },
        },
        402: {
            "description": "Nu mai există tokeni — topup necesar înainte de a trimite SMS-uri",
            "content": {
                "application/json": {
                    "example": {"detail": "Nu mai aveți tokeni disponibili. Contactați administratorul pentru a adăuga tokeni."}
                }
            },
        },
        404: {"description": "Nu s-a găsit eveniment cu plăcuța dată"},
        409: {"description": "Evenimentul există dar nu are fișier video utilizabil"},
        400: {"description": "Parametri invalizi"},
    },
)
async def send_video_link(request: Request, body: SendVideoLinkBody) -> dict:
    """
    Match plăcuță → generează link securizat cu token → trimite SMS către client.

    **Flow complet:**

    1. Dacă nu se specifică `event_id`, serverul caută cel mai recent eveniment
       în care ALPR a detectat plăcuța (verifică și numele folderului, și
       `alpr.json.selected_plate`).
    2. Se creează un token unic (`token_urlsafe(24)`) și un link public
       `{public_base_url}/verificare/{token}`.
    3. Se trimite SMS prin gateway-ul configurat (SMS_GATEWAY_URL) cu text
       personalizat incluzând numele proprietarului, plăcuța și link-ul.
    4. Clientul accesează link-ul, completează un scurt quiz de feedback,
       apoi vede video-urile de la ambele camere.

    **Exemplu cURL:**
    ```bash
    curl -X POST http://localhost:8000/api/v1/send-video-link \\
      -H "Content-Type: application/json" \\
      -d '{
        "phone_number": "0767991625",
        "license_plate": "TM14TZJ",
        "owner_name": "Ion Popescu",
        "mechanic_name": "Andrei Mecanicu"
      }'
    ```

    **Notă:** Fiecare trimitere decrementează contorul `tokens_remaining`
    (model de facturare 1 token = 1 vehicul).
    """
    svc = _service(request)
    event_id = body.event_id
    if not event_id:
        event_id = await svc.find_latest_event_by_plate(body.license_plate)
        if not event_id:
            raise HTTPException(
                status_code=404,
                detail=f"Nu s-a găsit niciun eveniment cu plăcuța {body.license_plate!r}.",
            )
    try:
        result = await svc.create_link(
            event_id=event_id,
            license_plate=body.license_plate,
            owner_name=body.owner_name,
            mechanic_name=body.mechanic_name,
            phone_number=body.phone_number,
            send_sms=True,
        )
    except CustomerPortalOutOfTokens as exc:
        raise HTTPException(status_code=402, detail=str(exc)) from exc
    except CustomerPortalNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CustomerPortalConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except CustomerPortalError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "success": True,
        "matched_event_id": result["event_id"],
        "license_plate": result["license_plate"],
        "owner_name": result["owner_name"],
        "mechanic_name": result["mechanic_name"],
        "phone_number": result["phone_number"],
        "public_url": result["public_url"],
        "token": result["token"],
        "expires_at": result["expires_at"],
        "sms_status": result["sms_status"],
        "sms_error": result.get("sms_error"),
        "sms_preview": result.get("sms_preview"),
        "warnings": result.get("warnings", []),
        "recording_partial": result.get("recording_partial", False),
    }


@router.post(
    "/api/customer-links",
    tags=["Customer Portal"],
    summary="Creează link client pentru un event_id specific",
)
async def create_customer_link(request: Request, body: CreateCustomerLinkBody) -> dict:
    try:
        result = await _service(request).create_link(
            event_id=body.event_id,
            license_plate=body.license_plate,
            owner_name=body.owner_name,
            mechanic_name=body.mechanic_name,
            phone_number=body.phone_number,
            send_sms=body.send_sms,
        )
    except CustomerPortalOutOfTokens as exc:
        raise HTTPException(status_code=402, detail=str(exc)) from exc
    except CustomerPortalNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CustomerPortalConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except CustomerPortalError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "success": True,
        "link_id": result["link_id"],
        "event_id": result["event_id"],
        "token": result["token"],
        "public_url": result["public_url"],
        "sms_status": result["sms_status"],
        "sms_error": result["sms_error"],
        "expires_at": result["expires_at"],
        "created_at": result["created_at"],
        "warnings": result.get("warnings", []),
        "recording_partial": result.get("recording_partial", False),
        "sms_preview": result.get("sms_preview"),
    }


@router.get("/api/customer-links/{link_id}")
async def get_customer_link(link_id: int, request: Request) -> dict:
    try:
        return await _service(request).get_link(link_id)
    except CustomerPortalNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CustomerPortalConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/api/customer-links/{link_id}/resend")
async def resend_customer_link(link_id: int, request: Request) -> dict:
    try:
        result = await _service(request).resend(link_id)
    except CustomerPortalNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CustomerPortalConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except CustomerPortalError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "success": True,
        "link_id": result["link_id"],
        "event_id": result["event_id"],
        "token": result["token"],
        "public_url": result["public_url"],
        "sms_status": result["sms_status"],
        "sms_error": result["sms_error"],
        "sent_at": result["sent_at"],
        "expires_at": result["expires_at"],
    }


@router.get(f"{PORTAL_PREFIX}/{{token}}", include_in_schema=False)
async def customer_portal_page(token: str, request: Request):
    try:
        record = await _service(request).get_portal_record(token)
    except CustomerPortalExpired:
        return _render_error_page(
            request,
            status_code=410,
            title="Link expirat",
            message="Acest link nu mai este valabil. Contactati Tedde Auto pentru un link nou.",
        )
    except CustomerPortalNotFound:
        return _render_error_page(
            request,
            status_code=404,
            title="Link invalid",
            message="Linkul solicitat nu exista sau nu mai este disponibil.",
        )
    except CustomerPortalConflict as exc:
        return _render_error_page(request, status_code=409, title="Eveniment indisponibil", message=str(exc))

    context = {
        "request": request,
        "portal": record,
        "event_meta": _event_metadata(record),
        "portal_video_card_count": _portal_video_card_count(record),
        **_portal_base_context(),
    }
    return templates.TemplateResponse(
        request=request,
        name="customer_portal.html",
        context=context,
    )


@router.post(f"{PORTAL_PREFIX}/{{token}}/quiz", include_in_schema=False)
async def customer_portal_quiz(
    token: str,
    request: Request,
    rating_overall: int = Form(...),
    rating_explanation: int = Form(...),
    free_text: str = Form(...),
):
    try:
        await _service(request).submit_feedback(
            token,
            rating_overall=rating_overall,
            rating_explanation=rating_explanation,
            free_text=free_text,
        )
    except CustomerPortalConflict:
        return RedirectResponse(url=f"{PORTAL_PREFIX}/{token}", status_code=status.HTTP_303_SEE_OTHER)
    except CustomerPortalExpired:
        return _render_error_page(
            request,
            status_code=410,
            title="Link expirat",
            message="Acest link a expirat si nu mai poate primi feedback.",
        )
    except CustomerPortalNotFound:
        return _render_error_page(
            request,
            status_code=404,
            title="Link invalid",
            message="Linkul solicitat nu exista sau nu mai este disponibil.",
        )
    except CustomerPortalError as exc:
        record = None
        try:
            record = await _service(request).get_portal_record(token)
        except Exception:
            record = None
        if record is None:
            return _render_error_page(
                request,
                status_code=400,
                title="Cerere invalida",
                message=str(exc),
            )
        context = {
            "request": request,
            "portal": record,
            "event_meta": _event_metadata(record) if record else None,
            "form_error": str(exc),
            "portal_video_card_count": _portal_video_card_count(record) if record else 0,
            **_portal_base_context(),
        }
        return templates.TemplateResponse(
            request=request,
            name="customer_portal.html",
            context=context,
            status_code=422,
        )

    return RedirectResponse(url=f"{PORTAL_PREFIX}/{token}", status_code=status.HTTP_303_SEE_OTHER)


async def _video_response(request: Request, token: str, camera_id: int):
    try:
        path = await _service(request).resolve_video_path(token, camera_id)
    except CustomerPortalForbidden as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except CustomerPortalExpired as exc:
        raise HTTPException(status_code=410, detail=str(exc)) from exc
    except CustomerPortalNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CustomerPortalConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    # Inline (not attachment): browsers refuse to play in <video> when Content-Disposition is attachment.
    return FileResponse(
        path=path,
        media_type="video/mp4",
        filename=Path(path).name,
        content_disposition_type="inline",
    )


@router.get(f"{PORTAL_PREFIX}/{{token}}/video/camera1", include_in_schema=False)
async def customer_portal_camera1(token: str, request: Request):
    return await _video_response(request, token, 1)


@router.get(f"{PORTAL_PREFIX}/{{token}}/video/camera2", include_in_schema=False)
async def customer_portal_camera2(token: str, request: Request):
    return await _video_response(request, token, 2)
