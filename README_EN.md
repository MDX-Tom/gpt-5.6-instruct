<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/images/gpt-instruct-hero-dark.webp" />
  <source media="(prefers-color-scheme: light)" srcset="docs/images/gpt-instruct-hero-light.webp" />
  <img src="docs/images/gpt-instruct-hero-light.webp" alt="gpt-instruct prompts and evaluation toolkit" width="70%" />
</picture><br />
<img src="docs/images/readme-spacer.png" alt="" width="1" height="5" />

<p>
  <a href="https://github.com/MDX-Tom/gpt-instruct/stargazers"><img src="https://img.shields.io/github/stars/MDX-Tom/gpt-instruct?logo=github&label=Stars" alt="GitHub Stars" /></a>
  <img src="https://img.shields.io/badge/Models-gpt--6--astra_%7C_gpt--5.6--sol-7c3aed" alt="gpt-6-astra and gpt-5.6-sol" />
  <a href="gpt-5.6-sol-v45.zip"><img src="https://img.shields.io/badge/Stable-gpt--5.6--sol--v45-0f766e" alt="gpt-5.6-sol-v45" /></a>
  <a href="gpt-6-astra-v1.zip"><img src="https://img.shields.io/badge/Release-gpt--6--astra--v1-b07d62" alt="gpt-6-astra-v1" /></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/Python-3.8%2B-3776AB?logo=python&logoColor=white" alt="Python 3.8+" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/github/license/MDX-Tom/gpt-instruct?color=f59e0b" alt="MIT License" /></a>
</p>

<p>
  <a href="README_EN.md"><img src="https://img.shields.io/badge/lang-English-blue.svg" alt="English" /></a>
  <a href="README.md"><img src="https://img.shields.io/badge/语言-简体中文-red.svg" alt="简体中文" /></a>
</p>

<h1>gpt-instruct</h1>

</div>

<!-- README_SYNC: Keep README.md and README_EN.md synchronized; publish paired localized diagrams. -->

## Overview

`gpt-instruct` provides Codex instruction prompts and a reproducible evaluation toolkit focused on first-turn execution, process continuity, artifact verification, and runnable rollback.

The project now maintains two long-term product lines:

| Version | Status | Description |
|---|---|---|
| **gpt-5.6-sol-v45** | Current stable production release | Preserves the original v45 prompt bytes; only its filename and project branding are normalized |
| **gpt-6-astra-v1** | First formal gpt-6-astra release | Byte-identical to the epoch2 best measured revision e2b19; A4 is 3/4 and B execution is 7/8, with all nine returned turns passing manual review |

Each development epoch contains at most 20 versions named `gpt-6-astra-v1-e<epoch>b<attempt>`. Prereleases use `gpt-6-astra-v1-rcN`. e1b5 was released as `v1-rc1` and is now archived; e2b19 was promoted by release decision to the first formal `v1`. All new runs use `gpt-6-astra` at `medium` reasoning, and every candidate prompt is limited to 8,000 UTF-8 bytes.

> **Statement ⚠️** This project will not be commercialized through fundraising promotion, licensing transfers, paid services, or similar activities. Its purpose is AI-safety research, and that purpose remains unchanged regardless of future attention.

> [!IMPORTANT]
> Custom model instructions can create account risk. This project uses the official Codex configuration mechanism; it does not patch binaries, intercept traffic, or tamper with processes. Use it only in environments you are entitled to operate and at your own risk.

## Architecture 🏗️

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/images/project-architecture-en-dark.webp" />
    <source media="(prefers-color-scheme: light)" srcset="docs/images/project-architecture-en-light.webp" />
    <img alt="gpt-6-astra-v1 prompt iteration, release gates, and production runtime" src="docs/images/project-architecture-en-light.webp" width="100%" />
  </picture>
</p>

`gpt-6-astra-v1` follows independent 20-version epochs and A→B→C release gates, while `gpt-5.6-sol-v45` remains the deployable stable line. Both lines share test banks, failure analysis, isolated execution, and artifact-evidence rules, but scores are compared only under the same model, reasoning level, and method identity.

## Version Iteration Trends 📈

### gpt-5.6-sol

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/images/gpt56-sol-version-pass-trend-en-dark.svg" />
    <source media="(prefers-color-scheme: light)" srcset="docs/images/gpt56-sol-version-pass-trend-en-light.svg" />
    <img alt="gpt-5.6-sol prompt-version pass trend" src="docs/images/gpt56-sol-version-pass-trend-en-light.svg" width="92%" />
  </picture>
</p>

### gpt-6-astra

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/images/gpt6-astra-v1-ab-trend-en-dark.svg" />
    <source media="(prefers-color-scheme: light)" srcset="docs/images/gpt6-astra-v1-ab-trend-en-light.svg" />
    <img alt="gpt-6-astra A/B iteration trend from v50 through e2b19" src="docs/images/gpt6-astra-v1-ab-trend-en-light.svg" width="92%" />
  </picture>
</p>

The `gpt-6-astra` chart plots v50, e1b1–e1b5, e2b12, e2b15, and e2b19 under the current A4 denominator; e1b5 is labeled `v1-rc1` and e2b19 is labeled `v1`. B plots only measured results: v50 is the historical 26/66 composite, while the other four points are `execution_completion` scores of 6/8, 4/8, 5/8, and 7/8. The v50 method/worker identity and B scope differ, so it is trend context only.

## Stable Release and Quick Start 📦

