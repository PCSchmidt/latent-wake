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

## Share of test false alarms by AIS ship-type code

Each vessel's most frequent reported type code. Pilot vessels (50) and dredging (33) fall in the model's "other" class.

|   ais_type | name                       |   n_normal |   vessels |   physics |   kalman |   jepa-s0 |   fused-s0 |   jepa-s1 |   fused-s1 |   jepa-s2 |   fused-s2 |   raw-s0 |   raw-s1 |   raw-s2 |
|-----------:|:---------------------------|-----------:|----------:|----------:|---------:|----------:|-----------:|----------:|-----------:|----------:|-----------:|---------:|---------:|---------:|
|         52 | tug                        |       1657 |        26 |     0.298 |    0.266 |     0.048 |      0.098 |     0.058 |      0.096 |     0.043 |      0.093 |    0.234 |    0.215 |    0.193 |
|         70 | cargo                      |        647 |        32 |     0.019 |    0.008 |     0.007 |      0.009 |     0.01  |      0.012 |     0.022 |      0.017 |    0.007 |    0.007 |    0.007 |
|         37 | pleasure craft             |        581 |        22 |     0.087 |    0.032 |     0.015 |      0.018 |     0.013 |      0.016 |     0.025 |      0.034 |    0.076 |    0.097 |    0.093 |
|         31 | towing                     |        524 |         8 |     0     |    0     |     0.004 |      0     |     0.003 |      0     |     0.004 |      0     |    0     |    0     |    0     |
|         50 | pilot vessel               |        358 |         3 |     0.115 |    0.073 |     0.161 |      0.121 |     0.115 |      0.096 |     0.119 |      0.093 |    0.069 |    0.076 |    0.079 |
|         33 | dredging or underwater ops |        307 |         3 |     0     |    0     |     0.15  |      0.049 |     0.121 |      0.06  |     0.201 |      0.097 |    0     |    0     |    0     |
|         30 | fishing                    |        243 |         4 |     0.394 |    0.548 |     0.3   |      0.348 |     0.419 |      0.406 |     0.273 |      0.325 |    0.517 |    0.521 |    0.536 |
|         60 | passenger                  |        235 |         4 |     0     |    0     |     0     |      0     |     0     |      0     |     0     |      0     |    0     |    0     |    0     |
|         79 | cargo                      |        211 |         4 |     0     |    0     |     0.278 |      0.321 |     0.236 |      0.289 |     0.273 |      0.304 |    0.028 |    0.028 |    0.029 |
|         51 | search and rescue          |        165 |         8 |     0.038 |    0.032 |     0.004 |      0.009 |     0     |      0.008 |     0.004 |      0.008 |    0.007 |    0.007 |    0.007 |
|         71 | cargo                      |        155 |        12 |     0.01  |    0     |     0.004 |      0     |     0.003 |      0     |     0.004 |      0     |    0.007 |    0.007 |    0.007 |
|         99 | other type                 |        120 |         1 |     0     |    0     |     0     |      0     |     0     |      0     |     0     |      0     |    0     |    0     |    0     |
|         90 | other type                 |        115 |         5 |     0     |    0     |     0.015 |      0.004 |     0.013 |      0     |     0.018 |      0.013 |    0.007 |    0.007 |    0.014 |
|         40 | high speed craft           |        102 |         2 |     0.01  |    0     |     0     |      0     |     0     |      0     |     0     |      0     |    0.034 |    0.014 |    0.021 |
|         55 | law enforcement            |        101 |         5 |     0.01  |    0.008 |     0     |      0     |     0     |      0     |     0     |      0     |    0     |    0     |    0     |
|         80 | tanker                     |         89 |         4 |     0     |    0.008 |     0.007 |      0.004 |     0.003 |      0.004 |     0.007 |      0     |    0     |    0     |    0     |
|         74 | cargo                      |         61 |         4 |     0     |    0.008 |     0.004 |      0.004 |     0     |      0.004 |     0     |      0.004 |    0     |    0     |    0     |
|         32 | towing, long               |         39 |         1 |     0     |    0     |     0     |      0     |     0.003 |      0     |     0.004 |      0.004 |    0     |    0.007 |    0     |
|         18 | reserved or NOAA code      |         35 |         1 |     0     |    0     |     0     |      0     |     0     |      0     |     0     |      0     |    0     |    0     |    0     |
|         77 | cargo                      |         32 |         1 |     0     |    0     |     0     |      0     |     0     |      0     |     0     |      0     |    0     |    0     |    0     |
|         35 | military ops               |         19 |         3 |     0.019 |    0.016 |     0.004 |      0.013 |     0.003 |      0.008 |     0.004 |      0.008 |    0.014 |    0.014 |    0.014 |
|         39 | reserved or NOAA code      |          1 |         1 |     0     |    0     |     0     |      0     |     0     |      0     |     0     |      0     |    0     |    0     |    0     |
|         36 | sailing                    |          1 |         1 |     0     |    0     |     0     |      0     |     0     |      0     |     0     |      0     |    0     |    0     |    0     |
|         89 | tanker                     |          1 |         1 |     0     |    0     |     0     |      0     |     0     |      0     |     0     |      0     |    0     |    0     |    0     |
|         84 | tanker                     |          1 |         1 |     0     |    0     |     0     |      0     |     0     |      0     |     0     |      0     |    0     |    0     |    0     |

