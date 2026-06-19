## Suggested classification approach

Use **multiple signals**, not a single date field. A repository can be old but still important if it has dependents, downloads, releases, or is a production/service repo. I’d recommend producing three labels:

- **Dead** — safe candidate for archival/deletion after owner review.
- **Stale** — inactive or neglected, but may still be used.
- **No longer used** — likely superseded, deprecated, fork-only, POC/test/template, or has no current consumers.

Also add a fourth operational label:

- **Needs manual review** — high-risk or ambiguous repo.

---

## Core signals available in the spreadsheet

Good columns to use:

| Signal | Columns |
|---|---|
| Explicit retirement | `archived`, `npm is deprecated` |
| Activity | `last commit date`, `pushed at`, `last release date`, `last edit date` |
| Usage by local repos | `npmjs used by`, `github dependents` |
| Package activity | `npmjs downloads last year`, `npmjs last published` |
| Project health / neglect | `open issues count`, `open prs count` |
| Repository role | `is fork`, `repo name`, `organization name`, `language` |
| Release/value signal | `github release count`, `github downloads` |
| Human involvement | `github contributors` |
| Commit history depth | `commit count` |

---

# Recommended rules

## 0. npmjs module lifecycle classifications

Published npm modules should be classified separately from their backing GitHub repositories. A repository may be stale or archived while its npm package is still installed by downstream users. Conversely, a package may remain published on npmjs even though it is obsolete, superseded, or unsafe to continue using.

Prefer **deprecating** npm packages over unpublishing them. Deprecation preserves installability for existing lockfiles while warning users to migrate.

### npmjs classifications

Use these additional labels for published npm modules:
```
plain text
Keep - npm package in use
Deprecate npm package candidate
Deprecated npm package
Manual review - npm package
```
### Rule P1 — Already deprecated npm package
```
plain text
npmjs package name is not empty
AND npm is deprecated = True
```
**Classification:** `Deprecated npm package`

The package is already explicitly marked as deprecated on npmjs.

**Recommended action:** Confirm the deprecation message points to the correct replacement, migration path, or explanation.

---

### Rule P2 — Published package with no detected use
```
plain text
npmjs package name is not empty
AND npm is deprecated is not True
AND npmjs used by is empty
AND github dependents is empty
AND npmjs downloads last year is empty or 0
```
**Classification:** `Deprecate npm package candidate`

A published package with no detected local consumers, no GitHub dependents, and no download activity is a strong candidate for npm deprecation.

**Recommended action:** Deprecate with a clear message, especially if the source repository is also stale, archived, or marked as no longer used.

---

### Rule P3 — Stale npm package with weak usage
```
plain text
npmjs package name is not empty
AND npm is deprecated is not True
AND npmjs last published older than 24 months
AND npmjs downloads last year < 100
AND npmjs used by is empty
```
**Classification:** `Deprecate npm package candidate`

The package has not been published recently and has little evidence of current use.

**Recommended action:** Review for replacement package, then deprecate if no owner confirms ongoing use.

---

### Rule P4 — Superseded or obsolete npm package
```
plain text
npmjs package name is not empty
AND npm is deprecated is not True
AND (
  repo name contains old, legacy, deprecated, obsolete, archive, backup
  OR npmjs package name contains old, legacy, deprecated, obsolete, archive, backup
)
```
**Classification:** `Deprecate npm package candidate`

Package or repository naming suggests the module has been replaced or intentionally retired.

**Recommended action:** Deprecate and include the replacement package name when known.

---

### Rule P5 — npm package backed by archived repository
```
plain text
npmjs package name is not empty
AND archived = True
AND npm is deprecated is not True
```
**Classification:** `Deprecate npm package candidate`

If the source repository is archived, the npm package is unlikely to receive maintenance. This rule is evaluated **before** the security/build-tool rule (P8), so an archived package is always classified here regardless of its name.

