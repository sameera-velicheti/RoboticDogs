# Agentic Paw Patrol

An AI-powered autonomous safety inspection system built on NVIDIA technology. NemoClaw pairs a locally-run large language model with ROSPug quadruped robots to autonomously inspect physical spaces, detect safety hazards, and generate documented compliance reports, with no cloud dependency.

---

## Overview

Agentic Paw Patrol is a system that uses AI and small robot dogs to inspect a space for safety issues. 

Through a web interface, users type plain-English commands (e.g. "walk forward for 10 seconds") to control one or more robots at once. As a robot moves, it avoids obstacles on its own using LiDAR and takes pictures along the way. After an inspection, all captured images can be analyzed together to create one report for the full inspection. Images remain visible in the interface, and each finding is tied to its source image and, when available, its named waypoint (for example, “Corner 1: loose cable”). The AI checks for safety problems like blocked walkways, loose cables, or open doors, rates the severity, and suggests remediation.

---

## Architecture

```
        Operator (Web UI)
               |
               v
        GB10 (NVIDIA Nemotron via NIM + Flask App)
               |
               v
             Router
          /         \
         v           v
    ROSPug #1     ROSPug #2
   (camera, LiDAR, ROS control)
```

- **GB10** runs the NVIDIA Nemotron language model locally via NIM, along with the Flask control application
- **Router** connects the GB10 to one or more ROSPug robots over a dedicated network
- **ROSPug units** execute movement commands, stream LiDAR data for obstacle avoidance, and capture images via onboard camera

---

## Key Capabilities

- **Natural language robot control** — plain-English commands are parsed into structured robot actions by a locally-run NVIDIA Nemotron model
- **Real-time obstacle avoidance** — onboard LiDAR detects obstacles during movement; the robot attempts to turn and reroute, or stops and requests new instructions if fully blocked
- **Automatic image capture** — images are captured at regular intervals during movement and saved for review
- **Inspection-wide compliance analysis** — analyze all captured images together for one report, with findings linked to their source image and named waypoint when available
- **Multi-robot control** — multiple ROSPug units can be commanded independently or simultaneously from a single interface
- **Fully local / no cloud dependency** — the entire pipeline (language model, vision analysis, robot control) runs on local hardware; no facility data leaves the network

---

## Code Reference

| File | Description |
|---|---|
| `app.py` | Flask backend and main application logic — handles UI routes, sends commands to NIM, executes robot movement, manages LiDAR-based obstacle avoidance, coordinates image capture, and triggers compliance analysis |
| `ros_nodes.py` | `RosPugBridge` class — manages the direct ROS connection to each robot, including movement commands, LiDAR readings, and camera capture |
| `vision/compliance_checker.py` | Sends captured images to the NIM for safety compliance analysis and returns findings |
| `vision/compliance_rules.json` | Configurable list of safety hazards the system checks for (e.g. loose cables, open doors, spills, blocked walkways) — edit this file to add or adjust compliance rules |
| `vision/report_generator.py` | Builds timestamped inspection-wide compliance reports (JSON and text) from analysis findings, including source images, waypoint names, severity ratings, and remediation guidance |
| `templates/index.html` | Web-based user interface — command inputs, live execution status, and image/report viewing panel |

---

## Current Limitations

This is a validated proof of concept, not a production-hardened deployment. Known limitations:
- Battery life of ~30–45 minutes per robot unit
- No support for stairs or uneven terrain
- LiDAR reliability is reduced on certain surfaces (e.g. wire mesh, chain-link)
- No authentication currently implemented on the web interface
- Single point-in-time inspections; no persistent historical tracking across sessions

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
