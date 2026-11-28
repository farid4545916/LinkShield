from server import create_app
from whop_webhook import whop_bp

app = create_app()
app.register_blueprint(whop_bp)
application = app
