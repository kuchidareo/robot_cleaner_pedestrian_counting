# Experimental Procedures and Objectives

## 1. Overview

This experiment aims to evaluate collision events between a Roomba and standing humans by using multiple sensors mounted on the Roomba, including a gyroscope sensor, an ultrasonic distance sensor, and a PIR sensor. During the experiment, only the Roomba is in motion while the standing humans remain stationary. The timestamps of collisions and the corresponding human IDs are recorded.

## 2. Experimental Environment

### 2.1 Controlled Situation

- **Location:**  
  A room (approximately 3m × 5m) at the Delta Center of the University of Tartu.

- **Grid Division:**  
  The room is divided into 15 grids of 1m × 1m.

- **Obstacle Placement:**  
  Obstacles are configured in 4 patterns: 1, 2, 4, or 8 obstacles.  
  They are placed randomly among the 15 grids, with each obstacle positioned at the center of a grid.

- **Standing Human Placement:**  
  Four configurations are used: 1, 2, 3, or 4 persons.  
  Humans are placed randomly within the grids, with each person positioned at the center of a grid.

- **Roomba Placement:**  
  The starting point of the Roomba is set randomly, located at the center of a grid, with its initial direction aimed toward the center of the room.

- **Experimental Parameters:**  
  A total of 16 (4 × 4) parameter combinations are tested, with each combination repeated twice.

### 2.2 Wild Situation

- **Location:**  
  The experiment is conducted in an environment that is not a simple rectangular room but an enclosed area with various obstacles such as desks and chairs.

- **Standing Human Placement:**  
  The arrangement of standing humans is determined by a specific random method (details provided separately).

- **Experimental Repetitions:**  
  Five experiments are conducted for the configuration involving 4 standing humans.

## 3. Experimental Procedure

- **Duration:**  
  Each experiment runs for 5 minutes.

- **Subject Behavior:**  
  - Standing humans remain stationary throughout the experiment.  
  - Only the Roomba moves, and collisions with standing humans are recorded.

- **Data Collection:**  
  When a collision occurs, the experiment records the timestamp of the collision and the corresponding human ID.

## 4. Roomba Equipment

- **Installed Devices:**  
  - Smartphone (for collecting gyroscope sensor data)  
  - Ultrasonic Distance Sensor  
  - PIR Sensor  
  - Mobile battery (mounted on the top to supply power to the sensors)

## 5. Experimental Objectives

1. **Evaluation of Obstacle Impact:**  
   It is hypothesized that as the number of obstacles increases, the number of standing humans encountered within the experimental time frame will decrease due to the Roomba colliding with obstacles.  
   - Each collision is annotated with a human ID so that later, the distinct individuals encountered can be verified.  
   - Although the same person might be counted multiple times, it is assumed (as a premise for future work) that additional data from the individual's smartphone could eventually be used for identification.

2. **Validation of Collision Detection Accuracy:**  
   The experiment aims to demonstrate that by using an ultrasonic distance sensor, a PIR sensor, and a gyroscope sensor, it is possible to determine with a certain degree of accuracy whether the Roomba has collided with a human.