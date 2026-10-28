# Agentic Paw Patrol

An AI-powered autonomous safety inspection system built on NVIDIA technology. NemoClaw pairs a locally-run large language model with ROSPug quadruped robots to autonomously inspect physical spaces, detect safety hazards, and generate documented compliance reports, with no cloud dependency.

---

## Overview

Agentic Paw Patrol is a system that uses AI and small robot dogs to inspect a space for safety issues.

Through a web interface, users pair one or more robots and send each one on a saved inspection route. The robot walks to each stop using its map, takes a picture, and returns to its start spot facing the right way for the next run. Users can choose which end of the aisle the robot starts from, and photos appear live in the interface as they are taken. After an inspection, all captured images can be analyzed together to create one report for the full inspection. Each finding is tied to its source image and named stop (for example, "Stop 4: loose cable"), and users can jump straight to the photo behind a finding. The AI checks for safety problems like blocked walkways, loose cables, or open doors, rates the severity, and suggests remediation. Users can also type plain-English commands (e.g. "walk backward for 2 seconds") to move a robot directly, and stop any robot at any time with Emergency Stop.

---

## Architecture

```
        Operator (Web UI)
               |
               v
     Dell Laptop (Qwen via NIM + Flask App)
               |
               v
        Router (TP-Link)
          /         \
         v           v
    ROSPug #1     ROSPug #2
   (camera, LiDAR, ROS navigation)
```

- **Dell Laptop** runs the Qwen model locally via NIM, along with the Flask control application
- **Router** connects the Dell laptop to one or more ROSPug robots over a dedicated network
- **ROSPug units** localize on a saved map, navigate between route stops, stream LiDAR data, and capture images via onboard camera

---

## Key Capabilities

- **Route-based inspections** — robots walk a saved route stop by stop, from either end of the aisle, and return to their start spot when finished
- **Live progress** — the interface shows each robot's position on a route map, its current task, its battery level, and each photo as it is taken
- **Inspection-wide compliance analysis** — analyze all captured images together for one report, with findings linked to their source image and named stop; the text report includes inspection date, route, image count, findings, and overall assessment
- **Emergency Stop** — stops a robot's route and any running command at once, without affecting other robots
- **Natural language robot control** — plain-English commands are parsed into structured robot actions by the locally-run Qwen model, for moving a robot directly when needed
- **Multi-robot control** — multiple ROSPug units can be paired and run independently from a single interface
- **One-click launch** — a desktop icon starts the application and opens the pairing screen
- **Fully local / no cloud dependency** — the entire pipeline (language model, vision analysis, robot control) runs on local hardware; no facility data leaves the network

---

## Code Reference

| File | Description |
|---|---|
| `app.py` | Flask entry point — starts the application and registers the API routes |
| `api/patrol_api.py` | Starts and stops inspection routes, Emergency Stop, and typed commands; streams progress and photos to the UI |
| `api/vision_api.py` | Runs inspection-wide compliance analysis and serves captured photos |
| `api/system_api.py` | Robot list and status, AI model status, and available routes |
| `services/legacy_commands.py` | Turns typed commands into robot actions using the AI model |
| `runtime.py` | Shared state, including each robot's connection and Emergency Stop flag |
| `route_runner.py` | Walks a route stop by stop and captures photos |
| `navigator.py` | Sends navigation goals to the robot's `move_base` |
| `ros_nodes.py` | `RosPugBridge` class — manages the direct ROS connection to each robot, including movement commands, LiDAR readings, and camera capture |
| `battery.py` | Converts battery voltage to a percentage and flags low battery |
| `startup/` | Pair & Connect steps and camera diagnostics |
| `routes/data_center.json` | Inspection route starting from the near end of the aisle |
| `routes/data_center_reverse.json` | Inspection route starting from the far end of the aisle |
| `vision/compliance_checker.py` | Sends captured images to the NIM for safety compliance analysis and returns findings |
| `vision/compliance_rules.json` | Configurable list of safety hazards the system checks for (e.g. loose cables, open doors, spills, blocked walkways) — edit this file to add or adjust compliance rules |
| `vision/report_generator.py` | Builds timestamped inspection-wide compliance reports (JSON and text) from analysis findings, including source images, stop names, severity ratings, and remediation guidance |
| `templates/new_ui.html` | Web-based user interface — pairing, route progress, live photos, analysis results, and typed commands |
| `start_pawpatrol.sh`, `install_desktop_icon.sh` | Desktop launcher and its installer (Linux) |

---

## Current Limitations

This is a validated proof of concept, not a production-hardened deployment. Known limitations:
- Battery life of ~30–45 minutes per robot unit
- No support for stairs or uneven terrain
- LiDAR reliability is reduced on certain surfaces (e.g. wire mesh, chain-link)
- No authentication currently implemented on the web interface
- Single point-in-time inspections; no persistent historical tracking across sessions
- Only one aisle route is currently mapped; a full facility loop requires new mapping
- The desktop launcher is Linux only
- The application runs on Flask's development server; a production server is being tested on the `production-server` branch

---

## Future Roadmap

- Migration to an industrial-grade robot platform (self-righting, all-terrain, longer battery life)
- Fleet management tooling — scheduling, charging coordination, historical trend analysis
- NVIDIA Isaac Sim / Omniverse integration for digital twin simulation and route testing prior to deployment
- Fine-tuned vision model trained on facility-specific hazard catalogs for improved compliance accuracy
- Authentication, audit logging, and access controls for enterprise deployment
- Integration with existing facility management / compliance software systems

---

## Repository

https://github.com/sameera-velicheti/RoboticDogs