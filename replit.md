# Running on Replit

## Start the app

The Replit workflow starts the existing Streamlit app on the preview port:

```bash
python -m streamlit run app.py --server.address 0.0.0.0 --server.port 5000
```

Use the **Demo tour** or open `/?demo=1` to see the prepared offline walkthrough. It does not require provider credentials or a built library.

## Current limitations

The app remains in local mode by default. Do not publish it as a shared service until protected learner access and server-side Admin authorization are in place. The local Admin workflow can perform cloud operations when configured, so use it only in a trusted development workspace.

Live search and generated answers require `PINECONE_API_KEY` and `OPENAI_API_KEY` in Replit Secrets, plus an explicitly built library and configured Pinecone index. No provider credentials are configured by this setup. The offline demo is available without them.

## Durable library storage

Local mode keeps the current file-based behavior. For a hosted Replit run, first add the project’s default bucket in **Tools → App Storage** and make sure the managed development database has the schema in `sql/amgen_library_storage.sql`. The schema is present in the development database for this Repl; Replit Publish will apply its schema change to production.

With the original local files still available, seed storage once:

```bash
AMGEN_STORAGE_BACKEND=app_storage python scripts/manage_library_storage.py seed-local
```

This copies PDFs, generated XML, pinned source snapshots, chunk records, and lexical search artifacts into App Storage; it verifies each upload by reading it back and comparing its checksum. It also copies existing review decisions and interrupted-ingestion batch checkpoints from the local SQLite files into managed SQL without deleting the originals. The seed command refuses to replace an already-initialized remote inventory.

Set `AMGEN_STORAGE_BACKEND=app_storage` in the hosted app’s environment after seeding. Startup restores the saved assets and validates the active library and citation files before search is available. The active pointer, reviews, and ingestion checkpoints use managed SQL. The default local preview does not contact App Storage.

The App Storage bucket is not configured in this workspace yet, so the real upload/restore round trip still needs a bucket before it can be verified here.
