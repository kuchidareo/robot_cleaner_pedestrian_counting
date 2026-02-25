import pandas as pd
import json

pir_distance_sensor_file = 'pir_distance_sensor_data/AggregatedData.csv'
gyro_sensor_file = 'gyro_sensor_data/aggregated_sensor_data.csv'
annotation_file = 'annotation/aggregated_annotation.csv'
config_file = 'annotation/ex_duration_config.json'

pir_distance_sensor_data = pd.read_csv(pir_distance_sensor_file)
gyro_sensor_data = pd.read_csv(gyro_sensor_file)
gyro_sensor_data = gyro_sensor_data.rename(columns={'time': 'timestamp'})
annotation_data = pd.read_csv(annotation_file)
annotation_data['timestamp'] = annotation_data['timestamp']
config_data = json.load(open(config_file))


def merge_data(pir_distance_sensor_df, gyro_sensor_df, annotation_df, config_list):
    # Convert timestamps to datetime objects
    pir_distance_sensor_df['timestamp'] = pd.to_datetime(pir_distance_sensor_df['timestamp'])
    gyro_sensor_df['timestamp'] = pd.to_datetime(gyro_sensor_df['timestamp'], unit='ns')
    annotation_df['timestamp'] = pd.to_datetime(annotation_df['timestamp'], unit='s')

    # Create new columns for event and turning flags
    gyro_sensor_df['event'] = None
    gyro_sensor_df['is_turning'] = False

    # Merge annotation events into gyro data (assign nearest timestamp)
    for _, row in annotation_df.iterrows():
        nearest_idx = (gyro_sensor_df['timestamp'] - row['timestamp']).abs().idxmin()
        gyro_sensor_df.at[nearest_idx, 'event'] = row['event']
        gyro_sensor_df.at[nearest_idx, 'human_id'] = row['human_id']

    # Merge PIR and distance sensor data into gyro data (assign nearest timestamp)
    for _, row in pir_distance_sensor_df.iterrows():
        nearest_idx = (gyro_sensor_df['timestamp'] - row['timestamp']).abs().idxmin()
        gyro_sensor_df.at[nearest_idx, 'PIRvalue'] = row['PIRvalue']
        gyro_sensor_df.at[nearest_idx, 'distance'] = row['distance']

    # Add experiment configuration details based on timestamp
    gyro_sensor_df['num_obstacles'] = None
    gyro_sensor_df['trial'] = None
    for config in config_list:
        start_time = pd.to_datetime(config['experiment_start'], unit='s')
        end_time = pd.to_datetime(config['experiment_end'], unit='s')
        mask = (gyro_sensor_df['timestamp'] >= start_time) & (gyro_sensor_df['timestamp'] <= end_time)
        gyro_sensor_df.loc[mask, 'num_obstacles'] = config['num_obstacles']
        gyro_sensor_df.loc[mask, 'trial'] = config['trial']
    
    return gyro_sensor_df


def add_is_turning_prediction(df, threshold=0.0338):
    """
    Compute the turning prediction based on a 1-second rolling average of gyroscope_z.
    A new column 'is_turning_pred' is added to the DataFrame.
    """
    df = df.sort_values('timestamp')
    df = df.set_index('timestamp')
    
    # Calculate the 1-second rolling average of gyroscope_z
    df['rolling_gyroscope_z'] = df['gyroscope_z'].rolling('1s').mean()
    
    # Mark turning events where the absolute rolling average exceeds the threshold
    df['is_turning_pred'] = df['rolling_gyroscope_z'].abs() > threshold
    
    df = df.reset_index()
    return df


