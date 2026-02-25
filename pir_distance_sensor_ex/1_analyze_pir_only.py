import os

import pandas as pd
import json
import plotly.express as px
import plotly.graph_objects as go
import numpy as np

# pir_distance_sensor_file = 'pir_distance_sensor_data/AggregatedData.csv'
# gyro_sensor_file = 'gyro_sensor_data/aggregated_sensor_data.csv'
# annotation_file = 'annotation/aggregated_annotation.csv'
# config_file = 'annotation/ex_duration_config.json'

# pir_distance_sensor_data = pd.read_csv(pir_distance_sensor_file)
# gyro_sensor_data = pd.read_csv(gyro_sensor_file)
# gyro_sensor_data = gyro_sensor_data.rename(columns={'time': 'timestamp'})
# annotation_data = pd.read_csv(annotation_file)
# annotation_data['timestamp'] = annotation_data['timestamp']
# config_data = json.load(open(config_file))


def merge_data(pir_distance_sensor_df, gyro_sensor_df, annotation_df, config_list):
    # Convert timestamps to datetime objects
    pir_distance_sensor_df['timestamp'] = pd.to_datetime(pir_distance_sensor_df['timestamp'])
    gyro_sensor_df['timestamp'] = pd.to_datetime(gyro_sensor_df['timestamp'], unit='ns')
    annotation_df['timestamp'] = pd.to_datetime(annotation_df['timestamp'], unit='s')

    # Create new columns for event and turning flags
    gyro_sensor_df['event'] = None

    # Merge annotation events into gyro data (assign nearest timestamp)
    for _, row in annotation_df.iterrows():
        nearest_idx = (gyro_sensor_df['timestamp'] - row['timestamp']).abs().idxmin()
        gyro_sensor_df.at[nearest_idx, 'event'] = row['event']
        gyro_sensor_df.at[nearest_idx, 'human_id'] = row['human_id']

    for _, row in pir_distance_sensor_df.iterrows():
        nearest_idx = (gyro_sensor_df['timestamp'] - row['timestamp']).abs().idxmin()
        gyro_sensor_df.at[nearest_idx, 'PIRvalue'] = row['PIRvalue']
        gyro_sensor_df.at[nearest_idx, 'distance'] = row['distance']

    # Add experiment configuration details based on timestamp
    gyro_sensor_df['experiment_id'] = None
    gyro_sensor_df['trial'] = None
    for config in config_list:
        start_time = pd.to_datetime(config['experiment_start'], unit='s')
        end_time = pd.to_datetime(config['experiment_end'], unit='s')
        mask = (gyro_sensor_df['timestamp'] >= start_time) & (gyro_sensor_df['timestamp'] <= end_time)
        gyro_sensor_df.loc[mask, 'experiment_id'] = config['experiment_id']
        gyro_sensor_df.loc[mask, 'trial'] = config['trial']

    gyro_sensor_df.sort_values('timestamp', inplace=True)

    return gyro_sensor_df


def add_turning_time_prediction(df, threshold=0.0338):
    """
    Compute the turning prediction based on a 1-second rolling average of gyroscope_z.
    Change the 'phase_pred' to 'turning_time'
    """
    df = df.sort_values('timestamp')
    df = df.set_index('timestamp')

    # Calculate the 1-second rolling average of gyroscope_z
    df['rolling_gyroscope_z'] = df['gyroscope_z'].rolling('1s').mean()

    # Mark turning events where the absolute rolling average exceeds the threshold
    df['phase_pred'] = None
    df['phase_pred'] = df['phase_pred'].astype(str)
    df.loc[df['rolling_gyroscope_z'].abs() > threshold, 'phase_pred'] = 'turning_time'

    df = df.reset_index()
    return df


