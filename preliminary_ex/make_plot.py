import matplotlib.pyplot as plt
import seaborn as sns
import pandas as pd

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


def plot_turning_info(prediction_df):
    prediction_df = prediction_df[(prediction_df["num_obstacles"] == 4) & (prediction_df["trial"] == 1)]
    x_axis = prediction_df.index
    
    # Boolean を 0/1 に変換
    window_is_turning = prediction_df['window_is_turning'].astype(int)
    window_is_turning_pred = prediction_df['window_is_turning_pred'].astype(int)
    
    # Figure を作成 (2段のサブプロット)
    fig, axes = plt.subplots(2, 1, figsize=(14, 8), sharex=True)
    
    # ① 上段: サンプルレベルの gyroscope_norm とウィンドウ平均の window_gyroscope_norm をプロット
    axes[0].plot(x_axis, prediction_df['gyroscope_norm'], label='Gyroscope Norm (sample)', color='tab:blue', alpha=0.6)
    axes[0].plot(x_axis, prediction_df['window_gyroscope_norm'], label='Window Gyroscope Norm (avg)', color='tab:orange', linewidth=2, linestyle='--')
    axes[0].set_ylabel('Gyroscope Norm')
    axes[0].legend(loc='upper right')
    axes[0].set_title('Gyroscope Norm vs. Window Gyroscope Norm')
    
    # ② 下段: 真の turning (window_is_turning) と予測 (window_is_turning_pred) をプロット
    axes[1].step(x_axis, window_is_turning, label='Window is Turning (annotation)', where='post', marker='o', color='tab:green')
    axes[1].step(x_axis, window_is_turning_pred, label='Window is Turning (prediction)', where='post', marker='x', color='tab:red')
    axes[1].set_ylabel('Turning Flag (0=False, 1=True)')
    axes[1].set_xlabel('Time')
    axes[1].legend(loc='upper right')
    axes[1].set_title('Turning State: Annotation vs. Prediction')
    
    plt.tight_layout()
    plt.show()

def main():
    activity_df = pd.read_csv('log_for_plot/activity_duration.csv')
    prediction_df = pd.read_csv('log_for_plot/prediction.csv')
    # plot_turning_activity_distribution(activity_df)
    plot_turning_info(prediction_df)

if __name__ == "__main__":
    main()