## Vessels with the most test false alarms

Position: median grid-cell center of the false-alarm windows' first step (about 5 km cells).

| method   | vessel |   false_alarms |   normal_windows |   ais_type | name                       |    lat |     lon |
|:---------|----------:|---------------:|-----------------:|-----------:|:---------------------------|-------:|--------:|
| jepa-s0  | cargo A |             76 |              136 |         79 | cargo                      | 36.875 | -76.325 |
| jepa-s0  | fishing A |             75 |              124 |         30 | fishing                    | 37.825 | -76.275 |
| jepa-s0  | pilot vessel A |             41 |              146 |         50 | pilot vessel               | 39.275 | -76.525 |
| jepa-s0  | dredging or underwater ops A |             41 |              145 |         33 | dredging or underwater ops | 36.925 | -76.325 |
| jepa-s0  | fishing B |              7 |               82 |         30 | fishing                    | 37.025 | -76.325 |
| jepa-s0  | tug B |              4 |              106 |         52 | tug                        | 36.975 | -76.325 |
| jepa-s0  | other type A |              3 |               32 |         90 | other type                 | 36.875 | -76.325 |
| jepa-s0  | tug A |              3 |              155 |         52 | tug                        | 36.975 | -76.325 |
| jepa-s0  | tug D |              2 |               10 |         52 | tug                        | 36.875 | -76.325 |
| jepa-s0  | pilot vessel B |              2 |               85 |         50 | pilot vessel               | 36.925 | -76.075 |
| kalman   | fishing A |             68 |              124 |         30 | fishing                    | 37.825 | -76.275 |
| kalman   | tug A |             11 |              155 |         52 | tug                        | 36.975 | -76.325 |
| kalman   | tug C |              9 |              151 |         52 | tug                        | 36.925 | -76.325 |
| kalman   | tug B |              8 |              106 |         52 | tug                        | 36.975 | -76.325 |
| kalman   | pilot vessel A |              5 |              146 |         50 | pilot vessel               | 39.275 | -76.525 |
| kalman   | pilot vessel B |              3 |               85 |         50 | pilot vessel               | 36.925 | -76.075 |
| kalman   | tug F |              2 |              143 |         52 | tug                        | 39.275 | -76.55  |
| kalman   | military ops A |              2 |                5 |         35 | military ops               | 36.925 | -76.225 |
| kalman   | search and rescue A |              2 |              136 |         51 | search and rescue          | 39.2   | -76.575 |
| kalman   | pleasure craft B |              2 |               19 |         37 | pleasure craft             | 38.925 | -76.525 |
| raw-s0   | fishing A |             75 |              124 |         30 | fishing                    | 37.825 | -76.275 |
| raw-s0   | tug B |             11 |              106 |         52 | tug                        | 36.975 | -76.325 |
| raw-s0   | tug A |              9 |              155 |         52 | tug                        | 36.975 | -76.325 |
| raw-s0   | pilot vessel A |              7 |              146 |         50 | pilot vessel               | 39.275 | -76.525 |
| raw-s0   | high speed craft A |              5 |               49 |         40 | high speed craft           | 36.875 | -75.725 |
| raw-s0   | cargo A |              4 |              136 |         79 | cargo                      | 36.875 | -76.325 |
| raw-s0   | tug C |              4 |              151 |         52 | tug                        | 36.925 | -76.325 |
| raw-s0   | pleasure craft A |              4 |               96 |         37 | pleasure craft             | 37.575 | -76.325 |
| raw-s0   | tug E |              3 |              122 |         52 | tug                        | 38.325 | -75.625 |
| raw-s0   | pilot vessel B |              3 |               85 |         50 | pilot vessel               | 36.925 | -76.075 |
| fused-s0 | fishing A |             77 |              124 |         30 | fishing                    | 37.825 | -76.275 |
| fused-s0 | cargo A |             72 |              136 |         79 | cargo                      | 36.875 | -76.325 |
| fused-s0 | pilot vessel A |             22 |              146 |         50 | pilot vessel               | 39.275 | -76.525 |
| fused-s0 | dredging or underwater ops A |             11 |              145 |         33 | dredging or underwater ops | 36.925 | -76.325 |
| fused-s0 | tug A |              7 |              155 |         52 | tug                        | 36.975 | -76.325 |
| fused-s0 | tug B |              6 |              106 |         52 | tug                        | 36.975 | -76.325 |
| fused-s0 | pilot vessel B |              4 |               85 |         50 | pilot vessel               | 36.925 | -76.075 |
| fused-s0 | tug C |              3 |              151 |         52 | tug                        | 36.925 | -76.325 |
| fused-s0 | tug D |              2 |               10 |         52 | tug                        | 36.875 | -76.325 |
| fused-s0 | military ops A |              2 |                5 |         35 | military ops               | 36.925 | -76.225 |
