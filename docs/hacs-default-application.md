# HACS default-catalog preparation

This document prepares a future submission of `lampje25/ha-fitage` to the HACS default catalog. It is not a submission and does not authorize a pull request.

## Verified status on 2026-09-02

- The GitHub repository is public, has Issues enabled, has a description and relevant topics, and uses `main` as its default branch.
- It contains one integration at `custom_components/fitage`, a valid `manifest.json`, `hacs.json`, and local brand images including `brand/icon.png`.
- Manifest version `1.4.0`, tag `v1.4.0`, and release commit `a36dabf7989703d8742b7a86ac07ab7d4e44677d` agree.
- Release `v1.4.0` is a normal, public GitHub release.
- HACS and Hassfest runs for the release commit succeeded.
- `lampje25/ha-fitage` is not present in the HACS `integration` list, and GitHub searches found no earlier open or closed HACS-default pull request for it.
- The repository is not limited to a known country, so no `country` key is proposed for `hacs.json`.

## Required action before submission

HACS requires a new full GitHub release after the HACS and Hassfest actions have completed successfully. Release `v1.4.0` was published at `2026-09-02T18:16:49Z`; Hassfest completed at `18:16:42Z`, but HACS validation completed at `18:17:05Z`. A future release must therefore be created after both workflows pass on the intended release commit. Do not represent v1.4.0 as satisfying this ordering requirement.

After the documentation/workflow changes are approved and published, both Actions must pass without disabled checks. Then create a new full release, and use links to the resulting successful runs and release in the application.

## Default-list change

Fork `hacs/default`, create a topic branch from its `master` branch, and add exactly this JSON string to the `integration` array:

```json
"lampje25/ha-fitage"
```

At the time of inspection, its alphabetical position is after `Lamarqe/ha_openems` and before `lancer73/ha-weather-uploader`. Recheck the live list immediately before editing because other submissions may change that position.

The repository owner `lampje25`, or another major contributor, must submit the pull request. Allow maintainers to edit the pull request. HACS says new additions currently take months to be reviewed; there is no guaranteed review date. Follow the live backlog rather than requesting priority.

## Draft pull request

**Title**

```text
Adds new integration [lampje25/ha-fitage]
```

**Body**

```markdown
## Checklist

- [x] I've read the [publishing documentation](https://hacs.xyz/docs/publish/start).
- [x] I've added the [HACS action](https://hacs.xyz/docs/publish/action) to my repository.
- [x] (For integrations only) I've added the [hassfest action](https://developers.home-assistant.io/blog/2020/04/16/hassfest/) to my repository.
- [x] The actions are passing without any disabled checks in my repository.
- [x] I've added a link to the action run on my repository below in the links section.
- [x] I've created a new release of the repository after the validation actions were run successfully.

## Links

Link to current release: <FUTURE_RELEASE_URL>
Link to successful HACS action (without the `ignore` key): <FUTURE_HACS_ACTION_URL>
Link to successful hassfest action (if integration): <FUTURE_HASSFEST_ACTION_URL>
```

Replace every placeholder with the post-validation release and its actual successful runs. Re-copy the current HACS template immediately before submitting and adapt this draft if the template has changed.

## Expected automated checks

The current HACS/default checks cover repository ownership, an editable pull request, existing/default/removed repository status, releases, HACS validation, Hassfest, manifest validity, brand assets, repository metadata, JSON validity, and sorted placement. Treat the live pull-request checks as authoritative if this list changes.
