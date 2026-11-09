# Evaluation results: frozen test set

Test set `data/testsets/chesapeake-test-v2` (sha256 826137bdb526), scored once at 2026-11-09T22:42:12+00:00. Calibration: tail; alert budget 1%; fused detector built from `jepa`.

**Contract verdict: 3 of 8 criteria met; not met: behavioral_gain_over_kalman_auroc, fused_beats_kalman_auroc, behavioral_gain_over_kalman_auprc, fused_no_precision_loss_vs_kalman_auprc, fused_false_alarms_within_2x_budget.**

| Criterion | Result | Met |
|---|---|---|
| `behavioral_gain_over_kalman_auroc` | jepa 0.807 vs kalman 0.737 (margin +0.100) | **no** |
| `fused_beats_kalman_auroc` | fused 0.872 vs kalman 0.853 (margin +0.030) | **no** |
| `fused_beats_jepa_auroc` | fused 0.872 vs jepa 0.832 (margin +0.030) | yes |
| `behavioral_gain_over_kalman_auprc` | jepa 0.760 vs kalman 0.721 (margin +0.050) | **no** |
| `fused_no_precision_loss_vs_kalman_auprc` | fused 0.643 vs kalman 0.704 (margin +0.000) | **no** |
| `fused_beats_jepa_auprc` | fused 0.643 vs jepa 0.526 (margin +0.030) | yes |
| `fused_false_alarms_within_2x_budget` | fused 0.0408 (needs <= 0.0200) | **no** |
| `fused_detects_at_least_kalman_at_budget` | fused 0.501 vs kalman 0.483 (margin +0.000) | yes |

Checkpoints scored (sha256):

- `jepa-s0`: 862eb8722747
- `jepa-s1`: a768866e48f6
- `jepa-s2`: 80b22816d75f
- `raw-s0`: e33db07915a8
- `raw-s1`: 4cc08f37536d
- `raw-s2`: 394fb081bb25

## Interpretation

Written after reading the numbers. Every number below is a three-seed mean
taken from the generated tables that follow; none of those tables was edited.

**The headline claim is not supported at the pre-registered margins.** The
JEPA beats Kalman on behavioral anomalies by +0.070 AUROC (margin 0.10) and
+0.039 AUPRC (margin 0.05). The direction matches validation (+0.090 AUROC)
and holds for all three seeds, which agree to within 0.01. The gain is
concentrated in loitering: 0.938 vs 0.841 AUROC (+0.097). On route deviation
it is +0.043 (0.677 vs 0.634), and the raw-target predictor does slightly
better there (0.694).

**What holds up: the JEPA is the best single detector for loitering.** That
is true on validation (0.80 vs Kalman 0.66 and raw target 0.73) and on test
(0.94 vs 0.84 and 0.90), with every seed. It is the one place where
predicting in latent space clearly beats predicting raw features (+0.038 on
test). On small spoofs and teleports the JEPA is near chance (0.53 to 0.60 at
the smallest level) while Kalman and the raw-target predictor exceed 0.92.

**Fusion does not add enough over Kalman.** Fused AUROC is +0.019 over Kalman
(margin 0.03), and fused AUPRC is 0.061 *below* Kalman's (margin 0.0). Taking
the larger of two calibrated scores adds the JEPA's false alarms to Kalman's,
which costs precision. It also hides the JEPA's own loitering detections at
the alert budget: the JEPA alone catches 17% to 29% of loitering, the fused
detector 4% to 5%.

**The 1% alert budget did not transfer from validation to test.** Thresholds
set on validation produced false alarms on test normals of 1.8% (physics),
2.1% (Kalman), 2.5% (raw target), about 5.0% (JEPA), and 4.1% (fused). The
contract allows 2%. Under-way normals fared worse: 7.5% for Kalman and about
10% for the JEPA. Validation and test cover the same weeks with disjoint
vessels (198 and 180), so the shift is between vessels, not over time, and
it hit the learned detectors hardest. Detection rates at the budget
(fused 0.501 vs Kalman 0.483, criterion met) are measured at false-alarm
rates the budget did not hold, so they should be read with that in mind.

