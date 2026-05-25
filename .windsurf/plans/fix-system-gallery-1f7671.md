# Fix System Gallery Page Error

The system gallery page has a JavaScript error: `_.filter is not a function`. The issue is that the `/api/recordings` endpoint returns data with `files` key but the frontend expects `recordings` key. This causes a data mismatch where an object is passed instead of an array, leading to the error.

## Fix
Update `frontend/src/app/(superadmin)/configure/system-gallery/page.tsx` to accept both `files` and `recordings` keys from the API response.
