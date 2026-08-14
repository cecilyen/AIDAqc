# OneDrive Compatibility

The repository was migrated to the work/school OneDrive checkout at
`%USERPROFILE%\OneDrive - National Institutes of Health\Codex\AIDAqc_Mod`.
The original checkout in `%USERPROFILE%\Documents\AIDAqc_Mod` is retained as a
separate recovery copy.

## Status

On 2026-08-14, the complete checkout, including hidden Git metadata, passed the
public Microsoft OneDrive checks implemented by
`scripts/check_onedrive_compatibility.py`. The audit found no prohibited names,
unsupported symbolic links, `.tmp` files, oversized files, or path-limit
violations. A separate Windows check confirmed that the checkout's
case-sensitive directory attribute is disabled, as OneDrive requires, and a
PowerShell link scan found no symbolic links or junctions.

This result is a compatibility check, not an NIH compliance certification.
Tenant-specific blocked extensions, sensitivity labels, data loss prevention,
retention, sharing, and records-management controls are configured by NIH and
cannot be inferred from the local files. Confirm those controls with the NIH
Microsoft 365 or IT administrator before storing controlled or sensitive data.

## Run the Audit

From PowerShell 7:

```powershell
uv run python -OO scripts/check_onedrive_compatibility.py `
  "$env:USERPROFILE\OneDrive - National Institutes of Health\Codex\AIDAqc_Mod"
```

The command returns exit code `0` when no blocking public OneDrive restriction
is found, `1` for compatibility violations, and `2` for an invalid command or
path. It checks hidden files and `.git` by design.

## Public Rules Checked

The audit enforces Microsoft's published filename, reserved-name, temporary
file, symbolic-link, 250 GB file-size, 255-character segment, 400-character
cloud-path, and 520-character local sync-path restrictions. It also warns about
the 260-character File Explorer/Office desktop limit, tenant-dependent `#` and
`%` support, semicolons in Office folder paths, and trees above Microsoft's
300,000-item performance recommendation.

See Microsoft's current documentation for the authoritative limits:

- [Restrictions and limitations in OneDrive and SharePoint](https://support.microsoft.com/en-us/onedrive/restrictions-and-limitations-in-onedrive-and-sharepoint)
- [OneDrive file path length limits](https://support.microsoft.com/en-us/onedrive/what-are-file-path-length-limits)

## Working Rules

- Use Git commits on `origin/codex` for version history. OneDrive sync does not
  resolve concurrent Git edits or repository conflicts.
- Work from only one checkout at a time and let OneDrive finish synchronizing
  before switching devices or starting Git operations elsewhere.
- Do not add symbolic links or junctions. OneDrive does not synchronize through
  them.
- Keep pipeline input and output paths shallow. MRI result trees can grow beyond
  desktop path and item-count limits even when this source tree remains small.
- Make required inputs locally available before a pipeline run. Files On-Demand
  is supported, but an online-only input still requires download before local
  scientific tools can read it.
- Keep controlled datasets and generated subject data outside the Git history
  unless the applicable NIH data-handling rules explicitly allow them.

The repository ignores Office lock files beginning with `~$` and `.tmp` files
so those local synchronization artifacts are not committed.
