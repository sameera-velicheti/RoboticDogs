"""
System API for Agentic Paw Patrol.

This Flask blueprint handles application-level functionality:

- System status
- Route information
- Dog configuration and preparation
- AI model / Qwen status and control
- Frontend pages

Robot movement, waypoint patrol execution, inspection analysis,
and reports are handled by other API modules.
"""

import json
import os
import subprocess

import requests as http_requests

from flask import (
    Blueprint,
    Response,
    render_template,
    request,
    stream_with_context,
)

from navigation.route_loader import load_route
from nim_config import (
    NIM_MODEL,
    NIM_SERVER_DIR,
    NIM_URL,
    headers as nim_headers,
)
from startup import dog_prep
from status.system_status import status

from runtime import (
    DOG_IPS,
    ROUTES_DIR,
    clear_bridge,
    is_patrolling,
    reload_dogs,
)


# ---------------------------------------------------------------------------
# Blueprint
# ---------------------------------------------------------------------------

system_bp = Blueprint(
    "system",
    __name__,
)


# ---------------------------------------------------------------------------
# Frontend pages
# ---------------------------------------------------------------------------

@system_bp.route("/")
def index():
    """
    Serve the original UI.

    This remains available during the Phase 2 migration so the working
    application is not removed while the new interface is being built.
    """

    return render_template(
        "index.html"
    )


@system_bp.route("/new")
def new_ui():
    """
    Serve the new Phase 2 UI.
    """

    return render_template(
        "new_ui.html"
    )


# ---------------------------------------------------------------------------
# System status
# ---------------------------------------------------------------------------

@system_bp.route(
    "/api/status",
    methods=["GET"]
)
def api_status():
    """
    Return the shared Agentic Paw Patrol system status.

    Used by:
    - Pair & Connect
    - Startup monitoring
    - Dog readiness
    - Route-state monitoring
    """

    return status.get_status()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@system_bp.route(
    "/routes",
    methods=["GET"]
)
def list_routes():
    """
    Return route files that the UI can offer in the patrol dropdown.

    This preserves the original /routes response shape.
    """

    routes = []

    if not os.path.isdir(ROUTES_DIR):

        return {
            "routes": routes
        }

    for filename in sorted(
        os.listdir(ROUTES_DIR)
    ):

        if not filename.endswith(".json"):
            continue

        route_path = os.path.join(
            ROUTES_DIR,
            filename
        )

        try:

            route = load_route(
                route_path
            )

            routes.append({
                "file": filename,
                "name": route["route_name"],
                "stops": len(
                    route["waypoints"]
                ),
            })

        except Exception as error:

            routes.append({
                "file": filename,
                "name": filename,
                "error": str(error),
            })

    return {
        "routes": routes
    }


@system_bp.route(
    "/api/routes",
    methods=["GET"]
)
def api_routes():
    """
    Return every route with its waypoint information.

    The response matches the shape used by the new UI's Route Setup page.
    """

    routes = []

    if not os.path.isdir(ROUTES_DIR):

        return {
            "routes": routes
        }

    for filename in sorted(
        os.listdir(ROUTES_DIR)
    ):

        if not filename.endswith(".json"):
            continue

        route_path = os.path.join(
            ROUTES_DIR,
            filename
        )

        try:

            route = load_route(
                route_path
            )

        except Exception as error:

            routes.append({
                "file": filename,
                "name": filename,
                "error": str(error),
                "waypoints": [],
            })

            continue

        routes.append({
            "file": filename,
            "name": route["route_name"],
            "waypoints": [
                {
                    "name": waypoint["name"],
                    "x": waypoint["x"],
                    "y": waypoint["y"],
                    "yaw": waypoint["yaw"],
                    "photo":
                        waypoint["action"]
                        == "capture_image",
                    "required":
                        waypoint["required"],
                }
                for waypoint
                in route["waypoints"]
            ],
        })

    return {
        "routes": routes
    }


# ---------------------------------------------------------------------------
# Dog status
# ---------------------------------------------------------------------------

def _dog_status(dog):
    """
    Build the UI card information for one configured dog.

    States come from dog_prep.dog_status().

    A dog with an active RouteRunner is displayed as "On patrol".
    """

    state, label = dog_prep.dog_status(
        dog
    )

    on_patrol = is_patrolling(
        dog["id"]
    )

    if on_patrol:

        label = "On patrol"

    ids = list(
        DOG_IPS
    )

    if dog["id"] in ids:

        unit = (
            f"Unit "
            f"{ids.index(dog['id']) + 1:02d}"
        )

    else:

        unit = "Unit --"

    return {
        "id": dog["id"],
        "name": dog["name"],
        "ip": dog["ip"],
        "ssh_user": dog.get(
            "ssh_user",
            "hiwonder"
        ),
        "ros_port": dog.get(
            "ros_port",
            9090
        ),
        "unit": unit,
        "state": state,
        "label": label,
        "online": state != "offline",
        "on_patrol": on_patrol,
        "battery": None,
    }


# ---------------------------------------------------------------------------
# Dog configuration
# ---------------------------------------------------------------------------