**Exception:** If the package has significant downloads or known production usage, classify as `Manual review - npm package`.

---

### Rule P6 — npm package has meaningful use
```
plain text
npmjs package name is not empty
AND (
  npmjs used by is not empty
  OR github dependents is not empty
  OR npmjs downloads last year >= 1000
)
```
**Classification:** `Keep - npm package in use`

The package has evidence of active or historical downstream use.

**Recommended action:** Do not deprecate automatically. If stale, assign an owner, publish a maintenance update, or create a migration plan.

---

### Rule P7 — npm package has low but nonzero usage
```
plain text
npmjs package name is not empty
AND npm is deprecated is not True
AND npmjs downloads last year >= 1
AND npmjs downloads last year < 1000
AND npmjs used by is empty
```
**Classification:** `Manual review - npm package`

Low download counts may represent real users, automated installs, CI, mirrors, or accidental usage.

**Recommended action:** Review package purpose, README, repository status, and replacement availability before deprecating.

---

### Rule P8 — Security-sensitive or build-tool package
```
plain text
npmjs package name is not empty
AND archived = False
AND repo name or npmjs package name contains:
  auth, login, token, crypto, security, deploy, build, cli, config, eslint, babel, webpack, rollup
```
**Classification:** `Manual review - npm package`

Some packages can have outsized impact even with low download counts, especially CLI tools, build tools, authentication utilities, or security-related modules.

**Note:** This rule only applies when the backing repository is not archived. Archived repositories are handled by Rule P5 first.

**Recommended action:** Require owner/security review before deprecation.

---

### npm deprecation message guidance

When deprecating a package, include a clear message:
```
plain text
This package is no longer maintained. Please migrate to <replacement-package> or contact <team/contact> if you still depend on it.
```
If there is no replacement:
```
plain text
This package is no longer maintained and should not be used for new work.
```
Avoid unpublishing unless there is a strong security, legal, or accidental-publication reason.

---


## 1. Automatically mark as **Dead**

A repo should be considered **Dead** if any of these are true:

### Rule D1 — Archived repositories

```plain text
archived = True
```


**Classification:** `Dead`

Archived repos are already explicitly marked as inactive. They may still be historically useful, but operationally they are dead.

**Exception:** If the repo has high release downloads, active external dependents, or is a historically important source artifact, mark as `Dead - keep archived`.

---

### Rule D2 — Deprecated npm package with no recent activity

```plain text
npm is deprecated = True
AND last commit date older than 24 months
```


**Classification:** `Dead`

A deprecated npm package with no meaningful recent maintenance is a strong dead signal.

---

### Rule D3 — Stub or experiment with very few commits and no recent activity

```plain text
commit count <= 5
AND last commit date older than 3 years
AND npmjs used by is empty
AND github dependents is empty
AND github downloads = 0
AND github release count = 0
```

**Classification:** `Dead candidate`

A repository with five or fewer commits that has had no activity in over three years with no evidence of use was almost certainly a stub, experiment, or scratch repo that never developed into a real project.

---

### Rule D4 — Very old and no evidence of use

```plain text
last commit date older than 5 years
AND archived = False
AND npmjs used by is empty
AND github dependents is empty
AND github downloads = 0
AND github release count = 0
AND commit count < 50
```


**Classification:** `Dead candidate`

This catches old one-off scripts, prototypes, obsolete service code, old mobile apps, old DokuWiki/MediaWiki tooling, and unused experiments.

**Note:** Repositories with 50 or more commits are excluded from this rule — they represent meaningful development history and fall through to `Stale` instead, which requires human review before action.

---

### Rule D5 — Old fork with no local use

```plain text
is fork = True
AND last commit date older than 3 years
AND npmjs used by is empty
AND github dependents is empty
AND github downloads = 0
```


**Classification:** `Dead candidate`

Forks are often snapshots or experiments. If they are old and not depended on, they are strong archive candidates.

