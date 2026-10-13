<!-- BEGIN DOC NAV -->
[✦ VIREA](../../README.md) · [Documentation](../README.en.md) · [Set Up](../getting-started/automatic-setup.en.md) · [Demos](../demos/README.en.md) · [简体中文](branching.zh-CN.md)
<!-- END DOC NAV -->

# 🌿 Branching and releases

**The public `Moonweave-AI/virea` repository keeps one branch: `main`.** Develop on short-lived local branches, or in a separate private repository when a team needs shared private review. Publish reviewed changes to `main`.

GitHub visibility applies to a repository, not to individual branches. A branch called `private/*` is still public in a public repository. Removing a branch name does not make its previously published commits, forks or pull requests private.

## Name the work

Use **`<type>/<short-topic>`**: lowercase ASCII words, hyphens between words, one slash, at most 64 characters in total. Name the result or problem. Add an issue number only when it helps identify the work, such as `fix/42-worker-recovery`.

| Prefix | Purpose | Example |
|:--|:--|:--|
| `feat/` | User-facing capability | `feat/provider-discovery` |
| `fix/` | Behavior correction | `fix/wrist-retargeting` |
| `refactor/` | Internal restructuring | `refactor/body-ownership` |
| `docs/` | Documentation | `docs/setup-guide` |
| `test/` | Test coverage | `test/avatar-rest-pose` |
| `perf/` | Measured performance work | `perf/worker-startup` |
| `build/` or `ci/` | Packaging or automation | `ci/windows-first-run` |
| `chore/` | Maintenance | `chore/retire-old-assets` |
| `codex/` | Automated local work | `codex/motion-optimization-baseline` |

The corresponding policy pattern is `^(feat|fix|refactor|docs|test|perf|build|ci|chore|codex)/[a-z0-9]+(-[a-z0-9]+)*$`, plus the 64-character limit. `main` is the sole long-lived branch. Release versions belong in tags, not permanent release branches.

Avoid repeated suffixes such as `detail-technical-method`, extra path levels, personal names, dates without a purpose, and labels such as `final-final`. Git's own name validation still applies:

```sh
git check-ref-format --branch fix/wrist-retargeting
```

That command checks Git syntax; the table and pattern above define VIREA's stricter naming convention.

## Develop and publish

Start with a clean working tree and up-to-date `main`:

```sh
git switch main
git pull --ff-only origin main
git switch -c fix/wrist-retargeting
```

Make a focused change, run the relevant checks and review the diff. Follow [AGENTS.md](../../AGENTS.md) for GitNexus impact analysis before edits and change analysis before committing. Update the [changelog](../../CHANGELOG.md) and its Chinese counterpart for user-visible changes.

The public origin rejects creating or updating branches other than `main`. Do not use `git push --all` or `git push --mirror`. For private collaboration, use a **separate private repository**, verify its access list, and give that remote a distinct name such as `private`. A public fork is suitable for public contributions, not private work.

After review and local checks, a maintainer can integrate locally:

```sh
git switch main
git pull --ff-only origin main
git merge --ff-only fix/wrist-retargeting
git push origin main
```

If `main` has advanced, reconcile the change on its development branch and rerun the affected checks before integration. Check the GitHub Actions run for the exact pushed commit. Delete a merged local branch with `git branch -d fix/wrist-retargeting` after verification. External contributions can still arrive as pull requests from public forks; private review stays in the separate private repository.

## Public repository rules

| Rule | Effect |
|:--|:--|
| **Public branches: main only** | Reject creation and updates of every branch except `main`; no bypass actors configured |
| **Main: preserve history** | Reject deletion and non-fast-forward updates of `main`; no bypass actors configured |
| Automatic branch deletion | Clean up merge branches if the publishing policy is later changed to permit them |

These are server-side rulesets, not a naming trick or a privacy boundary around old commits. Administrators can deliberately change repository settings. Review the [live rules](https://github.com/Moonweave-AI/virea/rules) when changing this workflow.

## Prepare a software release

1. Keep notable work in `Unreleased`, grouped under Added, Changed, Deprecated, Removed, Fixed or Security. Describe the user's new behavior and any migration step.
2. Choose the version using [Semantic Versioning](https://semver.org/). Keep package, CLI/API and documentation versions aligned. For the current `0.x` line, describe compatibility changes explicitly.
3. Run release validation on the exact source revision and wait for its CI checks. Create an immutable annotated `vMAJOR.MINOR.PATCH` tag only for an actual software release.
4. Move the release's entries from `Unreleased` into its version/date section; add a comparison link, matching GitHub Release notes and the tested artifacts.
5. Keep media tags such as `launch-film-2026-10` separate from software releases. Do not invent old tags or release dates while backfilling history.

The [current-main guide](../releases/current.en.md) explains today's source version. The historical `0.4.0` acceptance record describes its dated baseline, not an automatic release approval for all later changes.

## Recover a retired branch

The 2026-10-13 cleanup verified all remote branch tips and stored a complete local Git bundle under `.git/branch-archive/2026-10-13/heads.bundle`, with a ref inventory and SHA-256 record beside it. This backup is local, outside the versioned tree. Eight retired remote branches and eleven retired local branches were already contained in `main`; the two unique motion-optimization commits remain on local `codex/motion-optimization-baseline`.

To inspect the retained work, run `git log main..codex/motion-optimization-baseline`. To recover another tip, inspect `git bundle list-heads .git/branch-archive/2026-10-13/heads.bundle`, then fetch only the chosen archived ref into a new, well-named **local** branch. The backup path exists on the maintenance checkout, not on fresh clones.

## Sources behind the policy

- [GitHub flow](https://docs.github.com/en/get-started/using-github/github-flow): short descriptive branches, focused changes and review.
- [Git reference syntax](https://git-scm.com/docs/git-check-ref-format): legal Git branch names.
- [Repository visibility](https://docs.github.com/en/repositories/creating-and-managing-repositories/about-repositories): public/private access applies to the repository.
- [Ruleset controls](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets): creation, update, deletion and force-push restrictions.
- [Automatic branch deletion](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/managing-the-automatic-deletion-of-branches): merged-branch cleanup.
- [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and [Semantic Versioning](https://semver.org/): readable change records and explicit version meaning.

VIREA adopts these practices with a main-only public origin to suit its private-development workflow; the prefix list is a project convention.

<!-- BEGIN DOC FOOTER -->
---

[📚 Documentation map](../catalog.en.md) · [🛠️ Troubleshooting](../operations/troubleshooting.en.md) · [🤝 Contributing](../../CONTRIBUTING.md)
<!-- END DOC FOOTER -->

<!--
type: how-to
status: Active
owner: VIREA maintainers
created: 2026-10-13
updated: 2026-10-13
last_reviewed: 2026-10-13
review_cycle_days: 90
summary: Short branch names, local/private development, a main-only public origin and reproducible release notes.
canonical: doc/development/branching.en.md
related:
  - doc/development/branching.zh-CN.md
  - CONTRIBUTING.md
  - CHANGELOG.md
  - doc/releases/current.en.md
supersedes: []
superseded_by: []
-->
