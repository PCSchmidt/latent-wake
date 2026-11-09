# Post-hoc analysis of the test results (exploratory)

Computed after the single scoring from the saved scores; nothing was re-scored and the contract verdict is unchanged.

## Uncertainty: cluster bootstrap over 172 source vessels (200 draws)

| criterion                               |   difference |   ci_low |   ci_high |   margin |   share_of_draws_meeting_margin |   draws |
|:----------------------------------------|-------------:|---------:|----------:|---------:|--------------------------------:|--------:|
| behavioral_gain_over_kalman_auroc       |        0.07  |    0.032 |     0.115 |     0.1  |                           0.055 |     200 |
| fused_beats_kalman_auroc                |        0.019 |    0.009 |     0.028 |     0.03 |                           0.01  |     200 |
| fused_beats_jepa_auroc                  |        0.04  |    0.027 |     0.051 |     0.03 |                           0.925 |     200 |
| behavioral_gain_over_kalman_auprc       |        0.039 |   -0.013 |     0.091 |     0.05 |                           0.365 |     200 |
| fused_no_precision_loss_vs_kalman_auprc |       -0.061 |   -0.088 |     0.017 |     0    |                           0.11  |     200 |
| fused_beats_jepa_auprc                  |        0.117 |    0.09  |     0.148 |     0.03 |                           1     |     200 |

## Test false alarms by vessel (thresholds from validation, 1% budget)

| method   |   false_alarms |   vessels_alarming |   of_vessels |   top5_share |
|:---------|---------------:|-------------------:|-------------:|-------------:|
| physics  |            104 |                 25 |          157 |        0.712 |
| kalman   |            124 |                 22 |          157 |        0.815 |
| jepa-s0  |            273 |                 29 |          157 |        0.879 |
| fused-s0 |            224 |                 27 |          157 |        0.844 |
| jepa-s1  |            313 |                 29 |          157 |        0.885 |
| fused-s1 |            249 |                 26 |          157 |        0.831 |
| jepa-s2  |            278 |                 30 |          157 |        0.871 |
| fused-s2 |            237 |                 27 |          157 |        0.835 |
| raw-s0   |            145 |                 29 |          157 |        0.738 |
| raw-s1   |            144 |                 31 |          157 |        0.722 |
| raw-s2   |            140 |                 27 |          157 |        0.721 |

## Test false-alarm rate by stratum

| vessel_class   | under_way   |   n_normal |   physics |   kalman |   jepa-s0 |   fused-s0 |   jepa-s1 |   fused-s1 |   jepa-s2 |   fused-s2 |   raw-s0 |   raw-s1 |   raw-s2 |
|:---------------|:------------|-----------:|----------:|---------:|----------:|-----------:|----------:|-----------:|----------:|-----------:|---------:|---------:|---------:|
| unknown        | False       |         16 |    0      |   0      |    0      |     0      |    0      |     0      |    0      |     0      |   0      |   0      |   0      |
| unknown        | True        |         19 |    0      |   0      |    0      |     0      |    0      |     0      |    0      |     0      |   0      |   0      |   0      |
| cargo          | False       |        884 |    0.0011 |   0.0011 |    0.0882 |     0.0837 |    0.086  |     0.0848 |    0.0894 |     0.086  |   0.0057 |   0.0057 |   0.0057 |
| cargo          | True        |        222 |    0.009  |   0.0045 |    0.009  |     0.0045 |    0.009  |     0.0045 |    0.018  |     0.0045 |   0.0045 |   0.0045 |   0.0045 |
| tanker         | False       |         82 |    0      |   0.0122 |    0.0244 |     0.0122 |    0.0122 |     0.0122 |    0.0244 |     0      |   0      |   0      |   0      |
| tanker         | True        |          9 |    0      |   0      |    0      |     0      |    0      |     0      |    0      |     0      |   0      |   0      |   0      |
| passenger      | False       |        195 |    0      |   0      |    0      |     0      |    0      |     0      |    0      |     0      |   0      |   0      |   0      |
| passenger      | True        |         40 |    0      |   0      |    0      |     0      |    0      |     0      |    0      |     0      |   0      |   0      |   0      |
| fishing        | False       |        154 |    0.0065 |   0.0065 |    0.0455 |     0.013  |    0.3636 |     0.1623 |    0.0065 |     0.0065 |   0      |   0      |   0      |
| fishing        | True        |         89 |    0.4494 |   0.7528 |    0.8427 |     0.8539 |    0.8427 |     0.8539 |    0.8427 |     0.8539 |   0.8427 |   0.8427 |   0.8427 |
| tug_tow        | False       |       1653 |    0.0079 |   0.0127 |    0.0085 |     0.0085 |    0.0097 |     0.0085 |    0.0079 |     0.0091 |   0.0109 |   0.0103 |   0.0091 |
| tug_tow        | True        |        567 |    0.0317 |   0.0212 |    0      |     0.0141 |    0.0071 |     0.0176 |    0.0018 |     0.0141 |   0.0282 |   0.0265 |   0.0212 |
| pleasure       | False       |        508 |    0.0039 |   0.002  |    0.002  |     0.002  |    0.002  |     0.002  |    0.0098 |     0.0098 |   0.0118 |   0.0138 |   0.0118 |
| pleasure       | True        |         74 |    0.0946 |   0.0405 |    0.0405 |     0.0405 |    0.0405 |     0.0405 |    0.027  |     0.0405 |   0.0676 |   0.0946 |   0.0946 |
| military_law   | False       |        224 |    0.0312 |   0.0312 |    0.0089 |     0.0223 |    0.0045 |     0.0179 |    0.0089 |     0.0179 |   0.0134 |   0.0134 |   0.0134 |
| military_law   | True        |         61 |    0      |   0      |    0      |     0      |    0      |     0      |    0      |     0      |   0      |   0      |   0      |
| high_speed     | False       |         50 |    0      |   0      |    0      |     0      |    0      |     0      |    0      |     0      |   0      |   0      |   0      |
| high_speed     | True        |         52 |    0.0192 |   0      |    0      |     0      |    0      |     0      |    0      |     0      |   0.0962 |   0.0385 |   0.0577 |
| other          | False       |        746 |    0.0134 |   0.0121 |    0.0737 |     0.0322 |    0.0684 |     0.0389 |    0.0952 |     0.0536 |   0.0147 |   0.0147 |   0.0174 |
| other          | True        |        155 |    0.0129 |   0      |    0.2194 |     0.0968 |    0.1742 |     0.0645 |    0.1484 |     0.0516 |   0      |   0.0065 |   0      |
