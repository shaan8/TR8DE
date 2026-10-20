# TR8DE walkthrough videos

Recorded on 20 October 2026. These replace the earlier slow takes. Typing stays visible, prompts pause before submission, results are held for reading, and long processing waits are cut. The caption in every clip identifies its mode. No audio is included.

| Clip | Length | What it shows |
| --- | --- | --- |
| [Autonomous AI negotiation to Sepolia escrow and deposit](https://github.com/user-attachments/assets/fb32a346-2bb6-456b-adb2-29dbcb794922) | 136 s | Live Qwen buyer, supplier and checker; isolated fictional cash plan; real Sepolia test transactions; no owner payment confirmation. |
| [Local demo: startup output and generated login](https://github.com/user-attachments/assets/603aaf57-4132-47ee-a2e3-58a6ec503151) | 28 s | Prerequisites installed; same real demo session. Idle time shortened. |
| [TR8DE console overview](https://github.com/user-attachments/assets/d3d83836-bff7-4a3b-8df2-f0d14aafdf49) | 24 s | Local chain: workspace, payments, negotiation and saved suppliers. |
| [Wallet, supplier history and cash forecast](https://github.com/user-attachments/assets/7df4091b-84f0-46d9-8a29-6b4458273a45) | 59 s | Local chain + live model. Processing waits shortened between questions. |
| [Negotiation to escrow, deposit and final settlement](https://github.com/user-attachments/assets/5ea40fb8-f2a2-4bcb-9066-5c862a60870d) | 87 s | Local chain; rules-based buyer and scripted supplier, with the live AI payment checker. Waits shortened. |
| [Console fixture replay](https://github.com/user-attachments/assets/b9569369-7f93-4bd0-97d2-f630a172ee42) | 30 s | Saved approval and transaction evidence. No new blockchain transactions or model calls. |
| [Security: release refused before delivery attestation](https://github.com/user-attachments/assets/27e6acac-96bb-43d7-b927-a52b6fea154a) | 28 s | Local chain. The AI checker approves, but deterministic policy refuses the payment. Wait shortened. |
| [Login security: logout, failed attempts and lockout](https://github.com/user-attachments/assets/54c42be1-e022-40f9-913d-bcc26bb40069) | 70 s | Real local requests. Five failed passwords trigger lockout; a correct password is also blocked. |
| [Owner commands and wallet recovery](https://github.com/user-attachments/assets/fa613beb-dc20-44d2-9163-a0cd2a9b6d46) | 49 s | Local chain: /guide, /limits, /unfreeze (resuming a paused wallet). Idle time shortened. |
| [Live Sepolia: owner password setup and sign-in](https://github.com/user-attachments/assets/525bfdf8-0e7f-496c-914f-9b665c6af441) | 43 s | Existing deployment reused; a separate audit session, not a repair of historical logs. Setup waits shortened. |
| [Live Sepolia payment: escrow, deposit and Etherscan](https://github.com/user-attachments/assets/982cc5f3-d873-4a00-8a17-58cddb372a10) | 88 s | Real Sepolia test funds + live model. Chain and explorer indexing waits shortened. |

## Headline autonomous Sepolia run

Deal 10 proves the normal autonomous path: live buyer and supplier models agree on v7 of `NEG-FDFE804D`,
then the agent creates the 24,800 tPHP escrow and pays the 3,720 tPHP deposit without an owner payment
confirmation. Public RPC and Etherscan confirm both receipts, the scoped agent signer and the token transfer.
The [27-entry audit](../reports/videos/autonomous-sepolia-audit.jsonl) verifies intact, contains two Tier 1
payment verdicts and no owner confirmation events. [Verified receipt data](../reports/videos/autonomous-sepolia.json).

This independent fictional cash plan has a 20,000 PHP buffer and no other scheduled outflows. Existing user
and earlier recording plans are untouched. The supplier is a hosted live-model test agent, not a real supplier
contacted over WhatsApp/Telegram. The footage includes a browser refresh because an interface polling bug
stopped showing progress after offer exchange ended. Status reporting now includes the settlement worker;
11 negotiation regression tests pass, including that case.

## Evidence and boundaries

- The local full cycle uses rules-based buyer negotiation and a scripted supplier, plus a live Qwen payment checker. It records agreement, owner approval, escrow creation, deposit, an attempted early release refused by deterministic policy, owner attestation, balance release and completion.
- The earlier approval-card payment uses the existing Sepolia deployment. Deal 9 is owner-confirmed because its forecast is short; this is not evidence of a card-free autonomous create. The scoped agent key signs both escrow creation and deposit. Etherscan confirms the 200 tPHP transfer to the saved Lumen address.
- The login protection take records real logout, an unauthorized API read, five failed passwords and lockout of the correct password. It is not a claim that every security control has been penetration-tested.
- The live recording starts a separate audit session, verified with 11 entries after the payment. The earlier log with broken previous-hash links is preserved; a new intact session does not repair it.
- The temporary demo and live recording consoles were stopped before publication. The demo password visible in the startup clip no longer grants access to that recording session.
- Fixture replay is saved evidence. It creates no new model calls or transactions.

## Not covered by these clips

Real WhatsApp/Telegram sends, Streamlit/CLI use, first-time Sepolia deployment, the flagged-supplier retest, clarification/correction and deliberate provider failure are not shown. The separate five-minute submission film and the remaining scenario coverage in [execution evidence](submission/6-execution-evidence.md#610-remaining-recording-evidence) still need their own recording. These eleven clips are the README walkthrough set, not proof that every optional integration or attack case has been recorded.

Export dimensions, exact durations, checksums and source cut points are in [the manifest](../reports/videos/manifest.json). Each MP4 was visually reviewed and fully decoded successfully.
