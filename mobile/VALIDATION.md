# Mobile validation

Every change under `mobile/` must pass:

```bash
npm ci
npm run type-check
```

GitHub Actions runs the same check for mobile pull requests through `.github/workflows/mobile-check.yml`.
