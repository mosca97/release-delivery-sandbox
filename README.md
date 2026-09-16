# Release delivery sandbox

Private sandbox for testing the supplier delivery flow described by
`AgicCompany/chiome-release_management`.

The repository will contain:

- stable validation and publication automation under `.github/`;
- the versioned manifest contract under `schema/`;
- one delivery at a time on `main`;
- immutable delivery references under `release/*` tags.

The first scenario will use Git storage for source files and a small draft
GitHub Release asset for a distributable artifact.