@system_bp.route(
    "/api/dogs",
    methods=["GET"]
)
def api_dogs():
    """
    Return live status for every configured dog.

    Dog checks run in parallel so one unavailable robot does not make
    every other dog wait for its network timeout.
    """

    from concurrent.futures import (
        ThreadPoolExecutor,
    )

    dogs = reload_dogs()

    if not dogs:

        return {
            "dogs": []
        }

    with ThreadPoolExecutor(
        max_workers=len(dogs)
    ) as pool:

        dog_statuses = list(
            pool.map(
                _dog_status,
                dogs
            )
        )

    return {
        "dogs": dog_statuses
    }


@system_bp.route(
    "/api/dogs",
    methods=["POST"]
)
def api_add_dog():
    """
    Add a dog from the Add / Remove Dogs dialog.
    """

    data = (
        request.get_json(
            silent=True
        )
        or {}
    )

    dog, error = dog_prep.add_dog(
        data.get(
            "name",
            ""
        ),
        data.get(
            "ip",
            ""
        ),
        data.get(
            "ssh_user"
        )
        or "hiwonder",
        data.get(
            "ros_port",
            9090
        ),
    )

    if error:

        return {
            "error": error
        }, 400

    reload_dogs()

    return {
        "dog": dog
    }


@system_bp.route(
    "/api/dogs/<dog_id>",
    methods=["DELETE"]
)
def api_remove_dog(dog_id):
    """
    Remove a configured dog.

    A dog cannot be removed while its waypoint patrol is running.
    """

    if is_patrolling(dog_id):

        return {
            "error":
                "Stop this dog's patrol "
                "before removing it"
        }, 409

    if not dog_prep.remove_dog(
        dog_id
    ):

        return {
            "error": "No such dog"
        }, 404

    # Remove any cached ROS connection.
    #
    # The next request for this dog would otherwise reuse an old
    # bridge connection.

    clear_bridge(
        dog_id
    )

    reload_dogs()

    return {
        "status": "removed"
    }


# ---------------------------------------------------------------------------
# Dog preparation
# ---------------------------------------------------------------------------

@system_bp.route(
    "/api/dogs/<dog_id>/prepare",
    methods=["POST"]
)
def api_prepare_dog(dog_id):
    """
    Pair & Connect.

    Put the selected dog into patrol mode over SSH and stream each
    preparation step back to the UI.
    """

    dog = next(
        (
            candidate
            for candidate in reload_dogs()
            if candidate["id"] == dog_id
        ),
        None,
    )

    if not dog:

        return {
            "error": "No such dog"
        }, 404

    def generate():

        for update in dog_prep.prepare_dog(
            dog
        ):

            # If dog-side services were restarted successfully,
            # remove the previous ROS bridge so the next use creates
            # a fresh rosbridge connection.

            if (
                update.get("done")
                and update.get("ok")
            ):

                clear_bridge(
                    dog_id
                )

            yield (
                "data: "
                f"{json.dumps(update)}"
                "\n\n"
            )

    return Response(
        stream_with_context(
            generate()
        ),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# AI model / Qwen status
# ---------------------------------------------------------------------------

@system_bp.route(
    "/api/nim",
    methods=["GET"]
)
def api_nim():
    """
    Check whether the configured AI model server is answering.

    The frontend currently refers to this area as NIM even though the
    configured model is now Qwen.
    """

    models_url = (
        NIM_URL
        .rsplit(
            "/chat/completions",
            1
        )[0]
        + "/models"
    )

    try:

        response = http_requests.get(
            models_url,
            headers=nim_headers(),
            timeout=1.5,
        )

        response.raise_for_status()

        available_models = [
            model.get("id")
            for model
            in response.json().get(
                "data",
                []
            )
        ]

        loaded = (
            NIM_MODEL
            in available_models
        )

        return {
            "up": True,
            "model": NIM_MODEL,
            "loaded": loaded,
            "available":
                available_models,
            "label":
                "AI model ready"
                if loaded
                else (
                    "Server up, but "
                    f"'{NIM_MODEL}' "
                    "not loaded"
                ),
        }

    except Exception:

        return {
            "up": False,
            "model": NIM_MODEL,
            "loaded": False,
            "available": [],
            "label":
                "AI model offline "
                "(start Qwen to analyze photos)",
        }


# ---------------------------------------------------------------------------
# AI model / Qwen control
# ---------------------------------------------------------------------------

@system_bp.route(
    "/api/nim/<action>",
    methods=["POST"]
)
def api_nim_control(action):
    """
    Start or stop the Qwen server kit on this computer.

    The kit folder comes from:

        config_nim.yaml -> nim.server_dir
    """

    if action not in (
        "start",
        "stop"
    ):

        return {
            "error":
                "Use start or stop"
        }, 400

    if (
        not NIM_SERVER_DIR
        or not os.path.isdir(
            NIM_SERVER_DIR
        )
    ):

        return {
            "error":
                "Set server_dir in "
                "config_nim.yaml to "
                "the Qwen kit folder"
        }, 400

    script = os.path.join(
        NIM_SERVER_DIR,
        "linux",
        f"{action}.sh"
    )

    if not os.path.exists(
        script
    ):

        return {
            "error":
                f"{script} not found"
        }, 400

    command = [
        "bash",
        script,
    ]

    if action == "start":

        command.extend([
            "--no-harness",
            "-b",
        ])

    subprocess.Popen(
        command,
        cwd=NIM_SERVER_DIR,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    return {
        "status":
            f"{action} requested"
    }