def add_sensor_max_approach_time_prediction(df, sensor_threshold=230, tolerance=2):
    """
    sensor_max_time -> the time that the distance sensor values are the maximum(255).
    To predict this time, calculate the rolling distance. When it's the maximum, change 'phase_pred' to 'sensor_max_time'.
    approaching_time -> the time that the distance sensor values are decreasing.
    Compute the expected linearly decreasing distance and change 'distance_pred'.

    Hint: 'approaching_time' -> 'sensor_max_time' is not available.
    """

    df = df.sort_values('timestamp')
    df = df.set_index('timestamp')

    has_approached = False
    below_indices = []

    for i, row in df[df['distance'].notna()].iterrows():
        if row['phase_pred'] == 'turning_time':
            has_approached = False
            continue

        rd = row['distance']

        if has_approached:
            df.loc[i, 'phase_pred'] = 'approaching_time'
            continue

        # Before we've seen a clear decrease, allow sensor_max_time if the value is high.
        if rd >= sensor_threshold:
            below_indices = []
            df.loc[i, 'phase_pred'] = 'sensor_max_time'
        else:
            below_indices.append(i)

            if len(below_indices) > tolerance:
                df.loc[below_indices, 'phase_pred'] = 'approaching_time'
                has_approached = True
            else:
                df.loc[i, 'phase_pred'] = 'sensor_max_time'

    df['phase_pred'] = df['phase_pred'].replace("None", np.nan)
    df['phase_pred'] = df['phase_pred'].ffill()

    df = df.reset_index()

    return df


def add_pir_only_prediction(df, time_window='1s'):
    """
    PIR-only pedestrian detection.
    If PIRvalue == 1 within the time window, mark pedestrian_pred True.
    """
    df = df.sort_values('timestamp')
    df = df.set_index('timestamp')

    pir_hit = (df['PIRvalue'] == 1)
    df['pir_window_hit'] = pir_hit.rolling(time_window).max().fillna(0).astype(bool)

    df = df.reset_index()
    df['pedestrian_pred'] = df['pir_window_hit']
    df.loc[df['phase_pred'] == 'turning_time', 'pedestrian_pred'] = False

    return df


def visualize_phase_pred(df, experiment_id):
    """
    Visualize the phase predictions interactively using Plotly.
    """

    # Define colors for different phases
    phase_colors = {
        'sensor_max_time': 'lightcoral',
        'approaching_time': 'lightblue',
        'turning_time': 'white'
    }
    df = df[df['experiment_id'] == experiment_id]  # Filter data for a specific experiment
    collision_points = df[df['event'] == 'collision']
    prediction_points = df[df['pedestrian_pred'] == True]

    df = df[df['PIRvalue'].notna()]
    # Create an interactive line chart
    fig = px.scatter(df, x='timestamp', y='PIRvalue', title='PIR Value with Phase Annotations')
    fig.add_scatter(x=collision_points['timestamp'], y=[1.1] * len(collision_points), mode='markers', name='Pedestrian Crossed')
    fig.add_scatter(x=prediction_points['timestamp'], y=[1.2] * len(prediction_points), mode='markers', name='Pedestrian Prediction')
    fig.update_yaxes(tickmode='array', tickvals=[0, 1], ticktext=['False', 'True'], range=[-0.1, 1.3])

    # Add background colors for different phases
    prev_phase = None
    start_time = None

    for index, row in df.iterrows():
        phase = row['phase_pred']
        timestamp = row['timestamp']

        if prev_phase is None:
            prev_phase = phase
            start_time = timestamp
            continue

        if prev_phase != phase or index == df.index[-1]:  # Last row condition
            end_time = timestamp

            # Add vertical rectangle for phase
            fig.add_vrect(
                x0=start_time, x1=end_time,
                fillcolor=phase_colors.get(prev_phase, "gray"),
                opacity=0.3,
                layer="below",
                line_width=0,
            )

            prev_phase = phase
            start_time = end_time

    # Manually add legend items using scatter traces
    for phase, color in phase_colors.items():
        fig.add_trace(go.Scatter(
            x=[None], y=[None],  # Invisible points
            mode='markers',
            marker=dict(size=10, color=color),
            name=phase  # Legend label
        ))

    fig.update_xaxes(rangeslider_visible=True)  # Add a range slider for scrolling
    fig.show()