**Exception:** If the fork is a maintained organizational fork of an upstream dependency, mark as `Manual review`.

---

### Rule D6 — Obvious POC/test/demo/template with old activity and no dependents

```plain text
repo name contains any of:
  poc, proof, demo, test, sample, example, template, old, hackathon, playground

AND last commit date older than 2 years
AND npmjs used by is empty
AND github dependents is empty
```


**Classification:** `Dead candidate`

This is especially useful for names like `*-poc`, `*-demo`, `*-old`, `Example*`, `sample-*`, `hello-*`, and old QA/test repos.

---

### Rule D7 — Empty or metadata-only repo with no recent activity

```plain text
language is empty
AND github release count = 0
AND github downloads = 0
AND npmjs package name is empty
AND last commit date older than 3 years
```


**Classification:** `Dead candidate`

Many empty-language repos are docs, config, test data, or metadata repos. They may still matter, so this should be a **candidate**, not automatic deletion.

---

## 2. Mark as **Stale**

A repo is **Stale** if it appears inactive or under-maintained but still has some evidence of value.

### Rule S1 — No commits in 18 months

```plain text
last commit date older than 18 months
AND archived = False
```


**Classification:** `Stale`

This should be the broadest stale rule.

---

### Rule S2 — npm package not published recently

```plain text
npmjs package name is not empty
AND npmjs last published older than 18 months
AND npm is deprecated is not True
```


**Classification:** `Stale package`

This is useful for libraries that are still installed but no longer published.

---

### Rule S3 — Has dependents but no recent maintenance

```plain text
last commit date older than 18 months
AND (
  npmjs used by is not empty
  OR github dependents is not empty
  OR npmjs downloads last year > 0
)
```


**Classification:** `Stale but used`

These are risky to archive. They may need replacement, maintenance, or ownership assignment.

---

### Rule S4 — Many open PRs or issues but old activity

```plain text
last commit date older than 12 months
AND (
  open prs count >= 5
  OR open issues count >= 20
)
```


**Classification:** `Stale / neglected`

Open PRs and issues can indicate unresolved work or abandoned maintenance.

---

### Rule S5 — Releases are old compared to commits

```plain text
last commit date within last 24 months
AND last release date older than 24 months
AND github release count > 0
```


**Classification:** `Stale release process`

The repo may be active, but releases may be abandoned.

---

## 3. Mark as **No longer used**

This category should focus on replacement/supersession and lack of consumers.

### Rule N1 — Repo name indicates replacement

```plain text
repo name contains:
  old, legacy, deprecated, obsolete, archive, backup
```


**Classification:** `No longer used candidate`

Examples of common strong indicators:

- `*-old`
- `*-legacy`
- `old-*`
- `*-backup`
- `*-deprecated`

---

### Rule N2 — POC/demo/test/template repo with newer related repo

```plain text
repo name contains:
  poc, demo, example, sample, template, playground, test

AND last commit date older than 12 months
```


**Classification:** `No longer used candidate`

This is slightly different from `Dead`: a repo can be “no longer used” even if it was intentionally kept for reference.

---

### Rule N3 — Fork of another active repo but no unique consumers

```plain text
is fork = True
AND npmjs used by is empty
AND github dependents is empty
```


**Classification:** `No longer used candidate`

If the fork exists only as a snapshot and is not actively maintained, it is probably no longer used.

---

### Rule N4 — Package is not consumed by any local repos

```plain text
npmjs package name is not empty
AND npmjs used by is empty
AND github dependents is empty
AND npmjs downloads last year is empty or 0
```


**Classification:** `No longer used candidate`

This catches packages that exist in npm metadata but have no detected current consumers.

---

### Rule N5 — Superseded by same-name or renamed repo

Use name heuristics:

```plain text
repo name has suffix:
  -old, -legacy, -poc, -v1, -v2, -test, -demo

AND another repo exists with same base name or obvious replacement name
```


**Classification:** `No longer used candidate`