**Test is easier than validation in absolute terms.** Every method scores
higher on behavioral kinds on test (Kalman loitering 0.84 vs 0.66), because
the test anomaly set is injected into different windows. The criteria compare
methods on the same set, so this does not favor any method.

**Post-hoc analysis (exploratory; computed after the single scoring from the
saved scores; it does not change the verdict).** Full tables:
`reports/eval-v2/posthoc/POSTHOC.md`.

- *Uncertainty.* A cluster bootstrap over the 172 source vessels puts the
  JEPA's behavioral AUROC gain over Kalman at 0.032 to 0.115 (95%), so the
  gain is clearly positive and the 0.10 margin is not ruled out; 6% of draws
  reach it. The AUPRC gain interval (−0.013 to 0.091) includes zero. Fused
  over Kalman on AUROC (0.009 to 0.028) falls short of 0.03 in every part of
  the interval.
- *Where the false alarms come from.* They are concentrated: 22 to 31 of the
  157 vessels with normal windows raise all of them, and the top five raise
  71% to 89%. One stratum, 89 windows of fishing vessels under way, alarms at
  45% to 85% for every detector, including the physics check. Without it,
  Kalman's rate is 1.0% and the raw-target predictor's 1.1% to 1.2%, which is
  within budget. The JEPA has a second, model-specific problem: about a
  quarter of its false alarms come from anchored cargo ships and a quarter
  to a third from "other" vessels, where the baselines barely alarm. Without the
  fishing stratum the JEPA's rate is still 3.5% to 4.2%. The fused detector
  inherits it.

**Not shown here.** Anomalies are synthetic, injected into real tracks; the
data covers one region and one season and Class A vessels only.

### AUROC by kind (mean over severity levels)

| kind            |   fused-s0 |   fused-s1 |   fused-s2 |   jepa-s0 |   jepa-s1 |   jepa-s2 |   kalman |   physics |   raw-s0 |   raw-s1 |   raw-s2 |
|:----------------|-----------:|-----------:|-----------:|----------:|----------:|----------:|---------:|----------:|---------:|---------:|---------:|
| ais_gap         |      0.836 |      0.835 |      0.834 |     0.834 |     0.833 |     0.83  |    0.815 |     0.793 |    0.835 |    0.836 |    0.833 |
| loitering       |      0.903 |      0.903 |      0.905 |     0.937 |     0.937 |     0.939 |    0.841 |     0.425 |    0.901 |    0.899 |    0.899 |
| position_spoof  |      0.976 |      0.975 |      0.976 |     0.877 |     0.869 |     0.871 |    0.985 |     0.971 |    0.979 |    0.978 |    0.979 |
| route_deviation |      0.665 |      0.662 |      0.664 |     0.682 |     0.672 |     0.676 |    0.634 |     0.496 |    0.697 |    0.692 |    0.692 |
| teleport        |      0.982 |      0.981 |      0.981 |     0.847 |     0.835 |     0.846 |    0.989 |     0.976 |    0.988 |    0.987 |    0.987 |

### AUROC by cell

