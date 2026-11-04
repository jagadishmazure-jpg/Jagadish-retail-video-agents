# Interview points
- **Why edge:** video is heavy and sensitive; keeping it in the store cuts bandwidth and privacy risk.
- **Why till matching:** most internal loss shows up as voids, refunds and no-sales; video alone is ambiguous.
- **Explainable triage:** each score is a list of reasons, so a manager can disagree with a specific step.
- **Human in the loop:** theft labels need a named, single-use, scoped, expiring approval; denials are audited.
- **Privacy by design:** identity fields are rejected at input, not filtered later.
- **Honest limits:** thresholds are hand-set on synthetic data; accuracy and box sizing are unmeasured.
- **Swap the model:** the detector is an interface, so a real model plugs in without touching the agents.