def compute_human_collision_pred(df, time_window='1s'):
    """
    Encapsulated function to compute human collision predictions.
    
    For each turning start event (where is_turning_pred transitions from False to True),
    this function checks within a specified time window (before and after the turning start)
    for any instance where PIRvalue equals 1.
    
    A new column 'human_collision_pred' is added with True if a collision is detected.
    
    Parameters:
        df: DataFrame containing sensor data and turning predictions.
        time_window: Time window (as a string, e.g., '1s') to check before and after the turning start.
    """
    # Ensure the DataFrame is sorted by timestamp
    df = df.sort_values('timestamp')
    
    # Identify turning start events by comparing with previous row
    df['prev_turning'] = df['is_turning_pred'].shift(1, fill_value=False)
    df['is_start_turning'] = df['is_turning_pred'] & (~df['prev_turning'])
    
    # Initialize the human collision prediction column as False
    df['human_collision_pred'] = False

    # For each turning start event, check for a PIRvalue of 1 within the specified time window
    for idx, row in df.iterrows():
        if row['is_start_turning']:
            turning_time = row['timestamp']
            window_mask = (df['timestamp'] >= turning_time - pd.Timedelta(time_window)) & \
                          (df['timestamp'] <= turning_time + pd.Timedelta(time_window))
            if (df.loc[window_mask, 'PIRvalue'] == 1).any():
                df.at[idx, 'human_collision_pred'] = True
            else:
                df.at[idx, 'human_collision_pred'] = False
    
    # Optionally, drop temporary columns used in computation
    df = df.drop(columns=['prev_turning'])
    return df


def evaluate_performance(df):
    """
    Evaluate the detection performance by comparing the predicted collisions to the ground truth.
    
    Ground truth collisions are identified by rows where 'event' == "collision".
    For each ground truth collision, a ±1-second window is checked for a predicted collision.
    Similarly, for each predicted collision, a ±1-second window is checked for a ground truth collision.
    Precision, recall, and F1 score are computed and printed.
    """
    gt_events = df[df['event'] == 'collision']
    pred_events = df[df['human_collision_pred'] == True]

    true_positive_count = 0
    false_negative_count = 0

    # For each ground truth collision, check the ±1 second window for a prediction.
    for ts in gt_events['timestamp']:
        window_mask = (df['timestamp'] >= ts - pd.Timedelta(seconds=1)) & \
                      (df['timestamp'] <= ts + pd.Timedelta(seconds=1))
        if df.loc[window_mask, 'human_collision_pred'].any():
            true_positive_count += 1
        else:
            false_negative_count += 1

    false_positive_count = 0
    # For each predicted collision, check the ±1 second window for a ground truth collision.
    for ts in pred_events['timestamp']:
        window_mask = (df['timestamp'] >= ts - pd.Timedelta(seconds=1)) & \
                      (df['timestamp'] <= ts + pd.Timedelta(seconds=1))
        if not (df.loc[window_mask, 'event'] == 'collision').any():
            false_positive_count += 1

    precision = true_positive_count / (true_positive_count + false_positive_count) if (true_positive_count + false_positive_count) > 0 else 0
    recall = true_positive_count / (true_positive_count + false_negative_count) if (true_positive_count + false_negative_count) > 0 else 0
    f1_score = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0

    print("Evaluation Metrics:")
    print("True Positive:", true_positive_count)
    print("False Negative (ground truth collisions missed):", false_negative_count)
    print("False Positive (false collision predictions):", false_positive_count)
    print("Precision:", precision)
    print("Recall:", recall)
    print("F1 Score:", f1_score)


def main():
    merged_df = merge_data(pir_distance_sensor_data, gyro_sensor_data, annotation_data, config_data)
    print("Merged Data Preview:")
    print(merged_df.columns)
    print(merged_df.head())

    # Add turning predictions based on the gyroscope data.
    merged_df = add_is_turning_prediction(merged_df)

    # Compute human collision prediction using the encapsulated function.
    merged_df = compute_human_collision_pred(merged_df, time_window='1s')

    # Evaluate the performance of the collision detection.
    evaluate_performance(merged_df)


if __name__ == "__main__":
    main()