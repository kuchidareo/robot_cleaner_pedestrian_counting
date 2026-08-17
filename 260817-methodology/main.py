import argparse
from pathlib import Path

from camera_aggregation import run_camera_aggregation
from camera_fusion import run_camera_fusion
from config import get_config
from preprocessing import run_preprocessing
from radiant_temperature import run_radiant_temperature
from spatial_reconstruction import run_spatial_reconstruction


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the RoombaSense thermal-field pipeline.")
    parser.add_argument(
        "--input-dir",
        required=True,
        help="Recording directory containing main.csv and thermal2.csv..thermal4.csv",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_dir = Path(args.input_dir).expanduser().resolve()
    if not input_dir.is_dir():
        raise FileNotFoundError(f"input directory not found: {input_dir}")

    config = get_config()
    output_dir = config.output_root / input_dir.name
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"Input:  {input_dir}")
    print(f"Output: {output_dir}")

    print("\n[1/5] Sample preprocessing")
    cameras = run_preprocessing(input_dir, output_dir, config)

    print("\n[2/5] Per-camera temperature aggregation")
    aggregated = run_camera_aggregation(cameras, output_dir, config)

    print("\n[3/5] Multi-camera fusion")
    fused = run_camera_fusion(aggregated, output_dir, config)
    if fused.empty:
        raise ValueError("no four-camera samples could be synchronized")

    print("\n[4/5] Radiant-temperature estimation")
    radiant = run_radiant_temperature(fused, input_dir, output_dir, config)

    print("\n[5/5] Spatial field reconstruction")
    field = run_spatial_reconstruction(radiant, input_dir, output_dir, config)
    if field is None:
        print("  skipped: localization.csv is unavailable or insufficient")

    print(f"\nDone. Results saved to {output_dir}")


if __name__ == "__main__":
    main()
