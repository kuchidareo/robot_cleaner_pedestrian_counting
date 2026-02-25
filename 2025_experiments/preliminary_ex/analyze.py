import pandas as pd
import json
import numpy as np


sensor_file = 'sensor_data/aggregated_sensor_data.csv'
annotation_file = 'annotation/aggregated_annotation.csv'
config_file = 'annotation/ex_duration_config.json'

sensor_data = pd.read_csv(sensor_file)
sensor_data = sensor_data.rename(columns={'time': 'timestamp'})
annotation_data = pd.read_csv(annotation_file)
annotation_data['timestamp'] = annotation_data['timestamp']
config_data = json.load(open(config_file))

# Merging annotation events into sensor data at nearest timestamps
def merge_data(sensor_df, annotation_df, config_list):
    sensor_df['timestamp'] = pd.to_datetime(sensor_df['timestamp'], unit='ns')
    annotation_df['timestamp'] = pd.to_datetime(annotation_df['timestamp'], unit='s')

    # Create a new event column initialized with NaN
    sensor_df['event'] = None
    sensor_df['is_turning'] = False
    
    # Find the nearest timestamp in sensor_df for each annotation event and assign the event label
    for _, row in annotation_df.iterrows():
        nearest_idx = (sensor_df['timestamp'] - row['timestamp']).abs().idxmin()
        sensor_df.at[nearest_idx, 'event'] = row['event']
    
    # Mark is_turning as True for rows between 'start' and 'end'
    turning_active = False
    for idx, row in sensor_df.iterrows():
        if row['event'] == 'start':
            turning_active = True
        if turning_active:
            sensor_df.at[idx, 'is_turning'] = True
        if row['event'] == 'end':
            turning_active = False
    
    # Adding experiment configuration details dynamically based on timestamp
    sensor_df['num_obstacles'] = None
    sensor_df['trial'] = None
    
    for config in config_list:
        start_time = pd.to_datetime(config['experiment_start'], unit='s')
        end_time = pd.to_datetime(config['experiment_end'], unit='s')
        mask = (sensor_df['timestamp'] >= start_time) & (sensor_df['timestamp'] <= end_time)
        sensor_df.loc[mask, 'num_obstacles'] = config['num_obstacles']
        sensor_df.loc[mask, 'trial'] = config['trial']
    
    return sensor_df

def calculate_turning_activity_stats(merged_df):
    activity_durations = []
    
    for (num_obstacles, trial), group in merged_df.groupby(['num_obstacles', 'trial']):
        start_times = group[group['event'] == 'start']['timestamp'].values
        end_times = group[group['event'] == 'end']['timestamp'].values
        
        assert len(start_times) == len(end_times)
        total_turning_duration = sum((pd.to_datetime(end_times) - pd.to_datetime(start_times)).total_seconds())

        activity_durations.append({
            'num_obstacles': num_obstacles, 
            'trial': trial,
            'total_turning_duration': total_turning_duration,
        })
    
    activity_df = pd.DataFrame(activity_durations)
    stats = activity_df.groupby('num_obstacles')['total_turning_duration'].agg(['mean', 'std']).reset_index()
    stats.rename(columns={'mean': 'mean_total_turning_duration', 'std': 'std_total_turning_duration'}, inplace=True)
    
    return activity_df, stats

def find_turning_threshold(merged_df, time_window='1s'):
    """
    This function calculates the average of the gyroscope's z-axis angular velocity for each window,
    and finds the threshold value that best matches the annotation using a simple search.
    It outputs the threshold value and its classification accuracy, and returns the threshold value.
    """

    merged_df['window_start'] = merged_df['timestamp'].dt.floor(time_window)
    
    agg_df = merged_df.groupby('window_start').agg(
        window_gyroscope_z=('gyroscope_z', 'mean'),
        window_is_turning=('is_turning', lambda x: x.any())
    )
    
    X = agg_df['window_gyroscope_z'].values
    y = agg_df['window_is_turning'].astype(int).values
    
    thresholds = np.linspace(X.min(), X.max(), num=10000)
    best_threshold = None
    best_accuracy = -np.inf
    
    for thresh in thresholds:
        preds = (X >= thresh).astype(int)
        accuracy = np.mean(preds == y)
        if accuracy > best_accuracy:
            best_accuracy = accuracy
            best_threshold = thresh
            
    print("Best threshold found: {:.4f} with accuracy: {:.2f}%".format(best_threshold, best_accuracy * 100))

    agg_df['window_is_turning_pred'] = agg_df['window_gyroscope_z'] >= best_threshold
    new_df = merged_df.merge(agg_df, left_on='window_start', right_index=True, how='left')
    new_df = new_df[['timestamp', 'gyroscope_x', 'gyroscope_y', 'gyroscope_z', 'gyroscope_norm', 'is_turning', 'window_gyroscope_norm', 'window_is_turning', 'window_is_turning_pred', 'num_obstacles', 'trial']]
    
    return best_threshold, new_df


def main():
    merged_df = merge_data(sensor_data, annotation_data, config_data)
    print("Merged Data Preview:")
    print(merged_df.columns)
    print(merged_df.head())
    
    # activity_df, activity_stats = calculate_turning_activity_stats(merged_df)
    # print("Turning Activity Statistics by num_obstacles:")
    # print(activity_stats)
    # activity_df.to_csv('activity_duration.csv', index=False)

    # 1s, thresh = 0.0338 -> acc. 90.55%
    time_window = '1s'
    best_threshold, prediction_df = find_turning_threshold(merged_df, time_window)
    print(prediction_df.columns)
    print(prediction_df.head())
    prediction_df.to_csv('prediction.csv', index=False)

if __name__ == "__main__":
    main()
