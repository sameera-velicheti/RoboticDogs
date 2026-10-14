"""
Vision API for Agentic Paw Patrol.

This Flask blueprint handles inspection-image functionality:

- Analyze a collection of captured images
- Associate findings with waypoint names
- Generate one combined inspection report
- Delete captured images
- Serve captured images
- Serve generated reports

The actual computer-vision / AI analysis remains inside the vision package.
"""

import json
import os
from datetime import datetime

from flask import (
    Blueprint,
    Response,
    request,
    send_from_directory,
    stream_with_context,
)

from runtime import (
    CAPTURE_DIR,
    REPORT_DIR,
)


# ---------------------------------------------------------------------------
# Blueprint
# ---------------------------------------------------------------------------

vision_bp = Blueprint(
    "vision",
    __name__,
)


# ---------------------------------------------------------------------------
# Inspection analysis
# ---------------------------------------------------------------------------

@vision_bp.route(
    "/analyze",
    methods=["POST"]
)
def analyze():
    """
    Analyze one or more inspection images.

    The UI can send multiple images from a single route.

    Each image may include:
    - filepath
    - waypoint_name
    - route_name

    Findings are associated with the source image and waypoint.

    After all images are analyzed, one combined inspection report is
    generated for the complete route.
    """

    data = (
        request.get_json(
            silent=True
        )
        or {}
    )

    if not isinstance(
        data,
        dict
    ):

        return {
            "error":
                "Invalid request body"
        }, 400

    requested_images = data.get(
        "images"
    )

    # Keep compatibility with the older single-image request format.

    if (
        requested_images is None
        and data.get("filepath")
    ):

        requested_images = [
            {
                "filepath":
                    data["filepath"]
            }
        ]

    if (
        not isinstance(
            requested_images,
            list
        )
        or not requested_images
    ):

        return {
            "error":
                "No images provided"
        }, 400


    # -----------------------------------------------------------------------
    # Validate image paths
    # -----------------------------------------------------------------------

    capture_root = os.path.realpath(
        CAPTURE_DIR
    )

    images = []

    for image in requested_images:

        if not isinstance(
            image,
            dict
        ):

            return {
                "error":
                    "Each image must be "
                    "an object"
            }, 400

        filepath = image.get(
            "filepath",
            ""
        )

        if (
            not isinstance(
                filepath,
                str
            )
            or not filepath.strip()
        ):

            return {
                "error":
                    "Each image must include "
                    "a filepath"
            }, 400

        resolved_path = os.path.realpath(
            filepath.strip()
        )

        try:

            is_capture = (
                os.path.commonpath(
                    (
                        capture_root,
                        resolved_path,
                    )
                )
                == capture_root
            )

        except ValueError:

            is_capture = False

        if (
            not is_capture
            or resolved_path
            == capture_root
        ):

            return {
                "error":
                    "Invalid filepath"
            }, 400


        # -------------------------------------------------------------------
        # Optional route metadata
        # -------------------------------------------------------------------

        waypoint_name = image.get(
            "waypoint_name"
        )

        if waypoint_name is not None:

            waypoint_name = (
                str(
                    waypoint_name
                ).strip()
                or None
            )


        route_name = image.get(
            "route_name"
        )

        if route_name is not None:

            route_name = (
                str(
                    route_name
                ).strip()
                or None
            )


        images.append({
            "filepath":
                resolved_path,

            "waypoint_name":
                waypoint_name,

            "route_name":
                route_name,
        })


    # -----------------------------------------------------------------------
    # Determine route name
    # -----------------------------------------------------------------------

    route_name = str(
        data.get("route_name")
        or next(
            (
                image["route_name"]
                for image in images
                if image["route_name"]
            ),
            "Data Center Patrol",
        )
    ).strip()

    if not route_name:

        route_name = (
            "Data Center Patrol"
        )


    # -----------------------------------------------------------------------
    # Stream the analysis back to the UI
    # -----------------------------------------------------------------------

    def generate():

        from vision.compliance_checker import (
            check_compliance_with_nim,
        )

        from vision.report_generator import (
            generate_report,
        )

        try:

            all_findings = []


            # ---------------------------------------------------------------
            # Analyze every inspection image
            # ---------------------------------------------------------------

            for image in images:

                filepath = image[
                    "filepath"
                ]

                filename = os.path.basename(
                    filepath
                )

                timestamp = (
                    datetime.now()
                    .strftime(
                        "%Y%m%d_%H%M%S"
                    )
                )

                waypoint_name = image[
                    "waypoint_name"
                ]

                location = (
                    f"{waypoint_name}: "
                    if waypoint_name
                    else ""
                )


                yield (
                    "data: "
                    + json.dumps({
                        "type": "log",
                        "msg":
                            "Analyzing "
                            f"{location}"
                            f"{filename}..."
                    })
                    + "\n\n"
                )


                # -----------------------------------------------------------
                # Run AI compliance analysis
                # -----------------------------------------------------------

                findings = (
                    check_compliance_with_nim(
                        filepath=filepath,
                        timestamp=timestamp,
                    )
                )


                # Associate every finding with the waypoint where the image
                # was captured.

                for finding in findings:

                    finding[
                        "waypoint_name"
                    ] = waypoint_name


                all_findings.append(
                    findings
                )


                # -----------------------------------------------------------
                # Determine image-level inspection status
                # -----------------------------------------------------------

                high_fails = [
                    finding
                    for finding in findings
                    if (
                        finding["status"]
                        == "FAIL"
                        and finding[
                            "severity"
                        ]
                        in (
                            "HIGH",
                            "ALERT",
                        )
                    )
                ]


                other_fails = [
                    finding
                    for finding in findings
                    if (
                        finding["status"]
                        == "FAIL"
                        and finding[
                            "severity"
                        ]
                        in (
                            "MEDIUM",
                            "LOW",
                        )
                    )
                ]


                if high_fails:

                    image_status = (
                        "FAIL"
                    )

                elif other_fails:

                    image_status = (
                        "WARNING"
                    )

                else:

                    image_status = (
                        "PASS"
                    )


                # -----------------------------------------------------------
                # Preserve existing lost-cellphone log behavior
                # -----------------------------------------------------------

                if any(
                    finding.get(
                        "rule_id"
                    )
                    == "PHONE_001"
                    and finding[
                        "status"
                    ]
                    == "FAIL"

                    for finding
                    in findings
                ):

                    yield (
                        "data: "
                        + json.dumps({
                            "type": "log",
                            "msg":
                                "Lost cellphone "
                                "detected in "
                                f"{filename}",
                        })
                        + "\n\n"
                    )


                # -----------------------------------------------------------
                # Send findings for this image to the UI
                # -----------------------------------------------------------

                visible_findings = [
                    {
                        "rule_name":
                            finding[
                                "rule_name"
                            ],

                        "severity":
                            finding[
                                "severity"
                            ],

                        "status":
                            finding[
                                "status"
                            ],

                        "remediation":
                            finding[
                                "remediation"
                            ],
                    }

                    for finding
                    in findings
                ]


                yield (
                    "data: "
                    + json.dumps({
                        "type":
                            "image_findings",

                        "filename":
                            filename,

                        "waypoint_name":
                            waypoint_name,

                        "status":
                            image_status,

                        "findings":
                            visible_findings,
                    })
                    + "\n\n"
                )


            # ---------------------------------------------------------------
            # Generate one report for the complete inspection route
            # ---------------------------------------------------------------

            (
                report,
                json_path,
                txt_path,
            ) = generate_report(
                all_findings=
                    all_findings,

                location=
                    "SHI Lab",

                inspector=
                    "NemoClaw",

                route_name=
                    route_name,
            )


            total_fails = sum(
                finding["status"]
                == "FAIL"

                for findings
                in all_findings

                for finding
                in findings
            )


            yield (
                "data: "
                + json.dumps({
                    "type":
                        "report_summary",

                    "overall":
                        report[
                            "overall_status"
                        ],

                    "total_images":
                        len(images),

                    "total_fails":
                        total_fails,

                    "report_file":
                        os.path.basename(
                            txt_path
                        ),

                    "dog_id":
                        data.get(
                            "dog_id",
                            "dog1"
                        ),
                })
                + "\n\n"
            )


            yield (
                "data: "
                + json.dumps({
                    "type":
                        "done",

                    "msg":
                        "Analysis complete.",
                })
                + "\n\n"
            )


        except Exception as error:

            yield (
                "data: "
                + json.dumps({
                    "type":
                        "error",

                    "msg":
                        str(error),
                })
                + "\n\n"
            )


    return Response(
        stream_with_context(
            generate()
        ),

        mimetype=
            "text/event-stream",

        headers={
            "Cache-Control":
                "no-cache",

            "X-Accel-Buffering":
                "no",
        },
    )


