import pandas as pd
import matplotlib.pyplot as plt
from color_config import BLACK_COLOR


def plot_window(df, start_time, end_time, output_name):
    window_df = df[(df["timestamp"] >= start_time) & (df["timestamp"] <= end_time)].copy()
    window_df["elapsed_sec"] = (window_df["timestamp"] - start_time).dt.total_seconds()
    distance_df = window_df[window_df["distance"].notna()]
    pir_df = window_df[window_df["PIRvalue"].notna()]

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(3, 4), sharex=True)
    ax1.plot(pir_df["elapsed_sec"], pir_df["PIRvalue"], color=BLACK_COLOR, linewidth=2)
    ax1.scatter(pir_df["elapsed_sec"], pir_df["PIRvalue"], s=18, label="PIRvalue", color=BLACK_COLOR)
    ax1.set_ylabel("PIR Value")
    ax1.set_yticks([0, 1], ["False", "True"])
    ax1.set_ylim(-0.1, 1.1)

    ax2.plot(distance_df["elapsed_sec"], distance_df["distance"], color=BLACK_COLOR, linewidth=2)
    ax2.scatter(distance_df["elapsed_sec"], distance_df["distance"], s=18, label="Distance", color=BLACK_COLOR)
    ax2.set_ylabel("Distance (cm)")
    ax2.set_yticks([0, 50, 100, 150, 200, 250])
    ax2.set_xticks([0, 5, 10], ["0", "5", "10"])
    ax2.set_xlabel("Time (s)")

    fig.tight_layout()
    fig.savefig(output_name, dpi=150)
    plt.close(fig)


def main():
    df = pd.read_csv("result_df.csv")
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df_new = pd.read_csv("new_result_df.csv")
    df_new["timestamp"] = pd.to_datetime(df_new["timestamp"])

    ranges = [
        (
            df,
            pd.to_datetime("2025-03-10 14:06:17"),
            pd.to_datetime("2025-03-10 14:06:27"),
            "11_sensor_max.png",
        ),
        (
            df,
            pd.to_datetime("2025-03-10 13:56:36"),
            pd.to_datetime("2025-03-10 13:56:49"),
            "11_approaching.png",
        ),
        (
            df_new,
            pd.to_datetime("2025-03-10 14:11:37"),
            pd.to_datetime("2025-03-10 14:11:47"),
            "12_pir_reduce_false_positive.png",
        ),
    ]

    for data, start_time, end_time, output_name in ranges:
        plot_window(data, start_time, end_time, output_name)


if __name__ == "__main__":
    main()