Examples of replacement patterns:

```plain text
gateway-edit-POC -> gateway-edit
dcs-home-page-old -> dcs-homepage
old-tx-manager -> tx-manager or newer tx-* repos
```


This rule benefits from manual confirmation.

---

## 4. Mark as **Keep / Active**

Before marking anything dead, apply keep rules.

### Rule K0 — No last commit date (protected or private repository)

```plain text
last commit date is empty
```

**Classification:** `Protected private`

The repository has no accessible last commit date. This typically indicates a private or organization-restricted repository where commit history is not publicly available or was not retrievable during data collection.

**Recommended action:** Review manually with an account that has full organizational access. Do not treat as dead or stale — the absence of data is not evidence of inactivity.

---

### Rule M5 — Used as a git submodule

```plain text
is submodule of is not empty
```

**Classification:** `Manual review`

The repository is referenced as a git submodule by at least one other repository in the fetched set. This is a direct code dependency regardless of the repository's own commit activity or npm usage signals.

**Recommended action:** Identify which repositories depend on this submodule before archiving, renaming, or removing it. Submodule dependencies are not captured by npm usage fields.

---

### Rule K1 — Recently active

```plain text
last commit date within last 12 months
```


**Classification:** `Active`

---

### Rule K2 — Used by other local packages

```plain text
npmjs used by is not empty
```


**Classification:** `Keep - locally used`

Even if the repo is old, local use means it should not be archived without migration.

---

### Rule K3 — Has GitHub dependents

```plain text
github dependents is not empty
```


**Classification:** `Keep or manual review`

This indicates external or internal dependency visibility.

---

### Rule K4 — Significant npm downloads

Suggested thresholds:

```plain text
npmjs downloads last year >= 1000
```


**Classification:** `Keep - package in use`

Higher-confidence thresholds:

```plain text
>= 10,000 = definitely used
1,000–9,999 = likely used
100–999 = possibly used
1–99 = weak usage signal
```


---

### Rule K5 — Production or core repo name

Mark as `Manual review`, not dead, if the repo name contains important product/service terms:

```plain text
gateway
door43
dcs
translationCore
tc-create
obs-app
bt-servant
tx-job
catalog
content-validation
scripture
resource
```


Some of these may still be stale, but they are likely important.

---

## 5. Manual review rules

Some repos should not be automatically classified as dead even if they look stale.

### Rule M1 — High issue count

```plain text
open issues count >= 50
```


**Classification:** `Manual review`

A high issue count may mean the repo is important but neglected.

---

### Rule M2 — High release/download/commit history

```plain text
github release count >= 10
OR github downloads >= 100
OR commit count >= 100
```


**Classification:** `Manual review`

A high commit count indicates sustained development effort. Repositories with 100 or more commits represent real investment and should not be automatically classified as dead or stale without a human review, even if they have no recent activity, releases, or downloads.

---

### Rule M3 — Many contributors

```plain text
github contributors count >= 5
```


**Classification:** `Manual review`

Many contributors can indicate a historically significant or shared project.

---

### Rule M4 — Recent metadata update but old code

```plain text
last edit date within last 12 months
AND last commit date older than 3 years
```


**Classification:** `Manual review`

Someone may still be managing the repo settings, topics, issues, or visibility.

---

# Suggested scoring model

Instead of only hard rules, assign a score. This makes the result easier to sort.

## Dead score

Add points:

| Condition | Points |
|---|---:|
| `archived = True` | +100 |
| `npm is deprecated = True` | +40 |
| `last commit date > 5 years old` | +35 |
| `last commit date > 3 years old` | +25 |
| `last commit date > 2 years old` | +15 |
| `is fork = True` | +15 |
| No `npmjs used by` | +15 |
| No `github dependents` | +15 |
| `github release count = 0` | +10 |
| `github downloads = 0` | +10 |
| Repo name contains `old`, `legacy`, `poc`, `demo`, `test`, `sample`, `example`, `template`, `hackathon`, `playground` | +20 |
| `language` empty | +5 |

