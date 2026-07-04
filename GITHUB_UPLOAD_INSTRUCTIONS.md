# GitHub Upload Instructions

## Create Private Repo

1. Go to GitHub.
2. Select **New repository**.
3. Name the repository `agent-os`.
4. Set visibility to **Private**.
5. Do not initialize with README, license, or `.gitignore`.

## Upload With GitHub Web

1. Open the new empty `agent-os` repository.
2. Choose **uploading an existing file**.
3. Drag the contents of `agent-os-github-ready/` into the upload area.
4. Use commit message: `Initial Agent OS knowledge base draft`.
5. Commit to the default branch.

## Upload With GitHub Desktop

1. Create or clone the empty private `agent-os` repository.
2. Copy all files from `agent-os-github-ready/` into the local repo folder.
3. Review the changed files.
4. Commit with: `Initial Agent OS knowledge base draft`.
5. Publish or push to GitHub.

## Upload With Command Line

```bash
cd /path/to/agent-os-github-ready
git init
git add .
git commit -m "Initial Agent OS knowledge base draft"
git branch -M main
git remote add origin git@github.com:YOUR_ORG_OR_USER/agent-os.git
git push -u origin main
git tag v1.0.0-draft
git push origin v1.0.0-draft
```

## Recommended Metadata

- Repository name: `agent-os`
- Visibility: Private
- Initial commit: `Initial Agent OS knowledge base draft`
- Draft tag: `v1.0.0-draft`