# ---------------------------------------------------------------------------
# Captured image deletion
# ---------------------------------------------------------------------------

@vision_bp.route(
    "/clear-image",
    methods=["POST"]
)
def clear_image():
    """
    Delete one captured image from the captures directory.

    Only direct filenames inside CAPTURE_DIR are accepted.
    """

    data = (
        request.get_json(
            silent=True
        )
        or {}
    )

    filename = (
        data.get(
            "filename"
        )
        or ""
    ).strip()


    if not filename:

        return {
            "error":
                "No filename provided"
        }, 400


    safe_filename = os.path.basename(
        filename
    )


    if (
        not safe_filename
        or safe_filename
        != filename
    ):

        return {
            "error":
                "Invalid filename"
        }, 400


    target_path = os.path.abspath(
        os.path.join(
            CAPTURE_DIR,
            safe_filename
        )
    )


    capture_root = os.path.abspath(
        CAPTURE_DIR
    )


    if (
        os.path.commonpath(
            [
                capture_root,
                target_path,
            ]
        )
        != capture_root
    ):

        return {
            "error":
                "Invalid filename"
        }, 400


    if os.path.exists(
        target_path
    ):

        os.remove(
            target_path
        )


    return {
        "status":
            "deleted",

        "filename":
            safe_filename,
    }


# ---------------------------------------------------------------------------
# Captured images
# ---------------------------------------------------------------------------

@vision_bp.route(
    "/captures/<filename>"
)
def serve_capture(filename):
    """
    Serve a captured inspection image to the frontend.
    """

    return send_from_directory(
        CAPTURE_DIR,
        filename
    )


# ---------------------------------------------------------------------------
# Inspection reports
# ---------------------------------------------------------------------------

@vision_bp.route(
    "/reports/<filename>"
)
def serve_report(filename):
    """
    Serve a generated inspection report to the frontend.
    """

    return send_from_directory(
        REPORT_DIR,
        filename
    )