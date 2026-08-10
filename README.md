USER GUIDE

ON POWERED UP GB10:
1. To start NVIDIA NIM, paste into the terminal:
export NGC_API_KEY=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
export LOCAL_NIM_CACHE=~/.cache/nim
mkdir -p "$LOCAL_NIM_CACHE"
chmod -R a+w "$LOCAL_NIM_CACHE"
docker run -it --rm \
    --gpus all \
    --ipc host \
    --shm-size=32GB \
    -e NGC_API_KEY \
    -v "$LOCAL_NIM_CACHE:/opt/nim/.cache" \
    -p 8000:8000 \
    nvcr.io/nim/nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:latest

2. To start ROS Pug quadrupeds:
    - Turn on the physical dogs 
    - Connect to router: TP-Link_3AAF
    - Router admin page: http://192.168.0.1/webpages/index.html#/login 
        - Password: aiuser@SHI
    - Open NoMachine --> Choose dog (Pumbaa, Linux NX or Timon, Linux NX) --> enter system user and password: hiwonder 
    - Open first terminal in NoMachine, paste command: 
    sudo fuser -k 9090/tcp
    roslaunch rosbridge_server rosbridge_websocket.launch
    - Open second terminal:
    sudo systemctl stop start_app_node.service
    roslaunch pug_control pug_control.launch
    - To start another dog, open a new NoMachine terminal for that dog and repeat commands.  

3. Clone into VS Code repository:
    - Enter in terminal:
    git clone https://github.com/sameera-velicheti/RoboticDogs.git

    - Open RoboticDogs project in VS Code
    - Make sure virtual environment is activated:
    python3 -m venv venv
    source venv/bin/activate
    - Run "python3 app.py"
    - Open browser and go to: http://127.0.0.1:5000


UI User Guide:
Overview
- The NemoClaw interface (titled "Agentic Paw Patrol") has three sections:

- Left sidebar — sample commands and system notes (max duration, capture interval, turn timing)

- Center panel — command inputs for each dog and the SEND ALL / STOP ALL controls

- Right panel — tabbed image and compliance report viewer, one tab per dog

Sending Commands

- Each dog has its own input field, labeled with its name (e.g. "Pumbaa," "Timon").

- To command one dog:

- Type a natural language instruction in that dog's input field (e.g. "walk forward for 10 seconds")
Click the SEND button next to that field

- To command both dogs simultaneously:

- Type an instruction into both input fields (they can be different commands)
Click SEND ALL — both dogs execute their instructions at the same time, independently

- Example commands (also available as clickable buttons in the sidebar):

walk forward for 12 seconds

walk forward for 5 seconds, then turn left for 2 seconds

turn left for 1 second then turn right for 1 second

walk backwards for 5 seconds

Stopping a Dog

- Type "stop" into that dog's input field and click SEND, or click STOP ALL to halt both dogs immediately regardless of what they're doing.

- During a Walk

- Each dog captures an image automatically every 2 seconds.

- LiDAR checks for obstacles continuously. If something is detected within the safe distance, the dog will attempt to turn and route around it. If fully blocked, it will stop and wait for a new command.

- Progress and status updates stream live in the center panel under that dog's execution log.

Reviewing Captured Images
- Click the tab for the dog whose images you want to view (e.g. "Pumbaa" or "Timon") in the right panel
- Each captured image appears with a timestamp
- Click ANALYZE on any image to run a compliance check — NIM reviews the image for safety hazards and returns findings with severity ratings (PASS / WARNING / FAIL)
- Click CLEAR to remove an image from the panel
System Notes (reference, shown in sidebar)



Default duration (if unspecified): 3 seconds

Image capture interval during walk: every 2 seconds

90° turn takes approximately 4.5 seconds

Troubleshooting Quick Reference

- "Could not connect to robot" in UI — Confirm rosbridge is running on that dog; confirm IP in DOG_IPS is current

- "No LiDAR scan available" repeatedly — Run rostopic hz /scan on that dog; restart pug_bringup.service if silent

- NoMachine can't reach a dog — Check for HW-xxxxxxxx fallback hotspot; restart hw_wifi.service if found

- NIM not responding — Confirm container is running; test with curl http://localhost:8000/v1/models

- Dog moves but images don't appear — Confirm app.py terminal has no errors; check /captures folder permissions

