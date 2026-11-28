import os
from flask import Blueprint, jsonify, request

whop_bp = Blueprint("whop_webhook", __name__)


@whop_bp.route("/webhooks/whop", methods=["POST"])
def whop_webhook():
    secret = os.environ.get("WHOP_WEBHOOK_SECRET", "")
    signature = request.headers.get("Whop-Signature", "")
    payload = request.get_json(silent=True) or {}

    # TODO: vérifier la signature avec `secret` et mettre à jour l'accès utilisateur en base
    return jsonify({"received": True, "has_secret": bool(secret), "has_signature": bool(signature)}), 200
