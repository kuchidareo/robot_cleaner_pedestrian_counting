import matplotlib.pyplot as plt
from matplotlib.ticker import FormatStrFormatter
import seaborn as sns
import pandas as pd
import numpy as np

def plot_turning_activity_distribution(activity_df):
    box_edge_color = 'black'
    box_line_width = 1.5
    box_palette = ["#f2f3ae","#edd382","#fc9e4f","#f4442e"]
    xlabel_fontsize = 14
    ylabel_fontsize = 14
    xticks_fontsize = 12
    yticks_fontsize = 12

    plt.figure(figsize=(6, 5))
    
    sns.boxplot(x='num_obstacles', y='total_turning_duration', data=activity_df, 
                palette=box_palette, boxprops={'edgecolor': box_edge_color, 'linewidth': box_line_width})
    
    # Customizing labels and title
    plt.xlabel('Number of Obstacles', fontsize=xlabel_fontsize)
    plt.ylabel('Turning Activity Duration (s)', fontsize=ylabel_fontsize)
    # plt.title('Distribution of Turning Activity Duration by Number of Obstacles', fontsize=16, fontweight='bold')
    
    # Adjust tick font size
    plt.xticks(fontsize=xticks_fontsize)
    plt.yticks(fontsize=yticks_fontsize)

    plt.ylim(0, 300)
    plt.savefig('figures/turning_activity_duration_boxplot.png')
    plt.show()

def plot_opportunistic_measurable_time(activity_df):

    measurable_color = "#DB5461"
    turning_color = "#DBF1FA"
    bar_edge_color = '#3F3F3F'
    bar_line_width = 0
    errorbar_color = '#3F3F3F'
    errorbar_width = 1.5
    errorbar_capsize = 2
    bar_width = 0.65
    
    xlabel_fontsize = 14
    ylabel_fontsize = 14
    xticks_fontsize = 12
    yticks_fontsize = 12
    legend_fontsize = 12
    
    # Compute measurable time
    activity_df['measurable_time'] = 300 - activity_df['total_turning_duration']
    
    # Group by num_obstacles and compute mean and std
    grouped_df = activity_df.groupby('num_obstacles').agg(
        measurable_time_mean=('measurable_time', 'mean'),
        measurable_time_std=('measurable_time', 'std'),
        turning_time_mean=('total_turning_duration', 'mean')
    ).reset_index()

    # Filter for specific obstacles [1, 2, 4, 8]
    grouped_df = grouped_df[grouped_df['num_obstacles'].isin([1, 2, 4, 8])]

    plt.figure(figsize=(6, 5))

    # Create evenly spaced x-positions for bars
    x_positions = np.arange(len(grouped_df))

    # Plot measurable time (mean values)
    plt.bar(x_positions, grouped_df['measurable_time_mean'], color=measurable_color, label='Measurable Time', edgecolor=bar_edge_color, linewidth=bar_line_width, width=bar_width)

    # Plot turning activity time (mean values) stacked on measurable time
    plt.bar(x_positions, grouped_df['turning_time_mean'], bottom=grouped_df['measurable_time_mean'], 
            color=turning_color, label='Turning Activity Time', edgecolor=bar_edge_color, linewidth=bar_line_width, width=bar_width)

    # Add standard deviation as error bars on measurable time bars
    plt.errorbar(x_positions, grouped_df['measurable_time_mean'], 
                 yerr=grouped_df['measurable_time_std'], fmt='none', color=errorbar_color, capsize=errorbar_capsize, capthick=errorbar_width, linewidth=errorbar_width)

    # Labels and titles
    plt.xlabel('Number of Obstacles', fontsize=xlabel_fontsize)
    plt.ylabel('Duration (s)', fontsize=ylabel_fontsize)
    
    # Set x-axis labels correctly
    plt.xticks(x_positions, grouped_df['num_obstacles'], fontsize=xticks_fontsize)
    
    plt.yticks(fontsize=yticks_fontsize)
    plt.ylim(0, 300)  # Experiment time is always 300 sec
    # plt.title('Effect of Obstacles on Measurable Time & Turning Activity', fontsize=14, fontweight='bold')

    # Add legend
    plt.legend(loc='upper right', fontsize=legend_fontsize)

    plt.savefig('figures/obstacles_measurable_time.png')
    plt.show()