def remove_data_out_of_measurable_time(df, transition_window='3s'):
    """
    Remove data points that are within ±3 seconds of phase transitions.
    """
    df = df.sort_values('timestamp')

    # Identify phase transitions (where phase_pred changes)
    phase_changes = df['phase_pred'] != df['phase_pred'].shift()
    transition_timestamps = df[phase_changes]['timestamp']

    # Create a mask to identify rows to keep (outside transition windows)
    remove_mask = pd.Series(False, index=df.index)

    for ts in transition_timestamps:
        # Mark rows within transition window as False
        window_mask = (df['timestamp'] >= ts - pd.Timedelta(transition_window)) & \
                     (df['timestamp'] <= ts + pd.Timedelta(transition_window))
        remove_mask |= window_mask

    df.loc[remove_mask, 'event'] = None
    df.loc[remove_mask, 'pedestrian_pred'] = False

    df.loc[df['phase_pred'] == 'turning_time', 'event'] = None
    df.loc[df['phase_pred'] == 'turning_time', 'pedestrian_pred'] = False

    return df


def evaluate_performance(df, time_window='3s'):
    """
    Evaluate the detection performance by comparing the predicted collisions to the ground truth,
    separated by different phases (approaching_time, sensor_max_time).
    """
    metrics = {
        'approaching_time': {'tp': 0, 'fp': 0, 'fn': 0},
        'sensor_max_time': {'tp': 0, 'fp': 0, 'fn': 0}
    }

    for phase in ['approaching_time', 'sensor_max_time']:
        phase_df = df[df['phase_pred'] == phase]
        gt_events = phase_df[phase_df['event'] == 'collision']
        pred_events = phase_df[phase_df['pedestrian_pred'] == True]

        for ts in gt_events['timestamp']:
            window_mask = (phase_df['timestamp'] >= ts - pd.Timedelta(time_window)) & \
                         (phase_df['timestamp'] <= ts + pd.Timedelta(time_window))
            if phase_df.loc[window_mask, 'pedestrian_pred'].any():
                metrics[phase]['tp'] += 1
            else:
                metrics[phase]['fn'] += 1

        for ts in pred_events['timestamp']:
            window_mask = (phase_df['timestamp'] >= ts - pd.Timedelta(time_window)) & \
                         (phase_df['timestamp'] <= ts + pd.Timedelta(time_window))
            if not (phase_df.loc[window_mask, 'event'] == 'collision').any():
                metrics[phase]['fp'] += 1

    print("\nEvaluation Metrics by Phase:")
    print("-" * 30)

    for phase in metrics:
        tp = metrics[phase]['tp']
        fp = metrics[phase]['fp']
        fn = metrics[phase]['fn']

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0
        f1_score = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0

        print(f"\n{phase.upper()}:")
        print(f"True Positive: {tp}")
        print(f"False Positive: {fp}")
        print(f"False Negative: {fn}")
        print(f"Precision: {precision:.3f}")
        print(f"Recall: {recall:.3f}")
        print(f"F1 Score: {f1_score:.3f}")


def main():
    experiment_id = 2
    sensor_threshold = 230
    tolerance = 2

    if 'result_df.csv' in os.listdir():
        result_df = pd.read_csv('result_df.csv')
        result_df['timestamp'] = pd.to_datetime(result_df['timestamp'])
    else:
        if 'merged_df.csv' in os.listdir():
            merged_df = pd.read_csv('merged_df.csv')
            merged_df['timestamp'] = pd.to_datetime(merged_df['timestamp'])
        else:
            merged_df = merge_data(pir_distance_sensor_data, gyro_sensor_data, annotation_data, config_data)
            merged_df.to_csv("merged_df.csv", index=False)
        print("Merged Data Preview:")
        print(merged_df.columns)
        print(merged_df.head())

        # Add turning predictions based on the gyroscope data.
        merged_df = add_turning_time_prediction(merged_df)
        result_df = add_sensor_max_approach_time_prediction(merged_df, sensor_threshold, tolerance)

        result_df.to_csv("result_df.csv", index=False)

    print("visualizing...")
    result_df = add_pir_only_prediction(result_df, time_window='1s')

    # Remove pedestrian data on transition periods and 'turning_time'.
    result_df = remove_data_out_of_measurable_time(result_df, transition_window='0.5s')

    # Visualize
    visualize_phase_pred(result_df, experiment_id)
    evaluate_performance(result_df)


if __name__ == "__main__":
    main()
