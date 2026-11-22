# Running on Replit

## Start the app

The Replit workflow starts the existing Streamlit app on the preview port:

```bash
python -m streamlit run app.py --server.address 0.0.0.0 --server.port 5000
```

Use the **Demo tour** or open `/?demo=1` to see the prepared offline walkthrough. It does not require provider credentials or a built library.

## Access modes

The checked-in configuration keeps the app in local mode so the offline demo and local workflow remain available without sign-in. For a hosted pilot, set `[app].mode = "hosted"` and `auth_enabled = true` in `config/app.toml`, configure Streamlit's OIDC `[auth]` settings in the private `.streamlit/secrets.toml`, and add `ADMIN_EMAILS` as a Replit Secret containing comma-separated verified administrator email addresses. Do not commit a populated secrets file.

Hosted learner pages require OIDC sign-in. Admin, source-management, and recovery pages check the verified email allowlist in server-side Python, and library-changing service operations repeat that role check; hiding a navigation item is not the authorization control. The prepared offline demo remains available without sign-in or provider credentials.

## Current limitations

The app remains in local mode by default. Hosted use requires configured OIDC and an administrator allowlist. Do not use real learner or administrator data until the hosted Admin safeguards are complete and the configured App Storage bucket has passed an upload/restore round trip. The local Admin workflow can perform cloud operations when configured, so use it only in a trusted development workspace.

Live search and generated answers require `PINECONE_API_KEY` and `OPENAI_API_KEY` in Replit Secrets, plus an explicitly built library and configured Pinecone index. No provider credentials are configured by this setup. The offline demo is available without them.

## Durable library storage

Local mode keeps the current file-based behavior. For a hosted Replit run, first add the project’s default bucket in **Tools → App Storage** and make sure the managed development database has the schema in `sql/amgen_library_storage.sql` and `sql/amgen_admin_jobs.sql`. Apply the Admin-job migration before enabling hosted builds; publish the reviewed database schema change together with the code.

With the original local files still available, seed storage once:

```bash
AMGEN_STORAGE_BACKEND=app_storage python scripts/manage_library_storage.py seed-local
```

This copies PDFs, generated XML, pinned source snapshots, chunk records, and lexical search artifacts into App Storage; it verifies each upload by reading it back and comparing its checksum. It also copies existing review decisions and interrupted-ingestion batch checkpoints from the local SQLite files into managed SQL without deleting the originals. The seed command refuses to replace an already-initialized remote inventory.

Set `AMGEN_STORAGE_BACKEND=app_storage` in the hosted app’s environment after seeding. Startup restores the saved assets and validates the active library and citation files before search is available. The active pointer, reviews, and ingestion checkpoints use managed SQL. The default local preview does not contact App Storage.

Hosted full-library builds are queued in managed SQL and run independently of the browser. The Admin page can be closed while a build runs; after reopening Admin, refresh the saved job status. A worker restart reclaims jobs with expired heartbeats and resumes from durable ingestion batch checkpoints. Activation happens only after complete verification, so a failed candidate does not replace the previous active library.

The App Storage bucket is not configured in this workspace yet, so the real upload/restore round trip still needs a bucket before it can be verified here.