def plot_overlaid_signal(prediction_df):
    num_obstacles = 1
    trial = 2
    threshold = 0.0338

    line_color = '#3F3F3F'
    line_width = 2
    line_alpha = 1.0
    gt_color = '#C2E8F7'
    gt_alpha = 1.0
    pred_color = '#FFE2BB'
    pred_alpha = 1.0
    threshold_color = '#CA2E55'
    threshold_alpha = 1.0
    threshold_linewidth = 2
    xlabel_fontsize = 14
    ylabel_fontsize = 14
    xtick_fontsize = 12
    ytick_fontsize = 12
    legend_label_fontsize = 12
    
    prediction_df = prediction_df[(prediction_df['num_obstacles'] == num_obstacles) & (prediction_df['trial'] == trial)]
    prediction_df["timestamp"] = pd.to_datetime(prediction_df["timestamp"])
    prediction_df["elapsed_time"] = (prediction_df["timestamp"] - prediction_df["timestamp"].iloc[0]).dt.total_seconds()

    def get_regions(elapsed_time_series, bool_series):
        regions = []
        in_region = False
        start = None
        for t, val in zip(elapsed_time_series, bool_series):
            if val and not in_region:
                in_region = True
                start = t
            elif not val and in_region:
                end = t
                regions.append((start, end))
                in_region = False
        # 最後まで True が続いていた場合
        if in_region:
            regions.append((start, elapsed_time_series.iloc[-1]))
        return regions
    
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 5), sharex=True)
    plt.subplots_adjust(hspace=0.05)

    # --- Upper Figure: Ground Truth Overlay ---
    ax1.plot(prediction_df["elapsed_time"], prediction_df['window_gyroscope_norm'], label='Gyro z-axis', color=line_color, alpha=line_alpha, lw=line_width)
    
    # Ground truth regions
    gt_regions = get_regions(prediction_df["elapsed_time"], prediction_df['window_is_turning'])
    for region in gt_regions:
        ax1.axvspan(region[0], region[1], color=gt_color, alpha=gt_alpha, label='Ground Truth Turning')
    
    # ax1.set_title('Gyro Norm with Ground Truth Overlay')
    # ax1.set_xlabel('Elapsed Time (s)')
    ax1.set_xticklabels(ax1.get_xticks(), fontsize=xtick_fontsize)
    ax1.set_yticklabels(ax1.get_yticks(), fontsize=ytick_fontsize)
    ax1.xaxis.set_major_formatter(FormatStrFormatter('%.0f'))
    ax1.yaxis.set_major_formatter(FormatStrFormatter('%.1f'))
    ax1.set_ylabel('Gyro z-axis', fontsize=ylabel_fontsize)
    # ax1.axhline(threshold, color=threshold_color, alpha=threshold_alpha, lw=threshold_linewidth, ls='-')
    
    # 重複した凡例項目を整理
    handles, labels = ax1.get_legend_handles_labels()
    unique = {}
    for h, l in zip(handles, labels):
        if l not in unique:
            unique[l] = h
    ax1.legend(unique.values(), unique.keys(), loc='upper right', fontsize=legend_label_fontsize)

    # --- Lower Figure: Prediction Overlay ---
    ax2.plot(prediction_df["elapsed_time"], prediction_df['window_gyroscope_norm'], label='Gyro z-axis', color=line_color, alpha=line_alpha, lw=line_width)
    
    # Prediction regions
    pred_regions = get_regions(prediction_df["elapsed_time"], prediction_df['window_is_turning_pred'])
    for region in pred_regions:
        ax2.axvspan(region[0], region[1], color=pred_color, alpha=pred_alpha, label='Prediction Turning')
    
    # ax2.set_title('Gyro Norm with Prediction Overlay')
    ax2.set_xticklabels(ax2.get_xticks(), fontsize=xtick_fontsize)
    ax2.set_yticklabels(ax2.get_yticks(), fontsize=ytick_fontsize)
    ax2.xaxis.set_major_formatter(FormatStrFormatter('%.0f'))
    ax2.yaxis.set_major_formatter(FormatStrFormatter('%.1f'))
    ax2.set_xlabel('Elapsed Time (s)', fontsize=xlabel_fontsize)
    ax2.set_ylabel('Gyro z-axis', fontsize=ylabel_fontsize)
    ax2.axhline(threshold, color=threshold_color, alpha=threshold_alpha, lw=threshold_linewidth, ls='-', label=f'Threshold={threshold}')
    
    handles, labels = ax2.get_legend_handles_labels()
    unique = {}
    for h, l in zip(handles, labels):
        if l not in unique:
            unique[l] = h
    ax2.legend(unique.values(), unique.keys(), loc='upper right', fontsize=legend_label_fontsize)
    plt.savefig('figures/gyronorm_with_pred_overlay_v2.png')
    plt.show()

def main():
    activity_df = pd.read_csv('log_for_plot/activity_duration.csv')
    prediction_df = pd.read_csv('log_for_plot/prediction.csv')
    # plot_turning_activity_distribution(activity_df)
    # plot_opportunistic_measurable_time(activity_df)
    plot_overlaid_signal(prediction_df)

if __name__ == "__main__":
    main()