| kind            |   level |   fused-s0 |   fused-s1 |   fused-s2 |   jepa-s0 |   jepa-s1 |   jepa-s2 |   kalman |   physics |   raw-s0 |   raw-s1 |   raw-s2 |
|:----------------|--------:|-----------:|-----------:|-----------:|----------:|----------:|----------:|---------:|----------:|---------:|---------:|---------:|
| ais_gap         |       0 |      0.524 |      0.512 |      0.519 |     0.544 |     0.533 |     0.538 |    0.508 |     0.488 |    0.502 |    0.539 |    0.499 |
| ais_gap         |       1 |      0.973 |      0.971 |      0.97  |     0.951 |     0.942 |     0.943 |    0.983 |     0.955 |    0.988 |    0.988 |    0.987 |
| ais_gap         |       2 |      0.994 |      0.994 |      0.995 |     0.991 |     0.991 |     0.991 |    0.993 |     0.985 |    0.994 |    0.994 |    0.994 |
| ais_gap         |       3 |      0.581 |      0.582 |      0.575 |     0.606 |     0.616 |     0.605 |    0.513 |     0.517 |    0.562 |    0.533 |    0.555 |
| ais_gap         |       4 |      0.959 |      0.957 |      0.958 |     0.943 |     0.941 |     0.942 |    0.958 |     0.907 |    0.982 |    0.981 |    0.981 |
| ais_gap         |       5 |      0.99  |      0.99  |      0.99  |     0.987 |     0.986 |     0.987 |    0.989 |     0.981 |    0.992 |    0.992 |    0.991 |
| ais_gap         |       6 |      0.607 |      0.61  |      0.604 |     0.629 |     0.637 |     0.624 |    0.509 |     0.498 |    0.55  |    0.557 |    0.552 |
| ais_gap         |       7 |      0.92  |      0.925 |      0.917 |     0.879 |     0.876 |     0.869 |    0.912 |     0.86  |    0.956 |    0.954 |    0.955 |
| ais_gap         |       8 |      0.981 |      0.979 |      0.979 |     0.976 |     0.972 |     0.973 |    0.973 |     0.943 |    0.986 |    0.985 |    0.985 |
| loitering       |       0 |      0.869 |      0.871 |      0.867 |     0.909 |     0.912 |     0.91  |    0.824 |     0.481 |    0.901 |    0.899 |    0.9   |
| loitering       |       1 |      0.907 |      0.901 |      0.909 |     0.941 |     0.939 |     0.943 |    0.827 |     0.425 |    0.884 |    0.882 |    0.882 |
| loitering       |       2 |      0.932 |      0.937 |      0.939 |     0.96  |     0.961 |     0.963 |    0.871 |     0.368 |    0.917 |    0.915 |    0.915 |
| position_spoof  |       0 |      0.916 |      0.912 |      0.916 |     0.599 |     0.592 |     0.58  |    0.945 |     0.892 |    0.927 |    0.923 |    0.925 |
| position_spoof  |       1 |      0.965 |      0.963 |      0.962 |     0.783 |     0.758 |     0.768 |    0.977 |     0.966 |    0.973 |    0.97  |    0.971 |
| position_spoof  |       2 |      0.984 |      0.984 |      0.983 |     0.926 |     0.915 |     0.922 |    0.991 |     0.976 |    0.984 |    0.983 |    0.982 |
| position_spoof  |       3 |      0.993 |      0.993 |      0.993 |     0.976 |     0.972 |     0.975 |    0.998 |     0.993 |    0.994 |    0.993 |    0.994 |
| position_spoof  |       4 |      0.999 |      0.999 |      0.999 |     0.988 |     0.987 |     0.989 |    1     |     1     |    0.999 |    0.999 |    0.999 |
| position_spoof  |       5 |      1     |      1     |      1     |     0.991 |     0.991 |     0.992 |    1     |     1     |    1     |    1     |    1     |
| route_deviation |       0 |      0.557 |      0.547 |      0.55  |     0.575 |     0.556 |     0.571 |    0.516 |     0.517 |    0.546 |    0.547 |    0.544 |
| route_deviation |       1 |      0.545 |      0.545 |      0.554 |     0.56  |     0.543 |     0.557 |    0.529 |     0.518 |    0.578 |    0.573 |    0.567 |
| route_deviation |       2 |      0.586 |      0.575 |      0.579 |     0.618 |     0.61  |     0.609 |    0.542 |     0.509 |    0.652 |    0.641 |    0.64  |
| route_deviation |       3 |      0.765 |      0.762 |      0.756 |     0.789 |     0.776 |     0.774 |    0.723 |     0.466 |    0.82  |    0.813 |    0.818 |
| route_deviation |       4 |      0.874 |      0.88  |      0.881 |     0.869 |     0.876 |     0.869 |    0.858 |     0.47  |    0.891 |    0.888 |    0.889 |
| teleport        |       0 |      0.93  |      0.926 |      0.928 |     0.537 |     0.528 |     0.527 |    0.951 |     0.893 |    0.951 |    0.949 |    0.95  |
| teleport        |       1 |      0.976 |      0.975 |      0.974 |     0.662 |     0.624 |     0.666 |    0.989 |     0.975 |    0.986 |    0.986 |    0.985 |
| teleport        |       2 |      0.989 |      0.99  |      0.99  |     0.922 |     0.901 |     0.917 |    0.996 |     0.99  |    0.992 |    0.992 |    0.992 |
| teleport        |       3 |      0.995 |      0.995 |      0.995 |     0.977 |     0.972 |     0.977 |    0.998 |     0.998 |    0.997 |    0.997 |    0.997 |
| teleport        |       4 |      1     |      1     |      1     |     0.991 |     0.991 |     0.992 |    1     |     1     |    1     |    1     |    1     |
| teleport        |       5 |      1     |      1     |      1     |     0.995 |     0.996 |     0.996 |    1     |     1     |    1     |    1     |    1     |

