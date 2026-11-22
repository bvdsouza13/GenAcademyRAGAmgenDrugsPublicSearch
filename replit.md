# Running on Replit

## Start the app

The Replit workflow starts the existing Streamlit app on the preview port:

```bash
python -m streamlit run app.py --server.address 0.0.0.0 --server.port 5000
```

Use the **Demo tour** or open `/?demo=1` to see the prepared offline walkthrough. It does not require provider credentials or a built library.

## Current limitations

This project is configured for local operation. It has no sign-in or server-side role checks, and its library, uploaded files, and mutable state are stored in the project filesystem. Do not publish this workflow as a shared production service or use it for real learner or administrator data. The existing local Admin workflow can perform cloud operations when configured, so only use it in a trusted development workspace.

Live search and generated answers require `PINECONE_API_KEY` and `OPENAI_API_KEY` in Replit Secrets, plus an explicitly built library and configured Pinecone index. No provider credentials are configured by this setup. The offline demo is available without them.

The published deployment plan describes additional work needed before hosted use: protected learner access, durable library storage, verified startup restoration, and a separately secured hosted Admin workflow. Those features are not implemented by this Replit run setup.
