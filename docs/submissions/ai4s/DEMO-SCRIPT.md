# Actual-operation recording script (target 3 minutes)

Record a terminal and the generated files. This script is not a recorded video.

**0:00–0:20 — Purpose.** Show the title and repository. Say: “This workflow connects
liver-chip engineering checks with traceable published experimental evidence.”

**0:20–0:50 — Execute.** In the repository root, run:

```bash
python -m forma_core.biology.liverchip_demo --output /tmp/liverchip-recording
cat /tmp/liverchip-recording/REPORT.md
```

Use an unused output directory. Let viewers see the actual PASS result, fault
counts and evidence counts. Explain that the fixture builder is deterministic.

**0:50–1:30 — Engineering.** Open run.json. Show the missing-outlet error, its
component-specific findings and corrected validation. Show reversed connection
and excessive-flow cases. State that these are three prescribed fault injections.

**1:30–1:55 — Flow.** Show the two channels' perturbation ratios: velocity and
pressure drop double, residence time halves. State the Newtonian laminar
assumptions and that this is not biological injury simulation.

**1:55–2:30 — Evidence.** Open evidence.json and show Troglitazone observations,
source row IDs, dose/units and a missing entry. Show 32 measurements and four
missing values. State that these are published data, not measurements from our chip.

**2:30–2:50 — ML comparator.** Open molecular-baseline.json. Show the separate
six-compound nearest-neighbor results. Explain that its AUROC is 0.5 and it is not
a validated chip predictor. Do not imply it predicts the selected evidence drug.

**2:50–3:10 — Value and limits.** End on REPORT.md and the reproduction command.
Emphasize reproducibility, explicit defects and source traceability. State that
live AI design generation and independent chip validation remain future work.