Current stable ZIP: [`gpt-5.6-sol-v45.zip`](gpt-5.6-sol-v45.zip)  
First formal gpt-6-astra ZIP: [`gpt-6-astra-v1.zip`](gpt-6-astra-v1.zip) (contains `gpt-6-astra-v1.md`; A4 3/4; B execution 7/8; later B families/C not run)

```text
gpt-5.6-sol-v45.zip       SHA256  c86c2c6d20a4d1155d87422f485eb37b77539132270918c002b5d8237a5adf54
gpt-6-astra-v1.zip         SHA256  054edb6fa8a6edd2d144c8582756df3179a85481bcb6696d8b730177521b1de1
```

```bash
git clone https://github.com/MDX-Tom/gpt-instruct.git
cd gpt-instruct

# Preview stable without changing configuration
python3 codex-instruct.py --apply --version gpt-5.6-v45 --dry-run

# Deploy stable (--apply without --version is equivalent)
python3 codex-instruct.py --apply --version gpt-5.6-v45

# Deploy the formal gpt-6-astra-v1 release
python3 codex-instruct.py --apply --version gpt-6-v1
```

Run the script without arguments for the interactive menu. Additional commands:

```bash
# Select a Codex home
python3 codex-instruct.py --apply --codex-dir ~/.codex

# Deploy a custom ZIP or Markdown file
python3 codex-instruct.py --file ./custom-instructions.zip

# Restore only the model_instructions_file managed by this project
python3 codex-instruct.py --reset
```

The script records pre-deployment state. `--reset` preserves provider, model, authentication, and all unrelated configuration. Full snapshots are for manual emergencies and require explicit `--restore-snapshot` use.

### Manual Deployment and Rollback

Extract the stable ZIP, copy its prompt into `CODEX_HOME`, and add this top-level entry to `config.toml`:

```toml
model_instructions_file = "./gpt-5.6-sol-v45.md"
```

To roll back, remove or comment out the entry; optionally delete the matching Markdown file afterward.

## A / B / C Release Gates 🧪

| Tier | Scope | Passing requirement |
|---|---|---|
| **A** | 3 original cases + 1 exact-workdir continuation probe | 3/4 cases, 3/4 turns, every declared artifact gate, and an unchanged probe target |
| **B** | 66 Issue-regression cases / 74 turns | 66/66 cases, 74/74 turns, and every declared artifact gate |
| **C** | 120 original `medium` cases | 120/120; runs only after A and B pass completely |

Every new candidate runs A first, proceeds through B family by family only after meeting the current admission rule, and starts C only after the hard A and B gates pass. This v1 is the formal snapshot produced by explicitly promoting e2b19; the table still preserves the fact that later B families and C were not run rather than rewriting the evidence to match the version name.

Evaluation script names retain the `gpt56_sol` prefix for historical-result and automation compatibility. New development runs must explicitly pass `--model gpt-6-astra --reasoning medium`.

```bash
for archive in scripts/*.zip; do unzip -o "$archive" -d scripts; done

python3 scripts/run_gpt56_sol_issue_regression.py --dry-run \
  --model gpt-6-astra --reasoning medium
python3 scripts/verify_gpt56_sol_regression_scoring.py
python3 -m unittest discover -s unit-tests -q
```

See the [Chinese comparison guide](docs/comparison-tests.md) and [English comparison guide](docs/comparison-tests-en.md) for methods, historical evidence, and failure categories.

## Repository Layout 🗂️

```text
gpt-instruct/
├── README.md / README_EN.md              # Chinese and English home pages
├── codex-instruct.py                     # Version selection, deployment, and rollback
├── sync-archives.py                      # Source-to-ZIP synchronization
├── gpt-5.6-sol-v45.md/.zip               # Current stable production release
├── gpt-6-astra-v1.md/.zip                # First formal release, byte-identical to e2b19
├── historical-versions/                  # Historical releases
├── scripts/*.zip                         # Evaluation, scoring, and reporting tools
├── tests/                                # A/B/C banks and manifest
├── docs/                                 # Methods, charts, and architecture
└── reports/                              # Local run evidence; ignored by default
```

The external-maintainer candidate directory `gpt-5.6-instruct-darad/` is read-only evaluation input and is explicitly excluded from this repository's Git tracking scope.

## Maintenance Principles

- Preserve raw historical outputs, method SHA values, model, reasoning, and transport; never merge scores across identities.
- Record real model failures separately from network, capacity, account, and provider-policy interruptions.
- Run evaluations only with disposable HOME / CODEX_HOME / XDG / TMPDIR state and synthetic fixtures.
- Every modification candidate includes a modified artifact, diff, verification record, and runnable rollback.
- Do not overfit the general prompt to one case phrase or one-off answer.

## Star History ⭐

<p align="center">
  <a href="https://www.star-history.com/?repos=MDX-Tom%2Fgpt-instruct&type=date&legend=top-left">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="https://mdx-tom.github.io/gpt-instruct/star-history-dark.svg" />
      <source media="(prefers-color-scheme: light)" srcset="https://mdx-tom.github.io/gpt-instruct/star-history-light.svg" />
      <img alt="Star History Chart" src="https://mdx-tom.github.io/gpt-instruct/star-history-light.svg" width="80%" />
    </picture>
  </a>
</p>

## Acknowledgements 🙏

This project continues the open-source work of [yynxxxxx/Codex-5.5-codex-instruct-5.5](https://github.com/yynxxxxx/Codex-5.5-codex-instruct-5.5). Thanks to its authors and contributors.
