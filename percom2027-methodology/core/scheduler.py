class Scheduler:
    def __init__(self, alpha=0.6, threshold=0.7):
        self.alpha = alpha
        self.threshold = threshold

    def compute_reliability(self, activity_score, motion_score):
        reliability = (
            self.alpha * float(activity_score)
            + (1 - self.alpha) * float(motion_score)
        )
        reliability = min(1.0, max(0.0, reliability))
        return round(reliability, 2)

    def activate(self, reliability):
        return float(reliability) > self.threshold
