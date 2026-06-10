import math


class MotionEstimator:
    def __init__(self, gyro_max=2.0):
        self.gyro_max = gyro_max

    def estimate(self, gyro_z):
        try:
            gyro_value = float(gyro_z)
        except (TypeError, ValueError):
            gyro_value = 0.0

        if math.isnan(gyro_value):
            gyro_value = 0.0

        if self.gyro_max <= 0:
            raise ValueError("gyro_max must be greater than zero")

        motion_score = 1 - abs(gyro_value) / self.gyro_max
        motion_score = min(1.0, max(0.0, motion_score))
        return round(motion_score, 2)
