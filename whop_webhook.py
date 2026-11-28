from datetime import datetime, timedelta, timezone
import hashlib
import hmac
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


def _extract_member_info(payload: dict) -> tuple[str | None, str | None, str | None, int]:
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

    plan_text = " ".join(
        str(x or "")
        for x in [
            data.get("plan_name"),
            data.get("title"),
            data.get("variant_name"),
            (data.get("plan") or {}).get("name") if isinstance(data.get("plan"), dict) else "",
            (data.get("product") or {}).get("name") if isinstance(data.get("product"), dict) else "",
        ]
    ).lower()

    if "6" in plan_text or "six" in plan_text or "180" in plan_text:
        days = 180
    elif "3" in plan_text or "three" in plan_text or "trois" in plan_text or "90" in plan_text:
        days = 90
    else:
        days = 30

    return (
        email.strip().lower() if isinstance(email, str) and email.strip() else None,
        str(user_id).strip() if user_id else None,
        str(membership_id).strip() if membership_id else None,
        days,
    )


def _apply_subscription_change(
    email: str | None,
    whop_user_id: str | None,
    membership_id: str | None,
    active: bool,
    days: int = 30,
) -> tuple[bool, str | None]:
    from server.extensions import db
    from server.models import User

    user = None
    if whop_user_id:
        user = User.query.filter_by(whop_user_id=whop_user_id).first()
    if not user and email:
        user = User.query.filter(User.email.ilike(email)).first()

    if not user:
        return False, None

    now = datetime.utcnow()
    if whop_user_id:
        user.whop_user_id = whop_user_id
    if membership_id:
        user.whop_membership_id = membership_id

    if active:
        current_exp = getattr(user, "subscription_expires_at", None)
        if current_exp is not None and current_exp.tzinfo is not None:
            current_exp = current_exp.astimezone(timezone.utc).replace(tzinfo=None)
        base_date = current_exp if (current_exp and current_exp > now) else now
        new_exp = base_date + timedelta(days=days)
        user.is_subscribed = True
        if hasattr(user, "subscription_expires_at"):
            user.subscription_expires_at = new_exp
        db.session.commit()
        return True, new_exp.isoformat()

    user.is_subscribed = False
    if hasattr(user, "subscription_expires_at"):
        user.subscription_expires_at = now
    db.session.commit()
    return True, now.isoformat()


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

    activate_events = {"membership.activated", "payment.succeeded"}
    deactivate_events = {"membership.deactivated", "membership.expired", "membership.cancelled"}

    if event_type in activate_events or event_type in deactivate_events:
        email, whop_user_id, membership_id, days = _extract_member_info(payload)
        is_active = event_type in activate_events

        try:
            user_updated, expires_at = _apply_subscription_change(
                email=email,
                whop_user_id=whop_user_id,
                membership_id=membership_id,
                active=is_active,
                days=days,
            )
        except Exception as exc:
            return jsonify({
                "received": False,
                "event": event_type,
                "error": str(exc),
            }), 500

        return jsonify({
            "received": True,
            "event": event_type,
            "activated": is_active,
            "duration_days": days if is_active else 0,
            "expires_at": expires_at,
            "user_updated": user_updated,
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