### Operating point (threshold from validation)

False-alarm rate:

|             |   physics |   kalman |   jepa-s0 |   fused-s0 |   jepa-s1 |   fused-s1 |   jepa-s2 |   fused-s2 |   raw-s0 |   raw-s1 |   raw-s2 |
|:------------|----------:|---------:|----------:|-----------:|----------:|-----------:|----------:|-----------:|---------:|---------:|---------:|
| all normals |    0.0179 |   0.0214 |    0.0471 |     0.0386 |    0.054  |     0.0429 |    0.0479 |     0.0409 |   0.025  |   0.0248 |   0.0241 |
| moving only |    0.0607 |   0.0746 |    0.1025 |     0.0915 |    0.0975 |     0.0886 |    0.0965 |     0.0876 |   0.0896 |   0.0915 |   0.0905 |

Share detected, by kind (mean over severity levels):

| kind            |   fused-s0 |   fused-s1 |   fused-s2 |   jepa-s0 |   jepa-s1 |   jepa-s2 |   kalman |   physics |   raw-s0 |   raw-s1 |   raw-s2 |
|:----------------|-----------:|-----------:|-----------:|----------:|----------:|----------:|---------:|----------:|---------:|---------:|---------:|
| ais_gap         |      0.592 |      0.6   |      0.587 |     0.546 |     0.556 |     0.549 |    0.515 |     0.385 |    0.637 |    0.633 |    0.636 |
| loitering       |      0.043 |      0.052 |      0.053 |     0.167 |     0.235 |     0.285 |    0.025 |     0.01  |    0.217 |    0.232 |    0.217 |
| position_spoof  |      0.888 |      0.89  |      0.887 |     0.611 |     0.607 |     0.617 |    0.891 |     0.84  |    0.862 |    0.863 |    0.859 |
| route_deviation |      0.064 |      0.064 |      0.064 |     0.004 |     0.007 |     0.011 |    0.067 |     0.02  |    0.098 |    0.099 |    0.098 |
| teleport        |      0.911 |      0.912 |      0.911 |     0.612 |     0.619 |     0.623 |    0.915 |     0.866 |    0.93  |    0.932 |    0.927 |

### Validation alerts by stratum (alert rate at the 1% budget threshold)

