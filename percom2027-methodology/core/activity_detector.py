import math


class ActivityDetector:
    def __init__(self, distance_threshold=10):
        self.distance_threshold = distance_threshold

    @staticmethod
    def _is_missing(value) -> bool:
        try:
            return value is None or math.isnan(float(value))
        except (TypeError, ValueError):
            return value is None

    @staticmethod
    def _pir_active(value) -> bool:
        if ActivityDetector._is_missing(value):
            return False
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "yes", "y"}:
                return True
            if normalized in {"false", "no", "n", ""}:
                return False
        try:
            return float(value) > 0
        except (TypeError, ValueError):
            return bool(value)

    def detect(self, pir_detected, current_distance, previous_distance):
        current_missing = self._is_missing(current_distance)
        previous_missing = self._is_missing(previous_distance)

        if current_missing and previous_missing:
            distance_activity = False
        else:
            if current_missing:
                current_distance = previous_distance
            if previous_missing:
                previous_distance = current_distance
            distance_change = abs(float(current_distance) - float(previous_distance))
            distance_activity = distance_change > self.distance_threshold

        activity = self._pir_active(pir_detected) or distance_activity
        return int(activity)