Subtract points:

| Condition | Points |
|---|---:|
| `last commit date <= 12 months old` | -60 |
| `npmjs used by` not empty | -40 |
| `github dependents` not empty | -35 |
| `npmjs downloads last year >= 10000` | -35 |
| `npmjs downloads last year >= 1000` | -25 |
| `github release count >= 10` | -20 |
| `github downloads >= 100` | -20 |
| `commit count >= 100` | -20 |
| `open prs count > 0` | -5 |
| `open issues count > 0` | -5 |

Then classify:

| Score | Classification |
|---:|---|
| `>= 90` | Dead |
| `60–89` | Dead candidate |
| `35–59` | Stale / no longer used candidate |
| `10–34` | Needs review |
| `< 10` | Active / keep |

---

# Recommended final labels

I’d use these labels in the spreadsheet:

```plain text
Active
Keep - locally used
Keep - externally used
Keep - package in use
Keep - npm package in use
Stale
Stale but used
Stale package
No longer used candidate
Deprecate npm package candidate
Deprecated npm package
Dead candidate
Dead - archived
Dead - deprecated
Manual review
```


---

# Practical rule order

Apply rules in this order:

1. **Normalize dates** and calculate age in months from `last commit date`, `pushed at`, `last release date`, and `npmjs last published`.
2. Apply **Keep** rules first.
3. Apply **Dead** rules.
4. Apply **Stale** rules.
5. Apply **No longer used** naming/replacement rules.
6. Apply **Manual review override** for high-risk repos.
7. Sort by score descending.

---

# Suggested conservative policy

For an organization repo cleanup, I would avoid deleting anything immediately. Recommended actions:

| Classification | Action |
|---|---|
| `Dead - archived` | Leave archived unless there is a reason to delete |
| `Dead candidate` | Archive after owner review |
| `No longer used candidate` | Archive or rename/document replacement |
| `Stale but used` | Assign owner or plan migration |
| `Stale package` | Decide whether to publish update, deprecate, or archive |
| `Manual review` | Ask product/engineering owner |
| `Active` | Keep |

# npmjs-specific classifications

| Classification | When to use | Recommended action |
|---|---|---|
| `Deprecate npm package candidate` | Published npm module has no detected local usage, no GitHub dependents, no meaningful download activity, is stale, archived, obsolete, or likely superseded. | Deprecate the npm package with a clear message. Include a replacement package or migration path when known. |
| `Deprecated npm package` | Package is already marked as deprecated on npmjs. | Confirm the deprecation message is accurate and points users to the correct replacement, migration path, or explanation. |
| `Keep - npm package in use` | Package has evidence of use, such as local consumers, GitHub dependents, or significant npm downloads. | Do not deprecate automatically. Assign an owner, maintain it, or create a planned migration if the package is stale. |
| `Manual review - npm package` | Package has low but nonzero usage, unclear ownership, possible external usage, or security/build-tool relevance. | Require owner, engineering, or security review before deprecating. Check README, repository status, replacement availability, and downstream consumers. |
| `Needs migration path` | Package should probably be deprecated, but users need a documented replacement or upgrade path first. | Document the replacement, migration steps, and contact path before publishing the npm deprecation notice. |

---

## Best first-pass filters

If you want quick filters to find likely cleanup candidates, start with:

```plain text
archived = True
```


Then:

```plain text
last commit date < 2021-05-16
AND archived = False
AND npmjs used by is empty
AND github dependents is empty
```


Then:

```plain text
is fork = True
AND last commit date < 2023-05-16
AND npmjs used by is empty
AND github dependents is empty
```


Then:

```plain text
repo name contains old/poc/demo/test/sample/example/template
AND last commit date < 2024-05-16
```


These should surface the most obvious dead or no-longer-used repositories with relatively low risk.