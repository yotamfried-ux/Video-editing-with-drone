# Engineering OS Reference

This project uses Engineering OS as a read-only reference layer.

- Source repo: `https://github.com/yotamfried-ux/Engineering-OS`
- Default local path: `${ENGINEERING_OS_HOME:-$HOME/.engineering-os}`

Rules:

1. Do not vendor or copy the full Engineering OS repository into this project.
2. Do not commit generated graph reports, local tool paths, or machine-specific cache files.
3. Use this file only to document the expected reference location and usage contract.
4. Any changes to Engineering OS itself should be made through a separate PR in the Engineering OS repository.
