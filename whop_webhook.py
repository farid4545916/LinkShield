import hmac
import hashlib
import os
from flask import Blueprint, jsonify, redirect, request

whop_bp = Blueprint("whop_webhook", __name__)

try:
    from flask_wtf.csrf import CSRFProtect
except ImportError:
    CSRFProtect = None


@whop_bp.record_once
def _exempt_csrf(state):
    if CSRFProtect is not None:
        csrf_ext = state.app.extensions.get("csrf")
        if csrf_ext is not None and hasattr(csrf_ext, "exempt"):
            csrf_ext.exempt(whop_bp)


def _verify_whop_signature(raw_body: bytes, signature: str, secret: str) -> bool:
    if not secret:
        return True
    if not signature:
        return False
    cleaned = signature.replace("sha256=", "").strip()
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, cleaned)


def _extract_member_info(payload: dict) -> tuple[str | None, str | None, str | None]:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    email = (
        data.get("email")
        or (data.get("user") or {}).get("email")
        or payload.get("email")
    )
    user_id = (
        data.get("user_id")
        or (data.get("user") or {}).get("id")
        or payload.get("user_id")
    )
    membership_id = data.get("id") or data.get("membership_id") or payload.get("id")
    return (
        email.strip().lower() if isinstance(email, str) and email.strip() else None,
        str(user_id).strip() if user_id else None,
        str(membership_id).strip() if membership_id else None,
    )


@whop_bp.route("/subscribe", methods=["GET"])
def subscribe():
    checkout_url = os.environ.get(
        "WHOP_CHECKOUT_URL",
        "https://whop.com/traficclair1/linkshield-2d/",
    ).strip()
    return redirect(checkout_url, code=302)


@whop_bp.route("/webhooks/whop", methods=["POST"])
def whop_webhook():
    secret = os.environ.get("WHOP_WEBHOOK_SECRET", "").strip()
    signature = request.headers.get("Whop-Signature", "")
    raw_body = request.get_data()

    if signature and not _verify_whop_signature(raw_body, signature, secret):
        return jsonify({"received": False, "error": "invalid_signature"}), 401

    payload = request.get_json(silent=True) or {}
    event_type = payload.get("event") or payload.get("type") or payload.get("action") or ""

    if event_type == "membership.activated":
        email, whop_user_id, membership_id = _extract_member_info(payload)

        # TODO: relier `email` / `whop_user_id` à ton modèle utilisateur dans `server/models.py`
        # et marquer l'abonnement comme actif (`is_subscribed = True`, `whop_membership_id = membership_id`).

        return jsonify({
            "received": True,
            "event": event_type,
            "activated": True,
            "email": email,
            "whop_user_id": whop_user_id,
            "membership_id": membership_id,
            "has_secret": bool(secret),
            "has_signature": bool(signature),
        }), 200

    return jsonify({
        "received": True,
        "event": event_type,
        "has_secret": bool(secret),
        "has_signature": bool(signature),
    }), 200
