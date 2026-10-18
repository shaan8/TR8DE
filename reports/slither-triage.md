# Slither triage

Slither 0.11.6, 102 detectors, run on src/ only. 14 informational/low results, 0 medium or high.

| Detector | Count | Verdict |
|---|---|---|
| timestamp | 5 | Accepted. Deadlines, grace (2 days), supplier delay and the daily cap are measured in hours and days; validator timestamp drift of a few seconds cannot change any outcome. |
| naming-convention | rest | Accepted. Underscore-prefixed constructor and setter parameters are an intentional style to avoid shadowing state variables. |

Fixed after the first run: uninitialized locals in `cancelDeal`, unindexed address parameters in `AgentChanged`, `WalletCreated`, `PlatformChanged`.
