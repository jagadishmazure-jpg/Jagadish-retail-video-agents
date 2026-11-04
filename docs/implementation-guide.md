# Implementation guide

For a store owner or engineer taking this from synthetic demo to a real pilot.

## 1. Plug in a real detector
Write a class with `detect(frames) -> list[DetectorEvent]`. Map your model's classes to the labels the
detection agent knows: `item_to_bag`, `item_passed_unscanned`, `item_on_belt`, `person`, `queue`,
`liquid_on_floor`, `person_on_floor`, `zone_empty`, `drawer_open_no_customer`, `vehicle`.
Put only counts, dwell times and flags in `attrs`. Never emit face crops, embeddings or IDs; the detection agent will refuse them.

## 2. Plug in the till
Export void, refund, no-sale, discount and drawer-open events with lane, time and amount. Replace cashier names with
a pseudonymous token before the data reaches this code.

## 3. Map zones
Name each camera zone (`lane-1`, `aisle-5`, `backroom`, `fire-lane`). Lane names must match the till lane names.

## 4. Tune with the store
Start with the defaults, run for two weeks in "log only" mode, then agree on thresholds and known false positives
with the store manager. Record every change in the audit log.

## 5. Edge box sizing — TO BE MEASURED
| Question | Status |
|---|---|
| Cameras per box at target frame rate | To be measured in pilot |
| Detection latency per frame | To be measured in pilot |
| Disk needed for retention windows | To be measured in pilot |
| Power and cost per box | To be measured in pilot |
No numbers are claimed here until they are measured on real hardware.

## 6. Before go-live checklist
- Signs at entrances that cameras and video analytics are in use.
- Legal review of local privacy and biometric laws (see privacy-notes.md).
- Named managers enrolled in the review gate.
- Retention purge scheduled daily.
- Staff told clearly: an alert is not an accusation.
