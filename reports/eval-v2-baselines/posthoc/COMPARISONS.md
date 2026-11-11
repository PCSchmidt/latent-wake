# Pairwise comparisons on the test set (exploratory)

Post hoc, from saved scores of separately recorded benchmarks of the same frozen test set; seed-averaged; 95% intervals from a cluster bootstrap over 172 source vessels (200 draws). Not pre-registered.

| a      | b      | kinds           | metric   |   a_minus_b |   ci_low |   ci_high |   share_a_better |
|:-------|:-------|:----------------|:---------|------------:|---------:|----------:|-----------------:|
| trais  | jepa   | behavioral      | auroc    |       0.009 |   -0.027 |     0.042 |            0.685 |
| trais  | jepa   | behavioral      | auprc    |       0.044 |   -0.004 |     0.094 |            0.955 |
| trais  | jepa   | loitering       | auroc    |      -0.027 |   -0.058 |     0.002 |            0.055 |
| trais  | jepa   | loitering       | auprc    |       0     |   -0.037 |     0.047 |            0.54  |
| trais  | jepa   | route_deviation | auroc    |       0.045 |   -0.004 |     0.088 |            0.97  |
| trais  | jepa   | route_deviation | auprc    |       0.088 |    0.027 |     0.145 |            1     |
| trais  | jepa   | kinematic       | auroc    |       0.054 |    0.034 |     0.079 |            1     |
| trais  | jepa   | kinematic       | auprc    |       0.176 |   -0.051 |     0.314 |            0.85  |
| trais  | kalman | behavioral      | auroc    |       0.079 |    0.054 |     0.102 |            1     |
| trais  | kalman | behavioral      | auprc    |       0.083 |    0.046 |     0.131 |            1     |
| trais  | kalman | loitering       | auroc    |       0.07  |    0.044 |     0.092 |            1     |
| trais  | kalman | loitering       | auprc    |       0.088 |    0.046 |     0.129 |            1     |
| trais  | kalman | route_deviation | auroc    |       0.089 |    0.058 |     0.119 |            1     |
| trais  | kalman | route_deviation | auprc    |       0.079 |    0.037 |     0.136 |            1     |
| trais  | kalman | kinematic       | auroc    |      -0.026 |   -0.042 |    -0.014 |            0     |
| trais  | kalman | kinematic       | auprc    |      -0.147 |   -0.277 |    -0.047 |            0     |
| jepa   | kalman | behavioral      | auroc    |       0.07  |    0.032 |     0.115 |            1     |
| jepa   | kalman | behavioral      | auprc    |       0.039 |   -0.013 |     0.091 |            0.9   |
| jepa   | kalman | loitering       | auroc    |       0.097 |    0.052 |     0.135 |            1     |
| jepa   | kalman | loitering       | auprc    |       0.088 |    0.031 |     0.134 |            1     |
| jepa   | kalman | route_deviation | auroc    |       0.043 |   -0.008 |     0.09  |            0.95  |
| jepa   | kalman | route_deviation | auprc    |      -0.009 |   -0.063 |     0.051 |            0.42  |
| jepa   | kalman | kinematic       | auroc    |      -0.081 |   -0.098 |    -0.067 |            0     |
| jepa   | kalman | kinematic       | auprc    |      -0.323 |   -0.389 |    -0.18  |            0     |
| lstmae | jepa   | behavioral      | auroc    |      -0.057 |   -0.09  |    -0.027 |            0     |
| lstmae | jepa   | behavioral      | auprc    |      -0.038 |   -0.077 |     0.011 |            0.07  |
| lstmae | jepa   | loitering       | auroc    |      -0.031 |   -0.072 |     0.009 |            0.07  |
| lstmae | jepa   | loitering       | auprc    |      -0.019 |   -0.07  |     0.042 |            0.325 |
| lstmae | jepa   | route_deviation | auroc    |      -0.084 |   -0.119 |    -0.04  |            0     |
| lstmae | jepa   | route_deviation | auprc    |      -0.057 |   -0.114 |    -0.006 |            0.01  |
| lstmae | jepa   | kinematic       | auroc    |      -0.021 |   -0.045 |     0.008 |            0.065 |
| lstmae | jepa   | kinematic       | auprc    |      -0.013 |   -0.229 |     0.108 |            0.4   |
