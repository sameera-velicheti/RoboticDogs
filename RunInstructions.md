RUNNING PAW PATROL FROM UI - WITH WAYPOINTS!
Dogs: Pumbaa = hiwonder@192.168.0.60 · Timon = hiwonder@192.168.0.85
Dogs password: hiwonder
 -Make sure dogs are charged and powered on (should beep)
 -TP-Link router is on and laptop is connected to the network
 - MAKE SURE DOG IS AT STARTING POSITION, FACING THE CORRECT WAY

 In Terminal: Log into dogs
 For Pumbaa:
 ssh hiwonder@192.168.0.60
 For Timon: 
 ssh hiwonder@192.168.0.85
 password: hiwonder
 
 Run:
 sudo systemctl stop pug_bringup.service
pkill -f roslaunch; pkill -f rosmaster; sleep 5
sudo timedatectl set-timezone America/New_York
date

Check date/time, then run: 
nohup roslaunch pug_navigation patrol.launch map:=datacenter_01 > ~/patrol.log 2>&1 &

Wait 30 seconds, then run: 
rosnode list | grep -E "move_base|amcl|rosbridge"

Make sure you see: 
/amcl, /move_base_node, /rosbridge_websocket

 Open VS Code --> File --> Open Folder --> ~/Downloads/RoboticDogs
 In VS Code terminal, run: 
source ~/pawpatrol-venv/bin/activate
python3 app.py

Open web browser to http://localhost:5000
 - In the route dropdown, choose Data Center Left Aisle
 - Press Patrol Pumbaa or Patrol Timon
 - Let dog complete route or hit STOP ALL to restart