| vessel_class   | under_way   |    n |   physics |   kalman |   jepa-s0 |   fused-s0 |   jepa-s1 |   fused-s1 |   jepa-s2 |   fused-s2 |   raw-s0 |   raw-s1 |   raw-s2 |
|:---------------|:------------|-----:|----------:|---------:|----------:|-----------:|----------:|-----------:|----------:|-----------:|---------:|---------:|---------:|
| unknown        | False       | 2575 |    0.0101 |   0.0101 |    0.0101 |     0.0101 |    0.0101 |     0.0101 |    0.0101 |     0.0101 |   0.0101 |   0.0101 |   0.0101 |
| unknown        | True        |  946 |    0.0085 |   0.0085 |    0.0085 |     0.0085 |    0.0085 |     0.0085 |    0.0085 |     0.0085 |   0.0085 |   0.0085 |   0.0085 |
| cargo          | False       | 6817 |    0.0106 |   0.0103 |    0.0103 |     0.0101 |    0.0103 |     0.0095 |    0.0103 |     0.01   |   0.0103 |   0.0103 |   0.0103 |
| cargo          | True        | 2278 |    0.0101 |   0.0097 |    0.0097 |     0.0097 |    0.0097 |     0.0097 |    0.0097 |     0.0097 |   0.0097 |   0.0097 |   0.0097 |
| tanker         | False       |   90 |    0      |   0      |    0.0111 |     0.0111 |    0.0111 |     0      |    0.0111 |     0      |   0      |   0      |   0      |
| tanker         | True        |  114 |    0      |   0      |    0      |     0      |    0      |     0      |    0      |     0      |   0      |   0      |   0      |
| passenger      | False       | 4391 |    0.0102 |   0.0102 |    0.0102 |     0.0093 |    0.0102 |     0.0098 |    0.0102 |     0.0091 |   0.0102 |   0.0102 |   0.0102 |
| passenger      | True        | 3736 |    0.0104 |   0.0102 |    0.0102 |     0.0099 |    0.0102 |     0.0099 |    0.0102 |     0.0099 |   0.0102 |   0.0102 |   0.0102 |
| fishing        | False       | 1928 |    0.0083 |   0.0099 |    0.0099 |     0.0093 |    0.0099 |     0.0093 |    0.0099 |     0.0093 |   0.0099 |   0.0099 |   0.0099 |
| fishing        | True        |  730 |    0.0082 |   0.0082 |    0.0082 |     0.0082 |    0.0082 |     0.0082 |    0.0082 |     0.0082 |   0.0082 |   0.0082 |   0.0082 |
| tug_tow        | False       | 9991 |    0.0103 |   0.0103 |    0.0103 |     0.0108 |    0.0103 |     0.0108 |    0.0103 |     0.0108 |   0.0103 |   0.0103 |   0.0103 |
| tug_tow        | True        | 7728 |    0.0101 |   0.0104 |    0.0104 |     0.0105 |    0.0104 |     0.0106 |    0.0104 |     0.0105 |   0.0104 |   0.0104 |   0.0104 |
| pleasure       | False       | 4297 |    0.0098 |   0.0102 |    0.0102 |     0.0107 |    0.0102 |     0.0107 |    0.0102 |     0.0107 |   0.0102 |   0.0102 |   0.0102 |
| pleasure       | True        |  645 |    0.0078 |   0.0078 |    0.0078 |     0.0062 |    0.0078 |     0.0062 |    0.0078 |     0.0062 |   0.0078 |   0.0078 |   0.0078 |
| military_law   | False       | 4664 |    0.0105 |   0.0101 |    0.0101 |     0.0107 |    0.0101 |     0.0107 |    0.0101 |     0.0107 |   0.0101 |   0.0101 |   0.0101 |
| military_law   | True        |  624 |    0.008  |   0.008  |    0.008  |     0.0064 |    0.008  |     0.0048 |    0.008  |     0.0064 |   0.008  |   0.008  |   0.008  |
| high_speed     | False       |  352 |    0.0057 |   0.0057 |    0.0057 |     0      |    0.0057 |     0.0028 |    0.0057 |     0.0057 |   0.0057 |   0.0057 |   0.0057 |
| high_speed     | True        |  604 |    0.0066 |   0.0083 |    0.0083 |     0.0066 |    0.0083 |     0.0066 |    0.0083 |     0.0066 |   0.0083 |   0.0083 |   0.0083 |
| other          | False       | 6580 |    0.0105 |   0.0103 |    0.0102 |     0.0105 |    0.0102 |     0.0106 |    0.0102 |     0.0105 |   0.0103 |   0.0103 |   0.0103 |
| other          | True        | 1117 |    0.0098 |   0.009  |    0.009  |     0.009  |    0.009  |     0.009  |    0.009  |     0.009  |   0.009  |   0.009  |   0.009  |

Share of validation alerts on under-way windows (31% of windows are under way):

|       |   physics |   kalman |   jepa-s0 |   fused-s0 |   jepa-s1 |   fused-s1 |   jepa-s2 |   fused-s2 |   raw-s0 |   raw-s1 |   raw-s2 |
|:------|----------:|---------:|----------:|-----------:|----------:|-----------:|----------:|-----------:|---------:|---------:|---------:|
| share |     0.297 |    0.297 |     0.297 |      0.291 |     0.297 |      0.292 |     0.297 |      0.292 |    0.297 |    0.297 |    0.297 |
