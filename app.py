"""
Agentic Paw Patrol - Flask Backend

This is the main entry point for the Phase 2 application.

The actual backend functionality is separated into Flask blueprints:

- system_api.py
    System status
    Dog management
    Dog preparation
    AI model / Qwen management
    Route information
    Frontend pages

- patrol_api.py
    Waypoint patrols
    Emergency stopping
    Legacy Phase 1 movement commands

- vision_api.py
    Image analysis
    Inspection reports
    Captured images

Shared runtime resources such as ROS bridge connections and active patrols
are stored in runtime.py.
"""

from flask import Flask

from api.system_api import system_bp
from api.patrol_api import patrol_bp
from api.vision_api import vision_bp


def create_app():
    """
    Create and configure the Agentic Paw Patrol Flask application.
    """

    app = Flask(__name__)

    # Register the application/system API.
    app.register_blueprint(system_bp)

    # Register waypoint patrol and robot-control API.
    app.register_blueprint(patrol_bp)

    # Register inspection/image-analysis API.
    app.register_blueprint(vision_bp)

    return app


# Create the Flask application.
app = create_app()


if __name__ == "__main__":

    print(
        "Agentic Paw Patrol running at "
        "http://localhost:5000"
    )

    app.run(
        debug=False,
        threaded=True,
        port=5000
    )