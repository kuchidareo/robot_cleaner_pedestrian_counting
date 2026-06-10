import argparse
import os
from pathlib import Path

from analysis.availability_analysis import run_availability_analysis
from analysis.prediction_plot import save_prediction_plots
from analysis.score_plot import save_score_plots
from core.activity_detector import ActivityDetector
from core.data_loader import load_experiment_dataframe
from core.motion_estimator import MotionEstimator
from core.pedestrian_prediction import run_pedestrian_prediction
from core.scheduler import Scheduler


PROJECT_DIR = Path(__file__).resolve().parent


def parse_args():
    parser = argparse.ArgumentParser(description="Run the PerCom methodology pipeline.")
    parser.add_argument(
        "--data-dir",
        default="data/controlled_1person",
        help="Path to one experiment directory.",
    )
    return parser.parse_args()


def resolve_data_dir(data_dir: str) -> Path:
    requested = Path(data_dir)
    if requested.is_absolute():
        return requested
    if requested.exists():
        return requested.resolve()
    return (PROJECT_DIR / requested).resolve()


def main():
    args = parse_args()
    data_dir = resolve_data_dir(args.data_dir)
    experiment_name = os.path.basename(os.path.normpath(data_dir))
    output_dir = PROJECT_DIR / "figures" / experiment_name
    output_dir.mkdir(parents=True, exist_ok=True)

    print("loading data")
    data = load_experiment_dataframe(data_dir)
    print(f"number of loaded samples: {len(data)}")

    activity_detector = ActivityDetector()
    motion_estimator = MotionEstimator()
    scheduler = Scheduler()

    print("computing activity score")
    previous_distances = data["distance"].shift(1)
    data["activity_score"] = [
        activity_detector.detect(pir, current, previous)
        for pir, current, previous in zip(
            data["pir_detected"],
            data["distance"],
            previous_distances,
        )
    ]

    print("computing motion score")
    data["motion_score"] = data["gyro_z"].map(motion_estimator.estimate)

    print("computing reliability score")
    data["reliability_score"] = [
        scheduler.compute_reliability(activity, motion)
        for activity, motion in zip(data["activity_score"], data["motion_score"])
    ]
    data["available"] = data["reliability_score"].map(scheduler.activate)

    print("running availability analysis")
    run_availability_analysis(data)

    print("saving plots")
    save_score_plots(data, output_dir)

    print("saving processed dataframe")
    data.to_csv(output_dir / "processed_scores.csv", index=False)

    print("running pedestrian prediction")
    prediction_result = run_pedestrian_prediction(data_dir)
    prediction_output_dir = output_dir / "prediction"
    save_prediction_plots(
        prediction_result,
        data_dir,
        prediction_output_dir,
    )

    print("done")


if __name__ == "__main__":
    main()
