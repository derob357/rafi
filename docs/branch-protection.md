# Branch protection guidance

Protecting `main` ensures every change benefits from automated verification and human review. Follow these steps in GitHub Settings > Branches > Branch protection rules:

1. Create a rule that targets `main`.
2. Enable **Require pull request reviews before merging** and set **Require approvals** to at least 1. Keep **Dismiss stale pull request approvals when new commits are pushed** on so reviewers re-check changes.
3. Enable **Require status checks to pass before merging** and select the `CI` job produced by `.github/workflows/ci.yml`. If you add future workflows, include their checks here as well.
4. Turn on **Require linear history** to keep the commit graph simple.
5. (Optional) Enable **Require signed commits** if you want contributors to prove commit authenticity.
6. Check **Include administrators** so the above rules apply to maintainers.

These protections plus the `CI` workflow keep `main` fast-forwarded, reviewed, and automatically tested.