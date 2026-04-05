"""
AgentNimi Web Server - Flask backend with SSE streaming
Refactored with blueprints for better organization.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from flask import Flask, render_template
from web.utils import state
from web.services import agent_service


def create_app():
    """Application factory pattern for Flask app."""
    app = Flask(__name__, template_folder="templates", static_folder="static")
    
    # Register blueprints
    from web.blueprints.chat import chat_bp
    from web.blueprints.conversations import conversations_bp
    from web.blueprints.providers import providers_bp
    from web.blueprints.tools import tools_bp
    from web.blueprints.router import router_bp
    from web.blueprints.monitor import monitor_bp
    from web.blueprints.system import system_bp
    from web.blueprints.extension import extension_bp
    from web.blueprints.browser import browser_bp
    from web.blueprints.documents import documents_bp
    
    app.register_blueprint(chat_bp)
    app.register_blueprint(conversations_bp)
    app.register_blueprint(providers_bp)
    app.register_blueprint(tools_bp)
    app.register_blueprint(router_bp)
    app.register_blueprint(monitor_bp)
    app.register_blueprint(system_bp)
    app.register_blueprint(extension_bp)
    app.register_blueprint(browser_bp)
    app.register_blueprint(documents_bp)
    
    # Root route
    @app.route("/")
    def index():
        return render_template("index.html")
    
    return app


def run_web(host: str = "0.0.0.0", port: int = 1337, debug: bool = False):
    """Start the web server."""
    # Initialize agent and global state
    agent_service.init_agent()
    
    print(f"\n  🌐 AgentNimi Web UI: http://{host}:{port}")
    print(f"  Provider: {state.agent.provider.name()}\n")
    
    app = create_app()
    app.run(host=host, port=port, debug=debug, threaded=True, use_reloader=False)


if __name__ == "__main__":
    run_web(debug=False)
