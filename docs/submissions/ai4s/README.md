# Liver-chip submission demo

One command joins the working engineering and evidence components. Run from the
repository root with Python 3.11 or later:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m forma_core.biology.liverchip_demo --output /tmp/liverchip-demo
cat /tmp/liverchip-demo/REPORT.md
```

Use a new output directory for each run. Change `--compound Clozapine` to inspect
another published compound. No API key, paid service or new data download is
required. The source manifests are already in the repository.

The checked run is in `examples/organ-on-chip/demo-run/`. Outputs include design,
requirements, biological experiment, published observations, source provenance,
fault detection/repair results, analytical flow checks and a separate molecular
3-NN baseline. The human-readable entry point is `REPORT.md`.

This minimum demo uses a deterministic fixture builder. It does not demonstrate
live natural-language generation, an autonomous general repair model, a biological
injury simulator, or a fabricated/tested chip. Those broader RFD goals remain
unfinished; the write-up states that boundary.

## Submission status, checked October 11, 2026

Kaggle's live competition overview showed **Close — a day ago**, a disabled Accept
Rules button, and the written October 10 deadline. A normal competition submission
was not available in the inspected signed-out view. No submission or registration
has been made by this workflow. Acceptance of a late package is unconfirmed.

The package contains a write-up/technical report draft and a timed demo recording
script. Still required for an accepted entry: a real public demo video, confirmed
registration/team details, and organizer permission or an available submission
route. No outreach was sent.

- Competition: https://www.kaggle.com/competitions/ai-4-s-open-innovation-artificial-intelligence-for-life-scien
- Registration linked by the competition: https://docs.google.com/forms/d/e/1FAIpQLSdRAat5jIunRaFNh_NntsVeJUnekEJDrbuokLZ32LFgCwPtiA/viewform
- Public code: https://github.com/Mapped-Assembly/forma-oss
- Write-up: `WRITEUP.md`
- Recording script: `DEMO-SCRIPT.md`
