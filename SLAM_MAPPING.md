# SLAM Mapping Guide - Gmapping on ROSPug

How to build a 2D map of the ops center with the Gmapping on a HiWonder ROSPug. The saved map is a foundation for waypoint-based patrol routes.

All commands run **on the dog's Jetson**, in a terminal opened through NoMachine. Map files are saved on the dog in the 'pug_slam/maps' folder.

---

## BEFORE STARTING

- [] Dog is **fully charged**
- [] Ops center is clear of people and obstacles (they will then show up as ghost obstacles)
- [] Wireless controller is charged, and its USB Reciever is plugged into the dog
- [] Starting spot is **marked on the floor with tape**, with the facing direction noted - this will be known as the start position for navigating later
- [] Dog is place at the starting spot, **facing a straight wall** so that the dog's Lidar can scan as much points as possible

## CHECK IF THE CONTROLLER IS WIRED INTO THE MAPPING LAUNCH FILE

```bash
roscat pug_slam gmapping.launch | grep -iE "joy|teleop|handle"
```

- If it shows a joystick node: the controller works during mapping
- If it shows nothing, use keyboard control instead
 
---

## Terminal Layout

Use **one terminal window with three tabs**.

---

# Mapping procedure

### 1. Stop the auto-start service (tab 1)

```bash
sudo systemctl stop pug_bringup.service
```

### 2. Start Gmapping (tab 2)
```bash
roslaunch pug_slam gmapping.launch
```

### 3. Start RViz (tab 3)
```bash
roslaunch pug_slam rviz_slam.launch
```

RViz shows the map building live

### 4. Verify the Lidar is sending data (tab 1)

```bash
rostopic hz /scan
```

We should see a steady publishing rate. Press 'CCtrl+C' to stop the check

### 5. Drive the closed loop
- Move slowly
- Drive in staright lines as much as possible to minimize rotations
- Turn gently and pause briefly at corners
- Finish the loop back at the exact taped starting spot


### 6. Save the map
Save while Gmapping is still running. map_saver copies the first map from the live Gmapping process. If you 'Ctrl+C' Gmapping first, the map is lost.

```bash
roscd pug_slam/maps
rosrun map_server map_saver -f map_01
ls
```

### 7. Stop mapping
Press 'Ctrl+C' in tab 2 and tab 3.

### 8. Restart normal operations (tab 1)
```bash
sudo systemctl restart pug_bringup.service
```

