# fleet-review

## Landing: direct to `main` (a deliberate deviation)

This repository does not follow the fleet rule that every change lands by pull request, because
it has no pull request CI.
Interactive work, Rob's own and an agent's on his behalf, commits straight to `main` and pushes
at once, with no pull request; a "bypassed rules" notice on the push is expected. A loop
run here still lands by pull request. Force-push and deleting `main` stay refused for everyone.
GitHub enforces this, not this file: the repository is listed in `rulesets.tracker_bypass_allow_admin`
in `rknightion/.github` `fleet/repo-settings-standard.json`, the fleet's direct-to-main list.
