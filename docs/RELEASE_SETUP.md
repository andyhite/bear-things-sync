# Release Workflow Setup Guide

This guide walks you through the one-time setup required to enable automated publishing to PyPI and GitHub Releases.

## Prerequisites

- [x] GitHub repository with publish workflow (already configured)
- [ ] PyPI account
- [ ] Admin access to GitHub repository

## Step 1: Create PyPI Account

If you don't already have a PyPI account:

1. Go to https://pypi.org/account/register/
2. Create an account with email verification
3. Enable 2FA (required for trusted publishing)

## Step 2: Configure PyPI Trusted Publishing

Trusted publishing allows GitHub Actions to publish without storing API tokens.

### Option A: Pending Publisher (Before First Release)

If you haven't published `bear-things-sync` to PyPI yet:

1. Go to https://pypi.org/manage/account/publishing/
2. Scroll to "Pending publishers"
3. Click "Add a new pending publisher"
4. Fill in the form:
   - **PyPI Project Name**: `bear-things-sync`
   - **Owner**: `andyhite`
   - **Repository name**: `bear-things-sync`
   - **Workflow name**: `publish.yml`
   - **Environment name**: `release` (leave blank if not using environments)
5. Click "Add"

### Option B: Existing Project (After First Release)

If `bear-things-sync` already exists on PyPI:

1. Go to https://pypi.org/manage/project/bear-things-sync/settings/publishing/
2. Click "Add a new publisher"
3. Fill in the same details as Option A above
4. Click "Add"

## Step 3: Configure GitHub Environment (Optional but Recommended)

This adds a manual approval step before publishing to prevent accidental releases.

1. Go to https://github.com/andyhite/bear-things-sync/settings/environments
2. Click "New environment"
3. Name it `release`
4. Check "Required reviewers"
5. Add yourself as a reviewer
6. Click "Save protection rules"

**Note**: If you skip this step, remove `environment: release` from `.github/workflows/publish.yml`

## Step 4: Verify Conventional Commit Format

The workflow uses conventional commits to determine version bumps. Make sure your commits follow this format:

```
<type>: <description>

Examples:
  feat: add uninstall command
  fix: prevent duplicate todos
  docs: update README installation steps
  chore: bump dependencies
```

**Important commit types**:
- `feat:` → Minor version bump (1.0.0 → 1.1.0)
- `fix:` → Patch version bump (1.0.0 → 1.0.1)
- `BREAKING CHANGE:` → Major version bump (1.0.0 → 2.0.0)

See [Conventional Commits](https://www.conventionalcommits.org/) for full specification.

## Step 5: Trigger Your First Release

Once setup is complete:

1. Go to https://github.com/andyhite/bear-things-sync/actions/workflows/publish.yml
2. Click "Run workflow" dropdown
3. Select branch `main`
4. Click green "Run workflow" button
5. If using environment protection, approve the deployment when prompted
6. Monitor the workflow run for any errors

**The workflow will**:
- Analyze commits since last release
- Determine version bump (patch/minor/major)
- Update `pyproject.toml` with new version
- Generate changelog from commits
- Create git tag (e.g., `v1.0.1`)
- Build package
- Publish to PyPI
- Create GitHub release with changelog

## Troubleshooting

### "Trusted publishing not configured"

**Cause**: PyPI trusted publishing not set up correctly.

**Solution**:
- Verify the PyPI project name matches exactly: `bear-things-sync`
- Verify the workflow filename matches exactly: `publish.yml`
- Verify the repository owner/name matches: `andyhite/bear-things-sync`
- If using environments, verify the name matches: `release`

### "No version bump detected"

**Cause**: No commits with `feat:` or `fix:` since last release.

**Solution**:
- Ensure you have commits that warrant a release
- Use `feat:` for new features or `fix:` for bug fixes
- Check that commits follow conventional format

### "Package already exists on PyPI"

**Cause**: Version already published (python-semantic-release failed to bump version).

**Solution**:
- Check the git tags: `git tag -l`
- The workflow only analyzes commits since the last tag
- If you need to re-release, delete the tag and try again

### Environment approval stuck

**Cause**: Waiting for manual approval but no one is approving.

**Solution**:
- Go to Actions → Click the workflow run → Click "Review deployments" → Approve
- Or remove environment protection from GitHub settings

## Alternative: Token-Based Publishing

If you prefer using API tokens instead of trusted publishing:

1. Go to https://pypi.org/manage/account/token/
2. Create a new API token scoped to `bear-things-sync` project
3. Copy the token (starts with `pypi-`)
4. Go to GitHub repository → Settings → Secrets and variables → Actions
5. Click "New repository secret"
6. Name: `PYPI_TOKEN`
7. Value: paste the token
8. In `.github/workflows/publish.yml`, replace the PyPI publish step with:
   ```yaml
   - name: Publish to PyPI
     env:
       TWINE_USERNAME: __token__
       TWINE_PASSWORD: ${{ secrets.PYPI_TOKEN }}
     run: uv pip install twine && twine upload dist/*
   ```

## Next Steps

After your first successful release:

- Visit https://pypi.org/project/bear-things-sync/ to see your package
- Install it: `pip install bear-things-sync`
- Check GitHub releases: https://github.com/andyhite/bear-things-sync/releases
- Consider adding a release badge to README.md

## Maintenance

For future releases, just:

1. Make commits using conventional format
2. Go to Actions → Publish → Run workflow
3. Approve if using environment protection
4. Done!

The workflow handles everything else automatically.
